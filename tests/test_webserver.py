#!/usr/bin/env python3
''' test webserver '''

import logging
import time

import pytest
import requests

import nowplaying.subprocesses  # pylint: disable=import-error
import nowplaying.processes.webserver  # pylint: disable=import-error


@pytest.fixture
def getwebserver(bootstrap):
    ''' configure the webserver, dependents with prereqs '''
    config = bootstrap
    metadb = nowplaying.db.MetadataDB(initialize=True)
    logging.debug(metadb.databasefile)
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.sync()
    manager = nowplaying.subprocesses.SubprocessManager(config=config,
                                                        testmode=True)
    manager.start_webserver()
    time.sleep(5)
    yield config, metadb
    manager.stop_all_processes()


def test_startstopwebserver(getwebserver):  # pylint: disable=redefined-outer-name
    ''' test a simple start/stop '''
    config, metadb = getwebserver  #pylint: disable=unused-variable
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.sync()
    time.sleep(5)


def test_webserver_htmtest(getwebserver):  # pylint: disable=redefined-outer-name
    ''' start webserver, read existing data, add new data, then read that '''
    config, metadb = getwebserver
    config.cparser.setValue(
        'weboutput/htmltemplate',
        config.getbundledir().joinpath('templates', 'basic-plain.txt'))
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()
    time.sleep(10)

    logging.debug(config.cparser.value('weboutput/htmltemplate'))
    # handle no data, should return refresh

    req = requests.get('http://localhost:8899/index.html', timeout=5)
    assert req.status_code == 202
    assert req.text == nowplaying.processes.webserver.INDEXREFRESH

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
    assert req.text == nowplaying.processes.webserver.INDEXREFRESH

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
    config, metadb = getwebserver
    config.cparser.setValue('weboutput/httpenabled', 'true')
    config.cparser.setValue(
        'weboutput/htmltemplate',
        config.getbundledir().joinpath('templates', 'basic-plain.txt'))
    config.cparser.setValue(
        'textoutput/txttemplate',
        config.getbundledir().joinpath('templates', 'basic-plain.txt'))
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()
    time.sleep(10)

    # handle no data, should return refresh

    req = requests.get('http://localhost:8899/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ''


    # should return empty
    req = requests.get('http://localhost:8899/v1/last', timeout=5)
    assert req.status_code == 200
    assert req.json() == {}
    # handle first write

    metadb.write_to_metadb(metadata={
        'title': 'testtxttitle',
        'artist': 'testtxtartist'
    })
    time.sleep(1)
    req = requests.get('http://localhost:8899/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testtxtartist - testtxttitle'

    req = requests.get('http://localhost:8899/v1/last', timeout=5)
    assert req.status_code == 200
    checkdata = req.json()
    assert checkdata['artist'] == 'testtxtartist'
    assert checkdata['title'] == 'testtxttitle'
    assert not checkdata.get('dbid')

    # another read should give us same info

    time.sleep(1)
    req = requests.get('http://localhost:8899/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ' testtxtartist - testtxttitle'

    req = requests.get('http://localhost:8899/v1/last', timeout=5)
    assert req.status_code == 200
    checkdata = req.json()
    assert checkdata['artist'] == 'testtxtartist'
    assert checkdata['title'] == 'testtxttitle'
    assert not checkdata.get('dbid')

    # handle second write

    metadb.write_to_metadb(metadata={
        'artist': 'artisttxt2',
        'title': 'titletxt2',
    })
    time.sleep(1)
    req = requests.get('http://localhost:8899/index.txt', timeout=5)
    assert req.status_code == 200
    assert req.text == ' artisttxt2 - titletxt2'


    req = requests.get('http://localhost:8899/v1/last', timeout=5)
    assert req.status_code == 200
    checkdata = req.json()
    assert checkdata['artist'] == 'artisttxt2'
    assert checkdata['title'] == 'titletxt2'
    assert not checkdata.get('dbid')

def test_webserver_gifwordstest(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure gifwords works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get('http://localhost:8899/gifwords.htm', timeout=5)
    assert req.status_code == 200


def test_webserver_coverpng(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure coverpng works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get('http://localhost:8899/cover.png', timeout=5)
    assert req.status_code == 200


def test_webserver_artistfanart_test(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure artistfanart works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get('http://localhost:8899/artistfanart.htm', timeout=5)
    assert req.status_code == 202


def test_webserver_banner_test(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure banner works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get('http://localhost:8899/artistbanner.htm', timeout=5)
    assert req.status_code == 202

    req = requests.get('http://localhost:8899/artistbanner.png', timeout=5)
    assert req.status_code == 200


def test_webserver_logo_test(getwebserver):  # pylint: disable=redefined-outer-name
    ''' make sure banner works '''
    config, metadb = getwebserver  # pylint: disable=unused-variable
    config.cparser.setValue('weboutput/once', True)
    config.cparser.sync()

    req = requests.get('http://localhost:8899/artistlogo.htm', timeout=5)
    assert req.status_code == 202

    req = requests.get('http://localhost:8899/artistlogo.png', timeout=5)
    assert req.status_code == 200
