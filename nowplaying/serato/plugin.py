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
        qsettings.setValue("serato4/artist_query_scope", "entire_library")
        qsettings.setValue("serato4/selected_playlists", "")

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

        # Get location mappings for path resolution
        location_mappings = await self.handler.get_location_mappings()

        # Convert Serato 4 database format to TrackMetadata format
        return self._convert_local_track_data(track_data, location_mappings)

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
    def _convert_local_track_data(  # pylint: disable=too-many-branches
        track_data: dict[str, any], location_mappings: dict[int, pathlib.Path] | None = None
    ) -> TrackMetadata:
        """Convert local SQLite track data to TrackMetadata format

        Args:
            track_data: Track data from Serato SQLite database
            location_mappings: Optional mapping of location_id to base file path
        """
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
        # Construct full path from location_id + portable_id
        if track_data.get("portable_id") and track_data.get("location_id"):
            portable_id = str(track_data["portable_id"])
            location_id = track_data["location_id"]

            # Try to get base path from location mappings
            if location_mappings and location_id in location_mappings:
                base_path = location_mappings[location_id]
                full_path = base_path / portable_id
                track_metadata["filename"] = str(full_path)
            else:
                # Fallback: just use portable_id as-is
                track_metadata["filename"] = portable_id
                logging.warning(
                    "No location mapping for location_id=%s, using portable_id as-is: %s",
                    location_id,
                    portable_id,
                )
        elif track_data.get("file_name"):
            # Fallback to just filename if no portable_id
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

    async def _get_all_library_database_paths(self) -> list[pathlib.Path]:
        """Get all Serato library database paths (auto-discovered)

        Returns list of paths to root.sqlite or location.sqlite files
        for querying library/crates.
        """
        if not self.handler:
            return []

        # Auto-discover all library database paths from location_connections
        return await self.handler.get_library_database_paths()

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

            # Auto-discover all library database paths
            db_paths = await self._get_all_library_database_paths()
            if not db_paths:
                logging.warning("No Serato 4 library databases found")
                return False

            # Get query scope configuration
            scope = self.config.cparser.value(
                "serato4/artist_query_scope", defaultValue="entire_library"
            )

            if scope == "selected_playlists":
                # Check selected crates across all libraries
                return await self._has_tracks_in_selected_playlists(artist_name, db_paths)

            # Check entire library across all library databases
            for db_path in db_paths:
                if await self._has_tracks_in_entire_library(artist_name, db_path):
                    logging.debug("Found artist '%s' in library: %s", artist_name, db_path)
                    return True
            return False

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.exception(
                "Failed to query Serato 4 library for artist %s: %s", artist_name, err
            )
            return False

    async def _has_tracks_in_selected_playlists(
        self, artist_name: str, db_paths: list[pathlib.Path]
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

        # Check each library database
        for db_path in db_paths:
            # Create reader for this library and check for artist
            reader = Serato4RootReader(db_path)
            if await reader.has_artist_in_crates(artist_name, crate_names):
                return True

        return False

    async def _has_tracks_in_entire_library(  # pylint: disable=no-self-use
        self, artist_name: str, db_path: pathlib.Path
    ) -> bool:
        """Check for artist tracks in entire library database

        Uses the asset table in root.sqlite or location.sqlite to search the library.

        Args:
            artist_name: Artist name to search for
            db_path: Path to library database file (root.sqlite or location.sqlite)

        Returns:
            True if artist found in this library, False otherwise
        """
        try:

            async def _query_library() -> bool:
                async with aiosqlite.connect(db_path) as connection:
                    connection.row_factory = aiosqlite.Row

                    # Search asset table for artist (case-insensitive)
                    query = """
                        SELECT DISTINCT 1
                        FROM asset
                        WHERE LOWER(artist) LIKE LOWER(?)
                        LIMIT 1
                    """

                    params = [f"%{artist_name}%"]
                    cursor = await connection.execute(query, params)
                    row = await cursor.fetchone()

                    return row is not None

            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_query_library)
        except sqlite3.Error as exc:
            logging.error(
                "Failed to query library at %s for artist %s: %s", db_path, artist_name, exc
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
        # Serato 4 plugin uses auto-detection for all libraries - no manual configuration needed

    def on_add_additional_lib_button(self):
        """Add additional library button clicked action"""
        if not self.qwidget:
            logging.error("UI widget not initialized")
            return

        library_widgets = self.uihelp.find_tab_by_identifier(
            self.qwidget, "serato_artist_scope_combo"
        )
        if not library_widgets:
            logging.error("Library tab not found")
            return

        # DEPRECATED: Libraries are now auto-discovered from Serato database
        logging.info(
            "Additional library paths are auto-discovered - manual configuration not needed"
        )

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

            # Additional library paths are now auto-discovered
            # UI shows informational message, no loading needed

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
                "serato4/selected_playlists", library_widgets.serato_playlists_lineedit.text()
            )

            # Additional library paths are now auto-discovered, no need to save
