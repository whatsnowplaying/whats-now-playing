#!/usr/bin/env python3
"""Input Plugin definition"""

import sys
from typing import TYPE_CHECKING

# from nowplaying.exceptions import PluginVerifyError
from nowplaying.plugin import WNPBasePlugin
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    import nowplaying.config


class RecognitionPlugin(WNPBasePlugin):
    """base class of recognition plugins"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.plugintype: str = "recognition"

    #### Recognition methods

    async def recognize(  # pylint: disable=no-self-use
        self, metadata: TrackMetadata | None = None
    ) -> TrackMetadata | None:
        """return metadata"""
        raise NotImplementedError

    def providerinfo(self) -> dict[str, object]:
        """return list of what is provided by this recognition system"""
        raise NotImplementedError

    #### Utilities

    def calculate_delay(self) -> float:
        """determine a reasonable, minimal delay"""

        try:
            delay: float = self.config.cparser.value(
                "settings/delay", type=float, defaultValue=10.0
            )
        except ValueError:
            delay = 10.0

        if sys.platform == "win32":
            return max(delay / 2, 10)
        return max(delay / 2, 5)
