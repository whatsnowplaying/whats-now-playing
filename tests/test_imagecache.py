#!/usr/bin/env python3
''' test metadata DB '''

import logging
import pathlib
import tempfile
import time

import requests

import nowplaying.imagecache  # pylint: disable=import-error
import nowplaying.utils  # pylint: disable=import-error

TEST_URLS = [
    'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5026a93c591b1.jpg',
    'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b765ed348.jpg',
    'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b899f3268.jpg'
]


def test_imagecache(bootstrap):
    ''' create a temporary directory '''
    config = bootstrap  # pylint: disable=unused-variable
    with tempfile.TemporaryDirectory() as newpath:
        databasefile = pathlib.Path(newpath).joinpath('dbfile')
        mycache = nowplaying.imagecache.ArtistFanartCache(
            cachedir=newpath, initialize=True, databasefile=databasefile)
        mycache.start_pool()

        mycache.fill_queue(name='Gary Numan', urllist=TEST_URLS)
        mycache.fill_queue(name='Gary Numan', urllist=TEST_URLS)
        time.sleep(5)
        mycache.stop_pool()

        page = requests.get(TEST_URLS[2])
        png = nowplaying.utils.image2png(page.content)

        for diskcache in list(mycache.cache.iterkeys()):
            (name, cachekey) = diskcache.split('/')
            data1 = mycache.find_artist_cachekey(name, cachekey)
            logging.debug('%s %s %s %s', name, cachekey, data1['url'],
                          TEST_URLS[int(cachekey)])
            cachedimage = mycache.cache[diskcache]
            if png == cachedimage:
                logging.debug('Found it at %s', cachekey)
