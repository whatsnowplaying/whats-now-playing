#!/usr/bin/env python3
"""Tests for charts notification plugin"""

import json
import pathlib
import tempfile

import pytest

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.notifications.charts

nowplaying.bootstrap.set_qt_names(appname="testsuite")


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


@pytest.mark.asyncio
async def test_charts_plugin_disabled(bootstrap):
    """Test that charts plugin can be disabled"""
    config = nowplaying.config.ConfigFile(bundledir=bootstrap, testmode=True)
    config.cparser.setValue("charts/enabled", False)

    plugin = nowplaying.notifications.charts.Plugin(config=config)
    await plugin.start()

    assert plugin.enabled is False
