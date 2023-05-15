#!/usr/bin/env python3
''' test the trackpoller '''

import asyncio
import json
import logging
import pathlib
import threading

import pytest  # pylint: disable=import-error
import pytest_asyncio  # pylint: disable=import-error

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
    trackpoll = nowplaying.processes.trackpoll.TrackPoll(  # pylint: disable=unused-variable
        stopevent=stopevent, config=config, testmode=True)
    yield config
    stopevent.set()
    await asyncio.sleep(2)


async def write_json_metadata(config, metadata):
    ''' given config and metadata, write a JSONStub input file '''
    txtoutput = config.cparser.value('textoutput/file')
    pathlib.Path(txtoutput).unlink(missing_ok=True)
    filepath = pathlib.Path(config.cparser.value('jsoninput/filename'))
    with open(filepath, "w+", encoding='utf-8') as fhout:
        json.dump(metadata, fhout)
    await asyncio.sleep(5)  # windows is pokey
    logging.debug('waiting for output %s', txtoutput)
    await wait_for_output(txtoutput)


async def wait_for_output(filename):
    ''' wait for the output to appear '''

    # these tests tend to be a bit flaky/racy esp on github
    # runners so add some protection
    counter = 0
    while counter < 10 and not pathlib.Path(filename).exists():
        await asyncio.sleep(5)
        counter += 1
        logging.debug('waiting for %s: %s', filename, counter)
    assert counter < 10


@pytest.mark.asyncio
async def test_trackpoll_basic(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    ''' test basic trackpolling '''

    config = trackpollbootstrap
    template = config.templatedir.joinpath('simple.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    config.cparser.setValue('control/paused', False)
    config.cparser.sync()

    txtoutput = config.cparser.value('textoutput/file')
    await write_json_metadata(config=config, metadata={'artist': 'NIN'})
    with open(txtoutput, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == 'NIN'

    await write_json_metadata(config=config, metadata={'artist': 'NIN', 'title': 'Ghosts'})
    with open(txtoutput, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == 'NIN'
    assert text[1].strip() == 'Ghosts'


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
async def test_trackpoll_nofile(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test trackpoll title has no file '''
    config = trackpollbootstrap
    txtoutput = config.cparser.value('textoutput/file')
    template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    config.cparser.setValue('control/paused', False)
    config.cparser.sync()

    metadata = {'title': 'title', 'artist': 'artist'}
    await write_json_metadata(config=config, metadata=metadata)
    with open(txtoutput, encoding='utf-8') as filein:
        text = filein.readlines()

    assert text[0].strip() == ''
    assert text[1].strip() == 'artist'
    assert text[2].strip() == 'title'


@pytest.mark.asyncio
async def test_trackpoll_badfile(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test trackpoll title has no file '''
    config = trackpollbootstrap
    txtoutput = config.cparser.value('textoutput/file')
    template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    config.cparser.setValue('control/paused', False)
    config.cparser.sync()

    metadata = {'title': 'title', 'artist': 'artist', 'filename': 'completejunk'}
    await write_json_metadata(config=config, metadata=metadata)
    with open(txtoutput, encoding='utf-8') as filein:
        text = filein.readlines()

    assert text[0].strip() == ''
    assert text[1].strip() == 'artist'
    assert text[2].strip() == 'title'
