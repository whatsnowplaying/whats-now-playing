#!/usr/bin/env python3
''' test metadata DB '''

import logging
import multiprocessing
import pathlib
import tempfile
import time

import pytest
import requests

import nowplaying.imagecache  # pylint: disable=import-error
import nowplaying.utils  # pylint: disable=import-error

TEST_URLS = [
    'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5026a93c591b1.jpg',
    'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b765ed348.jpg',
    'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b899f3268.jpg'
]


@pytest.fixture
def get_imagecache(bootstrap):
    ''' setup the image cache for testing '''
    config = bootstrap
    workers = 2
    with tempfile.TemporaryDirectory() as newpath:
        newpathdir = pathlib.Path(newpath)
        logging.debug(newpathdir)
        logpath = newpathdir.joinpath('debug.log')
        stopevent = multiprocessing.Event()
        imagecache = nowplaying.imagecache.ImageCache(cachedir=newpathdir,
                                                      stopevent=stopevent)
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
        pathlib.Path(imagecache.databasefile).unlink()


def test_imagecache(get_imagecache):  # pylint: disable=redefined-outer-name
    ''' create a temporary directory '''
    config, imagecache = get_imagecache

    imagecache.fill_queue(config=config,
                          artist='Gary Numan',
                          imagetype='fanart',
                          urllist=TEST_URLS)
    imagecache.fill_queue(config=config,
                          artist='Gary Numan',
                          imagetype='fanart',
                          urllist=TEST_URLS)
    time.sleep(5)

    page = requests.get(TEST_URLS[2], timeout=10)
    png = nowplaying.utils.image2png(page.content)

    for cachekey in list(imagecache.cache.iterkeys()):
        data1 = imagecache.find_cachekey(cachekey)
        logging.debug('%s %s', cachekey, data1)
        cachedimage = imagecache.cache[cachekey]
        if png == cachedimage:
            logging.debug('Found it at %s', cachekey)
