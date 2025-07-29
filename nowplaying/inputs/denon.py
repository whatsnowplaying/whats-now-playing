#!/usr/bin/env python3
"""
Denon DJ StagelinQ Protocol Input Plugin

This plugin connects to Denon DJ equipment using the StagelinQ protocol to retrieve
real-time track information and playback status. Based on reverse engineering of the
StagelinQ protocol used by Denon DJ mixers and players.

Key protocol details:
- Discovery: UDP broadcasts on port 51337 with "airD" magic bytes
- Endianness: BigEndian for all multi-byte fields
- String encoding: UTF-16 BigEndian
- Token constraint: MSb must be 0 for device acceptance
"""

import asyncio
import contextlib
import json
import logging
import os
import socket
import struct
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import nowplaying.version
from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.uihelp

# Protocol constants
DISCOVERY_PORT = 51337
DISCOVERY_MAGIC = b"airD"
SMAA_MAGIC = b"smaa"

# Message IDs
MSG_SERVICE_ANNOUNCEMENT = 0x00000000
MSG_REFERENCE = 0x00000001
MSG_SERVICES_REQUEST = 0x00000002

# State message magic bytes
STATE_SUBSCRIBE_MAGIC = b"\x00\x00\x07\xd2"
STATE_EMIT_MAGIC = b"\x00\x00\x00\x00"


@dataclass
class DenonDevice:
    """Information about a discovered StagelinQ device"""

    ipaddr: str
    port: int
    name: str
    software_name: str
    software_version: str
    token: bytes


@dataclass
class DenonService:
    """Information about a service provided by a device"""

    name: str
    port: int


@dataclass
class DenonState:
    """State value update from StateMap service"""

    name: str
    value: dict[str, Any]


class StagelinqError(Exception):
    """Base exception for StagelinQ protocol errors"""


def _pack_utf16_string(string: str) -> bytes:
    """Pack a string as UTF-16 BigEndian with length prefix"""
    encoded = string.encode("utf-16be")
    return struct.pack(">I", len(encoded)) + encoded


def _unpack_utf16_string(data: bytes, offset: int = 0) -> tuple[str, int]:
    """Unpack a UTF-16 BigEndian string with length prefix"""
    if len(data) < offset + 4:
        raise StagelinqError("Insufficient data for string length")

    length: int = struct.unpack(">I", data[offset : offset + 4])[0]
    if len(data) < offset + 4 + length:
        raise StagelinqError("Insufficient data for string content")

    string_data = data[offset + 4 : offset + 4 + length]
    decoded = string_data.decode("utf-16be")
    return decoded, offset + 4 + length


class Plugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
    """Denon DJ StagelinQ input plugin"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Denon DJ"
        self.token = self._generate_token()
        self.device = None
        self.state_service = None
        self.current_metadata = {}
        self.tasks = []
        self.connections = []
        self._discovery_timeout = 5.0
        self._mixmode = "newest"
        self._deck_play_times = {}  # Track when each deck started playing

    @staticmethod
    def _generate_token() -> bytes:
        """Generate a random 16-byte token (MSb must be 0)"""
        token = bytearray(os.urandom(16))
        # Critical: Ensure MSb is 0 as per protocol requirement
        token[0] = token[0] & 0x7F
        return bytes(token)

    def install(self) -> bool:
        """Auto-install detection - StagelinQ devices are network-based"""
        # Cannot auto-detect network devices, user must configure manually
        return False

    def defaults(self, qsettings: "QSettings | None"):
        """Set default configuration values"""
        qsettings.setValue("denon/discovery_timeout", 5.0)
        qsettings.setValue("denon/deckskip", None)

    def connect_settingsui(self, qwidget: "QWidget", uihelp: "nowplaying.uihelp.UIHelp"):
        """Connect UI elements"""
        self.qwidget = qwidget
        self.uihelp = uihelp

    def load_settingsui(self, qwidget: "QWidget"):
        """Load configuration values into UI"""
        timeout = self.config.cparser.value(
            "denon/discovery_timeout", type=float, defaultValue=5.0
        )
        qwidget.denon_timeout_spinbox.setValue(timeout)

        # Load deck skip settings
        self._load_deckskip_settings(qwidget)

    def save_settingsui(self, qwidget: "QWidget"):
        """Save UI values to configuration"""
        self.config.cparser.setValue(
            "denon/discovery_timeout", qwidget.denon_timeout_spinbox.value()
        )

        # Save deck skip settings
        self._save_deckskip_settings(qwidget)

    def _load_deckskip_settings(self, qwidget: "QWidget"):
        """Load deck skip checkbox settings"""
        deckskip = self.config.cparser.value("denon/deckskip")

        # Reset all checkboxes first
        qwidget.denon_deck1_skip_checkbox.setChecked(False)
        qwidget.denon_deck2_skip_checkbox.setChecked(False)
        qwidget.denon_deck3_skip_checkbox.setChecked(False)
        qwidget.denon_deck4_skip_checkbox.setChecked(False)

        if not deckskip:
            return

        if not isinstance(deckskip, list):
            deckskip = list(deckskip)

        # Set checkboxes for decks that should be skipped
        if "1" in deckskip:
            qwidget.denon_deck1_skip_checkbox.setChecked(True)
        if "2" in deckskip:
            qwidget.denon_deck2_skip_checkbox.setChecked(True)
        if "3" in deckskip:
            qwidget.denon_deck3_skip_checkbox.setChecked(True)
        if "4" in deckskip:
            qwidget.denon_deck4_skip_checkbox.setChecked(True)

    def _save_deckskip_settings(self, qwidget: "QWidget"):
        """Save deck skip checkbox settings"""
        deckskip = []

        if qwidget.denon_deck1_skip_checkbox.isChecked():
            deckskip.append("1")
        if qwidget.denon_deck2_skip_checkbox.isChecked():
            deckskip.append("2")
        if qwidget.denon_deck3_skip_checkbox.isChecked():
            deckskip.append("3")
        if qwidget.denon_deck4_skip_checkbox.isChecked():
            deckskip.append("4")

        self.config.cparser.setValue("denon/deckskip", deckskip)

    def desc_settingsui(self, qwidget: "QWidget"):
        """Provide plugin description"""
        qwidget.setText(
            "Denon DJ StagelinQ protocol support for compatible Denon DJ mixers and players. "
            "Requires devices to be on the same network."
        )

    def validmixmodes(self) -> list[str]:
        """Valid mix modes for Denon DJ plugin"""
        return ["newest", "oldest"]

    def setmixmode(self, mixmode: str) -> str:
        """Set the mix mode"""
        if mixmode in self.validmixmodes():
            self._mixmode = mixmode
        return self._mixmode

    def getmixmode(self) -> str:
        """Get the current mix mode"""
        return self._mixmode

    async def start(self):
        """Initialize the StagelinQ connection"""
        logging.info("Starting Denon StagelinQ plugin")

        try:
            # Start continuous announcement task
            announce_task = asyncio.create_task(self._announce_every_second())
            self.tasks.append(announce_task)

            # Try to connect to a device
            await self._find_and_connect()

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.error("Failed to start Denon plugin: %s", err)

    async def _find_and_connect(self):
        """Find devices and connect to the first available one"""
        while True:
            try:
                self._discovery_timeout = self.config.cparser.value(
                    "denon/discovery_timeout", type=float, defaultValue=5.0
                )

                # Discover devices
                devices = await self._discover_devices(self._discovery_timeout)

                if devices:
                    logging.info("Found %d Denon device(s)", len(devices))

                    # Give devices time to receive multiple announcements before connecting
                    # The devices need to know who we are first
                    logging.debug("Waiting for devices to receive our announcements...")
                    await asyncio.sleep(3.0)  # Wait longer for devices to trust us

                    # Try each device until we find one with StateMap
                    for device in devices:
                        logging.debug("Trying device: %s (%s)", device.name, device.software_name)
                        success = await self._connect_and_monitor_device(device)
                        if success:
                            # Successfully connected, exit the retry loop
                            return

                # No devices found or connection failed, wait before trying again
                logging.debug("No devices found, retrying in 10 seconds...")
                await asyncio.sleep(10.0)

            except Exception as err:  # pylint: disable=broad-exception-caught
                logging.error("Error in device discovery: %s", err)
                await asyncio.sleep(10.0)

    async def _connect_and_monitor_device(self, device):
        """Connect to a device and start monitoring. Returns True on success."""
        try:
            logging.info("Connecting to Denon device: %s at %s", device.name, device.ipaddr)

            # Get available services
            services = await self._connect_to_device(device)

            logging.debug("Device offers %d services:", len(services))
            for service in services:
                logging.debug("  - %s on port %d", service.name, service.port)

            state_service = next(
                (service for service in services if service.name == "StateMap"),
                None,
            )
            if not state_service:
                logging.warning(
                    "StateMap service not available on device (found %d other services)",
                    len(services),
                )
                # Close any connections we opened
                for writer in self.connections:
                    with contextlib.suppress(Exception):
                        writer.close()
                        await writer.wait_closed()
                self.connections.clear()
                return False

            # Successfully connected
            self.device = device
            self.state_service = state_service

            # Start monitoring track states
            monitor_task = asyncio.create_task(self._monitor_track_states())
            monitor_task.add_done_callback(self._on_monitor_task_done)
            self.tasks.append(monitor_task)

            logging.info("Successfully connected to %s", device.name)
            return True

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Failed to connect to device %s: %s", device.name, err)
            return False

    def _on_monitor_task_done(self, task):
        """Called when monitoring task finishes (due to connection loss)"""
        if not task.cancelled():
            # Task finished due to error, not cancellation
            logging.info("Connection lost, will attempt to reconnect")
            self.device = None
            self.state_service = None
            self.current_metadata.clear()

            # Start reconnection task
            reconnect_task = asyncio.create_task(self._find_and_connect())
            self.tasks.append(reconnect_task)

    async def stop(self):
        """Stop the plugin and cleanup"""
        logging.info("Stopping Denon StagelinQ plugin")

        # Cancel all tasks
        for task in self.tasks:
            task.cancel()

        # Close all connections
        for writer in self.connections:
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()
        # Wait for tasks to complete
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

        self.tasks.clear()
        self.connections.clear()

    async def getrandomtrack(self, playlist: str) -> str | None:
        """Get random track from playlist - not supported by StagelinQ"""
        return None

    async def getplayingtrack(self) -> TrackMetadata | None:
        """Get the currently playing track metadata"""
        if not self.current_metadata:
            return None

        playing_decks = self._get_audible_playing_decks()
        if not playing_decks:
            return None

        selected_deck = self._select_deck_by_mix_mode(playing_decks)
        return self._build_track_metadata(selected_deck)

    def _get_deck_skip_list(self) -> list[str]:
        """Get the list of decks to skip"""
        deckskip = self.config.cparser.value("denon/deckskip")
        if deckskip and not isinstance(deckskip, list):
            deckskip = list(deckskip)
        return deckskip or []

    def _get_audible_playing_decks(self) -> list[dict]:
        """Find all currently playing and audible decks"""
        deckskip = self._get_deck_skip_list()
        playing_decks = []
        crossfader_pos = self._get_crossfader_position()

        for deck_num in range(1, 5):
            if str(deck_num) in deckskip:
                continue

            if deck_info := self._analyze_deck(deck_num, crossfader_pos):
                playing_decks.append(deck_info)
            elif deck_num in self._deck_play_times:
                # Deck stopped playing, remove from tracking
                del self._deck_play_times[deck_num]

        return playing_decks

    def _analyze_deck(self, deck_num: int, crossfader_pos: float) -> dict | None:
        """Analyze a single deck to see if it's playing and audible"""
        state_keys = self._get_deck_state_keys(deck_num)

        # Check if required metadata exists
        if any(key not in self.current_metadata for key in state_keys[:3]):
            return None

        play_state = self.current_metadata.get(state_keys[2], {})
        if not (isinstance(play_state, dict) and play_state.get("state") is True):
            return None

        # Get track metadata
        artist_data = self.current_metadata.get(state_keys[0], {})
        title_data = self.current_metadata.get(state_keys[1], {})
        fader_data = self.current_metadata.get(state_keys[3], {})

        if not (isinstance(artist_data, dict) and isinstance(title_data, dict)):
            return None

        # Calculate effective volume
        fader_pos = self._extract_numeric_value(fader_data)
        effective_volume = self._calculate_effective_volume(deck_num, fader_pos, crossfader_pos)

        if effective_volume <= 0.1:  # Not audible enough
            return None

        # Track is playing and audible
        if deck_num not in self._deck_play_times:
            self._deck_play_times[deck_num] = time.time()

        return {
            "deck": deck_num,
            "artist": artist_data.get("string", ""),
            "title": title_data.get("string", ""),
            "start_time": self._deck_play_times[deck_num],
            "effective_volume": effective_volume,
        }

    @staticmethod
    def _get_deck_state_keys(deck_num: int) -> list[str]:
        """Get the state keys for a specific deck"""
        return [
            f"/Engine/Deck{deck_num}/Track/ArtistName",
            f"/Engine/Deck{deck_num}/Track/SongName",
            f"/Engine/Deck{deck_num}/Play",
            f"/Mixer/CH{deck_num}faderPosition",
        ]

    def _select_deck_by_mix_mode(self, playing_decks: list[dict]) -> dict:
        """Select which deck to use based on mix mode and volume"""
        if len(playing_decks) == 1:
            return playing_decks[0]

        # Multiple audible decks - use volume-weighted selection
        max_volume = max(d["effective_volume"] for d in playing_decks)
        loudest_decks = [d for d in playing_decks if d["effective_volume"] >= max_volume * 0.8]

        if self._mixmode == "newest":
            return max(loudest_decks, key=lambda d: d["start_time"])
        # oldest
        return min(loudest_decks, key=lambda d: d["start_time"])

    def _build_track_metadata(self, selected_deck: dict) -> TrackMetadata:
        """Build the final track metadata dictionary"""
        metadata: TrackMetadata = {
            "artist": selected_deck["artist"],
            "title": selected_deck["title"],
        }

        deck_num = selected_deck["deck"]
        self._add_optional_metadata(metadata, deck_num)
        return metadata

    def _add_optional_metadata(self, metadata: dict, deck_num: int) -> None:
        """Add optional metadata fields if available"""
        optional_fields = [
            (f"/Engine/Deck{deck_num}/Track/AlbumName", "album", "string"),
            (f"/Engine/Deck{deck_num}/Track/BPM", "bpm", "data"),
            (f"/Engine/Deck{deck_num}/Track/Genre", "genre", "string"),
        ]

        for key, field_name, data_key in optional_fields:
            if key in self.current_metadata:
                data = self.current_metadata[key]
                if isinstance(data, dict) and data.get(data_key):
                    value = data.get(data_key, "")
                    if field_name == "bpm":
                        value = str(value)
                    metadata[field_name] = value

    def _get_crossfader_position(self) -> float:
        """Get crossfader position (0.0 = full left, 0.5 = center, 1.0 = full right)"""
        crossfader_data = self.current_metadata.get("/Mixer/CrossfaderPosition", {})
        return self._extract_numeric_value(crossfader_data, default=0.5)  # Default to center

    @staticmethod
    def _extract_numeric_value(data: dict, default: float = 0.0) -> float:
        """Extract numeric value from StagelinQ data dict"""
        if not isinstance(data, dict):
            return default

        # Try different possible numeric field names
        for field in ["data", "value", "number", "float"]:
            if field in data:
                try:
                    return float(data[field])
                except (ValueError, TypeError):
                    continue

        return default

    @staticmethod
    def _calculate_effective_volume(
        deck_num: int, fader_pos: float, crossfader_pos: float
    ) -> float:
        """Calculate effective volume considering channel fader and crossfader position"""
        if fader_pos <= 0.0:
            return 0.0

        # Simple crossfader logic:
        # Decks 1&3 are typically on left side (crossfader 0.0)
        # Decks 2&4 are typically on right side (crossfader 1.0)
        # When crossfader is in center (0.5), both sides are audible

        if deck_num in {1, 3}:  # Left side decks
            if crossfader_pos > 0.8:  # Crossfader strongly to right
                crossfader_factor = 0.0
            elif crossfader_pos <= 0.5:  # Crossfader center or left - left side audible
                crossfader_factor = 1.0
            else:  # Crossfader transitioning to right (0.5 < pos <= 0.8)
                crossfader_factor = 1.0 - ((crossfader_pos - 0.5) / 0.3)
        elif crossfader_pos < 0.2:  # Crossfader strongly to left
            crossfader_factor = 0.0
        elif crossfader_pos >= 0.5:  # Crossfader center or right - right side audible
            crossfader_factor = 1.0
        else:  # Crossfader transitioning from left (0.2 <= pos < 0.5)
            crossfader_factor = (crossfader_pos - 0.2) / 0.3

        return fader_pos * crossfader_factor

    async def _discover_devices(self, timeout: float) -> list[DenonDevice]:
        """Discover StagelinQ devices on the network"""
        devices = []
        found_tokens = set()

        # Create UDP socket for discovery
        loop = asyncio.get_event_loop()

        class DiscoveryProtocol(asyncio.DatagramProtocol):
            """protocol class"""

            def __init__(self, plugin):
                self.plugin = plugin

            def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
                try:
                    device: DenonDevice | None = self.plugin._parse_discovery_message(  # pylint: disable=protected-access
                        data, addr[0]
                    )
                    if (
                        device
                        and device.token not in found_tokens
                        and device.token != self.plugin.token
                    ):
                        devices.append(device)
                        found_tokens.add(device.token)
                except Exception as err:  # pylint: disable=broad-exception-caught
                    logging.debug("Failed to parse discovery message from %s: %s", addr, err)

        # Try to bind to discovery port
        try:
            transport, _protocol = await loop.create_datagram_endpoint(
                lambda: DiscoveryProtocol(self),
                local_addr=("0.0.0.0", DISCOVERY_PORT),
                reuse_port=True,
            )
        except OSError:
            # Fallback binding approaches
            try:
                transport, _protocol = await loop.create_datagram_endpoint(
                    lambda: DiscoveryProtocol(self), local_addr=("0.0.0.0", DISCOVERY_PORT)
                )
            except OSError:
                transport, _protocol = await loop.create_datagram_endpoint(
                    lambda: DiscoveryProtocol(self), local_addr=("", DISCOVERY_PORT)
                )

        try:
            # Wait for discovery messages
            await asyncio.sleep(timeout)
        finally:
            transport.close()

        return devices

    @staticmethod
    def _parse_discovery_message(data: bytes, ipaddr: str) -> DenonDevice | None:
        """Parse a discovery message from UDP broadcast"""
        if len(data) < 4 or data[:4] != DISCOVERY_MAGIC:
            return None

        try:
            offset = 4

            # Read token (16 bytes)
            if len(data) < offset + 16:
                return None
            token = data[offset : offset + 16]
            offset += 16

            # Read device name
            device_name, offset = _unpack_utf16_string(data, offset)

            # Read action
            action, offset = _unpack_utf16_string(data, offset)

            # Read software name
            software_name, offset = _unpack_utf16_string(data, offset)

            # Read software version
            software_version, offset = _unpack_utf16_string(data, offset)

            # Read port
            if len(data) < offset + 2:
                return None
            port = struct.unpack(">H", data[offset : offset + 2])[0]

            # Only return devices that are present
            if action == "DISCOVERER_HOWDY_":
                return DenonDevice(
                    ipaddr=ipaddr,
                    port=port,
                    name=device_name,
                    software_name=software_name,
                    software_version=software_version,
                    token=token,
                )

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Error parsing discovery message: %s", err)

        return None

    async def _connect_to_device(self, device: DenonDevice) -> list[DenonService]:
        """Connect to device and get available services"""
        reader, writer = await asyncio.open_connection(device.ipaddr, device.port)
        self.connections.append(writer)

        # Start reference message task
        ref_task = asyncio.create_task(self._send_reference_messages(writer, device.token))
        self.tasks.append(ref_task)

        # Send services request
        services_msg = struct.pack(">I", MSG_SERVICES_REQUEST) + self.token
        writer.write(services_msg)
        await writer.drain()

        # Read services
        services = []
        while True:
            try:
                # Read message ID
                msg_id_data = await reader.readexactly(4)
                msg_id = struct.unpack(">I", msg_id_data)[0]

                if msg_id == MSG_SERVICE_ANNOUNCEMENT:
                    # Read service announcement
                    await reader.readexactly(16)  # Skip token

                    # Read service name
                    str_len_data = await reader.readexactly(4)
                    str_len = struct.unpack(">I", str_len_data)[0]
                    str_data = await reader.readexactly(str_len)
                    service_name = str_data.decode("utf-16be")

                    # Read port
                    port_data = await reader.readexactly(2)
                    port = struct.unpack(">H", port_data)[0]

                    services.append(DenonService(name=service_name, port=port))

                elif msg_id == MSG_REFERENCE:
                    # End of service list
                    await reader.readexactly(40)  # Skip reference message data
                    break

            except asyncio.IncompleteReadError:
                break

        return services

    async def _monitor_track_states(self):
        """Monitor track state changes from StateMap service"""
        if not self.device or not self.state_service:
            return

        try:
            reader, writer = await asyncio.open_connection(
                self.device.ipaddr, self.state_service.port
            )
            self.connections.append(writer)

            # Send service announcement
            local_port = writer.get_extra_info("sockname")[1]
            service_msg = (
                struct.pack(">I", MSG_SERVICE_ANNOUNCEMENT)
                + self.token
                + _pack_utf16_string("StateMap")
                + struct.pack(">H", local_port)
            )
            writer.write(service_msg)
            await writer.drain()

            # Subscribe to track metadata for all decks and mixer fader positions
            state_paths = []
            for deck in range(1, 5):
                state_paths.extend(
                    [
                        f"/Engine/Deck{deck}/Play",
                        f"/Engine/Deck{deck}/PlayState",
                        f"/Engine/Deck{deck}/Track/ArtistName",
                        f"/Engine/Deck{deck}/Track/SongName",
                        f"/Engine/Deck{deck}/Track/AlbumName",
                        f"/Engine/Deck{deck}/Track/BPM",
                        f"/Engine/Deck{deck}/Track/Genre",
                        f"/Engine/Deck{deck}/Track/SongLoaded",
                        f"/Mixer/CH{deck}faderPosition",
                    ]
                )

            # Also subscribe to crossfader position
            state_paths.append("/Mixer/CrossfaderPosition")

            for state_path in state_paths:
                # Create state subscribe message
                content = SMAA_MAGIC + STATE_SUBSCRIBE_MAGIC
                content += _pack_utf16_string(state_path)
                content += struct.pack(">I", 0)  # Interval

                sub_msg = struct.pack(">I", len(content)) + content
                writer.write(sub_msg)
                await writer.drain()

            # Read state updates
            while True:
                try:
                    # Read length-prefixed message
                    length_data = await reader.readexactly(4)
                    length = struct.unpack(">I", length_data)[0]
                    payload = await reader.readexactly(length)

                    if state := self._parse_state_emit_message(payload):
                        self.current_metadata[state.name] = state.value
                        logging.debug("State update: %s = %s", state.name, state.value)

                except asyncio.IncompleteReadError:
                    break

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Track monitoring error: %s", err)
            # Task callback will handle reconnection

    @staticmethod
    def _parse_state_emit_message(data: bytes) -> DenonState | None:
        """Parse a state emit message"""
        try:
            # Check for SMAA magic and state emit magic
            if len(data) < 8:
                return None

            if data[:4] != SMAA_MAGIC or data[4:8] != STATE_EMIT_MAGIC:
                return None

            offset = 8

            # Read state name
            name, offset = _unpack_utf16_string(data, offset)

            # Read JSON value
            json_str, offset = _unpack_utf16_string(data, offset)

            # Parse JSON
            value = json.loads(json_str)

            return DenonState(name=name, value=value)

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Error parsing state emit message: %s", err)
            return None

    async def _send_reference_messages(self, writer: asyncio.StreamWriter, target_token: bytes):
        """Send periodic reference messages to keep connection alive"""
        try:
            while True:
                await asyncio.sleep(0.25)  # 250ms interval

                message = (
                    struct.pack(">I", MSG_REFERENCE)
                    + self.token
                    + target_token
                    + struct.pack(">q", 0)
                )
                writer.write(message)
                await writer.drain()

        except asyncio.CancelledError:
            pass
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Reference message error: %s", err)
            # Let monitoring task handle the disconnection

    async def _announce_every_second(self):
        """Continuously announce ourselves to devices"""
        try:
            while True:
                await self._announce_self()
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Announcement error: %s", err)

    async def _announce_self(self):
        """Send UDP announcement to let devices know about us"""
        try:
            device_name = "WhatsNowPlaying"

            # Create discovery message
            message = DISCOVERY_MAGIC  # "airD"
            message += self.token
            message += _pack_utf16_string(device_name)
            message += _pack_utf16_string("DISCOVERER_HOWDY_")
            message += _pack_utf16_string("WhatsNowPlaying")
            message += _pack_utf16_string(nowplaying.version.__VERSION__)
            message += struct.pack(">H", 0)  # Port (0 for client)

            # Send to broadcast address
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(message, ("255.255.255.255", DISCOVERY_PORT))
            sock.close()

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Self-announcement error: %s", err)
