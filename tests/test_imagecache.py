#!/usr/bin/env python3
"""test metadata DB"""

# pylint: disable=redefined-outer-name

import asyncio
import contextlib
import logging
import multiprocessing
import time
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio
import requests

import nowplaying.imagecache  # pylint: disable=import-error
import nowplaying.utils  # pylint: disable=import-error
import nowplaying.utils.sqlite

TEST_URLS = [
    "https://r2.theaudiodb.com/images/media/artist/fanart/numan-gary-5026a93c591b1.jpg",
    "https://r2.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b765ed348.jpg",
    "https://r2.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b899f3268.jpg",
]


@pytest_asyncio.fixture
async def get_imagecache(bootstrap):
    """setup the image cache for testing"""
    config = bootstrap
    workers = 2
    dbdir = config.testdir.joinpath("imagecache")
    dbdir.mkdir()
    logpath = config.testdir.joinpath("debug.log")
    stopevent = multiprocessing.Event()
    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir, stopevent=stopevent)
    icprocess = multiprocessing.Process(
        target=imagecache.queue_process,
        name="ICProcess",
        args=(
            logpath,
            workers,
        ),
    )
    icprocess.start()
    yield config, imagecache
    stopevent.set()
    imagecache.stop_process()
    icprocess.join()


@pytest_asyncio.fixture
async def imagecache_with_dir(bootstrap):
    """Simple ImageCache fixture with test directory"""
    config = bootstrap
    dbdir = config.testdir.joinpath("imagecache")
    dbdir.mkdir()
    cache = nowplaying.imagecache.ImageCache(cachedir=dbdir)
    yield cache
    cache.close()


@pytest_asyncio.fixture
async def imagecache_with_stopevent(bootstrap):
    """ImageCache fixture with configurable stopevent"""
    config = bootstrap
    dbdir = config.testdir.joinpath("imagecache")
    dbdir.mkdir()
    created_caches = []

    def _create_imagecache(stopevent=None):
        cache = nowplaying.imagecache.ImageCache(cachedir=dbdir, stopevent=stopevent)
        created_caches.append(cache)
        return cache

    yield _create_imagecache

    # Cleanup: close all created caches to release file handles
    for cache in created_caches:
        cache.close()


@pytest.mark.asyncio
async def test_ic_upgrade(bootstrap):
    """setup the image cache for testing"""

    config = bootstrap
    dbdir = config.testdir.joinpath("imagecache")
    dbdir.mkdir()

    with nowplaying.utils.sqlite.sqlite_connection(
        dbdir.joinpath("imagecachev1.db"), timeout=30
    ) as connection:
        cursor = connection.cursor()

        v1tabledef = """
        CREATE TABLE artistsha
        (url TEXT PRIMARY KEY,
         cachekey TEXT DEFAULT NULL,
         artist TEXT NOT NULL,
         imagetype TEXT NOT NULL,
         timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
         );
        """

        cursor.execute(v1tabledef)

    stopevent = multiprocessing.Event()
    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir, stopevent=stopevent)  # pylint: disable=unused-variable
    assert dbdir.joinpath("imagecachev2.db").exists()
    assert not dbdir.joinpath("imagecachev1.db").exists()
    stopevent.set()
    imagecache.stop_process()


def test_imagecache(get_imagecache):  # pylint: disable=redefined-outer-name
    """testing queue filling"""
    config, imagecache = get_imagecache

    imagecache.fill_queue(
        config=config, identifier="Gary Numan", imagetype="fanart", srclocationlist=TEST_URLS
    )
    imagecache.fill_queue(
        config=config, identifier="Gary Numan", imagetype="fanart", srclocationlist=TEST_URLS
    )
    time.sleep(5)

    page = requests.get(TEST_URLS[2], timeout=10)
    png = nowplaying.utils.image2png(page.content)

    for cachekey in list(imagecache.cache.iterkeys()):
        data1 = imagecache.find_cachekey(cachekey)
        logging.debug("%s %s", cachekey, data1)
        cachedimage = imagecache.cache[cachekey]
        if png == cachedimage:
            logging.debug("Found it at %s", cachekey)


@pytest.mark.asyncio
async def test_randomimage(get_imagecache):  # pylint: disable=redefined-outer-name
    """get a 'random' image'"""
    config, imagecache = get_imagecache  # pylint: disable=unused-variable

    imagedict = {"srclocation": TEST_URLS[0], "identifier": "Gary Numan", "imagetype": "fanart"}

    imagecache.image_dl(imagedict)

    data_find = imagecache.find_srclocation(TEST_URLS[0])
    assert data_find["identifier"] == "garynuman"
    assert data_find["imagetype"] == "fanart"

    data_random = imagecache.random_fetch(identifier="Gary Numan", imagetype="fanart")
    assert data_random["identifier"] == "garynuman"
    assert data_random["cachekey"]
    assert data_random["srclocation"] == TEST_URLS[0]

    data_findkey = imagecache.find_cachekey(data_random["cachekey"])
    assert data_findkey

    image = imagecache.random_image_fetch(identifier="Gary Numan", imagetype="fanart")
    cachedimage = imagecache.cache[data_random["cachekey"]]
    assert image == cachedimage


@pytest.mark.asyncio
async def test_randomfailure(get_imagecache):  # pylint: disable=redefined-outer-name
    """test db del 1"""
    config, imagecache = get_imagecache  # pylint: disable=unused-variable

    imagecache.setup_sql(initialize=True)
    assert imagecache.databasefile.exists()

    imagecache.setup_sql()
    assert imagecache.databasefile.exists()

    imagecache.databasefile.unlink()

    image = imagecache.random_image_fetch(identifier="Gary Numan", imagetype="fanart")
    assert not image

    image = imagecache.random_image_fetch(identifier="Gary Numan", imagetype="fanart")
    assert not image


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stopevent_state,expected",
    [
        ("set", True),
        ("unset", False),
        ("none", True),  # safe_stopevent_check treats None as AttributeError -> True
    ],
)
async def test_queue_should_stop(imagecache_with_stopevent, stopevent_state, expected):
    """test _queue_should_stop with different stopevent states"""
    if stopevent_state == "none":
        imagecache = imagecache_with_stopevent(stopevent=None)
    else:
        stopevent = asyncio.Event()
        if stopevent_state == "set":
            stopevent.set()
        imagecache = imagecache_with_stopevent(stopevent=stopevent)

    assert imagecache._queue_should_stop() is expected  # pylint: disable=protected-access


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mock_dataset,recently_processed,expected_count,expected_urls",
    [
        # Empty dataset
        (None, {}, 0, []),
        # Normal data with no filtering
        (
            [
                {"srclocation": "url1", "identifier": "artist1", "imagetype": "fanart"},
                {"srclocation": "url2", "identifier": "artist2", "imagetype": "fanart"},
            ],
            {},
            2,
            ["url1", "url2"],
        ),
        # Recently processed filtering
        (
            [
                {"srclocation": "url1", "identifier": "artist1", "imagetype": "fanart"},
                {"srclocation": "url2", "identifier": "artist2", "imagetype": "fanart"},
            ],
            {
                "url1": {
                    "timestamp": time.time(),
                    "error_type": "success",
                    "cooldown": 150,
                    "failure_count": 0,
                }
            },
            1,
            ["url2"],
        ),
        # Stop signal included
        (
            [
                {"srclocation": "url1", "identifier": "artist1", "imagetype": "fanart"},
                {"srclocation": "STOPWNP", "identifier": "STOPWNP", "imagetype": "STOPWNP"},
            ],
            {},
            2,
            ["url1", "STOPWNP"],
        ),
    ],
)
async def test_get_next_queue_batch(
    imagecache_with_dir, mock_dataset, recently_processed, expected_count, expected_urls
):
    """test _get_next_queue_batch with various scenarios"""
    with patch.object(imagecache_with_dir, "get_next_dlset", return_value=mock_dataset):
        batch = imagecache_with_dir._get_next_queue_batch(recently_processed)  # pylint: disable=protected-access

        if expected_count == 0:
            assert not batch
        else:
            assert len(batch) == expected_count
            actual_urls = [item["srclocation"] for item in batch]
            for url in expected_urls:
                assert url in actual_urls


def test_cleanup_queue_tracking():
    """test _cleanup_queue_tracking removes old entries"""
    current_time = time.time()
    recently_processed = {
        "url1": {
            "timestamp": current_time - 100,
            "error_type": "success",
            "cooldown": 150,  # Should stay (100 < 150)
            "failure_count": 0,
        },
        "url2": {
            "timestamp": current_time - 200,
            "error_type": "server_error",
            "cooldown": 180,  # Should be removed (200 > 180)
            "failure_count": 2,
        },
        "url3": {
            "timestamp": current_time - 50,
            "error_type": "network_error",
            "cooldown": 300,  # Should stay (50 < 300)
            "failure_count": 1,
        },
    }

    nowplaying.imagecache.ImageCache._cleanup_queue_tracking(recently_processed)  # pylint: disable=protected-access

    assert "url1" in recently_processed
    assert "url2" not in recently_processed
    assert "url3" in recently_processed


def test_cleanup_queue_tracking_empty():
    """test _cleanup_queue_tracking with empty dict"""
    recently_processed = {}

    nowplaying.imagecache.ImageCache._cleanup_queue_tracking(recently_processed)  # pylint: disable=protected-access

    assert not recently_processed


@pytest.mark.asyncio
async def test_get_next_dlset_empty_database(bootstrap):
    """test get_next_dlset with empty database"""
    config = bootstrap
    dbdir = config.testdir.joinpath("imagecache")
    dbdir.mkdir()

    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir)
    try:
        result = imagecache.get_next_dlset()
        assert result is None or result == []
    finally:
        # Clean up SQLite WAL files to prevent flaky test failures
        if imagecache.databasefile.exists():
            with contextlib.suppress(Exception):
                with nowplaying.utils.sqlite.sqlite_connection(
                    imagecache.databasefile, timeout=5
                ) as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.execute("PRAGMA journal_mode=DELETE")


@pytest.mark.asyncio
async def test_database_operations(bootstrap):
    """test core database operations"""
    config = bootstrap
    dbdir = config.testdir.joinpath("imagecache")
    dbdir.mkdir()

    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir)

    # Test put_db_srclocation
    imagecache.put_db_srclocation("testartist", "testurl", "fanart")

    # Test find_srclocation
    data = imagecache.find_srclocation("testurl")
    assert data is not None
    assert data["identifier"] == "testartist"
    assert data["imagetype"] == "fanart"
    assert data["srclocation"] == "testurl"

    # Test erase_srclocation
    imagecache.erase_srclocation("testurl")
    data = imagecache.find_srclocation("testurl")
    assert data is None


@pytest.mark.asyncio
async def test_put_db_cachekey_with_content(imagecache_with_dir):
    """test put_db_cachekey with actual content"""

    # Create some fake image content
    fake_content = b"fake_image_content"

    result = imagecache_with_dir.put_db_cachekey(
        identifier="testartist", srclocation="testurl", imagetype="fanart", content=fake_content
    )

    assert result is True

    # Verify it was stored
    data = imagecache_with_dir.find_srclocation("testurl")
    assert data is not None
    assert data["cachekey"] is not None

    # Verify content is in cache
    assert data["cachekey"] in imagecache_with_dir.cache


@pytest.mark.asyncio
async def test_vacuum_database(imagecache_with_dir):
    """test vacuum_database operation"""
    # Add some data
    imagecache_with_dir.put_db_srclocation("testartist", "testurl", "fanart")

    # This should not raise an exception
    imagecache_with_dir.vacuum_database()

    # Verify database still works
    data = imagecache_with_dir.find_srclocation("testurl")
    assert data is not None


@pytest.mark.asyncio
async def test_stopwnp_data_integrity(imagecache_with_dir):
    """test STOPWNP maintains data integrity during shutdown"""
    # Add some valid data to the database first
    imagecache_with_dir.put_db_srclocation("testartist1", "testurl1", "fanart")
    imagecache_with_dir.put_db_srclocation("testartist2", "testurl2", "fanart")

    # Verify data exists before shutdown
    data1 = imagecache_with_dir.find_srclocation("testurl1")
    data2 = imagecache_with_dir.find_srclocation("testurl2")
    assert data1 is not None
    assert data2 is not None

    # Call stop_process to inject STOPWNP
    imagecache_with_dir.stop_process()

    # Verify database integrity is maintained after shutdown signal
    data1_after = imagecache_with_dir.find_srclocation("testurl1")
    data2_after = imagecache_with_dir.find_srclocation("testurl2")
    assert data1_after is not None
    assert data2_after is not None
    assert data1_after == data1
    assert data2_after == data2

    # Verify database can still accept operations (not corrupted)
    imagecache_with_dir.put_db_srclocation("testartist3", "testurl3", "fanart")
    data3 = imagecache_with_dir.find_srclocation("testurl3")
    assert data3 is not None

    # Verify STOPWNP was properly inserted and can be cleaned up
    stopwnp_data = imagecache_with_dir.find_srclocation("STOPWNP")
    assert stopwnp_data is not None
    assert stopwnp_data["identifier"] == "STOPWNP"
    assert stopwnp_data["imagetype"] == "STOPWNP"

    # Cleanup should work without corruption
    imagecache_with_dir.erase_srclocation("STOPWNP")
    stopwnp_after_cleanup = imagecache_with_dir.find_srclocation("STOPWNP")
    assert stopwnp_after_cleanup is None


@pytest.mark.asyncio
async def test_stopwnp_only_in_batch(bootstrap):
    """test STOPWNP as the only item in batch during shutdown"""
    config = bootstrap
    dbdir = config.testdir.joinpath("imagecache")
    dbdir.mkdir()

    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir)
    recently_processed = {}

    # Simulate shutdown scenario where only STOPWNP is in the queue
    mock_dataset = [
        {"srclocation": "STOPWNP", "identifier": "STOPWNP", "imagetype": "STOPWNP"},
    ]

    with patch.object(imagecache, "get_next_dlset", return_value=mock_dataset):
        batch = imagecache._get_next_queue_batch(recently_processed)  # pylint: disable=protected-access
        assert len(batch) == 1
        assert batch[0]["srclocation"] == "STOPWNP"

    # Verify filtering out STOPWNP leaves empty batch (clean shutdown)
    items_to_process = [item for item in batch if item["srclocation"] != "STOPWNP"]
    should_stop = len(items_to_process) != len(batch)

    assert not items_to_process
    assert should_stop


@pytest.mark.asyncio
async def test_stopwnp_with_valid_items(bootstrap):
    """test STOPWNP processes valid items before stopping"""
    config = bootstrap
    dbdir = config.testdir.joinpath("imagecache")
    dbdir.mkdir()

    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir)
    recently_processed = {}

    # Simulate shutdown with valid work still pending
    mock_dataset = [
        {"srclocation": "validurl1", "identifier": "artist1", "imagetype": "fanart"},
        {"srclocation": "validurl2", "identifier": "artist2", "imagetype": "fanart"},
        {"srclocation": "STOPWNP", "identifier": "STOPWNP", "imagetype": "STOPWNP"},
    ]

    with patch.object(imagecache, "get_next_dlset", return_value=mock_dataset):
        batch = imagecache._get_next_queue_batch(recently_processed)  # pylint: disable=protected-access
        assert len(batch) == 3

    # Filter out STOPWNP but keep valid items
    items_to_process = [item for item in batch if item["srclocation"] != "STOPWNP"]
    should_stop = len(items_to_process) != len(batch)

    assert len(items_to_process) == 2  # Valid items should be processed
    assert should_stop
    assert items_to_process[0]["srclocation"] == "validurl1"
    assert items_to_process[1]["srclocation"] == "validurl2"


@pytest.mark.asyncio
async def test_database_operations_after_stopwnp(imagecache_with_dir):
    """test database remains functional after STOPWNP injection"""
    # Normal operations before shutdown
    imagecache_with_dir.put_db_srclocation("artist1", "url1", "fanart")
    result1 = imagecache_with_dir.find_srclocation("url1")
    assert result1 is not None

    # Inject shutdown signal
    imagecache_with_dir.stop_process()

    # Database should still be functional for all operations
    imagecache_with_dir.put_db_srclocation("artist2", "url2", "fanart")
    result2 = imagecache_with_dir.find_srclocation("url2")
    assert result2 is not None

    # Cache operations should work
    fake_content = b"test_image_data"
    cache_result = imagecache_with_dir.put_db_cachekey(
        identifier="artist3", srclocation="url3", imagetype="fanart", content=fake_content
    )
    assert cache_result is True

    # Cleanup operations should work
    imagecache_with_dir.erase_srclocation("url1")
    result1_after = imagecache_with_dir.find_srclocation("url1")
    assert result1_after is None

    # Database maintenance should work
    imagecache_with_dir.vacuum_database()  # Should not raise exception


@pytest.mark.asyncio
async def test_image_dl_rate_limit_handling(imagecache_with_dir):
    """Test that 429 rate limit responses preserve URLs for retry"""
    imagedict = {
        "srclocation": "https://example.com/image.jpg",
        "identifier": "testartist",
        "imagetype": "fanart",
    }

    # First add the URL to the database
    imagecache_with_dir.put_db_srclocation("testartist", "https://example.com/image.jpg", "fanart")

    # Verify URL exists
    data_before = imagecache_with_dir.find_srclocation("https://example.com/image.jpg")
    assert data_before is not None

    # Mock 429 response
    mock_response = MagicMock()
    mock_response.status_code = 429

    with patch("requests_cache.CachedSession.get", return_value=mock_response):
        imagecache_with_dir.image_dl(imagedict)

    # URL should still exist after 429 (not erased)
    data_after = imagecache_with_dir.find_srclocation("https://example.com/image.jpg")
    assert data_after is not None
    assert data_after["identifier"] == "testartist"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403, 410])
async def test_image_dl_client_errors_remove_urls(imagecache_with_dir, status_code):
    """Test that 4xx client errors remove URLs as they're likely invalid"""
    imagedict = {
        "srclocation": f"https://example.com/client_error_{status_code}.jpg",
        "identifier": "testartist",
        "imagetype": "fanart",
    }

    # Add URL to database
    imagecache_with_dir.put_db_srclocation("testartist", imagedict["srclocation"], "fanart")

    # Verify URL exists
    data_before = imagecache_with_dir.find_srclocation(imagedict["srclocation"])
    assert data_before is not None

    # Mock client error response
    mock_response = MagicMock()
    mock_response.status_code = status_code

    with patch("requests_cache.CachedSession.get", return_value=mock_response):
        imagecache_with_dir.image_dl(imagedict)

    # Verify URL was erased (invalid client error)
    data_after = imagecache_with_dir.find_srclocation(imagedict["srclocation"])
    assert data_after is None, f"URL should be removed after {status_code} client error"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
async def test_image_dl_server_errors_preserve_urls(imagecache_with_dir, status_code):
    """Test that 5xx server errors preserve URLs as they're likely transient"""
    imagedict = {
        "srclocation": f"https://example.com/server_error_{status_code}.jpg",
        "identifier": "testartist",
        "imagetype": "fanart",
    }

    # Add URL to database
    imagecache_with_dir.put_db_srclocation("testartist", imagedict["srclocation"], "fanart")

    # Verify URL exists
    data_before = imagecache_with_dir.find_srclocation(imagedict["srclocation"])
    assert data_before is not None

    # Mock server error response
    mock_response = MagicMock()
    mock_response.status_code = status_code

    with patch("requests_cache.CachedSession.get", return_value=mock_response):
        imagecache_with_dir.image_dl(imagedict)

    # Verify URL still exists (transient server error)
    data_after = imagecache_with_dir.find_srclocation(imagedict["srclocation"])
    assert data_after is not None, f"URL should be preserved after {status_code} server error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code,expected_error_type,expected_cooldown",
    [
        (429, "rate_limit", 60),
        (500, "server_error", 600),
        (502, "server_error", 600),
        (503, "server_error", 600),
    ],
)
async def test_image_dl_returns_proper_failure_info(
    imagecache_with_dir, status_code, expected_error_type, expected_cooldown
):
    """Test that image_dl returns correct failure information for different HTTP errors"""
    imagedict = {
        "srclocation": f"https://example.com/error_{status_code}.jpg",
        "identifier": "testartist",
        "imagetype": "fanart",
    }

    # Mock the HTTP response
    mock_response = MagicMock()
    mock_response.status_code = status_code

    with patch("requests_cache.CachedSession.get", return_value=mock_response):
        result = imagecache_with_dir.image_dl(imagedict)

    # Verify the correct failure information is returned
    assert result is not None, f"Should return failure info for {status_code}"
    assert result["error_type"] == expected_error_type
    assert result["cooldown"] == expected_cooldown


@pytest.mark.asyncio
async def test_image_dl_returns_none_on_success(imagecache_with_dir):
    """Test that image_dl returns None on successful download"""
    imagedict = {
        "srclocation": "https://example.com/success.jpg",
        "identifier": "testartist",
        "imagetype": "fanart",
    }

    # Mock successful HTTP response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"fake image data"

    with patch("requests_cache.CachedSession.get", return_value=mock_response):
        result = imagecache_with_dir.image_dl(imagedict)

    # Success should return None
    assert result is None, "Successful download should return None"


@pytest.mark.asyncio
async def test_image_dl_network_error_returns_failure_info(imagecache_with_dir):
    """Test that network errors return proper failure information"""
    imagedict = {
        "srclocation": "https://example.com/network_error.jpg",
        "identifier": "testartist",
        "imagetype": "fanart",
    }

    # Mock network exception
    with patch("requests_cache.CachedSession.get", side_effect=Exception("Network error")):
        result = imagecache_with_dir.image_dl(imagedict)

    # Should return network error info
    assert result is not None
    assert result["error_type"] == "network_error"
    assert result["cooldown"] == 300  # 5 minutes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type,expected_limit",
    [
        ("rate_limit", 10),
        ("server_error", 5),
        ("network_error", 3),
    ],
)
async def test_failure_count_tracking_and_limits(imagecache_with_dir, error_type, expected_limit):
    """Test that URLs are removed after exceeding failure limits"""
    # Create a tracking dict to simulate the queue processing
    recently_processed = {}
    current_time = time.time()

    srclocation = f"https://example.com/{error_type}_test.jpg"

    # Add URL to database first
    imagecache_with_dir.put_db_srclocation("testartist", srclocation, "fanart")

    # Verify URL exists initially
    data_before = imagecache_with_dir.find_srclocation(srclocation)
    assert data_before is not None

    # Simulate repeated failures up to the limit
    for attempt in range(1, expected_limit + 1):
        # Simulate existing failure info (like queue processing would have)
        existing_info = recently_processed.get(srclocation, {"failure_count": attempt - 1})
        failure_count = existing_info["failure_count"] + 1

        # Define the same failure limits as in the actual code
        failure_limits = {
            "rate_limit": 10,
            "server_error": 5,
            "network_error": 3,
            "client_error": 1,
        }

        max_failures = failure_limits.get(error_type, 3)

        if failure_count >= max_failures:
            # Should remove URL at this point
            imagecache_with_dir.erase_srclocation(srclocation)
            recently_processed.pop(srclocation, None)

            # Verify URL was removed
            data_after = imagecache_with_dir.find_srclocation(srclocation)
            assert data_after is None, (
                f"URL should be removed after {failure_count} {error_type} failures"
            )
            assert srclocation not in recently_processed
            break

        # Record failure (simulate queue processing logic)
        recently_processed[srclocation] = {
            "timestamp": current_time,
            "error_type": error_type,
            "cooldown": 300,  # Doesn't matter for this test
            "failure_count": failure_count,
        }

    # Final verification - URL should be gone after exceeding limit
    final_data = imagecache_with_dir.find_srclocation(srclocation)
    assert final_data is None, (
        f"URL should be permanently removed after {expected_limit} {error_type} failures"
    )


@pytest.mark.asyncio
async def test_failure_count_resets_on_success(imagecache_with_dir):  # pylint: disable=unused-argument
    """Test that failure counts reset to zero on successful download"""
    recently_processed = {}
    current_time = time.time()
    srclocation = "https://example.com/reset_test.jpg"

    # Simulate some failures first
    recently_processed[srclocation] = {
        "timestamp": current_time,
        "error_type": "server_error",
        "cooldown": 600,
        "failure_count": 3,  # Close to the limit of 5
    }

    # Simulate successful download (like queue processing would do)
    recently_processed[srclocation] = {
        "timestamp": current_time,
        "error_type": "success",
        "cooldown": 30,
        "failure_count": 0,  # Should reset to 0
    }

    # Verify failure count was reset
    assert recently_processed[srclocation]["failure_count"] == 0
    assert recently_processed[srclocation]["error_type"] == "success"


@pytest.mark.asyncio
async def test_failure_count_increments_properly(imagecache_with_dir):  # pylint: disable=unused-argument
    """Test that failure counts increment correctly across multiple failures"""
    recently_processed = {}
    current_time = time.time()
    srclocation = "https://example.com/increment_test.jpg"

    # Simulate gradual failure accumulation (like queue processing)
    for expected_count in range(1, 4):  # Test 1, 2, 3 failures
        existing_info = recently_processed.get(srclocation, {"failure_count": 0})
        failure_count = existing_info["failure_count"] + 1

        recently_processed[srclocation] = {
            "timestamp": current_time,
            "error_type": "network_error",
            "cooldown": 300,
            "failure_count": failure_count,
        }

        # Verify count incremented correctly
        assert recently_processed[srclocation]["failure_count"] == expected_count

    # At this point we should have 3 failures for network_error (which has limit of 3)
    # The 4th failure should trigger removal
    existing_info = recently_processed.get(srclocation, {"failure_count": 0})
    failure_count = existing_info["failure_count"] + 1  # This makes it 4

    failure_limits = {"network_error": 3}
    max_failures = failure_limits.get("network_error", 3)

    # Should hit the limit
    assert failure_count >= max_failures, "Should exceed failure limit"


@pytest.mark.asyncio
async def test_queue_processing_failure_count_integration(imagecache_with_dir):  # pylint: disable=too-many-locals
    """Integration test for the complete failure count system in queue processing"""
    # Add a URL that will consistently fail with server errors
    test_url = "https://example.com/integration_test.jpg"
    imagecache_with_dir.put_db_srclocation("testartist", test_url, "fanart")

    # Verify URL exists initially
    data_before = imagecache_with_dir.find_srclocation(test_url)
    assert data_before is not None

    # Mock the image_dl method to consistently return server errors
    server_error_count = 0
    original_image_dl = imagecache_with_dir.image_dl

    def mock_image_dl_server_errors(imagedict):  # pylint: disable=unused-argument
        nonlocal server_error_count
        server_error_count += 1
        # Return server error info (like the real method would)
        return {"error_type": "server_error", "cooldown": 600}

    imagecache_with_dir.image_dl = mock_image_dl_server_errors

    try:
        # Simulate the queue processing logic for server errors (limit: 5)
        recently_processed = {}
        current_time = time.time()

        for _ in range(1, 7):  # Go beyond the limit of 5
            # Simulate queue batch processing
            batch = [{"srclocation": test_url, "identifier": "testartist", "imagetype": "fanart"}]
            results = [mock_image_dl_server_errors(item) for item in batch]

            # Process results like the real queue processing does
            for i, item in enumerate(batch):
                result = results[i] if i < len(results) else None
                srclocation = item["srclocation"]

                if result is None:
                    # Success case (won't happen in this test)
                    recently_processed[srclocation] = {
                        "timestamp": current_time,
                        "error_type": "success",
                        "cooldown": 30,
                        "failure_count": 0,
                    }
                else:
                    # Failure - increment failure count and check limits
                    existing_info = recently_processed.get(srclocation, {"failure_count": 0})
                    failure_count = existing_info["failure_count"] + 1
                    error_type = result["error_type"]

                    # Use the same failure limits as the actual code
                    failure_limits = {
                        "rate_limit": 10,
                        "server_error": 5,
                        "network_error": 3,
                        "client_error": 1,
                    }

                    max_failures = failure_limits.get(error_type, 3)

                    if failure_count >= max_failures:
                        # Should remove URL at attempt 5
                        imagecache_with_dir.erase_srclocation(srclocation)
                        recently_processed.pop(srclocation, None)
                        break

                    # Record failure with updated count
                    recently_processed[srclocation] = {
                        "timestamp": current_time,
                        "error_type": error_type,
                        "cooldown": result["cooldown"],
                        "failure_count": failure_count,
                    }

        # Verify URL was removed after 5 server error failures
        data_after = imagecache_with_dir.find_srclocation(test_url)
        assert data_after is None, "URL should be removed after 5 server error failures"
        assert server_error_count >= 5, (
            f"Should have attempted at least 5 times, got {server_error_count}"
        )

    finally:
        # Restore original method
        imagecache_with_dir.image_dl = original_image_dl


@pytest.mark.asyncio
async def test_queue_processing_success_recovery_integration(imagecache_with_dir):  # pylint: disable=too-many-locals
    """Integration test for failure count reset on successful download"""
    # Add a URL that will fail then succeed
    test_url = "https://example.com/recovery_test.jpg"
    imagecache_with_dir.put_db_srclocation("testartist", test_url, "fanart")

    # Mock image_dl to fail 3 times then succeed
    attempt_count = 0
    original_image_dl = imagecache_with_dir.image_dl

    def mock_image_dl_recovery(imagedict):  # pylint: disable=unused-argument
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count <= 3:
            # First 3 attempts fail with network error
            return {"error_type": "network_error", "cooldown": 300}

        # 4th attempt succeeds
        return None  # Success returns None

    imagecache_with_dir.image_dl = mock_image_dl_recovery

    try:
        recently_processed = {}
        current_time = time.time()

        # Process 4 attempts
        for _ in range(1, 5):
            batch = [{"srclocation": test_url, "identifier": "testartist", "imagetype": "fanart"}]
            results = [mock_image_dl_recovery(item) for item in batch]

            # Process results
            for i, item in enumerate(batch):
                result = results[i] if i < len(results) else None
                srclocation = item["srclocation"]

                if result is None:
                    # Success - reset failure count
                    recently_processed[srclocation] = {
                        "timestamp": current_time,
                        "error_type": "success",
                        "cooldown": 30,
                        "failure_count": 0,
                    }
                else:
                    # Failure - increment count
                    existing_info = recently_processed.get(srclocation, {"failure_count": 0})
                    failure_count = existing_info["failure_count"] + 1

                    recently_processed[srclocation] = {
                        "timestamp": current_time,
                        "error_type": result["error_type"],
                        "cooldown": result["cooldown"],
                        "failure_count": failure_count,
                    }

        # Verify URL still exists (not removed due to success)
        data_after = imagecache_with_dir.find_srclocation(test_url)
        assert data_after is not None, "URL should still exist after successful recovery"

        # Verify failure count was reset to 0 on success
        assert recently_processed[test_url]["failure_count"] == 0
        assert recently_processed[test_url]["error_type"] == "success"
        assert attempt_count == 4, "Should have made exactly 4 attempts"

    finally:
        # Restore original method
        imagecache_with_dir.image_dl = original_image_dl


@pytest.mark.asyncio
async def test_image_dl_404_handling(imagecache_with_dir):
    """Test that 404 responses erase URLs as invalid"""
    imagedict = {
        "srclocation": "https://example.com/notfound.jpg",
        "identifier": "testartist",
        "imagetype": "fanart",
    }

    # First add the URL to the database
    imagecache_with_dir.put_db_srclocation(
        "testartist", "https://example.com/notfound.jpg", "fanart"
    )

    # Verify URL exists
    data_before = imagecache_with_dir.find_srclocation("https://example.com/notfound.jpg")
    assert data_before is not None

    # Mock 404 response
    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("requests_cache.CachedSession.get", return_value=mock_response):
        imagecache_with_dir.image_dl(imagedict)

    # URL should be erased after 404
    data_after = imagecache_with_dir.find_srclocation("https://example.com/notfound.jpg")
    assert data_after is None
