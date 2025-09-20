"""
Unit tests for datacache client layer.

Tests the high-level client interface, HTTP fetching,
rate limiting, and integration with storage.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from aioresponses import aioresponses

import nowplaying.datacache.client


@pytest_asyncio.fixture
async def temp_client(bootstrap):
    """Create temporary client instance"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        client = nowplaying.datacache.client.DataCacheClient(temp_path)
        await client.initialize()
        yield client
        await client.close()


@pytest.mark.asyncio
async def test_client_initialization(temp_client):
    """Test client initializes properly"""
    assert temp_client._initialized is True
    assert temp_client.storage is not None
    assert temp_client._session is not None


@pytest.mark.asyncio
async def test_get_or_fetch_cache_hit(temp_client):
    """Test cache hit returns cached data without HTTP request"""
    # Pre-populate cache
    test_url = "https://example.com/cached.jpg"
    test_data = b"cached_image_data"

    success = await temp_client.storage.store(
        url=test_url,
        identifier="test_artist",
        data_type="thumbnail",
        provider="test",
        data_value=test_data,
        ttl_seconds=3600,
    )
    assert success is True

    # Should return cached data without HTTP request
    result = await temp_client.get_or_fetch(
        url=test_url,
        identifier="test_artist",
        data_type="thumbnail",
        provider="test",
        immediate=True,
    )

    assert result is not None
    data, metadata = result
    assert data == test_data


@pytest.mark.asyncio
async def test_get_or_fetch_immediate_false_queues_request(temp_client):
    """Test immediate=False queues request instead of fetching"""
    test_url = "https://example.com/queue_test.jpg"

    result = await temp_client.get_or_fetch(
        url=test_url,
        identifier="queue_artist",
        data_type="thumbnail",
        provider="test",
        immediate=False,  # Should queue
    )

    # Should return None (queued for later)
    assert result is None

    # Should have queued the request
    request = await temp_client.storage.get_next_request()
    assert request is not None
    assert request["request_key"] == "fetch_url"
    assert request["params"]["url"] == test_url


@pytest.mark.asyncio
async def test_get_default_ttl_by_provider(temp_client):
    """Test TTL defaults vary by provider and data type"""
    # Test provider-specific defaults
    theaudiodb_ttl = temp_client._get_default_ttl("theaudiodb", "thumbnail")
    discogs_ttl = temp_client._get_default_ttl("discogs", "thumbnail")
    fanarttv_ttl = temp_client._get_default_ttl("fanarttv", "thumbnail")

    # FanartTV should have longer TTL (1 month vs 1 week for others)
    assert fanarttv_ttl > theaudiodb_ttl
    assert fanarttv_ttl > discogs_ttl

    # Images should have longer TTL than text data
    image_ttl = temp_client._get_default_ttl("test", "thumbnail")
    bio_ttl = temp_client._get_default_ttl("test", "bio")
    assert image_ttl > bio_ttl


@pytest.mark.asyncio
async def test_get_random_image(temp_client):
    """Test random image retrieval"""
    # Store multiple images
    urls = ["https://example.com/r1.jpg", "https://example.com/r2.jpg"]

    for i, url in enumerate(urls):
        await temp_client.storage.store(
            url=url,
            identifier="random_test_artist",
            data_type="thumbnail",
            provider="test",
            data_value=f"random_data_{i}".encode(),
            ttl_seconds=3600,
        )

    # Get random image
    result = await temp_client.get_random_image(
        identifier="random_test_artist",
        data_type="thumbnail",
    )

    assert result is not None
    data, metadata, url = result
    assert data.startswith(b"random_data_")


@pytest.mark.asyncio
async def test_get_cache_keys_for_identifier(temp_client):
    """Test retrieving cache keys for identifier/type"""
    # Store multiple images
    urls = ["https://example.com/all1.jpg", "https://example.com/all2.jpg"]

    for i, url in enumerate(urls):
        await temp_client.storage.store(
            url=url,
            identifier="all_test_artist",
            data_type="logo",
            provider="test",
            data_value=f"all_data_{i}".encode(),
            ttl_seconds=3600,
        )

    # Get cache keys
    cache_keys = await temp_client.get_cache_keys_for_identifier(
        identifier="all_test_artist",
        data_type="logo",
    )

    assert isinstance(cache_keys, list)
    assert len(cache_keys) == 2

    for cache_key in cache_keys:
        assert isinstance(cache_key, str)
        assert "all_test_artist" in cache_key


@pytest.mark.asyncio
async def test_queue_url_fetch(temp_client):
    """Test URL fetch queuing"""
    success = await temp_client.queue_url_fetch(
        url="https://example.com/queue.jpg",
        identifier="queue_artist",
        data_type="thumbnail",
        provider="test",
        priority=1,  # immediate priority
    )

    assert success is True

    # Verify request was queued
    request = await temp_client.storage.get_next_request()
    assert request is not None
    assert request["priority"] == 1
    assert request["params"]["url"] == "https://example.com/queue.jpg"


@pytest.mark.asyncio
async def test_fetch_and_store_json_response(temp_client):
    """Test fetching and storing JSON response"""
    test_data = {"test": "data", "id": 123}

    with aioresponses() as mock_responses:
        mock_responses.get(
            "https://api.example.com/test.json",
            payload=test_data,
            headers={"content-type": "application/json"},
        )

        result = await temp_client._fetch_and_store(
            url="https://api.example.com/test.json",
            identifier="json_test",
            data_type="api_response",
            provider="test",
            timeout=30.0,
            retries=3,
            ttl_seconds=3600,
            metadata=None,
        )

        assert result is not None
        data, metadata = result
        assert data == test_data

        # Verify stored in cache
        cached = await temp_client.storage.retrieve_by_url("https://api.example.com/test.json")
        assert cached is not None


@pytest.mark.asyncio
async def test_fetch_and_store_binary_response(temp_client):
    """Test fetching and storing binary response"""
    test_data = b"fake_jpeg_data"

    with aioresponses() as mock_responses:
        mock_responses.get(
            "https://example.com/image.jpg", body=test_data, headers={"content-type": "image/jpeg"}
        )

        result = await temp_client._fetch_and_store(
            url="https://example.com/image.jpg",
            identifier="binary_test",
            data_type="image",
            provider="test",
            timeout=30.0,
            retries=3,
            ttl_seconds=3600,
            metadata=None,
        )

        assert result is not None
        data, metadata = result
        assert data == test_data


@pytest.mark.asyncio
async def test_fetch_and_store_http_error(temp_client):
    """Test handling HTTP error responses"""
    with aioresponses() as mock_responses:
        mock_responses.get("https://example.com/notfound.jpg", status=404)

        result = await temp_client._fetch_and_store(
            url="https://example.com/notfound.jpg",
            identifier="error_test",
            data_type="image",
            provider="test",
            timeout=30.0,
            retries=0,  # No retries for faster test
            ttl_seconds=3600,
            metadata=None,
        )

        assert result is None


@pytest.mark.asyncio
async def test_fetch_and_store_rate_limit_handling(temp_client):
    """Test rate limit response handling"""
    with aioresponses() as mock_responses:
        mock_responses.get(
            "https://example.com/ratelimited.jpg", status=429, headers={"Retry-After": "1"}
        )

        # Should handle rate limit gracefully (but we won't wait for retry in test)
        result = await temp_client._fetch_and_store(
            url="https://example.com/ratelimited.jpg",
            identifier="rate_test",
            data_type="image",
            provider="test",
            timeout=30.0,
            retries=0,  # No retries to avoid waiting
            ttl_seconds=3600,
            metadata=None,
        )

        # Should fail due to rate limit with no retries
        assert result is None


@pytest.mark.asyncio
async def test_fetch_and_store_timeout_handling(temp_client):
    """Test timeout handling with retries"""
    with aioresponses() as mock_responses:
        # Mock timeout by not adding any response - aioresponses will timeout
        # We'll use a very short timeout to speed up the test
        result = await temp_client._fetch_and_store(
            url="https://example.com/timeout.jpg",
            identifier="timeout_test",
            data_type="image",
            provider="test",
            timeout=0.001,  # Very short timeout to trigger timeout quickly
            retries=1,  # One retry
            ttl_seconds=3600,
            metadata=None,
        )

        # Should fail after retries
        assert result is None


@pytest.mark.asyncio
async def test_process_queue_single_request(temp_client):
    """Test processing single queued request"""
    # Queue a request
    await temp_client.storage.queue_request(
        provider="test",
        request_key="fetch_url",
        params={
            "url": "https://example.com/process.jpg",
            "identifier": "process_test",
            "data_type": "thumbnail",
            "timeout": 30.0,
            "retries": 3,
            "ttl_seconds": 3600,
            "metadata": None,
        },
        priority=2,
    )

    # Mock successful response
    with patch.object(temp_client, "_fetch_and_store") as mock_fetch:
        mock_fetch.return_value = (b"processed_data", {})

        stats = await temp_client.process_queue()

        assert stats["processed"] == 1
        assert stats["succeeded"] == 1
        assert stats["failed"] == 0

        # Verify fetch was called with correct params
        mock_fetch.assert_called_once()


@pytest.mark.asyncio
async def test_process_queue_empty_queue(temp_client):
    """Test processing empty queue"""
    stats = await temp_client.process_queue()

    assert stats["processed"] == 0
    assert stats["succeeded"] == 0
    assert stats["failed"] == 0


@pytest.mark.asyncio
async def test_process_queue_unknown_request_key(temp_client):
    """Test processing request with unknown request key"""
    # Queue request with unknown key
    await temp_client.storage.queue_request(
        provider="test",
        request_key="unknown_operation",
        params={"test": "data"},
        priority=1,
    )

    stats = await temp_client.process_queue()

    assert stats["processed"] == 1
    assert stats["succeeded"] == 0
    assert stats["failed"] == 1


def test_get_client_singleton():
    """Test client singleton behavior"""
    # Should return same instance
    client1 = nowplaying.datacache.client.get_client()
    client2 = nowplaying.datacache.client.get_client()

    assert client1 is client2


@pytest.mark.asyncio
async def test_rate_limiter_integration(temp_client):
    """Test rate limiter is applied during fetch"""
    # Get rate limiter for test provider
    rate_limiter = temp_client.rate_limiters.get_limiter("test")

    # Should have tokens available initially
    assert rate_limiter.available_tokens() > 0

    # Mock response with aioresponses
    with aioresponses() as mock_responses:
        mock_responses.get(
            "https://example.com/ratelimit_test.txt",
            body="test data",
            headers={"content-type": "text/plain"},
        )

        # Fetch should apply rate limiting
        result = await temp_client._fetch_and_store(
            url="https://example.com/ratelimit_test.txt",
            identifier="rate_test",
            data_type="text",
            provider="test",
            timeout=30.0,
            retries=3,
            ttl_seconds=3600,
            metadata=None,
        )

        assert result is not None
        # Rate limiter should have consumed a token
        assert rate_limiter.available_tokens() < rate_limiter.capacity
