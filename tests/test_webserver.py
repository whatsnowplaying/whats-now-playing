#!/usr/bin/env python3
''' test webserver '''

import multiprocessing
import os
import tempfile
import time

import pytest
import requests

import nowplaying.webserver  # pylint: disable=import-error


@pytest.fixture
def getwebserver(bootstrap):
    ''' configure the webserver, dependents with prereqs '''
    with tempfile.TemporaryDirectory() as newpath:
        config = bootstrap
        metadb = nowplaying.db.MetadataDB(databasefile=os.path.join(
            newpath, 'test.db'),
                                          initialize=True)
        config.templatedir = os.path.join(newpath, 'templates')
        bundledir = config.getbundledir()
        webprocess = multiprocessing.Process(target=nowplaying.webserver.start,
                                             args=(bundledir, newpath))
        webprocess.start()
        time.sleep(1)
        yield config, metadb, webprocess
        if webprocess:
            nowplaying.webserver.stop(webprocess.pid)
            if not webprocess.join(5):
                webprocess.terminate()
            webprocess.join(5)
            webprocess.close()
            webprocess = None


def test_startstopwebserver(getwebserver):  # pylint: disable=redefined-outer-name
    ''' test a simple start/stop '''
    config, metadb, webprocess = getwebserver  #pylint: disable=unused-variable
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.sync()
    time.sleep(5)


def test_webserver_htmtest(getwebserver):  # pylint: disable=redefined-outer-name
    ''' start webserver, read existing data, add new data, then read that '''
    config, metadb, webprocess = getwebserver  #pylint: disable=unused-variable
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.setValue(
        'weboutput/htmltemplate',
        os.path.join(config.getbundledir(), 'templates', 'basic-plain.txt'))
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()
    time.sleep(10)

    # handle no data, should return refresh

    req = requests.get('http://localhost:8899/index.html', timeout=5)
    assert req.status_code == 202
    assert req.text == nowplaying.webserver.INDEXREFRESH

    # handle first write

    metadb.write_to_metadb(metadata={
        'title': 'testhtmtitle',
        'artist': 'testhtmartist'
    })
    time.sleep(1)
    req = requests.get('http://localhost:8899/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testhtmartist - testhtmtitle'

    # another read should give us refresh

    time.sleep(1)
    req = requests.get('http://localhost:8899/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == nowplaying.webserver.INDEXREFRESH

    config.cparser.setValue('weboutput/once', False)
    config.cparser.sync()

    # flipping once to false should give us back same info

    time.sleep(1)
    req = requests.get('http://localhost:8899/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testhtmartist - testhtmtitle'

    # handle second write

    metadb.write_to_metadb(metadata={
        'artist': 'artisthtm2',
        'title': 'titlehtm2',
    })
    time.sleep(1)
    req = requests.get('http://localhost:8899/index.html', timeout=5)
    assert req.status_code == 200
    assert req.text == ' artisthtm2 - titlehtm2'


def test_webserver_txttest(getwebserver):  # pylint: disable=redefined-outer-name
    ''' start webserver, read existing data, add new data, then read that '''
    config, metadb, webprocess = getwebserver  #pylint: disable=unused-variable
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.setValue(
        'weboutput/htmltemplate',
        os.path.join(config.getbundledir(), 'templates', 'basic-plain.txt'))
    config.cparser.setValue(
        'textoutput/txttemplate',
        os.path.join(config.getbundledir(), 'templates', 'basic-plain.txt'))
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()
    time.sleep(10)

    # handle no data, should return refresh

    req = requests.get('http://localhost:8899/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ''

    # handle first write

    metadb.write_to_metadb(metadata={
        'title': 'testtxttitle',
        'artist': 'testtxtartist'
    })
    time.sleep(1)
    req = requests.get('http://localhost:8899/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testtxtartist - testtxttitle'

    # another read should give us same info

    time.sleep(1)
    req = requests.get('http://localhost:8899/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testtxtartist - testtxttitle'

    # handle second write

    metadb.write_to_metadb(metadata={
        'artist': 'artisttxt2',
        'title': 'titletxt2',
    })
    time.sleep(1)
    req = requests.get('http://localhost:8899/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ' artisttxt2 - titletxt2'
