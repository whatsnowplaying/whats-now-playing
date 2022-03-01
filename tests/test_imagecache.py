#!/usr/bin/env python3
''' test metadata DB '''

import tempfile
import time

import requests
import pytest

import nowplaying.imagecache  # pylint: disable=import-error


def test_imagecache(bootstrap):
    ''' create a temporary directory '''
    config = bootstrap  # pylint: disable=unused-variable
    with tempfile.TemporaryDirectory() as newpath:
        mycache = nowplaying.imagecache.ImageCache(cachedir=newpath,
                                                   initialize=True)
        mycache.start_pool()

        mylist = [
            'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5026a93c591b1.jpg',
            'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b765ed348.jpg',
            'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b899f3268.jpg'
        ]
        mycache.fill_queue(name='Gary Numan', urllist=mylist)
        mycache.fill_queue(name='Gary Numan', urllist=mylist)
        time.sleep(10)
        mycache.stop_pool()

        cachedimage = mycache.cache['Gary Numan/1']

        page = requests.get(
            'https://www.theaudiodb.com/images/media/artist/fanart/numan-gary-5098b765ed348.jpg'
        )

        assert page.status_code == cachedimage['status_code']

        with open('/tmp/test1.jpg', 'wb') as fh:
            fh.write(page.content)

        with open('/tmp/test2.png', 'wb') as fh:
            fh.write(cachedimage['image'])
