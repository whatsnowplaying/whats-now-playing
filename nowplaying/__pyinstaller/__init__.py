#!/usr/bin/env python3
''' help for pyinstaller '''

import os

def get_hook_dirs():
    ''' point to where all the pyinstaller hooks are at '''
    return [os.path.dirname(__file__)]
