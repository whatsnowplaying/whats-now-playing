#!/usr/bin/env python3

''' bootstrap for pyinstaller-based runs
    It is setup this way so that multiprocessing
    does not go ballistic.

'''

import multiprocessing

multiprocessing.freeze_support()

if __name__ == "__main__":
    import nowplaying
    nowplaying.main()
