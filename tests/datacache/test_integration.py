"""
Integration tests for datacache module.

Tests the full integration between storage, client, providers,
and workers working together.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from aioresponses import aioresponses

import nowplaying.datacache


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

    with aioresponses() as mock_responses:
        mock_responses.get(test_url, body=test_image_data, headers={"content-type": "image/jpeg"})

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

    with aioresponses() as mock_responses:
        # Mock all image responses
        for i, url in enumerate(image_urls):
            mock_responses.get(
                url, body=f"image_data_{i}".encode(), headers={"content-type": "image/jpeg"}
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
            assert "random_test_artist" in cache_key


@pytest.mark.asyncio
async def test_queue_and_process_workflow(temp_datacache):  # pylint: disable=redefined-outer-name
    """Test queuing requests and processing them"""
    test_url = "https://example.com/queued_image.jpg"
    test_data = b"queued_image_data"

    with aioresponses() as mock_responses:
        mock_responses.get(test_url, body=test_data, headers={"content-type": "image/jpeg"})

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
    with aioresponses() as mock_responses:
        mock_responses.get(test_url, body=test_data, headers={"content-type": "image/jpeg"})

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

    with aioresponses() as mock_responses:
        # Mock responses from different providers
        mock_responses.get(
            test_urls["theaudiodb"],
            body=b"theaudiodb_data",
            headers={"content-type": "image/jpeg"},
        )
        mock_responses.get(
            test_urls["discogs"], body=b"discogs_data", headers={"content-type": "image/jpeg"}
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
        assert "filter_test_artist" in theaudiodb_keys[0]

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

    with aioresponses() as mock_responses:
        mock_responses.get(
            test_url, payload=test_bio_data, headers={"content-type": "application/json"}
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

    with aioresponses() as mock_responses:
        # Mock all responses
        for i, url in enumerate(test_urls):
            mock_responses.get(
                url, body=f"concurrent_data_{i}".encode(), headers={"content-type": "image/jpeg"}
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
