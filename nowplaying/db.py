#!/usr/bin/env python3
''' routines to read/write the metadb '''

import copy
import logging
import os
import pathlib
import sys
import sqlite3
import time

from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

SPLITSTR = '@@SPLITHERE@@'


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
        'acoustidid',
        'album',
        'albumartist',
        'artist',
        'artistwebsites',
        'artistlongbio',
        'artistshortbio',
        'bitrate',
        'bpm',
        'comments',
        'composer',
        'coverurl',
        'date',
        'deck',
        'disc',
        'disc_total',
        'discsubtitle',
        'filename',
        'genre',
        'hostfqdn',
        'hostip',
        'hostname',
        'httpport',
        'isrc',
        'key',
        'label',
        'lang',
        'length',
        'musicbrainzalbumid',
        'musicbrainzartistid',
        'musicbrainzrecordingid',
        'title',
        'track',
        'track_total',
    ]

    LISTFIELDS = [
        'artistwebsites',
        'isrc',
        'musicbrainzartistid',
    ]

    # NOTE: artistfanartraw is never actually stored in this DB
    # but putting it here triggers side-effects to force it to be
    # treated as binary
    METADATABLOBLIST = [
        'artistbannerraw', 'artistfanartraw', 'artistlogoraw',
        'artistthumbraw', 'coverimageraw'
    ]

    def __init__(self, databasefile=None, initialize=False):

        if databasefile:
            self.databasefile = pathlib.Path(databasefile)
        else:  # pragma: no cover
            self.databasefile = pathlib.Path(
                QStandardPaths.standardLocations(
                    QStandardPaths.CacheLocation)[0]).joinpath(
                        'metadb', 'npsql.db')

        if not self.databasefile.exists() or initialize:
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
                for key in MetadataDB.METADATALIST +
                MetadataDB.METADATABLOBLIST if key in mydict
            }

        logging.debug('Called write_to_metadb')
        if (not metadata or not MetadataDB.METADATALIST
                or 'title' not in metadata or 'artist' not in metadata):
            logging.debug('metadata is either empty or too incomplete')
            return

        if not self.databasefile.exists():
            self.setupsql()

        with sqlite3.connect(self.databasefile) as connection:
            # do not want to modify the original dictionary
            # otherwise Bad Things(tm) will happen
            mdcopy = copy.deepcopy(metadata)
            mdcopy['artistfanartraw'] = None

            # toss any keys we do not care about
            mdcopy = filterkeys(mdcopy)

            cursor = connection.cursor()

            logging.debug('Adding record with %s/%s', mdcopy['artist'],
                          mdcopy['title'])

            for key in MetadataDB.METADATABLOBLIST:
                if key not in mdcopy:
                    mdcopy[key] = None

            for data in mdcopy:
                if isinstance(mdcopy[data], list):
                    mdcopy[data] = SPLITSTR.join(mdcopy[data])
                if isinstance(mdcopy[data], str) and len(mdcopy[data]) == 0:
                    mdcopy[data] = None

            sql = 'INSERT INTO currentmeta ('
            sql += ', '.join(mdcopy.keys()) + ') VALUES ('
            sql += '?,' * (len(mdcopy.keys()) - 1) + '?)'

            datatuple = tuple(list(mdcopy.values()))
            cursor.execute(sql, datatuple)

    def make_lasttracklist(self):
        ''' create a reversed of the tracks played '''

        if not self.databasefile.exists():
            logging.error('MetadataDB does not exist yet?')
            return None

        with sqlite3.connect(self.databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute(
                    '''SELECT artist, title FROM currentmeta ORDER BY id DESC'''
                )
            except sqlite3.OperationalError:
                return None

            records = cursor.fetchall()

        lasttrack = []
        if records:
            lasttrack.extend({
                'artist': row['artist'],
                'title': row['title']
            } for row in records)

        return lasttrack

    def read_last_meta(self):
        ''' update metadb '''

        if not self.databasefile.exists():
            logging.error('MetadataDB does not exist yet?')
            return None

        with sqlite3.connect(self.databasefile) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute(
                    '''SELECT * FROM currentmeta ORDER BY id DESC LIMIT 1''')
            except sqlite3.OperationalError:
                return None

            row = cursor.fetchone()
            if not row:
                return None

        metadata = {data: row[data] for data in MetadataDB.METADATALIST}
        for key in MetadataDB.METADATABLOBLIST:
            metadata[key] = row[key]
            if not metadata[key]:
                del metadata[key]

        for key in MetadataDB.LISTFIELDS:
            metadata[key] = row[key]
            if metadata[key]:
                metadata[key] = metadata[key].split(SPLITSTR)

        metadata['dbid'] = row['id']
        metadata['lasttrack'] = self.make_lasttracklist()
        return metadata

    def setupsql(self):
        ''' setup the default database '''

        if not self.databasefile:
            logging.error('No dbfile')
            sys.exit(1)

        self.databasefile.parent.mkdir(parents=True, exist_ok=True)
        if self.databasefile.exists():
            logging.info('Clearing cache file %s', self.databasefile)
            os.unlink(self.databasefile)

        with sqlite3.connect(self.databasefile) as connection:
            cursor = connection.cursor()

            sql = 'CREATE TABLE currentmeta (id INTEGER PRIMARY KEY AUTOINCREMENT, '
            sql += ' TEXT, '.join(MetadataDB.METADATALIST) + ' TEXT, '
            sql += ' BLOB, '.join(MetadataDB.METADATABLOBLIST) + ' BLOB)'

            cursor.execute(sql)
            logging.debug('Cache db file created')
