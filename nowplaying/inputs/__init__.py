#!/usr/bin/env python3
"""Input Plugin definition"""

# import logging
from typing import TYPE_CHECKING

# from nowplaying.exceptions import PluginVerifyError
from nowplaying.plugin import WNPBasePlugin
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    import nowplaying.config


class InputPlugin(WNPBasePlugin):
    """base class of input plugins"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.plugintype: str = "input"

    #### Additional UI method

    def desc_settingsui(self, qwidget: "QWidget") -> None:  # pylint: disable=no-self-use
        """description of this input"""
        qwidget.setText("No description available.")

    #### Autoinstallation methods ####

    def install(self) -> bool:  # pylint: disable=no-self-use
        """if a fresh install, run this"""
        return False

    #### Mix Mode menu item methods

    def validmixmodes(self) -> list[str]:  # pylint: disable=no-self-use
        """tell ui valid mixmodes"""
        # return ['newest', 'oldest']
        return ["newest"]

    def setmixmode(self, mixmode: str) -> str:  # pylint: disable=no-self-use, unused-argument
        """handle user switching the mix mode: TBD"""
        return "newest"

    def getmixmode(self) -> str:  # pylint: disable=no-self-use
        """return what the current mixmode is set to"""

        # mixmode may only be allowed to be in one state
        # depending upon other configuration that may be in
        # play

        return "newest"

    #### Data feed methods

    async def getplayingtrack(self) -> TrackMetadata | None:
        """Get the currently playing track"""
        raise NotImplementedError

    async def getrandomtrack(self, playlist: str) -> str | None:  # pylint: disable=no-self-use, unused-argument
        """Get a file associated with a playlist, crate, whatever"""
        return None

    async def has_tracks_by_artist(self, artist_name: str) -> bool:  # pylint: disable=no-self-use, unused-argument
        """Check if DJ has any tracks by the specified artist"""
        # Default implementation - can be overridden by plugins with database access
        return False

    #### Control methods

    async def start(self) -> None:
        """any initialization before actual polling starts"""

    async def stop(self) -> None:
        """stopping either the entire program or just this
        input"""
