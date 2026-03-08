#!/usr/bin/env python3
"""Unit tests for nowplaying/metadata/processors.py targeting uncovered code paths."""

import unittest.mock

import pytest

import nowplaying.metadata
import nowplaying.metadata.processors


@pytest.mark.asyncio
async def test_filename_stem_as_title(bootstrap):
    """When filename has no title metadata, use the filename stem as title."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {"filename": "/some/path/my_cool_song.mp3"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["title"] == "my_cool_song"
    assert "artist" not in metadataout or not metadataout.get("artist")


@pytest.mark.asyncio
async def test_filename_stem_artist_dash_title(bootstrap):
    """When filename is 'Artist - Title.mp3' with no metadata, split into artist and title."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {"filename": "/some/path/Pet Shop Boys - West End Girls.mp3"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["artist"] == "Pet Shop Boys"
    assert metadataout["title"] == "West End Girls"


@pytest.mark.asyncio
async def test_duplicate_artist_in_title_removed(bootstrap):
    """When artist name appears in title as 'Artist - Title', strip it."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {"artist": "Nine Inch Nails", "title": "Nine Inch Nails - Hurt"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["title"] == "Hurt"
    assert metadataout["artist"] == "Nine Inch Nails"


@pytest.mark.asyncio
async def test_shortbio_promoted_to_longbio(bootstrap):
    """When only artistshortbio is set, it gets copied to artistlongbio."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "artist": "Test Artist",
        "title": "Test Song",
        "artistshortbio": "Short bio only.",
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["artistlongbio"] == "Short bio only."


@pytest.mark.asyncio
async def test_url_normalize_keeps_bad_url(bootstrap):
    """Invalid URLs that fail normalization should be kept as-is."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {"artist": "Test", "artistwebsites": ["not://a/valid/url!@#$%"]}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout.get("artistwebsites")


@pytest.mark.asyncio
async def test_skipplugins_prevents_artist_extras(bootstrap):
    """skipplugins=True should prevent artist extras plugins from running."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("artistextras/enabled", True)
    metadatain = {"artist": "Test Artist", "title": "Test Song"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain, skipplugins=True
    )
    assert metadataout["artist"] == "Test Artist"
    assert metadataout["title"] == "Test Song"


@pytest.mark.asyncio
async def test_musicbrainz_skip_when_already_have_key_identifiers(bootstrap):
    """MusicBrainz lookup should be skipped when all key identifiers are already present."""
    config = bootstrap
    config.cparser.setValue("musicbrainz/enabled", True)
    config.cparser.setValue("acoustidmb/enabled", False)
    metadatain = {
        "artist": "Test Artist",
        "title": "Test Song",
        "musicbrainzartistid": ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"],
        "musicbrainzrecordingid": "2d7f08e1-be1c-4b86-b725-6e675b7b6de0",
        "isrc": ["USXX11234567"],
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["musicbrainzartistid"] == ["b7ffd2af-418f-4be2-bdd1-22f8b48613da"]


@pytest.mark.asyncio
async def test_getmoremetadata_with_none_metadata(bootstrap):
    """getmoremetadata should handle None metadata gracefully."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=None
    )
    assert isinstance(metadataout, dict)


@pytest.mark.asyncio
async def test_date_zero_removed(bootstrap):
    """A date of '0' should be removed from metadata."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {"date": "0"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert "date" not in metadataout


@pytest.mark.asyncio
async def test_tinytag_exception_handled_gracefully(bootstrap):
    """If TinyTagRunner raises, the exception should be caught and processing continues."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {"artist": "Test Artist", "title": "Test Song"}

    with unittest.mock.patch(
        "nowplaying.metadata.tinytag_runner.TinyTagRunner.process",
        side_effect=RuntimeError("tinytag exploded"),
    ):
        metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
            metadata=metadatain
        )
    assert metadataout["artist"] == "Test Artist"
    assert metadataout["title"] == "Test Song"


def test_recognition_replacement_no_addmeta(bootstrap):
    """recognition_replacement returns metadata unchanged when addmeta is None/empty."""
    config = bootstrap
    metadata = {"artist": "Test", "title": "Song"}
    result = nowplaying.metadata.processors.recognition_replacement(
        config=config, metadata=metadata, addmeta=None
    )
    assert result == metadata


def test_recognition_replacement_no_metadata_no_addmeta(bootstrap):
    """recognition_replacement returns empty dict when both are None."""
    config = bootstrap
    result = nowplaying.metadata.processors.recognition_replacement(
        config=config, metadata=None, addmeta=None
    )
    assert result == {}


def test_recognition_replacement_fills_missing(bootstrap):
    """recognition_replacement fills in metadata fields not already present."""
    config = bootstrap
    config.cparser.setValue("recognition/replaceartist", False)
    metadata = {"artist": "Original Artist"}
    addmeta = {"artist": "New Artist", "album": "New Album"}
    result = nowplaying.metadata.processors.recognition_replacement(
        config=config, metadata=metadata, addmeta=addmeta
    )
    assert result["artist"] == "Original Artist"
    assert result["album"] == "New Album"


def test_recognition_replacement_replaces_when_configured(bootstrap):
    """recognition_replacement replaces artist/title/websites when configured."""
    config = bootstrap
    config.cparser.setValue("recognition/replaceartist", True)
    metadata = {"artist": "Original Artist", "title": "Original Title"}
    addmeta = {"artist": "New Artist"}
    result = nowplaying.metadata.processors.recognition_replacement(
        config=config, metadata=metadata, addmeta=addmeta
    )
    assert result["artist"] == "New Artist"


@pytest.mark.asyncio
async def test_bio_dedup_disabled_no_biohistory(bootstrap):
    """When bio_dedup is disabled, _biohistory should be None."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("artistextras/bio_dedup", False)
    processor = nowplaying.metadata.MetadataProcessors(config=config)
    assert processor._biohistory is None  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_bio_dedup_enabled_creates_biohistory(bootstrap):
    """When bio_dedup is enabled, _biohistory should be created."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("artistextras/bio_dedup", True)
    processor = nowplaying.metadata.MetadataProcessors(config=config)
    assert processor._biohistory is not None  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_filename_with_title_not_overridden(bootstrap):
    """When title already present, filename stem should NOT override it."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {
        "filename": "/some/path/Actual Filename.mp3",
        "title": "Real Title From Tags",
    }
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["title"] == "Real Title From Tags"


@pytest.mark.asyncio
async def test_duplicate_artist_no_strip_when_no_dash(bootstrap):
    """Artist name in title without ' - ' separator should NOT be stripped."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {"artist": "Madonna", "title": "Madonna Song Title"}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["title"] == "Madonna Song Title"
