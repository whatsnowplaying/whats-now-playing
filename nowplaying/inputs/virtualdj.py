#!/usr/bin/env python3
"""Virtual DJ support"""

import asyncio
import logging
import os
import pathlib
import sqlite3
import time
import xml.sax
from typing import TYPE_CHECKING

import aiosqlite
from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

import nowplaying.utils
import nowplaying.utils.xml
from nowplaying.db import LISTFIELDS
from nowplaying.exceptions import PluginVerifyError

from .m3u import Plugin as M3UPlugin

if TYPE_CHECKING:
    import nowplaying.config

PLAYLIST = [
    "name",
    "filename",
    "artist",
    "title",
    "album",
    "genre",
    "year",
    "bpm",
    "key",
    "label",
    "tracknumber",
]
METADATALIST = [
    "artist",
    "title",
    "album",
    "filename",
    "genre",
    "year",
    "bpm",
    "key",
    "label",
    "tracknumber",
]


class VirtualDJSAXHandler(xml.sax.ContentHandler):
    """SAX handler for streaming VirtualDJ XML parsing"""

    def __init__(self, sqlcursor: sqlite3.Cursor):
        super().__init__()
        self.sqlcursor = sqlcursor

    def startElement(self, name: str, attrs: dict[str, str]) -> None:
        if name == "Song":
            if filepath := attrs.get("FilePath", ""):
                # Initialize entry with filepath
                self.current_entry = {  # pylint: disable=attribute-defined-outside-init
                    "artist": None,
                    "title": None,
                    "album": None,
                    "filename": filepath,
                    "genre": None,
                    "year": None,
                    "bpm": None,
                    "key": None,
                    "label": None,
                    "tracknumber": None,
                }
        elif name == "Tags" and hasattr(self, "current_entry"):
            # Extract metadata from Tags element
            self.current_entry["artist"] = attrs.get("Author")
            self.current_entry["title"] = attrs.get("Title")
            self.current_entry["album"] = attrs.get("Album")
            self.current_entry["genre"] = attrs.get("Genre")
            self.current_entry["year"] = attrs.get("Year")
            self.current_entry["bpm"] = attrs.get("Bpm")
            self.current_entry["key"] = attrs.get("Key")
            self.current_entry["label"] = attrs.get("Label")
            self.current_entry["tracknumber"] = attrs.get("TrackNumber")

    def endElement(self, name: str) -> None:
        if name == "Song" and hasattr(self, "current_entry"):
            # Insert song if we have artist and title
            if self.current_entry.get("artist") and self.current_entry.get("title"):
                sql = "INSERT INTO songs ("
                sql += ", ".join(self.current_entry.keys()) + ") VALUES ("
                sql += "?," * (len(self.current_entry.keys()) - 1) + "?)"
                datatuple = tuple(self.current_entry.values())
                self.sqlcursor.execute(sql, datatuple)
            delattr(self, "current_entry")


class VirtualDJFolderSAXHandler(xml.sax.ContentHandler):
    """SAX handler for streaming VirtualDJ .vdjfolder XML parsing"""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.content = []

    def startElement(self, name: str, attrs: dict[str, str]) -> None:
        if name == "song":
            song_path = attrs.get("path")
            artist = attrs.get("artist")
            title = attrs.get("title")

            if song_path and artist and title:
                # Apply song path substitution like M3U processing
                song_path = nowplaying.utils.songpathsubst(self.config, song_path)

                # Extract all available metadata from vdjfolder
                entry = {
                    "filename": song_path,
                    "artist": artist,
                    "title": title,
                    "album": attrs.get("album"),
                    "genre": attrs.get("genre"),
                    "year": attrs.get("year"),
                    "bpm": attrs.get("bpm"),
                    "key": attrs.get("key"),
                    "label": attrs.get("label"),
                    "tracknumber": attrs.get("tracknumber"),
                }
                self.content.append(entry)


class Plugin(M3UPlugin):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """handler for NowPlaying"""

    def __init__(
        self, config: "nowplaying.config.ConfigFile | None" = None, m3udir=None, qsettings=None
    ):
        super().__init__(config=config, m3udir=m3udir, qsettings=qsettings)
        self.displayname = "VirtualDJ"
        # Separate databases for different data sources
        self.songs_databasefile = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]
        ).joinpath("virtualdj", "virtualdj-songs.db")
        self.playlists_databasefile = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]
        ).joinpath("virtualdj", "virtualdj-playlists.db")
        self.database = None

        # Add XML processor for songs table only (M3U handles playlists)
        def get_virtualdj_xml():
            vdjdir = pathlib.Path(self.config.cparser.value("virtualdj/playlists", "")).parent
            xml_file = vdjdir.joinpath("database.xml")
            return xml_file if xml_file.exists() else None

        songs_table_schema = [
            "CREATE TABLE IF NOT EXISTS songs "
            f"({', '.join(f'{field} TEXT' for field in METADATALIST)},"
            " id INTEGER PRIMARY KEY AUTOINCREMENT)"
        ]

        self.xml_processor = nowplaying.utils.xml.BackgroundXMLProcessor(
            self.songs_databasefile,
            VirtualDJSAXHandler,
            get_virtualdj_xml,
            songs_table_schema,
            "virtualdj",
            config,
        )
        self.tasks = set()

        # Add separate config flag for playlist refresh
        self.playlist_refresh_needed = False
        self._playlists_shutdown_event = asyncio.Event()

    def initdb(self):
        """initialize the db"""
        # Initialize playlists database using existing M3U code
        if not self.playlists_databasefile.exists():
            self.rewrite_db()
        # Initialize songs database via XML processor
        if not self.songs_databasefile.exists():
            self.config.cparser.setValue("virtualdj/rebuild_db", True)

    def db_age_days(self) -> float | None:
        """return age of database in days, or None if doesn't exist"""
        return self.xml_processor.db_age_days()

    def needs_refresh(self, max_age_days: float = 7.0) -> bool:
        """check if database needs refresh based on age"""
        return self.xml_processor.needs_refresh(max_age_days)

    def playlists_db_age_days(self) -> float | None:
        """return age of playlists database in days, or None if doesn't exist"""
        if not self.playlists_databasefile.exists():
            return None
        age_seconds = time.time() - self.playlists_databasefile.stat().st_mtime
        return age_seconds / (24 * 60 * 60)

    def playlists_needs_refresh(self, max_age_days: float = 7.0) -> bool:
        """check if playlists database needs refresh based on age"""
        age = self.playlists_db_age_days()
        return age is None or age > max_age_days

    async def background_playlists_refresh_loop(self) -> None:
        """Background playlists refresh polling loop with cancellation support"""
        try:
            while not self._playlists_shutdown_event.is_set():
                self.config.cparser.sync()

                rebuild_requested: bool = self.config.cparser.value(
                    "virtualdj/rebuild_playlists_db", type=bool
                )

                # Check if playlists DB needs refresh based on age
                max_age_days = self.config.cparser.value(
                    "virtualdj/max_age_days", type=int, defaultValue=7
                )

                if self.playlists_needs_refresh(max_age_days):
                    rebuild_requested = True

                if rebuild_requested:
                    if playlistdir := self.config.cparser.value("virtualdj/playlists", type=str):
                        playlistdirpath = pathlib.Path(playlistdir)
                        success = await self.background_playlists_refresh(playlistdirpath)
                        if success:
                            self.config.cparser.setValue("virtualdj/rebuild_playlists_db", False)

                # Wait with cancellation support
                try:
                    await asyncio.wait_for(self._playlists_shutdown_event.wait(), timeout=5)
                    break  # Shutdown requested
                except asyncio.TimeoutError:
                    continue  # Normal timeout, continue loop

        except asyncio.CancelledError:
            logging.info("Background playlists refresh loop cancelled")
            raise  # Re-raise to properly handle cancellation

    async def background_playlists_refresh(self, playlistdirpath: pathlib.Path) -> bool:
        """Background playlists refresh with temp database and atomic swap"""
        logging.info(
            "Starting VirtualDJ playlists database refresh: %s", self.playlists_databasefile
        )

        # Create temp database
        temp_playlists_db = self.playlists_databasefile.with_suffix(".db.tmp")
        backup_playlists_db = self.playlists_databasefile.with_suffix(".db.backup")

        # Create temp database directory
        temp_playlists_db.parent.mkdir(parents=True, exist_ok=True)

        # Remove any existing temp file
        if temp_playlists_db.exists():
            temp_playlists_db.unlink()

        try:
            # Build temp database using M3U processing
            await asyncio.to_thread(self.rewrite_db, str(playlistdirpath), temp_playlists_db)

            # Atomic swap: rename temp to live
            if temp_playlists_db.exists():
                await asyncio.to_thread(
                    self._atomic_playlists_swap, temp_playlists_db, backup_playlists_db
                )
                logging.info(
                    "VirtualDJ playlists database refreshed successfully: %s",
                    self.playlists_databasefile,
                )
                return True
            logging.error("Temp playlists database was not created")
            return False

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.error("Background VirtualDJ playlists refresh failed: %s", err)
            # Clean up temp file on error
            if temp_playlists_db.exists():
                temp_playlists_db.unlink()
            return False

    def _atomic_playlists_swap(
        self, temp_db_path: pathlib.Path, backup_db_path: pathlib.Path
    ) -> None:
        """Atomically swap temp playlists database with live database"""
        if self.playlists_databasefile.exists():
            # Create backup first
            if backup_db_path.exists():
                backup_db_path.unlink()
            self.playlists_databasefile.rename(backup_db_path)

        # Atomic rename
        temp_db_path.rename(self.playlists_databasefile)

        # Clean up backup after successful swap
        if backup_db_path.exists():
            backup_db_path.unlink()

    async def lookup(
        self, artist: str | None = None, title: str | None = None
    ) -> dict[str, str] | None:
        """lookup the metadata from songs table"""
        async with aiosqlite.connect(self.songs_databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            try:
                await cursor.execute(
                    """SELECT * FROM songs WHERE artist=? AND title=? ORDER BY id DESC LIMIT 1""",
                    (artist, title),
                )
            except sqlite3.OperationalError:
                return None

            row = await cursor.fetchone()
            if not row:
                return None

        metadata = {data: row[data] for data in METADATALIST}
        for key in LISTFIELDS:
            # Only process LISTFIELDS that actually exist in the row
            if key in row and row[key]:
                metadata[key] = [row[key]]
        return metadata

    @staticmethod
    def _write_playlist(sqlcursor, playlist, filelist):
        """take the collections XML and save the playlists off"""
        columns = ', '.join(PLAYLIST)
        placeholders = ', '.join('?' * len(PLAYLIST))
        sql = f"INSERT INTO playlists ({columns}) VALUES ({placeholders})"
        for entry in filelist:
            if isinstance(entry, dict):
                # New format with metadata - normalize empty strings to None
                values = []
                for field in PLAYLIST:
                    if field == "name":
                        values.append(playlist)
                    else:
                        value = entry.get(field)
                        # Strip whitespace and convert empty strings to None for consistency
                        value = value.strip() if value and isinstance(value, str) else None
                        values.append(value)

                # Only keep artist/title metadata if both are valid
                artist_idx = PLAYLIST.index("artist")
                title_idx = PLAYLIST.index("title")
                if not values[artist_idx] or not values[title_idx]:
                    values[artist_idx] = None
                    values[title_idx] = None

                datatuple = tuple(values)
            else:
                # Legacy format - just filename, rest None
                values = [
                    playlist if field == "name" else (entry if field == "filename" else None)
                    for field in PLAYLIST
                ]
                datatuple = tuple(values)
            sqlcursor.execute(sql, datatuple)

    def _scan_and_populate_playlists(self, cursor, playlistdirpath: pathlib.Path) -> None:
        """Scan and populate playlists from .m3u and .vdjfolder files"""
        # Get VirtualDJ root directory (parent of Playlists)
        vdj_root_dir = playlistdirpath.parent
        mylists_dir = vdj_root_dir / "MyLists"

        if mylists_dir.exists():
            # VirtualDJ 2024+ unified format - scan only MyLists directory
            logging.debug("Found VirtualDJ 2024+ MyLists directory, scanning unified playlists")
            for filepath in list(mylists_dir.rglob("*.vdjfolder")):
                logging.debug("Reading vdjfolder file %s", filepath)
                content = self._read_vdjfolder_file(filepath)
                playlist_name = filepath.stem
                self._write_playlist(cursor, playlist_name, content)
        else:
            # VirtualDJ 2023 and earlier - scan legacy locations
            logging.debug(
                "Using VirtualDJ 2023 legacy format, scanning Playlists and scattered files"
            )

            # Process legacy .m3u files from Playlists directory
            for filepath in list(playlistdirpath.rglob("*.m3u")):
                logging.debug("Reading M3U file %s", filepath)
                content = self._read_full_file(filepath)
                self._write_playlist(cursor, filepath.stem, content)

            # Process legacy .vdjfolder files scattered throughout VDJ directory
            for filepath in list(vdj_root_dir.rglob("*.vdjfolder")):
                logging.debug("Reading vdjfolder file %s", filepath)
                content = self._read_vdjfolder_file(filepath)
                playlist_name = filepath.stem
                self._write_playlist(cursor, playlist_name, content)

    def _read_vdjfolder_file(self, filepath):
        """read VirtualDJ .vdjfolder XML file and extract song metadata using SAX parser"""
        try:
            handler = VirtualDJFolderSAXHandler(self.config)
            with open(filepath, "r", encoding="utf-8") as xml_file:
                xml.sax.parse(xml_file, handler)
            return handler.content

        except (xml.sax.SAXException, OSError, UnicodeDecodeError) as err:
            logging.error("Error parsing vdjfolder file %s: %s", filepath, err)
            return []

    def rewrite_db(self, playlistdir=None, db_path=None):
        """erase and update the old db"""
        if not playlistdir:
            playlistdir = self.config.cparser.value("virtualdj/playlists")

        if not playlistdir:
            logging.error("VDJ Playlists not defined")
            return

        playlistdirpath = pathlib.Path(playlistdir)
        if not playlistdirpath.exists():
            logging.error("playlistdir (%s) does not exist", playlistdir)
            return

        # Use provided db_path or default to instance variable
        database_path = pathlib.Path(db_path) if db_path else self.playlists_databasefile

        database_path.parent.mkdir(parents=True, exist_ok=True)
        if database_path.exists():
            database_path.unlink()

        with sqlite3.connect(database_path) as connection:
            cursor = connection.cursor()
            sql = "CREATE TABLE IF NOT EXISTS playlists ("
            sql += " TEXT, ".join(PLAYLIST) + " TEXT, "
            sql += "id INTEGER PRIMARY KEY AUTOINCREMENT)"
            cursor.execute(sql)
            connection.commit()

            # Scan playlists with VirtualDJ 2024+ MyLists support
            self._scan_and_populate_playlists(cursor, playlistdirpath)

            connection.commit()

    def install(self) -> bool:
        """locate Virtual DJ"""
        # Check multiple possible VirtualDJ locations
        possible_locations = [
            # Traditional Documents/VirtualDJ location
            self.config.userdocs.joinpath("VirtualDJ"),
            # Windows 11 AppData\Local\VirtualDJ location
            pathlib.Path(
                QStandardPaths.standardLocations(QStandardPaths.AppLocalDataLocation)[0]
            ).parent.joinpath("VirtualDJ"),
        ]

        for vdjdir in possible_locations:
            if vdjdir.exists():
                self.config.cparser.setValue("settings/input", "virtualdj")
                self.config.cparser.setValue("virtualdj/history", str(vdjdir.joinpath("History")))
                self.config.cparser.setValue(
                    "virtualdj/playlists", str(vdjdir.joinpath("Playlists"))
                )
                return True

        return False

    async def start(self) -> None:
        """setup the watcher to run in a separate thread"""
        # Prevent multiple background tasks
        if self.tasks:
            logging.debug("VirtualDJ background tasks already running, skipping start()")
            return

        # Start XML songs background refresh task
        # Reset shutdown event if it was set from a previous instance
        self.xml_processor.reset_shutdown_event()
        xml_task = asyncio.create_task(self.xml_processor.background_refresh_loop())
        self.tasks.add(xml_task)
        xml_task.add_done_callback(self.tasks.discard)

        # Start M3U playlists background refresh task
        playlists_task = asyncio.create_task(self.background_playlists_refresh_loop())
        self.tasks.add(playlists_task)
        playlists_task.add_done_callback(self.tasks.discard)

        await self.setup_watcher("virtualdj/history")

    async def getplayingtrack(self):
        """wrapper to call getplayingtrack"""
        return self.metadata

    async def getrandomtrack(self, playlist):
        """return the contents of a playlist"""
        async with aiosqlite.connect(self.playlists_databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            try:
                await cursor.execute(
                    """SELECT filename FROM playlists WHERE name=? ORDER BY random() LIMIT 1""",
                    (playlist,),
                )
            except sqlite3.OperationalError as error:
                logging.error(error)
                return None

            row = await cursor.fetchone()
            if not row:
                logging.debug("no match")
                return None
            return row["filename"]

    async def stop(self):
        """stop the virtual dj plugin"""
        self._reset_meta()
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

        # Signal background processors to shutdown cleanly
        self.xml_processor.shutdown()
        self._playlists_shutdown_event.set()

        # Cancel and wait for all tasks to complete
        if self.tasks:
            for task in self.tasks:
                task.cancel()
            # Wait for tasks to finish cancellation
            await asyncio.gather(*self.tasks, return_exceptions=True)

    async def has_tracks_by_artist(self, artist_name: str) -> bool:
        """Check if DJ has any tracks by the specified artist"""
        try:
            scope = self.config.cparser.value(
                "virtualdj/artist_query_scope", defaultValue="entire_library"
            )

            if scope == "selected_playlists":
                return await self._has_tracks_in_selected_playlists(artist_name)

            return await self._has_tracks_in_entire_library(artist_name)

        except sqlite3.OperationalError as err:
            logging.error("Failed to query VirtualDJ database for artist %s: %s", artist_name, err)
            return False

    async def _has_tracks_in_entire_library(self, artist_name: str) -> bool:
        """Check if artist has tracks in the entire library"""
        async with aiosqlite.connect(self.songs_databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()

            await cursor.execute(
                "SELECT COUNT(*) as count FROM songs WHERE LOWER(artist) = LOWER(?)",
                (artist_name,),
            )
            row = await cursor.fetchone()
            return row["count"] > 0 if row else False

    async def _has_tracks_in_selected_playlists(self, artist_name: str) -> bool:
        """Check if artist has tracks in selected playlists"""
        playlist_names = self._get_selected_playlist_names()
        if not playlist_names:
            return False

        async with aiosqlite.connect(self.playlists_databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()

            # Limit to reasonable number of playlists to prevent abuse
            if len(playlist_names) > 50:
                playlist_names = playlist_names[:50]

            placeholders = ",".join("?" * len(playlist_names))

            # Check if playlists have artist metadata (vdjfolder entries)
            has_metadata = await self._playlists_have_metadata(
                cursor, playlist_names, placeholders
            )

            logging.debug(
                "VDJ hasartist: playlists have metadata=%s, checking artist %s",
                has_metadata,
                artist_name,
            )

            if has_metadata:
                return await self._check_artist_in_playlist_metadata(
                    cursor, artist_name, playlist_names, placeholders
                )

            return await self._check_artist_via_filename_matching(
                cursor, artist_name, playlist_names, placeholders
            )

    def _get_selected_playlist_names(self) -> list[str]:
        """Get the list of selected playlist names from configuration"""
        selected_playlists = self.config.cparser.value(
            "virtualdj/selected_playlists", defaultValue=""
        )
        if not selected_playlists.strip():
            return []

        playlist_names = [name.strip() for name in selected_playlists.split(",") if name.strip()]
        return playlist_names

    @staticmethod
    async def _playlists_have_metadata(
        cursor, playlist_names: list[str], placeholders: str
    ) -> bool:
        """Check if playlists have artist metadata (vdjfolder entries)"""
        metadata_sql = (
            f"SELECT COUNT(*) as count FROM playlists "
            f"WHERE name IN ({placeholders}) AND artist IS NOT NULL"
        )
        await cursor.execute(metadata_sql, playlist_names)
        metadata_row = await cursor.fetchone()
        return metadata_row and metadata_row["count"] > 0

    @staticmethod
    async def _check_artist_in_playlist_metadata(
        cursor, artist_name: str, playlist_names: list[str], placeholders: str
    ) -> bool:
        """Fast path: Direct artist query for modern vdjfolder playlists"""
        artist_sql = f"""
            SELECT COUNT(*) as count FROM playlists
            WHERE name IN ({placeholders}) AND LOWER(artist) = LOWER(?)
        """
        params = playlist_names + [artist_name]
        await cursor.execute(artist_sql, params)
        row = await cursor.fetchone()

        if row and row["count"] > 0:
            logging.debug(
                "VDJ hasartist: fast path found %d artist matches in playlists",
                row["count"],
            )
            return True

        logging.debug("VDJ hasartist: fast path found no matches, returning False")
        return False

    async def _check_artist_via_filename_matching(
        self, cursor, artist_name: str, playlist_names: list[str], placeholders: str
    ) -> bool:
        """Legacy path: Filename matching for M3U playlists"""
        logging.debug("VDJ hasartist: using legacy filename matching")
        # Get playlist filenames
        filename_sql = f"SELECT DISTINCT filename FROM playlists WHERE name IN ({placeholders})"
        await cursor.execute(filename_sql, playlist_names)
        rows = await cursor.fetchall()
        playlist_filenames = {row["filename"] for row in rows if row["filename"]}

        if not playlist_filenames:
            return False

        # Check songs database for filename matches
        async with aiosqlite.connect(self.songs_databasefile) as songs_conn:
            songs_conn.row_factory = sqlite3.Row
            songs_cursor = await songs_conn.cursor()

            filename_placeholders = ",".join("?" * len(playlist_filenames))
            songs_sql = f"""
                SELECT COUNT(*) as count FROM songs
                WHERE LOWER(artist) = LOWER(?) AND filename IN ({filename_placeholders})
            """
            params = [artist_name] + list(playlist_filenames)
            await songs_cursor.execute(songs_sql, params)
            row = await songs_cursor.fetchone()

            result = row and row["count"] > 0
            logging.debug(
                "VDJ hasartist: legacy path found %d matches, returning %s",
                row["count"] if row else 0,
                result,
            )
            return result

    def defaults(self, qsettings):
        """(re-)set the default configuration values for this plugin"""
        vdjdir = self.config.userdocs.joinpath("VirtualDJ")
        qsettings.setValue("virtualdj/history", str(vdjdir.joinpath("History")))
        qsettings.setValue("virtualdj/playlists", str(vdjdir.joinpath("Playlists")))
        qsettings.setValue("virtualdj/useremix", True)
        qsettings.setValue("virtualdj/max_age_days", 7)
        qsettings.setValue("virtualdj/artist_query_scope", "entire_library")
        qsettings.setValue("virtualdj/selected_playlists", "")

    def on_playlist_reread_button(self):
        """user clicked re-read collections - trigger background refresh"""
        # Trigger both XML songs and M3U playlists refresh
        logging.info("Manual VirtualDJ database refresh requested")
        self.config.cparser.setValue("virtualdj/rebuild_db", True)
        self.config.cparser.setValue("virtualdj/rebuild_playlists_db", True)

    def on_playlistdir_button(self):
        """filename button clicked action"""
        startdir = self.qwidget.playlistdir_lineedit.text() or str(
            self.config.userdocs.joinpath("VirtualDJ")
        )
        if filename := QFileDialog.getExistingDirectory(
            self.qwidget, "Select directory", startdir
        ):
            self.qwidget.playlistdir_lineedit.setText(filename)

    def on_history_dir_button(self):
        """filename button clicked action"""
        if self.qwidget.historydir_lineedit.text():
            startdir = self.qwidget.historydir_lineedit.text()
        else:
            startdir = str(self.config.userdocs.joinpath("VirtualDJ", "History"))
        if dirname := QFileDialog.getExistingDirectory(self.qwidget, "Select directory", startdir):
            self.qwidget.historydir_lineedit.setText(dirname)

    def connect_settingsui(self, qwidget, uihelp):
        """connect m3u button to filename picker"""
        self.qwidget = qwidget
        self.uihelp = uihelp
        qwidget.historydir_button.clicked.connect(self.on_history_dir_button)
        qwidget.playlistdir_button.clicked.connect(self.on_playlistdir_button)
        qwidget.playlist_reread_button.clicked.connect(self.on_playlist_reread_button)

    def load_settingsui(self, qwidget):
        """draw the plugin's settings page"""
        qwidget.historydir_lineedit.setText(self.config.cparser.value("virtualdj/history"))
        qwidget.playlistdir_lineedit.setText(self.config.cparser.value("virtualdj/playlists"))
        qwidget.remix_checkbox.setChecked(
            self.config.cparser.value("virtualdj/useremix", type=bool, defaultValue=True)
        )
        qwidget.virtualdj_max_age_spinbox.setValue(
            self.config.cparser.value("virtualdj/max_age_days", type=int, defaultValue=7)
        )

        # Set artist query scope
        scope = self.config.cparser.value(
            "virtualdj/artist_query_scope", defaultValue="entire_library"
        )
        if scope == "selected_playlists":
            qwidget.virtualdj_artist_scope_combo.setCurrentText("Selected Playlists")
        else:
            qwidget.virtualdj_artist_scope_combo.setCurrentText("Entire Library")

        # Load selected playlists
        qwidget.virtualdj_playlists_lineedit.setText(
            self.config.cparser.value("virtualdj/selected_playlists", defaultValue="")
        )

    def verify_settingsui(self, qwidget):
        """verify settings"""
        if not os.path.exists(qwidget.historydir_lineedit.text()):
            raise PluginVerifyError(r"Virtual DJ History directory must exist.")
        if not os.path.exists(qwidget.playlistdir_lineedit.text()):
            raise PluginVerifyError(r"Virtual DJ Playlists directory must exist.")

    def save_settingsui(self, qwidget):
        """take the settings page and save it"""
        self.config.cparser.setValue("virtualdj/history", qwidget.historydir_lineedit.text())
        self.config.cparser.setValue("virtualdj/playlists", qwidget.playlistdir_lineedit.text())
        self.config.cparser.setValue("virtualdj/useremix", qwidget.remix_checkbox.isChecked())
        self.config.cparser.setValue(
            "virtualdj/max_age_days", qwidget.virtualdj_max_age_spinbox.value()
        )

        # Save artist query scope
        scope = (
            "selected_playlists"
            if qwidget.virtualdj_artist_scope_combo.currentText() == "Selected Playlists"
            else "entire_library"
        )
        self.config.cparser.setValue("virtualdj/artist_query_scope", scope)

        # Save selected playlists
        self.config.cparser.setValue(
            "virtualdj/selected_playlists", qwidget.virtualdj_playlists_lineedit.text()
        )

    def desc_settingsui(self, qwidget):
        """description"""
        qwidget.setText("For Virtual DJ Support")
