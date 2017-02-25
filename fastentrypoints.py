'''
Monkey patch setuptools to write faster console_scripts with this format:

    from mymodule import entry_function
    entry_function()

This is better.
'''
from setuptools.command import easy_install
TEMPLATE = '''\
# -*- coding: utf-8 -*-
import re
import sys

from {0} import {1}

if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\.pyw?|\.exe)?$', '', sys.argv[0])
    sys.exit({1}()) '''


@classmethod
def get_args(cls, dist, header=None):
    """
    Yield write_script() argument tuples for a distribution's
    console_scripts and gui_scripts entry points.
    """
    if header is None:
        header = cls.get_header()
    spec = str(dist.as_requirement())
    for type_ in 'console', 'gui':
        group = type_ + '_scripts'
        for name, ep in dist.get_entry_map(group).items():
            cls._ensure_safe_name(name)
            script_text = TEMPLATE.format(
                          ep.module_name, ep.attrs[0])
            args = cls._get_script_args(type_, name, header, script_text)
            for res in args:
                yield res


easy_install.ScriptWriter.get_args = get_args


def main():
    import shutil
    import sys
    dests = sys.argv[1:] or ['.']
    print(__name__)
    for dst in dests:
        shutil.copy(__file__, dst)
        with open(dst + '/MANIFEST.in', 'a') as manifest:
            manifest.write('\ninclude fastentrypoints.py')
