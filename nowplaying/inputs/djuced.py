#!/usr/bin/env python3
"""djuced support

DJUCED Database Schema (DJUCED.db):

Main Tables:
- tracks: Complete track metadata and performance data
  - Core metadata: artist, title, album, composer, genre, year, rating
  - File info: absolutepath, filename, filetype, filesize, bitrate, samplerate
  - Performance: bpm, key, danceability, smart_advisor, max_val_gain
  - Play history: playcount, first_played, last_played, first_seen
  - Binary data: coverimage, waveform (BLOB)

- playlists2: Playlist structure with hierarchical types
  - type=0: Empty playlist containers/folders
  - type=2: Smart playlists (data contains JSON filter rules)
  - type=3: Individual track entries (data contains absolutepath)
  - type=5: Playlist metadata/properties
  - Fields: name, path, data, order_in_list, type

- trackCues: DJ cue points and loop markers
  - Per-track cue points: cuename, cuenumber, cuepos, loopLength, cueColor

- trackBeats: Beat grid data for DJ mixing
  - Per-track beat positions: beatpos, timesignature

Utility Tables:
- tblAdmin: Application settings (key-value pairs)
- tblFolderScan: Music folder scanning state
- samples: Sample references
- recordings: Recording metadata
"""

import asyncio
import json
import logging
import pathlib
import random
from typing import TYPE_CHECKING

import sqlite3
import aiosqlite
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import PatternMatchingEventHandler

from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

from nowplaying.exceptions import PluginVerifyError
from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata
import nowplaying.utils

if TYPE_CHECKING:
    import nowplaying.config
    import nowplaying.uihelp
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget


class Plugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
    """handler for NowPlaying"""

    metadata: TrackMetadata = {"artist": None, "title": None, "filename": None}
    decktracker: dict[str, TrackMetadata | None] = {}

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "DJUCED"
        self.mixmode = "newest"
        self.event_handler = None
        self.observer = None
        self.djuceddir = ""
        self._reset_meta()
        self.tasks = set()

    def install(self) -> bool:
        """locate Virtual DJ"""
        djuceddir = self.config.userdocs.joinpath("DJUCED")
        if djuceddir.exists():
            self.config.cparser.value("settings/input", "djuced")
            self.config.cparser.value("djuced/directory", str(djuceddir))
            return True
        return False

    def _reset_meta(self):
        """reset the metadata"""
        self.metadata = {"artist": None, "title": None, "filename": None}

    async def setup_watcher(self, configkey: str = "djuced/directory"):
        """set up a custom watch on the m3u dir so meta info
        can update on change"""

        djuceddir = self.config.cparser.value(configkey)
        if not self.djuceddir or self.djuceddir != djuceddir:
            await self.stop()

        if self.observer:
            return

        self.djuceddir = djuceddir
        if not self.djuceddir:
            logging.error(
                "DJUCED Directory Path not configured/does not exist: %s", self.djuceddir
            )
            await asyncio.sleep(1)
            return

        logging.info("Watching for changes on %s", self.djuceddir)
        self.event_handler = PatternMatchingEventHandler(
            patterns=["playing.txt"],
            ignore_patterns=[".DS_Store"],
            ignore_directories=True,
            case_sensitive=False,
        )
        self.event_handler.on_modified = self._fs_event
        self.event_handler.on_created = self._fs_event

        if self.config.cparser.value("quirks/pollingobserver", type=bool):
            polling_interval = self.config.cparser.value("quirks/pollinginterval", type=float)
            logging.debug("Using polling observer with %s second interval", polling_interval)
            self.observer = PollingObserver(timeout=polling_interval)
        else:
            logging.debug("Using fsevent observer")
            self.observer = Observer()
        self.observer.schedule(self.event_handler, self.djuceddir, recursive=False)
        self.observer.start()

    def _fs_event(self, event):
        if event.is_directory:
            return
        filename = event.src_path
        logging.debug(
            "event type: %s, syn: %s, path: %s", event.event_type, event.is_synthetic, filename
        )

        deck = self._read_playingtxt()
        if not deck:
            return

        logging.debug("Looking at deck: %s", Plugin.decktracker[deck])
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._get_metadata(deck))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self._get_metadata(deck))

    def _read_playingtxt(self) -> str | None:
        txtfile = pathlib.Path(self.djuceddir).joinpath("playing.txt")
        with open(txtfile, encoding="utf-8") as fhin:
            while line := fhin.readline():
                try:
                    title, deck, artist, album = line.split(" | ")
                except ValueError:
                    logging.error("text file output is not formatted correctly")
                    return None
                album = album.rstrip()
                if (
                    Plugin.decktracker.get(deck)
                    and Plugin.decktracker[deck]["title"] == title
                    and Plugin.decktracker[deck]["artist"] == artist
                ):
                    continue
                Plugin.decktracker[deck] = {
                    "title": title,
                    "artist": artist,
                    "album": album,
                }
                return deck
        return None

    async def _try_db(self, deck: str) -> TrackMetadata:
        metadata = {}
        dbfile = pathlib.Path(self.djuceddir).joinpath("DJUCED.db")
        sql = (
            "SELECT  artist, comment, coverimage, title, bpm, tracknumber, length, absolutepath "
            "FROM tracks WHERE album=? AND artist=? AND title=? "
            "ORDER BY last_played"
        )
        async with aiosqlite.connect(dbfile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            params = (
                Plugin.decktracker[deck]["album"],
                Plugin.decktracker[deck]["artist"],
                Plugin.decktracker[deck]["title"],
            )
            await cursor.execute(sql, params)
            row = await cursor.fetchone()
            await connection.commit()

            if row:
                metadata: TrackMetadata = {
                    "artist": str(row["artist"]),
                    "comment": str(row["comment"]),
                    "title": str(row["title"]),
                    "bpm": str(row["bpm"]),
                    "track": str(row["tracknumber"]),
                    "duration": int(row["length"]),
                    "filename": str(row["absolutepath"]),
                }
                if row["coverimage"]:
                    if image := nowplaying.utils.image2png(row["coverimage"]):
                        metadata["coverimageraw"] = image
        return metadata

    # async def _try_songxml(self, deck):
    #     filename = None
    #     xmlfile = pathlib.Path(self.djuceddir).joinpath(f'song{deck}.xml')
    #     with contextlib.suppress(Exception):
    #         root = xml.etree.ElementTree.parse(xmlfile).getroot()
    #         if root.tag == 'song':
    #             filename = root.attrib.get('path')

    #     if not filename or not pathlib.Path(filename).exists():
    #         return {}

    #     # we can get by with a shallow copy
    #     metadata = Plugin.decktracker[deck].copy()
    #     metadata['filename'] = filename
    #     return metadata

    async def _get_metadata(self, deck: str):
        if metadata := await self._try_db(deck):
            logging.debug("Adding data from db")
            Plugin.metadata = metadata
            return

        # print(f'trying songxml {deck}')
        # if metadata := await self._try_songxml(deck):
        #     Plugin.metadata = metadata
        #     return
        logging.debug("Setting to what we got from playing.txt")
        Plugin.metadata = Plugin.decktracker[deck]

    async def start(self):
        """setup the watcher to run in a separate thread"""
        await self.setup_watcher()

    async def getplayingtrack(self) -> TrackMetadata:
        """wrapper to call getplayingtrack"""

        # just in case called without calling start...
        await self.start()
        return Plugin.metadata

    async def get_available_playlists(self):
        """Get list of all playlists that have tracks (static or smart)"""
        dbfile = pathlib.Path(self.djuceddir).joinpath("DJUCED.db")
        playlists = []

        async with aiosqlite.connect(dbfile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()

            # Get playlists with static tracks (type=3)
            await cursor.execute("SELECT DISTINCT name FROM playlists2 WHERE type=3")
            static_playlists = await cursor.fetchall()
            playlists.extend(row["name"] for row in static_playlists)
            # Get smart playlists (type=2) and check if they have matching tracks
            await cursor.execute("SELECT name, data FROM playlists2 WHERE type=2")
            smart_playlists = await cursor.fetchall()
            for row in smart_playlists:
                if row["name"] not in playlists:  # Avoid duplicates
                    track_count = await self._count_smart_playlist_tracks(cursor, row["data"])
                    if track_count > 0:
                        playlists.append(row["name"])

            await connection.commit()

        return sorted(playlists)

    async def _count_smart_playlist_tracks(self, cursor, json_rules: str | bytes):
        """Count tracks matching smart playlist JSON rules"""
        try:
            rules = json.loads(json_rules)
            where_conditions = []
            params = []

            for rule in rules.get("rules", []):
                condition, param = self._parse_smart_rule(rule)
                if condition:
                    where_conditions.append(condition)
                    if param:
                        params.append(param)

            if not where_conditions:
                return 0

            # Combine conditions based on match type (1=AND, 0=OR assumed)
            match_type = rules.get("match", 1)
            connector = " AND " if match_type == 1 else " OR "
            where_clause = connector.join(where_conditions)

            sql = "SELECT COUNT(*) as count FROM tracks WHERE " + where_clause
            await cursor.execute(sql, params)
            row = await cursor.fetchone()
            return row["count"] if row else 0

        except (json.JSONDecodeError, KeyError, sqlite3.Error):
            return 0

    @staticmethod
    def _parse_smart_rule(rule):
        """Parse individual smart playlist rule into SQL condition"""
        # Based on observed rule structure: {"param": 0, "period": 0, "rule": 0, "value": "actors"}
        # param appears to be field type: 0=artist, 1=title, 2=album, etc.
        # rule appears to be comparison: 0=contains, 1=equals, etc.

        param = rule.get("param", 0)
        rule_type = rule.get("rule", 0)
        value = rule.get("value", "")

        if not value:
            return None, None

        # Map param to database field
        field_map = {
            0: "artist",
            1: "title",
            2: "album",
            3: "genre",
            4: "composer",
            # Add more mappings as needed
        }

        if param not in field_map:
            logging.warning(
                "Unknown smart playlist param value %s, skipping rule. "
                "This may indicate a schema change or new field type.",
                param,
            )
            return None, None

        field = field_map[param]

        # Map rule type to SQL condition
        if rule_type == 0:  # Contains (LIKE)
            return f"{field} LIKE ?", f"%{value}%"
        if rule_type == 1:  # Equals
            return f"{field} = ?", value

        # Handle unknown rule types
        logging.warning(
            "Unknown smart playlist rule type %s, defaulting to 'contains'. "
            "This may indicate a schema change or new comparison type.",
            rule_type,
        )
        return f"{field} LIKE ?", f"%{value}%"

    async def _get_smart_playlist_tracks(self, cursor, json_rules):
        """Get all tracks matching smart playlist JSON rules"""
        try:
            rules = json.loads(json_rules)
            where_conditions = []
            params = []

            for rule in rules.get("rules", []):
                condition, param = self._parse_smart_rule(rule)
                if condition:
                    where_conditions.append(condition)
                    if param:
                        params.append(param)

            if not where_conditions:
                return []

            # Combine conditions based on match type
            match_type = rules.get("match", 1)
            connector = " AND " if match_type == 1 else " OR "
            where_clause = connector.join(where_conditions)

            sql = "SELECT absolutepath FROM tracks WHERE " + where_clause
            await cursor.execute(sql, params)
            rows = await cursor.fetchall()
            return [row["absolutepath"] for row in rows]

        except (json.JSONDecodeError, KeyError, sqlite3.Error):
            return []

    async def getrandomtrack(self, playlist: str) -> str | None:
        """Get a random track from playlist (handles both static and smart playlists)"""
        dbfile = pathlib.Path(self.djuceddir).joinpath("DJUCED.db")

        async with aiosqlite.connect(dbfile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()

            # First try static playlist (type=3)
            await cursor.execute(
                "SELECT data FROM playlists2 WHERE name=? and type=3 ORDER BY random() LIMIT 1",
                (playlist,),
            )
            row = await cursor.fetchone()
            if row:
                await connection.commit()
                return row["data"]

            # Try smart playlist (type=2)
            await cursor.execute(
                "SELECT data FROM playlists2 WHERE name=? and type=2", (playlist,)
            )
            row = await cursor.fetchone()
            if row:
                tracks = await self._get_smart_playlist_tracks(cursor, row["data"])
                await connection.commit()
                if tracks:
                    return random.choice(tracks)

            await connection.commit()
            return None

    async def stop(self):
        """stop the m3u plugin"""
        self._reset_meta()
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    async def has_tracks_by_artist(self, artist_name: str) -> bool:
        """Check if DJ has any tracks by the specified artist"""
        dbfile = pathlib.Path(self.djuceddir).joinpath("DJUCED.db")
        scope = self.config.cparser.value(
            "djuced/artist_query_scope", defaultValue="entire_library"
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
            logging.error("Failed to query DJUCED database for artist %s: %s", artist_name, err)
            return False

    async def _check_artist_in_playlists(self, cursor, artist_name: str) -> bool:
        """Check if artist exists in selected playlists"""
        playlist_names = self._get_selected_playlist_names()
        if not playlist_names:
            return False

        # Check static playlists first (faster)
        if await self._check_artist_in_static_playlists(cursor, artist_name, playlist_names):
            return True

        # Check smart playlists (slower)
        return await self._check_artist_in_smart_playlists(cursor, artist_name, playlist_names)

    @staticmethod
    async def _check_artist_in_library(cursor, artist_name: str) -> bool:
        """Check if artist exists in entire library"""
        await cursor.execute(
            "SELECT COUNT(*) as count FROM tracks WHERE LOWER(artist) = LOWER(?)",
            (artist_name,),
        )
        row = await cursor.fetchone()
        return row["count"] > 0 if row else False

    def _get_selected_playlist_names(self) -> list[str]:
        """Get list of selected playlist names from config"""
        selected_playlists = self.config.cparser.value(
            "djuced/selected_playlists", defaultValue=""
        )
        if not selected_playlists.strip():
            return []

        return [name.strip() for name in selected_playlists.split(",") if name.strip()]

    @staticmethod
    async def _check_artist_in_static_playlists(
        cursor, artist_name: str, playlist_names: list[str]
    ) -> bool:
        """Check if artist exists in static playlists (type=3)"""
        placeholders = ",".join("?" * len(playlist_names))
        sql = f"""
            SELECT COUNT(*) as count
            FROM tracks t
            JOIN playlists2 p ON t.absolutepath = p.data
            WHERE LOWER(t.artist) = LOWER(?) AND p.name IN ({placeholders}) AND p.type = 3
        """
        params = [artist_name] + playlist_names
        await cursor.execute(sql, params)
        row = await cursor.fetchone()
        return row and row["count"] > 0

    @staticmethod
    async def _check_artist_in_smart_playlists(
        cursor, artist_name: str, playlist_names: list[str]
    ) -> bool:
        """Check if artist exists in any of the given smart playlists (type=2)"""
        if not playlist_names:
            return False

        placeholders = ",".join("?" for _ in playlist_names)
        sql = f"""
            SELECT COUNT(*) as count
            FROM tracks t
            JOIN playlists2 p ON t.absolutepath = p.data
            WHERE LOWER(t.artist) = LOWER(?) AND p.name IN ({placeholders}) AND p.type = 2
        """
        params = [artist_name] + playlist_names
        await cursor.execute(sql, params)
        row = await cursor.fetchone()
        return row and row["count"] > 0

    def on_djuced_dir_button(self):
        """filename button clicked action"""
        if self.qwidget.dir_lineedit.text():
            startdir = self.qwidget.dir_lineedit.text()
        else:
            startdir = str(self.config.userdocs.joinpath("DJUCED"))
        if dirname := QFileDialog.getExistingDirectory(self.qwidget, "Select directory", startdir):
            self.qwidget.dir_lineedit.setText(dirname)

    def defaults(self, qsettings: "QSettings"):
        """(re-)set the default configuration values for this plugin"""
        djuced = self.config.userdocs.joinpath("DJUCED")
        qsettings.setValue("djuced/directory", str(djuced))
        qsettings.setValue("djuced/artist_query_scope", "entire_library")
        qsettings.setValue("djuced/selected_playlists", "")

    def connect_settingsui(self, qwidget: "QWidget", uihelp: "nowplaying.uihelp.UIHelp"):
        """connect m3u button to filename picker"""
        self.qwidget = qwidget
        self.uihelp = uihelp
        qwidget.dir_button.clicked.connect(self.on_djuced_dir_button)

    def load_settingsui(self, qwidget: "QWidget"):
        """draw the plugin's settings page"""
        qwidget.dir_lineedit.setText(self.config.cparser.value("djuced/directory"))

        # Set artist query scope
        scope = self.config.cparser.value(
            "djuced/artist_query_scope", defaultValue="entire_library"
        )
        if scope == "selected_playlists":
            qwidget.djuced_artist_scope_combo.setCurrentText("Selected Playlists")
        else:
            qwidget.djuced_artist_scope_combo.setCurrentText("Entire Library")

        # Load selected playlists
        qwidget.djuced_playlists_lineedit.setText(
            self.config.cparser.value("djuced/selected_playlists", defaultValue="")
        )

    def verify_settingsui(self, qwidget: "QWidget"):
        """no verification to do"""
        if not pathlib.Path(qwidget.dir_lineedit.text()).exists():
            raise PluginVerifyError(r"djuced directory must exist.")

    def save_settingsui(self, qwidget: "QWidget"):
        """take the settings page and save it"""
        configdir = qwidget.dir_lineedit.text()
        self.config.cparser.setValue("djuced/directory", configdir)

        # Save artist query scope
        scope = (
            "selected_playlists"
            if qwidget.djuced_artist_scope_combo.currentText() == "Selected Playlists"
            else "entire_library"
        )
        self.config.cparser.setValue("djuced/artist_query_scope", scope)

        # Save selected playlists
        self.config.cparser.setValue(
            "djuced/selected_playlists", qwidget.djuced_playlists_lineedit.text()
        )

    def desc_settingsui(self, qwidget: "QWidget"):
        """description"""
        qwidget.setText("DJUCED is DJ software built for the Hercules-series of controllers.")
