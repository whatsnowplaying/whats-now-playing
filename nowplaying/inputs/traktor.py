#!/usr/bin/env python3
"""Traktor-specific support"""

import asyncio
import logging
import logging.config
import os
import pathlib
import sqlite3
import xml.sax
from typing import TYPE_CHECKING

import aiosqlite  # pylint: disable=import-error
from PySide6.QtCore import QStandardPaths  # pylint: disable=import-error, no-name-in-module
from PySide6.QtWidgets import QFileDialog  # pylint: disable=import-error, no-name-in-module

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": True,
    }
)

# pylint: disable=wrong-import-position

import nowplaying.utils.xml
from nowplaying.db import LISTFIELDS
from nowplaying.exceptions import PluginVerifyError

from .icecast import Plugin as IcecastPlugin

if TYPE_CHECKING:
    import nowplaying.config

METADATALIST = ["artist", "title", "album", "filename"]

PLAYLIST = ["name", "filename"]


class TraktorSAXHandler(xml.sax.ContentHandler):
    """SAX handler for streaming Traktor XML parsing"""

    def __init__(self, sqlcursor: sqlite3.Cursor):
        super().__init__()
        self.sqlcursor = sqlcursor
        self.current_element = None
        self.current_entry = {}
        self.current_playlist = None
        self.in_collection = False
        self.in_playlists = False

    def startElement(  # pylint: disable=too-many-branches
        self, name: str, attrs: dict[str, str]
    ) -> None:
        self.current_element = name

        if name == "COLLECTION":
            self.in_collection = True
        elif name == "PLAYLISTS":
            self.in_playlists = True
        elif name == "ENTRY" and self.in_collection:
            # Start of a new track entry in COLLECTION
            self.current_entry = {
                "artist": attrs.get("ARTIST"),
                "title": attrs.get("TITLE"),
                "album": None,
                "filename": None,
            }
        elif name == "ALBUM" and self.in_collection:
            if self.current_entry is not None:
                self.current_entry["album"] = attrs.get("TITLE")
        elif name == "LOCATION" and self.in_collection:
            if self.current_entry is not None:
                try:
                    volume = attrs.get("VOLUME", "")
                    filename = ""
                    if len(volume) >= 2 and volume[0].isalpha() and volume[1] == ":":
                        filename = volume
                    dir_part = attrs.get("DIR", "")
                    file_part = attrs.get("FILE", "")
                    if dir_part or file_part:  # Only process if we have path components
                        filename += dir_part.replace("/:", "/") + file_part
                        self.current_entry["filename"] = filename
                except (AttributeError, TypeError) as err:
                    logging.warning("Malformed LOCATION element in Traktor XML: %s", err)
        elif name == "NODE" and self.in_playlists and attrs.get("TYPE") == "PLAYLIST":
            # Playlist node
            self.current_playlist = attrs.get("NAME")
        elif name == "PRIMARYKEY" and self.in_playlists and self.current_playlist:
            # Handle playlist entries
            try:
                key = attrs.get("KEY", "")
                if key and isinstance(key, str):
                    filepathcomps = key.split("/:")
                    if len(filepathcomps) > 1:
                        # Create absolute path using pathlib for cross-platform compatibility
                        # Skip the volume name (first component) and join the rest as absolute path
                        if os.name == "nt":
                            # On Windows, assume C: drive if no explicit drive letter
                            filename = str(pathlib.Path("C:").joinpath(*filepathcomps[1:]))
                        else:
                            # On Unix-like systems, use root
                            filename = str(pathlib.Path("/").joinpath(*filepathcomps[1:]))
                        sql = "INSERT INTO playlists (name,filename) VALUES (?,?)"
                        self.sqlcursor.execute(sql, (self.current_playlist, filename))
            except (AttributeError, TypeError, ValueError, sqlite3.Error) as err:
                logging.warning("Malformed PRIMARYKEY element in Traktor XML: %s", err)

    def endElement(self, name: str) -> None:
        if name == "COLLECTION":
            self.in_collection = False
        elif name == "PLAYLISTS":
            self.in_playlists = False
        elif name == "ENTRY" and self.in_collection and self.current_entry:
            # End of track entry - insert into database
            try:
                metadata = self.current_entry
                if metadata.get("artist") and metadata.get("title"):
                    sql = "INSERT INTO songs ("
                    sql += ", ".join(metadata.keys()) + ") VALUES ("
                    sql += "?," * (len(metadata.keys()) - 1) + "?)"
                    datatuple = tuple(metadata.values())
                    self.sqlcursor.execute(sql, datatuple)
            except (sqlite3.Error, ValueError, TypeError) as err:
                logging.warning("Failed to insert track entry from Traktor XML: %s", err)
            finally:
                self.current_entry = {}
        elif name == "NODE" and self.in_playlists:
            if self.current_playlist:
                self.current_playlist = None


class Plugin(IcecastPlugin):
    """base class of input plugins"""

    def __init__(self, config: "nowplaying.config.ConfigFile | None" = None, qsettings=None):
        """no custom init"""
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Traktor"
        self.databasefile = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]
        ).joinpath("traktor", "traktor.db")
        self.xml_processor = None
        self.tasks = set()

    def install(self):
        """auto-install for Icecast"""
        nidir = self.config.userdocs.joinpath("Native Instruments")
        if nidir.exists():
            for entry in os.scandir(nidir):
                if entry.is_dir() and "Traktor" in entry.name:
                    cmlpath = pathlib.Path(entry).joinpath("collection.nml")
                    if cmlpath.exists():
                        self.config.cparser.value("traktor/collections", str(cmlpath))
                        self.config.cparser.value("settings/input", "traktor")
                        self.config.cparser.value("traktor/port", 8000)
                        return True

        return False

    def defaults(self, qsettings):
        """(re-)set the default configuration values for this plugin"""
        qsettings.setValue("traktor/port", "8000")
        qsettings.setValue("traktor/max_age_days", 7)
        qsettings.setValue("traktor/artist_query_scope", "entire_library")
        qsettings.setValue("traktor/selected_playlists", "")
        nidir = self.config.userdocs.joinpath("Native Instruments")
        if nidir.exists():
            if collist := list(nidir.glob("**/collection.nml")):
                collist.sort(key=lambda x: x.stat().st_mtime)
                qsettings.setValue("traktor/collections", str(collist[-1]))

    def connect_settingsui(self, qwidget, uihelp):
        """connect any UI elements such as buttons"""
        self.qwidget = qwidget
        self.uihelp = uihelp
        self.qwidget.traktor_browse_button.clicked.connect(self._on_traktor_browse_button)
        self.qwidget.traktor_rebuild_button.clicked.connect(self._on_traktor_rebuild_button)

    def _on_traktor_browse_button(self):
        """user clicked traktor browse button"""
        startdir = self.qwidget.traktor_collection_lineedit.text() or str(
            self.config.userdocs.joinpath("Native Instruments")
        )
        if filename := QFileDialog.getOpenFileName(
            self.qwidget, "Open collection file", startdir, "*.nml"
        ):
            self.qwidget.traktor_collection_lineedit.setText(filename[0])

    def _on_traktor_rebuild_button(self):
        """user clicked re-read collections - trigger background refresh"""
        logging.info("Manual Traktor database refresh requested")
        self.config.cparser.setValue("traktor/rebuild_db", True)

    def load_settingsui(self, qwidget):
        """load values from config and populate page"""
        qwidget.port_lineedit.setText(self.config.cparser.value("traktor/port"))
        qwidget.traktor_collection_lineedit.setText(
            self.config.cparser.value("traktor/collections")
        )
        qwidget.traktor_max_age_spinbox.setValue(
            self.config.cparser.value("traktor/max_age_days", type=int, defaultValue=7)
        )

        # Set artist query scope
        scope = self.config.cparser.value(
            "traktor/artist_query_scope", defaultValue="entire_library"
        )
        if scope == "selected_playlists":
            qwidget.traktor_artist_scope_combo.setCurrentText("Selected Playlists")
        else:
            qwidget.traktor_artist_scope_combo.setCurrentText("Entire Library")

        # Load selected playlists
        qwidget.traktor_playlists_lineedit.setText(
            self.config.cparser.value("traktor/selected_playlists", defaultValue="")
        )

    def verify_settingsui(self, qwidget):  # pylint: disable=no-self-use
        """verify the values in the UI prior to saving"""
        filename = qwidget.traktor_collection_lineedit.text()
        if not filename:
            raise PluginVerifyError("Traktor collections.nml is not set.")
        filepath = pathlib.Path(filename)
        if not filepath.exists():
            raise PluginVerifyError("Traktor collections.nml does not exist.")

    def save_settingsui(self, qwidget):
        """take the settings page and save it"""
        self.config.cparser.setValue("traktor/port", qwidget.port_lineedit.text())
        self.config.cparser.setValue(
            "traktor/collections", qwidget.traktor_collection_lineedit.text()
        )
        self.config.cparser.setValue(
            "traktor/max_age_days", qwidget.traktor_max_age_spinbox.value()
        )

        # Save artist query scope
        scope = (
            "selected_playlists"
            if qwidget.traktor_artist_scope_combo.currentText() == "Selected Playlists"
            else "entire_library"
        )
        self.config.cparser.setValue("traktor/artist_query_scope", scope)

        # Save selected playlists
        self.config.cparser.setValue(
            "traktor/selected_playlists", qwidget.traktor_playlists_lineedit.text()
        )

    def desc_settingsui(self, qwidget):
        """provide a description for the plugins page"""
        qwidget.setText("Support for Native Instruments Traktor.")

    def initdb(self):
        """initialize the db"""
        if not self.databasefile.exists():
            self.config.cparser.setValue("traktor/rebuild_db", True)

    async def lookup(self, artist: str | None = None, title: str | None = None):
        """lookup the metadata"""
        async with aiosqlite.connect(self.databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            try:
                await cursor.execute(
                    """SELECT * FROM songs WHERE artist=? AND title=? ORDER BY id DESC LIMIT 1""",
                    (
                        artist,
                        title,
                    ),
                )
            except sqlite3.OperationalError:
                return None

            row = await cursor.fetchone()
            if not row:
                return None

        metadata = {data: row[data] for data in METADATALIST}
        for key in LISTFIELDS:
            if metadata.get(key):
                metadata[key] = [row[key]]
        return metadata

    #### Data feed methods

    async def getplayingtrack(self):
        """give back the metadata global"""
        icmetadata = await super().getplayingtrack()
        if self.lastmetadata.get("artist") == icmetadata.get("artist") and self.lastmetadata.get(
            "title"
        ) == icmetadata.get("title"):
            return self.lastmetadata

        metadata = None
        if icmetadata.get("artist") and icmetadata.get("title"):
            metadata = await self.lookup(artist=icmetadata["artist"], title=icmetadata["title"])
        if not metadata:
            metadata = icmetadata
        self.lastmetadata = metadata
        return metadata

    async def getrandomtrack(self, playlist: str):
        """return the contents of a playlist"""
        async with aiosqlite.connect(self.databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            try:
                await cursor.execute(
                    """SELECT filename FROM playlists WHERE name=? ORDER BY random() LIMIT 1""",
                    (playlist,),
                )
            except sqlite3.OperationalError:
                return None

            row = await cursor.fetchone()
            if not row:
                return None

            return str(row["filename"])

    #### Control methods

    async def start(self):
        """any initialization before actual polling starts"""
        # Prevent multiple background tasks
        if self.tasks:
            logging.debug("Traktor background tasks already running, skipping start()")
            return

        # Start background XML refresh task
        def get_traktor_xml():
            collectionsfile = self.config.cparser.value("traktor/collections")
            return pathlib.Path(collectionsfile) if collectionsfile else None

        table_schemas = [
            "CREATE TABLE IF NOT EXISTS songs "
            f"({', '.join(f'{field} TEXT' for field in METADATALIST)},"
            " id INTEGER PRIMARY KEY AUTOINCREMENT)",
            "CREATE TABLE IF NOT EXISTS playlists "
            f"({', '.join(f'{field} TEXT' for field in PLAYLIST)},"
            " id INTEGER PRIMARY KEY AUTOINCREMENT)",
        ]

        self.xml_processor = nowplaying.utils.xml.BackgroundXMLProcessor(
            self.databasefile,
            TraktorSAXHandler,
            get_traktor_xml,
            table_schemas,
            "traktor",
            self.config,
        )

        # Reset shutdown event if it was set from a previous instance
        self.xml_processor.reset_shutdown_event()

        task = asyncio.create_task(self.xml_processor.background_refresh_loop())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

        port = self.config.cparser.value("traktor/port", type=int, defaultValue=8000)
        await self.start_port(port)

    async def stop(self):
        """stop the traktor plugin"""
        await super().stop()

        # Signal XML processor shutdown
        if self.xml_processor:
            self.xml_processor.shutdown()

        if self.tasks:
            for task in self.tasks:
                task.cancel()
            # Wait for all cancelled tasks to complete cleanup
            await asyncio.gather(*self.tasks, return_exceptions=True)

    async def has_tracks_by_artist(self, artist_name: str) -> bool:
        """Check if DJ has any tracks by the specified artist"""
        try:
            scope = self.config.cparser.value(
                "traktor/artist_query_scope", defaultValue="entire_library"
            )

            async with aiosqlite.connect(self.databasefile) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()

                if scope == "selected_playlists":
                    # Query specific playlists
                    selected_playlists = self.config.cparser.value(
                        "traktor/selected_playlists", defaultValue=""
                    )
                    if not selected_playlists.strip():
                        return False

                    playlist_names = [
                        name.strip() for name in selected_playlists.split(",") if name.strip()
                    ]
                    if not playlist_names:
                        return False

                    # Create placeholders for playlist names
                    placeholders = ",".join("?" * len(playlist_names))
                    sql = f"""
                        SELECT COUNT(*) as count
                        FROM songs s
                        JOIN playlists p ON s.filename = p.filename
                        WHERE LOWER(s.artist) = LOWER(?) AND p.name IN ({placeholders})
                    """
                    params = [artist_name] + playlist_names
                    await cursor.execute(sql, params)
                else:
                    # Query entire library
                    await cursor.execute(
                        "SELECT COUNT(*) as count FROM songs WHERE LOWER(artist) = LOWER(?)",
                        (artist_name,),
                    )

                row = await cursor.fetchone()
                return row["count"] > 0 if row else False

        except sqlite3.OperationalError as err:
            logging.error("Failed to query Traktor database for artist %s: %s", artist_name, err)
            return False
