#!/usr/bin/env python3
"""
StagelinQ Connection Manager

This module handles device discovery, connection lifecycle, and network management
for StagelinQ devices. It manages the async networking layer and connection state.
"""

import asyncio
import contextlib
import logging
import socket
from typing import Callable

import nowplaying.version

from .protocol import StagelinqProtocol
from .types import (
    DISCOVERY_PORT,
    MSG_REFERENCE,
    MSG_SERVICE_ANNOUNCEMENT,
    DenonDevice,
    DenonService,
    DenonState,
)


class ConnectionManager:
    """Manages StagelinQ device connections and network communication"""

    def __init__(self, token: bytes):
        self.token = token
        self.device: DenonDevice | None = None
        self.state_service: DenonService | None = None
        self.connections: list[asyncio.StreamWriter] = []
        self.tasks: list[asyncio.Task] = []

    async def discover_devices(self, timeout: float) -> list[DenonDevice]:
        """Discover StagelinQ devices on the network"""
        devices = []
        found_tokens = set()

        # Create UDP socket for discovery
        loop = asyncio.get_event_loop()

        class DiscoveryProtocol(asyncio.DatagramProtocol):
            """Protocol class for UDP discovery"""

            def __init__(self, manager: ConnectionManager):
                self.manager = manager

            def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
                try:
                    device: DenonDevice | None = StagelinqProtocol.parse_discovery_message(
                        data, addr[0]
                    )
                    if (
                        device
                        and device.token not in found_tokens
                        and device.token != self.manager.token
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

    async def connect_to_device(self, device: DenonDevice) -> list[DenonService]:
        """Connect to device and get available services"""
        reader, writer = await asyncio.open_connection(device.ipaddr, device.port)

        try:
            self.connections.append(writer)

            # Start reference message task
            ref_task = asyncio.create_task(self._send_reference_messages(writer, device.token))
            self.tasks.append(ref_task)

            # Send services request
            services_msg = StagelinqProtocol.create_services_request(self.token)
            writer.write(services_msg)
            await writer.drain()

            # Read services
            services = []
            while True:
                try:
                    # Read message ID
                    msg_id_data = await reader.readexactly(4)
                    msg_id = int.from_bytes(msg_id_data, "big")

                    if msg_id == MSG_SERVICE_ANNOUNCEMENT:
                        # Read the full message first
                        token_data = await reader.readexactly(16)  # Token

                        # Read service name length and data
                        str_len_data = await reader.readexactly(4)
                        str_len = int.from_bytes(str_len_data, "big")
                        str_data = await reader.readexactly(str_len)

                        # Read port
                        port_data = await reader.readexactly(2)

                        # Reconstruct the service announcement data for parsing
                        service_data = token_data + str_len_data + str_data + port_data

                        # Use the protocol parser
                        service, _ = StagelinqProtocol.parse_service_announcement(service_data)
                        if service:
                            services.append(service)

                    elif msg_id == MSG_REFERENCE:
                        # End of service list
                        await reader.readexactly(40)  # Skip reference message data
                        break

                except asyncio.IncompleteReadError:
                    break

            return services

        except Exception:
            # Ensure writer is closed on any failure
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()
            # Remove from connections list if it was added
            if writer in self.connections:
                self.connections.remove(writer)
            raise

    async def monitor_state_changes(  # pylint: disable=too-many-locals
        self,
        device: DenonDevice,
        service: DenonService,
        state_callback: Callable[[DenonState], None],
    ) -> None:
        """Monitor track state changes from StateMap service"""
        try:
            reader, writer = await asyncio.open_connection(device.ipaddr, service.port)
            self.connections.append(writer)

            # Send service announcement
            local_port = writer.get_extra_info("sockname")[1]
            service_msg = StagelinqProtocol.create_service_announcement(
                self.token, "StateMap", local_port
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
                sub_msg = StagelinqProtocol.create_state_subscription(state_path)
                writer.write(sub_msg)
                await writer.drain()

            # Read state updates
            while True:
                try:
                    # Read length-prefixed message
                    length_data = await reader.readexactly(4)
                    length = int.from_bytes(length_data, "big")
                    payload = await reader.readexactly(length)

                    if state := StagelinqProtocol.parse_state_emit_message(payload):
                        state_callback(state)
                        logging.debug("State update: %s = %s", state.name, state.value)

                except asyncio.IncompleteReadError:
                    break

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Track monitoring error: %s", err)
            raise

    async def send_announcements(self) -> None:
        """Continuously announce ourselves to devices"""
        try:
            while True:
                await self._announce_self()
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Announcement error: %s", err)

    async def _announce_self(self) -> None:
        """Send UDP announcement to let devices know about us"""
        try:
            device_name = "WhatsNowPlaying"
            message = StagelinqProtocol.create_discovery_message(
                self.token, device_name, nowplaying.version.__VERSION__
            )

            # Send to broadcast address
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(message, ("255.255.255.255", DISCOVERY_PORT))
            sock.close()

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Self-announcement error: %s", err)

    async def _send_reference_messages(
        self, writer: asyncio.StreamWriter, target_token: bytes
    ) -> None:
        """Send periodic reference messages to keep connection alive"""
        try:
            while True:
                await asyncio.sleep(0.25)  # 250ms interval

                message = StagelinqProtocol.create_reference_message(self.token, target_token)
                writer.write(message)
                await writer.drain()

        except asyncio.CancelledError:
            pass
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Reference message error: %s", err)

    async def cleanup(self) -> None:
        """Stop all tasks and close all connections"""
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
        self.device = None
        self.state_service = None
