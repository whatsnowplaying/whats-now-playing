#!/usr/bin/env python3
''' test serato '''

from datetime import datetime
import logging
import pathlib
import os

import pytest
import pytest_asyncio  # pylint: disable=import-error

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
    files = {
        '1': '2021-02-06 15:14:57',
        '12': '2021-02-06 19:13:23',
        '66': '2021-02-07 00:27:26',
        '74': '2021-02-07 12:59:41',
        '80': '2021-02-07 23:21:04',
        '84': '2021-02-08 00:15:07'
    }
    for key, value in files.items():
        filepath = pathlib.Path(directory).joinpath(f'{key}.session')
        if not filepath.exists():
            continue
        utc_dt = datetime.fromisoformat(value)
        epochtime = (utc_dt - datetime(1970, 1, 1)).total_seconds()
        logging.debug('changing %s to %s', filepath, epochtime)
        os.utime(filepath, times=(epochtime, epochtime))


@pytest_asyncio.fixture
async def getseratoplugin(serato_bootstrap, getroot, request):  # pylint: disable=redefined-outer-name
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
    await plugin.start()
    yield plugin
    await plugin.stop()


def results(expected, metadata):
    ''' take a metadata result and compare to expected '''
    for expkey in expected:
        assert expkey in metadata
        assert expected[expkey] == metadata[expkey]
        del metadata[expkey]
    assert metadata == {}


@pytest.mark.seratosettings(mode='remote', url='https://localhost')
@pytest.mark.asyncio
async def test_serato_remote2(getseratoplugin, getroot, httpserver):  # pylint: disable=redefined-outer-name
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
    metadata = await plugin.getplayingtrack()

    assert metadata['artist'] == 'Chris McClenney'
    assert metadata['title'] == 'Tuning Up'
    assert 'filename' not in metadata


@pytest.mark.asyncio
@pytest.mark.seratosettings(datadir='serato-2.4-mac', mixmode='oldest')
async def test_serato24_mac_oldest(getseratoplugin):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    plugin = getseratoplugin
    metadata = await plugin.getplayingtrack()
    expected = {
        'album': 'Mental Jewelry',
        'artist': 'LĪVE',
        'bpm': 109,
        'date': '1991',
        'deck': 2,
        'filename':
        '/Users/aw/Music/songs/LĪVE/Mental Jewelry/08 Take My Anthem.mp3',
        'genre': 'Rock',
        'key': 'G#m',
        'label': 'Radioactive Records',
        'title': 'Take My Anthem',
    }
    results(expected, metadata)


@pytest.mark.asyncio
@pytest.mark.seratosettings(datadir='serato-2.4-mac', mixmode='newest')
async def test_serato24_mac_newest(getseratoplugin):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    plugin = getseratoplugin
    metadata = await plugin.getplayingtrack()
    expected = {
        'album': 'Secret Samadhi',
        'artist': 'LĪVE',
        'bpm': 91,
        'date': '1997',
        'deck': 1,
        'filename':
        "/Users/aw/Music/songs/LĪVE/Secret Samadhi/02 Lakini's Juice.mp3",
        'genre': 'Rock',
        'key': 'C#m',
        'label': 'Radioactive Records',
        'title': 'Lakini\'s Juice',
    }
    results(expected, metadata)


@pytest.mark.asyncio
@pytest.mark.seratosettings(datadir='serato-2.5-win', mixmode='oldest')
async def test_serato25_win_oldest(getseratoplugin):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    plugin = getseratoplugin
    metadata = await plugin.getplayingtrack()
    expected = {
        'album':
        'Directionless EP',
        'artist':
        'Broke For Free',
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
        'Night Owl',
    }
    results(expected, metadata)


@pytest.mark.asyncio
@pytest.mark.seratosettings(datadir='serato-2.5-win', mixmode='newest')
async def test_serato25_win_newest(getseratoplugin):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    plugin = getseratoplugin
    metadata = await plugin.getplayingtrack()
    expected = {
        'album': 'Ampex',
        'artist': 'Bio Unit',
        'date': '2020',
        'deck': 1,
        'filename': 'C:\\Users\\aw\\Music\\Bio Unit - Heaven.mp3',
        'genre': 'Electronica',
        'title': 'Heaven',
    }
    results(expected, metadata)


@pytest.mark.asyncio
@pytest.mark.seratosettings(datadir='serato-2.5-win')
async def test_serato_nomixmode(getseratoplugin):  # pylint: disable=redefined-outer-name
    ''' test default mixmode '''
    plugin = getseratoplugin
    assert plugin.getmixmode() == 'newest'


@pytest.mark.asyncio
@pytest.mark.seratosettings(datadir='serato-2.5-win')
async def test_serato_localmixmodes(getseratoplugin):  # pylint: disable=redefined-outer-name
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


@pytest.mark.asyncio
@pytest.mark.seratosettings(mode='remote', url='https://localhost.example.com')
async def test_serato_remote1(getseratoplugin):  # pylint: disable=redefined-outer-name
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
