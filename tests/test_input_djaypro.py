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
    - int   → 0x0F uint8 (e.g. deckNumber)
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
        elif isinstance(value, bool):
            # bool is a subclass of int — handle before int to avoid misclassification
            raise TypeError("Use int for uint8 values, not bool")
        elif isinstance(value, int):
            # 0x0F uint8 — type byte + 1-byte value, no alignment
            field_bytes += bytes([0x0F, value & 0xFF])
            current_offset += 2
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


@pytest.mark.parametrize(
    "deck_num,expected",
    [
        (1, "1"),
        (2, "2"),
    ],
)
def test_parse_blob_deck_uint8(deck_num, expected):
    """_parse_blob extracts deckNumber from a 0x0F uint8 field."""
    blob = _build_tsaf_blob(
        "ADCHistorySessionItem",
        [
            ("Test Artist", "artist"),
            ("Test Title", "title"),
            (deck_num, "deckNumber"),
        ],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["deck"] == expected


@pytest.mark.parametrize(
    "key_index,expected_key",
    [
        (5, "Cm"),  # Camelot 10A — confirmed from Ladytron "Cease2xist"
        (8, "F"),  # Camelot 12B — confirmed from Sinéad O'Connor "Silent Night"
        (9, "Dm"),  # Camelot 12A — relative minor of F (8)
        (10, "F#"),  # Camelot 7B
        (11, "Ebm"),  # Camelot 7A — confirmed from Amanda Palmer "On The Door"
        (0, "Db"),  # Camelot 8B
        (1, "Bbm"),  # Camelot 8A — relative minor of Db (0)
        (17, "F#m"),  # Camelot 4A
    ],
)
def test_parse_blob_key_signature(key_index, expected_key):
    """_parse_blob maps keySignatureIndex to the correct key name (Camelot wheel order)."""
    blob = _build_tsaf_blob(
        "ADCMediaItemAnalyzedData",
        [
            ("Test Artist", "artist"),
            ("Test Title", "title"),
            (float(key_index), "keySignatureIndex"),
        ],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["key"] == expected_key


def test_parse_blob_key_out_of_range():
    """_parse_blob returns key=None for an out-of-range keySignatureIndex."""
    blob = _build_tsaf_blob(
        "ADCMediaItemAnalyzedData",
        [
            ("Test Artist", "artist"),
            (99.0, "keySignatureIndex"),
        ],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["key"] is None


def test_parse_blob_deck_none_when_absent():
    """_parse_blob returns deck=None when deckNumber field is not present."""
    blob = _build_tsaf_blob(
        "ADCHistorySessionItem",
        [("Artist", "artist"), ("Title", "title")],
    )

    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["deck"] is None


# ---------------------------------------------------------------------------
# parse_tsaf primitive type smoke tests
# ---------------------------------------------------------------------------


def _build_typed_tsaf(tc: int, alignment: int, value_bytes: bytes, key: str) -> bytes:
    """Build a minimal TSAF blob with one typed field for parse_tsaf testing.

    Computes alignment padding so the value starts at the correct boundary.
    The prefix is 29 bytes; the value begins at offset 30 (after the tc byte).
    """
    prefix = b"TSAF" + b"\x00" * 16 + b"\x2b\x08C\x00\x08I\x00\x05\x01"
    value_offset = len(prefix) + 1  # offset where value bytes start (after tc byte)
    pad = 0
    if alignment > 1:
        rem = value_offset % alignment
        if rem:
            pad = alignment - rem
    key_bytes = b"\x08" + key.encode() + b"\x00"
    return prefix + bytes([tc]) + b"\x00" * pad + value_bytes + key_bytes


@pytest.mark.parametrize(
    "tc,alignment,value_bytes,key,expected",
    [
        (0x0A, 2, struct.pack("<h", -5), "sortOrder", -5),
        (0x0C, 4, struct.pack("<i", 100), "playCount", 100),
        (0x11, 4, struct.pack("<I", 10_000_000), "fileSize", 10_000_000),
        (0x1A, 4, struct.pack("<I", 3), "colorIndex", 3),
        (0x12, 8, struct.pack("<Q", 5_000_000_000), "fileSizeLarge", 5_000_000_000),
        (0x0D, 1, b"", "isStraightGrid", 0),
        (0x0E, 1, b"", "featured", 1),
    ],
)
def test_parse_tsaf_primitive_types(tc, alignment, value_bytes, key, expected):
    """parse_tsaf correctly decodes new primitive type codes."""
    blob = _build_typed_tsaf(tc, alignment, value_bytes, key)

    result = nowplaying.djaypro.tsaf.parse_tsaf(blob)

    assert result.get(key) == expected


# ---------------------------------------------------------------------------
# _get_analyzed_data_from_db integration tests
# ---------------------------------------------------------------------------


def _make_db_with_collections(dbfile: pathlib.Path, blobs_by_collection: dict[str, list]) -> None:
    """Create a MediaLibrary.db with the given blobs in each collection."""
    conn = sqlite3.connect(dbfile)
    conn.execute(
        "CREATE TABLE database2 (rowid INTEGER PRIMARY KEY, collection CHAR, "
        "key CHAR, data BLOB, metadata BLOB)"
    )
    for collection, blobs in blobs_by_collection.items():
        for i, blob in enumerate(blobs):
            conn.execute(
                "INSERT INTO database2 (collection, key, data) VALUES (?, ?, ?)",
                (collection, f"key-{i}", blob),
            )
    conn.commit()
    conn.close()


def test_get_analyzed_data_from_db_returns_bpm_and_key(bootstrap):
    """_get_analyzed_data_from_db returns bpm and key for a matching track."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        analyzed_blob = _build_tsaf_blob(
            "ADCMediaItemAnalyzedData",
            [
                ("DJ Artist", "artist"),
                ("Club Track", "title"),
                (128.0, "bpm"),
                (8.0, "keySignatureIndex"),  # F major (Camelot 12B, confirmed)
            ],
        )
        _make_db_with_collections(dbfile, {"mediaItemAnalyzedData": [analyzed_blob]})

        result = plugin._get_analyzed_data_from_db("DJ Artist", "Club Track")

        assert result["bpm"] == "128.0"
        assert result["key"] == "F"


def test_get_analyzed_data_from_db_case_insensitive(bootstrap):
    """_get_analyzed_data_from_db matches artist/title case-insensitively."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        analyzed_blob = _build_tsaf_blob(
            "ADCMediaItemAnalyzedData",
            [
                ("DJ Artist", "artist"),
                ("Club Track", "title"),
                (140.0, "bpm"),
            ],
        )
        _make_db_with_collections(dbfile, {"mediaItemAnalyzedData": [analyzed_blob]})

        result = plugin._get_analyzed_data_from_db("dj artist", "club track")

        assert result["bpm"] == "140.0"


def test_get_analyzed_data_from_db_no_match(bootstrap):
    """_get_analyzed_data_from_db returns empty dict when no match is found."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        analyzed_blob = _build_tsaf_blob(
            "ADCMediaItemAnalyzedData",
            [("Other Artist", "artist"), ("Other Track", "title"), (120.0, "bpm")],
        )
        _make_db_with_collections(dbfile, {"mediaItemAnalyzedData": [analyzed_blob]})

        result = plugin._get_analyzed_data_from_db("DJ Artist", "Club Track")

        assert not result


def test_get_analyzed_data_from_db_missing_db(bootstrap):
    """_get_analyzed_data_from_db returns empty dict when database is absent."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        # No MediaLibrary.db created

        result = plugin._get_analyzed_data_from_db("Artist", "Title")

        assert not result


def test_check_for_new_track_uses_analyzed_bpm(bootstrap):
    """_check_for_new_track supplements missing bpm from mediaItemAnalyzedData."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        history_blob = _build_tsaf_blob(
            "ADCHistorySessionItem",
            [("Beat Artist", "artist"), ("Kick Drum", "title")],
        )
        analyzed_blob = _build_tsaf_blob(
            "ADCMediaItemAnalyzedData",
            [
                ("Beat Artist", "artist"),
                ("Kick Drum", "title"),
                (174.0, "bpm"),
                (22.0, "keySignatureIndex"),  # C major (Camelot 1B, idx=22)
            ],
        )
        _make_db_with_collections(
            dbfile,
            {
                "historySessionItems": [history_blob],
                "mediaItemAnalyzedData": [analyzed_blob],
            },
        )

        plugin._check_for_new_track()

        assert plugin.metadata["artist"] == "Beat Artist"
        assert plugin.metadata["bpm"] == "174.0"
        assert plugin.metadata["key"] == "C"


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
