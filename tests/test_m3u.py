#!/usr/bin/env python3
''' test m3u '''

import pathlib
import os
import sys
import time

import logging
import tempfile

import pytest
import watchdog.observers.polling  # pylint: disable=import-error

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
    with open(m3u, 'w') as m3ufn:  # pylint: disable=unspecified-encoding
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
    plugin.start()
    time.sleep(5)
    (artist, title, filename) = plugin.getplayingtrack()
    plugin.stop()
    time.sleep(5)
    assert artist is None
    assert title is None
    assert filename is None


def test_emptym3u(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mydir = config.cparser.value('m3u/directory')
    if not os.path.exists(mydir):
        logging.error('mydir does not exist!')
    pathlib.Path(os.path.join(mydir, 'fake.m3u')).touch()
    plugin = nowplaying.inputs.m3u.Plugin(config=config)
    plugin.start()
    time.sleep(5)
    (artist, title, filename) = plugin.getplayingtrack()
    plugin.stop()
    time.sleep(5)
    assert artist is None
    assert title is None
    assert filename is None


def test_emptym3u2(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mydir = config.cparser.value('m3u/directory')
    if not os.path.exists(mydir):
        logging.error('mydir does not exist!')
    with open(os.path.join(mydir, 'fake.m3u'), 'w') as m3ufh:  # pylint: disable=unspecified-encoding
        m3ufh.write(os.linesep)
        m3ufh.write(os.linesep)
    plugin = nowplaying.inputs.m3u.Plugin(config=config)
    plugin.start()
    time.sleep(5)
    (artist, title, filename) = plugin.getplayingtrack()
    plugin.stop()
    time.sleep(5)
    assert artist is None
    assert title is None
    assert filename is None


def test_no2newm3u(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    (artist, title, filename) = plugin.getplayingtrack()
    plugin.start()
    time.sleep(5)
    assert artist is None
    assert title is None
    assert filename is None

    testmp3 = os.path.join(getroot, 'tests', 'audio',
                           '15_Ghosts_II_64kb_orig.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u(m3ufile, testmp3)
    time.sleep(1)
    (artist, title, filename) = plugin.getplayingtrack()
    assert artist is None
    assert title is None
    assert testmp3 == filename
    plugin.stop()
    time.sleep(5)


def test_no2newm3upolltest(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    config.cparser.setValue('quirks/pollingobserver', True)
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    (artist, title, filename) = plugin.getplayingtrack()
    plugin.start()
    time.sleep(5)
    assert artist is None
    assert title is None
    assert filename is None
    assert isinstance(plugin.observer,
                      watchdog.observers.polling.PollingObserver)

    testmp3 = os.path.join(getroot, 'tests', 'audio',
                           '15_Ghosts_II_64kb_orig.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u(m3ufile, testmp3)
    time.sleep(10)  # needs to be long enough that the poller finds the update!
    (artist, title, filename) = plugin.getplayingtrack()
    assert artist is None
    assert title is None
    assert testmp3 == filename
    plugin.stop()
    time.sleep(5)


def test_noencodingm3u8(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    plugin.start()
    time.sleep(5)
    (artist, title, filename) = plugin.getplayingtrack()

    testmp3 = os.path.join(getroot, 'tests', 'audio',
                           '15_Ghosts_II_64kb_orig.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u8(m3ufile, testmp3)
    time.sleep(1)
    (artist, title, filename) = plugin.getplayingtrack()
    assert artist is None
    assert title is None
    assert testmp3 == filename
    plugin.stop()
    time.sleep(5)


def test_encodingm3u(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    plugin.start()
    time.sleep(5)
    testmp3 = os.path.join(getroot, 'tests', 'audio',
                           '15_Ghosts_II_64kb_füllytâgged.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u(m3ufile, testmp3)
    time.sleep(1)
    (artist, title, filename) = plugin.getplayingtrack()
    assert artist is None
    assert title is None
    assert testmp3 == filename
    plugin.stop()
    time.sleep(5)


def test_no2newm3u8(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    plugin.start()
    time.sleep(5)
    (artist, title, filename) = plugin.getplayingtrack()
    assert artist is None
    assert title is None
    assert filename is None

    testmp3 = os.path.join(getroot, 'tests', 'audio',
                           '15_Ghosts_II_64kb_füllytâgged.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u8')
    write_m3u8(m3ufile, testmp3)
    time.sleep(1)
    (artist, title, filename) = plugin.getplayingtrack()
    assert artist is None
    assert title is None
    assert testmp3 == filename
    plugin.stop()
    time.sleep(5)


def test_m3urelative(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    plugin.start()
    time.sleep(5)
    (artist, title, filename) = plugin.getplayingtrack()
    assert artist is None
    assert title is None
    assert filename is None

    testmp3 = os.path.join('fakedir', '15_Ghosts_II_64kb_orig.mp3')
    pathlib.Path(os.path.join(mym3udir, 'fakedir')).mkdir(parents=True,
                                                          exist_ok=True)
    pathlib.Path(os.path.join(mym3udir, testmp3)).touch()
    m3ufile = os.path.join(mym3udir, 'test.m3u8')
    write_m3u(m3ufile, testmp3)
    time.sleep(1)
    (artist, title, filename) = plugin.getplayingtrack()
    assert artist is None
    assert title is None
    assert testmp3 in filename

    plugin.stop()
    time.sleep(5)


def test_m3urelativesubst(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    audiodir = getroot.joinpath('tests', 'audio')
    mym3udir = pathlib.Path(config.cparser.value('m3u/directory'))
    if sys.platform == 'darwin':
        mym3udir = mym3udir.resolve()
    config.cparser.setValue('quirks/filesubst', True)
    config.cparser.setValue('quirks/filesubstin', str(mym3udir.joinpath('fakedir')))
    config.cparser.setValue('quirks/filesubstout', str(audiodir))
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=str(mym3udir))
    plugin.start()
    time.sleep(5)
    (artist, title, filename) = plugin.getplayingtrack()
    assert artist is None
    assert title is None
    assert filename is None

    testmp3 = str(pathlib.Path('fakedir').joinpath('15_Ghosts_II_64kb_orig.mp3'))
    mym3udir.joinpath('fakedir').mkdir(parents=True, exist_ok=True)
    mym3udir.joinpath(testmp3).touch()
    m3ufile = str(mym3udir.joinpath('test.m3u8'))
    write_m3u(m3ufile, testmp3)
    time.sleep(5)
    (artist, title, filename) = plugin.getplayingtrack()
    assert filename == str(audiodir.joinpath('15_Ghosts_II_64kb_orig.mp3'))
    plugin.stop()
    time.sleep(5)


def test_m3ustream(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    plugin.start()
    time.sleep(5)
    (artist, title, filename) = plugin.getplayingtrack()
    assert artist is None
    assert title is None
    assert filename is None

    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u(m3ufile, 'http://somecooltrack')
    time.sleep(1)
    (artist, title, filename) = plugin.getplayingtrack()
    assert artist is None
    assert title is None
    assert filename is None

    plugin.stop()
    time.sleep(5)


def test_m3umixmode(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' make sure mix mode is always newest '''
    config = m3u_bootstrap
    plugin = nowplaying.inputs.m3u.Plugin(config=config)
    plugin.start()
    time.sleep(5)
    assert plugin.validmixmodes()[0] == 'newest'
    assert plugin.setmixmode('fred') == 'newest'
    assert plugin.getmixmode() == 'newest'
    plugin.stop()
    time.sleep(5)
