#!/usr/bin/env python3
''' test metadata DB '''

import os
import tempfile

import pytest

import nowplaying.db  # pylint: disable=import-error
import nowplaying.utils  # pylint: disable=import-error


@pytest.fixture
def getmetadb(bootstrap):
    ''' create a temporary directory '''
    config = bootstrap  # pylint: disable=unused-variable
    with tempfile.TemporaryDirectory() as newpath:
        yield nowplaying.db.MetadataDB(databasefile=os.path.join(
            newpath, 'test.db'),
                                       initialize=True)


def results(expected, metadata):
    ''' take a metadata result and compare to expected '''
    for expkey in expected:
        assert expkey in metadata
        assert expkey and expected[expkey] == metadata[expkey]
        del metadata[expkey]

    assert metadata == {}


def test_empty_db(getmetadb):  # pylint: disable=redefined-outer-name
    ''' test writing false data '''
    metadb = getmetadb
    metadb.write_to_metadb(metadata=None)
    readdata = metadb.read_last_meta()

    assert readdata is None

    metadata = {'filename': 'tests/audio/15_Ghosts_II_64kb_orig.mp3'}
    metadb.write_to_metadb(metadata=metadata)
    readdata = metadb.read_last_meta()
    assert readdata is None


def test_data_db1(getmetadb):  # pylint: disable=redefined-outer-name
    ''' simple data test '''
    metadb = getmetadb

    expected = {
        'acoustidid': None,
        'album': 'Ghosts I - IV',
        'albumartist': None,
        'artist': 'Nine Inch Nails',
        'artistlongbio': None,
        'bitrate': '64000',
        'bpm': None,
        'comments': None,
        'composer': None,
        'coverurl': None,
        'date': None,
        'deck': None,
        'disc': None,
        'disc_total': None,
        'discsubtitle': None,
        'filename': 'tests/audio/15_Ghosts_II_64kb_orig.mp3',
        'genre': None,
        'hostfqdn': None,
        'hostip': None,
        'hostname': None,
        'httpport': None,
        'isrc': None,
        'key': None,
        'label': None,
        'lang': None,
        'length': None,
        'musicbrainzalbumid': None,
        'musicbrainzartistid': None,
        'musicbrainzrecordingid': None,
        'title': '15 Ghosts II',
        'track': '15',
        'track_total': None,
    }

    metadb.write_to_metadb(metadata=expected)
    readdata = metadb.read_last_meta()

    expected['dbid'] = 1
    results(expected, readdata)


def test_data_db2(getmetadb):  # pylint: disable=redefined-outer-name
    ''' more complex data test '''
    metadb = getmetadb

    expected = {
        'album': 'Secret Samadhi',
        'artist': 'LĪVE',
        'artistlogoraw': "Rawr! I'm an image!",
        'artistthumbraw': "Quack! Am I duck?",
        'bpm': 91,
        'coverimageraw': "Grr! I'm an image!",
        'date': '1997',
        'deck': 1,
        'filename':
        "/Users/aw/Music/songs/LĪVE/Secret Samadhi/02 Lakini's Juice.mp3",
        'genre': 'Rock',
        'key': 'C#m',
        'label': 'Radioactive Records',
        'title': 'Lakini\'s Juice',
    }

    metadb.write_to_metadb(metadata=expected)
    readdata = metadb.read_last_meta()

    expected = {
        'acoustidid': None,
        'album': 'Secret Samadhi',
        'albumartist': None,
        'artist': 'LĪVE',
        'artistlongbio': None,
        'artistlogoraw': "Rawr! I'm an image!",
        'artistthumbraw': "Quack! Am I duck?",
        'bitrate': None,
        'bpm': '91',
        'comments': None,
        'composer': None,
        'coverimageraw': "Grr! I'm an image!",
        'coverurl': None,
        'date': '1997',
        'deck': '1',
        'disc': None,
        'disc_total': None,
        'discsubtitle': None,
        'filename':
        "/Users/aw/Music/songs/LĪVE/Secret Samadhi/02 Lakini's Juice.mp3",
        'genre': 'Rock',
        'hostfqdn': None,
        'hostip': None,
        'hostname': None,
        'httpport': None,
        'isrc': None,
        'key': 'C#m',
        'label': 'Radioactive Records',
        'lang': None,
        'length': None,
        'musicbrainzalbumid': None,
        'musicbrainzartistid': None,
        'musicbrainzrecordingid': None,
        'title': 'Lakini\'s Juice',
        'track': None,
        'track_total': None,
        'dbid': 1
    }

    results(expected, readdata)


def test_data_dbid(getmetadb):  # pylint: disable=redefined-outer-name
    ''' make sure dbid increments '''
    metadb = getmetadb

    expected = {
        'artist': 'Nine Inch Nails',
        'title': '15 Ghosts II',
    }

    metadb.write_to_metadb(metadata=expected)
    readdata = metadb.read_last_meta()

    expected = {
        'artist': 'Great Artist Here',
        'title': 'Great Title Here',
    }

    metadb.write_to_metadb(metadata=expected)
    readdata = metadb.read_last_meta()

    assert readdata['dbid'] == 2
