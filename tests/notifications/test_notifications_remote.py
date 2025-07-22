#!/usr/bin/env python3
"""test the remote notification plugin"""

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
    """test that remote plugin strips binary blob data"""
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
    }

    with aioresponses() as mock_resp:
        mock_resp.post("http://localhost:8899/v1/remoteinput", payload={"dbid": 123})

        await remote_plugin.notify_track_change(metadata)

        # Verify blob data was stripped
        first_key = list(mock_resp.requests.keys())[0]
        request = mock_resp.requests[first_key][0]
        payload = request.kwargs["json"]
        assert "coverimageraw" not in payload
        assert "artistthumbnailraw" not in payload
        assert "dbid" not in payload
        assert payload["artist"] == "Test Artist"
        assert payload["title"] == "Test Title"


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
