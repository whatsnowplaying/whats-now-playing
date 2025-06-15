#!/usr/bin/env python3
''' test artistextras theaudiodb plugin '''

import logging
import os

import pytest

from utils_artistextras import (configureplugins, configuresettings, skip_no_theaudiodb_key,
                                run_api_call_count_test)


def _setup_theaudiodb_plugin(bootstrap):
    """Set up TheAudioDB plugin for testing"""
    config = bootstrap
    configuresettings('theaudiodb', config.cparser)
    config.cparser.setValue('theaudiodb/apikey', os.environ['THEAUDIODB_API_KEY'])
    imagecaches, plugins = configureplugins(config)
    return plugins['theaudiodb'], imagecaches['theaudiodb']


@pytest.mark.asyncio
@skip_no_theaudiodb_key
async def test_theaudiodb_artist_name_correction(bootstrap):
    ''' test theaudiodb artist name correction for name-based vs musicbrainz searches '''

    plugin, _ = _setup_theaudiodb_plugin(bootstrap)

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
        logging.info('Artist name corrected: %s -> %s', metadata_lowercase['artist'],
                     result1['artist'])

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
@skip_no_theaudiodb_key
async def test_theaudiodb_apicache_duplicate_artists(bootstrap):
    ''' test TheAudioDB two-level caching with duplicate artist names '''

    plugin, imagecache = _setup_theaudiodb_plugin(bootstrap)

    # Test two different searches that might return different artists with similar names
    # First search - likely to match main "Madonna"
    metadata_madonna1 = {'artist': 'Madonna', 'imagecacheartist': 'madonna1'}

    # Second search - variation that might match different artist
    metadata_madonna2 = {
        'artist': 'madonna',  # lowercase variation
        'imagecacheartist': 'madonna2'
    }

    # Test both variations - first calls hit API, second calls use cache
    result1a = await plugin.download_async(metadata_madonna1.copy(), imagecache=imagecache)
    result2a = await plugin.download_async(metadata_madonna2.copy(), imagecache=imagecache)

    # Second calls - should use cached data
    result1b = await plugin.download_async(metadata_madonna1.copy(), imagecache=imagecache)
    result2b = await plugin.download_async(metadata_madonna2.copy(), imagecache=imagecache)

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
            logging.info('TheAudioDB distinguished between different artists: %s vs %s', artist1,
                         artist2)
        else:
            logging.info('TheAudioDB returned same artist for both variations')
    else:
        logging.info('TheAudioDB duplicate artist test completed - two-level caching working')

    # Test passes if two-level caching works correctly (search + individual artist ID)


@pytest.mark.asyncio
@skip_no_theaudiodb_key
async def test_theaudiodb_invalid_musicbrainz_id_fallback(bootstrap):
    ''' test theaudiodb plugin falls back to name-based search when MusicBrainz ID is invalid '''

    plugin, _ = _setup_theaudiodb_plugin(bootstrap)

    # Mock the MBID and name-based fetch methods to track calls
    original_mbid_fetch = plugin.artistdatafrommbid_async
    original_name_fetch = plugin.artistdatafromname_async

    mbid_call_count = 0
    name_call_count = 0

    async def mock_mbid_fetch(apikey, mbartistid, artist_name):  # pylint: disable=unused-argument
        nonlocal mbid_call_count
        mbid_call_count += 1
        logging.debug('MBID fetch call #%d for MBID: %s', mbid_call_count, mbartistid)

        if mbartistid == 'invalid-mbid-12345':
            # Simulate invalid MBID - API returns no results
            logging.debug('Simulating invalid MBID response')
            return None

        # Call original method for valid MBIDs
        return await original_mbid_fetch(apikey, mbartistid, artist_name)

    async def mock_name_fetch(apikey, artist):
        nonlocal name_call_count
        name_call_count += 1
        logging.debug('Name fetch call #%d for artist: %s', name_call_count, artist)

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
        assert name_call_count >= 1, (
            f'Expected at least 1 name call (fallback), got {name_call_count}')

        # Should get a result from name-based fallback with corrected artist name
        assert result is not None, 'Expected result from name-based fallback'

        # If name correction feature is enabled, verify corrected artist name
        if result and result.get('artist'):
            assert result['artist'] == 'Nine Inch Nails', (
                f'Expected corrected artist name, got {result.get("artist")}')
            logging.info('TheAudioDB invalid MBID fallback verified: '
                         'MBID failed, name-based succeeded with correction')
        else:
            logging.info('TheAudioDB invalid MBID fallback verified: '
                         'MBID failed, name-based search attempted')

        # Test without any MusicBrainz ID to ensure same name-based behavior
        mbid_call_count = 0
        name_call_count = 0

        metadata_no_mbid = {
            'album': 'The Downward Spiral',
            'artist': 'nine inch nails',
            'imagecacheartist': 'nineinchnails'
            # No musicbrainzartistid provided
        }

        await plugin.download_async(metadata_no_mbid.copy(), imagecache=None)

        # Should skip MBID and go straight to name-based search
        assert mbid_call_count == 0, (
            f'Expected 0 MBID calls when no MBID provided, got {mbid_call_count}')
        assert name_call_count >= 1, (
            f'Expected at least 1 name call when no MBID, got {name_call_count}')

        logging.info('TheAudioDB MBID fallback behavior test completed successfully')

    finally:
        # Restore original methods
        plugin.artistdatafrommbid_async = original_mbid_fetch
        plugin.artistdatafromname_async = original_name_fetch


@pytest.mark.asyncio
@skip_no_theaudiodb_key
async def test_theaudiodb_api_call_count(bootstrap):
    ''' test that theaudiodb plugin makes only one API call when cache is used '''

    plugin, imagecache = _setup_theaudiodb_plugin(bootstrap)

    # Test with a known artist
    metadata = {'artist': 'Madonna', 'imagecacheartist': 'madonna'}

    await run_api_call_count_test(plugin=plugin,
                                  test_metadata=metadata,
                                  mock_method_name='_fetch_async',
                                  imagecache=imagecache)
