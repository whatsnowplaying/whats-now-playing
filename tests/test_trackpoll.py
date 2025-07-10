#!/usr/bin/env python3
''' test the trackpoller '''

import asyncio
import json
import logging
import pathlib
import sys
import threading

import pytest  # pylint: disable=import-error
import pytest_asyncio  # pylint: disable=import-error
from aioresponses import aioresponses

import nowplaying.processes.trackpoll  # pylint: disable=import-error


@pytest_asyncio.fixture
async def trackpollbootstrap(bootstrap, getroot, tmp_path):  # pylint: disable=redefined-outer-name
    ''' bootstrap a configuration '''
    txtfile = tmp_path.joinpath('output.txt')
    if pathlib.Path(txtfile).exists():
        pathlib.Path(txtfile).unlink()
    jsonfile = tmp_path.joinpath('input.json')
    config = bootstrap
    config.templatedir = getroot.joinpath('tests', 'templates')
    config.cparser.setValue('artistextras/enabled', False)
    config.cparser.setValue('control/paused', True)
    config.cparser.setValue('settings/input', 'jsonreader')
    config.cparser.setValue('jsoninput/delay', 1)
    config.cparser.setValue('jsoninput/filename', str(jsonfile))
    config.cparser.setValue('textoutput/file', str(txtfile))
    stopevent = threading.Event()
    logging.debug('output = %s', txtfile)
    config.cparser.sync()
    trackpoll = nowplaying.processes.trackpoll.TrackPoll(stopevent=stopevent,
                                                         config=config,
                                                         testmode=True)
    try:
        yield config
    finally:
        # Properly shut down trackpoll to avoid Windows timing issues
        await trackpoll.stop()
        await asyncio.sleep(0.1)  # Brief pause to let cleanup finish


async def write_json_metadata(config, metadata):
    ''' given config and metadata, write a JSONStub input file '''
    txtoutput = config.cparser.value('textoutput/file')
    pathlib.Path(txtoutput).unlink(missing_ok=True)
    filepath = pathlib.Path(config.cparser.value('jsoninput/filename'))
    with open(filepath, "w+", encoding='utf-8') as fhout:
        json.dump(metadata, fhout)
    # Windows file system is slower
    await asyncio.sleep(2 if sys.platform == 'win32' else 1)
    logging.debug('waiting for output %s', txtoutput)
    await wait_for_output(txtoutput)


async def wait_for_output(filename):
    ''' wait for the output to appear '''

    # these tests tend to be a bit flaky/racy esp on github
    # runners so add some protection
    counter = 0
    sleep_time = 2 if sys.platform == 'win32' else 1
    max_attempts = 10 if sys.platform == 'win32' else 15  # Reasonable polling for all platforms
    while counter < max_attempts and not pathlib.Path(filename).exists():
        await asyncio.sleep(sleep_time)
        counter += 1
        logging.debug('waiting for %s: %s', filename, counter)
    assert pathlib.Path(filename).exists(), f"File {filename} not created after {counter} attempts"


@pytest.mark.parametrize(
    "test_case",
    [
        # Basic trackpolling test
        {
            "id": "basic_single",
            "template": "simple.txt",
            "metadata": {
                'artist': 'NIN'
            },
            "expected": ['NIN']
        },
        {
            "id": "basic_double",
            "template": "simple.txt",
            "metadata": {
                'artist': 'NIN',
                'title': 'Ghosts'
            },
            "expected": ['NIN', 'Ghosts']
        },
        # No file test
        {
            "id": "nofile",
            "template": "simplewfn.txt",
            "metadata": {
                'title': 'title',
                'artist': 'artist'
            },
            "expected": ['', 'artist', 'title']
        },
        # Bad file test
        {
            "id": "badfile",
            "template": "simplewfn.txt",
            "metadata": {
                'title': 'title',
                'artist': 'artist',
                'filename': 'completejunk'
            },
            "expected": ['', 'artist', 'title']
        }
    ])
@pytest.mark.asyncio
async def test_trackpoll_scenarios(trackpollbootstrap, getroot, test_case):  # pylint: disable=redefined-outer-name
    ''' test various trackpolling scenarios '''
    config = trackpollbootstrap

    # Set up template
    if test_case["template"] == "simple.txt":
        template = config.templatedir.joinpath('simple.txt')
    else:
        template = getroot.joinpath('tests', 'templates', test_case["template"])

    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    config.cparser.setValue('control/paused', False)
    config.cparser.sync()

    txtoutput = config.cparser.value('textoutput/file')
    await write_json_metadata(config=config, metadata=test_case["metadata"])

    with open(txtoutput, encoding='utf-8') as filein:
        text = filein.readlines()

    for i, expected_line in enumerate(test_case["expected"]):
        assert text[i].strip() == expected_line


@pytest.mark.asyncio
async def test_trackpoll_titleisfile(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test trackpoll title is a filename '''
    config = trackpollbootstrap
    txtoutput = config.cparser.value('textoutput/file')
    template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    config.cparser.setValue('control/paused', False)
    config.cparser.sync()
    title = str(getroot.joinpath('tests', 'audio', '15_Ghosts_II_64kb_orig.mp3'))
    await write_json_metadata(config=config, metadata={'title': title})
    with open(txtoutput, encoding='utf-8') as filein:
        text = filein.readlines()

    assert text[0].strip() == title
    assert text[1].strip() == 'Nine Inch Nails'
    assert text[2].strip() == '15 Ghosts II'


@pytest.mark.asyncio
async def test_trackpoll_metadata(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test trackpolling + metadata + input override '''
    config = trackpollbootstrap
    template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    config.cparser.setValue('control/paused', False)
    config.cparser.sync()
    metadata = {'filename': str(getroot.joinpath('tests', 'audio', '15_Ghosts_II_64kb_orig.mp3'))}

    txtoutput = config.cparser.value('textoutput/file')
    await write_json_metadata(config=config, metadata=metadata)
    with open(txtoutput, encoding='utf-8') as filein:
        text = filein.readlines()

    assert text[0].strip() == metadata['filename']
    assert text[1].strip() == 'Nine Inch Nails'
    assert text[2].strip() == '15 Ghosts II'

    metadata['artist'] = 'NIN'

    await write_json_metadata(config=config, metadata=metadata)
    with open(txtoutput, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == metadata['filename']
    assert text[1].strip() == 'NIN'
    assert text[2].strip() == '15 Ghosts II'

    metadata['title'] = 'Ghosts'
    del metadata['artist']
    await write_json_metadata(config=config, metadata=metadata)
    await wait_for_output(txtoutput)
    with open(txtoutput, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == metadata['filename']
    assert text[1].strip() == 'Nine Inch Nails'
    assert text[2].strip() == 'Ghosts'


@pytest.mark.asyncio
async def test_trackpoll_write_to_remote_disabled(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    ''' test _write_to_remote when remote is disabled '''
    config = trackpollbootstrap
    config.cparser.setValue('remote/enabled', False)
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(stopevent=threading.Event(),
                                                         config=config,
                                                         testmode=True)

    try:
        # Should do nothing when remote is disabled
        await trackpoll._write_to_remote()  # pylint: disable=protected-access
    finally:
        # Properly cleanup to avoid Windows timing issues
        await trackpoll.stop()


@pytest.mark.asyncio
async def test_trackpoll_write_to_remote_no_secret(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    ''' test _write_to_remote without secret configured '''
    config = trackpollbootstrap
    config.cparser.setValue('remote/enabled', True)
    config.cparser.setValue('remote/remote_server', 'localhost')
    config.cparser.setValue('remote/remote_port', 8899)
    config.cparser.setValue('remote/remote_key', '')  # No secret
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(stopevent=threading.Event(),
                                                         config=config,
                                                         testmode=True)

    try:
        trackpoll.currentmeta = {
            'artist': 'Test Artist',
            'title': 'Test Title',
            'filename': 'test.mp3'
        }

        with aioresponses() as mock_resp:
            mock_resp.post('http://localhost:8899/v1/remoteinput', payload={'dbid': 123})

            await trackpoll._write_to_remote()  # pylint: disable=protected-access

            # Verify the request was made - aioresponses automatically validates the URL and method
    finally:
        # Properly cleanup to avoid Windows timing issues
        await trackpoll.stop()


@pytest.mark.asyncio
async def test_trackpoll_write_to_remote_with_secret(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    ''' test _write_to_remote with secret configured '''
    config = trackpollbootstrap
    config.cparser.setValue('remote/enabled', True)
    config.cparser.setValue('remote/remote_server', 'localhost')
    config.cparser.setValue('remote/remote_port', 8899)
    config.cparser.setValue('remote/remote_key', 'test_secret_123')
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(stopevent=threading.Event(),
                                                         config=config,
                                                         testmode=True)

    try:
        trackpoll.currentmeta = {
            'artist': 'Test Artist',
            'title': 'Test Title',
            'filename': 'test.mp3'
        }

        with aioresponses() as mock_resp:
            mock_resp.post('http://localhost:8899/v1/remoteinput', payload={'dbid': 456})

            await trackpoll._write_to_remote()  # pylint: disable=protected-access

            # Verify the request was made - aioresponses automatically validates the URL and method
    finally:
        # Properly cleanup to avoid Windows timing issues
        await trackpoll.stop()


@pytest.mark.asyncio
async def test_trackpoll_write_to_remote_auth_failure(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    ''' test _write_to_remote with authentication failure '''
    config = trackpollbootstrap
    config.cparser.setValue('remote/enabled', True)
    config.cparser.setValue('remote/remote_server', 'localhost')
    config.cparser.setValue('remote/remote_port', 8899)
    config.cparser.setValue('remote/remote_key', 'test_secret')
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(stopevent=threading.Event(),
                                                         config=config,
                                                         testmode=True)

    try:
        trackpoll.currentmeta = {'artist': 'Test Artist', 'title': 'Test Title'}

        with aioresponses() as mock_resp:
            mock_resp.post('http://localhost:8899/v1/remoteinput',
                           status=403,
                           payload={'error': 'Invalid secret'})

            # Should handle auth failure gracefully
            await trackpoll._write_to_remote()  # pylint: disable=protected-access
    finally:
        # Properly cleanup to avoid Windows timing issues
        await trackpoll.stop()


@pytest.mark.asyncio
async def test_trackpoll_write_to_remote_server_error(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    ''' test _write_to_remote with server error '''
    config = trackpollbootstrap
    config.cparser.setValue('remote/enabled', True)
    config.cparser.setValue('remote/remote_server', 'localhost')
    config.cparser.setValue('remote/remote_port', 8899)
    config.cparser.setValue('remote/remote_key', '')
    config.cparser.sync()

    trackpoll = nowplaying.processes.trackpoll.TrackPoll(stopevent=threading.Event(),
                                                         config=config,
                                                         testmode=True)

    try:
        trackpoll.currentmeta = {'artist': 'Test Artist', 'title': 'Test Title'}

        with aioresponses() as mock_resp:
            mock_resp.post('http://localhost:8899/v1/remoteinput',
                           status=500,
                           payload={'error': 'Internal server error'})

            # Should handle server error gracefully
            await trackpoll._write_to_remote()  # pylint: disable=protected-access
    finally:
        # Properly cleanup to avoid Windows timing issues
        await trackpoll.stop()
