#!/usr/bin/env python3
"""bootstrap for pyinstaller-based runs
It is setup this way so that multiprocessing
does not go ballistic.

"""

import multiprocessing
import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")  # pylint: disable=unspecified-encoding, consider-using-with
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")  # pylint: disable=unspecified-encoding, consider-using-with

multiprocessing.freeze_support()

# Ensure the current directory is in sys.path
if __name__ == "__main__":
    from nowplaying.__main__ import main as realmain

    realmain()
sys.stdout.close()
sys.stderr.close()
