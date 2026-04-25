"""
Unit tests for datacache client layer.

Tests the high-level client interface, HTTP fetching,
rate limiting, and integration with storage.
"""

import tempfile
from pathlib import Path

import aiosqlite
import httpx
import pytest
import pytest_asyncio
import respx

import nowplaying.datacache.client
import nowplaying.utils.sqlite


@pytest_asyncio.fixture
async def temp_client(bootstrap):  # pylint: disable=unused-argument
    """Create temporary client instance"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        client = nowplaying.datacache.client.DataCacheClient(temp_path)
        await client.initialize()
        yield client
        await client.close()


@pytest.mark.asyncio
async def test_client_initialization(temp_client):  # pylint: disable=redefined-outer-name
    """Test client initializes properly"""
    assert temp_client._initialized is True  # pylint: disable=protected-access
    assert temp_client.storage is not None
    assert temp_client._session is not None  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_get_or_fetch_cache_hit(temp_client):  # pylint: disable=redefined-outer-name
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
    data, _metadata = result
    assert data == test_data


@pytest.mark.asyncio
async def test_get_or_fetch_immediate_false_queues_request(temp_client):  # pylint: disable=redefined-outer-name
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
async def test_get_random_image(temp_client):  # pylint: disable=redefined-outer-name
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
    data, _metadata, url = result
    assert data.startswith(b"random_data_")


@pytest.mark.asyncio
async def test_get_cache_keys_for_identifier(temp_client):  # pylint: disable=redefined-outer-name
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
        # Keys are now opaque UUIDs (36 chars: 8-4-4-4-12)
        assert len(cache_key) == 36
        assert cache_key.count("-") == 4


@pytest.mark.asyncio
async def test_queue_url_fetch(temp_client):  # pylint: disable=redefined-outer-name
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
async def test_fetch_and_store_json_response(temp_client):  # pylint: disable=redefined-outer-name
    """Test fetching and storing JSON response"""
    test_data = {"test": "data", "id": 123}

    with respx.mock() as mock_responses:
        mock_responses.get("https://api.example.com/test.json").mock(
            return_value=httpx.Response(
                200, json=test_data, headers={"content-type": "application/json"}
            )
        )

        result = await temp_client._fetch_and_store(  # pylint: disable=protected-access
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
        data, _metadata = result
        assert data == test_data

        # Verify stored in cache
        cached = await temp_client.storage.retrieve_by_url("https://api.example.com/test.json")
        assert cached is not None


@pytest.mark.asyncio
async def test_fetch_and_store_binary_response(temp_client):  # pylint: disable=redefined-outer-name
    """Test fetching and storing binary response"""
    test_data = b"fake_jpeg_data"

    with respx.mock() as mock_responses:
        mock_responses.get("https://example.com/image.jpg").mock(
            return_value=httpx.Response(
                200, content=test_data, headers={"content-type": "image/jpeg"}
            )
        )

        result = await temp_client._fetch_and_store(  # pylint: disable=protected-access
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
        data, _metadata = result
        assert data == test_data


@pytest.mark.asyncio
async def test_fetch_and_store_http_error(temp_client):  # pylint: disable=redefined-outer-name
    """Test handling HTTP error responses"""
    with respx.mock() as mock_responses:
        mock_responses.get("https://example.com/notfound.jpg").mock(
            return_value=httpx.Response(404)
        )

        result = await temp_client._fetch_and_store(  # pylint: disable=protected-access
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
async def test_fetch_and_store_rate_limit_handling(temp_client):  # pylint: disable=redefined-outer-name
    """Test rate limit response handling"""
    with respx.mock() as mock_responses:
        mock_responses.get("https://example.com/ratelimited.jpg").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "1"})
        )

        # Should handle rate limit gracefully (but we won't wait for retry in test)
        result = await temp_client._fetch_and_store(  # pylint: disable=protected-access
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
async def test_fetch_and_store_timeout_handling(temp_client):  # pylint: disable=redefined-outer-name
    """Test timeout handling with retries"""
    with respx.mock() as mock_responses:
        mock_responses.get("https://example.com/timeout.jpg").mock(
            side_effect=httpx.ReadTimeout("timed out")
        )
        result = await temp_client._fetch_and_store(  # pylint: disable=protected-access
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
async def test_process_queue_single_request(temp_client):  # pylint: disable=redefined-outer-name
    """Test processing single queued request"""
    url = "https://example.com/process.jpg"
    expected_data = b"processed_data"

    await temp_client.storage.queue_request(
        provider="test",
        request_key="fetch_url",
        params={
            "url": url,
            "identifier": "process_test",
            "data_type": "thumbnail",
            "timeout": 30.0,
            "retries": 3,
            "ttl_seconds": 3600,
            "metadata": None,
        },
        priority=2,
    )

    with respx.mock() as mock_responses:
        mock_responses.get(url).mock(
            return_value=httpx.Response(
                200, content=expected_data, headers={"content-type": "image/jpeg"}
            )
        )

        stats = await temp_client.process_queue()

    assert stats["processed"] == 1
    assert stats["succeeded"] == 1
    assert stats["failed"] == 0

    # Verify data was actually stored in the cache
    cached = await temp_client.storage.retrieve_by_url(url)
    assert cached is not None
    data, _metadata = cached
    assert data == expected_data


@pytest.mark.asyncio
async def test_process_queue_empty_queue(temp_client):  # pylint: disable=redefined-outer-name
    """Test processing empty queue"""
    stats = await temp_client.process_queue()

    assert stats["processed"] == 0
    assert stats["succeeded"] == 0
    assert stats["failed"] == 0


@pytest.mark.asyncio
async def test_process_queue_fetch_and_store_exception(  # pylint: disable=redefined-outer-name
    temp_client, monkeypatch
):
    """_fetch_and_store raising counts as failed and marks the DB row failed"""

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated fetch failure")

    monkeypatch.setattr(temp_client, "_fetch_and_store", _boom)

    await temp_client.storage.queue_request(
        provider="test",
        request_key="fetch_url",
        params={
            "url": "https://example.com/boom.jpg",
            "identifier": "boom_artist",
            "data_type": "thumbnail",
            "timeout": 30.0,
            "retries": 0,
            "ttl_seconds": 3600,
            "metadata": None,
        },
        priority=2,
    )

    stats = await temp_client.process_queue()

    assert stats["processed"] == 1
    assert stats["succeeded"] == 0
    assert stats["failed"] == 1

    async def _check_status() -> aiosqlite.Row | None:
        async with aiosqlite.connect(str(temp_client.storage.database_path), timeout=30.0) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT status FROM pending_requests WHERE provider = 'test'"
            ) as cursor:
                return await cursor.fetchone()

    row = await nowplaying.utils.sqlite.retry_sqlite_operation_async(_check_status)
    assert row is not None
    assert row["status"] == "failed"


@pytest.mark.asyncio
async def test_process_queue_unknown_request_key(temp_client):  # pylint: disable=redefined-outer-name
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


# ---------------------------------------------------------------------------
# HTTP error behaviour tests
# (Ported concept from imagecache: verify how 4xx/5xx responses are handled.)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_4xx_not_stored_in_cache(temp_client):  # pylint: disable=redefined-outer-name
    """404 returns None and nothing is written to the cache"""
    url = "https://example.com/gone.jpg"

    with respx.mock() as mock_responses:
        mock_responses.get(url).mock(return_value=httpx.Response(404))

        result = await temp_client._fetch_and_store(  # pylint: disable=protected-access
            url=url,
            identifier="gone_artist",
            data_type="thumbnail",
            provider="test",
            timeout=30.0,
            retries=0,
            ttl_seconds=3600,
            metadata=None,
        )

    assert result is None
    # Nothing should have been written
    cached = await temp_client.storage.retrieve_by_url(url)
    assert cached is None


@pytest.mark.asyncio
async def test_5xx_retry_then_success_stores_item(temp_client):  # pylint: disable=redefined-outer-name
    """503 on first attempt then 200 on retry — item ends up in the cache"""
    url = "https://example.com/flaky.jpg"
    good_data = b"finally_succeeded"

    attempts = 0

    def _seq(request):  # pylint: disable=unused-argument
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=good_data, headers={"content-type": "image/jpeg"})

    with respx.mock() as mock_responses:
        mock_responses.get(url).mock(side_effect=_seq)

        result = await temp_client._fetch_and_store(  # pylint: disable=protected-access
            url=url,
            identifier="flaky_artist",
            data_type="thumbnail",
            provider="test",
            timeout=30.0,
            retries=1,
            ttl_seconds=3600,
            metadata=None,
        )

    assert result is not None
    data, _metadata = result
    assert data == good_data
    assert attempts == 2

    cached = await temp_client.storage.retrieve_by_url(url)
    assert cached is not None
    cached_data, _ = cached
    assert cached_data == good_data


@pytest.mark.asyncio
async def test_process_queue_all_failed_drains_queue(temp_client):  # pylint: disable=redefined-outer-name
    """process_queue drains the queue even when every fetch fails"""
    urls = [
        "https://example.com/fail1.jpg",
        "https://example.com/fail2.jpg",
        "https://example.com/fail3.jpg",
    ]
    for url in urls:
        await temp_client.storage.queue_request(
            provider="test",
            request_key="fetch_url",
            params={
                "url": url,
                "identifier": "fail_artist",
                "data_type": "thumbnail",
                "timeout": 30.0,
                "retries": 0,
                "ttl_seconds": 3600,
                "metadata": None,
            },
            priority=2,
        )

    with respx.mock() as mock_responses:
        for url in urls:
            mock_responses.get(url).mock(return_value=httpx.Response(503))

        stats = await temp_client.process_queue()

    assert stats["processed"] == 3
    assert stats["failed"] == 3
    assert stats["succeeded"] == 0

    # Queue should be empty — all items were marked failed
    next_request = await temp_client.storage.get_next_request()
    assert next_request is None


@pytest.mark.asyncio
async def test_rate_limiter_integration(temp_client):  # pylint: disable=redefined-outer-name
    """Test rate limiter is applied during fetch"""
    # Get rate limiter for test provider
    rate_limiter = temp_client.rate_limiters.get_limiter("test")

    # Should have tokens available initially
    assert rate_limiter.available_tokens() > 0

    with respx.mock() as mock_responses:
        mock_responses.get("https://example.com/ratelimit_test.txt").mock(
            return_value=httpx.Response(
                200, text="test data", headers={"content-type": "text/plain"}
            )
        )

        # Fetch should apply rate limiting
        result = await temp_client._fetch_and_store(  # pylint: disable=protected-access
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
