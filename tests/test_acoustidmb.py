#!/usr/bin/env python3
''' test acoustid '''

import os

import pytest

import nowplaying.recognition.acoustidmb  # pylint: disable=import-error

if 'ACOUSTID_TEST_APIKEY' not in os.environ:
    pytest.skip("skipping, ACOUSTID_TEST_APIKEY is not set",
                allow_module_level=True)


@pytest.fixture
def getacoustidmbplugin(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', True)
    config.cparser.setValue('musicbrainz/enabled', True)
    config.cparser.setValue('acoustidmb/acoustidapikey',
                            os.environ['ACOUSTID_TEST_APIKEY'])
    config.cparser.setValue('acoustidmb/emailaddress',
                            'aw+wnptest@effectivemachines.com')
    yield nowplaying.recognition.acoustidmb.Plugin(config=config)


def test_15ghosts2_orig(getacoustidmbplugin, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    plugin = getacoustidmbplugin
    metadata = plugin.recognize({
        'filename':
        os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.mp3')
    })
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


def test_15ghosts2_fullytagged(getacoustidmbplugin, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    plugin = getacoustidmbplugin
    metadata = plugin.recognize({
        'filename':
        os.path.join(getroot, 'tests', 'audio',
                     '15_Ghosts_II_64kb_füllytâgged.mp3')
    })
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
