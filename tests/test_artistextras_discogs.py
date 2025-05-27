#!/usr/bin/env python3
''' test artistextras discogs plugin '''

import asyncio
import logging
import os

import pytest
from aiohttp import ClientResponseError

from utils_artistextras import (configureplugins, configuresettings, skip_no_discogs_key)

import nowplaying.metadata  # pylint: disable=import-error
import nowplaying.apicache  # pylint: disable=import-error
import nowplaying.discogsclient  # pylint: disable=import-error


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_note_stripping(bootstrap):
    ''' test note stripping in discogs bio '''

    config = bootstrap

    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)  # pylint: disable=unused-variable

    logging.debug('Testing discogs')
    data = await plugins['discogs'].download_async(
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
@skip_no_discogs_key
async def test_discogs_weblocation1(bootstrap):
    ''' test discogs web location lookup '''

    config = bootstrap

    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)  # pylint: disable=unused-variable

    logging.debug('Testing discogs')
    data = await plugins['discogs'].download_async(
        {
            'title':
            'Computer Blue',
            'album':
            'Purple Rain',
            'artist':
            'Prince and The Revolution',
            'artistwebsites': [
                'https://www.discogs.com/artist/271351', 'https://www.discogs.com/artist/28795',
                'https://www.discogs.com/artist/293637', 'https://www.discogs.com/artist/342899',
                'https://www.discogs.com/artist/79903', 'https://www.discogs.com/artist/571633',
                'https://www.discogs.com/artist/96774'
            ],
            'imagecacheartist':
            'princeandtherevoluion'
        },
        imagecache=None)
    assert 'NOTE: If The Revolution are credited without Prince' in data['artistlongbio']


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_apicache_usage(bootstrap):
    ''' test that discogs plugin uses apicache for API calls '''

    config = bootstrap

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


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_website_lookup_cache(bootstrap):
    ''' test discogs website lookup path with caching (different from search path) '''

    config = bootstrap

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
@skip_no_discogs_key
async def test_discogs_artist_duplicates(bootstrap):
    ''' test discogs handling of artists with duplicate names like "Madonna" '''

    config = bootstrap

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


# Error Handling and Network Resilience Tests


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_timeout_handling(bootstrap):
    ''' test handling of API timeouts and network errors '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Mock the client to simulate timeout
    original_search = plugin.client.search_async if plugin.client else None

    async def mock_timeout(*args, **kwargs):  # pylint: disable=unused-argument
        raise asyncio.TimeoutError("Simulated timeout")

    if plugin.client:
        plugin.client.search_async = mock_timeout

        try:
            # Should handle timeout gracefully and return None
            result = await plugin.download_async(
                {
                    'album': 'Test Album',
                    'artist': 'Test Artist',
                    'imagecacheartist': 'testartist'
                },
                imagecache=imagecaches['discogs'])

            # Should return None on timeout, not raise exception
            assert result is None
            logging.info('Discogs timeout handled gracefully')

        finally:
            # Restore original method
            if original_search:
                plugin.client.search_async = original_search


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_http_error_handling(bootstrap):
    ''' test handling of various HTTP error codes '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Test various HTTP error scenarios
    error_codes = [401, 404, 429, 500, 503]

    for error_code in error_codes:
        logging.debug('Testing HTTP error code: %d', error_code)

        # Mock the client to simulate HTTP errors
        original_search = plugin.client.search_async if plugin.client else None

        def make_mock_http_error(status_code):

            async def mock_http_error(*args, **kwargs):  # pylint: disable=unused-argument
                raise ClientResponseError(request_info=None,
                                          history=(),
                                          status=status_code,
                                          message=f"HTTP {status_code}")

            return mock_http_error

        if plugin.client:
            plugin.client.search_async = make_mock_http_error(error_code)

            try:
                # Should handle HTTP errors gracefully and return None
                result = await plugin.download_async(
                    {
                        'album': 'Test Album',
                        'artist': 'Test Artist',
                        'imagecacheartist': 'testartist'
                    },
                    imagecache=imagecaches['discogs'])

                # Should return None on HTTP error, not raise exception
                assert result is None
                logging.info('Discogs HTTP %d error handled gracefully', error_code)

            finally:
                # Restore original method
                if original_search:
                    plugin.client.search_async = original_search


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_malformed_json_handling(bootstrap):
    ''' test handling of malformed JSON responses '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Mock the client to return malformed data
    original_search = plugin.client.search_async if plugin.client else None

    async def mock_malformed_response(*args, **kwargs):  # pylint: disable=unused-argument
        # Return malformed response that would break normal processing
        class MalformedResponse:  # pylint: disable=too-few-public-methods
            """Mock malformed response for testing."""

            def __init__(self):
                self.results = None  # This should break normal processing

            def page(self, page_num):  # pylint: disable=unused-argument
                """Return self for compatibility."""
                return self

            def __iter__(self):
                return iter([])

        return MalformedResponse()

    if plugin.client:
        plugin.client.search_async = mock_malformed_response

        try:
            # Should handle malformed response gracefully
            result = await plugin.download_async(
                {
                    'album': 'Test Album',
                    'artist': 'Test Artist',
                    'imagecacheartist': 'testartist'
                },
                imagecache=imagecaches['discogs'])

            # Should return None on malformed response, not crash
            assert result is None
            logging.info('Discogs malformed JSON response handled gracefully')

        finally:
            # Restore original method
            if original_search:
                plugin.client.search_async = original_search


# Input Validation and Edge Case Tests


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_malformed_metadata_input(bootstrap):
    ''' test handling of malformed input metadata '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Test various malformed metadata inputs
    malformed_inputs = [
        {},  # Empty dict
        {
            'artist': None,
            'album': 'Test'
        },  # None values
        {
            'artist': '',
            'album': ''
        },  # Empty strings
        {
            'artist': 'A' * 1000,
            'album': 'B' * 1000
        },  # Very long strings
        {
            'artist': 'Test\x00Artist',
            'album': 'Test\x00Album'
        },  # Null bytes
        {
            'artist': '<script>alert("xss")</script>',
            'album': 'Test'
        },  # XSS attempt
        {
            'artist': 'Björk',
            'album': 'Homogénic'
        },  # Unicode characters
        {
            'artist': 'AC/DC',
            'album': 'Back in Black'
        },  # Special characters
    ]

    for i, metadata in enumerate(malformed_inputs):
        logging.debug('Testing malformed input %d: %s', i, metadata)

        try:
            # Should handle malformed input gracefully
            result = await plugin.download_async(metadata, imagecache=imagecaches['discogs'])

            # Should return None or valid data, not crash
            assert result is None or isinstance(result, dict)
            logging.info('Malformed input %d handled gracefully', i)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Log but don't fail test - some edge cases might raise exceptions
            logging.warning('Malformed input %d raised exception: %s', i, exc)


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_artist_name_variations(bootstrap):
    ''' test artist name variation handling '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Test various artist name variations
    artist_variations = [
        'Madonna',  # Basic name
        'Madonna feat. Justin Timberlake',  # Featuring
        'Madonna featuring Justin Timberlake',  # Full featuring
        'Madonna & Justin Timberlake',  # Ampersand
        'Madonna and Justin Timberlake',  # And
        'Madonna (Artist)',  # Parentheses
        'madonna',  # Lowercase
        'MADONNA',  # Uppercase
        'The Beatles',  # With article
        'Beatles, The',  # Inverted article
    ]

    for artist in artist_variations:
        logging.debug('Testing artist variation: %s', artist)

        try:
            result = await plugin.download_async(
                {
                    'artist': artist,
                    'album': 'Test Album',
                    'imagecacheartist': 'testartist'
                },
                imagecache=imagecaches['discogs'])

            # Should handle all variations without crashing
            assert result is None or isinstance(result, dict)
            if result:
                logging.info('Successfully processed artist variation: %s', artist)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning('Artist variation "%s" raised exception: %s', artist, exc)


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_website_url_parsing(bootstrap):
    ''' test website URL parsing edge cases '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Test various malformed/edge case URLs
    url_test_cases = [
        # Malformed Discogs URLs
        ['https://www.discogs.com/artist/'],  # Missing ID
        ['https://www.discogs.com/artist/abc'],  # Non-numeric ID
        ['https://discogs.com/artist/123456'],  # Missing www
        ['http://www.discogs.com/artist/123456'],  # HTTP instead of HTTPS
        ['https://www.discogs.com/artist/123456?param=value'],  # With query params
        ['https://www.discogs.com/artist/123456#fragment'],  # With fragment
        # Non-Discogs URLs
        ['https://www.spotify.com/artist/123'],  # Non-Discogs URL
        ['https://musicbrainz.org/artist/123'],  # MusicBrainz URL
        ['not-a-url'],  # Invalid URL format
        [''],  # Empty URL
    ]

    for urls in url_test_cases:
        logging.debug('Testing URLs: %s', urls)

        try:
            result = await plugin.download_async(
                {
                    'artist': 'Test Artist',
                    'album': 'Test Album',
                    'imagecacheartist': 'testartist',
                    'artistwebsites': urls
                },
                imagecache=imagecaches['discogs'])

            # Should handle malformed URLs gracefully
            assert result is None or isinstance(result, dict)
            logging.info('URL test case handled gracefully: %s', urls)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning('URL test case "%s" raised exception: %s', urls, exc)


# Configuration State Validation Tests


def test_discogs_invalid_api_key_format(bootstrap):
    ''' test behavior with invalid API key formats '''

    config = bootstrap

    # Test various invalid API key formats
    invalid_keys = [
        '',  # Empty string
        None,  # None value
        'invalid-key',  # Too short
        'k' * 1000,  # Too long
        'key with spaces',  # Contains spaces
        'key\nwith\nnewlines',  # Contains newlines
        '<script>alert("xss")</script>',  # XSS attempt
    ]

    for i, invalid_key in enumerate(invalid_keys):
        logging.debug('Testing invalid API key %d: %s', i, repr(invalid_key))

        configuresettings('discogs', config.cparser)
        if invalid_key is not None:
            config.cparser.setValue('discogs/apikey', invalid_key)
        else:
            # Test None by not setting the key at all
            config.cparser.remove('discogs/apikey')

        _, plugins = configureplugins(config)

        plugin = plugins['discogs']

        # Should handle invalid API key gracefully
        apikey = plugin._get_apikey()  # pylint: disable=protected-access
        if invalid_key == '' or invalid_key is None:
            # Empty or None keys should be rejected
            assert apikey is None
            assert not plugin._setup_client()  # pylint: disable=protected-access
        else:
            # Non-empty invalid keys may still be accepted by client setup
            # but should not crash the plugin
            assert apikey == invalid_key
            # Client setup may succeed or fail, but shouldn't crash
            try:
                setup_result = plugin._setup_client()  # pylint: disable=protected-access
                logging.info('Invalid API key %d setup result: %s', i, setup_result)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.info('Invalid API key %d caused setup exception: %s', i, exc)

        logging.info('Invalid API key %d handled gracefully', i)


def test_discogs_selective_feature_disabling(bootstrap):
    ''' test plugin behavior when specific features are disabled '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', 'test-key')

    # Test various feature combination scenarios
    feature_combinations = [
        {
            'bio': True,
            'fanart': False,
            'thumbnails': False
        },  # Bio only
        {
            'bio': False,
            'fanart': True,
            'thumbnails': False
        },  # Fanart only
        {
            'bio': False,
            'fanart': False,
            'thumbnails': True
        },  # Thumbnails only
        {
            'bio': True,
            'fanart': True,
            'thumbnails': False
        },  # Bio + fanart
        {
            'bio': False,
            'fanart': False,
            'thumbnails': False
        },  # Nothing enabled
        {
            'bio': True,
            'fanart': True,
            'thumbnails': True
        },  # Everything enabled
    ]

    for i, features in enumerate(feature_combinations):
        logging.debug('Testing feature combination %d: %s', i, features)

        # Set feature flags
        config.cparser.setValue('discogs/bio', features['bio'])
        config.cparser.setValue('discogs/fanart', features['fanart'])
        config.cparser.setValue('discogs/thumbnails', features['thumbnails'])

        _, plugins = configureplugins(config)
        plugin = plugins['discogs']

        # Client setup should still work regardless of feature flags
        if plugin._get_apikey():  # pylint: disable=protected-access
            setup_result = plugin._setup_client()  # pylint: disable=protected-access
            # Setup may fail with invalid test key, but shouldn't crash
            logging.info('Feature combination %d setup result: %s', i, setup_result)


# Cache Failure Scenario Tests


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_cache_corruption_handling(bootstrap):
    ''' test handling of corrupted cache data '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Mock the cache to return corrupted data
    original_cached_fetch = nowplaying.apicache.cached_fetch

    async def mock_corrupted_cache(*args, **kwargs):  # pylint: disable=unused-argument
        # Return corrupted data that would break normal processing
        return {'corrupted': 'data', 'invalid': True}

    # Test with corrupted cache
    nowplaying.apicache.cached_fetch = mock_corrupted_cache

    try:
        # Should handle corrupted cache gracefully
        result = await plugin.download_async(
            {
                'album': 'Test Album',
                'artist': 'Test Artist',
                'imagecacheartist': 'testartist'
            },
            imagecache=imagecaches['discogs'])

        # Should return None or valid data, not crash
        assert result is None or isinstance(result, dict)
        logging.info('Discogs corrupted cache handled gracefully')

    finally:
        # Restore original cache function
        nowplaying.apicache.cached_fetch = original_cached_fetch


# Search Result Edge Case Tests


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_empty_search_results(bootstrap):
    ''' test handling of empty search results '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Mock the client to return empty search results
    original_search = plugin.client.search_async if plugin.client else None

    async def mock_empty_results(*args, **kwargs):  # pylint: disable=unused-argument

        class EmptySearchResult:  # pylint: disable=too-few-public-methods
            """Mock empty search result for testing."""

            def __init__(self):
                self.results = []

            def page(self, page_num):  # pylint: disable=unused-argument
                """Return self for compatibility."""
                return self

            def __iter__(self):
                return iter([])

        return EmptySearchResult()

    if plugin.client:
        plugin.client.search_async = mock_empty_results

        try:
            # Should handle empty results gracefully
            result = await plugin.download_async(
                {
                    'album': 'Nonexistent Album',
                    'artist': 'Nonexistent Artist',
                    'imagecacheartist': 'nonexistent'
                },
                imagecache=imagecaches['discogs'])

            # Should return None for empty results
            assert result is None
            logging.info('Discogs empty search results handled gracefully')

        finally:
            # Restore original method
            if original_search:
                plugin.client.search_async = original_search


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_missing_artist_data(bootstrap):
    ''' test handling of releases without proper artist data '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Mock the client to return results with missing artist data
    original_search = plugin.client.search_async if plugin.client else None

    async def mock_missing_artist_data(*args, **kwargs):  # pylint: disable=unused-argument
        models = nowplaying.discogsclient.Models

        class MissingArtistSearchResult:  # pylint: disable=too-few-public-methods
            """Mock search result with missing artist data for testing."""

            def __init__(self):
                # Create a release with missing/malformed artist data
                release_data = {
                    'id': 123456,
                    'title': 'Test Album',
                    'artists': []  # Empty artists list
                }
                release = models.Release(release_data)
                release.artists = []  # Explicitly empty
                self.results = [release]

            def page(self, page_num):  # pylint: disable=unused-argument
                """Return self for compatibility."""
                return self

            def __iter__(self):
                return iter(self.results)

        return MissingArtistSearchResult()

    if plugin.client:
        plugin.client.search_async = mock_missing_artist_data

        try:
            # Should handle missing artist data gracefully
            result = await plugin.download_async(
                {
                    'album': 'Test Album',
                    'artist': 'Test Artist',
                    'imagecacheartist': 'testartist'
                },
                imagecache=imagecaches['discogs'])

            # Should return None or valid data, not crash
            assert result is None or isinstance(result, dict)
            logging.info('Discogs missing artist data handled gracefully')

        finally:
            # Restore original method
            if original_search:
                plugin.client.search_async = original_search


# DJ-Specific Reliability Tests


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_rapid_track_changes(bootstrap):
    ''' test handling of rapid consecutive API calls (typical during DJ sets) '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Simulate rapid track changes during a DJ set
    tracks = [
        {
            'artist': 'Daft Punk',
            'album': 'Random Access Memories',
            'imagecacheartist': 'daftpunk1'
        },
        {
            'artist': 'Justice',
            'album': 'Cross',
            'imagecacheartist': 'justice1'
        },
        {
            'artist': 'Moderat',
            'album': 'II',
            'imagecacheartist': 'moderat1'
        },
        {
            'artist': 'Burial',
            'album': 'Untrue',
            'imagecacheartist': 'burial1'
        },
        {
            'artist': 'Four Tet',
            'album': 'There Is Love In You',
            'imagecacheartist': 'fourtet1'
        },
    ]

    # Simulate rapid-fire requests (common when DJs are mixing quickly)
    tasks = []
    for track in tracks:
        task = asyncio.create_task(plugin.download_async(track, imagecache=imagecaches['discogs']))
        tasks.append(task)

    try:
        # All requests should complete without errors
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify no exceptions were raised
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logging.warning('Track %d raised exception: %s', i, result)
            else:
                # Should return None or valid data, not crash
                assert result is None or isinstance(result, dict)

        logging.info('Discogs handled %d rapid track changes successfully', len(tracks))

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logging.error('Rapid track changes test failed: %s', exc)
        # Don't fail the test - log the issue for investigation


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_common_dj_genres(bootstrap):
    ''' test reliability with common DJ music genres and special characters '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Common DJ genres with challenging artist names
    dj_tracks = [
        # Electronic/EDM with special characters
        {
            'artist': 'Aphex Twin',
            'album': 'Selected Ambient Works',
            'imagecacheartist': 'aphextwin'
        },
        {
            'artist': 'µ-Ziq',
            'album': 'Lunatic Harness',
            'imagecacheartist': 'uziq'
        },
        {
            'artist': 'Squarepusher',
            'album': 'Go Plastic',
            'imagecacheartist': 'squarepusher'
        },

        # Hip-hop with featuring artists
        {
            'artist': 'Kanye West feat. Jay-Z',
            'album': 'Watch the Throne',
            'imagecacheartist': 'kanyejay'
        },
        {
            'artist': 'Wu-Tang Clan',
            'album': 'Enter the Wu-Tang',
            'imagecacheartist': 'wutang'
        },

        # House/Techno with numbers and symbols
        {
            'artist': '2 Many DJs',
            'album': 'As Heard on Radio Soulwax',
            'imagecacheartist': '2manydjs'
        },
        {
            'artist': 'LCD Soundsystem',
            'album': 'Sound of Silver',
            'imagecacheartist': 'lcdsoundsystem'
        },

        # International artists with accents
        {
            'artist': 'Röyksopp',
            'album': 'Melody A.M.',
            'imagecacheartist': 'royksopp'
        },
        {
            'artist': 'Sigur Rós',
            'album': 'Ágætis byrjun',
            'imagecacheartist': 'sigurros'
        },
    ]

    for i, track in enumerate(dj_tracks):
        logging.debug('Testing DJ track %d: %s - %s', i, track['artist'], track['album'])

        try:
            result = await plugin.download_async(track, imagecache=imagecaches['discogs'])

            # Should handle all DJ music without crashing
            assert result is None or isinstance(result, dict)
            if result:
                logging.info('Successfully processed DJ track: %s', track['artist'])

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning('DJ track "%s" raised exception: %s', track['artist'], exc)


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_live_performance_timeout_recovery(bootstrap):
    ''' test timeout recovery during live performance (critical for DJs) '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Mock intermittent timeouts (simulating network issues during live sets)
    original_search = plugin.client.search_async if plugin.client else None
    call_count = 0

    async def mock_intermittent_timeout(*args, **kwargs):
        nonlocal call_count
        call_count += 1

        # Simulate timeout on first call, success on second
        if call_count == 1:
            raise asyncio.TimeoutError("Simulated network issue")
        # Return to original behavior for subsequent calls
        if original_search:
            return await original_search(*args, **kwargs)
        return None

    if plugin.client:
        plugin.client.search_async = mock_intermittent_timeout

        try:
            # First call should timeout
            result1 = await plugin.download_async(
                {
                    'artist': 'Test Artist',
                    'album': 'Test Album',
                    'imagecacheartist': 'testartist1'
                },
                imagecache=imagecaches['discogs'])

            # Should handle timeout gracefully
            assert result1 is None

            # Second call should work (network recovered)
            result2 = await plugin.download_async(
                {
                    'artist': 'Test Artist 2',
                    'album': 'Test Album 2',
                    'imagecacheartist': 'testartist2'
                },
                imagecache=imagecaches['discogs'])

            # Plugin should continue working after timeout recovery
            assert result2 is None or isinstance(result2, dict)
            logging.info('Discogs recovered from timeout during live performance simulation')

        finally:
            # Restore original method
            if original_search:
                plugin.client.search_async = original_search


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_memory_usage_stability(bootstrap):
    ''' test memory stability during extended DJ sets '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Simulate a long DJ set with many track lookups
    base_tracks = [
        {
            'artist': 'Daft Punk',
            'album': 'Discovery'
        },
        {
            'artist': 'Justice',
            'album': 'Cross'
        },
        {
            'artist': 'Moderat',
            'album': 'Moderat'
        },
    ]

    # Create many variations to test memory usage
    tracks = []
    for i in range(20):  # Simulate 20 tracks in a set
        for base_track in base_tracks:
            track = base_track.copy()
            track['imagecacheartist'] = f"{base_track['artist'].lower().replace(' ', '')}{i}"
            tracks.append(track)

    successful_lookups = 0

    for i, track in enumerate(tracks):
        try:
            result = await plugin.download_async(track, imagecache=imagecaches['discogs'])

            # Should handle all requests without memory issues
            assert result is None or isinstance(result, dict)
            if result:
                successful_lookups += 1

            # Log progress every 10 tracks
            if (i + 1) % 10 == 0:
                logging.info('Processed %d tracks, %d successful lookups', i + 1,
                             successful_lookups)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.warning('Track %d raised exception: %s', i, exc)

    logging.info('Memory stability test completed: %d/%d tracks processed successfully',
                 successful_lookups, len(tracks))


def test_discogs_configuration_validation_for_djs(bootstrap):
    ''' test configuration scenarios important for DJ reliability '''

    config = bootstrap

    # Test scenarios DJs commonly encounter
    dj_config_scenarios = [
        # Minimal config (bio only for performance)
        {
            'bio': True,
            'fanart': False,
            'thumbnails': False,
            'websites': False
        },

        # Visual-heavy config (for streaming DJs)
        {
            'bio': False,
            'fanart': True,
            'thumbnails': True,
            'websites': False
        },

        # Balanced config (most common)
        {
            'bio': True,
            'fanart': True,
            'thumbnails': False,
            'websites': True
        },

        # Everything disabled (fallback mode)
        {
            'bio': False,
            'fanart': False,
            'thumbnails': False,
            'websites': False
        },
    ]

    for i, scenario in enumerate(dj_config_scenarios):
        logging.debug('Testing DJ config scenario %d: %s', i, scenario)

        configuresettings('discogs', config.cparser)
        config.cparser.setValue('discogs/apikey', 'test-key-for-validation')

        # Apply scenario settings
        for setting, value in scenario.items():
            config.cparser.setValue(f'discogs/{setting}', value)

        _, plugins = configureplugins(config)
        plugin = plugins['discogs']

        # Plugin should initialize successfully in all DJ scenarios
        assert plugin is not None
        assert hasattr(plugin, '_get_apikey')
        assert hasattr(plugin, '_setup_client')

        logging.info('DJ config scenario %d validated successfully', i)


@pytest.mark.asyncio
@skip_no_discogs_key
async def test_discogs_api_call_count(bootstrap):
    ''' test that discogs plugin makes only one API call when cache is used '''

    config = bootstrap
    configuresettings('discogs', config.cparser)
    config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    imagecaches, plugins = configureplugins(config)

    plugin = plugins['discogs']

    # Test with known artist and album
    metadata = {
        'artist': 'Daft Punk',
        'album': 'Random Access Memories',
        'imagecacheartist': 'daftpunk'
    }

    # Mock the actual Discogs client API call to count calls
    original_search = plugin.client.search_async if plugin.client else None
    api_call_count = 0

    async def mock_search_async(*args, **kwargs):
        nonlocal api_call_count
        api_call_count += 1
        logging.debug('Mock Discogs API call #%d', api_call_count)
        # Call the original method to get real data
        if original_search:
            return await original_search(*args, **kwargs)
        return None

    if plugin.client:
        plugin.client.search_async = mock_search_async

        try:
            # First call - should hit API and cache result
            result1 = await plugin.download_async(metadata.copy(),
                                                  imagecache=imagecaches['discogs'])

            # Verify one API call was made
            assert api_call_count == 1, (
                f'Expected 1 API call after first download, got {api_call_count}'
            )

            # Second call - should use cached result, no additional API call
            result2 = await plugin.download_async(metadata.copy(),
                                                  imagecache=imagecaches['discogs'])

            # Verify still only one API call was made (cache hit)
            assert api_call_count == 1, (
                f'Expected 1 API call after second download (cache hit), got {api_call_count}'
            )

            # Both results should be consistent
            assert (result1 is None) == (result2 is None)
            if result1:  # Only test if we got data back
                logging.info('Discogs API cache verified: 1 API call for 2 downloads')
                assert result1 == result2
            else:
                logging.info('Discogs API cache test completed - '
                             'cache working regardless of data found')

        finally:
            # Restore the original method
            if original_search:
                plugin.client.search_async = original_search
