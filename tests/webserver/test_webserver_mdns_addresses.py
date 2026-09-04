#!/usr/bin/env python3
"""test which interface addresses get advertised over mDNS

Anything advertised here is somewhere a client will try to connect, and it is
also the interface list handed to zeroconf, so a wrong answer either sends
EarShot to an address that cannot answer or stops the announcement reaching the
network at all.  The awkward cases come from real machines: virtualization
bridges sitting on the network address of their own subnet, and point-to-point
tunnels sitting on what looks like one.
"""

import pytest

import nowplaying.processes.webserver  # pylint: disable=import-error


def advertisable(ip_addr, netmask):
    """call the filter under test"""
    return nowplaying.processes.webserver.WebHandler._advertisable_address(  # pylint: disable=protected-access
        ip_addr, netmask
    )


@pytest.mark.parametrize(
    "ip_addr,netmask,expected,why",
    [
        ("192.168.100.221", "255.255.255.0", True, "ordinary LAN address"),
        ("192.168.139.3", "255.255.254.0", True, "ordinary address on a /23"),
        ("10.0.0.1", "255.0.0.0", True, "ordinary address on a /8"),
        # An OrbStack bridge was seen holding 192.168.97.0/24: the host address
        # is also the network address, so nothing can source a packet from it.
        ("192.168.97.0", "255.255.255.0", False, "network address of its own /24"),
        ("10.0.0.0", "255.0.0.0", False, "network address of its own /8"),
        ("192.168.1.255", "255.255.255.0", False, "broadcast address"),
        ("127.0.0.1", "255.0.0.0", False, "loopback"),
        ("127.0.0.53", "255.0.0.0", False, "loopback, not just .0.1"),
        ("169.254.10.4", "255.255.0.0", False, "link-local, reachable by nobody"),
        ("0.0.0.0", "255.255.255.0", False, "unspecified"),
        # RFC 3021 /31 links and /32 tunnel endpoints legitimately sit on an
        # address ipaddress reports as the network address.  Rejecting these
        # would stop advertising over a VPN, which is when discovery matters.
        ("10.8.0.2", "255.255.255.255", True, "/32 tunnel endpoint"),
        ("10.8.0.0", "255.255.255.254", True, "/31 point-to-point, low half"),
        ("10.8.0.1", "255.255.255.254", True, "/31 point-to-point, high half"),
        ("192.168.5.7", None, True, "missing netmask falls back to /32"),
        ("garbage", "255.255.255.0", False, "unparseable address"),
        ("192.168.1.5", "not-a-mask", False, "unparseable netmask"),
    ],
)
def test_advertisable_address(ip_addr, netmask, expected, why):
    """only addresses a client could actually reach are advertised"""
    assert advertisable(ip_addr, netmask) is expected, why


def test_malformed_input_does_not_raise():
    """a DJ set does not stop because netifaces returned something strange"""
    for ip_addr, netmask in [
        ("", ""),
        ("::1", "255.255.255.0"),
        ("999.999.999.999", "255.255.255.0"),
        ("192.168.1.1", "255.255.255.0/24"),
    ]:
        try:
            assert isinstance(advertisable(ip_addr, netmask), bool)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            pytest.fail(f"_advertisable_address({ip_addr!r}, {netmask!r}) raised {exc}")
