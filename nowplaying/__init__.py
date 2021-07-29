#!/usr/bin/env python3
'''
    Titles for streaming for Serato
'''

#from . import version
#__version__ = version.get_versions()['version']

import nowplaying.version

__version__ = nowplaying.version.get_versions()['version']


def main():  #pylint: disable=missing-function-docstring
    from .__main__ import main as realmain  #pylint: disable=import-outside-toplevel
    realmain()


if __name__ == "__main__":
    main()
