#!/usr/bin/env python3
''' routines to read/write the metadb '''

import copy
import logging
import os
import pathlib
import sys
import multiprocessing
import sqlite3
import time

from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

from PySide2.QtCore import QStandardPaths  # pylint: disable=no-name-in-module


class DBWatcher:
    ''' utility to watch for database changes '''
    def __init__(self, databasefile):
        self.observer = None
        self.event_handler = None
        self.updatetime = time.time()
        self.databasefile = databasefile

    def start(self, customhandler=None):
        ''' fire up the watcher '''
        logging.debug('Asked for a DB watcher')
        directory = os.path.dirname(self.databasefile)
        filename = os.path.basename(self.databasefile)
        logging.info('Watching for changes on %s', self.databasefile)
        self.event_handler = PatternMatchingEventHandler(
            patterns=[filename],
            ignore_patterns=['.DS_Store'],
            ignore_directories=True,
            case_sensitive=False)
        if not customhandler:
            self.event_handler.on_modified = self.update_time
            self.event_handler.on_created = self.update_time
        else:
            self.event_handler.on_modified = customhandler
            self.event_handler.on_created = customhandler
        self.observer = Observer()
        self.observer.schedule(self.event_handler, directory, recursive=False)
        self.observer.start()

    def update_time(self, event):  # pylint: disable=unused-argument
        ''' just need to update the time '''
        self.updatetime = time.time()

    def stop(self):
        ''' stop the watcher '''
        logging.debug('watcher asked to stop')
        if self.observer:
            logging.debug('calling stop')
            self.observer.stop()
            logging.debug('calling join')
            self.observer.join()
            self.observer = None

    def __del__(self):
        self.stop()


class MetadataDB:
    """ Metadata DB module"""

    METADATALIST = [
        'album',
        'albumartist',
        'artist',
        'bitrate',
        'bpm',
        'composer',
        'coverurl',
        'date',
        'deck',
        'disc',
        'disc_total',
        'filename',
        'genre',
        'key',
        'label',
        'lang',
        'length',
        'title',
        'track',
        'track_total',
    ]

    LOCK = multiprocessing.RLock()

    def __init__(self, databasefile=None, initialize=False):

        if databasefile:
            self.databasefile = databasefile
        else:
            self.databasefile = os.path.join(
                QStandardPaths.standardLocations(
                    QStandardPaths.CacheLocation)[0], 'npsql.db')

        if not os.path.exists(self.databasefile) or initialize:
            logging.debug('Setting up a new DB')
            self.setupsql()

    def watcher(self):
        ''' get access to a watch on the database file '''
        return DBWatcher(self.databasefile)

    def write_to_metadb(self, metadata=None):
        ''' update metadb '''
        def filterkeys(mydict):
            return {
                key: mydict[key]
                for key in MetadataDB.METADATALIST + ['coverimageraw']
                if key in mydict
            }

        logging.debug('Called write_to_metadb')
        if not metadata or not MetadataDB.METADATALIST:
            return

        if not os.path.exists(self.databasefile):
            self.setupsql()

        logging.debug('Waiting for lock')
        MetadataDB.LOCK.acquire()

        # do not want to modify the original dictionary
        # otherwise Bad Things(tm) will happen
        mdcopy = copy.deepcopy(metadata)

        # toss any keys we do not care about
        mdcopy = filterkeys(mdcopy)

        connection = sqlite3.connect(self.databasefile)
        cursor = connection.cursor()

        logging.debug('Adding record with %s/%s', mdcopy['artist'],
                      mdcopy['title'])

        if 'coverimageraw' not in mdcopy:
            mdcopy['coverimageraw'] = None

        for data in mdcopy:
            if isinstance(mdcopy[data], str) and len(mdcopy[data]) == 0:
                mdcopy[data] = None

        sql = 'INSERT INTO currentmeta ('
        sql += ', '.join(mdcopy.keys()) + ') VALUES ('
        sql += '?,' * (len(mdcopy.keys()) - 1) + '?)'

        cursor.execute(sql, tuple(list(mdcopy.values())))
        connection.commit()
        connection.close()
        logging.debug('releasing lock')
        MetadataDB.LOCK.release()

    def read_last_meta(self):
        ''' update metadb '''

        if not os.path.exists(self.databasefile):
            logging.error('MetadataDB does not exist yet?')
            return None

        MetadataDB.LOCK.acquire()
        connection = sqlite3.connect(self.databasefile)
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()
        try:
            cursor.execute(
                '''SELECT * FROM currentmeta ORDER BY id DESC LIMIT 1''')
        except sqlite3.OperationalError:
            MetadataDB.LOCK.release()
            return None

        row = cursor.fetchone()
        if not row:
            MetadataDB.LOCK.release()
            return None

        metadata = {data: row[data] for data in MetadataDB.METADATALIST}

        metadata['coverimageraw'] = row['coverimageraw']
        if not metadata['coverimageraw']:
            del metadata['coverimageraw']

        metadata['dbid'] = row['id']
        connection.commit()
        connection.close()
        MetadataDB.LOCK.release()
        return metadata

    def setupsql(self):
        ''' setup the default database '''

        if not self.databasefile:
            logging.error('No dbfile')
            sys.exit(1)

        MetadataDB.LOCK.acquire()

        pathlib.Path(os.path.dirname(self.databasefile)).mkdir(parents=True,
                                                               exist_ok=True)
        if os.path.exists(self.databasefile):
            logging.info('Clearing cache file %s', self.databasefile)
            os.unlink(self.databasefile)

        logging.info('Create cache db file %s', self.databasefile)
        connection = sqlite3.connect(self.databasefile)
        cursor = connection.cursor()

        sql = 'CREATE TABLE currentmeta ('
        sql += 'id INTEGER PRIMARY KEY AUTOINCREMENT, '
        sql += ' TEXT, '.join(
            MetadataDB.METADATALIST) + ' TEXT,  coverimageraw BLOB'
        sql += ')'

        cursor.execute(sql)
        connection.commit()
        connection.close()
        logging.debug('Cache db file created')
        MetadataDB.LOCK.release()
