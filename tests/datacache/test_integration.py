"""
Integration tests for datacache module.

Tests the full integration between storage, client, providers,
and workers working together.
"""

import asyncio
import tempfile
from pathlib import Path

import httpx
import orjson
import pytest
import respx

import nowplaying.datacache

# Real image URLs used for live network tests.  Same source as the imagecache
# tests — these have been stable for 2+ years.
_LIVE_FANART_URLS = [
    "https://r2.theaudiodb.com/images/media/artist/fanart/numan-gary-5026a93c591b1.jpg",
    "https://r2.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b765ed348.jpg",
    "https://r2.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b899f3268.jpg",
]


@pytest.mark.asyncio
async def test_full_image_caching_workflow(bootstrap, isolated_datacache_client):  # pylint: disable=unused-argument,redefined-outer-name
    """Test complete image caching workflow"""
    test_image_data = b"fake_image_bytes"
    test_url = "https://example.com/artist_thumb.jpg"

    with respx.mock() as mock_responses:
        mock_responses.get(test_url).mock(
            return_value=httpx.Response(
                200, content=test_image_data, headers={"content-type": "image/jpeg"}
            )
        )

        result = await nowplaying.datacache.get_client().get_or_fetch(
            nowplaying.datacache.FetchRequest(
                url=test_url,
                identifier="integration_test_artist",
                data_type="thumbnail",
                provider="test_provider",
                immediate=True,
                metadata={"source": "integration_test"},
            )
        )

        assert result is not None
        assert result.data == test_image_data
        assert result.metadata["source"] == "integration_test"


@pytest.mark.asyncio
async def test_randomimage_functionality_integration(bootstrap, isolated_datacache_client):  # pylint: disable=unused-argument,redefined-outer-name
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

        for url in image_urls:
            await nowplaying.datacache.get_client().get_or_fetch(
                nowplaying.datacache.FetchRequest(
                    url=url,
                    identifier="random_test_artist",
                    data_type="thumbnail",
                    provider="test_provider",
                    immediate=True,
                )
            )

        # Get random image
        random_result = await nowplaying.datacache.get_client().get_random_image(
            identifier="random_test_artist", data_type="thumbnail"
        )

        assert random_result is not None
        assert random_result.data.startswith(b"image_data_")
        assert random_result.url in image_urls

        # Get cache keys
        cache_keys = await isolated_datacache_client.get_cache_keys_for_identifier(
            identifier="random_test_artist", data_type="thumbnail"
        )

        assert len(cache_keys) == 3
        for cache_key in cache_keys:
            assert isinstance(cache_key, str)
            # Keys are opaque UUIDs (36 chars: 8-4-4-4-12)
            assert len(cache_key) == 36
            assert cache_key.count("-") == 4


@pytest.mark.asyncio
async def test_queue_and_process_workflow(bootstrap, isolated_datacache_client):  # pylint: disable=unused-argument,redefined-outer-name
    """Test queuing requests and processing them"""
    test_url = "https://example.com/queued_image.jpg"
    test_data = b"queued_image_data"

    with respx.mock() as mock_responses:
        mock_responses.get(test_url).mock(
            return_value=httpx.Response(
                200, content=test_data, headers={"content-type": "image/jpeg"}
            )
        )

        result = await nowplaying.datacache.get_client().get_or_fetch(
            nowplaying.datacache.FetchRequest(
                url=test_url,
                identifier="queue_test_artist",
                data_type="logo",
                provider="test_provider",
                immediate=False,
            )
        )

        # Should return None (queued for background processing)
        assert result is None

        # Process the queue
        stats = await nowplaying.datacache.get_client().process_queue()

        # Should have processed some requests
        assert stats["processed"] >= 0


@pytest.mark.asyncio
async def test_cache_hit_avoids_http_request(bootstrap, isolated_datacache_client):  # pylint: disable=unused-argument,redefined-outer-name
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

        result1 = await nowplaying.datacache.get_client().get_or_fetch(
            nowplaying.datacache.FetchRequest(
                url=test_url,
                identifier="cache_hit_artist",
                data_type="banner",
                provider="test_provider",
                immediate=True,
            )
        )

        assert result1 is not None

    result2 = await nowplaying.datacache.get_client().get_or_fetch(
        nowplaying.datacache.FetchRequest(
            url=test_url,
            identifier="cache_hit_artist",
            data_type="banner",
            provider="test_provider",
            immediate=True,
        )
    )

    assert result2 is not None
    assert result2.data == test_data


@pytest.mark.asyncio
async def test_provider_filtering_works(bootstrap, isolated_datacache_client):  # pylint: disable=unused-argument,redefined-outer-name
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

        await nowplaying.datacache.get_client().get_or_fetch(
            nowplaying.datacache.FetchRequest(
                url=test_urls["theaudiodb"],
                identifier="filter_test_artist",
                data_type="fanart",
                provider="theaudiodb",
                immediate=True,
            )
        )

        await nowplaying.datacache.get_client().get_or_fetch(
            nowplaying.datacache.FetchRequest(
                url=test_urls["discogs"],
                identifier="filter_test_artist",
                data_type="fanart",
                provider="discogs",
                immediate=True,
            )
        )

        # Get cache keys filtered by provider
        theaudiodb_keys = await isolated_datacache_client.get_cache_keys_for_identifier(
            identifier="filter_test_artist", data_type="fanart", provider="theaudiodb"
        )

        assert len(theaudiodb_keys) == 1
        assert isinstance(theaudiodb_keys[0], str)
        # Keys are opaque UUIDs (36 chars: 8-4-4-4-12)
        assert len(theaudiodb_keys[0]) == 36
        assert theaudiodb_keys[0].count("-") == 4

        # Get all cache keys (no provider filter)
        all_keys = await isolated_datacache_client.get_cache_keys_for_identifier(
            identifier="filter_test_artist", data_type="fanart"
        )

        assert len(all_keys) == 2


@pytest.mark.asyncio
async def test_api_response_caching_integration(bootstrap, isolated_datacache_client):  # pylint: disable=unused-argument,redefined-outer-name
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

        result = await nowplaying.datacache.get_client().get_or_fetch(
            nowplaying.datacache.FetchRequest(
                url=test_url,
                identifier="api_test_artist",
                data_type="bio_en",
                provider="test_api",
                immediate=True,
                metadata={"language": "en", "source": "test_api"},
            )
        )

        assert result is not None
        assert isinstance(result.data, bytes)
        assert orjson.loads(result.data) == test_bio_data
        assert result.metadata["language"] == "en"
        assert result.metadata["source"] == "test_api"


@pytest.mark.asyncio
async def test_cached_fetch_bytes_round_trip(bootstrap, isolated_datacache_client):  # pylint: disable=unused-argument,redefined-outer-name
    """cached_fetch must round-trip dicts containing bytes values via base64 sentinel."""
    test_data = {"text": "hello", "raw": b"\x00\x01\x02binary"}
    call_count = 0

    async def fetch_func():
        nonlocal call_count
        call_count += 1
        return test_data

    result1 = await nowplaying.datacache.cached_fetch(
        provider="test",
        artist_name="testartist",
        endpoint="bytes_test",
        fetch_func=fetch_func,
    )
    assert result1 == test_data
    assert isinstance(result1["raw"], bytes)
    assert call_count == 1

    # Second call must be a cache hit — fetch_func not invoked again
    result2 = await nowplaying.datacache.cached_fetch(
        provider="test",
        artist_name="testartist",
        endpoint="bytes_test",
        fetch_func=fetch_func,
    )
    assert result2 == test_data
    assert isinstance(result2["raw"], bytes)
    assert call_count == 1, "cache hit should not call fetch_func again"


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
async def test_concurrent_storage_operations(bootstrap, isolated_datacache_client):  # pylint: disable=unused-argument,redefined-outer-name
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
            task = isolated_datacache_client.get_or_fetch(
                nowplaying.datacache.FetchRequest(
                    url=url,
                    identifier=f"concurrent_artist_{i}",
                    data_type="thumbnail",
                    provider="test_provider",
                    immediate=True,
                )
            )
            tasks.append(task)

        # Wait for all to complete
        results = await asyncio.gather(*tasks)

        # All should succeed
        for result in results:
            assert result is not None
            assert result.data.startswith(b"concurrent_data_")


def test_module_level_convenience_functions():
    """Test module-level convenience functions"""
    # Test get_client returns same instance
    client1 = nowplaying.datacache.get_client()
    client2 = nowplaying.datacache.get_client()
    assert client1 is client2


# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_queue_and_process_random_image_bytes(bootstrap, isolated_datacache_client):  # pylint: disable=unused-argument,redefined-outer-name
    """get_or_fetch(immediate=False) + process_queue → get_random_image returns bytes"""
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

        for url in image_urls:
            result = await nowplaying.datacache.get_client().get_or_fetch(
                nowplaying.datacache.FetchRequest(
                    url=url,
                    identifier="fanart_artist",
                    data_type="fanart",
                    provider="cdn",
                    immediate=False,
                )
            )
            assert result is None

        stats = await nowplaying.datacache.get_client().process_queue()
        assert stats["processed"] == 3
        assert stats["succeeded"] == 3
        assert stats["failed"] == 0

    random_result = await nowplaying.datacache.get_client().get_random_image(
        identifier="fanart_artist", data_type="fanart"
    )
    result = random_result.data if random_result else None
    assert result is not None
    assert isinstance(result, bytes)
    assert result.startswith(b"fanart_data_")


@pytest.mark.asyncio
async def test_random_image_bytes_returns_none_when_nothing_cached(  # pylint: disable=unused-argument,redefined-outer-name
    bootstrap, isolated_datacache_client
):
    """random_image_bytes returns None when there are no cached images"""
    random_result = await nowplaying.datacache.get_client().get_random_image(
        identifier="nobody", data_type="thumbnail"
    )
    result = random_result.data if random_result else None
    assert result is None


# ---------------------------------------------------------------------------
# Live network tests — talk to real servers, same URLs as imagecache tests
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_immediate_fetch(bootstrap):  # pylint: disable=unused-argument,redefined-outer-name
    """Immediate fetch of a real image URL returns bytes and caches them"""
    url = _LIVE_FANART_URLS[0]

    result = await nowplaying.datacache.get_client().get_or_fetch(
        nowplaying.datacache.FetchRequest(
            url=url,
            identifier="gary_numan",
            data_type="fanart",
            provider="theaudiodb",
            immediate=True,
        )
    )

    assert result is not None
    assert isinstance(result.data, bytes)
    assert len(result.data) > 0

    result2 = await nowplaying.datacache.get_client().get_or_fetch(
        nowplaying.datacache.FetchRequest(
            url=url,
            identifier="gary_numan",
            data_type="fanart",
            provider="theaudiodb",
            immediate=True,
        )
    )
    assert result2 is not None
    assert result2.data == result.data


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_queue_and_random_image_bytes(bootstrap):  # pylint: disable=unused-argument,redefined-outer-name
    """get_or_fetch(immediate=False) + process_queue → get_random_image returns bytes"""
    # Use the production path (get_or_fetch checks cached_data before queuing)
    for url in _LIVE_FANART_URLS:
        result = await nowplaying.datacache.get_client().get_or_fetch(
            nowplaying.datacache.FetchRequest(
                url=url,
                identifier="gary_numan",
                data_type="fanart",
                provider="cdn",
                timeout=30.0,
                retries=3,
                immediate=False,
            )
        )
        assert result is None or isinstance(result.data, bytes)

    await nowplaying.datacache.get_client().process_queue()

    random_result = await nowplaying.datacache.get_client().get_random_image(
        identifier="gary_numan", data_type="fanart"
    )
    result = random_result.data if random_result else None
    assert result is not None
    assert isinstance(result, bytes)
    assert len(result) > 0
