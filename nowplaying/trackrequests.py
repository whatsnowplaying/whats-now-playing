#!/usr/bin/env python3
"""request handling"""
# pylint: disable=too-many-lines

import asyncio
import logging
import pathlib
import re
import sqlite3
import time
import typing as t
from collections.abc import Iterable
from typing import TYPE_CHECKING

import aiohttp
import aiosqlite

# Optional rapidfuzz import - gracefully handle missing vcredist on Windows
try:
    import rapidfuzz

    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

from PySide6.QtCore import (  # pylint: disable=import-error, no-name-in-module
    QFile,
    QFileSystemWatcher,
    QSettings,
    QStandardPaths,
    Slot,
)
from PySide6.QtUiTools import QUiLoader  # pylint: disable=import-error, no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=import-error, no-name-in-module
    QComboBox,
    QHeaderView,
    QTableWidgetItem,
    QWidget,
)

import nowplaying.db
import nowplaying.metadata
import nowplaying.utils
import nowplaying.utils.sqlite
from nowplaying.exceptions import PluginVerifyError
from nowplaying.types import (  # pylint: disable=import-error
    GifWordsTrackRequest,
    TrackMetadata,
    TrackRequestResult,
    TrackRequestSetting,
    UserTrackRequest,
)

if TYPE_CHECKING:
    import nowplaying.config
    import nowplaying.uihelp


USERREQUEST_TEXT = [
    "artist",
    "title",
    "displayname",
    "type",
    "playlist",
    "username",
    "filename",
    "user_input",
    "normalizedartist",
    "normalizedtitle",
]

USERREQUEST_BLOB = ["userimage"]

REQUEST_WINDOW_FIELDS = [
    "artist",
    "title",
    "type",
    "playlist",
    "username",
    "filename",
    "timestamp",
    "reqid",
]

REQUEST_SETTING_MAPPING = {
    "command": "Chat Command",
    "twitchtext": "Twitch Text",
    "type": "Type",
    "displayname": "Display Name",
    "playlist": "Playlist File",
}

ROULETTE_ARTIST_TEXT = ["playlist", "artist"]

RESPIN_TEXT = "RESPIN SCHEDULED"
"""
Auto-detected formats:

artist - title
artist - title for someone
artist - "title"
artist - "title" for someone
"title" - artist
"title" by artist for someone
"title"
artist

... and strips all excess whitespace

"""

WEIRDAL_RE = re.compile(r'"weird al"', re.IGNORECASE)
ARTIST_TITLE_RE = re.compile(r'^\s*(.*?)\s+[-]+\s+"?(.*?)"?\s*(for @.*)*$')
TITLE_ARTIST_RE = re.compile(r'^\s*"(.*?)"\s+[-by]+\s+(.*?)\s*(for @.*)*$')
TITLE_RE = re.compile(r'^\s*"(.*?)"\s*(for @.*)*$')
TWOFERTITLE_RE = re.compile(r'^\s*"?(.*?)"?\s*(for @.*)*$')

BASE_URL = "https://tenor.googleapis.com/v2/search"

GIFWORDS_TEXT = ["keywords", "requester", "requestdisplayname", "imageurl"]
GIFWORDS_BLOB = ["image"]


class Requests:  # pylint: disable=too-many-instance-attributes, too-many-public-methods
    """handle requests


    Note that different methods are being called by different parts of the system
    presently.  Should probably split them out between UI/non-UI if possible,
    since UI code can't call async code.

    """

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile|None" = None,
        stopevent: asyncio.Event | None = None,
        testmode: bool = False,
        upgrade: bool = False,
    ):
        self.config = config
        self.stopevent = stopevent
        self.testmode = testmode
        self.filelists = None
        self.databasefile = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]
        ).joinpath("requests", "request.db")
        self.widgets = None
        self.watcher = None
        if not self.databasefile.exists() or upgrade:
            self.setupdb()
        if not RAPIDFUZZ_AVAILABLE:
            logging.warning("rapidfuzz not available - fuzzy matching disabled")

    def setupdb(self):
        """setup the database file for keeping track of requests"""
        logging.debug("Setting up the database %s", self.databasefile)
        self.databasefile.parent.mkdir(parents=True, exist_ok=True)
        if self.databasefile.exists():
            for attempt in range(3):
                try:
                    self.databasefile.unlink()
                    break
                except OSError as error:
                    if attempt < 2:  # Don't sleep on the last attempt
                        time.sleep(0.5 * (attempt + 1))  # 0.5s, then 1.0s
                        continue
                    # Final attempt failed - continue without rotation rather than crash
                    logging.warning(
                        "Could not delete request.db after 3 attempts "
                        "(previous instance may still be shutting down): %s",
                        error,
                    )

        with nowplaying.utils.sqlite.sqlite_connection(
            self.databasefile, timeout=30
        ) as connection:
            cursor = connection.cursor()
            try:
                sql = (
                    "CREATE TABLE IF NOT EXISTS userrequest ("
                    + " TEXT COLLATE NOCASE, ".join(USERREQUEST_TEXT)
                    + " TEXT COLLATE NOCASE, "
                    + " BLOB, ".join(USERREQUEST_BLOB)
                    + " BLOB, "
                    " reqid INTEGER PRIMARY KEY AUTOINCREMENT,"
                    " timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
                )
                cursor.execute(sql)
                connection.commit()

                sql = (
                    "CREATE TABLE IF NOT EXISTS gifwords ("
                    + " TEXT COLLATE NOCASE, ".join(GIFWORDS_TEXT)
                    + " TEXT COLLATE NOCASE, "
                    + " BLOB, ".join(GIFWORDS_BLOB)
                    + " BLOB, "
                    " reqid INTEGER PRIMARY KEY AUTOINCREMENT,"
                    " timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
                )
                cursor.execute(sql)
                connection.commit()

            except sqlite3.OperationalError as error:
                logging.error(error)

    def vacuum_database(self):
        """Vacuum the requests database to reclaim space from deleted entries."""
        if not self.databasefile.exists():
            return
        try:
            with nowplaying.utils.sqlite.sqlite_connection(
                self.databasefile, timeout=30
            ) as connection:
                logging.debug("Vacuuming requests database...")
                connection.execute("VACUUM")
                connection.commit()
                logging.info("Requests database vacuumed successfully")
        except sqlite3.Error as error:
            logging.error("Database error during vacuum: %s", error)

    def clear_roulette_artist_dupes(self):
        """clear out artists from the roulette table"""
        with nowplaying.utils.sqlite.sqlite_connection(
            self.databasefile, timeout=30
        ) as connection:
            cursor = connection.cursor()
            try:
                sql = (
                    "CREATE TABLE IF NOT EXISTS rouletteartist ("
                    + " TEXT COLLATE NOCASE, ".join(ROULETTE_ARTIST_TEXT)
                    + " TEXT COLLATE NOCASE, "
                    " reqid INTEGER PRIMARY KEY AUTOINCREMENT,"
                    " timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
                )
                cursor.execute(sql)
                connection.commit()
                # if it did exist, then wipe it out
                sql = "DELETE FROM rouletteartist"
                cursor.execute(sql)
                connection.commit()
            except sqlite3.OperationalError as error:
                logging.error(error)

    async def add_roulette_dupelist(self, artist: str, playlist: str):
        """add a record to the dupe list"""
        if not self.databasefile.exists():
            logging.error("%s does not exist, refusing to add.", self.databasefile)
            return

        logging.debug("marking %s as played against %s", artist, playlist)
        sql = "INSERT INTO rouletteartist (artist,playlist) VALUES (?,?)"
        datatuple = (artist, playlist)
        async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            await cursor.execute(sql, datatuple)
            await connection.commit()

    async def get_roulette_dupe_list(self, playlist: str | None = None) -> Iterable[str] | None:
        """get the artist dupelist"""
        if not self.databasefile.exists():
            logging.error("%s does not exist, refusing to add.", self.databasefile)
            return

        sql = "SELECT artist FROM rouletteartist"
        async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = lambda cursor, row: row[0]
            cursor = await connection.cursor()
            try:
                if playlist:
                    sql += " WHERE playlist=?"
                    datatuple = (playlist,)
                    await cursor.execute(sql, datatuple)
                else:
                    await cursor.execute(sql)
                await connection.commit()
            except sqlite3.OperationalError as error:
                logging.error(error)
                return None

            dataset = await cursor.fetchall()
            if not dataset:
                return None
        return dataset

    @staticmethod
    def _normalize(text: str | None) -> str:
        """db normalize"""
        if text := nowplaying.utils.normalize(text, sizecheck=0, nospaces=True):
            return text
        return ""

    async def add_to_db(self, data: UserTrackRequest):
        """add an entry to the db"""
        if not self.databasefile.exists():
            logging.error("%s does not exist, refusing to add.", self.databasefile)
            return

        data["normalizedartist"] = self._normalize(data.get("artist", ""))
        data["normalizedtitle"] = self._normalize(data.get("title", ""))

        if data.get("reqid"):
            reqid = data["reqid"]
            del data["reqid"]
            del data["username"]
            del data["playlist"]
            del data["type"]
            del data["displayname"]
            sql = "UPDATE userrequest SET " + "= ? , ".join(data.keys())
            sql += "= ? WHERE reqid=? "
            datatuple = list(data.values()) + [reqid]
        else:
            sql = "INSERT OR REPLACE INTO userrequest ("
            sql += ", ".join(data.keys()) + ") VALUES ("
            sql += "?," * (len(data.keys()) - 1) + "?)"
            datatuple = tuple(list(data.values()))

        async def _do_add_to_db():
            logging.debug(
                "Request artist: >%s< / title: >%s< has made it to the requestdb",
                data.get("artist"),
                data.get("title"),
            )
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()
                await cursor.execute(sql, datatuple)
                await connection.commit()

        try:
            await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_add_to_db)
        except sqlite3.OperationalError:
            logging.exception("Failed to add to database after retries")

    async def add_to_gifwordsdb(self, data: GifWordsTrackRequest):
        """add an entry to the db"""
        if not self.databasefile.exists():
            logging.error("%s does not exist, refusing to add.", self.databasefile)
            return

        sql = "INSERT OR REPLACE INTO gifwords ("
        sql += ", ".join(data.keys()) + ") VALUES ("
        sql += "?," * (len(data.keys()) - 1) + "?)"
        datatuple = tuple(list(data.values()))

        try:
            logging.debug(
                "Request gifwords: >%s< / url: >%s< has made it to the requestdb",
                data.get("keywords"),
                data.get("imageurl"),
            )
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()
                await cursor.execute(sql, datatuple)
                await connection.commit()

        except sqlite3.OperationalError as error:
            logging.exception(error)

    def respin_a_reqid(self, reqid: int):
        """given a reqid, set to respin"""
        if not self.databasefile.exists():
            logging.error("%s does not exist, refusing to respin.", self.databasefile)
            return

        sql = "UPDATE userrequest SET filename=? WHERE reqid=?"
        with nowplaying.utils.sqlite.sqlite_connection(
            self.databasefile, timeout=30
        ) as connection:
            try:
                connection.row_factory = sqlite3.Row
                cursor = connection.cursor()
                datatuple = RESPIN_TEXT, reqid
                cursor.execute(sql, datatuple)
                connection.commit()
            except sqlite3.OperationalError as error:
                logging.error(error)

    def erase_id(self, reqid: int):
        """remove entry from requests"""
        if not self.databasefile.exists():
            logging.error("%s does not exist, refusing to erase.", self.databasefile)
            return

        def _do_erase():
            with nowplaying.utils.sqlite.sqlite_connection(
                self.databasefile, timeout=30, row_factory=sqlite3.Row
            ) as connection:
                cursor = connection.cursor()
                cursor.execute("DELETE FROM userrequest WHERE reqid=?;", (reqid,))
                connection.commit()

        try:
            nowplaying.utils.sqlite.retry_sqlite_operation(_do_erase)
        except sqlite3.OperationalError:
            logging.exception("Failed to erase request ID %s after retries", reqid)

    async def erase_gifwords_id(self, reqid: int):
        """remove entry from gifwords"""
        if not self.databasefile.exists():
            logging.error("%s does not exist, refusing to erase.", self.databasefile)
            return

        async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.cursor()
            try:
                await cursor.execute("DELETE FROM gifwords WHERE reqid=?;", (reqid,))
                await connection.commit()
            except sqlite3.OperationalError as error:
                logging.exception(error)

    async def _find_good_request(self, setting: TrackRequestSetting) -> TrackMetadata | None:
        artistdupes = await self.get_roulette_dupe_list(playlist=setting["playlist"])
        plugin = self.config.cparser.value("settings/input")
        tryagain = True
        counter = 10
        metadata = None
        while tryagain and counter > 0:
            counter -= 1
            roulette = await self.config.pluginobjs["inputs"][
                f"nowplaying.inputs.{plugin}"
            ].getrandomtrack(setting["playlist"])
            metadata = await nowplaying.metadata.MetadataProcessors(
                config=self.config
            ).getmoremetadata(metadata={"filename": roulette}, skipplugins=True)

            if not metadata:
                logging.error("Did not get any metadata from %s", roulette)
                continue

            if not artistdupes or (
                metadata.get("artist") and metadata["artist"] not in artistdupes
            ):
                tryagain = False
                await asyncio.sleep(0.5)
            if tryagain:
                logging.debug("Duped on %s. Retrying.", metadata["artist"])
        return metadata

    async def user_roulette_request(
        self, setting: TrackRequestSetting, user: str, user_input: str, reqid: int | None = None
    ) -> TrackRequestResult | None:
        """roulette request"""
        if not setting.get("playlist"):
            logging.error("%s does not have a playlist defined", setting.get("displayname"))
            return None

        logging.debug("%s requested roulette %s | %s", user, setting["playlist"], user_input)

        metadata = await self._find_good_request(setting)

        data = {
            "username": user,
            "artist": metadata.get("artist"),
            "filename": metadata["filename"],
            "title": metadata.get("title"),
            "type": "Roulette",
            "playlist": setting["playlist"],
            "displayname": setting.get("displayname"),
            "user_input": user_input,
            "userimage": setting.get("userimage"),
        }
        if reqid:
            data["reqid"] = reqid
        await self.add_to_db(data)
        return {"requester": user, "requestdisplayname": setting.get("displayname")}

    async def _get_and_del_request_lookup(
        self, sql: str, datatuple: tuple
    ) -> TrackRequestResult | None:
        """run sql for request"""
        if not self.databasefile.exists():
            logging.error("%s does not exist, refusing to lookup.", self.databasefile)
            return None

        async def _do_lookup():
            row_to_delete: int | None = None
            row_to_add_to_dupelist: list[str] | None = None
            result: TrackRequestResult | None = None
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()
                await cursor.execute(sql, datatuple)
                row = await cursor.fetchone()
                if row:
                    row_to_delete = row["reqid"]
                    if row["type"] == "Roulette":
                        row_to_add_to_dupelist = [
                            row["artist"],
                            row["playlist"],
                        ]
                    result = {
                        "requester": row["username"],
                        "requesterimageraw": row["userimage"],
                        "requestdisplayname": row["displayname"],
                    }
            return result, row_to_delete, row_to_add_to_dupelist

        try:
            (
                result,
                row_to_delete,
                row_to_add_to_dupelist,
            ) = await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_lookup)

            # Delete the row after closing the async connection to avoid database locks
            if row_to_delete is not None:
                self.erase_id(row_to_delete)
            if row_to_add_to_dupelist is not None:
                await self.add_roulette_dupelist(
                    row_to_add_to_dupelist[0], row_to_add_to_dupelist[1]
                )

            return result
        except Exception as error:  # pylint: disable=broad-except
            logging.exception(error)
        return None

    async def _request_lookup_by_artist_title(
        self, artist: str = "", title: str = ""
    ) -> TrackRequestResult | None:
        """perform lookups in the request DB using exact, normalized, and fuzzy matching"""
        logging.debug("trying artist >%s< / title >%s<", artist, title)

        # Try exact matching first
        sql = "SELECT * FROM userrequest WHERE artist=? AND title=?"
        datatuple = artist, title
        logging.debug("request db lookup (exact): %s", datatuple)
        newdata = await self._get_and_del_request_lookup(sql, datatuple)

        if not newdata:
            # Try normalized matching
            normalized_artist = self._normalize(artist)
            normalized_title = self._normalize(title)
            logging.debug(
                "trying normalized artist >%s< / title >%s<", normalized_artist, normalized_title
            )
            sql = "SELECT * FROM userrequest WHERE normalizedartist=? AND normalizedtitle=?"
            datatuple = normalized_artist, normalized_title
            logging.debug("request db lookup (normalized): %s", datatuple)
            newdata = await self._get_and_del_request_lookup(sql, datatuple)

        if not newdata and RAPIDFUZZ_AVAILABLE:
            # Try fuzzy matching as final fallback (only if rapidfuzz is available)
            newdata = await self._fuzzy_request_lookup(artist, title)

        return newdata

    async def _fuzzy_request_lookup(
        self, artist: str = "", title: str = ""
    ) -> TrackRequestResult | None:
        """perform fuzzy matching on request database using rapidfuzz"""
        if not RAPIDFUZZ_AVAILABLE:
            logging.debug("rapidfuzz not available - skipping fuzzy matching")
            return None
        if not self.databasefile.exists():
            logging.error("%s does not exist, refusing to fuzzy lookup.", self.databasefile)
            return None

        try:
            # Get all requests from database for fuzzy matching
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()
                await cursor.execute("SELECT * FROM userrequest")
                all_requests = await cursor.fetchall()
        except sqlite3.OperationalError as error:
            logging.exception(error)

        if not all_requests:
            return None

        # Configuration for fuzzy matching thresholds - user configurable
        fuzzy_threshold = self.config.cparser.value(
            "requests/fuzzythreshold", type=int, defaultValue=85
        )
        best_match = None
        best_score = 0

        for request in all_requests:
            score = self._calculate_fuzzy_score(
                artist, title, request["artist"] or "", request["title"] or ""
            )

            if score > best_score and score >= fuzzy_threshold:
                best_score = score
                best_match = request

        if best_match:
            logging.debug(
                "fuzzy match found (score: %d): artist >%s< / title >%s< matched to >%s< / >%s<",
                best_score,
                artist,
                title,
                best_match["artist"] or "",
                best_match["title"] or "",
            )

            # Handle roulette duplicate tracking before deleting
            if best_match["type"] == "Roulette":
                await self.add_roulette_dupelist(best_match["artist"], best_match["playlist"])

            # Remove the matched request and return metadata
            self.erase_id(best_match["reqid"])

            return {
                "requester": best_match["username"],
                "requesterimageraw": best_match["userimage"],
                "requestdisplayname": best_match["displayname"],
            }

        logging.debug("no fuzzy match found for artist >%s< / title >%s<", artist, title)
        return None

    @staticmethod
    def _extract_core_text(text: str | None) -> str | None:
        """Extract core artist/title text by removing common filler words"""
        if not text:
            return text

        # Common phrases that people add to requests
        filler_patterns = [
            r"\bplay\b",
            r"\banything\s+by\b",
            r"\bsomething\s+by\b",
            r"\bplease\b",
            r"\bthanks?\b",
            r"\bty\b",
            r"\bthank\s+you\b",
            r"\bcan\s+you\s+play\b",
            r"\bcould\s+you\s+play\b",
            r"\bwould\s+you\s+play\b",
            r"\bi\s+want\b",
            r"\bi\s+would\s+like\b",
            r"\bi\s+request\b",
            r"\brequest\s+for\b",
            r"\bhow\s+about\b",
        ]

        cleaned = text.lower()

        # Remove filler patterns
        for pattern in filler_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        # Clean up extra whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        return cleaned or text

    @staticmethod
    def _calculate_similarity_with_length_penalty(text1: str, text2: str) -> int:
        """Calculate similarity with penalty for very different lengths"""
        if not RAPIDFUZZ_AVAILABLE or not text1 or not text2:
            return 0

        # Get base similarity score
        base_score = rapidfuzz.fuzz.WRatio(text1, text2)

        # Apply length penalty for very short matches
        len1, len2 = len(text1.strip()), len(text2.strip())
        min_len, max_len = min(len1, len2), max(len1, len2)

        # If one string is very short compared to the other, apply penalty
        if min_len > 0 and max_len / min_len > 2:
            # Reduce score for very different length strings
            length_penalty = min_len / max_len
            base_score = int(base_score * length_penalty)

        return base_score

    def _calculate_fuzzy_score(
        self, current_artist: str, current_title: str, request_artist: str, request_title: str
    ) -> int:
        """calculate combined fuzzy score for artist and title matching"""
        # Handle empty values
        if (not current_artist and not current_title) or (
            not request_artist and not request_title
        ):
            return 0

        # Extract core text to remove filler words from current track metadata
        clean_current_artist = self._extract_core_text(current_artist)
        clean_current_title = self._extract_core_text(current_title)

        artist_score = 0
        title_score = 0

        # Calculate artist similarity if both are provided
        # Try both original and cleaned text, take the higher score
        if current_artist and request_artist:
            artist_score = self._calc_raw_fuzzy_scores(
                current_artist, request_artist, clean_current_artist
            )
        # Calculate title similarity if both are provided
        # Try both original and cleaned text, take the higher score
        if current_title and request_title:
            title_score = self._calc_raw_fuzzy_scores(
                current_title, request_title, clean_current_title
            )
        # Determine what information is available for comparison
        has_both_current = current_artist and current_title
        has_both_request = request_artist and request_title

        if has_both_current and has_both_request:
            # Both artist and title available - weighted average (artist 40%, title 60%)
            return int(artist_score * 0.4 + title_score * 0.6)

        if current_artist and request_artist:
            # Only artist comparison possible
            return int(artist_score)

        if current_title and request_title:
            # Only title comparison possible
            return int(title_score)
        # No valid comparison possible
        return 0

    def _calc_raw_fuzzy_scores(self, arg0: str, arg1: str, arg2: str) -> int:
        original_score = self._calculate_similarity_with_length_penalty(arg0.lower(), arg1.lower())
        cleaned_score = (
            self._calculate_similarity_with_length_penalty(arg2.lower(), arg1.lower())
            if arg2
            else 0
        )
        return max(original_score, cleaned_score)

    async def get_request(self, metadata: TrackMetadata):
        """if a track gets played, finish out the request"""
        if not self.config.cparser.value("settings/requests"):
            return None

        newdata = None
        if metadata.get("filename"):
            logging.debug("trying filename %s", metadata["filename"])
            sql = "SELECT * FROM userrequest WHERE filename=?"
            datatuple = (metadata["filename"],)
            newdata = await self._get_and_del_request_lookup(sql, datatuple)

        if not newdata and metadata.get("artist") and metadata.get("title"):
            newdata = await self._request_lookup_by_artist_title(
                artist=metadata.get("artist"), title=metadata.get("title")
            )

        if not newdata and metadata.get("artist"):
            newdata = await self._request_lookup_by_artist_title(artist=metadata.get("artist"))

        if not newdata and metadata.get("title"):
            newdata = await self._request_lookup_by_artist_title(title=metadata.get("title"))

        if not newdata:
            logging.debug("not a request")
            return None

        if not newdata.get("requesterimageraw"):
            newdata["requesterimageraw"] = nowplaying.utils.TRANSPARENT_PNG_BIN

        return newdata

    async def watch_for_respin(self, stopevent: asyncio.Event):
        """startup a watcher to handle respins"""
        datatuple = (RESPIN_TEXT,)
        while not nowplaying.utils.safe_stopevent_check(stopevent):
            await asyncio.sleep(5)
            if not self.databasefile.exists():
                continue

            try:
                async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                    connection.row_factory = sqlite3.Row
                    cursor = await connection.cursor()
                    await cursor.execute(
                        "SELECT * from userrequest WHERE filename=? ORDER BY timestamp DESC",
                        datatuple,
                    )
                    rows_to_process = []
                    while row := await cursor.fetchone():
                        logging.debug(
                            "calling user_roulette_request: %s %s %s",
                            row["username"],
                            row["playlist"],
                            row["reqid"],
                        )
                        rows_to_process.append(dict(row))

                # need to do this outside of the aiosqlite call to avoid DB locks
                for row_data in rows_to_process:
                    await self.user_roulette_request(
                        {"playlist": row_data["playlist"]},
                        row_data["username"],
                        "",
                        row_data["reqid"],
                    )
            except Exception as error:  # pylint: disable=broad-except
                logging.exception(error)

    async def check_for_gifwords(self) -> GifWordsTrackRequest:
        """check if a gifword has been requested"""
        content: GifWordsTrackRequest = {"requester": None, "image": None, "keywords": None}
        reqid = None
        try:
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()
                await cursor.execute("SELECT * from gifwords ORDER BY timestamp DESC")
                if row := await cursor.fetchone():
                    content = {
                        "requester": row["requester"],
                        "image": row["image"],
                        "keywords": row["keywords"],
                    }
                    reqid = row["reqid"]
            if reqid is not None:
                await self.erase_gifwords_id(reqid)
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("check for gifwords exception: %s", err)
        return content

    async def find_command(self, command: str | None) -> TrackRequestSetting:
        """locate request information based upon a command"""
        setting: TrackRequestSetting = {}
        if not command:
            return setting

        for configitem in self.config.cparser.childGroups():
            if "request-" in configitem:
                tvtext = self.config.cparser.value(f"{configitem}/command")
                if tvtext == command:
                    for key in nowplaying.trackrequests.REQUEST_SETTING_MAPPING:
                        setting[key] = self.config.cparser.value(f"{configitem}/{key}")
                    break
        return setting

    async def find_twitchtext(self, twitchtext: str | None) -> TrackRequestSetting:
        """locate request information based upon twitchtext"""
        setting: TrackRequestSetting = {}
        if not twitchtext:
            return setting

        for configitem in self.config.cparser.childGroups():
            if "request-" in configitem:
                tvtext = self.config.cparser.value(f"{configitem}/twitchtext")
                if tvtext == twitchtext:
                    for key in nowplaying.trackrequests.REQUEST_SETTING_MAPPING:
                        setting[key] = self.config.cparser.value(f"{configitem}/{key}")
                    break
        return setting

    async def user_track_request(
        self, setting: TrackRequestSetting, user: str, user_input: str
    ) -> TrackRequestResult:
        """generic request"""
        logging.debug("%s generic requested %s", user, user_input)
        artist = None
        title = None
        weirdal = False

        if user_input.count("-") == 1:
            user_input = user_input.replace("-", " - ")
        if user_input := WEIRDAL_RE.sub("Weird Al", user_input):
            weirdal = True
        if user_input[0] != '"' and (atmatch := ARTIST_TITLE_RE.search(user_input)):
            artist = atmatch.group(1).strip()
            title = atmatch.group(2).strip()
        elif tmatch := TITLE_ARTIST_RE.search(user_input):
            title = tmatch.group(1).strip()
            artist = tmatch.group(2).strip()
        elif tmatch := TITLE_RE.search(user_input):
            title = tmatch.group(1).strip()
        else:
            artist = user_input.strip()

        if weirdal and artist:
            artist = artist.replace("Weird Al", '"Weird Al"')
        data: UserTrackRequest = {
            "username": user,
            "artist": artist,
            "title": title,
            "type": "Generic",
            "displayname": setting.get("displayname"),
            "user_input": user_input,
            "userimage": setting.get("userimage"),
        }

        await self.add_to_db(data)
        newdata: TrackRequestResult = {
            "requester": user,
            "requestartist": artist,
            "requesttitle": title,
            "requestdisplayname": setting.get("displayname"),
        }
        if self.testmode:
            newdata |= data

        return newdata

    async def _tenor_request(self, search_terms: str) -> GifWordsTrackRequest:
        """get an image from tenor for a given set of terms"""

        content: GifWordsTrackRequest = {
            "imageurl": None,
            "image": nowplaying.utils.TRANSPARENT_PNG_BIN,
            "keywords": search_terms,
        }

        apikey = self.config.cparser.value("gifwords/tenorkey")

        if not apikey:
            return content

        result = None
        streamer = self.config.cparser.value("twitch/channel")
        client_key = f"whatsnowplaying/{self.config.version}/{streamer}"

        params = {
            "media_filter": "gif",
            "client_key": client_key,
            "key": apikey,
            "limit": 1,
            "q": search_terms,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(BASE_URL, params=params, timeout=10) as response:
                if response.status == 200:
                    # load the GIFs using the urls for the smaller GIF sizes
                    result = await response.json()

        if result:
            content["imageurl"] = result["results"][0]["media_formats"]["gif"]["url"]
            async with aiohttp.ClientSession() as session:
                async with session.get(content["imageurl"], timeout=10) as response:
                    if response.status == 200:
                        # load the GIFs using the urls for the smaller GIF sizes
                        content["image"] = await response.read()

        return content

    async def gifwords_request(
        self, setting: TrackRequestSetting, user: str, user_input: str
    ) -> GifWordsTrackRequest:
        """gifword request"""
        logging.debug("%s gifwords requested %s", user, user_input)
        if not user_input and self.testmode:
            return None

        content = await self._tenor_request(user_input)
        content["requester"] = user
        content["requestdisplayname"] = setting.get("displayname")
        if self.testmode:
            return content

        await self.add_to_gifwordsdb(content)
        return content

    async def artist_query_request(  # pylint: disable=unused-argument,too-many-return-statements
        self, setting: TrackRequestSetting, user: str, user_input: str
    ) -> TrackRequestResult:
        """artist query request"""
        logging.debug("%s artist query requested %s", user, user_input)

        # Refresh config to get current input plugin
        self.config.get()
        current_input = self.config.cparser.value("settings/input")
        logging.debug("Artist query using %s input plugin", current_input)

        if not user_input:
            return {"hasartist_result": "Please specify an artist name"}

        artist_name = user_input.strip()
        if not artist_name:
            return {"hasartist_result": "Please specify an artist name"}

        if not current_input:
            return {"hasartist_result": "No input plugin configured"}

        # Create input plugin instance (without starting it)
        try:
            input_plugin = self.config.plugins["inputs"][
                f"nowplaying.inputs.{current_input}"
            ].Plugin(config=self.config)
        except KeyError:
            return {"hasartist_result": f"Input plugin {current_input} not available"}

        # Check if input plugin supports artist queries
        if not hasattr(input_plugin, "has_tracks_by_artist"):
            return {"hasartist_result": f"Artist queries not supported by {current_input}"}

        try:
            has_tracks = await input_plugin.has_tracks_by_artist(artist_name)
            if has_tracks:
                return {
                    "hasartist_result": f"Yes, {artist_name} was found in the library",
                    "hasartist_found": True,
                }
            return {
                "hasartist_result": f"No, {artist_name} was not found in the library",
                "hasartist_found": False,
            }
        except Exception as err:  # pylint: disable=broad-except
            logging.error("Artist query failed for %s: %s", artist_name, err, exc_info=True)
            return {"hasartist_result": f"Error checking for {artist_name}"}

    async def twofer_request(
        self, setting: TrackRequestSetting, user: str, user_input: str
    ) -> TrackRequestResult:
        """twofer request"""

        metadb = nowplaying.db.MetadataDB()
        metadata = await metadb.read_last_meta_async()
        if not metadata:
            logging.debug("Twofer: No currently playing track? skipping")
            return {}

        artist = metadata.get("artist")
        logging.debug("%s twofer request (%s/%s)", user, artist, user_input)

        if user_input:
            if tmatch := TWOFERTITLE_RE.search(user_input):
                title = tmatch.group(1)
            else:
                title = user_input
        else:
            title = None

        data: UserTrackRequest = {
            "username": user,
            "artist": artist,
            "title": title,
            "type": "Twofer",
            "displayname": setting.get("displayname"),
            "user_input": user_input,
            "userimage": setting.get("userimage"),
        }

        await self.add_to_db(data)
        newdata: TrackRequestResult = {
            "requester": user,
            "requestartist": artist,
            "requesttitle": title,
            "requestdisplayname": setting.get("displayname"),
        }
        if self.testmode:
            newdata |= data

        return newdata

    def start_watcher(self):
        """start the qfilesystemwatcher"""
        self.watcher = QFileSystemWatcher()
        self.watcher.addPath(str(self.databasefile))
        self.watcher.fileChanged.connect(self.update_window)

    def _connect_request_widgets(self):
        """connect request buttons"""
        self.widgets.respin_button.clicked.connect(self.on_respin_button)
        self.widgets.del_button.clicked.connect(self.on_del_button)

    def on_respin_button(self):
        """request respin button clicked action"""
        reqidlist = []
        if items := self.widgets.request_table.selectedItems():
            for item in items:
                row = item.row()
                reqidlist.append(self.widgets.request_table.item(row, 7).text())

        for reqid in reqidlist:
            try:
                self.respin_a_reqid(reqid)
            except Exception as error:  # pylint: disable=broad-except
                logging.error(error)

    def on_del_button(self):
        """request del button clicked action"""
        reqidlist = []
        if items := self.widgets.request_table.selectedItems():
            for item in items:
                row = item.row()
                reqidlist.append(self.widgets.request_table.item(row, 7).text())

        for reqid in reqidlist:
            try:
                self.erase_id(reqid)
            except Exception as error:  # pylint: disable=broad-except
                logging.error(error)

    async def get_all_generator(self) -> t.AsyncGenerator[UserTrackRequest, None]:
        """get all records, but use a generator"""

        def dict_factory(cursor, row):
            fields = [column[0] for column in cursor.description]
            return dict(zip(fields, row, strict=False))

        async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = dict_factory
            cursor = await connection.cursor()
            try:
                await cursor.execute("""SELECT * FROM userrequest""")
            except sqlite3.OperationalError as error:
                logging.exception(error)

            while dataset := await cursor.fetchone():
                yield dataset

    def get_dataset(self) -> list[UserTrackRequest] | None:
        """get the current request list for display"""
        if not self.databasefile.exists():
            logging.error("%s does not exist, refusing to get_dataset.", self.databasefile)
            return None

        def _do_get_dataset():
            with nowplaying.utils.sqlite.sqlite_connection(
                self.databasefile, timeout=30, row_factory=sqlite3.Row
            ) as connection:
                cursor = connection.cursor()
                cursor.execute("""SELECT * FROM userrequest""")
                dataset = cursor.fetchall()
                if not dataset:
                    return None
                return dataset

        try:
            return nowplaying.utils.sqlite.retry_sqlite_operation(_do_get_dataset)
        except sqlite3.OperationalError:
            logging.exception("Failed to get dataset after retries")
            return None

    def _request_window_load(self, **kwargs):
        """fill in a row on the request window"""
        row = self.widgets.request_table.rowCount()
        self.widgets.request_table.insertRow(row)

        for column, cbtype in enumerate(REQUEST_WINDOW_FIELDS):
            if cbtype == "displayname":
                continue
            if kwargs.get(cbtype):
                self.widgets.request_table.setItem(
                    row, column, QTableWidgetItem(str(kwargs[cbtype]))
                )
            else:
                self.widgets.request_table.setItem(row, column, QTableWidgetItem(""))

    def update_window(self):
        """redraw the request window"""
        if not self.config.cparser.value("settings/requests"):
            return

        def clear_table(widget):
            widget.clearContents()
            rows = widget.rowCount()
            for row in range(rows, -1, -1):
                widget.removeRow(row)

        dataset = self.get_dataset()
        clear_table(self.widgets.request_table)

        if not dataset:
            return

        for configitem in dataset:
            self._request_window_load(**configitem)
        self.widgets.request_table.horizontalHeader().ResizeMode(QHeaderView.Stretch)
        self.widgets.request_table.resizeColumnsToContents()
        self.widgets.request_table.adjustSize()
        self.widgets.adjustSize()
        self.widgets.show()

    def initial_ui(self):
        """load the UI"""
        uipath = self.config.uidir.joinpath("request_window.ui")
        loader = QUiLoader()
        ui_file = QFile(str(uipath))
        ui_file.open(QFile.ReadOnly)
        self.widgets = loader.load(ui_file)
        self.widgets.setLayout(self.widgets.window_layout)
        self.widgets.request_table.horizontalHeader().ResizeMode(QHeaderView.Stretch)
        ui_file.close()
        self._connect_request_widgets()
        self.update_window()
        self.start_watcher()

    def raise_window(self):
        """raise the request window"""
        if not self.config.cparser.value("settings/requests"):
            return
        self.update_window()
        self.widgets.raise_()

    def close_window(self):
        """close the request window"""
        if self.widgets:
            self.widgets.hide()
            self.widgets.close()


class TrackRequestSettings:
    """for settings UI"""

    def __init__(self):
        self.widget = None
        self.enablegifwords = False
        self.uihelp = None

    def connect(self, uihelp: "nowplaying.uihelp.UIHelp", widget: QWidget):
        """connect buttons"""
        self.widget = widget
        self.uihelp = uihelp

        if add_button := uihelp.find_widget_in_tabs(widget, "add_button"):
            add_button.clicked.connect(self.on_add_button)

        if del_button := uihelp.find_widget_in_tabs(widget, "del_button"):
            del_button.clicked.connect(self.on_del_button)

    def _row_load(self, widget: QWidget, uihelp: "nowplaying.uihelp.UIHelp", **kwargs):
        def _typebox(current, enablegifwords=False):
            box = QComboBox()
            reqtypes = ["Generic", "Roulette", "Twofer", "ArtistQuery"]
            if enablegifwords:
                reqtypes.append("GifWords")
            for reqtype in reqtypes:
                box.addItem(reqtype)
                if current and reqtype == current:
                    box.setCurrentIndex(box.count() - 1)
            return box

        request_table = uihelp.find_widget_in_tabs(widget, "request_table")
        if not request_table:
            return

        row = request_table.rowCount()
        request_table.insertRow(row)

        for column, cbtype in enumerate(nowplaying.trackrequests.REQUEST_SETTING_MAPPING):
            if cbtype == "type":
                box = _typebox(kwargs.get("type"), self.enablegifwords)
                request_table.setCellWidget(row, column, box)
            elif kwargs.get(cbtype):
                request_table.setItem(row, column, QTableWidgetItem(str(kwargs.get(cbtype))))
            else:
                request_table.setItem(row, column, QTableWidgetItem(""))
        request_table.resizeColumnsToContents()

    def load(  # pylint: disable=too-many-locals
        self,
        config: "nowplaying.config.ConfigFile",
        widget: QWidget,
        uihelp: "nowplaying.uihelp.UIHelp",
    ):
        """load the settings window"""

        def clear_table(table_widget):
            table_widget.clearContents()
            rows = table_widget.rowCount()
            for row in range(rows, -1, -1):
                table_widget.removeRow(row)

        # Find widgets across tabs
        request_table = uihelp.find_widget_in_tabs(widget, "request_table")
        enable_chat_checkbox = uihelp.find_widget_in_tabs(widget, "enable_chat_checkbox")
        enable_redemptions_checkbox = uihelp.find_widget_in_tabs(
            widget, "enable_redemptions_checkbox"
        )
        enable_checkbox = uihelp.find_widget_in_tabs(widget, "enable_checkbox")
        fuzzy_threshold_spinbox = uihelp.find_widget_in_tabs(widget, "fuzzy_threshold_spinbox")
        tenor_key_lineedit = uihelp.find_widget_in_tabs(widget, "tenor_key_lineedit")

        if request_table:
            clear_table(request_table)

        if config.cparser.value("gifwords/tenorkey"):
            self.enablegifwords = True

        for configitem in config.cparser.childGroups():
            setting = {}
            if "request-" in configitem:
                for key in nowplaying.trackrequests.REQUEST_SETTING_MAPPING:
                    setting[key] = config.cparser.value(f"{configitem}/{key}")
                self._row_load(widget, uihelp, **setting)

        if request_table:
            request_table.resizeColumnsToContents()

        if enable_chat_checkbox:
            enable_chat_checkbox.setChecked(
                config.cparser.value("twitchbot/chatrequests", type=bool)
            )

        if enable_redemptions_checkbox:
            enable_redemptions_checkbox.setChecked(
                config.cparser.value("twitchbot/redemptions", type=bool)
            )

        if enable_checkbox:
            enable_checkbox.setChecked(config.cparser.value("settings/requests", type=bool))

        # Load fuzzy matching threshold setting
        if fuzzy_threshold_spinbox:
            threshold = config.cparser.value("requests/fuzzythreshold", type=int, defaultValue=85)
            fuzzy_threshold_spinbox.setValue(threshold)

        # Load Tenor API key
        if tenor_key_lineedit:
            tenor_key = config.cparser.value("gifwords/tenorkey", defaultValue="")
            tenor_key_lineedit.setText(tenor_key)

    def save(self, config: "nowplaying.config.ConfigFile", widget: QWidget, subprocesses):  # pylint: disable=unused-argument
        """update the twitch settings"""

        def reset_commands(table_widget: QWidget, config: QSettings):
            for configitem in config.allKeys():
                if "request-" in configitem:
                    config.remove(configitem)

            rowcount = table_widget.rowCount()
            for row in range(rowcount):
                for column, cbtype in enumerate(nowplaying.trackrequests.REQUEST_SETTING_MAPPING):
                    if cbtype == "type":
                        item = table_widget.cellWidget(row, column)
                        value = item.currentText()
                    else:
                        item = table_widget.item(row, column)
                        if not item:
                            continue
                        value = item.text()
                    config.setValue(f"request-{row}/{cbtype}", value)

        # Find widgets across tabs
        enable_redemptions_checkbox = self.uihelp.find_widget_in_tabs(
            widget, "enable_redemptions_checkbox"
        )
        enable_chat_checkbox = self.uihelp.find_widget_in_tabs(widget, "enable_chat_checkbox")
        enable_checkbox = self.uihelp.find_widget_in_tabs(widget, "enable_checkbox")
        fuzzy_threshold_spinbox = self.uihelp.find_widget_in_tabs(
            widget, "fuzzy_threshold_spinbox"
        )
        tenor_key_lineedit = self.uihelp.find_widget_in_tabs(widget, "tenor_key_lineedit")
        request_table = self.uihelp.find_widget_in_tabs(widget, "request_table")

        if enable_redemptions_checkbox:
            config.cparser.setValue(
                "twitchbot/redemptions", enable_redemptions_checkbox.isChecked()
            )

        if enable_chat_checkbox:
            config.cparser.setValue("twitchbot/chatrequests", enable_chat_checkbox.isChecked())

        if enable_checkbox:
            config.cparser.setValue("settings/requests", enable_checkbox.isChecked())

        # Save fuzzy matching threshold setting
        if fuzzy_threshold_spinbox:
            config.cparser.setValue("requests/fuzzythreshold", fuzzy_threshold_spinbox.value())

        # Save Tenor API key
        if tenor_key_lineedit:
            config.cparser.setValue("gifwords/tenorkey", tenor_key_lineedit.text())

        if request_table:
            reset_commands(request_table, config.cparser)

    def verify(self, widget: QWidget):
        """verify the settings are good"""

        request_table = self.uihelp.find_widget_in_tabs(widget, "request_table")
        if not request_table:
            return

        count = request_table.rowCount()
        for row in range(count):
            item0 = request_table.item(row, 0)
            item1 = request_table.item(row, 1)
            item2 = request_table.cellWidget(row, 2)
            if not item0.text() and not item1.text():
                raise PluginVerifyError("Request must have either a command or redemption text.")

            if item2.currentText() in "Roulette":
                playlistitem = request_table.item(row, 4)
                if not playlistitem.text():
                    raise PluginVerifyError("Roulette request has an empty playlist")

    @Slot()
    def on_add_button(self):
        """add button clicked action"""
        self._row_load(self.widget, self.uihelp)

    @Slot()
    def on_del_button(self):
        """del button clicked action"""
        request_table = self.uihelp.find_widget_in_tabs(self.widget, "request_table")
        if request_table and (items := request_table.selectedIndexes()):
            request_table.removeRow(items[0].row())
