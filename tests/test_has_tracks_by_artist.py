#!/usr/bin/env python3
# pylint: disable=redefined-outer-name,broad-exception-caught,protected-access,line-too-long,too-many-arguments
"""
Comprehensive tests for has_tracks_by_artist functionality across all DJ plugins.

This is a critical feature for live DJ performance - must handle all error cases gracefully.
Refactored version using parameterization to reduce duplication.
"""

import asyncio
import gc
import tempfile
import time
import unittest.mock
from pathlib import Path

import pytest

import nowplaying.inputs.djuced
import nowplaying.inputs.traktor
import nowplaying.inputs.virtualdj
import nowplaying.serato3.plugin
import nowplaying.utils.sqlite

# Test data shared across all plugins
TEST_TRACKS = [
    ("Nine Inch Nails", "Head Like a Hole", "Pretty Hate Machine", "/music/nin1.flac"),
    ("Nine Inch Nails", "Closer", "The Downward Spiral", "/music/nin2.flac"),
    ("The Beatles", "Hey Jude", "The Beatles 1967-1970", "/music/beatles1.flac"),
    ("Madonna", "Like a Virgin", "Like a Virgin", "/music/madonna1.flac"),
    ("Self", "So Low", "Subliminal Plastic Motives", "/music/self1.flac"),
    ("µ-Ziq", "Hasty Boom Alert", "Lunatic Harness", "/music/uziq1.flac"),
    ("Björk", "Human Behaviour", "Debut", "/music/bjork1.flac"),
]

TEST_PLAYLISTS = [
    ("House", "/music/nin1.flac"),
    ("House", "/music/beatles1.flac"),
    ("Techno", "/music/nin2.flac"),
    ("Electronic", "/music/uziq1.flac"),
    ("Electronic", "/music/bjork1.flac"),
]

# Extended playlist data with artist/title metadata (for modern .vdjfolder format)
TEST_PLAYLISTS_WITH_METADATA = [
    ("House", "/music/nin1.flac", "Nine Inch Nails", "Head Like a Hole"),
    ("House", "/music/beatles1.flac", "The Beatles", "Hey Jude"),
    ("Techno", "/music/nin2.flac", "Nine Inch Nails", "Closer"),
    ("Electronic", "/music/uziq1.flac", "µ-Ziq", "Hasty Boom Alert"),
    ("Electronic", "/music/bjork1.flac", "Björk", "Human Behaviour"),
]


@pytest.fixture
def traktor_database():
    """Create Traktor-style database with songs table"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    def _create_database():
        with nowplaying.utils.sqlite.sqlite_connection(db_path, timeout=30.0) as connection:
            connection.execute("""
                CREATE TABLE songs (
                    id INTEGER PRIMARY KEY,
                    artist TEXT,
                    title TEXT,
                    album TEXT,
                    filename TEXT
                )
            """)
            connection.execute("""
                CREATE TABLE playlists (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    filename TEXT
                )
            """)

            # Insert test data
            for artist, title, album, filename in TEST_TRACKS:
                connection.execute(
                    "INSERT INTO songs (artist, title, album, filename) VALUES (?, ?, ?, ?)",
                    (artist, title, album, filename),
                )

            for playlist_name, filename in TEST_PLAYLISTS:
                connection.execute(
                    "INSERT INTO playlists (name, filename) VALUES (?, ?)",
                    (playlist_name, filename),
                )

            connection.commit()

    nowplaying.utils.sqlite.retry_sqlite_operation(_create_database)

    yield db_path

    def _cleanup_database():
        # Force garbage collection to ensure connections are closed
        gc.collect()

        # Small delay for Windows file handle cleanup
        time.sleep(0.1)

        # Try to remove the file
        try:
            Path(db_path).unlink(missing_ok=True)
        except PermissionError:
            # On Windows, retry after a longer delay
            time.sleep(1.0)
            Path(db_path).unlink(missing_ok=True)

    nowplaying.utils.sqlite.retry_sqlite_operation(_cleanup_database)


@pytest.fixture
def djuced_database():
    """Create DJUCED-style database with tracks table"""
    with tempfile.NamedTemporaryFile(suffix="-DJUCED.db", delete=False) as djuced_file:
        djuced_db_path = djuced_file.name

    def _create_database():
        with nowplaying.utils.sqlite.sqlite_connection(djuced_db_path, timeout=30.0) as connection:
            connection.execute("""
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

            connection.execute("""
                CREATE TABLE playlists2 (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    data TEXT,
                    type INTEGER,
                    order_in_list INTEGER,
                    path TEXT
                )
            """)

            for artist, title, album, absolutepath in TEST_TRACKS:
                connection.execute(
                    "INSERT INTO tracks (artist, title, album, absolutepath, comment, bpm, tracknumber, length) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (artist, title, album, absolutepath, "", 120.0, 1, 240),
                )

            # Add static playlist entries (type=3)
            for playlist_name, absolutepath in TEST_PLAYLISTS:
                connection.execute(
                    "INSERT INTO playlists2 (name, data, type) VALUES (?, ?, ?)",
                    (playlist_name, absolutepath, 3),
                )

            connection.commit()

    nowplaying.utils.sqlite.retry_sqlite_operation(_create_database)

    yield djuced_db_path

    def _cleanup_database():
        # Force garbage collection to ensure connections are closed
        gc.collect()

        # Small delay for Windows file handle cleanup
        time.sleep(0.1)

        # Try to remove the file
        try:
            Path(djuced_db_path).unlink(missing_ok=True)
        except PermissionError:
            # On Windows, retry after a longer delay
            time.sleep(1.0)
            Path(djuced_db_path).unlink(missing_ok=True)

    nowplaying.utils.sqlite.retry_sqlite_operation(_cleanup_database)


@pytest.fixture
def virtualdj_databases():
    """Create VirtualDJ-style separate databases for songs and playlists"""
    # Create songs database
    with tempfile.NamedTemporaryFile(suffix="-songs.db", delete=False) as songs_file:
        songs_db_path = songs_file.name

    # Create playlists database
    with tempfile.NamedTemporaryFile(suffix="-playlists.db", delete=False) as playlists_file:
        playlists_db_path = playlists_file.name

    def _create_songs_database():
        with nowplaying.utils.sqlite.sqlite_connection(songs_db_path, timeout=30.0) as connection:
            connection.execute("""
                CREATE TABLE songs (
                    id INTEGER PRIMARY KEY,
                    artist TEXT,
                    title TEXT,
                    album TEXT,
                    filename TEXT
                )
            """)

            for artist, title, album, filename in TEST_TRACKS:
                connection.execute(
                    "INSERT INTO songs (artist, title, album, filename) VALUES (?, ?, ?, ?)",
                    (artist, title, album, filename),
                )
            connection.commit()

    def _create_playlists_database():
        with nowplaying.utils.sqlite.sqlite_connection(
            playlists_db_path, timeout=30.0
        ) as connection:
            connection.execute("""
                CREATE TABLE playlists (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    filename TEXT,
                    artist TEXT,
                    title TEXT
                )
            """)

            # Insert modern vdjfolder-style playlists with metadata
            for playlist_name, filename, artist, title in TEST_PLAYLISTS_WITH_METADATA:
                connection.execute(
                    "INSERT INTO playlists (name, filename, artist, title) VALUES (?, ?, ?, ?)",
                    (playlist_name, filename, artist, title),
                )
            connection.commit()

    # Setup both databases with retry logic
    nowplaying.utils.sqlite.retry_sqlite_operation(_create_songs_database)
    nowplaying.utils.sqlite.retry_sqlite_operation(_create_playlists_database)

    yield {"songs_db": songs_db_path, "playlists_db": playlists_db_path}

    def _cleanup_songs_database():
        # Force garbage collection to ensure connections are closed
        gc.collect()

        # Small delay for Windows file handle cleanup
        time.sleep(0.1)

        # Try to remove the file
        try:
            Path(songs_db_path).unlink(missing_ok=True)
        except PermissionError:
            # On Windows, retry after a longer delay
            time.sleep(1.0)
            Path(songs_db_path).unlink(missing_ok=True)

    def _cleanup_playlists_database():
        # Force garbage collection to ensure connections are closed
        gc.collect()

        # Small delay for Windows file handle cleanup
        time.sleep(0.1)

        # Try to remove the file
        try:
            Path(playlists_db_path).unlink(missing_ok=True)
        except PermissionError:
            # On Windows, retry after a longer delay
            time.sleep(1.0)
            Path(playlists_db_path).unlink(missing_ok=True)

    nowplaying.utils.sqlite.retry_sqlite_operation(_cleanup_songs_database)
    nowplaying.utils.sqlite.retry_sqlite_operation(_cleanup_playlists_database)


def _setup_djuced_plugin(plugin, db_path):
    """Setup DJUCED plugin with database symlink"""
    plugin.djuceddir = str(Path(db_path).parent)
    djuced_db_path = Path(plugin.djuceddir) / "DJUCED.db"
    djuced_db_path.symlink_to(db_path)
    return djuced_db_path  # Return for cleanup


# Plugin configuration for parameterized tests
PLUGIN_TEST_DATA = [
    pytest.param(
        nowplaying.inputs.traktor.Plugin,
        "traktor/artist_query_scope",
        lambda plugin, db_path: setattr(plugin, "databasefile", db_path),
        "traktor_database",
        None,  # No cleanup needed
        id="traktor",
    ),
    pytest.param(
        nowplaying.inputs.virtualdj.Plugin,
        "virtualdj/artist_query_scope",
        lambda plugin, db_paths: (
            setattr(plugin, "songs_databasefile", db_paths["songs_db"]),
            setattr(plugin, "playlists_databasefile", db_paths["playlists_db"]),
        ),
        "virtualdj_databases",
        None,  # No cleanup needed
        id="virtualdj",
    ),
    pytest.param(
        nowplaying.inputs.djuced.Plugin,
        "djuced/artist_query_scope",
        _setup_djuced_plugin,
        "djuced_database",
        lambda cleanup_path: cleanup_path.unlink(missing_ok=True) if cleanup_path else None,
        id="djuced",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plugin_class,scope_key,setup_func,fixture_name,cleanup_func", PLUGIN_TEST_DATA
)
async def test_plugin_has_tracks_found(
    request, bootstrap, plugin_class, scope_key, setup_func, fixture_name, cleanup_func
):
    """Test that all plugins can find existing artists"""
    db_data = request.getfixturevalue(fixture_name)

    bootstrap.cparser.setValue(scope_key, "entire_library")

    plugin = plugin_class(config=bootstrap)
    cleanup_path = setup_func(plugin, db_data)

    try:
        result = await plugin.has_tracks_by_artist("Nine Inch Nails")
        assert result is True
    finally:
        if cleanup_func and cleanup_path:
            cleanup_func(cleanup_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plugin_class,scope_key,setup_func,fixture_name,cleanup_func", PLUGIN_TEST_DATA
)
async def test_plugin_has_tracks_not_found(
    request, bootstrap, plugin_class, scope_key, setup_func, fixture_name, cleanup_func
):
    """Test that all plugins return False for non-existent artists"""
    db_data = request.getfixturevalue(fixture_name)

    bootstrap.cparser.setValue(scope_key, "entire_library")

    plugin = plugin_class(config=bootstrap)
    cleanup_path = setup_func(plugin, db_data)

    try:
        result = await plugin.has_tracks_by_artist("Nonexistent Artist")
        assert result is False
    finally:
        if cleanup_func and cleanup_path:
            cleanup_func(cleanup_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plugin_class,scope_key,setup_func,fixture_name,cleanup_func", PLUGIN_TEST_DATA
)
@pytest.mark.parametrize(
    "artist_variant", ["nine inch nails", "NINE INCH NAILS", "Nine Inch Nails", "nInE iNcH nAiLs"]
)
async def test_plugin_case_insensitive_matching(
    request,
    bootstrap,
    plugin_class,
    scope_key,
    setup_func,
    fixture_name,
    cleanup_func,
    artist_variant,
):
    """Test case-insensitive artist matching across all plugins"""
    db_data = request.getfixturevalue(fixture_name)

    bootstrap.cparser.setValue(scope_key, "entire_library")

    plugin = plugin_class(config=bootstrap)
    cleanup_path = setup_func(plugin, db_data)

    try:
        result = await plugin.has_tracks_by_artist(artist_variant)
        assert result is True, f"Failed for case variant: {artist_variant}"
    finally:
        if cleanup_func and cleanup_path:
            cleanup_func(cleanup_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plugin_class,scope_key,setup_func,fixture_name,cleanup_func", PLUGIN_TEST_DATA
)
@pytest.mark.parametrize("unicode_artist", ["µ-Ziq", "Björk"])
async def test_plugin_unicode_artists(
    request,
    bootstrap,
    plugin_class,
    scope_key,
    setup_func,
    fixture_name,
    cleanup_func,
    unicode_artist,
):
    """Test Unicode artist name support across all plugins"""
    db_data = request.getfixturevalue(fixture_name)

    bootstrap.cparser.setValue(scope_key, "entire_library")

    plugin = plugin_class(config=bootstrap)
    cleanup_path = setup_func(plugin, db_data)

    try:
        result = await plugin.has_tracks_by_artist(unicode_artist)
        assert result is True
    finally:
        if cleanup_func and cleanup_path:
            cleanup_func(cleanup_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plugin_class,scope_key",
    [
        (nowplaying.inputs.traktor.Plugin, "traktor/artist_query_scope"),
        (nowplaying.inputs.virtualdj.Plugin, "virtualdj/artist_query_scope"),
        (nowplaying.inputs.djuced.Plugin, "djuced/artist_query_scope"),
    ],
)
async def test_plugin_database_error_handling(bootstrap, plugin_class, scope_key):
    """Test graceful error handling with database issues across all plugins"""
    bootstrap.cparser.setValue(scope_key, "entire_library")

    plugin = plugin_class(config=bootstrap)

    # Set invalid database paths for each plugin type
    if plugin_class == nowplaying.inputs.traktor.Plugin:
        plugin.databasefile = "/nonexistent/database.db"
    elif plugin_class == nowplaying.inputs.virtualdj.Plugin:
        plugin.songs_databasefile = "/nonexistent/songs.db"
        plugin.playlists_databasefile = "/nonexistent/playlists.db"
    elif plugin_class == nowplaying.inputs.djuced.Plugin:
        plugin.djuceddir = "/nonexistent/directory"

    # Should return False, not raise exception (critical for live performance)
    try:
        result = await plugin.has_tracks_by_artist("Any Artist")
        assert result is False
    except Exception as exc:
        pytest.fail(
            f"Plugin {plugin_class.__name__} raised exception: {exc}. "
            f"Plugins must handle all errors gracefully for live performance."
        )


# Playlist-scoped tests for plugins that support it
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plugin_class,scope_key,setup_func,fixture_name,cleanup_func",
    [
        pytest.param(
            nowplaying.inputs.virtualdj.Plugin,
            "virtualdj/artist_query_scope",
            lambda plugin, db_paths: (
                setattr(plugin, "songs_databasefile", db_paths["songs_db"]),
                setattr(plugin, "playlists_databasefile", db_paths["playlists_db"]),
            ),
            "virtualdj_databases",
            None,
            id="virtualdj",
        ),
        pytest.param(
            nowplaying.inputs.djuced.Plugin,
            "djuced/artist_query_scope",
            _setup_djuced_plugin,
            "djuced_database",
            lambda cleanup_path: cleanup_path.unlink(missing_ok=True) if cleanup_path else None,
            id="djuced",
        ),
    ],
)
async def test_plugin_selected_playlists_scope(
    request, bootstrap, plugin_class, scope_key, setup_func, fixture_name, cleanup_func
):
    """Test playlist-scoped artist queries"""
    db_data = request.getfixturevalue(fixture_name)

    # Configure for selected playlists
    bootstrap.cparser.setValue(scope_key, "selected_playlists")
    bootstrap.cparser.setValue(
        scope_key.replace("artist_query_scope", "selected_playlists"), "House,Electronic"
    )

    plugin = plugin_class(config=bootstrap)
    cleanup_path = setup_func(plugin, db_data)

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
        if cleanup_func and cleanup_path:
            cleanup_func(cleanup_path)


# VirtualDJ-specific tests that don't fit the general pattern
@pytest.mark.asyncio
async def test_virtualdj_selected_playlists_empty_config(bootstrap, virtualdj_databases):
    """Test VirtualDJ with empty selected playlists configuration"""
    bootstrap.cparser.setValue("virtualdj/artist_query_scope", "selected_playlists")
    bootstrap.cparser.setValue("virtualdj/selected_playlists", "")

    plugin = nowplaying.inputs.virtualdj.Plugin(config=bootstrap)
    plugin.songs_databasefile = virtualdj_databases["songs_db"]
    plugin.playlists_databasefile = virtualdj_databases["playlists_db"]

    # Should return False when no playlists selected
    result = await plugin.has_tracks_by_artist("Nine Inch Nails")
    assert result is False


# Edge case tests
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "edge_case_artist",
    ["", "   ", "Self", "self", "SELF", "Madonna", "The Beatles", "the beatles"],
)
async def test_edge_case_artist_names(bootstrap, traktor_database, edge_case_artist):
    """Test edge cases in artist name matching"""
    bootstrap.cparser.setValue("traktor/artist_query_scope", "entire_library")

    plugin = nowplaying.inputs.traktor.Plugin(config=bootstrap)
    plugin.databasefile = traktor_database

    try:
        result = await plugin.has_tracks_by_artist(edge_case_artist)
        # Should always return a boolean, never raise an exception
        assert isinstance(result, bool)
    except Exception as exc:
        pytest.fail(
            f'Plugin raised exception for "{edge_case_artist}": {exc}. '
            f"Must handle all edge cases gracefully for live performance."
        )


# Traktor-specific playlist scope test
@pytest.mark.asyncio
async def test_traktor_selected_playlists_scope(bootstrap, traktor_database):
    """Test Traktor playlist-scoped artist queries"""
    bootstrap.cparser.setValue("traktor/artist_query_scope", "selected_playlists")
    bootstrap.cparser.setValue("traktor/selected_playlists", "House,Techno")

    plugin = nowplaying.inputs.traktor.Plugin(config=bootstrap)
    plugin.databasefile = traktor_database

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


# Serato-specific multi-database tests (kept separate due to complexity)
@pytest.mark.asyncio
async def test_serato_has_tracks_multiple_databases(bootstrap):
    """Test Serato multiple database support"""
    bootstrap.cparser.setValue("serato/artist_query_scope", "entire_library")
    bootstrap.cparser.setValue("serato/libpath", "/music/_Serato_")
    bootstrap.cparser.setValue(
        "serato/additional_libpaths", "/external/_Serato_\n/backup/_Serato_"
    )

    plugin = nowplaying.serato3.plugin.Plugin(config=bootstrap)

    # Mock the static database search method
    with unittest.mock.patch(
        "nowplaying.serato3.plugin.Plugin._has_tracks_in_entire_library"
    ) as mock_search:
        mock_search.side_effect = [False, True, False]  # Found in second database

        result = await plugin.has_tracks_by_artist("Test Artist")
        assert result is True
        assert mock_search.call_count == 2  # Should stop after finding match


# Performance and reliability tests
@pytest.mark.asyncio
async def test_no_exceptions_during_rapid_queries(bootstrap):
    """Test rapid successive queries don't cause issues"""
    bootstrap.cparser.setValue("traktor/artist_query_scope", "entire_library")

    plugin = nowplaying.inputs.traktor.Plugin(config=bootstrap)
    plugin.databasefile = "/nonexistent/database.db"

    # Simulate rapid track changes during live performance
    artists = ["Artist 1", "Artist 2", "Artist 3", "Artist 4", "Artist 5"]

    tasks = [plugin.has_tracks_by_artist(artist) for artist in artists]

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
async def test_all_plugins_implement_has_tracks_by_artist(bootstrap):
    """Ensure all DJ plugins implement has_tracks_by_artist"""
    plugins_to_test = [
        nowplaying.inputs.traktor.Plugin,
        nowplaying.inputs.virtualdj.Plugin,
        nowplaying.inputs.djuced.Plugin,
        nowplaying.serato3.plugin.Plugin,
    ]

    for plugin_class in plugins_to_test:
        plugin = plugin_class(config=bootstrap)
        assert hasattr(plugin, "has_tracks_by_artist"), (
            f"{plugin_class.__name__} missing has_tracks_by_artist method"
        )
        assert asyncio.iscoroutinefunction(plugin.has_tracks_by_artist), (
            f"{plugin_class.__name__}.has_tracks_by_artist must be async"
        )


@pytest.mark.asyncio
async def test_memory_efficiency_large_queries(bootstrap):
    """Test memory efficiency with repeated queries"""
    bootstrap.cparser.setValue("traktor/artist_query_scope", "entire_library")

    plugin = nowplaying.inputs.traktor.Plugin(config=bootstrap)
    plugin.databasefile = "/nonexistent/database.db"

    # Simulate many queries during a long DJ set
    for i in range(100):
        try:
            result = await plugin.has_tracks_by_artist(f"Artist {i}")
            assert isinstance(result, bool)
        except Exception as exc:
            pytest.fail(
                f"Query {i} raised exception: {exc}. Must maintain stability during long sessions."
            )
