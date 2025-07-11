"""StageLinq protocol messages."""

from __future__ import annotations

import contextlib
import io
import secrets
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO, TypeVar

T = TypeVar("T", bound="Message")


class Token:
    """16-byte token used for device authentication."""

    def __init__(self, data: bytes | None = None) -> None:
        if data is None:
            self.data = secrets.token_bytes(16)
        elif len(data) == 16:
            self.data = data
        else:
            raise ValueError("Token must be exactly 16 bytes")

    def __bytes__(self) -> bytes:
        return self.data

    def __eq__(self, other: object) -> bool:
        return self.data == other.data if isinstance(other, Token) else False

    def __str__(self) -> str:
        return self.data.hex()

    def __repr__(self) -> str:
        return f"Token({self.data.hex()[:16]}...)"


class MessageSerializer:
    """Pythonic message serializer that eliminates manual struct operations."""

    def __init__(self):
        self.endian = ">"  # Network byte order

    def write_uint32(self, writer: BinaryIO, value: int) -> None:
        """Write a 32-bit unsigned integer."""
        writer.write(struct.pack(f"{self.endian}I", value))

    def read_uint32(self, reader: BinaryIO) -> int:
        """Read a 32-bit unsigned integer."""
        data = reader.read(4)
        if len(data) != 4:
            raise EOFError("Failed to read uint32")
        return struct.unpack(f"{self.endian}I", data)[0]

    def write_uint16(self, writer: BinaryIO, value: int) -> None:
        """Write a 16-bit unsigned integer."""
        writer.write(struct.pack(f"{self.endian}H", value))

    def read_uint16(self, reader: BinaryIO) -> int:
        """Read a 16-bit unsigned integer."""
        data = reader.read(2)
        if len(data) != 2:
            raise EOFError("Failed to read uint16")
        return struct.unpack(f"{self.endian}H", data)[0]

    def write_int64(self, writer: BinaryIO, value: int) -> None:
        """Write a 64-bit signed integer."""
        writer.write(struct.pack(f"{self.endian}q", value))

    def read_int64(self, reader: BinaryIO) -> int:
        """Read a 64-bit signed integer."""
        data = reader.read(8)
        if len(data) != 8:
            raise EOFError("Failed to read int64")
        return struct.unpack(f"{self.endian}q", data)[0]

    def write_uint64(self, writer: BinaryIO, value: int) -> None:
        """Write a 64-bit unsigned integer."""
        writer.write(struct.pack(f"{self.endian}Q", value))

    def read_uint64(self, reader: BinaryIO) -> int:
        """Read a 64-bit unsigned integer."""
        data = reader.read(8)
        if len(data) != 8:
            raise EOFError("Failed to read uint64")
        return struct.unpack(f"{self.endian}Q", data)[0]

    def write_double(self, writer: BinaryIO, value: float) -> None:
        """Write a 64-bit double."""
        writer.write(struct.pack(f"{self.endian}d", value))

    def read_double(self, reader: BinaryIO) -> float:
        """Read a 64-bit double."""
        data = reader.read(8)
        if len(data) != 8:
            raise EOFError("Failed to read double")
        return struct.unpack(f"{self.endian}d", data)[0]

    def write_token(self, writer: BinaryIO, token: Token) -> None:
        """Write a 16-byte token."""
        writer.write(bytes(token))

    def read_token(self, reader: BinaryIO) -> Token:
        """Read a 16-byte token."""
        data = reader.read(16)
        if len(data) != 16:
            raise EOFError("Failed to read token")
        return Token(data)

    def write_utf16_string(self, writer: BinaryIO, text: str) -> None:
        """Write a UTF-16 string with length prefix."""
        if not text:
            self.write_uint32(writer, 0)
            return

        encoded = text.encode("utf-16be")
        self.write_uint32(writer, len(encoded))
        writer.write(encoded)

    def read_utf16_string(self, reader: BinaryIO, max_length: int = 64 * 1024) -> str:
        """Read a UTF-16 string with length prefix.

        Args:
            reader: Binary stream to read from
            max_length: Maximum allowed string length in bytes (default: 64KB)

        Returns:
            Decoded UTF-16 string

        Raises:
            ValueError: If string length exceeds max_length
            EOFError: If unable to read expected amount of data
        """
        length = self.read_uint32(reader)
        if length == 0:
            return ""

        # Validate string length to prevent memory exhaustion
        if length > max_length:
            raise ValueError(
                f"String length {length} exceeds maximum allowed length {max_length}"
            )

        # Additional sanity check for reasonable string lengths
        if length > 10 * 1024 * 1024:  # 10MB absolute limit
            raise ValueError(f"String length {length} is unreasonably large")

        data = reader.read(length)
        if len(data) != length:
            raise EOFError(
                f"Failed to read string data: expected {length} bytes, got {len(data)}"
            )

        try:
            return data.decode("utf-16be")
        except UnicodeDecodeError as e:
            raise ValueError(f"Invalid UTF-16 string data: {e}") from e


# Global serializer instance
serializer = MessageSerializer()


class LengthPrefixedReader:
    """Utility for handling length-prefixed message parsing."""

    @staticmethod
    def read_with_length_prefix(
        reader: BinaryIO, expected_magic: bytes | None = None
    ) -> BinaryIO:
        """
        Read a length-prefixed message and return a reader for the content.

        Args:
            reader: Source reader
            expected_magic: If provided, will peek to check if length prefix is needed

        Returns:
            BinaryIO reader positioned at the message content
        """
        if expected_magic:
            # Peek at first bytes to check if length prefix exists
            current_pos = reader.tell()
            first_bytes = reader.read(len(expected_magic))
            reader.seek(current_pos)

            # If starts with magic, no length prefix
            if first_bytes == expected_magic:
                return reader

        # Read length prefix
        length = serializer.read_uint32(reader)

        # Read message content
        message_data = reader.read(length)
        if len(message_data) != length:
            raise EOFError(
                f"Failed to read complete message: expected {length} bytes, got {len(message_data)}"
            )

        return io.BytesIO(message_data)

    @staticmethod
    def write_with_length_prefix(writer: BinaryIO, content_writer_func) -> None:
        """
        Write a message with length prefix.

        Args:
            writer: Destination writer
            content_writer_func: Function that writes content to a BytesIO buffer
        """
        # Build message payload
        payload = io.BytesIO()
        content_writer_func(payload)

        # Write length and payload
        payload_data = payload.getvalue()
        serializer.write_uint32(writer, len(payload_data))
        writer.write(payload_data)


class Message(ABC):
    """Base class for all StageLinq messages."""

    @abstractmethod
    def read_from(self, reader: BinaryIO) -> None:
        """Read message from stream."""

    @abstractmethod
    def write_to(self, writer: BinaryIO) -> None:
        """Write message to stream."""

    def serialize(self) -> bytes:
        """Serialize message to bytes."""
        buffer = io.BytesIO()
        self.write_to(buffer)
        return buffer.getvalue()

    @classmethod
    def deserialize(cls: type[T], data: bytes) -> T:
        """Deserialize bytes to message."""
        buffer = io.BytesIO(data)
        instance = cls()
        instance.read_from(buffer)
        return instance


# Discovery message types
DISCOVERER_HOWDY = "DISCOVERER_HOWDY_"
DISCOVERER_EXIT = "DISCOVERER_EXIT_"
DISCOVERY_MAGIC = b"airD"


@dataclass
class DiscoveryMessage(Message):
    """Message for device discovery on UDP port 51337."""

    token: Token
    source: str = ""
    action: str = ""
    software_name: str = ""
    software_version: str = ""
    port: int = 0

    def __init__(
        self,
        token: Token | None = None,
        source: str = "",
        action: str = "",
        software_name: str = "",
        software_version: str = "",
        port: int = 0,
    ):
        self.token = token or Token()
        self.source = source
        self.action = action
        self.software_name = software_name
        self.software_version = software_version
        self.port = port

    def read_from(self, reader: BinaryIO) -> None:
        """Read message from stream."""
        magic = reader.read(4)
        if magic != DISCOVERY_MAGIC:
            raise ValueError("Invalid discovery magic")

        self.token = serializer.read_token(reader)
        # Use reasonable limits for discovery message fields
        self.source = serializer.read_utf16_string(
            reader, max_length=512
        )  # Device name
        self.action = serializer.read_utf16_string(
            reader, max_length=128
        )  # Action string
        self.software_name = serializer.read_utf16_string(
            reader, max_length=256
        )  # Software name
        self.software_version = serializer.read_utf16_string(
            reader, max_length=128
        )  # Version string
        self.port = serializer.read_uint16(reader)

    def write_to(self, writer: BinaryIO) -> None:
        """Write message to stream."""
        writer.write(DISCOVERY_MAGIC)
        serializer.write_token(writer, self.token)
        serializer.write_utf16_string(writer, self.source)
        serializer.write_utf16_string(writer, self.action)
        serializer.write_utf16_string(writer, self.software_name)
        serializer.write_utf16_string(writer, self.software_version)
        serializer.write_uint16(writer, self.port)


class TokenPrefixedMessage(Message):
    """Base class for messages that start with a token."""

    def __init__(self, token: Token | None = None):
        self.token = token or Token()

    @property
    @abstractmethod
    def MESSAGE_ID(self) -> int:
        """Message ID that must be implemented by subclasses."""

    def read_message_id(self, reader: BinaryIO) -> int:
        """Read and validate message ID."""
        message_id = serializer.read_uint32(reader)
        if message_id != self.MESSAGE_ID:
            raise ValueError(
                f"Invalid message ID: expected {self.MESSAGE_ID:#x}, got {message_id:#x}"
            )
        return message_id

    def write_message_id(self, writer: BinaryIO) -> None:
        """Write message ID."""
        serializer.write_uint32(writer, self.MESSAGE_ID)


@dataclass
class ServiceAnnouncementMessage(TokenPrefixedMessage):
    """Message announcing a service on a specific port."""

    service: str = ""
    port: int = 0

    @property
    def MESSAGE_ID(self) -> int:
        """Service announcement message ID."""
        return 0x00000000

    def __init__(self, token: Token | None = None, service: str = "", port: int = 0):
        super().__init__(token)
        self.service = service
        self.port = port

    def read_from(self, reader: BinaryIO) -> None:
        """Read message from stream."""
        self.read_message_id(reader)
        self.token = serializer.read_token(reader)
        self.service = serializer.read_utf16_string(
            reader, max_length=256
        )  # Service name
        self.port = serializer.read_uint16(reader)

    def write_to(self, writer: BinaryIO) -> None:
        """Write message to stream."""
        self.write_message_id(writer)
        serializer.write_token(writer, self.token)
        serializer.write_utf16_string(writer, self.service)
        serializer.write_uint16(writer, self.port)


@dataclass
class ReferenceMessage(TokenPrefixedMessage):
    """Message containing reference information."""

    token2: Token = None
    reference: int = 0

    @property
    def MESSAGE_ID(self) -> int:
        """Reference message ID."""
        return 0x00000001

    def __init__(
        self,
        token: Token | None = None,
        token2: Token | None = None,
        reference: int = 0,
    ):
        super().__init__(token)
        self.token2 = token2 or Token()
        self.reference = reference

    def read_from(self, reader: BinaryIO) -> None:
        """Read message from stream."""
        self.read_message_id(reader)
        self.token = serializer.read_token(reader)
        self.token2 = serializer.read_token(reader)
        self.reference = serializer.read_int64(reader)

    def write_to(self, writer: BinaryIO) -> None:
        """Write message to stream."""
        self.write_message_id(writer)
        serializer.write_token(writer, self.token)
        serializer.write_token(writer, self.token2)
        serializer.write_int64(writer, self.reference)


class ServicesRequestMessage(TokenPrefixedMessage):
    """Message requesting available services."""

    @property
    def MESSAGE_ID(self) -> int:
        """Services request message ID."""
        return 0x00000002

    def read_from(self, reader: BinaryIO) -> None:
        """Read message from stream."""
        self.read_message_id(reader)
        self.token = serializer.read_token(reader)

    def write_to(self, writer: BinaryIO) -> None:
        """Write message to stream."""
        self.write_message_id(writer)
        serializer.write_token(writer, self.token)


# State map message types
SMAA_MAGIC = b"smaa"

# Beat info message types
BEAT_INFO_START_STREAM_MAGIC = b"\x00\x00\x00\x00"
BEAT_INFO_STOP_STREAM_MAGIC = b"\x00\x00\x00\x01"
BEAT_EMIT_MAGIC = b"\x00\x00\x00\x02"

# Special protocol values
NO_UPDATES_INTERVAL = 4294967295  # 0xFFFFFFFF - indicates no periodic updates


@dataclass
class StateSubscribeMessage(Message):
    """Message to subscribe to state updates."""

    name: str = ""
    interval: int = 0

    MAGIC_ID = 0x000007D2

    def read_from(self, reader: BinaryIO) -> None:
        """Read message from stream."""
        msg_reader = LengthPrefixedReader.read_with_length_prefix(reader)

        magic = msg_reader.read(4)
        if magic != SMAA_MAGIC:
            raise ValueError("Invalid SMAA magic")

        magic_id = serializer.read_uint32(msg_reader)
        if magic_id != self.MAGIC_ID:
            raise ValueError(f"Invalid magic ID: {magic_id}")

        self.name = serializer.read_utf16_string(
            msg_reader, max_length=1024
        )  # State name
        self.interval = serializer.read_uint32(msg_reader)

    def write_to(self, writer: BinaryIO) -> None:
        """Write message to stream."""

        def write_content(payload):
            payload.write(SMAA_MAGIC)
            serializer.write_uint32(payload, self.MAGIC_ID)
            serializer.write_utf16_string(payload, self.name)
            serializer.write_uint32(payload, self.interval)

        LengthPrefixedReader.write_with_length_prefix(writer, write_content)


@dataclass
class StateEmitMessage(Message):
    """Message containing state data."""

    name: str = ""
    json_data: str = ""

    MAGIC_ID = 0x00000000  # This is for state emit messages

    def read_from(self, reader: BinaryIO) -> None:
        """Read message from stream."""
        # Use utility to handle conditional length prefix
        msg_reader = LengthPrefixedReader.read_with_length_prefix(reader, SMAA_MAGIC)

        magic = msg_reader.read(4)
        if magic != SMAA_MAGIC:
            raise ValueError("Invalid SMAA magic")

        magic_id = serializer.read_uint32(msg_reader)
        if magic_id != self.MAGIC_ID:
            raise ValueError(f"Invalid magic ID: {magic_id}")

        self.name = serializer.read_utf16_string(
            msg_reader, max_length=1024
        )  # State name

        # Read JSON data - it's actually a UTF-16 string with length prefix
        json_data_str = serializer.read_utf16_string(
            msg_reader, max_length=8192
        )  # JSON data
        self.json_data = json_data_str

    def write_to(self, writer: BinaryIO) -> None:
        """Write message to stream."""

        def write_content(payload):
            payload.write(SMAA_MAGIC)
            serializer.write_uint32(payload, self.MAGIC_ID)
            serializer.write_utf16_string(payload, self.name)
            serializer.write_utf16_string(payload, self.json_data)

        LengthPrefixedReader.write_with_length_prefix(writer, write_content)


@dataclass
class PlayerInfo:
    """Information about a player's beat state."""

    beat: float = 0.0
    total_beats: float = 0.0
    bpm: float = 0.0

    def __str__(self) -> str:
        return f"Player(beat={self.beat:.2f}, bpm={self.bpm:.1f})"


@dataclass
class BeatInfoStartStreamMessage(Message):
    """Message to start streaming beat information."""

    def read_from(self, reader: BinaryIO) -> None:
        """Read message from stream."""
        _length = serializer.read_uint32(reader)

        magic = reader.read(4)
        if magic != BEAT_INFO_START_STREAM_MAGIC:
            raise ValueError("Invalid beat info start stream magic")

    def write_to(self, writer: BinaryIO) -> None:
        """Write message to stream."""
        # Write length (4 bytes for magic)
        serializer.write_uint32(writer, len(BEAT_INFO_START_STREAM_MAGIC))
        writer.write(BEAT_INFO_START_STREAM_MAGIC)


@dataclass
class BeatInfoStopStreamMessage(Message):
    """Message to stop streaming beat information."""

    def read_from(self, reader: BinaryIO) -> None:
        """Read message from stream."""
        _length = serializer.read_uint32(reader)

        magic = reader.read(4)
        if magic != BEAT_INFO_STOP_STREAM_MAGIC:
            raise ValueError("Invalid beat info stop stream magic")

    def write_to(self, writer: BinaryIO) -> None:
        """Write message to stream."""
        # Write length (4 bytes for magic)
        serializer.write_uint32(writer, len(BEAT_INFO_STOP_STREAM_MAGIC))
        writer.write(BEAT_INFO_STOP_STREAM_MAGIC)


class BeatEmitMessage(Message):
    """Message containing beat timing information."""

    def __init__(
        self,
        clock: int = 0,
        players: list[PlayerInfo] | None = None,
        timelines: list[float] | None = None,
    ):
        self.clock: int = clock
        self.players: list[PlayerInfo] = players or []
        self.timelines: list[float] = timelines or []

    def read_from(self, reader: BinaryIO) -> None:
        """Read message from stream."""
        # Read expected message length
        length = serializer.read_uint32(reader)

        # Read entire message into buffer
        message_data = reader.read(length)
        if len(message_data) != length:
            raise EOFError("Failed to read complete beat emit message")

        msg_reader = io.BytesIO(message_data)

        # Read and validate magic bytes
        magic = msg_reader.read(4)
        if magic != BEAT_EMIT_MAGIC:
            raise ValueError("Invalid beat emit magic bytes")

        # Read clock value
        self.clock = serializer.read_uint64(msg_reader)

        # Read number of expected records
        num_records = serializer.read_uint32(msg_reader)

        # Bounds check - each player record is 24 bytes
        if msg_reader.tell() + (num_records * 24) > len(message_data):
            raise ValueError("Not enough data for player records")

        # Read player records
        self.players = []
        for _ in range(num_records):
            beat = serializer.read_double(msg_reader)
            total_beats = serializer.read_double(msg_reader)
            bpm = serializer.read_double(msg_reader)
            self.players.append(PlayerInfo(beat=beat, total_beats=total_beats, bpm=bpm))

        # Bounds check - remaining bytes should match timeline records (8 bytes each)
        remaining_bytes = len(message_data) - msg_reader.tell()
        if remaining_bytes != num_records * 8:
            raise ValueError("Incorrect number of timeline records")

        # Read timeline records
        self.timelines = []
        for _ in range(num_records):
            timeline = serializer.read_double(msg_reader)
            self.timelines.append(timeline)

    def write_to(self, writer: BinaryIO) -> None:
        """Write message to stream."""
        # Validate that players and timelines match
        num_records = len(self.players)
        if num_records != len(self.timelines):
            raise ValueError("Number of players must match number of timelines")

        # Build message payload
        payload = io.BytesIO()

        # Write magic bytes
        payload.write(BEAT_EMIT_MAGIC)

        # Write clock value
        serializer.write_uint64(payload, self.clock)

        # Write number of records
        serializer.write_uint32(payload, num_records)

        # Write all player records
        for player in self.players:
            serializer.write_double(payload, player.beat)
            serializer.write_double(payload, player.total_beats)
            serializer.write_double(payload, player.bpm)

        # Write all timeline records
        for timeline in self.timelines:
            serializer.write_double(payload, timeline)

        # Write length prefix and payload
        payload_data = payload.getvalue()
        serializer.write_uint32(writer, len(payload_data))
        writer.write(payload_data)


# Convenience functions for creating common messages
def create_discovery_message(
    token: Token | None = None,
    source: str = "Python StageLinq",
    action: str = DISCOVERER_HOWDY,
    software_name: str = "python-stagelinq",
    software_version: str = "0.1.0",
    port: int = 51337,
) -> DiscoveryMessage:
    """Create a discovery message with sensible defaults."""
    return DiscoveryMessage(
        token=token,
        source=source,
        action=action,
        software_name=software_name,
        software_version=software_version,
        port=port,
    )


def create_state_subscribe(name: str = "", interval: int = 0) -> StateSubscribeMessage:
    """Create a state subscription message."""
    return StateSubscribeMessage(name=name, interval=interval)


def create_beat_start_stream() -> BeatInfoStartStreamMessage:
    """Create a beat info start stream message."""
    return BeatInfoStartStreamMessage()


def create_beat_stop_stream() -> BeatInfoStopStreamMessage:
    """Create a beat info stop stream message."""
    return BeatInfoStopStreamMessage()


def create_beat_emit(
    clock: int = 0,
    players: list[PlayerInfo] | None = None,
    timelines: list[float] | None = None,
) -> BeatEmitMessage:
    """Create a beat emit message."""
    return BeatEmitMessage(clock=clock, players=players, timelines=timelines)


# Utility functions for special protocol values
def format_interval(interval: int) -> str:
    """Format an interval value for display."""
    return "no-updates" if interval == NO_UPDATES_INTERVAL else str(interval)


def is_no_updates_interval(interval: int) -> bool:
    """Check if an interval indicates no periodic updates."""
    return interval == NO_UPDATES_INTERVAL


def parse_beat_message(payload: bytes) -> Message | None:
    """Parse a beat-related message from payload bytes.

    Tries to parse the payload as different types of beat messages:
    1. BeatInfoStartStreamMessage
    2. BeatInfoStopStreamMessage
    3. BeatEmitMessage

    Returns:
        The parsed message object, or None if parsing fails
    """
    if len(payload) < 8:  # Need at least length prefix + some data
        return None

    # Try BeatInfoStartStreamMessage
    with contextlib.suppress(Exception):
        return BeatInfoStartStreamMessage.deserialize(payload)

    # Try BeatInfoStopStreamMessage
    with contextlib.suppress(Exception):
        return BeatInfoStopStreamMessage.deserialize(payload)

    # Try BeatEmitMessage
    with contextlib.suppress(Exception):
        return BeatEmitMessage.deserialize(payload)

    # No valid beat message found
    return None
