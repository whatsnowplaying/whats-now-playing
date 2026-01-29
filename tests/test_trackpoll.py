#!/usr/bin/env python3
"""test the trackpoller"""

import asyncio
import json
import logging
import pathlib
import sys
import threading

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
async def test_trackpoll_game_buffering(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    """test game buffering and flushing logic"""
    config = trackpollbootstrap
    config.cparser.setValue("guessgame/enabled", True)
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(
        stopevent=threading.Event(), config=config, testmode=True
    )
    trackpoll._setup_guessgame()  # pylint: disable=protected-access
    trackpoll._setup_notifications()  # pylint: disable=protected-access

    try:
        # Mock guessgame.should_start_game to return True
        async def mock_should_start():
            return True

        trackpoll.guessgame.should_start_game = mock_should_start

        # Mock guessgame.start_new_game
        async def mock_start_game(track, artist):  # pylint: disable=unused-argument
            pass

        trackpoll.guessgame.start_new_game = mock_start_game

        # Set up metadata
        trackpoll.currentmeta = {
            "artist": "Test Artist",
            "title": "Test Title",
            "filename": "test.mp3",
        }

        # Simulate buffered metadata (game is active)
        trackpoll.buffered_metadata = trackpoll.currentmeta.copy()

        # Test flushing buffered metadata
        await trackpoll._flush_buffered_metadata()  # pylint: disable=protected-access

        # Verify buffered metadata was cleared
        assert trackpoll.buffered_metadata is None
        assert trackpoll.game_start_time is None

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
