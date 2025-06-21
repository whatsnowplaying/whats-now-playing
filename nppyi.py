#!/usr/bin/env python3
''' bootstrap for pyinstaller-based runs
    It is setup this way so that multiprocessing
    does not go ballistic.

'''

import multiprocessing
import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

multiprocessing.freeze_support()

if __name__ == "__main__":
    from nowplaying.__main__ import main as realmain
    realmain()
