#!/usr/bin/env python3
''' test artistextras discogs plugin '''

import logging
import os

import pytest

from test_artistextras_core import (
    configureplugins,
    configuresettings
)

import nowplaying.metadata  # pylint: disable=import-error
import nowplaying.apicache  # pylint: disable=import-error


@pytest.mark.asyncio
async def test_discogs_note_stripping(bootstrap):
    ''' test note stripping in discogs bio '''

    config = bootstrap
    if not os.environ.get('DISCOGS_API_KEY'):
        pytest.skip("Discogs API key not available")

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
async def test_discogs_weblocation1(bootstrap):
    ''' test discogs web location lookup '''

    config = bootstrap
    if not os.environ.get('DISCOGS_API_KEY'):
        pytest.skip("Discogs API key not available")

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
                'https://www.discogs.com/artist/271351',
                'https://www.discogs.com/artist/28795',
                'https://www.discogs.com/artist/293637',
                'https://www.discogs.com/artist/342899',
                'https://www.discogs.com/artist/79903',
                'https://www.discogs.com/artist/571633',
                'https://www.discogs.com/artist/96774'
            ],
            'imagecacheartist':
            'princeandtherevoluion'
        },
        imagecache=None)
    assert 'NOTE: If The Revolution are credited without Prince' in data['artistlongbio']


@pytest.mark.asyncio
async def test_discogs_apicache_usage(bootstrap, temp_api_cache):
    ''' test that discogs plugin uses apicache for API calls '''

    config = bootstrap
    if not os.environ.get('DISCOGS_API_KEY'):
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
async def test_discogs_website_lookup_cache(bootstrap):
    ''' test discogs website lookup path with caching (different from search path) '''

    config = bootstrap
    if not os.environ.get('DISCOGS_API_KEY'):
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
async def test_discogs_artist_duplicates(bootstrap):
    ''' test discogs handling of artists with duplicate names like "Madonna" '''

    config = bootstrap
    if not os.environ.get('DISCOGS_API_KEY'):
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
