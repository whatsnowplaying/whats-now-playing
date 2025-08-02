#!/usr/bin/env python3
"""hook for usage in pyinstaller"""

# pylint: disable=invalid-name

from PyInstaller.utils.hooks import collect_submodules  # pylint: disable=import-error

hiddenimports = (
    collect_submodules("nowplaying.artistextras")
    + collect_submodules("nowplaying.denon")
    + collect_submodules("nowplaying.inputs")
    + collect_submodules("nowplaying.kick")
    + collect_submodules("nowplaying.musicbrainz")
    + collect_submodules("nowplaying.notifications")
    + collect_submodules("nowplaying.processes")
    + collect_submodules("nowplaying.recognition")
    + collect_submodules("nowplaying.serato")
    + collect_submodules("nowplaying.settings")
    + collect_submodules("nowplaying.twitch")
    + collect_submodules("nowplaying.upgrades")
    + collect_submodules("nowplaying.utils")
    + collect_submodules("nowplaying.webserver")
)
