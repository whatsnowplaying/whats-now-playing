#!/usr/bin/env python3
''' test acoustid '''

import os

import logging
import logging.config
import logging.handlers

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.config  # pylint: disable=import-error
import nowplaying.musicbrainz  # pylint: disable=import-error


def bootstrap():
    ''' bootstrap test '''
    bundledir = os.path.abspath(os.path.dirname(__file__))
    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names(appname='testsuite')
    # need to make sure config is initialized with something
    config = nowplaying.config.ConfigFile(bundledir=bundledir, testmode=True)
    config.cparser.setValue('acoustidmb/enabled', True)
    config.cparser.setValue('acoustidmb/emailaddress',
                            'aw+wnptest@effectivemachines.com')
    return config


def test_15ghosts2_orig():
    ''' automated integration test '''
    config = bootstrap()
    mbhelper = nowplaying.musicbrainz.MusicBrainzHelper(config=config)
    metadata = mbhelper.recordingid('2d7f08e1-be1c-4b86-b725-6e675b7b6de0')
    config.cparser.clear()
    assert metadata['album'] == 'Ghosts I–IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['date'] == '2008-03-02'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata[
        'musicbrainzartistid'] == 'b7ffd2af-418f-4be2-bdd1-22f8b48613da'
    assert metadata[
        'musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadata['title'] == '15 Ghosts II'


def test_15ghosts2_fullytagged():
    ''' automated integration test '''
    config = bootstrap()
    mbhelper = nowplaying.musicbrainz.MusicBrainzHelper(config=config)
    metadata = mbhelper.isrc('USTC40852243')
    config.cparser.clear()
    assert metadata['album'] == 'Ghosts I–IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['date'] == '2008-03-02'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata[
        'musicbrainzartistid'] == 'b7ffd2af-418f-4be2-bdd1-22f8b48613da'
    assert metadata[
        'musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadata['title'] == '15 Ghosts II'


if __name__ == "__main__":
    test_15ghosts2_orig()
    test_15ghosts2_fullytagged()
