#!/usr/bin/env python3
''' test acoustid '''

import os

import logging
import logging.config
import logging.handlers

import nowplaying.bootstrap # pylint: disable=import-error
import nowplaying.config # pylint: disable=import-error
import nowplaying.recognition.ACRCloud # pylint: disable=import-error

def bootstrap():
    ''' bootstrap test '''
    bundledir = os.path.abspath(os.path.dirname(__file__))
    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names(appname='testsuite')
    # need to make sure config is initialized with something
    config = nowplaying.config.ConfigFile(bundledir=bundledir, testmode=True)
    config.cparser.setValue('acrcloud/enabled', True)
    config.cparser.setValue('acrcloud/key', os.environ['ACRCLOUD_TEST_KEY'])
    config.cparser.setValue('acrcloud/secret',
                            os.environ['ACRCLOUD_TEST_SECRET'])
    config.cparser.setValue('acrcloud/host', os.environ['ACRCLOUD_TEST_HOST'])
    return config


def test_15ghosts2_orig():
    ''' automated integration test '''
    config = bootstrap()
    plugin = nowplaying.recognition.ACRCloud.Plugin(config=config)
    metadata = plugin.recognize(
        {'filename': 'test/audio/15_Ghosts_II_64kb_orig.mp3'})
    config.cparser.clear()

    assert metadata['album'] == 'Ghosts I-IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata['title'] == '15 Ghosts II'
    assert metadata[
        'musicbrainzrecordingid'] == 'e0632d22-f355-41dd-ae01-9bcd87aaacf6'


def test_15ghosts2_fullytagged():
    ''' automated integration test '''
    config = bootstrap()
    plugin = nowplaying.recognition.ACRCloud.Plugin(config=config)
    metadata = plugin.recognize(
        {'filename': 'test/audio/15_Ghosts_II_64kb_orig.mp3'})
    config.cparser.clear()

    assert metadata['album'] == 'Ghosts I-IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata[
        'musicbrainzrecordingid'] == 'e0632d22-f355-41dd-ae01-9bcd87aaacf6'
    assert metadata['title'] == '15 Ghosts II'


if __name__ == "__main__":
    test_15ghosts2_orig()
    test_15ghosts2_fullytagged()
