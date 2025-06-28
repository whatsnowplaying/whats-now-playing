#!/usr/bin/env python3
''' test metadata DB '''

#pylint: disable=redefined-outer-name

import asyncio
import contextlib
import logging
import multiprocessing
import sqlite3
import sys
import time
from unittest.mock import patch

import pytest
import pytest_asyncio
import requests

import nowplaying.imagecache  # pylint: disable=import-error
import nowplaying.utils  # pylint: disable=import-error

TEST_URLS = [
    'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5026a93c591b1.jpg',
    'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b765ed348.jpg',
    'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b899f3268.jpg'
]


@pytest_asyncio.fixture
async def get_imagecache(bootstrap):
    ''' setup the image cache for testing '''
    config = bootstrap
    workers = 2
    dbdir = config.testdir.joinpath('imagecache')
    dbdir.mkdir()
    logpath = config.testdir.joinpath('debug.log')
    stopevent = multiprocessing.Event()
    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir, stopevent=stopevent)
    icprocess = multiprocessing.Process(target=imagecache.queue_process,
                                        name='ICProcess',
                                        args=(
                                            logpath,
                                            workers,
                                        ))
    icprocess.start()
    yield config, imagecache
    stopevent.set()
    imagecache.stop_process()
    icprocess.join()


@pytest_asyncio.fixture
async def imagecache_with_dir(bootstrap):
    ''' Simple ImageCache fixture with test directory '''
    config = bootstrap
    dbdir = config.testdir.joinpath('imagecache')
    dbdir.mkdir()
    cache = nowplaying.imagecache.ImageCache(cachedir=dbdir)
    yield cache

    # Cleanup: close cache to release file handles
    with contextlib.suppress(Exception):
        if hasattr(cache, 'close'):
            cache.close()
        # Force close any database connections
        if hasattr(cache, 'databasefile'):
            with contextlib.suppress(sqlite3.Error, Exception):
                conn = sqlite3.connect(cache.databasefile)
                conn.close()


@pytest_asyncio.fixture
async def imagecache_with_stopevent(bootstrap):
    ''' ImageCache fixture with configurable stopevent '''
    config = bootstrap
    dbdir = config.testdir.joinpath('imagecache')
    dbdir.mkdir()
    created_caches = []

    def _create_imagecache(stopevent=None):
        cache = nowplaying.imagecache.ImageCache(cachedir=dbdir, stopevent=stopevent)
        created_caches.append(cache)
        return cache

    yield _create_imagecache

    # Cleanup: close all created caches to release file handles
    for cache in created_caches:
        with contextlib.suppress(Exception):
            if hasattr(cache, 'close'):
                cache.close()
            # Force close any database connections
            if hasattr(cache, 'databasefile'):
                with contextlib.suppress(sqlite3.Error, Exception):
                    conn = sqlite3.connect(cache.databasefile)
                    conn.close()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot close fast enough")
@pytest.mark.asyncio
async def test_ic_upgrade(bootstrap):
    ''' setup the image cache for testing '''

    config = bootstrap
    dbdir = config.testdir.joinpath('imagecache')
    dbdir.mkdir()

    with sqlite3.connect(dbdir.joinpath("imagecachev1.db"), timeout=30) as connection:

        cursor = connection.cursor()

        v1tabledef = '''
        CREATE TABLE artistsha
        (url TEXT PRIMARY KEY,
         cachekey TEXT DEFAULT NULL,
         artist TEXT NOT NULL,
         imagetype TEXT NOT NULL,
         timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
         );
        '''

        cursor.execute(v1tabledef)

    stopevent = multiprocessing.Event()
    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir, stopevent=stopevent)  #pylint: disable=unused-variable
    assert dbdir.joinpath("imagecachev2.db").exists()
    assert not dbdir.joinpath("imagecachev1.db").exists()
    stopevent.set()
    imagecache.stop_process()


def test_imagecache(get_imagecache):  # pylint: disable=redefined-outer-name
    ''' testing queue filling '''
    config, imagecache = get_imagecache

    imagecache.fill_queue(config=config,
                          identifier='Gary Numan',
                          imagetype='fanart',
                          srclocationlist=TEST_URLS)
    imagecache.fill_queue(config=config,
                          identifier='Gary Numan',
                          imagetype='fanart',
                          srclocationlist=TEST_URLS)
    time.sleep(5)

    page = requests.get(TEST_URLS[2], timeout=10)
    png = nowplaying.utils.image2png(page.content)

    for cachekey in list(imagecache.cache.iterkeys()):
        data1 = imagecache.find_cachekey(cachekey)
        logging.debug('%s %s', cachekey, data1)
        cachedimage = imagecache.cache[cachekey]
        if png == cachedimage:
            logging.debug('Found it at %s', cachekey)


#@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot close fast enough")
@pytest.mark.asyncio
async def test_randomimage(get_imagecache):  # pylint: disable=redefined-outer-name
    ''' get a 'random' image' '''
    config, imagecache = get_imagecache  # pylint: disable=unused-variable

    imagedict = {'srclocation': TEST_URLS[0], 'identifier': 'Gary Numan', 'imagetype': 'fanart'}

    imagecache.image_dl(imagedict)

    data_find = imagecache.find_srclocation(TEST_URLS[0])
    assert data_find['identifier'] == 'garynuman'
    assert data_find['imagetype'] == 'fanart'

    data_random = imagecache.random_fetch(identifier='Gary Numan', imagetype='fanart')
    assert data_random['identifier'] == 'garynuman'
    assert data_random['cachekey']
    assert data_random['srclocation'] == TEST_URLS[0]

    data_findkey = imagecache.find_cachekey(data_random['cachekey'])
    assert data_findkey

    image = imagecache.random_image_fetch(identifier='Gary Numan', imagetype='fanart')
    cachedimage = imagecache.cache[data_random['cachekey']]
    assert image == cachedimage


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot close fast enough")
@pytest.mark.asyncio
async def test_randomfailure(get_imagecache):  # pylint: disable=redefined-outer-name
    ''' test db del 1 '''
    config, imagecache = get_imagecache  # pylint: disable=unused-variable

    imagecache.setup_sql(initialize=True)
    assert imagecache.databasefile.exists()

    imagecache.setup_sql()
    assert imagecache.databasefile.exists()

    imagecache.databasefile.unlink()

    image = imagecache.random_image_fetch(identifier='Gary Numan', imagetype='fanart')
    assert not image

    image = imagecache.random_image_fetch(identifier='Gary Numan', imagetype='fanart')
    assert not image


@pytest.mark.asyncio
@pytest.mark.parametrize("stopevent_state,expected", [
    ("set", True),
    ("unset", False),
    ("none", True),  # safe_stopevent_check treats None as AttributeError -> True
])
async def test_queue_should_stop(imagecache_with_stopevent, stopevent_state, expected):
    ''' test _queue_should_stop with different stopevent states '''
    if stopevent_state == "none":
        imagecache = imagecache_with_stopevent(stopevent=None)
    else:
        stopevent = asyncio.Event()
        if stopevent_state == "set":
            stopevent.set()
        imagecache = imagecache_with_stopevent(stopevent=stopevent)

    assert imagecache._queue_should_stop() is expected  # pylint: disable=protected-access


@pytest.mark.asyncio
@pytest.mark.parametrize("mock_dataset,recently_processed,expected_count,expected_urls", [
    # Empty dataset
    (None, {}, 0, []),
    # Normal data with no filtering
    ([
        {'srclocation': 'url1', 'identifier': 'artist1', 'imagetype': 'fanart'},
        {'srclocation': 'url2', 'identifier': 'artist2', 'imagetype': 'fanart'},
    ], {}, 2, ['url1', 'url2']),
    # Recently processed filtering
    ([
        {'srclocation': 'url1', 'identifier': 'artist1', 'imagetype': 'fanart'},
        {'srclocation': 'url2', 'identifier': 'artist2', 'imagetype': 'fanart'},
    ], {'url1': time.time()}, 1, ['url2']),
    # Stop signal included
    ([
        {'srclocation': 'url1', 'identifier': 'artist1', 'imagetype': 'fanart'},
        {'srclocation': 'STOPWNP', 'identifier': 'STOPWNP', 'imagetype': 'STOPWNP'},
    ], {}, 2, ['url1', 'STOPWNP']),
])
async def test_get_next_queue_batch(imagecache_with_dir, mock_dataset, recently_processed,
                                   expected_count, expected_urls):
    ''' test _get_next_queue_batch with various scenarios '''
    with patch.object(imagecache_with_dir, 'get_next_dlset', return_value=mock_dataset):
        batch = imagecache_with_dir._get_next_queue_batch(recently_processed)  # pylint: disable=protected-access

        if expected_count == 0:
            assert not batch
        else:
            assert len(batch) == expected_count
            actual_urls = [item['srclocation'] for item in batch]
            for url in expected_urls:
                assert url in actual_urls


def test_cleanup_queue_tracking():
    ''' test _cleanup_queue_tracking removes old entries '''
    current_time = time.time()
    recently_processed = {
        'url1': current_time - 100,  # 100 seconds ago - should stay
        'url2': current_time - 200,  # 200 seconds ago - should be removed
        'url3': current_time - 50,   # 50 seconds ago - should stay
    }

    nowplaying.imagecache.ImageCache._cleanup_queue_tracking(recently_processed)  # pylint: disable=protected-access

    assert 'url1' in recently_processed
    assert 'url2' not in recently_processed
    assert 'url3' in recently_processed


def test_cleanup_queue_tracking_empty():
    ''' test _cleanup_queue_tracking with empty dict '''
    recently_processed = {}

    nowplaying.imagecache.ImageCache._cleanup_queue_tracking(recently_processed)  # pylint: disable=protected-access

    assert not recently_processed


@pytest.mark.asyncio
async def test_get_next_dlset_empty_database(bootstrap):
    ''' test get_next_dlset with empty database '''
    config = bootstrap
    dbdir = config.testdir.joinpath('imagecache')
    dbdir.mkdir()

    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir)
    try:
        result = imagecache.get_next_dlset()
        assert result is None or result == []
    finally:
        # Clean up SQLite WAL files to prevent flaky test failures
        if imagecache.databasefile.exists():
            with contextlib.suppress(Exception):
                with sqlite3.connect(imagecache.databasefile, timeout=5) as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.execute("PRAGMA journal_mode=DELETE")


@pytest.mark.asyncio
async def test_database_operations(bootstrap):
    ''' test core database operations '''
    config = bootstrap
    dbdir = config.testdir.joinpath('imagecache')
    dbdir.mkdir()

    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir)

    # Test put_db_srclocation
    imagecache.put_db_srclocation('testartist', 'testurl', 'fanart')

    # Test find_srclocation
    data = imagecache.find_srclocation('testurl')
    assert data is not None
    assert data['identifier'] == 'testartist'
    assert data['imagetype'] == 'fanart'
    assert data['srclocation'] == 'testurl'

    # Test erase_srclocation
    imagecache.erase_srclocation('testurl')
    data = imagecache.find_srclocation('testurl')
    assert data is None


@pytest.mark.asyncio
async def test_put_db_cachekey_with_content(imagecache_with_dir):
    ''' test put_db_cachekey with actual content '''

    # Create some fake image content
    fake_content = b'fake_image_content'

    result = imagecache_with_dir.put_db_cachekey(
        identifier='testartist',
        srclocation='testurl',
        imagetype='fanart',
        content=fake_content
    )

    assert result is True

    # Verify it was stored
    data = imagecache_with_dir.find_srclocation('testurl')
    assert data is not None
    assert data['cachekey'] is not None

    # Verify content is in cache
    assert data['cachekey'] in imagecache_with_dir.cache


@pytest.mark.asyncio
async def test_vacuum_database(imagecache_with_dir):
    ''' test vacuum_database operation '''
    # Add some data
    imagecache_with_dir.put_db_srclocation('testartist', 'testurl', 'fanart')

    # This should not raise an exception
    imagecache_with_dir.vacuum_database()

    # Verify database still works
    data = imagecache_with_dir.find_srclocation('testurl')
    assert data is not None


@pytest.mark.asyncio
async def test_stopwnp_data_integrity(imagecache_with_dir):
    ''' test STOPWNP maintains data integrity during shutdown '''
    # Add some valid data to the database first
    imagecache_with_dir.put_db_srclocation('testartist1', 'testurl1', 'fanart')
    imagecache_with_dir.put_db_srclocation('testartist2', 'testurl2', 'fanart')

    # Verify data exists before shutdown
    data1 = imagecache_with_dir.find_srclocation('testurl1')
    data2 = imagecache_with_dir.find_srclocation('testurl2')
    assert data1 is not None
    assert data2 is not None

    # Call stop_process to inject STOPWNP
    imagecache_with_dir.stop_process()

    # Verify database integrity is maintained after shutdown signal
    data1_after = imagecache_with_dir.find_srclocation('testurl1')
    data2_after = imagecache_with_dir.find_srclocation('testurl2')
    assert data1_after is not None
    assert data2_after is not None
    assert data1_after == data1
    assert data2_after == data2

    # Verify database can still accept operations (not corrupted)
    imagecache_with_dir.put_db_srclocation('testartist3', 'testurl3', 'fanart')
    data3 = imagecache_with_dir.find_srclocation('testurl3')
    assert data3 is not None

    # Verify STOPWNP was properly inserted and can be cleaned up
    stopwnp_data = imagecache_with_dir.find_srclocation('STOPWNP')
    assert stopwnp_data is not None
    assert stopwnp_data['identifier'] == 'STOPWNP'
    assert stopwnp_data['imagetype'] == 'STOPWNP'

    # Cleanup should work without corruption
    imagecache_with_dir.erase_srclocation('STOPWNP')
    stopwnp_after_cleanup = imagecache_with_dir.find_srclocation('STOPWNP')
    assert stopwnp_after_cleanup is None


@pytest.mark.asyncio
async def test_stopwnp_only_in_batch(bootstrap):
    ''' test STOPWNP as the only item in batch during shutdown '''
    config = bootstrap
    dbdir = config.testdir.joinpath('imagecache')
    dbdir.mkdir()

    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir)
    recently_processed = {}

    # Simulate shutdown scenario where only STOPWNP is in the queue
    mock_dataset = [
        {'srclocation': 'STOPWNP', 'identifier': 'STOPWNP', 'imagetype': 'STOPWNP'},
    ]

    with patch.object(imagecache, 'get_next_dlset', return_value=mock_dataset):
        batch = imagecache._get_next_queue_batch(recently_processed)  # pylint: disable=protected-access
        assert len(batch) == 1
        assert batch[0]['srclocation'] == 'STOPWNP'

    # Verify filtering out STOPWNP leaves empty batch (clean shutdown)
    items_to_process = [item for item in batch if item['srclocation'] != 'STOPWNP']
    should_stop = len(items_to_process) != len(batch)

    assert not items_to_process
    assert should_stop


@pytest.mark.asyncio
async def test_stopwnp_with_valid_items(bootstrap):
    ''' test STOPWNP processes valid items before stopping '''
    config = bootstrap
    dbdir = config.testdir.joinpath('imagecache')
    dbdir.mkdir()

    imagecache = nowplaying.imagecache.ImageCache(cachedir=dbdir)
    recently_processed = {}

    # Simulate shutdown with valid work still pending
    mock_dataset = [
        {'srclocation': 'validurl1', 'identifier': 'artist1', 'imagetype': 'fanart'},
        {'srclocation': 'validurl2', 'identifier': 'artist2', 'imagetype': 'fanart'},
        {'srclocation': 'STOPWNP', 'identifier': 'STOPWNP', 'imagetype': 'STOPWNP'},
    ]

    with patch.object(imagecache, 'get_next_dlset', return_value=mock_dataset):
        batch = imagecache._get_next_queue_batch(recently_processed)  # pylint: disable=protected-access
        assert len(batch) == 3

    # Filter out STOPWNP but keep valid items
    items_to_process = [item for item in batch if item['srclocation'] != 'STOPWNP']
    should_stop = len(items_to_process) != len(batch)

    assert len(items_to_process) == 2  # Valid items should be processed
    assert should_stop
    assert items_to_process[0]['srclocation'] == 'validurl1'
    assert items_to_process[1]['srclocation'] == 'validurl2'


@pytest.mark.asyncio
async def test_database_operations_after_stopwnp(imagecache_with_dir):
    ''' test database remains functional after STOPWNP injection '''
    # Normal operations before shutdown
    imagecache_with_dir.put_db_srclocation('artist1', 'url1', 'fanart')
    result1 = imagecache_with_dir.find_srclocation('url1')
    assert result1 is not None

    # Inject shutdown signal
    imagecache_with_dir.stop_process()

    # Database should still be functional for all operations
    imagecache_with_dir.put_db_srclocation('artist2', 'url2', 'fanart')
    result2 = imagecache_with_dir.find_srclocation('url2')
    assert result2 is not None

    # Cache operations should work
    fake_content = b'test_image_data'
    cache_result = imagecache_with_dir.put_db_cachekey(
        identifier='artist3',
        srclocation='url3',
        imagetype='fanart',
        content=fake_content
    )
    assert cache_result is True

    # Cleanup operations should work
    imagecache_with_dir.erase_srclocation('url1')
    result1_after = imagecache_with_dir.find_srclocation('url1')
    assert result1_after is None

    # Database maintenance should work
    imagecache_with_dir.vacuum_database()  # Should not raise exception
