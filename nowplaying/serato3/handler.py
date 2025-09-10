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

from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from ..serato.remote import SeratoRemoteHandler

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
            # Initialize shared remote handler
            self.remote_handler = SeratoRemoteHandler(seratourl, 30.0)
        else:
            self.url = None
            self.seratodir = None
            self.mode = None
            self.mixmode = mixmode

        if self.mixmode not in ["newest", "oldest"]:
            self.mixmode = "newest"

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

    async def _get_remote_track(self):
        """Get track from shared remote handler"""
        if not self.remote_handler:
            return {}

        track_data = await self.remote_handler.get_current_track()
        return track_data if track_data else {}

    async def getplayingtrack(self, deckskiplist=None):
        """generate a dict of data"""

        if self.mode == "remote":
            return await self._get_remote_track()

        # Local mode logic
        self.getlocalplayingtrack(deckskiplist=deckskiplist)

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
