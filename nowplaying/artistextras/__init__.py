#!/usr/bin/env python3
"""Input Plugin definition"""

import contextlib

# import logging
import sys
from typing import TYPE_CHECKING

from nowplaying.plugin import WNPBasePlugin
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    import nowplaying.config
    from PySide6.QtWidgets import QWidget


class ArtistExtrasPlugin(WNPBasePlugin):
    """base class of plugins"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.plugintype: str = "artistextras"

    #### Plug-in methods

    async def download_async(  #  pylint: disable=no-self-use,unused-argument
        self, metadata: TrackMetadata | None = None, imagecache: object | None = None
    ) -> TrackMetadata | None:
        """return metadata (async version) - override this in async plugins"""
        return None

    def providerinfo(self) -> list[str] | None:  # pylint: disable=no-self-use, unused-argument
        """return list of what is provided by this recognition system"""
        return None

    #### Utilities

    def calculate_delay(self) -> float:
        """determine a reasonable, minimal delay"""

        delay: float = 10.0

        with contextlib.suppress(ValueError):
            delay = self.config.cparser.value("settings/delay", type=float, defaultValue=10.0)

        if sys.platform == "win32":
            delay = max(delay / 2, 10)
        else:
            delay = max(delay / 2, 5)

        return delay
