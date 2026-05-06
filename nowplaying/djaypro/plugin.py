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
- TSAF binary serialization format (djay Pro proprietary)
- 20-byte header: "TSAF" magic + version + counts
- Typed value stream: value appears BEFORE its key
- Type codes:
    0x00  end-of-object marker
    0x05  2-byte skip marker
    0x08  null-terminated UTF-8 string
    0x0b  array (4-byte-aligned int32 count, then elements)
    0x13  float32 (4-byte-aligned) — macOS only
    0x14  float64 (8-byte-aligned) — Windows only
    0x15  binary blob: 4-byte-aligned uint32 length, then raw bytes
          (macOS: CFURLBookmarkData stored in the urlBookmarkData field)
    0x21  string wrapper: skip 1 sub-type byte, read string, skip trailing 0x00
    0x2b  nested object whose fields merge into the parent object
    0x30  timestamp float64 (8-byte-aligned)
- File paths: Windows stores plain file:// URIs in sourceURIs; macOS stores
  plain file:// URIs for direct-access files and CFURLBookmarkData (via
  mac-alias, optional) in urlBookmarkData for library/network-volume tracks

Database Location:
- macOS: ~/Music/djay/djay Media Library.djayMediaLibrary/MediaLibrary.db
- Windows: %USERPROFILE%/Music/djay/djay Media Library/MediaLibrary.db
"""

import asyncio
import logging
import pathlib
import sqlite3
import threading
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

import nowplaying.djaypro.tsaf
import nowplaying.utils.sqlite
from nowplaying.exceptions import PluginVerifyError
from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.uihelp


_WAL_DEBOUNCE_SECONDS = 0.3


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
        self._wal_timer: threading.Timer | None = None
        self._wal_timer_lock = threading.Lock()
        self.metadata: TrackMetadata = {
            "artist": None,
            "title": None,
            "album": None,
            "filename": None,
            "bpm": None,
            "duration": None,
        }
        self._reset_meta()

    @classmethod
    def get_path_keys(cls) -> frozenset[str]:
        return frozenset({"djaypro/directory"})

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
                self.config.cparser.setValue("settings/input", "djaypro")
                self.config.cparser.setValue("djaypro/directory", str(djaypro_dir))
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

        # Check if directory exists before trying to watch it
        if not pathlib.Path(self.djaypro_dir).exists():
            logging.error("djay Pro directory does not exist: %s", self.djaypro_dir)
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
        self._check_for_new_track()

    def _fs_event(self, event):
        """File system event handler - called from watchdog thread"""
        if event.is_directory:
            return

        filename = event.src_path

        if filename.endswith("NowPlaying.txt"):
            self._check_for_new_track()
            return

        if not filename.endswith("MediaLibrary.db-wal"):
            return

        # On Windows, djay Pro writes analysis rows first then historySessionItems
        # in a separate transaction.  Debounce so we query after both land.
        with self._wal_timer_lock:
            if self._wal_timer is not None:
                self._wal_timer.cancel()
            self._wal_timer = threading.Timer(_WAL_DEBOUNCE_SECONDS, self._wal_timer_fired)
            self._wal_timer.daemon = True
            self._wal_timer.start()

    def _wal_timer_fired(self):
        """Called by the debounce timer; clears the timer reference then checks."""
        with self._wal_timer_lock:
            self._wal_timer = None
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

        records = self._query_recent_history(dbfile, limit=1)
        if not records:
            return

        track_data = records[0]
        if not (
            self.metadata.get("artist") != track_data["artist"]
            or self.metadata.get("title") != track_data["title"]
        ):
            return

        # New track detected — look up filename if the history blob didn't include it
        if not track_data["filename"]:
            t_artist = track_data["artist"]
            t_title = track_data["title"]
            if isinstance(t_artist, str) and isinstance(t_title, str):
                filename = self._get_filename_from_db(t_artist, t_title)
                if filename:
                    track_data["filename"] = filename

        new_meta: TrackMetadata = {
            "artist": track_data["artist"],
            "title": track_data["title"],
            "album": track_data["album"],
            "filename": track_data["filename"],
            "bpm": track_data["bpm"],
            "duration": track_data["duration"],
        }
        if isinstance(track_data.get("isrc"), str):
            new_meta["isrc"] = [track_data["isrc"]]
        self.metadata = new_meta
        logging.info(
            "New track detected: %s - %s%s%s%s%s",
            track_data["artist"],
            track_data["title"],
            f" (BPM: {track_data['bpm']})" if track_data["bpm"] else "",
            f" [{track_data['album']}]" if track_data["album"] else "",
            f" - {track_data['filename']}" if track_data["filename"] else "",
            f" ISRC:{track_data['isrc']}" if track_data.get("isrc") else "",
        )

    def _read_nowplaying_file(self):  # pylint: disable=too-many-locals,too-many-branches
        """Read NowPlaying.txt file for current track (macOS)"""
        nowplaying_file = pathlib.Path(self.djaypro_dir).joinpath("NowPlaying.txt")

        if not nowplaying_file.exists():
            return

        # Try UTF-8 first (macOS), then UTF-16 (Windows)
        content = None
        for encoding in ["utf-8", "utf-16"]:
            try:
                with open(nowplaying_file, encoding=encoding) as file:
                    content = file.read().strip()
                if content:
                    break
            except (UnicodeDecodeError, OSError):
                continue

        if not content:
            return

        # Parse line by line
        track_data = {}
        for line in content.split("\n"):
            line = line.strip()
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip().lower()
                value = value.strip()
                if value and value != "N/A":
                    track_data[key] = value

        artist = track_data.get("artist")
        title = track_data.get("title")
        album = track_data.get("album")
        time_str = track_data.get("time")

        if not artist or not title:
            return

        # Convert time to duration in seconds (format: MM:SS)
        duration = None
        if time_str:
            try:
                time_parts = time_str.split(":")
                if len(time_parts) == 2:
                    minutes, seconds = time_parts
                    duration = int(minutes) * 60 + int(seconds)
            except (ValueError, IndexError):
                pass

        # Check if this is a new track
        if self.metadata.get("artist") != artist or self.metadata.get("title") != title:
            # Supplement NowPlaying.txt with database lookups
            filename = self._get_filename_from_db(artist, title)
            isrc = self._get_isrc_from_db(artist, title)

            new_meta: TrackMetadata = {
                "artist": artist,
                "title": title,
                "album": album,
                "filename": filename,
                "bpm": None,
                "duration": duration,
            }
            if isrc:
                new_meta["isrc"] = [isrc]
            self.metadata = new_meta

            logging.info(
                "New track detected: %s - %s%s%s%s%s",
                artist,
                title,
                f" [{album}]" if album else "",
                f" ({time_str})" if time_str else "",
                f" - {filename}" if filename else " (no filename found)",
                f" ISRC:{isrc}" if isrc else "",
            )

    @staticmethod
    def _query_recent_history(dbfile: pathlib.Path, limit: int = 20) -> list[dict]:
        """Return parsed metadata dicts for the most recent historySessionItems.

        Results are ordered newest-first.  Blobs that fail to parse are
        silently skipped so callers always get a clean list of dicts.
        """

        def query_db():
            records = []
            with nowplaying.utils.sqlite.sqlite_connection(str(dbfile), timeout=1) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    "SELECT data FROM database2 "
                    "WHERE collection='historySessionItems' "
                    "ORDER BY rowid DESC LIMIT ?",
                    (limit,),
                )
                for (blob,) in cursor:
                    parsed = nowplaying.djaypro.tsaf.parse_blob(blob)
                    if parsed.get("title"):
                        records.append(parsed)
            return records

        try:
            return nowplaying.utils.sqlite.retry_sqlite_operation(query_db)
        except (sqlite3.OperationalError, FileNotFoundError):
            return []

    def _get_isrc_from_db(self, artist: str, title: str) -> str | None:
        """Return the ISRC for the track by scanning recent historySessionItems.

        The most recently added history entry is almost always the currently
        playing track, so we scan from the end and stop as soon as we find a
        matching artist/title pair.  Scanning is bounded to 20 rows to keep it
        fast even for large history tables.
        """
        dbfile = self._get_db_path()
        if not dbfile:
            return None

        artist_lower = artist.strip().lower()
        title_lower = title.strip().lower()

        for parsed in self._query_recent_history(dbfile, limit=20):
            p_artist = parsed.get("artist")
            p_title = parsed.get("title")
            if (
                isinstance(p_artist, str)
                and isinstance(p_title, str)
                and p_artist.strip().lower() == artist_lower
                and p_title.strip().lower() == title_lower
            ):
                return parsed.get("isrc")  # type: ignore[return-value]
        return None

    def _get_filename_from_db(self, artist: str, title: str) -> str | None:
        """Get filename from database by querying localMediaItemLocations"""
        dbfile = pathlib.Path(self.djaypro_dir).joinpath("MediaLibrary.db")
        if not dbfile.exists():
            return None

        def query_db():
            with nowplaying.utils.sqlite.sqlite_connection(
                str(dbfile), timeout=1, row_factory=sqlite3.Row
            ) as connection:
                cursor = connection.cursor()
                filename = self._get_filename_for_track(cursor, artist, title)
                return filename

        try:
            return nowplaying.utils.sqlite.retry_sqlite_operation(query_db)
        except (sqlite3.OperationalError, FileNotFoundError):
            return None

    @staticmethod
    def _get_filename_for_track(cursor, artist: str, title: str) -> str | None:
        """Query localMediaItemLocations collection for file path"""
        try:
            cursor.execute("SELECT data FROM database2 WHERE collection='localMediaItemLocations'")

            # Iterate the cursor lazily — fetchall() would load the whole library
            # into memory before we even start comparing.
            for row in cursor:
                blob_data = row[0]
                parsed = nowplaying.djaypro.tsaf.parse_blob(blob_data)

                # Case-insensitive, whitespace-normalized comparison
                artist_norm = artist.strip().lower() if artist else ""
                title_norm = title.strip().lower() if title else ""
                if not (artist_norm and title_norm and parsed["artist"] and parsed["title"]):
                    continue
                if (
                    parsed["artist"].strip().lower() == artist_norm
                    and parsed["title"].strip().lower() == title_norm
                ):
                    if parsed["filename"]:
                        return parsed["filename"]

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Error searching localMediaItemLocations: %s", err)

        return None

    async def stop(self):
        """stop the watcher"""
        with self._wal_timer_lock:
            if self._wal_timer is not None:
                self._wal_timer.cancel()
                self._wal_timer = None
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

    @staticmethod
    def _has_tracks_in_entire_library(dbfile: str, artist_name: str) -> bool:
        """Scan mediaItemTitleIDs TSAF blobs for a case-insensitive artist match."""
        artist_lower = artist_name.strip().lower()
        if not artist_lower:
            return False

        with nowplaying.utils.sqlite.sqlite_connection(str(dbfile), timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data FROM database2 WHERE collection='mediaItemTitleIDs'")
            for (blob,) in cursor:
                parsed = nowplaying.djaypro.tsaf.parse_blob(blob)
                raw_artist = parsed.get("artist")
                if isinstance(raw_artist, str) and raw_artist.strip().lower() == artist_lower:
                    return True
        return False

    @staticmethod
    def _has_tracks_in_playlists(dbfile: str, artist_name: str, playlist_names: list[str]) -> bool:
        """Scan mediaItemTitleIDs blobs for tracks in selected playlists.

        Uses view_mediaItemPlaylistView_map and view_mediaItemPlaylistView_page
        to restrict the search to tracks belonging to the given playlists.
        Falls back to False (rather than the entire library) when the view
        tables are absent, which happens when no playlists are configured.
        """
        artist_lower = artist_name.strip().lower()
        if not artist_lower or not playlist_names:
            return False

        # Use a single-playlist parameterised query (no dynamic SQL) to satisfy
        # the SQL injection scanner.  The IN clause cannot be expressed with a
        # fixed number of placeholders, so we issue one query per playlist name
        # instead — playlist counts are always small in practice.
        static_sql = (
            "SELECT d.data"
            " FROM database2 d"
            " JOIN view_mediaItemPlaylistView_map m"
            "   ON CAST(m.rowid AS INTEGER) = d.rowid"
            " JOIN view_mediaItemPlaylistView_page p"
            "   ON p.pageKey = m.pageKey"
            ' WHERE p."group" = ?'
            "   AND d.collection = 'mediaItemTitleIDs'"
        )
        with nowplaying.utils.sqlite.sqlite_connection(str(dbfile), timeout=5) as conn:
            cursor = conn.cursor()
            for playlist_name in playlist_names:
                try:
                    cursor.execute(static_sql, (playlist_name,))
                except sqlite3.OperationalError:
                    # View tables don't exist (no playlists configured in djay Pro)
                    return False
                for (blob,) in cursor:
                    parsed = nowplaying.djaypro.tsaf.parse_blob(blob)
                    raw_artist = parsed.get("artist")
                    if isinstance(raw_artist, str) and raw_artist.strip().lower() == artist_lower:
                        return True
        return False

    def _get_db_path(self) -> pathlib.Path | None:
        """Return the MediaLibrary.db path, or None if not found.

        Checks self.djaypro_dir first (set by setup_watcher), then falls back
        to the configured directory so callers that run before the watcher
        starts still get a valid path.
        """
        if self.djaypro_dir:
            dbfile = pathlib.Path(self.djaypro_dir).joinpath("MediaLibrary.db")
            if dbfile.exists():
                return dbfile
        configured = self.config.cparser.value("djaypro/directory", defaultValue="")
        if configured:
            dbfile = pathlib.Path(configured).joinpath("MediaLibrary.db")
            if dbfile.exists():
                return dbfile
        return None

    async def has_tracks_by_artist(self, artist_name: str) -> bool:
        """Check if the djay Pro library contains any tracks by the given artist."""
        dbfile = self._get_db_path()
        if not dbfile:
            return False

        scope = self.config.cparser.value(
            "djaypro/artist_query_scope", defaultValue="entire_library"
        )

        try:
            if scope == "selected_playlists":
                raw_playlists = self.config.cparser.value(
                    "djaypro/selected_playlists", defaultValue=""
                )
                playlist_names = [p.strip() for p in raw_playlists.split(",") if p.strip()]
                if not playlist_names:
                    return False
                return await asyncio.to_thread(
                    self._has_tracks_in_playlists, str(dbfile), artist_name, playlist_names
                )

            return await asyncio.to_thread(
                self._has_tracks_in_entire_library, str(dbfile), artist_name
            )

        except (sqlite3.OperationalError, FileNotFoundError, OSError) as err:
            logging.error("Failed to query djay Pro library for artist %s: %s", artist_name, err)
            return False

    @staticmethod
    def _get_available_playlists_sync(dbfile: str) -> list[str]:
        """Return sorted list of playlist names from view_mediaItemPlaylistView_page."""
        with nowplaying.utils.sqlite.sqlite_connection(str(dbfile), timeout=5) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    'SELECT DISTINCT "group" FROM view_mediaItemPlaylistView_page'
                    ' WHERE "group" IS NOT NULL AND "group" != \'\''
                    ' ORDER BY "group"'
                )
                return [row[0] for row in cursor.fetchall()]
            except sqlite3.OperationalError:
                # View table absent (no playlists configured)
                return []

    async def get_available_playlists(self) -> list[str]:
        """Return sorted list of playlist names from the djay Pro library."""
        dbfile = self._get_db_path()
        if not dbfile:
            return []
        try:
            return await asyncio.to_thread(self._get_available_playlists_sync, str(dbfile))
        except (sqlite3.OperationalError, FileNotFoundError, OSError) as err:
            logging.error("Failed to list djay Pro playlists: %s", err)
            return []

    def desc_settingsui(self, qwidget: "QWidget") -> None:
        """provide a description for the plugins page"""
        qwidget.setText(
            "djay Pro is DJ software from Algoriddim. This plugin supports both "
            "macOS and Windows versions through database monitoring."
        )

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

        scope = self.config.cparser.value(
            "djaypro/artist_query_scope", defaultValue="entire_library"
        )
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

        self.config.cparser.setValue(
            "djaypro/selected_playlists", qwidget.djaypro_playlists_lineedit.text()
        )

    def on_djaypro_dir_button(self):
        """open file browser to set djay Pro directory"""
        startdir = self.config.cparser.value("djaypro/directory")
        if not startdir:
            # Use same base path as defaults() and install(): Music/djay
            music_dir = self.config.userdocs.parent.joinpath("Music")
            startdir = str(music_dir.joinpath("djay"))
        if dirname := QFileDialog.getExistingDirectory(self.qwidget, "Select directory", startdir):
            self.qwidget.dir_lineedit.setText(dirname)
