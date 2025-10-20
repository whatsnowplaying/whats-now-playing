#!/usr/bin/env python3
"""test artistextras fanarttv plugin"""

import os

import pytest
from utils_artistextras import (
    configureplugins,
    configuresettings,
    run_api_call_count_test,
    run_cache_consistency_test,
    run_failure_cache_test,
    skip_no_fanarttv_key,
)

import nowplaying.apicache  # pylint: disable=import-error


def _setup_fanarttv_plugin(bootstrap):
    """Set up FanartTV plugin for testing"""
    config = bootstrap
    configuresettings("fanarttv", config.cparser)
    config.cparser.setValue("fanarttv/apikey", os.environ["FANARTTV_API_KEY"])
    imagecaches, plugins = configureplugins(config)
    return plugins["fanarttv"], imagecaches["fanarttv"]


def _get_test_metadata():
    """Get test metadata for FanartTV (requires MBID)"""
    return {
        "album": "The Downward Spiral",
        "artist": "Nine Inch Nails",
        "imagecacheartist": "nineinchnails",
        "musicbrainzartistid": ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"],  # NIN's MBID
    }


@pytest.mark.asyncio
@skip_no_fanarttv_key
async def test_fanarttv_apicache_usage(bootstrap):
    """test that fanarttv plugin uses apicache for API calls"""
    plugin, imagecache = _setup_fanarttv_plugin(bootstrap)

    await run_cache_consistency_test(
        plugin=plugin,
        test_metadata=_get_test_metadata(),
        imagecache=imagecache,
        success_message="FanartTV API call successful, caching verified",
    )


@pytest.mark.asyncio
@skip_no_fanarttv_key
async def test_fanarttv_apicache_api_call_count(bootstrap, temp_api_cache):  # pylint: disable=redefined-outer-name
    """test that fanarttv plugin makes only one API call when cache is used"""
    # Use the temp cache for this test
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(temp_api_cache)

    try:
        plugin, imagecache = _setup_fanarttv_plugin(bootstrap)

        await run_api_call_count_test(
            plugin=plugin,
            test_metadata=_get_test_metadata(),
            mock_method_name="_fetch_async",
            imagecache=imagecache,
        )
    finally:
        # Restore original cache
        nowplaying.apicache.set_cache_instance(original_cache)


@pytest.mark.asyncio
@skip_no_fanarttv_key
async def test_fanarttv_apicache_api_failure_behavior(bootstrap, temp_api_cache):  # pylint: disable=redefined-outer-name
    """test that fanarttv plugin doesn't cache failed API calls"""
    # Use the temp cache for this test
    original_cache = nowplaying.apicache._global_cache_instance  # pylint: disable=protected-access
    nowplaying.apicache.set_cache_instance(temp_api_cache)

    try:
        plugin, imagecache = _setup_fanarttv_plugin(bootstrap)

        # Use test metadata with invalid MBID to trigger failure
        test_metadata = {
            "album": "Test Album",
            "artist": "Test Artist",
            "imagecacheartist": "testartist",
            "musicbrainzartistid": ["invalid-mbid-that-will-fail"],  # Invalid MBID
        }

        await run_failure_cache_test(
            plugin=plugin,
            test_metadata=test_metadata,
            mock_method_name="_fetch_async",
            imagecache=imagecache,
        )
    finally:
        # Restore original cache
        nowplaying.apicache.set_cache_instance(original_cache)
