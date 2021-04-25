#!/usr/bin/env python3

import multiprocessing

multiprocessing.freeze_support()

if __name__ == "__main__":
    import nowplaying
    nowplaying.main()
