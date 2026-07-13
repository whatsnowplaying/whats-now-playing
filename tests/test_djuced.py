#!/usr/bin/env python3
"""test djuced"""

import asyncio
import pathlib
import os
import sys

import logging
import tempfile

import pytest
import watchdog.observers.polling  # pylint: disable=import-error

import nowplaying.inputs.djuced  # pylint: disable=import-error
import nowplaying.utils  # pylint: disable=import-error


@pytest.fixture
def djuced_bootstrap(bootstrap):  # pylint: disable=redefined-outer-name
    """bootstrap test"""
    with tempfile.TemporaryDirectory() as newpath:
        config = bootstrap
        config.cparser.setValue("djuced/directory", newpath)
        config.cparser.sync()
        yield config


def results(expected, metadata):
    """take a metadata result and compare to expected"""
    for expkey in expected:
        assert expkey in metadata
        assert expected[expkey] == metadata[expkey]
        del metadata[expkey]

    assert metadata == {}


@pytest.mark.asyncio
async def test_nodjuced(djuced_bootstrap):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydir = config.cparser.value("djuced/directory")
    if not os.path.exists(mydir):
        logging.error("mydir does not exist!")
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    await plugin.stop()
    await asyncio.sleep(5)
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert not metadata.get("filename")


@pytest.mark.asyncio
async def test_emptydjuced(djuced_bootstrap):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydir = config.cparser.value("djuced/directory")
    if not os.path.exists(mydir):
        logging.error("mydir does not exist!")
    pathlib.Path(os.path.join(mydir, "fake.m3u")).touch()
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    await plugin.stop()
    await asyncio.sleep(5)
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert not metadata.get("filename")


@pytest.mark.asyncio
async def test_emptydjuced2(djuced_bootstrap):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydir = config.cparser.value("djuced/directory")
    if not os.path.exists(mydir):
        logging.error("mydir does not exist!")
    with open(os.path.join(mydir, "fake.m3u"), "w") as djucedfh:  # pylint: disable=unspecified-encoding
        djucedfh.write(os.linesep)
        djucedfh.write(os.linesep)
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    await plugin.stop()
    await asyncio.sleep(5)
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert not metadata.get("filename")


@pytest.mark.asyncio
async def test_no2newdjuced(djuced_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydjuceddir = config.cparser.value("djuced/directory")
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    metadata = await plugin.getplayingtrack()
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert not metadata.get("filename")

    testmp3 = os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_orig.mp3")
    djucedfile = os.path.join(mydjuceddir, "test.m3u")
    write_djuced(djucedfile, testmp3)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert metadata["filename"] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_no2newdjucedpolltest(djuced_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydjuceddir = config.cparser.value("djuced/directory")
    config.cparser.setValue("quirks/pollingobserver", True)
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    metadata = await plugin.getplayingtrack()
    await plugin.start()
    await asyncio.sleep(5)
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert not metadata.get("filename")
    assert isinstance(plugin.observer, watchdog.observers.polling.PollingObserver)

    testmp3 = os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_orig.mp3")
    djucedfile = os.path.join(mydjuceddir, "test.m3u")
    write_djuced(djucedfile, testmp3)
    await asyncio.sleep(10)  # needs to be long enough that the poller finds the update!
    metadata = await plugin.getplayingtrack()
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert metadata["filename"] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_noencodingdjuced8(djuced_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydjuceddir = config.cparser.value("djuced/directory")
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()

    testmp3 = os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_orig.mp3")
    djucedfile = os.path.join(mydjuceddir, "test.m3u")
    write_djuced8(djucedfile, testmp3)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert metadata["filename"] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_encodingdjuced(djuced_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydjuceddir = config.cparser.value("djuced/directory")
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    testmp3 = os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_füllytâgged.mp3")
    djucedfile = os.path.join(mydjuceddir, "test.m3u")
    write_djuced(djucedfile, testmp3)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert metadata["filename"] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_vdjdjuced_normal(djuced_bootstrap):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydjuceddir = config.cparser.value("djuced/directory")
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    djucedfile = os.path.join(mydjuceddir, "test.m3u")
    write_extvdj_djuced8(djucedfile)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert metadata.get("artist") == "Lords Of The Underground"
    assert metadata.get("title") == "Chief Rocka"
    assert not metadata.get("filename")
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_vdjdjuced_remix(djuced_bootstrap):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydjuceddir = config.cparser.value("djuced/directory")
    config.cparser.setValue("djuced/useremix", True)
    config.cparser.sync()
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    djucedfile = os.path.join(mydjuceddir, "test.m3u")
    write_extvdj_remix(djucedfile)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert metadata.get("artist") == "j. period"
    assert (
        metadata.get("title")
        == "Buddy [Remix] (feat. De La Soul, Jungle Brothers, Q-Tip & Queen Latifah)"
    )
    assert not metadata.get("filename")
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_m3u_remix(djuced_bootstrap):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydjuceddir = config.cparser.value("djuced/directory")
    config.cparser.setValue("djuced/useremix", True)
    config.cparser.sync()
    djucedfile = os.path.join(mydjuceddir, "test.m3u")
    write_extvdj_remix(djucedfile)

    plugin = nowplaying.inputs.m3u.Plugin(config=config)
    myevent = watchdog.events.FileModifiedEvent(djucedfile)
    plugin._read_track(myevent)  # pylint: disable=protected-access
    assert plugin.metadata["artist"] == "j. period"
    assert (
        plugin.metadata["title"]
        == "Buddy [Remix] (feat. De La Soul, Jungle Brothers, Q-Tip & Queen Latifah)"
    )
    await plugin.stop()


@pytest.mark.asyncio
async def test_vdjdjuced_noremix(djuced_bootstrap):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydjuceddir = config.cparser.value("djuced/directory")
    config.cparser.setValue("djuced/useremix", False)
    config.cparser.sync()
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    djucedfile = os.path.join(mydjuceddir, "test.m3u")
    write_extvdj_remix(djucedfile)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert metadata.get("artist") == "j. period"
    assert metadata.get("title") == "Buddy [Remix]"
    assert not metadata.get("filename")
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_vdjdjuced_ampersand(djuced_bootstrap):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydjuceddir = config.cparser.value("djuced/directory")
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    djucedfile = os.path.join(mydjuceddir, "test.m3u")
    write_extvdj_ampersand(djucedfile)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert metadata.get("artist") == "Nick Cave & The Bad Seeds"
    assert metadata.get("title") == "Hollywood"
    assert not metadata.get("filename")
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_no2newdjuced8(djuced_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydjuceddir = config.cparser.value("djuced/directory")
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert not metadata.get("filename")

    testmp3 = os.path.join(getroot, "tests", "audio", "15_Ghosts_II_64kb_füllytâgged.mp3")
    djucedfile = os.path.join(mydjuceddir, "test.m3u")
    write_djuced8(djucedfile, testmp3)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert metadata["filename"] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_djucedrelative(djuced_bootstrap):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydjuceddir = config.cparser.value("djuced/directory")
    mydjucedpath = pathlib.Path(mydjuceddir)
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert not metadata.get("filename")

    testmp3 = os.path.join("fakedir", "15_Ghosts_II_64kb_orig.mp3")
    mydjucedpath.joinpath("fakedir").mkdir(parents=True, exist_ok=True)
    mydjucedpath.joinpath(testmp3).touch()
    djucedfile = mydjucedpath.joinpath("test.m3u")
    write_djuced(djucedfile, testmp3)
    fullpath = mydjucedpath.joinpath("fakedir", "15_Ghosts_II_64kb_orig.mp3")
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert fullpath.resolve() == pathlib.Path(metadata["filename"]).resolve()

    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_djucedrelativesubst(djuced_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    audiodir = getroot.joinpath("tests", "audio")
    mydjuceddir = pathlib.Path(config.cparser.value("djuced/directory"))
    if sys.platform == "darwin":
        mydjuceddir = mydjuceddir.resolve()
    config.cparser.setValue("quirks/filesubst", True)
    config.cparser.setValue("quirks/filesubstin", str(mydjuceddir.joinpath("fakedir")))
    config.cparser.setValue("quirks/filesubstout", str(audiodir))
    plugin = nowplaying.inputs.djuced.Plugin(config=config, m3udir=str(mydjuceddir))
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert not metadata.get("filename")

    testmp3 = str(pathlib.Path("fakedir").joinpath("15_Ghosts_II_64kb_orig.mp3"))
    mydjuceddir.joinpath("fakedir").mkdir(parents=True, exist_ok=True)
    mydjuceddir.joinpath(testmp3).touch()
    djucedfile = str(mydjuceddir.joinpath("test.m3u"))
    write_djuced(djucedfile, testmp3)
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert metadata["filename"] == str(audiodir.joinpath("15_Ghosts_II_64kb_orig.mp3"))
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_djucedstream(djuced_bootstrap):  # pylint: disable=redefined-outer-name
    """automated integration test"""
    config = djuced_bootstrap
    mydjuceddir = config.cparser.value("djuced/directory")
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert not metadata.get("filename")

    djucedfile = os.path.join(mydjuceddir, "test.m3u")
    write_djuced(djucedfile, "http://somecooltrack")
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get("artist")
    assert not metadata.get("title")
    assert not metadata.get("filename")

    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_djucedmixmode(djuced_bootstrap):  # pylint: disable=redefined-outer-name
    """make sure mix mode is always newest"""
    config = djuced_bootstrap
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    assert plugin.validmixmodes()[0] == "newest"
    assert plugin.setmixmode("fred") == "newest"
    assert plugin.getmixmode() == "newest"
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_playlist_read(djuced_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    """test getting random tracks"""
    config = djuced_bootstrap
    config.cparser.setValue("quirks/filesubst", True)
    config.cparser.setValue("quirks/filesubstin", "/SRCROOT")
    config.cparser.setValue("quirks/filesubstout", str(getroot))
    playlistdir = getroot.joinpath("tests", "playlists", "djuced")
    mydjuceddir = config.cparser.value("djuced/directory")
    config.cparser.setValue("djuced/playlists", playlistdir)
    plugin = nowplaying.inputs.djuced.Plugin(config=config)
    plugin.initdb()
    filename = await plugin.getrandomtrack("videos")
    assert filename
    filename = await plugin.getrandomtrack("testplaylist")
    assert filename
