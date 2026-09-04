#!/usr/bin/env python3
"""Beam input plugin"""

import logging
import os
import pathlib
from typing import TYPE_CHECKING

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=import-error, no-name-in-module
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

import nowplaying.db
from nowplaying.inputs import Detected, InputPlugin
from nowplaying.types import TrackMetadata
import nowplaying.wizard

if TYPE_CHECKING:
    import nowplaying.config


class _RemoteWizardPage(nowplaying.wizard.WizardPage):  # pylint: disable=too-few-public-methods
    """Wizard page for the Remote (multi-PC) input plugin."""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.setTitle("Receiving From Another Machine")
        self.setSubTitle(
            "Tracks arrive here from somewhere else, so there is nothing on this "
            "machine to point at."
        )

        info = QLabel(
            "From a DJ machine: run this setup over there too and choose the DJ "
            "machine role. It will find this machine on its own.\n\n"
            "From EarShot: nothing more to do. It starts sending as soon as it "
            "runs."
        )
        info.setWordWrap(True)

        self._secret_edit = QLineEdit()
        self._secret_edit.setPlaceholderText("leave blank for no authentication")
        self._secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._secret_edit.setText(str(config.cparser.value("remote/remote_key", defaultValue="")))

        form = QFormLayout()
        form.addRow("Shared secret (optional):", self._secret_edit)

        layout = QVBoxLayout()
        layout.addWidget(info)
        layout.addSpacing(12)
        layout.addLayout(form)
        layout.addStretch()
        self.setLayout(layout)

    def collected(self) -> dict[str, object]:
        """The shared secret, blank when the user wants no authentication."""
        return {"remote/remote_key": self._secret_edit.text().strip()}


class Plugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
    """handler for NowPlaying"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: QWidget | None = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Remote"
        self.wizardpage = _RemoteWizardPage
        if os.environ.get("WNP_REMOTEDB_TEST_FILE"):
            self.remotedbfile = pathlib.Path(os.environ["WNP_REMOTEDB_TEST_FILE"])
        else:
            self.remotedbfile = pathlib.Path(
                QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]
            ).joinpath("remotedb", "remote.db")

        self.remotedb: nowplaying.db.MetadataDB | None = None
        self.mixmode = "newest"
        self.event_handler = None
        self.metadata: TrackMetadata = {"artist": None, "title": None, "filename": None}
        self.observer = None
        self._reset_meta()

    def detect(self) -> Detected:
        """Never detected: tracks arrive from another machine, not from software here."""
        return Detected()

    def get_source_agent_data(self) -> dict:
        """Remote input preserves source_agent data set by the sender."""
        return {}

    def _reset_meta(self):
        """reset the metadata"""
        self.metadata = {"artist": None, "title": None, "filename": None}

    async def setup_watcher(self):
        """set up a custom watch on the m3u dir so meta info
        can update on change"""

        if self.observer:
            return

        logging.info("Opening %s for input", self.remotedbfile)
        self.observer = nowplaying.db.DBWatcher(databasefile=str(self.remotedbfile))
        self.observer.start(customhandler=self._read_track)

    def _read_track(self, event):
        if event.is_directory:
            return

        logging.debug("remote db event: %s", event.src_path)
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
        # Discard the last session's tracks, open the database, then watch. The
        # unlink used to live in setup_watcher(), which put it after the watcher
        # was already running: its own delete and recreate were the first events
        # delivered, and they arrived before there was a database to read.
        self.remotedbfile.unlink(missing_ok=True)
        self.remotedb = nowplaying.db.MetadataDB(databasefile=str(self.remotedbfile))
        await self.setup_watcher()

    async def getplayingtrack(self) -> TrackMetadata | None:
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

    @staticmethod
    def settingsui():
        """Remote input plugin has no settings UI"""

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
