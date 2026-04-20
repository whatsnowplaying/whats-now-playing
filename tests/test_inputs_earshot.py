#!/usr/bin/env python3
"""tests for the EarShot input plugin"""

import pytest  # pylint: disable=import-error

import nowplaying.inputs.earshot  # pylint: disable=import-error


@pytest.mark.parametrize(
    "metadata,should_return",
    [
        # EarShot source agents — should pass through
        ({"artist": "Artist", "title": "Track", "source_agent_name": "wnpearshot"}, True),
        ({"artist": "Artist", "title": "Track", "source_agent_name": "wnpearshot-1.0"}, True),
        ({"artist": "Artist", "title": "Track", "source_agent_name": "wnpearshot-2.3.1"}, True),
        # Non-EarShot source agents — should be filtered out
        ({"artist": "Artist", "title": "Track", "source_agent_name": "serato"}, False),
        ({"artist": "Artist", "title": "Track", "source_agent_name": "remote"}, False),
        ({"artist": "Artist", "title": "Track", "source_agent_name": "traktor"}, False),
        # Missing source agent — should be filtered out
        ({"artist": "Artist", "title": "Track"}, False),
        ({"artist": "Artist", "title": "Track", "source_agent_name": None}, False),
        ({"artist": "Artist", "title": "Track", "source_agent_name": ""}, False),
    ],
)
@pytest.mark.asyncio
async def test_earshot_getplayingtrack_filter(bootstrap, metadata, should_return):
    """getplayingtrack only returns tracks from EarShot source agents"""
    plugin = nowplaying.inputs.earshot.Plugin(config=bootstrap)
    plugin.metadata = metadata

    result = await plugin.getplayingtrack()

    if should_return:
        assert result == metadata
    else:
        assert result is None


@pytest.mark.asyncio
async def test_earshot_getplayingtrack_no_metadata(bootstrap):
    """getplayingtrack returns None when no metadata is set"""
    plugin = nowplaying.inputs.earshot.Plugin(config=bootstrap)
    plugin.metadata = {"artist": None, "title": None, "filename": None}

    result = await plugin.getplayingtrack()

    assert result is None


def test_earshot_displayname(bootstrap):
    """EarShot plugin has correct display name"""
    plugin = nowplaying.inputs.earshot.Plugin(config=bootstrap)
    assert plugin.displayname == "EarShot"


def test_earshot_settings_load_save(bootstrap):
    """load and save of earshot_always_accept setting round-trips correctly"""
    plugin = nowplaying.inputs.earshot.Plugin(config=bootstrap)

    bootstrap.cparser.setValue("earshot/always_accept", False)

    import unittest.mock  # pylint: disable=import-outside-toplevel

    qwidget = unittest.mock.MagicMock()
    qwidget.earshot_always_checkbox.isChecked.return_value = True

    plugin.load_settingsui(qwidget)
    qwidget.earshot_always_checkbox.setChecked.assert_called_once_with(False)

    plugin.save_settingsui(qwidget)
    assert bootstrap.cparser.value("earshot/always_accept", type=bool, defaultValue=False) is True
