#!/usr/bin/env python3
"""routines to read/write the metadb"""

import copy
import logging
import os
import pathlib
import sys
import sqlite3
import time
from typing import TYPE_CHECKING, Any

import aiosqlite

import watchdog.observers.api  # pylint: disable=import-error, no-name-in-module
from watchdog.observers import Observer  # pylint: disable=import-error
from watchdog.events import PatternMatchingEventHandler  # pylint: disable=import-error

from PySide6.QtCore import QStandardPaths  # pylint: disable=import-error, no-name-in-module

if TYPE_CHECKING:
    from nowplaying.types import TrackMetadata
    import nowplaying.config

SPLITSTR = "@@SPLITHERE@@"

METADATALIST = [
    "acoustidid",
    "album",
    "albumartist",
    "artist",
    "artistwebsites",
    "artistlongbio",
    "artistshortbio",
    "bitrate",
    "bpm",
    "comments",
    "composer",
    "coverurl",
    "date",
    "deck",
    "disc",
    "disc_total",
    "discsubtitle",
    "duration",
    "duration_hhmmss",
    "filename",
    "fpcalcduration",
    "fpcalcfingerprint",
    "genre",
    "genres",
    "hostfqdn",
    "hostip",
    "hostname",
    "httpport",
    "isrc",
    "key",
    "label",
    "lang",
    "musicbrainzalbumid",
    "musicbrainzartistid",
    "musicbrainzrecordingid",
    "imagecacheartist",
    "imagecachealbum",
    "requestdisplayname",
    "requester",
    "title",
    "track",
    "track_total",
]

LISTFIELDS = [
    "artistwebsites",
    "genres",
    "isrc",
    "musicbrainzalbumid",
    "musicbrainzartistid",
]

# NOTE: artistfanartraw is never actually stored in this DB
# but putting it here triggers side-effects to force it to be
# treated as binary
METADATABLOBLIST = [
    "artistbannerraw",
    "artistfanartraw",
    "artistlogoraw",
    "artistthumbnailraw",
    "coverimageraw",
    "requesterimageraw",
]


class DBWatcher:
    """utility to watch for database changes"""

    def __init__(self, databasefile: str | pathlib.Path):
        self.observer: watchdog.observers.api.BaseObserver | None = None
        self.event_handler: PatternMatchingEventHandler | None = None
        self.updatetime: float = time.time()
        self.databasefile: str = str(databasefile)  # Convert to string for os.path functions
        self.callback: Any = None

    def start(self, customhandler=None):
        """fire up the watcher"""
        logging.debug("Asked for a DB watcher")
        directory = os.path.dirname(self.databasefile)
        filename = os.path.basename(self.databasefile)
        logging.info("Watching for changes on %s", self.databasefile)
        self.event_handler = PatternMatchingEventHandler(
            patterns=[filename],
            ignore_patterns=[".DS_Store"],
            ignore_directories=True,
            case_sensitive=False,
        )
        if not customhandler:
            self.event_handler.on_modified = self.update_time
            self.event_handler.on_created = self.update_time
        else:
            self.event_handler.on_modified = customhandler
            self.event_handler.on_created = customhandler
        self.observer = Observer()
        self.observer.schedule(self.event_handler, directory, recursive=False)
        self.observer.start()

    def update_time(self, event):  # pylint: disable=unused-argument
        """just need to update the time"""
        self.updatetime = time.time()

    def _set_callback(self, discardcallable):
        self.callback = discardcallable

    def stop(self):
        """stop the watcher"""
        logging.debug("watcher asked to stop")
        if self.observer:
            logging.debug("calling stop")
            self.observer.stop()
            logging.debug("calling join")
            self.observer.join()
            self.observer = None
        if self.callback:
            self.callback(self)

    def __del__(self):
        self.stop()


class MetadataDB:
    """Metadata DB module"""

    def __init__(self, databasefile: str | pathlib.Path | None = None, initialize: bool = False):
        self.watchers: set[DBWatcher] = set()

        self.databasefile: pathlib.Path = self.init_db_var(databasefile=databasefile)
        logging.debug("Metadata DB at %s", self.databasefile)
        if not self.databasefile.exists() or initialize:
            logging.debug("Setting up a new DB")
            self.setupsql()

    @staticmethod
    def init_db_var(databasefile: str | pathlib.Path | None) -> pathlib.Path:
        """split this out to make testing easier"""
        if os.environ.get("WNP_METADB_TEST_FILE"):
            return pathlib.Path(os.environ["WNP_METADB_TEST_FILE"])
        if databasefile:
            return pathlib.Path(databasefile)
        return pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]
        ).joinpath("metadb", "npsql.db")

    def watcher(self):
        """get access to a watch on the database file"""
        watcher = DBWatcher(self.databasefile)
        self.watchers.add(watcher)
        watcher._set_callback(self.watchers.discard)  # pylint: disable=protected-access
        return watcher

    def __del__(self):
        for watcher in copy.copy(self.watchers):
            logging.exception("Clearing leftover watcher")
            watcher.stop()

    async def write_to_metadb(self, metadata: "TrackMetadata | None" = None) -> None:
        """update metadb"""

        def filterkeys(mydict: dict[str, Any]) -> dict[str, Any]:
            return {key: mydict[key] for key in METADATALIST + METADATABLOBLIST if key in mydict}

        logging.debug("Called (async) write_to_metadb")
        if metadata is None:
            logging.debug("metadata is None")
            return
        if not metadata or not METADATALIST or "title" not in metadata or "artist" not in metadata:
            logging.debug("metadata is either empty or too incomplete")
            return

        if not self.databasefile.exists():
            self.setupsql()

        async with aiosqlite.connect(self.databasefile, timeout=10) as connection:
            # do not want to modify the original dictionary
            # otherwise Bad Things(tm) will happen
            mdcopy: dict[str, Any] = copy.deepcopy(dict(metadata))
            mdcopy["artistfanartraw"] = None

            # toss any keys we do not care about
            mdcopy = filterkeys(mdcopy)

            cursor = await connection.cursor()

            logging.debug("Adding record with %s/%s", mdcopy["artist"], mdcopy["title"])

            for key in METADATABLOBLIST:
                if key not in mdcopy:
                    mdcopy[key] = None

            for data in mdcopy:
                if isinstance(mdcopy[data], list):
                    mdcopy[data] = SPLITSTR.join(mdcopy[data])
                if isinstance(mdcopy[data], str) and len(mdcopy[data]) == 0:
                    mdcopy[data] = None

            sql = "INSERT INTO currentmeta ("
            sql += ", ".join(mdcopy.keys()) + ") VALUES ("
            sql += "?," * (len(mdcopy.keys()) - 1) + "?)"

            datatuple = tuple(list(mdcopy.values()))
            await cursor.execute(sql, datatuple)
            await connection.commit()

    def make_previoustracklist(self) -> list[dict[str, str]] | None:
        """create a reversed list of the tracks played"""

        if not self.databasefile.exists():
            logging.error("MetadataDB does not exist yet?")
            return None

        with sqlite3.connect(self.databasefile, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute("""SELECT artist, title FROM currentmeta ORDER BY id DESC""")
            except sqlite3.OperationalError:
                return None

            records = cursor.fetchall()

        previouslist = []
        if records:
            previouslist.extend(
                {"artist": row["artist"], "title": row["title"]} for row in records
            )

        return previouslist

    async def make_previoustracklist_async(self) -> list[dict[str, str]] | None:
        """create a reversed list of the tracks played"""

        if not self.databasefile.exists():
            logging.error("MetadataDB does not exist yet?")
            return None

        async with aiosqlite.connect(self.databasefile, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            try:
                await cursor.execute("""SELECT artist, title FROM currentmeta ORDER BY id DESC""")
            except sqlite3.OperationalError:
                return None

            records = await cursor.fetchall()
            await connection.commit()

        previouslist = []
        if records:
            previouslist.extend(
                {"artist": row["artist"], "title": row["title"]} for row in records
            )

        return previouslist

    @staticmethod
    def _postprocess_read_last_meta(row: sqlite3.Row) -> "TrackMetadata":
        """common post-process of read_last_meta"""
        metadata: dict[str, Any] = {data: row[data] for data in METADATALIST}
        for key in METADATABLOBLIST:
            metadata[key] = row[key]
            if not metadata[key]:
                del metadata[key]

        for key in LISTFIELDS:
            metadata[key] = row[key]
            if metadata[key]:
                metadata[key] = metadata[key].split(SPLITSTR)

        metadata["dbid"] = row["id"]
        return metadata  # type: ignore[return-value]

    async def read_last_meta_async(self) -> "TrackMetadata | None":
        """update metadb"""

        if not self.databasefile.exists():
            logging.error("MetadataDB does not exist yet?")
            return None

        async with aiosqlite.connect(self.databasefile, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            try:
                await cursor.execute("""SELECT * FROM currentmeta ORDER BY id DESC LIMIT 1""")
            except sqlite3.OperationalError as err:
                logging.exception("SQLite3 error: %s", err)
                return None

            row = await cursor.fetchone()
            await cursor.close()
            await connection.commit()

            if not row:
                return None

        metadata = self._postprocess_read_last_meta(row)
        metadata["previoustrack"] = await self.make_previoustracklist_async()  # type: ignore[misc]
        return metadata

    def read_last_meta(self) -> "TrackMetadata | None":
        """update metadb"""

        if not self.databasefile.exists():
            logging.error("MetadataDB does not exist yet?")
            return None

        with sqlite3.connect(self.databasefile, timeout=10) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute("""SELECT * FROM currentmeta ORDER BY id DESC LIMIT 1""")
            except sqlite3.OperationalError as err:
                logging.exception("SQLite3 error: %s", err)
                return None

            row = cursor.fetchone()
            if not row:
                return None

        metadata = self._postprocess_read_last_meta(row)
        metadata["previoustrack"] = self.make_previoustracklist()  # type: ignore[misc]
        return metadata

    def setupsql(self):
        """setup the default database"""

        if not self.databasefile:
            logging.error("No dbfile")
            sys.exit(1)

        self.databasefile.parent.mkdir(parents=True, exist_ok=True)
        if self.databasefile.exists():
            logging.info("Clearing cache file %s", self.databasefile)
            os.unlink(self.databasefile)

        with sqlite3.connect(self.databasefile, timeout=10) as connection:
            cursor = connection.cursor()

            sql = "CREATE TABLE currentmeta (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            sql += " TEXT, ".join(METADATALIST) + " TEXT, "
            sql += " BLOB, ".join(METADATABLOBLIST) + " BLOB)"

            cursor.execute(sql)
            logging.debug("Cache db file created")


def create_setlist(
    config: "nowplaying.config.ConfigFile | None" = None, databasefile: str | None = None
) -> None:
    """create the setlist"""

    if not config:
        logging.debug("config=%s / databasefile=%s", config is None, databasefile)
        return

    datestr = time.strftime("%Y%m%d-%H%M%S")
    setlistpath = pathlib.Path(config.getsetlistdir())
    logging.debug("setlistpath = %s", setlistpath)
    metadb = MetadataDB(databasefile=databasefile, initialize=False)
    metadata = metadb.read_last_meta()
    if not metadata:
        logging.info("No tracks were played; not saving setlist")
        return

    previoustrack = metadata["previoustrack"]  # type: ignore[misc]
    if not previoustrack:
        logging.info("No previoustracks were played; not saving setlist")
        return

    for track in previoustrack:
        if not track.get("artist"):
            track["artist"] = ""

    for track in previoustrack:
        if not track.get("title"):
            track["title"] = ""

    previoustrack.reverse()

    setlistfn = setlistpath.joinpath(f"{datestr}.md")
    max_artist_size = max(len(trk.get("artist", "")) for trk in previoustrack)
    max_title_size = max(len(trk.get("title", "")) for trk in previoustrack)

    max_artist_size = max(max_artist_size, len("ARTIST"))
    max_title_size = max(max_title_size, len("TITLE"))

    setlistpath.mkdir(parents=True, exist_ok=True)
    logging.info("Creating %s", setlistfn)
    with open(setlistfn, "w", encoding="utf-8") as fileh:
        fileh.writelines(f"| {'ARTIST':{max_artist_size}} | {'TITLE':{max_title_size}} |\n")
        fileh.writelines(f"|:{'-':-<{max_artist_size}} |:{'-':-<{max_title_size}} |\n")

        for track in previoustrack:
            fileh.writelines(
                f"| {track['artist']:{max_artist_size}} | {track['title']:{max_title_size}} |\n"
            )
