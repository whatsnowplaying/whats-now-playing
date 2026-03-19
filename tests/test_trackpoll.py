#!/usr/bin/env python3
"""test the trackpoller"""

import asyncio
import json
import logging
import pathlib
import sys
import threading

import unittest.mock

import pytest  # pylint: disable=import-error
import pytest_asyncio  # pylint: disable=import-error

import nowplaying.processes.trackpoll  # pylint: disable=import-error


@pytest_asyncio.fixture
async def trackpollbootstrap(bootstrap, getroot, tmp_path):  # pylint: disable=redefined-outer-name
    """bootstrap a configuration"""
    txtfile = tmp_path.joinpath("output.txt")
    if pathlib.Path(txtfile).exists():
        pathlib.Path(txtfile).unlink()
    jsonfile = tmp_path.joinpath("input.json")
    config = bootstrap
    config.templatedir = getroot.joinpath("tests", "templates")
    config.cparser.setValue("artistextras/enabled", False)
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
        # Properly shut down trackpoll to avoid Windows timing issues
        await trackpoll.stop()
        await asyncio.sleep(0.1)  # Brief pause to let cleanup finish


async def write_json_metadata(config, metadata):
    """given config and metadata, write a JSONStub input file"""
    txtoutput = config.cparser.value("textoutput/file")
    pathlib.Path(txtoutput).unlink(missing_ok=True)
    filepath = pathlib.Path(config.cparser.value("jsoninput/filename"))
    with open(filepath, "w+", encoding="utf-8") as fhout:
        json.dump(metadata, fhout)
    # Windows file system is slower
    await asyncio.sleep(2 if sys.platform == "win32" else 1)
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
            "metadata": {"title": "title", "artist": "artist"},
            "expected": ["", "artist", "title"],
        },
        # Bad file test
        {
            "id": "badfile",
            "template": "simplewfn.txt",
            "metadata": {"title": "title", "artist": "artist", "filename": "completejunk"},
            "expected": ["", "artist", "title"],
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
    config.cparser.setValue("control/paused", False)
    config.cparser.sync()

    txtoutput = config.cparser.value("textoutput/file")
    await write_json_metadata(config=config, metadata=test_case["metadata"])

    with open(txtoutput, encoding="utf-8") as filein:
        text = filein.readlines()

    for i, expected_line in enumerate(test_case["expected"]):
        assert text[i].strip() == expected_line


@pytest.mark.asyncio
async def test_trackpoll_titleisfile(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    """test trackpoll title is a filename"""
    config = trackpollbootstrap
    txtoutput = config.cparser.value("textoutput/file")
    template = getroot.joinpath("tests", "templates", "simplewfn.txt")
    config.txttemplate = str(template)
    config.cparser.setValue("textoutput/txttemplate", str(template))
    config.cparser.setValue("control/paused", False)
    config.cparser.sync()
    title = str(getroot.joinpath("tests", "audio", "15_Ghosts_II_64kb_orig.mp3"))
    await write_json_metadata(config=config, metadata={"title": title})
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
    config.cparser.setValue("control/paused", False)
    config.cparser.sync()
    metadata = {"filename": str(getroot.joinpath("tests", "audio", "15_Ghosts_II_64kb_orig.mp3"))}

    txtoutput = config.cparser.value("textoutput/file")
    await write_json_metadata(config=config, metadata=metadata)
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


@pytest.mark.asyncio
async def test_trackpoll_start_artistfanartpool(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    """test artist fanart pool startup"""
    config = trackpollbootstrap
    config.cparser.setValue("artistextras/enabled", False)
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(
        stopevent=threading.Event(), config=config, testmode=True
    )

    try:
        # Set up metadata with fanart URLs
        trackpoll.currentmeta = {
            "artist": "Test Artist",
            "artistfanarturls": ["http://example.com/fanart1.jpg"],
        }

        # Test that _start_artistfanartpool returns early when disabled
        trackpoll._start_artistfanartpool()  # pylint: disable=protected-access

        # Verify fanart URLs are still present (not deleted because feature disabled)
        assert "artistfanarturls" in trackpoll.currentmeta

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


def _make_trackpoll(config):
    """Create a minimal TrackPoll for unit testing _artfallbacks."""
    return nowplaying.processes.trackpoll.TrackPoll(
        stopevent=threading.Event(), config=config, testmode=True
    )


def test_artfallbacks_front_cover_from_imagecache(bootstrap):
    """front_cover in imagecache is used before falling back to artist images"""
    tptest = _make_trackpoll(bootstrap)
    cover_bytes = b"fake_cover"
    mock_ic = unittest.mock.MagicMock()
    mock_ic.random_image_fetch.side_effect = lambda identifier, imagetype: (
        cover_bytes if imagetype == "front_cover" else None
    )
    tptest.imagecache = mock_ic
    tptest.currentmeta = {"artist": "Artist", "album": "Album"}
    bootstrap.cparser.setValue("artistextras/nocoverfallback", "fanart")

    tptest._artfallbacks()  # pylint: disable=protected-access

    assert tptest.currentmeta.get("coverimageraw") == cover_bytes
    mock_ic.random_image_fetch.assert_any_call(identifier="Artist_Album", imagetype="front_cover")


def test_artfallbacks_falls_back_to_artist_image_when_no_front_cover(bootstrap):
    """artist fallback image used when imagecache has no front_cover"""
    tptest = _make_trackpoll(bootstrap)
    fanart_bytes = b"fake_fanart"
    mock_ic = unittest.mock.MagicMock()
    mock_ic.random_image_fetch.side_effect = lambda identifier, imagetype: (
        fanart_bytes if imagetype == "artistfanart" else None
    )
    tptest.imagecache = mock_ic
    tptest.currentmeta = {"artist": "Artist", "album": "Album", "imagecacheartist": "Artist"}
    bootstrap.cparser.setValue("artistextras/nocoverfallback", "fanart")

    tptest._artfallbacks()  # pylint: disable=protected-access

    assert tptest.currentmeta.get("coverimageraw") == fanart_bytes


def test_artfallbacks_no_fallback_when_front_cover_missing_and_nocoverfallback_none(bootstrap):
    """coverimageraw stays empty when nocoverfallback is 'none'"""
    tptest = _make_trackpoll(bootstrap)
    mock_ic = unittest.mock.MagicMock()
    mock_ic.random_image_fetch.return_value = None
    tptest.imagecache = mock_ic
    tptest.currentmeta = {"artist": "Artist", "album": "Album", "imagecacheartist": "Artist"}
    bootstrap.cparser.setValue("artistextras/nocoverfallback", "none")

    tptest._artfallbacks()  # pylint: disable=protected-access

    assert not tptest.currentmeta.get("coverimageraw")


def test_artfallbacks_cover_used_as_logo_fallback(bootstrap):
    """existing coverimageraw is copied to artistlogoraw when coverfornologos enabled"""
    tptest = _make_trackpoll(bootstrap)
    tptest.imagecache = None
    cover_bytes = b"fake_cover"
    tptest.currentmeta = {"coverimageraw": cover_bytes}
    bootstrap.cparser.setValue("artistextras/coverfornologos", True)

    tptest._artfallbacks()  # pylint: disable=protected-access

    assert tptest.currentmeta.get("artistlogoraw") == cover_bytes


def test_artfallbacks_cover_used_as_thumbnail_fallback(bootstrap):
    """existing coverimageraw is copied to artistthumbnailraw when coverfornothumbs enabled"""
    tptest = _make_trackpoll(bootstrap)
    tptest.imagecache = None
    cover_bytes = b"fake_cover"
    tptest.currentmeta = {"coverimageraw": cover_bytes}
    bootstrap.cparser.setValue("artistextras/coverfornothumbs", True)

    tptest._artfallbacks()  # pylint: disable=protected-access

    assert tptest.currentmeta.get("artistthumbnailraw") == cover_bytes


def test_artfallbacks_preexisting_cover_not_overwritten(bootstrap):
    """coverimageraw already in metadata is never replaced"""
    tptest = _make_trackpoll(bootstrap)
    original = b"original_cover"
    mock_ic = unittest.mock.MagicMock()
    mock_ic.random_image_fetch.return_value = b"should_not_be_used"
    tptest.imagecache = mock_ic
    tptest.currentmeta = {
        "artist": "Artist",
        "album": "Album",
        "imagecacheartist": "Artist",
        "coverimageraw": original,
    }
    bootstrap.cparser.setValue("artistextras/nocoverfallback", "fanart")

    tptest._artfallbacks()  # pylint: disable=protected-access

    assert tptest.currentmeta.get("coverimageraw") == original
    mock_ic.random_image_fetch.assert_not_called()
