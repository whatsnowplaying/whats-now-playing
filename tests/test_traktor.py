#!/usr/bin/env python3
"""test virtualdj"""

import asyncio
import os

import pytest

import nowplaying.inputs.traktor  # pylint: disable=import-error
import nowplaying.utils  # pylint: disable=import-error


def results(expected, metadata):
    """take a metadata result and compare to expected"""
    for expkey in expected:
        assert expkey in metadata
        assert expected[expkey] == metadata[expkey]
        del metadata[expkey]

    assert metadata == {}


@pytest.mark.xfail(
    os.name == "nt", reason="Windows file locking issues with background XML processing"
)
@pytest.mark.asyncio
async def test_read_collections(bootstrap, getroot):
    """read the collections file"""
    config = bootstrap
    cml = getroot.joinpath("tests", "playlists", "traktor", "collection.nml")
    config.cparser.setValue("traktor/collections", str(cml))
    plugin = nowplaying.inputs.traktor.Plugin(config=config)
    await plugin.start()

    # Wait for background XML processing to complete
    # Instead of fixed sleep, wait for database to exist and be populated
    max_wait = 10  # Maximum 10 seconds wait
    wait_interval = 0.5
    waited = 0

    while waited < max_wait:
        if plugin.databasefile.exists() and not config.cparser.value(
            "traktor/rebuild_db", type=bool
        ):
            # Database exists and rebuild flag is cleared - processing complete
            break
        await asyncio.sleep(wait_interval)
        waited += wait_interval

    # Additional small wait to ensure database is fully written
    await asyncio.sleep(0.5)

    track = await plugin.getrandomtrack(playlist="videos")
    assert track

    data = await plugin.lookup(artist="Divine", title="Shoot Your Shot")
    assert data
    assert data["artist"] == "Divine"
    assert data["title"] == "Shoot Your Shot"
    assert data["album"] == "The Best of Divine"

    await plugin.stop()


# @pytest.mark.asyncio
# async def test_playlist_read(virtualdj_bootstrap, getroot):  # pylint: disable=redefined-outer-name
#     ''' test getting random tracks '''
#     config = virtualdj_bootstrap
#     config.cparser.setValue('quirks/filesubst', True)
#     config.cparser.setValue('quirks/filesubstin', '/SRCROOT')
#     config.cparser.setValue('quirks/filesubstout', str(getroot))
#     playlistdir = getroot.joinpath('tests', 'playlists', 'virtualdj')
#     myvirtualdjdir = config.cparser.value('virtualdj/history')
#     config.cparser.setValue('virtualdj/playlists', playlistdir)
#     plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
#     plugin.initdb()
#     filename = await plugin.getrandomtrack('videos')
#     assert filename
#     filename = await plugin.getrandomtrack('testplaylist')
#     assert filename
