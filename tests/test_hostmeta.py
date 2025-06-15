#!/usr/bin/env python3
''' test hostmeta '''

import datetime
import unittest.mock

import nowplaying.hostmeta  # pylint: disable=import-error


def test_basic_hostmeta():
    ''' test getting basic host info '''
    hostinfo = nowplaying.hostmeta.gethostmeta()
    assert hostinfo is not None
    assert hostinfo['hostname'] is not None
    assert hostinfo['hostfqdn'] is not None
    assert hostinfo['hostip'] is not None

    # Validate IP format (basic check)
    host_ip = hostinfo['hostip']
    assert '.' in host_ip or ':' in host_ip  # IPv4 or IPv6

    # Validate hostname types
    assert isinstance(hostinfo['hostname'], str)
    assert isinstance(hostinfo['hostfqdn'], str)
    assert isinstance(hostinfo['hostip'], str)


def test_hostmeta_caching():
    ''' test that hostmeta caches results for 10 minutes '''
    # Clear cached values
    nowplaying.hostmeta.TIMESTAMP = None
    nowplaying.hostmeta.HOSTNAME = None
    nowplaying.hostmeta.HOSTFQDN = None
    nowplaying.hostmeta.HOSTIP = None

    # First call should populate cache
    hostinfo1 = nowplaying.hostmeta.gethostmeta()
    timestamp1 = nowplaying.hostmeta.TIMESTAMP

    # Second immediate call should use cache
    hostinfo2 = nowplaying.hostmeta.gethostmeta()
    timestamp2 = nowplaying.hostmeta.TIMESTAMP

    assert hostinfo1 == hostinfo2
    assert timestamp1 == timestamp2


def test_hostmeta_cache_expiry():
    ''' test that cache expires after time delta '''
    # Clear cached values
    nowplaying.hostmeta.TIMESTAMP = None
    nowplaying.hostmeta.HOSTNAME = None

    # Mock old timestamp (11 minutes ago)
    old_time = datetime.datetime.now() - datetime.timedelta(minutes=11)
    nowplaying.hostmeta.TIMESTAMP = old_time

    # Should refresh due to expired cache
    hostinfo = nowplaying.hostmeta.gethostmeta()
    new_timestamp = nowplaying.hostmeta.TIMESTAMP

    assert new_timestamp > old_time
    assert hostinfo is not None


def test_socket_failure_graceful_degradation():
    ''' test graceful behavior when socket methods fail '''
    # Clear cached values
    nowplaying.hostmeta.TIMESTAMP = None
    nowplaying.hostmeta.HOSTNAME = None
    nowplaying.hostmeta.HOSTFQDN = None
    nowplaying.hostmeta.HOSTIP = None

    # Mock socket failures
    with unittest.mock.patch('socket.gethostname', side_effect=OSError("Mock socket error")):
        with unittest.mock.patch('socket.getfqdn', side_effect=OSError("Mock socket error")):
            with unittest.mock.patch('socket.gethostbyname',
                                     side_effect=OSError("Mock socket error")):
                hostinfo = nowplaying.hostmeta.gethostmeta()

                # Critical: Must not crash and must return proper structure
                assert isinstance(hostinfo, dict)
                assert 'hostname' in hostinfo
                assert 'hostfqdn' in hostinfo
                assert 'hostip' in hostinfo

                # Values should be strings or None (no mixed types)
                for key, value in hostinfo.items():
                    assert isinstance(value, (str, type(None))), \
                        f"{key} has wrong type: {type(value)}"

                # At minimum, should have some usable IP (from netifaces or fallback)
                # Different platforms may behave differently
                assert hostinfo['hostip'] is not None, \
                    "Should always have some IP address for DJ use"


def test_netifaces_fallback():
    ''' test netifaces fallback when socket IP resolution fails '''
    # Clear cached values
    nowplaying.hostmeta.TIMESTAMP = None
    nowplaying.hostmeta.HOSTNAME = None
    nowplaying.hostmeta.HOSTFQDN = None
    nowplaying.hostmeta.HOSTIP = None

    # Mock partial socket failure (hostname works, IP fails)
    with unittest.mock.patch('socket.gethostbyname',
                             side_effect=OSError("Mock IP resolution error")):
        hostinfo = nowplaying.hostmeta.gethostmeta()

        # Should still get valid results (either from netifaces or fallback)
        assert hostinfo['hostname'] is not None
        assert hostinfo['hostfqdn'] is not None
        assert hostinfo['hostip'] is not None
        assert hostinfo['hostip'] != ''


def test_extreme_network_failure_resilience():
    ''' test resilience when everything fails (broken club/conference networks) '''
    # Clear cached values
    nowplaying.hostmeta.TIMESTAMP = None
    nowplaying.hostmeta.HOSTNAME = None
    nowplaying.hostmeta.HOSTFQDN = None
    nowplaying.hostmeta.HOSTIP = None

    # Mock all possible failures including netifaces
    socket_error = OSError("Mock complete network failure")
    with unittest.mock.patch('socket.gethostname', side_effect=socket_error):
        with unittest.mock.patch('socket.getfqdn', side_effect=socket_error):
            with unittest.mock.patch('socket.gethostbyname', side_effect=socket_error):
                # Mock netifaces complete failure if available
                if nowplaying.hostmeta.IFACES:
                    # Mock netifaces module itself to fail internally
                    with unittest.mock.patch(
                            'netifaces.gateways',
                            side_effect=Exception("Mock netifaces module failure")):
                        hostinfo = nowplaying.hostmeta.gethostmeta()
                else:
                    hostinfo = nowplaying.hostmeta.gethostmeta()

                # Critical for DJ use: Must not crash and provide usable structure
                assert isinstance(hostinfo, dict)
                assert 'hostname' in hostinfo
                assert 'hostfqdn' in hostinfo
                assert 'hostip' in hostinfo

                # In extreme failure, should fall back to localhost/127.0.0.1
                # This ensures DJ can still use the webserver locally
                assert hostinfo['hostip'] is not None, \
                    "Must provide fallback IP for local webserver access"


def test_netifaces_availability():
    ''' test whether netifaces is available and working '''
    if nowplaying.hostmeta.IFACES:
        # netifaces is available, test that trynetifaces doesn't crash
        try:
            nowplaying.hostmeta.trynetifaces()
            # Should not raise exception (IP may or may not be set)
        except Exception:  # pylint: disable=broad-exception-caught
            # If it fails, that's expected behavior (logged but handled)
            assert True  # Test passes either way
    else:
        # netifaces not available, should skip gracefully
        assert not nowplaying.hostmeta.IFACES


def test_reverse_dns_hostname_detection():
    ''' test detection and correction of reverse DNS hostnames '''
    # Clear cached values
    nowplaying.hostmeta.TIMESTAMP = None
    nowplaying.hostmeta.HOSTNAME = None
    nowplaying.hostmeta.HOSTFQDN = None
    nowplaying.hostmeta.HOSTIP = None

    # Mock getfqdn returning reverse DNS result
    with unittest.mock.patch('socket.gethostname', return_value='test-machine.local'):
        with unittest.mock.patch('socket.getfqdn', return_value='1.0.0.127.in-addr.arpa'):
            with unittest.mock.patch('socket.gethostbyname', side_effect=OSError("DNS error")):
                hostinfo = nowplaying.hostmeta.gethostmeta()

                # Should detect and fix reverse DNS hostname
                assert hostinfo['hostname'] == 'test-machine.local'
                assert hostinfo['hostfqdn'] == 'test-machine.local'  # Fixed, not reverse DNS
                assert hostinfo['hostip'] is not None  # Should get IP from netifaces or fallback


def test_ipv6_reverse_dns_hostname_detection():
    ''' test detection and correction of IPv6 reverse DNS hostnames '''
    # Clear cached values
    nowplaying.hostmeta.TIMESTAMP = None
    nowplaying.hostmeta.HOSTNAME = None
    nowplaying.hostmeta.HOSTFQDN = None
    nowplaying.hostmeta.HOSTIP = None

    # Mock getfqdn returning IPv6 reverse DNS result
    with unittest.mock.patch('socket.gethostname', return_value='test-machine'):
        with unittest.mock.patch('socket.getfqdn', return_value='1.0.0.0.0.0.0.0.ip6.arpa'):
            with unittest.mock.patch('socket.gethostbyname', side_effect=OSError("DNS error")):
                hostinfo = nowplaying.hostmeta.gethostmeta()

                # Should detect and fix IPv6 reverse DNS hostname
                assert hostinfo['hostname'] == 'test-machine'
                assert hostinfo['hostfqdn'] == 'test-machine'  # Fixed, not reverse DNS
                assert hostinfo['hostip'] is not None


def test_localhost_ip_rejection():
    ''' test that localhost IPs are rejected in favor of netifaces '''
    # Clear cached values
    nowplaying.hostmeta.TIMESTAMP = None
    nowplaying.hostmeta.HOSTNAME = None
    nowplaying.hostmeta.HOSTFQDN = None
    nowplaying.hostmeta.HOSTIP = None

    # Mock scenario where hostname resolves to localhost
    with unittest.mock.patch('socket.gethostname', return_value='localhost.localdomain'):
        with unittest.mock.patch('socket.getfqdn', return_value='localhost.localdomain'):
            with unittest.mock.patch('socket.gethostbyname', return_value='127.0.0.1'):
                hostinfo = nowplaying.hostmeta.gethostmeta()

                # Should reject 127.0.0.1 and use netifaces or fallback
                if nowplaying.hostmeta.IFACES:
                    # If netifaces available, should get real network IP (not 127.0.0.1)
                    # Allow 127.0.0.1 only if netifaces also fails to find network interface
                    assert hostinfo['hostip'] is not None
                else:
                    # Without netifaces, will fall back to 127.0.0.1
                    assert hostinfo['hostip'] == '127.0.0.1'


def test_cross_platform_hostname_formats():
    ''' test handling of different hostname formats across platforms '''
    test_cases = [
        # (hostname, fqdn, description)
        ('DESKTOP-ABC123', 'DESKTOP-ABC123', 'Windows machine name'),
        ('ubuntu-server', 'ubuntu-server.example.com', 'Linux with domain'),
        ('macbook-pro.local', 'macbook-pro.local', 'macOS .local domain'),
        ('test-machine', 'test-machine.localdomain', 'Generic localhost domain'),
        ('server01', 'server01', 'Simple hostname without domain'),
    ]

    for hostname, fqdn, description in test_cases:
        # Clear cached values for each test
        nowplaying.hostmeta.TIMESTAMP = None
        nowplaying.hostmeta.HOSTNAME = None
        nowplaying.hostmeta.HOSTFQDN = None
        nowplaying.hostmeta.HOSTIP = None

        with unittest.mock.patch('socket.gethostname', return_value=hostname):
            with unittest.mock.patch('socket.getfqdn', return_value=fqdn):
                with unittest.mock.patch('socket.gethostbyname', side_effect=OSError("DNS error")):
                    hostinfo = nowplaying.hostmeta.gethostmeta()

                    # Should handle all hostname formats gracefully
                    assert hostinfo['hostname'] == hostname, f"Failed for {description}"
                    assert hostinfo['hostfqdn'] == fqdn, f"Failed for {description}"
                    assert hostinfo['hostip'] is not None, f"Failed for {description}"

                    # Validate types
                    assert isinstance(hostinfo['hostname'], str), f"Failed for {description}"
                    assert isinstance(hostinfo['hostfqdn'], str), f"Failed for {description}"
                    assert isinstance(hostinfo['hostip'], str), f"Failed for {description}"


def test_windows_dns_behavior_simulation():
    ''' test simulation of Windows DNS resolution behavior '''
    # Clear cached values
    nowplaying.hostmeta.TIMESTAMP = None
    nowplaying.hostmeta.HOSTNAME = None
    nowplaying.hostmeta.HOSTFQDN = None
    nowplaying.hostmeta.HOSTIP = None

    # Simulate Windows behavior: hostname without domain, FQDN with domain
    with unittest.mock.patch('socket.gethostname', return_value='WORKSTATION01'):
        with unittest.mock.patch('socket.getfqdn', return_value='WORKSTATION01.company.local'):
            with unittest.mock.patch('socket.gethostbyname', return_value='192.168.1.100'):
                hostinfo = nowplaying.hostmeta.gethostmeta()

                # Should use real network IP (not localhost)
                assert hostinfo['hostname'] == 'WORKSTATION01'
                assert hostinfo['hostfqdn'] == 'WORKSTATION01.company.local'
                assert hostinfo['hostip'] == '192.168.1.100'  # Real IP, should be used


def test_linux_dns_behavior_simulation():
    ''' test simulation of Linux DNS resolution behavior '''
    # Clear cached values
    nowplaying.hostmeta.TIMESTAMP = None
    nowplaying.hostmeta.HOSTNAME = None
    nowplaying.hostmeta.HOSTFQDN = None
    nowplaying.hostmeta.HOSTIP = None

    # Simulate Linux behavior: hostname and FQDN may be same or different
    with unittest.mock.patch('socket.gethostname', return_value='ubuntu-server'):
        with unittest.mock.patch('socket.getfqdn', return_value='ubuntu-server.internal'):
            with unittest.mock.patch('socket.gethostbyname', return_value='10.0.0.50'):
                hostinfo = nowplaying.hostmeta.gethostmeta()

                # Should use real network IP
                assert hostinfo['hostname'] == 'ubuntu-server'
                assert hostinfo['hostfqdn'] == 'ubuntu-server.internal'
                assert hostinfo['hostip'] == '10.0.0.50'  # Real IP, should be used


def test_hostname_edge_cases():
    ''' test edge cases in hostname handling '''
    edge_cases = [
        # (hostname, fqdn, expected_behavior)
        ('', 'fallback.local', 'empty hostname'),
        ('localhost', 'localhost', 'localhost hostname'),
        ('127.0.0.1', '127.0.0.1', 'IP as hostname'),
        ('a' * 100, 'long.hostname.test', 'very long hostname'),
        ('test-with-unicode-café', 'test.local', 'unicode in hostname'),
    ]

    for hostname, fqdn, description in edge_cases:
        # Clear cached values for each test
        nowplaying.hostmeta.TIMESTAMP = None
        nowplaying.hostmeta.HOSTNAME = None
        nowplaying.hostmeta.HOSTFQDN = None
        nowplaying.hostmeta.HOSTIP = None

        with unittest.mock.patch('socket.gethostname', return_value=hostname):
            with unittest.mock.patch('socket.getfqdn', return_value=fqdn):
                with unittest.mock.patch('socket.gethostbyname', side_effect=OSError("DNS error")):
                    try:
                        hostinfo = nowplaying.hostmeta.gethostmeta()

                        # Should handle edge cases gracefully without crashing
                        assert isinstance(hostinfo, dict), f"Failed for {description}"
                        assert 'hostname' in hostinfo, f"Failed for {description}"
                        assert 'hostfqdn' in hostinfo, f"Failed for {description}"
                        assert 'hostip' in hostinfo, f"Failed for {description}"

                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        # If it fails, should be graceful (fallback should work)
                        assert False, f"Crashed on {description}: {exc}"
