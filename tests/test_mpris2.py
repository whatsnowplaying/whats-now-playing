#!/usr/bin/env python3
''' test mpris2 input plugin '''

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from dbus_fast.signature import Variant
    DBUS_FAST_AVAILABLE = True
except ImportError:
    DBUS_FAST_AVAILABLE = False

import nowplaying.inputs.mpris2  # pylint: disable=import-error,no-member,no-name-in-module


def test_init_without_dbus():
    """Test handler initialization without D-Bus available"""
    with patch('nowplaying.inputs.mpris2.DBUS_STATUS', False):
        handler = nowplaying.inputs.mpris2.MPRIS2Handler()  # pylint: disable=no-member
        assert handler.dbus_status is False


def test_service_assignment():
    """Test service assignment in init"""
    with patch('nowplaying.inputs.mpris2.DBUS_STATUS', True):
        handler = nowplaying.inputs.mpris2.MPRIS2Handler(service="vlc")  # pylint: disable=no-member
        assert handler.service == "vlc"


def test_plugin_init_without_dbus():
    """Test plugin initialization without D-Bus available"""
    with patch('nowplaying.inputs.mpris2.DBUS_STATUS', False):
        plugin = nowplaying.inputs.mpris2.Plugin()  # pylint: disable=no-member
        assert plugin.dbus_status is False
        assert plugin.available is False


def test_plugin_install():
    """Test install method"""
    with patch('nowplaying.inputs.mpris2.DBUS_STATUS', True):
        plugin = nowplaying.inputs.mpris2.Plugin()  # pylint: disable=no-member
        assert plugin.install() is False


@pytest.mark.asyncio
async def test_plugin_getrandomtrack():
    """Test getrandomtrack method"""
    with patch('nowplaying.inputs.mpris2.DBUS_STATUS', True):
        plugin = nowplaying.inputs.mpris2.Plugin()  # pylint: disable=no-member
        result = await plugin.getrandomtrack(None)
        assert result is None


def test_desc_settingsui_without_dbus():
    """Test settings UI description without D-Bus"""
    with patch('nowplaying.inputs.mpris2.DBUS_STATUS', False):
        plugin = nowplaying.inputs.mpris2.Plugin()  # pylint: disable=no-member
        mock_widget = MagicMock()

        plugin.desc_settingsui(mock_widget)

        mock_widget.setText.assert_called_once_with('Not available - dbus-fast package required.')


def test_desc_settingsui_with_dbus():
    """Test settings UI description with D-Bus"""
    with patch('nowplaying.inputs.mpris2.DBUS_STATUS', True):
        plugin = nowplaying.inputs.mpris2.Plugin()  # pylint: disable=no-member
        mock_widget = MagicMock()

        plugin.desc_settingsui(mock_widget)

        expected_text = ('This plugin provides support for MPRIS2 '
                         'compatible software on Linux and other DBus systems. '
                         'Now using dbus-fast for better performance.')
        mock_widget.setText.assert_called_once_with(expected_text)


@pytest.mark.asyncio
async def test_main_no_dbus_fast():
    """Test main function without dbus-fast"""
    with patch('nowplaying.inputs.mpris2.DBUS_STATUS', False):
        with patch('sys.exit') as mock_exit:
            await nowplaying.inputs.mpris2.main()  # pylint: disable=no-member
            mock_exit.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_plugin_cleanup():
    """Test plugin cleanup method"""
    with patch('nowplaying.inputs.mpris2.DBUS_STATUS', True):
        plugin = nowplaying.inputs.mpris2.Plugin()  # pylint: disable=no-member
        plugin.mpris2.bus = MagicMock()

        await plugin.cleanup()

        plugin.mpris2.bus.disconnect.assert_called_once()


@pytest.mark.skipif(not DBUS_FAST_AVAILABLE, reason="dbus-fast not available")
@pytest.mark.asyncio
async def test_getplayingtrack_with_vlc_metadata(getroot):
    """Test getplayingtrack with real VLC metadata containing D-Bus variants"""

    with patch('nowplaying.inputs.mpris2.DBUS_STATUS', True):
        handler = nowplaying.inputs.mpris2.MPRIS2Handler(service="vlc")  # pylint: disable=no-member

        # Mock the bus and introspection
        mock_bus = MagicMock()
        mock_props_obj = MagicMock()
        mock_properties = MagicMock()

        handler.bus = mock_bus
        handler.introspection = MagicMock()

        mock_bus.get_proxy_object.return_value = mock_props_obj
        mock_props_obj.get_interface.return_value = mock_properties

        # Get actual path to test file
        test_file_path = os.path.join(getroot, 'tests', 'audio',
                                      '15_Ghosts_II_64kb_füllytâgged.m4a')

        # Real VLC D-Bus response with variants using actual test file path
        vlc_response = {
            'Metadata':
            Variant(
                'a{sv}',
                {
                    'mpris:trackid':
                    Variant('o', '/org/videolan/vlc/playlist/15'),
                    'xesam:url':
                    Variant('s', f'file://{test_file_path}'),
                    'xesam:title':
                    Variant('s', '15 Ghosts II'),
                    'xesam:artist':
                    Variant('as', ['Nine Inch Nails']),
                    'xesam:album':
                    Variant('s', 'Ghosts I-IV'),
                    'xesam:tracknumber':
                    Variant('s', '15'),
                    'vlc:time':
                    Variant('u', 113),
                    'mpris:length':
                    Variant('x', 113000000),  # 113 seconds in microseconds
                    'xesam:contentCreated':
                    Variant('s', '2008'),
                    'mpris:artUrl':
                    Variant(
                        's',
                        'file:///tmp/.cache/vlc/art/artistalbum/Nine%20Inch%20Nails/Ghosts%20I-IV/art'  #pylint: disable=line-too-long
                    ),
                    'vlc:encodedby':
                    Variant('s', 'Lavf61.1.100'),
                    'vlc:length':
                    Variant('x', 113000),
                    'vlc:publisher':
                    Variant('i', 1)
                }),
            'Position':
            Variant('x', 45000000),  # 45 seconds into the track
            'PlaybackStatus':
            Variant('s', 'Playing')
        }

        mock_properties.call_get_all = AsyncMock(return_value=vlc_response)

        # Test the method
        result = await handler.getplayingtrack()

        # Verify extracted data
        assert result['artist'] == 'Nine Inch Nails'
        assert result['title'] == '15 Ghosts II'
        assert result['album'] == 'Ghosts I-IV'
        assert result.get('track') == 15  # Use .get() in case parsing fails
        assert result['duration'] == 113  # 113000000 microseconds / 1000000
        assert result['filename'] == test_file_path


@pytest.mark.skipif(not DBUS_FAST_AVAILABLE, reason="dbus-fast not available")
@pytest.mark.asyncio
async def test_getplayingtrack_multiple_artists():
    """Test getplayingtrack with multiple artists"""
    with patch('nowplaying.inputs.mpris2.DBUS_STATUS', True):
        handler = nowplaying.inputs.mpris2.MPRIS2Handler(service="vlc")  # pylint: disable=no-member

        # Mock the bus and introspection
        mock_bus = MagicMock()
        mock_props_obj = MagicMock()
        mock_properties = MagicMock()

        handler.bus = mock_bus
        handler.introspection = MagicMock()

        mock_bus.get_proxy_object.return_value = mock_props_obj
        mock_props_obj.get_interface.return_value = mock_properties

        # Mock response with multiple artists
        response = {
            'Metadata':
            Variant(
                'a{sv}', {
                    'xesam:title': Variant('s', 'Collaboration Song'),
                    'xesam:artist': Variant('as', ['Artist One', 'Artist Two', 'Artist Three']),
                    'mpris:length': Variant('x', 180000000)
                })
        }

        mock_properties.call_get_all = AsyncMock(return_value=response)

        result = await handler.getplayingtrack()

        # Verify multiple artists are joined with /
        assert result['artist'] == 'Artist One/Artist Two/Artist Three'
        assert result['title'] == 'Collaboration Song'
        assert result['duration'] == 180
