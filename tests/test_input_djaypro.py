#!/usr/bin/env python3
"""test djay Pro input plugin"""

import pathlib
import sqlite3
import tempfile

import pytest

import nowplaying.inputs.djaypro


def test_parse_blob_basic():
    """test basic blob parsing with simple artist and title"""
    # Simulate a simple blob with artist and title
    # Format: [value]'key' where value comes before key
    blob = b"Test Artist\x00artist\x00Test Title\x00title\x00"

    result = nowplaying.inputs.djaypro.Plugin._parse_blob(blob)

    assert result["artist"] == "Test Artist"
    assert result["title"] == "Test Title"


def test_parse_blob_with_filepath():
    """test blob parsing with real djay Pro data - local file"""
    # Real blob data from djay Pro database (rowid=229)
    blob = (
        b'TSAF\x00\x00\x00\x00ADCMediaItemLocation\x001684700398760c88942bd2d0f394b68f\x00'
        b'uuid\x00ADCMediaItemTitleID\x00Free To Love\x00title\x00Brendan Maclean\x00artist\x00'
        b'y=C\x00duration\x00titleIDs\x00'
        b'file:///Users/aw/Music/bandcamp/flac/Brendan%20Maclean%20-%20funbang1%20-%2003%20Free%20To%20Love.flac\x00'
        b'sourceURIs\x00'
    )

    result = nowplaying.inputs.djaypro.Plugin._parse_blob(blob)

    assert result["artist"] == "Brendan Maclean"
    assert result["title"] == "Free To Love"
    assert result["filename"] == "/Users/aw/Music/bandcamp/flac/Brendan Maclean - funbang1 - 03 Free To Love.flac"


def test_parse_blob_with_url_encoding():
    """test blob parsing with URL-encoded special characters"""
    # Real blob data with parentheses in filename (rowid=249)
    blob = (
        b'TSAF\x00\x00\x00\x00ADCMediaItemLocation\x00846e6dd8a38e2231c6471c91689f57d5\x00'
        b'uuid\x00ADCMediaItemTitleID\x00On The Door (feat. Amanda Palmer)\x00title\x00'
        b'Brendan Maclean\x00artist\x00CC\x00duration\x00titleIDs\x00'
        b'file:///Users/aw/Music/bandcamp/flac/Brendan%20Maclean%20-%20funbang1%20-%2007%20On%20The%20Door%20(feat.%20Amanda%20Palmer).flac\x00'
        b'sourceURIs\x00'
    )

    result = nowplaying.inputs.djaypro.Plugin._parse_blob(blob)

    assert result["artist"] == "Brendan Maclean"
    assert result["title"] == "On The Door (feat. Amanda Palmer)"
    assert result["filename"] == "/Users/aw/Music/bandcamp/flac/Brendan Maclean - funbang1 - 07 On The Door (feat. Amanda Palmer).flac"


def test_parse_blob_with_source():
    """test blob parsing with iTunes library track (no file path)"""
    # Real blob data from iTunes library track (rowid=209)
    blob = (
        b'TSAF\x00\x00\x00\x00ADCMediaItemLocation\x004518010d2b8c6d764351e10f3abc3765\x00'
        b'uuid\x00ADCMediaItemTitleID\x00We Don\'t Have to Dance\x00title\x00ACTORS\x00artist\x00'
        b'sC\x00duration\x00titleIDs\x00'
        b'com.apple.iTunes:15499219261370860655\x00sourceURIs\x00'
    )

    result = nowplaying.inputs.djaypro.Plugin._parse_blob(blob)

    assert result["artist"] == "ACTORS"
    assert result["title"] == "We Don't Have to Dance"
    # iTunes tracks don't have file:// URLs
    assert result["filename"] is None


def test_parse_blob_empty():
    """test blob parsing with empty data"""
    blob = b""

    result = nowplaying.inputs.djaypro.Plugin._parse_blob(blob)

    assert result["artist"] is None
    assert result["title"] is None
    assert result["filename"] is None
    assert result["source"] is None


def test_parse_blob_malformed():
    """test blob parsing with malformed data"""
    blob = b"\x00\x00\xFF\xFF\x00\x00"

    result = nowplaying.inputs.djaypro.Plugin._parse_blob(blob)

    # Should return None values for all fields without crashing
    assert result["artist"] is None
    assert result["title"] is None


def test_parse_blob_special_characters():
    """test blob parsing with special characters in metadata"""
    blob = (
        b"AC/DC\x00artist\x00"
        b"Back in Black (Live)\x00title\x00"
    )

    result = nowplaying.inputs.djaypro.Plugin._parse_blob(blob)

    assert result["artist"] == "AC/DC"
    assert "Back in Black" in result["title"]


def test_parse_blob_unicode():
    """test blob parsing with unicode characters"""
    # UTF-8 encoded unicode
    blob = (
        "Björk\x00artist\x00".encode('utf-8') +
        "Café del Mar\x00title\x00".encode('utf-8')
    )

    result = nowplaying.inputs.djaypro.Plugin._parse_blob(blob)

    # Should properly decode UTF-8
    assert result["artist"] == "Björk"
    assert result["title"] == "Café del Mar"


def test_parse_blob_ignores_short_file_url():
    """test that bare 'file:///' strings are ignored"""
    # Real blob data contains both full file URL and bare "file:///" marker
    blob = (
        b'Free To Love\x00title\x00Brendan Maclean\x00artist\x00'
        b'file:///Users/aw/Music/test.flac\x00sourceURIs\x00'
        b'file:///\x00'  # This should be ignored (too short)
    )

    result = nowplaying.inputs.djaypro.Plugin._parse_blob(blob)

    # Should use the full URL, not the bare "file:///"
    assert result["filename"] == "/Users/aw/Music/test.flac"


@pytest.mark.asyncio
async def test_check_for_new_track_no_db(bootstrap):
    """test checking for new track when database doesn't exist"""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir

        # Should not crash when database doesn't exist
        plugin._check_for_new_track()

        # Metadata should remain reset
        assert plugin.metadata["artist"] is None
        assert plugin.metadata["title"] is None


@pytest.mark.asyncio
async def test_check_for_new_track_empty_db(bootstrap):
    """test checking for new track with empty database"""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        # Create empty database with proper schema
        conn = sqlite3.connect(dbfile)
        conn.execute(
            'CREATE TABLE database2 (rowid INTEGER PRIMARY KEY, collection CHAR, key CHAR, data BLOB, metadata BLOB)'
        )
        conn.commit()
        conn.close()

        plugin._check_for_new_track()

        # Should handle empty database gracefully
        assert plugin.metadata["artist"] is None


@pytest.mark.asyncio
async def test_check_for_new_track_with_data(bootstrap):
    """test checking for new track with actual data"""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        # Create database with test data
        conn = sqlite3.connect(dbfile)
        conn.execute(
            'CREATE TABLE database2 (rowid INTEGER PRIMARY KEY, collection CHAR, key CHAR, data BLOB, metadata BLOB)'
        )

        # Insert a test history item
        blob = b"Test Artist\x00artist\x00Test Song\x00title\x00"
        conn.execute(
            "INSERT INTO database2 (collection, key, data) VALUES (?, ?, ?)",
            ("historySessionItems", "test-key", blob)
        )
        conn.commit()
        conn.close()

        plugin._check_for_new_track()

        # Should have extracted the metadata
        assert plugin.metadata["artist"] == "Test Artist"
        assert plugin.metadata["title"] == "Test Song"


@pytest.mark.asyncio
async def test_check_for_new_track_duplicate(bootstrap):
    """test that duplicate tracks don't update metadata unnecessarily"""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    with tempfile.TemporaryDirectory() as tmpdir:
        plugin.djaypro_dir = tmpdir
        dbfile = pathlib.Path(tmpdir).joinpath("MediaLibrary.db")

        # Create database
        conn = sqlite3.connect(dbfile)
        conn.execute(
            'CREATE TABLE database2 (rowid INTEGER PRIMARY KEY, collection CHAR, key CHAR, data BLOB, metadata BLOB)'
        )

        blob = b"Same Artist\x00artist\x00Same Song\x00title\x00"
        conn.execute(
            "INSERT INTO database2 (collection, key, data) VALUES (?, ?, ?)",
            ("historySessionItems", "test-key", blob)
        )
        conn.commit()
        conn.close()

        # First check
        plugin._check_for_new_track()
        assert plugin.metadata["artist"] == "Same Artist"

        # Second check - should recognize it's the same track
        plugin._check_for_new_track()
        assert plugin.metadata["artist"] == "Same Artist"


def test_plugin_install_not_found(bootstrap):
    """test install when djay Pro directory doesn't exist"""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    # Override to a non-existent path
    config.userdocs = pathlib.Path("/nonexistent/path")

    result = plugin.install()
    assert result is False


def test_plugin_defaults(bootstrap):
    """test default configuration values"""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    plugin.defaults(config.cparser)

    directory = config.cparser.value("djaypro/directory")
    assert directory is not None
    assert "djay" in directory or directory != ""

    scope = config.cparser.value("djaypro/artist_query_scope")
    assert scope == "entire_library"

    playlists = config.cparser.value("djaypro/selected_playlists")
    assert playlists == ""


@pytest.mark.asyncio
async def test_getplayingtrack(bootstrap):
    """test getplayingtrack returns current metadata"""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    # Set some metadata
    plugin.metadata = {
        "artist": "Test Artist",
        "title": "Test Title",
        "filename": "/path/to/file.mp3"
    }

    result = await plugin.getplayingtrack()

    assert result["artist"] == "Test Artist"
    assert result["title"] == "Test Title"


def test_reset_meta(bootstrap):
    """test metadata reset functionality"""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    # Set some metadata
    plugin.metadata = {
        "artist": "Some Artist",
        "title": "Some Title",
        "filename": "/some/file.mp3"
    }

    plugin._reset_meta()

    assert plugin.metadata["artist"] is None
    assert plugin.metadata["title"] is None
    assert plugin.metadata["filename"] is None


@pytest.mark.asyncio
async def test_stop(bootstrap):
    """test stop cleans up resources but preserves metadata"""
    config = bootstrap
    plugin = nowplaying.inputs.djaypro.Plugin(config=config)

    plugin.metadata = {"artist": "Test", "title": "Test", "filename": "test.mp3"}

    await plugin.stop()

    # Should NOT reset metadata - stopping the watcher doesn't clear current track
    assert plugin.metadata["artist"] == "Test"

    # Observer should be None
    assert plugin.observer is None
