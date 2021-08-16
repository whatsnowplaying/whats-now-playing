#!/usr/bin/env python3
''' test acoustid '''

import pathlib
import os

import logging
import logging.config
import logging.handlers

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.config  # pylint: disable=import-error
import nowplaying.inputs.serato  # pylint: disable=import-error


def bootstrap():
    ''' bootstrap test '''
    bundledir = os.path.abspath(os.path.dirname(__file__))
    logging.basicConfig(level=logging.DEBUG)
    nowplaying.bootstrap.set_qt_names(appname='testsuite')
    return nowplaying.config.ConfigFile(bundledir=bundledir, testmode=True)


def touchdir(directory):
    ''' serato requires current session files to process '''
    for file in os.listdir(directory):
        filename = os.path.join(directory, file)
        print(f'Touching {filename}')
        pathlib.Path(filename).touch()


def testresults(expected, metadata):
    ''' take a metadata result and compare to expected '''
    for expkey in expected:
        assert expkey in metadata
        assert expected[expkey] == metadata[expkey]
        del metadata[expkey]

    assert metadata == {}


def test_serato24_mac_oldest():
    ''' automated integration test '''
    config = bootstrap()
    config.cparser.setValue('serato/libpath', 'test/serato-2.4-mac/')
    config.cparser.setValue('serato/interval', 10.0)
    config.cparser.setValue('serato/local', True)
    config.cparser.setValue('serato/mixmode', "oldest")
    config.cparser.setValue('serato/url', None)
    config.cparser.setValue('serato/deckskip', None)
    touchdir('test/serato-2.4-mac/History/Sessions/')
    plugin = nowplaying.inputs.serato.Plugin(config=config)
    (artist, title) = plugin.getplayingtrack()
    metadata = plugin.getplayingmetadata()
    config.cparser.clear()
    plugin.serato.__del__()
    assert artist == 'LĪVE'
    assert title == 'Take My Anthem'
    expected = {}
    expected['album'] = 'Mental Jewelry'
    expected['artist'] = artist
    expected['bpm'] = 109
    expected['date'] = '1991'
    expected['deck'] = 2
    expected[
        'filename'] = '/Users/aw/Music/songs/LĪVE/Mental Jewelry/08 Take My Anthem.mp3'
    expected['genre'] = 'Rock'
    expected['key'] = 'G#m'
    expected['label'] = 'Radioactive Records'
    expected['title'] = title
    testresults(expected, metadata)


def test_serato24_mac_newest():
    ''' automated integration test '''
    config = bootstrap()
    config.cparser.setValue('serato/libpath', 'test/serato-2.4-mac/')
    config.cparser.setValue('serato/interval', 10.0)
    config.cparser.setValue('serato/local', True)
    config.cparser.setValue('serato/mixmode', "newest")
    config.cparser.setValue('serato/url', None)
    config.cparser.setValue('serato/deckskip', None)
    touchdir('test/serato-2.4-mac/History/Sessions/')
    plugin = nowplaying.inputs.serato.Plugin(config=config)
    (artist, title) = plugin.getplayingtrack()
    metadata = plugin.getplayingmetadata()
    config.cparser.clear()
    plugin.serato.__del__()
    assert artist == 'LĪVE'
    assert title == 'Lakini\'s Juice'
    expected = {}
    expected['album'] = 'Secret Samadhi'
    expected['artist'] = artist
    expected['bpm'] = 91
    expected['date'] = '1997'
    expected['deck'] = 1
    expected[
        'filename'] = '/Users/aw/Music/songs/LĪVE/Secret Samadhi/02 Lakini\'s Juice.mp3'
    expected['genre'] = 'Rock'
    expected['key'] = 'C#m'
    expected['label'] = 'Radioactive Records'
    expected['title'] = title
    testresults(expected, metadata)


def test_serato25_win_oldest():
    ''' automated integration test '''
    config = bootstrap()
    config.cparser.setValue('serato/libpath', 'test/serato-2.5-win/')
    config.cparser.setValue('serato/interval', 10.0)
    config.cparser.setValue('serato/local', True)
    config.cparser.setValue('serato/mixmode', "oldest")
    config.cparser.setValue('serato/url', None)
    config.cparser.setValue('serato/deckskip', None)
    touchdir('test/serato-2.5-win/History/Sessions/')
    plugin = nowplaying.inputs.serato.Plugin(config=config)
    (artist, title) = plugin.getplayingtrack()
    metadata = plugin.getplayingmetadata()
    config.cparser.clear()
    plugin.serato.__del__()
    assert artist == 'Broke For Free'
    assert title == 'Night Owl'
    expected = {}
    expected['album'] = 'Directionless EP'
    expected['artist'] = artist
    expected[
        'comments'] = 'URL: http://freemusicarchive.org/music/Broke_For_Free/Directionless_EP/Broke_For_Free_-_Directionless_EP_-_01_Night_Owl\r\nComments: http://freemusicarchive.org/\r\nCurator: WFMU\r\nCopyright: Creative Commons Attribution: http://creativecommons.org/licenses/by/3.0/'
    expected['date'] = '2011-01-18T11:15:40'
    expected['deck'] = 2
    expected[
        'filename'] = 'C:\\Users\\aw\\Music\\Broke For Free - Night Owl.mp3'
    expected['genre'] = 'Electronic'
    expected['title'] = title
    testresults(expected, metadata)


def test_serato25_win_newest():
    ''' automated integration test '''
    config = bootstrap()
    config.cparser.setValue('serato/libpath', 'test/serato-2.5-win/')
    config.cparser.setValue('serato/interval', 10.0)
    config.cparser.setValue('serato/local', True)
    config.cparser.setValue('serato/mixmode', "newest")
    config.cparser.setValue('serato/url', None)
    config.cparser.setValue('serato/deckskip', None)
    touchdir('test/serato-2.5-win/History/Sessions/')
    plugin = nowplaying.inputs.serato.Plugin(config=config)
    (artist, title) = plugin.getplayingtrack()
    metadata = plugin.getplayingmetadata()
    config.cparser.clear()
    plugin.serato.__del__()
    assert artist == 'Bio Unit'
    assert title == 'Heaven'
    expected = {}
    expected['album'] = 'Ampex'
    expected['artist'] = artist
    expected['date'] = '2020'
    expected['deck'] = 1
    expected['filename'] = 'C:\\Users\\aw\\Music\\Bio Unit - Heaven.mp3'
    expected['genre'] = 'Electronica'
    expected['title'] = title
    testresults(expected, metadata)


if __name__ == "__main__":
    test_serato24_mac_oldest()
    test_serato24_mac_newest()
    test_serato25_win_oldest()
    test_serato25_win_newest()
