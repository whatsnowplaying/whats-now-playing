#!/usr/bin/env python3
# pylint: disable=invalid-name
''' image cache '''

import asyncio
import concurrent.futures
import pathlib
import random
import sqlite3
import threading
import time
import uuid
import typing as t

import logging
import logging.config
import logging.handlers

import aiosqlite
import diskcache
import requests_cache

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.bootstrap
import nowplaying.utils
import nowplaying.version  # pylint: disable=import-error, no-name-in-module

MAX_FANART_DOWNLOADS = 50


class ImageCache:
    ''' database operations for caches '''

    TABLEDEF = '''
    CREATE TABLE identifiersha
    (srclocation TEXT PRIMARY KEY,
     cachekey TEXT DEFAULT NULL,
     identifier TEXT NOT NULL,
     imagetype TEXT NOT NULL,
     timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
     );
    '''

    def __init__(self, sizelimit=1, initialize=False, cachedir=None, stopevent=None):
        if not cachedir:
            self.cachedir = pathlib.Path(
                QStandardPaths.standardLocations(
                    QStandardPaths.CacheLocation)[0]).joinpath('imagecache')

        else:
            self.cachedir = pathlib.Path(cachedir)

        self.cachedir.resolve().mkdir(parents=True, exist_ok=True)
        self.databasefile = self.cachedir.joinpath('imagecachev2.db')
        if not self.databasefile.exists():
            initialize = True
        self.httpcachefile = self.cachedir.joinpath('http')
        self.cache = diskcache.Cache(directory=self.cachedir.joinpath('diskcache'),
                                     timeout=30,
                                     eviction_policy='least-frequently-used',
                                     size_limit=sizelimit * 1024 * 1024 * 1024)
        if initialize:
            self.setup_sql(initialize=True)
        self.session = None
        self.logpath = None
        self.stopevent: asyncio.Event = stopevent

    def attempt_v1tov2_upgrade(self):
        ''' dbv1 to dbv2 '''
        v1path = self.databasefile.parent.joinpath('imagecachev1.db')
        if not v1path.exists() or self.databasefile.exists():
            return

        logging.info("Upgrading ImageCache DB from v1 to v2")

        v1path.rename(self.databasefile)

        with sqlite3.connect(self.databasefile, timeout=30) as connection:

            cursor = connection.cursor()
            failed = False
            try:
                cursor.execute('ALTER TABLE artistsha RENAME COLUMN url TO srclocation;')
                cursor.execute('ALTER TABLE artistsha RENAME COLUMN artist TO identifier;')
                cursor.execute('ALTER TABLE artistsha RENAME TO identifiersha;')
            except sqlite3.OperationalError as err:
                self._log_sqlite_error(err)
                failed = True

        if failed:
            self.databasefile.unlink()

    def setup_sql(self, initialize=False):
        ''' create the database '''

        if initialize and self.databasefile.exists():
            self.databasefile.unlink()

        self.attempt_v1tov2_upgrade()

        if self.databasefile.exists():
            return

        logging.info('Create imagecache db file %s', self.databasefile)
        self.databasefile.resolve().parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.databasefile, timeout=30) as connection:

            cursor = connection.cursor()

            try:
                cursor.execute(self.TABLEDEF)
            except sqlite3.OperationalError:
                cursor.execute('DROP TABLE identifiersha;')
                cursor.execute(self.TABLEDEF)

        logging.debug('initialize imagecache')
        self.cache.clear()
        self.cache.cull()

    def random_fetch(self, identifier, imagetype):
        ''' fetch a random row from a cache for the identifier '''
        normalidentifier = nowplaying.utils.normalize(identifier, sizecheck=0, nospaces=True)
        data = None
        if not self.databasefile.exists():
            self.setup_sql()
            return None

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute(
                    '''SELECT * FROM identifiersha
 WHERE identifier=?
 AND imagetype=?
 AND cachekey NOT NULL
 ORDER BY random() LIMIT 1;''', (
                        normalidentifier,
                        imagetype,
                    ))
            except sqlite3.OperationalError as error:
                self._log_sqlite_error(error)
                return None

            row = cursor.fetchone()
            if not row:
                return None

            data = {
                'identifier': row['identifier'],
                'cachekey': row['cachekey'],
                'srclocation': row['srclocation'],
            }
            logging.debug('random got %s/%s/%s', imagetype, row['identifier'], row['cachekey'])

        return data

    def random_image_fetch(self, identifier, imagetype):
        ''' fetch a random image from an identifier '''
        image = None
        while data := self.random_fetch(identifier, imagetype):
            try:
                image = self.cache[data['cachekey']]
            except KeyError as error:
                logging.error('random: cannot fetch key %s', error)
                self.erase_cachekey(data['cachekey'])
            if image:
                break
        return image

    def find_srclocation(self, srclocation):
        ''' update metadb '''

        data = None
        if not self.databasefile.exists():
            self.setup_sql()
            return None

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute('''SELECT * FROM identifiersha WHERE srclocation=?''',
                               (srclocation, ))
            except sqlite3.OperationalError as error:
                self._log_sqlite_error(error)
                return None

            if row := cursor.fetchone():
                data = {
                    'identifier': row['identifier'],
                    'cachekey': row['cachekey'],
                    'imagetype': row['imagetype'],
                    'srclocation': row['srclocation'],
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
                cursor.execute('''SELECT * FROM identifiersha WHERE cachekey=?''', (cachekey, ))
            except sqlite3.OperationalError:
                return None

            if row := cursor.fetchone():
                data = {
                    'identifier': row['identifier'],
                    'cachekey': row['cachekey'],
                    'srclocation': row['srclocation'],
                    'imagetype': row['imagetype'],
                    'timestamp': row['timestamp']
                }

        return data

    def fill_queue(self,
                   config=None,
                   identifier: str = None,
                   imagetype: str = None,
                   srclocationlist: t.List[str] = None):
        ''' fill the queue '''

        if not self.databasefile.exists():
            self.setup_sql()

        if 'logo' in imagetype:
            maxart = config.cparser.value('identifierextras/logos', defaultValue=3, type=int)
        elif 'banner' in imagetype:
            maxart = config.cparser.value('identifierextras/banners', defaultValue=3, type=int)
        elif 'thumb' in imagetype:
            maxart = config.cparser.value('identifierextras/thumbnails', defaultValue=3, type=int)
        else:
            maxart = config.cparser.value('identifierextras/fanart', defaultValue=20, type=int)

        logging.debug('Putting %s unfiltered for %s/%s', min(len(srclocationlist), maxart),
                      imagetype, identifier)
        normalidentifier = nowplaying.utils.normalize(identifier, sizecheck=0, nospaces=True)
        for srclocation in random.sample(srclocationlist, min(len(srclocationlist), maxart)):
            self.put_db_srclocation(identifier=normalidentifier,
                                    imagetype=imagetype,
                                    srclocation=srclocation)

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
                cursor.execute('''SELECT * FROM identifiersha WHERE cachekey IS NULL
 AND EXISTS (SELECT * FROM identifiersha
 WHERE imagetype='artistthumbnail' OR imagetype='artistbanner' OR imagetype='artistlogo')
 ORDER BY TIMESTAMP DESC''')
            except sqlite3.OperationalError as error:
                logging.error(error)
                return None

            dataset = cursor.fetchall()

            if dataset:
                logging.debug('banner/logo/thumbs found')
                return dataset

            try:
                cursor.execute('''SELECT * FROM identifiersha WHERE cachekey IS NULL
ORDER BY TIMESTAMP DESC''')
            except sqlite3.OperationalError as error:
                logging.error(error)
                return None

            dataset = cursor.fetchall()

        if dataset:
            logging.debug('artwork found')
        return dataset

    def put_db_cachekey(  # pylint:disable=too-many-arguments
            self,
            identifier: str,
            srclocation: str,
            imagetype: str,
            cachekey: t.Optional[str] = None,
            content: t.Optional[bytes] = None) -> bool:
        ''' update imagedb '''

        if not self.databasefile.exists():
            logging.error('imagecache does not exist yet?')
            return False

        if not identifier or not srclocation or not imagetype:
            logging.error("missing parameters: ident %s srcl: %s it: %s", identifier, srclocation,
                          imagetype)
            return False

        if not cachekey:
            cachekey = str(uuid.uuid4())

        if content:
            image = nowplaying.utils.image2png(content)
            self.cache[cachekey] = image

        normalidentifier = nowplaying.utils.normalize(identifier, sizecheck=0, nospaces=True)
        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()

            sql = '''
INSERT OR REPLACE INTO
 identifiersha(srclocation, identifier, cachekey, imagetype) VALUES(?, ?, ?, ?);
'''
            try:
                cursor.execute(sql, (
                    srclocation,
                    normalidentifier,
                    cachekey,
                    imagetype,
                ))
            except sqlite3.OperationalError as error:
                self._log_sqlite_error(error)
                return False
        return True

    @staticmethod
    def _log_sqlite_error(error):
        """ extract the error bits """
        msg = str(error)
        error_code = error.sqlite_errorcode
        error_name = error.sqlite_name
        logging.error('Error %s [Errno %s]: %s', msg, error_code, error_name)

    def put_db_srclocation(self, identifier, srclocation, imagetype=None):
        ''' update metadb '''

        if not self.databasefile.exists():
            logging.error('imagecache does not exist yet?')
            return

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()

            sql = '''
INSERT INTO
identifiersha(srclocation, identifier, imagetype)
VALUES (?,?,?);
'''
            try:
                cursor.execute(sql, (
                    srclocation,
                    identifier,
                    imagetype,
                ))
            except sqlite3.IntegrityError as error:
                if 'UNIQUE' in str(error):
                    logging.debug('Duplicate srclocation (%s), ignoring', srclocation)
                else:
                    logging.error(error)
            except sqlite3.OperationalError as error:
                logging.error(error)

    def erase_srclocation(self, srclocation):
        ''' update metadb '''

        if not self.databasefile.exists():
            self.setup_sql()
            return

        logging.debug('Erasing %s', srclocation)
        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute('DELETE FROM identifiersha WHERE srclocation=?;', (srclocation, ))
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
        logging.debug('Cache %s  srclocation %s has left cache, requeue it.', cachekey,
                      data['srclocation'])
        self.erase_srclocation(data['srclocation'])
        self.put_db_srclocation(identifier=data['identifier'],
                                imagetype=data['imagetype'],
                                srclocation=data['srclocation'])
        return

    def vacuum_database(self):
        """Vacuum the image cache database to reclaim space from deleted entries.
        
        This should be called on application shutdown to optimize disk usage.
        """
        if not self.databasefile.exists():
            return

        try:
            with sqlite3.connect(self.databasefile, timeout=30) as connection:
                logging.debug("Vacuuming image cache database...")
                connection.execute("VACUUM")
                connection.commit()
                logging.info("Image cache database vacuumed successfully")
        except sqlite3.Error as error:
            logging.error("Database error during vacuum: %s", error)

    def image_dl(self, imagedict):
        ''' fetch an image and store it '''
        nowplaying.bootstrap.setuplogging(logdir=self.logpath, rotate=False)
        threading.current_thread().name = 'ICFollower'
        logging.getLogger('requests_cache').setLevel(logging.CRITICAL + 1)
        logging.getLogger('aiosqlite').setLevel(logging.CRITICAL + 1)
        session = requests_cache.CachedSession(str(self.httpcachefile))

        logging.debug("Downloading %s %s", imagedict['imagetype'], imagedict['srclocation'])
        try:
            headers = {
                'user-agent':
                f'whatsnowplaying/{nowplaying.version.__VERSION__}'  #pylint: disable=no-member
                ' +https://whatsnowplaying.github.io/'
            }
            dlimage = session.get(imagedict['srclocation'], timeout=5, headers=headers)
        except Exception as error:  # pylint: disable=broad-except
            logging.error('image_dl: %s %s', imagedict['srclocation'], error)
            self.erase_srclocation(imagedict['srclocation'])
            return
        if dlimage.status_code == 200:
            if not self.put_db_cachekey(identifier=imagedict['identifier'],
                                        srclocation=imagedict['srclocation'],
                                        imagetype=imagedict['imagetype'],
                                        content=dlimage.content):
                logging.error("db put failed")
        else:
            logging.error('image_dl: status_code %s', dlimage.status_code)
            self.erase_srclocation(imagedict['srclocation'])
            return

        return

    async def verify_cache_timer(self, stopevent):
        ''' run verify_cache periodically '''
        await self.verify_cache()
        counter = 0
        while not stopevent.is_set():
            await asyncio.sleep(2)
            counter += 2
            if counter > 3600:
                await self.verify_cache()
                counter = 0

    async def verify_cache(self):
        ''' verify the image cache '''
        if not self.databasefile.exists():
            return

        cachekeys = {}

        try:
            logging.debug('Starting image cache verification')
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                sql = 'SELECT cachekey, srclocation FROM identifiersha'
                async with connection.execute(sql) as cursor:
                    async for row in cursor:
                        srclocation = row['srclocation']
                        if srclocation == 'STOPWNP':
                            continue
                        cachekeys[row['cachekey']] = srclocation
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("Error: %s", err)

        startsize = len(cachekeys)
        if not startsize:
            logging.debug('Finished image cache verification: no cache!')
            return

        count = startsize
        # making this two separate operations unlocks the DB
        for key, srclocation in cachekeys.items():
            try:
                image = self.cache[key]  # pylint: disable=unused-variable
            except KeyError:
                count -= 1
                logging.debug('%s/%s expired', key, srclocation)
                self.erase_srclocation(srclocation)
        logging.debug('Finished image cache verification: %s/%s images', count, startsize)

    def queue_process(self, logpath, maxworkers=5):
        ''' Process to download stuff in the background to avoid the GIL '''

        threading.current_thread().name = 'ICQueue'
        nowplaying.bootstrap.setuplogging(logdir=logpath, rotate=False)
        self.logpath = logpath
        self.erase_srclocation('STOPWNP')
        endloop = False
        oldset = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=maxworkers) as executor:
            while not endloop and not self.stopevent.is_set():
                if dataset := self.get_next_dlset():
                    # sometimes images are downloaded but not
                    # written to sql yet so don't try to resend
                    # same data
                    newset = []
                    newdataset = []
                    for entry in dataset:
                        newset.append({
                            'srclocation': entry['srclocation'],
                            'time': int(time.time())
                        })
                        if entry['srclocation'] == 'STOPWNP':
                            endloop = True
                            break
                        oldcopy = oldset
                        for oldentry in oldcopy:
                            if int(time.time()) - oldentry['time'] > 180:
                                oldset.remove(oldentry)
                                logging.debug('removing %s from the previously processed queue',
                                              oldentry['srclocation'])
                        if all(u['srclocation'] != entry['srclocation'] for u in oldset):
                            logging.debug('skipping in-progress srclocation %s ',
                                          entry['srclocation'])
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
        self.erase_srclocation('STOPWNP')

    def stop_process(self):
        ''' stop the bg ImageCache process'''
        logging.debug('imagecache stop_process called')
        self.put_db_srclocation('STOPWNP', 'STOPWNP', imagetype='STOPWNP')
        self.cache.close()
        logging.debug('WNP should be set')
