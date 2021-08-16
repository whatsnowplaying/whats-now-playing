#!/usr/bin/env python3
''' test serato '''

import pathlib
import os

import pytest

import nowplaying.inputs.serato  # pylint: disable=import-error


@pytest.fixture
def serato_bootstrap(bootstrap):
    ''' bootstrap test '''
    config = bootstrap
    config.cparser.setValue('serato/interval', 10.0)
    config.cparser.setValue('serato/local', True)
    config.cparser.setValue('serato/url', None)
    config.cparser.setValue('serato/deckskip', None)
    config.cparser.sync()
    yield config


def touchdir(directory):
    ''' serato requires current session files to process '''
    for file in os.listdir(directory):
        filename = os.path.join(directory, file)
        print(f'Touching {filename}')
        pathlib.Path(filename).touch()


@pytest.fixture
def getseratoplugin(serato_bootstrap, getroot, request):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = serato_bootstrap
    mark = request.node.get_closest_marker("seratosettings")
    datadir = mark.kwargs['datadir']
    mixmode = mark.kwargs['mixmode']
    config.cparser.setValue('serato/libpath',
                            os.path.join(getroot, 'tests', datadir))
    config.cparser.setValue('serato/mixmode', mixmode)
    touchdir(os.path.join(getroot, 'tests', datadir))
    plugin = nowplaying.inputs.serato.Plugin(config=config)
    yield plugin
    plugin.stop()


def results(expected, metadata):
    ''' take a metadata result and compare to expected '''
    for expkey in expected:
        assert expkey in metadata
        assert expected[expkey] == metadata[expkey]
        del metadata[expkey]
    assert metadata == {}


@pytest.mark.seratosettings(datadir='serato-2.4-mac', mixmode='oldest')
def test_serato24_mac_oldest(getseratoplugin):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    plugin = getseratoplugin
    (artist, title) = plugin.getplayingtrack()
    metadata = plugin.getplayingmetadata()
    assert artist == 'LĪVE'
    assert title == 'Take My Anthem'
    expected = {
        'album': 'Mental Jewelry',
        'artist': artist,
        'bpm': 109,
        'date': '1991',
        'deck': 2,
        'filename':
        '/Users/aw/Music/songs/LĪVE/Mental Jewelry/08 Take My Anthem.mp3',
        'genre': 'Rock',
        'key': 'G#m',
        'label': 'Radioactive Records',
        'title': title,
    }
    results(expected, metadata)


@pytest.mark.seratosettings(datadir='serato-2.4-mac', mixmode='newest')
def test_serato24_mac_newest(getseratoplugin):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    plugin = getseratoplugin
    (artist, title) = plugin.getplayingtrack()
    metadata = plugin.getplayingmetadata()
    assert artist == 'LĪVE'
    assert title == 'Lakini\'s Juice'
    expected = {
        'album': 'Secret Samadhi',
        'artist': artist,
        'bpm': 91,
        'date': '1997',
        'deck': 1,
        'filename':
        "/Users/aw/Music/songs/LĪVE/Secret Samadhi/02 Lakini's Juice.mp3",
        'genre': 'Rock',
        'key': 'C#m',
        'label': 'Radioactive Records',
        'title': title,
    }
    results(expected, metadata)


@pytest.mark.seratosettings(datadir='serato-2.5-win', mixmode='oldest')
def test_serato25_win_oldest(getseratoplugin):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    plugin = getseratoplugin
    (artist, title) = plugin.getplayingtrack()
    metadata = plugin.getplayingmetadata()
    assert artist == 'Broke For Free'
    assert title == 'Night Owl'
    expected = {
        'album':
        'Directionless EP',
        'artist':
        artist,
        'comments':
        'URL: http://freemusicarchive.org/music/Broke_For_Free/'
        'Directionless_EP/Broke_For_Free_-_Directionless_EP_-_01_Night_Owl\r\n'
        'Comments: http://freemusicarchive.org/\r\nCurator: WFMU\r\n'
        'Copyright: Creative Commons Attribution: http://creativecommons.org/licenses/by/3.0/',
        'date':
        '2011-01-18T11:15:40',
        'deck':
        2,
        'filename':
        'C:\\Users\\aw\\Music\\Broke For Free - Night Owl.mp3',
        'genre':
        'Electronic',
        'title':
        title,
    }
    results(expected, metadata)


@pytest.mark.seratosettings(datadir='serato-2.5-win', mixmode='newest')
def test_serato25_win_newest(getseratoplugin):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    plugin = getseratoplugin
    (artist, title) = plugin.getplayingtrack()
    metadata = plugin.getplayingmetadata()
    assert artist == 'Bio Unit'
    assert title == 'Heaven'
    expected = {
        'album': 'Ampex',
        'artist': artist,
        'date': '2020',
        'deck': 1,
        'filename': 'C:\\Users\\aw\\Music\\Bio Unit - Heaven.mp3',
        'genre': 'Electronica',
        'title': title,
    }
    results(expected, metadata)
