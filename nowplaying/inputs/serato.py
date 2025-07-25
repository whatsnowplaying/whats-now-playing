#!/usr/bin/env python3
"""A _very_ simple and incomplete parser for Serato Live session files"""

# pylint: disable=too-many-lines

import asyncio
import copy
import datetime
import logging
import os
import re
import pathlib
import random
import struct
import time
import typing as t
from collections.abc import Callable

import aiofiles
import lxml.html
import requests

from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import PatternMatchingEventHandler

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QFileDialog  # pylint: disable=no-name-in-module

from nowplaying.inputs import InputPlugin
from nowplaying.exceptions import PluginVerifyError

# when in local mode, these are shared variables between threads
LASTPROCESSED: int = 0
PARSEDSESSIONS = []

TIDAL_FORMAT = re.compile("^_(.*).tdl")


class SeratoCrateReader:
    """read a Serato crate (not smart crate) -
    based on https://gist.github.com/kerrickstaley/8eb04988c02fa7c62e75c4c34c04cf02"""

    def __init__(self, filename: str | pathlib.Path) -> None:
        self.decode_func_full: dict[str | None, Callable[[bytes], t.Any]] = {
            None: self._decode_struct,
            "vrsn": self._decode_unicode,
            "sbav": self._noop,
            "rart": self._noop,
            "rlut": self._noop,
            "rurt": self._noop,
        }

        self.decode_func_first: dict[str, Callable[[bytes], t.Any]] = {
            "o": self._decode_struct,
            "t": self._decode_unicode,
            "p": self._decode_unicode,
            "u": self._decode_unsigned,
            "b": self._noop,
        }

        self.cratepath: pathlib.Path = pathlib.Path(filename)
        self.crate: list[tuple[str, t.Any]] | None = None

    def _decode_struct(self, data: bytes) -> list[tuple[str, t.Any]]:
        """decode the structures of the crate"""
        ret: list[tuple[str, t.Any]] = []
        i = 0
        while i < len(data):
            tag = data[i : i + 4].decode("ascii")
            length = struct.unpack(">I", data[i + 4 : i + 8])[0]
            value = data[i + 8 : i + 8 + length]
            value = self._datadecode(value, tag=tag)
            ret.append((tag, value))
            i += 8 + length
        return ret

    @staticmethod
    def _decode_unicode(data: bytes) -> str:
        return data.decode("utf-16-be")

    @staticmethod
    def _decode_unsigned(data: bytes) -> int:
        return struct.unpack(">I", data)[0]

    @staticmethod
    def _noop(data: bytes) -> bytes:
        return data

    def _datadecode(self, data: bytes, tag: str | None = None) -> t.Any:
        if tag in self.decode_func_full:
            decode_func = self.decode_func_full[tag]
        else:
            decode_func = self.decode_func_first[tag[0]]

        return decode_func(data)

    async def loadcrate(self) -> None:
        """load/overwrite current crate"""
        async with aiofiles.open(self.cratepath, "rb") as cratefhin:
            self.crate = self._datadecode(await cratefhin.read())

    def getfilenames(self) -> list[str] | None:
        """get the filenames from this crate"""
        if not self.crate:
            logging.error("crate has not been loaded")
            return None
        filelist: list[str] = []
        anchor = self.cratepath.anchor
        for tag in self.crate:
            if tag[0] != "otrk":
                continue
            otrk = tag[1]
            for subtag in otrk:
                if subtag[0] != "ptrk":
                    continue
                filelist.extend(f"{anchor}{filepart}" for filepart in subtag[1:])
        return filelist


class SeratoSessionReader:
    """read a Serato session file"""

    def __init__(self) -> None:
        self.decode_func_full: dict[str | None, Callable[[bytes], t.Any]] = {
            None: self._decode_struct,
            "vrsn": self._decode_unicode,
            "adat": self._decode_adat,
            "oent": self._decode_struct,
        }

        self.decode_func_first: dict[str, Callable[[bytes], t.Any]] = {
            "o": self._decode_struct,
            "t": self._decode_unicode,
            "p": self._decode_unicode,
            "u": self._decode_unsigned,
            "b": self._noop,
        }

        self._adat_func: dict[int, list[str | Callable[[bytes], t.Any]]] = {
            2: ["pathstr", self._decode_unicode],
            3: ["location", self._decode_unicode],
            4: ["filename", self._decode_unicode],
            6: ["title", self._decode_unicode],
            7: ["artist", self._decode_unicode],
            8: ["album", self._decode_unicode],
            9: ["genre", self._decode_unicode],
            10: ["duration", self._decode_unicode],
            11: ["filesize", self._decode_unicode],
            13: ["bitrate", self._decode_unicode],
            14: ["frequency", self._decode_unicode],
            15: ["bpm", self._decode_unsigned],
            16: ["field16", self._decode_hex],
            17: ["comments", self._decode_unicode],
            18: ["lang", self._decode_unicode],
            19: ["grouping", self._decode_unicode],
            20: ["remixer", self._decode_unicode],
            21: ["label", self._decode_unicode],
            22: ["composer", self._decode_unicode],
            23: ["date", self._decode_unicode],
            28: ["starttime", self._decode_timestamp],
            29: ["endtime", self._decode_timestamp],
            31: ["deck", self._decode_unsigned],
            45: ["playtime", self._decode_unsigned],
            48: ["sessionid", self._decode_unsigned],
            50: ["played", self._decode_bool],
            51: ["key", self._decode_unicode],
            52: ["added", self._decode_bool],
            53: ["updatedat", self._decode_timestamp],
            63: ["playername", self._decode_unicode],
            64: ["commentname", self._decode_unicode],
        }

        self.sessiondata: list[dict[str, t.Any]] = []

    def _decode_adat(self, data: bytes) -> dict[str, t.Any]:
        ret: dict[str, t.Any] = {}
        # i = 0
        # tag = struct.unpack('>I', data[0:i + 4])[0]
        # length = struct.unpack('>I', data[i + 4:i + 8])[0]
        i = 8
        while i < len(data) - 8:
            tag = struct.unpack(">I", data[i + 4 : i + 8])[0]
            length = struct.unpack(">I", data[i + 8 : i + 12])[0]
            value = data[i + 12 : i + 12 + length]
            try:
                field = self._adat_func[tag][0]
                value = self._adat_func[tag][1](value)
            except KeyError:
                field = f"unknown{tag}"
                value = self._noop(value)
            ret[field] = value
            i += 8 + length
        if not ret.get("filename"):
            ret["filename"] = ret.get("pathstr")
        return ret

    def _decode_struct(self, data: bytes) -> list[tuple[str, t.Any]]:
        """decode the structures of the session"""
        ret: list[tuple[str, t.Any]] = []
        i = 0
        while i < len(data):
            tag = data[i : i + 4].decode("ascii")
            length = struct.unpack(">I", data[i + 4 : i + 8])[0]
            value = data[i + 8 : i + 8 + length]
            value = self._datadecode(value, tag=tag)
            ret.append((tag, value))
            i += 8 + length
        return ret

    @staticmethod
    def _decode_unicode(data: bytes) -> str:
        return data.decode("utf-16-be")[:-1]

    @staticmethod
    def _decode_timestamp(data: bytes) -> datetime.datetime:
        try:
            timestamp = struct.unpack(">I", data)[0]
        except struct.error:
            timestamp = struct.unpack(">Q", data)[0]
        return datetime.datetime.fromtimestamp(timestamp)

    @staticmethod
    def _decode_hex(data: bytes) -> str:
        """read a string, then encode as hex"""
        return data.encode("utf-8").hex()

    @staticmethod
    def _decode_bool(data: bytes) -> bool:
        """true/false handling"""
        return bool(struct.unpack("b", data)[0])

    @staticmethod
    def _decode_unsigned(data: bytes) -> int:
        try:
            field = struct.unpack(">I", data)[0]
        except struct.error:
            field = struct.unpack(">Q", data)[0]
        return field

    @staticmethod
    def _noop(data: bytes) -> bytes:
        return data

    def _datadecode(self, data: bytes, tag: str | None = None) -> t.Any:
        if tag in self.decode_func_full:
            decode_func = self.decode_func_full[tag]
        else:
            decode_func = self.decode_func_first[tag[0]]
        return decode_func(data)

    async def loadsessionfile(self, filename: str | pathlib.Path) -> None:
        """load/extend current session"""
        async with aiofiles.open(filename, "rb") as sessionfhin:
            self.sessiondata.extend(self._datadecode(await sessionfhin.read()))

    def condense(self) -> None:
        """shrink to just adats"""
        adatdata: list[dict[str, t.Any]] = []
        if not self.sessiondata:
            logging.error("session has not been loaded")
            return
        for sessiontuple in self.sessiondata:
            if sessiontuple[0] == "oent":
                adatdata.extend(
                    oentdata[1] for oentdata in sessiontuple[1] if oentdata[0] == "adat"
                )

        self.sessiondata = adatdata

    def sortsession(self) -> None:
        """sort them by starttime"""
        records = sorted(self.sessiondata, key=lambda x: x.get("starttime"))
        self.sessiondata = records

    def getadat(self) -> t.Generator[dict[str, t.Any], None, None]:
        """get the filenames from this session"""
        if not self.sessiondata:
            logging.error("session has not been loaded")
            return
        yield from self.sessiondata

    def getreverseadat(self) -> t.Generator[dict[str, t.Any], None, None]:
        """same as getadat, but reversed order"""
        if not self.sessiondata:
            logging.error("session has not been loaded")
            return
        yield from reversed(self.sessiondata)


class SeratoHandler:  # pylint: disable=too-many-instance-attributes
    """Generic handler to get the currently playing track.

    To use Serato Live Playlits, construct with:
        self.seratourl='url')


    To use local Serato directory, construct with:
        self.seratodir='/path/to/_Serato_'

    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        mixmode: str = "oldest",
        pollingobserver: bool = False,
        seratodir: str | None = None,
        seratourl: str | None = None,
        testmode: bool = False,
        polling_interval: float = 1.0,
    ):
        global LASTPROCESSED, PARSEDSESSIONS  # pylint: disable=global-statement
        self.pollingobserver = pollingobserver
        self.polling_interval = polling_interval
        self.tasks = set()
        self.event_handler = None
        self.observer = None
        self.testmode = testmode
        self.decks = {}
        self.playingadat: dict[str, t.Any] = {}
        PARSEDSESSIONS = []
        LASTPROCESSED = 0
        self.lastfetched = 0
        self.url: str | None = None  # Explicitly clear URL in local mode
        # Prefer local mode over remote mode when both are configured
        if seratodir:
            self.seratodir = pathlib.Path(seratodir)
            self.watchdeck = None
            PARSEDSESSIONS = []
            self.mode = "local"
            self.mixmode = mixmode
            self.url = None  # Explicitly clear URL in local mode
        elif seratourl:
            self.url = seratourl
            self.mode = "remote"
            self.mixmode = "newest"  # there is only 1 deck so always newest
            self.seratodir = None
        else:
            self.url = None
            self.seratodir = None
            self.mode = None
            self.mixmode = mixmode

        if self.mixmode not in ["newest", "oldest"]:
            self.mixmode = "newest"

        # Network failure tracking for circuit breaker pattern
        self.network_failure_count = 0
        self.backoff_until = 0

        # Track change detection for log spam reduction
        self.last_extracted_track = None
        self.last_extraction_method = None

    async def start(self):
        """perform any startup tasks"""
        if self.seratodir and self.mode == "local":
            await self._setup_watcher()

    async def _setup_watcher(self):
        logging.debug("setting up watcher")
        self.event_handler = PatternMatchingEventHandler(
            patterns=["*.session"],
            ignore_patterns=[".DS_Store"],
            ignore_directories=True,
            case_sensitive=False,
        )
        self.event_handler.on_modified = self.process_sessions

        if self.pollingobserver:
            self.observer = PollingObserver(timeout=self.polling_interval)
            logging.debug("Using polling observer with %s second interval", self.polling_interval)
        else:
            self.observer = Observer()
            logging.debug("Using fsevent observer")

        _ = self.observer.schedule(
            self.event_handler,
            str(self.seratodir.joinpath("History", "Sessions")),
            recursive=False,
        )
        self.observer.start()

        # process what is already there
        await self._async_process_sessions()

    def process_sessions(self, event):
        """handle incoming session file updates"""
        logging.debug("processing %s", event)
        try:
            loop = asyncio.get_running_loop()
            logging.debug("got a running loop")
            task = loop.create_task(self._async_process_sessions())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

        except RuntimeError:
            loop = asyncio.new_event_loop()
            logging.debug("created a loop")
            loop.run_until_complete(self._async_process_sessions())

    async def _async_process_sessions(self):
        """read and process all of the relevant session files"""
        global LASTPROCESSED, PARSEDSESSIONS  # pylint: disable=global-statement

        if self.mode == "remote":
            return

        logging.debug("triggered by watcher")

        # Just nuke the OS X metadata file rather than
        # work around it

        sessionpath = self.seratodir.joinpath("History", "Sessions")

        sessionlist = sorted(sessionpath.glob("*.session"), key=lambda path: int(path.stem))
        # sessionlist = sorted(seratopath.glob('*.session'),
        #                     key=lambda path: path.stat().st_mtime)

        if not sessionlist:
            logging.debug("no session files found")
            return

        if not self.testmode:
            difftime = time.time() - sessionlist[-1].stat().st_mtime
            if difftime > 600:
                logging.debug("%s is too old", sessionlist[-1].name)
                return

        session = SeratoSessionReader()
        await session.loadsessionfile(sessionlist[-1])
        session.condense()

        sessiondata = list(session.getadat())
        LASTPROCESSED = round(time.time())
        PARSEDSESSIONS = copy.copy(sessiondata)
        # logging.debug(PARSEDSESSIONS)
        logging.debug("finished processing")

    def computedecks(self, deckskiplist=None):
        """based upon the session data, figure out what is actually
        on each deck"""

        logging.debug("called computedecks")

        if self.mode == "remote":
            return

        self.decks = {}

        for adat in reversed(PARSEDSESSIONS):
            if not adat.get("deck"):
                # broken record
                continue
            if deckskiplist and str(adat["deck"]) in deckskiplist:
                # on a deck that is supposed to be ignored
                continue
            if not adat.get("played"):
                # wasn't played, so skip it
                continue
            if adat["deck"] in self.decks and adat.get("starttime") < self.decks[adat["deck"]].get(
                "starttime"
            ):
                # started after a deck that is already set
                continue
            self.decks[adat["deck"]] = adat

    def computeplaying(self):
        """set the adat for the playing track based upon the
        computed decks"""

        logging.debug("called computeplaying")

        if self.mode == "remote":
            logging.debug("in remote mode; skipping")
            return

        # at this point, self.decks should have
        # all decks with their _most recent_ "unplayed" tracks

        # under most normal operations, we should expect
        # a round-robin between the decks:

        # mixmode = oldest, better for a 2+ deck mixing scenario
        # 1. serato startup
        # 2. load deck 1   -> title set to deck 1 since only title known
        # 3. hit play
        # 4. load deck 2
        # 5. cross fade
        # 6. hit play
        # 7. load deck 1   -> title set to deck 2 since it is now the oldest
        # 8. go to #2

        # mixmode = newest, better for 1 deck or using autoplay
        # 1. serato startup
        # 2. load deck 1   -> title set to deck 1
        # 3. play
        # 4. go to #2

        # it is important to remember that due to the timestamp
        # checking in process_sessions, oldest/newest switching
        # will not effect until the NEXT session file update.
        # e.g., unless you are changing more than two decks at
        # once, this behavior should be the expected result

        self.playingadat = {}

        logging.debug("mixmode: %s", self.mixmode)

        if self.mixmode == "newest":
            self.playingadat["starttime"] = datetime.datetime.fromtimestamp(0)
        else:
            self.playingadat["starttime"] = datetime.datetime.fromtimestamp(time.time())
        self.playingadat["updatedat"] = self.playingadat["starttime"]

        logging.debug(
            "Find the current playing deck. Starting at time: %s",
            self.playingadat.get("starttime"),
        )
        for deck, adat in self.decks.items():
            if self.mixmode == "newest" and adat.get("starttime") > self.playingadat.get(
                "starttime"
            ):
                self.playingadat = adat
                logging.debug(
                    "Playing = time: %s deck: %d artist: %s title %s",
                    self.playingadat.get("starttime"),
                    deck,
                    self.playingadat.get("artist"),
                    self.playingadat.get("title"),
                )
            elif self.mixmode == "oldest" and adat.get("starttime") < self.playingadat.get(
                "starttime"
            ):
                self.playingadat = adat
                logging.debug(
                    "Playing = time: %s deck: %d artist: %s title %s",
                    self.playingadat.get("starttime"),
                    deck,
                    self.playingadat.get("artist"),
                    self.playingadat.get("title"),
                )

    def getlocalplayingtrack(self, deckskiplist=None) -> tuple[str | None, str | None, str | None]:
        """parse out last track from binary session file
        get latest session file
        """

        if self.mode == "remote":
            logging.debug("in remote mode; skipping")
            return None, None

        if not self.lastfetched or LASTPROCESSED >= self.lastfetched:
            self.lastfetched = LASTPROCESSED + 1
            self.computedecks(deckskiplist=deckskiplist)
            self.computeplaying()

        if self.playingadat:
            return (
                self.playingadat.get("artist"),
                self.playingadat.get("title"),
                self.playingadat.get("filename"),
            )
        return None, None, None

    def _remote_extract_by_js_id(self, page_text, tree) -> str | None:
        """Extract track using JavaScript track ID (most robust)"""
        if not (track_id_match := re.search(r"end_track_id:\s*(\d+)", page_text)):
            return None
        current_track_id = track_id_match[1]
        track_xpath = (
            f'//div[@id="track_{current_track_id}"]//div[@class="playlist-trackname"]/text()'  # pylint: disable=line-too-long
        )
        result = tree.xpath(track_xpath)
        if result:
            # Only log when track changes to reduce spam
            track_text = result[0]
            if track_text != self.last_extracted_track:
                logging.debug("Method 1 success: JavaScript+XPath (track_%s)", current_track_id)
                self.last_extracted_track = track_text
            return track_text
        return None

    @staticmethod
    def _remote_extract_by_position(tree) -> str | None:
        """Extract track using positional XPath (fallback)"""
        result = tree.xpath('(//div[@class="playlist-trackname"]/text())[1]')
        if result:
            logging.debug("Method 2 success: Positional XPath")
            return result[0]
        return None

    @staticmethod
    def _remote_extract_by_pattern(tree) -> str | None:
        """Extract track using text pattern matching (regex fallback)"""
        track_divs = tree.xpath('//div[contains(@class, "playlist-track")]')
        for track_div in track_divs[:3]:  # Check first 3 tracks
            text_content = track_div.text_content()
            # Look for "Artist - Title" pattern
            if (match := re.search(r"([^-\n]+)\s*-\s*([^-\n]+)", text_content)) and len(
                match[0].strip()
            ) > 10:  # Reasonable length
                result = match[0].strip()
                logging.debug("Method 3 success: Text pattern matching")
                return result
        return None

    @staticmethod
    def _remote_extract_by_text_search(tree) -> str | None:
        """Extract track using fallback text search (last resort)"""
        all_text = tree.xpath('//text()[contains(., " - ")]')
        for text in all_text:
            cleaned = text.strip()
            if len(cleaned) > 10 and not any(
                skip in cleaned.lower() for skip in ["copyright", "serato", "playlist"]
            ):
                logging.debug("Method 4 success: Text fallback search")
                return cleaned
        return None

    def getremoteplayingtrack(self):  # pylint: disable=too-many-return-statements
        """get the currently playing title from Live Playlists"""

        if self.mode == "local":
            logging.debug("in local mode; skipping")
            return

        # Circuit breaker: check if we should back off due to recent failures
        if not self._can_make_request():
            return

        # Fetch the page with error handling
        page = self._fetch_page()
        if not page:
            return

        if track_text := self._extract_track_from_page(page):
            # Parse and store the track data
            self._parse_and_store_track(track_text)
        else:
            return

    def _can_make_request(self) -> bool:
        """Check if we can make a request based on circuit breaker state"""
        current_time = time.time()
        return current_time >= self.backoff_until

    def _fetch_page(self) -> requests.Response | None:
        """Fetch the page with network error handling"""
        current_time = time.time()
        try:
            page = requests.get(self.url, timeout=5)
            # Success: reset failure tracking
            self.network_failure_count = 0
            self.backoff_until = 0
            return page
        except Exception as error:  # pylint: disable=broad-except
            self._handle_network_failure(current_time, error)
            return None

    def _handle_network_failure(self, current_time: float, error):
        """Handle network failure with live DJ-friendly backoff"""
        self.network_failure_count += 1

        # Live DJ backoff: 1s, 2s, 3s, then max 5s
        if self.network_failure_count <= 3:
            backoff_seconds = self.network_failure_count
        else:
            backoff_seconds = 5
        self.backoff_until = current_time + backoff_seconds

        # Reduce log spam: only log every 10th error after first few
        should_log = self.network_failure_count <= 3 or self.network_failure_count % 10 == 0

        if should_log:
            if self.network_failure_count == 1:
                logging.error("Cannot process %s: %s", self.url, error)
            else:
                logging.error(
                    "Cannot process %s: %s (failure #%d, backing off for %ds)",
                    self.url,
                    error,
                    self.network_failure_count,
                    backoff_seconds,
                )

    def _extract_track_from_page(self, page) -> str | None:
        """Extract track information from the page"""
        try:
            tree = lxml.html.fromstring(page.text)
            # Try methods in order of reliability
            extraction_methods = [
                ("JavaScript+XPath", lambda: self._remote_extract_by_js_id(page.text, tree)),
                ("Positional XPath", lambda: SeratoHandler._remote_extract_by_position(tree)),
                ("Pattern matching", lambda: SeratoHandler._remote_extract_by_pattern(tree)),
                ("Text search", lambda: SeratoHandler._remote_extract_by_text_search(tree)),
            ]

            for method_name, method_func in extraction_methods:
                try:
                    if track_text := method_func():
                        # Only log when track or method changes to reduce spam
                        if (
                            track_text != self.last_extracted_track
                            or method_name != self.last_extraction_method
                        ):
                            logging.debug("Successfully extracted track using: %s", method_name)
                            self.last_extracted_track = track_text
                            self.last_extraction_method = method_name
                        return track_text
                except Exception as method_error:  # pylint: disable=broad-except
                    logging.debug("Method %s failed: %s", method_name, method_error)
                    continue
            return None
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot process %s: %s", self.url, error)
            return None

    def _parse_and_store_track(self, track_text):
        """Parse track text and store in playingadat"""
        # Convert to expected list format for compatibility with existing code
        item = [track_text] if track_text else None
        if not item:
            return

        # cleanup
        tdat = str(item)
        for char in ["['", "']", "[]", "\\n", "\\t", '["', '"]']:
            tdat = tdat.replace(char, "")
        tdat = tdat.strip()

        if not tdat:
            self.playingadat = {}
            return

        # Parse artist and title
        if " - " not in tdat:
            artist = None
            title = tdat.strip()
        else:
            # The only hope we have is to split on ' - ' and hope that the
            # artist/title doesn't have a similar split.
            (artist, title) = tdat.split(" - ", 1)

        # Clean up artist
        if not artist or artist == ".":
            artist = None
        else:
            artist = artist.strip()

        # Clean up title
        if not title or title == ".":
            title = None
        else:
            title = title.strip()

        # Store the results
        self.playingadat["artist"] = artist
        self.playingadat["title"] = title

        if not title and not artist:
            self.playingadat = {}

    def _get_tidal_cover(self, filename):
        """try to get the cover from tidal"""
        if tmatch := TIDAL_FORMAT.search(str(filename)):
            imgfile = f"{tmatch[1]}.jpg"
            tidalimgpath = self.seratodir.joinpath("Metadata", "Tidal", imgfile)
            logging.debug("using tidal image path: %s", tidalimgpath)
            if tidalimgpath.exists():
                with open(tidalimgpath, "rb") as fhin:
                    return fhin.read()
        return None

    def getplayingtrack(self, deckskiplist=None):
        """generate a dict of data"""

        if self.mode == "local":
            self.getlocalplayingtrack(deckskiplist=deckskiplist)
        else:
            self.getremoteplayingtrack()

        if not self.playingadat:
            return {}

        if self.playingadat.get("filename") and ".tdl" in self.playingadat.get("filename"):
            if coverimage := self._get_tidal_cover(self.playingadat["filename"]):
                self.playingadat["coverimageraw"] = coverimage

        return {
            key: self.playingadat[key]
            for key in [
                "album",
                "artist",
                "bitrate",
                "bpm",
                "comments",
                "composer",
                "coverimageraw",
                "date",
                "deck",
                "duration",
                "filename",
                "genre",
                "key",
                "label",
                "lang",
                "title",
            ]
            if self.playingadat.get(key)
        }

    def stop(self):
        """stop serato handler"""
        global LASTPROCESSED, PARSEDSESSIONS  # pylint: disable=global-statement

        self.decks = {}
        PARSEDSESSIONS = []
        self.playingadat = {}
        LASTPROCESSED = 0
        self.lastfetched = 0
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    def __del__(self):
        self.stop()


class Plugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
    """handler for NowPlaying"""

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Serato"
        self.url: str | None = None
        self.libpath = None
        self.local = True
        self.serato = None
        self.mixmode = "newest"
        self.testmode = False
        # Network failure tracking for circuit breaker pattern
        self.network_failure_count = 0
        self.last_network_failure_time = 0
        self.backoff_until: int = 0
        # Track last extracted track to reduce success log spam
        self.last_extracted_track = None
        self.last_extraction_method = None

    def install(self):
        """auto-install for Serato"""
        seratodir = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.MusicLocation)[0]
        ).joinpath("_Serato_")

        if seratodir.exists():
            self.config.cparser.value("settings/input", "serato")
            self.config.cparser.value("serato/libpath", str(seratodir))
            return True

        return False

    async def gethandler(self):
        """setup the SeratoHandler for this session"""

        stilllocal = self.config.cparser.value("serato/local", type=bool)
        usepoll = self.config.cparser.value("quirks/pollingobserver", type=bool)

        # now configured as remote!
        if not stilllocal:
            stillurl: str = self.config.cparser.value("serato/url")

            # if previously remote and same URL, do nothing
            if not self.local and self.url == stillurl:
                return

            logging.debug("new url = %s", stillurl)
            self.local = stilllocal
            self.url = stillurl
            if self.serato:
                self.serato.stop()
            polling_interval = self.config.cparser.value(
                "quirks/pollinginterval", type=float, defaultValue=1.0
            )
            self.serato = SeratoHandler(
                pollingobserver=usepoll,
                seratourl=self.url,
                testmode=self.testmode,
                polling_interval=polling_interval,
            )
            return

        # configured as local!

        self.local = stilllocal
        stilllibpath = self.config.cparser.value("serato/libpath")
        stillmixmode = self.config.cparser.value("serato/mixmode")

        # same path and same mixmode, no nothing
        if self.libpath == stilllibpath and self.mixmode == stillmixmode:
            return

        self.libpath = stilllibpath
        self.mixmode = stillmixmode

        self.serato = None

        # paths for session history
        hist_dir = os.path.abspath(os.path.join(self.libpath, "History"))
        sess_dir = os.path.abspath(os.path.join(hist_dir, "Sessions"))
        if os.path.isdir(sess_dir):
            logging.debug("new session path = %s", sess_dir)
            polling_interval = self.config.cparser.value(
                "quirks/pollinginterval", type=float, defaultValue=1.0
            )
            self.serato = SeratoHandler(
                seratodir=self.libpath,
                mixmode=self.mixmode,
                pollingobserver=usepoll,
                testmode=self.testmode,
                polling_interval=polling_interval,
            )
            # if self.serato:
            #    self.serato.process_sessions()
        else:
            logging.error("%s does not exist!", sess_dir)
            return
        await self.serato.start()

    async def start(self, testmode=False):
        """get a handler"""
        self.testmode = testmode
        await self.gethandler()

    async def getplayingtrack(self):
        """wrapper to call getplayingtrack"""
        await self.gethandler()

        # get poll interval and then poll
        if self.local:
            interval = 1
        else:
            interval = self.config.cparser.value("settings/interval", type=float)

        time.sleep(interval)

        if self.serato:
            deckskip = self.config.cparser.value("serato/deckskip")
            if deckskip and not isinstance(deckskip, list):
                deckskip = list(deckskip)
            return self.serato.getplayingtrack(deckskiplist=deckskip)
        return {}

    async def getrandomtrack(self, playlist: str) -> str | None:
        """Get the files associated with a playlist, crate, whatever"""

        libpath = self.config.cparser.value("serato/libpath")
        logging.debug("libpath: %s", libpath)
        if not libpath:
            return None

        crate_path = pathlib.Path(libpath).joinpath("Subcrates")
        smartcrate_path = pathlib.Path(libpath).joinpath("SmartCrates")

        logging.debug("Determined: %s %s", crate_path, smartcrate_path)
        if crate_path.joinpath(f"{playlist}.crate").exists():
            playlistfile = crate_path.joinpath(f"{playlist}.crate")
        elif smartcrate_path.joinpath(f"{playlist}.scrate"):
            playlistfile = smartcrate_path.joinpath(f"{playlist}.scrate")
        else:
            logging.error("Unknown crate: %s", playlist)
            return None

        logging.debug("Using %s", playlistfile)

        crate = SeratoCrateReader(playlistfile)
        await crate.loadcrate()
        if filelist := crate.getfilenames():
            return filelist[random.randrange(len(filelist))]
        return None

    def defaults(self, qsettings):
        qsettings.setValue(
            "serato/libpath",
            os.path.join(
                QStandardPaths.standardLocations(QStandardPaths.MusicLocation)[0], "_Serato_"
            ),
        )
        qsettings.setValue("serato/interval", 10.0)
        qsettings.setValue("serato/local", True)
        qsettings.setValue("serato/mixmode", "newest")
        qsettings.setValue("serato/url", None)
        qsettings.setValue("serato/deckskip", None)

    def validmixmodes(self):
        """let the UI know which modes are valid"""
        if self.config.cparser.value("serato/local", type=bool):
            return ["newest", "oldest"]

        return ["newest"]

    def setmixmode(self, mixmode):
        """set the mixmode"""
        if mixmode not in ["newest", "oldest"]:
            mixmode = self.config.cparser.value("serato/mixmode")

        if not self.config.cparser.value("serato/local", type=bool):
            mixmode = "newest"

        self.config.cparser.setValue("serato/mixmode", mixmode)
        return mixmode

    def getmixmode(self):
        """get the mixmode"""

        if self.config.cparser.value("serato/local", type=bool):
            return self.config.cparser.value("serato/mixmode")

        self.config.cparser.setValue("serato/mixmode", "newest")
        return "newest"

    async def stop(self):
        """stop the handler"""
        if self.serato:
            self.serato.stop()

    def on_serato_lib_button(self):
        """lib button clicked action"""
        startdir = self.qwidget.local_dir_lineedit.text() or str(pathlib.Path.home())
        if libdir := QFileDialog.getExistingDirectory(self.qwidget, "Select directory", startdir):
            self.qwidget.local_dir_lineedit.setText(libdir)

    def connect_settingsui(self, qwidget, uihelp):
        """connect serato local dir button"""
        self.qwidget = qwidget
        self.uihelp = uihelp
        self.qwidget.local_dir_button.clicked.connect(self.on_serato_lib_button)

    def load_settingsui(self, qwidget):
        """draw the plugin's settings page"""

        def handle_deckskip(cparser, qwidget):
            deckskip = cparser.value("serato/deckskip")
            qwidget.deck1_checkbox.setChecked(False)
            qwidget.deck2_checkbox.setChecked(False)
            qwidget.deck3_checkbox.setChecked(False)
            qwidget.deck4_checkbox.setChecked(False)

            if not deckskip:
                return

            if not isinstance(deckskip, list):
                deckskip = list(deckskip)

            if "1" in deckskip:
                qwidget.deck1_checkbox.setChecked(True)

            if "2" in deckskip:
                qwidget.deck2_checkbox.setChecked(True)

            if "3" in deckskip:
                qwidget.deck3_checkbox.setChecked(True)

            if "4" in deckskip:
                qwidget.deck4_checkbox.setChecked(True)

        if self.config.cparser.value("serato/local", type=bool):
            qwidget.local_button.setChecked(True)
            qwidget.remote_button.setChecked(False)
        else:
            qwidget.local_dir_button.setChecked(False)
            qwidget.remote_button.setChecked(True)
        qwidget.local_dir_lineedit.setText(self.config.cparser.value("serato/libpath"))
        qwidget.remote_url_lineedit.setText(self.config.cparser.value("serato/url"))
        qwidget.remote_poll_lineedit.setText(str(self.config.cparser.value("serato/interval")))
        handle_deckskip(self.config.cparser, qwidget)

    def verify_settingsui(self, qwidget):
        """no verification to do"""
        if qwidget.remote_button.isChecked() and (
            "https://serato.com/playlists" not in qwidget.remote_url_lineedit.text()
            and "https://www.serato.com/playlists" not in qwidget.remote_url_lineedit.text()
            or len(qwidget.remote_url_lineedit.text()) < 30
        ):
            raise PluginVerifyError("Serato Live Playlist URL is invalid")

        if qwidget.local_button.isChecked() and (
            "_Serato_" not in qwidget.local_dir_lineedit.text()
        ):
            raise PluginVerifyError(
                r'Serato Library Path is required.  Should point to "\_Serato\_" folder'
            )

    def save_settingsui(self, qwidget):
        """take the settings page and save it"""
        self.config.cparser.setValue("serato/libpath", qwidget.local_dir_lineedit.text())
        self.config.cparser.setValue("serato/local", qwidget.local_button.isChecked())
        self.config.cparser.setValue("serato/url", qwidget.remote_url_lineedit.text())
        self.config.cparser.setValue("serato/interval", qwidget.remote_poll_lineedit.text())

        deckskip = []
        if qwidget.deck1_checkbox.isChecked():
            deckskip.append("1")
        if qwidget.deck2_checkbox.isChecked():
            deckskip.append("2")
        if qwidget.deck3_checkbox.isChecked():
            deckskip.append("3")
        if qwidget.deck4_checkbox.isChecked():
            deckskip.append("4")

        self.config.cparser.setValue("serato/deckskip", deckskip)

    def desc_settingsui(self, qwidget):
        """description"""
        qwidget.setText(
            "This plugin provides support for Serato in both a local and remote capacity."
        )
