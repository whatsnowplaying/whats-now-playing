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
import datetime
import logging
import pathlib
import sqlite3
import threading
import time
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

import nowplaying.djaypro.locationdb
import nowplaying.djaypro.mediadb
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
_ANALYZED_DATA_RETRY_DEFAULT = 0.5

# djay Pro stores timestamps as Core Data epoch: seconds since 2001-01-01 UTC.
_COREDATA_EPOCH = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc)


class Plugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
    """handler for djay Pro"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "djay Pro"
        self.event_handler = None
        self.observer = None
        self.djaypro_dir = ""
        self._wal_timer: threading.Timer | None = None
        self._wal_timer_lock = threading.Lock()
        self._deck_tracks: dict[str, nowplaying.djaypro.mediadb.DeckTrack] = {}
        self._location_db_path: pathlib.Path = nowplaying.djaypro.locationdb.default_db_path()
        # Record launch time in Core Data epoch (seconds since 2001-01-01 UTC)
        # so we can skip tracks that were already playing when WNP started.
        self._launch_time: float = (
            datetime.datetime.now(datetime.timezone.utc) - _COREDATA_EPOCH
        ).total_seconds()
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
            "deck": None,
            "duration": None,
            "key": None,
        }

    async def _maybe_rebuild_location_db(self) -> None:
        """Rebuild the location index if the manual flag is set or it has aged out."""
        rebuild = self.config.cparser.value(
            "djaypro/rebuild_location_db", type=bool, defaultValue=False
        )
        if not rebuild and self._location_db_path.exists():
            max_age_days = max(
                1,
                self.config.cparser.value(
                    "djaypro/location_max_age_days", type=int, defaultValue=7
                ),
            )
            last_rebuild = nowplaying.djaypro.locationdb.get_last_rebuild_time(
                self._location_db_path
            )
            age_days = (time.time() - last_rebuild) / 86400
            if age_days > max_age_days:
                logging.info(
                    "djay Pro location index is %.1f days old (max %d); rebuilding",
                    age_days,
                    max_age_days,
                )
                rebuild = True

        if rebuild:
            dbfile = self._get_db_path()
            if dbfile:
                await asyncio.to_thread(
                    nowplaying.djaypro.locationdb.rebuild, dbfile, self._location_db_path
                )
                self.config.cparser.setValue("djaypro/rebuild_location_db", False)

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

    def _get_deckskip(self) -> list[str]:
        """Return the list of deck numbers to skip, or empty list."""
        deckskip = self.config.cparser.value("djaypro/deckskip")
        if not deckskip:
            return []
        if isinstance(deckskip, list):
            return deckskip
        # QSettings returns a plain string when only one value is stored.
        return [deckskip]

    def _supplement_from_db(  # pylint: disable=too-many-arguments
        self,
        artist: str,
        title: str,
        *,
        seed_bpm: str | None = None,
        seed_key: str | None = None,
        retry_filename: bool = False,
        title_id: str | None = None,
    ) -> tuple[str | None, dict, str | None]:
        """Look up file path, analyzed data, and location ISRC from the database.

        seed_bpm / seed_key: BPM/key already known from historySessionItems
        (Windows path). When both are provided the mediaItemAnalyzedData lookup
        is skipped entirely.

        retry_filename: retry the filename lookup on first miss (macOS path,
        where NowPlaying.txt fires before localMediaItemLocations is committed).

        title_id: ADCMediaItemTitleID UUID from the history blob.  When present
        a direct O(1) key lookup is tried before falling back to the side table.

        Returns (filename, analyzed, loc_isrc).
        """
        filename, track_uuid, loc_isrc = self._get_filename_from_db(artist, title, title_id)
        dbfile = self._get_db_path()

        need_analyzed = not seed_bpm or not seed_key
        analyzed: dict = {}
        if need_analyzed:
            analyzed = nowplaying.djaypro.mediadb.get_analyzed_data_by_uuid(
                dbfile, track_uuid or ""
            )

        needs_retry = (retry_filename and filename is None) or (
            need_analyzed and (not analyzed.get("bpm") or not analyzed.get("key"))
        )
        if needs_retry:
            delay = self.config.cparser.value(
                "djaypro/analyzed_data_delay",
                defaultValue=_ANALYZED_DATA_RETRY_DEFAULT,
                type=float,
            )
            time.sleep(delay)
            if retry_filename and filename is None:
                filename, track_uuid, loc_isrc = self._get_filename_from_db(
                    artist, title, title_id
                )
            if need_analyzed and (not analyzed.get("bpm") or not analyzed.get("key")):
                analyzed = nowplaying.djaypro.mediadb.get_analyzed_data_by_uuid(
                    dbfile, track_uuid or ""
                )

        return filename, analyzed, loc_isrc

    def _commit_new_track(  # pylint: disable=too-many-arguments
        self,
        *,
        artist: str | None,
        title: str | None,
        album: str | None,
        duration: int | None,
        filename: str | None,
        bpm: str | None,
        key: str | None,
        deck: str | None,
        isrc: str | None,
        source: str | None,
    ) -> None:
        """Assemble new_meta from resolved fields, commit it, and log the track."""
        new_meta: TrackMetadata = {
            "artist": artist,
            "title": title,
            "album": album,
            "filename": filename,
            "bpm": bpm,
            "deck": deck,
            "duration": duration,
            "key": key,
        }
        if isrc:
            new_meta["isrc"] = [isrc]
        if source:
            new_meta["source"] = source
        self.metadata = new_meta
        logging.info(
            "New track detected: %s - %s%s%s%s%s%s%s%s",
            artist,
            title,
            f" (BPM: {bpm})" if bpm else "",
            f" (Key: {key})" if key else "",
            f" [deck {deck}]" if deck else "",
            f" [source: {source}]" if source else "",
            f" [{album}]" if album else "",
            f" - {filename}" if filename else " (no filename found)",
            f" ISRC:{isrc}" if isrc else "",
        )

    def _check_for_new_track(self):  # pylint: disable=too-many-locals,too-many-return-statements
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

        records = nowplaying.djaypro.mediadb.query_recent_history(dbfile, limit=1)
        if not records:
            return

        track_data = records[0]
        t_artist = track_data.get("artist")
        t_title = track_data.get("title")
        if not isinstance(t_title, str):
            return

        deck = track_data.get("deck")
        deck_key = deck or "0"

        # Skip if this deck is configured to be ignored.
        deckskip = self._get_deckskip()
        if deckskip and deck_key in deckskip:
            return

        # If this deck's track hasn't changed, the mix mode selection is unchanged.
        existing = self._deck_tracks.get(deck_key)
        if existing and existing.artist == t_artist and existing.title == t_title:
            return

        # Skip tracks that started before WNP launched — record state to avoid
        # re-processing on every poll, but do not report them as new tracks.
        starttime = track_data.get("starttime")
        if isinstance(starttime, float) and starttime < self._launch_time:
            logging.debug(
                "Skipping pre-launch track on deck %s: %s - %s",
                deck_key,
                t_artist,
                t_title,
            )
            self._deck_tracks[deck_key] = nowplaying.djaypro.mediadb.DeckTrack(
                artist=t_artist,
                title=t_title,
                deck=deck,
            )
            return

        # localMediaItemLocations is authoritative for file paths; supplement
        # historySessionItems BPM/key with mediaItemAnalyzedData when missing.
        # retry_filename=True because localMediaItemLocations is written in the
        # same second transaction as analyzedData and may not yet be present.
        t_title_id = track_data.get("title_id")
        filename, analyzed, loc_isrc = self._supplement_from_db(
            t_artist or "",
            t_title,
            seed_bpm=track_data.get("bpm"),
            seed_key=track_data.get("key"),
            retry_filename=True,
            title_id=t_title_id if isinstance(t_title_id, str) else None,
        )
        if filename:
            track_data["filename"] = filename

        # Prefer history blob ISRC (streaming); fall back to location blob (local files).
        isrc_str = track_data.get("isrc") if isinstance(track_data.get("isrc"), str) else loc_isrc

        new_track = nowplaying.djaypro.mediadb.DeckTrack(
            artist=t_artist,
            title=t_title,
            album=track_data.get("album"),
            duration=track_data.get("duration"),
            filename=track_data.get("filename"),
            bpm=track_data.get("bpm") or analyzed.get("bpm"),
            key=track_data.get("key") or analyzed.get("key"),
            isrc=isrc_str,
            source=track_data.get("source"),
            deck=deck,
        )
        self._deck_tracks[deck_key] = new_track

        if (
            self.metadata.get("artist") == new_track.artist
            and self.metadata.get("title") == new_track.title
        ):
            return

        self._commit_new_track(
            artist=new_track.artist,
            title=new_track.title,
            album=new_track.album,
            duration=new_track.duration,
            filename=new_track.filename,
            bpm=new_track.bpm,
            key=new_track.key,
            deck=new_track.deck,
            isrc=new_track.isrc,
            source=new_track.source,
        )

    def _read_nowplaying_file(self):  # pylint: disable=too-many-locals,too-many-branches,too-many-return-statements
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

        # Get deck from historySessionItems first — needed for deckskip check
        # before doing the expensive file-path / analysis-data lookup.
        extras = nowplaying.djaypro.mediadb.get_history_extras_from_db(
            self._get_db_path(), artist, title
        )
        deck_key = extras.deck or "0"

        deckskip = self._get_deckskip()
        if deckskip and deck_key in deckskip:
            return

        existing = self._deck_tracks.get(deck_key)
        if existing and existing.artist == artist and existing.title == title:
            return

        # Skip tracks that started before WNP launched.  NowPlaying.txt is
        # never deleted between sessions so it persists from previous runs;
        # the starttime from historySessionItems is the only reliable signal
        # that the track is actually new since WNP started.
        if extras.starttime is not None and extras.starttime < self._launch_time:
            logging.debug(
                "Skipping pre-launch track on deck %s: %s - %s",
                deck_key,
                artist,
                title,
            )
            self._deck_tracks[deck_key] = nowplaying.djaypro.mediadb.DeckTrack(
                artist=artist,
                title=title,
                album=album,
                duration=duration,
                deck=extras.deck,
            )
            return

        # NowPlaying.txt fires before localMediaItemLocations and
        # mediaItemAnalyzedData are committed — retry once after the delay.
        filename, analyzed, loc_isrc = self._supplement_from_db(
            artist, title, retry_filename=True, title_id=extras.title_id
        )

        isrc = extras.isrc if extras.isrc is not None else loc_isrc

        new_track = nowplaying.djaypro.mediadb.DeckTrack(
            artist=artist,
            title=title,
            album=album,
            duration=duration,
            filename=filename,
            bpm=analyzed.get("bpm"),
            key=analyzed.get("key"),
            isrc=isrc,
            source=extras.source,
            deck=extras.deck,
        )
        self._deck_tracks[deck_key] = new_track

        if (
            self.metadata.get("artist") == new_track.artist
            and self.metadata.get("title") == new_track.title
        ):
            return

        self._commit_new_track(
            artist=new_track.artist,
            title=new_track.title,
            album=new_track.album,
            duration=new_track.duration,
            filename=new_track.filename,
            bpm=new_track.bpm,
            key=new_track.key,
            deck=new_track.deck,
            isrc=new_track.isrc,
            source=new_track.source,
        )

    def _get_filename_from_db(
        self, artist: str, title: str, title_id: str | None = None
    ) -> tuple[str | None, str | None, str | None]:
        """Get filename, track UUID, and ISRC for a track.

        When title_id is present, tries a direct O(1) key lookup in djay's DB
        first (the ADCMediaItemTitleID UUID is the database2 key for location
        collections).  Falls back to the WNP-owned side-table index on miss.
        """
        dbfile = self._get_db_path()
        if not dbfile:
            return None, None, None

        if title_id:
            filename, loc_isrc = nowplaying.djaypro.locationdb.lookup_direct(dbfile, title_id)
            if filename is not None or loc_isrc is not None:
                return filename, title_id, loc_isrc

        nowplaying.djaypro.locationdb.sync(dbfile, self._location_db_path)
        return nowplaying.djaypro.locationdb.lookup(artist, title, self._location_db_path)

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
        self._deck_tracks.clear()

    async def start(self):
        """setup the watcher"""
        await self._maybe_rebuild_location_db()
        await self.setup_watcher()

    async def getplayingtrack(self) -> TrackMetadata:
        """wrapper to call getplayingtrack"""
        await self.start()
        return self.metadata

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
                    nowplaying.djaypro.mediadb.has_tracks_in_playlists,
                    dbfile,
                    artist_name,
                    playlist_names,
                )

            return await asyncio.to_thread(
                nowplaying.djaypro.mediadb.has_tracks_in_entire_library, dbfile, artist_name
            )

        except (sqlite3.OperationalError, FileNotFoundError, OSError) as err:
            logging.error("Failed to query djay Pro library for artist %s: %s", artist_name, err)
            return False

    async def get_available_playlists(self) -> list[str]:
        """Return sorted list of playlist names from the djay Pro library."""
        dbfile = self._get_db_path()
        if not dbfile:
            return []
        try:
            return await asyncio.to_thread(
                nowplaying.djaypro.mediadb.get_available_playlists_sync, dbfile
            )
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
        qsettings.setValue("djaypro/analyzed_data_delay", _ANALYZED_DATA_RETRY_DEFAULT)
        qsettings.setValue("djaypro/deckskip", None)
        qsettings.setValue("djaypro/location_max_age_days", 7)
        qsettings.setValue("djaypro/rebuild_location_db", False)

    def connect_settingsui(self, qwidget: "QWidget", uihelp: "nowplaying.uihelp.UIHelp"):
        """connect djay Pro button to filename picker"""
        self.qwidget = qwidget
        self.uihelp = uihelp
        qwidget.dir_button.clicked.connect(self.on_djaypro_dir_button)
        qwidget.djaypro_rebuild_location_button.clicked.connect(self.on_rebuild_location_button)

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

        qwidget.djaypro_analyzed_delay_lineedit.setText(
            str(
                self.config.cparser.value(
                    "djaypro/analyzed_data_delay",
                    defaultValue=_ANALYZED_DATA_RETRY_DEFAULT,
                    type=float,
                )
            )
        )

        qwidget.djaypro_location_max_age_spinbox.setValue(
            self.config.cparser.value("djaypro/location_max_age_days", type=int, defaultValue=7)
        )

        deckskip = self._get_deckskip()
        qwidget.djaypro_deck1_skip_checkbox.setChecked("1" in deckskip)
        qwidget.djaypro_deck2_skip_checkbox.setChecked("2" in deckskip)
        qwidget.djaypro_deck3_skip_checkbox.setChecked("3" in deckskip)
        qwidget.djaypro_deck4_skip_checkbox.setChecked("4" in deckskip)

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
        try:
            delay = float(qwidget.djaypro_analyzed_delay_lineedit.text())
        except ValueError:
            delay = _ANALYZED_DATA_RETRY_DEFAULT
        delay = max(0.0, min(delay, 10.0))
        self.config.cparser.setValue("djaypro/analyzed_data_delay", delay)

        self.config.cparser.setValue(
            "djaypro/location_max_age_days",
            qwidget.djaypro_location_max_age_spinbox.value(),
        )

        deckskip = []
        if qwidget.djaypro_deck1_skip_checkbox.isChecked():
            deckskip.append("1")
        if qwidget.djaypro_deck2_skip_checkbox.isChecked():
            deckskip.append("2")
        if qwidget.djaypro_deck3_skip_checkbox.isChecked():
            deckskip.append("3")
        if qwidget.djaypro_deck4_skip_checkbox.isChecked():
            deckskip.append("4")
        self.config.cparser.setValue("djaypro/deckskip", deckskip)

    def on_rebuild_location_button(self):
        """user clicked Rebuild Now — flag for rebuild on next poll cycle"""
        logging.info("Manual djay Pro location index rebuild requested")
        self.config.cparser.setValue("djaypro/rebuild_location_db", True)

    def on_djaypro_dir_button(self):
        """open file browser to set djay Pro directory"""
        startdir = self.config.cparser.value("djaypro/directory")
        if not startdir:
            # Use same base path as defaults() and install(): Music/djay
            music_dir = self.config.userdocs.parent.joinpath("Music")
            startdir = str(music_dir.joinpath("djay"))
        if dirname := QFileDialog.getExistingDirectory(self.qwidget, "Select directory", startdir):
            self.qwidget.dir_lineedit.setText(dirname)
