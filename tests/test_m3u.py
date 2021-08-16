#!/usr/bin/env python3
''' test m3u '''

import pathlib
import os
import time

import logging
import tempfile

import pytest

import nowplaying.inputs.m3u  # pylint: disable=import-error
import nowplaying.utils  # pylint: disable=import-error


@pytest.fixture
def m3udir():
    ''' create a temporary directory '''
    with tempfile.TemporaryDirectory() as newpath:
        old_cwd = os.getcwd()
        os.chdir(newpath)
        yield newpath
        os.chdir(old_cwd)


@pytest.fixture
def m3u_bootstrap(bootstrap, m3udir):  # pylint: disable=redefined-outer-name
    ''' bootstrap test '''
    config = bootstrap
    config.cparser.setValue('m3u/directory', m3udir)
    config.cparser.sync()
    yield config


def touchdir(directory):
    ''' serato requires current session files to process '''
    for file in os.listdir(directory):
        filename = os.path.join(directory, file)
        pathlib.Path(filename).touch()


def results(expected, metadata):
    ''' take a metadata result and compare to expected '''
    for expkey in expected:
        assert expkey in metadata
        assert expected[expkey] == metadata[expkey]
        del metadata[expkey]

    assert metadata == {}


def write_m3u(m3u, filename):
    ''' create m3u file with content '''
    with open(m3u, 'w') as m3ufn:
        m3ufn.write('#EXTM3U' + os.linesep)
        m3ufn.write(f'{filename}' + os.linesep)


def test_nom3u(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mydir = config.cparser.value('m3u/directory')
    if not os.path.exists(mydir):
        logging.error('mydir does not exist!')
    plugin = nowplaying.inputs.m3u.Plugin(config=config)
    (artist, title) = plugin.getplayingtrack()
    plugin.stop()
    time.sleep(5)
    assert artist is None
    assert title is None


def test_no2newm3u(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    (artist, title) = plugin.getplayingtrack()
    assert artist is None
    assert title is None

    filename = os.path.join(getroot, 'tests', 'audio',
                            '15_Ghosts_II_64kb_orig.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u(m3ufile, filename)
    # need to give some time for watcher it pick it up
    time.sleep(1)
    (artist, title) = plugin.getplayingtrack()
    assert artist is None
    assert '15_Ghosts_II_64kb_orig.mp3' in title
    metadata = plugin.getplayingmetadata()
    assert '15_Ghosts_II_64kb_orig.mp3' in metadata['filename']
    metadata = nowplaying.utils.getmoremetadata(metadata)
    assert metadata['album'] == 'Ghosts I - IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['title'] == '15 Ghosts II'
    assert metadata['bitrate'] == 64000
    assert metadata['track'] == '15'

    plugin.stop()
    time.sleep(2)


def test_no2newm3u8(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    (artist, title) = plugin.getplayingtrack()
    assert artist is None
    assert title is None

    filename = os.path.join(getroot, 'tests', 'audio',
                            '15_Ghosts_II_64kb_orig.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u8')
    write_m3u(m3ufile, filename)
    # need to give some time for watcher it pick it up
    time.sleep(1)
    (artist, title) = plugin.getplayingtrack()
    assert artist is None
    assert '15_Ghosts_II_64kb_orig.mp3' in title
    plugin.stop()
    time.sleep(2)
