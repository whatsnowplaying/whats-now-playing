#!/usr/bin/env python3
"""test the remote notification plugin"""

from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from aioresponses import aioresponses

import nowplaying.notifications.remote


@pytest_asyncio.fixture
async def remote_plugin(bootstrap):  # pylint: disable=redefined-outer-name
    """bootstrap a remote notification plugin"""
    config = bootstrap
    plugin = nowplaying.notifications.remote.Plugin(config=config)
    await plugin.start()
    try:
        yield plugin
    finally:
        await plugin.stop()


@pytest.mark.asyncio
async def test_remote_plugin_disabled(remote_plugin):  # pylint: disable=redefined-outer-name
    """test remote plugin when disabled"""
    remote_plugin.config.cparser.setValue("remote/enabled", False)
    await remote_plugin.start()

    metadata = {"artist": "Test Artist", "title": "Test Title", "filename": "test.mp3"}

    # Should do nothing when disabled
    await remote_plugin.notify_track_change(metadata)


@pytest.mark.asyncio
async def test_remote_plugin_no_secret(remote_plugin):  # pylint: disable=redefined-outer-name
    """test remote plugin without secret configured"""
    remote_plugin.config.cparser.setValue("remote/enabled", True)
    remote_plugin.config.cparser.setValue("remote/remote_server", "localhost")
    remote_plugin.config.cparser.setValue("remote/remote_port", 8899)
    remote_plugin.config.cparser.setValue("remote/remote_key", "")  # No secret
    await remote_plugin.start()

    metadata = {"artist": "Test Artist", "title": "Test Title", "filename": "test.mp3"}

    with aioresponses() as mock_resp:
        mock_resp.post("http://localhost:8899/v1/remoteinput", payload={"dbid": 123})

        await remote_plugin.notify_track_change(metadata)

        # Verify the request was made
        assert len(mock_resp.requests) == 1
        first_key = list(mock_resp.requests.keys())[0]
        request = mock_resp.requests[first_key][0]
        # Should not have secret in the payload
        assert "secret" not in request.kwargs["json"]


@pytest.mark.asyncio
async def test_remote_plugin_with_secret(remote_plugin):  # pylint: disable=redefined-outer-name
    """test remote plugin with secret configured"""
    remote_plugin.config.cparser.setValue("remote/enabled", True)
    remote_plugin.config.cparser.setValue("remote/remote_server", "localhost")
    remote_plugin.config.cparser.setValue("remote/remote_port", 8899)
    remote_plugin.config.cparser.setValue("remote/remote_key", "test_secret_123")
    await remote_plugin.start()

    metadata = {"artist": "Test Artist", "title": "Test Title", "filename": "test.mp3"}

    with aioresponses() as mock_resp:
        mock_resp.post("http://localhost:8899/v1/remoteinput", payload={"dbid": 456})

        await remote_plugin.notify_track_change(metadata)

        # Verify the request was made with secret
        assert len(mock_resp.requests) == 1
        first_key = list(mock_resp.requests.keys())[0]
        request = mock_resp.requests[first_key][0]
        assert request.kwargs["json"]["secret"] == "test_secret_123"  # pragma: allowlist secret


@pytest.mark.asyncio
async def test_remote_plugin_auth_failure(remote_plugin):  # pylint: disable=redefined-outer-name
    """test remote plugin with authentication failure"""
    remote_plugin.config.cparser.setValue("remote/enabled", True)
    remote_plugin.config.cparser.setValue("remote/remote_server", "localhost")
    remote_plugin.config.cparser.setValue("remote/remote_port", 8899)
    remote_plugin.config.cparser.setValue("remote/remote_key", "test_secret")
    await remote_plugin.start()

    metadata = {"artist": "Test Artist", "title": "Test Title"}

    with aioresponses() as mock_resp:
        mock_resp.post(
            "http://localhost:8899/v1/remoteinput", status=403, payload={"error": "Invalid secret"}
        )

        # Should handle auth failure gracefully
        await remote_plugin.notify_track_change(metadata)


@pytest.mark.asyncio
async def test_remote_plugin_server_error(remote_plugin):  # pylint: disable=redefined-outer-name
    """test remote plugin with server error"""
    remote_plugin.config.cparser.setValue("remote/enabled", True)
    remote_plugin.config.cparser.setValue("remote/remote_server", "localhost")
    remote_plugin.config.cparser.setValue("remote/remote_port", 8899)
    remote_plugin.config.cparser.setValue("remote/remote_key", "")
    await remote_plugin.start()

    metadata = {"artist": "Test Artist", "title": "Test Title"}

    with aioresponses() as mock_resp:
        mock_resp.post(
            "http://localhost:8899/v1/remoteinput",
            status=500,
            payload={"error": "Internal server error"},
        )

        # Should handle server error gracefully
        await remote_plugin.notify_track_change(metadata)


@pytest.mark.asyncio
async def test_remote_plugin_strips_blobs(remote_plugin):  # pylint: disable=redefined-outer-name
    """test that remote plugin strips binary blob data and local system data"""
    remote_plugin.config.cparser.setValue("remote/enabled", True)
    remote_plugin.config.cparser.setValue("remote/remote_server", "localhost")
    remote_plugin.config.cparser.setValue("remote/remote_port", 8899)
    await remote_plugin.start()

    metadata = {
        "artist": "Test Artist",
        "title": "Test Title",
        "coverimageraw": b"binary_image_data",  # Should be stripped
        "artistthumbnailraw": b"binary_thumb_data",  # Should be stripped
        "dbid": 999,  # Should be removed
        "httpport": 8080,  # Should be stripped
        "hostname": "local-system",  # Should be stripped
        "hostfqdn": "local-system.local",  # Should be stripped
        "hostip": "192.168.1.100",  # Should be stripped
        "ipaddress": "192.168.1.100",  # Should be stripped
        "previoustrack": [{"artist": "Previous", "title": "Track"}],  # Should be stripped
        "cache_warmed": True,  # Should be stripped
        "twitchchannel": "teststreamer",  # Should be kept
        "kickchannel": "kickstreamer",  # Should be kept
        "discordguild": "My Discord Server",  # Should be kept
    }

    with aioresponses() as mock_resp:
        mock_resp.post("http://localhost:8899/v1/remoteinput", payload={"dbid": 123})

        await remote_plugin.notify_track_change(metadata)

        # Verify blob data and local system data was stripped
        first_key = list(mock_resp.requests.keys())[0]
        request = mock_resp.requests[first_key][0]
        payload = request.kwargs["json"]

        # Binary blob fields should be stripped
        assert "coverimageraw" not in payload
        assert "artistthumbnailraw" not in payload

        # Local system fields should be stripped
        assert "dbid" not in payload
        assert "httpport" not in payload
        assert "hostname" not in payload
        assert "hostfqdn" not in payload
        assert "hostip" not in payload
        assert "ipaddress" not in payload
        assert "previoustrack" not in payload
        assert "cache_warmed" not in payload

        # Track data should remain
        assert payload["artist"] == "Test Artist"
        assert payload["title"] == "Test Title"

        # Streaming channel data should be kept (not stripped)
        assert payload["twitchchannel"] == "teststreamer"
        assert payload["kickchannel"] == "kickstreamer"
        assert payload["discordguild"] == "My Discord Server"


def test_remote_plugin_strip_blobs_static():
    """test the static _strip_blobs_metadata method"""
    metadata = {
        "artist": "Test Artist",
        "title": "Test Title",
        "coverimageraw": b"binary_data",
        "artistlogoraw": b"more_binary_data",
        "dbid": 123,
        "some_bytes": b"random_bytes",
    }

    result = nowplaying.notifications.remote.Plugin._strip_blobs_metadata(metadata)  # pylint: disable=protected-access

    # Should keep regular metadata
    assert result["artist"] == "Test Artist"
    assert result["title"] == "Test Title"

    # Should remove blob fields and bytes
    assert "coverimageraw" not in result
    assert "artistlogoraw" not in result
    assert "dbid" not in result
    assert "some_bytes" not in result


# Settings UI and auto-discovery tests


@pytest.fixture
def remote_notification_bootstrap(bootstrap):
    """bootstrap test for remote notification plugin settings"""
    config = bootstrap
    config.cparser.setValue("remote/enabled", False)
    config.cparser.setValue("remote/autodiscover", False)
    config.cparser.setValue("remote/remote_server", "testhost")
    config.cparser.setValue("remote/remote_port", 8899)
    config.cparser.setValue("remote/remote_key", "testkey")
    config.cparser.sync()
    yield config


@pytest.mark.asyncio
async def test_remote_notification_init(remote_notification_bootstrap):  # pylint: disable=redefined-outer-name
    """test remote notification plugin initialization"""
    config = remote_notification_bootstrap
    plugin = nowplaying.notifications.remote.Plugin(config=config)

    assert plugin.displayname == "Remote Output"
    assert plugin.enabled is False
    assert plugin.server == "remotehost"
    assert plugin.port == 8899
    assert plugin.key is None


@pytest.mark.asyncio
async def test_remote_notification_start_manual_config(remote_notification_bootstrap):  # pylint: disable=redefined-outer-name
    """test start method with manual configuration"""
    config = remote_notification_bootstrap
    config.cparser.setValue("remote/enabled", True)
    config.cparser.setValue("remote/autodiscover", False)
    config.cparser.setValue("remote/remote_server", "manual.host")
    config.cparser.setValue("remote/remote_port", 9000)

    plugin = nowplaying.notifications.remote.Plugin(config=config)
    await plugin.start()

    assert plugin.enabled is True
    assert plugin.server == "manual.host"
    assert plugin.port == 9000


@pytest.mark.asyncio
async def test_remote_notification_start_autodiscover_found(remote_notification_bootstrap):  # pylint: disable=redefined-outer-name
    """test start method with autodiscover when service is found"""
    config = remote_notification_bootstrap
    config.cparser.setValue("remote/enabled", True)
    config.cparser.setValue("remote/autodiscover", True)

    plugin = nowplaying.notifications.remote.Plugin(config=config)

    mock_service = MagicMock()
    mock_service.addresses = ["192.168.1.100"]
    mock_service.host = "discovered.local."
    mock_service.port = 8899

    async def mock_async_discover():
        return mock_service

    with patch(
        "nowplaying.mdns_discovery.get_first_whatsnowplaying_service_async",
        side_effect=mock_async_discover,
    ):
        await plugin.start()

        assert plugin.enabled is True
        assert plugin.server == "192.168.1.100"
        assert plugin.port == 8899


@pytest.mark.asyncio
async def test_remote_notification_start_autodiscover_not_found(remote_notification_bootstrap):  # pylint: disable=redefined-outer-name
    """test start method with autodiscover when no service is found"""
    config = remote_notification_bootstrap
    config.cparser.setValue("remote/enabled", True)
    config.cparser.setValue("remote/autodiscover", True)

    plugin = nowplaying.notifications.remote.Plugin(config=config)

    async def mock_async_discover():
        return None

    with patch(
        "nowplaying.mdns_discovery.get_first_whatsnowplaying_service_async",
        side_effect=mock_async_discover,
    ):
        await plugin.start()

        # Should disable plugin when autodiscover fails
        assert plugin.enabled is False


@pytest.mark.asyncio
async def test_remote_notification_start_autodiscover_fallback_to_host(
    remote_notification_bootstrap,
):  # pylint: disable=redefined-outer-name
    """test start method autodiscover uses hostname when no addresses"""
    config = remote_notification_bootstrap
    config.cparser.setValue("remote/enabled", True)
    config.cparser.setValue("remote/autodiscover", True)

    plugin = nowplaying.notifications.remote.Plugin(config=config)

    mock_service = MagicMock()
    mock_service.addresses = []
    mock_service.host = "fallback.local."
    mock_service.port = 8899

    async def mock_async_discover():
        return mock_service

    with patch(
        "nowplaying.mdns_discovery.get_first_whatsnowplaying_service_async",
        side_effect=mock_async_discover,
    ):
        await plugin.start()

        assert plugin.enabled is True
        assert plugin.server == "fallback.local."
        assert plugin.port == 8899


@pytest.mark.asyncio
async def test_remote_notification_defaults():
    """test defaults method"""
    plugin = nowplaying.notifications.remote.Plugin()

    mock_qsettings = MagicMock()
    plugin.defaults(mock_qsettings)

    mock_qsettings.setValue.assert_any_call("remote/enabled", False)
    mock_qsettings.setValue.assert_any_call("remote/autodiscover", False)
    mock_qsettings.setValue.assert_any_call("remote/remote_server", "remotehost")
    mock_qsettings.setValue.assert_any_call("remote/remote_port", 8899)
    mock_qsettings.setValue.assert_any_call("remote/remote_key", "")


@pytest.mark.asyncio
async def test_remote_notification_load_settingsui(remote_notification_bootstrap):  # pylint: disable=redefined-outer-name
    """test load_settingsui method"""
    config = remote_notification_bootstrap
    config.cparser.setValue("remote/enabled", True)
    config.cparser.setValue("remote/autodiscover", True)
    config.cparser.setValue("remote/remote_server", "testhost")
    config.cparser.setValue("remote/remote_port", 8899)
    config.cparser.setValue("remote/remote_key", "secret")

    plugin = nowplaying.notifications.remote.Plugin(config=config)

    mock_qwidget = MagicMock()
    mock_qwidget.enable_checkbox = MagicMock()
    mock_qwidget.autodiscover_checkbox = MagicMock()
    mock_qwidget.server_lineedit = MagicMock()
    mock_qwidget.port_lineedit = MagicMock()
    mock_qwidget.secret_lineedit = MagicMock()

    plugin.load_settingsui(mock_qwidget)

    mock_qwidget.enable_checkbox.setChecked.assert_called_once_with(True)
    mock_qwidget.autodiscover_checkbox.setChecked.assert_called_once_with(True)
    mock_qwidget.server_lineedit.setText.assert_called_once_with("testhost")
    mock_qwidget.port_lineedit.setText.assert_called_once_with("8899")
    mock_qwidget.secret_lineedit.setText.assert_called_once_with("secret")
    # Verify signal connection is set up
    mock_qwidget.autodiscover_checkbox.stateChanged.connect.assert_called_once()


@pytest.mark.asyncio
async def test_remote_notification_save_settingsui(remote_notification_bootstrap):  # pylint: disable=redefined-outer-name
    """test save_settingsui method"""
    config = remote_notification_bootstrap
    plugin = nowplaying.notifications.remote.Plugin(config=config)

    mock_qwidget = MagicMock()
    mock_qwidget.enable_checkbox.isChecked.return_value = True
    mock_qwidget.autodiscover_checkbox.isChecked.return_value = True
    mock_qwidget.server_lineedit.text.return_value = "newhost"
    mock_qwidget.port_lineedit.text.return_value = "9000"
    mock_qwidget.secret_lineedit.text.return_value = "newsecret"

    plugin.save_settingsui(mock_qwidget)

    assert config.cparser.value("remote/enabled", type=bool) is True
    assert config.cparser.value("remote/autodiscover", type=bool) is True
    assert config.cparser.value("remote/remote_server") == "newhost"
    assert config.cparser.value("remote/remote_port", type=int) == 9000
    assert config.cparser.value("remote/remote_key") == "newsecret"


@pytest.mark.asyncio
async def test_remote_notification_update_field_states():
    """test _update_field_states method"""
    plugin = nowplaying.notifications.remote.Plugin()

    mock_qwidget = MagicMock()
    mock_qwidget.autodiscover_checkbox.isChecked.return_value = True
    mock_qwidget.server_lineedit = MagicMock()
    mock_qwidget.port_lineedit = MagicMock()

    plugin._update_field_states(mock_qwidget)  # pylint: disable=protected-access

    # Fields should be disabled when autodiscover is checked
    mock_qwidget.server_lineedit.setEnabled.assert_called_once_with(False)
    mock_qwidget.port_lineedit.setEnabled.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_remote_notification_verify_settingsui_autodiscover():
    """test verify_settingsui with autodiscover enabled"""
    plugin = nowplaying.notifications.remote.Plugin()

    mock_qwidget = MagicMock()
    mock_qwidget.enable_checkbox.isChecked.return_value = True
    mock_qwidget.autodiscover_checkbox.isChecked.return_value = True

    # Should pass validation even with empty server/port
    mock_qwidget.server_lineedit.text.return_value = ""
    result = plugin.verify_settingsui(mock_qwidget)

    assert result is True


@pytest.mark.asyncio
async def test_remote_notification_verify_settingsui_manual_valid():
    """test verify_settingsui with manual config and valid settings"""
    plugin = nowplaying.notifications.remote.Plugin()

    mock_qwidget = MagicMock()
    mock_qwidget.enable_checkbox.isChecked.return_value = True
    mock_qwidget.autodiscover_checkbox.isChecked.return_value = False
    mock_qwidget.server_lineedit.text.return_value = "testhost"
    mock_qwidget.port_lineedit.text.return_value = "8899"

    result = plugin.verify_settingsui(mock_qwidget)

    assert result is True


@pytest.mark.asyncio
async def test_remote_notification_verify_settingsui_manual_invalid_server():
    """test verify_settingsui with manual config and empty server"""
    plugin = nowplaying.notifications.remote.Plugin()

    mock_qwidget = MagicMock()
    mock_qwidget.enable_checkbox.isChecked.return_value = True
    mock_qwidget.autodiscover_checkbox.isChecked.return_value = False
    mock_qwidget.server_lineedit.text.return_value = ""

    with pytest.raises(Exception) as exc_info:
        plugin.verify_settingsui(mock_qwidget)

    assert "Remote server address is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_remote_notification_verify_settingsui_manual_invalid_port():
    """test verify_settingsui with manual config and non-numeric port"""
    plugin = nowplaying.notifications.remote.Plugin()

    mock_qwidget = MagicMock()
    mock_qwidget.enable_checkbox.isChecked.return_value = True
    mock_qwidget.autodiscover_checkbox.isChecked.return_value = False
    mock_qwidget.server_lineedit.text.return_value = "testhost"
    mock_qwidget.port_lineedit.text.return_value = "invalid"

    with pytest.raises(Exception) as exc_info:
        plugin.verify_settingsui(mock_qwidget)

    assert "port must be a valid number" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("port_value", ["0", "65536", "-1", "100000"])
async def test_remote_notification_verify_settingsui_manual_port_out_of_range(port_value):
    """test verify_settingsui with manual config and out-of-range port"""
    plugin = nowplaying.notifications.remote.Plugin()

    mock_qwidget = MagicMock()
    mock_qwidget.enable_checkbox.isChecked.return_value = True
    mock_qwidget.autodiscover_checkbox.isChecked.return_value = False
    mock_qwidget.server_lineedit.text.return_value = "testhost"
    mock_qwidget.port_lineedit.text.return_value = port_value

    with pytest.raises(Exception) as exc_info:
        plugin.verify_settingsui(mock_qwidget)

    assert "Remote port must be between 1 and 65535" in str(exc_info.value)
