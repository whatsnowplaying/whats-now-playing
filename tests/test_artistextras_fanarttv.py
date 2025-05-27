#!/usr/bin/env python3
''' test artistextras fanarttv plugin '''

import logging
import os

import pytest

from test_artistextras_core import configureplugins, configuresettings

import nowplaying.apicache  # pylint: disable=import-error


@pytest.mark.asyncio
async def test_fanarttv_apicache_usage(bootstrap, temp_api_cache):
    ''' test that fanarttv plugin uses apicache for API calls '''

    config = bootstrap
    if not os.environ.get('FANARTTV_API_KEY'):
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
async def test_fanarttv_apicache_api_call_count(bootstrap, temp_api_cache):
    ''' test that fanarttv plugin makes only one API call when cache is used '''

    config = bootstrap
    if not os.environ.get('FANARTTV_API_KEY'):
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
        original_fetch_async = plugin._fetch_async  # pylint: disable=protected-access
        api_call_count = 0

        async def mock_fetch_async(apikey, artistid):
            nonlocal api_call_count
            api_call_count += 1
            logging.debug('Mock API call #%d for artistid: %s', api_call_count, artistid)
            # Call the original method to get real data
            return await original_fetch_async(apikey, artistid)

        # Replace the method with our mock
        plugin._fetch_async = mock_fetch_async  # pylint: disable=protected-access

        try:
            # First call - should hit API and cache result
            result1 = await plugin.download_async(metadata_with_mbid.copy(),
                                                 imagecache=imagecaches['fanarttv'])

            # Verify one API call was made
            assert api_call_count == 1, (
                f'Expected 1 API call after first download, '
                f'got {api_call_count}'
            )

            # Second call - should use cached result, no additional API call
            result2 = await plugin.download_async(metadata_with_mbid.copy(),
                                                 imagecache=imagecaches['fanarttv'])

            # Verify still only one API call was made (cache hit)
            assert api_call_count == 1, (
                f'Expected 1 API call after second download (cache hit), '
                f'got {api_call_count}'
            )

            # Both results should be consistent
            assert (result1 is None) == (result2 is None)

            if result1:  # Only test if we got data back
                logging.info('FanartTV API cache verified: 1 API call for 2 downloads')
                assert result1 == result2
            else:
                logging.info('FanartTV API cache test completed - '
                           'cache working regardless of data found')

        finally:
            # Restore the original method
            plugin._fetch_async = original_fetch_async  # pylint: disable=protected-access

    finally:
        # Restore original cache
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
async def test_fanarttv_apicache_api_failure_behavior(bootstrap, temp_api_cache):
    ''' test that fanarttv plugin doesn't cache failed API calls '''

    config = bootstrap
    if not os.environ.get('FANARTTV_API_KEY'):
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
            'musicbrainzartistid': [
                'invalid-mbid-that-will-fail'  # Invalid MBID to trigger failure
            ]
        }

        # Mock the internal _fetch_async method to simulate failures then success
        original_fetch_async = plugin._fetch_async  # pylint: disable=protected-access
        api_call_count = 0

        async def mock_fetch_async_with_failure(apikey, artistid):  # pylint: disable=unused-argument
            nonlocal api_call_count
            api_call_count += 1
            logging.debug('Mock API call #%d for artistid: %s', api_call_count, artistid)

            if api_call_count == 1:
                # First call: simulate API failure (network error, timeout, etc.)
                logging.debug('Simulating API failure on first call')
                return None
            if api_call_count == 2:
                # Second call: simulate API returning valid empty response (artist not found)
                logging.debug('Simulating successful but empty API response on second call')
                return {'name': 'Test Artist', 'mbid_id': artistid}

            # Subsequent calls: should not happen if caching works correctly
            logging.debug('Unexpected additional API call')
            return {'name': 'Test Artist', 'mbid_id': artistid}

        # Replace the method with our mock
        plugin._fetch_async = mock_fetch_async_with_failure  # pylint: disable=protected-access

        try:
            # First call - API fails, should return None and NOT cache the failure
            result1 = await plugin.download_async(metadata_with_mbid.copy(),
                                                 imagecache=imagecaches['fanarttv'])

            # Verify one API call was made and result is None (failure)
            assert api_call_count == 1, (
                f'Expected 1 API call after first download, '
                f'got {api_call_count}'
            )
            assert result1 is None, 'Expected None result from failed API call'

            # Second call - should retry API (not use cached failure), API succeeds this time
            result2 = await plugin.download_async(metadata_with_mbid.copy(),
                                                 imagecache=imagecaches['fanarttv'])

            # Verify second API call was made (failure wasn't cached)
            assert api_call_count == 2, (
                f'Expected 2 API calls after second download '
                f'(failure not cached), got {api_call_count}'
            )

            # Third call - should use cached success result, no additional API call
            result3 = await plugin.download_async(metadata_with_mbid.copy(),
                                                 imagecache=imagecaches['fanarttv'])

            # Verify still only two API calls (success result was cached)
            assert api_call_count == 2, (
                f'Expected 2 API calls after third download '
                f'(success cached), got {api_call_count}'
            )

            # Results should show the pattern: None (failure), data (success), data (cached success)
            assert result1 is None, 'First result should be None (API failure)'
            assert result2 == result3, (
                'Second and third results should be identical (cached success)'
            )

            logging.info('FanartTV API failure cache behavior verified: '
                        'failures not cached, successes cached')

        finally:
            # Restore the original method
            plugin._fetch_async = original_fetch_async  # pylint: disable=protected-access

    finally:
        # Restore original cache
        nowplaying.apicache.set_cache_instance(original_cache)
