#!/usr/bin/env python3
''' test virtualdj '''

import asyncio
import pathlib
import os
import sys

import logging
import tempfile

import pytest
import watchdog.observers.polling  # pylint: disable=import-error

import nowplaying.inputs.virtualdj  # pylint: disable=import-error
import nowplaying.utils  # pylint: disable=import-error


@pytest.fixture
def virtualdj_bootstrap(bootstrap):  # pylint: disable=redefined-outer-name
    ''' bootstrap test '''
    with tempfile.TemporaryDirectory() as newpath:
        config = bootstrap
        config.cparser.setValue('virtualdj/history', newpath)
        config.cparser.sync()
        yield config


def results(expected, metadata):
    ''' take a metadata result and compare to expected '''
    for expkey in expected:
        assert expkey in metadata
        assert expected[expkey] == metadata[expkey]
        del metadata[expkey]

    assert metadata == {}


def write_virtualdj(virtualdj, filename):
    ''' create virtualdj file with content '''
    with open(virtualdj, 'w') as virtualdjfn:  # pylint: disable=unspecified-encoding
        virtualdjfn.write(f'#EXTM3U{os.linesep}')
        virtualdjfn.write(f'{filename}{os.linesep}')


def write_virtualdj8(virtualdj, filename):
    ''' create virtualdj file with content '''
    with open(virtualdj, 'w', encoding='utf-8') as virtualdjfn:
        virtualdjfn.write(f'#EXTM3U{os.linesep}')
        virtualdjfn.write(f'{filename}{os.linesep}')


def write_extvdj_remix(virtualdj):
    ''' create virtualdj file with VDJ '''
    with open(virtualdj, 'w', encoding='utf-8') as virtualdjfn:
        virtualdjfn.write('#EXTVDJ:<time>21:39</time><lastplaytime>1674884385</lastplaytime>')
        virtualdjfn.write(
            '<artist>j. period</artist><title>Buddy [Remix]</title><remix>feat. De La Soul')
        virtualdjfn.write(f', Jungle Brothers, Q-Tip & Queen Latifah</remix>{os.linesep}')
        virtualdjfn.write(f'netsearch://dz715352532{os.linesep}')


def write_extvdj_virtualdj8(virtualdj):
    ''' create virtualdj file with VDJ '''
    with open(virtualdj, 'w', encoding='utf-8') as virtualdjfn:
        virtualdjfn.write('#EXTVDJ:<time>21:39</time><lastplaytime>1674884385</lastplaytime>')
        virtualdjfn.write(
            '<artist>j. period</artist><title>Buddy [Remix]</title><remix>feat. De La Soul')
        virtualdjfn.write(f', Jungle Brothers, Q-Tip & Queen Latifah</remix>{os.linesep}')
        virtualdjfn.write(f'netsearch://dz715352532{os.linesep}')
        virtualdjfn.write('#EXTVDJ:<time>21:41</time><lastplaytime>1674884510</lastplaytime>')
        virtualdjfn.write(
            f'<artist>Kid \'N Play</artist><title>Can You Dig That</title>{os.linesep}')
        virtualdjfn.write(f'netsearch://dz85144450{os.linesep}')
        virtualdjfn.write('#EXTVDJ:<time>21:45</time><lastplaytime>1674884707</lastplaytime>')
        virtualdjfn.write('<artist>Lords Of The Underground</artist>')
        virtualdjfn.write(f'<title>Chief Rocka</title>{os.linesep}')
        virtualdjfn.write(f'netsearch://dz3130706{os.linesep}')


def write_extvdj_ampersand(virtualdj):
    ''' create virtualdj file with VDJ '''
    with open(virtualdj, 'w', encoding='utf-8') as virtualdjfn:
        virtualdjfn.write('#EXTVDJ:<time>08:43</time><lastplaytime>1675701805</lastplaytime>')
        virtualdjfn.write('<artist>Nick Cave & The Bad Seeds</artist>')
        virtualdjfn.write(f'<title>Hollywood</title>{os.linesep}')
        virtualdjfn.write(f'netsearch://dz1873796677{os.linesep}')


@pytest.mark.asyncio
async def test_novirtualdj(virtualdj_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    mydir = config.cparser.value('virtualdj/history')
    if not os.path.exists(mydir):
        logging.error('mydir does not exist!')
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    await plugin.stop()
    await asyncio.sleep(5)
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')


@pytest.mark.asyncio
async def test_emptyvirtualdj(virtualdj_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    mydir = config.cparser.value('virtualdj/history')
    if not os.path.exists(mydir):
        logging.error('mydir does not exist!')
    pathlib.Path(os.path.join(mydir, 'fake.m3u')).touch()
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    await plugin.stop()
    await asyncio.sleep(5)
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')


@pytest.mark.asyncio
async def test_emptyvirtualdj2(virtualdj_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    mydir = config.cparser.value('virtualdj/history')
    if not os.path.exists(mydir):
        logging.error('mydir does not exist!')
    with open(os.path.join(mydir, 'fake.m3u'), 'w') as virtualdjfh:  # pylint: disable=unspecified-encoding
        virtualdjfh.write(os.linesep)
        virtualdjfh.write(os.linesep)
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    await plugin.stop()
    await asyncio.sleep(5)
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')


@pytest.mark.asyncio
async def test_no2newvirtualdj(virtualdj_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    myvirtualdjdir = config.cparser.value('virtualdj/history')
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
    metadata = await plugin.getplayingtrack()
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')

    testmp3 = os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.mp3')
    virtualdjfile = os.path.join(myvirtualdjdir, 'test.m3u')
    write_virtualdj(virtualdjfile, testmp3)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert metadata['filename'] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_no2newvirtualdjpolltest(virtualdj_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    myvirtualdjdir = config.cparser.value('virtualdj/history')
    config.cparser.setValue('quirks/pollingobserver', True)
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
    metadata = await plugin.getplayingtrack()
    await plugin.start()
    await asyncio.sleep(5)
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')
    assert isinstance(plugin.observer, watchdog.observers.polling.PollingObserver)

    testmp3 = os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.mp3')
    virtualdjfile = os.path.join(myvirtualdjdir, 'test.m3u')
    write_virtualdj(virtualdjfile, testmp3)
    await asyncio.sleep(10)  # needs to be long enough that the poller finds the update!
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert metadata['filename'] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_noencodingvirtualdj8(virtualdj_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    myvirtualdjdir = config.cparser.value('virtualdj/history')
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()

    testmp3 = os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.mp3')
    virtualdjfile = os.path.join(myvirtualdjdir, 'test.m3u')
    write_virtualdj8(virtualdjfile, testmp3)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert metadata['filename'] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_encodingvirtualdj(virtualdj_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    myvirtualdjdir = config.cparser.value('virtualdj/history')
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
    await plugin.start()
    await asyncio.sleep(5)
    testmp3 = os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_füllytâgged.mp3')
    virtualdjfile = os.path.join(myvirtualdjdir, 'test.m3u')
    write_virtualdj(virtualdjfile, testmp3)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert metadata['filename'] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_vdjvirtualdj_normal(virtualdj_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    myvirtualdjdir = config.cparser.value('virtualdj/history')
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
    await plugin.start()
    await asyncio.sleep(5)
    virtualdjfile = os.path.join(myvirtualdjdir, 'test.m3u')
    write_extvdj_virtualdj8(virtualdjfile)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert metadata.get('artist') == 'Lords Of The Underground'
    assert metadata.get('title') == 'Chief Rocka'
    assert not metadata.get('filename')
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_vdjvirtualdj_remix(virtualdj_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    myvirtualdjdir = config.cparser.value('virtualdj/history')
    config.cparser.setValue('virtualdj/useremix', True)
    config.cparser.sync()
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
    await plugin.start()
    await asyncio.sleep(5)
    virtualdjfile = os.path.join(myvirtualdjdir, 'test.m3u')
    write_extvdj_remix(virtualdjfile)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert metadata.get('artist') == 'j. period'
    assert metadata.get(
        'title') == 'Buddy [Remix] (feat. De La Soul, Jungle Brothers, Q-Tip & Queen Latifah)'
    assert not metadata.get('filename')
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_vdjvirtualdj_noremix(virtualdj_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    myvirtualdjdir = config.cparser.value('virtualdj/history')
    config.cparser.setValue('virtualdj/useremix', False)
    config.cparser.sync()
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
    await plugin.start()
    await asyncio.sleep(5)
    virtualdjfile = os.path.join(myvirtualdjdir, 'test.m3u')
    write_extvdj_remix(virtualdjfile)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert metadata.get('artist') == 'j. period'
    assert metadata.get('title') == 'Buddy [Remix]'
    assert not metadata.get('filename')
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_vdjvirtualdj_ampersand(virtualdj_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    myvirtualdjdir = config.cparser.value('virtualdj/history')
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
    await plugin.start()
    await asyncio.sleep(5)
    virtualdjfile = os.path.join(myvirtualdjdir, 'test.m3u')
    write_extvdj_ampersand(virtualdjfile)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert metadata.get('artist') == 'Nick Cave & The Bad Seeds'
    assert metadata.get('title') == 'Hollywood'
    assert not metadata.get('filename')
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_no2newvirtualdj8(virtualdj_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    myvirtualdjdir = config.cparser.value('virtualdj/history')
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')

    testmp3 = os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_füllytâgged.mp3')
    virtualdjfile = os.path.join(myvirtualdjdir, 'test.m3u')
    write_virtualdj8(virtualdjfile, testmp3)
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert metadata['filename'] == testmp3
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_virtualdjrelative(virtualdj_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    myvirtualdjdir = config.cparser.value('virtualdj/history')
    myvirtualdjpath = pathlib.Path(myvirtualdjdir)
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')

    testmp3 = os.path.join('fakedir', '15_Ghosts_II_64kb_orig.mp3')
    myvirtualdjpath.joinpath('fakedir').mkdir(parents=True, exist_ok=True)
    myvirtualdjpath.joinpath(testmp3).touch()
    virtualdjfile = myvirtualdjpath.joinpath('test.m3u')
    write_virtualdj(virtualdjfile, testmp3)
    fullpath = myvirtualdjpath.joinpath('fakedir', '15_Ghosts_II_64kb_orig.mp3')
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert fullpath.resolve() == pathlib.Path(metadata['filename']).resolve()

    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_virtualdjrelativesubst(virtualdj_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    audiodir = getroot.joinpath('tests', 'audio')
    myvirtualdjdir = pathlib.Path(config.cparser.value('virtualdj/history'))
    if sys.platform == 'darwin':
        myvirtualdjdir = myvirtualdjdir.resolve()
    config.cparser.setValue('quirks/filesubst', True)
    config.cparser.setValue('quirks/filesubstin', str(myvirtualdjdir.joinpath('fakedir')))
    config.cparser.setValue('quirks/filesubstout', str(audiodir))
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=str(myvirtualdjdir))
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')

    testmp3 = str(pathlib.Path('fakedir').joinpath('15_Ghosts_II_64kb_orig.mp3'))
    myvirtualdjdir.joinpath('fakedir').mkdir(parents=True, exist_ok=True)
    myvirtualdjdir.joinpath(testmp3).touch()
    virtualdjfile = str(myvirtualdjdir.joinpath('test.m3u'))
    write_virtualdj(virtualdjfile, testmp3)
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert metadata['filename'] == str(audiodir.joinpath('15_Ghosts_II_64kb_orig.mp3'))
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_virtualdjstream(virtualdj_bootstrap):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    config = virtualdj_bootstrap
    myvirtualdjdir = config.cparser.value('virtualdj/history')
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
    await plugin.start()
    await asyncio.sleep(5)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')

    virtualdjfile = os.path.join(myvirtualdjdir, 'test.m3u')
    write_virtualdj(virtualdjfile, 'http://somecooltrack')
    await asyncio.sleep(1)
    metadata = await plugin.getplayingtrack()
    assert not metadata.get('artist')
    assert not metadata.get('title')
    assert not metadata.get('filename')

    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_virtualdjmixmode(virtualdj_bootstrap):  # pylint: disable=redefined-outer-name
    ''' make sure mix mode is always newest '''
    config = virtualdj_bootstrap
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config)
    await plugin.start()
    await asyncio.sleep(5)
    assert plugin.validmixmodes()[0] == 'newest'
    assert plugin.setmixmode('fred') == 'newest'
    assert plugin.getmixmode() == 'newest'
    await plugin.stop()
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_playlist_read(virtualdj_bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test getting random tracks '''
    config = virtualdj_bootstrap
    config.cparser.setValue('quirks/filesubst', True)
    config.cparser.setValue('quirks/filesubstin', '/SRCROOT')
    config.cparser.setValue('quirks/filesubstout', str(getroot))
    playlistdir = getroot.joinpath('tests', 'playlists', 'virtualdj')
    myvirtualdjdir = config.cparser.value('virtualdj/history')
    config.cparser.setValue('virtualdj/playlists', playlistdir)
    plugin = nowplaying.inputs.virtualdj.Plugin(config=config, m3udir=myvirtualdjdir)
    plugin.initdb()
    filename = await plugin.getrandomtrack('videos')
    assert filename
    filename = await plugin.getrandomtrack('testplaylist')
    assert filename
