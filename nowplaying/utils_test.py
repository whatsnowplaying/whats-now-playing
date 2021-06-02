#!/usr/bin/env python3
''' pytest for utils.py '''

import os
import sys

sys.path.insert(0, os.path.abspath('..'))

# pylint: disable=wrong-import-position

import nowplaying.bootstrap
import nowplaying.db
import nowplaying.utils

DBFILE = '/tmp/test.db'

nowplaying.bootstrap.setuplogging('/tmp/debug.log')

METADB = nowplaying.db.MetadataDB(databasefile=DBFILE, initialize=True)
METADB.write_to_metadb(metadata=None)
METADATA1 = {'filename': '/tmp/1.mp3'}
METADATA1 = nowplaying.utils.getmoremetadata(metadata=METADATA1)
METADB.write_to_metadb(metadata=METADATA1)
METADATA2 = METADB.read_last_meta()

print(METADATA2['artist'])
