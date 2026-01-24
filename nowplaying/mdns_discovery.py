#!/usr/bin/env python3
"""mDNS/Bonjour service discovery helper"""

import logging
import socket
import time
from typing import NamedTuple

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf


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
            # Convert addresses to readable IP strings
            addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
            service = DiscoveredService(
                name=name,
                host=info.server,
                port=info.port,
                addresses=addresses,
                properties=info.properties,
            )
            self.services.append(service)
            logging.debug("Discovered service: %s at %s:%s", name, addresses, info.port)


def discover_whatsnowplaying_services(timeout: float = 3.0) -> list[DiscoveredService]:
    """
    Discover WhatsNowPlaying services on the local network via mDNS/Bonjour

    Args:
        timeout: How long to search for services (seconds)

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
