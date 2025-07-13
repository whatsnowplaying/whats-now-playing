#!/usr/bin/env python3
''' Input Plugin definition '''

import asyncio
import contextlib
import dataclasses
import datetime
import logging

from typing import TYPE_CHECKING

from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata

from nowplaying.vendor.stagelinq.discovery import DiscoveryConfig, discover_stagelinq_devices
from nowplaying.vendor.stagelinq.device import AsyncDevice
from nowplaying.vendor.stagelinq.messages import Token
from nowplaying.vendor.stagelinq.value_names import DeckValueNames

if TYPE_CHECKING:
    import nowplaying.config
    from nowplaying.vendor.stagelinq.device import State
    from PySide6.QtWidgets import QWidget


@dataclasses.dataclass
class DeckInfo():
    """ what is on a deck """
    updated: datetime.datetime
    track: str | None = None
    artist: str | None = None
    bpm: float | None = None
    playing: bool = False

    def __post_init__(self):
        """Set updated timestamp if not provided."""
        if not self.updated:
            self.updated = datetime.datetime.now(tz=datetime.timezone.utc)

    def __lt__(self, other: "DeckInfo") -> bool:
        """Compare DeckInfo instances by updated timestamp for sorting."""
        return self.updated < other.updated

    def copy(self) -> "DeckInfo":
        """Create a copy of this DeckInfo instance."""
        return dataclasses.replace(self)

    def same_content(self, other: "DeckInfo") -> bool:
        """Check if this deck has the same track and artist as another deck."""
        if self.track == other.track and self.artist == other.artist:
            return True
        return False


class StagelinqHandler():
    """ StagelinQ server """

    def __init__(self, event: asyncio.Event):
        """Initialize the StagelinQ handler.

        Args:
            event: Asyncio event used to signal shutdown
        """
        self.event = event
        self.device: AsyncDevice | None = None
        self.loop_task: asyncio.Task[None] | None = None
        self.decks: dict[int, DeckInfo] = {}

    async def get_device(self) -> None:
        """Discover and connect to a StagelinQ device.

        Continuously searches for StagelinQ devices until one is found
        or the event is set to stop searching.
        """
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
                    logging.info("Waiting for devices... (searching)")
                    await asyncio.sleep(2)

            except Exception as err:  # pylint: disable=broad-exception-caught
                logging.exception("Discovery error: %s", err)

    async def loop(self) -> None:
        """Main loop that maintains connection to StagelinQ device and processes updates.

        This method handles device discovery, connection management, and subscribes
        to track state updates from all decks. It automatically reconnects if
        the connection is lost.
        """

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

            except Exception as err:  # pylint: disable=broad-exception-caught
                logging.exception("Connection error: %s", err)
                logging.error("Retrying connection in 5 seconds...")
                await asyncio.sleep(5)

    @staticmethod
    def process_state_update(temp_decks: dict[int, DeckInfo], state: "State") -> None:
        """Process a state update and update deck information.

        Args:
            temp_decks: Dictionary of deck information being built during this update cycle
            state: StagelinQ state object containing updated deck information
        """
        deck_num = next((i for i in range(1, 5) if f"Deck{i}" in state.name), None)
        if deck_num is None:
            return

        # Initialize deck if it doesn't exist
        if deck_num not in temp_decks:
            temp_decks[deck_num] = DeckInfo(updated=datetime.datetime.now(tz=datetime.timezone.utc))

        # Update deck information based on state type using typed values
        if "ArtistName" in state.name:
            temp_decks[deck_num].artist = state.get_typed_value() or ""
        elif "SongName" in state.name:
            temp_decks[deck_num].track = state.get_typed_value() or ""
        elif "CurrentBPM" in state.name:
            # BPM values are already properly typed as float
            temp_decks[deck_num].bpm = state.get_typed_value()
        elif "PlayState" in state.name:
            # Boolean states are already properly typed
            temp_decks[deck_num].playing = state.get_typed_value()

    def update_current_tracks(self, temp_decks: dict[int, DeckInfo]) -> None:
        """Update the current deck states with new information.

        Args:
            temp_decks: Dictionary of updated deck information from the latest state updates
        """
        this_update = datetime.datetime.now(tz=datetime.timezone.utc)
        for deck_num in range(1, 5):
            # If deck doesn't exist in temp_decks, remove it from self.decks
            if deck_num not in temp_decks:
                _ = self.decks.pop(deck_num, None)
                continue

            if not temp_decks[deck_num].playing and deck_num in self.decks:
                del self.decks[deck_num]
            elif self.decks.get(deck_num) is None:
                self.decks[deck_num] = temp_decks[deck_num].copy()
                self.decks[deck_num].updated = this_update
            elif self.decks.get(deck_num) and not self.decks[deck_num].same_content(
                    temp_decks[deck_num]):
                self.decks[deck_num] = temp_decks[deck_num].copy()
                self.decks[deck_num].updated = this_update

    async def start(self) -> None:
        """Start the StagelinQ handler by creating the main loop task."""
        self.loop_task = asyncio.create_task(self.loop())

    async def stop(self) -> None:
        """Stop the StagelinQ handler and cancel the main loop task."""
        self.event.set()
        logging.info("Shutting down StagelinQ")
        if self.loop_task:
            _ = self.loop_task.cancel()

    async def get_track(self, mixmode: str) -> DeckInfo | None:
        """Get the currently playing track based on the specified mix mode.

        Args:
            mixmode: Either "newest" or "oldest" to determine which deck to return

        Returns:
            DeckInfo for the selected deck, or None if no decks are playing
        """
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
        self.displayname = "StagelinQ"
        self.url: str | None = None
        self.mixmode = "newest"
        self.testmode = False
        self.handler: StagelinqHandler | None = None
        self.event = asyncio.Event()

#### Additional UI method

    def desc_settingsui(self, qwidget: "QWidget") -> None:  # pylint: disable=no-self-use
        """Set the description text for the settings UI."""
        qwidget.setText('Denon StagelinQ compatible equipment')

#### Autoinstallation methods ####

    def install(self) -> bool:  # pylint: disable=no-self-use
        """Install method for fresh installations. Not required for StagelinQ."""
        return False

#### Mix Mode menu item methods

    def validmixmodes(self) -> list[str]:  # pylint: disable=no-self-use
        """Return the list of valid mix modes for the UI."""
        return ['newest', 'oldest']

    def setmixmode(self, mixmode: str) -> str:  # pylint: disable=no-self-use, unused-argument
        """Set the mix mode for determining which deck to use.

        Args:
            mixmode: Either "newest" or "oldest"

        Returns:
            The validated mix mode that was set
        """
        if mixmode not in ['newest', 'oldest']:
            mixmode = self.config.cparser.value('stagelinq/mixmode')

        self.config.cparser.setValue('stagelinq/mixmode', mixmode)
        return mixmode

    def getmixmode(self) -> str:  # pylint: disable=no-self-use
        """Get the current mix mode setting."""
        return self.config.cparser.value('stagelinq/mixmode')

#### Data feed methods

    async def getplayingtrack(self) -> TrackMetadata | None:
        """Get the currently playing track metadata.

        Returns:
            Dictionary containing track metadata (artist, track, bpm) or None if no handler
        """
        if not self.handler:
            return None

        deck = await self.handler.get_track(mixmode=self.mixmode)
        metadata: TrackMetadata = {}
        if not deck:
            return metadata
        if deck.artist is not None:
            metadata["artist"] = deck.artist
        if deck.track is not None:
            metadata["track"] = deck.track
        if deck.bpm is not None:
            metadata["bpm"] = str(deck.bpm)
        return metadata

    async def getrandomtrack(self, playlist: str) -> str | None:
        """Get a random track from a playlist.

        Args:
            playlist: Name of the playlist (not implemented for StagelinQ)

        Raises:
            NotImplementedError: This method is not supported for StagelinQ
        """
        raise NotImplementedError


#### Control methods

    async def start(self) -> None:
        """Initialize the StagelinQ handler and start listening for devices."""
        self.handler = StagelinqHandler(event=self.event)
        await self.handler.start()

    async def stop(self) -> None:
        """Stop the StagelinQ handler and clean up resources."""
        self.event.set()
        if self.handler:
            await self.handler.stop()
