#!/usr/bin/env python3
'''
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
'''
import sys, os, re
import shlex, shutil, inspect
import collections
import argparse
import subprocess as sp
import pathlib

BRACES =  '\U000c41bb'
BS = '\U000c41bd'
DELIM = '\U000c41be'
BUILTINS = {}

class GenerousNamespace(dict):
    '''namespace that imports modules lazily.'''
    def __missing__(self, name):
        return __import__(name)


namespace = GenerousNamespace(__builtins__)


def pysub(arg, line, num):
    'substitutes the return value of a python statement for an arg'
    namespace.update(l=line)
    value = eval(arg, namespace)
    # return multiple args if the return value is a list, tuple or iterator
    if isinstance(value, (list, tuple, collections.Iterator)):
        return value
    return [str(value)]


def cmdsub(arg, line, num):
    '''substitutes the return value of an external command for an arg'''
    cmd = shlex.split(arg)
    return [sp.run(cmd, input=line, stdout=sp.PIPE,
                  universal_newlines=True).stdout.rstrip()]


def subsub(arg, line, num):
    pat, rep = arg
    if inspect.iscode(rep):
        return [re.sub(pat, lambda m: eval(rep, GenerousNamespace(m=m)),
                      line)]
    return [re.sub(pat, rep, line)]


def pipesub(arg, line, num):
    return [arg[num]]


def code_sub(args, stdin):
    code_subbed_args = []
    sub_indicies = {}
    for index, arg in enumerate(args):

        if arg.startswith('@py '):
            code_subbed_args.append(compile(arg[4:].lstrip(),
                                            '<string>', 'eval'))
            sub_indicies[index] = 'py'

        elif arg.startswith('s') and not arg[1].isalnum():
            dlmtr = arg[1]
            sub = arg.replace(r'\\', BS
                    ).replace('\\'+dlmtr, DELIM
                    ).split(dlmtr)[1:]

            pat, rep, flags = (i.replace(BS, r'\\').replace(DELIM, dlmtr)
                               for i in sub)

            if rep.startswith(r'\e'):
                rep = compile(rep[2:].lstrip(), '<string>', 'eval')

            count = 0 if 'g' in flags else 1
            flags = flags.replace('g', '')
            if flags:
                pat = '(?%s)' % flags

            code_subbed_args.append((pat, rep))
            sub_indicies[index] = 'sub'

        elif arg[0] == '|':
            filtered = sp.run(
                        shlex.split(arg[1:]),
                        input=stdin,
                        check=True,
                        universal_newlines=True,
                        stdout=sp.PIPE).stdout.splitlines()

            code_subbed_args.append(filtered)
            sub_indicies[index] = 'pipe'

        elif arg[0] == '@':
            code_subbed_args.append(arg[1:])
            sub_indicies[index] = 'cmd'

        else:
            if arg[0] == '\\':
                arg = arg[1:]
            code_subbed_args.append(arg)

    return sub_indicies, code_subbed_args


def print_err(message):
    print('\x1b[31mError\x1b[0m:', message, file=sys.stderr)


def check_args(cmd, num, args):
    if len(args) - 1 != num:
        word = 'argument' if num == 1 else 'arguments'
        print_err('%s builtin takes exactly %d %s' % (cmd, num, word))
        sys.exit(1)


def builtin(num, resolve_dest=False):
    def nummer(func):
        cmd = func.__name__

        def resolved(args):
            if resolve_dest:
                if os.path.isdir(args[-1]):
                    p = pathlib.Path(args[-1], os.path.basename(args[0]))
                    args[-1] = str(p)
            return func(args)

        BUILTINS.update({func.__name__: (resolved, num)})

        return resolved
    return nummer


@builtin(2)
def move(args):
    shutil.move(*args)


@builtin(2)
def copy(args):
    try:
        shutil.copy(*args)
    except IsADirectoryError:
        shutil.copytree(*args)


@builtin(2, resolve_dest=True)
def slink(args):
    os.symlink(args[0], args[1])


@builtin(2, resolve_dest=True)
def srlink(args):
    os.symlink(os.path.abspath(args[0]), args[1])


@builtin(2, resolve_dest=True)
def hlink(args):
    try:
        os.link(*args)
    except IsADirectoryError as e:
        print_err(e)

@builtin(1)
def remove(args):
    '''remove stuff recursively'''
    for path, dirs, files in os.walk(args[0], topdown=False):

        for f in files:
            remover(os.remove, path, f)

        for d in dirs:
            remover(os.rmdir, path, d)
    try:
        remover(os.rmdir, args[0])
    except NotADirectoryError:
        remover(os.remove, args[0])


def remover(func, path, file=None):
        p = pathlib.Path(path, file) if file else path
        try:
            func(str(p))
        except PermissionError as e:
            print_err(e)


@builtin(1)
def makedir(args):
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

    a = ap.parse_args()

    args = [arg.replace('\{}', BRACES) for arg in a.args]
    if args[0] in BUILTINS:
        check_args(args[0], BUILTINS[args[0]][1], args)
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

    sub_indicies, code_subbed_args = code_sub(args, stdin)

    for num, line in enumerate(items):
        namespace.update(i=line)

        fixd_args = []
        for arg in code_subbed_args:
            if isinstance(arg, str):
                arg = arg.replace('{}', line)
                arg = arg.replace(BRACES, '{}')
            fixd_args.append(arg)

        cmd_subbed_args = []
        for index, arg in enumerate(fixd_args):
            if index in sub_indicies:
                cmd_subbed_args.extend({
                        'py': pysub,
                        'cmd': cmdsub,
                        'sub': subsub,
                        'pipe': pipesub
                        }[sub_indicies[index]](arg, line, num))
            else:
                cmd_subbed_args.append(arg)
        if not a.no_echo:
            print(' '.join(map(shlex.quote, cmd_subbed_args)), file=sys.stderr)

        cmd, args = cmd_subbed_args[0], cmd_subbed_args[1:]
        try:
            BUILTINS[cmd][0](args)
        except FileExistsError as e:
            print_err(e)
        except KeyError:
            if cmd[1:] in BUILTINS and cmd[0] == '\\':
                cmd = cmd[1:]
            sp.run([cmd]+args)
