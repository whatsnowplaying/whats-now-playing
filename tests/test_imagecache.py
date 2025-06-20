#!/usr/bin/env python3
''' test metadata DB '''

#import asyncio
import logging
import multiprocessing
import sqlite3
import sys
import time

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
