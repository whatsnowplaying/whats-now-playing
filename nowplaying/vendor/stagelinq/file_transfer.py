"""StagelinQ file transfer implementation.

Based on the FileTransfer protocol analysis from:
https://github.com/icedream/go-stagelinq/issues/8

Protocol Notes:
- 0x02: FRAME_END (frame end with success flag - triggers auto-crawling)
- 0x06: STREAM_UPDATE (live database updates when transfer not completed)
- 0x09: DIRECTORY_INVALIDATE (directory invalidation when storage ejected)
- 0x0A: TRANSFER_STATUS_QUERY (query if transfer ID is still active)
- 0x7D1: DATABASE_PATH request
- 0x7D2: DIRECTORY_LIST (ls/dir - list directory contents with path parameter)
- 0x7D3: SESSION_CLEANUP (end of inquiry, no response expected)
- 0x7D4: DATABASE_INFO (complex stat response with file size in last 8 bytes)
- 0x7D5: DATABASE_READ (chunked file download, 4096 byte chunks)
- 0x7D6: REQUEST_COMPLETE (end of transfer)
- 0x7D8: PAUSE_TRANSFER (suspend transfer session, will resume later)

The request ID field after 'fltx' magic enables async request/response correlation.
Database files can be streamed live by omitting the 0x7D6 completion message.

Directory List Response Trailer (last 3 bytes):
- Byte 1: First payload flag (0x01 = first chunk of response)
- Byte 2: Last payload flag (0x01 = last chunk of response)
- Byte 3: Content type flag (0x01 = directories/volumes, 0x00 = files)

Directory Auto-Crawling:
- After 0x7D2 responses, devices send 0x02 (FRAME_END) with success flag
- Success flag = true: Device automatically crawls subdirectories
- Success flag = false: Device stops directory traversal
- Enables automatic discovery of "Engine Library" and music directories

Storage Device Events:
- 0x09 messages are sent when storage devices are ejected
- Contains the transaction ID from previous directory list requests
- Used to invalidate cached directory contents for ejected volumes

Transfer Session Management (discovered May 5, 2023 by @honusz):
- 0x7D8 indicates session pause: "okay, I'm going to pause on this txid for a
  minute and do some other stuff, but I may come back to it"
- Observed pattern: device may pause one transfer to handle another, then resume
- Transfer sessions can be interleaved across multiple transaction IDs
- 0x0A query may be sent to check if a transfer ID is still active before 0x7D8 response
- Player can return to paused transfer ID later and continue with 0x7D5 chunk requests

DATABASE_INFO Response Structure (discovered May 9, 2023):
The 0x7D4 stat response is critical for successful file serving to Denon equipment.
Structure breakdown (49 bytes after length-fltx-txId-messageId):

- File size is in the LAST 8 BYTES (not penultimate 4 bytes as previously thought)
- First byte: boolean "Exists" (0x01 = exists, 0x00 = does not exist)
- Second byte: boolean "IsDirectory" (0x01 = directory, 0x00 = file)
- Bytes 3-4: 00 00 (unknown/padding)
- Next 2 bytes: file permissions (77 55, 66 44, or 00 00 for non-existing)
- Remaining 35 bytes appear to be three 13-byte repetitions with patterns:
  * First byte: 00 or 80
  * Next 4 bytes: 00 00 00 00
  * 6th byte: always 25 if valid
  * Bytes 7-12: timestamp-related data (changes on file copy operations)
  * Byte 13: always 00

Analysis of copy operations shows:
- Original file and copies have same permissions (77 55)
- Timestamp data in metadata blocks differs between copies
- Multiple copies made seconds apart share identical timestamp values
- Suggests metadata contains creation/modification times or inode-like data

Without proper stat response structure, Denon equipment will:
- Jump erratically between chunks (e.g., chunk 0 to chunk 12)
- Determine database is corrupt and abort transfer
- Display corruption error on device

For successful file serving, the stat response must match expected Denon format exactly.
Recommendation: Capture stat responses from working USB files and replicate structure.

Remote Source Implementation:
- Computers can appear as storage sources by implementing proper responses
- Must respond to 0x7D2 with directory listings and 0x02 with success flags
- Device will auto-crawl looking for "Engine Library" directory structure
"""

from __future__ import annotations

import io
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .messages import Message, Token, serializer
from .protocol import StagelinQConnection

logger = logging.getLogger(__name__)

# FileTransfer protocol constants
FLTX_MAGIC = b"fltx"
FILE_TRANSFER_REQUEST_DIRECTORY_LIST = 0x7D2  # List directory contents (ls/dir)
FILE_TRANSFER_REQUEST_DATABASE_PATH = 0x7D1
FILE_TRANSFER_SESSION_CLEANUP = (
    0x7D3  # End of inquiry/session cleanup (no response expected)
)
FILE_TRANSFER_REQUEST_DATABASE_INFO = 0x7D4
FILE_TRANSFER_REQUEST_DATABASE_READ = 0x7D5
FILE_TRANSFER_FRAME_END = 0x2  # Frame end with success flag
FILE_TRANSFER_REQUEST_COMPLETE = 0x7D6
FILE_TRANSFER_REQUEST_END = 0x0
FILE_TRANSFER_PAUSE_TRANSFER = (
    0x7D8  # Pause/suspend transfer session (will resume later)
)
FILE_TRANSFER_STREAM_UPDATE = 0x6  # Live database update (when transfer not completed)
FILE_TRANSFER_DIRECTORY_INVALIDATE = 0x9  # Directory invalidation when storage ejected
FILE_TRANSFER_STATUS_QUERY = 0x0A  # Query if transfer ID is still active

# Protocol chunk size for file transfers
CHUNK_SIZE = 4096


@dataclass
class FileInfo:
    """Information about a file on the StagelinQ device."""

    path: str
    name: str
    size: int | None = None
    modified_time: str | None = None
    is_directory: bool = False

    def __str__(self) -> str:
        type_str = "DIR" if self.is_directory else "FILE"
        size_str = f" ({self.size} bytes)" if self.size is not None else ""
        return f"{type_str}: {self.name}{size_str}"


@dataclass
class FileSource:
    """Information about a file source on the StagelinQ device."""

    name: str
    database_path: str
    database_size: int = 0

    def __str__(self) -> str:
        return f"{self.name} -> {self.database_path} ({self.database_size} bytes)"


class FileAnnouncementMessage(Message):
    """File announcement message using fltx protocol."""

    def __init__(
        self, path: str = "", message_type: int = 0, size: int = 0, request_id: int = 0
    ):
        self.path = path
        self.message_type = message_type
        self.size = size
        self.request_id = request_id

    def read_from(self, reader: BinaryIO) -> None:
        """Read file announcement message from stream."""
        # Read magic
        magic = reader.read(4)
        if magic != FLTX_MAGIC:
            raise ValueError(f"Invalid magic: expected {FLTX_MAGIC}, got {magic}")

        # Read request ID (for async request/response correlation)
        self.request_id = serializer.read_uint32(reader)

        # Read message type
        self.message_type = serializer.read_uint32(reader)

        # Read size field
        self.size = serializer.read_uint32(reader)

        if path_data := reader.read():
            self.path = path_data.decode("utf-16be").rstrip("\x00")
        else:
            self.path = ""

    def write_to(self, writer: BinaryIO) -> None:
        """Write file announcement message to stream."""
        # Write magic
        writer.write(FLTX_MAGIC)

        # Write request ID (for async request/response correlation)
        serializer.write_uint32(writer, self.request_id)

        # Write message type
        serializer.write_uint32(writer, self.message_type)

        # Write size
        serializer.write_uint32(writer, self.size)

        # Write path as UTF-16BE
        if self.path:
            path_data = self.path.encode("utf-16be")
            writer.write(path_data)

    def serialize(self) -> bytes:
        """Serialize message with length prefix."""
        # First serialize the message content
        content = io.BytesIO()
        self.write_to(content)
        content_bytes = content.getvalue()

        # Then add length prefix
        output = io.BytesIO()
        serializer.write_uint32(output, len(content_bytes))
        output.write(content_bytes)
        return output.getvalue()

    @classmethod
    def deserialize(cls, data: bytes) -> FileAnnouncementMessage:
        """Deserialize message from bytes."""
        reader = io.BytesIO(data)

        # Read length prefix
        length = serializer.read_uint32(reader)

        # Read message content
        content = reader.read(length)
        content_reader = io.BytesIO(content)

        # Create instance and read from content
        instance = cls()
        instance.read_from(content_reader)
        return instance


class FileTransferRequestMessage(Message):
    """Request message for FileTransfer operations."""

    def __init__(
        self,
        request_type: int = FILE_TRANSFER_REQUEST_DIRECTORY_LIST,
        request_id: int = 0,
    ):
        self.request_type = request_type
        self.request_id = request_id

    def read_from(self, reader: BinaryIO) -> None:
        """Read message from stream."""
        # Read request type
        self.request_type = serializer.read_uint32(reader)

    def write_to(self, writer: BinaryIO) -> None:
        """Write message to stream."""
        # Write request type
        serializer.write_uint32(writer, self.request_type)
        # Write end marker
        serializer.write_uint32(writer, FILE_TRANSFER_REQUEST_END)
        # Write final marker
        writer.write(b"\x01")


class FileTransferResponseMessage(Message):
    """Response message for FileTransfer operations."""

    def __init__(self):
        self.sources: list[FileSource] = []
        self.is_first_chunk: bool = False
        self.is_last_chunk: bool = False
        self.is_directories: bool = False  # True = directories/volumes, False = files

    def read_from(self, reader: BinaryIO) -> None:
        """Read message from stream."""
        # Read all available data
        data = reader.read()
        if not data:
            return

        # Parse trailer flags from last 3 bytes
        if len(data) >= 3:
            trailer = data[-3:]
            self.is_first_chunk = bool(trailer[0] & 0x01)
            self.is_last_chunk = bool(trailer[1] & 0x01)
            self.is_directories = bool(trailer[2] & 0x01)

            # Process data excluding trailer
            content_data = data[:-3]
        else:
            # No trailer, assume single complete response with files
            content_data = data
            self.is_first_chunk = True
            self.is_last_chunk = True
            self.is_directories = False

        # Parse the response data - it should contain FileAnnouncementMessage objects
        pos = 0
        while pos < len(content_data):
            try:
                # Look for file announcement magic bytes
                if (
                    pos + 4 <= len(content_data)
                    and content_data[pos : pos + 4] == FLTX_MAGIC
                ):
                    # Found a file announcement message
                    remaining_data = content_data[pos:]
                    msg_reader = io.BytesIO(remaining_data)

                    try:
                        # Parse the file announcement
                        announcement = FileAnnouncementMessage()
                        announcement.read_from(msg_reader)

                        # Create FileSource with database_size from announcement.size
                        source = FileSource(
                            name=announcement.path or "Unknown Source",
                            database_path=announcement.path or "",
                            database_size=announcement.size,
                        )
                        self.sources.append(source)

                        logger.debug(
                            "Found file source: %s (size: %d bytes)",
                            source.name,
                            source.database_size,
                        )

                        # Move position forward (rough estimate)
                        pos += (
                            16 + len(announcement.path.encode("utf-16be"))
                            if announcement.path
                            else 16
                        )

                    except Exception as e:
                        logger.debug(
                            "Failed to parse file announcement at pos %d: %s", pos, e
                        )
                        pos += 1
                else:
                    pos += 1

            except Exception:
                break

    def write_to(self, writer: BinaryIO) -> None:
        """Write message to stream."""
        # FileTransferResponseMessage is typically only read, not written
        # But we need to implement this for the abstract base class


class FileTransferInvalidateMessage(Message):
    """Message indicating directory invalidation when storage is ejected."""

    def __init__(self, transaction_id: int = 0):
        self.transaction_id = transaction_id

    def read_from(self, reader: BinaryIO) -> None:
        """Read invalidation message from stream."""
        # Read fltx magic
        magic = reader.read(4)
        if magic != FLTX_MAGIC:
            raise ValueError(f"Invalid magic: expected {FLTX_MAGIC}, got {magic}")

        # Read request ID
        self.transaction_id = serializer.read_uint32(reader)

        # Read message type (should be 0x9)
        message_type = serializer.read_uint32(reader)
        if message_type != FILE_TRANSFER_DIRECTORY_INVALIDATE:
            raise ValueError(
                f"Expected invalidate message type 0x9, got {message_type:#x}"
            )

    def write_to(self, writer: BinaryIO) -> None:
        """Write invalidation message to stream."""
        writer.write(FLTX_MAGIC)
        serializer.write_uint32(writer, self.transaction_id)
        serializer.write_uint32(writer, FILE_TRANSFER_DIRECTORY_INVALIDATE)


class FileTransferFrameEndMessage(Message):
    """Frame end message with success flag that controls directory auto-crawling."""

    def __init__(self, transaction_id: int = 0, success: bool = True):
        self.transaction_id = transaction_id
        self.success = success  # True = continue crawling, False = stop

    def read_from(self, reader: BinaryIO) -> None:
        """Read frame end message from stream."""
        # Read fltx magic
        magic = reader.read(4)
        if magic != FLTX_MAGIC:
            raise ValueError(f"Invalid magic: expected {FLTX_MAGIC}, got {magic}")

        # Read transaction ID
        self.transaction_id = serializer.read_uint32(reader)

        # Read message type (should be 0x2)
        message_type = serializer.read_uint32(reader)
        if message_type != FILE_TRANSFER_FRAME_END:
            raise ValueError(
                f"Expected frame end message type 0x2, got {message_type:#x}"
            )

        if success_byte := reader.read(1):
            self.success = bool(success_byte[0])
        else:
            self.success = False

    def write_to(self, writer: BinaryIO) -> None:
        """Write frame end message to stream."""
        writer.write(FLTX_MAGIC)
        serializer.write_uint32(writer, self.transaction_id)
        serializer.write_uint32(writer, FILE_TRANSFER_FRAME_END)
        writer.write(b"\x01" if self.success else b"\x00")


class FileTransferPauseMessage(Message):
    """Message indicating transfer session pause/suspend (0x7D8).

    Discovered by @honusz on May 5, 2023. This message indicates:
    'okay, I'm going to pause on this txid for a minute and do some other stuff,
    but I may come back to it later'
    """

    def __init__(self, transaction_id: int = 0):
        self.transaction_id = transaction_id

    def read_from(self, reader: BinaryIO) -> None:
        """Read pause message from stream."""
        # Read fltx magic
        magic = reader.read(4)
        if magic != FLTX_MAGIC:
            raise ValueError(f"Invalid magic: expected {FLTX_MAGIC}, got {magic}")

        # Read transaction ID
        self.transaction_id = serializer.read_uint32(reader)

        # Read message type (should be 0x7D8)
        message_type = serializer.read_uint32(reader)
        if message_type != FILE_TRANSFER_PAUSE_TRANSFER:
            raise ValueError(
                f"Expected pause message type 0x7D8, got {message_type:#x}"
            )

    def write_to(self, writer: BinaryIO) -> None:
        """Write pause message to stream."""
        writer.write(FLTX_MAGIC)
        serializer.write_uint32(writer, self.transaction_id)
        serializer.write_uint32(writer, FILE_TRANSFER_PAUSE_TRANSFER)


class FileTransferStatusQueryMessage(Message):
    """Message querying if a transfer ID is still active (0x0A).

    Discovered by @honusz on May 5, 2023. This appears to be a query message
    that may be sent before 0x7D8 pause responses to check transfer status.
    """

    def __init__(
        self,
        transaction_id: int = 0,
        query_data: bytes = b"\x01\x00\x00\x00\x00\x00\x00\x00\x00",
    ):
        self.transaction_id = transaction_id
        self.query_data = query_data  # Observed: 01 00 00 00 00 00 00 00 00

    def read_from(self, reader: BinaryIO) -> None:
        """Read status query message from stream."""
        # Read fltx magic
        magic = reader.read(4)
        if magic != FLTX_MAGIC:
            raise ValueError(f"Invalid magic: expected {FLTX_MAGIC}, got {magic}")

        # Read transaction ID
        self.transaction_id = serializer.read_uint32(reader)

        # Read message type (should be 0x0A)
        message_type = serializer.read_uint32(reader)
        if message_type != FILE_TRANSFER_STATUS_QUERY:
            raise ValueError(
                f"Expected status query message type 0x0A, got {message_type:#x}"
            )

        # Read remaining query data
        self.query_data = reader.read()

    def write_to(self, writer: BinaryIO) -> None:
        """Write status query message to stream."""
        writer.write(FLTX_MAGIC)
        serializer.write_uint32(writer, self.transaction_id)
        serializer.write_uint32(writer, FILE_TRANSFER_STATUS_QUERY)
        writer.write(self.query_data)


@dataclass
class DatabaseInfoResponse:
    """Parsed DATABASE_INFO (0x7D4) response structure.

    Discovered May 9, 2023: The stat response has a complex 49-byte structure
    that is critical for successful file serving to Denon equipment.
    """

    file_exists: bool
    is_directory: bool
    file_size: int
    permissions: int  # File permissions (77 55, 66 44, or 00 00 for non-existing)
    metadata_blocks: list[bytes]  # Three 13-byte metadata blocks

    @classmethod
    def parse(cls, response_data: bytes) -> DatabaseInfoResponse:
        """Parse DATABASE_INFO response from raw bytes."""
        if len(response_data) < 49:
            raise ValueError(
                f"DATABASE_INFO response too short: {len(response_data)} bytes"
            )

        # Skip length prefix if present
        offset = 4 if len(response_data) > 49 else 0
        data = response_data[offset:]

        if len(data) < 49:
            raise ValueError(f"DATABASE_INFO content too short: {len(data)} bytes")

        # Parse file size from last 8 bytes
        file_size = int.from_bytes(data[-8:], byteorder="big", signed=False)

        # Parse existence and directory flags (first 6 bytes)
        file_exists = bool(data[0])  # First byte: boolean "Exists"
        is_directory = bool(data[1])  # Second byte: boolean "IsDirectory"
        permissions = int.from_bytes(data[4:6], byteorder="big", signed=False)

        # Parse metadata blocks (bytes 6-40, up to 35 bytes)
        metadata_blocks = []
        metadata_start = 6
        metadata_end = 41  # File size starts at byte 41

        # Parse complete 13-byte blocks first
        pos = metadata_start
        while pos + 13 <= metadata_end:
            metadata_blocks.append(data[pos : pos + 13])
            pos += 13

        # Handle any remaining partial block
        if pos < metadata_end:
            if remaining_bytes := data[pos:metadata_end]:
                # Pad partial block to 13 bytes
                padded_block = remaining_bytes.ljust(13, b"\x00")
                metadata_blocks.append(padded_block)

        return cls(
            file_exists=file_exists,
            is_directory=is_directory,
            file_size=file_size,
            permissions=permissions,
            metadata_blocks=metadata_blocks,
        )

    def to_bytes(self) -> bytes:
        """Serialize back to raw DATABASE_INFO response format."""
        result = bytearray()

        # Existence and directory flags (4 bytes)
        result.append(0x01 if self.file_exists else 0x00)
        result.append(0x01 if self.is_directory else 0x00)
        result.extend(b"\x00\x00")  # Padding bytes 3-4

        # Permissions (2 bytes)
        result.extend(self.permissions.to_bytes(2, byteorder="big"))

        # Metadata area (35 bytes, bytes 6-40)
        metadata_bytes = bytearray(35)  # Initialize with zeros
        pos = 0

        for block in self.metadata_blocks:
            if pos >= 35:
                break

            # How many bytes can we write from this block?
            bytes_to_write = min(len(block), 35 - pos)
            metadata_bytes[pos : pos + bytes_to_write] = block[:bytes_to_write]
            pos += 13  # Move to next block position (even if partial)

        result.extend(metadata_bytes)

        # File size (8 bytes)
        result.extend(self.file_size.to_bytes(8, byteorder="big"))

        return bytes(result)


class FileTransferConnection:
    """Pythonic FileTransfer connection for accessing device files."""

    def __init__(self, host: str, port: int, token: Token) -> None:
        self.host = host
        self.port = port
        self.token = token
        self._connection: StagelinQConnection | None = None
        self._sources: list[FileSource] = []
        self._next_request_id = 1
        self._directory_cache: dict[str, list[FileInfo]] = {}  # path -> files
        self._request_id_to_path: dict[int, str] = {}  # request_id -> path

    def _get_next_request_id(self) -> int:
        """Get next request ID for async correlation."""
        request_id = self._next_request_id
        self._next_request_id += 1
        return request_id

    async def __aenter__(self) -> FileTransferConnection:
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
        """Connect to FileTransfer service."""
        if self._connection is not None:
            return

        try:
            self._connection = StagelinQConnection(self.host, self.port)
            await self._connection.connect()
            logger.info("Connected to FileTransfer at %s:%s", self.host, self.port)
        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to FileTransfer service: {e}"
            ) from e

    async def disconnect(self) -> None:
        """Disconnect from FileTransfer service."""
        if self._connection:
            await self._connection.disconnect()
            self._connection = None
        logger.info("Disconnected from FileTransfer at %s:%s", self.host, self.port)

    async def get_sources(self) -> list[FileSource]:
        """Get available file sources from the device."""
        if not self._connection:
            raise RuntimeError("Not connected")

        # Send request for root directory listing with unique request ID
        request_id = self._get_next_request_id()
        request = FileTransferRequestMessage(
            FILE_TRANSFER_REQUEST_DIRECTORY_LIST, request_id
        )

        writer = io.BytesIO()
        request.write_to(writer)
        request_data = writer.getvalue()

        await self._connection.send_message(request_data)

        # Receive response
        response_data = await self._connection.receive_message()
        if not response_data:
            return []

        # Parse response
        response = FileTransferResponseMessage()
        reader = io.BytesIO(response_data)
        response.read_from(reader)

        self._sources = response.sources

        # Send session cleanup after getting sources (matches observed behavior)
        await self.cleanup_session()

        return self._sources

    async def download_database(
        self, source_name: str, local_path: str | Path | None = None
    ) -> bytes:
        """Download the Engine Library database from a specific source.

        Args:
            source_name: Name of the source (e.g., "Music (SD)")
            local_path: Optional local path to save the database

        Returns:
            Database file content as bytes
        """
        if not self._connection:
            raise RuntimeError("Not connected")

        # Get sources if not already loaded
        if not self._sources:
            await self.get_sources()

        source = next((s for s in self._sources if s.name == source_name), None)
        if not source:
            raise FileNotFoundError(f"Source not found: {source_name}")

        # Download the database file using chunked transfer
        logger.info(f"Downloading database from {source_name}: {source.database_path}")

        def progress_callback(chunk_data, chunk_index, total_chunks):
            percent = ((chunk_index + 1) / total_chunks) * 100
            logger.info(
                f"Download progress: {percent:.1f}% ({chunk_index + 1}/{total_chunks} chunks)"
            )

        file_data = await self.get_file(source.database_path, progress_callback)

        # Save to local file if path provided
        if local_path:
            path = Path(local_path)
            path.write_bytes(file_data)
            logger.info(f"Database saved to: {path}")

        return file_data

    async def get_database_info(self, source_name: str) -> dict[str, str]:
        """Get database information for a specific source.

        Args:
            source_name: Name of the source (e.g., "Music (SD)")

        Returns:
            Dictionary with database information
        """
        if not self._connection:
            raise RuntimeError("Not connected")

        # Get sources if not already loaded
        if not self._sources:
            await self.get_sources()

        # Find the requested source
        for source in self._sources:
            if source.name == source_name:
                return {
                    "source_name": source.name,
                    "database_path": source.database_path,
                }

        raise FileNotFoundError(f"Source not found: {source_name}")

    async def list_sources(self) -> list[str]:
        """List all available sources on the device.

        Returns:
            List of source names
        """
        sources = await self.get_sources()
        return [source.name for source in sources]

    async def list_directory(self, path: str = "") -> list[FileInfo]:
        """List directory contents using 0x7D2 with path parameter.

        Args:
            path: Directory path to list (empty string for root/sources)
                 Example: "/Source (USB 1)/Engine Library"

        Returns:
            List of FileInfo objects for files and subdirectories
        """
        if not self._connection:
            raise RuntimeError("Not connected")

        # Check cache first
        if path in self._directory_cache:
            logger.debug("Returning cached directory listing for: %s", path)
            return self._directory_cache[path]

        # Send directory listing request with path
        request_id = self._get_next_request_id()
        self._request_id_to_path[request_id] = path  # Track request for invalidation
        request = FileTransferRequestMessage(
            FILE_TRANSFER_REQUEST_DIRECTORY_LIST, request_id
        )

        writer = io.BytesIO()
        request.write_to(writer)

        # Add path parameter as size-prefixed UTF-16BE string
        if path:
            path_data = path.encode("utf-16be")
            serializer.write_uint32(writer, len(path_data))
            writer.write(path_data)
        else:
            # Empty path for root directory listing
            serializer.write_uint32(writer, 0)

        request_data = writer.getvalue()
        await self._connection.send_message(request_data)

        # Handle potentially multi-chunk responses
        all_sources = []
        is_complete = False

        while not is_complete:
            # Receive response chunk
            response_data = await self._connection.receive_message()
            if not response_data:
                break

            # Parse response chunk
            response = FileTransferResponseMessage()
            reader = io.BytesIO(response_data)
            response.read_from(reader)

            # Add sources from this chunk
            all_sources.extend(response.sources)

            # Check if this is the last chunk
            is_complete = response.is_last_chunk

            logger.debug(
                "Received directory listing chunk: first=%s, last=%s, is_directories=%s, items=%d",
                response.is_first_chunk,
                response.is_last_chunk,
                response.is_directories,
                len(response.sources),
            )

        # Convert sources to FileInfo objects
        file_list = []
        for source in all_sources:
            file_info = FileInfo(
                path=source.database_path,
                name=source.name,
                size=source.database_size,
                is_directory=response.is_directories,  # Use flag from response
            )
            file_list.append(file_info)

        # Cache the results
        self._directory_cache[path] = file_list

        # Send session cleanup after directory listing
        await self.cleanup_session()

        return file_list

    def invalidate_directory_cache(self, transaction_id: int) -> None:
        """Invalidate cached directory based on transaction ID from 0x9 message.

        Args:
            transaction_id: The request ID from the original directory listing
        """
        if transaction_id in self._request_id_to_path:
            path = self._request_id_to_path[transaction_id]
            if path in self._directory_cache:
                del self._directory_cache[path]
                logger.info(
                    "Invalidated directory cache for: %s (transaction %d)",
                    path,
                    transaction_id,
                )
            del self._request_id_to_path[transaction_id]
        else:
            logger.debug(
                "Received invalidation for unknown transaction ID: %d", transaction_id
            )

    def clear_directory_cache(self) -> None:
        """Clear all cached directory listings."""
        self._directory_cache.clear()
        self._request_id_to_path.clear()
        logger.debug("Cleared all directory cache")

    async def get_file_size(self, database_path: str) -> int:
        """Get file size using DATABASE_INFO request (0x7D4).

        Args:
            database_path: Path to the database file

        Returns:
            File size in bytes
        """
        if not self._connection:
            raise RuntimeError("Not connected")

        # Use DATABASE_INFO request (0x7D4) - last 8 bytes contain size
        request_id = self._get_next_request_id()
        request = FileTransferRequestMessage(
            FILE_TRANSFER_REQUEST_DATABASE_INFO, request_id
        )

        writer = io.BytesIO()
        request.write_to(writer)
        # Add database path as UTF-16BE string
        if database_path:
            path_data = database_path.encode("utf-16be")
            writer.write(path_data)

        request_data = writer.getvalue()
        await self._connection.send_message(request_data)

        # Receive response
        response_data = await self._connection.receive_message()
        if not response_data or len(response_data) < 8:
            raise ValueError("Invalid file stat response")

        file_size_bytes = response_data[-8:]  # Last 8 bytes contain file size
        return int.from_bytes(file_size_bytes, byteorder="big", signed=False)

    async def get_file(self, database_path: str, chunk_callback=None) -> bytes:
        """Download a complete file using chunked transfers.

        Args:
            database_path: Path to the database file
            chunk_callback: Optional callback function called for each chunk: callback(chunk_data, chunk_index, total_chunks)

        Returns:
            Complete file content as bytes
        """
        if not self._connection:
            raise RuntimeError("Not connected")

        # Get file size first
        file_size = await self.get_file_size(database_path)
        logger.info(f"File size: {file_size} bytes")

        # Calculate number of chunks needed
        total_chunks = math.ceil(file_size / CHUNK_SIZE)
        logger.info(f"Will download {total_chunks} chunks of {CHUNK_SIZE} bytes each")

        # Download all chunks
        file_data = bytearray()

        for chunk_index in range(total_chunks):
            chunk_offset = chunk_index * CHUNK_SIZE

            # Send chunk request (0x7D5)
            request_id = self._get_next_request_id()
            request = FileTransferRequestMessage(
                FILE_TRANSFER_REQUEST_DATABASE_READ, request_id
            )

            writer = io.BytesIO()
            request.write_to(writer)

            # Add chunk request parameters
            # Format: [database_path:utf16][chunk_offset:4][chunk_size:4]
            if database_path:
                path_data = database_path.encode("utf-16be")
                writer.write(path_data)
                writer.write(b"\x00\x00")  # Null terminator for string

            # Write chunk offset and size
            serializer.write_uint32(writer, chunk_offset)
            serializer.write_uint32(writer, CHUNK_SIZE)

            request_data = writer.getvalue()
            await self._connection.send_message(request_data)

            # Receive chunk response
            chunk_response = await self._connection.receive_message()
            if not chunk_response:
                raise ValueError(f"Failed to receive chunk {chunk_index}")

            # Extract actual file data from response (skip any headers)
            # The response should contain the raw chunk data
            chunk_data = chunk_response

            # Handle partial last chunk
            bytes_remaining = file_size - len(file_data)
            if len(chunk_data) > bytes_remaining:
                chunk_data = chunk_data[:bytes_remaining]

            file_data.extend(chunk_data)

            # Call progress callback if provided
            if chunk_callback:
                chunk_callback(chunk_data, chunk_index, total_chunks)

            logger.debug(
                f"Downloaded chunk {chunk_index + 1}/{total_chunks} ({len(chunk_data)} bytes)"
            )

        # Send completion request (0x7D6)
        request_id = self._get_next_request_id()
        request = FileTransferRequestMessage(FILE_TRANSFER_REQUEST_COMPLETE, request_id)

        writer = io.BytesIO()
        request.write_to(writer)
        completion_data = writer.getvalue()
        await self._connection.send_message(completion_data)

        logger.info(f"File download complete: {len(file_data)} bytes")
        return bytes(file_data)

    async def cleanup_session(self, session_request_id: int | None = None) -> None:
        """Send session cleanup command (0x7D3) to signal end of inquiry.

        This command doesn't expect a response and signals that the client
        is done with a particular line of inquiry/transfer session.

        Args:
            session_request_id: Optional specific request ID to cleanup,
                               otherwise uses next available ID
        """
        if not self._connection:
            raise RuntimeError("Not connected")

        # Use provided request ID or get next one
        request_id = (
            session_request_id
            if session_request_id is not None
            else self._get_next_request_id()
        )
        request = FileTransferRequestMessage(FILE_TRANSFER_SESSION_CLEANUP, request_id)

        writer = io.BytesIO()
        request.write_to(writer)
        cleanup_data = writer.getvalue()

        # Send cleanup command (no response expected)
        await self._connection.send_message(cleanup_data)
        logger.debug(f"Sent session cleanup for request ID {request_id}")
