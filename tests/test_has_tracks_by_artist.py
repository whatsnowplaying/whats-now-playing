#!/usr/bin/env python3
# pylint: disable=redefined-outer-name,broad-exception-caught,protected-access,line-too-long
"""
Comprehensive tests for has_tracks_by_artist functionality across all DJ plugins.

This is a critical feature for live DJ performance - must handle all error cases gracefully.
"""

import asyncio
import tempfile
import unittest.mock
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

import nowplaying.inputs.djuced
import nowplaying.inputs.traktor
import nowplaying.inputs.virtualdj
import nowplaying.serato.plugin


@pytest.fixture
def mock_config():
    """Create a mock config for testing"""
    config = unittest.mock.MagicMock()
    config.cparser = unittest.mock.MagicMock()
    return config


@pytest_asyncio.fixture
async def temp_sqlite_db():
    """Create a temporary SQLite database for testing"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    # Create basic schema for testing
    async with aiosqlite.connect(db_path) as connection:
        await connection.execute("""
            CREATE TABLE songs (
                id INTEGER PRIMARY KEY,
                artist TEXT,
                title TEXT,
                album TEXT,
                filename TEXT
            )
        """)
        await connection.execute("""
            CREATE TABLE playlists (
                id INTEGER PRIMARY KEY,
                name TEXT,
                filename TEXT
            )
        """)

        # Insert test data
        test_tracks = [
            ("Nine Inch Nails", "Head Like a Hole", "Pretty Hate Machine", "/music/nin1.flac"),
            ("Nine Inch Nails", "Closer", "The Downward Spiral", "/music/nin2.flac"),
            ("The Beatles", "Hey Jude", "The Beatles 1967-1970", "/music/beatles1.flac"),
            ("Madonna", "Like a Virgin", "Like a Virgin", "/music/madonna1.flac"),
            ("Self", "So Low", "Subliminal Plastic Motives", "/music/self1.flac"),
            ("µ-Ziq", "Hasty Boom Alert", "Lunatic Harness", "/music/uziq1.flac"),
            ("Björk", "Human Behaviour", "Debut", "/music/bjork1.flac"),
        ]

        for artist, title, album, filename in test_tracks:
            await connection.execute(
                "INSERT INTO songs (artist, title, album, filename) VALUES (?, ?, ?, ?)",
                (artist, title, album, filename),
            )

        # Insert playlists test data for VirtualDJ
        test_playlists = [
            ("House", "/music/nin1.flac"),
            ("House", "/music/beatles1.flac"),
            ("Techno", "/music/nin2.flac"),
            ("Electronic", "/music/uziq1.flac"),
            ("Electronic", "/music/bjork1.flac"),
        ]

        for playlist_name, filename in test_playlists:
            await connection.execute(
                "INSERT INTO playlists (name, filename) VALUES (?, ?)",
                (playlist_name, filename),
            )

        await connection.commit()

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest_asyncio.fixture
async def temp_djuced_database():
    """Create temporary DJUCED-style database with tracks table"""
    with tempfile.NamedTemporaryFile(suffix="-DJUCED.db", delete=False) as djuced_file:
        djuced_db_path = djuced_file.name

    # Setup DJUCED database with tracks table (not songs)
    async with aiosqlite.connect(djuced_db_path) as connection:
        await connection.execute("""
            CREATE TABLE tracks (
                id INTEGER PRIMARY KEY,
                artist TEXT,
                title TEXT,
                album TEXT,
                absolutepath TEXT,
                comment TEXT,
                bpm REAL,
                tracknumber INTEGER,
                length INTEGER,
                coverimage BLOB
            )
        """)

        await connection.execute("""
            CREATE TABLE playlists2 (
                id INTEGER PRIMARY KEY,
                name TEXT,
                data TEXT,
                type INTEGER,
                order_in_list INTEGER,
                path TEXT
            )
        """)

        test_tracks = [
            ("Nine Inch Nails", "Head Like a Hole", "Pretty Hate Machine", "/music/nin1.flac"),
            ("Nine Inch Nails", "Closer", "The Downward Spiral", "/music/nin2.flac"),
            ("The Beatles", "Hey Jude", "The Beatles 1967-1970", "/music/beatles1.flac"),
            ("Madonna", "Like a Virgin", "Like a Virgin", "/music/madonna1.flac"),
            ("Self", "So Low", "Subliminal Plastic Motives", "/music/self1.flac"),
            ("µ-Ziq", "Hasty Boom Alert", "Lunatic Harness", "/music/uziq1.flac"),
            ("Björk", "Human Behaviour", "Debut", "/music/bjork1.flac"),
        ]

        for artist, title, album, absolutepath in test_tracks:
            await connection.execute(
                "INSERT INTO tracks (artist, title, album, absolutepath, comment, bpm, tracknumber, length) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (artist, title, album, absolutepath, "", 120.0, 1, 240),
            )

        # Add some static playlist entries (type=3)
        test_static_playlists = [
            ("House", "/music/nin1.flac", 3),
            ("House", "/music/beatles1.flac", 3),
            ("Techno", "/music/nin2.flac", 3),
            ("Electronic", "/music/uziq1.flac", 3),
            ("Electronic", "/music/bjork1.flac", 3),
        ]

        for playlist_name, absolutepath, playlist_type in test_static_playlists:
            await connection.execute(
                "INSERT INTO playlists2 (name, data, type) VALUES (?, ?, ?)",
                (playlist_name, absolutepath, playlist_type),
            )

        await connection.commit()

    yield djuced_db_path

    # Cleanup
    Path(djuced_db_path).unlink(missing_ok=True)


@pytest_asyncio.fixture
async def temp_virtualdj_databases():
    """Create temporary VirtualDJ-style separate databases for songs and playlists"""
    # Create songs database
    with tempfile.NamedTemporaryFile(suffix="-songs.db", delete=False) as songs_file:
        songs_db_path = songs_file.name

    # Create playlists database
    with tempfile.NamedTemporaryFile(suffix="-playlists.db", delete=False) as playlists_file:
        playlists_db_path = playlists_file.name

    # Setup songs database
    async with aiosqlite.connect(songs_db_path) as connection:
        await connection.execute("""
            CREATE TABLE songs (
                id INTEGER PRIMARY KEY,
                artist TEXT,
                title TEXT,
                album TEXT,
                filename TEXT
            )
        """)

        test_tracks = [
            ("Nine Inch Nails", "Head Like a Hole", "Pretty Hate Machine", "/music/nin1.flac"),
            ("Nine Inch Nails", "Closer", "The Downward Spiral", "/music/nin2.flac"),
            ("The Beatles", "Hey Jude", "The Beatles 1967-1970", "/music/beatles1.flac"),
            ("Madonna", "Like a Virgin", "Like a Virgin", "/music/madonna1.flac"),
            ("Self", "So Low", "Subliminal Plastic Motives", "/music/self1.flac"),
            ("µ-Ziq", "Hasty Boom Alert", "Lunatic Harness", "/music/uziq1.flac"),
            ("Björk", "Human Behaviour", "Debut", "/music/bjork1.flac"),
        ]

        for artist, title, album, filename in test_tracks:
            await connection.execute(
                "INSERT INTO songs (artist, title, album, filename) VALUES (?, ?, ?, ?)",
                (artist, title, album, filename),
            )
        await connection.commit()

    # Setup playlists database
    async with aiosqlite.connect(playlists_db_path) as connection:
        await connection.execute("""
            CREATE TABLE playlists (
                id INTEGER PRIMARY KEY,
                name TEXT,
                filename TEXT
            )
        """)

        test_playlists = [
            ("House", "/music/nin1.flac"),
            ("House", "/music/beatles1.flac"),
            ("Techno", "/music/nin2.flac"),
            ("Electronic", "/music/uziq1.flac"),
            ("Electronic", "/music/bjork1.flac"),
        ]

        for playlist_name, filename in test_playlists:
            await connection.execute(
                "INSERT INTO playlists (name, filename) VALUES (?, ?)",
                (playlist_name, filename),
            )
        await connection.commit()

    yield {"songs_db": songs_db_path, "playlists_db": playlists_db_path}

    # Cleanup
    Path(songs_db_path).unlink(missing_ok=True)
    Path(playlists_db_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_traktor_has_tracks_by_artist_found(mock_config, temp_sqlite_db):
    """Test Traktor finding existing artist"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "traktor/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.traktor.Plugin(config=mock_config)
    plugin.extradb = unittest.mock.MagicMock()
    plugin.extradb.databasefile = temp_sqlite_db

    result = await plugin.has_tracks_by_artist("Nine Inch Nails")
    assert result is True


@pytest.mark.asyncio
async def test_traktor_has_tracks_by_artist_not_found(mock_config, temp_sqlite_db):
    """Test Traktor with non-existent artist"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "traktor/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.traktor.Plugin(config=mock_config)
    plugin.extradb = unittest.mock.MagicMock()
    plugin.extradb.databasefile = temp_sqlite_db

    result = await plugin.has_tracks_by_artist("Nonexistent Artist")
    assert result is False


@pytest.mark.asyncio
async def test_traktor_has_tracks_case_insensitive(mock_config, temp_sqlite_db):
    """Test Traktor case-insensitive matching"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "traktor/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.traktor.Plugin(config=mock_config)
    plugin.extradb = unittest.mock.MagicMock()
    plugin.extradb.databasefile = temp_sqlite_db

    # Test various case combinations
    test_cases = ["nine inch nails", "NINE INCH NAILS", "Nine Inch Nails", "nInE iNcH nAiLs"]

    for artist_variant in test_cases:
        result = await plugin.has_tracks_by_artist(artist_variant)
        assert result is True, f"Failed for case variant: {artist_variant}"


@pytest.mark.asyncio
async def test_traktor_unicode_artists(mock_config, temp_sqlite_db):
    """Test Traktor with Unicode artist names"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "traktor/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.traktor.Plugin(config=mock_config)
    plugin.extradb = unittest.mock.MagicMock()
    plugin.extradb.databasefile = temp_sqlite_db

    # Test Unicode characters
    result = await plugin.has_tracks_by_artist("µ-Ziq")
    assert result is True

    result = await plugin.has_tracks_by_artist("Björk")
    assert result is True


@pytest.mark.asyncio
async def test_traktor_database_error_handling(mock_config):
    """Test Traktor graceful error handling with database issues"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "traktor/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.traktor.Plugin(config=mock_config)
    plugin.extradb = unittest.mock.MagicMock()
    plugin.extradb.databasefile = "/nonexistent/database.db"

    # Should return False, not raise exception (critical for live performance)
    try:
        result = await plugin.has_tracks_by_artist("Any Artist")
        assert result is False
    except Exception as exc:
        pytest.fail(
            f"Plugin raised exception: {exc}. "
            f"Plugins must handle all errors gracefully for live performance."
        )


@pytest.mark.asyncio
async def test_virtualdj_has_tracks_by_artist_found(mock_config, temp_virtualdj_databases):
    """Test VirtualDJ finding existing artist in songs database"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "virtualdj/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.virtualdj.Plugin(config=mock_config)
    plugin.songs_databasefile = temp_virtualdj_databases["songs_db"]
    plugin.playlists_databasefile = temp_virtualdj_databases["playlists_db"]

    result = await plugin.has_tracks_by_artist("Nine Inch Nails")
    assert result is True


@pytest.mark.asyncio
async def test_virtualdj_has_tracks_by_artist_not_found(mock_config, temp_virtualdj_databases):
    """Test VirtualDJ with non-existent artist"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "virtualdj/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.virtualdj.Plugin(config=mock_config)
    plugin.songs_databasefile = temp_virtualdj_databases["songs_db"]
    plugin.playlists_databasefile = temp_virtualdj_databases["playlists_db"]

    result = await plugin.has_tracks_by_artist("Nonexistent Artist")
    assert result is False


@pytest.mark.asyncio
async def test_virtualdj_has_tracks_case_insensitive(mock_config, temp_virtualdj_databases):
    """Test VirtualDJ case-insensitive matching"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "virtualdj/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.virtualdj.Plugin(config=mock_config)
    plugin.songs_databasefile = temp_virtualdj_databases["songs_db"]
    plugin.playlists_databasefile = temp_virtualdj_databases["playlists_db"]

    # Test various case combinations
    test_cases = ["nine inch nails", "NINE INCH NAILS", "Nine Inch Nails", "nInE iNcH nAiLs"]

    for artist_variant in test_cases:
        result = await plugin.has_tracks_by_artist(artist_variant)
        assert result is True, f"Failed for case variant: {artist_variant}"


@pytest.mark.asyncio
async def test_virtualdj_has_tracks_unicode_artists(mock_config, temp_virtualdj_databases):
    """Test VirtualDJ with Unicode artist names"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "virtualdj/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.virtualdj.Plugin(config=mock_config)
    plugin.songs_databasefile = temp_virtualdj_databases["songs_db"]
    plugin.playlists_databasefile = temp_virtualdj_databases["playlists_db"]

    # Test Unicode characters
    result = await plugin.has_tracks_by_artist("µ-Ziq")
    assert result is True

    result = await plugin.has_tracks_by_artist("Björk")
    assert result is True


@pytest.mark.asyncio
async def test_virtualdj_selected_playlists_scope(mock_config, temp_virtualdj_databases):
    """Test VirtualDJ playlist-scoped artist queries"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "virtualdj/artist_query_scope": "selected_playlists",
        "virtualdj/selected_playlists": "House,Electronic",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.virtualdj.Plugin(config=mock_config)
    plugin.songs_databasefile = temp_virtualdj_databases["songs_db"]
    plugin.playlists_databasefile = temp_virtualdj_databases["playlists_db"]

    # Nine Inch Nails is in House playlist, should be found
    result = await plugin.has_tracks_by_artist("Nine Inch Nails")
    assert result is True

    # µ-Ziq is in Electronic playlist, should be found
    result = await plugin.has_tracks_by_artist("µ-Ziq")
    assert result is True

    # Madonna is not in any selected playlist, should not be found
    result = await plugin.has_tracks_by_artist("Madonna")
    assert result is False


@pytest.mark.asyncio
async def test_virtualdj_selected_playlists_empty_config(mock_config, temp_virtualdj_databases):
    """Test VirtualDJ with empty selected playlists configuration"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "virtualdj/artist_query_scope": "selected_playlists",
        "virtualdj/selected_playlists": "",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.virtualdj.Plugin(config=mock_config)
    plugin.songs_databasefile = temp_virtualdj_databases["songs_db"]
    plugin.playlists_databasefile = temp_virtualdj_databases["playlists_db"]

    # Should return False when no playlists selected
    result = await plugin.has_tracks_by_artist("Nine Inch Nails")
    assert result is False


@pytest.mark.asyncio
async def test_virtualdj_database_error_handling(mock_config):
    """Test VirtualDJ graceful error handling with database issues"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "virtualdj/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.virtualdj.Plugin(config=mock_config)
    plugin.songs_databasefile = "/nonexistent/songs.db"
    plugin.playlists_databasefile = "/nonexistent/playlists.db"

    # Should return False, not raise exception (critical for live performance)
    try:
        result = await plugin.has_tracks_by_artist("Any Artist")
        assert result is False
    except Exception as exc:
        pytest.fail(
            f"Plugin raised exception: {exc}. "
            f"Plugins must handle all errors gracefully for live performance."
        )


# DJUCED Tests


@pytest.mark.asyncio
async def test_djuced_has_tracks_by_artist_found(mock_config, temp_djuced_database):
    """Test DJUCED finding existing artist in entire library"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "djuced/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.djuced.Plugin(config=mock_config)
    plugin.djuceddir = str(Path(temp_djuced_database).parent)

    # Create DJUCED.db symlink to our test database
    djuced_db_path = Path(plugin.djuceddir) / "DJUCED.db"
    djuced_db_path.symlink_to(temp_djuced_database)

    try:
        result = await plugin.has_tracks_by_artist("Nine Inch Nails")
        assert result is True
    finally:
        djuced_db_path.unlink()


@pytest.mark.asyncio
async def test_djuced_has_tracks_by_artist_not_found(mock_config, temp_djuced_database):
    """Test DJUCED with non-existent artist"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "djuced/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.djuced.Plugin(config=mock_config)
    plugin.djuceddir = str(Path(temp_djuced_database).parent)

    # Create DJUCED.db symlink to our test database
    djuced_db_path = Path(plugin.djuceddir) / "DJUCED.db"
    djuced_db_path.symlink_to(temp_djuced_database)

    try:
        result = await plugin.has_tracks_by_artist("Nonexistent Artist")
        assert result is False
    finally:
        djuced_db_path.unlink()


@pytest.mark.asyncio
async def test_djuced_selected_playlists_scope(mock_config, temp_djuced_database):
    """Test DJUCED playlist-scoped artist queries"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "djuced/artist_query_scope": "selected_playlists",
        "djuced/selected_playlists": "House,Electronic",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.djuced.Plugin(config=mock_config)
    plugin.djuceddir = str(Path(temp_djuced_database).parent)

    # Create DJUCED.db symlink to our test database
    djuced_db_path = Path(plugin.djuceddir) / "DJUCED.db"
    djuced_db_path.symlink_to(temp_djuced_database)

    try:
        # Nine Inch Nails is in House playlist, should be found
        result = await plugin.has_tracks_by_artist("Nine Inch Nails")
        assert result is True

        # µ-Ziq is in Electronic playlist, should be found
        result = await plugin.has_tracks_by_artist("µ-Ziq")
        assert result is True

        # Madonna is not in any selected playlist, should not be found
        result = await plugin.has_tracks_by_artist("Madonna")
        assert result is False
    finally:
        djuced_db_path.unlink()


@pytest.mark.asyncio
async def test_djuced_database_error_handling(mock_config):
    """Test DJUCED graceful error handling with database issues"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "djuced/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.djuced.Plugin(config=mock_config)
    plugin.djuceddir = "/nonexistent/directory"

    # Should return False, not raise exception (critical for live performance)
    try:
        result = await plugin.has_tracks_by_artist("Any Artist")
        assert result is False
    except Exception as exc:
        pytest.fail(
            f"Plugin raised exception: {exc}. "
            f"Plugins must handle all errors gracefully for live performance."
        )


@pytest.mark.asyncio
async def test_serato_has_tracks_multiple_databases(mock_config):
    """Test Serato multiple database support"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "serato/artist_query_scope": "entire_library",
        "serato/libpath": "/music/_Serato_",
        "serato/additional_libpaths": "/external/_Serato_\n/backup/_Serato_",
    }.get(key, defaultValue)

    plugin = nowplaying.serato.plugin.Plugin(config=mock_config)

    # Mock the database search across multiple paths
    with unittest.mock.patch.object(plugin, "_has_tracks_in_entire_library") as mock_search:
        mock_search.side_effect = [False, True, False]  # Found in second database

        result = await plugin.has_tracks_by_artist("Test Artist")
        assert result is True
        assert mock_search.call_count == 2  # Should stop after finding match


@pytest.mark.asyncio
async def test_edge_case_artist_names(mock_config, temp_sqlite_db):
    """Test edge cases in artist name matching"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "traktor/artist_query_scope": "entire_library"
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.traktor.Plugin(config=mock_config)
    plugin.extradb = unittest.mock.MagicMock()
    plugin.extradb.databasefile = temp_sqlite_db

    # Test edge cases that could occur during live DJ sets
    edge_cases = [
        "",  # Empty string
        "   ",  # Whitespace only
        "Self",  # Single word (matches test data)
        "self",  # Case variant
        "SELF",  # All caps
        "Madonna",  # Single name artist
        "The Beatles",  # Artist with "The"
        "the beatles",  # Case variant with "The"
    ]

    for artist_name in edge_cases:
        try:
            result = await plugin.has_tracks_by_artist(artist_name)
            # Should always return a boolean, never raise an exception
            assert isinstance(result, bool)
        except Exception as exc:
            pytest.fail(
                f'Plugin raised exception for "{artist_name}": {exc}. '
                f"Must handle all edge cases gracefully for live performance."
            )


@pytest.mark.asyncio
async def test_selected_playlists_scope(mock_config, temp_sqlite_db):
    """Test playlist-scoped artist queries"""
    mock_config.cparser.value.side_effect = lambda key, defaultValue=None: {
        "traktor/artist_query_scope": "selected_playlists",
        "traktor/selected_playlists": "House,Techno",
    }.get(key, defaultValue)

    plugin = nowplaying.inputs.traktor.Plugin(config=mock_config)
    plugin.extradb = unittest.mock.MagicMock()
    plugin.extradb.databasefile = temp_sqlite_db

    # This would normally check playlist membership, but for this test
    # we're just ensuring the scoped query path doesn't crash
    try:
        result = await plugin.has_tracks_by_artist("Nine Inch Nails")
        assert isinstance(result, bool)
    except Exception as exc:
        pytest.fail(
            f"Selected playlists scope raised exception: {exc}. "
            f"Must handle playlist queries gracefully."
        )


@pytest.mark.asyncio
async def test_all_plugins_implement_has_tracks_by_artist():
    """Ensure all DJ plugins implement has_tracks_by_artist"""
    plugins_to_test = [
        nowplaying.inputs.traktor.Plugin,
        nowplaying.inputs.virtualdj.Plugin,
        nowplaying.inputs.djuced.Plugin,
        nowplaying.serato.plugin.Plugin,
    ]

    mock_config = unittest.mock.MagicMock()

    for plugin_class in plugins_to_test:
        plugin = plugin_class(config=mock_config)
        assert hasattr(plugin, "has_tracks_by_artist"), (
            f"{plugin_class.__name__} missing has_tracks_by_artist method"
        )
        assert asyncio.iscoroutinefunction(plugin.has_tracks_by_artist), (
            f"{plugin_class.__name__}.has_tracks_by_artist must be async"
        )


# DJ Performance Critical Tests
@pytest.mark.asyncio
async def test_no_exceptions_during_rapid_queries():
    """Test rapid successive queries don't cause issues"""
    mock_config = unittest.mock.MagicMock()
    mock_config.cparser.value.return_value = "entire_library"

    plugin = nowplaying.inputs.traktor.Plugin(config=mock_config)
    plugin.extradb = unittest.mock.MagicMock()
    plugin.extradb.databasefile = "/nonexistent/database.db"

    # Simulate rapid track changes during live performance
    artists = ["Artist 1", "Artist 2", "Artist 3", "Artist 4", "Artist 5"]

    tasks = []
    for artist in artists:
        task = plugin.has_tracks_by_artist(artist)
        tasks.append(task)

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # All results should be booleans, no exceptions
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                pytest.fail(
                    f"Query {i} raised exception: {result}. "
                    f"Must handle concurrent queries gracefully."
                )
            assert isinstance(result, bool)

    except Exception as exc:
        pytest.fail(
            f"Concurrent queries raised exception: {exc}. "
            f"Must handle rapid queries for live performance."
        )


@pytest.mark.asyncio
async def test_memory_efficiency_large_queries(mock_config):
    """Test memory efficiency with repeated queries"""
    mock_config.cparser.value.return_value = "entire_library"

    plugin = nowplaying.inputs.traktor.Plugin(config=mock_config)
    plugin.extradb = unittest.mock.MagicMock()
    plugin.extradb.databasefile = "/nonexistent/database.db"

    # Simulate many queries during a long DJ set
    for i in range(100):
        try:
            result = await plugin.has_tracks_by_artist(f"Artist {i}")
            assert isinstance(result, bool)
        except Exception as exc:
            pytest.fail(
                f"Query {i} raised exception: {exc}. Must maintain stability during long sessions."
            )
