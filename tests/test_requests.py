#!/usr/bin/env python3
''' test the trackpoller '''

import asyncio

import threading

import pytest  # pylint: disable=import-error
import pytest_asyncio  # pylint: disable=import-error

import nowplaying.trackrequests  # pylint: disable=import-error


@pytest_asyncio.fixture
async def trackrequestbootstrap(bootstrap):  # pylint: disable=redefined-outer-name
    ''' bootstrap a configuration '''
    config = bootstrap
    stopevent = threading.Event()
    config.cparser.sync()
    yield nowplaying.trackrequests.Requests(stopevent=stopevent,
                                            config=config,
                                            testmode=True)
    stopevent.set()
    await asyncio.sleep(2)


@pytest.mark.asyncio
async def test_trackrequest_artisttitlenoquote(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist - title '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'},
                                                 'user', 'artist - title')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'


@pytest.mark.asyncio
async def test_trackrequest_artisttitlenoquotespaces(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist - title '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {'displayname': 'test'}, 'user', '      artist     -      title    ')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'


@pytest.mark.asyncio
async def test_trackrequest_artisttitlenoquotecomplex(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist - title '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {'displayname': 'test'}, 'user',
        '      prince and the revolution     -      purple rain    ')
    assert data['artist'] == 'prince and the revolution'
    assert data['title'] == 'purple rain'


@pytest.mark.asyncio
async def test_trackrequest_artisttitlequotes(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist - "title" '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'},
                                                 'user', 'artist - "title"')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'


@pytest.mark.asyncio
async def test_trackrequest_artisttitlequotesspaces(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist - "title" '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {'displayname': 'test'}, 'user', '    artist    -     "title"   ')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'


@pytest.mark.asyncio
async def test_trackrequest_titlequotesartist(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' "title" - artist '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'},
                                                 'user', '"title" - artist')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'


@pytest.mark.asyncio
async def test_trackrequest_titlequotesbyartist(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' title by artist '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'},
                                                 'user', '"title" by artist')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'


@pytest.mark.asyncio
async def test_trackrequest_quotedweirdal(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' weird al is weird '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {'displayname': 'test'}, 'user',
        '"Weird Al" Yankovic - This Is The Life.')
    assert data['artist'] == '"Weird Al" Yankovic'
    assert data['title'] == 'This Is The Life.'


@pytest.mark.asyncio
async def test_trackrequest_xtcfornigel(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' for part of the title '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {'displayname': 'test'}, 'user', 'xtc - making plans for nigel')
    assert data['artist'] == 'xtc'
    assert data['title'] == 'making plans for nigel'


@pytest.mark.asyncio
async def test_trackrequest_xtcforatnigel(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' for @user test '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request(
        {'displayname': 'test'}, 'user', 'xtc - making plans for @nigel')
    assert data['artist'] == 'xtc'
    assert data['title'] == 'making plans'


@pytest.mark.asyncio
async def test_trackrequest_nospace(trackrequestbootstrap):  # pylint: disable=redefined-outer-name
    ''' artist-title '''

    trackrequest = trackrequestbootstrap

    data = await trackrequest.user_track_request({'displayname': 'test'},
                                                 'user', 'artist-title')
    assert data['artist'] == 'artist'
    assert data['title'] == 'title'
