#!/usr/bin/env python3
''' Input Plugin definition '''

import asyncio
import contextlib
from curses import meta
import dataclasses
import datetime
import logging

from typing import TYPE_CHECKING

from nowplaying.exceptions import PluginVerifyError
from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata

from nowplaying.vendor.stagelinq.discovery import DiscoveryConfig, discover_stagelinq_devices
from nowplaying.vendor.stagelinq.messages import Token
from nowplaying.vendor.stagelinq.value_names import DeckValueNames

if TYPE_CHECKING:
    import nowplaying.config
    from nowplaying.vendor.stagelinq.device import AsyncDevice, State
    from PySide6.QtWidgets import QWidget


@dataclasses.dataclass
class DeckInfo():
    """ what is on a deck """
    updated: datetime.datetime
    track: str | None = None
    artist: str | None = None
    bpm: int | None = None
    playing: bool = False

    def __post_init__(self):
        if not self.updated:
            self.updated = datetime.datetime.now(tz=datetime.timezone.utc)

    def __lt__(self, other: "DeckInfo") -> bool:
        return self.updated < other.updated

    def copy(self) -> "DeckInfo":
        return dataclasses.replace(self)

    def same_content(self, other: "DeckInfo") -> bool:
        if self.track == other.track and self.artist == other.artist:
            return True
        return False


class StagelinqHandler():
    """ stagelinq server """

    def __init__(self, event: asyncio.Event):
        self.event = event
        self.device: AsyncDevice | None = None
        self.loop_task: asyncio.Task | None = None
        self.decks: dict[int, DeckInfo] = {}

    async def get_device(self):
        """ find a device """
        config = DiscoveryConfig(discovery_timeout=3.0)
        while not self.event.is_set() and self.device is None:
            try:
                async with discover_stagelinq_devices(config) as discovery:
                    await discovery.start_announcing()
                    devices = await discovery.get_devices()

                    if devices:
                        self.device = AsyncDevice(**vars(devices[0]))
                        logging.info("Found device: %s", self.device.name)
                        logging.info("Connecting to %s", self.device.name)
                        break
                    else:
                        logging.info("Waiting for devices... (searching)")
                        await asyncio.sleep(2)

            except Exception as e:
                logging.exception("Discovery error: %s", e)

    async def loop(self):

        # Connect to device with retry loop
        while not self.event.is_set():
            try:
                await self.get_device()

                if not self.device:
                    await asyncio.sleep(.5)
                    continue

                # Create client token
                client_token = Token(
                    b"\x00\x00\x00\x00\x00\x00\x00\x00\x80\x00\x00\x05\x95\x04\x14\x1c")

                # Connect to device
                connection = self.device.connect(client_token)
                async with connection:
                    services = await connection.discover_services()
                    print(f"Available services: {[s.name for s in services]}")

                    # Connect to StateMap service
                    async with connection.state_map() as state_map:
                        logging.debug("Connected to StateMap service")
                        # Subscribe to track information for all decks
                        logging.debug("Subscribing to track information...")
                        for deck_num in range(1, 5):
                            deck = DeckValueNames(deck_num)
                            track_states = [
                                deck.track_artist_name(),
                                deck.track_song_name(),
                                deck.track_current_bpm(),
                                deck.play_state(),
                            ]

                            for state_name in track_states:
                                with contextlib.suppress(Exception):
                                    await state_map.subscribe(state_name, 100)  # 100ms interval

                # Listen for state updates
                temp_decks: dict[int, DeckInfo] = {}
                async for state in state_map.states():
                    if not self.event.is_set():
                        break

                    # Parse state updates
                    self.process_state_update(temp_decks, state)

                self.update_current_tracks(temp_decks)

                # If we get here, connection was lost
                if self.event.is_set():
                    return

            except Exception as e:
                logging.error(f"Connection error: {e}")
                logging.error("Retrying connection in 5 seconds...")
                await asyncio.sleep(5)

    def process_state_update(self, temp_decks: dict[int, DeckInfo], state: "State"):
        """Process a state update and update deck information."""
        deck_num = next((i for i in range(1, 5) if f"Deck{i}" in state.name), None)
        if deck_num is None:
            return

        # Update deck information based on state type using typed values
        if "ArtistName" in state.name:
            temp_decks[deck_num].artist = state.get_typed_value() or ""
        elif "SongName" in state.name:
            temp_decks[deck_num].track = state.get_typed_value() or ""
        elif "CurrentBPM" in state.name:
            # BPM values are already properly typed as float
            temp_decks[deck_num].bpm = state.get_typed_value() or 0.0
        elif "PlayState" in state.name:
            # Boolean states are already properly typed
            temp_decks[deck_num].playing = state.get_typed_value()

    def update_current_tracks(self, temp_decks: dict[int, DeckInfo]):
        this_update = datetime.datetime.now(tz=datetime.timezone.utc)
        for deck_num in range(1, 5):
            if not temp_decks[deck_num].playing and self.decks[deck_num]:
                del self.decks[deck_num]
            elif self.decks.get(deck_num) is None:
                self.decks[deck_num] = temp_decks[deck_num].copy()
                self.decks[deck_num].updated = this_update
            elif not self.decks[deck_num].same_content(temp_decks[deck_num]):
                self.decks[deck_num] = temp_decks[deck_num].copy()
                self.decks[deck_num].updated = this_update

    async def start(self):
        self.loop_task = asyncio.create_task(self.loop())

    async def stop(self):
        self.event.set()
        logging.info("Shutting down Stagelinq")
        if self.loop_task:
            self.loop_task.cancel()

    async def get_track(self, mixmode: str) -> DeckInfo | None:
        sorted_decks = sorted(self.decks.values(), key=lambda deck: deck.updated)

        if not sorted_decks:
            return None
        if mixmode == "newest":
            return sorted_decks[-1]
        return sorted_decks[0]


class Plugin(InputPlugin):
    ''' base class of input plugins '''

    def __init__(self,
                 config: "nowplaying.config.ConfigFile | None" = None,
                 qsettings: "QWidget | None" = None):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Stagelinq"
        self.url: str | None = None
        self.mixmode = "newest"
        self.testmode = False
        self.handler: StagelinqHandler | None = None
        self.event = asyncio.Event()

#### Additional UI method

    def desc_settingsui(self, qwidget: "QWidget") -> None:  # pylint: disable=no-self-use
        ''' description of this input '''
        qwidget.setText('Denon Stagelinq compatible equipment')

#### Autoinstallation methods ####

    def install(self) -> bool:  # pylint: disable=no-self-use
        ''' if a fresh install, run this '''
        return False

#### Mix Mode menu item methods

    def validmixmodes(self) -> list[str]:  # pylint: disable=no-self-use
        ''' tell ui valid mixmodes '''
        return ['newest', 'oldest']

    def setmixmode(self, mixmode: str) -> str:  # pylint: disable=no-self-use, unused-argument
        ''' handle user switching the mix mode: TBD '''
        if mixmode not in ['newest', 'oldest']:
            mixmode = self.config.cparser.value('stagelinq/mixmode')

        self.config.cparser.setValue('stagelinq/mixmode', mixmode)
        return mixmode

    def getmixmode(self) -> str:  # pylint: disable=no-self-use
        ''' return what the current mixmode is set to '''
        return self.config.cparser.value('stagelinq/mixmode')

#### Data feed methods

    async def getplayingtrack(self) -> TrackMetadata | None:
        ''' Get the currently playing track '''
        if not self.handler:
            return None

        deck = await self.handler.get_track(mixmode=self.mixmode)
        metadata: TrackMetadata = {}
        if not deck:
            return metadata
        if deck.artist:
            metadata["artist"] = deck.artist
        if deck.track:
            metadata["track"] = deck.track
        if deck.bpm:
            metadata["bpm"] = str(deck.bpm)
        return metadata

    async def getrandomtrack(self, playlist: str) -> str | None:
        ''' Get a file associated with a playlist, crate, whatever '''
        raise NotImplementedError


#### Control methods

    async def start(self) -> None:
        ''' any initialization before actual polling starts '''
        self.handler = StagelinqHandler(event=self.event)
        await self.handler.start()

    async def stop(self) -> None:
        ''' stopping either the entire program or just this
            input '''
        if self.handler:
            self.event.set()
            await self.handler.stop()
