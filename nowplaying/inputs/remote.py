#!/usr/bin/env python3
''' Beam input plugin '''

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


class Plugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
    ''' handler for NowPlaying '''

    def __init__(self,
                 config: 'nowplaying.config.ConfigFile | None' = None,
                 qsettings: QWidget | None = None):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Remote"
        self.remotedbfile: str = config.cparser.value('remote/remotedb', type=str)
        self.remotedb: nowplaying.db.MetadataDB | None = None
        self.mixmode = "newest"
        self.event_handler = None
        self.metadata: TrackMetadata = {'artist': None, 'title': None, 'filename': None}
        self.observer = None
        self._reset_meta()

    def install(self):
        ''' remote install '''
        return False

    def _reset_meta(self):
        ''' reset the metadata '''
        self.metadata = {'artist': None, 'title': None, 'filename': None}

    def defaults(self, qsettings: QWidget) -> None:
        dbfile: pathlib.Path = pathlib.Path(
                QStandardPaths.standardLocations(
                    QStandardPaths.CacheLocation)[0]).joinpath('remotedb').joinpath("remote.db")
        self.config.cparser.setValue('remote/remotedb', str(dbfile))

    async def setup_watcher(self):
        ''' set up a custom watch on the m3u dir so meta info
            can update on change'''

        if self.observer:
            return

        logging.info("Opening %s for input", self.remotedbfile)
        self.observer = nowplaying.db.DBWatcher(databasefile=self.remotedbfile)
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
        ''' setup the watcher to run in a separate thread '''
        await self.setup_watcher()
        self.remotedb = nowplaying.db.MetadataDB(databasefile=self.remotedbfile)

    async def getplayingtrack(self):
        ''' wrapper to call getplayingtrack '''
        return self.metadata

    async def getrandomtrack(self, playlist):
        ''' not supported '''
        return None

    async def stop(self):
        ''' stop the remote plugin '''
        self._reset_meta()
        if self.observer:
            self.observer.stop()

    def on_m3u_dir_button(self):
        ''' filename button clicked action'''

    def connect_settingsui(self, qwidget, uihelp):
        ''' connect m3u button to filename picker'''
        self.qwidget = qwidget
        self.uihelp = uihelp

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''

    def verify_settingsui(self, qwidget):
        ''' no verification to do '''

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''

    def desc_settingsui(self, qwidget):
        ''' description '''
        qwidget.setText('Remote gets input from one or more other WNP setups.')
