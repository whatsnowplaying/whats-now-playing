#!/usr/bin/env python3
"""
Serato Plugin

Main plugin class for Serato DJ SQLite database input (4.0+).
"""

import logging
import os
import pathlib
import platform
from typing import TYPE_CHECKING

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.inputs
from nowplaying.types import TrackMetadata
from .handler import Serato4Handler
from .remote import SeratoRemoteHandler


if TYPE_CHECKING:
    from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module
    from PySide6.QtWidgets import QWidget

    import nowplaying.config


class Plugin(nowplaying.inputs.InputPlugin):  # pylint: disable=too-many-instance-attributes
    """Serato 4+ input plugin"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QSettings | None" = None,
    ) -> None:
        super().__init__(config=config, qsettings=qsettings)

        self.displayname = "Serato DJ"
        self.handler: Serato4Handler | None = None
        self.remote_handler: SeratoRemoteHandler | None = None
        self.serato_lib_path: pathlib.Path | None = None
        self.mode = "local"  # "local" or "remote"
        self.url: str | None = None

    @property
    def detected_serato_library_path(self) -> pathlib.Path | None:
        """Auto-detected Serato 4+ library path - can be mocked for testing"""
        return self._find_serato_library()

    def configure(self) -> None:
        """Configure the plugin for local or remote mode"""
        if not self.config:
            # No config - default to local mode with auto-detection
            self.mode = "local"
            self.serato_lib_path = self.detected_serato_library_path
            self.url = None
            return

        # Check if remote URL is configured
        remote_url = self.config.cparser.value("serato4/url")
        local_mode = self.config.cparser.value("serato4/local", type=bool, defaultValue=True)

        # Prefer local mode when both are configured, like serato3
        if local_mode or not remote_url:
            self.mode = "local"
            self.url = None
            self.serato_lib_path = self.detected_serato_library_path
        elif remote_url and SeratoRemoteHandler.validate_url(remote_url):
            self.mode = "remote"
            self.url = remote_url
            self.serato_lib_path = None
        else:
            # Fallback to local mode if remote URL is invalid
            self.mode = "local"
            self.url = None
            self.serato_lib_path = self.detected_serato_library_path

    @staticmethod
    def _find_serato_library() -> pathlib.Path | None:
        """Find Serato 4+ library directory with master.sqlite"""
        # Common Serato 4+ locations to check
        search_paths = []

        # 1. Qt standard app data locations
        app_data_locations = QStandardPaths.standardLocations(QStandardPaths.AppDataLocation)
        for app_data_path in app_data_locations:
            search_paths.append(pathlib.Path(app_data_path).parent / "Serato" / "Library")

        # 2. Platform-specific standard locations
        system = platform.system()

        if system == "Darwin":  # macOS
            home = pathlib.Path.home()
            search_paths.extend(
                [
                    home / "Library" / "Application Support" / "Serato" / "Library",
                    home / "Music" / "Serato" / "Library",
                ]
            )
        elif system == "Windows":
            if appdata := os.getenv("APPDATA"):
                search_paths.append(pathlib.Path(appdata) / "Serato" / "Library")
            if localappdata := os.getenv("LOCALAPPDATA"):
                search_paths.append(pathlib.Path(localappdata) / "Serato" / "Library")
        elif system == "Linux":
            home = pathlib.Path.home()
            search_paths.extend(
                [
                    home / ".local" / "share" / "Serato" / "Library",
                    home / ".config" / "Serato" / "Library",
                ]
            )

        # Check each potential path
        for serato_lib_path in search_paths:
            if serato_lib_path.exists() and (serato_lib_path / "master.sqlite").exists():
                logging.info("Found Serato library at: %s", serato_lib_path)
                return serato_lib_path

        logging.debug("No Serato library found in standard locations: %s", search_paths)
        return None

    async def start(self) -> None:
        """Start the plugin in local or remote mode"""
        self.configure()

        if self.mode == "local":
            await self._start_local_mode()
        elif self.mode == "remote":
            await self._start_remote_mode()
        else:
            logging.error("Invalid mode: %s", self.mode)

    async def _start_local_mode(self) -> None:
        """Start local SQLite mode"""
        if not self.serato_lib_path:
            logging.error(
                "Serato library path not found. "
                "Please ensure Serato DJ is installed and has been run at least once."
            )
            return

        # Check if polling observer should be used
        usepoll = False
        polling_interval = 1.0
        if self.config:
            usepoll = self.config.cparser.value("quirks/pollingobserver", type=bool)
            polling_interval = self.config.cparser.value(
                "quirks/pollinginterval", type=float, defaultValue=1.0
            )

        self.handler = Serato4Handler(
            self.serato_lib_path, pollingobserver=usepoll, polling_interval=polling_interval
        )
        await self.handler.start()

    async def _start_remote_mode(self) -> None:
        """Start remote web scraping mode"""
        if not self.url:
            logging.error("Remote URL not configured for Serato remote mode")
            return

        # Get polling interval for remote mode
        poll_interval = 30.0
        if self.config:
            poll_interval = self.config.cparser.value(
                "serato4/interval", type=float, defaultValue=30.0
            )

        self.remote_handler = SeratoRemoteHandler(self.url, poll_interval)
        logging.info("Started Serato remote mode with URL: %s", self.url)

    async def stop(self) -> None:
        """Stop the plugin"""
        if self.handler:
            await self.handler.stop()
            self.handler = None
        if self.remote_handler:
            # Remote handler doesn't need async cleanup
            self.remote_handler = None

    def install(self) -> bool:
        """Auto-install for Serato 4"""
        serato_lib_path = self.detected_serato_library_path
        if serato_lib_path:
            logging.info("Auto-installing Serato plugin with library at: %s", serato_lib_path)
            self.config.cparser.setValue("settings/input", "serato")
            return True

        logging.debug("Serato 4+ installation not found for auto-install")
        return False

    def validmixmodes(self) -> list[str]:
        """Valid mix modes for Serato"""
        return ["newest", "oldest"]  # Both modes supported with SQLite timestamps

    def setmixmode(self, mixmode: str) -> str:
        """Set mix mode"""
        if mixmode not in ["newest", "oldest"]:
            mixmode = self.config.cparser.value("serato4/mixmode", defaultValue="newest")

        self.config.cparser.setValue("serato4/mixmode", mixmode)
        return mixmode

    def getmixmode(self) -> str:
        """Get current mix mode"""
        return self.config.cparser.value("serato4/mixmode", defaultValue="newest")

    def defaults(self, qsettings: "QWidget") -> None:
        """Set default configuration values"""
        # Default to local mode
        qsettings.setValue("serato4/local", True)
        qsettings.setValue("serato4/url", "")
        qsettings.setValue("serato4/interval", 30.0)

    def desc_settingsui(self, qwidget: "QWidget") -> None:
        """Plugin description for UI"""
        qwidget.setText(
            "This plugin provides support for Serato DJ 4+. "
            "Local mode uses SQLite database for real-time track detection. "
            "Remote mode scrapes Serato Live Playlists from serato.com."
        )

    async def getplayingtrack(self) -> TrackMetadata | None:
        """Get current track information from local or remote mode"""
        if self.mode == "local":
            return await self._get_local_track()
        if self.mode == "remote":
            return await self._get_remote_track()
        return None

    async def _get_local_track(self) -> TrackMetadata | None:
        """Get track from local SQLite database"""
        if not self.handler:
            return None

        # Get configuration
        mixmode = self.getmixmode()
        deckskip = None
        if self.config:
            deckskip = self.config.cparser.value("serato4/deckskip")
            if deckskip and not isinstance(deckskip, list):
                deckskip = list(deckskip)

        # Get track using mixmode and deck skip logic
        track_data = await self.handler.get_current_track_by_mixmode(
            mixmode=mixmode, deckskip=deckskip
        )
        if not track_data:
            return None

        # Convert Serato 4 database format to TrackMetadata format
        return self._convert_local_track_data(track_data)

    async def _get_remote_track(self) -> TrackMetadata | None:
        """Get track from remote web scraping"""
        if not self.remote_handler:
            return None

        # Remote mode is always "newest" - no mixmode/deckskip logic needed
        track_data = await self.remote_handler.get_current_track()
        if not track_data:
            return None

        # Convert remote track data to TrackMetadata format
        return self._convert_remote_track_data(track_data)

    @staticmethod
    def _convert_local_track_data(track_data: dict[str, any]) -> TrackMetadata:
        """Convert local SQLite track data to TrackMetadata format"""
        track_metadata: TrackMetadata = {}

        # Basic track information
        if track_data.get("artist"):
            track_metadata["artist"] = str(track_data["artist"])
        if track_data.get("title"):
            track_metadata["title"] = str(track_data["title"])
        if track_data.get("album"):
            track_metadata["album"] = str(track_data["album"])
        if track_data.get("genre"):
            track_metadata["genre"] = str(track_data["genre"])
        if track_data.get("year"):
            track_metadata["year"] = str(track_data["year"])
        if track_data.get("key"):
            track_metadata["key"] = str(track_data["key"])

        # Numeric fields that need string conversion
        if track_data.get("bpm"):
            track_metadata["bpm"] = str(track_data["bpm"])
        if track_data.get("bitrate"):
            track_metadata["bitrate"] = str(track_data["bitrate"])

        # Duration should be integer (seconds)
        if track_data.get("duration"):
            track_metadata["duration"] = int(track_data["duration"])

        # Handle file path for local tracks
        if track_data.get("file_name"):
            track_metadata["filename"] = str(track_data["file_name"])

        # Store deck info in the standard 'deck' field
        if track_data.get("deck"):
            track_metadata["deck"] = str(track_data["deck"])

        return track_metadata

    @staticmethod
    def _convert_remote_track_data(track_data: dict[str, any]) -> TrackMetadata:
        """Convert remote web scraping track data to TrackMetadata format"""
        track_metadata: TrackMetadata = {}

        # Remote only provides artist and title
        if track_data.get("artist"):
            track_metadata["artist"] = str(track_data["artist"])
        if track_data.get("title"):
            track_metadata["title"] = str(track_data["title"])

        return track_metadata

    @property
    def pluginname(self) -> str:
        """Plugin name for identification"""
        return "serato"

    @property
    def description(self) -> str:
        """Plugin description"""
        return "Serato DJ input"

    def connect_settingsui(self, qwidget: "QWidget", uihelp) -> None:
        """Connect UI elements"""
        self.qwidget = qwidget
        self.uihelp = uihelp
        # New serato plugin uses auto-detection - no directory selection needed

    def load_settingsui(self, qwidget: "QWidget") -> None:
        """Load settings into UI"""
        # Load connection mode settings
        local_mode = self.config.cparser.value("serato4/local", type=bool, defaultValue=True)
        remote_url = self.config.cparser.value("serato4/url", defaultValue="")
        remote_interval = self.config.cparser.value(
            "serato4/interval", type=float, defaultValue=30.0
        )

        # Set radio buttons
        qwidget.local_button.setChecked(local_mode)
        qwidget.remote_button.setChecked(not local_mode)

        # Update local status
        library_path = self.detected_serato_library_path
        if library_path:
            qwidget.local_status_display.setText(f"Auto-detected Serato library at {library_path}")
        else:
            qwidget.local_status_display.setText("No Serato 4+ installation found")

        # Load remote settings
        qwidget.remote_url_lineedit.setText(remote_url)
        qwidget.remote_poll_lineedit.setText(str(remote_interval))

        # Load mixmode
        mixmode = self.getmixmode()
        if mixmode == "oldest":
            qwidget.oldest_button.setChecked(True)
        else:
            qwidget.newest_button.setChecked(True)

        # Load deck skip settings
        deckskip = self.config.cparser.value("serato4/deckskip")

        # Reset all checkboxes
        qwidget.deck1_checkbox.setChecked(False)
        qwidget.deck2_checkbox.setChecked(False)
        qwidget.deck3_checkbox.setChecked(False)
        qwidget.deck4_checkbox.setChecked(False)

        if deckskip:
            if not isinstance(deckskip, list):
                deckskip = list(deckskip)

            if "1" in deckskip:
                qwidget.deck1_checkbox.setChecked(True)
            if "2" in deckskip:
                qwidget.deck2_checkbox.setChecked(True)
            if "3" in deckskip:
                qwidget.deck3_checkbox.setChecked(True)
            if "4" in deckskip:
                qwidget.deck4_checkbox.setChecked(True)

    def save_settingsui(self, qwidget: "QWidget") -> None:
        """Save settings from UI"""
        # Save connection mode settings
        local_mode = qwidget.local_button.isChecked()
        self.config.cparser.setValue("serato4/local", local_mode)

        # Save remote settings
        remote_url = qwidget.remote_url_lineedit.text().strip()
        self.config.cparser.setValue("serato4/url", remote_url)

        remote_interval = float(qwidget.remote_poll_lineedit.text() or "30.0")
        self.config.cparser.setValue("serato4/interval", remote_interval)

        # Save mixmode
        if qwidget.oldest_button.isChecked():
            self.setmixmode("oldest")
        else:
            self.setmixmode("newest")

        # Save deck skip settings
        deckskip = []
        if qwidget.deck1_checkbox.isChecked():
            deckskip.append("1")
        if qwidget.deck2_checkbox.isChecked():
            deckskip.append("2")
        if qwidget.deck3_checkbox.isChecked():
            deckskip.append("3")
        if qwidget.deck4_checkbox.isChecked():
            deckskip.append("4")

        self.config.cparser.setValue("serato4/deckskip", deckskip)
