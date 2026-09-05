#!/usr/bin/env python3
# pylint: disable=too-many-lines
"""test the trackpoller"""

import asyncio
import json
import logging
import pathlib
import sys
import threading
import time
import unittest.mock

import pytest  # pylint: disable=import-error
import pytest_asyncio  # pylint: disable=import-error

import nowplaying.inputs  # pylint: disable=import-error
import nowplaying.processes.trackpoll  # pylint: disable=import-error
from tests.utils_images import jpeg_bytes, png_bytes

# datacache refuses bytes it cannot parse under an image data_type, so artwork
# fixtures have to be real images -- a signature plus filler takes the rejection
# branch instead of the path under test.
MINIMAL_PNG = png_bytes()
MINIMAL_JPEG = jpeg_bytes()


@pytest_asyncio.fixture(loop_scope="function")
async def trackpollbootstrap(bootstrap, getroot, tmp_path):  # pylint: disable=redefined-outer-name
    """bootstrap a configuration"""
    txtfile = tmp_path.joinpath("output.txt")
    if pathlib.Path(txtfile).exists():
        pathlib.Path(txtfile).unlink()
    jsonfile = tmp_path.joinpath("input.json")
    config = bootstrap
    config.templatedir = getroot.joinpath("tests", "templates")
    config.cparser.setValue("artistextras/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("control/paused", True)
    config.cparser.setValue("settings/input", "jsonreader")
    config.cparser.setValue("settings/delay", 0)  # No artificial delay in tests
    config.cparser.setValue("jsoninput/delay", 1)
    config.cparser.setValue("jsoninput/filename", str(jsonfile))
    config.cparser.setValue("textoutput/file", str(txtfile))
    stopevent = threading.Event()
    logging.debug("output = %s", txtfile)
    config.cparser.sync()
    trackpoll = nowplaying.processes.trackpoll.TrackPoll.create_with_plugins(
        stopevent=stopevent, config=config, testmode=True
    )
    try:
        yield config
    finally:
        await trackpoll.stop()
        # With session-scoped event loop, cancel and await all tasks so they
        # don't linger and interfere with the next test's TrackPoll instance.
        remaining = list(trackpoll.tasks)
        for task in remaining:
            task.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)
        await asyncio.sleep(0.1)


def write_json_metadata_sync(config, metadata):
    """Synchronously write the JSON input file and clear any previous output.

    Called before any await so the file is guaranteed to exist when
    run()'s getplayingtrack() wakes from its poll-interval sleep.
    """
    txtoutput = config.cparser.value("textoutput/file")
    pathlib.Path(txtoutput).unlink(missing_ok=True)
    filepath = pathlib.Path(config.cparser.value("jsoninput/filename"))
    with open(filepath, "w+", encoding="utf-8") as fhout:
        json.dump(metadata, fhout)
    return txtoutput


async def write_json_metadata(config, metadata):
    """Write JSON input and wait for text output to appear."""
    txtoutput = write_json_metadata_sync(config, metadata)
    logging.debug("waiting for output %s", txtoutput)
    await wait_for_output(txtoutput)


async def wait_for_output(filename):
    """wait for the output to appear"""

    # these tests tend to be a bit flaky/racy esp on github
    # runners so add some protection
    counter = 0
    sleep_time = 2 if sys.platform == "win32" else 1
    max_attempts = 10 if sys.platform == "win32" else 15  # Reasonable polling for all platforms
    while counter < max_attempts and not pathlib.Path(filename).exists():
        await asyncio.sleep(sleep_time)
        counter += 1
        logging.debug("waiting for %s: %s", filename, counter)
    assert pathlib.Path(filename).exists(), f"File {filename} not created after {counter} attempts"


@pytest.mark.parametrize(
    "test_case",
    [
        # Basic trackpolling test
        {
            "id": "basic_single",
            "template": "simple.txt",
            "metadata": {"artist": "NIN"},
            "expected": ["NIN"],
        },
        {
            "id": "basic_double",
            "template": "simple.txt",
            "metadata": {"artist": "NIN", "title": "Ghosts"},
            "expected": ["NIN", "Ghosts"],
        },
        # No file test
        {
            "id": "nofile",
            "template": "simplewfn.txt",
            "metadata": {"title": "Xyzzy WNP Test Title", "artist": "Xyzzy WNP Test Artist"},
            "expected": ["", "Xyzzy WNP Test Artist", "Xyzzy WNP Test Title"],
        },
        # Bad file test
        {
            "id": "badfile",
            "template": "simplewfn.txt",
            "metadata": {
                "title": "Xyzzy WNP Test Title",
                "artist": "Xyzzy WNP Test Artist",
                "filename": "completejunk",
            },
            "expected": ["", "Xyzzy WNP Test Artist", "Xyzzy WNP Test Title"],
        },
    ],
)
@pytest.mark.asyncio
async def test_trackpoll_scenarios(trackpollbootstrap, getroot, test_case):  # pylint: disable=redefined-outer-name
    """test various trackpolling scenarios"""
    config = trackpollbootstrap

    # Set up template
    if test_case["template"] == "simple.txt":
        template = config.templatedir.joinpath("simple.txt")
    else:
        template = getroot.joinpath("tests", "templates", test_case["template"])

    config.txttemplate = str(template)
    config.cparser.setValue("textoutput/txttemplate", str(template))

    # Write JSON synchronously before any await so run()'s getplayingtrack()
    # always finds the file when it wakes from its 1-second poll sleep.
    txtoutput = write_json_metadata_sync(config, test_case["metadata"])

    # Unpause after the file is on disk.
    config.cparser.setValue("control/paused", False)
    config.cparser.sync()

    await wait_for_output(txtoutput)

    with open(txtoutput, encoding="utf-8") as filein:
        text = filein.readlines()

    for i, expected_line in enumerate(test_case["expected"]):
        assert text[i].strip() == expected_line


@pytest.mark.asyncio
async def test_trackpoll_titleisfile(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    """test trackpoll title is a filename"""
    config = trackpollbootstrap
    template = getroot.joinpath("tests", "templates", "simplewfn.txt")
    config.txttemplate = str(template)
    config.cparser.setValue("textoutput/txttemplate", str(template))
    title = str(getroot.joinpath("tests", "audio", "15_Ghosts_II_64kb_orig.mp3"))
    txtoutput = write_json_metadata_sync(config, {"title": title})
    config.cparser.setValue("control/paused", False)
    config.cparser.sync()
    await wait_for_output(txtoutput)
    with open(txtoutput, encoding="utf-8") as filein:
        text = filein.readlines()

    assert text[0].strip() == title
    assert text[1].strip() == "Nine Inch Nails"
    assert text[2].strip() == "15 Ghosts II"


@pytest.mark.asyncio
async def test_trackpoll_metadata(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    """test trackpolling + metadata + input override"""
    config = trackpollbootstrap
    template = getroot.joinpath("tests", "templates", "simplewfn.txt")
    config.txttemplate = str(template)
    config.cparser.setValue("textoutput/txttemplate", str(template))
    metadata = {"filename": str(getroot.joinpath("tests", "audio", "15_Ghosts_II_64kb_orig.mp3"))}
    txtoutput = write_json_metadata_sync(config, metadata)
    config.cparser.setValue("control/paused", False)
    config.cparser.sync()
    await wait_for_output(txtoutput)
    with open(txtoutput, encoding="utf-8") as filein:
        text = filein.readlines()

    assert text[0].strip() == metadata["filename"]
    assert text[1].strip() == "Nine Inch Nails"
    assert text[2].strip() == "15 Ghosts II"

    metadata["artist"] = "NIN"

    await write_json_metadata(config=config, metadata=metadata)
    with open(txtoutput, encoding="utf-8") as filein:
        text = filein.readlines()
    assert text[0].strip() == metadata["filename"]
    assert text[1].strip() == "NIN"
    assert text[2].strip() == "15 Ghosts II"

    metadata["title"] = "Ghosts"
    del metadata["artist"]
    await write_json_metadata(config=config, metadata=metadata)
    await wait_for_output(txtoutput)
    with open(txtoutput, encoding="utf-8") as filein:
        text = filein.readlines()
    assert text[0].strip() == metadata["filename"]
    assert text[1].strip() == "Nine Inch Nails"
    assert text[2].strip() == "Ghosts"


@pytest.mark.asyncio
async def test_trackpoll_notifications_loaded(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    """test that notification plugins are loaded properly"""
    config = trackpollbootstrap
    config.cparser.setValue("remote/enabled", True)
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(
        stopevent=threading.Event(), config=config, testmode=True
    )
    # Manually setup plugins to test the separated functionality
    trackpoll._setup_notifications()  # pylint: disable=protected-access

    try:
        # Verify notification plugins are loaded
        assert trackpoll.notification_plugins is not None
        assert trackpoll.active_notifications is not None
        # Should have notification plugins available
        assert len(trackpoll.notification_plugins) > 0
    finally:
        # Properly cleanup to avoid Windows timing issues
        await trackpoll.stop()


@pytest.mark.asyncio
async def test_trackpoll_notify_plugins_called(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    """test that _notify_plugins is called during track processing"""
    config = trackpollbootstrap
    config.cparser.setValue("remote/enabled", False)  # Test with disabled to avoid network calls
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(
        stopevent=threading.Event(), config=config, testmode=True
    )
    # Manually setup plugins to test the separated functionality
    trackpoll._setup_notifications()  # pylint: disable=protected-access

    try:
        trackpoll.currentmeta = {
            "artist": "Test Artist",
            "title": "Test Title",
            "filename": "test.mp3",
        }

        # Mock the notify method to avoid actual network calls
        async def mock_notify(metadata, imagecache=None):  # pylint: disable=unused-argument
            pass

        # Replace the notification plugins with mock
        for plugin in trackpoll.active_notifications:
            plugin.notify_track_change = mock_notify

        # Test that _notify_plugins executes without error
        await trackpoll._notify_plugins()  # pylint: disable=protected-access
    finally:
        # Properly cleanup to avoid Windows timing issues
        await trackpoll.stop()


@pytest.mark.asyncio
async def test_trackpoll_stop_flushes_pending_meta(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    """ensure TrackPoll.stop() flushes _pending_meta via end_game and _publish on shutdown"""
    config = trackpollbootstrap
    config.cparser.setValue("guessgame/enabled", True)
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(
        stopevent=threading.Event(), config=config, testmode=True
    )
    trackpoll._setup_guessgame()  # pylint: disable=protected-access
    trackpoll._setup_notifications()  # pylint: disable=protected-access

    trackpoll._pending_meta = {  # pylint: disable=protected-access
        "artist": "Test Artist",
        "title": "Test Title",
    }

    end_game_calls = []
    publish_calls = []

    async def mock_end_game(reason=None):
        end_game_calls.append(reason)

    async def mock_publish(metadata):
        publish_calls.append(metadata)

    trackpoll.guessgame.end_game = mock_end_game
    trackpoll._publish = mock_publish  # pylint: disable=protected-access

    await trackpoll.stop()

    assert end_game_calls, "end_game should be called when _pending_meta is set on stop()"
    assert publish_calls, "_publish should be called when _pending_meta is set on stop()"
    assert trackpoll._pending_meta is None  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_trackpoll_game_pending_meta(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    """test that _pending_meta is published via _publish and then cleared"""
    config = trackpollbootstrap
    config.cparser.setValue("guessgame/enabled", True)
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(
        stopevent=threading.Event(), config=config, testmode=True
    )
    trackpoll._setup_guessgame()  # pylint: disable=protected-access
    trackpoll._setup_notifications()  # pylint: disable=protected-access

    try:
        # Mock may_publish to report the game has ended
        async def mock_may_publish():
            return True

        trackpoll.guessgame.may_publish = mock_may_publish

        # Set up metadata and simulate a deferred (pending) write
        trackpoll.currentmeta = {
            "artist": "Test Artist",
            "title": "Test Title",
            "filename": "test.mp3",
        }
        trackpoll._pending_meta = trackpoll.currentmeta.copy()  # pylint: disable=protected-access

        # Simulate the idle-cycle permission check: may_publish → publish → clear
        if await trackpoll.guessgame.may_publish():
            await trackpoll._publish(trackpoll._pending_meta)  # pylint: disable=protected-access
            trackpoll._pending_meta = None  # pylint: disable=protected-access

        # Verify pending metadata was cleared
        assert trackpoll._pending_meta is None  # pylint: disable=protected-access

    finally:
        await trackpoll.stop()


@pytest.mark.asyncio
async def test_trackpoll_requests_integration(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    """test track requests integration"""
    config = trackpollbootstrap
    config.cparser.setValue("settings/requests", True)
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(
        stopevent=threading.Event(), config=config, testmode=True
    )
    trackpoll._setup_trackrequests()  # pylint: disable=protected-access

    try:
        # Mock trackrequests.get_request
        async def mock_get_request(metadata):  # pylint: disable=unused-argument
            return {"requester": "TestUser"}

        trackpoll.trackrequests.get_request = mock_get_request

        # Set up metadata
        trackpoll.currentmeta = {
            "artist": "Test Artist",
            "title": "Test Title",
        }

        # Simulate request processing
        if data := await trackpoll.trackrequests.get_request(trackpoll.currentmeta):
            trackpoll.currentmeta.update(data)

        # Verify request data was added
        assert trackpoll.currentmeta.get("requester") == "TestUser"

    finally:
        await trackpoll.stop()


@pytest.mark.asyncio
async def test_trackpoll_cache_warmed(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    """test cache warming path"""
    config = trackpollbootstrap
    config.cparser.setValue("artistextras/enabled", True)
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(
        stopevent=threading.Event(), config=config, testmode=True
    )

    try:
        # Set up metadata with cache_warmed flag
        trackpoll.currentmeta = {
            "artist": "Test Artist",
            "title": "Test Title",
            "cache_warmed": True,
        }

        # Test that cache_warmed path is taken
        assert trackpoll.currentmeta.get("cache_warmed") is True

    finally:
        await trackpoll.stop()


@pytest.mark.parametrize(
    "fill_duration,configured_delay,expected",
    [
        # Fast fill: final sleep = configured_delay / 2 (full grace period)
        (0.0, 1.0, 0.5),
        (0.0, 2.0, 1.0),
        (0.0, 0.5, 0.25),
        # Fill equal to half delay: grace period unchanged
        (0.5, 1.0, 0.5),
        (1.0, 2.0, 1.0),
        # Fill equals configured delay: no reduction yet
        (1.0, 1.0, 0.5),
        (2.0, 2.0, 1.0),
        # Fill slightly exceeds configured: grace period starts reducing
        (1.2, 1.0, 0.3),
        (2.4, 2.0, 0.6),
        # Fill exceeds configured by half: grace period = 0
        (1.5, 1.0, 0.0),
        (3.0, 2.0, 0.0),
        # Fill far exceeds configured: clamped to 0
        (5.0, 1.0, 0.0),
        # Realistic DJ delay of 10s — old hardcoded 0.5 would be wildly wrong here
        (0.5, 10.0, 5.0),  # fast fill: full 5s grace period
        (2.0, 10.0, 5.0),  # typical metadata fetch: still full grace period
        (5.0, 10.0, 5.0),  # slow fetch, still within configured: full grace period
        (10.0, 10.0, 5.0),  # fill equals configured: grace period unaffected
        (12.0, 10.0, 3.0),  # fill exceeds by 2s: grace reduced to 3s
        (15.0, 10.0, 0.0),  # fill exceeds by 5s: grace period exhausted
        (20.0, 10.0, 0.0),  # fill far exceeds: clamped to 0
    ],
)
def test_gettrack_final_sleep_formula(fill_duration, configured_delay, expected):
    """final sleep before checkagain must scale with configured_delay"""
    sleep_time = nowplaying.processes.trackpoll.compute_final_sleep(
        fill_duration, configured_delay
    )
    assert abs(sleep_time - expected) < 1e-9


@pytest.fixture
def trackpoll_testmode(bootstrap):  # pylint: disable=redefined-outer-name
    """Create a minimal TrackPoll for unit testing _artfallbacks, closing its loop on teardown."""
    tp = nowplaying.processes.trackpoll.TrackPoll(
        stopevent=threading.Event(), config=bootstrap, testmode=True
    )
    yield tp
    if not tp.loop.is_running() and not tp.loop.is_closed():
        tp.loop.close()


@pytest.mark.asyncio
async def test_artfallbacks_front_cover_from_imagecache(
    bootstrap, trackpoll_testmode, isolated_datacache_client
):  # pylint: disable=redefined-outer-name,unused-argument
    """front_cover in datacache is used before falling back to artist images"""
    tptest = trackpoll_testmode
    cover_bytes = MINIMAL_PNG
    # Pre-populate via client.storage — _artfallbacks uses get_client().storage
    # _artfallbacks builds identifier as normalize(artist)_normalize(album)
    await isolated_datacache_client.storage.store(
        url="embedded://artist_album/provided_0",
        identifier="artist_album",
        data_type="front_cover",
        provider="embedded",
        data_value=cover_bytes,
        ttl_seconds=86400,
    )
    tptest.currentmeta = {"artist": "Artist", "album": "Album"}
    bootstrap.cparser.setValue("artistextras/nocoverfallback", "fanart")

    await tptest._artfallbacks()  # pylint: disable=protected-access

    assert tptest.currentmeta.get("coverimageraw") == cover_bytes


@pytest.mark.asyncio
async def test_artfallbacks_falls_back_to_artist_image_when_no_front_cover(
    bootstrap,
    trackpoll_testmode,  # pylint: disable=redefined-outer-name
    isolated_datacache_client,  # pylint: disable=unused-argument
):
    """artist fallback image used when datacache has no front_cover"""
    tptest = trackpoll_testmode
    fanart_bytes = MINIMAL_JPEG
    # Pre-populate via client.storage — _artfallbacks uses get_client().storage
    await isolated_datacache_client.storage.store(
        url="http://example.com/fanart.jpg",
        identifier="artist",
        data_type="artistfanart",
        provider="theaudiodb",
        data_value=fanart_bytes,
        ttl_seconds=86400,
    )
    tptest.currentmeta = {"artist": "Artist", "album": "Album", "imagecacheartist": "artist"}
    bootstrap.cparser.setValue("artistextras/nocoverfallback", "fanart")

    await tptest._artfallbacks()  # pylint: disable=protected-access

    assert tptest.currentmeta.get("coverimageraw") == fanart_bytes


@pytest.mark.asyncio
async def test_artfallbacks_no_fallback_when_front_cover_missing_and_nocoverfallback_none(
    bootstrap,
    trackpoll_testmode,  # pylint: disable=redefined-outer-name
):
    """coverimageraw stays empty when nocoverfallback is 'none'"""
    tptest = trackpoll_testmode
    tptest.currentmeta = {"artist": "Artist", "album": "Album", "imagecacheartist": "Artist"}
    bootstrap.cparser.setValue("artistextras/nocoverfallback", "none")

    await tptest._artfallbacks()  # pylint: disable=protected-access

    assert not tptest.currentmeta.get("coverimageraw")


@pytest.mark.asyncio
async def test_artfallbacks_cover_used_as_logo_fallback(bootstrap, trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """existing coverimageraw is copied to artistlogoraw when coverfornologos enabled"""
    tptest = trackpoll_testmode
    cover_bytes = b"fake_cover"
    tptest.currentmeta = {"coverimageraw": cover_bytes}
    bootstrap.cparser.setValue("artistextras/coverfornologos", True)

    await tptest._artfallbacks()  # pylint: disable=protected-access

    assert tptest.currentmeta.get("artistlogoraw") == cover_bytes


@pytest.mark.asyncio
async def test_artfallbacks_cover_used_as_thumbnail_fallback(bootstrap, trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """existing coverimageraw is copied to artistthumbnailraw when coverfornothumbs enabled"""
    tptest = trackpoll_testmode
    cover_bytes = b"fake_cover"
    tptest.currentmeta = {"coverimageraw": cover_bytes}
    bootstrap.cparser.setValue("artistextras/coverfornothumbs", True)

    await tptest._artfallbacks()  # pylint: disable=protected-access

    assert tptest.currentmeta.get("artistthumbnailraw") == cover_bytes


@pytest.mark.asyncio
async def test_artfallbacks_preexisting_cover_not_overwritten(bootstrap, trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """coverimageraw already in metadata is never replaced"""
    tptest = trackpoll_testmode
    original = b"original_cover"
    tptest.currentmeta = {
        "artist": "Artist",
        "album": "Album",
        "imagecacheartist": "Artist",
        "coverimageraw": original,
    }
    bootstrap.cparser.setValue("artistextras/nocoverfallback", "fanart")

    await tptest._artfallbacks()  # pylint: disable=protected-access

    assert tptest.currentmeta.get("coverimageraw") == original


# ---------------------------------------------------------------------------
# EarShot override tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "meta,expected",
    [
        ({}, ("", "")),
        ({"artist": "Artist"}, ("Artist", "")),
        ({"title": "Title"}, ("", "Title")),
        ({"artist": "Artist", "title": "Title"}, ("Artist", "Title")),
        ({"artist": None, "title": None}, ("", "")),
    ],
)
def test_earshot_track_key(meta, expected):
    """_earshot_track_key returns stable (artist, title) tuple"""
    result = nowplaying.processes.trackpoll.TrackPoll._earshot_track_key(meta)  # pylint: disable=protected-access
    assert result == expected


@pytest.mark.asyncio
async def test_check_earshot_override_no_plugin(trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """when no earshot plugin is running meta passes through unchanged"""
    tptest = trackpoll_testmode
    main_meta = {"artist": "Serato Artist", "title": "Serato Track"}
    result, overrode = await tptest._check_earshot_override(main_meta)  # pylint: disable=protected-access
    assert result == main_meta
    assert overrode is False


@pytest.mark.asyncio
async def test_check_earshot_override_new_track(trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """new EarShot track overrides main source and updates state"""
    tptest = trackpoll_testmode
    main_meta = {"artist": "Serato Artist", "title": "Serato Track"}
    earshot_meta = {
        "artist": "Vinyl Artist",
        "title": "Vinyl Track",
        "source_agent_name": "wnpearshot-1.0",
    }

    mock_plugin = unittest.mock.AsyncMock()
    mock_plugin.getplayingtrack.return_value = earshot_meta
    tptest.earshot_plugin = mock_plugin  # pylint: disable=protected-access

    result, overrode = await tptest._check_earshot_override(main_meta)  # pylint: disable=protected-access

    assert result == earshot_meta
    assert overrode is True
    assert tptest.earshot_last_meta == earshot_meta  # pylint: disable=protected-access
    assert tptest.main_source_suppressed_meta == main_meta  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_check_earshot_override_same_track_no_suppression(trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """EarShot unchanged and no suppression active — main source passes through"""
    tptest = trackpoll_testmode
    earshot_meta = {
        "artist": "Vinyl Artist",
        "title": "Vinyl Track",
        "source_agent_name": "wnpearshot-1.0",
    }
    tptest.earshot_last_meta = earshot_meta  # pylint: disable=protected-access

    mock_plugin = unittest.mock.AsyncMock()
    mock_plugin.getplayingtrack.return_value = earshot_meta
    tptest.earshot_plugin = mock_plugin  # pylint: disable=protected-access

    main_meta = {"artist": "Serato Artist", "title": "Serato Track"}
    result, overrode = await tptest._check_earshot_override(main_meta)  # pylint: disable=protected-access

    assert result == main_meta
    assert overrode is False
    assert tptest.main_source_suppressed_meta == {}  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_check_earshot_override_suppresses_stale_main_source(trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """main source reporting same stale track is suppressed after EarShot override"""
    tptest = trackpoll_testmode
    earshot_meta = {
        "artist": "Vinyl Artist",
        "title": "Vinyl Track",
        "source_agent_name": "wnpearshot-1.0",
    }
    stale_main = {"artist": "Serato Artist", "title": "Serato Track"}

    tptest.earshot_last_meta = earshot_meta  # pylint: disable=protected-access
    tptest.main_source_suppressed_meta = stale_main  # pylint: disable=protected-access

    mock_plugin = unittest.mock.AsyncMock()
    mock_plugin.getplayingtrack.return_value = earshot_meta
    tptest.earshot_plugin = mock_plugin  # pylint: disable=protected-access

    result, overrode = await tptest._check_earshot_override(stale_main)  # pylint: disable=protected-access

    assert result == {}
    assert overrode is False
    # suppression still active — suppressed_meta not cleared
    assert tptest.main_source_suppressed_meta == stale_main  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_check_earshot_override_clears_suppression_on_new_main_track(trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """genuinely new main source track clears EarShot suppression"""
    tptest = trackpoll_testmode
    earshot_meta = {
        "artist": "Vinyl Artist",
        "title": "Vinyl Track",
        "source_agent_name": "wnpearshot-1.0",
    }
    stale_main = {"artist": "Serato Artist", "title": "Serato Track"}
    new_main = {"artist": "Serato Artist", "title": "New Serato Track"}

    tptest.earshot_last_meta = earshot_meta  # pylint: disable=protected-access
    tptest.main_source_suppressed_meta = stale_main  # pylint: disable=protected-access

    mock_plugin = unittest.mock.AsyncMock()
    mock_plugin.getplayingtrack.return_value = earshot_meta
    tptest.earshot_plugin = mock_plugin  # pylint: disable=protected-access

    result, overrode = await tptest._check_earshot_override(new_main)  # pylint: disable=protected-access

    assert result == new_main
    assert overrode is False
    assert tptest.main_source_suppressed_meta == {}  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_check_earshot_override_poll_failure(trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """EarShot poll exception is caught and main source passes through"""
    tptest = trackpoll_testmode
    main_meta = {"artist": "Serato Artist", "title": "Serato Track"}

    mock_plugin = unittest.mock.AsyncMock()
    mock_plugin.getplayingtrack.side_effect = RuntimeError("connection lost")
    tptest.earshot_plugin = mock_plugin  # pylint: disable=protected-access

    result, overrode = await tptest._check_earshot_override(main_meta)  # pylint: disable=protected-access

    assert result == main_meta
    assert overrode is False


@pytest.mark.asyncio
async def test_check_earshot_override_ignores_same_as_main(trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """EarShot hearing the same track as main source does not trigger an override"""
    tptest = trackpoll_testmode
    main_meta = {"artist": "Vinyl Artist", "title": "Vinyl Track", "source_agent_name": "serato"}
    earshot_meta = {
        "artist": "Vinyl Artist",
        "title": "Vinyl Track",
        "source_agent_name": "wnpearshot",
    }

    mock_plugin = unittest.mock.AsyncMock()
    mock_plugin.getplayingtrack.return_value = earshot_meta
    tptest.earshot_plugin = mock_plugin  # pylint: disable=protected-access

    result, overrode = await tptest._check_earshot_override(main_meta)  # pylint: disable=protected-access

    assert overrode is False
    assert result == main_meta
    # earshot_last_meta updated so next poll does not recheck
    assert tptest.earshot_last_meta == earshot_meta  # pylint: disable=protected-access


def _status_plugin(status, started=None, stopped=None):
    """Build a Plugin class reporting a fixed status."""

    class Reports:  # pylint: disable=no-self-use,too-few-public-methods
        """Starts fine and reports whatever the test asked for."""

        def __init__(self, config=None):  # pylint: disable=unused-argument
            pass

        async def start(self):
            """Succeed, per the contract."""
            if started is not None:
                started.append(True)

        async def stop(self):
            """Release nothing."""
            if stopped is not None:
                stopped.append(True)

        def status(self):
            """Report the health under test."""
            return status

        async def getplayingtrack(self):
            """No track."""
            return None

    return Reports


def _use_plugin(trackpoll, config, plugin_cls):
    """Point trackpoll at a single fake input."""
    config.cparser.setValue("settings/input", "pretend")
    trackpoll.plugins = {"nowplaying.inputs.pretend": unittest.mock.MagicMock(Plugin=plugin_cls)}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "health,pollable",
    [
        (nowplaying.inputs.InputHealth.OK, True),
        (nowplaying.inputs.InputHealth.STARTING, True),
        (nowplaying.inputs.InputHealth.WAITING, True),
        (nowplaying.inputs.InputHealth.NEEDS_USER, False),
        (nowplaying.inputs.InputHealth.NEEDS_RESTART, False),
        (nowplaying.inputs.InputHealth.BROKEN, False),
    ],
)
async def test_status_decides_whether_to_poll(bootstrap, trackpoll_testmode, health, pollable):  # pylint: disable=redefined-outer-name
    """WAITING is the plugin saying it has this in hand, so polling continues."""
    status = nowplaying.inputs.InputStatus(health=health, message="because")
    _use_plugin(trackpoll_testmode, bootstrap, _status_plugin(status))
    assert await trackpoll_testmode.switch_input_plugin() is pollable


@pytest.mark.asyncio
async def test_needs_user_is_reported_once(bootstrap, trackpoll_testmode, caplog):  # pylint: disable=redefined-outer-name
    """The message cannot change until the user acts, so say it once."""
    status = nowplaying.inputs.InputStatus(
        health=nowplaying.inputs.InputHealth.NEEDS_USER,
        message="Rekordbox key does not open the database",
    )
    _use_plugin(trackpoll_testmode, bootstrap, _status_plugin(status))

    with caplog.at_level(logging.ERROR):
        for _ in range(10):
            assert await trackpoll_testmode.switch_input_plugin() is False

    said = [r for r in caplog.records if "needs attention" in r.message]
    assert len(said) == 1, f"reported {len(said)} times"
    assert "does not open the database" in said[0].getMessage()


@pytest.mark.asyncio
async def test_needs_restart_waits_then_rebuilds(bootstrap, trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """A restart is honoured once, after the delay, not on the next cycle."""
    started = []
    status = nowplaying.inputs.InputStatus(
        health=nowplaying.inputs.InputHealth.NEEDS_RESTART, message="discovery died"
    )
    _use_plugin(trackpoll_testmode, bootstrap, _status_plugin(status, started=started))

    assert await trackpoll_testmode.switch_input_plugin() is False
    assert len(started) == 1

    for _ in range(10):  # still inside the delay
        await trackpoll_testmode.switch_input_plugin()
    assert len(started) == 1, "restarted before the delay elapsed"

    # Arrive at the far side of the wait without sleeping through it.
    trackpoll_testmode._restart_input_at = time.monotonic() - 1  # pylint: disable=protected-access
    await trackpoll_testmode.switch_input_plugin()  # notices the wait is over
    await trackpoll_testmode.switch_input_plugin()  # rebuilds
    assert len(started) == 2, "the restart never happened"


@pytest.mark.asyncio
async def test_earshot_is_still_read_when_the_main_source_cannot_run(
    bootstrap, trackpoll_testmode
):  # pylint: disable=redefined-outer-name
    """gettrack() is the only thing that reads EarShot, so it has to keep running.

    EarShot writes whether or not the chosen source works, and returning False
    from switch_input_plugin() skips gettrack() entirely -- so a source stuck on
    NEEDS_USER would silently discard everything EarShot produced.
    """
    config = bootstrap
    config.cparser.setValue("settings/input", "pretend")
    status = nowplaying.inputs.InputStatus(
        health=nowplaying.inputs.InputHealth.NEEDS_USER, message="fix me"
    )
    healthy = nowplaying.inputs.InputStatus()
    trackpoll_testmode.plugins = {
        "nowplaying.inputs.pretend": unittest.mock.MagicMock(Plugin=_status_plugin(status)),
    }

    # No EarShot available: nothing to run, so the loop skips gettrack().
    assert await trackpoll_testmode.switch_input_plugin() is False
    assert trackpoll_testmode._input_pollable is False  # pylint: disable=protected-access

    # EarShot present, so _manage_earshot_plugin() starts it and the loop has
    # to reach gettrack() even though the chosen source cannot run.
    trackpoll_testmode.plugins["nowplaying.inputs.earshot"] = unittest.mock.MagicMock(
        Plugin=_status_plugin(healthy)
    )
    assert await trackpoll_testmode.switch_input_plugin() is True
    assert trackpoll_testmode.earshot_plugin is not None
    assert trackpoll_testmode._input_pollable is False, (  # pylint: disable=protected-access
        "the main source is still not worth polling"
    )


@pytest.mark.asyncio
async def test_a_restart_deadline_does_not_carry_across_plugins(bootstrap, trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """A deadline from a previous plugin would skip the wait the constant exists for."""
    config = bootstrap
    config.cparser.setValue("settings/input", "pretend")
    status = nowplaying.inputs.InputStatus(
        health=nowplaying.inputs.InputHealth.NEEDS_RESTART, message="again"
    )
    trackpoll_testmode.plugins = {
        "nowplaying.inputs.pretend": unittest.mock.MagicMock(Plugin=_status_plugin(status)),
        "nowplaying.inputs.other": unittest.mock.MagicMock(Plugin=_status_plugin(status)),
    }

    await trackpoll_testmode.switch_input_plugin()
    # Pretend its wait already expired, then switch to a different input.
    trackpoll_testmode._restart_input_at = time.monotonic() - 1  # pylint: disable=protected-access
    config.cparser.setValue("settings/input", "other")
    await trackpoll_testmode.switch_input_plugin()

    pending = trackpoll_testmode._restart_input_at  # pylint: disable=protected-access
    assert pending == 0.0 or pending > time.monotonic(), (
        "the new plugin inherited an expired deadline"
    )


@pytest.mark.asyncio
async def test_earshot_overrides_a_source_reporting_nothing(trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """EarShot always accepts input, so it has to win against an empty source.

    A source that cannot run contributes {} now rather than not being polled,
    and EarShot's identification has to come through that.
    """
    heard = {"artist": "Wire", "title": "The 15th"}
    earshot = unittest.mock.AsyncMock()
    earshot.getplayingtrack.return_value = heard
    trackpoll_testmode.earshot_plugin = earshot

    used, overrode = await trackpoll_testmode._check_earshot_override({})  # pylint: disable=protected-access

    assert overrode is True, "EarShot should have overridden an empty source"
    assert used["artist"] == "Wire" and used["title"] == "The 15th"
    assert not trackpoll_testmode.main_source_suppressed_meta, (
        "there is no stale main track to suppress"
    )


@pytest.mark.asyncio
async def test_earshot_is_managed_even_when_the_source_will_not_start(trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """A source that cannot start must not leave EarShot unmanaged for a cycle.

    Returning early on start failure skipped _manage_earshot_plugin(), so
    EarShot was neither started nor stopped until the next pass.
    """
    config = trackpoll_testmode.config
    config.cparser.setValue("settings/input", "pretend")

    class WillNotStart:  # pylint: disable=no-self-use,too-few-public-methods
        """Raises out of start(), which the contract calls a defect."""

        def __init__(self, config=None):  # pylint: disable=unused-argument
            pass

        async def start(self):
            """Fail."""
            raise RuntimeError("no soup for you")

        async def stop(self):
            """Nothing held."""

    trackpoll_testmode.plugins = {
        "nowplaying.inputs.pretend": unittest.mock.MagicMock(Plugin=WillNotStart),
        "nowplaying.inputs.earshot": unittest.mock.MagicMock(
            Plugin=_status_plugin(nowplaying.inputs.InputStatus())
        ),
    }

    assert await trackpoll_testmode.switch_input_plugin() is True, (
        "EarShot is running, so the loop still has work"
    )
    assert trackpoll_testmode.earshot_plugin is not None, "EarShot was left unmanaged"
    assert trackpoll_testmode.input is None
    assert trackpoll_testmode._input_pollable is False  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_losing_the_input_setting_still_manages_earshot(trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """A config reset clears settings/input while EarShot may be running.

    Returning early there left the monitor neither stopped nor read: it keeps
    its watcher on remotedb, which is the collision hazard for the remote
    plugin, and keeps writing with nobody looking.
    """
    config = trackpoll_testmode.config
    config.cparser.setValue("settings/input", "pretend")
    trackpoll_testmode.plugins = {
        "nowplaying.inputs.pretend": unittest.mock.MagicMock(
            Plugin=_status_plugin(nowplaying.inputs.InputStatus())
        ),
        "nowplaying.inputs.earshot": unittest.mock.MagicMock(
            Plugin=_status_plugin(nowplaying.inputs.InputStatus())
        ),
    }

    assert await trackpoll_testmode.switch_input_plugin() is True
    assert trackpoll_testmode.earshot_plugin is not None

    # The setting goes away underneath us.
    config.cparser.remove("settings/input")
    assert await trackpoll_testmode.switch_input_plugin() is True, (
        "EarShot alone is still something to poll"
    )
    assert trackpoll_testmode.input is None
    assert trackpoll_testmode._input_pollable is False  # pylint: disable=protected-access
    assert trackpoll_testmode.earshot_plugin is not None, (
        "EarShot should still be managed, not orphaned"
    )


@pytest.mark.asyncio
async def test_an_input_wedged_in_stop_does_not_hang_the_switch(
    bootstrap, trackpoll_testmode, monkeypatch
):  # pylint: disable=redefined-outer-name
    """A plugin that never returns from stop() must not take the poll loop.

    The contract asks stop() to be safe at any time but sets no bound on how
    long it may take, so every caller here has to impose one.
    """
    monkeypatch.setattr(nowplaying.processes.trackpoll, "_STOP_TIMEOUT_SECONDS", 0.05)

    class Wedges:  # pylint: disable=no-self-use,too-few-public-methods
        """Starts fine, then never returns from stop()."""

        def __init__(self, config=None):  # pylint: disable=unused-argument
            pass

        async def start(self):
            """Succeed, per the contract."""

        async def stop(self):
            """Never return."""
            await asyncio.sleep(3600)

        def status(self):
            """Healthy right up to the switch."""
            return nowplaying.inputs.InputStatus()

        async def getplayingtrack(self):
            """No track."""
            return None

    _use_plugin(trackpoll_testmode, bootstrap, Wedges)
    assert await trackpoll_testmode.switch_input_plugin() is True

    # Switching away stops the old plugin, which is where it wedges.
    bootstrap.cparser.setValue("settings/input", "other")
    trackpoll_testmode.plugins["nowplaying.inputs.other"] = unittest.mock.MagicMock(
        Plugin=_status_plugin(nowplaying.inputs.InputStatus())
    )

    await asyncio.wait_for(trackpoll_testmode.switch_input_plugin(), timeout=5)
    assert trackpoll_testmode.previousinput == "other", "the switch never completed"


@pytest.mark.asyncio
async def test_a_dead_earshot_monitor_is_rebuilt(trackpoll_testmode):  # pylint: disable=redefined-outer-name
    """EarShot's watcher can die after start() and nothing else would notice.

    It subclasses remote, so it inherits the watcher that dies when another
    observer already holds remotedb, and then stores arriving tracks where
    nobody reads them.
    """
    config = trackpoll_testmode.config
    config.cparser.setValue("settings/input", "pretend")
    started = []
    trackpoll_testmode.plugins = {
        "nowplaying.inputs.pretend": unittest.mock.MagicMock(
            Plugin=_status_plugin(nowplaying.inputs.InputStatus())
        ),
        "nowplaying.inputs.earshot": unittest.mock.MagicMock(
            Plugin=_status_plugin(
                nowplaying.inputs.InputStatus.needs_restart("Stopped watching for tracks."),
                started=started,
            )
        ),
    }

    assert await trackpoll_testmode.switch_input_plugin() is True
    assert len(started) == 1

    for _ in range(10):  # still inside the delay
        await trackpoll_testmode.switch_input_plugin()
    assert len(started) == 1, "rebuilt before the delay elapsed"

    # Arrive at the far side of the wait without sleeping through it.
    trackpoll_testmode._restart_earshot_at = time.monotonic() - 1  # pylint: disable=protected-access
    await trackpoll_testmode.switch_input_plugin()  # drops the dead monitor
    assert trackpoll_testmode.earshot_plugin is None
    await trackpoll_testmode.switch_input_plugin()  # rebuilds it
    assert len(started) == 2, "the dead monitor was never rebuilt"
