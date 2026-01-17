#!/usr/bin/env python3
"""djay Pro support

djay Pro Database Schema (MediaLibrary.db):

Main Tables:
- database2: Main storage table with binary blob data
  - rowid: Unique identifier
  - collection: Collection name (type of data)
  - data: Binary blob containing track/playlist information

Key Collections:
- historySessionItems: Play history with timestamps
- localMediaItemLocations: Track file paths and metadata

Data Format:
- Binary blobs containing UTF-8 strings
- Metadata structure: value appears BEFORE key in binary format
  Example: [artist_name][string 'artist'][title_name][string 'title']
- File paths stored as file:/// URLs (URL-encoded)

Database Location:
- macOS: ~/Music/djay/djay Media Library.djayMediaLibrary/MediaLibrary.db
- Windows: %USERPROFILE%/Music/djay/djay Media Library/MediaLibrary.db
"""

import asyncio
import logging
import pathlib
import sqlite3
import urllib.parse
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

import nowplaying.utils.sqlite
from nowplaying.exceptions import PluginVerifyError
from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.uihelp


class Plugin(InputPlugin):
    """handler for djay Pro"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "djay Pro"
        self.mixmode = "newest"
        self.event_handler = None
        self.observer = None
        self.djaypro_dir = ""
        self.metadata: TrackMetadata = {
            "artist": None,
            "title": None,
            "album": None,
            "filename": None,
            "bpm": None,
            "duration": None,
        }
        self._reset_meta()

    def install(self) -> bool:
        """locate djay Pro database directory"""
        music_dir = self.config.userdocs.parent.joinpath("Music")
        # Try macOS path first
        djaypro_dir = music_dir.joinpath("djay", "djay Media Library.djayMediaLibrary")

        if not djaypro_dir.exists():
            # Try Windows path
            djaypro_dir = music_dir.joinpath("djay", "djay Media Library")

        if djaypro_dir.exists():
            dbfile = djaypro_dir.joinpath("MediaLibrary.db")
            if dbfile.exists():
                self.config.cparser.value("settings/input", "djaypro")
                self.config.cparser.value("djaypro/directory", str(djaypro_dir))
                return True
        return False

    def _reset_meta(self):
        """reset the metadata"""
        self.metadata = {
            "artist": None,
            "title": None,
            "album": None,
            "filename": None,
            "bpm": None,
            "duration": None,
        }

    async def setup_watcher(self, configkey: str = "djaypro/directory"):
        """set up a custom watch on the djay Pro directory"""
        djaypro_dir = self.config.cparser.value(configkey)
        if not self.djaypro_dir or self.djaypro_dir != djaypro_dir:
            await self.stop()

        if self.observer:
            return

        self.djaypro_dir = djaypro_dir
        if not self.djaypro_dir:
            logging.error("djay Pro Directory Path not configured")
            await asyncio.sleep(1)
            return

        logging.info("Watching for changes on %s", self.djaypro_dir)
        # Watch for changes to NowPlaying.txt (macOS) or MediaLibrary.db-wal (Windows)
        self.event_handler = FileSystemEventHandler()
        self.event_handler.on_modified = self._fs_event
        self.event_handler.on_created = self._fs_event

        if self.config.cparser.value("quirks/pollingobserver", type=bool):
            polling_interval = self.config.cparser.value("quirks/pollinginterval", type=float)
            self.observer = PollingObserver(timeout=polling_interval)
        else:
            self.observer = Observer()
        self.observer.schedule(self.event_handler, self.djaypro_dir, recursive=False)
        self.observer.start()

    def _fs_event(self, event):
        """File system event handler - called from watchdog thread"""
        if event.is_directory:
            return

        # Log all file events for debugging
        filename = event.src_path
        logging.debug("File event: %s - %s", event.event_type, filename)

        # Only process specific files
        if not (filename.endswith("NowPlaying.txt") or filename.endswith("MediaLibrary.db-wal")):
            return

        logging.debug("Processing track change for: %s", filename)
        # Do synchronous work directly in this thread
        self._check_for_new_track()

    def _check_for_new_track(self):
        """Check for new track from NowPlaying.txt (macOS) or database (Windows)"""
        # Try NowPlaying.txt first (macOS)
        nowplaying_file = pathlib.Path(self.djaypro_dir).joinpath("NowPlaying.txt")
        if nowplaying_file.exists():
            self._read_nowplaying_file()
            return

        # Fall back to database polling (Windows)
        dbfile = pathlib.Path(self.djaypro_dir).joinpath("MediaLibrary.db")
        if not dbfile.exists():
            return

        def query_db():
            connection = sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True, timeout=1.0)
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()

            # Query for latest history item
            cursor.execute(
                "SELECT rowid, data FROM database2 WHERE collection='historySessionItems' ORDER BY rowid DESC LIMIT 1"
            )
            row = cursor.fetchone()

            if row:
                track_data = self._parse_blob(row["data"])
                if track_data["artist"] and track_data["title"]:
                    # Check if this is a new track
                    if (self.metadata.get("artist") != track_data["artist"]
                        or self.metadata.get("title") != track_data["title"]):

                        # If filename not in history blob, try to get it from localMediaItemLocations
                        if not track_data["filename"]:
                            filename = self._get_filename_for_track(cursor, track_data["artist"], track_data["title"])
                            if filename:
                                track_data["filename"] = filename

                        self.metadata = {
                            "artist": track_data["artist"],
                            "title": track_data["title"],
                            "album": track_data["album"],
                            "filename": track_data["filename"],
                            "bpm": track_data["bpm"],
                            "duration": track_data["duration"],
                        }
                        logging.info(
                            "New track detected: %s - %s%s%s%s",
                            track_data["artist"],
                            track_data["title"],
                            f" (BPM: {track_data['bpm']})" if track_data["bpm"] else "",
                            f" [{track_data['album']}]" if track_data["album"] else "",
                            f" - {track_data['filename']}" if track_data["filename"] else ""
                        )

            connection.close()

        try:
            nowplaying.utils.sqlite.retry_sqlite_operation(query_db)
        except (sqlite3.OperationalError, FileNotFoundError) as err:
            logging.debug("Failed to check for new track: %s", err)

    def _read_nowplaying_file(self):
        """Read NowPlaying.txt file for current track (macOS)"""
        nowplaying_file = pathlib.Path(self.djaypro_dir).joinpath("NowPlaying.txt")

        if not nowplaying_file.exists():
            return

        # Try UTF-8 first (macOS), then UTF-16 (Windows)
        content = None
        for encoding in ['utf-8', 'utf-16']:
            try:
                with open(nowplaying_file, 'r', encoding=encoding) as file:
                    content = file.read().strip()
                if content:
                    break
            except (UnicodeDecodeError, OSError):
                continue

        if not content:
            return

        # Parse line by line
        track_data = {}
        for line in content.split('\n'):
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                if value and value != 'N/A':
                    track_data[key] = value

        artist = track_data.get('artist')
        title = track_data.get('title')
        album = track_data.get('album')
        time_str = track_data.get('time')

        if not artist or not title:
            return

        # Convert time to duration in seconds (format: MM:SS)
        duration = None
        if time_str:
            try:
                time_parts = time_str.split(':')
                if len(time_parts) == 2:
                    minutes, seconds = time_parts
                    duration = int(minutes) * 60 + int(seconds)
            except (ValueError, IndexError):
                pass

        # Check if this is a new track
        if (self.metadata.get("artist") != artist or self.metadata.get("title") != title):
            # Try to get filename from database
            filename = self._get_filename_from_db(artist, title)

            self.metadata = {
                "artist": artist,
                "title": title,
                "album": album,
                "filename": filename,
                "bpm": None,
                "duration": duration,
            }

            logging.info(
                "New track detected: %s - %s%s%s%s",
                artist,
                title,
                f" [{album}]" if album else "",
                f" ({time_str})" if time_str else "",
                f" - {filename}" if filename else " (no filename found)"
            )

    def _get_filename_from_db(self, artist: str, title: str) -> str | None:
        """Get filename from database by querying localMediaItemLocations"""
        dbfile = pathlib.Path(self.djaypro_dir).joinpath("MediaLibrary.db")
        if not dbfile.exists():
            return None

        def query_db():
            connection = sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True, timeout=1.0)
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            filename = self._get_filename_for_track(cursor, artist, title)
            connection.close()
            return filename

        try:
            return nowplaying.utils.sqlite.retry_sqlite_operation(query_db)
        except (sqlite3.OperationalError, FileNotFoundError):
            return None

    def _get_filename_for_track(self, cursor, artist: str, title: str) -> str | None:
        """Query localMediaItemLocations collection for file path"""
        try:
            cursor.execute(
                "SELECT data FROM database2 WHERE collection='localMediaItemLocations'"
            )
            rows = cursor.fetchall()

            # Parse each blob looking for matching artist/title
            for row in rows:
                blob_data = row[0]
                parsed = self._parse_blob(blob_data)

                # Case-insensitive comparison
                if (parsed["artist"] and parsed["title"] and
                    parsed["artist"].lower() == artist.lower() and
                    parsed["title"].lower() == title.lower()):
                    if parsed["filename"]:
                        return parsed["filename"]

        except Exception:  # pylint: disable=broad-exception-caught
            pass

        return None

    @staticmethod
    def _parse_blob(blob_data: bytes) -> dict[str, str | None]:
        """Parse binary blob data to extract track metadata"""
        try:
            # Extract all null-terminated strings from the blob
            decoded = []
            i = 0
            while i < len(blob_data) - 1:
                # Look for printable ASCII start
                if 32 <= blob_data[i] <= 126:
                    string_start = i
                    while i < len(blob_data) and blob_data[i] != 0 and blob_data[i] >= 32:
                        i += 1

                    if i > string_start:
                        try:
                            string = blob_data[string_start:i].decode('utf-8', errors='ignore').strip()
                            if len(string) > 1:
                                decoded.append(string)
                        except UnicodeDecodeError:
                            pass
                else:
                    i += 1

            title = None
            artist = None
            album = None
            source = None
            file_path = None
            bpm = None
            duration = None

            # Parse metadata - value comes BEFORE key in blob format
            for i, string in enumerate(decoded):
                if string == 'title' and i > 0:
                    title = decoded[i - 1]
                elif string == 'artist' and i > 0:
                    artist = decoded[i - 1]
                elif string == 'album' and i > 0:
                    album = decoded[i - 1]
                elif string == 'originSourceID' and i > 0:
                    source = decoded[i - 1]
                elif string == 'bpm' and i > 0:
                    try:
                        bpm = float(decoded[i - 1])
                    except (ValueError, IndexError):
                        pass
                elif string == 'duration' and i > 0:
                    try:
                        duration = int(float(decoded[i - 1]))
                    except (ValueError, IndexError):
                        pass
                elif string.startswith('file:///') and len(string) > 8:
                    # Found a file URL (ignore bare "file:///" entries)
                    try:
                        file_path = urllib.parse.unquote(string)
                        if file_path.startswith('file:///'):
                            file_path = file_path[7:]  # Remove file:// prefix, keep leading /
                    except Exception:  # pylint: disable=broad-exception-caught
                        pass

            return {
                "artist": artist,
                "title": title,
                "album": album,
                "source": source,
                "filename": file_path,
                "bpm": str(bpm) if bpm else None,
                "duration": duration,
            }
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Failed to parse blob: %s", err)
            return {
                "artist": None,
                "title": None,
                "album": None,
                "source": None,
                "filename": None,
                "bpm": None,
                "duration": None,
            }

    async def stop(self):
        """stop the watcher"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    async def start(self):
        """setup the watcher"""
        await self.setup_watcher()

    async def getplayingtrack(self) -> TrackMetadata:
        """wrapper to call getplayingtrack"""
        await self.start()
        return self.metadata

    async def get_available_playlists(self):
        """Get list of all playlists - not implemented yet"""
        return []

    def defaults(self, qsettings: "QSettings"):
        """set the default configuration values for this plugin"""
        # Auto-detect djay Pro directory (macOS vs Windows)
        music_dir = self.config.userdocs.parent.joinpath("Music")
        # Try macOS path first
        djaypro = music_dir.joinpath("djay", "djay Media Library.djayMediaLibrary")
        if not djaypro.exists():
            # Try Windows path
            djaypro = music_dir.joinpath("djay", "djay Media Library")

        qsettings.setValue("djaypro/directory", str(djaypro))
        qsettings.setValue("djaypro/artist_query_scope", "entire_library")
        qsettings.setValue("djaypro/selected_playlists", "")

    def connect_settingsui(self, qwidget: "QWidget", uihelp: "nowplaying.uihelp.UIHelp"):
        """connect djay Pro button to filename picker"""
        self.qwidget = qwidget
        self.uihelp = uihelp
        qwidget.dir_button.clicked.connect(self.on_djaypro_dir_button)

    def load_settingsui(self, qwidget: "QWidget"):
        """draw the plugin's settings page"""
        qwidget.dir_lineedit.setText(self.config.cparser.value("djaypro/directory"))

        scope = self.config.cparser.value("djaypro/artist_query_scope", defaultValue="entire_library")
        if scope == "selected_playlists":
            qwidget.djaypro_artist_scope_combo.setCurrentText("Selected Playlists")
        else:
            qwidget.djaypro_artist_scope_combo.setCurrentText("Entire Library")

        qwidget.djaypro_playlists_lineedit.setText(
            self.config.cparser.value("djaypro/selected_playlists", defaultValue="")
        )

    def verify_settingsui(self, qwidget: "QWidget"):
        """verify settings are valid"""
        if not pathlib.Path(qwidget.dir_lineedit.text()).exists():
            raise PluginVerifyError(r"djay Pro directory must exist.")

    def save_settingsui(self, qwidget: "QWidget"):
        """save the settings page"""
        configdir = qwidget.dir_lineedit.text()
        self.config.cparser.setValue("djaypro/directory", configdir)

        if qwidget.djaypro_artist_scope_combo.currentText() == "Selected Playlists":
            self.config.cparser.setValue("djaypro/artist_query_scope", "selected_playlists")
        else:
            self.config.cparser.setValue("djaypro/artist_query_scope", "entire_library")

        self.config.cparser.setValue("djaypro/selected_playlists", qwidget.djaypro_playlists_lineedit.text())

    def on_djaypro_dir_button(self):
        """open file browser to set djay Pro directory"""
        startdir = self.config.cparser.value("djaypro/directory")
        if not startdir:
            startdir = str(self.config.userdocs.joinpath("djay Pro"))
        if dirname := QFileDialog.getExistingDirectory(self.qwidget, "Select directory", startdir):
            self.qwidget.dir_lineedit.setText(dirname)
