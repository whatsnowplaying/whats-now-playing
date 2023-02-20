#!/usr/bin/env python3
# pylint: disable=invalid-name
''' image cache '''

import concurrent.futures
import pathlib
import random
import sqlite3
import threading
import time
import uuid

import logging
import logging.config
import logging.handlers

import diskcache
import normality
import requests_cache

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.bootstrap
import nowplaying.utils
import nowplaying.version

TABLEDEF = '''
CREATE TABLE artistsha
(url TEXT PRIMARY KEY,
 cachekey TEXT DEFAULT NULL,
 artist TEXT NOT NULL,
 imagetype TEXT NOT NULL,
 timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
 );
'''

MAX_FANART_DOWNLOADS = 50


class ImageCache:
    ''' database operations for caches '''

    def __init__(self,
                 sizelimit=1,
                 initialize=False,
                 cachedir=None,
                 stopevent=None):
        if not cachedir:
            self.cachedir = pathlib.Path(
                QStandardPaths.standardLocations(
                    QStandardPaths.CacheLocation)[0]).joinpath('imagecache')

        else:
            self.cachedir = pathlib.Path(cachedir)

        self.cachedir.resolve().mkdir(parents=True, exist_ok=True)
        self.databasefile = self.cachedir.joinpath('imagecachev1.db')
        if not self.databasefile.exists():
            initialize = True
        self.httpcachefile = self.cachedir.joinpath('http')
        self.cache = diskcache.Cache(
            directory=self.cachedir.joinpath('diskcache'),
            eviction_policy='least-frequently-used',
            size_limit=sizelimit * 1024 * 1024 * 1024)
        if initialize:
            self.setup_sql(initialize=True)
        self.session = None
        self.logpath = None
        self.stopevent = stopevent

    @staticmethod
    def _normalize_artist(artist):
        return normality.normalize(artist).replace(' ', '')

    def setup_sql(self, initialize=False):
        ''' create the database '''

        if initialize and self.databasefile.exists():
            self.databasefile.unlink()

        if self.databasefile.exists():
            return

        logging.info('Create imagecache db file %s', self.databasefile)
        self.databasefile.resolve().parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.databasefile, timeout=30) as connection:

            cursor = connection.cursor()

            try:
                cursor.execute(TABLEDEF)
            except sqlite3.OperationalError:
                cursor.execute('DROP TABLE artistsha;')
                cursor.execute(TABLEDEF)

        logging.debug('initialize imagecache')
        self.cache.clear()
        self.cache.cull()

    def random_fetch(self, artist, imagetype):
        ''' fetch a random row from a cache for the artist '''
        normalartist = self._normalize_artist(artist)
        data = None
        if not self.databasefile.exists():
            self.setup_sql()
            return None

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute(
                    '''SELECT * FROM artistsha
 WHERE artist=?
 AND imagetype=?
 AND cachekey NOT NULL
 ORDER BY random() LIMIT 1;''', (
                        normalartist,
                        imagetype,
                    ))
            except sqlite3.OperationalError as error:
                msg = str(error)
                error_code = error.sqlite_errorcode
                error_name = error.sqlite_name
                logging.error('Error %s [Errno %s]: %s', msg, error_code,
                              error_name)
                return None

            row = cursor.fetchone()
            if not row:
                return None

            data = {
                'artist': row['artist'],
                'cachekey': row['cachekey'],
                'url': row['url'],
            }
            logging.debug('random got %s/%s/%s', imagetype, row['artist'],
                          row['cachekey'])

        return data

    def random_image_fetch(self, artist, imagetype):
        ''' fetch a random image from an artist '''
        image = None
        while data := self.random_fetch(artist, imagetype):
            try:
                image = self.cache[data['cachekey']]
            except KeyError as error:
                logging.error('random: %s', error)
                self.erase_cachekey(data['cachekey'])
            if image:
                break
        return image

    def find_url(self, url):
        ''' update metadb '''

        data = None
        if not self.databasefile.exists():
            self.setup_sql()
            return None

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute('''SELECT * FROM artistsha WHERE url=?''',
                               (url, ))
            except sqlite3.OperationalError as error:
                msg = str(error)
                error_code = error.sqlite_errorcode
                error_name = error.sqlite_name
                logging.error('Error %s [Errno %s]: %s', msg, error_code,
                              error_name)
                return None

            if row := cursor.fetchone():
                data = {
                    'artist': row['artist'],
                    'cachekey': row['cachekey'],
                    'imagetype': row['imagetype'],
                    'url': row['url'],
                    'timestamp': row['timestamp']
                }
        return data

    def find_cachekey(self, cachekey):
        ''' update metadb '''

        data = None
        if not self.databasefile.exists():
            self.setup_sql()
            return None

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute('''SELECT * FROM artistsha WHERE cachekey=?''',
                               (cachekey, ))
            except sqlite3.OperationalError:
                return None

            if row := cursor.fetchone():
                data = {
                    'artist': row['artist'],
                    'cachekey': row['cachekey'],
                    'url': row['url'],
                    'imagetype': row['imagetype'],
                    'timestamp': row['timestamp']
                }

        return data

    def fill_queue(self, config, artist, imagetype, urllist):
        ''' fill the queue '''

        if not self.databasefile.exists():
            self.setup_sql()

        if 'logo' in imagetype:
            maxart = config.cparser.value('artistextras/logos',
                                          defaultValue=3,
                                          type=int)
        elif 'banner' in imagetype:
            maxart = config.cparser.value('artistextras/banners',
                                          defaultValue=3,
                                          type=int)
        elif 'thumb' in imagetype:
            maxart = config.cparser.value('artistextras/thumbnails',
                                          defaultValue=3,
                                          type=int)
        else:
            maxart = config.cparser.value('artistextras/fanart',
                                          defaultValue=20,
                                          type=int)

        logging.debug('Putting %s unfiltered for %s/%s',
                      min(len(urllist), maxart), imagetype, artist)
        normalartist = self._normalize_artist(artist)
        for url in random.sample(urllist, min(len(urllist), maxart)):
            self.put_db_url(artist=normalartist, imagetype=imagetype, url=url)

    def get_next_dlset(self):
        ''' update metadb '''

        def dict_factory(cursor, row):
            d = {}
            for idx, col in enumerate(cursor.description):
                d[col[0]] = row[idx]
            return d

        dataset = None
        if not self.databasefile.exists():
            logging.error('imagecache does not exist yet?')
            return None

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = dict_factory
            cursor = connection.cursor()
            try:
                cursor.execute(
                    '''SELECT * FROM artistsha WHERE cachekey IS NULL
 AND EXISTS (SELECT * FROM artistsha
 WHERE imagetype='artistthumb' OR imagetype='artistbanner' OR imagetype='artistlogo')
 ORDER BY TIMESTAMP DESC''')
            except sqlite3.OperationalError as error:
                logging.error(error)
                return None

            dataset = cursor.fetchall()

            if not dataset:
                try:
                    cursor.execute(
                        '''SELECT * FROM artistsha WHERE cachekey IS NULL
 ORDER BY TIMESTAMP DESC''')
                except sqlite3.OperationalError as error:
                    logging.error(error)
                    return None

                dataset = cursor.fetchall()

        return dataset

    def put_db_cachekey(self, artist, url, imagetype, cachekey=None):
        ''' update metadb '''

        if not self.databasefile.exists():
            logging.error('imagecache does not exist yet?')
            return

        normalartist = self._normalize_artist(artist)
        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()

            sql = '''
INSERT OR REPLACE INTO
 artistsha(url, artist, cachekey, imagetype) VALUES(?, ?, ?, ?);
'''
            try:
                cursor.execute(sql, (
                    url,
                    normalartist,
                    cachekey,
                    imagetype,
                ))
            except sqlite3.OperationalError as error:
                msg = str(error)
                error_code = error.sqlite_errorcode
                error_name = error.sqlite_name
                logging.error('Error %s [Errno %s]: %s', msg, error_code,
                              error_name)
                return

    def put_db_url(self, artist, url, imagetype=None):
        ''' update metadb '''

        if not self.databasefile.exists():
            logging.error('imagecache does not exist yet?')
            return

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()

            sql = '''
INSERT INTO
artistsha(url, artist, imagetype)
VALUES (?,?,?);
'''
            try:
                cursor.execute(sql, (
                    url,
                    artist,
                    imagetype,
                ))
            except sqlite3.IntegrityError as error:
                if 'UNIQUE' in str(error):
                    logging.debug('Duplicate URL, ignoring')
                else:
                    logging.error(error)
            except sqlite3.OperationalError as error:
                logging.error(error)

    def erase_url(self, url):
        ''' update metadb '''

        if not self.databasefile.exists():
            self.setup_sql()
            return

        logging.debug('Erasing %s', url)
        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            logging.debug('Delete %s for reasons', url)
            try:
                cursor.execute('DELETE FROM artistsha WHERE url=?;', (url, ))
            except sqlite3.OperationalError:
                return

    def erase_cachekey(self, cachekey):
        ''' update metadb '''

        if not self.databasefile.exists():
            self.setup_sql()
            return

        data = self.find_cachekey(cachekey)
        if not data:
            return

        # It was retrieved once before so put it back in the queue
        # if it fails in the queue, it will be deleted
        logging.debug('Cache %s  url %s has left cache, requeue it.', cachekey,
                      data['url'])
        self.erase_url(data['url'])
        self.put_db_url(artist=data['artist'],
                        imagetype=data['imagetype'],
                        url=data['url'])
        return

    def image_dl(self, imagedict):
        ''' fetch an image and store it '''
        nowplaying.bootstrap.setuplogging(logdir=self.logpath, rotate=False)
        threading.current_thread().name = 'ICFollower'
        logging.getLogger('requests_cache').setLevel(logging.CRITICAL + 1)
        logging.getLogger('aiosqlite').setLevel(logging.CRITICAL + 1)
        version = nowplaying.version.get_versions()['version']
        session = requests_cache.CachedSession(self.httpcachefile)
        cachekey = str(uuid.uuid4())

        logging.debug("Downloading %s %s", cachekey, imagedict['url'])
        try:
            headers = {
                'user-agent':
                f'whatsnowplaying/{version}'
                ' +https://whatsnowplaying.github.io/'
            }
            dlimage = session.get(imagedict['url'], timeout=5, headers=headers)
        except Exception as error:  # pylint: disable=broad-except
            logging.debug('image_dl: %s %s', imagedict['url'], error)
            self.erase_url(imagedict['url'])
            return
        if dlimage.status_code == 200:
            image = nowplaying.utils.image2png(dlimage.content)
            self.cache[cachekey] = image
            self.put_db_cachekey(artist=imagedict['artist'],
                                 url=imagedict['url'],
                                 imagetype=imagedict['imagetype'],
                                 cachekey=cachekey)
        else:
            logging.debug('image_dl: status_code %s', dlimage.status_code)
            self.erase_url(imagedict['url'])
            return

        return

    def queue_process(self, logpath, maxworkers=5):
        ''' Process to download stuff in the background to avoid the GIL '''

        threading.current_thread().name = 'ICQueue'
        nowplaying.bootstrap.setuplogging(logdir=logpath, rotate=False)
        self.logpath = logpath
        self.erase_url('STOPWNP')
        endloop = False
        oldset = []
        with concurrent.futures.ProcessPoolExecutor(
                max_workers=maxworkers) as executor:
            while not endloop and not self.stopevent.is_set():
                if dataset := self.get_next_dlset():
                    # sometimes images are downloaded but not
                    # written to sql yet so don't try to resend
                    # same data
                    newset = []
                    newdataset = []
                    for entry in dataset:
                        newset.append({
                            'url': entry['url'],
                            'time': int(time.time())
                        })
                        if entry['url'] == 'STOPWNP':
                            endloop = True
                            break
                        oldcopy = oldset
                        for oldentry in oldcopy:
                            if int(time.time()) - oldentry['time'] > 180:
                                oldset.remove(oldentry)
                                logging.debug(
                                    'removing %s from the previously processed queue',
                                    oldentry['url'])
                        if all(u['url'] != entry['url'] for u in oldset):
                            logging.debug('skipping in-progress url %s ',
                                          entry['url'])
                        else:
                            newdataset.append(entry)
                    oldset = newset

                    if endloop:
                        break

                    executor.map(self.image_dl, newdataset)
                time.sleep(2)
                if not self.databasefile.exists():
                    self.setup_sql()

        logging.debug('stopping download processes')
        self.erase_url('STOPWNP')

    def stop_process(self):
        ''' stop the bg ImageCache process'''
        logging.debug('imagecache stop_process called')
        self.put_db_url('STOPWNP', 'STOPWNP', imagetype='STOPWNP')
        self.cache.close()
        logging.debug('WNP should be set')
