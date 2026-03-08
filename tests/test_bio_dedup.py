#!/usr/bin/env python3
"""Tests for artist bio deduplication feature"""

import unittest.mock

import pytest

import nowplaying.metadata.biohistory
import nowplaying.metadata.processors


# ── ArtistBioHistory unit tests ───────────────────────────────────────────────


@pytest.fixture
def tmpbiohistory(bootstrap, tmp_path):  # pylint: disable=redefined-outer-name,unused-argument
    """ArtistBioHistory instance backed by a temp directory."""
    db_path = tmp_path / "artistbio" / "artistbio.db"
    with unittest.mock.patch.object(
        nowplaying.metadata.biohistory.ArtistBioHistory,
        "_get_database_path",
        return_value=db_path,
    ):
        history = nowplaying.metadata.biohistory.ArtistBioHistory("session-test")
    yield history


@pytest.mark.asyncio
async def test_new_artist_not_shown(tmpbiohistory):  # pylint: disable=redefined-outer-name
    """Artist not yet seen returns False."""
    result = await tmpbiohistory.has_been_shown("Madonna")
    assert result is False


@pytest.mark.asyncio
async def test_record_then_shown(tmpbiohistory):  # pylint: disable=redefined-outer-name
    """Recording an artist then querying returns True."""
    await tmpbiohistory.record_shown("Madonna", None, "Some bio text")
    result = await tmpbiohistory.has_been_shown("Madonna")
    assert result is True


@pytest.mark.asyncio
async def test_mbid_match(tmpbiohistory):  # pylint: disable=redefined-outer-name
    """MBID-based matching works."""
    mbid = "79239441-bfd5-4981-a70c-55c3f15c1287"
    await tmpbiohistory.record_shown("Madonna", mbid, None)
    result = await tmpbiohistory.has_been_shown("Madonna", mbid)
    assert result is True


@pytest.mark.asyncio
async def test_has_been_shown_mbid_finds_name_only_entry(tmpbiohistory):  # pylint: disable=redefined-outer-name
    """has_been_shown with MBID finds an existing name-only record."""
    await tmpbiohistory.record_shown("Madonna", None, "bio")
    # Querying with an MBID should still find the name-only record via the OR clause
    result = await tmpbiohistory.has_been_shown("Madonna", "some-mbid")
    assert result is True


@pytest.mark.asyncio
async def test_session_isolation(bootstrap, tmp_path):  # pylint: disable=redefined-outer-name,unused-argument
    """Different session IDs are isolated from each other."""
    db_path = tmp_path / "artistbio" / "artistbio.db"
    with unittest.mock.patch.object(
        nowplaying.metadata.biohistory.ArtistBioHistory,
        "_get_database_path",
        return_value=db_path,
    ):
        session_a = nowplaying.metadata.biohistory.ArtistBioHistory("session-a")
        session_b = nowplaying.metadata.biohistory.ArtistBioHistory("session-b")

    await session_a.record_shown("Madonna", None, "bio")

    assert await session_b.has_been_shown("Madonna") is False
    assert await session_a.has_been_shown("Madonna") is True


@pytest.mark.asyncio
async def test_case_insensitive_name(tmpbiohistory):  # pylint: disable=redefined-outer-name
    """Artist name lookup is case-insensitive (COLLATE NOCASE)."""
    await tmpbiohistory.record_shown("madonna", None, None)
    assert await tmpbiohistory.has_been_shown("MADONNA") is True
    assert await tmpbiohistory.has_been_shown("Madonna") is True


@pytest.mark.asyncio
async def test_multiple_artists_independent(tmpbiohistory):  # pylint: disable=redefined-outer-name
    """Recording one artist does not affect another."""
    await tmpbiohistory.record_shown("Madonna", None, "bio")
    assert await tmpbiohistory.has_been_shown("Prince") is False


@pytest.mark.asyncio
async def test_record_shown_none_bio_text(tmpbiohistory):  # pylint: disable=redefined-outer-name
    """record_shown handles None bio_text gracefully."""
    await tmpbiohistory.record_shown("Madonna", None, None)
    assert await tmpbiohistory.has_been_shown("Madonna") is True


@pytest.mark.asyncio
async def test_idempotent_record(tmpbiohistory):  # pylint: disable=redefined-outer-name
    """Recording the same artist twice (INSERT OR REPLACE) does not raise."""
    await tmpbiohistory.record_shown("Madonna", None, "bio 1")
    await tmpbiohistory.record_shown("Madonna", None, "bio 2")
    assert await tmpbiohistory.has_been_shown("Madonna") is True


# ── MetadataProcessors bio dedup integration tests ───────────────────────────


@pytest.fixture
def bioprocessor(bootstrap, tmp_path):
    """MetadataProcessors with bio_dedup enabled, using a temp DB."""
    config = bootstrap
    config.cparser.setValue("artistextras/bio_dedup", True)
    db_path = tmp_path / "artistbio" / "artistbio.db"
    with unittest.mock.patch.object(
        nowplaying.metadata.biohistory.ArtistBioHistory,
        "_get_database_path",
        return_value=db_path,
    ):
        processor = nowplaying.metadata.processors.MetadataProcessors(config=config)
    yield processor


@pytest.fixture
def bioprocessor_disabled(bootstrap):
    """MetadataProcessors with bio_dedup disabled."""
    config = bootstrap
    config.cparser.setValue("artistextras/bio_dedup", False)
    processor = nowplaying.metadata.processors.MetadataProcessors(config=config)
    yield processor


@pytest.mark.asyncio
async def test_select_bio_artist_no_biohistory(bioprocessor_disabled):  # pylint: disable=redefined-outer-name
    """When bio_dedup is disabled, _select_bio_artist returns the original artist."""
    bioprocessor_disabled.metadata = {"artist": "Madonna"}
    result = await bioprocessor_disabled._select_bio_artist()  # pylint: disable=protected-access
    assert result == ("Madonna", None)


@pytest.mark.asyncio
async def test_select_bio_artist_no_artist(bioprocessor):  # pylint: disable=redefined-outer-name
    """Missing artist field returns (None, None)."""
    bioprocessor.metadata = {}
    result = await bioprocessor._select_bio_artist()  # pylint: disable=protected-access
    assert result == (None, None)


@pytest.mark.asyncio
async def test_select_bio_artist_unseen(bioprocessor):  # pylint: disable=redefined-outer-name
    """Unseen artist is returned unchanged."""
    bioprocessor.metadata = {"artist": "Madonna"}
    result = await bioprocessor._select_bio_artist()  # pylint: disable=protected-access
    assert result == ("Madonna", None)


@pytest.mark.asyncio
async def test_select_bio_artist_with_mbid(bioprocessor):  # pylint: disable=redefined-outer-name
    """MBID is returned alongside the artist name when available."""
    bioprocessor.metadata = {
        "artist": "Madonna",
        "musicbrainzartistid": ["79239441-bfd5-4981-a70c-55c3f15c1287"],
    }
    artist, mbid = await bioprocessor._select_bio_artist()  # pylint: disable=protected-access
    assert artist == "Madonna"
    assert mbid == "79239441-bfd5-4981-a70c-55c3f15c1287"


@pytest.mark.asyncio
async def test_select_bio_artist_all_seen(bioprocessor):  # pylint: disable=redefined-outer-name
    """(None, None) returned when all artists have been seen this session."""
    await bioprocessor._biohistory.record_shown("Madonna", None, "bio")  # pylint: disable=protected-access
    bioprocessor.metadata = {"artist": "Madonna"}
    result = await bioprocessor._select_bio_artist()  # pylint: disable=protected-access
    assert result == (None, None)


@pytest.mark.asyncio
async def test_select_bio_artist_second_unseen(bioprocessor):  # pylint: disable=redefined-outer-name
    """Second artist is selected when the first has already been shown."""
    await bioprocessor._biohistory.record_shown("Madonna", None, "bio")  # pylint: disable=protected-access
    bioprocessor.metadata = {"artist": "Madonna feat. Prince"}
    artist, mbid = await bioprocessor._select_bio_artist()  # pylint: disable=protected-access
    assert artist == "Prince"
    assert mbid is None


@pytest.mark.asyncio
async def test_select_bio_artist_second_unseen_with_mbids(bioprocessor):  # pylint: disable=redefined-outer-name
    """Second artist's MBID is returned when it is the first unseen artist."""
    await bioprocessor._biohistory.record_shown("Madonna", "mbid-madonna", "bio")  # pylint: disable=protected-access
    bioprocessor.metadata = {
        "artist": "Madonna feat. Prince",
        "musicbrainzartistid": ["mbid-madonna", "mbid-prince"],
    }
    artist, mbid = await bioprocessor._select_bio_artist()  # pylint: disable=protected-access
    assert artist == "Prince"
    assert mbid == "mbid-prince"


@pytest.mark.asyncio
async def test_bio_dedup_setup_disabled_passthrough(bioprocessor_disabled):  # pylint: disable=redefined-outer-name
    """When disabled, setup returns original artist with suppress_bio=False."""
    bioprocessor_disabled.metadata = {"artist": "Madonna"}
    bio_artist, bio_mbid, suppress_bio, orig_artist, _ = (
        await bioprocessor_disabled._bio_dedup_setup()  # pylint: disable=protected-access
    )
    assert bio_artist == "Madonna"
    assert bio_mbid is None
    assert suppress_bio is False
    assert orig_artist == "Madonna"


@pytest.mark.asyncio
async def test_bio_dedup_setup_first_artist_no_swap(bioprocessor):  # pylint: disable=redefined-outer-name
    """First unseen artist: no metadata swap, suppress_bio=False."""
    bioprocessor.metadata = {"artist": "Madonna"}
    bio_artist, _, suppress_bio, _, _ = (
        await bioprocessor._bio_dedup_setup()  # pylint: disable=protected-access
    )
    assert bio_artist == "Madonna"
    assert suppress_bio is False
    assert bioprocessor.metadata["artist"] == "Madonna"


@pytest.mark.asyncio
async def test_bio_dedup_setup_suppress_when_all_seen(bioprocessor):  # pylint: disable=redefined-outer-name
    """suppress_bio=True when all artists in the track have been seen."""
    await bioprocessor._biohistory.record_shown("Madonna", None, "bio")  # pylint: disable=protected-access
    bioprocessor.metadata = {"artist": "Madonna"}
    bio_artist, _, suppress_bio, _, _ = (
        await bioprocessor._bio_dedup_setup()  # pylint: disable=protected-access
    )
    assert bio_artist is None
    assert suppress_bio is True


@pytest.mark.asyncio
async def test_bio_dedup_setup_swaps_to_unseen_artist(bioprocessor):  # pylint: disable=redefined-outer-name
    """Metadata artist is temporarily swapped to the first unseen artist."""
    await bioprocessor._biohistory.record_shown("Madonna", None, "bio")  # pylint: disable=protected-access
    bioprocessor.metadata = {
        "artist": "Madonna feat. Prince",
        "musicbrainzartistid": ["mbid-madonna", "mbid-prince"],
    }
    bio_artist, bio_mbid, suppress_bio, orig_artist, _ = (
        await bioprocessor._bio_dedup_setup()  # pylint: disable=protected-access
    )
    assert suppress_bio is False
    assert bio_artist == "Prince"
    assert bio_mbid == "mbid-prince"
    assert bioprocessor.metadata["artist"] == "Prince"
    assert bioprocessor.metadata["musicbrainzartistid"] == ["mbid-prince"]
    assert orig_artist == "Madonna feat. Prince"


@pytest.mark.asyncio
async def test_bio_dedup_restore_records_bio(bioprocessor):  # pylint: disable=redefined-outer-name
    """_bio_dedup_restore records the bio artist as shown."""
    bioprocessor.metadata = {"artist": "Madonna", "artistlongbio": "Long bio"}
    await bioprocessor._bio_dedup_restore(  # pylint: disable=protected-access
        "Madonna", None, False, "Madonna", None
    )
    assert await bioprocessor._biohistory.has_been_shown("Madonna") is True  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_bio_dedup_restore_suppresses_bio_fields(bioprocessor):  # pylint: disable=redefined-outer-name
    """_bio_dedup_restore removes bio fields when suppress_bio=True."""
    bioprocessor.metadata = {
        "artist": "Madonna",
        "artistlongbio": "Some bio",
        "artistshortbio": "Short bio",
    }
    await bioprocessor._bio_dedup_restore(  # pylint: disable=protected-access
        None, None, True, "Madonna", None
    )
    assert "artistlongbio" not in bioprocessor.metadata
    assert "artistshortbio" not in bioprocessor.metadata


@pytest.mark.asyncio
async def test_bio_dedup_restore_does_not_record_when_suppressed(bioprocessor):  # pylint: disable=redefined-outer-name
    """_bio_dedup_restore does not record a bio when suppress_bio=True."""
    bioprocessor.metadata = {"artist": "Madonna"}
    await bioprocessor._bio_dedup_restore(  # pylint: disable=protected-access
        None, None, True, "Madonna", None
    )
    assert await bioprocessor._biohistory.has_been_shown("Madonna") is False  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_bio_dedup_restore_restores_original_artist(bioprocessor):  # pylint: disable=redefined-outer-name
    """_bio_dedup_restore puts the original artist back after a swap."""
    bioprocessor.metadata = {
        "artist": "Prince",
        "musicbrainzartistid": ["mbid-prince"],
        "artistlongbio": "Prince bio",
    }
    await bioprocessor._bio_dedup_restore(  # pylint: disable=protected-access
        "Prince",
        "mbid-prince",
        False,
        "Madonna feat. Prince",
        ["mbid-madonna", "mbid-prince"],
    )
    assert bioprocessor.metadata["artist"] == "Madonna feat. Prince"
    assert bioprocessor.metadata["musicbrainzartistid"] == ["mbid-madonna", "mbid-prince"]


@pytest.mark.asyncio
async def test_bio_dedup_restore_no_biohistory_noop(bioprocessor_disabled):  # pylint: disable=redefined-outer-name
    """_bio_dedup_restore is a no-op when bio_dedup is disabled."""
    bioprocessor_disabled.metadata = {"artist": "Madonna", "artistlongbio": "bio"}
    await bioprocessor_disabled._bio_dedup_restore(  # pylint: disable=protected-access
        "Madonna", None, False, "Madonna", None
    )
    # Bio must NOT be stripped when dedup is inactive
    assert bioprocessor_disabled.metadata.get("artistlongbio") == "bio"


@pytest.mark.asyncio
async def test_double_detection_same_track_not_suppressed(tmpbiohistory):  # pylint: disable=redefined-outer-name
    """Bio shown for the same track (double-detection) is not suppressed on the second run."""
    # First pipeline run: record bio for this track
    await tmpbiohistory.record_shown(
        "RuPaul",
        None,
        "bio",
        track=("Elton John, RuPaul", "Don't Go Breaking My Heart"),
    )
    # Second pipeline run for the SAME track: should NOT be considered "shown" for dedup
    result = await tmpbiohistory.has_been_shown(
        "RuPaul", None, ("Elton John, RuPaul", "Don't Go Breaking My Heart")
    )
    assert result is False


@pytest.mark.asyncio
async def test_double_detection_different_track_suppressed(tmpbiohistory):  # pylint: disable=redefined-outer-name
    """Bio shown for a different earlier track IS suppressed (legitimate dedup)."""
    await tmpbiohistory.record_shown("RuPaul", None, "bio", track=("RuPaul", "Supermodel"))
    result = await tmpbiohistory.has_been_shown("RuPaul", None, ("RuPaul", "Cover Girl"))
    assert result is True


@pytest.mark.asyncio
async def test_bio_dedup_setup_restore_roundtrip(bioprocessor):  # pylint: disable=redefined-outer-name
    """Full setup → restore roundtrip leaves metadata with original artist intact."""
    bioprocessor.metadata = {
        "artist": "Madonna feat. Prince",
        "musicbrainzartistid": ["mbid-madonna", "mbid-prince"],
    }
    # Mark Madonna as already seen
    await bioprocessor._biohistory.record_shown("Madonna", "mbid-madonna", "old bio")  # pylint: disable=protected-access

    bio_state = await bioprocessor._bio_dedup_setup()  # pylint: disable=protected-access
    # During plugins, metadata uses Prince
    assert bioprocessor.metadata["artist"] == "Prince"

    # Simulate plugin adding a bio
    bioprocessor.metadata["artistlongbio"] = "Prince bio text"

    await bioprocessor._bio_dedup_restore(*bio_state)  # pylint: disable=protected-access

    # Original artist restored
    assert bioprocessor.metadata["artist"] == "Madonna feat. Prince"
    assert bioprocessor.metadata["musicbrainzartistid"] == ["mbid-madonna", "mbid-prince"]
    # Bio stays (Prince was not suppressed)
    assert bioprocessor.metadata.get("artistlongbio") == "Prince bio text"
    # Prince is now recorded
    assert await bioprocessor._biohistory.has_been_shown("Prince") is True  # pylint: disable=protected-access
