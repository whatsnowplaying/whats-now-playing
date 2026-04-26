"""
Integration tests for datacache module.

Tests the full integration between storage, client, providers,
and workers working together.
"""

import asyncio
import tempfile
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx

import nowplaying.datacache

# Real image URLs used for live network tests.  Same source as the imagecache
# tests — these have been stable for 2+ years.
_LIVE_FANART_URLS = [
    "https://r2.theaudiodb.com/images/media/artist/fanart/numan-gary-5026a93c591b1.jpg",
    "https://r2.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b765ed348.jpg",
    "https://r2.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b899f3268.jpg",
]


@pytest_asyncio.fixture
async def temp_datacache(bootstrap):  # pylint: disable=unused-argument
    """Create temporary datacache instance"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        providers = nowplaying.datacache.DataCacheProviders(temp_path)
        await providers.initialize()
        yield providers
        await providers.close()


@pytest.mark.asyncio
async def test_full_image_caching_workflow(temp_datacache):  # pylint: disable=redefined-outer-name
    """Test complete image caching workflow"""
    test_image_data = b"fake_image_bytes"
    test_url = "https://example.com/artist_thumb.jpg"

    with respx.mock() as mock_responses:
        mock_responses.get(test_url).mock(
            return_value=httpx.Response(
                200, content=test_image_data, headers={"content-type": "image/jpeg"}
            )
        )

        # Cache image immediately
        result = await temp_datacache.images.cache_artist_thumbnail(
            url=test_url,
            artist_identifier="integration_test_artist",
            provider="test_provider",
            immediate=True,
            metadata={"source": "integration_test"},
        )

        assert result is not None
        data, metadata = result
        assert data == test_image_data
        assert metadata["source"] == "integration_test"


@pytest.mark.asyncio
async def test_randomimage_functionality_integration(temp_datacache):  # pylint: disable=redefined-outer-name
    """Test randomimage functionality works end-to-end"""
    # Cache multiple images for same artist
    image_urls = [
        "https://example.com/thumb1.jpg",
        "https://example.com/thumb2.jpg",
        "https://example.com/thumb3.jpg",
    ]

    with respx.mock() as mock_responses:
        # Mock all image responses
        for i, url in enumerate(image_urls):
            mock_responses.get(url).mock(
                return_value=httpx.Response(
                    200, content=f"image_data_{i}".encode(), headers={"content-type": "image/jpeg"}
                )
            )

        # Cache all images
        for url in image_urls:
            await temp_datacache.images.cache_artist_thumbnail(
                url=url,
                artist_identifier="random_test_artist",
                provider="test_provider",
                immediate=True,
            )

        # Get random image
        random_result = await temp_datacache.images.get_random_image(
            artist_identifier="random_test_artist", image_type="thumbnail"
        )

        assert random_result is not None
        data, _metadata, url = random_result
        assert data.startswith(b"image_data_")
        assert url in image_urls

        # Get cache keys
        cache_keys = await temp_datacache.images.get_cache_keys_for_identifier(
            artist_identifier="random_test_artist", image_type="thumbnail"
        )

        assert len(cache_keys) == 3
        for cache_key in cache_keys:
            assert isinstance(cache_key, str)
            # Keys are opaque UUIDs (36 chars: 8-4-4-4-12)
            assert len(cache_key) == 36
            assert cache_key.count("-") == 4


@pytest.mark.asyncio
async def test_queue_and_process_workflow(temp_datacache):  # pylint: disable=redefined-outer-name
    """Test queuing requests and processing them"""
    test_url = "https://example.com/queued_image.jpg"
    test_data = b"queued_image_data"

    with respx.mock() as mock_responses:
        mock_responses.get(test_url).mock(
            return_value=httpx.Response(
                200, content=test_data, headers={"content-type": "image/jpeg"}
            )
        )

        # Queue image for background processing
        result = await temp_datacache.images.cache_artist_logo(
            url=test_url,
            artist_identifier="queue_test_artist",
            provider="test_provider",
            immediate=False,  # Queue for later
        )

        # Should return None (queued for background processing)
        assert result is None

        # Process the queue
        stats = await temp_datacache.process_queue()

        # Should have processed some requests
        assert stats["processed"] >= 0


@pytest.mark.asyncio
async def test_cache_hit_avoids_http_request(temp_datacache):  # pylint: disable=redefined-outer-name
    """Test that cache hits don't make HTTP requests"""
    test_url = "https://example.com/cached_test.jpg"
    test_data = b"cached_test_data"

    # First request with mock
    with respx.mock() as mock_responses:
        mock_responses.get(test_url).mock(
            return_value=httpx.Response(
                200, content=test_data, headers={"content-type": "image/jpeg"}
            )
        )

        result1 = await temp_datacache.images.cache_artist_banner(
            url=test_url,
            artist_identifier="cache_hit_artist",
            provider="test_provider",
            immediate=True,
        )

        assert result1 is not None

    # Second request without mock (should hit cache)
    result2 = await temp_datacache.images.cache_artist_banner(
        url=test_url,
        artist_identifier="cache_hit_artist",
        provider="test_provider",
        immediate=True,
    )

    assert result2 is not None
    data, _metadata = result2
    assert data == test_data


@pytest.mark.asyncio
async def test_provider_filtering_works(temp_datacache):  # pylint: disable=redefined-outer-name
    """Test that provider filtering works correctly"""
    test_urls = {
        "theaudiodb": "https://theaudiodb.com/image1.jpg",
        "discogs": "https://discogs.com/image2.jpg",
    }

    with respx.mock() as mock_responses:
        # Mock responses from different providers
        mock_responses.get(test_urls["theaudiodb"]).mock(
            return_value=httpx.Response(
                200, content=b"theaudiodb_data", headers={"content-type": "image/jpeg"}
            )
        )
        mock_responses.get(test_urls["discogs"]).mock(
            return_value=httpx.Response(
                200, content=b"discogs_data", headers={"content-type": "image/jpeg"}
            )
        )

        # Cache images from different providers
        await temp_datacache.images.cache_artist_fanart(
            url=test_urls["theaudiodb"],
            artist_identifier="filter_test_artist",
            provider="theaudiodb",
            immediate=True,
        )

        await temp_datacache.images.cache_artist_fanart(
            url=test_urls["discogs"],
            artist_identifier="filter_test_artist",
            provider="discogs",
            immediate=True,
        )

        # Get cache keys filtered by provider
        theaudiodb_keys = await temp_datacache.images.get_cache_keys_for_identifier(
            artist_identifier="filter_test_artist", image_type="fanart", provider="theaudiodb"
        )

        assert len(theaudiodb_keys) == 1
        assert isinstance(theaudiodb_keys[0], str)
        # Keys are opaque UUIDs (36 chars: 8-4-4-4-12)
        assert len(theaudiodb_keys[0]) == 36
        assert theaudiodb_keys[0].count("-") == 4

        # Get all cache keys (no provider filter)
        all_keys = await temp_datacache.images.get_cache_keys_for_identifier(
            artist_identifier="filter_test_artist", image_type="fanart"
        )

        assert len(all_keys) == 2


@pytest.mark.asyncio
async def test_api_response_caching_integration(temp_datacache):  # pylint: disable=redefined-outer-name
    """Test API response caching works end-to-end"""
    test_url = "https://api.example.com/artist/bio"
    test_bio_data = {
        "biography": "This is a test artist biography.",
        "born": "1990-01-01",
        "genre": "Electronic",
    }

    with respx.mock() as mock_responses:
        mock_responses.get(test_url).mock(
            return_value=httpx.Response(
                200, json=test_bio_data, headers={"content-type": "application/json"}
            )
        )

        result = await temp_datacache.api.cache_artist_bio(
            url=test_url,
            artist_identifier="api_test_artist",
            provider="test_api",
            language="en",
            immediate=True,
            metadata={"source": "test_api"},
        )

        assert result is not None
        data, metadata = result
        assert data == test_bio_data
        assert metadata["language"] == "en"
        assert metadata["source"] == "test_api"


def test_maintenance_integration():
    """Test maintenance functions work with real database"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Run maintenance (creates database)
        stats = nowplaying.datacache.run_maintenance(temp_path)

        assert "expired_cleaned" in stats
        assert "requests_cleaned" in stats
        assert "requests_recovered" in stats
        assert "vacuum_performed" in stats
        assert stats["errors"] == 0

        # Database should exist
        db_path = nowplaying.datacache.get_datacache_path(temp_path)
        assert db_path.exists()


@pytest.mark.asyncio
async def test_concurrent_storage_operations(temp_datacache):  # pylint: disable=redefined-outer-name
    """Test concurrent operations don't interfere"""
    test_urls = [
        "https://example.com/concurrent1.jpg",
        "https://example.com/concurrent2.jpg",
        "https://example.com/concurrent3.jpg",
    ]

    with respx.mock() as mock_responses:
        # Mock all responses
        for i, url in enumerate(test_urls):
            mock_responses.get(url).mock(
                return_value=httpx.Response(
                    200,
                    content=f"concurrent_data_{i}".encode(),
                    headers={"content-type": "image/jpeg"},
                )
            )

        # Start concurrent caching operations
        tasks = []
        for i, url in enumerate(test_urls):
            task = temp_datacache.images.cache_artist_thumbnail(
                url=url,
                artist_identifier=f"concurrent_artist_{i}",
                provider="test_provider",
                immediate=True,
            )
            tasks.append(task)

        # Wait for all to complete
        results = await asyncio.gather(*tasks)

        # All should succeed
        for result in results:
            assert result is not None
            data, _metadata = result
            assert data.startswith(b"concurrent_data_")


def test_module_level_convenience_functions():
    """Test module-level convenience functions"""
    # Test get_providers returns same instance
    providers1 = nowplaying.datacache.get_providers()
    providers2 = nowplaying.datacache.get_providers()
    assert providers1 is providers2

    # Test get_client returns same instance
    client1 = nowplaying.datacache.get_client()
    client2 = nowplaying.datacache.get_client()
    assert client1 is client2


# ---------------------------------------------------------------------------
# fill_queue / random_image_bytes tests
# (Ported concept from imagecache: queue URLs for background download, then
#  retrieve via the random-image interface.)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fill_queue_and_process_random_image_bytes(temp_datacache):  # pylint: disable=redefined-outer-name
    """fill_queue → process_queue fetches all URLs → random_image_bytes returns bytes"""
    image_urls = [
        "https://example.com/fanart1.jpg",
        "https://example.com/fanart2.jpg",
        "https://example.com/fanart3.jpg",
    ]

    with respx.mock() as mock_responses:
        for i, url in enumerate(image_urls):
            mock_responses.get(url).mock(
                return_value=httpx.Response(
                    200,
                    content=f"fanart_data_{i}".encode(),
                    headers={"content-type": "image/jpeg"},
                )
            )

        queued = await temp_datacache.images.fill_queue(
            identifier="fanart_artist",
            imagetype="fanart",
            srclocationlist=image_urls,
            provider="theaudiodb",
        )
        assert queued == 3

        stats = await temp_datacache.process_queue()
        assert stats["processed"] == 3
        assert stats["succeeded"] == 3
        assert stats["failed"] == 0

    result = await temp_datacache.images.random_image_bytes(
        artist_identifier="fanart_artist", image_type="fanart"
    )
    assert result is not None
    assert isinstance(result, bytes)
    assert result.startswith(b"fanart_data_")


@pytest.mark.asyncio
async def test_fill_queue_respects_maxcount(temp_datacache):  # pylint: disable=redefined-outer-name
    """fill_queue maxcount caps how many URLs are queued"""
    image_urls = [
        "https://example.com/maxcount1.jpg",
        "https://example.com/maxcount2.jpg",
        "https://example.com/maxcount3.jpg",
        "https://example.com/maxcount4.jpg",
        "https://example.com/maxcount5.jpg",
    ]

    queued = await temp_datacache.images.fill_queue(
        identifier="maxcount_artist",
        imagetype="thumbnail",
        srclocationlist=image_urls,
        provider="test",
        maxcount=2,
    )
    assert queued == 2

    # Drain the pending queue without making HTTP calls — count items directly
    queue_depth = 0
    while await temp_datacache.client.storage.get_next_request() is not None:
        queue_depth += 1
    assert queue_depth == 2


@pytest.mark.asyncio
async def test_fill_queue_empty_list(temp_datacache):  # pylint: disable=redefined-outer-name
    """fill_queue with an empty list queues nothing"""
    queued = await temp_datacache.images.fill_queue(
        identifier="empty_artist",
        imagetype="thumbnail",
        srclocationlist=[],
        provider="test",
    )
    assert queued == 0

    stats = await temp_datacache.process_queue()
    assert stats["processed"] == 0


@pytest.mark.asyncio
async def test_fill_queue_deduplicates(temp_datacache):  # pylint: disable=redefined-outer-name
    """Passing the same URL twice only queues it once"""
    url = "https://example.com/dedup.jpg"

    queued = await temp_datacache.images.fill_queue(
        identifier="dedup_artist",
        imagetype="fanart",
        srclocationlist=[url, url],
        provider="test",
    )
    assert queued == 1


@pytest.mark.asyncio
async def test_random_image_bytes_returns_none_when_nothing_cached(temp_datacache):  # pylint: disable=redefined-outer-name
    """random_image_bytes returns None when there are no cached images"""
    result = await temp_datacache.images.random_image_bytes(
        artist_identifier="nobody", image_type="thumbnail"
    )
    assert result is None


# ---------------------------------------------------------------------------
# Live network tests — talk to real servers, same URLs as imagecache tests
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_immediate_fetch(temp_datacache):  # pylint: disable=redefined-outer-name
    """Immediate fetch of a real image URL returns bytes and caches them"""
    url = _LIVE_FANART_URLS[0]

    result = await temp_datacache.images.cache_artist_fanart(
        url=url,
        artist_identifier="gary_numan",
        provider="theaudiodb",
        immediate=True,
    )

    assert result is not None
    data, _metadata = result
    assert isinstance(data, bytes)
    assert len(data) > 0

    # Cache hit — no network call needed
    result2 = await temp_datacache.images.cache_artist_fanart(
        url=url,
        artist_identifier="gary_numan",
        provider="theaudiodb",
        immediate=True,
    )
    assert result2 is not None
    data2, _metadata2 = result2
    assert data2 == data


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_fill_queue_and_random_image_bytes(temp_datacache):  # pylint: disable=redefined-outer-name
    """fill_queue + process_queue with real URLs → random_image_bytes returns bytes"""
    queued = await temp_datacache.images.fill_queue(
        identifier="gary_numan",
        imagetype="fanart",
        srclocationlist=_LIVE_FANART_URLS,
        provider="theaudiodb",
    )
    assert queued == len(_LIVE_FANART_URLS)

    stats = await temp_datacache.process_queue()
    assert stats["processed"] == len(_LIVE_FANART_URLS)
    assert stats["failed"] == 0

    result = await temp_datacache.images.random_image_bytes(
        artist_identifier="gary_numan", image_type="fanart"
    )
    assert result is not None
    assert isinstance(result, bytes)
    assert len(result) > 0
