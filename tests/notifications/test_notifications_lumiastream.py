#!/usr/bin/env python3
"""Tests for Lumia Stream notification plugin"""

import logging

import aiohttp
import pytest
import pytest_asyncio
from aioresponses import aioresponses

import nowplaying.notifications.lumiastream


@pytest_asyncio.fixture
async def lumia_plugin(bootstrap):  # pylint: disable=redefined-outer-name
    """bootstrap a lumia stream notification plugin"""
    plugin = nowplaying.notifications.lumiastream.Plugin(config=bootstrap)
    await plugin.start()
    try:
        yield plugin
    finally:
        await plugin.stop()


@pytest.mark.asyncio
async def test_lumia_disabled_skips_request(lumia_plugin):  # pylint: disable=redefined-outer-name
    """plugin does nothing when disabled"""
    lumia_plugin.config.cparser.setValue("lumiastream/enabled", False)
    lumia_plugin.config.cparser.setValue("lumiastream/token", "sometoken")
    await lumia_plugin.start()

    with aioresponses() as mock_resp:
        await lumia_plugin.notify_track_change({"artist": "WNP Mock Artist", "title": "Test"})
        assert len(mock_resp.requests) == 0


@pytest.mark.asyncio
async def test_lumia_no_token_skips_request(lumia_plugin):  # pylint: disable=redefined-outer-name
    """plugin does nothing when enabled but token is missing"""
    lumia_plugin.config.cparser.setValue("lumiastream/enabled", True)
    lumia_plugin.config.cparser.setValue("lumiastream/token", "")
    await lumia_plugin.start()

    with aioresponses() as mock_resp:
        await lumia_plugin.notify_track_change({"artist": "WNP Mock Artist", "title": "Test"})
        assert len(mock_resp.requests) == 0


@pytest.mark.asyncio
async def test_lumia_sends_on_track_change(lumia_plugin):  # pylint: disable=redefined-outer-name
    """plugin POSTs alert payload when enabled with token"""
    lumia_plugin.config.cparser.setValue("lumiastream/enabled", True)
    lumia_plugin.config.cparser.setValue("lumiastream/token", "testtoken123")
    lumia_plugin.config.cparser.setValue("lumiastream/port", 39231)
    await lumia_plugin.start()

    metadata = {
        "artist": "WNP Mock Artist",
        "title": "Mock Track",
        "album": "Mock Album",
        "httpport": 8899,
    }

    with aioresponses() as mock_resp:
        mock_resp.post("http://localhost:39231/api/send?token=testtoken123", status=200)
        await lumia_plugin.notify_track_change(metadata)
        assert len(mock_resp.requests) == 1


def test_lumia_payload_fields():
    """payload contains all expected Lumia extraSettings fields"""
    metadata = {
        "artist": "WNP Mock Artist",
        "title": "Mock Track",
        "album": "Mock Album",
        "label": "Mock Label",
        "bpm": "128",
        "key": "Am",
        "comments": "test comment",
        "duration": 210,
        "isrc": ["USABC1234567"],
        "httpport": 8899,
    }

    payload = nowplaying.notifications.lumiastream.Plugin.build_payload(metadata)

    assert payload["type"] == "alert"
    assert payload["params"]["value"] == "nowplaying-switchSong"
    extra = payload["params"]["extraSettings"]
    assert extra["title"] == "Mock Track"
    assert extra["artist"] == "WNP Mock Artist"
    assert extra["album"] == "Mock Album"
    assert extra["label"] == "Mock Label"
    assert extra["bpm"] == "128"
    assert extra["key"] == "Am"
    assert extra["comment"] == "test comment"
    assert extra["length"] == "210"
    assert extra["id"] == "USABC1234567"
    assert extra["image"] == "http://localhost:8899/cover.png"


def test_lumia_payload_no_httpport():
    """image field is empty when httpport is absent"""
    metadata = {"artist": "WNP Mock Artist", "title": "Mock Track"}
    payload = nowplaying.notifications.lumiastream.Plugin.build_payload(metadata)
    assert payload["params"]["extraSettings"]["image"] == ""


def test_lumia_payload_no_isrc():
    """id field is empty when isrc is absent"""
    metadata = {"artist": "WNP Mock Artist", "title": "Mock Track"}
    payload = nowplaying.notifications.lumiastream.Plugin.build_payload(metadata)
    assert payload["params"]["extraSettings"]["id"] == ""


@pytest.mark.asyncio
async def test_lumia_client_error_logged(
    lumia_plugin,  # pylint: disable=redefined-outer-name
    caplog,
):
    """aiohttp.ClientError is caught and logged, not raised"""
    lumia_plugin.config.cparser.setValue("lumiastream/enabled", True)
    lumia_plugin.config.cparser.setValue("lumiastream/token", "testtoken123")
    lumia_plugin.config.cparser.setValue("lumiastream/port", 39231)
    await lumia_plugin.start()

    metadata = {"artist": "WNP Mock Artist", "title": "Mock Track"}

    with aioresponses() as mock_resp:
        mock_resp.post(
            "http://localhost:39231/api/send?token=testtoken123",
            exception=aiohttp.ClientConnectionError("connection refused"),
        )
        with caplog.at_level(logging.ERROR):
            await lumia_plugin.notify_track_change(metadata)

        assert any("Failed to connect to Lumia Stream" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_lumia_generic_error_logged(
    lumia_plugin,  # pylint: disable=redefined-outer-name
    caplog,
):
    """unexpected non-aiohttp errors are caught and logged, not raised"""
    lumia_plugin.config.cparser.setValue("lumiastream/enabled", True)
    lumia_plugin.config.cparser.setValue("lumiastream/token", "testtoken123")
    lumia_plugin.config.cparser.setValue("lumiastream/port", 39231)
    await lumia_plugin.start()

    metadata = {"artist": "WNP Mock Artist", "title": "Mock Track"}

    with aioresponses() as mock_resp:
        mock_resp.post(
            "http://localhost:39231/api/send?token=testtoken123",
            exception=ValueError("unexpected"),
        )
        with caplog.at_level(logging.ERROR):
            await lumia_plugin.notify_track_change(metadata)

        assert any("Unexpected error" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_lumia_non_200_logged(
    lumia_plugin,  # pylint: disable=redefined-outer-name
    caplog,
):
    """non-200 HTTP responses are logged"""
    lumia_plugin.config.cparser.setValue("lumiastream/enabled", True)
    lumia_plugin.config.cparser.setValue("lumiastream/token", "testtoken123")
    lumia_plugin.config.cparser.setValue("lumiastream/port", 39231)
    await lumia_plugin.start()

    metadata = {"artist": "WNP Mock Artist", "title": "Mock Track"}

    with aioresponses() as mock_resp:
        mock_resp.post(
            "http://localhost:39231/api/send?token=testtoken123",
            status=401,
            body="Unauthorized",
        )
        with caplog.at_level(logging.ERROR):
            await lumia_plugin.notify_track_change(metadata)

        assert any("401" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_lumia_defaults(bootstrap):
    """defaults() sets expected QSettings keys"""
    plugin = nowplaying.notifications.lumiastream.Plugin(config=bootstrap)
    plugin.defaults(bootstrap.cparser)

    assert bootstrap.cparser.value("lumiastream/enabled", type=bool) is False
    assert bootstrap.cparser.value("lumiastream/token", defaultValue="") == ""
    assert bootstrap.cparser.value("lumiastream/port", type=int) == 39231
