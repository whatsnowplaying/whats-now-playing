#!/usr/bin/env python3
"""
Serato Plugin

Main plugin class for Serato DJ SQLite database input (4.0+).
"""

import logging
import os
import pathlib
import platform
import sqlite3
from typing import TYPE_CHECKING

import aiosqlite
from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

import nowplaying.inputs
import nowplaying.utils.sqlite
from nowplaying.types import TrackMetadata
from .handler import Serato4Handler
from .reader import Serato4RootReader
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
        self.root_reader: Serato4RootReader | None = None
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

        # Initialize root reader for crate/container queries
        root_db_path = self.serato_lib_path / "root.sqlite"
        if root_db_path.exists():
            self.root_reader = Serato4RootReader(root_db_path)
        else:
            logging.warning(
                "root.sqlite not found at %s - crate filtering unavailable", root_db_path
            )

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
        qsettings.setValue("serato4/artist_query_scope", "entire_library")
        qsettings.setValue("serato4/selected_playlists", "")
        qsettings.setValue("serato4/additional_libpaths", "")

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

    def _get_all_library_paths(self) -> list[pathlib.Path]:
        """Get all configured Serato 4 library paths (primary + additional)

        Returns list of paths to check for root.sqlite or location.sqlite files
        """
        paths = []

        # Add primary library path (auto-detected)
        if self.serato_lib_path:
            paths.append(self.serato_lib_path)

        # Add additional library paths from config
        if additional_paths := self.config.cparser.value(
            "serato4/additional_libpaths", defaultValue=""
        ):
            # Split by newlines or semicolons, strip whitespace, filter empty
            extra_paths = [
                pathlib.Path(path.strip())
                for path in additional_paths.replace(";", "\n").split("\n")
                if path.strip()
            ]
            paths.extend(extra_paths)

        return paths

    async def has_tracks_by_artist(self, artist_name: str) -> bool:
        """Check if DJ has any tracks by the specified artist

        This method is used by the artist extras system to filter artists
        based on whether the DJ has tracks by them in their library.

        Args:
            artist_name: Artist name to search for

        Returns:
            True if artist found in library or selected playlists, False otherwise
        """
        try:
            # Only check local library - remote mode doesn't support this
            if self.mode != "local":
                logging.debug("Artist query not available - not in local mode")
                return False

            library_paths = self._get_all_library_paths()
            if not library_paths:
                logging.warning("No Serato 4 library paths configured")
                return False

            # Get query scope configuration
            scope = self.config.cparser.value(
                "serato4/artist_query_scope", defaultValue="entire_library"
            )

            if scope == "selected_playlists":
                # Check selected crates across all libraries
                return await self._has_tracks_in_selected_playlists(artist_name, library_paths)

            # Check entire library across all library paths
            for lib_path in library_paths:
                if await self._has_tracks_in_entire_library(artist_name, lib_path):
                    logging.debug("Found artist '%s' in library: %s", artist_name, lib_path)
                    return True
            return False

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.exception(
                "Failed to query Serato 4 library for artist %s: %s", artist_name, err
            )
            return False

    async def _has_tracks_in_selected_playlists(
        self, artist_name: str, library_paths: list[pathlib.Path]
    ) -> bool:
        """Check for artist tracks in specific playlists/crates across all libraries"""
        selected_playlists = self.config.cparser.value(
            "serato4/selected_playlists", defaultValue=""
        )
        if not selected_playlists.strip():
            logging.debug("No playlists selected for artist filtering")
            return False

        # Parse comma-separated playlist names
        crate_names = [name.strip() for name in selected_playlists.split(",") if name.strip()]
        if not crate_names:
            return False

        logging.debug("Checking artist '%s' in crates: %s", artist_name, crate_names)

        # Check each library path
        for lib_path in library_paths:
            # Determine which database file to use
            root_db = lib_path / "root.sqlite"
            location_db = lib_path / "Library" / "location.sqlite"

            db_path = None
            if root_db.exists():
                db_path = root_db
            elif location_db.exists():
                db_path = location_db

            if not db_path:
                logging.debug("No database found at %s", lib_path)
                continue

            # Create reader for this library and check for artist
            reader = Serato4RootReader(db_path)
            if await reader.has_artist_in_crates(artist_name, crate_names):
                return True

        return False

    async def _has_tracks_in_entire_library(  # pylint: disable=no-self-use
        self, artist_name: str, lib_path: pathlib.Path
    ) -> bool:
        """Check for artist tracks in entire library at given path

        Uses the asset table in root.sqlite or location.sqlite to search the library.
        This is more efficient than loading the full master.sqlite database.

        Args:
            artist_name: Artist name to search for
            lib_path: Path to Serato library (containing root.sqlite or Library/location.sqlite)

        Returns:
            True if artist found in this library, False otherwise
        """
        # Determine which database file to use
        root_db = lib_path / "root.sqlite"
        location_db = lib_path / "Library" / "location.sqlite"

        db_path = None
        if root_db.exists():
            db_path = root_db
        elif location_db.exists():
            db_path = location_db

        if not db_path:
            logging.debug("No database found at %s", lib_path)
            return False

        try:
            async def _query_library() -> bool:
                async with aiosqlite.connect(db_path) as connection:
                    connection.row_factory = aiosqlite.Row

                    # Search asset table for artist
                    query = """
                        SELECT DISTINCT 1
                        FROM asset
                        WHERE artist LIKE ?
                        LIMIT 1
                    """

                    params = [f"%{artist_name}%"]
                    cursor = await connection.execute(query, params)
                    row = await cursor.fetchone()

                    return row is not None

            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_query_library)
        except sqlite3.Error as exc:
            logging.error(
                "Failed to query library at %s for artist %s: %s", lib_path, artist_name, exc
            )
            return False

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

        # Connect library tab button if it exists
        library_widgets = self.uihelp.find_tab_by_identifier(qwidget, "serato_artist_scope_combo")
        if library_widgets and hasattr(library_widgets, "add_additional_lib_button"):
            library_widgets.add_additional_lib_button.clicked.connect(
                self.on_add_additional_lib_button
            )

    def on_add_additional_lib_button(self):
        """Add additional library button clicked action"""
        library_widgets = self.uihelp.find_tab_by_identifier(
            self.qwidget, "serato_artist_scope_combo"
        )
        startdir = str(pathlib.Path.home())
        if libdir := QFileDialog.getExistingDirectory(
            self.qwidget, "Select additional Serato library directory", startdir
        ):
            if current_text := library_widgets.additional_libs_textedit.toPlainText().strip():
                new_text = current_text + "\n" + libdir
            else:
                new_text = libdir
            library_widgets.additional_libs_textedit.setPlainText(new_text)

    def load_settingsui(self, qwidget: "QWidget") -> None:
        """Load settings into UI"""
        self._load_connection_settings(qwidget)
        self._load_library_settings(qwidget)

    def _load_connection_settings(self, qwidget: "QWidget") -> None:
        """Load connection tab settings"""
        connection_widgets = self.uihelp.find_tab_by_identifier(qwidget, "local_button")

        # Load connection mode settings
        local_mode = self.config.cparser.value("serato4/local", type=bool, defaultValue=True)
        remote_url = self.config.cparser.value("serato4/url", defaultValue="")
        remote_interval = self.config.cparser.value(
            "serato4/interval", type=float, defaultValue=30.0
        )

        # Set radio buttons
        connection_widgets.local_button.setChecked(local_mode)
        connection_widgets.remote_button.setChecked(not local_mode)

        # Serato 4 auto-detects library path, but show it in the lineedit if requested
        library_path = self.detected_serato_library_path
        if library_path and hasattr(connection_widgets, "local_dir_lineedit"):
            connection_widgets.local_dir_lineedit.setText(str(library_path))

        # Load remote settings
        connection_widgets.remote_url_lineedit.setText(remote_url)
        connection_widgets.remote_poll_lineedit.setText(str(remote_interval))

        # Load deck skip settings
        deckskip = self.config.cparser.value("serato4/deckskip")

        # Reset all checkboxes
        connection_widgets.deck1_checkbox.setChecked(False)
        connection_widgets.deck2_checkbox.setChecked(False)
        connection_widgets.deck3_checkbox.setChecked(False)
        connection_widgets.deck4_checkbox.setChecked(False)

        if deckskip:
            if not isinstance(deckskip, list):
                deckskip = list(deckskip)

            if "1" in deckskip:
                connection_widgets.deck1_checkbox.setChecked(True)
            if "2" in deckskip:
                connection_widgets.deck2_checkbox.setChecked(True)
            if "3" in deckskip:
                connection_widgets.deck3_checkbox.setChecked(True)
            if "4" in deckskip:
                connection_widgets.deck4_checkbox.setChecked(True)

    def _load_library_settings(self, qwidget: "QWidget") -> None:
        """Load library tab settings"""
        # Load library/query settings if the tab exists
        library_widgets = self.uihelp.find_tab_by_identifier(qwidget, "serato_artist_scope_combo")
        if library_widgets:
            # Load artist query scope
            scope = self.config.cparser.value(
                "serato4/artist_query_scope", defaultValue="entire_library"
            )
            if scope == "selected_playlists":
                library_widgets.serato_artist_scope_combo.setCurrentText("Selected Playlists")
            else:
                library_widgets.serato_artist_scope_combo.setCurrentText("Entire Library")

            # Load selected playlists
            library_widgets.serato_playlists_lineedit.setText(
                self.config.cparser.value("serato4/selected_playlists", defaultValue="")
            )

            # Load additional library paths
            additional_paths = self.config.cparser.value(
                "serato4/additional_libpaths", defaultValue=""
            )
            library_widgets.additional_libs_textedit.setPlainText(additional_paths)

    def save_settingsui(self, qwidget: "QWidget") -> None:
        """Save settings from UI"""
        connection_widgets = self.uihelp.find_tab_by_identifier(qwidget, "local_button")

        # Save connection mode settings
        local_mode = connection_widgets.local_button.isChecked()
        self.config.cparser.setValue("serato4/local", local_mode)

        # Save remote settings
        remote_url = connection_widgets.remote_url_lineedit.text().strip()
        self.config.cparser.setValue("serato4/url", remote_url)

        remote_interval = float(connection_widgets.remote_poll_lineedit.text() or "30.0")
        self.config.cparser.setValue("serato4/interval", remote_interval)

        # Save deck skip settings
        deckskip = []
        if connection_widgets.deck1_checkbox.isChecked():
            deckskip.append("1")
        if connection_widgets.deck2_checkbox.isChecked():
            deckskip.append("2")
        if connection_widgets.deck3_checkbox.isChecked():
            deckskip.append("3")
        if connection_widgets.deck4_checkbox.isChecked():
            deckskip.append("4")

        self.config.cparser.setValue("serato4/deckskip", deckskip)

        # Save library/query settings if the tab exists
        library_widgets = self.uihelp.find_tab_by_identifier(qwidget, "serato_artist_scope_combo")
        if library_widgets:
            # Save artist query scope
            scope = (
                "selected_playlists"
                if library_widgets.serato_artist_scope_combo.currentText() == "Selected Playlists"
                else "entire_library"
            )
            self.config.cparser.setValue("serato4/artist_query_scope", scope)

            # Save selected playlists
            self.config.cparser.setValue(
                "serato4/selected_playlists",
                library_widgets.serato_playlists_lineedit.text()
            )

            # Save additional library paths
            additional_paths = library_widgets.additional_libs_textedit.toPlainText().strip()
            self.config.cparser.setValue("serato4/additional_libpaths", additional_paths)
