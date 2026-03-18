#!/usr/bin/env python3
"""test mDNS discovery module"""

import socket
from unittest.mock import MagicMock, patch

import pytest

import nowplaying.mdns_discovery


@pytest.mark.asyncio
async def test_discovered_service_namedtuple():
    """test DiscoveredService namedtuple structure"""
    service = nowplaying.mdns_discovery.DiscoveredService(
        name="TestService._whatsnowplaying._tcp.local.",
        host="testhost.local.",
        port=8899,
        addresses=["192.168.1.100"],
        properties={b"version": b"1.0.0", b"app": b"WhatsNowPlaying"},
    )

    assert service.name == "TestService._whatsnowplaying._tcp.local."
    assert service.host == "testhost.local."
    assert service.port == 8899
    assert service.addresses == ["192.168.1.100"]
    assert service.properties == {b"version": b"1.0.0", b"app": b"WhatsNowPlaying"}


@pytest.mark.asyncio
async def test_service_discovery_listener_add_service():
    """test ServiceDiscoveryListener add_service method"""
    listener = nowplaying.mdns_discovery.ServiceDiscoveryListener()

    # Mock Zeroconf and service info
    mock_zc = MagicMock()
    mock_info = MagicMock()
    mock_info.server = "testhost.local."
    mock_info.port = 8899
    mock_info.addresses = [b"\xc0\xa8\x01\x64"]  # 192.168.1.100
    mock_info.properties = {b"version": b"1.0.0"}

    mock_zc.get_service_info.return_value = mock_info

    listener.add_service(mock_zc, "_whatsnowplaying._tcp.local.", "TestService")

    assert len(listener.services) == 1
    assert listener.services[0].host == "testhost.local."
    assert listener.services[0].port == 8899
    assert listener.services[0].addresses == ["192.168.1.100"]


@pytest.mark.asyncio
async def test_service_discovery_listener_add_service_no_info():
    """test ServiceDiscoveryListener when service info is None"""
    listener = nowplaying.mdns_discovery.ServiceDiscoveryListener()

    # Mock Zeroconf returning None
    mock_zc = MagicMock()
    mock_zc.get_service_info.return_value = None

    listener.add_service(mock_zc, "_whatsnowplaying._tcp.local.", "TestService")

    assert len(listener.services) == 0


@pytest.mark.asyncio
async def test_discover_whatsnowplaying_services_success():
    """test discover_whatsnowplaying_services with successful discovery"""
    with (
        patch("nowplaying.mdns_discovery.Zeroconf") as mock_zeroconf_class,
        patch("nowplaying.mdns_discovery.ServiceBrowser") as mock_browser_class,
        patch("nowplaying.mdns_discovery.time.sleep"),
    ):
        mock_zc = MagicMock()
        mock_zeroconf_class.return_value = mock_zc

        # Mock the listener to simulate finding a service
        def create_browser(mock_zeroconf, service_type, listener):
            # Simulate finding a service
            mock_info = MagicMock()
            mock_info.server = "testhost.local."
            mock_info.port = 8899
            mock_info.addresses = [b"\xc0\xa8\x01\x64"]
            mock_info.properties = {}
            mock_zeroconf.get_service_info.return_value = mock_info
            listener.add_service(mock_zeroconf, service_type, "TestService")
            return MagicMock()

        mock_browser_class.side_effect = create_browser

        with patch("nowplaying.mdns_discovery.get_local_addresses", return_value=set()):
            services = nowplaying.mdns_discovery.discover_whatsnowplaying_services(timeout=0.1)

        assert len(services) == 1
        assert services[0].host == "testhost.local."
        assert services[0].port == 8899
        mock_zc.close.assert_called_once()


@pytest.mark.asyncio
async def test_discover_whatsnowplaying_services_no_services():
    """test discover_whatsnowplaying_services when no services found"""
    with (
        patch("nowplaying.mdns_discovery.Zeroconf") as mock_zeroconf_class,
        patch("nowplaying.mdns_discovery.ServiceBrowser"),
        patch("nowplaying.mdns_discovery.time.sleep"),
    ):
        mock_zc = MagicMock()
        mock_zeroconf_class.return_value = mock_zc

        services = nowplaying.mdns_discovery.discover_whatsnowplaying_services(timeout=0.1)

        assert len(services) == 0
        mock_zc.close.assert_called_once()


@pytest.mark.asyncio
async def test_discover_whatsnowplaying_services_exception():
    """test discover_whatsnowplaying_services handles exceptions gracefully"""
    with patch("nowplaying.mdns_discovery.Zeroconf") as mock_zeroconf_class:
        mock_zeroconf_class.side_effect = Exception("Network error")

        services = nowplaying.mdns_discovery.discover_whatsnowplaying_services(timeout=0.1)

        assert not services


@pytest.mark.asyncio
async def test_get_first_whatsnowplaying_service_found():
    """test get_first_whatsnowplaying_service when service is found"""
    with patch("nowplaying.mdns_discovery.discover_whatsnowplaying_services") as mock_discover:
        mock_service = nowplaying.mdns_discovery.DiscoveredService(
            name="TestService._whatsnowplaying._tcp.local.",
            host="testhost.local.",
            port=8899,
            addresses=["192.168.1.100"],
            properties={},
        )
        mock_discover.return_value = [mock_service]

        service = nowplaying.mdns_discovery.get_first_whatsnowplaying_service()

        assert service == mock_service


@pytest.mark.asyncio
async def test_get_first_whatsnowplaying_service_not_found():
    """test get_first_whatsnowplaying_service when no service is found"""
    with patch("nowplaying.mdns_discovery.discover_whatsnowplaying_services") as mock_discover:
        mock_discover.return_value = []

        service = nowplaying.mdns_discovery.get_first_whatsnowplaying_service()

        assert service is None


def test_get_local_addresses_returns_set():
    """test get_local_addresses returns a set of IP strings"""
    addresses = nowplaying.mdns_discovery.get_local_addresses()
    assert isinstance(addresses, set)
    for addr in addresses:
        # Each entry should be a valid IPv4 address string
        socket.inet_aton(addr)  # raises if invalid


def test_get_local_addresses_no_netifaces():
    """test get_local_addresses falls back to socket when netifaces unavailable"""
    with patch("nowplaying.mdns_discovery._HAVE_NETIFACES", False):
        addresses = nowplaying.mdns_discovery.get_local_addresses()
    assert isinstance(addresses, set)


def test_is_local_service_all_local():
    """test _is_local_service returns True when all addresses are local"""
    service = nowplaying.mdns_discovery.DiscoveredService(
        name="test",
        host="myhost.local.",
        port=8899,
        addresses=["192.168.1.10", "10.0.0.5"],
        properties={},
    )
    assert nowplaying.mdns_discovery._is_local_service(  # pylint: disable=protected-access
        service, {"192.168.1.10", "10.0.0.5"}
    )


def test_is_local_service_partial_local():
    """test _is_local_service returns False when only some addresses are local"""
    service = nowplaying.mdns_discovery.DiscoveredService(
        name="test",
        host="myhost.local.",
        port=8899,
        addresses=["192.168.1.10", "192.168.1.99"],
        properties={},
    )
    assert not nowplaying.mdns_discovery._is_local_service(  # pylint: disable=protected-access
        service, {"192.168.1.10"}
    )


def test_is_local_service_no_addresses():
    """test _is_local_service returns False when service has no addresses"""
    service = nowplaying.mdns_discovery.DiscoveredService(
        name="test",
        host="myhost.local.",
        port=8899,
        addresses=[],
        properties={},
    )
    assert not nowplaying.mdns_discovery._is_local_service(  # pylint: disable=protected-access
        service, {"192.168.1.10"}
    )


@pytest.mark.asyncio
async def test_discover_filters_own_service():
    """test that discover_whatsnowplaying_services filters out the local machine's own service"""
    with (
        patch("nowplaying.mdns_discovery.Zeroconf") as mock_zeroconf_class,
        patch("nowplaying.mdns_discovery.ServiceBrowser") as mock_browser_class,
        patch("nowplaying.mdns_discovery.time.sleep"),
        patch(
            "nowplaying.mdns_discovery.get_local_addresses",
            return_value={"192.168.1.100"},
        ),
    ):
        mock_zc = MagicMock()
        mock_zeroconf_class.return_value = mock_zc

        def create_browser(mock_zeroconf, service_type, listener):
            # Simulate finding this machine's own service
            mock_info = MagicMock()
            mock_info.server = "myhost.local."
            mock_info.port = 8899
            mock_info.addresses = [b"\xc0\xa8\x01\x64"]  # 192.168.1.100
            mock_info.properties = {}
            mock_zeroconf.get_service_info.return_value = mock_info
            listener.add_service(mock_zeroconf, service_type, "WhatsNowPlaying")
            return MagicMock()

        mock_browser_class.side_effect = create_browser

        services = nowplaying.mdns_discovery.discover_whatsnowplaying_services(timeout=0.1)

    # Own service should be filtered out
    assert len(services) == 0


@pytest.mark.asyncio
async def test_discover_keeps_remote_service():
    """test that discover_whatsnowplaying_services keeps remote machines' services"""
    with (
        patch("nowplaying.mdns_discovery.Zeroconf") as mock_zeroconf_class,
        patch("nowplaying.mdns_discovery.ServiceBrowser") as mock_browser_class,
        patch("nowplaying.mdns_discovery.time.sleep"),
        patch(
            "nowplaying.mdns_discovery.get_local_addresses",
            return_value={"192.168.1.50"},  # local machine is .50, service is .100
        ),
    ):
        mock_zc = MagicMock()
        mock_zeroconf_class.return_value = mock_zc

        def create_browser(mock_zeroconf, service_type, listener):
            mock_info = MagicMock()
            mock_info.server = "remotehost.local."
            mock_info.port = 8899
            mock_info.addresses = [b"\xc0\xa8\x01\x64"]  # 192.168.1.100
            mock_info.properties = {}
            mock_zeroconf.get_service_info.return_value = mock_info
            listener.add_service(mock_zeroconf, service_type, "WhatsNowPlaying")
            return MagicMock()

        mock_browser_class.side_effect = create_browser

        services = nowplaying.mdns_discovery.discover_whatsnowplaying_services(timeout=0.1)

    # Remote service should not be filtered
    assert len(services) == 1
    assert services[0].addresses == ["192.168.1.100"]
