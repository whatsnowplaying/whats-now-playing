#!/usr/bin/env python3
''' test the trackpoller '''

import json
import multiprocessing
import logging
import pathlib
import time

import pytest

import nowplaying.trackpoll  # pylint: disable=import-error


@pytest.fixture
def trackpollbootstrap(bootstrap, getroot, tmp_path):  # pylint: disable=redefined-outer-name
    ''' bootstrap a configuration '''
    txtfile = tmp_path.joinpath('output.txt')
    if pathlib.Path(txtfile).exists():
        pathlib.Path(txtfile).unlink()
    jsonfile = tmp_path.joinpath('input.json')
    config = bootstrap
    config.templatedir = getroot.joinpath('tests', 'templates')
    config.cparser.setValue('artistextras/enabled', False)
    config.cparser.setValue('control/paused', True)
    config.cparser.setValue('settings/input', 'json')
    config.cparser.setValue('jsoninput/delay', 1)
    config.cparser.setValue('jsoninput/filename', str(jsonfile))
    config.cparser.setValue('textoutput/file', str(txtfile))
    config.file = str(txtfile)

    logging.debug('output = %s', txtfile)
    config.cparser.sync()
    trackpoll = multiprocessing.Process(target=nowplaying.trackpoll.start,
                                        name='TrackProcess',
                                        args=(
                                            config.BUNDLEDIR,
                                            True,
                                        ))
    trackpoll.start()
    yield config
    if trackpoll:
        nowplaying.trackpoll.stop(trackpoll.pid)
        if not trackpoll.join(5):
            trackpoll.terminate()
        trackpoll.join(5)
        trackpoll.close()
        trackpoll = None


def wait_for_output(filename):
    ''' wait for the output to appear '''

    # these tests tend to be a bit flaky/racy esp on github
    # runners so add some protection
    time.sleep(5)
    counter = 0
    while counter < 10 and not pathlib.Path(filename).exists():
        time.sleep(5)
        counter += 1
        logging.debug('waiting for %s: %s', filename, counter)
    assert counter < 10


def test_trackpoll_basic(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    ''' test basic trackpolling '''

    config = trackpollbootstrap
    template = config.templatedir.joinpath('simple.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    config.cparser.setValue('control/paused', False)
    config.cparser.sync()
    filepath = pathlib.Path(config.cparser.value('jsoninput/filename'))

    metadata = {'artist': 'NIN', 'title': 'Ghosts'}

    with open(filepath, "w+", encoding='utf-8') as fhout:
        json.dump(metadata, fhout)

    # ARTIST = 'NIN'
    # wait_for_output(config.file)
    # with open(config.file, encoding='utf-8') as filein:
    #     text = filein.readlines()
    # assert text[0].strip() == 'NIN'

    # TITLE = 'Ghosts'
    wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == 'NIN'
    assert text[1].strip() == 'Ghosts'


# def test_trackpoll_metadata(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
#     ''' test trackpolling + metadata + input override '''
#     global ARTIST, FILENAME, TITLE  # pylint: disable=global-statement

#     config = trackpollbootstrap
#     config.cparser.setValue('settings/input', 'InputStub')
#     template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
#     config.txttemplate = str(template)
#     config.cparser.setValue('textoutput/txttemplate', str(template))
#     FILENAME = str(
#         getroot.joinpath('tests', 'audio', '15_Ghosts_II_64kb_orig.mp3'))
#     trackthread = nowplaying.trackpoll.TrackPoll(testmode=True,
#                                                  inputplugin=InputStub(),
#                                                  config=config)
#     trackthread.currenttrack[dict].connect(tracknotify)
#     trackthread.start()

#     wait_for_output(config.file)
#     with open(config.file, encoding='utf-8') as filein:
#         text = filein.readlines()

#     assert text[0].strip() == FILENAME
#     assert text[1].strip() == 'Nine Inch Nails'
#     assert text[2].strip() == '15 Ghosts II'

#     ARTIST = 'NIN'
#     QThread.msleep(2000)
#     with open(config.file, encoding='utf-8') as filein:
#         text = filein.readlines()
#     assert text[0].strip() == FILENAME
#     assert text[1].strip() == 'NIN'
#     assert text[2].strip() == '15 Ghosts II'

#     ARTIST = None
#     TITLE = 'Ghosts'
#     wait_for_output(config.file)
#     with open(config.file, encoding='utf-8') as filein:
#         text = filein.readlines()
#     assert text[0].strip() == FILENAME
#     assert text[1].strip() == 'Nine Inch Nails'
#     assert text[2].strip() == 'Ghosts'

#     trackthread.endthread = True
#     trackthread.wait()

#     ARTIST = FILENAME = TITLE = None

# def test_trackpoll_titleisfile(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
#     ''' test trackpoll title is a filename '''
#     global ARTIST, FILENAME, TITLE  # pylint: disable=global-statement

#     config = trackpollbootstrap
#     config.cparser.setValue('settings/input', 'InputStub')
#     template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
#     config.txttemplate = str(template)
#     config.cparser.setValue('textoutput/txttemplate', str(template))
#     TITLE = str(
#         getroot.joinpath('tests', 'audio', '15_Ghosts_II_64kb_orig.mp3'))
#     trackthread = nowplaying.trackpoll.TrackPoll(testmode=True,
#                                                  inputplugin=InputStub(),
#                                                  config=config)
#     trackthread.currenttrack[dict].connect(tracknotify)
#     trackthread.start()

#     wait_for_output(config.file)
#     with open(config.file, encoding='utf-8') as filein:
#         text = filein.readlines()

#     assert text[0].strip() == TITLE
#     assert text[1].strip() == 'Nine Inch Nails'
#     assert text[2].strip() == '15 Ghosts II'

#     trackthread.endthread = True
#     trackthread.wait()

#     ARTIST = FILENAME = TITLE = None

# def test_trackpoll_nofile(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
#     ''' test trackpoll title is a filename '''
#     global ARTIST, FILENAME, TITLE  # pylint: disable=global-statement

#     config = trackpollbootstrap
#     config.cparser.setValue('settings/input', 'InputStub')
#     template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
#     config.txttemplate = str(template)
#     config.cparser.setValue('textoutput/txttemplate', str(template))
#     TITLE = 'title'
#     ARTIST = 'artist'
#     trackthread = nowplaying.trackpoll.TrackPoll(testmode=True,
#                                                  inputplugin=InputStub(),
#                                                  config=config)
#     trackthread.currenttrack[dict].connect(tracknotify)
#     trackthread.start()

#     wait_for_output(config.file)
#     with open(config.file, encoding='utf-8') as filein:
#         text = filein.readlines()

#     assert text[0].strip() == ''
#     assert text[1].strip() == 'artist'
#     assert text[2].strip() == 'title'

#     trackthread.endthread = True
#     trackthread.wait()

#     ARTIST = FILENAME = TITLE = None
