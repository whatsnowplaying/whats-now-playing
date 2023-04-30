#!/usr/bin/env python3
'''
    Titles for streaming
'''
from nowplaying.version import __VERSION__  # pylint: disable=no-name-in-module,import-error

__version__ = __VERSION__  #pylint: disable=no-member


def main():  #pylint: disable=missing-function-docstring; pragma: no cover
    from .__main__ import main as realmain  #pylint: disable=import-outside-toplevel
    realmain()


if __name__ == "__main__":  # pragma: no cover
    main()
