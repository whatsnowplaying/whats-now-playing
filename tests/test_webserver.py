#!/usr/bin/env python3
''' test webserver '''

import asyncio
import os
import sys
import tempfile

import pytest

import nowplaying.webserver  # pylint: disable=import-error

if sys.platform.startswith('win'):
    pytest.skip('These do not work on Windows', allow_module_level=True)

@pytest.fixture
async def getwebserver(bootstrap, aiohttp_client):
    ''' configure the webserver, dependents with prereqs '''
    with tempfile.TemporaryDirectory() as newpath:
        config = bootstrap
        metadbfile = os.path.join(newpath, 'metatest.db')
        webdbfile = os.path.join(newpath, 'webtest.db')
        metadb = nowplaying.db.MetadataDB(databasefile=metadbfile,
                                          initialize=True)
        config.templatedir = os.path.join(newpath, 'templates')

        event = asyncio.Event()
        webprocess = nowplaying.webserver.WebHandler(event,
                                                     metadbfile=metadbfile,
                                                     webdbfile=webdbfile,
                                                     testmode=True)
        app = webprocess.create_app()
        app.skip_url_asserts = True
        client = await aiohttp_client(app,
                                      server_kwargs={"skip_url_asserts": True})
        await asyncio.sleep(1)
        yield config, metadb, webprocess, client
        # Windows has a tendency to be a bit racy here
        await asyncio.sleep(5)
        event.set()
        await asyncio.sleep(10)

@pytest.mark.asyncio
async def test_startstopwebserver(getwebserver):  # pylint: disable=redefined-outer-name
    ''' test a simple start/stop '''
    config, metadb, webprocess, client = getwebserver  #pylint: disable=unused-variable
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.sync()
    await asyncio.sleep(2)


@pytest.mark.asyncio
async def test_webserver_htmtest(getwebserver):  # pylint: disable=redefined-outer-name
    ''' start webserver, read existing data, add new data, then read that '''
    config, metadb, webprocess, client = getwebserver  #pylint: disable=unused-variable
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.setValue(
        'weboutput/htmltemplate',
        os.path.join(config.getbundledir(), 'templates', 'basic-plain.txt'))
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()
    await asyncio.sleep(2)

    # handle no data, should return refresh

    req = await client.get('/index.html')
    assert req.status == 202
    assert await req.text() == nowplaying.webserver.INDEXREFRESH

    # handle first write

    await asyncio.sleep(2)
    metadb.write_to_metadb(metadata={
        'title': 'testhtmtitle',
        'artist': 'testhtmartist'
    })
    await asyncio.sleep(2)
    req = await client.get('/index.html')
    assert req.status == 200
    assert await req.text() == ' testhtmartist - testhtmtitle'

    # another read should give us refresh

    await asyncio.sleep(2)
    req = await client.get('/index.html')
    assert req.status == 200
    assert await req.text() == nowplaying.webserver.INDEXREFRESH

    config.cparser.setValue('weboutput/once', False)
    config.cparser.sync()

    # flipping once to false should give us back same info

    await asyncio.sleep(2)
    req = await client.get('/index.html')
    assert req.status == 200
    assert await req.text() == ' testhtmartist - testhtmtitle'

    # handle second write

    metadb.write_to_metadb(metadata={
        'artist': 'artisthtm2',
        'title': 'titlehtm2',
    })
    await asyncio.sleep(2)
    req = await client.get('/index.html')
    assert req.status == 200
    assert await req.text() == ' artisthtm2 - titlehtm2'


@pytest.mark.asyncio
async def test_webserver_txttest(getwebserver):  # pylint: disable=redefined-outer-name
    ''' start webserver, read existing data, add new data, then read that '''
    config, metadb, webprocess, client = getwebserver  #pylint: disable=unused-variable
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.setValue(
        'weboutput/htmltemplate',
        os.path.join(config.getbundledir(), 'templates', 'basic-plain.txt'))
    config.cparser.setValue(
        'textoutput/txttemplate',
        os.path.join(config.getbundledir(), 'templates', 'basic-plain.txt'))
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()
    await asyncio.sleep(2)

    # handle no data, should return refresh

    req = await client.get('/index.txt')
    assert req.status == 200
    assert await req.text() == ''

    # handle first write
    await asyncio.sleep(2)
    metadb.write_to_metadb(metadata={
        'title': 'testtxttitle',
        'artist': 'testtxtartist'
    })
    await asyncio.sleep(2)
    req = await client.get('/index.txt')
    assert req.status == 200
    assert await req.text() == ' testtxtartist - testtxttitle'

    # another read should give us same info

    await asyncio.sleep(2)
    req = await client.get('/index.txt')
    assert req.status == 200
    assert await req.text() == ' testtxtartist - testtxttitle'

    # handle second write

    metadb.write_to_metadb(metadata={
        'artist': 'artisttxt2',
        'title': 'titletxt2',
    })
    await asyncio.sleep(2)
    req = await client.get('/index.txt')
    assert req.status == 200
    assert await req.text() == ' artisttxt2 - titletxt2'
