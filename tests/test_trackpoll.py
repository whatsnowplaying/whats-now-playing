#!/usr/bin/env python3
''' test the trackpoller '''

import asyncio
import logging
import pathlib

import pytest

import nowplaying.trackpoll  # pylint: disable=import-error
import nowplaying.inputs  # pylint: disable=import-error

ARTIST = None
FILENAME = None
TITLE = None


@pytest.fixture
async def trackpollbootstrap(bootstrap, tmp_path):  # pylint: disable=redefined-outer-name
    ''' bootstrap a configuration '''
    txtfile = tmp_path.joinpath('output.txt')
    if pathlib.Path(txtfile).exists():
        pathlib.Path(txtfile).unlink()
    config = bootstrap
    config.cparser.setValue('textoutput/file', str(txtfile))
    config.file = str(txtfile)
    config.cparser.sync()
    event = asyncio.Event()
    yield config, event
    event.set()


class InputStub(nowplaying.inputs.InputPlugin):
    ''' stupid input plugin '''

    def start(self):
        ''' dummy start '''

    def stop(self):
        ''' dummy stop '''

    def getplayingtrack(self):  # pylint: disable=no-self-use
        ''' dummy meta -> just return globals '''
        return {'artist': ARTIST, 'filename': FILENAME, 'title': TITLE}


async def wait_for_output(filename):
    ''' wait for the output to appear '''

    # these tests tend to be a bit flaky/racy esp on github
    # runners so add some protection
    await asyncio.sleep(5)
    counter = 0
    while (not pathlib.Path(filename).exists()) or counter > 5:
        await asyncio.sleep(5)
        counter += 1
        logging.debug('waiting for %s: %s', filename, counter)
    assert counter < 6


async def stop_trackpoll(event, trackthread):
    ''' trigger the event to stop the trackpoll '''
    await asyncio.sleep(5)
    event.set()
    await asyncio.sleep(5)
    assert len(trackthread.tasks) == 0


@pytest.mark.asyncio
async def test_trackpoll_startstop(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' see if the thread starts and stops '''
    config, event = trackpollbootstrap
    config.cparser.setValue('settings/input', 'InputStub')
    template = getroot.joinpath('tests', 'templates', 'simple.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    trackthread = nowplaying.trackpoll.TrackPoll(event,
                                                 testmode=True,
                                                 inputplugin=InputStub(),
                                                 config=config)
    await stop_trackpoll(event, trackthread)


@pytest.mark.asyncio
async def test_trackpoll_basic(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test basic trackpolling '''
    global ARTIST, FILENAME, TITLE  # pylint: disable=global-statement

    config, event = trackpollbootstrap
    config.cparser.setValue('settings/input', 'InputStub')
    template = getroot.joinpath('tests', 'templates', 'simple.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    FILENAME = 'randomfile'
    trackthread = nowplaying.trackpoll.TrackPoll(event,
                                                 testmode=True,
                                                 inputplugin=InputStub(),
                                                 config=config)

    await asyncio.sleep(5)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()

    assert text[0].strip() == ''

    ARTIST = 'NIN'
    await wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == 'NIN'

    TITLE = 'Ghosts'
    await wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == 'NIN'
    assert text[1].strip() == 'Ghosts'

    await stop_trackpoll(event, trackthread)

    ARTIST = FILENAME = TITLE = None


@pytest.mark.asyncio
async def test_trackpoll_metadata(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test trackpolling + metadata + input override '''
    global ARTIST, FILENAME, TITLE  # pylint: disable=global-statement

    config, event = trackpollbootstrap
    config.cparser.setValue('settings/input', 'InputStub')
    template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    FILENAME = str(
        getroot.joinpath('tests', 'audio', '15_Ghosts_II_64kb_orig.mp3'))
    trackthread = nowplaying.trackpoll.TrackPoll(event,
                                                 testmode=True,
                                                 inputplugin=InputStub(),
                                                 config=config)

    await wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()

    assert text[0].strip() == FILENAME
    assert text[1].strip() == 'Nine Inch Nails'
    assert text[2].strip() == '15 Ghosts II'

    ARTIST = 'NIN'
    await asyncio.sleep(5)

    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == FILENAME
    assert text[1].strip() == 'NIN'
    assert text[2].strip() == '15 Ghosts II'

    ARTIST = None
    TITLE = 'Ghosts'

    await wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == FILENAME
    assert text[1].strip() == 'Nine Inch Nails'
    assert text[2].strip() == 'Ghosts'

    await stop_trackpoll(event, trackthread)

    ARTIST = FILENAME = TITLE = None


@pytest.mark.asyncio
async def test_trackpoll_titleisfile(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test trackpoll title is a filename '''
    global ARTIST, FILENAME, TITLE  # pylint: disable=global-statement

    config, event = trackpollbootstrap
    config.cparser.setValue('settings/input', 'InputStub')
    template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    TITLE = str(
        getroot.joinpath('tests', 'audio', '15_Ghosts_II_64kb_orig.mp3'))
    trackthread = nowplaying.trackpoll.TrackPoll(event,
                                                 testmode=True,
                                                 inputplugin=InputStub(),
                                                 config=config)

    await wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()

    assert text[0].strip() == TITLE
    assert text[1].strip() == 'Nine Inch Nails'
    assert text[2].strip() == '15 Ghosts II'

    await stop_trackpoll(event, trackthread)

    ARTIST = FILENAME = TITLE = None


@pytest.mark.asyncio
async def test_trackpoll_nofile(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test trackpoll title is a filename '''
    global ARTIST, FILENAME, TITLE  # pylint: disable=global-statement

    config, event = trackpollbootstrap
    config.cparser.setValue('settings/input', 'InputStub')
    template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    TITLE = 'title'
    ARTIST = 'artist'
    trackthread = nowplaying.trackpoll.TrackPoll(event,
                                                 testmode=True,
                                                 inputplugin=InputStub(),
                                                 config=config)

    await wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()

    assert text[0].strip() == ''
    assert text[1].strip() == 'artist'
    assert text[2].strip() == 'title'

    await stop_trackpoll(event, trackthread)

    ARTIST = FILENAME = TITLE = None
