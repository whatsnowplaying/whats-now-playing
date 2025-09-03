#!/usr/bin/env python3
"""Notification Plugin definition"""

from typing import TYPE_CHECKING

from nowplaying.plugin import WNPBasePlugin
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.imagecache


class NotificationPlugin(WNPBasePlugin):
    """base class for notification plugins"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.plugintype: str = "notification"

    #### Core notification methods ####

    async def notify_track_change(
        self, metadata: TrackMetadata, imagecache: "nowplaying.imagecache.ImageCache|None" = None
    ) -> None:
        """
        Called when a new track becomes live

        Args:
            metadata: Track metadata including artist, title, etc.
            imagecache: Optional imagecache instance for accessing cached images
        """
        raise NotImplementedError

    #### Plugin lifecycle methods ####

    async def start(self) -> None:
        """Initialize the notification plugin"""

    async def stop(self) -> None:
        """Clean up the notification plugin"""

    #### Configuration UI methods ####

    def desc_settingsui(self, qwidget: "QWidget") -> None:  # pylint: disable=no-self-use
        """description of this notification plugin"""
        qwidget.setText("No description available.")
