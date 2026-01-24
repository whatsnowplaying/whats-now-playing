#!/usr/bin/env python3
"""test mDNS discovery module"""

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
    with patch("nowplaying.mdns_discovery.Zeroconf") as mock_zeroconf_class, patch(
        "nowplaying.mdns_discovery.ServiceBrowser"
    ) as mock_browser_class, patch("nowplaying.mdns_discovery.time.sleep"):
        mock_zc = MagicMock()
        mock_zeroconf_class.return_value = mock_zc

        # Mock the listener to simulate finding a service
        def create_browser(zc, service_type, listener):
            # Simulate finding a service
            mock_info = MagicMock()
            mock_info.server = "testhost.local."
            mock_info.port = 8899
            mock_info.addresses = [b"\xc0\xa8\x01\x64"]
            mock_info.properties = {}
            zc.get_service_info.return_value = mock_info
            listener.add_service(zc, service_type, "TestService")
            return MagicMock()

        mock_browser_class.side_effect = create_browser

        services = nowplaying.mdns_discovery.discover_whatsnowplaying_services(timeout=0.1)

        assert len(services) == 1
        assert services[0].host == "testhost.local."
        assert services[0].port == 8899
        mock_zc.close.assert_called_once()


@pytest.mark.asyncio
async def test_discover_whatsnowplaying_services_no_services():
    """test discover_whatsnowplaying_services when no services found"""
    with patch("nowplaying.mdns_discovery.Zeroconf") as mock_zeroconf_class, patch(
        "nowplaying.mdns_discovery.ServiceBrowser"
    ), patch("nowplaying.mdns_discovery.time.sleep"):
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

        assert services == []


@pytest.mark.asyncio
async def test_get_first_whatsnowplaying_service_found():
    """test get_first_whatsnowplaying_service when service is found"""
    with patch(
        "nowplaying.mdns_discovery.discover_whatsnowplaying_services"
    ) as mock_discover:
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
    with patch(
        "nowplaying.mdns_discovery.discover_whatsnowplaying_services"
    ) as mock_discover:
        mock_discover.return_value = []

        service = nowplaying.mdns_discovery.get_first_whatsnowplaying_service()

        assert service is None
