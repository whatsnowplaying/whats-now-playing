#!/usr/bin/env python3
"""Beam input plugin"""

import logging
import pathlib
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget  # pylint: disable=import-error, no-name-in-module
from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata
import nowplaying.db

if TYPE_CHECKING:
    import nowplaying.config
    from PySide6.QtCore import QSettings


class Plugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
    """handler for NowPlaying"""

    def __init__(
        self, config: "nowplaying.config.ConfigFile | None" = None, qsettings: QWidget | None = None
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Remote"
        # Set default path
        default_path = (
            pathlib.Path(QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0])
            .joinpath("remotedb")
            .joinpath("remote.db")
        )

        # Use configured path if available, otherwise use default
        if self.config and self.config.cparser.value("remote/remotedb"):
            self.remotedbfile = pathlib.Path(self.config.cparser.value("remote/remotedb"))
        else:
            self.remotedbfile = default_path

        self.remotedb: nowplaying.db.MetadataDB | None = None
        self.mixmode = "newest"
        self.event_handler = None
        self.metadata: TrackMetadata = {"artist": None, "title": None, "filename": None}
        self.observer = None
        self._reset_meta()

    def install(self):
        """remote install"""
        return False

    def _reset_meta(self):
        """reset the metadata"""
        self.metadata = {"artist": None, "title": None, "filename": None}

    async def setup_watcher(self):
        """set up a custom watch on the m3u dir so meta info
        can update on change"""

        if self.observer:
            return

        self.remotedbfile.unlink(missing_ok=True)
        logging.info("Opening %s for input", self.remotedbfile)
        self.observer = nowplaying.db.DBWatcher(databasefile=str(self.remotedbfile))
        self.observer.start(customhandler=self._read_track)

    def _read_track(self, event):
        if event.is_directory:
            return

        if not self.remotedb:
            logging.error("remotedb isn't opened yet.")
            return

        newmeta = self.remotedb.read_last_meta()
        if not newmeta:
            self._reset_meta()
            return

        self.metadata = newmeta

    async def start(self):
        """setup the watcher to run in a separate thread"""
        await self.setup_watcher()
        self.remotedb = nowplaying.db.MetadataDB(databasefile=str(self.remotedbfile))

    async def getplayingtrack(self):
        """wrapper to call getplayingtrack"""
        return self.metadata

    async def getrandomtrack(self, playlist):
        """not supported"""
        return None

    async def stop(self):
        """stop the remote plugin"""
        self._reset_meta()
        if self.observer:
            self.observer.stop()

    def on_m3u_dir_button(self):
        """filename button clicked action"""

    def connect_settingsui(self, qwidget: "QWidget", uihelp):
        """connect m3u button to filename picker"""
        self.qwidget = qwidget
        self.uihelp = uihelp

    def load_settingsui(self, qwidget: "QWidget"):
        """draw the plugin's settings page"""

    def verify_settingsui(self, qwidget: "QWidget"):
        """no verification to do"""

    def save_settingsui(self, qwidget: "QWidget"):
        """take the settings page and save it"""

    def desc_settingsui(self, qwidget: "QWidget"):
        """description"""
        qwidget.setText("Remote gets input from one or more other WNP setups.")
