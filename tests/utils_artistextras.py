#!/usr/bin/env python3
"""
Test utilities for artistextras plugins.

This module provides reusable helper functions and fixtures for testing
artistextras plugins, particularly around API caching functionality.
"""

import logging
import os
import typing as t

import pytest

# Shared pytest.mark.skipif decorators for API key requirements
skip_no_discogs_key = pytest.mark.skipif(
    not os.environ.get('DISCOGS_API_KEY'),
    reason="Discogs API key not available"
)

skip_no_fanarttv_key = pytest.mark.skipif(
    not os.environ.get('FANARTTV_API_KEY'),
    reason="FanartTV API key not available"
)

skip_no_theaudiodb_key = pytest.mark.skipif(
    not os.environ.get('THEAUDIODB_API_KEY'),
    reason="TheAudioDB API key not available"
)

skip_no_acoustid_key = pytest.mark.skipif(
    not os.environ.get('ACOUSTID_TEST_APIKEY'),
    reason="AcoustID test API key not available"
)



class FakeImageCache:  # pylint: disable=too-few-public-methods
    """A fake ImageCache that just keeps track of urls"""

    def __init__(self):
        self.urls = {}

    def fill_queue(
            self,
            config=None,  # pylint: disable=unused-argument
            identifier: str = None,
            imagetype: str = None,
            srclocationlist: t.List[str] = None):
        """Just keep track of what was picked"""
        if not self.urls.get(identifier):
            self.urls[identifier] = {}
        self.urls[identifier][imagetype] = srclocationlist


def configureplugins(config):
    """Configure plugins for testing"""
    plugins = ['wikimedia']
    if os.environ.get('DISCOGS_API_KEY'):
        plugins.append('discogs')
    if os.environ.get('FANARTTV_API_KEY'):
        plugins.append('fanarttv')
    if os.environ.get('THEAUDIODB_API_KEY'):
        plugins.append('theaudiodb')

    imagecaches = {}
    plugin_objects = {}
    for pluginname in plugins:
        imagecaches[pluginname] = FakeImageCache()
        plugin_objects[pluginname] = config.pluginobjs['artistextras'][
            f'nowplaying.artistextras.{pluginname}']
    return imagecaches, plugin_objects


def configuresettings(pluginname, cparser):
    """Configure each setting for a plugin"""
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


# Cache testing helpers
async def run_cache_consistency_test(plugin, test_metadata, imagecache=None, success_message=""):
    """
    Generic cache consistency test helper.

    Args:
        plugin: The plugin instance to test
        test_metadata: Metadata dict to use for testing
        imagecache: Image cache to use (optional)
        success_message: Message to log on successful cache verification

    Returns:
        (result1, result2): The two results from consecutive calls
    """

    # First call - should hit API and cache result
    result1 = await plugin.download_async(test_metadata.copy(), imagecache=imagecache)

    # Second call - should use cached result
    result2 = await plugin.download_async(test_metadata.copy(), imagecache=imagecache)

    # Both results should be consistent (either both None or both have data)
    assert (result1 is None) == (result2 is None)

    if result1:  # Only test if we got data back
        if success_message:
            logging.info(success_message)
        # Should return the same metadata structure
        assert result1 == result2

    return result1, result2


async def run_api_call_count_test(plugin, test_metadata, mock_method_name, imagecache=None):
    """
    Generic API call count test helper with mocking.

    Args:
        plugin: The plugin instance to test
        test_metadata: Metadata dict to use for testing
        mock_method_name: Name of the plugin method to mock (e.g., '_fetch_async')
        imagecache: Image cache to use (optional)

    Returns:
        api_call_count: Number of API calls made
    """

    # Mock the internal API method to count calls
    original_method = getattr(plugin, mock_method_name)
    api_call_count = 0

    async def mock_method(*args, **kwargs):
        nonlocal api_call_count
        api_call_count += 1
        logging.debug('Mock API call #%d', api_call_count)
        # Call the original method to get real data
        return await original_method(*args, **kwargs)

    # Replace the method with our mock
    setattr(plugin, mock_method_name, mock_method)

    try:
        # First call - should hit API and cache result
        result1 = await plugin.download_async(test_metadata.copy(), imagecache=imagecache)

        # Verify one API call was made
        assert api_call_count == 1, (
            f'Expected 1 API call after first download, got {api_call_count}'
        )

        # Second call - should use cached result, no additional API call
        result2 = await plugin.download_async(test_metadata.copy(), imagecache=imagecache)

        # Verify still only one API call was made (cache hit)
        assert api_call_count == 1, (
            f'Expected 1 API call after second download (cache hit), got {api_call_count}'
        )

        # Both results should be consistent
        assert (result1 is None) == (result2 is None)

        if result1:  # Only test if we got data back
            logging.info('API cache verified: 1 API call for 2 downloads')
            assert result1 == result2
        else:
            logging.info('API cache test completed - cache working regardless of data found')

    finally:
        # Restore the original method
        setattr(plugin, mock_method_name, original_method)

    return api_call_count


async def run_failure_cache_test(plugin, test_metadata, mock_method_name, imagecache=None):
    """
    Generic API failure cache behavior test helper.

    Tests that failures are not cached but successes are.

    Args:
        plugin: The plugin instance to test
        test_metadata: Metadata dict to use for testing
        mock_method_name: Name of the plugin method to mock
        imagecache: Image cache to use (optional)
    """

    # Mock the internal API method to simulate failures then success
    original_method = getattr(plugin, mock_method_name)
    api_call_count = 0

    async def mock_method_with_failure(*args, **kwargs):  # pylint: disable=unused-argument
        nonlocal api_call_count
        api_call_count += 1
        logging.debug('Mock API call #%d', api_call_count)

        if api_call_count == 1:
            # First call: simulate API failure
            logging.debug('Simulating API failure on first call')
            return None
        if api_call_count == 2:
            # Second call: simulate successful response
            logging.debug('Simulating successful API response on second call')
            # Return a minimal success response - adapt based on plugin
            return {'name': test_metadata.get('artist', 'Test Artist')}

        # Subsequent calls: should not happen if caching works correctly
        logging.debug('Unexpected additional API call')
        return {'name': test_metadata.get('artist', 'Test Artist')}

    # Replace the method with our mock
    setattr(plugin, mock_method_name, mock_method_with_failure)

    try:
        # First call - API fails, should return None and NOT cache the failure
        result1 = await plugin.download_async(test_metadata.copy(), imagecache=imagecache)

        # Verify one API call was made and result is None (failure)
        assert api_call_count == 1, (
            f'Expected 1 API call after first download, got {api_call_count}'
        )
        assert result1 is None, 'Expected None result from failed API call'

        # Second call - should retry API (not use cached failure), API succeeds this time
        result2 = await plugin.download_async(test_metadata.copy(), imagecache=imagecache)

        # Verify second API call was made (failure wasn't cached)
        assert api_call_count == 2, (
            f'Expected 2 API calls after second download (failure not cached), got {api_call_count}'
        )

        # Third call - should use cached success result, no additional API call
        result3 = await plugin.download_async(test_metadata.copy(), imagecache=imagecache)

        # Verify still only two API calls (success result was cached)
        assert api_call_count == 2, (
            f'Expected 2 API calls after third download (success cached), got {api_call_count}'
        )

        # Results should show the pattern: None (failure), data (success), data (cached success)
        assert result1 is None, 'First result should be None (API failure)'
        assert result2 == result3, 'Second and third results should be identical (cached success)'

        logging.info('API failure cache behavior verified: failures not cached, successes cached')

    finally:
        # Restore the original method
        setattr(plugin, mock_method_name, original_method)
