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
import struct
import sys
import threading
import urllib.parse
from typing import TYPE_CHECKING

try:
    from mac_alias import Bookmark as _MacAliasBookmark  # type: ignore[import-untyped]
    from mac_alias.bookmark import kBookmarkPath as _kBookmarkPath  # type: ignore[import-untyped]

    _HAS_MAC_ALIAS = True
except ImportError:
    _HAS_MAC_ALIAS = False

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

        def query_db():
            with nowplaying.utils.sqlite.sqlite_connection(
                str(dbfile), timeout=1, row_factory=sqlite3.Row
            ) as connection:
                cursor = connection.cursor()

                # Query for latest history item
                cursor.execute(
                    "SELECT rowid, data FROM database2 "
                    "WHERE collection='historySessionItems' ORDER BY rowid DESC LIMIT 1"
                )
                row = cursor.fetchone()

                if not row:
                    return

                track_data = self._parse_blob(row["data"])

                # Only require title - metadata extraction will handle the rest
                if track_data["title"]:
                    # Check if this is a new track
                    if (
                        self.metadata.get("artist") != track_data["artist"]
                        or self.metadata.get("title") != track_data["title"]
                    ):
                        # If filename not in history blob, try to get it from
                        # localMediaItemLocations
                        if not track_data["filename"]:
                            t_artist = track_data["artist"]
                            t_title = track_data["title"]
                            if isinstance(t_artist, str) and isinstance(t_title, str):
                                filename = self._get_filename_for_track(cursor, t_artist, t_title)
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

        try:
            nowplaying.utils.sqlite.retry_sqlite_operation(query_db)
        except (sqlite3.OperationalError, FileNotFoundError) as err:
            logging.debug("Failed to query database: %s", err)

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

    def _get_isrc_from_db(self, artist: str, title: str) -> str | None:
        """Return the ISRC for the track by scanning recent historySessionItems.

        The most recently added history entry is almost always the currently
        playing track, so we scan from the end and stop as soon as we find a
        matching artist/title pair.  Scanning is bounded to 20 rows to keep it
        fast even for large history tables.
        """
        dbfile = pathlib.Path(self.djaypro_dir).joinpath("MediaLibrary.db")
        if not dbfile.exists():
            return None

        artist_lower = artist.strip().lower()
        title_lower = title.strip().lower()

        def query_db():
            with nowplaying.utils.sqlite.sqlite_connection(
                str(dbfile), timeout=1
            ) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    "SELECT data FROM database2 "
                    "WHERE collection='historySessionItems' "
                    "ORDER BY rowid DESC LIMIT 20"
                )
                for (blob,) in cursor:
                    parsed = self._parse_blob(blob)
                    p_artist = parsed.get("artist")
                    p_title = parsed.get("title")
                    if (
                        isinstance(p_artist, str)
                        and isinstance(p_title, str)
                        and p_artist.strip().lower() == artist_lower
                        and p_title.strip().lower() == title_lower
                    ):
                        return parsed.get("isrc")
                return None

        try:
            return nowplaying.utils.sqlite.retry_sqlite_operation(query_db)
        except (sqlite3.OperationalError, FileNotFoundError):
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

    def _get_filename_for_track(self, cursor, artist: str, title: str) -> str | None:
        """Query localMediaItemLocations collection for file path"""
        try:
            cursor.execute("SELECT data FROM database2 WHERE collection='localMediaItemLocations'")

            # Iterate the cursor lazily — fetchall() would load the whole library
            # into memory before we even start comparing.
            for row in cursor:
                blob_data = row[0]
                parsed = self._parse_blob(blob_data)

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

    @staticmethod
    def _parse_tsaf(blob: bytes) -> dict:  # pylint: disable=too-many-branches,too-many-statements
        """Deserialize a TSAF binary blob from the djay Pro MediaLibrary database.

        Returns a flat dict of all fields found.  Nested 0x2b objects have
        their fields merged into the parent; 0x0b array elements are stored
        as lists (file:// strings are later resolved to a 'filename' key by
        _parse_blob).
        """
        if len(blob) < 20 or blob[:4] != b"TSAF":
            return {}

        pos = 20  # skip 20-byte header

        def read_string() -> str:
            nonlocal pos
            end = blob.index(b"\x00", pos)
            s = blob[pos:end].decode("utf-8", errors="replace")
            pos = end + 1
            return s

        def read_float32() -> float:
            nonlocal pos
            rem = pos % 4
            if rem:
                pos += 4 - rem
            val = struct.unpack_from("<f", blob, pos)[0]
            pos += 4
            return val

        def read_float64() -> float:
            nonlocal pos
            rem = pos % 8
            if rem:
                pos += 8 - rem
            val = struct.unpack_from("<d", blob, pos)[0]
            pos += 8
            return val

        def _merge_list_into(target: dict, items: list) -> None:
            """Merge dict items from a keyless array into *target* (first-seen wins)."""
            for item in items:
                if isinstance(item, dict):
                    for k, v in item.items():
                        if v is not None and k not in target:
                            target[k] = v

        def read_array_element() -> object:
            nonlocal pos
            if pos >= len(blob):
                return None
            tc = blob[pos]
            pos += 1
            if tc == 0x2B:
                return parse_object()
            if tc == 0x21:
                if pos < len(blob):
                    pos += 1  # skip sub-type byte
                s = read_string()
                if pos < len(blob) and blob[pos] == 0x00:
                    pos += 1  # skip trailing null
                return s
            if tc == 0x08:
                return read_string()
            return None

        def parse_object() -> dict:  # pylint: disable=too-many-branches,too-many-statements
            nonlocal pos
            result: dict = {}

            # class name (discard)
            if pos >= len(blob) or blob[pos] != 0x08:
                return result
            pos += 1
            read_string()

            # Detect obj_id: a string immediately followed by 0x05 is an
            # object identity field, not a named field.
            local_max: int | None = None
            if pos < len(blob) and blob[pos] == 0x08:
                save_pos = pos
                pos += 1
                read_string()  # candidate obj_id (discard)
                if pos < len(blob) and blob[pos] == 0x05:
                    pos += 1
                    local_max = blob[pos]
                    pos += 1
                else:
                    pos = save_pos  # not an obj_id – rewind

            fields_read = 0
            while pos < len(blob):
                if local_max is not None and fields_read >= local_max:
                    break

                peek = blob[pos]

                if peek == 0x00:
                    # Distinguish null-value (0x00 followed by key marker 0x08)
                    # from end-of-object (0x00 followed by anything else).
                    if pos + 1 < len(blob) and blob[pos + 1] == 0x08:
                        pos += 1  # null-value type — consume and fall through to key read
                        value = None
                        if pos < len(blob) and blob[pos] == 0x08:
                            pos += 1
                            key = read_string()
                            result[key] = value
                            fields_read += 1
                        continue
                    pos += 1  # end-of-object marker
                    break

                if peek == 0x05:
                    # 0x05 N is a field-count marker.  The value N sets (or
                    # overrides) the loop limit for this object.  When two
                    # consecutive markers appear (e.g. 05 01 05 02 in
                    # localMediaItemLocations), the LAST one wins, which
                    # correctly scopes the nested ADCMediaItemTitleID to 2
                    # fields even when no UUID obj_id precedes them.
                    local_max = blob[pos + 1] if pos + 1 < len(blob) else local_max
                    pos += 2
                    continue

                tc = blob[pos]
                pos += 1

                if tc == 0x08:
                    value: object = read_string()
                elif tc == 0x0F:
                    # uint8: value is the next byte (e.g. deckNumber on macOS)
                    value = blob[pos] if pos < len(blob) else None
                    pos += 1
                elif tc == 0x13:
                    # macOS: float32 with 4-byte alignment
                    value = read_float32()
                elif tc in (0x14, 0x30):
                    # Windows: float64 with 8-byte alignment; 0x30 = timestamp
                    value = read_float64()
                elif tc == 0x2D:
                    # Zero-byte integer marker seen before deckNumber=1 on macOS.
                    # The value is implicit (1); no value bytes precede the key.
                    value = 1
                elif tc == 0x2B:
                    # Inline nested object: merge fields into parent
                    sub = parse_object()
                    result.update(sub)
                    fields_read += 1
                    continue  # no separate key
                elif tc == 0x0B:
                    # Array: 4-byte-aligned int32 count, then elements
                    rem = pos % 4
                    if rem:
                        pos += 4 - rem
                    count = struct.unpack_from("<i", blob, pos)[0]
                    pos += 4
                    value = [read_array_element() for _ in range(count) if pos < len(blob)]
                elif tc == 0x21:
                    if pos < len(blob):
                        pos += 1  # skip sub-type byte
                    value = read_string()
                    if pos < len(blob) and blob[pos] == 0x00:
                        pos += 1
                elif tc == 0x15:
                    # Binary blob: 4-byte-aligned uint32 length, then raw bytes
                    # Used on macOS for CFURLBookmarkData (urlBookmarkData field)
                    rem = pos % 4
                    if rem:
                        pos += 4 - rem
                    length = struct.unpack_from("<I", blob, pos)[0]
                    pos += 4
                    value = bytes(blob[pos : pos + length])
                    pos += length
                else:
                    # Unknown type: cannot safely advance pos, so stop parsing
                    # this object rather than misreading value bytes as the next
                    # type code.
                    logging.debug("Unknown TSAF type 0x%02x at offset %d", tc, pos - 1)
                    break

                if pos < len(blob) and blob[pos] == 0x08:
                    pos += 1
                    key = read_string()
                    result[key] = value
                    fields_read += 1
                elif isinstance(value, list):
                    # Array of objects with no following key: merge dict items
                    # into the parent.  This handles localMediaItemLocations
                    # where a 0x0b array of ADCMediaItemTitleID objects carries
                    # title/artist but has no explicit key in the byte stream.
                    _merge_list_into(result, value)
                    fields_read += 1

            return result

        if pos >= len(blob) or blob[pos] != 0x2B:
            return {}
        pos += 1
        return parse_object()

    @staticmethod
    def _flatten_tsaf_raw(raw: dict) -> dict[str, object]:
        """Flatten a raw TSAF dict: expand list values into top-level keys.

        0x0b array values may contain dicts (whose keys are merged in) or
        file:// strings (stored under 'sourceURI').  Scalar values are kept
        as-is.  First-seen wins for duplicate keys.
        """
        result: dict[str, object] = {}
        for key, val in raw.items():
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        new = {k: v for k, v in item.items() if v is not None and k not in result}
                        result.update(new)
                    elif isinstance(item, str) and item.startswith("file://"):
                        result.setdefault("sourceURI", item)
            elif val is not None:
                result.setdefault(key, val)  # first-seen wins for scalars too
        return result

    @staticmethod
    def _resolve_file_uri(uri: str) -> str | None:
        """Convert a file:// URI to a local filesystem path."""
        try:
            parsed_url = urllib.parse.urlparse(uri)
            path = urllib.parse.unquote(parsed_url.path)
            if not path or path == "/":
                return None
            if sys.platform == "win32" and len(path) > 2 and path[2] == ":":
                path = path[1:]
            return path
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    @staticmethod
    def _resolve_bookmark(bookmark_data: bytes) -> str | None:
        """Resolve a macOS CFURLBookmarkData blob to a local file path.

        Requires mac_alias (mac-alias on PyPI).  Returns None when the
        library is unavailable or the bookmark cannot be decoded.
        """
        if not _HAS_MAC_ALIAS:
            return None
        try:
            bm = _MacAliasBookmark.from_bytes(bookmark_data)
            components: object = bm.get(_kBookmarkPath, None)
            if isinstance(components, list) and components:
                return "/" + "/".join(str(c) for c in components)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return None

    @staticmethod
    def _parse_blob(blob_data: bytes) -> dict[str, str | int | None]:
        """Parse a TSAF blob and return a flat track-metadata dict."""
        try:
            flat = Plugin._flatten_tsaf_raw(Plugin._parse_tsaf(blob_data))

            uri = flat.get("sourceURI")
            file_path = Plugin._resolve_file_uri(uri) if isinstance(uri, str) else None

            if file_path is None:
                bookmark = flat.get("urlBookmarkData")
                if isinstance(bookmark, bytes):
                    file_path = Plugin._resolve_bookmark(bookmark)

            duration_raw = flat.get("duration")
            duration: int | None = int(duration_raw) if isinstance(duration_raw, float) else None

            bpm_raw = flat.get("bpm")
            bpm: str | None = str(bpm_raw) if isinstance(bpm_raw, float) else None

            isrc_raw = flat.get("isrc")
            isrc: str | None = str(isrc_raw) if isinstance(isrc_raw, str) and isrc_raw else None

            return {
                "artist": flat.get("artist") or None,  # type: ignore[return-value]
                "title": flat.get("title") or None,  # type: ignore[return-value]
                "album": flat.get("album") or None,  # type: ignore[return-value]
                "source": flat.get("originSourceID") or None,  # type: ignore[return-value]
                "filename": file_path,
                "bpm": bpm,
                "duration": duration,
                "isrc": isrc,
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
                "isrc": None,
            }

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

    def _has_tracks_in_entire_library(self, dbfile: str, artist_name: str) -> bool:
        """Scan mediaItemTitleIDs TSAF blobs for a case-insensitive artist match."""
        artist_lower = artist_name.strip().lower()
        if not artist_lower:
            return False

        with nowplaying.utils.sqlite.sqlite_connection(str(dbfile), timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data FROM database2 WHERE collection='mediaItemTitleIDs'")
            for (blob,) in cursor:
                parsed = self._parse_blob(blob)
                raw_artist = parsed.get("artist")
                if isinstance(raw_artist, str) and raw_artist.strip().lower() == artist_lower:
                    return True
        return False

    def _has_tracks_in_playlists(
        self, dbfile: str, artist_name: str, playlist_names: list[str]
    ) -> bool:
        """Scan mediaItemTitleIDs blobs for tracks in selected playlists.

        Uses view_mediaItemPlaylistView_map and view_mediaItemPlaylistView_page
        to restrict the search to tracks belonging to the given playlists.
        Falls back to False (rather than the entire library) when the view
        tables are absent, which happens when no playlists are configured.
        """
        artist_lower = artist_name.strip().lower()
        if not artist_lower or not playlist_names:
            return False

        placeholders = ",".join("?" * len(playlist_names))
        sql = f"""
            SELECT d.data
            FROM database2 d
            JOIN view_mediaItemPlaylistView_map m
                ON CAST(m.rowid AS INTEGER) = d.rowid
            JOIN view_mediaItemPlaylistView_page p
                ON p.pageKey = m.pageKey
            WHERE p."group" IN ({placeholders})
              AND d.collection = 'mediaItemTitleIDs'
        """
        with nowplaying.utils.sqlite.sqlite_connection(str(dbfile), timeout=5) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, playlist_names)
            except sqlite3.OperationalError:
                # View tables don't exist (no playlists configured in djay Pro)
                return False
            for (blob,) in cursor:
                parsed = self._parse_blob(blob)
                raw_artist = parsed.get("artist")
                if isinstance(raw_artist, str) and raw_artist.strip().lower() == artist_lower:
                    return True
        return False

    async def has_tracks_by_artist(self, artist_name: str) -> bool:
        """Check if the djay Pro library contains any tracks by the given artist."""
        dbfile = pathlib.Path(self.djaypro_dir or "").joinpath("MediaLibrary.db")
        if not dbfile or not dbfile.exists():
            # Fall back to configured directory if djaypro_dir isn't set yet
            configured = self.config.cparser.value("djaypro/directory", defaultValue="")
            if configured:
                dbfile = pathlib.Path(configured).joinpath("MediaLibrary.db")
        if not dbfile.exists():
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
        configured = self.config.cparser.value("djaypro/directory", defaultValue="")
        dbfile = pathlib.Path(configured).joinpath("MediaLibrary.db") if configured else None
        if not dbfile or not dbfile.exists():
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
