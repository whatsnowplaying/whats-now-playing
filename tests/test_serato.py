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
    config.cparser.setValue('serato/interval', 0.0)
    config.cparser.setValue('serato/deckskip', None)
    config.cparser.sync()
    yield config


def touchdir(directory):
    ''' serato requires current session files to process '''
    for file in os.listdir(directory):
        filename = os.path.join(directory, file)
        pathlib.Path(filename).touch()


@pytest.fixture
def getseratoplugin(serato_bootstrap, getroot, request):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = serato_bootstrap
    mark = request.node.get_closest_marker("seratosettings")
    if 'mode' in mark.kwargs and 'remote' in mark.kwargs['mode']:
        config.cparser.setValue('serato/local', False)
        config.cparser.setValue('serato/url', mark.kwargs['url'])
    else:
        datadir = mark.kwargs['datadir']
        config.cparser.setValue('serato/local', True)
        config.cparser.setValue('serato/libpath',
                                os.path.join(getroot, 'tests', datadir))
        if 'mixmode' in mark.kwargs:
            config.cparser.setValue('serato/mixmode', mark.kwargs['mixmode'])
        touchdir(os.path.join(getroot, 'tests', datadir, 'History',
                              'Sessions'))
    config.cparser.sync()
    plugin = nowplaying.inputs.serato.Plugin(config=config)
    plugin.start()
    yield plugin
    plugin.stop()


def results(expected, metadata):
    ''' take a metadata result and compare to expected '''
    for expkey in expected:
        assert expkey in metadata
        assert expected[expkey] == metadata[expkey]
        del metadata[expkey]
    assert metadata == {}


@pytest.mark.seratosettings(mode='remote', url='https://localhost')
def test_serato_remote2(getseratoplugin, getroot, httpserver):  # pylint: disable=redefined-outer-name
    ''' test serato remote '''
    plugin = getseratoplugin
    with open(os.path.join(getroot, 'tests', 'seratolive',
                           '2021_08_25_pong.html'),
              encoding='utf8') as inputfh:
        content = inputfh.readlines()
    httpserver.expect_request('/index.html').respond_with_data(
        ''.join(content))
    plugin.config.cparser.setValue('serato/url',
                                   httpserver.url_for('/index.html'))
    plugin.config.cparser.sync()
    (artist, title) = plugin.getplayingtrack()

    assert artist == 'Chris McClenney'
    assert title == 'Tuning Up'


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


@pytest.mark.seratosettings(datadir='serato-2.5-win')
def test_serato_nomixmode(getseratoplugin):  # pylint: disable=redefined-outer-name
    ''' test default mixmode '''
    plugin = getseratoplugin
    assert plugin.getmixmode() == 'newest'


@pytest.mark.seratosettings(datadir='serato-2.5-win')
def test_serato_localmixmodes(getseratoplugin):  # pylint: disable=redefined-outer-name
    ''' test local mixmodes '''
    plugin = getseratoplugin
    validmodes = plugin.validmixmodes()
    assert 'newest' in validmodes
    assert 'oldest' in validmodes
    mode = plugin.setmixmode('oldest')
    assert mode == 'oldest'
    mode = plugin.setmixmode('fred')
    assert mode == 'oldest'
    mode = plugin.setmixmode('newest')
    mode = plugin.getmixmode()
    assert mode == 'newest'


@pytest.mark.seratosettings(mode='remote', url='https://localhost.example.com')
def test_serato_remote1(getseratoplugin):  # pylint: disable=redefined-outer-name
    ''' test local mixmodes '''
    plugin = getseratoplugin
    validmodes = plugin.validmixmodes()
    assert 'newest' in validmodes
    assert 'oldest' not in validmodes
    mode = plugin.setmixmode('oldest')
    assert mode == 'newest'
    mode = plugin.setmixmode('fred')
    assert mode == 'newest'
    mode = plugin.getmixmode()
    assert mode == 'newest'
