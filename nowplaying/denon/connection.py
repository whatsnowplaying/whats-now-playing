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
from collections.abc import Callable
from dataclasses import dataclass

import netifaces

import nowplaying.version  # pylint: disable=no-member,import-error,no-name-in-module

from .protocol import StagelinqProtocol
from .types import (
    DISCOVERY_PORT,
    MSG_REFERENCE,
    MSG_SERVICE_ANNOUNCEMENT,
    MSG_SERVICES_REQUEST,
    DenonDevice,
    DenonService,
    DenonState,
)


@dataclass
class DeviceConnection:
    """Live connections and tasks for one StagelinQ device"""

    device: DenonDevice
    main_writer: asyncio.StreamWriter
    ref_task: asyncio.Task
    state_writer: asyncio.StreamWriter | None = None
    monitor_task: asyncio.Task | None = None


class ConnectionManager:
    """Manages StagelinQ device connections and network communication"""

    def __init__(self, token: bytes):
        self.token = token
        # live device connections keyed by discovery token
        self.active: dict[bytes, DeviceConnection] = {}
        # global tasks: self-announcement and the discovery loop
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
                        found_tokens.add(device.token)
                        if device.is_connectable():
                            devices.append(device)
                        else:
                            logging.debug(
                                "Skipping non-connectable StagelinQ device: %s (%s) at %s",
                                device.name,
                                device.software_name,
                                addr[0],
                            )
                except Exception as err:  # pylint: disable=broad-exception-caught
                    logging.debug("Failed to parse discovery message from %s: %s", addr, err)

        # Try to bind to discovery port
        try:
            transport, _protocol = await loop.create_datagram_endpoint(
                lambda: DiscoveryProtocol(self),
                local_addr=("0.0.0.0", DISCOVERY_PORT),
                reuse_port=True,
            )
        except (OSError, ValueError):
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

    async def connect_to_device(  # pylint: disable=too-many-locals
        self, device: DenonDevice
    ) -> list[DenonService]:
        """Connect to device and get available services"""
        reader, writer = await asyncio.open_connection(device.ipaddr, device.port)

        # Start reference message task to keep the connection alive
        ref_task = asyncio.create_task(self._send_reference_messages(writer, device.token))

        try:
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

                    elif msg_id == MSG_SERVICES_REQUEST:
                        # Devices are peers: they ask what services we offer.
                        # Consume the device's token and keep reading; we
                        # offer no services of our own.
                        await reader.readexactly(16)

                    elif msg_id == MSG_REFERENCE:
                        # End of service list
                        await reader.readexactly(40)  # Skip reference message data
                        break

                    else:
                        # Unknown message: length is unknowable, so the rest
                        # of the stream cannot be parsed safely
                        logging.warning(
                            "Unknown StagelinQ message id 0x%08x from %s; "
                            "stopping service read with %d service(s)",
                            msg_id,
                            device.ipaddr,
                            len(services),
                        )
                        break

                except asyncio.IncompleteReadError:
                    break

            # Hand the live connection and its keepalive to the manager;
            # callers that decide not to use this device must call
            # disconnect_device() to release them
            self.active[device.token] = DeviceConnection(
                device=device, main_writer=writer, ref_task=ref_task
            )
            return services

        except BaseException:  # pylint: disable=broad-exception-caught
            # Ensure keepalive is stopped and writer is closed on any
            # failure. BaseException so that cancellation (stop() during an
            # input-plugin switch cancelling an in-flight setup task) cannot
            # orphan the keepalive and socket, which are not yet registered
            # in self.active at this point. Close the socket synchronously
            # first: close() cannot be interrupted by a further cancel.
            writer.close()
            ref_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ref_task
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            raise

    async def disconnect_device(self, token: bytes) -> None:
        """Close all connections and stop all tasks for one device"""
        conn = self.active.pop(token, None)
        if not conn:
            return

        # Close sockets synchronously first: the conn is already popped from
        # self.active, so a cancellation between the awaits below must not be
        # able to skip these
        for writer in (conn.state_writer, conn.main_writer):
            if writer:
                with contextlib.suppress(Exception):
                    writer.close()

        for task in (conn.monitor_task, conn.ref_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        for writer in (conn.state_writer, conn.main_writer):
            if writer:
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

    async def monitor_state_changes(  # pylint: disable=too-many-locals
        self,
        device: DenonDevice,
        service: DenonService,
        state_callback: Callable[[DenonState], None],
    ) -> None:
        """Monitor track state changes from StateMap service"""
        writer = None
        try:
            reader, writer = await asyncio.open_connection(device.ipaddr, service.port)
            if conn := self.active.get(device.token):
                conn.state_writer = writer

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
                        # Effective per-deck audibility: Denon mixers and
                        # all-in-one controllers push fader x crossfader into
                        # the deck's own StateMap; standalone players never
                        # emit /Mixer/ states at all
                        f"/Engine/Deck{deck}/ExternalMixerVolume",
                        f"/Engine/Deck{deck}/DeckIsMaster",
                    ]
                )

            # Also subscribe to crossfader position
            state_paths.append("/Mixer/CrossfaderPosition")

            # Device-level states: DJ-assigned player number (deck identity
            # across multiple players), deck count, and sync-master status
            state_paths.extend(
                [
                    "/Client/Preferences/Player",
                    "/Engine/DeckCount",
                    "/Engine/Sync/Network/MasterStatus",
                ]
            )

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
                        # Include the device address: multiple players often
                        # share a name (e.g. two "sc6000m") and all use the
                        # same per-device Deck1/Deck2 state paths
                        logging.debug(
                            "State update [%s@%s]: %s = %s",
                            device.name,
                            device.ipaddr,
                            state.name,
                            state.value,
                        )

                except asyncio.IncompleteReadError:
                    break

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Track monitoring error: %s", err)
            raise
        finally:
            # The monitor ending means this connection is finished; close
            # the writer directly in case the device was disconnected
            # before it could be registered in self.active
            if writer:
                with contextlib.suppress(Exception):
                    writer.close()

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

    @staticmethod
    def _get_broadcast_addresses() -> list[str]:
        """Get broadcast addresses for all IPv4 interfaces plus the global broadcast"""
        addresses = {"255.255.255.255"}
        try:
            # pylint: disable=no-member
            for interface in netifaces.interfaces():
                for addr_info in netifaces.ifaddresses(interface).get(netifaces.AF_INET, []):
                    broadcast = addr_info.get("broadcast")
                    if broadcast and not addr_info.get("addr", "").startswith("127."):
                        addresses.add(broadcast)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Failed to enumerate interface broadcast addresses")
        return sorted(addresses)

    async def _announce_self(self) -> None:
        """Send UDP announcement to let devices know about us"""
        try:
            device_name = "WhatsNowPlaying"
            message = StagelinqProtocol.create_discovery_message(
                self.token,
                device_name,
                nowplaying.version.__VERSION__,  # pylint:disable=no-member
            )

            # The global broadcast address only goes out the default-route
            # interface, so also send to each interface's subnet broadcast
            # to reach devices on non-default networks
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for address in self._get_broadcast_addresses():
                with contextlib.suppress(OSError):
                    sock.sendto(message, (address, DISCOVERY_PORT))
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
        # Disconnect every device (monitors, keepalives, sockets)
        for token in list(self.active):
            await self.disconnect_device(token)

        # Cancel global tasks (announcements, discovery loop)
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
