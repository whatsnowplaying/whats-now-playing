#!/usr/bin/env python3
''' test the trackpoller '''

import logging
import pathlib

import pytest

from PySide6.QtCore import QThread  # pylint: disable=no-name-in-module

import nowplaying.trackpoll  # pylint: disable=import-error
import nowplaying.inputs  # pylint: disable=import-error

ARTIST = None
FILENAME = None
TITLE = None


@pytest.fixture
def trackpollbootstrap(bootstrap, tmp_path):  # pylint: disable=redefined-outer-name
    ''' bootstrap a configuration '''
    txtfile = tmp_path.joinpath('output.txt')
    if pathlib.Path(txtfile).exists():
        pathlib.Path(txtfile).unlink()
    config = bootstrap
    config.cparser.setValue('textoutput/file', str(txtfile))
    config.cparser.setValue('artistextras/enabled', False)
    config.file = str(txtfile)
    config.cparser.sync()
    yield config


class InputStub(nowplaying.inputs.InputPlugin):
    ''' stupid input plugin '''

    def start(self):
        ''' dummy start '''

    def stop(self):
        ''' dummy stop '''

    def getplayingtrack(self):  # pylint: disable=no-self-use
        ''' dummy meta -> just return globals '''
        return {'artist': ARTIST, 'filename': FILENAME, 'title': TITLE}


def wait_for_output(filename):
    ''' wait for the output to appear '''

    # these tests tend to be a bit flaky/racy esp on github
    # runners so add some protection
    QThread.msleep(2000)
    counter = 0
    while counter < 5 and not pathlib.Path(filename).exists():
        QThread.msleep(2000)
        counter += 1
        logging.debug('waiting for %s: %s', filename, counter)
    assert counter < 5


def tracknotify(metadata):
    ''' log what trackpoll meta notified with. do more in the future '''
    logging.debug(metadata)


def test_trackpoll1a(trackpollbootstrap):  # pylint: disable=redefined-outer-name
    ''' see if the thread starts and stops '''
    config = trackpollbootstrap
    config.cparser.setValue('settings/input', 'InputStub')
    trackthread = nowplaying.trackpoll.TrackPoll(testmode=True,
                                                 inputplugin=InputStub(),
                                                 config=config)
    trackthread.currenttrack[dict].connect(tracknotify)
    trackthread.start()
    trackthread.endthread = True
    trackthread.wait()


def test_trackpoll_startstop(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' see if the thread starts and stops '''
    config = trackpollbootstrap
    config.cparser.setValue('settings/input', 'InputStub')
    template = getroot.joinpath('tests', 'templates', 'simple.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    trackthread = nowplaying.trackpoll.TrackPoll(testmode=True,
                                                 inputplugin=InputStub(),
                                                 config=config)
    trackthread.currenttrack[dict].connect(tracknotify)
    trackthread.start()
    QThread.msleep(1000)
    trackthread.endthread = True
    trackthread.wait()


def test_trackpoll_basic(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test basic trackpolling '''
    global ARTIST, FILENAME, TITLE  # pylint: disable=global-statement

    config = trackpollbootstrap
    config.cparser.setValue('settings/input', 'InputStub')
    template = getroot.joinpath('tests', 'templates', 'simple.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    FILENAME = 'randomfile'
    trackthread = nowplaying.trackpoll.TrackPoll(testmode=True,
                                                 inputplugin=InputStub(),
                                                 config=config)
    trackthread.currenttrack[dict].connect(tracknotify)
    trackthread.start()

    QThread.msleep(2000)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()

    assert text[0].strip() == ''

    ARTIST = 'NIN'
    wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == 'NIN'

    TITLE = 'Ghosts'
    wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == 'NIN'
    assert text[1].strip() == 'Ghosts'

    trackthread.endthread = True
    trackthread.wait()

    ARTIST = FILENAME = TITLE = None


def test_trackpoll_metadata(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test trackpolling + metadata + input override '''
    global ARTIST, FILENAME, TITLE  # pylint: disable=global-statement

    config = trackpollbootstrap
    config.cparser.setValue('settings/input', 'InputStub')
    template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    FILENAME = str(
        getroot.joinpath('tests', 'audio', '15_Ghosts_II_64kb_orig.mp3'))
    trackthread = nowplaying.trackpoll.TrackPoll(testmode=True,
                                                 inputplugin=InputStub(),
                                                 config=config)
    trackthread.currenttrack[dict].connect(tracknotify)
    trackthread.start()

    wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()

    assert text[0].strip() == FILENAME
    assert text[1].strip() == 'Nine Inch Nails'
    assert text[2].strip() == '15 Ghosts II'

    ARTIST = 'NIN'
    QThread.msleep(2000)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == FILENAME
    assert text[1].strip() == 'NIN'
    assert text[2].strip() == '15 Ghosts II'

    ARTIST = None
    TITLE = 'Ghosts'
    wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()
    assert text[0].strip() == FILENAME
    assert text[1].strip() == 'Nine Inch Nails'
    assert text[2].strip() == 'Ghosts'

    trackthread.endthread = True
    trackthread.wait()

    ARTIST = FILENAME = TITLE = None


def test_trackpoll_titleisfile(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test trackpoll title is a filename '''
    global ARTIST, FILENAME, TITLE  # pylint: disable=global-statement

    config = trackpollbootstrap
    config.cparser.setValue('settings/input', 'InputStub')
    template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    TITLE = str(
        getroot.joinpath('tests', 'audio', '15_Ghosts_II_64kb_orig.mp3'))
    trackthread = nowplaying.trackpoll.TrackPoll(testmode=True,
                                                 inputplugin=InputStub(),
                                                 config=config)
    trackthread.currenttrack[dict].connect(tracknotify)
    trackthread.start()

    wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()

    assert text[0].strip() == TITLE
    assert text[1].strip() == 'Nine Inch Nails'
    assert text[2].strip() == '15 Ghosts II'

    trackthread.endthread = True
    trackthread.wait()

    ARTIST = FILENAME = TITLE = None


def test_trackpoll_nofile(trackpollbootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test trackpoll title is a filename '''
    global ARTIST, FILENAME, TITLE  # pylint: disable=global-statement

    config = trackpollbootstrap
    config.cparser.setValue('settings/input', 'InputStub')
    template = getroot.joinpath('tests', 'templates', 'simplewfn.txt')
    config.txttemplate = str(template)
    config.cparser.setValue('textoutput/txttemplate', str(template))
    TITLE = 'title'
    ARTIST = 'artist'
    trackthread = nowplaying.trackpoll.TrackPoll(testmode=True,
                                                 inputplugin=InputStub(),
                                                 config=config)
    trackthread.currenttrack[dict].connect(tracknotify)
    trackthread.start()

    wait_for_output(config.file)
    with open(config.file, encoding='utf-8') as filein:
        text = filein.readlines()

    assert text[0].strip() == ''
    assert text[1].strip() == 'artist'
    assert text[2].strip() == 'title'

    trackthread.endthread = True
    trackthread.wait()

    ARTIST = FILENAME = TITLE = None
