"""
Unit tests for datacache storage layer.

Tests the core URL-based storage functionality, database schema,
and randomimage support.
"""

import asyncio
import logging
import tempfile
import time
from pathlib import Path

import orjson
import pytest
import pytest_asyncio

import nowplaying.datacache.storage
import nowplaying.datacache.utils
import nowplaying.exceptions
import nowplaying.utils.sqlite


def test_get_datacache_path_default():
    """Test default datacache path"""
    path = nowplaying.datacache.utils.get_datacache_path()
    assert path.name == "datacache.sqlite"
    assert "datacache" in str(path)


def test_get_datacache_path_custom():
    """Test custom datacache path"""
    with tempfile.TemporaryDirectory() as temp_dir:
        custom_path = Path(temp_dir)
        path = nowplaying.datacache.utils.get_datacache_path(custom_path)
        assert path.parent == custom_path
        assert path.name == "datacache.sqlite"


def test_run_datacache_maintenance():
    """Test sync maintenance operations"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Run maintenance (creates database if needed)
        stats = nowplaying.datacache.utils.run_datacache_maintenance(temp_path)

        assert "expired_cleaned" in stats
        assert "requests_cleaned" in stats
        assert "requests_recovered" in stats
        assert "vacuum_performed" in stats
        assert stats["errors"] == 0

        # Database should exist
        db_path = temp_path / "datacache.sqlite"
        assert db_path.exists()

        # Should have proper schema
        with nowplaying.utils.sqlite.sqlite_connection(str(db_path)) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='cached_data'"
            )
            assert cursor.fetchone() is not None


def test_maintenance_cleanup_expired():
    """Test that maintenance cleans up expired entries"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        db_path = temp_path / "datacache.sqlite"

        # Let run_datacache_maintenance create the schema, then insert test rows directly
        nowplaying.datacache.utils.run_datacache_maintenance(temp_path)

        now = int(time.time())
        # Write blob files so cleanup_expired can unlink them
        blobs_dir = temp_path / "blobs"
        blobs_dir.mkdir()
        expired_blob = blobs_dir / "expired.bin"
        valid_blob = blobs_dir / "valid.bin"
        expired_blob.write_bytes(b"expired_data")
        valid_blob.write_bytes(b"valid_data")

        with nowplaying.utils.sqlite.sqlite_connection(str(db_path)) as conn:
            conn.execute(
                """
                INSERT INTO cached_data
                (url, cachekey, identifier, data_type, provider, file_path, metadata,
                 created_at, expires_at, last_accessed, data_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "https://example.com/expired.jpg",
                    "uuid-expired",
                    "test",
                    "thumbnail",
                    "test",
                    "blobs/expired.bin",
                    "{}",
                    now - 3600,
                    now - 1800,  # Expired 30 minutes ago
                    now - 3600,
                    len(b"expired_data"),
                ),
            )
            conn.execute(
                """
                INSERT INTO cached_data
                (url, cachekey, identifier, data_type, provider, file_path, metadata,
                 created_at, expires_at, last_accessed, data_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "https://example.com/valid.jpg",
                    "uuid-valid",
                    "test",
                    "thumbnail",
                    "test",
                    "blobs/valid.bin",
                    "{}",
                    now,
                    now + 3600,
                    now,
                    len(b"valid_data"),
                ),
            )

        # Run maintenance again to trigger cleanup
        stats = nowplaying.datacache.utils.run_datacache_maintenance(temp_path)

        assert stats["expired_cleaned"] == 1

        with nowplaying.utils.sqlite.sqlite_connection(str(db_path)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM cached_data").fetchone()[0]
            assert count == 1
            url = conn.execute("SELECT url FROM cached_data").fetchone()[0]
            assert url == "https://example.com/valid.jpg"


@pytest_asyncio.fixture
async def temp_storage(bootstrap):  # pylint: disable=unused-argument
    """Create temporary storage instance"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        storage = nowplaying.datacache.storage.DataStorage(temp_path)
        await storage.initialize()
        yield storage
        await storage.close()


@pytest.mark.asyncio
async def test_storage_initialization(temp_storage):  # pylint: disable=redefined-outer-name
    """Test database initialization creates proper schema"""
    # Check that database file exists
    assert temp_storage.database_path.exists()

    # Check schema using sync connection for testing
    with nowplaying.utils.sqlite.sqlite_connection(str(temp_storage.database_path)) as conn:
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
async def test_store_and_retrieve_by_url(temp_storage):  # pylint: disable=redefined-outer-name
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
    # store() returns the stored entry, carrying the cachekey and detected mime_type
    assert success is not None and success.cachekey

    # Retrieve by URL
    result = await temp_storage.retrieve_by_url(url)
    assert result is not None

    assert result.data == test_data
    assert result.status_code == 200
    assert result.metadata["width"] == 100
    assert result.metadata["height"] == 200


@pytest.mark.asyncio
async def test_store_duplicate_url(temp_storage):  # pylint: disable=redefined-outer-name
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
    assert result.data == b"data_v2"


@pytest.mark.asyncio
async def test_retrieve_by_identifier_multiple_images(temp_storage):  # pylint: disable=redefined-outer-name
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

    # Get all thumbnails — random=False returns CachedEntry list without loading blobs
    results = await temp_storage.retrieve_by_identifier(
        identifier="test_artist", data_type="thumbnail", random=False
    )
    assert isinstance(results, list)
    assert len(results) == 3

    for entry in results:
        assert entry.url in urls
        assert entry.status_code == 200
        # Fetch the blob separately to verify data integrity
        cached = await temp_storage.retrieve_by_url(entry.url)
        assert cached is not None
        assert cached.status_code == 200
        assert cached.data.startswith(b"image_data_")


@pytest.mark.asyncio
async def test_retrieve_by_identifier_filters_non_200(temp_storage):  # pylint: disable=redefined-outer-name
    """retrieve_by_identifier never returns entries with status_code != 200."""
    await temp_storage.store(
        url="https://example.com/ok.jpg",
        identifier="filter_artist",
        data_type="thumbnail",
        provider="test",
        data_value=b"ok_image",
        ttl_seconds=3600,
        status_code=200,
    )
    await temp_storage.store(
        url="https://example.com/not_found.jpg",
        identifier="filter_artist",
        data_type="thumbnail",
        provider="test",
        data_value=b"",
        ttl_seconds=3600,
        status_code=404,
    )

    results = await temp_storage.retrieve_by_identifier(
        identifier="filter_artist", data_type="thumbnail", random=False
    )
    assert all(e.status_code == 200 for e in results)
    assert all(e.url != "https://example.com/not_found.jpg" for e in results)

    for _ in range(10):
        entry = await temp_storage.retrieve_by_identifier(
            identifier="filter_artist", data_type="thumbnail", random=True
        )
        if entry is not None:
            assert entry.status_code == 200
            assert entry.url != "https://example.com/not_found.jpg"


@pytest.mark.asyncio
async def test_retrieve_by_identifier_random(temp_storage):  # pylint: disable=redefined-outer-name
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
    assert random_result is not None
    assert random_result.data.startswith(b"random_data_")
    assert random_result.url in urls


@pytest.mark.asyncio
async def test_retrieve_by_identifier_with_provider_filter(temp_storage):  # pylint: disable=redefined-outer-name
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

    # Filter by provider — random=False returns CachedEntry list without loading blobs
    results = await temp_storage.retrieve_by_identifier(
        identifier="filter_artist", data_type="thumbnail", provider="theaudiodb", random=False
    )
    assert len(results) == 1
    assert results[0].url == "https://theaudiodb.com/image1.jpg"
    cached = await temp_storage.retrieve_by_url(results[0].url)
    assert cached is not None
    assert cached.data == b"audiodb_image"


@pytest.mark.asyncio
async def test_ttl_expiration(temp_storage):  # pylint: disable=redefined-outer-name
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
async def test_data_serialization_json(temp_storage):  # pylint: disable=redefined-outer-name
    """Test JSON stored as bytes; callers decode"""
    url = "https://example.com/json"
    test_data = {"key": "value", "list": [1, 2, 3]}

    success = await temp_storage.store(
        url=url,
        identifier="json_test",
        data_type="api_data",
        provider="test",
        data_value=orjson.dumps(test_data),
        ttl_seconds=3600,
    )
    # store() returns the stored entry, carrying the cachekey and detected mime_type
    assert success is not None and success.cachekey

    result = await temp_storage.retrieve_by_url(url)
    assert result is not None
    assert orjson.loads(result.data) == test_data


@pytest.mark.asyncio
async def test_data_serialization_binary(temp_storage):  # pylint: disable=redefined-outer-name
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
    # store() returns the stored entry, carrying the cachekey and detected mime_type
    assert success is not None and success.cachekey

    result = await temp_storage.retrieve_by_url(url)
    assert result is not None
    assert result.data == test_data


@pytest.mark.asyncio
async def test_inline_vs_file_threshold(temp_storage):  # pylint: disable=redefined-outer-name
    """Small content stored inline in DB; large content written to a blob file"""
    small_data = b"x" * 100
    large_data = b"x" * (16 * 1024 + 1)

    await temp_storage.store(
        url="https://example.com/small",
        identifier="test",
        data_type="api",
        provider="test",
        data_value=small_data,
        ttl_seconds=3600,
    )
    await temp_storage.store(
        url="https://example.com/large",
        identifier="test",
        data_type="image",
        provider="test",
        data_value=large_data,
        ttl_seconds=3600,
    )

    db_path = temp_storage.database_path
    with nowplaying.utils.sqlite.sqlite_connection(str(db_path)) as conn:
        small_row = conn.execute(
            "SELECT data_value, file_path FROM cached_data WHERE url = ?",
            ("https://example.com/small",),
        ).fetchone()
        large_row = conn.execute(
            "SELECT data_value, file_path FROM cached_data WHERE url = ?",
            ("https://example.com/large",),
        ).fetchone()

    assert small_row[0] is not None and small_row[1] is None, "small content should be inline"
    assert large_row[0] is None and large_row[1] is not None, "large content should be a file"

    small_result = await temp_storage.retrieve_by_url("https://example.com/small")
    large_result = await temp_storage.retrieve_by_url("https://example.com/large")
    assert small_result is not None and small_result.data == small_data
    assert large_result is not None and large_result.data == large_data


@pytest.mark.asyncio
async def test_cleanup_expired(temp_storage):  # pylint: disable=redefined-outer-name
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
async def test_cachekey_roundtrip(temp_storage):  # pylint: disable=redefined-outer-name
    """store → get_cache_keys_for_identifier → retrieve_by_cachekey returns the original bytes"""
    url = "https://example.com/cachekey_rt.jpg"
    test_data = b"roundtrip_image_bytes"

    await temp_storage.store(
        url=url,
        identifier="rt_artist",
        data_type="thumbnail",
        provider="test",
        data_value=test_data,
        ttl_seconds=3600,
    )

    cachekeys = await temp_storage.get_cache_keys_for_identifier(
        identifier="rt_artist", data_type="thumbnail"
    )
    assert len(cachekeys) == 1

    result = await temp_storage.retrieve_by_cachekey(cachekeys[0])
    assert result is not None
    assert result.data == test_data
    assert result.url == url


@pytest.mark.asyncio
async def test_cachekey_preserved_on_refetch(temp_storage):  # pylint: disable=redefined-outer-name
    """Upsert on the same URL preserves the original cachekey UUID"""
    url = "https://example.com/cachekey_preserve.jpg"

    await temp_storage.store(
        url=url,
        identifier="preserve_artist",
        data_type="thumbnail",
        provider="test",
        data_value=b"v1",
        ttl_seconds=3600,
    )

    cachekeys_v1 = await temp_storage.get_cache_keys_for_identifier(
        identifier="preserve_artist", data_type="thumbnail"
    )
    assert len(cachekeys_v1) == 1

    # Re-store the same URL (simulates a re-fetch with fresh content)
    await temp_storage.store(
        url=url,
        identifier="preserve_artist",
        data_type="thumbnail",
        provider="test",
        data_value=b"v2",
        ttl_seconds=3600,
    )

    cachekeys_v2 = await temp_storage.get_cache_keys_for_identifier(
        identifier="preserve_artist", data_type="thumbnail"
    )
    assert len(cachekeys_v2) == 1
    # UUID must survive the upsert
    assert cachekeys_v2[0] == cachekeys_v1[0]

    # But the stored bytes should be the new version
    result = await temp_storage.retrieve_by_cachekey(cachekeys_v1[0])
    assert result is not None
    assert result.data == b"v2"


@pytest.mark.asyncio
async def test_cachekey_unknown_returns_none(temp_storage):  # pylint: disable=redefined-outer-name
    """retrieve_by_cachekey returns None for an unknown UUID"""
    result = await temp_storage.retrieve_by_cachekey("00000000-0000-0000-0000-000000000000")
    assert result is None


@pytest.mark.asyncio
async def test_cachekey_expired_returns_none(temp_storage):  # pylint: disable=redefined-outer-name
    """retrieve_by_cachekey returns None once the entry has expired"""
    url = "https://example.com/cachekey_expired.jpg"

    await temp_storage.store(
        url=url,
        identifier="expiry_artist",
        data_type="thumbnail",
        provider="test",
        data_value=b"ephemeral",
        ttl_seconds=1,
    )

    cachekeys = await temp_storage.get_cache_keys_for_identifier(
        identifier="expiry_artist", data_type="thumbnail"
    )
    assert len(cachekeys) == 1
    cachekey = cachekeys[0]

    await asyncio.sleep(1.1)

    result = await temp_storage.retrieve_by_cachekey(cachekey)
    assert result is None


@pytest.mark.asyncio
async def test_concurrent_access():
    """Test concurrent access to storage (multiprocess simulation)"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create multiple storage instances (simulates multiple processes)
        storages = []
        for _ in range(3):
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
                assert result.data == f"data_{i}".encode()

        finally:
            # Cleanup
            for storage in storages:
                await storage.close()


@pytest.mark.asyncio
async def test_retrieve_returns_none_when_db_missing(bootstrap):  # pylint: disable=unused-argument
    """retrieve_by_url returns None gracefully if the database file is deleted mid-operation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        storage = nowplaying.datacache.storage.DataStorage(Path(temp_dir))
        await storage.initialize()

        url = "https://example.com/robustness.jpg"
        await storage.store(
            url=url,
            identifier="robustness_test",
            data_type="fanart",
            provider="test",
            data_value=b"data",
            ttl_seconds=3600,
        )

        # Close before unlinking — required on Windows where open files cannot be deleted
        await storage.close()

        # Delete the database file to simulate a missing/corrupted DB
        storage.database_path.unlink()

        # retrieve_by_url must not raise — it should return None and log an error
        result = await storage.retrieve_by_url(url)
        assert result is None


@pytest.mark.asyncio
async def test_store_returns_cachekey_usable_for_retrieval(temp_storage):  # pylint: disable=redefined-outer-name
    """The cachekey store() hands back addresses that exact entry.

    This is what lets the metadata pipeline put a /cover/{cachekey} URL in a track's
    metadata: it needs a handle for the art it just stored.
    """
    stored = await temp_storage.store(
        url="embedded://wnpmockartist_wnpmockalbum/provided_0",
        identifier="wnpmockartist_wnpmockalbum",
        data_type="front_cover",
        provider="embedded",
        data_value=b"\x89PNG\r\n\x1a\ncover-bytes",
        ttl_seconds=3600,
    )

    assert stored is not None and stored.cachekey
    entry = await temp_storage.retrieve_by_cachekey(stored.cachekey)
    assert entry is not None
    assert entry.data == b"\x89PNG\r\n\x1a\ncover-bytes"


@pytest.mark.asyncio
async def test_random_retrieval_reports_cachekey(temp_storage):  # pylint: disable=redefined-outer-name
    """A randomly-retrieved entry carries the cachekey it was stored under.

    The cover restore path reads art back with random=True and needs the key so it
    can point coverurl at the keyed route rather than the singleton /cover.png.
    """
    stored = await temp_storage.store(
        url="embedded://wnpmockartist_wnpmockalbum/provided_0",
        identifier="wnpmockartist_wnpmockalbum",
        data_type="front_cover",
        provider="embedded",
        data_value=b"\xff\xd8\xff\xe0jpeg-cover-bytes",
        ttl_seconds=3600,
    )

    entry = await temp_storage.retrieve_by_identifier(
        "wnpmockartist_wnpmockalbum", "front_cover", random=True
    )

    assert entry is not None
    assert entry.cachekey == stored.cachekey
    # mime_type is detected on store, so consumers never have to sniff it again
    assert entry.mime_type == "image/jpeg"


@pytest.mark.asyncio
async def test_store_keeps_source_bytes_untranscoded(temp_storage):  # pylint: disable=redefined-outer-name
    """Cover art is stored exactly as supplied rather than converted to PNG.

    Album art is usually JPEG; the old pipeline re-encoded it to lossless PNG, which
    inflated it for no benefit.  Only /wsstream converts now, at serialization time.
    """
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"jpeg-payload" * 8
    stored = await temp_storage.store(
        url="embedded://wnpmockartist_wnpmockalbum/provided_0",
        identifier="wnpmockartist_wnpmockalbum",
        data_type="front_cover",
        provider="embedded",
        data_value=jpeg_bytes,
        ttl_seconds=3600,
    )
    assert stored is not None

    entry = await temp_storage.retrieve_by_cachekey(stored.cachekey)
    assert entry is not None
    assert entry.data == jpeg_bytes
    assert entry.mime_type == "image/jpeg"


@pytest.mark.asyncio
async def test_store_returns_the_row_cachekey_not_a_generated_one(temp_storage):  # pylint: disable=redefined-outer-name
    """store() reports the cachekey actually on the row, including on upsert.

    store() generates a UUID before knowing whether it will insert or update. The
    UPDATE deliberately preserves the original key -- clients hold key lists from
    get_cache_keys_for_identifier -- so reporting the generated one would hand back a
    key present in no row. embedded://.../provided_0 is stable per track, so every
    replay after the first takes the upsert path.
    """
    url = "embedded://wnpmockartist_wnpmockalbum/provided_0"
    common = {
        "url": url,
        "identifier": "wnpmockartist_wnpmockalbum",
        "data_type": "front_cover",
        "provider": "embedded",
        "ttl_seconds": 3600,
    }

    first = await temp_storage.store(**common, data_value=b"\x89PNG\r\n\x1a\nfirst")
    second = await temp_storage.store(**common, data_value=b"\xff\xd8\xff\xe0second")
    assert first is not None and second is not None

    assert second.cachekey == first.cachekey, "the upsert preserves the original key"

    # And the reported key resolves to the current bytes, not a phantom row
    entry = await temp_storage.retrieve_by_cachekey(second.cachekey)
    assert entry is not None, "store() returned a cachekey that is not in the database"
    assert entry.data == b"\xff\xd8\xff\xe0second"


@pytest.mark.asyncio
@pytest.mark.parametrize("data_type", sorted(nowplaying.datacache.storage.IMAGE_DATA_TYPES))
async def test_store_refuses_non_image_under_image_type(temp_storage, data_type):  # pylint: disable=redefined-outer-name
    """Non-image bytes are refused for every image data_type.

    This is the single chokepoint: these bytes would be served with their detected
    type as Content-Type and rendered by templates. A remote submission supplies
    coverurl, which the webserver fetches, so the body is whoever's URL that was.
    Refusing here means later reads can assume image data_types hold images.
    """
    with pytest.raises(nowplaying.exceptions.ToxicContentError):
        await temp_storage.store(
            url=f"https://example.com/not-an-image-{data_type}",
            identifier="wnpmockartist_wnpmockalbum",
            data_type=data_type,
            provider="test",
            data_value=b"<html><script>alert(1)</script></html>",
            ttl_seconds=3600,
        )


@pytest.mark.asyncio
async def test_store_refusal_leaves_nothing_behind(temp_storage):  # pylint: disable=redefined-outer-name
    """A refused store must not leave a retrievable entry."""
    url = "https://example.com/toxic.png"
    with pytest.raises(nowplaying.exceptions.ToxicContentError):
        await temp_storage.store(
            url=url,
            identifier="wnpmockartist_wnpmockalbum",
            data_type="front_cover",
            provider="test",
            data_value=b"this is definitely not an image",
            ttl_seconds=3600,
        )

    assert await temp_storage.retrieve_by_url(url) is None
    assert (
        await temp_storage.retrieve_by_identifier(
            "wnpmockartist_wnpmockalbum", "front_cover", random=True
        )
        is None
    )


@pytest.mark.asyncio
async def test_store_allows_non_image_under_non_image_type(temp_storage):  # pylint: disable=redefined-outer-name
    """The image filter is scoped to image data_types, not applied to everything.

    API responses and MusicBrainz payloads are JSON by design; rejecting them would
    disable caching for most of the application.
    """
    stored = await temp_storage.store(
        url="apicache://theaudiodb/wnpmockartist/search",
        identifier="wnpmockartist",
        data_type="api_response",
        provider="theaudiodb",
        data_value=orjson.dumps({"artists": []}),
        ttl_seconds=3600,
    )

    assert stored is not None and stored.cachekey
    entry = await temp_storage.retrieve_by_cachekey(stored.cachekey)
    assert entry is not None
    assert entry.cachekey == stored.cachekey, "retrieve_by_cachekey should echo the given key"


@pytest.mark.asyncio
@pytest.mark.parametrize("data_type", sorted(nowplaying.datacache.storage.IMAGE_DATA_TYPES))
async def test_negative_cache_survives_the_image_filter(temp_storage, data_type):  # pylint: disable=redefined-outer-name
    """A recorded 404 stores for image data_types even though b"" is not an image.

    Negative entries are b"" with status_code=404, which puremagic cannot identify.
    If the image filter judged them as content they would all be refused, the
    status_code != 200 retrieval guard would have no row to suppress retries with,
    and every track would re-ask the provider for art it has already said it lacks.
    """
    url = f"https://example.com/missing-{data_type}.jpg"
    stored = await temp_storage.store(
        url=url,
        identifier="wnpmockartist",
        data_type=data_type,
        provider="test",
        data_value=b"",
        ttl_seconds=3600,
        status_code=404,
    )

    assert stored is not None, "negative caching must not be refused by the image filter"
    entry = await temp_storage.retrieve_by_url(url)
    assert entry is not None
    assert entry.status_code == 404


@pytest.mark.asyncio
async def test_negative_cache_skips_color_extraction(temp_storage, caplog):  # pylint: disable=redefined-outer-name
    """A recorded 404 must not be handed to the colour extractor.

    front_cover is in COLOR_EXTRACT_TYPES, so a negative entry used to spawn
    extraction on b'', which Pillow cannot open -- logging a full traceback at ERROR
    for every provider miss.
    """
    caplog.set_level(logging.DEBUG)
    await temp_storage.store(
        url="https://example.com/missing-cover.jpg",
        identifier="wnpmockartist",
        data_type="front_cover",
        provider="test",
        data_value=b"",
        ttl_seconds=3600,
        status_code=404,
    )
    # Extraction is fire-and-forget, so give a spawned task a chance to run and fail
    await asyncio.sleep(0)

    assert not [r for r in caplog.records if "palette" in r.getMessage().lower()]
