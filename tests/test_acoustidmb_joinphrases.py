#!/usr/bin/env python3
"""test acoustid join phrases"""

import os
import json
import pathlib
import unittest.mock

import pytest

import nowplaying.recognition.acoustid  # pylint: disable=import-error

if not os.environ.get("ACOUSTID_TEST_APIKEY"):
    pytest.skip("skipping, ACOUSTID_TEST_APIKEY is not set", allow_module_level=True)


@pytest.fixture
def getacoustidplugin(bootstrap):
    """automated integration test"""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", True)
    config.cparser.setValue("musicbrainz/enabled", True)
    config.cparser.setValue("acoustidmb/acoustidapikey", os.environ["ACOUSTID_TEST_APIKEY"])
    config.cparser.setValue("musicbrainz/emailaddress", "aw+wnptest@effectivemachines.com")
    yield nowplaying.recognition.acoustid.Plugin(config=config)


@pytest.mark.asyncio
async def test_join_phrases_multiartist(getacoustidplugin):  # pylint: disable=redefined-outer-name
    """test join phrase support with multi-artist track using mocked data"""
    plugin = getacoustidplugin

    # Load fingerprint data from external JSON file
    fingerprint_file = (
        pathlib.Path(__file__).parent / "audio" / "1_Giant_Leap_My_Culture_fingerprint.json"
    )
    with open(fingerprint_file, "r", encoding="utf-8") as json_file:
        mock_fingerprint = json.load(json_file)

    # Load mock AcoustID lookup response from external JSON file
    joinphrases_file = pathlib.Path(__file__).parent / "resources" / "joinphrases.json"
    with open(joinphrases_file, "r", encoding="utf-8") as json_file:
        mock_acoustid_response = json.load(json_file)

    # Mock both fpcalc and acoustid.lookup to return our test data
    with (
        unittest.mock.patch(
            "nowplaying.recognition.acoustid.Plugin._fpcalc", return_value=mock_fingerprint
        ),
        unittest.mock.patch("acoustid.lookup", return_value=mock_acoustid_response),
    ):
        metadata = await plugin.recognize({"filename": "test_multiartist.m4a"})

    # Verify join phrases are working correctly
    # Note: The final result may show "and" instead of "&" due to
    # MusicBrainz processing
    assert metadata["artist"] in [
        "1 Giant Leap feat. Robbie Williams & Maxi Jazz",  # Direct from AcoustID
        "1 Giant Leap feat. Robbie Williams and Maxi Jazz",  # After MusicBrainz
    ]
    assert metadata["title"] == "My Culture"
    assert metadata["album"] == "1 Giant Leap"
    assert metadata["musicbrainzrecordingid"] == ("b366689f-4b81-4f1f-974b-3dff361d45a1")

    # Verify multiple artist IDs are returned for multi-artist track
    assert len(metadata["musicbrainzartistid"]) == 3
    expected_artist_ids = [
        "3eff5a3a-b011-4da3-81fe-bc8d4a11b28c",  # 1 Giant Leap
        "db4624cf-0e44-481e-a9dc-2142b833ec2f",  # Robbie Williams
        "debd408d-72b3-4c14-a0eb-dd4fe526e240",  # Maxi Jazz
    ]
    assert set(metadata["musicbrainzartistid"]) == set(expected_artist_ids)
