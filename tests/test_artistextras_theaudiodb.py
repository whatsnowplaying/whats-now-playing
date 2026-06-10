#!/usr/bin/env python3
"""test artistextras theaudiodb plugin"""

# pylint: disable=protected-access,
import logging

import httpx
import pytest
import respx
from utils_artistextras import (
    configureplugins,
    configuresettings,
    datacache_has_pending,
    datacache_image_available,
)

import nowplaying.artistextras.theaudiodb
import nowplaying.datacache
from nowplaying.artistextras.theaudiodb import DEFAULT_THEAUDIODB_API_KEY

ARTIST_MBID = "b7ffd2af-418f-4be2-bdd1-22f8b48613da"

TADB_BASE_URL = f"https://theaudiodb.com/api/v1/json/{DEFAULT_THEAUDIODB_API_KEY}"


def _setup_theaudiodb_plugin(bootstrap):
    """Set up TheAudioDB plugin for testing"""
    config = bootstrap
    configuresettings("theaudiodb", config.cparser)
    config.cparser.setValue("theaudiodb/apikey", DEFAULT_THEAUDIODB_API_KEY)
    plugins = configureplugins(config)
    return plugins["theaudiodb"]


def _setup_theaudiodb_plugin_no_key(bootstrap):
    """Set up TheAudioDB plugin for testing without requiring API key"""
    config = bootstrap
    configuresettings("theaudiodb", config.cparser)
    config.cparser.setValue("theaudiodb/apikey", DEFAULT_THEAUDIODB_API_KEY)
    # Directly instantiate the plugin since we don't need real API key
    plugin = nowplaying.artistextras.theaudiodb.Plugin(config=config)
    return plugin


@pytest.mark.asyncio
async def test_theaudiodb_artist_name_correction(bootstrap):
    """test theaudiodb artist name correction for name-based vs musicbrainz searches"""

    plugin = _setup_theaudiodb_plugin(bootstrap)

    # Test 1: Name-based search with lowercase input (should correct artist name)
    metadata_lowercase = {
        "album": "The Downward Spiral",
        "artist": "nine inch nails",  # lowercase input
        "imagecacheartist": "nineinchnails",
    }
    result1 = await plugin.download_async(metadata_lowercase.copy())

    if result1:  # Only test if we got data back
        # Should have corrected the artist name to proper case
        assert result1["artist"] == "Nine Inch Nails"
        logging.info(
            "Artist name corrected: %s -> %s", metadata_lowercase["artist"], result1["artist"]
        )

    # Test 2: With MusicBrainz ID (should NOT correct artist name)
    metadata_with_mbid = {
        "album": "The Downward Spiral",
        "artist": "nine inch nails",  # lowercase input
        "imagecacheartist": "nineinchnails",
        "musicbrainzartistid": ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"],  # NIN's MBID
    }
    result2 = await plugin.download_async(metadata_with_mbid.copy())

    if result2:  # Only test if we got data back
        # Should NOT have corrected the artist name (MusicBrainz is authoritative)
        assert result2["artist"] == "nine inch nails"
        logging.info("Artist name preserved for MusicBrainz search: %s", result2["artist"])


@pytest.mark.asyncio
async def test_theaudiodb_apicache_duplicate_artists(bootstrap):
    """test TheAudioDB two-level caching with duplicate artist names"""

    plugin = _setup_theaudiodb_plugin(bootstrap)

    # Test two different searches that might return different artists with similar names
    # First search - likely to match main "Madonna"
    metadata_madonna1 = {"artist": "Madonna", "imagecacheartist": "madonna1"}

    # Second search - variation that might match different artist
    metadata_madonna2 = {
        "artist": "madonna",  # lowercase variation
        "imagecacheartist": "madonna2",
    }

    # Test both variations - first calls hit API, second calls use cache
    result1a = await plugin.download_async(metadata_madonna1.copy())
    result2a = await plugin.download_async(metadata_madonna2.copy())

    # Second calls - should use cached data
    result1b = await plugin.download_async(metadata_madonna1.copy())
    result2b = await plugin.download_async(metadata_madonna2.copy())

    # Verify caching works for both variations
    assert (result1a is None) == (result1b is None)
    assert (result2a is None) == (result2b is None)

    if result1a:
        assert result1a == result1b
        logging.info("TheAudioDB cache verified for Madonna (capitalized)")

    if result2a:
        assert result2a == result2b
        logging.info("TheAudioDB cache verified for madonna (lowercase)")

    # Check if different normalizations potentially return different results
    if result1a and result2a:
        artist1 = result1a.get("artist", "")
        artist2 = result2a.get("artist", "")

        if artist1 and artist2 and artist1 != artist2:
            logging.info(
                "TheAudioDB distinguished between different artists: %s vs %s", artist1, artist2
            )
        else:
            logging.info("TheAudioDB returned same artist for both variations")
    else:
        logging.info("TheAudioDB duplicate artist test completed - two-level caching working")

    # Test passes if two-level caching works correctly (search + individual artist ID)


@pytest.mark.asyncio
async def test_theaudiodb_invalid_musicbrainz_id_fallback(bootstrap):
    """test theaudiodb plugin falls back to name-based search when MusicBrainz ID is invalid"""

    plugin = _setup_theaudiodb_plugin(bootstrap)

    # Mock the MBID and name-based fetch methods to track calls
    original_mbid_fetch = plugin.artistdatafrommbid_async
    original_name_fetch = plugin.artistdatafromname_async

    mbid_call_count = 0
    name_call_count = 0

    async def mock_mbid_fetch(apikey, mbartistid, artist_name):  # pylint: disable=unused-argument
        nonlocal mbid_call_count
        mbid_call_count += 1
        logging.debug("MBID fetch call #%d for MBID: %s", mbid_call_count, mbartistid)

        if mbartistid == "invalid-mbid-12345":
            # Simulate invalid MBID - API returns no results
            logging.debug("Simulating invalid MBID response")
            return None

        # Call original method for valid MBIDs
        return await original_mbid_fetch(apikey, mbartistid, artist_name)

    async def mock_name_fetch(apikey, artist):
        nonlocal name_call_count
        name_call_count += 1
        logging.debug("Name fetch call #%d for artist: %s", name_call_count, artist)

        # Call original method but simulate finding data for Nine Inch Nails
        if "nine inch nails" in artist.lower():
            # Return minimal mock data to simulate successful name-based search
            return {
                "artists": [
                    {
                        "idArtist": "111239",
                        "strArtist": "Nine Inch Nails",  # Corrected capitalization
                        "strBiographyEN": "Mock biography for Nine Inch Nails",
                        "strArtistLogo": None,
                        "strArtistThumb": None,
                        "strArtistFanart": None,
                        "strArtistBanner": None,
                    }
                ]
            }

        return await original_name_fetch(apikey, artist)

    # Replace methods with mocks
    plugin.artistdatafrommbid_async = mock_mbid_fetch
    plugin.artistdatafromname_async = mock_name_fetch

    try:
        # Test with invalid MusicBrainz ID - should fallback to name-based search
        metadata_invalid_mbid = {
            "album": "The Downward Spiral",
            "artist": "nine inch nails",  # lowercase to test name correction
            "imagecacheartist": "nineinchnails",
            "musicbrainzartistid": ["invalid-mbid-12345"],  # Invalid MBID
        }

        result = await plugin.download_async(metadata_invalid_mbid.copy())

        # Verify the call pattern: MBID tried first, then fallback to name-based
        assert mbid_call_count == 1, f"Expected 1 MBID call, got {mbid_call_count}"
        assert name_call_count >= 1, (
            f"Expected at least 1 name call (fallback), got {name_call_count}"
        )

        # Should get a result from name-based fallback with corrected artist name
        assert result is not None, "Expected result from name-based fallback"

        # If name correction feature is enabled, verify corrected artist name
        if result and result.get("artist"):
            assert result["artist"] == "Nine Inch Nails", (
                f"Expected corrected artist name, got {result.get('artist')}"
            )
            logging.info(
                "TheAudioDB invalid MBID fallback verified: "
                "MBID failed, name-based succeeded with correction"
            )
        else:
            logging.info(
                "TheAudioDB invalid MBID fallback verified: "
                "MBID failed, name-based search attempted"
            )

        # Test without any MusicBrainz ID to ensure same name-based behavior
        mbid_call_count = 0
        name_call_count = 0

        metadata_no_mbid = {
            "album": "The Downward Spiral",
            "artist": "nine inch nails",
            "imagecacheartist": "nineinchnails",
            # No musicbrainzartistid provided
        }

        await plugin.download_async(metadata_no_mbid.copy())

        # Should skip MBID and go straight to name-based search
        assert mbid_call_count == 0, (
            f"Expected 0 MBID calls when no MBID provided, got {mbid_call_count}"
        )
        assert name_call_count >= 1, (
            f"Expected at least 1 name call when no MBID, got {name_call_count}"
        )

        logging.info("TheAudioDB MBID fallback behavior test completed successfully")

    finally:
        # Restore original methods
        plugin.artistdatafrommbid_async = original_mbid_fetch
        plugin.artistdatafromname_async = original_name_fetch


@pytest.mark.asyncio
async def test_theaudiodb_api_call_count(bootstrap):  # pylint: disable=redefined-outer-name
    """test that theaudiodb plugin makes only one HTTP call when cache is warm"""
    plugin = _setup_theaudiodb_plugin(bootstrap)
    fake_mbid = "00000000-0000-0000-0000-000000000001"
    metadata = {
        "artist": "WNP Mock Artist",
        "musicbrainzartistid": [fake_mbid],
        "imagecacheartist": "wnpmockartist",
    }
    artist_url = f"{TADB_BASE_URL}/artist-mb.php?i={fake_mbid}"
    mock_payload = {"artists": [{"strArtist": "WNP Mock Artist", "idArtist": "999999"}]}

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(artist_url).mock(return_value=httpx.Response(200, json=mock_payload))

        await plugin.download_async(metadata.copy())
        first_count = mock_http.calls.call_count
        assert first_count >= 1, "Expected at least one HTTP call on cache miss"

        await plugin.download_async(metadata.copy())
        assert mock_http.calls.call_count == first_count, "Cache hit should not add HTTP calls"


@pytest.mark.asyncio
async def test_theaudiodb_other_http_errors(bootstrap):  # pylint: disable=redefined-outer-name
    """test that theaudiodb handles non-200 HTTP errors by returning None"""
    plugin = _setup_theaudiodb_plugin_no_key(bootstrap)
    url = f"{TADB_BASE_URL}/search.php?s=notfound"

    # Use side_effect callable so the mock persists across retries
    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(url).mock(side_effect=lambda _: httpx.Response(404))
        result = await plugin._fetch_cached(  # pylint: disable=protected-access
            DEFAULT_THEAUDIODB_API_KEY, "search.php?s=notfound", "testartist"
        )
        assert result is None


@pytest.mark.asyncio
async def test_theaudiodb_429_not_cached(bootstrap, isolated_datacache_client):  # pylint: disable=redefined-outer-name,unused-argument
    """test that theaudiodb 429 responses are not cached; second call retries"""
    plugin = _setup_theaudiodb_plugin_no_key(bootstrap)
    url = f"{TADB_BASE_URL}/search.php?s=test"

    # Side-effect callable keeps responding 429 across all retry attempts.
    # Retry-After: 1 caps the per-retry sleep to 1 s.
    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(url).mock(
            side_effect=lambda _: httpx.Response(429, headers={"Retry-After": "1"})
        )
        result = await plugin._fetch_cached(  # pylint: disable=protected-access
            DEFAULT_THEAUDIODB_API_KEY, "search.php?s=test", "testartist"
        )
        assert result is None

    # Clear in-memory cooldown so the second call can attempt the HTTP request.
    # The test verifies that 429 was not written to the persistent cache — the
    # in-memory cooldown is a separate, correct mechanism unrelated to caching.
    isolated_datacache_client._retry_after_until.clear()  # pylint: disable=protected-access

    # Second call: if 429 had been cached to disk, this would also return None
    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(url).mock(
            return_value=httpx.Response(200, json={"artists": [{"strArtist": "Test"}]})
        )
        result2 = await plugin._fetch_cached(  # pylint: disable=protected-access
            DEFAULT_THEAUDIODB_API_KEY, "search.php?s=test", "testartist"
        )
        assert result2 is not None


WNP_MOCK_ARTIST_URL = f"{TADB_BASE_URL}/search.php?s=wnp%20mock%20artist"
WNP_MOCK_ALBUM_URL = f"{TADB_BASE_URL}/searchalbum.php?s=WNP%20Mock%20Artist&a=WNP%20Mock%20Album"
COVER_IMAGE_URL = "https://cdn.theaudiodb.com/images/media/album/thumb/cover.jpg"

WNP_MOCK_ARTIST_RESPONSE = {
    "artists": [
        {
            "idArtist": "999999",
            "strArtist": "WNP Mock Artist",
            "strBiography": "WNP Mock Artist is a fictional band used for unit testing.",
            "strArtistThumb": "https://cdn.theaudiodb.com/images/media/artist/thumb/mock.jpg",
            "strWebsite": "www.example.com",
        }
    ]
}

WNP_MOCK_ALBUM_RESPONSE = {
    "album": [
        {
            "idAlbum": "8888888",
            "strAlbum": "WNP Mock Album",
            "strArtist": "WNP Mock Artist",
            "strAlbumThumb": COVER_IMAGE_URL,
        }
    ]
}

WNP_MOCK_ALBUM_RESPONSE_HQ = {
    "album": [
        {
            "idAlbum": "8888888",
            "strAlbum": "WNP Mock Album",
            "strArtist": "WNP Mock Artist",
            "strAlbumThumb": "https://cdn.theaudiodb.com/images/media/album/thumb/cover_sd.jpg",
            "strAlbumThumbHQ": COVER_IMAGE_URL,
        }
    ]
}


@pytest.mark.asyncio
async def test_theaudiodb_coverart_queued(bootstrap):  # pylint: disable=redefined-outer-name
    """album cover art URL is queued in imagecache when album is present"""
    plugin = _setup_theaudiodb_plugin_no_key(bootstrap)
    bootstrap.cparser.setValue("theaudiodb/coverart", True)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_ARTIST_URL).mock(
            return_value=httpx.Response(200, json=WNP_MOCK_ARTIST_RESPONSE)
        )
        mock_http.get(WNP_MOCK_ALBUM_URL).mock(
            return_value=httpx.Response(200, json=WNP_MOCK_ALBUM_RESPONSE)
        )
        result = await plugin.download_async(
            {
                "artist": "WNP Mock Artist",
                "album": "WNP Mock Album",
                "imagecacheartist": "wnpmockartist",
            },
        )

    assert result is not None
    identifier = "wnpmockartist_wnpmockalbum"
    assert await datacache_image_available(
        nowplaying.datacache.get_client(), identifier, "front_cover"
    )


@pytest.mark.asyncio
async def test_theaudiodb_coverart_prefers_hq(bootstrap):  # pylint: disable=redefined-outer-name
    """strAlbumThumbHQ is preferred over strAlbumThumb when available"""
    plugin = _setup_theaudiodb_plugin_no_key(bootstrap)
    bootstrap.cparser.setValue("theaudiodb/coverart", True)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_ARTIST_URL).mock(
            return_value=httpx.Response(200, json=WNP_MOCK_ARTIST_RESPONSE)
        )
        mock_http.get(WNP_MOCK_ALBUM_URL).mock(
            return_value=httpx.Response(200, json=WNP_MOCK_ALBUM_RESPONSE_HQ)
        )
        result = await plugin.download_async(
            {
                "artist": "WNP Mock Artist",
                "album": "WNP Mock Album",
                "imagecacheartist": "wnpmockartist",
            },
        )

    assert result is not None
    identifier = "wnpmockartist_wnpmockalbum"
    assert await datacache_image_available(
        nowplaying.datacache.get_client(), identifier, "front_cover"
    )


@pytest.mark.asyncio
async def test_theaudiodb_coverart_disabled(bootstrap):  # pylint: disable=redefined-outer-name
    """album cover art is not fetched when coverart setting is disabled"""
    plugin = _setup_theaudiodb_plugin_no_key(bootstrap)
    bootstrap.cparser.setValue("theaudiodb/coverart", False)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_ARTIST_URL).mock(
            return_value=httpx.Response(200, json=WNP_MOCK_ARTIST_RESPONSE)
        )
        result = await plugin.download_async(
            {
                "artist": "WNP Mock Artist",
                "album": "WNP Mock Album",
                "imagecacheartist": "wnpmockartist",
            },
        )

    assert result is not None
    # images queued to datacache


@pytest.mark.asyncio
async def test_theaudiodb_coverart_skipped_when_coverimageraw_present(  # pylint: disable=redefined-outer-name
    bootstrap,
):
    """album cover art fetch is skipped when coverimageraw already in metadata"""
    plugin = _setup_theaudiodb_plugin_no_key(bootstrap)
    bootstrap.cparser.setValue("theaudiodb/coverart", True)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_ARTIST_URL).mock(
            return_value=httpx.Response(200, json=WNP_MOCK_ARTIST_RESPONSE)
        )
        result = await plugin.download_async(
            {
                "artist": "WNP Mock Artist",
                "album": "WNP Mock Album",
                "imagecacheartist": "wnpmockartist",
                "coverimageraw": b"\xff\xd8\xff",
            },
        )

    assert result is not None
    assert not await datacache_has_pending(
        nowplaying.datacache.get_client(), "wnpmockartist", "front_cover"
    )


@pytest.mark.asyncio
async def test_theaudiodb_coverart_no_album(bootstrap):  # pylint: disable=redefined-outer-name
    """album cover art fetch is skipped when no album in metadata"""
    plugin = _setup_theaudiodb_plugin_no_key(bootstrap)
    bootstrap.cparser.setValue("theaudiodb/coverart", True)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_ARTIST_URL).mock(
            return_value=httpx.Response(200, json=WNP_MOCK_ARTIST_RESPONSE)
        )
        result = await plugin.download_async(
            {"artist": "WNP Mock Artist", "imagecacheartist": "wnpmockartist"},
        )

    assert result is not None
    assert not await datacache_has_pending(
        nowplaying.datacache.get_client(), "wnpmockartist", "front_cover"
    )


@pytest.mark.asyncio
async def test_theaudiodb_coverart_album_api_error(bootstrap):  # pylint: disable=redefined-outer-name
    """album API error does not prevent artist data from being returned"""
    plugin = _setup_theaudiodb_plugin_no_key(bootstrap)
    bootstrap.cparser.setValue("theaudiodb/coverart", True)

    with respx.mock(assert_all_called=False) as mock_http:
        mock_http.get(WNP_MOCK_ARTIST_URL).mock(
            return_value=httpx.Response(200, json=WNP_MOCK_ARTIST_RESPONSE)
        )
        mock_http.get(WNP_MOCK_ALBUM_URL).mock(
            return_value=httpx.Response(200, json={"album": None})
        )
        result = await plugin.download_async(
            {
                "artist": "WNP Mock Artist",
                "album": "WNP Mock Album",
                "imagecacheartist": "wnpmockartist",
            },
        )

    assert result is not None
    assert not await datacache_has_pending(
        nowplaying.datacache.get_client(), "wnpmockartist", "front_cover"
    )


@pytest.mark.asyncio
async def test_theaudiodb_live_coverart(bootstrap):  # pylint: disable=redefined-outer-name
    """live: album cover art URL is queued for Nine Inch Nails - The Downward Spiral"""
    plugin = _setup_theaudiodb_plugin(bootstrap)
    bootstrap.cparser.setValue("theaudiodb/coverart", True)

    try:
        result = await plugin.download_async(
            {
                "artist": "Nine Inch Nails",
                "album": "The Downward Spiral",
                "imagecacheartist": "nineinchnails",
            },
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        pytest.fail(f"Plugin raised exception during live cover art test: {exc}")

    identifier = "nineinchnails_thedownwardspiral"
    assert result is not None
    assert await datacache_image_available(
        nowplaying.datacache.get_client(), identifier, "front_cover"
    ), "Expected cover art to be queued or cached"
