#!/usr/bin/env python3
''' routines to read/write the metadb '''

import copy
import logging
import os
import pathlib
import sys
import threading
import urllib
import sqlite3

from PySide2.QtCore import QStandardPaths  # pylint: disable=no-name-in-module


class MetadataDB:
    """ Metadata DB module"""

    METADATALIST = [
        'album',
        'albumartist',
        'artist',
        'bitrate',
        'bpm',
        'composer',
        'coverimagetype',
        'coverurl',
        'coverurldeck',
        'deck',
        'disc',
        'disc_total',
        'fetchedartist',
        'fetchedtitle',
        'filename',
        'genre',
        'key',
        'lang',
        'publisher',
        'title',
        'track',
        'track_total',
        'year',
    ]

    LOCK = threading.RLock()

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

    def write_to_metadb(self, metadata=None):
        ''' update metadb '''

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
        coverimageraw = None

        connection = sqlite3.connect(self.databasefile)
        cursor = connection.cursor()

        logging.debug('Adding record with %s/%s', mdcopy['artist'],
                      mdcopy['title'])

        if 'coverimageraw' in mdcopy:
            coverimageraw = bytearray(mdcopy['coverimageraw'])
            del mdcopy['coverimageraw']

        for data in self.databasefile:
            if data in metadata:
                if isinstance(mdcopy[data], str):
                    mdcopy[data] = urllib.parse.quote(mdcopy[data])
                else:
                    mdcopy[data] = str(mdcopy[data])

        sql = 'INSERT INTO currentmeta ('
        sql += ', '.join(mdcopy.keys()) + ', coverimageraw) VALUES ('
        sql += '?,' * len(mdcopy.keys()) + '?)'

        cursor.execute(sql, list(mdcopy.values()) + [coverimageraw])
        connection.commit()
        connection.close()
        MetadataDB.LOCK.release()

    def read_last_meta(self):
        ''' update metadb '''
        metadata = {}

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

        for data in MetadataDB.METADATALIST:
            value = row[data]
            if isinstance(value, str):
                metadata[data] = urllib.parse.unquote(value)
            else:
                metadata[data] = value

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
