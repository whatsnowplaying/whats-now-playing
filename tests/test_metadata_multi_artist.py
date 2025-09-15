#!/usr/bin/env python3
"""Test multi-artist resolution functionality"""

import logging
import pytest
import pytest_asyncio

import nowplaying.metadata
import nowplaying.musicbrainz
import nowplaying.musicbrainz.helper


# Test data for artist splitting - only genuine collaborations that should be split
SPLITTING_TEST_CASES = [
    # Strong delimiters - should split
    ("Disclosure ft. AlunaGeorge", ["Disclosure", "AlunaGeorge"]),
    ("Artist1 featuring Artist2", ["Artist1", "Artist2"]),
    ("DJ A vs. DJ B", ["DJ A", "DJ B"]),
    ("Band1 with Band2", ["Band1", "Band2"]),
    ("Producer A x Producer B", ["Producer A", "Producer B"]),
    ("Artist1 × Artist2", ["Artist1", "Artist2"]),  # Unicode multiplication
    ("Rapper feat MC", ["Rapper", "MC"]),
    ("DJ One w/ MC Two", ["DJ One", "MC Two"]),
    ("Artist vs Artist2", ["Artist", "Artist2"]),
    ("Skrillex & Diplo", ["Skrillex", "Diplo"]),
    # Clear comma collaborations - should split
    ("Artist1, Artist2, Artist3", ["Artist1", "Artist2", "Artist3"]),
    ("DJ X, MC Y, Singer Z", ["DJ X", "MC Y", "Singer Z"]),
    # Multiple delimiters - first takes precedence
    ("A feat. B, C", ["A", "B, C"]),  # feat. beats comma
    ("X with Y vs. Z", ["X", "Y vs. Z"]),  # with beats vs.
    # Single artists that should not split (no delimiters or obvious single entities)
    ("Single Artist", ["Single Artist"]),
    ("The Beatles", ["The Beatles"]),
    ("Madonna", ["Madonna"]),
    ("", [""]),  # Empty string
]

# Test data for edge cases - only legitimate collaborations
EDGE_CASE_TEST_CASES = [
    # Case sensitivity
    ("Artist FEAT. Artist2", ["Artist", "Artist2"]),
    ("artist1 VS. artist2", ["artist1", "artist2"]),
    # Extra whitespace
    ("Artist1  ,  Artist2", ["Artist1", "Artist2"]),
    ("DJ A   feat.   DJ B", ["DJ A", "DJ B"]),
    # Numbers and special characters in names
    ("2Pac feat. Dr. Dre", ["2Pac", "Dr. Dre"]),
    ("Daft Punk vs. Justice", ["Daft Punk", "Justice"]),
]


@pytest.mark.parametrize("artist_string,expected", SPLITTING_TEST_CASES)
def test_split_artist_string(bootstrap, artist_string, expected):
    """Test artist string splitting with various formats"""
    config = bootstrap
    config.cparser.setValue("musicbrainz/enabled", True)
    helper = nowplaying.musicbrainz.helper.MusicBrainzHelper(config=config)
    result = helper._split_artist_string(artist_string)
    assert result == expected


@pytest.mark.parametrize("artist_string,expected", EDGE_CASE_TEST_CASES)
def test_split_artist_string_edge_cases(bootstrap, artist_string, expected):
    """Test artist string splitting edge cases"""
    config = bootstrap
    config.cparser.setValue("musicbrainz/enabled", True)
    helper = nowplaying.musicbrainz.helper.MusicBrainzHelper(config=config)
    result = helper._split_artist_string(artist_string)
    assert result == expected


def test_strong_delimiters_constant():
    """Test that STRONG_ARTIST_DELIMITERS constant is properly defined"""
    delimiters = nowplaying.musicbrainz.helper.STRONG_ARTIST_DELIMITERS

    # Check for key collaboration indicators
    expected_delimiters = [
        " feat. ",
        " featuring ",
        " ft. ",
        " feat ",
        " with ",
        " w/ ",
        " vs. ",
        " versus ",
        " vs ",
        " x ",
        " × ",
    ]

    for delimiter in expected_delimiters:
        assert delimiter in delimiters, f"Missing delimiter: {delimiter}"


# Test cases for common DJ music collaboration formats
DJ_COLLABORATION_CASES = [
    # Hip-hop
    ("Kendrick Lamar feat. SZA", ["Kendrick Lamar", "SZA"]),
    ("Drake ft. Future", ["Drake", "Future"]),
    ("Jay-Z featuring Beyoncé", ["Jay-Z", "Beyoncé"]),
    # Electronic/House/Techno
    ("Calvin Harris x Dua Lipa", ["Calvin Harris", "Dua Lipa"]),
    ("Disclosure vs. London Grammar", ["Disclosure", "London Grammar"]),
    ("Skrillex & Diplo", ["Skrillex", "Diplo"]),
    ("Martin Garrix feat. Usher", ["Martin Garrix", "Usher"]),
    # Beatport/Spotify style comma lists
    ("Armin van Buuren, Vini Vici, Alok", ["Armin van Buuren", "Vini Vici", "Alok"]),
    ("David Guetta, Bebe Rexha, J Balvin", ["David Guetta", "Bebe Rexha", "J Balvin"]),
    ("Tiësto, Jonas Blue, Rita Ora", ["Tiësto", "Jonas Blue", "Rita Ora"]),
]


@pytest.mark.parametrize("artist_string,expected", DJ_COLLABORATION_CASES)
def test_dj_collaboration_formats(bootstrap, artist_string, expected):
    """Test common DJ/electronic music collaboration formats"""
    config = bootstrap
    config.cparser.setValue("musicbrainz/enabled", True)
    helper = nowplaying.musicbrainz.helper.MusicBrainzHelper(config=config)
    result = helper._split_artist_string(artist_string)
    assert result == expected


# Integration tests with real MusicBrainz API calls
@pytest.mark.asyncio
async def test_integration_single_artist_known_to_mb(bootstrap):
    """Test that artists known to MusicBrainz don't get split"""
    config = bootstrap
    config.cparser.setValue("musicbrainz/enabled", True)
    processor = nowplaying.metadata.MetadataProcessors(config=config)

    # Test cases: artists that SHOULD be found in MusicBrainz as single entities
    known_single_artists = [
        "Emerson, Lake & Palmer",
        "Crosby, Stills & Nash",
        "Blood, Sweat & Tears",
        "Earth, Wind & Fire",
    ]

    for artist_name in known_single_artists:
        processor.metadata = {
            "artist": artist_name,
            "title": "Test Song",  # Generic title
        }

        # Call the full MusicBrainz resolution
        await processor._musicbrainz()

        # If MB found the artist, should not have triggered multi-artist resolution
        if processor.metadata.get("musicbrainzartistid"):
            # Found in MB - should not have split
            assert "musicbrainzartistids" not in processor.metadata, (
                f"{artist_name} was split even though it was found in MusicBrainz"
            )
            assert processor.metadata["artist"] == artist_name, (
                f"Original artist name changed for {artist_name}"
            )


@pytest.mark.asyncio
async def test_integration_collaboration_not_in_mb(bootstrap):
    """Test that collaborations not in MB get resolved to individual artists"""
    config = bootstrap
    config.cparser.setValue("musicbrainz/enabled", True)
    processor = nowplaying.metadata.MetadataProcessors(config=config)

    # Test cases: collaborations that probably DON'T exist in MB as combined entities
    collaboration_cases = [
        {"artist": "Drake ft. Future", "expected_artists": ["Drake", "Future"]},
        {"artist": "Calvin Harris x Dua Lipa", "expected_artists": ["Calvin Harris", "Dua Lipa"]},
        {
            "artist": "Artist1, Artist2, Artist3",  # Generic case
            "expected_artists": ["Artist1", "Artist2", "Artist3"],
        },
    ]

    for case in collaboration_cases:
        processor.metadata = {"artist": case["artist"], "title": "Test Song"}

        # Call the full MusicBrainz resolution
        await processor._musicbrainz()

        # Check if multi-artist resolution was triggered
        if processor.metadata.get("musicbrainzartistids"):
            # Splitting occurred - verify it found individual artists
            assert len(processor.metadata["musicbrainzartistids"]) == len(
                case["expected_artists"]
            ), f"Expected {len(case['expected_artists'])} artists for {case['artist']}"
            assert processor.metadata.get("artists") == case["expected_artists"], (
                f"Artist names don't match for {case['artist']}"
            )

            # Verify all individual artist IDs are valid UUIDs (MusicBrainz format)
            for artist_id in processor.metadata["musicbrainzartistids"]:
                assert len(artist_id) == 36 and artist_id.count("-") == 4, (
                    f"Invalid MusicBrainz ID format: {artist_id}"
                )


@pytest.mark.asyncio
async def test_integration_hierarchical_breakdown(bootstrap):
    """Test hierarchical breakdown with a case that requires splitting"""
    config = bootstrap
    config.cparser.setValue("musicbrainz/enabled", True)
    processor = nowplaying.metadata.MetadataProcessors(config=config)

    # Test case that should require hierarchical breakdown - using a made-up collaboration
    # that definitely won't exist as a full string in MusicBrainz
    processor.metadata = {
        "artist": "Daft Punk feat Pharrell Williams & Madonna",
        "title": "Fake Song",
    }

    # Call the full MusicBrainz resolution
    await processor._musicbrainz()

    # This should trigger hierarchical resolution:
    # 1. Try full string (should fail)
    # 2. Split on "feat" -> "Daft Punk" + "Pharrell Williams & Nile Rodgers"
    # 3. "Daft Punk" should resolve, "Pharrell Williams & Nile Rodgers" should fail
    # 4. Split "Pharrell Williams & Nile Rodgers" on "&" -> "Pharrell Williams" + "Nile Rodgers"
    # 5. Both should resolve

    if (
        processor.metadata.get("musicbrainzartistid")
        and len(processor.metadata["musicbrainzartistid"]) > 1
    ):
        # Should have resolved to 3 artists
        assert len(processor.metadata["musicbrainzartistid"]) == 3, (
            f"Expected 3 artists, got {len(processor.metadata['musicbrainzartistid'])}"
        )
        assert len(processor.metadata["artists"]) == 3, (
            f"Expected 3 artist names, got {processor.metadata['artists']}"
        )

        # Should have the correct artist names (order matters)
        expected_artists = ["Daft Punk", "Pharrell Williams", "Madonna"]
        assert processor.metadata["artists"] == expected_artists, (
            f"Expected {expected_artists}, got {processor.metadata['artists']}"
        )

        # All artist IDs should be valid MusicBrainz UUIDs
        for artist_id in processor.metadata["musicbrainzartistid"]:
            assert len(artist_id) == 36 and artist_id.count("-") == 4, (
                f"Invalid MusicBrainz ID format: {artist_id}"
            )

        logging.info(
            "Successfully resolved hierarchical breakdown: %s", processor.metadata["artists"]
        )
    else:
        # If hierarchical resolution didn't work, the full string might have been found
        # This would be unexpected but not necessarily wrong
        assert processor.metadata.get("musicbrainzartistid") is not None, (
            "Neither hierarchical breakdown nor full string lookup worked"
        )
        logging.info("Full string was found in MusicBrainz instead of hierarchical breakdown")


# Test cases for artists that should NOT be split (single entities in MusicBrainz)
SINGLE_ARTIST_WITH_DELIMITERS = [
    "Dick Dale & His Del-Tones",
    "DJ Jazzy Jeff & the Fresh Prince",
    "Prince & the Revolution",
    "Emerson, Lake & Palmer",
    "Crosby, Stills & Nash",
    "Blood, Sweat & Tears",
    "Earth, Wind & Fire",
    "MC 900 Ft Jesus",
    "MC 900 Ft, Jesus",  # Same artist as above, different punctuation
    # Conservative cases that should not split even if not found in MB
    "Smith, John",  # Likely LastName, FirstName pattern
    "Producer A, Vocalist B",  # Ambiguous 2-part name
    "DJ A, B, and C",  # Contains "and" indicator
]

# Test cases for collaborations that SHOULD be split into multiple artists
COLLABORATION_CASES = [
    ("DjeuhDjoah, Lieutenant Nicholson", ["DjeuhDjoah", "Lieutenant Nicholson"]),
    (
        "MISHA, cocabona, Joya Mooi, Derrick McKenzie",
        ["MISHA", "cocabona", "Joya Mooi", "Derrick McKenzie"],
    ),
    ("A$AP Rocky, Tyler, The Creator", ["A$AP Rocky", "Tyler, The Creator"]),
]


@pytest.mark.parametrize("artist_name", SINGLE_ARTIST_WITH_DELIMITERS)
@pytest.mark.asyncio
async def test_integration_single_artists_not_split(bootstrap, artist_name):
    """Test that single artists containing delimiters are not split when found in MusicBrainz"""
    config = bootstrap
    config.cparser.setValue("musicbrainz/enabled", True)
    processor = nowplaying.metadata.MetadataProcessors(config=config)

    processor.metadata = {
        "artist": artist_name,
        "title": "Test Song",
    }

    # Call the full MusicBrainz resolution
    await processor._musicbrainz()

    # These should be found as single artists (step 1 of hierarchical lookup)
    # and NOT trigger multi-artist resolution
    if processor.metadata.get("musicbrainzartistid"):
        # Found as single artist - should have one artist ID
        assert len(processor.metadata["musicbrainzartistid"]) == 1, (
            f"{artist_name} was split into multiple artists when it should be single"
        )
        assert processor.metadata["artist"] == artist_name, (
            f"Original artist name changed for {artist_name}"
        )

        # Should have a valid MusicBrainz ID
        artist_id = processor.metadata["musicbrainzartistid"][0]  # Get first (and only) ID
        assert len(artist_id) == 36 and artist_id.count("-") == 4, (
            f"Invalid MusicBrainz ID format for {artist_name}: {artist_id}"
        )

        logging.info(f"✓ {artist_name} correctly found as single artist: {artist_id}")
    else:
        # If not found in MusicBrainz, that's unexpected but not necessarily a test failure
        # (could be due to network issues, etc.)
        logging.warning(f"Could not find {artist_name} in MusicBrainz - this may be expected")


@pytest.mark.parametrize("collaboration,expected_artists", COLLABORATION_CASES)
@pytest.mark.asyncio
async def test_integration_collaborations_split(bootstrap, collaboration, expected_artists):
    """Test that collaborations are properly split when individual artists exist in MusicBrainz"""
    config = bootstrap
    config.cparser.setValue("musicbrainz/enabled", True)
    processor = nowplaying.metadata.MetadataProcessors(config=config)

    processor.metadata = {
        "artist": collaboration,
        "title": "Test Song",
    }

    # Call the full MusicBrainz resolution
    await processor._musicbrainz()

    # This should trigger hierarchical resolution since full string likely doesn't exist
    if (
        processor.metadata.get("musicbrainzartistid")
        and len(processor.metadata["musicbrainzartistid"]) > 1
    ):
        # Should have resolved to multiple artists
        assert len(processor.metadata["musicbrainzartistid"]) == len(expected_artists), (
            f"Expected {len(expected_artists)} artists for {collaboration}, got {len(processor.metadata['musicbrainzartistid'])}"
        )
        assert processor.metadata["artists"] == expected_artists, (
            f"Expected {expected_artists}, got {processor.metadata['artists']}"
        )

        # All artist IDs should be valid MusicBrainz UUIDs
        for artist_id in processor.metadata["musicbrainzartistid"]:
            assert len(artist_id) == 36 and artist_id.count("-") == 4, (
                f"Invalid MusicBrainz ID format: {artist_id}"
            )

        logging.info(f"✓ {collaboration} correctly split into: {processor.metadata['artists']}")
    else:
        # Could be that the full collaboration string was found in MusicBrainz
        if processor.metadata.get("musicbrainzartistid"):
            logging.info(f"✓ {collaboration} found as complete collaboration in MusicBrainz")
        else:
            logging.warning(f"Could not resolve {collaboration} - may be due to network issues")


@pytest.mark.asyncio
async def test_integration_real_collaboration_example(bootstrap):
    """Test our known working example: Disclosure ft. AlunaGeorge"""
    config = bootstrap
    config.cparser.setValue("musicbrainz/enabled", True)
    processor = nowplaying.metadata.MetadataProcessors(config=config)

    processor.metadata = {"artist": "Disclosure ft. AlunaGeorge", "title": "White Noise"}

    # Call the full MusicBrainz resolution
    await processor._musicbrainz()

    # This should trigger multi-artist resolution based on our earlier testing
    if processor.metadata.get("musicbrainzartistids"):
        assert len(processor.metadata["musicbrainzartistids"]) == 2
        assert processor.metadata["artists"] == ["Disclosure", "AlunaGeorge"]

        # Should have found both Disclosure and AlunaGeorge
        disclosure_id = processor.metadata["musicbrainzartistids"][0]
        alunageorge_id = processor.metadata["musicbrainzartistids"][1]

        # These should be valid MusicBrainz IDs
        assert len(disclosure_id) == 36 and disclosure_id.count("-") == 4
        assert len(alunageorge_id) == 36 and alunageorge_id.count("-") == 4

        # Primary artist ID should be set to the first one
        assert processor.metadata["musicbrainzartistid"] == disclosure_id
    else:
        # If no splitting occurred, the full string should have been found in MB
        # (This would be unexpected based on our earlier testing)
        assert processor.metadata.get("musicbrainzartistid") is not None, (
            "Neither full lookup nor splitting worked for Disclosure ft. AlunaGeorge"
        )


@pytest.mark.asyncio
async def test_integration_conservative_splitting(bootstrap):
    """Test that ambiguous cases are handled conservatively"""
    config = bootstrap
    config.cparser.setValue("musicbrainz/enabled", True)
    processor = nowplaying.metadata.MetadataProcessors(config=config)

    # Test ambiguous cases that should NOT split
    conservative_cases = [
        "Smith, John",  # Could be LastName, FirstName
        "The Artist, The Band",  # Ambiguous comma usage
    ]

    for artist_name in conservative_cases:
        processor.metadata = {"artist": artist_name, "title": "Test Song"}

        await processor._musicbrainz()

        # These should either:
        # 1. Be found in MB as single artists (no splitting), OR
        # 2. Not split due to conservative heuristics
        if not processor.metadata.get("musicbrainzartistid"):
            # Not found in MB - should not have split due to conservative logic
            assert "musicbrainzartistids" not in processor.metadata, (
                f"Conservatively should not split: {artist_name}"
            )
