#!/usr/bin/env python3
''' test musicbrainz '''

import pytest

import nowplaying.musicbrainz  # pylint: disable=import-error


@pytest.fixture
def getmusicbrainz(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('musicbrainz/enabled', True)
    config.cparser.setValue('acoustidmb/emailaddress',
                            'aw+wnptest@effectivemachines.com')
    return nowplaying.musicbrainz.MusicBrainzHelper(config=config)


def test_15ghosts2_orig(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    mbhelper = getmusicbrainz
    metadata = mbhelper.recordingid('2d7f08e1-be1c-4b86-b725-6e675b7b6de0')
    assert metadata['album'] == 'Ghosts I–IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['date'] == '2008-03-02'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata['musicbrainzartistid'] == [
        'b7ffd2af-418f-4be2-bdd1-22f8b48613da'
    ]
    assert metadata[
        'musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadata['title'] == '15 Ghosts II'


def test_15ghosts2_fullytagged(getmusicbrainz):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    mbhelper = getmusicbrainz
    metadata = mbhelper.isrc(['USTC40852243'])
    assert metadata['album'] == 'Ghosts I–IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['date'] == '2008-03-02'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata['musicbrainzartistid'] == [
        'b7ffd2af-418f-4be2-bdd1-22f8b48613da'
    ]
    assert metadata[
        'musicbrainzrecordingid'] == '2d7f08e1-be1c-4b86-b725-6e675b7b6de0'
    assert metadata['title'] == '15 Ghosts II'
