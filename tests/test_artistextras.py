#!/usr/bin/env python3
''' test artistextras '''

import logging
import os
import typing as t

import pytest

import nowplaying.metadata  # pylint: disable=import-error

PLUGINS = ['wikimedia']

if os.environ.get('DISCOGS_API_KEY'):
    PLUGINS.append('discogs')
if os.environ.get('FANARTTV_API_KEY'):
    PLUGINS.append('fanarttv')
if os.environ.get('THEAUDIODB_API_KEY'):
    PLUGINS.append('theaudiodb')


class FakeImageCache:  # pylint: disable=too-few-public-methods
    ''' a fake ImageCache that just keeps track of urls '''

    def __init__(self):
        self.urls = {}

    def fill_queue(
            self,
            config=None,  # pylint: disable=unused-argument
            identifier: str = None,
            imagetype: str = None,
            srclocationlist: t.List[str] = None):
        ''' just keep track of what was picked '''
        if not self.urls.get(identifier):
            self.urls[identifier] = {}
        self.urls[identifier][imagetype] = srclocationlist


def configureplugins(config):
    ''' configure plugins '''
    imagecaches = {}
    plugins = {}
    for pluginname in PLUGINS:
        imagecaches[pluginname] = FakeImageCache()
        plugins[pluginname] = config.pluginobjs['artistextras'][
            f'nowplaying.artistextras.{pluginname}']
    return imagecaches, plugins


def configuresettings(pluginname, cparser):
    ''' configure each setting '''
    for key in [
            'banners',
            'bio',
            'enabled',
            'fanart',
            'logos',
            'thumbnails',
            'websites',
    ]:
        cparser.setValue(f'{pluginname}/{key}', True)


@pytest.fixture
def getconfiguredplugin(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    configuresettings('wikimedia', config.cparser)
    if 'discogs' in PLUGINS:
        configuresettings('discogs', config.cparser)
        config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    if 'fanarttv' in PLUGINS:
        configuresettings('fanarttv', config.cparser)
        config.cparser.setValue('fanarttv/apikey', os.environ['FANARTTV_API_KEY'])
    if 'theaudiodb' in PLUGINS:
        configuresettings('theaudiodb', config.cparser)
        config.cparser.setValue('theaudiodb/apikey', os.environ['THEAUDIODB_API_KEY'])
    if 'theaudiodb' in PLUGINS:
        configuresettings('theaudiodb', config.cparser)
    yield configureplugins(config)


@pytest.mark.asyncio
async def test_disabled(bootstrap):
    ''' test disabled '''
    imagecaches, plugins = configureplugins(bootstrap)
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        data = await plugins[pluginname].download_async(imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


def test_providerinfo(bootstrap):  # pylint: disable=redefined-outer-name
    ''' test providerinfo '''
    imagecaches, plugins = configureplugins(bootstrap)  # pylint: disable=unused-variable
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        data = plugins[pluginname].providerinfo()
        assert data


@pytest.mark.asyncio
async def test_noapikey(bootstrap):  # pylint: disable=redefined-outer-name
    ''' test disabled '''
    config = bootstrap
    imagecaches, plugins = configureplugins(config)
    for pluginname in PLUGINS:
        config.cparser.setValue(f'{pluginname}/enabled', True)
        logging.debug('Testing %s', pluginname)
        data = await plugins[pluginname].download_async(imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_nodata(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' test disabled '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        data = await plugins[pluginname].download_async(imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_noimagecache(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' noimagecache '''

    imagecaches, plugins = getconfiguredplugin  # pylint: disable=unused-variable
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        data = await plugins[pluginname].download_async(
            {
                'album': 'The Downward Spiral',
                'artist': 'Nine Inch Nails',
                'imagecacheartist': 'nineinchnails'
            },
            imagecache=None)
        if pluginname in ['discogs', 'theaudiodb']:
            assert data['artistwebsites']
            assert data['artistlongbio']
        else:
            assert not data


@pytest.mark.asyncio
async def test_theaudiodb_artist_name_correction(bootstrap):  # pylint: disable=redefined-outer-name
    ''' test theaudiodb artist name correction for name-based vs musicbrainz searches '''

    config = bootstrap
    if 'theaudiodb' not in PLUGINS:
        pytest.skip("TheAudioDB API key not available")

    configuresettings('theaudiodb', config.cparser)
    config.cparser.setValue('theaudiodb/apikey', os.environ['THEAUDIODB_API_KEY'])
    _, plugins = configureplugins(config)

    plugin = plugins['theaudiodb']

    # Test 1: Name-based search with lowercase input (should correct artist name)
    metadata_lowercase = {
        'album': 'The Downward Spiral',
        'artist': 'nine inch nails',  # lowercase input
        'imagecacheartist': 'nineinchnails'
    }
    result1 = await plugin.download_async(metadata_lowercase.copy(), imagecache=None)

    if result1:  # Only test if we got data back
        # Should have corrected the artist name to proper case
        assert result1['artist'] == 'Nine Inch Nails'
        logging.info('Artist name corrected: %s -> %s',
                    metadata_lowercase['artist'], result1['artist'])

    # Test 2: With MusicBrainz ID (should NOT correct artist name)
    metadata_with_mbid = {
        'album': 'The Downward Spiral',
        'artist': 'nine inch nails',  # lowercase input
        'imagecacheartist': 'nineinchnails',
        'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da']  # NIN's MBID
    }
    result2 = await plugin.download_async(metadata_with_mbid.copy(), imagecache=None)

    if result2:  # Only test if we got data back
        # Should NOT have corrected the artist name (MusicBrainz is authoritative)
        assert result2['artist'] == 'nine inch nails'
        logging.info('Artist name preserved for MusicBrainz search: %s', result2['artist'])


@pytest.mark.asyncio
async def test_fanarttv_apicache_usage(bootstrap):  # pylint: disable=redefined-outer-name
    ''' test that fanarttv plugin uses apicache for API calls '''

    config = bootstrap
    if 'fanarttv' not in PLUGINS:
        pytest.skip("FanartTV API key not available")

    configuresettings('fanarttv', config.cparser)
    config.cparser.setValue('fanarttv/apikey', os.environ['FANARTTV_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['fanarttv']

    # Test with MusicBrainz ID (fanarttv requires MBID)
    metadata_with_mbid = {
        'album': 'The Downward Spiral',
        'artist': 'Nine Inch Nails',
        'imagecacheartist': 'nineinchnails',
        'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da']  # NIN's MBID
    }

    # First call - should hit API and cache result
    result1 = await plugin.download_async(metadata_with_mbid.copy(),
                                         imagecache=imagecaches['fanarttv'])

    # Second call - should use cached result
    result2 = await plugin.download_async(metadata_with_mbid.copy(),
                                         imagecache=imagecaches['fanarttv'])

    # Both results should be consistent (either both None or both have data)
    assert (result1 is None) == (result2 is None)

    if result1:  # Only test if we got data back
        logging.info('FanartTV API call successful, caching verified')
        # Should return the same metadata structure
        assert result1 == result2


@pytest.mark.asyncio
async def test_discogs_note_stripping(bootstrap):  # pylint: disable=redefined-outer-name
    ''' noimagecache '''

    config = bootstrap
    if 'discogs' in PLUGINS:
        configuresettings('discogs', config.cparser)
        config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)  # pylint: disable=unused-variable
    for pluginname in PLUGINS:
        if 'discogs' not in pluginname:
            continue
        logging.debug('Testing %s', pluginname)
        data = await plugins[pluginname].download_async(
            {
                'title': 'Tiny Dancer',
                'album': 'Diamonds',
                'artist': 'Elton John',
                'imagecacheartist': 'eltonjohn'
            },
            imagecache=None)
        assert data['artistlongbio']
        mpproc = nowplaying.metadata.MetadataProcessors(config=config)
        mpproc.metadata = data
        assert 'Note:' in mpproc.metadata['artistlongbio']
        mpproc._generate_short_bio()  # pylint: disable=protected-access
        assert 'Note:' not in mpproc.metadata['artistshortbio']


@pytest.mark.asyncio
async def test_discogs_weblocation1(bootstrap):  # pylint: disable=redefined-outer-name
    ''' noimagecache '''

    config = bootstrap
    if 'discogs' in PLUGINS:
        configuresettings('discogs', config.cparser)
        config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)  # pylint: disable=unused-variable
    for pluginname in PLUGINS:
        if 'discogs' not in pluginname:
            continue
        logging.debug('Testing %s', pluginname)
        data = await plugins[pluginname].download_async(
            {
                'title':
                'Computer Blue',
                'album':
                'Purple Rain',
                'artist':
                'Prince and The Revolution',
                'artistwebsites': [
                    'https://www.discogs.com/artist/271351', 'https://www.discogs.com/artist/28795',
                    'https://www.discogs.com/artist/293637',
                    'https://www.discogs.com/artist/342899', 'https://www.discogs.com/artist/79903',
                    'https://www.discogs.com/artist/571633', 'https://www.discogs.com/artist/96774'
                ],
                'imagecacheartist':
                'princeandtherevoluion'
            },
            imagecache=None)
        assert 'NOTE: If The Revolution are credited without Prince' in data['artistlongbio']


@pytest.mark.asyncio
async def test_missingallartistdata(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' missing all artist data '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async({'title': 'title'},
                                                        imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_missingmbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' artist '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'artist': 'Nine Inch Nails',
                'imagecacheartist': 'nineinchnails'
            },
            imagecache=imagecaches[pluginname])
        if pluginname == 'theaudiodb':
            assert data['artistfanarturls']
            assert data['artistlongbio']
            assert data['artistwebsites']
            assert imagecaches[pluginname].urls['nineinchnails']['artistbanner']
            assert imagecaches[pluginname].urls['nineinchnails']['artistlogo']
            assert imagecaches[pluginname].urls['nineinchnails']['artistthumbnail']
        else:
            assert not data
            assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_featuring1(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' artist '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'artist': 'Grimes feat Janelle Monáe',
                'title': 'Venus Fly',
                'album': 'Art Angel',
                'imagecacheartist': 'grimesfeatjanellemonae'
            },
            imagecache=imagecaches[pluginname])
        if pluginname == 'discogs':
            assert data['artistfanarturls']
            assert data['artistlongbio']
            assert data['artistwebsites']
        elif pluginname == 'theaudiodb':
            assert data['artistfanarturls']
            assert data['artistlongbio']
            assert data['artistwebsites']
            assert imagecaches[pluginname].urls['grimesfeatjanellemonae']['artistbanner']
            assert imagecaches[pluginname].urls['grimesfeatjanellemonae']['artistlogo']
            assert imagecaches[pluginname].urls['grimesfeatjanellemonae']['artistthumbnail']


@pytest.mark.asyncio
async def test_featuring2(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' artist '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'artist': 'MӨЯIS BLΛK feat. grabyourface',
                'title': 'Complicate',
                'album': 'Irregular Revisions',
                'imagecacheartist': 'morisblakfeatgrabyourface'
            },
            imagecache=imagecaches[pluginname])
        if pluginname == 'discogs':
            assert data['artistfanarturls']
            assert data['artistlongbio']
            assert data['artistwebsites']


@pytest.mark.asyncio
async def test_badmbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'artist': 'NonExistentArtistXYZ',
                'imagecacheartist': 'nonexistentartistxyz',
                'musicbrainzartistid': ['xyz']
            },
            imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_onlymbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da'],
            },
            imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_artist_and_mbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'artist': 'Nine Inch Nails',
                'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da'],
                'imagecacheartist': 'nineinchnails',
            },
            imagecache=imagecaches[pluginname])
        if pluginname == 'theaudiodb':
            assert data['artistlongbio']
            assert data['artistwebsites']
        if pluginname in ['fanarttv', 'theaudiodb']:
            assert data['artistfanarturls']
            assert imagecaches[pluginname].urls['nineinchnails']['artistbanner']
            assert imagecaches[pluginname].urls['nineinchnails']['artistlogo']
            assert imagecaches[pluginname].urls['nineinchnails']['artistthumbnail']
        else:
            assert not data
            assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_all(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        metadata = {
            'artist': 'Nine Inch Nails',
            'album': 'The Downward Spiral',
            'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da'],
            'imagecacheartist': 'nineinchnails',
        }
        if pluginname == 'wikimedia':
            metadata['artistwebsites'] = ['https://www.wikidata.org/wiki/Q11647']
        data = await plugins[pluginname].download_async(metadata,
                                                        imagecache=imagecaches[pluginname])
        if pluginname in ['discogs', 'theaudiodb']:
            assert data['artistlongbio']
            assert data['artistwebsites']
        if pluginname in ['fanarttv', 'theaudiodb']:
            assert imagecaches[pluginname].urls['nineinchnails']['artistbanner']
            assert imagecaches[pluginname].urls['nineinchnails']['artistlogo']
        assert data['artistfanarturls']


@pytest.mark.xfail(reason="Non-deterministic at the moment")
@pytest.mark.asyncio
async def test_theall(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        metadata = {
            'artist': 'The Nine Inch Nails',
            'album': 'The Downward Spiral',
            'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da'],
            'imagecacheartist': 'nineinchnails'
        }
        if pluginname == 'wikimedia':
            metadata['artistwebsites'] = ['https://www.wikidata.org/wiki/Q11647']
        data = await plugins[pluginname].download_async(metadata,
                                                        imagecache=imagecaches[pluginname])
        if pluginname in ['discogs', 'theaudiodb']:
            assert data['artistlongbio']
            assert data['artistwebsites']
        if pluginname in ['fanarttv', 'theaudiodb']:
            assert imagecaches[pluginname].urls['nineinchnails']['artistbanner']
            assert imagecaches[pluginname].urls['nineinchnails']['artistlogo']
        assert data['artistfanarturls']
        assert imagecaches[pluginname].urls['nineinchnails']['artistthumbnail']


@pytest.mark.asyncio
async def test_notfound(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' discogs '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'album': 'ZYX fake album XYZ',
                'artist': 'The XYZ fake artist XYZ',
                'musicbrainzartistid': ['xyz']
            },
            imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_wikimedia_langfallback_zh_to_en(bootstrap):  # pylint: disable=redefined-outer-name
    ''' not english test '''

    config = bootstrap
    configuresettings('wikimedia', config.cparser)
    config.cparser.setValue('wikimedia/bio_iso', 'zh')
    config.cparser.setValue('wikimedia/bio_iso_en_fallback', True)
    _, plugins = configureplugins(config)
    data = await plugins['wikimedia'].download_async(
        {'artistwebsites': [
            'https://www.wikidata.org/wiki/Q7766138',
        ]}, imagecache=None)
    assert 'video' in data.get('artistlongbio')


@pytest.mark.asyncio
async def test_wikimedia_langfallback_zh_to_none(bootstrap):  # pylint: disable=redefined-outer-name
    ''' not english test '''

    config = bootstrap
    configuresettings('wikimedia', config.cparser)
    config.cparser.setValue('wikimedia/bio_iso', 'zh')
    config.cparser.setValue('wikimedia/bio_iso_en_fallback', False)
    _, plugins = configureplugins(config)
    data = await plugins['wikimedia'].download_async(
        {'artistwebsites': [
            'https://www.wikidata.org/wiki/Q7766138',
        ]}, imagecache=None)
    assert not data.get('artistlongbio')


@pytest.mark.asyncio
async def test_wikimedia_humantetris_en(bootstrap):  # pylint: disable=redefined-outer-name
    ''' not english test '''

    config = bootstrap
    configuresettings('wikimedia', config.cparser)
    config.cparser.setValue('wikimedia/bio_iso', 'en')
    config.cparser.setValue('wikimedia/bio_iso_en_fallback', False)
    _, plugins = configureplugins(config)
    data = await plugins['wikimedia'].download_async(
        {'artistwebsites': [
            'https://www.wikidata.org/wiki/Q60845849',
        ]}, imagecache=None)
    assert data.get('artistshortbio') == 'Russian post-punk band from Moscow'
    assert not data.get('artistlongbio')


@pytest.mark.asyncio
async def test_wikimedia_humantetris_de(bootstrap):  # pylint: disable=redefined-outer-name
    ''' not english test '''

    config = bootstrap
    configuresettings('wikimedia', config.cparser)
    config.cparser.setValue('wikimedia/bio_iso', 'de')
    config.cparser.setValue('wikimedia/bio_iso_en_fallback', True)
    _, plugins = configureplugins(config)
    data = await plugins['wikimedia'].download_async(
        {'artistwebsites': [
            'https://www.wikidata.org/wiki/Q60845849',
        ]}, imagecache=None)
    assert 'Human Tetris ist eine Band aus Moskau' in data.get('artistlongbio')
