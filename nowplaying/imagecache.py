#!/usr/bin/env python3
# pylint: disable=invalid-name
''' image cache '''

import multiprocessing
import pathlib

import logging
import logging.config
import logging.handlers

import diskcache
import requests_cache

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.utils


class ImageCache:
    ''' implement the image cache '''

    def __init__(self,
                 imagetype='artistlogo',
                 cachedir=None,
                 initialize=False,
                 sizelimit=1):
        ''' image cache initialization '''

        if cachedir:
            self.cachedir = pathlib.Path(cachedir)
        else:  # pragma: no cover
            self.cachedir = pathlib.Path(
                QStandardPaths.standardLocations(QStandardPaths.CacheLocation)
                [0]).joinpath(f'{imagetype}-cache')
        self.httpcachefile = pathlib.Path.joinpath(self.cachedir, 'http')
        self.cache = diskcache.Cache(directory=self.cachedir,
                                     eviction_policy='least-frequently-used',
                                     size_limit=sizelimit * 1024 * 1024 * 1024)
        if initialize:
            self.cache.clear()
        self.queue = multiprocessing.Queue()
        self.pool = None
        self.session = requests_cache.CachedSession(self.httpcachefile)
        self.session.cache.responses.is_binary = True  # force it to treat everything as binary to avoid bugs

    def image_fetch(self, key, url=None):
        ''' fetch an image and store it '''
        if key not in self.cache and url:
            logging.debug("Putting %s %s", key, url)
            try:
                dlimage = self.session.get(url, timeout=5)
            except Exception as error:  # pylint: disable=broad-except
                logging.error("Cannot process %s: %s", url, error)
                return None
            image = {
                'status_code': dlimage.status_code,
                'image': nowplaying.utils.image2png(dlimage.content),
            }
            self.cache[key] = image

        if key in self.cache:
            return self.cache[key]

        return None

    def queue_process(self):
        ''' process the inbound MP queue '''
        while True:
            (key, url) = self.queue.get(block=True, timeout=None)
            if key == 'WNPSTOP':
                break
            self.image_fetch(key, url)

    def fill_queue(self, name, urllist):
        ''' fill the queue '''

        for (num, url) in enumerate(urllist):
            logging.debug("Putting %s %s", num, url)
            self.queue.put([f'{name}/{num}', url])

    def start_pool(self):
        ''' start the pool '''
        self.pool = multiprocessing.Pool(
            processes=2,
            initializer=self.queue_process,
        )
        logging.debug('Got a pool')

    def stop_pool(self):
        ''' stop the pool '''
        logging.debug('Shutting down')
        self.queue.put(['WNPSTOP', ''])
        self.pool.close()
        self.session.close()


class ArtistLogoCache(ImageCache):
    ''' artist logo cache '''

    def __init__(self, cachedir=None, initialize=False, sizelimit=1):
        super().__init__(imagetype='artistlogo',
                         cachedir=cachedir,
                         initialize=initialize,
                         sizelimit=sizelimit)


class ArtistThumbCache(ImageCache):
    ''' artist logo cache '''

    def __init__(self, cachedir=None, initialize=False, sizelimit=1):
        super().__init__(imagetype='artistthumb',
                         cachedir=cachedir,
                         initialize=initialize,
                         sizelimit=sizelimit)
