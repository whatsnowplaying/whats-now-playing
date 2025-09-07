#!/usr/bin/env python3
# pylint: disable=redefined-outer-name,broad-exception-caught,protected-access
"""
Tests for Serato (SQLite-based) has_tracks_by_artist functionality.

Note: The SQLite-based Serato plugin does not implement has_tracks_by_artist
as it only handles currently playing tracks from the history_entry table,
not the full library database.
"""

import pytest

import nowplaying.config
import nowplaying.inputs
import nowplaying.inputs.serato


@pytest.mark.asyncio
async def test_has_tracks_by_artist_not_implemented():
    """Test that has_tracks_by_artist returns False (not implemented for SQLite plugin)"""
    config = nowplaying.config.ConfigFile()
    plugin = nowplaying.inputs.serato.Plugin(config=config)

    # SQLite plugin doesn't implement artist search - returns False
    result = await plugin.has_tracks_by_artist("Any Artist")
    assert result is False


@pytest.mark.asyncio
async def test_has_tracks_by_artist_base_implementation():
    """Test that the plugin uses the base InputPlugin implementation"""
    config = nowplaying.config.ConfigFile()
    plugin = nowplaying.inputs.serato.Plugin(config=config)

    # Verify it uses the base class implementation
    base_plugin = nowplaying.inputs.InputPlugin(config=config)

    # Both should return False (base implementation)
    assert await plugin.has_tracks_by_artist("Test") == await base_plugin.has_tracks_by_artist(
        "Test"
    )
    assert await plugin.has_tracks_by_artist("Test") is False
