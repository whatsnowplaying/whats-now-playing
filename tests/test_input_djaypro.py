#!/usr/bin/env python3
"""test djay Pro input plugin"""
# pylint: disable=protected-access,too-many-lines

import pathlib
import sqlite3
import struct
import tempfile

import pytest

import nowplaying.djaypro.tsaf
import nowplaying.inputs.djaypro
from nowplaying.djaypro.plugin import _DeckTrack


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


def test_parse_blob_isrc_source_fields():
    """_parse_blob extracts ISRC and maps originSourceID → source."""
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


def test_parse_blob_title_id_from_nested_object():
    """parse_blob extracts titleID from an ADCMediaItemTitleID nested object.

    Real historySessionItems blobs have:
      0x2b 0x08 'ADCMediaItemTitleID' 0x00  (nested class)
      0x08 <32-hex-uuid> 0x00              (obj_id — the join key)
      0x05 0x02                             (nested field count = 2)
      <2 fields consumed by nested object>
    followed by a 0x2e null-typed 'titleID' field that must NOT stomp the UUID.
    """
    uuid = "a1b2c3d4e5f6789012345678901234ab"
    header = b"TSAF" + b"\x00" * 16
    outer = bytearray()
    outer += b"\x08ADCHistorySessionItem\x00"  # class name (no field count — reads to EOS)
    # artist and title fields
    outer += b"\x08Test Artist\x00\x08artist\x00"
    outer += b"\x08Test Track\x00\x08title\x00"
    # nested ADCMediaItemTitleID: obj_id=UUID, 0x05 0x02 = 2 fields for nested to consume
    outer += b"\x2b"
    outer += b"\x08ADCMediaItemTitleID\x00"
    outer += b"\x08" + uuid.encode() + b"\x00"
    outer += b"\x05\x02"
    outer += b"\x08nested1\x00\x08nf1\x00"  # 2 fields consumed by nested obj
    outer += b"\x08nested2\x00\x08nf2\x00"
    # 0x2e null field named 'titleID' — must not overwrite the UUID
    outer += b"\x2e\x08titleID\x00"

    blob = header + b"\x2b" + bytes(outer)
    result = nowplaying.djaypro.tsaf.parse_blob(blob)

    assert result["title_id"] == uuid
    assert result["artist"] == "Test Artist"
    assert result["title"] == "Test Track"


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
# _get_analyzed_data_by_uuid integration tests
# ---------------------------------------------------------------------------


def _make_db_with_collections(dbfile: pathlib.Path, blobs_by_collection: dict[str, list]) -> None:
    """Create a MediaLibrary.db with the given blobs in each collection.

    Each collection's list may contain either:
    - bytes: blob inserted with an auto-generated key
    - tuple[str, bytes]: (key, blob) inserted with the given key
    """
    conn = sqlite3.connect(dbfile)
    conn.execute(
        "CREATE TABLE database2 (rowid INTEGER PRIMARY KEY, collection CHAR, "
        "key CHAR, data BLOB, metadata BLOB)"
    )
    for collection, items in blobs_by_collection.items():
        for i, item in enumerate(items):
            if isinstance(item, tuple):
                key, blob = item
            else:
                key, blob = f"key-{i}", item
            conn.execute(
                "INSERT INTO database2 (collection, key, data) VALUES (?, ?, ?)",
                (collection, key, blob),
            )
    conn.commit()
    conn.close()


def test_get_analyzed_data_by_uuid_returns_bpm_and_key(bootstrap):
    """_get_analyzed_data_by_uuid returns bpm and key for a matching UUID."""
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
        _make_db_with_collections(
            dbfile, {"mediaItemAnalyzedData": [("track-uuid-1", analyzed_blob)]}
        )

        result = plugin._get_analyzed_data_by_uuid("track-uuid-1")

        assert result["bpm"] == "128.0"
        assert result["key"] == "F"


def test_get_analyzed_data_by_uuid_no_match(bootstrap):
    """_get_analyzed_data_by_uuid returns empty dict when UUID is not found."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        analyzed_blob = _build_tsaf_blob(
            "ADCMediaItemAnalyzedData",
            [("Other Artist", "artist"), ("Other Track", "title"), (120.0, "bpm")],
        )
        _make_db_with_collections(
            dbfile, {"mediaItemAnalyzedData": [("other-uuid", analyzed_blob)]}
        )

        result = plugin._get_analyzed_data_by_uuid("track-uuid-1")

        assert not result


def test_get_analyzed_data_by_uuid_missing_db(bootstrap):
    """_get_analyzed_data_by_uuid returns empty dict when database is absent."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        # No MediaLibrary.db created

        result = plugin._get_analyzed_data_by_uuid("any-uuid")

        assert not result


def test_check_for_new_track_uses_analyzed_bpm(bootstrap):
    """_check_for_new_track supplements missing bpm from mediaItemAnalyzedData.

    The UUID from localMediaItemLocations links to mediaItemAnalyzedData so
    BPM and key are retrieved even when absent from the history blob.
    """
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        plugin._location_db_path = pathlib.Path(tmpdir).joinpath("locations.db")
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        track_uuid = "beat-artist-kick-drum-uuid"

        history_blob = _build_tsaf_blob(
            "ADCHistorySessionItem",
            [("Beat Artist", "artist"), ("Kick Drum", "title")],
        )
        # localMediaItemLocations blob links artist+title to the track UUID
        location_blob = _build_tsaf_blob(
            "ADCMediaItemLocation",
            [("Beat Artist", "artist"), ("Kick Drum", "title")],
        )
        analyzed_blob = _build_tsaf_blob(
            "ADCMediaItemAnalyzedData",
            [
                (174.0, "bpm"),
                (22.0, "keySignatureIndex"),  # C major (Camelot 1B, idx=22)
            ],
        )
        _make_db_with_collections(
            dbfile,
            {
                "historySessionItems": [history_blob],
                "localMediaItemLocations": [(track_uuid, location_blob)],
                "mediaItemAnalyzedData": [(track_uuid, analyzed_blob)],
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
    config.cparser.setValue("djaypro/analyzed_data_delay", 0)
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


@pytest.mark.parametrize(
    "artist,title,history_extra_fields,location_fields,expected_isrc",
    [
        # ISRC from historySessionItems (streaming track — no location blob needed)
        (
            "Missy Elliott",
            "Work It",
            [("USEE10240944", "isrc"), ("apple-music", "originSourceID")],
            None,
            ["USEE10240944"],
        ),
        # ISRC from localMediaItemLocations (local file — history has no ISRC)
        (
            "Local Artist",
            "Local Track",
            [],
            [("Local Artist", "artist"), ("Local Track", "title"), ("USRC10000001", "isrc")],
            ["USRC10000001"],
        ),
        # historySessionItems ISRC takes priority over localMediaItemLocations ISRC
        (
            "Missy Elliott",
            "Work It",
            [("USEE10240944", "isrc"), ("apple-music", "originSourceID")],
            [("Missy Elliott", "artist"), ("Work It", "title"), ("DIFFERENT0001", "isrc")],
            ["USEE10240944"],
        ),
        # No ISRC in either source — key must be absent from metadata
        (
            "Local Artist",
            "Local Track",
            [],
            None,
            None,
        ),
    ],
    ids=["history_isrc", "location_isrc", "history_wins", "no_isrc"],
)
def test_check_for_new_track_isrc_sources(  # pylint: disable=too-many-arguments
    bootstrap, artist, title, history_extra_fields, location_fields, expected_isrc
):
    """_check_for_new_track picks up ISRC from the correct source."""
    config = bootstrap
    config.cparser.setValue("djaypro/analyzed_data_delay", 0)
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        plugin._location_db_path = pathlib.Path(tmpdir).joinpath("locations.db")
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        history_blob = _build_tsaf_blob(
            "ADCHistorySessionItem",
            [(artist, "artist"), (title, "title")] + history_extra_fields,
        )
        collections: dict = {"historySessionItems": [history_blob]}
        if location_fields is not None:
            location_blob = _build_tsaf_blob("ADCMediaItemLocation", location_fields)
            collections["localMediaItemLocations"] = [("loc-uuid", location_blob)]
        _make_db_with_collections(dbfile, collections)

        plugin._check_for_new_track()

        assert plugin.metadata.get("artist") == artist
        if expected_isrc is None:
            assert "isrc" not in plugin.metadata
        else:
            assert plugin.metadata.get("isrc") == expected_isrc


def test_check_for_new_track_duplicate(bootstrap):
    """_check_for_new_track preserves metadata when the same track is polled twice."""
    config = bootstrap
    config.cparser.setValue("djaypro/analyzed_data_delay", 0)
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


@pytest.mark.asyncio
async def test_stop_clears_deck_tracks(bootstrap):
    """stop() clears the _deck_tracks dict."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    plugin._deck_tracks["1"] = _DeckTrack(artist="DJ", title="Track")
    plugin._deck_tracks["2"] = _DeckTrack(artist="DJ", title="Other")

    await plugin.stop()

    assert not plugin._deck_tracks


# ---------------------------------------------------------------------------
# Deck skip tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "deckskip_value,expected",
    [
        (None, []),
        ("", []),
        ("1", ["1"]),
        (["1", "2"], ["1", "2"]),
    ],
    ids=["none", "empty", "single_string", "list"],
)
def test_get_deckskip(bootstrap, deckskip_value, expected):
    """_get_deckskip returns the correct list for various stored values."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)
    config.cparser.setValue("djaypro/deckskip", deckskip_value)

    result = plugin._get_deckskip()

    assert result == expected


@pytest.mark.parametrize(
    "deck_num,expected_artist",
    [
        (1, None),  # skipped deck → not reported
        (2, "Track Artist"),  # non-skipped deck → reported
    ],
    ids=["skipped", "allowed"],
)
def test_check_for_new_track_deckskip(bootstrap, deck_num, expected_artist):
    """_check_for_new_track skips decks in deckskip and reports others."""
    config = bootstrap
    config.cparser.setValue("djaypro/analyzed_data_delay", 0)
    config.cparser.setValue("djaypro/deckskip", ["1"])
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        blob = _build_tsaf_blob(
            "ADCHistorySessionItem",
            [("Track Artist", "artist"), ("Track Title", "title"), (deck_num, "deckNumber")],
        )
        _make_db_with_collections(dbfile, {"historySessionItems": [blob]})

        plugin._check_for_new_track()

        assert plugin.metadata["artist"] == expected_artist


def test_check_for_new_track_deck_switch_reports_new(bootstrap):
    """_check_for_new_track reports a new track when the active deck changes."""
    config = bootstrap
    config.cparser.setValue("djaypro/analyzed_data_delay", 0)
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        deck1_blob = _build_tsaf_blob(
            "ADCHistorySessionItem",
            [("Deck1 Artist", "artist"), ("Deck1 Track", "title"), (1, "deckNumber")],
        )
        _make_db_with_collections(dbfile, {"historySessionItems": [deck1_blob]})

        plugin._check_for_new_track()
        assert plugin.metadata["artist"] == "Deck1 Artist"

        deck2_blob = _build_tsaf_blob(
            "ADCHistorySessionItem",
            [("Deck2 Artist", "artist"), ("Deck2 Track", "title"), (2, "deckNumber")],
        )
        # Recreate DB with deck2_blob as the most recent item (highest rowid).
        dbfile.unlink()
        _make_db_with_collections(dbfile, {"historySessionItems": [deck1_blob, deck2_blob]})

        plugin._check_for_new_track()
        assert plugin.metadata["artist"] == "Deck2 Artist"


def test_check_for_new_track_skips_prelaunch(bootstrap):
    """_check_for_new_track ignores a track whose starttime precedes WNP launch."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    # Use a starttime well in the past (Core Data epoch: seconds since 2001-01-01)
    past_starttime = plugin._launch_time - 3600.0  # 1 hour before launch

    blob = _build_tsaf_blob(
        "ADCHistorySessionItem",
        [
            ("Old Artist", "artist"),
            ("Old Track", "title"),
            (past_starttime, "startTime"),
        ],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")
        _make_db_with_collections(dbfile, {"historySessionItems": [blob]})

        plugin._check_for_new_track()

        # metadata should remain empty — pre-launch track is not reported
        assert plugin.metadata.get("artist") is None


def test_check_for_new_track_reports_postlaunch(bootstrap):
    """_check_for_new_track reports a track whose starttime is after WNP launch."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    future_starttime = plugin._launch_time + 5.0  # 5 seconds after launch

    blob = _build_tsaf_blob(
        "ADCHistorySessionItem",
        [
            ("New Artist", "artist"),
            ("New Track", "title"),
            (future_starttime, "startTime"),
        ],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")
        _make_db_with_collections(dbfile, {"historySessionItems": [blob]})

        plugin._check_for_new_track()

        assert plugin.metadata.get("artist") == "New Artist"


def test_parse_blob_starttime():
    """parse_blob extracts startTime as a float."""
    # Core Data timestamp: seconds since 2001-01-01
    start = 800138507.0

    blob = _build_tsaf_blob(
        "ADCHistorySessionItem",
        [("Artist", "artist"), ("Title", "title"), (start, "startTime")],
    )
    result = nowplaying.djaypro.tsaf.parse_blob(blob)
    assert result["starttime"] == start


def _add_playlist_views(
    dbfile: pathlib.Path,
    playlist_assignments: dict[str, list[int]],
) -> None:
    """Create the view_mediaItemPlaylistView_{map,page} helper tables.

    playlist_assignments maps a playlist display name to the list of
    database2 rowids that belong to that playlist.  Real djay Pro stores
    these as SQL views over deeper structures; for tests we just create
    plain tables with the same column shape the production query uses.
    """
    conn = sqlite3.connect(dbfile)
    conn.execute("CREATE TABLE view_mediaItemPlaylistView_map (rowid INTEGER, pageKey TEXT)")
    conn.execute('CREATE TABLE view_mediaItemPlaylistView_page (pageKey TEXT, "group" TEXT)')
    for page_key, (playlist_name, rowids) in enumerate(playlist_assignments.items(), start=1):
        conn.execute(
            'INSERT INTO view_mediaItemPlaylistView_page (pageKey, "group") VALUES (?, ?)',
            (str(page_key), playlist_name),
        )
        for rowid in rowids:
            conn.execute(
                "INSERT INTO view_mediaItemPlaylistView_map (rowid, pageKey) VALUES (?, ?)",
                (rowid, str(page_key)),
            )
    conn.commit()
    conn.close()


@pytest.mark.parametrize(
    "library_artist,query_artist,expected",
    [
        ("Daft Punk", "Daft Punk", True),
        ("Daft Punk", "Other Artist", False),
        ("Daft Punk", "daft punk", True),
        ("Daft Punk", "  Daft Punk  ", True),
    ],
    ids=["exact-match", "no-match", "case-insensitive", "whitespace-trim"],
)
@pytest.mark.asyncio
async def test_has_tracks_by_artist_entire_library(
    bootstrap, library_artist, query_artist, expected
):
    """has_tracks_by_artist scans mediaItemTitleIDs in entire-library mode."""
    config = bootstrap
    config.cparser.setValue("djaypro/artist_query_scope", "entire_library")
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")
        blob = _build_tsaf_blob(
            "ADCMediaItemTitleID",
            [(library_artist, "artist"), ("Some Title", "title")],
        )
        _make_db_with_collections(dbfile, {"mediaItemTitleIDs": [blob]})

        assert await plugin.has_tracks_by_artist(query_artist) is expected


@pytest.mark.parametrize("artist_name", ["", "   ", "\t"], ids=["empty", "spaces", "tab"])
@pytest.mark.asyncio
async def test_has_tracks_by_artist_empty_query(bootstrap, artist_name):
    """has_tracks_by_artist returns False for empty / whitespace queries."""
    config = bootstrap
    config.cparser.setValue("djaypro/artist_query_scope", "entire_library")
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")
        blob = _build_tsaf_blob(
            "ADCMediaItemTitleID",
            [("Daft Punk", "artist"), ("Some Title", "title")],
        )
        _make_db_with_collections(dbfile, {"mediaItemTitleIDs": [blob]})

        assert await plugin.has_tracks_by_artist(artist_name) is False


@pytest.mark.asyncio
async def test_has_tracks_by_artist_missing_db(bootstrap):
    """has_tracks_by_artist returns False when MediaLibrary.db is absent."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        # No MediaLibrary.db created

        assert await plugin.has_tracks_by_artist("Daft Punk") is False


@pytest.mark.parametrize(
    "selected_playlists,view_assignments,expected",
    [
        ("Friday Set", {"Friday Set": [1]}, True),
        ("Friday Set", {"Saturday Set": [1]}, False),
        ("", {"Friday Set": [1]}, False),
        ("Friday Set", None, False),
    ],
    ids=["track-in-selected", "track-in-other", "no-playlist-configured", "no-view-tables"],
)
@pytest.mark.asyncio
async def test_has_tracks_by_artist_selected_playlists(
    bootstrap, selected_playlists, view_assignments, expected
):
    """has_tracks_by_artist in selected_playlists mode across playlist scenarios.

    view_assignments=None means the view tables are not created at all, which
    is djay Pro state when the user has never made a native playlist.
    """
    config = bootstrap
    config.cparser.setValue("djaypro/artist_query_scope", "selected_playlists")
    config.cparser.setValue("djaypro/selected_playlists", selected_playlists)
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")
        blob = _build_tsaf_blob(
            "ADCMediaItemTitleID",
            [("Daft Punk", "artist"), ("Some Title", "title")],
        )
        # The first rowid inserted by _make_db_with_collections is 1.
        _make_db_with_collections(dbfile, {"mediaItemTitleIDs": [blob]})
        if view_assignments is not None:
            _add_playlist_views(dbfile, view_assignments)

        assert await plugin.has_tracks_by_artist("Daft Punk") is expected


@pytest.mark.asyncio
async def test_get_available_playlists_returns_sorted_unique(bootstrap):
    """get_available_playlists returns a sorted list of distinct playlist names."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")
        # database2 must exist for _make_db_with_collections to be useful, but the
        # playlists query reads only from the view tables.  Create an empty one.
        _make_db_with_collections(dbfile, {})
        _add_playlist_views(
            dbfile,
            {"Zulu Set": [1], "Alpha Set": [2], "Mike Set": [3]},
        )

        result = await plugin.get_available_playlists()

        assert result == ["Alpha Set", "Mike Set", "Zulu Set"]


@pytest.mark.asyncio
async def test_get_available_playlists_view_missing(bootstrap):
    """get_available_playlists returns [] when the view table doesn't exist."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")
        # Create the DB but no playlist views — djay Pro state when the user has
        # never made a playlist.
        _make_db_with_collections(dbfile, {})

        assert await plugin.get_available_playlists() == []


@pytest.mark.asyncio
async def test_get_available_playlists_missing_db(bootstrap):
    """get_available_playlists returns [] when MediaLibrary.db is absent."""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        # No MediaLibrary.db created

        assert await plugin.get_available_playlists() == []
