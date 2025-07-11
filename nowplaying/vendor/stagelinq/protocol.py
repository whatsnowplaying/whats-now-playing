"""StageLinq protocol handlers for async communication."""

from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import AsyncIterator, Callable

from .messages import serializer

logger = logging.getLogger(__name__)


class StageLinqProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler for StageLinq discovery."""

    def __init__(
        self, message_handler: Callable[[bytes, tuple[str, int]], None]
    ) -> None:
        self.message_handler = message_handler
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        """Called when connection is established."""
        self.transport = transport
        logger.debug("StageLinq UDP connection established")

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Called when a datagram is received."""
        try:
            self.message_handler(data, addr)
        except Exception as e:
            logger.error("Error handling datagram from %s: %s", addr, e)

    def error_received(self, exc: Exception) -> None:
        """Called when an error is received."""
        # Common network errors when mixing IPv4/IPv6 - log as debug
        if "address family mismatched" in str(
            exc
        ) or "Can't assign requested address" in str(exc):
            logger.debug("StageLinq protocol error (expected): %s", exc)
        else:
            logger.error("StageLinq protocol error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when connection is lost."""
        if exc:
            logger.error("StageLinq connection lost: %s", exc)
        else:
            logger.debug("StageLinq connection closed")


class MessageStream:
    """Message stream that handles length-prefixed messages."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self._closed = False

    async def read_message(self) -> bytes | None:
        """Read a length-prefixed message from the stream."""
        if self._closed:
            return None

        try:
            # Read message length (4 bytes, network byte order)
            length_data = await self.reader.readexactly(4)
            message_length = serializer.read_uint32(io.BytesIO(length_data))

            # Validate message length
            if message_length > 10 * 1024 * 1024:  # 10MB limit
                logger.warning(
                    "Message length too large: %d bytes, dropping message",
                    message_length,
                )
                return None

            # Read the message data
            return await self.reader.readexactly(message_length)

        except asyncio.IncompleteReadError as e:
            # Check if this is a partial read (we got length but not full message)
            if e.partial and len(e.partial) > 0:
                logger.warning(
                    "Partial message read detected: got %d bytes, expected %d bytes. Data may be lost.",
                    len(e.partial),
                    e.expected,
                )
                # This is data loss - we should consider raising an exception
                raise ConnectionError(
                    "Stream closed during message read, data lost"
                ) from e
            else:
                # Normal connection close (no data read yet)
                logger.debug("Message stream connection closed")
                return None
        except Exception as e:
            logger.error("Error reading message: %s", e)
            return None

    async def write_message(self, data: bytes) -> None:
        """Write a length-prefixed message to the stream."""
        if self._closed:
            raise RuntimeError("Stream is closed")

        try:
            # Write length prefix
            length_buffer = io.BytesIO()
            serializer.write_uint32(length_buffer, len(data))

            # Write length and data
            self.writer.write(length_buffer.getvalue())
            self.writer.write(data)
            await self.writer.drain()

        except Exception as e:
            logger.error("Error writing message: %s", e)
            raise

    async def messages(self) -> AsyncIterator[bytes]:
        """Async iterator over messages from the stream."""
        while not self._closed:
            message = await self.read_message()
            if message is None:
                break
            yield message

    async def close(self) -> None:
        """Close the message stream."""
        if not self._closed:
            self._closed = True
            self.writer.close()
            await self.writer.wait_closed()

    async def __aenter__(self) -> MessageStream:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit."""
        await self.close()


class StageLinqStreamProtocol(asyncio.Protocol):
    """TCP protocol handler for StageLinq services."""

    def __init__(self) -> None:
        self.transport: asyncio.Transport | None = None
        self._stream_buffer = io.BytesIO()
        self._message_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._connection_lost = asyncio.Event()

    def connection_made(self, transport: asyncio.Transport) -> None:
        """Called when connection is established."""
        self.transport = transport
        logger.debug("StageLinq TCP connection established")

    def data_received(self, data: bytes) -> None:
        """Called when data is received."""
        # Write new data to buffer
        self._stream_buffer.write(data)
        self._process_messages()

    def _process_messages(self) -> None:
        """Process buffered data for complete messages."""
        # Get current buffer contents
        buffer_data = self._stream_buffer.getvalue()
        buffer_reader = io.BytesIO(buffer_data)

        messages_processed = 0

        while True:
            # Save current position
            start_pos = buffer_reader.tell()

            try:
                # Try to read message length
                length = serializer.read_uint32(buffer_reader)

                # Check if we have enough data for the complete message
                if len(buffer_data) < start_pos + 4 + length:
                    # Not enough data, reset position and break
                    buffer_reader.seek(start_pos)
                    break

                # Read the complete message
                message_data = buffer_reader.read(length)
                if len(message_data) != length:
                    # Shouldn't happen, but handle gracefully
                    buffer_reader.seek(start_pos)
                    break

                # Queue the message
                try:
                    self._message_queue.put_nowait(message_data)
                    messages_processed += 1
                except asyncio.QueueFull:
                    logger.warning("Message queue full, dropping message")
                    break

            except (EOFError, ValueError):
                # Not enough data for complete message
                buffer_reader.seek(start_pos)
                break

        # Update buffer with remaining data
        remaining_data = buffer_reader.read()
        self._stream_buffer = io.BytesIO(remaining_data)

        if messages_processed > 0:
            logger.debug("Processed %s messages", messages_processed)

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when connection is lost."""
        if exc:
            logger.error("StageLinq stream connection lost: %s", exc)
        else:
            logger.debug("StageLinq stream connection closed")

        self._connection_lost.set()

    async def read_message(self) -> bytes | None:
        """Read the next message from the stream."""
        try:
            # Wait for either a message or connection loss
            message_task = asyncio.create_task(self._message_queue.get())
            connection_task = asyncio.create_task(self._connection_lost.wait())

            done, pending = await asyncio.wait(
                [message_task, connection_task], return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel pending tasks
            for task in pending:
                task.cancel()

            return message_task.result() if message_task in done else None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error reading message: %s", e)
            return None

    async def write_message(self, data: bytes) -> None:
        """Write a message to the stream."""
        if not self.transport:
            raise RuntimeError("No transport available")

        # Use serializer for consistent length prefix
        length_buffer = io.BytesIO()
        serializer.write_uint32(length_buffer, len(data))

        self.transport.write(length_buffer.getvalue() + data)

    def close(self) -> None:
        """Close the connection."""
        if self.transport:
            self.transport.close()


async def connect_message_stream(host: str, port: int) -> MessageStream:
    """Create a message stream connection to a host and port."""
    reader, writer = await asyncio.open_connection(host, port)
    return MessageStream(reader, writer)


class StageLinqConnection:
    """High-level StageLinq connection."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._stream: MessageStream | None = None

    async def connect(self) -> None:
        """Connect to the StageLinq service."""
        if self._stream:
            return

        try:
            self._stream = await connect_message_stream(self.host, self.port)
            logger.info("Connected to StageLinq service at %s:%s", self.host, self.port)
        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to {self.host}:{self.port}: {e}"
            ) from e

    async def disconnect(self) -> None:
        """Disconnect from the StageLinq service."""
        if self._stream:
            await self._stream.close()
            self._stream = None
            logger.info(
                "Disconnected from StageLinq service at %s:%s", self.host, self.port
            )

    async def send_message(self, message_data: bytes) -> None:
        """Send a message to the service."""
        if not self._stream:
            raise RuntimeError("Not connected")

        await self._stream.write_message(message_data)

    async def receive_message(self) -> bytes | None:
        """Receive a message from the service."""
        if not self._stream:
            raise RuntimeError("Not connected")

        return await self._stream.read_message()

    async def messages(self) -> AsyncIterator[bytes]:
        """Async iterator over messages from the service."""
        if not self._stream:
            raise RuntimeError("Not connected")

        async for message in self._stream.messages():
            yield message

    @property
    def local_port(self) -> int:
        """Get the local port of the connection."""
        if not self._stream:
            raise RuntimeError("Not connected")

        # Get the local port from the writer's transport
        transport = self._stream.writer.transport
        if transport and hasattr(transport, "get_extra_info"):
            if sockname := transport.get_extra_info("sockname"):
                return sockname[1]  # (host, port) tuple

        return 0  # Fallback if unable to get port

    async def __aenter__(self) -> StageLinqConnection:
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

    @classmethod
    def from_streams(
        cls, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> StageLinqConnection:
        """Create a StageLinqConnection from existing streams (for server-side connections)."""
        # Create an instance without connecting
        peer_addr = writer.get_extra_info("peername")
        host = peer_addr[0] if peer_addr else "unknown"
        port = peer_addr[1] if peer_addr else 0

        connection = cls(host, port)
        # Directly set the stream instead of connecting
        connection._stream = MessageStream(reader, writer)
        return connection
