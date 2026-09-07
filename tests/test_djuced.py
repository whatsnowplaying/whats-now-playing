"""test DJUCED input plugin"""
# pylint: disable=protected-access

import pytest

import nowplaying.inputs.djuced


@pytest.mark.asyncio
async def test_a_missing_database_falls_back_to_playing_txt(bootstrap, tmp_path):
    """DJUCED may not have written its database yet, and the track still matters.

    _try_db() is awaited from a task whose exception nothing reports, so raising
    there loses the track silently instead of degrading to the artist and title
    playing.txt already supplied.
    """
    config = bootstrap
    config.cparser.setValue("djuced/directory", str(tmp_path))
    assert not (tmp_path / "DJUCED.db").exists()

    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    plugin.djuceddir = str(tmp_path)
    nowplaying.inputs.djuced.Plugin.decktracker["1"] = {
        "title": "Whitelightgenerator",
        "artist": "Ladytron",
        "album": "Witching Hour",
    }

    await plugin._get_metadata("1")

    assert nowplaying.inputs.djuced.Plugin.metadata["artist"] == "Ladytron"
    assert nowplaying.inputs.djuced.Plugin.metadata["title"] == "Whitelightgenerator"
