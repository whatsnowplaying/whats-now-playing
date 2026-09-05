#!/usr/bin/env python3
"""
Rekordbox Main Plugin

This module contains the main plugin class that coordinates all the Rekordbox components.
It handles the plugin lifecycle, UI integration, and track detection via file watching.
"""

import asyncio
import contextlib
import logging
import threading
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QLabel,
    QLineEdit,
    QVBoxLayout,
)
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

import nowplaying.inputs
import nowplaying.wizard
from nowplaying.inputs import Detected, InputPlugin

from .config import ConfigReader
from .database import DatabaseReader
from .types import RekordboxError

_WAL_DEBOUNCE_SECONDS = 5.0

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.uihelp


class _RekordboxWizardPage(nowplaying.wizard.WizardPage):  # pylint: disable=too-few-public-methods
    """First-run wizard page for Rekordbox configuration."""

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.setTitle("Rekordbox Setup")

        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("Required for Rekordbox 7")

        layout = QVBoxLayout()
        layout.addWidget(
            QLabel(
                "Rekordbox 6: key is read automatically.\n"
                "Rekordbox 7: enter the 64-character database key below.\n"
                'Search: "what is the rekordbox 7 sqlcipher key for master.db"'
            )
        )
        layout.addWidget(self._key_edit)
        layout.addStretch()
        self.setLayout(layout)

    def initializePage(self):  # pylint: disable=invalid-name
        """Pre-populate the key field from saved configuration."""
        self._key_edit.setText(self.config.cparser.value("rekordbox/custom_key", defaultValue=""))

    def collected(self) -> dict[str, object]:
        """The database key the user supplied."""
        return {"rekordbox/custom_key": self._key_edit.text().strip()}


class RekordboxPlugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
    """Rekordbox input plugin for reading track data from database"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QSettings | None" = None,
    ):
        # Initialize components first before calling super
        self.config_reader = ConfigReader()
        self.database_reader = DatabaseReader(self.config_reader)

        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Rekordbox"
        self.wizardpage = _RekordboxWizardPage

        self.event_handler = None
        self.observer = None
        self._current_track: dict | None = None
        self._running = False
        self._needs_refresh: bool = True
        self._last_wal_mtime: float = 0.0
        self._wal_timer: threading.Timer | None = None
        self._wal_timer_lock = threading.Lock()
        self._status = nowplaying.inputs.InputStatus()
        self._tried_key: str = ""

    def detect(self) -> Detected:
        """Report whether the Rekordbox data directory exists on this machine.

        Nothing to configure: the data path is found automatically, and the one
        setting Rekordbox needs is the database key, which cannot be detected.
        """
        try:
            return Detected(self.config_reader.get_data_path().exists())
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Rekordbox detect() failed")
            return Detected()

    def defaults(self, qsettings: "QSettings"):
        """Set default configuration values"""
        qsettings.setValue("rekordbox/artist_query_scope", "entire_library")
        qsettings.setValue("rekordbox/custom_key", "")
        qsettings.setValue("rekordbox/selected_playlists", "")

    def connect_settingsui(self, qwidget: "QWidget", uihelp: "nowplaying.uihelp.UIHelp"):
        """Connect UI elements"""
        self.qwidget = qwidget
        self.uihelp = uihelp

    def load_settingsui(self, qwidget: "QWidget"):
        """Load configuration values into UI"""
        qwidget.rekordbox_custom_key_lineedit.setText(
            self.config.cparser.value("rekordbox/custom_key", defaultValue="")
        )

        scope = self.config.cparser.value(
            "rekordbox/artist_query_scope", defaultValue="entire_library"
        )
        if scope == "selected_playlists":
            qwidget.rekordbox_artist_scope_combo.setCurrentText("Selected Playlists")
        else:
            qwidget.rekordbox_artist_scope_combo.setCurrentText("Entire Library")

        qwidget.rekordbox_selected_playlists_lineedit.setText(
            self.config.cparser.value("rekordbox/selected_playlists", defaultValue="")
        )

    def save_settingsui(self, qwidget: "QWidget"):
        """Save UI values to configuration"""
        self.config.cparser.setValue(
            "rekordbox/custom_key", qwidget.rekordbox_custom_key_lineedit.text()
        )

        scope = (
            "selected_playlists"
            if qwidget.rekordbox_artist_scope_combo.currentText() == "Selected Playlists"
            else "entire_library"
        )
        self.config.cparser.setValue("rekordbox/artist_query_scope", scope)

        self.config.cparser.setValue(
            "rekordbox/selected_playlists", qwidget.rekordbox_selected_playlists_lineedit.text()
        )

    def verify_settingsui(self, qwidget: "QWidget"):
        """Verify configuration settings"""

    def desc_settingsui(self, qwidget: "QWidget"):
        """Provide plugin description"""
        qwidget.setText(
            "Rekordbox plugin reads track data from Rekordbox 6 or 7 play history. "
            "Rekordbox 6: database key is read automatically. "
            "Rekordbox 7: enter the 64-character database key above. Search: "
            '"what is the rekordbox 7 sqlcipher key for master.db". '
            "Requires Performance Mode."
        )

    def _fs_event(self, event):  # pylint: disable=unused-argument
        """File system event handler - called from watchdog thread"""
        with self._wal_timer_lock:
            if self._wal_timer is not None:
                self._wal_timer.cancel()
            self._wal_timer = threading.Timer(_WAL_DEBOUNCE_SECONDS, self._wal_timer_fired)
            self._wal_timer.daemon = True
            self._wal_timer.start()

    def _wal_timer_fired(self) -> None:
        """Called after debounce silence; clears the timer reference and flags a refresh."""
        logging.debug("processing rekordbox database change")
        with self._wal_timer_lock:
            self._wal_timer = None
        self._needs_refresh = True

    def _database_present(self) -> bool:
        """Whether the database file is there, recording WAITING when it is not."""
        try:
            present = self.config_reader.get_database_path().exists()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Rekordbox database location is unknown")
            self._status = nowplaying.inputs.InputStatus.broken(
                "Cannot work out where the Rekordbox database lives."
            )
            return False
        if not present:
            self._status = nowplaying.inputs.InputStatus.waiting(
                "Waiting for the Rekordbox library.", "the database file is not there yet"
            )
        return present

    async def _open_database(self) -> bool:
        """Try to open the database with whatever key is configured.

        Records the key it tried, so status() can tell a key the user has since
        corrected from the one that failed.

        An absent database file is WAITING, not NEEDS_USER: Rekordbox may not
        have been launched yet, or the library may be on a drive that is not
        mounted. Calling that the user's problem would wedge the plugin, since
        nothing rebuilds it and the key it has may be perfectly good.
        """
        if not self._database_present():
            return False

        self._tried_key = self.config.cparser.value("rekordbox/custom_key", defaultValue="")
        try:
            await self.database_reader.initialize(custom_key=self._tried_key)
        except RekordboxError as err:
            self._status = nowplaying.inputs.InputStatus.needs_user(str(err), repr(err))
            return False
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.exception("Rekordbox database reader would not initialize")
            self._status = nowplaying.inputs.InputStatus.broken(
                "Rekordbox could not be read. See the log for details.",
                repr(err),
            )
            return False
        self._status = nowplaying.inputs.InputStatus()
        return True

    def status(self) -> "nowplaying.inputs.InputStatus":
        """Report health, noticing what has changed since the last attempt.

        Both recoveries go through STARTING rather than straight to OK, because
        STARTING is what licenses getplayingtrack() to do the setup: reporting
        OK from here would promise a working plugin while nothing had reopened
        anything. It stays cheap for the same reason -- this runs every cycle,
        so it reads configuration and stats a directory, and leaves the work to
        the call already allowed to do it.
        """
        health = self._status.health
        if health is nowplaying.inputs.InputHealth.NEEDS_USER:
            configured = self.config.cparser.value("rekordbox/custom_key", defaultValue="")
            if configured != self._tried_key:
                self._status = nowplaying.inputs.InputStatus.starting(
                    "Trying the new Rekordbox key."
                )
        elif health is nowplaying.inputs.InputHealth.WAITING:
            # Only leave WAITING when the thing being waited for has appeared,
            # or getplayingtrack() would retry the setup on every cycle.
            with contextlib.suppress(Exception):
                if self.config_reader.get_database_path().exists():
                    self._status = nowplaying.inputs.InputStatus.starting(
                        "Found the Rekordbox library."
                    )
        return self._status

    async def start(self, testmode: bool = False):  # pylint: disable=unused-argument
        """Initialize and start the plugin.

        Nothing here raises for an operational problem. A missing directory or a
        key that does not open the database are both reported through status(),
        and _ensure_started() is safe to call again once whatever was wrong has
        changed.
        """
        logging.info("Starting Rekordbox plugin")
        await self._ensure_started()

    async def _ensure_started(self) -> None:
        """Set up whatever is not set up yet. Safe to call repeatedly.

        The watcher comes before the database and is kept even when the key is
        wrong: which directory to watch comes from options.json rather than
        from decrypting anything, so a plugin waiting on a corrected key still
        gets told when the database changes. Without it the plugin would fall
        back to _check_wal_mtime() stat polling for the rest of the session.
        """
        if not self._start_watcher():
            return
        await self._open_database()

    def _start_watcher(self) -> bool:
        """Watch the database directory. False if there is nothing to watch yet.

        The directory can be absent for ordinary reasons -- Rekordbox not
        installed yet, or a library on a drive that is not mounted -- so this is
        WAITING and gets tried again rather than being the user's problem.
        Checking first matters because PollingObserver and inotify both raise
        from schedule() on a missing path, where fsevents does not.
        """
        if self.observer:
            return True

        try:
            db_dir = self.config_reader.get_database_path().parent
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Rekordbox database location is unknown")
            self._status = nowplaying.inputs.InputStatus.broken(
                "Cannot work out where the Rekordbox database lives."
            )
            return False

        if not db_dir.is_dir():
            self._status = nowplaying.inputs.InputStatus.waiting(
                "Waiting for the Rekordbox library to appear.", f"{db_dir} is not there"
            )
            return False

        logging.info("Watching for Rekordbox database changes in %s", db_dir)

        self.event_handler = PatternMatchingEventHandler(
            patterns=["*.db", "*.db-wal", "*.db-journal"],
            ignore_patterns=[".DS_Store"],
            ignore_directories=True,
        )
        self.event_handler.on_modified = self._fs_event
        self.event_handler.on_created = self._fs_event

        if self.config.cparser.value("quirks/pollingobserver", type=bool):
            polling_interval = self.config.cparser.value("quirks/pollinginterval", type=float)
            self.observer = PollingObserver(timeout=polling_interval)
        else:
            self.observer = Observer()

        try:
            self.observer.schedule(self.event_handler, str(db_dir), recursive=False)
            self.observer.start()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Could not watch %s", db_dir)
            self.observer = None
            self._status = nowplaying.inputs.InputStatus.waiting(
                "Waiting for the Rekordbox library to appear.", f"could not watch {db_dir}"
            )
            return False

        self._running = True
        self._needs_refresh = True
        return True

    async def stop(self):
        """Stop the plugin and cleanup"""
        logging.info("Stopping Rekordbox plugin")
        self._running = False

        with self._wal_timer_lock:
            if self._wal_timer is not None:
                self._wal_timer.cancel()
                self._wal_timer = None

        if self.observer:
            self.observer.stop()
            await asyncio.to_thread(self.observer.join)
            self.observer = None
        self.event_handler = None

    def _check_wal_mtime(self) -> bool:
        """Return True if master.db-wal has been modified since last check."""
        if not self.database_reader.database_path:
            return False
        wal_path = self.database_reader.database_path.with_suffix(".db-wal")
        try:
            mtime = wal_path.stat().st_mtime
        except OSError:
            return False
        if mtime != self._last_wal_mtime:
            self._last_wal_mtime = mtime
            return True
        return False

    async def getplayingtrack(self) -> dict:
        """Get the currently playing track metadata.

        Reopens the database when status() has noticed a new key: this is where
        that belongs, since it is the call already allowed to do the work.
        """
        if self._status.health is nowplaying.inputs.InputHealth.STARTING:
            await self._ensure_started()
            # Setup has to have finished, which is narrower than "worth
            # polling": InputStatus is truthy for WAITING too, so testing the
            # status itself would walk into a read with no database open.
            if self._status.health is not nowplaying.inputs.InputHealth.OK:
                return self._current_track or {}
            self._needs_refresh = True

        if self._check_wal_mtime():
            self._needs_refresh = True
        if self._needs_refresh:
            try:
                track = await self.database_reader.get_recent_track()
            except RekordboxError:
                logging.exception("Rekordbox database query failed")
                return self._current_track or {}
            logging.debug(
                "Rekordbox query returned: %s",
                f"{track.artist} - {track.title}" if track else None,
            )
            if self.database_reader.has_track_changed(track):
                self._current_track = track.to_metadata() if track else None
                if track:
                    logging.debug("Rekordbox track changed: %s - %s", track.artist, track.title)
            self._needs_refresh = False
        return self._current_track or {}

    async def getrandomtrack(self, playlist: str) -> str | None:
        """Get random track from playlist"""
        try:
            track = await self.database_reader.get_random_track_from_playlist(playlist)
            if track and track.artist and track.title:
                return f"{track.artist} - {track.title}"
            return None
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.error("Failed to get random track from playlist %s: %s", playlist, err)
            return None

    def validmixmodes(self) -> list[str]:
        """Valid mix modes - Rekordbox only shows latest track"""
        return ["newest"]

    def setmixmode(self, mixmode: str) -> str:  # pylint: disable=unused-argument
        """Set mix mode - only newest is supported"""
        return "newest"

    def getmixmode(self) -> str:
        """Get current mix mode"""
        return "newest"

    async def has_tracks_by_artist(self, artist_name: str) -> bool:
        """Check if DJ has any tracks by the specified artist"""
        scope = self.config.cparser.value(
            "rekordbox/artist_query_scope", defaultValue="entire_library"
        )
        try:
            if scope == "selected_playlists":
                return await self._check_artist_in_playlists(artist_name)
            return await self.database_reader.has_artist_in_library(artist_name)
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.error("Failed to query Rekordbox for artist %s: %s", artist_name, err)
            return False

    async def _check_artist_in_playlists(self, artist_name: str) -> bool:
        """Check if artist exists in any of the selected playlists"""
        selected = self.config.cparser.value("rekordbox/selected_playlists", defaultValue="")
        playlist_names = [n.strip() for n in selected.split(",") if n.strip()]
        if not playlist_names:
            return False
        for playlist_name in playlist_names:
            if await self.database_reader.has_artist_in_playlist(artist_name, playlist_name):
                return True
        return False
