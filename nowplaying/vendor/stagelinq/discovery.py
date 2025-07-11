"""StageLinq device discovery implementation."""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum

import netifaces

from .messages import DISCOVERER_EXIT, DISCOVERER_HOWDY, DiscoveryMessage, Token
from .protocol import StageLinqProtocol

logger = logging.getLogger(__name__)


class DeviceState(Enum):
    """Device state enumeration."""

    PRESENT = "present"
    LEAVING = "leaving"


@dataclass
class Device:
    """Represents a StageLinq device."""

    ip: str
    name: str
    software_name: str
    software_version: str
    port: int
    token: Token
    state: DeviceState = DeviceState.PRESENT

    def __post_init__(self) -> None:
        """Validate device data after initialization."""
        if not self.ip:
            raise ValueError("Device IP cannot be empty")
        if not self.name:
            raise ValueError("Device name cannot be empty")
        if self.port <= 0:
            raise ValueError("Device port must be positive")

    @property
    def endpoint(self) -> tuple[str, int]:
        """Get device endpoint as (host, port) tuple."""
        return (self.ip, self.port)

    def __str__(self) -> str:
        return f"{self.name} ({self.software_name} {self.software_version}) at {self.ip}:{self.port}"

    def __eq__(self, other: object) -> bool:
        """Check device equality based on token and identity."""
        if not isinstance(other, Device):
            return False
        return (
            self.token == other.token
            and self.name == other.name
            and self.software_name == other.software_name
            and self.software_version == other.software_version
        )

    @classmethod
    def from_discovery_message(
        cls, addr: tuple[str, int], msg: DiscoveryMessage
    ) -> Device:
        """Create device from discovery message."""
        state = (
            DeviceState.PRESENT
            if msg.action == DISCOVERER_HOWDY
            else DeviceState.LEAVING
        )
        return cls(
            ip=addr[0],
            name=msg.source,
            software_name=msg.software_name,
            software_version=msg.software_version,
            port=msg.port,
            token=msg.token,
            state=state,
        )


@dataclass
class DiscoveryConfig:
    """Configuration for device discovery."""

    name: str = "Python StageLinq"
    software_name: str = "python-stagelinq"
    software_version: str = "0.1.0"
    token: Token | None = None
    port: int = 51337
    announce_interval: float = 1.0
    discovery_timeout: float = 5.0

    def __post_init__(self) -> None:
        """Initialize token if not provided."""
        if self.token is None:
            self.token = Token()


class StageLinqError(Exception):
    """Base exception for StageLinq errors."""


class DiscoveryError(StageLinqError):
    """Exception raised during device discovery."""


class StageLinqDiscovery:
    """Async StageLinq device discovery."""

    def __init__(self, config: DiscoveryConfig | None = None) -> None:
        self.config = config or DiscoveryConfig()
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: StageLinqProtocol | None = None
        self._announce_task: asyncio.Task | None = None
        self._discovered_devices: dict[str, Device] = {}

    async def __aenter__(self) -> StageLinqDiscovery:
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit."""
        await self.stop()

    async def start(self) -> None:
        """Start discovery service."""
        if self._transport is not None:
            return

        loop = asyncio.get_event_loop()
        self._transport, self._protocol = await loop.create_datagram_endpoint(
            lambda: StageLinqProtocol(self._on_message_received),
            local_addr=("0.0.0.0", self.config.port),
            reuse_port=True,
        )

        logger.info("Started StageLinq discovery on port %s", self.config.port)

    async def stop(self) -> None:
        """Stop discovery service."""
        if self._announce_task:
            self._announce_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._announce_task
        if self._transport:
            # Send leaving announcement
            await self._announce(DISCOVERER_EXIT)
            self._transport.close()
            self._transport = None

        logger.info("Stopped StageLinq discovery")

    async def start_announcing(self) -> None:
        """Start periodic announcements."""
        if self._announce_task and not self._announce_task.done():
            return

        self._announce_task = asyncio.create_task(self._announce_loop())

    async def _announce_loop(self) -> None:
        """Periodic announcement loop."""
        try:
            # Send initial announcement
            await self._announce(DISCOVERER_HOWDY)

            while True:
                await asyncio.sleep(self.config.announce_interval)
                await self._announce(DISCOVERER_HOWDY)

        except asyncio.CancelledError:
            # Send leaving announcement on cancellation
            await self._announce(DISCOVERER_EXIT)
            raise

    async def _announce(self, action: str) -> None:
        """Send announcement message."""
        if not self._transport:
            return

        msg = DiscoveryMessage(
            token=self.config.token,
            source=self.config.name,
            action=action,
            software_name=self.config.software_name,
            software_version=self.config.software_version,
            port=0,  # We don't provide services in basic discovery
        )

        writer = io.BytesIO()
        msg.write_to(writer)
        data = writer.getvalue()

        # Send to all broadcast addresses
        for broadcast_addr in self._get_broadcast_addresses():
            try:
                self._transport.sendto(data, (broadcast_addr, self.config.port))
            except Exception as e:
                # Skip IPv6 addresses or other invalid addresses for IPv4 socket
                logger.debug("Failed to send to %s: %s", broadcast_addr, e)

    def _get_broadcast_addresses(self) -> list[str]:
        """Get broadcast addresses for all network interfaces."""
        addresses = ["255.255.255.255"]  # General broadcast

        for interface in netifaces.interfaces():
            try:
                addrs = netifaces.ifaddresses(interface)
                # Include both IPv4 and IPv6 addresses like Go code does
                for family in [netifaces.AF_INET, netifaces.AF_INET6]:
                    if family in addrs:
                        addresses.extend(
                            addr_info["broadcast"]
                            for addr_info in addrs[family]
                            if "broadcast" in addr_info
                        )
            except Exception:
                continue

        return list(set(addresses))

    def _on_message_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle received discovery message."""
        try:
            reader = io.BytesIO(data)
            msg = DiscoveryMessage(Token())
            msg.read_from(reader)

            device = Device.from_discovery_message(addr, msg)

            # Skip our own messages
            if device.token == self.config.token:
                return

            device_id = f"{device.ip}:{device.token}"

            if device.state == DeviceState.LEAVING:
                self._discovered_devices.pop(device_id, None)
                logger.info("Device leaving: %s", device)
            else:
                self._discovered_devices[device_id] = device
                logger.info("Device discovered: %s", device)

        except Exception as e:
            logger.warning("Failed to parse discovery message from %s: %s", addr, e)

    async def discover_devices(
        self, timeout: float | None = None
    ) -> AsyncIterator[Device]:
        """Discover devices with async iterator."""
        if timeout is None:
            timeout = self.config.discovery_timeout

        # Start announcing ourselves
        await self.start_announcing()

        # Wait for devices to be discovered
        start_time = asyncio.get_event_loop().time()
        seen_devices = set()

        while True:
            current_time = asyncio.get_event_loop().time()
            if current_time - start_time >= timeout:
                break

            # Yield new devices
            for device in self._discovered_devices.values():
                device_key = (device.ip, str(device.token))
                if device_key not in seen_devices:
                    seen_devices.add(device_key)
                    yield device

            await asyncio.sleep(0.1)  # Small delay to prevent busy waiting

    async def get_devices(self, timeout: float | None = None) -> list[Device]:
        """Get all discovered devices as a list."""
        return [device async for device in self.discover_devices(timeout)]

    @property
    def discovered_devices(self) -> dict[str, Device]:
        """Get currently discovered devices."""
        return self._discovered_devices.copy()


@contextlib.asynccontextmanager
async def discover_stagelinq_devices(
    config: DiscoveryConfig | None = None,
) -> AsyncIterator[StageLinqDiscovery]:
    """Context manager for StageLinq device discovery."""
    discovery = StageLinqDiscovery(config)
    try:
        await discovery.start()
        yield discovery
    finally:
        await discovery.stop()
