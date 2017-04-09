#!/usr/bin/env python3
"""
Avoid writing loops in shell one-liners.

When reading from stdin (the default), wrld abbreviates simple
`while read line; do` style loops. You could also think of it as
`xargs -I{}` or the `-exec` flag from `find` on steroids, because it
iterates on stdin, but it also allows inlining arbitrary shell commands.

    $ ls|wrld mv {} '@awk "{print $2, $1}"'
    mv 'Arnold Palmer' 'Palmer Arnold'
    mv 'Jane Doe' 'Doe Jane'
    mv 'John Doe' 'Doe John'
    mv 'John Wayne' 'Wayne John'
    mv 'Lucy Lawless' 'Lawless Lucy'
    mv 'Ricky Lake' 'Lake Ricky'

As you can see, inlined commands have the current line piped to their
stdin. If you want to use some idiotic command that doesn't read from
stdin as the filter, you can also substitute '{}' for the current line.
Use \\{} if you need a literal '{}'. However, if you can't do it with
sed or awk, there's always `perl -pe`, and if you can't do it with perl
-pe, I don't want to know about it. You can also see that wrld echos
back the commands it constructs. You can shut it up with -q/--no-echo.

If you are iterating on file names as above, you should be aware that
POSIX stupidly allows newlines in file names, so this is actually a
"dangerous" example unless can guarantee there are no idiot newlines in
the file names. For this reason, you may instead specify a list of file
names to iterate over (like, preferably with a glob) with the
-f/--file-list flag:

    $ wrld mv {} '@awk "{print $2, $1}"' -f *
    mv 'Doe Jane' 'Jane Doe'
    mv 'Doe John' 'John Doe'
    mv 'Lake Ricky' 'Ricky Lake'
    mv 'Lawless Lucy' 'Lucy Lawless'
    mv 'Palmer Arnold' 'Arnold Palmer'
    mv 'Wayne John' 'John Wayne'

If you're using a proper shell like fish or zsh, you can do recursive
globbing and get quite a lot done this way. One day, in the far distant
future, wrld may support splitting stdin on the null byte for
compatibility with `find -print0`. It is a little know fact that any
task which a computer is capable of preforming may be prefomed with the
`find` command, so compatibility is key.

As you may note, wrld is capable of spawning a lot of processes. If it's
some quick thing, who cares? If your iterating over a million files, it
might be bad. wrld offers some internal goodies to speed things along,
but they are written in python, so don't expect any miracles! (kind of
kidding. A few lines of python is way faster than spawning a new
process, but it would be much slower than piping a million lines strait
through `sed` or whatever).

These builtins are for certain common file operations: they have names
like "move", "copy", "hlink" and "slink". I'll leave it to your
imagination to figure out what they do. There are also builtin filters
for sed-like substitution on the current line/filename, and using python
expressions as filters. for example:

    $ wrld move {} '@py i.upper()' -f *
    move 'Arnold Palmer' 'ARNOLD PALMER'
    move 'Jane Doe' 'JANE DOE'
    move 'John Doe' 'JOHN DOE'
    move 'John Wayne' 'JOHN WAYNE'
    move 'Lucy Lawless' 'LUCY LAWLESS'
    move 'Ricky Lake' 'RICKY LAKE'

or:

    wrld move {} 's/[aeiou]/λ/g' -f *
    move 'Arnold Palmer' 'Arnλld Pλlmλr'
    move 'Jane Doe' 'Jλnλ Dλλ'
    move 'John Doe' 'Jλhn Dλλ'
    move 'John Wayne' 'Jλhn Wλynλ'
    move 'Lucy Lawless' 'Lλcy Lλwlλss'
    move 'Ricky Lake' 'Rλcky Lλkλ'

For more information on these builtins, please view the README, which
can be found at https://github.com/ninjaaron/wrld.
"""
import sys
import os
import re
import shlex
import shutil
import inspect
import collections
import argparse
import subprocess as sp
import pathlib
from functools import wraps

BRACES = '\U000c41bb'
BS = '\U000c41bd'
DELIM = '\U000c41be'
BUILTINS = {}


class GenerousNamespace(dict):
    """namespace that imports modules lazily."""
    def __missing__(self, name):
        return __import__(name)


namespace = GenerousNamespace(__builtins__)


def pysub(arg, line, num):
    """substitutes the return value of a python statement for an arg"""
    namespace.update(l=line)
    value = eval(arg, namespace)
    # return multiple args if the return value is a list, tuple or iterator
    if isinstance(value, (list, tuple, collections.Iterator)):
        return value
    return [str(value)]


def cmdsub(arg, line, num):
    """substitutes the return value of an external command for an arg"""
    cmd = shlex.split(arg)
    return [sp.run(cmd, input=line, stdout=sp.PIPE,
                   universal_newlines=True).stdout.rstrip()]


def subsub(arg, line, num):
    """preforms regex substitution on current line of stdin for an arg"""
    pat, rep, count = arg
    if inspect.iscode(rep):
        return [re.sub(pat, lambda m: eval(rep, GenerousNamespace(m=m)),
                       line)]
    return [re.sub(pat, rep, line, count=count)]


def pipesub(arg, line, num):
    """return the results of the already-completed (in preprocess_args()) pipe
    thing that match the current line.
    """
    return [arg[num]]

FUNCS = {'py': pysub, 'cmd': cmdsub, 'sub': subsub, 'pipe': pipesub}

def preprocess_args(args, stdin):
    """add do preprocessing on different types of command line arguments before
    entering the the main loop. compile the code for @py args, convert
    substitution args from a sed-like format to re.sub arguments, run all input
    through the filters with | arguments, and simply mark off the @ arguments.
    It also removes the backslash from escaped arguments
    """
    code_subbed_args = []
    # sub_indicies is a dictionary marking off the index for args where special
    # action needs to be taken, we refer back to it in the main loop.
    sub_indicies = {}
    for index, arg in enumerate(args):

        # handle @py args
        if arg.startswith('@py '):
            code_subbed_args.append(compile(arg[4:].lstrip(),
                                            '<string>', 'eval'))
            sub_indicies[index] = 'py'

        # handle substitution, 's' args
        elif arg.startswith('s') and not arg[1].isalnum():
            dlmtr = arg[1]
            sub = arg.replace(r'\\', BS).replace(
                '\\'+dlmtr, DELIM).split(dlmtr)[1:]

            pat, rep, flags = (i.replace(BS, r'\\').replace(DELIM, dlmtr)
                               for i in sub)

            if rep.startswith(r'\e'):
                rep = compile(rep[2:].lstrip(), '<string>', 'eval')

            count = 0 if 'g' in flags else 1
            flags = flags.replace('g', '')
            if flags:
                pat = '(?%s)%s' % (flags, pat)

            code_subbed_args.append((pat, rep, count))
            sub_indicies[index] = 'sub'

        # handle pipe filter args
        elif arg[0] == '|':
            filtered = sp.run(
                        shlex.split(arg[1:]),
                        input=stdin,
                        check=True,
                        universal_newlines=True,
                        stdout=sp.PIPE).stdout.splitlines()

            code_subbed_args.append(filtered)
            sub_indicies[index] = 'pipe'

        # handle @ filter args
        elif arg[0] == '@':
            code_subbed_args.append(arg[1:])
            sub_indicies[index] = 'cmd'

        # remove backslash from escaped args and flags
        else:
            if arg[0] == '\\':
                arg = arg[1:]
            code_subbed_args.append(arg)

    return sub_indicies, code_subbed_args


def insert_line(line, args):
    args_with_line = []
    for arg in args:
        if isinstance(arg, str):
            arg = arg.replace('{}', line)
            arg = arg.replace(BRACES, '{}')
        args_with_line.append(arg)
    return args_with_line


def print_err(message):
    """print error messages to stderr with color and style!"""
    print('\x1b[31mError\x1b[0m:', message, file=sys.stderr)


def check_args(cmd, args):
    """make sure builtins have the required number of arguments supplied"""
    num = BUILTINS[cmd][1]
    if isinstance(num, int):
        num = [num]
    else:
        num = list(range(num[0], num[1]+1))
    if len(args) - 1 not in num:
        word = 'argument' if num == [1] else 'arguments'
        num = str(num[0]) if len(num) == 1 else '%d-%d' % (num[0], num[-1])
        print_err('%s builtin takes %s %s' % (cmd, num, word))
        sys.exit(1)


def builtin(num, add_line=None, resolve_dest=False):
    """decorator factory for builtin commands. num is the number of arguments
    the builtin expects. It may be a tuple containting the minimum and maximum
    number of arguments.

    If resolve_dest is True and the final argument is a directory name, the
    basename of the initial argument is appended to the destination. e.g. in
    `copy ~/Downloads/a_photo.jpg ~/Pictures`, the last argument becomes
    ~/Pictures/a_photo.jpg, much like it does with most command line utilities
    (and like it does not with many python fs utilities)

    add_line, if given, should be an integer. If the given number of arguments
    equals that number, the line or filename being processed will be given as
    the initial argument.
    """
    def nummer(func):
        @wraps(func)
        def resolved(args, line):
            if len(args) == add_line:
                args.insert(0, line)
            if resolve_dest and os.path.isdir(args[-1]):
                p = pathlib.Path(args[-1], os.path.basename(args[0]))
                args[-1] = str(p)
            return func(args)
        BUILTINS.update({func.__name__: (resolved, num, add_line)})
        return resolved
    return nummer


@builtin((1, 2), add_line=1)
def move(args):
    """move stuff (recursively)"""
    shutil.move(*args)


@builtin((1, 2), add_line=1)
def copy(args):
    """copy stuff (recursively)"""
    try:
        shutil.copy(*args)
    except IsADirectoryError:
        shutil.copytree(*args)


@builtin((1, 2), add_line=1, resolve_dest=True)
def slink(args):
    """make symlinks"""
    os.symlink(args[0], args[1])


@builtin((1, 2), add_line=1, resolve_dest=True)
def srlink(args):
    """make symlinks where a relative path is expanded to an absolute path"""
    os.symlink(os.path.abspath(args[0]), args[1])


@builtin((1, 2), add_line=1, resolve_dest=True)
def hlink(args):
    """make hardlinks"""
    os.link(*args)


@builtin((0, 1), add_line=0)
def remove(args):
    """remove stuff (recursively). Take care!"""
    try:
        os.remove(args[0])
    except IsADirectoryError:
        shutil.rmtree(args[0])


@builtin(1)
def makedir(args):
    """make directories. like mkdir -p"""
    os.makedirs(args[0], exist_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('args', nargs='+',
                    help='arguments to be expanded (or not) at runtime')

    ap.add_argument('-f', '--file-list',  nargs='+',
                    help='iterate on specified file list (or glob instead '
                         'instead of stdin. Should come AFTER args.')

    ap.add_argument('-q', '--no-echo', action='store_true',
                    help='suppress command echo')

    ap.add_argument('-t', '--test', action='store_true',
                    help='test-run that only prints resulting commands')

    ap.add_argument('-v', '--previewer', help='previewer command')

    ap.add_argument('-p', '--prompt', action='store_true',
                    help='prompt for each command')

    ap.add_argument('-s', '--command-string', action='store_true',
                    help='format args from a single string')

    a = ap.parse_args()

    if a.command_string:
        args = shlex.split(a.args[0])
    args = [arg.replace('\{}', BRACES) for arg in a.args]

    if args[0] in BUILTINS:
        check_args(args[0], args)
    if a.file_list:
        stdin = '\n'.join(a.file_list)
        items = a.file_list
    else:
        if [arg for arg in args if arg.startswith('|')]:
            stdin = sys.stdin.read()
            items = stdin.splitlines()
        else:
            stdin = None
            items = (i.rstrip('\n') for i in sys.stdin)

    sub_indicies, compiled_args = preprocess_args(args, stdin)

    for i, line in enumerate(items):
        namespace.update(i=line)

        # convert all args to strings # # # # # # # # # # # #
        #                                                   #
        # This should be a function, but I can't be         #
        # bothered to pass in all the parameters. I can,    #
        # however, be bothered to draw this box.            #
        # # # # # # # # # # # # # # # # # # # # # # # # # # #
        args_with_line = insert_line(line, compiled_args)   #
        cmd_subbed_args = []                                #
        for index, arg in enumerate(args_with_line):        #
            if index in sub_indicies:                       #
                cmd_subbed_args.extend(                     #
                    FUNCS[sub_indicies[index]](             #
                        arg, line, i))                      #
            else:                                           #
                cmd_subbed_args.append(arg)                 #
        # # # # # # # # # # # # # # # # # # # # # # # # # # #

        # do stuff with other flags
        if a.previewer:
            sp.run(shlex.split(a.previewer) + [line])

        if not a.no_echo:
            print(' '.join(map(shlex.quote, cmd_subbed_args)), file=sys.stderr)

        if a.prompt and input('[y/N]? ').lower() != 'y':
            continue

        if a.test:
            continue

        cmd, args = cmd_subbed_args[0], cmd_subbed_args[1:]
        try:
            BUILTINS[cmd][0](args, line)
        except KeyError:
            if cmd[1:] in BUILTINS and cmd[0] == '\\':
                cmd = cmd[1:]
            sp.run([cmd]+args)
        except Exception as e:
            print_err(e)
