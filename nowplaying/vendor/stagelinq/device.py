"""StageLinq device connection implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .discovery import Device
from .file_transfer import FileTransferConnection
from .messages import (
    BeatEmitMessage,
    BeatInfoStartStreamMessage,
    BeatInfoStopStreamMessage,
    ReferenceMessage,
    ServiceAnnouncementMessage,
    ServicesRequestMessage,
    StateEmitMessage,
    StateSubscribeMessage,
    Token,
    format_interval,
)
from .protocol import StageLinqConnection

logger = logging.getLogger(__name__)


class DeviceRegistry:
    """Collection of discovered StageLinq devices."""

    def __init__(self) -> None:
        self._devices: list[Device] = []

    def add_device(self, device: Device) -> None:
        """Add a device to the registry."""
        # Avoid duplicates based on token
        if all(d.token.data != device.token.data for d in self._devices):
            self._devices.append(device)

    def find_device_by_uuid(self, uuid: str) -> Device | None:
        """Find a device by UUID (with or without hyphens)."""
        # Remove hyphens to match token format
        uuid_no_hyphens = uuid.replace("-", "")

        return next(
            (
                device
                for device in self._devices
                if device.token.data.hex() == uuid_no_hyphens
            ),
            None,
        )

    def find_device_by_token(self, token: Token) -> Device | None:
        """Find a device by token."""
        return next(
            (device for device in self._devices if device.token.data == token.data),
            None,
        )

    def parse_channel_assignment(self, assignment_str: str) -> str:
        """Parse a channel assignment string and return human-readable format."""
        if not assignment_str or "{" not in assignment_str:
            return assignment_str

        try:
            # Extract UUID part
            uuid_part = assignment_str.split("{")[1].split("}")[0]
            if device := self.find_device_by_uuid(uuid_part):
                if "," in assignment_str:
                    channel_num = assignment_str.split(",")[-1]
                    return f"{device.name} channel {channel_num}"
                return f"{device.name} ({assignment_str})"
            return assignment_str
        except (IndexError, ValueError):
            return assignment_str

    def list_devices(self) -> list[Device]:
        """List all registered devices."""
        return self._devices.copy()

    def __len__(self) -> int:
        """Return number of devices in registry."""
        return len(self._devices)

    def __iter__(self):
        """Iterate over devices."""
        return iter(self._devices)


@dataclass
class Service:
    """Represents a StageLinq service."""

    name: str
    port: int

    def __str__(self) -> str:
        return f"{self.name}:{self.port}"


class StateCategory(Enum):
    """Categories of device states."""

    TRACK_INFO = "track_info"
    DECK_STATE = "deck_state"
    SUBSCRIPTION = "subscription"
    CHANNEL_ASSIGNMENT = "channel_assignment"
    OTHER = "other"


class StateValueType(Enum):
    """StageLinq StateMap value types based on protocol documentation."""

    VALUE_FLOAT = 0  # Float value (type 0)
    STATE_BOOL = 1  # Boolean state (type 1)
    LOOP_STATE = 2  # Loop/button state (type 2)
    TRACK_DATA = 3  # Track data state (type 3)
    STRING_ENUM = 4  # String enumeration (type 4)
    STRING_TEXT = 8  # Text string (type 8)
    VALUE_INT = 10  # Integer value (type 10)
    SAMPLE_RATE = 14  # Sample rate/technical value (type 14)
    COLOR = 16  # Color value (type 16)


@dataclass
class State:
    """Represents a device state value with proper type handling."""

    name: str
    value: float | bool | str | int
    type_hint: int = 0

    @classmethod
    def from_json_data(cls, name: str, json_data: dict) -> State:
        """Create State from parsed JSON data with type information."""
        type_hint = json_data.get("type", 0)

        # Extract value based on type
        if type_hint in (0, 10, 14):  # Float/int values
            value = json_data.get("value", 0)
        elif type_hint in (1, 2, 3):  # Boolean states
            value = json_data.get("state", False)
        elif type_hint in (4, 8):  # String values
            value = json_data.get("string", "")
        elif type_hint == 16:  # Color values
            value = json_data.get("color", "#ff000000")
        else:
            # Unknown type, try to extract any available value
            value = (
                json_data.get("value")
                or json_data.get("state")
                or json_data.get("string")
                or json_data.get("color")
                or ""
            )

        return cls(name=name, value=value, type_hint=type_hint)

    def is_float_value(self) -> bool:
        """Check if this is a float/numeric value (types 0, 10, 14)."""
        return self.type_hint in (0, 10, 14)

    def is_boolean_state(self) -> bool:
        """Check if this is a boolean state (types 1, 2, 3)."""
        return self.type_hint in (1, 2, 3)

    def is_string_value(self) -> bool:
        """Check if this is a string value (types 4, 8)."""
        return self.type_hint in (4, 8)

    def is_color_value(self) -> bool:
        """Check if this is a color value (type 16)."""
        return self.type_hint == 16

    def get_typed_value(self) -> float | bool | str | int:
        """Get value with proper type casting."""
        if self.is_float_value():
            return (
                float(self.value) if isinstance(self.value, (int, str)) else self.value
            )
        elif self.is_boolean_state():
            return bool(self.value)
        elif self.is_string_value() or self.is_color_value():
            return str(self.value)
        else:
            return self.value

    def __str__(self) -> str:
        return f"{self.name}={self.value}"


@dataclass
class BeatInfo:
    """Represents beat timing information."""

    clock: int
    players: list[PlayerInfo]
    timelines: list[float]

    def __str__(self) -> str:
        return f"BeatInfo(clock={self.clock}, players={len(self.players)})"


@dataclass
class PlayerInfo:
    """Information about a player's beat state."""

    beat: float
    total_beats: float
    bpm: float

    def __str__(self) -> str:
        return f"Player(beat={self.beat:.2f}, bpm={self.bpm:.1f})"


class DeviceConnection:
    """Pythonic async connection to a StageLinq device."""

    def __init__(self, device: Device, token: Token) -> None:
        self.device = device
        self.token = token
        self._connection: StageLinqConnection | None = None
        self._services: list[Service] | None = None

    async def __aenter__(self) -> DeviceConnection:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit."""
        await self.disconnect()

    async def connect(self) -> None:
        """Connect to the device."""
        if self._connection is not None:
            return

        try:
            self._connection = StageLinqConnection(self.device.ip, self.device.port)
            await self._connection.connect()
            logger.info("Connected to device %s", self.device)
        except Exception as e:
            raise ConnectionError(f"Failed to connect to {self.device}: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        if self._connection:
            await self._connection.disconnect()
            self._connection = None
        logger.info("Disconnected from device %s", self.device)

    async def discover_services(
        self, timeout: float = 5.0, max_messages: int = 100
    ) -> list[Service]:
        """Discover available services on the device.

        Args:
            timeout: Maximum time to wait for service discovery (seconds)
            max_messages: Maximum number of messages to process

        Returns:
            List of discovered services

        Raises:
            TimeoutError: If service discovery times out
            ConnectionError: If connection to device fails
        """
        if self._services is not None:
            return self._services

        # Implement proper service discovery protocol
        # Connect to main port and request services
        main_conn = StageLinqConnection(self.device.ip, self.device.port)
        services = []

        try:
            await main_conn.connect()

            # Send services request message
            request = ServicesRequestMessage(token=self.token)
            await main_conn.send_message(request.serialize())

            # Collect service announcements until we get a reference message
            message_count = 0

            async def collect_services():
                nonlocal message_count
                async for message_data in main_conn.messages():
                    message_count += 1

                    # Safety check to prevent infinite loop
                    if message_count > max_messages:
                        logger.warning(
                            "Reached maximum message limit (%d) during service discovery",
                            max_messages,
                        )
                        break

                    with suppress(Exception):
                        # Try to parse as service announcement
                        service_msg = ServiceAnnouncementMessage.deserialize(
                            message_data
                        )
                        services.append(Service(service_msg.service, service_msg.port))
                        logger.debug(
                            "Discovered service: %s:%d",
                            service_msg.service,
                            service_msg.port,
                        )
                        continue

                    with suppress(Exception):
                        # Try to parse as reference message (signals end of services)
                        ReferenceMessage.deserialize(message_data)
                        logger.debug(
                            "Received reference message, ending service discovery"
                        )
                        break  # End of services list

            # Apply timeout to service collection
            try:
                await asyncio.wait_for(collect_services(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "Service discovery timed out after %gs, discovered %d services",
                    timeout,
                    len(services),
                )
                # Don't raise - return what we found

        finally:
            await main_conn.disconnect()

        self._services = services
        logger.info(
            "Discovered %d services: %s", len(services), [s.name for s in services]
        )
        return self._services

    @asynccontextmanager
    async def state_map(self) -> AsyncIterator[StateMap]:
        """Get a StateMap connection."""
        services = await self.discover_services()
        state_service = next((s for s in services if s.name == "StateMap"), None)
        if not state_service:
            raise ValueError("StateMap service not available")

        state_map = StateMap(self.device.ip, state_service.port, self.token)
        try:
            await state_map.connect()
            yield state_map
        finally:
            await state_map.disconnect()

    @asynccontextmanager
    async def beat_info(self) -> AsyncIterator[BeatInfoStream]:
        """Get a BeatInfo connection."""
        services = await self.discover_services()
        beat_service = next((s for s in services if s.name == "BeatInfo"), None)
        if not beat_service:
            raise ValueError("BeatInfo service not available")

        beat_info = BeatInfoStream(self.device.ip, beat_service.port, self.token)
        try:
            await beat_info.connect()
            yield beat_info
        finally:
            await beat_info.disconnect()

    @asynccontextmanager
    async def file_transfer(self) -> AsyncIterator[FileTransferConnection]:
        """Get a FileTransfer connection."""
        services = await self.discover_services()
        file_service = next((s for s in services if s.name == "FileTransfer"), None)
        if not file_service:
            raise ValueError("FileTransfer service not available")

        file_transfer = FileTransferConnection(
            self.device.ip, file_service.port, self.token
        )
        try:
            await file_transfer.connect()
            yield file_transfer
        finally:
            await file_transfer.disconnect()


class StateMap:
    """Pythonic StateMap connection for monitoring device state."""

    def __init__(self, host: str, port: int, token: Token) -> None:
        self.host = host
        self.port = port
        self.token = token
        self._connection: StageLinqConnection | None = None
        self._subscriptions: set[str] = set()

    async def connect(self) -> None:
        """Connect to StateMap service."""
        if self._connection:
            return

        self._connection = StageLinqConnection(self.host, self.port)
        await self._connection.connect()

        # Send service announcement message (required by protocol)
        # This announces our local port to the device, as observed in commercial DJ software

        announcement = ServiceAnnouncementMessage(
            token=self.token, service="StateMap", port=self._connection.local_port
        )
        await self._connection.send_message(announcement.serialize())

        logger.info("Connected to StateMap at %s:%s", self.host, self.port)

    async def disconnect(self) -> None:
        """Disconnect from StateMap service."""
        if self._connection:
            await self._connection.disconnect()
            self._connection = None
        logger.info("Disconnected from StateMap at %s:%s", self.host, self.port)

    async def subscribe(self, state_name: str, interval: int = 0) -> None:
        """Subscribe to state updates."""
        if not self._connection:
            raise RuntimeError("Not connected")

        if state_name in self._subscriptions:
            return

        msg = StateSubscribeMessage(name=state_name, interval=interval)
        await self._connection.send_message(msg.serialize())

        self._subscriptions.add(state_name)
        logger.debug("Subscribed to state: %s", state_name)

    async def states(self) -> AsyncIterator[State]:
        """Stream state updates."""
        if not self._connection:
            raise RuntimeError("Not connected")

        async for message_data in self._connection.messages():
            try:
                msg = StateEmitMessage.deserialize(message_data)

                # Parse JSON value with type information
                try:
                    json_data = json.loads(msg.json_data)
                    yield State.from_json_data(name=msg.name, json_data=json_data)
                except json.JSONDecodeError:
                    # Fallback for invalid JSON - create basic State
                    yield State(name=msg.name, value=msg.json_data, type_hint=0)

            except Exception as e:
                logger.error("Error parsing state message: %s", e)
                continue

    def categorize_state(self, state_name: str) -> StateCategory:
        """Categorize a state by its name."""
        if state_name.startswith("Subscribe_"):
            return StateCategory.SUBSCRIPTION
        elif "ChannelAssignment" in state_name:
            return StateCategory.CHANNEL_ASSIGNMENT
        elif any(
            keyword in state_name
            for keyword in [
                "/Track/CurrentBPM",
                "/Track/Title",
                "/Track/Artist",
                "/Track/Album",
                "/Track/TrackName",
                "/Track/ArtistName",
            ]
        ):
            return StateCategory.TRACK_INFO
        elif any(
            keyword in state_name
            for keyword in [
                "/PlayState",
                "/DeckIsMaster",
                "/LoopEnableState",
                "/LayerB",
                "/MasterStatus",
            ]
        ):
            return StateCategory.DECK_STATE
        else:
            return StateCategory.OTHER

    def extract_deck_info(self, state_name: str) -> tuple[str | None, str]:
        """Extract deck information from state name.

        Returns:
            tuple: (deck_name, base_name) where deck_name is like "Deck1" or None
        """
        # Look for DeckN pattern (where N is any number)
        deck_match = re.search(r"Deck(\d+)", state_name)
        if not deck_match:
            return None, state_name.split("/")[-1] if "/" in state_name else state_name
        deck_name = f"Deck{deck_match[1]}"
        return deck_name, state_name.split("/")[-1]

    def parse_state_value(self, json_data: str) -> Any:
        """Parse JSON state value with fallback handling."""
        try:
            return json.loads(json_data)
        except json.JSONDecodeError:
            return json_data

    def format_interval(self, interval: int) -> str:
        """Format an interval value for display."""
        return format_interval(interval)


class BeatInfoStream:
    """Pythonic BeatInfo connection for monitoring beat timing."""

    def __init__(self, host: str, port: int, token: Token) -> None:
        self.host = host
        self.port = port
        self.token = token
        self._connection: StageLinqConnection | None = None
        self._streaming = False

    async def connect(self) -> None:
        """Connect to BeatInfo service."""
        if self._connection:
            return

        self._connection = StageLinqConnection(self.host, self.port)
        await self._connection.connect()
        logger.info("Connected to BeatInfo at %s:%s", self.host, self.port)

    async def disconnect(self) -> None:
        """Disconnect from BeatInfo service."""
        if self._streaming:
            await self.stop_stream()

        if self._connection:
            await self._connection.disconnect()
            self._connection = None
        logger.info("Disconnected from BeatInfo at %s:%s", self.host, self.port)

    async def start_stream(self) -> None:
        """Start beat info streaming."""
        if not self._connection:
            raise RuntimeError("Not connected")

        if self._streaming:
            return

        msg = BeatInfoStartStreamMessage()
        await self._connection.send_message(msg.serialize())

        self._streaming = True
        logger.debug("Started beat info streaming")

    async def stop_stream(self) -> None:
        """Stop beat info streaming."""
        if not self._connection:
            raise RuntimeError("Not connected")

        if not self._streaming:
            return

        msg = BeatInfoStopStreamMessage()
        await self._connection.send_message(msg.serialize())

        self._streaming = False
        logger.debug("Stopped beat info streaming")

    async def beats(self) -> AsyncIterator[BeatInfo]:
        """Stream beat information."""
        if not self._connection:
            raise RuntimeError("Not connected")

        if not self._streaming:
            await self.start_stream()

        async for message_data in self._connection.messages():
            if not self._streaming:
                break

            try:
                msg = BeatEmitMessage.deserialize(message_data)

                yield BeatInfo(
                    clock=msg.clock, players=msg.players, timelines=msg.timelines
                )

            except Exception as e:
                logger.error("Error parsing beat message: %s", e)
                continue


# Extend the Device class with async methods
class AsyncDevice(Device):
    """Extended device with async connection methods."""

    def connect(self, token: Token) -> DeviceConnection:
        """Create a connection to this device."""
        return DeviceConnection(self, token)

    @asynccontextmanager
    async def state_map(self, token: Token) -> AsyncIterator[StateMap]:
        """Direct state map connection."""
        async with DeviceConnection(self, token) as conn:
            async with conn.state_map() as state_map:
                yield state_map

    @asynccontextmanager
    async def beat_info(self, token: Token) -> AsyncIterator[BeatInfoStream]:
        """Direct beat info connection."""
        async with DeviceConnection(self, token) as conn:
            async with conn.beat_info() as beat_info:
                yield beat_info

    @asynccontextmanager
    async def file_transfer(
        self, token: Token
    ) -> AsyncIterator[FileTransferConnection]:
        """Direct file transfer connection."""
        async with DeviceConnection(self, token) as conn:
            async with conn.file_transfer() as file_transfer:
                yield file_transfer
