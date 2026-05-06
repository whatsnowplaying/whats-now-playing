#!/usr/bin/env python3
"""test djay Pro input plugin"""
# pylint: disable=protected-access

import pathlib
import sqlite3
import struct
import tempfile

import pytest

import nowplaying.djaypro.tsaf
import nowplaying.inputs.djaypro


def _build_tsaf_blob(
    class_name: str,
    fields: list[tuple],
    obj_id: str | None = "test-uuid",
) -> bytes:
    """Build a minimal valid TSAF blob for testing.

    fields: list of (value, key) tuples where value is one of:
    - str   → 0x08 null-terminated string
    - float → 0x14 float64 with 8-byte alignment
    - list[str] → 0x0b array of 0x21-wrapped strings with 4-byte-aligned count
    """
    header = b"TSAF" + b"\x00" * 16  # 20-byte header

    obj_header = bytearray()
    obj_header += b"\x08" + class_name.encode() + b"\x00"
    if obj_id is not None:
        obj_header += b"\x08" + obj_id.encode() + b"\x00"
        obj_header += bytes([0x05, len(fields)])

    # Offset of the first field byte from the start of the blob
    current_offset = len(header) + 1 + len(obj_header)  # 1 for 0x2b

    field_bytes = bytearray()
    for value, key in fields:
        if isinstance(value, str):
            encoded = value.encode("utf-8")
            field_bytes += b"\x08" + encoded + b"\x00"
            current_offset += 1 + len(encoded) + 1
        elif isinstance(value, float):
            field_bytes += b"\x14"
            current_offset += 1
            rem = current_offset % 8
            if rem:
                padding = 8 - rem
                field_bytes += b"\x00" * padding
                current_offset += padding
            field_bytes += struct.pack("<d", value)
            current_offset += 8
        elif isinstance(value, list):
            # 0x0b array of 0x21-wrapped strings
            field_bytes += b"\x0b"
            current_offset += 1
            rem = current_offset % 4
            if rem:
                padding = 4 - rem
                field_bytes += b"\x00" * padding
                current_offset += padding
            field_bytes += struct.pack("<i", len(value))
            current_offset += 4
            for item in value:
                encoded_item = item.encode("utf-8")
                field_bytes += b"\x21\x00" + encoded_item + b"\x00\x00"
                current_offset += 2 + len(encoded_item) + 2

        key_enc = key.encode("utf-8")
        field_bytes += b"\x08" + key_enc + b"\x00"
        current_offset += 1 + len(key_enc) + 1

    return header + b"\x2b" + bytes(obj_header) + bytes(field_bytes)


# ---------------------------------------------------------------------------
# _parse_blob unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "artist,title",
    [
        ("Test Artist", "Test Title"),
        ("AC/DC", "Back in Black (Live)"),
        ("Björk", "Café del Mar"),
    ],
)
def test_parse_blob_string_fields(artist, title):
    """_parse_blob extracts artist and title from TSAF string fields."""
    blob = _build_tsaf_blob(
        "ADCHistorySessionItem",
        [(artist, "artist"), (title, "title")],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["artist"] == artist
    assert result["title"] == title


def test_parse_blob_float_fields():
    """_parse_blob converts float64 duration and bpm correctly."""
    blob = _build_tsaf_blob(
        "ADCHistorySessionItem",
        [
            ("Test Artist", "artist"),
            (240.0, "duration"),
            (128.5, "bpm"),
        ],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["duration"] == 240
    assert result["bpm"] == "128.5"


def test_parse_blob_isrc_field():
    """_parse_blob extracts ISRC from streaming history items."""
    blob = _build_tsaf_blob(
        "ADCHistorySessionItem",
        [
            ("Missy Elliott", "artist"),
            ("Work It", "title"),
            ("USEE10240944", "isrc"),
            ("apple-music", "originSourceID"),
        ],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["isrc"] == "USEE10240944"
    assert result["source"] == "apple-music"


def test_parse_blob_no_isrc():
    """_parse_blob returns isrc=None when the field is absent."""
    blob = _build_tsaf_blob(
        "ADCHistorySessionItem",
        [("Artist", "artist"), ("Title", "title")],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["isrc"] is None


def test_parse_blob_source_field():
    """_parse_blob maps originSourceID to the 'source' key."""
    blob = _build_tsaf_blob(
        "ADCHistorySessionItem",
        [
            ("Test Track", "title"),
            ("spotify", "originSourceID"),
        ],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["source"] == "spotify"
    assert result["title"] == "Test Track"


def test_parse_blob_file_uri():
    """_parse_blob resolves a file:// URI from a sourceURIs array."""
    uri = "file:///Users/aw/Music/test.flac"
    blob = _build_tsaf_blob(
        "ADCMediaItemLocation",
        [
            ("Test Artist", "artist"),
            ("Test Title", "title"),
            ([uri], "sourceURIs"),
        ],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["artist"] == "Test Artist"
    assert result["title"] == "Test Title"
    assert result["filename"] == "/Users/aw/Music/test.flac"


def test_parse_blob_url_encoded_filename():
    """_parse_blob URL-decodes percent-encoded characters in file URIs."""
    uri = "file:///Users/aw/Music/Br%C3%BCcke%20-%20Test.flac"
    blob = _build_tsaf_blob(
        "ADCMediaItemLocation",
        [
            ("Test Artist", "artist"),
            ([uri], "sourceURIs"),
        ],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["filename"] == "/Users/aw/Music/Brücke - Test.flac"


def test_parse_blob_non_file_uri():
    """_parse_blob returns filename=None for non-file:// URIs (e.g. iTunes)."""
    blob = _build_tsaf_blob(
        "ADCMediaItemLocation",
        [
            ("ACTORS", "artist"),
            ("We Don't Have to Dance", "title"),
            (["com.apple.iTunes:15499219261370860655"], "sourceURIs"),
        ],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["artist"] == "ACTORS"
    assert result["title"] == "We Don't Have to Dance"
    assert result["filename"] is None


def test_parse_blob_ignores_root_only_file_uri():
    """_parse_blob ignores a file:/// URI that resolves to the root path only."""
    blob = _build_tsaf_blob(
        "ADCMediaItemLocation",
        [
            ("Artist", "artist"),
            (["file:///"], "sourceURIs"),
        ],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["filename"] is None


def test_parse_blob_no_float_returns_none_bpm_duration():
    """_parse_blob returns None for bpm/duration when those fields are absent."""
    blob = _build_tsaf_blob(
        "ADCHistorySessionItem",
        [("Track", "title")],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["bpm"] is None
    assert result["duration"] is None


def test_parse_blob_empty():
    """_parse_blob returns all-None dict for an empty blob."""
    result = nowplaying.djaypro.tsaf.parse_blob(b"")

    assert result["artist"] is None
    assert result["title"] is None
    assert result["filename"] is None
    assert result["source"] is None


def test_parse_blob_malformed():
    """_parse_blob returns all-None dict for blobs without TSAF magic."""
    result = nowplaying.djaypro.tsaf.parse_blob(b"\x00\x00\xff\xff\x00\x00")

    assert result["artist"] is None
    assert result["title"] is None


# ---------------------------------------------------------------------------
# _check_for_new_track integration tests
# ---------------------------------------------------------------------------


def test_check_for_new_track_no_db(bootstrap):
    """_check_for_new_track handles a missing database without crashing."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir

        plugin._check_for_new_track()

        assert plugin.metadata["artist"] is None
        assert plugin.metadata["title"] is None


def test_check_for_new_track_empty_db(bootstrap):
    """_check_for_new_track handles an empty database without crashing."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        conn = sqlite3.connect(dbfile)
        conn.execute(
            "CREATE TABLE database2 (rowid INTEGER PRIMARY KEY, collection CHAR, "
            "key CHAR, data BLOB, metadata BLOB)"
        )
        conn.commit()
        conn.close()

        plugin._check_for_new_track()

        assert plugin.metadata["artist"] is None


def test_check_for_new_track_with_data(bootstrap):
    """_check_for_new_track extracts track metadata from a valid TSAF blob."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        conn = sqlite3.connect(dbfile)
        conn.execute(
            "CREATE TABLE database2 (rowid INTEGER PRIMARY KEY, collection CHAR, "
            "key CHAR, data BLOB, metadata BLOB)"
        )

        blob = _build_tsaf_blob(
            "ADCHistorySessionItem",
            [("Test Artist", "artist"), ("Test Song", "title")],
        )
        conn.execute(
            "INSERT INTO database2 (collection, key, data) VALUES (?, ?, ?)",
            ("historySessionItems", "test-key", blob),
        )
        conn.commit()
        conn.close()

        plugin._check_for_new_track()

        assert plugin.metadata["artist"] == "Test Artist"
        assert plugin.metadata["title"] == "Test Song"


def test_check_for_new_track_with_isrc(bootstrap):
    """_check_for_new_track passes ISRC from history blob as list."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        conn = sqlite3.connect(dbfile)
        conn.execute(
            "CREATE TABLE database2 (rowid INTEGER PRIMARY KEY, collection CHAR, "
            "key CHAR, data BLOB, metadata BLOB)"
        )
        blob = _build_tsaf_blob(
            "ADCHistorySessionItem",
            [
                ("Missy Elliott", "artist"),
                ("Work It", "title"),
                ("USEE10240944", "isrc"),
                ("apple-music", "originSourceID"),
            ],
        )
        conn.execute(
            "INSERT INTO database2 (collection, key, data) VALUES (?, ?, ?)",
            ("historySessionItems", "test-key", blob),
        )
        conn.commit()
        conn.close()

        plugin._check_for_new_track()

        assert plugin.metadata.get("artist") == "Missy Elliott"
        assert plugin.metadata.get("isrc") == ["USEE10240944"]


def test_check_for_new_track_no_isrc_omitted(bootstrap):
    """_check_for_new_track omits isrc key when track has no ISRC."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        conn = sqlite3.connect(dbfile)
        conn.execute(
            "CREATE TABLE database2 (rowid INTEGER PRIMARY KEY, collection CHAR, "
            "key CHAR, data BLOB, metadata BLOB)"
        )
        blob = _build_tsaf_blob(
            "ADCHistorySessionItem",
            [("Local Artist", "artist"), ("Local Track", "title")],
        )
        conn.execute(
            "INSERT INTO database2 (collection, key, data) VALUES (?, ?, ?)",
            ("historySessionItems", "test-key", blob),
        )
        conn.commit()
        conn.close()

        plugin._check_for_new_track()

        assert plugin.metadata.get("artist") == "Local Artist"
        assert "isrc" not in plugin.metadata


def test_check_for_new_track_duplicate(bootstrap):
    """_check_for_new_track preserves metadata when the same track is polled twice."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        conn = sqlite3.connect(dbfile)
        conn.execute(
            "CREATE TABLE database2 (rowid INTEGER PRIMARY KEY, collection CHAR, "
            "key CHAR, data BLOB, metadata BLOB)"
        )

        blob = _build_tsaf_blob(
            "ADCHistorySessionItem",
            [("Same Artist", "artist"), ("Same Song", "title")],
        )
        conn.execute(
            "INSERT INTO database2 (collection, key, data) VALUES (?, ?, ?)",
            ("historySessionItems", "test-key", blob),
        )
        conn.commit()
        conn.close()

        plugin._check_for_new_track()
        assert plugin.metadata["artist"] == "Same Artist"

        plugin._check_for_new_track()
        assert plugin.metadata["artist"] == "Same Artist"


# ---------------------------------------------------------------------------
# Plugin lifecycle tests
# ---------------------------------------------------------------------------


def test_plugin_install_not_found(bootstrap):
    """install() returns False when the djay Pro directory doesn't exist."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    config.userdocs = pathlib.Path("/nonexistent/path")

    result = plugin.install()
    assert result is False


def test_plugin_defaults(bootstrap):
    """defaults() writes sensible initial configuration values."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    plugin.defaults(config.cparser)

    directory = config.cparser.value("djaypro/directory")
    assert isinstance(directory, str)
    assert directory.strip() != ""

    directory_path = pathlib.Path(directory)
    expected_suffixes = {
        "djay Media Library.djayMediaLibrary",
        "djay Media Library",
    }
    assert any(str(directory_path).endswith(suffix) for suffix in expected_suffixes)

    scope = config.cparser.value("djaypro/artist_query_scope")
    assert scope == "entire_library"

    playlists = config.cparser.value("djaypro/selected_playlists")
    assert playlists == ""


@pytest.mark.asyncio
async def test_getplayingtrack(bootstrap):
    """getplayingtrack() returns the current metadata dict."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        config.cparser.setValue("djaypro/directory", tmpdir)

        plugin.metadata = {
            "artist": "Test Artist",
            "title": "Test Title",
            "filename": "/path/to/file.mp3",
        }

        result = await plugin.getplayingtrack()

        assert result["artist"] == "Test Artist"
        assert result["title"] == "Test Title"

        await plugin.stop()


def test_reset_meta(bootstrap):
    """_reset_meta() clears all metadata fields to None."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    plugin.metadata = {
        "artist": "Some Artist",
        "title": "Some Title",
        "filename": "/some/file.mp3",
    }

    plugin._reset_meta()

    assert plugin.metadata["artist"] is None
    assert plugin.metadata["title"] is None
    assert plugin.metadata["filename"] is None


@pytest.mark.asyncio
async def test_stop(bootstrap):
    """stop() cleans up the watcher but preserves current track metadata."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    plugin.metadata = {"artist": "Test", "title": "Test", "filename": "test.mp3"}

    await plugin.stop()

    assert plugin.metadata["artist"] == "Test"
    assert plugin.observer is None
