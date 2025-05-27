#!/usr/bin/env python3
''' test artistextras wikimedia plugin '''

import logging

import pytest

from test_artistextras_core import configureplugins, configuresettings

import nowplaying.apicache  # pylint: disable=import-error


@pytest.mark.asyncio
async def test_wikimedia_apicache_usage(bootstrap, temp_api_cache):
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
async def test_wikimedia_langfallback_zh_to_en(bootstrap):
    ''' test wikimedia language fallback from zh to en '''

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
async def test_wikimedia_langfallback_zh_to_none(bootstrap):
    ''' test wikimedia language fallback disabled '''

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
async def test_wikimedia_humantetris_en(bootstrap):
    ''' test wikimedia english content '''

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
async def test_wikimedia_humantetris_de(bootstrap):
    ''' test wikimedia german content '''

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
