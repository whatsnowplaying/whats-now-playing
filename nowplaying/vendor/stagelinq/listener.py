"""StagelinQ Listener implementation.

Based on @honusz's Listener approach that allows devices to connect TO software
instead of software discovering and connecting to devices.

This greatly simplifies connection management and enables support for devices
like X1800/X1850 mixers that were previously difficult to work with.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .messages import (
    ReferenceMessage,
    ServiceAnnouncementMessage,
    ServicesRequestMessage,
    Token,
)
from .protocol import StagelinQConnection

logger = logging.getLogger(__name__)


@dataclass
class ServiceInfo:
    """Information about a service offered by the listener."""

    name: str
    port: int
    handler_class: type


class StagelinQService(ABC):
    """Base class for StagelinQ services that can accept device connections."""

    def __init__(self, port: int, token: Token):
        self.port = port
        self.token = token
        self.connections: dict[str, StagelinQConnection] = {}
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """Start the service listener."""
        self._server = await asyncio.start_server(
            self._handle_connection, "0.0.0.0", self.port
        )
        logger.info("Started %s service on port %d", self.__class__.__name__, self.port)

    async def stop(self) -> None:
        """Stop the service listener."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        # Close all connections
        for conn in self.connections.values():
            await conn.disconnect()
        self.connections.clear()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle incoming device connection."""
        try:
            # Get peer address for identification
            peer_addr = writer.get_extra_info("peername")
            device_id = f"{peer_addr[0]}:{peer_addr[1]}"

            logger.info(
                "Device connected to %s: %s", self.__class__.__name__, device_id
            )

            # Create StagelinQ connection wrapper
            connection = StagelinQConnection.from_streams(reader, writer)
            self.connections[device_id] = connection

            # Handle the specific service protocol
            await self.handle_device_connection(device_id, connection)

        except Exception as e:
            logger.error(
                "Error handling connection to %s: %s", self.__class__.__name__, e
            )
        finally:
            if device_id in self.connections:
                del self.connections[device_id]
            writer.close()
            await writer.wait_closed()

    @abstractmethod
    async def handle_device_connection(
        self, device_id: str, connection: StagelinQConnection
    ) -> None:
        """Handle device-specific protocol for this service."""


class DirectoryService(StagelinQService):
    """Directory service that handles initial device connections and service announcements."""

    def __init__(self, port: int, token: Token, offered_services: list[ServiceInfo]):
        super().__init__(port, token)
        self.offered_services = offered_services

    async def handle_device_connection(
        self, device_id: str, connection: StagelinQConnection
    ) -> None:
        """Handle directory service protocol."""
        try:
            # Wait for services request (0x2)
            async for message_data in connection.messages():
                try:
                    request = ServicesRequestMessage.deserialize(message_data)
                    logger.debug("Received services request from %s", device_id)

                    # Send service announcements for all offered services
                    for service_info in self.offered_services:
                        announcement = ServiceAnnouncementMessage(
                            token=self.token,
                            service=service_info.name,
                            port=service_info.port,
                        )
                        await connection.send_message(announcement.serialize())
                        logger.debug(
                            "Announced %s service on port %d to %s",
                            service_info.name,
                            service_info.port,
                            device_id,
                        )

                    # Send reference message to complete handshake
                    reference = ReferenceMessage(
                        token=self.token, token2=request.token, reference=0
                    )
                    await connection.send_message(reference.serialize())

                except Exception as e:
                    logger.debug("Error processing message from %s: %s", device_id, e)
                    continue

        except Exception as e:
            logger.error("Directory service error with %s: %s", device_id, e)


class FileTransferService(StagelinQService):
    """File transfer service that can serve files to devices."""

    def __init__(self, port: int, token: Token, file_handler=None):
        super().__init__(port, token)
        self.file_handler = file_handler  # Custom file serving logic

    async def handle_device_connection(
        self, device_id: str, connection: StagelinQConnection
    ) -> None:
        """Handle file transfer service protocol."""
        try:
            # Wait for service announcement from device
            async for _ in connection.messages():
                try:
                    # Handle file transfer requests here
                    # This would integrate with our existing FileTransferRequestMessage handling
                    logger.debug("Received file transfer message from %s", device_id)

                    # TODO: Implement file transfer request handling
                    # This would use our existing file transfer protocol classes

                except Exception as e:
                    logger.debug(
                        "Error processing file transfer message from %s: %s",
                        device_id,
                        e,
                    )
                    continue

        except Exception as e:
            logger.error("File transfer service error with %s: %s", device_id, e)


class StateMapService(StagelinQService):
    """StateMap service for monitoring device states."""

    async def handle_device_connection(
        self, device_id: str, connection: StagelinQConnection
    ) -> None:
        """Handle StateMap service protocol."""
        try:
            async for _ in connection.messages():
                try:
                    # Handle state map messages
                    logger.debug("Received state map message from %s", device_id)
                    # TODO: Implement state map message handling

                except Exception as e:
                    logger.debug(
                        "Error processing state map message from %s: %s", device_id, e
                    )
                    continue

        except Exception as e:
            logger.error("StateMap service error with %s: %s", device_id, e)


class BeatInfoService(StagelinQService):
    """BeatInfo service for receiving beat timing information."""

    async def handle_device_connection(
        self, device_id: str, connection: StagelinQConnection
    ) -> None:
        """Handle BeatInfo service protocol."""
        try:
            async for _ in connection.messages():
                try:
                    # Handle beat info messages
                    logger.debug("Received beat info message from %s", device_id)
                    # TODO: Implement beat info message handling

                except Exception as e:
                    logger.debug(
                        "Error processing beat info message from %s: %s", device_id, e
                    )
                    continue

        except Exception as e:
            logger.error("BeatInfo service error with %s: %s", device_id, e)


class StagelinQListener:
    """Main listener that manages all StagelinQ services and device connections."""

    def __init__(self, discovery_port: int = 51337):
        # Use special token format that devices accept (starts with 0xFF...)
        self.token = Token(
            b"\xff\xff\xff\xff\xff\xff\x00\x00\x80\x00\x00\x05\x95\x04\x14\x1c"
        )
        self.discovery_port = discovery_port
        self.services: dict[str, StagelinQService] = {}
        self.offered_services: list[ServiceInfo] = []
        self._discovery_task: asyncio.Task | None = None

    def add_service(self, service_name: str, port: int, service_class: type) -> None:
        """Add a service that devices can connect to."""
        service_info = ServiceInfo(
            name=service_name, port=port, handler_class=service_class
        )
        self.offered_services.append(service_info)

        # Create service instance
        service = service_class(port, self.token)
        self.services[service_name] = service

        logger.info("Added %s service on port %d", service_name, port)

    async def start(self) -> None:
        """Start the listener with all configured services."""
        # Start directory service (required)
        directory_service = DirectoryService(
            self.discovery_port, self.token, self.offered_services
        )
        self.services["Directory"] = directory_service
        await directory_service.start()

        # Start all other services
        for service in self.services.values():
            if service != directory_service:
                await service.start()

        # Start discovery announcements
        self._discovery_task = asyncio.create_task(self._announce_discovery())

        logger.info(
            "StagelinQ Listener started on port %d with %d services",
            self.discovery_port,
            len(self.services),
        )

    async def stop(self) -> None:
        """Stop the listener and all services."""
        if self._discovery_task:
            self._discovery_task.cancel()
            try:
                await self._discovery_task
            except asyncio.CancelledError:
                pass

        # Stop all services
        for service in self.services.values():
            await service.stop()

        self.services.clear()
        logger.info("StagelinQ Listener stopped")

    async def _announce_discovery(self) -> None:
        """Continuously announce discovery to attract device connections."""
        from .discovery import DiscoveryAnnouncer

        announcer = DiscoveryAnnouncer(
            name="Python StagelinQ Listener",
            software_name="python-stagelinq",
            software_version="0.2.0",
            port=self.discovery_port,
            token=self.token,
        )

        try:
            await announcer.start_announcing()
            # Keep announcing until cancelled
            while True:
                await asyncio.sleep(3600)  # Sleep but keep task alive
        except asyncio.CancelledError:
            pass
        finally:
            await announcer.stop_announcing()


# Convenience functions for common setups


async def create_file_server(port: int = 51338) -> StagelinQListener:
    """Create a listener that serves as a file transfer service."""
    listener = StagelinQListener()
    listener.add_service("FileTransfer", port, FileTransferService)
    return listener


async def create_analytics_server(
    state_port: int = 51338, beat_port: int = 51339
) -> StagelinQListener:
    """Create a listener for DJ analytics (StateMap + BeatInfo)."""
    listener = StagelinQListener()
    listener.add_service("StateMap", state_port, StateMapService)
    listener.add_service("BeatInfo", beat_port, BeatInfoService)
    return listener


async def create_full_server() -> StagelinQListener:
    """Create a listener with all services."""
    listener = StagelinQListener()
    listener.add_service("FileTransfer", 51338, FileTransferService)
    listener.add_service("StateMap", 51339, StateMapService)
    listener.add_service("BeatInfo", 51340, BeatInfoService)
    return listener
