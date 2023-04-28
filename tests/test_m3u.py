#!/usr/bin/env python3
''' test m3u '''

import asyncio
import pathlib
import os
import sys

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
        m3ufn.write(f'#EXTM3U{os.linesep}')
        m3ufn.write(f'{filename}{os.linesep}')


def write_m3u8(m3u, filename):
    ''' create m3u file with content '''
    with open(m3u, 'w', encoding='utf-8') as m3ufn:
        m3ufn.write(f'#EXTM3U{os.linesep}')
        m3ufn.write(f'{filename}{os.linesep}')


def write_extvdj_remix(m3u):
    ''' create m3u file with VDJ '''
    with open(m3u, 'w', encoding='utf-8') as m3ufn:
        m3ufn.write(
            '#EXTVDJ:<time>21:39</time><lastplaytime>1674884385</lastplaytime>'
        )
        m3ufn.write(
            '<artist>j. period</artist><title>Buddy [Remix]</title><remix>feat. De La Soul'
        )
        m3ufn.write(
            f', Jungle Brothers, Q-Tip & Queen Latifah</remix>{os.linesep}')
        m3ufn.write(f'netsearch://dz715352532{os.linesep}')


def write_extvdj_m3u8(m3u):
    ''' create m3u file with VDJ '''
    with open(m3u, 'w', encoding='utf-8') as m3ufn:
        m3ufn.write(
            '#EXTVDJ:<time>21:39</time><lastplaytime>1674884385</lastplaytime>'
        )
        m3ufn.write(
            '<artist>j. period</artist><title>Buddy [Remix]</title><remix>feat. De La Soul'
        )
        m3ufn.write(
            f', Jungle Brothers, Q-Tip & Queen Latifah</remix>{os.linesep}')
        m3ufn.write(f'netsearch://dz715352532{os.linesep}')
        m3ufn.write(
            '#EXTVDJ:<time>21:41</time><lastplaytime>1674884510</lastplaytime>'
        )
        m3ufn.write(
            f'<artist>Kid \'N Play</artist><title>Can You Dig That</title>{os.linesep}'
        )
        m3ufn.write(f'netsearch://dz85144450{os.linesep}')
        m3ufn.write(
            '#EXTVDJ:<time>21:45</time><lastplaytime>1674884707</lastplaytime>'
        )
        m3ufn.write('<artist>Lords Of The Underground</artist>')
        m3ufn.write(f'<title>Chief Rocka</title>{os.linesep}')
        m3ufn.write(f'netsearch://dz3130706{os.linesep}')


def write_extvdj_ampersand(m3u):
    ''' create m3u file with VDJ '''
    with open(m3u, 'w', encoding='utf-8') as m3ufn:
        m3ufn.write(
            '#EXTVDJ:<time>08:43</time><lastplaytime>1675701805</lastplaytime>'
        )
        m3ufn.write('<artist>Nick Cave & The Bad Seeds</artist>')
        m3ufn.write(f'<title>Hollywood</title>{os.linesep}')
        m3ufn.write(f'netsearch://dz1873796677{os.linesep}')


@pytest.mark.asyncio
async def test_nom3u(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mydir = config.cparser.value('m3u/directory')
    if not os.path.exists(mydir):
        logging.error('mydir does not exist!')
    plugin = nowplaying.inputs.m3u.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    await plugin.stop()
    await asyncio.sleep(5)
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')


@pytest.mark.asyncio
async def test_emptym3u(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mydir = config.cparser.value('m3u/directory')
    if not os.path.exists(mydir):
        logging.error('mydir does not exist!')
    pathlib.Path(os.path.join(mydir, 'fake.m3u')).touch()
    plugin = nowplaying.inputs.m3u.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    await plugin.stop()
    await asyncio.sleep(5)
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')


@pytest.mark.asyncio
async def test_emptym3u2(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mydir = config.cparser.value('m3u/directory')
    if not os.path.exists(mydir):
        logging.error('mydir does not exist!')
    with open(os.path.join(mydir, 'fake.m3u'), 'w') as m3ufh:  # pylint: disable=unspecified-encoding
        m3ufh.write(os.linesep)
        m3ufh.write(os.linesep)
    plugin = nowplaying.inputs.m3u.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    await plugin.stop()
    await asyncio.sleep(5)
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')


@pytest.mark.asyncio
async def test_no2newm3u(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    metadata = await plugin.getplayingtrack()
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')

    testmp3 = os.path.join(getroot, 'tests', 'audio',
                           '15_Ghosts_II_64kb_orig.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u(m3ufile, testmp3)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert metadata['filename'] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_no2newm3upolltest(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    config.cparser.setValue('quirks/pollingobserver', True)
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    metadata = await plugin.getplayingtrack()
    await plugin.start()
    await asyncio.sleep(5)
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')
    assert isinstance(plugin.observer,
                      watchdog.observers.polling.PollingObserver)

    testmp3 = os.path.join(getroot, 'tests', 'audio',
                           '15_Ghosts_II_64kb_orig.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u(m3ufile, testmp3)
    await asyncio.sleep(
        10)  # needs to be long enough that the poller finds the update!
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert metadata['filename'] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_noencodingm3u8(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()

    testmp3 = os.path.join(getroot, 'tests', 'audio',
                           '15_Ghosts_II_64kb_orig.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u8(m3ufile, testmp3)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert metadata['filename'] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_encodingm3u(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    await plugin.start()
    await asyncio.sleep(5)
    testmp3 = os.path.join(getroot, 'tests', 'audio',
                           '15_Ghosts_II_64kb_füllytâgged.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u(m3ufile, testmp3)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert metadata['filename'] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_vdjm3u_normal(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    await plugin.start()
    await asyncio.sleep(5)
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_extvdj_m3u8(m3ufile)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert metadata.get('artist') == 'Lords Of The Underground'
    assert metadata.get('title') == 'Chief Rocka'
    assert not metadata.get('filename')
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_vdjm3u_remix(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    config.cparser.setValue('virtualdj/useremix', True)
    config.cparser.sync()
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    await plugin.start()
    await asyncio.sleep(5)
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_extvdj_remix(m3ufile)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert metadata.get('artist') == 'j. period'
    assert metadata.get(
        'title'
    ) == 'Buddy [Remix] (feat. De La Soul, Jungle Brothers, Q-Tip & Queen Latifah)'
    assert not metadata.get('filename')
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_vdjm3u_noremix(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    config.cparser.setValue('virtualdj/useremix', False)
    config.cparser.sync()
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    await plugin.start()
    await asyncio.sleep(5)
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_extvdj_remix(m3ufile)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert metadata.get('artist') == 'j. period'
    assert metadata.get('title') == 'Buddy [Remix]'
    assert not metadata.get('filename')
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_vdjm3u_ampersand(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    await plugin.start()
    await asyncio.sleep(5)
    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_extvdj_ampersand(m3ufile)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert metadata.get('artist') == 'Nick Cave & The Bad Seeds'
    assert metadata.get('title') == 'Hollywood'
    assert not metadata.get('filename')
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_no2newm3u8(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')

    testmp3 = os.path.join(getroot, 'tests', 'audio',
                           '15_Ghosts_II_64kb_füllytâgged.mp3')
    m3ufile = os.path.join(mym3udir, 'test.m3u8')
    write_m3u8(m3ufile, testmp3)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert metadata['filename'] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_m3urelative(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    mym3upath = pathlib.Path(mym3udir)
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')

    testmp3 = os.path.join('fakedir', '15_Ghosts_II_64kb_orig.mp3')
    mym3upath.joinpath('fakedir').mkdir(parents=True, exist_ok=True)
    mym3upath.joinpath(testmp3).touch()
    m3ufile = mym3upath.joinpath('test.m3u8')
    write_m3u(m3ufile, testmp3)
    fullpath = mym3upath.joinpath('fakedir', '15_Ghosts_II_64kb_orig.mp3')
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert fullpath.resolve() == pathlib.Path(metadata['filename']).resolve()

    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_m3urelativesubst(m3u_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    audiodir = getroot.joinpath('tests', 'audio')
    mym3udir = pathlib.Path(config.cparser.value('m3u/directory'))
    if sys.platform == 'darwin':
        mym3udir = mym3udir.resolve()
    config.cparser.setValue('quirks/filesubst', True)
    config.cparser.setValue('quirks/filesubstin',
                            str(mym3udir.joinpath('fakedir')))
    config.cparser.setValue('quirks/filesubstout', str(audiodir))
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=str(mym3udir))
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')

    testmp3 = str(
        pathlib.Path('fakedir').joinpath('15_Ghosts_II_64kb_orig.mp3'))
    mym3udir.joinpath('fakedir').mkdir(parents=True, exist_ok=True)
    mym3udir.joinpath(testmp3).touch()
    m3ufile = str(mym3udir.joinpath('test.m3u8'))
    write_m3u(m3ufile, testmp3)
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert metadata['filename'] == str(
        audiodir.joinpath('15_Ghosts_II_64kb_orig.mp3'))
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_m3ustream(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = m3u_bootstrap
    mym3udir = config.cparser.value('m3u/directory')
    plugin = nowplaying.inputs.m3u.Plugin(config=config, m3udir=mym3udir)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')

    m3ufile = os.path.join(mym3udir, 'test.m3u')
    write_m3u(m3ufile, 'http://somecooltrack')
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')

    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_m3umixmode(m3u_bootstrap):  # pylint: disable=redefined-outer-name
    ''' make sure mix mode is always newest '''
    config = m3u_bootstrap
    plugin = nowplaying.inputs.m3u.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    assert plugin.validmixmodes()[0] == 'newest'
    assert plugin.setmixmode('fred') == 'newest'
    assert plugin.getmixmode() == 'newest'
    await plugin.stop()
    await asyncio.sleep(5)
