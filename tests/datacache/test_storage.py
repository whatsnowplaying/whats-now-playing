"""
Unit tests for datacache storage layer.

Tests the core URL-based storage functionality, database schema,
randomimage support, and multiprocess queue operations.
"""

import asyncio
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest
import pytest_asyncio

import nowplaying.datacache.storage


def test_get_datacache_path_default():
    """Test default datacache path"""
    path = nowplaying.datacache.storage.get_datacache_path()
    assert path.name == "datacache.sqlite"
    assert "datacache" in str(path)


def test_get_datacache_path_custom():
    """Test custom datacache path"""
    with tempfile.TemporaryDirectory() as temp_dir:
        custom_path = Path(temp_dir)
        path = nowplaying.datacache.storage.get_datacache_path(custom_path)
        assert path.parent == custom_path
        assert path.name == "datacache.sqlite"


def test_run_datacache_maintenance():
    """Test sync maintenance operations"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Run maintenance (creates database if needed)
        stats = nowplaying.datacache.storage.run_datacache_maintenance(temp_path)

        assert "expired_cleaned" in stats
        assert "requests_cleaned" in stats
        assert "vacuum_performed" in stats
        assert stats["errors"] == 0

        # Database should exist
        db_path = temp_path / "datacache.sqlite"
        assert db_path.exists()

        # Should have proper schema
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='cached_data'"
            )
            assert cursor.fetchone() is not None


def test_maintenance_cleanup_expired():
    """Test that maintenance cleans up expired entries"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        db_path = temp_path / "datacache.sqlite"

        # Create database with expired entry
        with sqlite3.connect(str(db_path)) as conn:
            # Create schema
            conn.execute("""
                CREATE TABLE cached_data (
                    url TEXT PRIMARY KEY,
                    cache_key TEXT NOT NULL,
                    identifier TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    data_value BLOB,
                    metadata TEXT,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    access_count INTEGER DEFAULT 1,
                    last_accessed INTEGER NOT NULL,
                    data_size INTEGER NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE pending_requests (
                    request_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    params TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    last_attempt INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending'
                )
            """)

            now = int(time.time())

            # Add expired entry
            conn.execute(
                """
                INSERT INTO cached_data
                (url, cache_key, identifier, data_type, provider, data_value, metadata,
                 created_at, expires_at, last_accessed, data_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "https://example.com/expired.jpg",
                    "test_thumbnail_test_expired",
                    "test",
                    "thumbnail",
                    "test",
                    b"expired_data",
                    "{}",
                    now - 3600,
                    now - 1800,  # Expired 30 minutes ago
                    now - 3600,
                    len(b"expired_data"),
                ),
            )

            # Add valid entry
            conn.execute(
                """
                INSERT INTO cached_data
                (url, cache_key, identifier, data_type, provider, data_value, metadata,
                 created_at, expires_at, last_accessed, data_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "https://example.com/valid.jpg",
                    "test_thumbnail_test_valid",
                    "test",
                    "thumbnail",
                    "test",
                    b"valid_data",
                    "{}",
                    now,
                    now + 3600,  # Expires in 1 hour
                    now,
                    len(b"valid_data"),
                ),
            )

            conn.commit()

        # Run maintenance
        stats = nowplaying.datacache.storage.run_datacache_maintenance(temp_path)

        # Should have cleaned up 1 expired entry
        assert stats["expired_cleaned"] == 1

        # Verify cleanup
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM cached_data")
            count = cursor.fetchone()[0]
            assert count == 1  # Only valid entry remains

            cursor = conn.execute("SELECT url FROM cached_data")
            url = cursor.fetchone()[0]
            assert url == "https://example.com/valid.jpg"


@pytest_asyncio.fixture
async def temp_storage(bootstrap):
    """Create temporary storage instance"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        storage = nowplaying.datacache.storage.DataStorage(temp_path)
        await storage.initialize()
        yield storage
        await storage.close()


@pytest.mark.asyncio
async def test_storage_initialization(temp_storage):
    """Test database initialization creates proper schema"""
    # Check that database file exists
    assert temp_storage.database_path.exists()

    # Check schema using sync connection for testing
    with sqlite3.connect(str(temp_storage.database_path)) as conn:
        # Check cached_data table
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cached_data'"
        )
        assert cursor.fetchone() is not None

        # Check pending_requests table
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pending_requests'"
        )
        assert cursor.fetchone() is not None

        # Check key indexes exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_identifier_type'"
        )
        assert cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_store_and_retrieve_by_url(temp_storage):
    """Test basic URL-based storage and retrieval"""
    # Store test data
    url = "https://example.com/test.jpg"
    test_data = b"fake_image_data"
    metadata = {"width": 100, "height": 200}

    success = await temp_storage.store(
        url=url,
        identifier="test_artist",
        data_type="thumbnail",
        provider="test",
        data_value=test_data,
        ttl_seconds=3600,
        metadata=metadata,
    )
    assert success is True

    # Retrieve by URL
    result = await temp_storage.retrieve_by_url(url)
    assert result is not None

    data, retrieved_metadata = result
    assert data == test_data
    assert retrieved_metadata["width"] == 100
    assert retrieved_metadata["height"] == 200


@pytest.mark.asyncio
async def test_store_duplicate_url(temp_storage):
    """Test that duplicate URLs are handled correctly (replaced)"""
    url = "https://example.com/duplicate.jpg"

    # Store first version
    await temp_storage.store(
        url=url,
        identifier="artist1",
        data_type="thumbnail",
        provider="test",
        data_value=b"data_v1",
        ttl_seconds=3600,
    )

    # Store second version with same URL
    await temp_storage.store(
        url=url,
        identifier="artist2",
        data_type="logo",
        provider="test",
        data_value=b"data_v2",
        ttl_seconds=3600,
    )

    # Should retrieve the second version
    result = await temp_storage.retrieve_by_url(url)
    assert result is not None
    data, metadata = result
    assert data == b"data_v2"


@pytest.mark.asyncio
async def test_retrieve_by_identifier_multiple_images(temp_storage):
    """Test identifier-based retrieval (randomimage functionality)"""
    # Store multiple images for the same artist
    urls = [
        "https://example.com/thumb1.jpg",
        "https://example.com/thumb2.jpg",
        "https://example.com/thumb3.jpg",
    ]

    for i, url in enumerate(urls):
        await temp_storage.store(
            url=url,
            identifier="test_artist",
            data_type="thumbnail",
            provider="test",
            data_value=f"image_data_{i}".encode(),
            ttl_seconds=3600,
        )

    # Get all thumbnails
    results = await temp_storage.retrieve_by_identifier(
        identifier="test_artist", data_type="thumbnail", random=False
    )
    assert isinstance(results, list)
    assert len(results) == 3

    # Each result should be (data, metadata, url) tuple
    for result in results:
        assert isinstance(result, tuple)
        assert len(result) == 3
        data, metadata, url = result
        assert data.startswith(b"image_data_")
        assert url in urls


@pytest.mark.asyncio
async def test_retrieve_by_identifier_random(temp_storage):
    """Test random image retrieval"""
    # Store multiple images
    urls = ["https://example.com/r1.jpg", "https://example.com/r2.jpg"]

    for i, url in enumerate(urls):
        await temp_storage.store(
            url=url,
            identifier="random_artist",
            data_type="thumbnail",
            provider="test",
            data_value=f"random_data_{i}".encode(),
            ttl_seconds=3600,
        )

    # Get random thumbnail
    random_result = await temp_storage.retrieve_by_identifier(
        identifier="random_artist", data_type="thumbnail", random=True
    )
    assert isinstance(random_result, tuple)
    data, metadata, url = random_result
    assert data.startswith(b"random_data_")
    assert url in urls


@pytest.mark.asyncio
async def test_retrieve_by_identifier_with_provider_filter(temp_storage):
    """Test identifier retrieval with provider filtering"""
    # Store images from different providers
    await temp_storage.store(
        url="https://theaudiodb.com/image1.jpg",
        identifier="filter_artist",
        data_type="thumbnail",
        provider="theaudiodb",
        data_value=b"audiodb_image",
        ttl_seconds=3600,
    )

    await temp_storage.store(
        url="https://discogs.com/image2.jpg",
        identifier="filter_artist",
        data_type="thumbnail",
        provider="discogs",
        data_value=b"discogs_image",
        ttl_seconds=3600,
    )

    # Filter by provider
    results = await temp_storage.retrieve_by_identifier(
        identifier="filter_artist", data_type="thumbnail", provider="theaudiodb", random=False
    )
    assert len(results) == 1
    data, metadata, url = results[0]
    assert data == b"audiodb_image"
    assert url == "https://theaudiodb.com/image1.jpg"


@pytest.mark.asyncio
async def test_ttl_expiration(temp_storage):
    """Test that expired items are not retrieved"""
    url = "https://example.com/expired.jpg"

    # Store with very short TTL
    await temp_storage.store(
        url=url,
        identifier="expire_artist",
        data_type="thumbnail",
        provider="test",
        data_value=b"expired_data",
        ttl_seconds=1,  # 1 second
    )

    # Should be retrievable immediately
    result = await temp_storage.retrieve_by_url(url)
    assert result is not None

    # Wait for expiration
    await asyncio.sleep(1.1)

    # Should no longer be retrievable
    result = await temp_storage.retrieve_by_url(url)
    assert result is None


@pytest.mark.asyncio
async def test_data_serialization_json(temp_storage):
    """Test JSON data serialization"""
    url = "https://example.com/json"
    test_data = {"key": "value", "list": [1, 2, 3]}

    success = await temp_storage.store(
        url=url,
        identifier="json_test",
        data_type="api_data",
        provider="test",
        data_value=test_data,
        ttl_seconds=3600,
    )
    assert success is True

    result = await temp_storage.retrieve_by_url(url)
    assert result is not None
    data, metadata = result
    assert data == test_data


@pytest.mark.asyncio
async def test_data_serialization_binary(temp_storage):
    """Test binary data serialization"""
    url = "https://example.com/binary"
    test_data = b"binary content with \x00 null bytes"

    success = await temp_storage.store(
        url=url,
        identifier="binary_test",
        data_type="image",
        provider="test",
        data_value=test_data,
        ttl_seconds=3600,
    )
    assert success is True

    result = await temp_storage.retrieve_by_url(url)
    assert result is not None
    data, metadata = result
    assert data == test_data


@pytest.mark.asyncio
async def test_queue_request(temp_storage):
    """Test request queuing functionality"""
    # Queue a request
    success = await temp_storage.queue_request(
        provider="test_provider",
        request_key="fetch_url",
        params={"url": "https://example.com/test.jpg", "timeout": 30},
        priority=1,  # immediate
    )
    assert success is True

    # Queue duplicate request (should return False)
    success = await temp_storage.queue_request(
        provider="test_provider",
        request_key="fetch_url",
        params={"url": "https://example.com/test.jpg", "timeout": 30},
        priority=1,
    )
    assert success is False


@pytest.mark.asyncio
async def test_get_next_request_priority_order(temp_storage):
    """Test request retrieval respects priority order"""
    # Queue batch request first
    await temp_storage.queue_request(
        provider="test",
        request_key="fetch_url",
        params={"url": "https://example.com/batch.jpg"},
        priority=2,  # batch
    )

    # Queue immediate request second
    await temp_storage.queue_request(
        provider="test",
        request_key="fetch_url",
        params={"url": "https://example.com/immediate.jpg"},
        priority=1,  # immediate
    )

    # Should get immediate priority first
    request = await temp_storage.get_next_request()
    assert request is not None
    assert request["priority"] == 1
    assert "immediate.jpg" in request["params"]["url"]

    # Should get batch priority next
    request = await temp_storage.get_next_request()
    assert request is not None
    assert request["priority"] == 2
    assert "batch.jpg" in request["params"]["url"]

    # No more requests
    request = await temp_storage.get_next_request()
    assert request is None


@pytest.mark.asyncio
async def test_complete_request(temp_storage):
    """Test request completion"""
    # Queue and get a request
    await temp_storage.queue_request(
        provider="test",
        request_key="test_request",
        params={"test": "data"},
        priority=1,
    )

    request = await temp_storage.get_next_request()
    assert request is not None
    request_id = request["request_id"]

    # Complete successfully
    success = await temp_storage.complete_request(request_id, success=True)
    assert success is True

    # Should no longer be available
    next_request = await temp_storage.get_next_request()
    assert next_request is None


@pytest.mark.asyncio
async def test_cleanup_expired(temp_storage):
    """Test cleanup of expired entries"""
    # Store expired item
    await temp_storage.store(
        url="https://example.com/expired.jpg",
        identifier="cleanup_test",
        data_type="test",
        provider="test",
        data_value=b"expired",
        ttl_seconds=-1,  # Already expired
    )

    # Store valid item
    await temp_storage.store(
        url="https://example.com/valid.jpg",
        identifier="cleanup_test",
        data_type="test",
        provider="test",
        data_value=b"valid",
        ttl_seconds=3600,
    )

    # Cleanup
    cleaned_count = await temp_storage.cleanup_expired()
    assert cleaned_count == 1

    # Expired item should be gone
    result = await temp_storage.retrieve_by_url("https://example.com/expired.jpg")
    assert result is None

    # Valid item should remain
    result = await temp_storage.retrieve_by_url("https://example.com/valid.jpg")
    assert result is not None


@pytest.mark.asyncio
async def test_concurrent_access():
    """Test concurrent access to storage (multiprocess simulation)"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create multiple storage instances (simulates multiple processes)
        storages = []
        for i in range(3):
            storage = nowplaying.datacache.storage.DataStorage(temp_path)
            await storage.initialize()
            storages.append(storage)

        try:
            # Concurrent operations
            tasks = []
            for i, storage in enumerate(storages):
                # Each "process" stores different data
                task = storage.store(
                    url=f"https://example.com/concurrent_{i}.jpg",
                    identifier=f"artist_{i}",
                    data_type="thumbnail",
                    provider="test",
                    data_value=f"data_{i}".encode(),
                    ttl_seconds=3600,
                )
                tasks.append(task)

            # Wait for all operations
            results = await asyncio.gather(*tasks)
            assert all(results)  # All should succeed

            # Verify all data is stored correctly
            for i, storage in enumerate(storages):
                result = await storage.retrieve_by_url(f"https://example.com/concurrent_{i}.jpg")
                assert result is not None
                data, metadata = result
                assert data == f"data_{i}".encode()

        finally:
            # Cleanup
            for storage in storages:
                await storage.close()
