#!/usr/bin/env python3
''' test musicbrainz '''

import logging
import pytest

import nowplaying.musicbrainz  # pylint: disable=import-error


@pytest.fixture
def getmusicbrainz(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', True)
    config.cparser.setValue('acoustidmb/emailaddress', 'aw+wnptest@effectivemachines.com')
    return nowplaying.musicbrainz.MusicBrainzHelper(config=config)


def test_15ghosts2_orig(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    mbhelper = getmusicbrainz
    metadata = mbhelper.recordingid('2d7f08e1-be1c-4b86-b725-6e675b7b6de0')
    assert metadata['album'] == 'Ghosts I–IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['date'] == '2008-03-02'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata['musicbrainzartistid'] == ['b7ffd2af-418f-4be2-bdd1-22f8b48613da']
    assert metadata['musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadata['title'] == '15 Ghosts II'


def test_15ghosts2_fullytagged(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    mbhelper = getmusicbrainz
    metadata = mbhelper.isrc(['USTC40852243'])
    assert metadata['album'] == 'Ghosts I–IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['date'] == '2008-03-02'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata['musicbrainzartistid'] == ['b7ffd2af-418f-4be2-bdd1-22f8b48613da']
    assert metadata['musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadata['title'] == '15 Ghosts II'


def test_fallback1(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Nine Inch Nails', 'title': '15 Ghosts II'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['artist'] == 'Nine Inch Nails'
    assert newdata['title'] == '15 Ghosts II'
    assert newdata['musicbrainzartistid'] == ['b7ffd2af-418f-4be2-bdd1-22f8b48613da']
    assert newdata['album'] == 'Ghosts I–IV'


def test_fallback2(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Danse Society', 'title': 'Somewhere'}
    newdata = mbhelper.lastditcheffort(metadata)
    assert newdata['musicbrainzartistid'] == ['75ede374-68bb-4429-85fb-4b3b1421dbd1']
    assert newdata['album'] == 'Somewhere'


def test_fallback3(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    mbhelper = getmusicbrainz
    #
    # MB has this classified as Prince & The Revolution. So we get a
    # weird (but valid!) answer back because the input is technically wrong!
    #
    metadata = {'artist': 'Prince', 'title': 'Computer Blue'}
    newdata = mbhelper.lastditcheffort(metadata)
    if newdata.get('coverimageraw'):
        del newdata['coverimageraw']
    logging.debug(newdata)
    assert newdata['musicbrainzartistid'] == ['070d193a-845c-479f-980e-bef15710653e']


def test_fallback3a(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    mbhelper = getmusicbrainz
    #
    # Now if the album is there, hopefully that helps...
    #
    metadata = {'artist': 'Prince', 'title': 'Computer Blue', 'album': 'Purple Rain'}
    newdata = mbhelper.lastditcheffort(metadata)
    if newdata.get('coverimageraw'):
        del newdata['coverimageraw']
    logging.debug(newdata)
    assert newdata['musicbrainzartistid'] == [
        '070d193a-845c-479f-980e-bef15710653e', '4c8ead39-b9df-4c56-a27c-51bc049cfd48'
    ]


def test_fallback4(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Snap! vs. Martin Eyerer', 'title': 'Green Grass Grows'}
    newdata = mbhelper.lastditcheffort(metadata)

    #
    # Our search specifically avoid compilations so this ends up being the non-vs
    # version. Could be worse?
    #

    if newdata.get('coverimageraw'):
        del newdata['coverimageraw']
    logging.debug(newdata)
    assert newdata['musicbrainzartistid'] == ['cd23732d-ffd2-444e-8884-53475d7ac7d9']
    assert newdata['album'] == 'Welcome to Tomorrow'


def test_fallback5(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    mbhelper = getmusicbrainz
    metadata = {
        'artist': 'Sander van Doorn vs. Robbie Williams',
        'title': 'Close My Eyes (radio edit)'
    }
    newdata = mbhelper.lastditcheffort(metadata)

    #
    # Our search specifically avoid compilations so this ends up being the non-vs
    # version. Could be worse?
    #
    assert newdata['musicbrainzartistid'] == [
        '733a2394-e003-43cb-88a6-02f3b57e345b', 'db4624cf-0e44-481e-a9dc-2142b833ec2f'
    ]
    assert newdata['album'] == 'Close My Eyes'


@pytest.mark.xfail(reason="Non-deterministic at the moment")
def test_fallback6(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    mbhelper = getmusicbrainz
    metadata = {
        'artist': 'The KLF vs. E.N.T.',
        'title': '3 A.M. Eternal (The KLF vs. E.N.T. Radio Freedom edit)'
    }
    newdata = mbhelper.lastditcheffort(metadata)
    #
    # Not the best choice, but passable
    #
    assert newdata['musicbrainzartistid'] == [
        '8092b8b7-235e-4844-9f72-95a9d5a73dbf', '709af0d0-dcb6-4858-b76d-05a13fc9a0a6'
    ]
    assert newdata['album'] == 'Solid State Logik 1'


def test_fallback7(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    mbhelper = getmusicbrainz
    metadata = {'artist': 'Mareux', 'title': 'The Perfect Girl (Live at Coachella 2023)'}
    newdata = mbhelper.lastditcheffort(metadata)
    #
    # Not the best choice, but passable
    #
    assert newdata['musicbrainzartistid'] == ['09095919-c549-4f33-9555-70df9dd941e1']
    assert newdata['album'] == 'The Perfect Girl'
