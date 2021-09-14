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
def m3u_bootstrap(bootstrap):  # pylint: disable=redefined-outer-name
    ''' bootstrap test '''
    with tempfile.TemporaryDirectory() as newpath:
        config = bootstrap
        config.cparser.setValue('m3u/directory', newpath)
        config.cparser.sync()
        yield config


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


def write_m3u8(m3u, filename):
    ''' create m3u file with content '''
    with open(m3u, 'w', encoding='utf-8') as m3ufn:
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


def test_emptym3u(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mydir = config.cparser.value('m3u/directory')
    if not os.path.exists(mydir):
        logging.error('mydir does not exist!')
    pathlib.Path(os.path.join(mydir, 'fake.m3u')).touch()
    plugin = nowplaying.inputs.m3u.Plugin(config=config)
    (artist, title) = plugin.getplayingtrack()
    plugin.stop()
    time.sleep(5)
    assert artist is None
    assert title is None


def test_emptym3u2(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mydir = config.cparser.value('m3u/directory')
    if not os.path.exists(mydir):
        logging.error('mydir does not exist!')
    with open(os.path.join(mydir, 'fake.m3u'), 'w') as m3ufh:
        m3ufh.write(os.linesep)
        m3ufh.write(os.linesep)
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
    plugin.stop()
    time.sleep(2)


def test_noencodingm3u8(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    (artist, title) = plugin.getplayingtrack()

    filename = os.path.join(getroot, 'tests', 'audio',
                            '15_Ghosts_II_64kb_orig.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u8(m3ufile, filename)
    # need to give some time for watcher it pick it up
    time.sleep(1)
    (artist, title) = plugin.getplayingtrack()
    assert artist is None
    assert '15_Ghosts_II_64kb_orig.mp3' in title
    plugin.stop()
    time.sleep(2)


def test_encodingm3u(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    filename = os.path.join(getroot, 'tests', 'audio',
                            '15_Ghosts_II_64kb_füllytâgged.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u(m3ufile, filename)
    # need to give some time for watcher it pick it up
    time.sleep(2)
    (artist, title) = plugin.getplayingtrack()
    assert artist is None
    assert '15_Ghosts_II_64kb_füllytâgged.mp3' in title
    assert 'tests' in title
    assert 'audio' in title
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
                            '15_Ghosts_II_64kb_füllytâgged.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u8')
    write_m3u8(m3ufile, filename)
    # need to give some time for watcher it pick it up
    time.sleep(2)
    (artist, title) = plugin.getplayingtrack()
    assert artist is None
    assert '15_Ghosts_II_64kb_füllytâgged.mp3' in title
    assert 'tests' in title
    assert 'audio' in title
    plugin.stop()
    time.sleep(2)


def test_m3urelative(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    (artist, title) = plugin.getplayingtrack()
    assert artist is None
    assert title is None

    filename = os.path.join('fakedir', '15_Ghosts_II_64kb_orig.mp3')
    pathlib.Path(os.path.join(mym3udir, 'fakedir')).mkdir(parents=True,
                                                          exist_ok=True)
    pathlib.Path(os.path.join(mym3udir, filename)).touch()
    m3ufile = os.path.join(mym3udir, 'test.m3u8')
    write_m3u(m3ufile, filename)
    # need to give some time for watcher it pick it up
    time.sleep(1)
    (artist, title) = plugin.getplayingtrack()
    assert artist is None
    assert filename in title

    plugin.stop()
    time.sleep(2)


def test_m3ustream(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    (artist, title) = plugin.getplayingtrack()
    assert artist is None
    assert title is None

    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u(m3ufile, 'http://somecooltrack')
    # need to give some time for watcher it pick it up
    time.sleep(1)
    (artist, title) = plugin.getplayingtrack()
    assert artist is None
    assert title is None

    plugin.stop()
    time.sleep(2)


def test_m3umixmode(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' make sure mix mode is always newest '''
    config = m3u_bootstrap
    plugin = nowplaying.inputs.m3u.Plugin(config=config)
    time.sleep(1)
    assert plugin.validmixmodes()[0] == 'newest'
    assert plugin.setmixmode('fred') == 'newest'
    assert plugin.getmixmode() == 'newest'
    plugin.stop()
    time.sleep(2)
