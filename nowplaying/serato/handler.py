#!/usr/bin/env python3
"""
Serato Handler

Original SeratoHandler class extracted from the monolithic serato.py file.
This preserves all the original functionality and complexity that was
developed and tested over time.
"""

import asyncio
import copy
import datetime
import logging
import pathlib
import re
import time
import typing as t

import lxml.html
import requests
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

# Import the base classes from the same module
from .session import SeratoSessionReader

TIDAL_FORMAT = re.compile(r"^_(.*).tdl")


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
        self.pollingobserver = pollingobserver
        self.polling_interval = polling_interval
        self.tasks = set()
        self.event_handler = None
        self.observer = None
        self.testmode = testmode
        self.decks = {}
        self.playingadat: dict[str, t.Any] = {}
        self.parsed_sessions = []
        self.last_processed = 0
        self.lastfetched = 0
        self.url: str | None = None  # Explicitly clear URL in local mode
        # Prefer local mode over remote mode when both are configured
        if seratodir:
            self.seratodir = pathlib.Path(seratodir)
            self.watchdeck = None
            self.parsed_sessions = []
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
        self.last_processed = round(time.time())
        self.parsed_sessions = copy.copy(sessiondata)
        # logging.debug(self.parsed_sessions)
        logging.debug("finished processing")

    def computedecks(self, deckskiplist=None):
        """based upon the session data, figure out what is actually
        on each deck"""

        logging.debug("called computedecks")

        if self.mode == "remote":
            return

        self.decks = {}

        for adat in reversed(self.parsed_sessions):
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
            if (
                self.mixmode == "newest"
                and adat.get("starttime") > self.playingadat.get("starttime")
                or self.mixmode == "oldest"
                and adat.get("starttime") < self.playingadat.get("starttime")
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

        if not self.lastfetched or self.last_processed >= self.lastfetched:
            self.lastfetched = self.last_processed + 1
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
        if result := tree.xpath(track_xpath):
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
        if result := tree.xpath('(//div[@class="playlist-trackname"]/text())[1]'):
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
            if len(cleaned) > 10 and all(
                skip not in cleaned.lower() for skip in ["copyright", "serato", "playlist"]
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

        self.decks = {}
        self.parsed_sessions = []
        self.playingadat = {}
        self.last_processed = 0
        self.lastfetched = 0
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    def __del__(self):
        self.stop()
