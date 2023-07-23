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
        yield nowplaying.db.MetadataDB(databasefile=os.path.join(newpath, 'test.db'),
                                       initialize=True)


@pytest.fixture
def config_and_getmetadb(bootstrap):
    ''' create a temporary directory '''
    config = bootstrap  # pylint: disable=unused-variable
    with tempfile.TemporaryDirectory() as newpath:
        config.setlistdir = os.path.join(newpath, 'sl')
        yield config, nowplaying.db.MetadataDB(databasefile=os.path.join(newpath, 'test.db'),
                                               initialize=True)


def results(expected, metadata):
    ''' take a metadata result and compare to expected '''
    for expkey in expected:
        assert expkey in metadata
        assert expkey and expected[expkey] == metadata[expkey]
        del metadata[expkey]

    assert metadata == {}


@pytest.mark.asyncio
async def test_empty_db(getmetadb):  # pylint: disable=redefined-outer-name
    ''' test writing false data '''
    metadb = getmetadb
    await metadb.write_to_metadb(metadata=None)
    readdata = metadb.read_last_meta()

    assert readdata is None

    metadata = {'filename': 'tests/audio/15_Ghosts_II_64kb_orig.mp3'}
    await metadb.write_to_metadb(metadata=metadata)
    readdata = metadb.read_last_meta()
    assert readdata is None


@pytest.mark.asyncio
async def test_empty_db_async(getmetadb):  # pylint: disable=redefined-outer-name
    ''' test writing false data '''
    metadb = getmetadb
    await metadb.write_to_metadb(metadata=None)
    readdata = await metadb.read_last_meta_async()

    assert readdata is None

    metadata = {'filename': 'tests/audio/15_Ghosts_II_64kb_orig.mp3'}
    await metadb.write_to_metadb(metadata=metadata)
    readdata = await metadb.read_last_meta_async()
    assert readdata is None


@pytest.mark.asyncio
async def test_data_db1(getmetadb):  # pylint: disable=redefined-outer-name
    ''' simple data test '''
    metadb = getmetadb

    expected = {
        'acoustidid': None,
        'album': 'Ghosts I - IV',
        'albumartist': None,
        'artist': 'Nine Inch Nails',
        'artistlongbio': None,
        'artistshortbio': None,
        'artistwebsites': None,
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
        'duration': None,
        'duration_hhmmss': None,
        'filename': 'tests/audio/15_Ghosts_II_64kb_orig.mp3',
        'fpcalcduration': None,
        'fpcalcfingerprint': None,
        'genre': None,
        'genres': None,
        'hostfqdn': None,
        'hostip': None,
        'hostname': None,
        'httpport': None,
        'imagecacheartist': None,
        'isrc': None,
        'key': None,
        'label': None,
        'lang': None,
        'musicbrainzalbumid': None,
        'musicbrainzartistid': None,
        'musicbrainzrecordingid': None,
        'previoustrack': [{
            'artist': 'Nine Inch Nails',
            'title': "15 Ghosts II"
        }],
        'requester': None,
        'requestdisplayname': None,
        'title': '15 Ghosts II',
        'track': '15',
        'track_total': None,
    }

    await metadb.write_to_metadb(metadata=expected)
    readdata = metadb.read_last_meta()

    expected['dbid'] = 1
    results(expected, readdata)


@pytest.mark.asyncio
async def test_data_db2(getmetadb):  # pylint: disable=redefined-outer-name
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
        'filename': "/Users/aw/Music/songs/LĪVE/Secret Samadhi/02 Lakini's Juice.mp3",
        'genre': 'Rock',
        'key': 'C#m',
        'label': 'Radioactive Records',
        'title': 'Lakini\'s Juice',
        'genres': ['trip-hop', 'electronic', 'country']
    }

    await metadb.write_to_metadb(metadata=expected)
    readdata = metadb.read_last_meta()

    expected = {
        'acoustidid': None,
        'album': 'Secret Samadhi',
        'albumartist': None,
        'artist': 'LĪVE',
        'artistlongbio': None,
        'artistshortbio': None,
        'artistlogoraw': "Rawr! I'm an image!",
        'artistthumbraw': "Quack! Am I duck?",
        'artistwebsites': None,
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
        'duration': None,
        'duration_hhmmss': None,
        'filename': "/Users/aw/Music/songs/LĪVE/Secret Samadhi/02 Lakini's Juice.mp3",
        'fpcalcduration': None,
        'fpcalcfingerprint': None,
        'genre': 'Rock',
        'genres': ['trip-hop', 'electronic', 'country'],
        'hostfqdn': None,
        'hostip': None,
        'hostname': None,
        'httpport': None,
        'imagecacheartist': None,
        'isrc': None,
        'key': 'C#m',
        'label': 'Radioactive Records',
        'lang': None,
        'musicbrainzalbumid': None,
        'musicbrainzartistid': None,
        'musicbrainzrecordingid': None,
        'previoustrack': [{
            'artist': 'LĪVE',
            'title': "Lakini's Juice"
        }],
        'requester': None,
        'requestdisplayname': None,
        'title': 'Lakini\'s Juice',
        'track': None,
        'track_total': None,
        'dbid': 1
    }

    results(expected, readdata)


@pytest.mark.asyncio
async def test_data_dbid(getmetadb):  # pylint: disable=redefined-outer-name
    ''' make sure dbid increments '''
    metadb = getmetadb

    expected = {
        'artist': 'Nine Inch Nails',
        'title': '15 Ghosts II',
    }

    await metadb.write_to_metadb(metadata=expected)
    readdata = metadb.read_last_meta()

    expected = {
        'artist': 'Great Artist Here',
        'title': 'Great Title Here',
    }

    await metadb.write_to_metadb(metadata=expected)
    readdata = metadb.read_last_meta()

    assert readdata['dbid'] == 2


@pytest.mark.asyncio
async def test_data_previoustrack(getmetadb):  # pylint: disable=redefined-outer-name
    ''' test the previoustrack functionality '''
    metadb = getmetadb

    for counter in range(4):
        await metadb.write_to_metadb(metadata={'artist': f'a{counter}', 'title': f't{counter}'})

    readdata = metadb.read_last_meta()

    assert readdata['previoustrack'][0] == {'artist': 'a3', 'title': 't3'}
    assert readdata['previoustrack'][1] == {'artist': 'a2', 'title': 't2'}


## NOTE: these don't check content, just make sure
## there are no crashes


def test_empty_setlist(bootstrap):
    ''' test a simple empty db '''
    config = bootstrap
    config.cparser.setValue('setlist/enabled', True)
    nowplaying.db.create_setlist(config)


@pytest.mark.asyncio
async def test_simple_setlist(config_and_getmetadb):  # pylint: disable=redefined-outer-name
    ''' test a single entry db '''
    config, metadb = config_and_getmetadb
    config.cparser.setValue('setlist/enabled', True)

    expected = {
        'artist': 'Great Artist Here',
        'title': 'Great Title Here',
    }

    await metadb.write_to_metadb(metadata=expected)
    nowplaying.db.create_setlist(config, databasefile=metadb.databasefile)


@pytest.mark.asyncio
async def test_missingartist_setlist(config_and_getmetadb):  # pylint: disable=redefined-outer-name
    ''' test a single entry db '''
    config, metadb = config_and_getmetadb
    config.cparser.setValue('setlist/enabled', True)

    expected = {
        'artist': None,
        'title': 'Great Title Here',
    }

    await metadb.write_to_metadb(metadata=expected)
    nowplaying.db.create_setlist(config, databasefile=metadb.databasefile)
