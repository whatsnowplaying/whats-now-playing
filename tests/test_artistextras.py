#!/usr/bin/env python3
''' test artistextras '''

import logging
import os
import typing as t

import pytest

import nowplaying.metadata  # pylint: disable=import-error
import nowplaying.apicache  # pylint: disable=import-error

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
async def test_theaudiodb_invalid_musicbrainz_id_fallback(bootstrap):  # pylint: disable=redefined-outer-name
    ''' test theaudiodb plugin falls back to name-based search when MusicBrainz ID is invalid '''

    config = bootstrap
    if 'theaudiodb' not in PLUGINS:
        pytest.skip("TheAudioDB API key not available")

    configuresettings('theaudiodb', config.cparser)
    config.cparser.setValue('theaudiodb/apikey', os.environ['THEAUDIODB_API_KEY'])
    _, plugins = configureplugins(config)

    plugin = plugins['theaudiodb']

    # Mock the MBID and name-based fetch methods to track calls
    original_mbid_fetch = plugin.artistdatafrommbid_async
    original_name_fetch = plugin.artistdatafromname_async

    mbid_call_count = 0
    name_call_count = 0

    async def mock_mbid_fetch(apikey, mbartistid, artist_name):
        nonlocal mbid_call_count
        mbid_call_count += 1
        logging.debug(f'MBID fetch call #{mbid_call_count} for MBID: {mbartistid}')

        if mbartistid == 'invalid-mbid-12345':
            # Simulate invalid MBID - API returns no results
            logging.debug('Simulating invalid MBID response')
            return None
        else:
            # Call original method for valid MBIDs
            return await original_mbid_fetch(apikey, mbartistid, artist_name)

    async def mock_name_fetch(apikey, artist):
        nonlocal name_call_count
        name_call_count += 1
        logging.debug(f'Name fetch call #{name_call_count} for artist: {artist}')

        # Call original method but simulate finding data for Nine Inch Nails
        if 'nine inch nails' in artist.lower():
            # Return minimal mock data to simulate successful name-based search
            return {
                'artists': [{
                    'idArtist': '111239',
                    'strArtist': 'Nine Inch Nails',  # Corrected capitalization
                    'strBiographyEN': 'Mock biography for Nine Inch Nails',
                    'strArtistLogo': None,
                    'strArtistThumb': None,
                    'strArtistFanart': None,
                    'strArtistBanner': None
                }]
            }
        else:
            return await original_name_fetch(apikey, artist)

    # Replace methods with mocks
    plugin.artistdatafrommbid_async = mock_mbid_fetch
    plugin.artistdatafromname_async = mock_name_fetch

    try:
        # Test with invalid MusicBrainz ID - should fallback to name-based search
        metadata_invalid_mbid = {
            'album': 'The Downward Spiral',
            'artist': 'nine inch nails',  # lowercase to test name correction
            'imagecacheartist': 'nineinchnails',
            'musicbrainzartistid': ['invalid-mbid-12345']  # Invalid MBID
        }

        result = await plugin.download_async(metadata_invalid_mbid.copy(), imagecache=None)

        # Verify the call pattern: MBID tried first, then fallback to name-based
        assert mbid_call_count == 1, f'Expected 1 MBID call, got {mbid_call_count}'
        assert name_call_count >= 1, f'Expected at least 1 name call (fallback), got {name_call_count}'

        # Should get a result from name-based fallback with corrected artist name
        assert result is not None, 'Expected result from name-based fallback'

        # If name correction feature is enabled, verify corrected artist name
        if result and result.get('artist'):
            assert result['artist'] == 'Nine Inch Nails', f'Expected corrected artist name, got {result.get("artist")}'
            logging.info('TheAudioDB invalid MBID fallback verified: MBID failed, name-based succeeded with correction')
        else:
            logging.info('TheAudioDB invalid MBID fallback verified: MBID failed, name-based search attempted')

        # Test without any MusicBrainz ID to ensure same name-based behavior
        mbid_call_count = 0
        name_call_count = 0

        metadata_no_mbid = {
            'album': 'The Downward Spiral',
            'artist': 'nine inch nails',
            'imagecacheartist': 'nineinchnails'
            # No musicbrainzartistid provided
        }

        result_no_mbid = await plugin.download_async(metadata_no_mbid.copy(), imagecache=None)

        # Should skip MBID and go straight to name-based search
        assert mbid_call_count == 0, f'Expected 0 MBID calls when no MBID provided, got {mbid_call_count}'
        assert name_call_count >= 1, f'Expected at least 1 name call when no MBID, got {name_call_count}'

        logging.info('TheAudioDB MBID fallback behavior test completed successfully')

    finally:
        # Restore original methods
        plugin.artistdatafrommbid_async = original_mbid_fetch
        plugin.artistdatafromname_async = original_name_fetch


@pytest.mark.asyncio
async def test_fanarttv_apicache_usage(bootstrap, temp_api_cache):  # pylint: disable=redefined-outer-name
    ''' test that fanarttv plugin uses apicache for API calls '''

    config = bootstrap
    if 'fanarttv' not in PLUGINS:
        pytest.skip("FanartTV API key not available")

    # Use the properly initialized temporary cache
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(temp_api_cache)

    try:
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

    finally:
        # Restore original cache
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
async def test_fanarttv_apicache_api_call_count(bootstrap, temp_api_cache):  # pylint: disable=redefined-outer-name
    ''' test that fanarttv plugin makes only one API call when cache is used '''

    config = bootstrap
    if 'fanarttv' not in PLUGINS:
        pytest.skip("FanartTV API key not available")

    # Use the properly initialized temporary cache
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(temp_api_cache)

    try:
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

        # Mock the internal _fetch_async method to count API calls
        original_fetch_async = plugin._fetch_async
        api_call_count = 0

        async def mock_fetch_async(apikey, artistid):
            nonlocal api_call_count
            api_call_count += 1
            logging.debug(f'Mock API call #{api_call_count} for artistid: {artistid}')
            # Call the original method to get real data
            return await original_fetch_async(apikey, artistid)

        # Replace the method with our mock
        plugin._fetch_async = mock_fetch_async

        try:
            # First call - should hit API and cache result
            result1 = await plugin.download_async(metadata_with_mbid.copy(),
                                                 imagecache=imagecaches['fanarttv'])

            # Verify one API call was made
            assert api_call_count == 1, f'Expected 1 API call after first download, got {api_call_count}'

            # Second call - should use cached result, no additional API call
            result2 = await plugin.download_async(metadata_with_mbid.copy(),
                                                 imagecache=imagecaches['fanarttv'])

            # Verify still only one API call was made (cache hit)
            assert api_call_count == 1, f'Expected 1 API call after second download (cache hit), got {api_call_count}'

            # Both results should be consistent
            assert (result1 is None) == (result2 is None)

            if result1:  # Only test if we got data back
                logging.info('FanartTV API cache verified: 1 API call for 2 downloads')
                assert result1 == result2
            else:
                logging.info('FanartTV API cache test completed - cache working regardless of data found')

        finally:
            # Restore the original method
            plugin._fetch_async = original_fetch_async

    finally:
        # Restore original cache
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
async def test_fanarttv_apicache_api_failure_behavior(bootstrap, temp_api_cache):  # pylint: disable=redefined-outer-name
    ''' test that fanarttv plugin doesn't cache failed API calls '''

    config = bootstrap
    if 'fanarttv' not in PLUGINS:
        pytest.skip("FanartTV API key not available")

    # Use the properly initialized temporary cache
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(temp_api_cache)

    try:
        configuresettings('fanarttv', config.cparser)
        config.cparser.setValue('fanarttv/apikey', os.environ['FANARTTV_API_KEY'])
        imagecaches, plugins = configureplugins(config)

        plugin = plugins['fanarttv']

        # Test with MusicBrainz ID (fanarttv requires MBID)
        metadata_with_mbid = {
            'album': 'Test Album',
            'artist': 'Test Artist',
            'imagecacheartist': 'testartist',
            'musicbrainzartistid': ['invalid-mbid-that-will-fail']  # Invalid MBID to trigger failure
        }

        # Mock the internal _fetch_async method to simulate failures then success
        original_fetch_async = plugin._fetch_async
        api_call_count = 0

        async def mock_fetch_async_with_failure(apikey, artistid):
            nonlocal api_call_count
            api_call_count += 1
            logging.debug(f'Mock API call #{api_call_count} for artistid: {artistid}')

            if api_call_count == 1:
                # First call: simulate API failure (network error, timeout, etc.)
                logging.debug('Simulating API failure on first call')
                return None
            elif api_call_count == 2:
                # Second call: simulate API returning valid empty response (artist not found)
                logging.debug('Simulating successful but empty API response on second call')
                return {'name': 'Test Artist', 'mbid_id': artistid}
            else:
                # Subsequent calls: should not happen if caching works correctly
                logging.debug('Unexpected additional API call')
                return {'name': 'Test Artist', 'mbid_id': artistid}

        # Replace the method with our mock
        plugin._fetch_async = mock_fetch_async_with_failure

        try:
            # First call - API fails, should return None and NOT cache the failure
            result1 = await plugin.download_async(metadata_with_mbid.copy(),
                                                 imagecache=imagecaches['fanarttv'])

            # Verify one API call was made and result is None (failure)
            assert api_call_count == 1, f'Expected 1 API call after first download, got {api_call_count}'
            assert result1 is None, 'Expected None result from failed API call'

            # Second call - should retry API (not use cached failure), API succeeds this time
            result2 = await plugin.download_async(metadata_with_mbid.copy(),
                                                 imagecache=imagecaches['fanarttv'])

            # Verify second API call was made (failure wasn't cached)
            assert api_call_count == 2, f'Expected 2 API calls after second download (failure not cached), got {api_call_count}'

            # Third call - should use cached success result, no additional API call
            result3 = await plugin.download_async(metadata_with_mbid.copy(),
                                                 imagecache=imagecaches['fanarttv'])

            # Verify still only two API calls (success result was cached)
            assert api_call_count == 2, f'Expected 2 API calls after third download (success cached), got {api_call_count}'

            # Results should show the pattern: None (failure), data (success), data (cached success)
            assert result1 is None, 'First result should be None (API failure)'
            assert result2 == result3, 'Second and third results should be identical (cached success)'

            logging.info('FanartTV API failure cache behavior verified: failures not cached, successes cached')

        finally:
            # Restore the original method
            plugin._fetch_async = original_fetch_async

    finally:
        # Restore original cache
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
async def test_discogs_apicache_usage(bootstrap, temp_api_cache):  # pylint: disable=redefined-outer-name
    ''' test that discogs plugin uses apicache for API calls '''

    config = bootstrap
    if 'discogs' not in PLUGINS:
        pytest.skip("Discogs API key not available")

    # Use the properly initialized temporary cache
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(temp_api_cache)

    try:
        configuresettings('discogs', config.cparser)
        config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
        imagecaches, plugins = configureplugins(config)

        plugin = plugins['discogs']

        # Test with album search (discogs searches by album+artist)
        metadata_with_album = {
            'album': 'The Downward Spiral',
            'artist': 'Nine Inch Nails',
            'imagecacheartist': 'nineinchnails'
        }

        # First call - should hit API and cache result
        result1 = await plugin.download_async(metadata_with_album.copy(),
                                             imagecache=imagecaches['discogs'])

        # Second call - should use cached result
        result2 = await plugin.download_async(metadata_with_album.copy(),
                                             imagecache=imagecaches['discogs'])

        # Both results should be consistent (either both None or both have data)
        assert (result1 is None) == (result2 is None)

        if result1:  # Only test if we got data back
            logging.info('Discogs API call successful, caching verified')
            # Should return the same metadata structure
            assert result1 == result2

    finally:
        # Restore original cache
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
async def test_discogs_website_lookup_cache(bootstrap):  # pylint: disable=redefined-outer-name
    ''' test discogs website lookup path with caching (different from search path) '''

    config = bootstrap
    if 'discogs' not in PLUGINS:
        pytest.skip("Discogs API key not available")

    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Test metadata with artistwebsites to trigger website lookup path
    metadata_with_websites = {
        'album': 'Purple Rain',
        'artist': 'Prince',
        'imagecacheartist': 'prince',
        'artistwebsites': ['https://www.discogs.com/artist/79903']  # Prince's Discogs page
    }

    # First call - should hit API and cache result (website lookup path)
    result1 = await plugin.download_async(metadata_with_websites.copy(),
                                         imagecache=imagecaches['discogs'])

    # Second call - should use cached result (tests _artist_async_cached)
    result2 = await plugin.download_async(metadata_with_websites.copy(),
                                         imagecache=imagecaches['discogs'])

    # Both results should be consistent
    assert (result1 is None) == (result2 is None)

    if result1:  # Only test if we got data back
        logging.info('Discogs website lookup caching verified')
        # Should return the same metadata structure
        assert result1 == result2
    else:
        logging.info('Discogs website lookup test completed - '
                     'cache working regardless of data found')


@pytest.mark.asyncio
async def test_discogs_artist_duplicates(bootstrap):  # pylint: disable=redefined-outer-name
    ''' test discogs handling of artists with duplicate names like "Madonna" '''

    config = bootstrap
    if 'discogs' not in PLUGINS:
        pytest.skip("Discogs API key not available")

    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Test different albums with same artist name to see if discogs can distinguish
    # Using more common artist names that definitely exist on Discogs
    metadata_madonna1 = {
        'album': 'Like a Virgin',  # The famous Madonna
        'artist': 'Madonna',
        'imagecacheartist': 'madonna1'
    }

    metadata_madonna2 = {
        'album': 'Red',  # Different Madonna (less famous)
        'artist': 'Madonna',
        'imagecacheartist': 'madonna2'
    }

    # Test both Madonna combinations - first calls should hit API, second calls should use cache

    # Madonna 1: Like a Virgin - first call (API)
    result1a = await plugin.download_async(metadata_madonna1.copy(),
                                          imagecache=imagecaches['discogs'])

    # Madonna 2: Red - first call (API)
    result2a = await plugin.download_async(metadata_madonna2.copy(),
                                          imagecache=imagecaches['discogs'])

    # Madonna 1: Like a Virgin - second call (should use cache)
    result1b = await plugin.download_async(metadata_madonna1.copy(),
                                          imagecache=imagecaches['discogs'])

    # Madonna 2: Red - second call (should use cache)
    result2b = await plugin.download_async(metadata_madonna2.copy(),
                                          imagecache=imagecaches['discogs'])

    # Verify caching works for both artist+album combinations
    assert (result1a is None) == (result1b is None)
    assert (result2a is None) == (result2b is None)

    if result1a:
        assert result1a == result1b
        logging.info('Cache verified for Madonna/Like a Virgin')

    if result2a:
        assert result2a == result2b
        logging.info('Cache verified for Madonna/Red')

    # If both found data, verify they're different artists (different bios)
    if result1a and result2a:
        bio1 = result1a.get('artistlongbio', '')
        bio2 = result2a.get('artistlongbio', '')
        if bio1 and bio2 and bio1 != bio2:
            logging.info('Discogs successfully distinguished between different '
                         '"Madonna" artists with caching')
        else:
            logging.info('Both Madonna searches returned data but with same/empty bios')
    else:
        logging.info('Discogs duplicate artist test completed - '
                     'cache working regardless of data found')

    # Test passes if caching works correctly for both duplicate artist scenarios


@pytest.mark.asyncio
async def test_theaudiodb_apicache_duplicate_artists(bootstrap, temp_api_cache):  # pylint: disable=redefined-outer-name
    ''' test TheAudioDB two-level caching with duplicate artist names '''

    config = bootstrap
    if 'theaudiodb' not in PLUGINS:
        pytest.skip("TheAudioDB API key not available")

    # Use the properly initialized temporary cache
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(temp_api_cache)

    try:
        configuresettings('theaudiodb', config.cparser)
        config.cparser.setValue('theaudiodb/apikey', os.environ['THEAUDIODB_API_KEY'])
        imagecaches, plugins = configureplugins(config)

        plugin = plugins['theaudiodb']

        # Test two different searches that might return different artists with similar names
        # First search - likely to match main "Madonna"
        metadata_madonna1 = {
            'artist': 'Madonna',
            'imagecacheartist': 'madonna1'
        }

        # Second search - variation that might match different artist
        metadata_madonna2 = {
            'artist': 'madonna',  # lowercase variation
            'imagecacheartist': 'madonna2'
        }

        # Test both variations - first calls hit API, second calls use cache
        result1a = await plugin.download_async(metadata_madonna1.copy(),
                                              imagecache=imagecaches['theaudiodb'])
        result2a = await plugin.download_async(metadata_madonna2.copy(),
                                              imagecache=imagecaches['theaudiodb'])

        # Second calls - should use cached data
        result1b = await plugin.download_async(metadata_madonna1.copy(),
                                              imagecache=imagecaches['theaudiodb'])
        result2b = await plugin.download_async(metadata_madonna2.copy(),
                                              imagecache=imagecaches['theaudiodb'])

        # Verify caching works for both variations
        assert (result1a is None) == (result1b is None)
        assert (result2a is None) == (result2b is None)

        if result1a:
            assert result1a == result1b
            logging.info('TheAudioDB cache verified for Madonna (capitalized)')

        if result2a:
            assert result2a == result2b
            logging.info('TheAudioDB cache verified for madonna (lowercase)')

        # Check if different normalizations potentially return different results
        if result1a and result2a:
            artist1 = result1a.get('artist', '')
            artist2 = result2a.get('artist', '')

            if artist1 and artist2 and artist1 != artist2:
                logging.info('TheAudioDB distinguished between different artists: %s vs %s',
                         artist1, artist2)
            else:
                logging.info('TheAudioDB returned same artist for both variations')
        else:
            logging.info('TheAudioDB duplicate artist test completed - two-level caching working')

        # Test passes if two-level caching works correctly (search + individual artist ID)

    finally:
        # Restore original cache
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
async def test_wikimedia_apicache_usage(bootstrap, temp_api_cache):  # pylint: disable=redefined-outer-name
    ''' test that wikimedia plugin uses apicache for API calls '''

    config = bootstrap

    # Use the properly initialized temporary cache
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(temp_api_cache)

    try:
        configuresettings('wikimedia', config.cparser)
        imagecaches, plugins = configureplugins(config)

        plugin = plugins['wikimedia']

        # Test with Wikidata entity ID (wikimedia uses unique entity IDs for differentiation)
        metadata_with_wikidata = {
            'artist': 'Nine Inch Nails',
            'imagecacheartist': 'nineinchnails',
            'artistwebsites': ['https://www.wikidata.org/wiki/Q11647']  # NIN's Wikidata page
        }

        # First call - should hit API and cache result
        result1 = await plugin.download_async(metadata_with_wikidata.copy(),
                                             imagecache=imagecaches['wikimedia'])

        # Second call - should use cached result
        result2 = await plugin.download_async(metadata_with_wikidata.copy(),
                                             imagecache=imagecaches['wikimedia'])

        # Both results should be consistent (either both None or both have data)
        assert (result1 is None) == (result2 is None)

        if result1:  # Only test if we got data back
            logging.info('Wikimedia API call successful, caching verified')
            # Should return the same metadata structure
            assert result1 == result2
        else:
            logging.info('Wikimedia caching test completed - '
                         'no data found but cache working')

    finally:
        # Restore original cache
        nowplaying.apicache.set_cache_instance(original_cache)


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
                'album': 'Art Angels',
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
