#!/usr/bin/env python3
"""Unit tests for nowplaying/metadata/processors.py targeting uncovered code paths."""

import unittest.mock

import pytest

import nowplaying.metadata
import nowplaying.metadata.processors
from tests.utils_images import jpeg_bytes, png_bytes, unparseable_image_bytes


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
@pytest.mark.parametrize(
    "filename,expected_artist,expected_title",
    [
        ("/some/path/Pet Shop Boys - West End Girls.mp3", "Pet Shop Boys", "West End Girls"),
        ("/Volumes/Music/input5/sombr \u2013 Undressed.mp4", "sombr", "Undressed"),
    ],
)
async def test_filename_stem_artist_sep_title(
    bootstrap, filename, expected_artist, expected_title
):
    """When filename is 'Artist - Title' or 'Artist – Title' with no metadata, split correctly."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    metadatain = {"filename": filename}
    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain
    )
    assert metadataout["artist"] == expected_artist
    assert metadataout["title"] == expected_title


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


@pytest.mark.asyncio
@pytest.mark.parametrize("prioritize_network", [False, True])
async def test_prioritizenetworkart_toggle(bootstrap, prioritize_network):
    """prioritizenetworkart stashes embedded art, lets plugins run,
    restores only if nothing found."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)
    config.cparser.setValue("artistextras/prioritizenetworkart", prioritize_network)

    fake_image = png_bytes()
    metadatain = {
        "artist": "WNP Mock Artist",
        "title": "WNP Mock Song",
        "coverimageraw": fake_image,
        "_embedded_extra_covers": [fake_image],
    }

    # Bypass image conversion and color extraction so fake bytes don't crash PIL.
    # skipplugins=True simulates no network source providing cover art, so the
    # embedded backup should be restored when prioritize_network is True.
    with (
        unittest.mock.patch.object(
            nowplaying.metadata.processors.MetadataProcessors,
            "_process_coverimagetype",
            lambda self: None,
        ),
        unittest.mock.patch.object(
            nowplaying.metadata.processors.MetadataProcessors,
            "_process_cover_colors",
            unittest.mock.AsyncMock(),
        ),
    ):
        metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
            metadata=metadatain, skipplugins=True
        )

    # In both cases the embedded art should be present: when toggle is off it
    # was never cleared; when toggle is on plugins found nothing so it was restored.
    assert metadataout.get("coverimageraw") == fake_image
    # Stripped either by the stash block (prioritize_network=True) or by the
    # datacache block, which now handles album-less tracks via the artist+title key.
    assert "_embedded_extra_covers" not in metadataout


@pytest.mark.parametrize(
    "metadata,expected_key",
    [
        # album present: key on artist+album so embedded and network art share an entry
        (
            {"artist": "WNP Mock Artist", "album": "WNP Mock Album", "title": "WNP Mock Song"},
            "wnpmockartist_wnpmockalbum",
        ),
        # no album at all: fall back to a prefixed artist+title key
        (
            {"artist": "WNP Mock Artist", "title": "WNP Mock Song"},
            "track_wnpmockartist_wnpmocksong",
        ),
        # empty album is treated as absent
        (
            {"artist": "WNP Mock Artist", "album": "", "title": "WNP Mock Song"},
            "track_wnpmockartist_wnpmocksong",
        ),
        # a whitespace-only album normalizes to empty, so fall back rather than
        # keying on the literal string "None"
        (
            {"artist": "WNP Mock Artist", "album": "  ", "title": "WNP Mock Song"},
            "track_wnpmockartist_wnpmocksong",
        ),
    ],
)
def test_cover_cache_key(metadata, expected_key):
    """cover art keys on artist+album, falling back to artist+title when album is missing"""
    assert nowplaying.metadata.processors.cover_cache_key(metadata) == expected_key


@pytest.mark.parametrize(
    "metadata",
    [
        {"title": "WNP Mock Song"},  # no artist
        {"artist": "WNP Mock Artist"},  # artist but nothing to pair it with
        {"artist": "  ", "title": "WNP Mock Song"},  # artist normalizes to empty
        {},
    ],
)
def test_cover_cache_key_unusable(metadata):
    """metadata with nothing to key on yields no cache key rather than a bogus one"""
    assert nowplaying.metadata.processors.cover_cache_key(metadata) is None


def test_cover_cache_key_selftitled_album_does_not_collide():
    """A self-titled album and a same-named track must not share a key.

    "Weezer"/"Weezer" and Michael Jackson's Bad/"Bad" normalize identically, so
    without the track prefix an album-less track would read or overwrite the
    album's cover art.
    """
    album_key = nowplaying.metadata.processors.cover_cache_key(
        {"artist": "Weezer", "album": "Weezer"}
    )
    track_key = nowplaying.metadata.processors.cover_cache_key(
        {"artist": "Weezer", "title": "Weezer"}
    )

    assert album_key != track_key


@pytest.mark.asyncio
async def test_cover_art_is_not_transcoded(bootstrap):
    """The pipeline records the cover's type instead of re-encoding it to PNG.

    Album art is usually JPEG, and converting it to lossless PNG inflated it several
    times over.  /wsstream still converts at serialization time for templates that
    hardcode a data:image/png prefix.
    """
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)

    # A real JPEG: the body matters now, since unparsable art is rejected.
    cover = jpeg_bytes()
    metadatain = {
        "artist": "WNP Mock Artist",
        "title": "WNP Mock Song",
        "album": "WNP Mock Album",
        "coverimageraw": cover,
    }

    with unittest.mock.patch.object(
        nowplaying.metadata.processors.MetadataProcessors,
        "_process_cover_colors",
        unittest.mock.AsyncMock(),
    ):
        metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
            metadata=metadatain, skipplugins=True
        )

    assert metadataout["coverimageraw"] == cover
    assert metadataout["coverimagetype"] == "image/jpeg"


@pytest.mark.asyncio
async def test_coverurl_points_at_keyed_route(bootstrap):
    """coverurl addresses the specific cached image once the art has an entry.

    Naming the entry rather than the singleton /cover.png is what stops a client
    from fetching whatever is playing by the time it gets around to the request.
    """
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)

    metadatain = {
        "artist": "WNP Mock Artist",
        "title": "WNP Mock Song",
        "album": "WNP Mock Album",
        "coverimageraw": png_bytes(),
    }

    with unittest.mock.patch.object(
        nowplaying.metadata.processors.MetadataProcessors,
        "_process_cover_colors",
        unittest.mock.AsyncMock(),
    ):
        metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
            metadata=metadatain, skipplugins=True
        )

    assert metadataout["coverurl"].startswith("cover/")
    assert metadataout["coverurl"] != "cover/None"


@pytest.mark.asyncio
async def test_coverurl_falls_back_without_a_cache_entry(bootstrap):
    """Art with nothing to key on keeps the singleton URL rather than a broken one."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)

    # No artist, so cover_cache_key() returns None and the art never reaches datacache
    metadatain = {"title": "WNP Mock Song", "coverimageraw": png_bytes()}

    with unittest.mock.patch.object(
        nowplaying.metadata.processors.MetadataProcessors,
        "_process_cover_colors",
        unittest.mock.AsyncMock(),
    ):
        metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
            metadata=metadatain, skipplugins=True
        )

    assert metadataout["coverurl"] == "cover.png"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cover_bytes,description",
    [
        (b"<html><script>alert(1)</script></html>", "no image magic at all"),
        # Passes puremagic as image/png; only Pillow can tell it is not a PNG.  This
        # is the shape a truncated download or half-written file takes, so it is the
        # likelier one in the wild.
        (unparseable_image_bytes(), "image magic, unparsable body"),
    ],
)
@pytest.mark.parametrize(
    "artist,album",
    [
        ("WNP Mock Artist", "WNP Mock Album"),
        # cover_cache_key() returns None without an artist, so _process_cover_images
        # never calls store() -- rejection cannot be left to datacache alone.
        (None, None),
    ],
)
async def test_unparseable_cover_art_is_discarded(
    bootstrap, cover_bytes, description, artist, album
):
    """Art we cannot parse is dropped from metadata, whether or not it can be cached.

    Reachable from a remote submission -- the submitter names a coverurl, the webserver
    fetches it, and those bytes become coverimageraw -- and from djuced and winmedia,
    which hand over whatever their source gave them.  Keeping the bytes would serve
    them from /cover.png under an image Content-Type that no decoder can honour.
    """
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)

    metadatain = {
        "title": "WNP Mock Song",
        "coverimageraw": cover_bytes,
        "coverimagetype": "text/html",
    }
    if artist:
        metadatain |= {"artist": artist, "album": album}

    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain, skipplugins=True
    )

    assert "coverimageraw" not in metadataout, description
    assert "coverimagetype" not in metadataout, description
    # No palette either: the extractor would have logged a full traceback at ERROR
    # and then written three empty strings in over nothing.
    assert not metadataout.get("cover_palette")
    assert "cover_palette_type" not in metadataout


@pytest.mark.asyncio
async def test_parseable_cover_art_still_gets_a_palette(bootstrap):
    """The rejection and the empty-palette guard must not suppress real extraction."""
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)

    metadatain = {
        "artist": "WNP Mock Artist",
        "album": "WNP Mock Album",
        "title": "WNP Mock Song",
        "coverimageraw": jpeg_bytes(),
    }

    metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
        metadata=metadatain, skipplugins=True
    )

    assert metadataout["coverimageraw"] == metadatain["coverimageraw"]
    assert metadataout["coverimagetype"] == "image/jpeg"
    assert metadataout["cover_palette_type"] in ("vibrant", "desaturated", "monochrome")
    assert metadataout["cover_palette"].startswith("#")


@pytest.mark.asyncio
async def test_declared_cover_type_is_not_trusted(bootstrap):
    """A supplied coverimagetype is replaced by one derived from the bytes.

    coverimagetype becomes a response Content-Type, and both places it can come
    from -- an audio file's own tag and a remote submission -- are content we did
    not create.
    """
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)

    metadatain = {
        "artist": "WNP Mock Artist",
        "album": "WNP Mock Album",
        "title": "WNP Mock Song",
        "coverimageraw": jpeg_bytes(),
        "coverimagetype": "text/html",
    }

    with unittest.mock.patch.object(
        nowplaying.metadata.processors.MetadataProcessors,
        "_process_cover_colors",
        unittest.mock.AsyncMock(),
    ):
        metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
            metadata=metadatain, skipplugins=True
        )

    assert metadataout["coverimagetype"] == "image/jpeg"


@pytest.mark.asyncio
async def test_supplied_coverurl_is_replaced(bootstrap):
    """A submitter's coverurl never survives into metadata.

    static_handlers fetches whatever coverurl names and puts the bytes in
    coverimageraw, but templates use coverurl as an img src in an OBS browser source
    -- so leaving a remote host there would point the DJ's overlay at it. The value
    is overwritten unconditionally rather than filled only when absent.
    """
    config = bootstrap
    config.cparser.setValue("acoustidmb/enabled", False)
    config.cparser.setValue("musicbrainz/enabled", False)

    metadatain = {
        "artist": "WNP Mock Artist",
        "album": "WNP Mock Album",
        "title": "WNP Mock Song",
        "coverimageraw": png_bytes(),
        "coverurl": "http://attacker.example/payload",
    }

    with unittest.mock.patch.object(
        nowplaying.metadata.processors.MetadataProcessors,
        "_process_cover_colors",
        unittest.mock.AsyncMock(),
    ):
        metadataout = await nowplaying.metadata.MetadataProcessors(config=config).getmoremetadata(
            metadata=metadatain, skipplugins=True
        )

    assert "attacker.example" not in metadataout["coverurl"]


@pytest.mark.parametrize(
    "cachekey,expected",
    [
        ("abc-123", "cover/abc-123"),
        (None, "cover.png"),
    ],
)
def test_coverurl_is_relative_on_both_branches(bootstrap, cachekey, expected):
    """Both coverurl forms agree about the leading slash.

    docs document it as a relative location and consumers join it onto a base, so
    mixing "cover.png" with "/cover/{key}" would hand one of them a double slash that
    aiohttp's router will not match.
    """
    processors = nowplaying.metadata.MetadataProcessors(config=bootstrap)
    processors.metadata = {"coverimageraw": b"x"}

    processors._set_cover_pointers(cachekey)  # pylint: disable=protected-access

    assert processors.metadata["coverurl"] == expected
    assert not processors.metadata["coverurl"].startswith("/")
