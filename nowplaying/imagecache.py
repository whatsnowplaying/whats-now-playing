#!/usr/bin/env python3
# pylint: disable=invalid-name
''' image cache '''

import multiprocessing
import os
import pathlib
import random
import sqlite3
import time

import logging
import logging.config
import logging.handlers

import diskcache
import requests_cache

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.utils
import nowplaying.version

TABLEDEF = ('CREATE TABLE artistsha '
            '(url TEXT PRIMARY KEY, '
            'cachekey TEXT NOT NULL, '
            'artist TEXT NOT NULL, '
            'strikes INT DEFAULT 0); ')


class ImageCache:  # pylint: disable=too-many-instance-attributes
    ''' implement the image cache '''

    # This will lock all DBs at once.
    # less than ideal, but I'm not really sure how to do
    # this is in a sane method
    LOCK = {}

    # pylint: disable=too-many-arguments
    def __init__(self,
                 imagetype=None,
                 cachedir=None,
                 initialize=False,
                 sizelimit=1,
                 poolsize=1,
                 databasefile=None):
        ''' image cache initialization '''

        assert imagetype
        self.imagetype = imagetype
        ImageCache.LOCK[self.imagetype] = multiprocessing.RLock()
        if cachedir:
            self.cachedir = pathlib.Path(cachedir)
        else:  # pragma: no cover
            self.cachedir = pathlib.Path(
                QStandardPaths.standardLocations(QStandardPaths.CacheLocation)
                [0]).joinpath(f'{imagetype}-cache')
        logging.debug('Setting cachedir to %s', self.cachedir)
        if databasefile:
            self.databasefile = pathlib.Path(databasefile)
        else:  # pragma: no cover
            self.databasefile = pathlib.Path(
                QStandardPaths.standardLocations(QStandardPaths.CacheLocation)
                [0]).joinpath(f'{imagetype}.db')
        self.queue = multiprocessing.Queue()
        self.pool = None
        self.poolsize = poolsize
        self.httpcachefile = pathlib.Path.joinpath(self.cachedir, 'http')
        self.cache = diskcache.Cache(directory=self.cachedir,
                                     eviction_policy='least-frequently-used',
                                     size_limit=sizelimit * 1024 * 1024 * 1024)
        if initialize:
            self.cache.clear()
        self.session = requests_cache.CachedSession(self.httpcachefile)
        # force it to treat everything as binary to avoid bugs
        self.session.cache.responses.is_binary = True
        self.version = nowplaying.version.get_versions()['version']

    def image_fetch(self, cachekey, url=None):
        ''' fetch an image and store it '''
        if cachekey not in self.cache and url:
            logging.debug("Downloading %s %s", cachekey, url)
            try:
                headers = {
                    'user-agent':
                    f'whatsnowplaying/{self.version}'
                    ' +https://whatsnowplaying.github.io/'
                }
                dlimage = self.session.get(url, timeout=5, headers=headers)
            except Exception as error:  # pylint: disable=broad-except
                logging.error("Cannot process %s: %s", url, error)
                return None
            if dlimage.status_code == 200:
                image = nowplaying.utils.image2png(dlimage.content)
                self.cache[cachekey] = image
                logging.debug('Placed %s %s %s', self.imagetype, cachekey, url)
            else:
                return None

        if self.cache.get(cachekey):
            return self.cache[cachekey]

        return None

    def image_list_fetch(self, artist, urllist):
        ''' fetch all the images from a list '''
        for (num, url) in enumerate(urllist):
            self.image_fetch(f'{artist}/{num}', url)

    def random_fetch(self, artist):
        ''' fetch a random row from a cache for the artist '''
        data = None
        if not self.databasefile.exists():
            logging.error('%s cache does not exist yet?', self.imagetype)
            return None

        with ImageCache.LOCK[self.imagetype]:
            connection = sqlite3.connect(self.databasefile)
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute(
                    '''SELECT * FROM artistsha WHERE artist=? ORDER BY random() LIMIT 1;''',
                    (artist, ))
            except sqlite3.OperationalError:
                return None

            row = cursor.fetchone()
            if not row:
                return None

            data = {
                'artist': row['artist'],
                'cachekey': row['cachekey'],
                'url': row['url'],
                'strikes': row['strikes']
            }
            logging.debug('%s random got %s %s', self.imagetype, row['artist'],
                          row['cachekey'])
            connection.commit()
            connection.close()
        return data

    def random_image_fetch(self, artist):
        ''' fetch a random image from an artist '''
        image = None
        while data := self.random_fetch(artist):
            if data['cachekey'] == '0':
                time.sleep(.5)
            try:
                image = self.cache[f'{artist}/' + data['cachekey']]
            except KeyError:
                self.erase_key(artist, data['cachekey'])
            if image:
                self.reset_strikes(artist, data['cachekey'])
                break
        return image

    def queue_process(self):
        ''' process the inbound MP queue '''
        logging.debug('Launched queue %s process %s', self.imagetype,
                      os.getpid())
        while True:
            (name, cachekey, url) = self.queue.get(block=True, timeout=None)
            if not self.image_fetch(f'{name}/{cachekey}', url):
                self.erase_url(url)
                logging.debug('Queue %s %s: failed', self.imagetype,
                              os.getpid())
            else:
                self.put_db_url(name, cachekey, url)
            time.sleep(1)

    def fill_queue(self, name, urllist):
        ''' fill the queue '''

        cachekey = -1
        for url in random.sample(urllist, min(len(urllist), 20)):
            logging.debug('Checking %s', url)
            checkdata = self.find_url(url)
            logging.debug('got an answer')
            if checkdata and checkdata['artist'] == name:
                continue
            while True:
                cachekey += 1
                try:
                    self.cache[f'{name}/{cachekey}']
                except KeyError:
                    break
                if not self.find_artist_cachekey(name, cachekey):
                    break
            logging.debug("Putting %s %s", cachekey, url)
            self.put_db_url(name, cachekey, url)
            self.queue.put([name, cachekey, url])

    def start_pool(self):
        ''' start the pool '''
        self._setup_sql()
        self.pool = multiprocessing.Pool(  # pylint: disable=consider-using-with
            processes=self.poolsize,
            initializer=self.queue_process,
        )
        logging.debug('Got a pool')

    def stop_pool(self):
        ''' stop the pool '''
        logging.debug('closing %s queue', self.imagetype)
        self.queue.close()
        logging.debug('closing the %s pool', self.imagetype)
        self.pool.close()
        logging.debug('closing %s session', self.imagetype)
        self.session.close()
        logging.debug('session %s closed', self.imagetype)

    def _setup_sql(self):
        with ImageCache.LOCK[self.imagetype]:
            parent = self.databasefile.joinpath('..').resolve()
            parent.mkdir(parents=True, exist_ok=True)
            if self.databasefile.exists():
                return

            logging.info('Create %s cache db file %s', self.imagetype,
                         self.databasefile)
            connection = sqlite3.connect(self.databasefile)
            cursor = connection.cursor()

            try:
                cursor.execute(TABLEDEF)
            except sqlite3.OperationalError:
                cursor.execute('DROP TABLE artistsha;')
                cursor.execute(TABLEDEF)

            connection.commit()
            connection.close()
            logging.debug('Cache %s cache db file created', self.imagetype)

    def find_url(self, url):
        ''' update metadb '''

        data = None
        if not self.databasefile.exists():
            logging.error('%s cache does not exist yet?', self.imagetype)
            return None

        with ImageCache.LOCK[self.imagetype]:
            connection = sqlite3.connect(self.databasefile)
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute('''SELECT * FROM artistsha WHERE url=?''',
                               (url, ))
            except sqlite3.OperationalError:
                return None

            row = cursor.fetchone()
            if not row:
                return None

            data = {
                'artist': row['artist'],
                'cachekey': row['cachekey'],
                'url': row['url']
            }
            logging.debug('Found %s = %s in cache', url, data)
            connection.commit()
            connection.close()
        return data

    def find_artist_cachekey(self, artist, cachekey):
        ''' update metadb '''

        data = None
        if not self.databasefile.exists():
            logging.error('%s cache does not exist yet?', self.imagetype)
            return None

        with ImageCache.LOCK[self.imagetype]:
            connection = sqlite3.connect(self.databasefile)
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute(
                    '''SELECT * FROM artistsha WHERE artist=? AND cachekey=?''',
                    (
                        artist,
                        cachekey,
                    ))
            except sqlite3.OperationalError:
                return None

            row = cursor.fetchone()
            if not row:
                return None

            data = {
                'artist': row['artist'],
                'cachekey': row['cachekey'],
                'url': row['url'],
                'strikes': row['strikes']
            }
            connection.commit()
            connection.close()
        return data

    def put_db_url(self, name, cachekey, url):
        ''' update metadb '''

        if not self.databasefile.exists():
            logging.error('%s cache does not exist yet?', self.imagetype)
            return

        with ImageCache.LOCK[self.imagetype]:
            connection = sqlite3.connect(self.databasefile)
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()

            sql = ('INSERT OR REPLACE INTO '
                   'artistsha(url, artist, cachekey, strikes) '
                   'VALUES (?,?,?,0);')
            try:
                cursor.execute(sql, (
                    url,
                    name,
                    cachekey,
                ))
            except sqlite3.OperationalError:
                return

            connection.commit()
            connection.close()

    def erase_url(self, url):
        ''' update metadb '''

        if not self.databasefile.exists():
            logging.error('%s cache does not exist yet?', self.imagetype)
            return

        with ImageCache.LOCK[self.imagetype]:
            connection = sqlite3.connect(self.databasefile)
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            logging.debug('Delete %s for reasons', url)
            try:
                cursor.execute('DELETE FROM artistsha WHERE url=?;', (url, ))
            except sqlite3.OperationalError:
                return

            connection.commit()
            connection.close()

    def erase_key(self, artist, cachekey):
        ''' update metadb '''

        if not self.databasefile.exists():
            logging.error('%s cache does not exist yet?', self.imagetype)
            return

        with ImageCache.LOCK[self.imagetype]:

            logging.debug('Want to delete %s %s, %s', self.imagetype, artist,
                          cachekey)
            data = self.find_artist_cachekey(artist, cachekey)
            logging.debug('In %s erase_key, data = %s', self.imagetype, data)
            if not data:
                logging.debug('Already deleted/never placed')
                return

            if data['strikes'] > 10:
                self.erase_url(data['url'])
            else:
                logging.debug('Update %s %s/%s strikes, was %s',
                              self.imagetype, artist, cachekey,
                              data['strikes'])

                connection = sqlite3.connect(self.databasefile)
                connection.row_factory = sqlite3.Row
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        'UPDATE artistsha SET strikes=? WHERE artist=? AND cachekey=?;',
                        (
                            data['strikes'] + 1,
                            artist,
                            cachekey,
                        ))
                except sqlite3.OperationalError:
                    return

                connection.commit()
                connection.close()

    def reset_strikes(self, artist, cachekey):
        ''' update metadb '''

        if not self.databasefile.exists():
            logging.error('%s cache does not exist yet?', self.imagetype)
            return

        with ImageCache.LOCK[self.imagetype]:

            data = self.find_artist_cachekey(artist, cachekey)
            if not data:
                logging.debug('Already deleted')
                return

            if data.get('strikes') > 0:
                logging.debug('Resetting strikes on %s %s/%s', self.imagetype,
                              artist, cachekey)
                connection = sqlite3.connect(self.databasefile)
                connection.row_factory = sqlite3.Row
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        'UPDATE artistsha SET strikes=? WHERE artist=? AND cachekey=?;',
                        (
                            0,
                            artist,
                            cachekey,
                        ))
                except sqlite3.OperationalError:
                    return

                connection.commit()
                connection.close()


class ArtistBannerCache(ImageCache):
    ''' artist logo cache '''

    # pylint: disable=too-many-arguments
    def __init__(self,
                 cachedir=None,
                 initialize=False,
                 sizelimit=1,
                 poolsize=1,
                 databasefile=None):
        super().__init__(imagetype='artistbanner',
                         cachedir=cachedir,
                         initialize=initialize,
                         sizelimit=sizelimit,
                         poolsize=poolsize,
                         databasefile=databasefile)


class ArtistLogoCache(ImageCache):
    ''' artist logo cache '''

    # pylint: disable=too-many-arguments
    def __init__(self,
                 cachedir=None,
                 initialize=False,
                 sizelimit=1,
                 poolsize=1,
                 databasefile=None):
        super().__init__(imagetype='artistlogo',
                         cachedir=cachedir,
                         initialize=initialize,
                         sizelimit=sizelimit,
                         poolsize=poolsize,
                         databasefile=databasefile)


class ArtistThumbCache(ImageCache):
    ''' artist logo cache '''

    # pylint: disable=too-many-arguments
    def __init__(self,
                 cachedir=None,
                 initialize=False,
                 sizelimit=1,
                 poolsize=1,
                 databasefile=None):
        super().__init__(imagetype='artistthumb',
                         cachedir=cachedir,
                         initialize=initialize,
                         sizelimit=sizelimit,
                         poolsize=poolsize,
                         databasefile=databasefile)


class ArtistFanartCache(ImageCache):
    ''' artist logo cache '''

    # pylint: disable=too-many-arguments
    def __init__(self,
                 cachedir=None,
                 initialize=False,
                 sizelimit=1,
                 poolsize=2,
                 databasefile=None):
        super().__init__(imagetype='artistfanart',
                         cachedir=cachedir,
                         initialize=initialize,
                         sizelimit=sizelimit,
                         poolsize=poolsize,
                         databasefile=databasefile)
