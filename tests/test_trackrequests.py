#!/usr/bin/env python3
''' test the trackpoller '''

import asyncio
import logging
import pathlib

import pytest  # pylint: disable=import-error
import pytest_asyncio  # pylint: disable=import-error

import nowplaying.db  # pylint: disable=import-error
import nowplaying.trackrequests  # pylint: disable=import-error


@pytest_asyncio.fixture
async def trackrequestbootstrap(bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' bootstrap a configuration '''
    stopevent = asyncio.Event()
    config = bootstrap
    config.cparser.setValue('settings/input', 'jsonreader')
    playlistpath = pathlib.Path(getroot).joinpath('tests', 'playlists', 'json', 'test.json')
    config.pluginobjs['inputs']['nowplaying.inputs.jsonreader'].load_playlists(
        getroot, playlistpath)
    config.cparser.sync()
    yield nowplaying.trackrequests.Requests(stopevent=stopevent, config=config, testmode=True)
    stopevent.set()
    await asyncio.sleep(2)


@pytest.mark.asyncio
async def test_trackrequest_artisttitlenoquote(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist - title '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user', 'artist - title')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'


@pytest.mark.asyncio
async def test_trackrequest_artisttitlenoquotespaces(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist - title '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user',
                                                 '      artist     -      title    ')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'


@pytest.mark.asyncio
async def test_trackrequest_artisttitlenoquotecomplex(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist - title '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {'displayname': 'test'}, 'user',
        '      prince and the revolution     -      purple rain    ')
    assert data['artist'] == 'prince and the revolution'
    assert data['title'] == 'purple rain'
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'


@pytest.mark.asyncio
async def test_trackrequest_artisttitlequotes(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist - "title" '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user',
                                                 'artist - "title"')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'


@pytest.mark.asyncio
async def test_trackrequest_artisttitlequotesspaces(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist - "title" '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user',
                                                 '    artist    -     "title"   ')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'


@pytest.mark.asyncio
async def test_trackrequest_titlequotesartist(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' "title" - artist '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user',
                                                 '"title" - artist')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'


@pytest.mark.asyncio
async def test_trackrequest_titlequotesbyartist(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' title by artist '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user',
                                                 '"title" by artist')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'


@pytest.mark.asyncio
async def test_trackrequest_quotedweirdal(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' weird al is weird '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user',
                                                 '"Weird Al" Yankovic - This Is The Life.')
    assert data['artist'] == '"Weird Al" Yankovic'
    assert data['title'] == 'This Is The Life.'
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'


@pytest.mark.asyncio
async def test_trackrequest_quotedchampagne(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' weird al is weird '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user',
                                                 'Evelyn "Champagne" King - "I\'m In Love"')
    assert data['artist'] == 'Evelyn "Champagne" King'
    assert data['title'] == 'I\'m In Love'
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'


@pytest.mark.asyncio
async def test_trackrequest_xtcfornigel(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' for part of the title '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user',
                                                 'xtc - making plans for nigel')
    assert data['artist'] == 'xtc'
    assert data['title'] == 'making plans for nigel'
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'


@pytest.mark.asyncio
async def test_trackrequest_xtcforatnigel(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' for @user test '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user',
                                                 'xtc - making plans for @nigel')
    assert data['artist'] == 'xtc'
    assert data['title'] == 'making plans'
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'


@pytest.mark.asyncio
async def test_trackrequest_nospace(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist-title '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user', 'artist-title')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'


@pytest.mark.asyncio
async def test_trackrequest_rouletterequest(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist-title '''

    trackrequest = trackrequestbootstrap
    logging.debug(trackrequest.databasefile)
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue('settings/requests', True)
    trackrequest.config.cparser.sync()

    data = await trackrequest.user_roulette_request({
        'displayname': 'test',
        'playlist': 'testlist'
    }, 'user', 'artist-title')
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'

    data = await trackrequest.get_request({'artist': 'Nine Inch Nails', 'title': '15 Ghosts II'})
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'
    assert data['requesterimageraw']


@pytest.mark.asyncio
async def test_trackrequest_rouletterequest_normalized(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist-title '''

    trackrequest = trackrequestbootstrap
    logging.debug(trackrequest.databasefile)
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue('settings/requests', True)
    trackrequest.config.cparser.sync()

    data = await trackrequest.user_roulette_request({
        'displayname': 'test',
        'playlist': 'testlist'
    }, 'user', 'artist-title')
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'

    data = await trackrequest.get_request({'artist': 'Níne Ínch Näíls', 'title': '15 Ghosts II'})
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'
    assert data['requesterimageraw']


@pytest.mark.asyncio
async def test_trackrequest_getrequest_artist(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist-title '''

    trackrequest = trackrequestbootstrap
    logging.debug(trackrequest.databasefile)
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue('settings/requests', True)
    trackrequest.config.cparser.sync()
    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user', 'Nine Inch Nails')
    logging.debug(data)
    assert data['requestartist'] == 'Nine Inch Nails'
    assert not data['requesttitle']

    data = await trackrequest.get_request({'artist': 'Níne Ínch Näíls', 'title': '15 Ghosts II'})
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'
    assert data['requesterimageraw']


@pytest.mark.asyncio
async def test_trackrequest_getrequest_title(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist-title '''

    trackrequest = trackrequestbootstrap
    logging.debug(trackrequest.databasefile)
    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue('settings/requests', True)
    trackrequest.config.cparser.sync()
    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'}, 'user', '"15 Ghosts II"')
    logging.debug(data)
    assert not data['requestartist']
    assert data['requesttitle'] == '15 Ghosts II'

    data = await trackrequest.get_request({'artist': 'Níne Ínch Näíls', 'title': '15 Ghosts II'})
    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'
    assert data['requesterimageraw']


@pytest.mark.asyncio
async def test_twofer(bootstrap, getroot):  # pylint: disable=redefined-outer-name
    ''' test twofers '''
    stopevent = asyncio.Event()
    config = bootstrap
    config.cparser.setValue('settings/input', 'json')
    playlistpath = pathlib.Path(getroot).joinpath('tests', 'playlists', 'json', 'test.json')
    config.pluginobjs['inputs']['nowplaying.inputs.jsonreader'].load_playlists(
        getroot, playlistpath)
    config.cparser.sync()

    metadb = nowplaying.db.MetadataDB(initialize=True)
    trackrequest = nowplaying.trackrequests.Requests(stopevent=stopevent,
                                                     config=config,
                                                     testmode=True)

    trackrequest.clear_roulette_artist_dupes()
    trackrequest.config.cparser.setValue('settings/requests', True)
    trackrequest.config.cparser.sync()

    data = await trackrequest.twofer_request({
        'displayname': 'test',
    }, 'user', None)

    assert not data

    testdata = {'artist': 'myartist', 'title': 'mytitle1'}
    await metadb.write_to_metadb(testdata)

    data = await trackrequest.twofer_request({
        'displayname': 'test',
    }, 'user', None)

    assert data['requestartist'] == 'myartist'
    assert not data['requesttitle']

    testdata = {'artist': 'myartist', 'title': 'mytitle2'}
    data = await trackrequest.get_request(testdata)

    assert data['requester'] == 'user'
    assert data['requestdisplayname'] == 'test'

    data = await trackrequest.twofer_request({
        'displayname': 'test',
    }, 'user1', "mytitle3")

    assert data['requestartist'] == 'myartist'
    assert data['requesttitle'] == 'mytitle3'

    data = await trackrequest.twofer_request({
        'displayname': 'test',
    }, 'user2', "mytitle4")

    assert data['requestartist'] == 'myartist'
    assert data['requesttitle'] == 'mytitle4'

    testdata = {'artist': 'myartist', 'title': 'mytitle3'}
    data = await trackrequest.get_request(testdata)
    assert data['requester'] == 'user1'
    assert data['requestdisplayname'] == 'test'
