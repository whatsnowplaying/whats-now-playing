#!/usr/bin/env python3
"""test icecast input plugin"""

# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import nowplaying.inputs.icecast


@pytest.fixture
def icecast_bootstrap(bootstrap):
    """bootstrap test"""
    config = bootstrap
    config.cparser.setValue("icecast/port", "8000")
    config.cparser.sync()
    yield config


@pytest.fixture
def icecast_plugin(icecast_bootstrap):
    """create an icecast plugin instance"""
    return nowplaying.inputs.icecast.Plugin(config=icecast_bootstrap)


def test_protocol_init():
    """test protocol initialization"""
    protocol = nowplaying.inputs.icecast.IcecastProtocol()
    assert not protocol.streaming
    assert protocol.previous_page == b""
    assert protocol.metadata_callback is None  # pylint: disable=no-member
    assert not protocol._current_metadata  # pylint: disable=protected-access,no-member


def test_protocol_init_with_callback():
    """test protocol initialization with callback"""
    callback = MagicMock()
    protocol = nowplaying.inputs.icecast.IcecastProtocol(metadata_callback=callback)  # pylint: disable=unexpected-keyword-arg
    assert protocol.metadata_callback == callback  # pylint: disable=no-member


def test_connection_made():
    """test connection establishment"""
    protocol = nowplaying.inputs.icecast.IcecastProtocol()
    transport = MagicMock()

    protocol.connection_made(transport)
    assert protocol.transport == transport


@pytest.mark.parametrize(
    "query_string,expected_artist,expected_title,test_description",
    [
        # Song field parsing tests
        ("song=Artist%20-%20Title", "Artist", "Title", 'song with proper " - " separator'),
        (
            "song=Artist%20-%20Song%20-%20Remix",
            "Artist",
            "Song - Remix",
            'song with multiple " - " separators',
        ),
        ("song=Just%20A%20Title", None, "Just A Title", "song without separator"),
        ("song=Artist-Title", None, "Artist-Title", "song with hyphen but no spaces"),
        (
            "song=Caf%C3%A9%20-%20R%C3%A9mix",  # codespell:ignore
            "Café",  # codespell:ignore
            "Rémix",  # codespell:ignore
            "song with URL-encoded special characters",
        ),
        # Separate field tests
        (
            "artist=Test%20Artist&title=Test%20Title",
            "Test Artist",
            "Test Title",
            "separate artist and title fields",
        ),
        # Edge cases
        ("song=", None, "", "empty song field"),
        ("song=%20%20%20", None, "", "whitespace-only song field"),
    ],
)
def test_query_parse_metadata(query_string, expected_artist, expected_title, test_description):  # pylint: disable=unused-argument
    """test various metadata parsing scenarios"""
    callback = MagicMock()
    protocol = nowplaying.inputs.icecast.IcecastProtocol(metadata_callback=callback)  # pylint: disable=unexpected-keyword-arg

    query_data = f"GET /admin/metadata?mode=updinfo&{query_string} HTTP/1.1".encode()
    protocol._query_parse(query_data)  # pylint: disable=protected-access

    callback.assert_called_once()
    metadata = callback.call_args[0][0]
    assert metadata.get("artist") == expected_artist
    assert metadata.get("title") == expected_title


@pytest.mark.parametrize(
    "test_data,should_log_warning,expected_warning_msg",
    [
        # Unicode decode errors
        (
            b"GET /admin/metadata?mode=updinfo&song=\xff\xfe HTTP/1.1",
            True,
            "Failed to decode icecast query data as UTF-8",
        ),
        # Invalid URL parsing
        (b"", True, None),  # Empty data - any warning message accepted
    ],
)
def test_query_parse_error_handling(test_data, should_log_warning, expected_warning_msg):
    """test error handling for malformed requests"""
    callback = MagicMock()
    protocol = nowplaying.inputs.icecast.IcecastProtocol(metadata_callback=callback)  # pylint: disable=unexpected-keyword-arg

    with patch("logging.warning") as mock_warning:
        protocol._query_parse(test_data)  # pylint: disable=protected-access

    # Should log warning and not call callback
    if should_log_warning:
        mock_warning.assert_called()
        if expected_warning_msg:
            mock_warning.assert_called_with(expected_warning_msg)
    callback.assert_not_called()


@pytest.mark.parametrize(
    "test_data,test_description",
    [
        (b"GET /other/path?mode=updinfo&song=Test HTTP/1.1", "wrong path"),
        (b"GET /admin/metadata?mode=other&song=Test HTTP/1.1", "wrong mode"),
    ],
)
def test_query_parse_ignored_requests(test_data, test_description):  # pylint: disable=unused-argument
    """test requests that should be ignored"""
    callback = MagicMock()
    protocol = nowplaying.inputs.icecast.IcecastProtocol(metadata_callback=callback)  # pylint: disable=unexpected-keyword-arg

    protocol._query_parse(test_data)  # pylint: disable=protected-access

    # Should not call callback for invalid requests
    callback.assert_not_called()


def test_multiple_metadata_updates():
    """test that multiple metadata updates work correctly"""
    callback = MagicMock()
    protocol = nowplaying.inputs.icecast.IcecastProtocol(metadata_callback=callback)  # pylint: disable=unexpected-keyword-arg

    # First update
    query_data1 = b"GET /admin/metadata?mode=updinfo&song=Artist1%20-%20Title1 HTTP/1.1"
    protocol._query_parse(query_data1)  # pylint: disable=protected-access

    # Second update
    query_data2 = b"GET /admin/metadata?mode=updinfo&song=Artist2%20-%20Title2 HTTP/1.1"
    protocol._query_parse(query_data2)  # pylint: disable=protected-access

    # Should have been called twice
    assert callback.call_count == 2

    # Check that each call had the correct metadata
    first_call_metadata = callback.call_args_list[0][0][0]
    second_call_metadata = callback.call_args_list[1][0][0]

    assert first_call_metadata["artist"] == "Artist1"
    assert first_call_metadata["title"] == "Title1"
    assert second_call_metadata["artist"] == "Artist2"
    assert second_call_metadata["title"] == "Title2"


def test_plugin_init(icecast_plugin):
    """test plugin initialization"""
    assert icecast_plugin.displayname == "Icecast"
    assert icecast_plugin.server is None
    assert icecast_plugin.mode is None
    assert not icecast_plugin.lastmetadata
    assert not icecast_plugin._current_metadata  # pylint: disable=protected-access,no-member


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata_input,expected_output",
    [
        (None, {}),  # No metadata
        (
            {"artist": "Test Artist", "title": "Test Title"},
            {"artist": "Test Artist", "title": "Test Title"},
        ),  # With metadata
    ],
)
async def test_getplayingtrack(icecast_plugin, metadata_input, expected_output):
    """test getplayingtrack with various metadata states"""
    if metadata_input:
        icecast_plugin._metadata_callback(metadata_input)  # pylint: disable=protected-access,no-member

    metadata = await icecast_plugin.getplayingtrack()
    assert metadata == expected_output


def test_metadata_callback(icecast_plugin):
    """test the metadata callback function"""
    test_metadata = {"artist": "Test Artist", "title": "Test Title"}
    icecast_plugin._metadata_callback(test_metadata)  # pylint: disable=protected-access,no-member

    assert icecast_plugin._current_metadata == test_metadata  # pylint: disable=protected-access,no-member


@pytest.mark.asyncio
async def test_start_port_success(icecast_bootstrap):
    """test successful port start"""
    config = icecast_bootstrap
    plugin = nowplaying.inputs.icecast.Plugin(config=config)

    mock_server = MagicMock()

    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        mock_loop.create_server = AsyncMock(return_value=mock_server)

        await plugin.start_port(8000)

        # Verify server was created with correct parameters
        mock_loop.create_server.assert_called_once()
        args = mock_loop.create_server.call_args[0]
        assert len(args) == 3  # protocol_factory, host, port
        assert args[1] == ""  # host
        assert args[2] == 8000  # port

        # Verify the protocol factory creates IcecastProtocol with callback
        protocol_factory = args[0]
        protocol = protocol_factory()
        assert isinstance(protocol, nowplaying.inputs.icecast.IcecastProtocol)
        assert protocol.metadata_callback == plugin._metadata_callback  # pylint: disable=no-member,protected-access,comparison-with-callable

        assert plugin.server == mock_server


@pytest.mark.asyncio
async def test_start_port_failure(icecast_bootstrap):
    """test port start failure handling"""
    config = icecast_bootstrap
    plugin = nowplaying.inputs.icecast.Plugin(config=config)

    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        mock_loop.create_server = AsyncMock(side_effect=OSError("Port already in use"))

        with patch("logging.error") as mock_error:
            await plugin.start_port(8000)

            # Verify error was logged
            mock_error.assert_called_with(
                "Failed to launch icecast: %s", mock_loop.create_server.side_effect
            )


@pytest.mark.asyncio
async def test_start_uses_config_port(icecast_bootstrap):
    """test that start method uses configured port"""
    config = icecast_bootstrap
    config.cparser.setValue("icecast/port", 9000)
    plugin = nowplaying.inputs.icecast.Plugin(config=config)

    with patch.object(plugin, "start_port", new_callable=AsyncMock) as mock_start_port:
        await plugin.start()
        mock_start_port.assert_called_once_with(9000)


@pytest.mark.asyncio
async def test_start_uses_default_port(icecast_bootstrap):
    """test that start method uses default port when not configured"""
    config = icecast_bootstrap
    plugin = nowplaying.inputs.icecast.Plugin(config=config)

    with patch.object(plugin, "start_port", new_callable=AsyncMock) as mock_start_port:
        await plugin.start()
        mock_start_port.assert_called_once_with(8000)  # Default port


@pytest.mark.asyncio
async def test_stop(icecast_bootstrap):
    """test stop method"""
    config = icecast_bootstrap
    plugin = nowplaying.inputs.icecast.Plugin(config=config)

    mock_server = MagicMock()
    plugin.server = mock_server

    await plugin.stop()

    mock_server.close.assert_called_once()


@pytest.mark.asyncio
async def test_getrandomtrack(icecast_bootstrap):
    """test getrandomtrack method"""
    config = icecast_bootstrap
    plugin = nowplaying.inputs.icecast.Plugin(config=config)

    result = await plugin.getrandomtrack("test_playlist")
    assert result is None


def test_protocol_data_received_streaming_state():
    """test data_received method transitions to streaming state"""
    protocol = nowplaying.inputs.icecast.IcecastProtocol()
    transport = MagicMock()
    protocol.connection_made(transport)

    # Initial non-streaming state
    assert not protocol.streaming

    # Send initial GET request
    protocol.data_received(b"GET /admin/metadata?mode=updinfo&song=Test HTTP/1.1")

    # Should now be streaming
    assert protocol.streaming
    transport.write.assert_called_with(b"HTTP/1.0 200 OK\r\n\r\n")


def test_defaults(icecast_bootstrap):
    """test default configuration values"""
    config = icecast_bootstrap
    plugin = nowplaying.inputs.icecast.Plugin(config=config)

    mock_qsettings = MagicMock()
    plugin.defaults(mock_qsettings)

    mock_qsettings.setValue.assert_called_with("icecast/port", "8000")


def test_load_settingsui(icecast_bootstrap):
    """test loading settings UI"""
    config = icecast_bootstrap
    config.cparser.setValue("icecast/port", "9000")
    plugin = nowplaying.inputs.icecast.Plugin(config=config)

    mock_widget = MagicMock()
    plugin.load_settingsui(mock_widget)

    mock_widget.port_lineedit.setText.assert_called_with("9000")


def test_save_settingsui(icecast_bootstrap):
    """test saving settings UI"""
    config = icecast_bootstrap
    plugin = nowplaying.inputs.icecast.Plugin(config=config)

    mock_widget = MagicMock()
    mock_widget.port_lineedit.text.return_value = "9001"

    plugin.save_settingsui(mock_widget)

    assert config.cparser.value("icecast/port") == "9001"


def test_desc_settingsui(icecast_bootstrap):
    """test description settings UI"""
    config = icecast_bootstrap
    plugin = nowplaying.inputs.icecast.Plugin(config=config)

    mock_widget = MagicMock()
    plugin.desc_settingsui(mock_widget)

    # Verify description was set
    mock_widget.setText.assert_called_once()
    description = mock_widget.setText.call_args[0][0]
    assert "Icecast" in description
    assert "MIXXX" in description


@pytest.mark.parametrize(
    "malformed_input,input_description",
    [
        (b"", "empty data"),
        (b"invalid data", "not a valid HTTP request"),
        (b"GET", "incomplete request"),
        (b"GET /admin/metadata?invalid", "invalid query"),
        (b"GET /admin/metadata?mode=updinfo&song=", "empty song field"),
        (b"\x00\x01\x02", "binary data"),
    ],
)
def test_no_crash_on_malformed_input(malformed_input, input_description):
    """test that malformed input doesn\'t crash the plugin"""
    callback = MagicMock()
    protocol = nowplaying.inputs.icecast.IcecastProtocol(metadata_callback=callback)  # pylint: disable=unexpected-keyword-arg

    try:
        protocol._query_parse(malformed_input)  # pylint: disable=protected-access
        # Should not crash - this is the main test
    except Exception as error:  # pylint: disable=broad-exception-caught
        pytest.fail(f"Plugin crashed on {input_description}: {error}")


def test_thread_safety_multiple_calls():
    """test that multiple rapid metadata updates don\'t cause issues"""
    plugin = nowplaying.inputs.icecast.Plugin()

    # Simulate rapid metadata updates
    for i in range(100):
        metadata = {"artist": f"Artist{i}", "title": f"Title{i}"}
        plugin._metadata_callback(metadata)  # pylint: disable=protected-access,no-member

    # Final metadata should be the last one
    final_metadata = plugin._current_metadata  # pylint: disable=protected-access,no-member
    assert final_metadata["artist"] == "Artist99"
    assert final_metadata["title"] == "Title99"
