#!/usr/bin/env python3
"""bootstrap for pyinstaller-based runs
It is setup this way so that multiprocessing
does not go ballistic.

"""

import multiprocessing
import os
import sys

import truststore

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")  # pylint: disable=unspecified-encoding, consider-using-with
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")  # pylint: disable=unspecified-encoding, consider-using-with

multiprocessing.freeze_support()

truststore.inject_into_ssl()

# Ensure the current directory is in sys.path
if __name__ == "__main__":
    from nowplaying.__main__ import main as realmain

    if "--smoke-test" in sys.argv:
        sys.exit(0)
    realmain()
sys.stdout.close()
sys.stderr.close()
