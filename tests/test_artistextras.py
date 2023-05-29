#!/usr/bin/env python3
''' test artistextras '''

import logging
import os

import pytest

PLUGINS = []

if os.environ.get('DISCOGS_API_KEY'):
    PLUGINS.append('discogs')
if os.environ.get('FANARTTV_API_KEY'):
    PLUGINS.append('fanarttv')
if os.environ.get('THEAUDIODB_API_KEY'):
    PLUGINS.append('theaudiodb')

if not PLUGINS:
    pytest.skip("skipping, no API keys for artistextras are available", allow_module_level=True)


class FakeImageCache:  # pylint: disable=too-few-public-methods
    ''' a fake ImageCache that just keeps track of urls '''

    def __init__(self):
        self.urls = {}

    def fill_queue(self, urllist, config=None, artist=None, imagetype=None):  # pylint: disable=unused-argument
        ''' just keep track of what was picked '''
        if not self.urls.get(artist):
            self.urls[artist] = {}
        self.urls[artist][imagetype] = urllist


def configureplugins(config):
    ''' configure plugins '''
    imagecaches = {}
    plugins = {}
    for pluginname in PLUGINS:
        imagecaches[pluginname] = FakeImageCache()
        plugins[pluginname] = config.pluginobjs['artistextras'][
            f'nowplaying.artistextras.{pluginname}']
    return imagecaches, plugins


def configuresettings(pluginname, cparser):
    ''' configure each setting '''
    for key in [
            'banners',
            'bio',
            'enabled',
            'fanart',
            'logos',
            'thumbnails',
            'websites',
    ]:
        cparser.setValue(f'{pluginname}/{key}', True)


@pytest.fixture
def getconfiguredplugin(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    if 'discogs' in PLUGINS:
        configuresettings('discogs', config.cparser)
        config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    if 'fanarttv' in PLUGINS:
        configuresettings('fanarttv', config.cparser)
        config.cparser.setValue('fanarttv/apikey', os.environ['FANARTTV_API_KEY'])
    if 'theaudiodb' in PLUGINS:
        configuresettings('theaudiodb', config.cparser)
        config.cparser.setValue('theaudiodb/apikey', os.environ['THEAUDIODB_API_KEY'])
    yield configureplugins(config)


def test_disabled(bootstrap):
    ''' test disabled '''
    imagecaches, plugins = configureplugins(bootstrap)
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        data = plugins[pluginname].download(imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


def test_providerinfo(bootstrap):  # pylint: disable=redefined-outer-name
    ''' test providerinfo '''
    imagecaches, plugins = configureplugins(bootstrap)  # pylint: disable=unused-variable
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        data = plugins[pluginname].providerinfo()
        assert data


def test_noapikey(bootstrap):  # pylint: disable=redefined-outer-name
    ''' test disabled '''
    config = bootstrap
    imagecaches, plugins = configureplugins(config)
    for pluginname in PLUGINS:
        config.cparser.setValue(f'{pluginname}/enabled', True)
        logging.debug('Testing %s', pluginname)
        data = plugins[pluginname].download(imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


def test_nodata(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' test disabled '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        data = plugins[pluginname].download(imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


def test_noimagecache(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' noimagecache '''

    imagecaches, plugins = getconfiguredplugin  # pylint: disable=unused-variable
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        data = plugins[pluginname].download(
            {
                'album': 'The Downward Spiral',
                'artist': 'Nine Inch Nails'
            }, imagecache=None)
        if pluginname in ['discogs', 'theaudiodb']:
            assert data['artistwebsites']
            assert data['artistlongbio']
        else:
            assert not data


def test_missingallartistdata(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' missing all artist data '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = plugins[pluginname].download({'title': 'title'}, imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


def test_missingmbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' artist '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = plugins[pluginname].download({'artist': 'Nine Inch Nails'},
                                            imagecache=imagecaches[pluginname])
        if pluginname == 'theaudiodb':
            assert data['artistfanarturls']
            assert data['artistlongbio']
            assert data['artistwebsites']
            assert imagecaches[pluginname].urls['Nine Inch Nails']['artistbanner']
            assert imagecaches[pluginname].urls['Nine Inch Nails']['artistlogo']
            assert imagecaches[pluginname].urls['Nine Inch Nails']['artistthumb']
        else:
            assert not data
            assert not imagecaches[pluginname].urls


def test_badmbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = plugins[pluginname].download(
            {
                'artist': 'Nine Inch Nails',
                'musicbrainzartistid': ['xyz']
            },
            imagecache=imagecaches[pluginname])
        if pluginname == 'theaudiodb':
            assert data['artistfanarturls']
            assert data['artistlongbio']
            assert data['artistwebsites']
            assert imagecaches[pluginname].urls['Nine Inch Nails']['artistbanner']
            assert imagecaches[pluginname].urls['Nine Inch Nails']['artistlogo']
            assert imagecaches[pluginname].urls['Nine Inch Nails']['artistthumb']
        else:
            assert not data
            assert not imagecaches[pluginname].urls


def test_onlymbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = plugins[pluginname].download(
            {
                'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da'],
            },
            imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


def test_artist_and_mbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = plugins[pluginname].download(
            {
                'artist': 'Nine Inch Nails',
                'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da'],
            },
            imagecache=imagecaches[pluginname])
        if pluginname == 'theaudiodb':
            assert data['artistlongbio']
            assert data['artistwebsites']
        if pluginname in ['fanarttv', 'theaudiodb']:
            assert data['artistfanarturls']
            assert imagecaches[pluginname].urls['Nine Inch Nails']['artistbanner']
            assert imagecaches[pluginname].urls['Nine Inch Nails']['artistlogo']
            assert imagecaches[pluginname].urls['Nine Inch Nails']['artistthumb']
        else:
            assert not data
            assert not imagecaches[pluginname].urls


def test_all(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = plugins[pluginname].download(
            {
                'artist': 'Nine Inch Nails',
                'album': 'The Downward Spiral',
                'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da'],
            },
            imagecache=imagecaches[pluginname])
        if pluginname in ['discogs', 'theaudiodb']:
            assert data['artistlongbio']
            assert data['artistwebsites']
        if pluginname in ['fanarttv', 'theaudiodb']:
            assert imagecaches[pluginname].urls['Nine Inch Nails']['artistbanner']
            assert imagecaches[pluginname].urls['Nine Inch Nails']['artistlogo']
        assert data['artistfanarturls']


@pytest.mark.xfail(reason="Non-deterministic at the moment")
def test_theall(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = plugins[pluginname].download(
            {
                'artist': 'The Nine Inch Nails',
                'album': 'The Downward Spiral',
                'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da'],
            },
            imagecache=imagecaches[pluginname])
        logging.debug(imagecaches['theaudiodb'].urls)
        if pluginname in ['discogs', 'theaudiodb']:
            assert data['artistlongbio']
            assert data['artistwebsites']
        if pluginname in ['fanarttv', 'theaudiodb']:
            assert imagecaches[pluginname].urls['The Nine Inch Nails']['artistbanner']
            assert imagecaches[pluginname].urls['The Nine Inch Nails']['artistlogo']
        assert data['artistfanarturls']
        assert imagecaches[pluginname].urls['The Nine Inch Nails']['artistthumb']


def test_notfound(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' discogs '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = plugins[pluginname].download(
            {
                'album': 'ZYX fake album XYZ',
                'artist': 'The XYZ fake artist XYZ',
                'musicbrainzartistid': ['xyz']
            },
            imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls
