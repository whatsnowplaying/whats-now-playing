#!/usr/bin/env python3
''' hook for usage in pyinstaller '''

#pylint: disable=invalid-name

from PyInstaller.utils.hooks import collect_submodules  # pylint: disable=import-error

hiddenimports = collect_submodules('nowplaying.artistextras') + \
    collect_submodules('nowplaying.inputs') + \
    collect_submodules('nowplaying.processes') + \
    collect_submodules('nowplaying.recognition') + \
    collect_submodules('nowplaying.twitch')
