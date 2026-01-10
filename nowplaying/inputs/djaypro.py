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

Common Fields in Blobs:
- title: Track title
- artist: Artist name
- originSourceID: Source (e.g., 'explorer' for local files, streaming service names)
- file:///: Local file path (URL-encoded)

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

import aiosqlite
from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

import nowplaying.utils
from nowplaying.exceptions import PluginVerifyError
from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.uihelp


class Plugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
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
        self.tasks = set()
        self._reset_meta()

    def install(self) -> bool:
        """locate djay Pro database directory"""
        # Check for djay Pro Media Library location
        # macOS: ~/Music/djay/djay Media Library.djayMediaLibrary/
        # Windows: %USERPROFILE%/Music/djay/djay Media Library/
        music_dir = self.config.userdocs.parent.joinpath("Music")
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
        """set up a custom watch on the djay Pro directory so meta info
        can update on change"""

        djaypro_dir = self.config.cparser.value(configkey)
        if not self.djaypro_dir or self.djaypro_dir != djaypro_dir:
            await self.stop()

        if self.observer:
            return

        self.djaypro_dir = djaypro_dir
        if not self.djaypro_dir:
            logging.error(
                "djay Pro Directory Path not configured/does not exist: %s", self.djaypro_dir
            )
            await asyncio.sleep(1)
            return

        logging.info("Watching for changes on %s", self.djaypro_dir)
        # Watch for changes to NowPlaying.txt
        self.event_handler = FileSystemEventHandler()
        self.event_handler.on_modified = self._fs_event
        self.event_handler.on_created = self._fs_event

        if self.config.cparser.value("quirks/pollingobserver", type=bool):
            polling_interval = self.config.cparser.value("quirks/pollinginterval", type=float)
            logging.debug("Using polling observer with %s second interval", polling_interval)
            self.observer = PollingObserver(timeout=polling_interval)
        else:
            logging.debug("Using fsevent observer")
            self.observer = Observer()
        self.observer.schedule(self.event_handler, self.djaypro_dir, recursive=False)
        self.observer.start()

    def _fs_event(self, event):
        if event.is_directory:
            return
        # Only process NowPlaying.txt changes
        if not event.src_path.endswith("NowPlaying.txt"):
            return

        # Read NowPlaying.txt for current track
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._read_nowplaying_file())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self._read_nowplaying_file())

    async def _read_nowplaying_file(self):
        """Read NowPlaying.txt file for current track information

        File encoding: UTF-8 (macOS) or UTF-16 (Windows)
        Format:
        Title: Vorfreude
        Artist: Thomas Schumacher
        Album: N/A
        Time: 09:45
        """
        nowplaying_file = pathlib.Path(self.djaypro_dir).joinpath("NowPlaying.txt")

        if not nowplaying_file.exists():
            logging.debug("NowPlaying.txt not found")
            return

        # Retry logic in case file is being written
        max_retries = 3
        retry_delay = 0.1  # 100ms
        content = None

        # Try UTF-8 first (macOS), then UTF-16 (Windows)
        encodings = ['utf-8', 'utf-16']

        for attempt in range(max_retries):
            for encoding in encodings:
                try:
                    with open(nowplaying_file, 'r', encoding=encoding) as file:
                        content = file.read().strip()

                    if not content:
                        return

                    # Successfully read the file
                    break

                except UnicodeDecodeError:
                    # Try next encoding
                    continue
                except OSError as err:
                    if attempt < max_retries - 1:
                        # File might be locked, wait and retry
                        await asyncio.sleep(retry_delay)
                        break  # Break encoding loop to retry
                    else:
                        logging.error("Failed to read NowPlaying.txt after %d attempts: %s", max_retries, err)
                        return

            # If we got content, break out of retry loop
            if content:
                break

        if not content:
            logging.error("Failed to read NowPlaying.txt with any supported encoding")
            return

        try:

            # Parse line by line
            lines = content.split('\n')
            track_data = {}

            for line in lines:
                line = line.strip()
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip().lower()
                    value = value.strip()

                    # Skip N/A values
                    if value and value != 'N/A':
                        track_data[key] = value

            artist = track_data.get('artist')
            title = track_data.get('title')
            album = track_data.get('album')
            time_str = track_data.get('time')

            if not artist or not title:
                logging.warning("Missing artist or title in NowPlaying.txt")
                return

            # Convert time to duration in seconds if present (format: MM:SS)
            duration = None
            if time_str:
                try:
                    time_parts = time_str.split(':')
                    if len(time_parts) == 2:
                        minutes, seconds = time_parts
                        duration = int(minutes) * 60 + int(seconds)
                except (ValueError, IndexError):
                    logging.debug("Failed to parse time: %s", time_str)

            # Check if this is a new track
            if (self.metadata.get("artist") != artist or
                self.metadata.get("title") != title):

                # Try to get filename from database
                filename = await self._get_filename_from_db(artist, title)

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

        except (OSError, UnicodeDecodeError) as err:
            logging.error("Failed to read NowPlaying.txt: %s", err)

    @staticmethod
    def _parse_blob(blob_data: bytes) -> dict[str, str | None]:
        """Parse binary blob data to extract track metadata

        djay Pro uses TSAF format. Extract strings by looking for sequences
        of printable ASCII/UTF-8 characters terminated by null bytes.
        """
        try:
            # Extract all null-terminated strings from the blob
            decoded = []
            i = 0
            while i < len(blob_data) - 1:
                # Look for printable ASCII start (common case)
                if 32 <= blob_data[i] <= 126:
                    string_start = i
                    # Collect until null byte or non-printable
                    while i < len(blob_data) and blob_data[i] != 0 and blob_data[i] >= 32:
                        i += 1

                    # Extract the string
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
            # Also look for file:// URLs directly in the decoded strings
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
                    # BPM might be a number, try to parse
                    try:
                        bpm = float(decoded[i - 1])
                    except (ValueError, IndexError):
                        pass
                elif string == 'duration' and i > 0:
                    # Duration might be in seconds
                    try:
                        duration = int(float(decoded[i - 1]))
                    except (ValueError, IndexError):
                        pass
                elif string.startswith('file:///') and len(string) > 8:
                    # Found a file URL (ignore bare "file:///" entries)
                    # Decode URL-encoding and remove file:// prefix
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

    async def _get_filename_from_db(self, artist: str, title: str) -> str | None:
        """Get filename from database by querying localMediaItemLocations

        Args:
            artist: Artist name
            title: Track title

        Returns:
            File path if found, None otherwise
        """
        dbfile = pathlib.Path(self.djaypro_dir).joinpath("MediaLibrary.db")
        if not dbfile.exists():
            logging.debug("MediaLibrary.db not found")
            return None

        try:
            async with aiosqlite.connect(f"file:{dbfile}?mode=ro", uri=True, timeout=1.0) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()
                filename = await self._get_filename_for_track(cursor, artist, title)
                await connection.commit()
                return filename
        except (sqlite3.OperationalError, FileNotFoundError) as err:
            logging.debug("Failed to query database for filename: %s", err)
            return None

    async def _get_filename_for_track(self, cursor, artist: str, title: str) -> str | None:
        """Query localMediaItemLocations collection for file path

        Args:
            cursor: Database cursor (already connected)
            artist: Artist name to search for
            title: Track title to search for

        Returns:
            File path string if found, None otherwise
        """
        try:
            # Query all localMediaItemLocations entries
            await cursor.execute(
                "SELECT data FROM database2 WHERE collection='localMediaItemLocations'"
            )
            rows = await cursor.fetchall()

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

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.error("Failed to query database for filename: %s", err)

        return None

    async def _check_for_new_track(self):
        """Check database for new tracks in history"""
        dbfile = pathlib.Path(self.djaypro_dir).joinpath("MediaLibrary.db")
        if not dbfile.exists():
            return

        try:
            async with aiosqlite.connect(f"file:{dbfile}?mode=ro", uri=True, timeout=1.0) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()

                # Query for latest history item
                await cursor.execute(
                    "SELECT rowid, data FROM database2 WHERE collection='historySessionItems' ORDER BY rowid DESC LIMIT 1"
                )
                row = await cursor.fetchone()
                await connection.commit()

                if row:
                    track_data = self._parse_blob(row["data"])
                    if track_data["artist"] and track_data["title"]:
                        # Check if this is a new track
                        if (self.metadata.get("artist") != track_data["artist"]
                            or self.metadata.get("title") != track_data["title"]):

                            # If filename not in history blob, try to get it from localMediaItemLocations
                            if not track_data["filename"]:
                                filename = await self._get_filename_for_track(
                                    cursor, track_data["artist"], track_data["title"]
                                )
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
        except (sqlite3.OperationalError, FileNotFoundError) as err:
            logging.debug("Failed to check for new track: %s", err)


    async def start(self):
        """setup the watcher to run in a separate thread"""
        await self.setup_watcher()

    async def getplayingtrack(self) -> TrackMetadata:
        """wrapper to call getplayingtrack"""

        # just in case called without calling start...
        await self.start()
        return self.metadata

    async def get_available_playlists(self):
        """Get list of all playlists from djay Pro database

        TODO: Implement based on actual Media.db playlist schema
        """
        dbfile = pathlib.Path(self.djaypro_dir).joinpath("Media.db")
        if not dbfile.exists():
            return []

        playlists = []

        try:
            async with aiosqlite.connect(dbfile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()

                # TODO: Replace with actual playlist query
                await cursor.execute("SELECT DISTINCT name FROM playlists")
                rows = await cursor.fetchall()
                playlists.extend(row["name"] for row in rows)

                await connection.commit()
        except (sqlite3.OperationalError, FileNotFoundError) as err:
            logging.error("Failed to get playlists from djay Pro database: %s", err)

        return sorted(playlists)

    async def getrandomtrack(self, playlist: str) -> str | None:
        """Get a random track from playlist

        TODO: Implement based on actual Media.db schema
        """
        dbfile = pathlib.Path(self.djaypro_dir).joinpath("Media.db")
        if not dbfile.exists():
            return None

        try:
            async with aiosqlite.connect(dbfile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()

                # TODO: Replace with actual query based on schema
                await cursor.execute(
                    "SELECT filename FROM playlist_tracks WHERE playlist_name=? ORDER BY random() LIMIT 1",
                    (playlist,),
                )
                row = await cursor.fetchone()
                await connection.commit()

                if row:
                    return row["filename"]
        except (sqlite3.OperationalError, FileNotFoundError) as err:
            logging.error("Failed to get random track from djay Pro database: %s", err)

        return None

    async def stop(self):
        """stop the djay Pro plugin"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    async def has_tracks_by_artist(self, artist_name: str) -> bool:
        """Check if DJ has any tracks by the specified artist

        TODO: Implement based on actual Media.db schema
        """
        dbfile = pathlib.Path(self.djaypro_dir).joinpath("Media.db")
        if not dbfile.exists():
            return False

        scope = self.config.cparser.value(
            "djaypro/artist_query_scope", defaultValue="entire_library"
        )

        try:
            async with aiosqlite.connect(dbfile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()

                if scope == "selected_playlists":
                    result = await self._check_artist_in_playlists(cursor, artist_name)
                else:
                    result = await self._check_artist_in_library(cursor, artist_name)

                await connection.commit()
                return result

        except (sqlite3.OperationalError, FileNotFoundError) as err:
            logging.error("Failed to query djay Pro database for artist %s: %s", artist_name, err)
            return False

    async def _check_artist_in_playlists(self, cursor, artist_name: str) -> bool:
        """Check if artist exists in selected playlists

        TODO: Implement based on actual schema
        """
        playlist_names = self._get_selected_playlist_names()
        if not playlist_names:
            return False

        # TODO: Replace with actual query
        placeholders = ",".join("?" * len(playlist_names))
        sql = f"""
            SELECT COUNT(*) as count
            FROM tracks t
            JOIN playlist_tracks pt ON t.id = pt.track_id
            JOIN playlists p ON pt.playlist_id = p.id
            WHERE LOWER(t.artist) = LOWER(?) AND p.name IN ({placeholders})
        """
        params = [artist_name] + playlist_names
        await cursor.execute(sql, params)
        row = await cursor.fetchone()
        return row and row["count"] > 0

    @staticmethod
    async def _check_artist_in_library(cursor, artist_name: str) -> bool:
        """Check if artist exists in entire library

        TODO: Update table name based on actual schema
        """
        await cursor.execute(
            "SELECT COUNT(*) as count FROM tracks WHERE LOWER(artist) = LOWER(?)",
            (artist_name,),
        )
        row = await cursor.fetchone()
        return row["count"] > 0 if row else False

    def _get_selected_playlist_names(self) -> list[str]:
        """Get list of selected playlist names from config"""
        selected_playlists = self.config.cparser.value(
            "djaypro/selected_playlists", defaultValue=""
        )
        if not selected_playlists.strip():
            return []

        return [name.strip() for name in selected_playlists.split(",") if name.strip()]

    def on_djaypro_dir_button(self):
        """filename button clicked action"""
        if self.qwidget.dir_lineedit.text():
            startdir = self.qwidget.dir_lineedit.text()
        else:
            startdir = str(self.config.userdocs.joinpath("djay Pro"))
        if dirname := QFileDialog.getExistingDirectory(self.qwidget, "Select directory", startdir):
            self.qwidget.dir_lineedit.setText(dirname)

    def defaults(self, qsettings: "QSettings"):
        """(re-)set the default configuration values for this plugin"""
        # Default to Music/djay/djay Media Library.djayMediaLibrary
        music_dir = self.config.userdocs.parent.joinpath("Music")
        djaypro = music_dir.joinpath("djay", "djay Media Library.djayMediaLibrary")
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

        # Set artist query scope
        scope = self.config.cparser.value(
            "djaypro/artist_query_scope", defaultValue="entire_library"
        )
        if scope == "selected_playlists":
            qwidget.djaypro_artist_scope_combo.setCurrentText("Selected Playlists")
        else:
            qwidget.djaypro_artist_scope_combo.setCurrentText("Entire Library")

        # Load selected playlists
        qwidget.djaypro_playlists_lineedit.setText(
            self.config.cparser.value("djaypro/selected_playlists", defaultValue="")
        )

    def verify_settingsui(self, qwidget: "QWidget"):
        """verify settings are valid"""
        if not pathlib.Path(qwidget.dir_lineedit.text()).exists():
            raise PluginVerifyError(r"djay Pro directory must exist.")

    def save_settingsui(self, qwidget: "QWidget"):
        """take the settings page and save it"""
        configdir = qwidget.dir_lineedit.text()
        self.config.cparser.setValue("djaypro/directory", configdir)

        # Save artist query scope
        scope = (
            "selected_playlists"
            if qwidget.djaypro_artist_scope_combo.currentText() == "Selected Playlists"
            else "entire_library"
        )
        self.config.cparser.setValue("djaypro/artist_query_scope", scope)

        # Save selected playlists
        self.config.cparser.setValue(
            "djaypro/selected_playlists", qwidget.djaypro_playlists_lineedit.text()
        )

    def desc_settingsui(self, qwidget: "QWidget"):
        """description"""
        qwidget.setText("djay Pro is professional DJ software by Algoriddim for macOS, Windows, and iOS.")
