#!/usr/bin/env python3
"""mDNS/Bonjour service discovery helper"""

import asyncio
import logging
import socket
import time
from typing import NamedTuple

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

try:
    import netifaces  # pylint: disable=import-error

    _HAVE_NETIFACES = True
except ImportError:
    _HAVE_NETIFACES = False


class DiscoveredService(NamedTuple):
    """Information about a discovered service"""

    name: str
    host: str
    port: int
    addresses: list[str]
    properties: dict[bytes, bytes]


class ServiceDiscoveryListener(ServiceListener):
    """Listener that collects discovered services"""

    def __init__(self):
        self.services: list[DiscoveredService] = []

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Service updated"""

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Service removed"""

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Service discovered"""
        info = zc.get_service_info(type_, name)
        if info:
            # Convert addresses to readable IP strings (IPv4 only)
            addresses = []
            for addr in info.addresses:
                if len(addr) == 4:
                    addresses.append(socket.inet_ntoa(addr))
            service = DiscoveredService(
                name=name,
                host=info.server,
                port=info.port,
                addresses=addresses,
                properties=info.properties,
            )
            self.services.append(service)
            logging.debug("Discovered service: %s at %s:%s", name, addresses, info.port)


def get_local_addresses() -> set[str]:
    """Return the set of local non-loopback IPv4 addresses for self-filtering."""
    local_ips: set[str] = set()
    if _HAVE_NETIFACES:
        try:
            for interface in netifaces.interfaces():  # pylint: disable=no-member
                addrs = netifaces.ifaddresses(interface)  # pylint: disable=no-member
                if netifaces.AF_INET in addrs:  # pylint: disable=no-member
                    for addr_info in addrs[netifaces.AF_INET]:  # pylint: disable=no-member
                        ip_addr = addr_info.get("addr")
                        if ip_addr and not ip_addr.startswith("127."):
                            local_ips.add(ip_addr)
        except Exception:  # pylint: disable=broad-except
            pass
    if not local_ips:
        # Fallback: resolve own hostname
        try:
            ip_addr = socket.gethostbyname(socket.gethostname())
            if ip_addr and not ip_addr.startswith("127."):
                local_ips.add(ip_addr)
        except Exception:  # pylint: disable=broad-except
            pass
    return local_ips


def _is_local_service(service: DiscoveredService, local_ips: set[str]) -> bool:
    """Return True if all of a service's addresses belong to this machine."""
    if not service.addresses:
        return False
    return all(addr in local_ips for addr in service.addresses)


def discover_whatsnowplaying_services(
    timeout: float = 3.0, filter_local: bool = True
) -> list[DiscoveredService]:
    """
    Discover WhatsNowPlaying services on the local network via mDNS/Bonjour

    Args:
        timeout: How long to search for services (seconds)
        filter_local: If True, exclude services running on this machine

    Returns:
        List of discovered services
    """
    try:
        zeroconf = Zeroconf()
        listener = ServiceDiscoveryListener()
        _browser = ServiceBrowser(zeroconf, "_whatsnowplaying._tcp.local.", listener)

        # Wait for discovery
        time.sleep(timeout)

        zeroconf.close()

        if filter_local:
            local_ips = get_local_addresses()
            services = [s for s in listener.services if not _is_local_service(s, local_ips)]
            if len(services) < len(listener.services):
                logging.debug(
                    "Filtered %d local self-service(s) from discovery results",
                    len(listener.services) - len(services),
                )
            return services

        return listener.services
    except Exception as error:  # pylint: disable=broad-except
        logging.warning("mDNS discovery failed: %s", error)
        return []


def get_first_whatsnowplaying_service() -> DiscoveredService | None:
    """
    Convenience function to get the first discovered WhatsNowPlaying service

    Returns:
        First discovered service or None
    """
    services = discover_whatsnowplaying_services()
    if services:
        return services[0]
    return None


async def discover_whatsnowplaying_services_async(timeout: float = 3.0) -> list[DiscoveredService]:
    """
    Async version: Discover WhatsNowPlaying services without blocking the event loop

    Args:
        timeout: How long to search for services (seconds)

    Returns:
        List of discovered services
    """
    return await asyncio.to_thread(discover_whatsnowplaying_services, timeout)


async def get_first_whatsnowplaying_service_async() -> DiscoveredService | None:
    """
    Async convenience function to get the first discovered WhatsNowPlaying service

    Returns:
        First discovered service or None
    """
    services = await discover_whatsnowplaying_services_async()
    if services:
        return services[0]
    return None
