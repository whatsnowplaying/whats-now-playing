#!/usr/bin/env python3
''' hook for usage in pyinstaller '''

#pylint: disable=invalid-name

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('nowplaying.inputs') + collect_submodules(
    'nowplaying.recognition')
