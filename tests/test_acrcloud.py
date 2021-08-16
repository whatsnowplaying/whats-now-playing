#!/usr/bin/env python3
''' test acoustid '''
import os

import pytest

import nowplaying.recognition.ACRCloud  # pylint: disable=import-error

if not os.environ['ACRCLOUD_TEST_KEY']:
    pytest.skip("skipping, ACRCLOUD_TEST_KEY is not set",
                allow_module_level=True)

if not os.environ['ACRCLOUD_TEST_SECRET']:
    pytest.skip("skipping, ACRCLOUD_TEST_SECRET is not set",
                allow_module_level=True)

if not os.environ['ACRCLOUD_TEST_HOST']:
    pytest.skip("skipping, ACRCLOUD_TEST_HOST is not set",
                allow_module_level=True)


@pytest.fixture
def getacrcloudplugin(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.setValue('acrcloud/enabled', True)
    config.cparser.setValue('acrcloud/key', os.environ['ACRCLOUD_TEST_KEY'])
    config.cparser.setValue('acrcloud/secret',
                            os.environ['ACRCLOUD_TEST_SECRET'])
    config.cparser.setValue('acrcloud/host', os.environ['ACRCLOUD_TEST_HOST'])
    plugin = nowplaying.recognition.ACRCloud.Plugin(config=config)
    yield plugin


def test_15ghosts2_orig(getacrcloudplugin, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    plugin = getacrcloudplugin
    metadata = plugin.recognize({
        'filename':
        os.path.join(getroot, 'tests', 'audio', '15_Ghosts_II_64kb_orig.mp3')
    })
    assert metadata['album'] == 'Ghosts I-IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata['title'] == '15 Ghosts II'
    assert metadata[
        'musicbrainzrecordingid'] == 'e0632d22-f355-41dd-ae01-9bcd87aaacf6'


def test_15ghosts2_fullytagged(getacrcloudplugin, getroot):  # pylint: disable=redefined-outer-name
    ''' automated integration test '''
    plugin = getacrcloudplugin
    metadata = plugin.recognize({
        'filename':
        os.path.join(getroot, 'tests', 'audio',
                     '15_Ghosts_II_64kb_fullytagged.mp3')
    })

    assert metadata['album'] == 'Ghosts I-IV'
    assert metadata['artist'] == 'Nine Inch Nails'
    assert metadata['label'] == 'The Null Corporation'
    assert metadata[
        'musicbrainzrecordingid'] == 'e0632d22-f355-41dd-ae01-9bcd87aaacf6'
    assert metadata['title'] == '15 Ghosts II'
