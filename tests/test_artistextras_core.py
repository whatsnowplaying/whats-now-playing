#!/usr/bin/env python3
''' test artistextras core functionality '''

import logging
import os

import pytest

from utils_artistextras import configureplugins, configuresettings

PLUGINS = ['wikimedia']

if os.environ.get('DISCOGS_API_KEY'):
    PLUGINS.append('discogs')
if os.environ.get('FANARTTV_API_KEY'):
    PLUGINS.append('fanarttv')
if os.environ.get('THEAUDIODB_API_KEY'):
    PLUGINS.append('theaudiodb')


@pytest.fixture
def getconfiguredplugin(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    configuresettings('wikimedia', config.cparser)
    if 'discogs' in PLUGINS:
        configuresettings('discogs', config.cparser)
        config.cparser.setValue('discogs/apikey', os.environ['DISCOGS_API_KEY'])
    if 'fanarttv' in PLUGINS:
        configuresettings('fanarttv', config.cparser)
        config.cparser.setValue('fanarttv/apikey', os.environ['FANARTTV_API_KEY'])
    if 'theaudiodb' in PLUGINS:
        configuresettings('theaudiodb', config.cparser)
        config.cparser.setValue('theaudiodb/apikey', os.environ['THEAUDIODB_API_KEY'])
    if 'theaudiodb' in PLUGINS:
        configuresettings('theaudiodb', config.cparser)
    yield configureplugins(config)


@pytest.mark.asyncio
async def test_disabled(bootstrap):
    ''' test disabled '''
    imagecaches, plugins = configureplugins(bootstrap)
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        data = await plugins[pluginname].download_async(imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


def test_providerinfo(bootstrap):  # pylint: disable=redefined-outer-name
    ''' test providerinfo '''
    imagecaches, plugins = configureplugins(bootstrap)  # pylint: disable=unused-variable
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        data = plugins[pluginname].providerinfo()
        assert data


@pytest.mark.asyncio
async def test_noapikey(bootstrap):  # pylint: disable=redefined-outer-name
    ''' test disabled '''
    config = bootstrap
    imagecaches, plugins = configureplugins(config)
    for pluginname in PLUGINS:
        config.cparser.setValue(f'{pluginname}/enabled', True)
        logging.debug('Testing %s', pluginname)
        data = await plugins[pluginname].download_async(imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_nodata(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' test disabled '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        data = await plugins[pluginname].download_async(imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_noimagecache(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' noimagecache '''

    imagecaches, plugins = getconfiguredplugin  # pylint: disable=unused-variable
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        data = await plugins[pluginname].download_async(
            {
                'album': 'The Downward Spiral',
                'artist': 'Nine Inch Nails',
                'imagecacheartist': 'nineinchnails'
            },
            imagecache=None)
        if pluginname in ['discogs', 'theaudiodb']:
            assert data['artistwebsites']
            assert data['artistlongbio']
        else:
            assert not data


@pytest.mark.asyncio
async def test_missingallartistdata(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' missing all artist data '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async({'title': 'title'},
                                                        imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_missingmbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' artist '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'artist': 'Nine Inch Nails',
                'imagecacheartist': 'nineinchnails'
            },
            imagecache=imagecaches[pluginname])
        if pluginname == 'theaudiodb':
            assert data['artistfanarturls']
            assert data['artistlongbio']
            assert data['artistwebsites']
            assert imagecaches[pluginname].urls['nineinchnails']['artistbanner']
            assert imagecaches[pluginname].urls['nineinchnails']['artistlogo']
            assert imagecaches[pluginname].urls['nineinchnails']['artistthumbnail']
        else:
            assert not data
            assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_featuring1(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' artist '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'artist': 'Grimes feat Janelle Monáe',
                'title': 'Venus Fly',
                'album': 'Art Angels',
                'imagecacheartist': 'grimesfeatjanellemonae'
            },
            imagecache=imagecaches[pluginname])
        if pluginname == 'discogs':
            assert data['artistfanarturls']
            assert data['artistlongbio']
            assert data['artistwebsites']
        elif pluginname == 'theaudiodb':
            assert data['artistfanarturls']
            assert data['artistlongbio']
            assert data['artistwebsites']
            assert imagecaches[pluginname].urls['grimesfeatjanellemonae']['artistbanner']
            assert imagecaches[pluginname].urls['grimesfeatjanellemonae']['artistlogo']
            assert imagecaches[pluginname].urls['grimesfeatjanellemonae']['artistthumbnail']


@pytest.mark.asyncio
async def test_featuring2(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' artist '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'artist': 'MӨЯIS BLΛK feat. grabyourface',
                'title': 'Complicate',
                'album': 'Irregular Revisions',
                'imagecacheartist': 'morisblakfeatgrabyourface'
            },
            imagecache=imagecaches[pluginname])
        if pluginname == 'discogs':
            assert data['artistfanarturls']
            assert data['artistlongbio']
            assert data['artistwebsites']


@pytest.mark.asyncio
async def test_badmbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'artist': 'NonExistentArtistXYZ',
                'imagecacheartist': 'nonexistentartistxyz',
                'musicbrainzartistid': ['xyz']
            },
            imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_onlymbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da'],
            },
            imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_artist_and_mbid(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'artist': 'Nine Inch Nails',
                'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da'],
                'imagecacheartist': 'nineinchnails',
            },
            imagecache=imagecaches[pluginname])
        if pluginname == 'theaudiodb':
            assert data['artistlongbio']
            assert data['artistwebsites']
        if pluginname in ['fanarttv', 'theaudiodb']:
            assert data['artistfanarturls']
            assert imagecaches[pluginname].urls['nineinchnails']['artistbanner']
            assert imagecaches[pluginname].urls['nineinchnails']['artistlogo']
            assert imagecaches[pluginname].urls['nineinchnails']['artistthumbnail']
        else:
            assert not data
            assert not imagecaches[pluginname].urls


@pytest.mark.asyncio
async def test_all(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)
        metadata = {
            'artist': 'Nine Inch Nails',
            'album': 'The Downward Spiral',
            'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da'],
            'imagecacheartist': 'nineinchnails',
        }
        if pluginname == 'wikimedia':
            metadata['artistwebsites'] = ['https://www.wikidata.org/wiki/Q11647']
        data = await plugins[pluginname].download_async(metadata,
                                                        imagecache=imagecaches[pluginname])
        if pluginname in ['discogs', 'theaudiodb']:
            assert data['artistlongbio']
            assert data['artistwebsites']
        if pluginname in ['fanarttv', 'theaudiodb']:
            assert imagecaches[pluginname].urls['nineinchnails']['artistbanner']
            assert imagecaches[pluginname].urls['nineinchnails']['artistlogo']
        assert data['artistfanarturls']


@pytest.mark.xfail(reason="Non-deterministic at the moment")
@pytest.mark.asyncio
async def test_theall(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' badmbid '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        metadata = {
            'artist': 'The Nine Inch Nails',
            'album': 'The Downward Spiral',
            'musicbrainzartistid': ['b7ffd2af-418f-4be2-bdd1-22f8b48613da'],
            'imagecacheartist': 'nineinchnails'
        }
        if pluginname == 'wikimedia':
            metadata['artistwebsites'] = ['https://www.wikidata.org/wiki/Q11647']
        data = await plugins[pluginname].download_async(metadata,
                                                        imagecache=imagecaches[pluginname])
        if pluginname in ['discogs', 'theaudiodb']:
            assert data['artistlongbio']
            assert data['artistwebsites']
        if pluginname in ['fanarttv', 'theaudiodb']:
            assert imagecaches[pluginname].urls['nineinchnails']['artistbanner']
            assert imagecaches[pluginname].urls['nineinchnails']['artistlogo']
        assert data['artistfanarturls']
        assert imagecaches[pluginname].urls['nineinchnails']['artistthumbnail']


@pytest.mark.asyncio
async def test_notfound(getconfiguredplugin):  # pylint: disable=redefined-outer-name
    ''' discogs '''
    imagecaches, plugins = getconfiguredplugin
    for pluginname in PLUGINS:
        logging.debug('Testing %s', pluginname)

        data = await plugins[pluginname].download_async(
            {
                'album': 'ZYX fake album XYZ',
                'artist': 'The XYZ fake artist XYZ',
                'musicbrainzartistid': ['xyz']
            },
            imagecache=imagecaches[pluginname])
        assert not data
        assert not imagecaches[pluginname].urls
