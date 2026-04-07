#!/usr/bin/env python3
"""Tests for charts notification plugin"""

import json
import pathlib
import tempfile

import pytest

import nowplaying.config
import nowplaying.notifications.charts


@pytest.mark.asyncio
async def test_charts_plugin_start_no_deadlock(bootstrap):
    """Test that charts plugin start() method doesn't deadlock on lock acquisition"""
    config = nowplaying.config.ConfigFile(bundledir=bootstrap, testmode=True)

    # Enable charts plugin
    config.cparser.setValue("charts/enabled", True)
    config.cparser.setValue("charts/charts_key", "test_key_12345")

    plugin = nowplaying.notifications.charts.Plugin(config=config)

    # This should not deadlock (previously would hang forever)
    # If there's a deadlock, pytest will timeout
    await plugin.start()

    assert plugin.enabled is True
    assert plugin.key == "test_key_12345"


@pytest.mark.asyncio
async def test_charts_plugin_load_queue_with_lock(bootstrap):
    """Test that _load_queue works correctly when called with lock held"""
    config = nowplaying.config.ConfigFile(bundledir=bootstrap, testmode=True)
    config.cparser.setValue("charts/enabled", True)
    config.cparser.setValue("charts/charts_key", "test_key")

    plugin = nowplaying.notifications.charts.Plugin(config=config)

    # Set up queue file in temp location
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_file = pathlib.Path(tmpdir) / "charts_queue.json"
        plugin.queue_file = queue_file

        # Create a sample queue file
        sample_queue = [
            {"artist": "Test Artist", "title": "Test Song"},
            {"artist": "Another Artist", "title": "Another Song"},
        ]
        with open(queue_file, "w", encoding="utf-8") as file_handle:
            json.dump(sample_queue, file_handle)

        # Load queue with lock held (simulating what start() does)
        async with plugin._get_queue_lock():  # pylint: disable=protected-access
            await plugin._load_queue()  # pylint: disable=protected-access

        assert len(plugin.queue) == 2
        assert plugin.queue[0]["artist"] == "Test Artist"


@pytest.mark.parametrize(
    "input_data,expected_source_agent,expect_flat_removed",
    [
        (
            {
                "artist": "Test",
                "title": "Track",
                "source_agent_name": "WNPListener",
                "source_agent_version": "1.2.3",
            },
            {"name": "WNPListener", "version": "1.2.3"},
            True,
        ),
        (
            {"artist": "Test", "title": "Track", "source_agent_name": "WNPListener"},
            {"name": "WNPListener", "version": None},
            True,
        ),
        (
            {"artist": "Test", "title": "Track", "source_agent_version": "1.2.3"},
            {"name": None, "version": "1.2.3"},
            True,
        ),
        (
            {"artist": "Test", "title": "Track"},
            None,
            False,
        ),
    ],
)
def test_build_source_agent(input_data, expected_source_agent, expect_flat_removed):
    """Test that flat source_agent fields are replaced with nested structure"""
    result = nowplaying.notifications.charts.Plugin._build_source_agent(input_data)  # pylint: disable=protected-access

    if expected_source_agent is None:
        assert "source_agent" not in result
    else:
        assert result["source_agent"] == expected_source_agent

    if expect_flat_removed:
        assert "source_agent_name" not in result
        assert "source_agent_version" not in result


def test_build_source_agent_preserves_other_fields():
    """Test that _build_source_agent does not disturb unrelated fields"""
    input_data = {
        "artist": "Aphex Twin",
        "title": "Windowlicker",
        "album": "Windowlicker EP",
        "source_agent_name": "WNPListener",
        "source_agent_version": "2.0.0",
    }
    result = nowplaying.notifications.charts.Plugin._build_source_agent(input_data)  # pylint: disable=protected-access
    assert result["artist"] == "Aphex Twin"
    assert result["title"] == "Windowlicker"
    assert result["album"] == "Windowlicker EP"


def test_strip_blobs_passes_source_agent_fields():
    """Test that _strip_blobs_metadata does not remove source_agent fields"""
    input_data = {
        "artist": "Test",
        "title": "Track",
        "source_agent_name": "WNPListener",
        "source_agent_version": "1.0.0",
        "coverimageraw": b"binarydata",
        "hostname": "myhost",
    }
    result = nowplaying.notifications.charts.Plugin._strip_blobs_metadata(input_data)  # pylint: disable=protected-access
    assert result["source_agent_name"] == "WNPListener"
    assert result["source_agent_version"] == "1.0.0"
    assert "coverimageraw" not in result
    assert "hostname" not in result


def test_strip_then_build_source_agent():
    """Test the full pipeline: strip blobs then build source_agent structure"""
    input_data = {
        "artist": "Burial",
        "title": "Archangel",
        "source_agent_name": "WNPListener",
        "source_agent_version": "3.1.0",
        "coverimageraw": b"binarydata",
        "hostname": "myhost",
        "filename": "/local/path/track.mp3",
    }
    stripped = nowplaying.notifications.charts.Plugin._strip_blobs_metadata(input_data)  # pylint: disable=protected-access
    result = nowplaying.notifications.charts.Plugin._build_source_agent(stripped)  # pylint: disable=protected-access

    assert result["source_agent"] == {"name": "WNPListener", "version": "3.1.0"}
    assert "source_agent_name" not in result
    assert "source_agent_version" not in result
    assert "coverimageraw" not in result
    assert "hostname" not in result
    assert "filename" not in result
    assert result["artist"] == "Burial"
    assert result["title"] == "Archangel"


@pytest.mark.asyncio
async def test_charts_plugin_disabled(bootstrap):
    """Test that charts plugin can be disabled"""
    config = nowplaying.config.ConfigFile(bundledir=bootstrap, testmode=True)
    config.cparser.setValue("charts/enabled", False)

    plugin = nowplaying.notifications.charts.Plugin(config=config)
    await plugin.start()

    assert plugin.enabled is False


@pytest.mark.asyncio
async def test_charts_skips_when_remote_charts_submitted(bootstrap):
    """Test that charts plugin skips submission when remote client already submitted"""
    config = nowplaying.config.ConfigFile(bundledir=bootstrap, testmode=True)
    config.cparser.setValue("charts/enabled", True)
    config.cparser.setValue("charts/charts_key", "test_key_abc123")

    plugin = nowplaying.notifications.charts.Plugin(config=config)
    await plugin.start()

    metadata = {
        "artist": "Test Artist",
        "title": "Test Title",
        "remote_charts_submitted": True,
    }

    await plugin.notify_track_change(metadata)

    # Queue should be empty — submission was skipped
    assert len(plugin.queue) == 0
