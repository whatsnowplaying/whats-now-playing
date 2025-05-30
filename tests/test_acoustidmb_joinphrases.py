#!/usr/bin/env python3
''' test acoustid join phrases '''

import os
import json
import pathlib
import unittest.mock

import pytest

import nowplaying.recognition.acoustidmb  # pylint: disable=import-error

if not os.environ.get('ACOUSTID_TEST_APIKEY'):
    pytest.skip("skipping, ACOUSTID_TEST_APIKEY is not set", allow_module_level=True)


@pytest.fixture
def getacoustidmbplugin(bootstrap):
    ''' automated integration test '''
    config = bootstrap
    config.cparser.setValue('acoustidmb/enabled', True)
    config.cparser.setValue('musicbrainz/enabled', True)
    config.cparser.setValue('acoustidmb/acoustidapikey', os.environ['ACOUSTID_TEST_APIKEY'])
    config.cparser.setValue('acoustidmb/emailaddress', 'aw+wnptest@effectivemachines.com')
    yield nowplaying.recognition.acoustidmb.Plugin(config=config)


@pytest.mark.asyncio
async def test_join_phrases_multiartist(getacoustidmbplugin):  # pylint: disable=redefined-outer-name
    ''' test join phrase support with multi-artist track using mocked data '''
    plugin = getacoustidmbplugin

    # Load fingerprint data from external JSON file
    fingerprint_file = (pathlib.Path(__file__).parent / 'audio' /
                        '1_Giant_Leap_My_Culture_fingerprint.json')
    with open(fingerprint_file, 'r', encoding='utf-8') as json_file:
        mock_fingerprint = json.load(json_file)

    # Mock AcoustID lookup response for "My Culture" by 1 Giant Leap
    # feat. Robbie Williams & Maxi Jazz
    mock_acoustid_response = {
        'results': [{
            'id': '4ba8faaf-cc17-4a38-8e35-9b21889e4001',
            'score': 0.99775845,
            'recordings': [{
                'id': 'b366689f-4b81-4f1f-974b-3dff361d45a1',
                'releases': [{
                    'artists': [
                        {'id': '3eff5a3a-b011-4da3-81fe-bc8d4a11b28c',
                         'name': '1 Giant Leap'}
                    ],
                    'country': 'XE',
                    'date': {'year': 2001},
                    'id': 'b79afe7c-7f2c-4516-a8bf-e34efa290c54',
                    'medium_count': 1,
                    'mediums': [{
                        'format': 'CD',
                        'position': 1,
                        'track_count': 12,
                        'tracks': [{
                            'artists': [
                                {'id': '3eff5a3a-b011-4da3-81fe-bc8d4a11b28c',
                                 'joinphrase': ' feat. ',
                                 'name': '1 Giant Leap'},
                                {'id': 'db4624cf-0e44-481e-a9dc-2142b833ec2f',
                                 'joinphrase': ' & ',
                                 'name': 'Robbie Williams'},
                                {'id': 'debd408d-72b3-4c14-a0eb-dd4fe526e240',
                                 'name': 'Maxi Jazz'}
                            ],
                            'id': 'c713d252-3ba9-445e-a70e-1dda9609029f',
                            'position': 2,
                            'title': 'My Culture'
                        }]
                    }],
                    'releaseevents': [{'country': 'XE', 'date': {'year': 2001}}],
                    'title': '1 Giant Leap',
                    'track_count': 12
                }]
            }]
        }]
    }

    # Mock both fpcalc and acoustid.lookup to return our test data
    with unittest.mock.patch(
            'nowplaying.recognition.acoustidmb.Plugin._fpcalc',
            return_value=mock_fingerprint), \
         unittest.mock.patch('acoustid.lookup',
                             return_value=mock_acoustid_response):
        metadata = await plugin.recognize({'filename': 'test_multiartist.m4a'})

    # Verify join phrases are working correctly
    # Note: The final result may show "and" instead of "&" due to
    # MusicBrainz processing
    assert metadata['artist'] in [
        '1 Giant Leap feat. Robbie Williams & Maxi Jazz',  # Direct from AcoustID
        '1 Giant Leap feat. Robbie Williams and Maxi Jazz'  # After MusicBrainz
    ]
    assert metadata['title'] == 'My Culture'
    assert metadata['album'] == '1 Giant Leap'
    assert metadata['musicbrainzrecordingid'] == (
        'b366689f-4b81-4f1f-974b-3dff361d45a1')

    # Verify multiple artist IDs are returned for multi-artist track
    assert len(metadata['musicbrainzartistid']) == 3
    expected_artist_ids = [
        '3eff5a3a-b011-4da3-81fe-bc8d4a11b28c',  # 1 Giant Leap
        'db4624cf-0e44-481e-a9dc-2142b833ec2f',  # Robbie Williams
        'debd408d-72b3-4c14-a0eb-dd4fe526e240'   # Maxi Jazz
    ]
    assert set(metadata['musicbrainzartistid']) == set(expected_artist_ids)
