#!/usr/bin/env python3
"""
Test suite for Serato 4+ SQLite input plugin.

These tests use the conftest.py bootstrap fixture and a custom Serato database fixture.
"""

import pathlib
import tempfile
import unittest.mock

import pytest

import nowplaying.inputs.serato
import nowplaying.utils.sqlite


@pytest.fixture
def serato_master_db():
    """Create a temporary Serato 4+ master.sqlite database with test data"""
    with tempfile.TemporaryDirectory() as temp_dir:
        serato_dir = pathlib.Path(temp_dir) / "Serato"
        library_dir = serato_dir / "Library"
        library_dir.mkdir(parents=True)

        db_path = library_dir / "master.sqlite"

        def _create_database():
            with nowplaying.utils.sqlite.sqlite_connection(db_path) as conn:
                # Create realistic Serato 4+ schema (simplified but functional)
                conn.execute("""
                CREATE TABLE history_session (
                    id INTEGER PRIMARY KEY,
                    start_time INTEGER,
                    end_time INTEGER,
                    file_name TEXT
                )
            """)

                conn.execute("""
                    CREATE TABLE history_entry (
                        id INTEGER PRIMARY KEY,
                        session_id INTEGER,
                        file_name TEXT,
                        portable_id TEXT,
                        location_id INTEGER,
                        artist TEXT,
                        name TEXT,
                        album TEXT,
                        genre TEXT,
                        bpm REAL,
                        key TEXT,
                        year TEXT,
                        length_sec INTEGER,
                        start_time INTEGER,
                        played INTEGER,
                        deck TEXT,
                        file_size INTEGER,
                        file_sample_rate REAL,
                        file_bit_rate REAL,
                        FOREIGN KEY (session_id) REFERENCES history_session(id)
                    )
                """)

                # Create location table and location_connections view for path resolution
                conn.execute("""
                    CREATE TABLE location (
                        id INTEGER PRIMARY KEY,
                        uuid BLOB,
                        path TEXT
                    )
                """)

                conn.execute("""
                    CREATE TABLE connection (
                        location_id INTEGER,
                        database_uri TEXT,
                        show_when_disconnected INTEGER
                    )
                """)

                conn.execute("""
                    CREATE VIEW location_connections AS
                    SELECT l.id as location_id, l.uuid, c.database_uri, c.show_when_disconnected
                    FROM location l
                    LEFT OUTER JOIN connection c ON l.id = c.location_id
                """)

                # Insert test location (local library)
                conn.execute(
                    """
                    INSERT INTO location (id, uuid, path)
                    VALUES (1, X'1234567890ABCDEF', '')  -- pragma: allowlist secret
                """
                )

                conn.execute(
                    """
                    INSERT INTO connection (location_id, database_uri, show_when_disconnected)
                    VALUES (1, ?, 0)
                """,
                    (str(library_dir / "root.sqlite"),),
                )

                # Insert test session (end_time = -1 means active session)
                current_time = 1693125000
                conn.execute(
                    """
                    INSERT INTO history_session (id, start_time, end_time, file_name)
                    VALUES (1, ?, -1, 'session.txt')
                """,
                    (current_time - 1800,),
                )  # Session started 30 min ago

                # Insert test tracks with different timestamps and decks
                test_tracks = [
                    # Deck 1 - older track (20 min ago) - will be superseded by newer track
                    (
                        1,
                        1,
                        "track1.mp3",
                        "music/track1.mp3",
                        1,
                        "Artist One",
                        "Track One",
                        "Album One",
                        "House",
                        120.0,
                        "Gm",
                        "2020",
                        180,
                        current_time - 1200,
                        1,
                        "1",
                        5000000,
                        44100.0,
                        320.0,
                    ),
                    # Deck 1 - latest track on deck 1 (5 min ago)
                    (
                        2,
                        1,
                        "track2.mp3",
                        "music/track2.mp3",
                        1,
                        "Artist Two",
                        "Track Two",
                        "Album Two",
                        "Techno",
                        132.0,
                        "Cm",
                        "2022",
                        220,
                        current_time - 300,
                        1,
                        "1",
                        7000000,
                        44100.0,
                        320.0,
                    ),
                    # Deck 2 - newest track overall (2 min ago) - latest on deck 2
                    (
                        3,
                        1,
                        "track3.mp3",
                        "music/track3.mp3",
                        1,
                        "Artist Three",
                        "Track Three",
                        "Album Three",
                        "Electronic",
                        125.0,
                        "Dm",
                        "2023",
                        240,
                        current_time - 120,
                        1,
                        "2",
                        8000000,
                        44100.0,
                        320.0,
                    ),
                    # Deck 3 - oldest among current deck leaders (10 min ago) - latest on deck 3
                    (
                        4,
                        1,
                        "track4.mp3",
                        "music/track4.mp3",
                        1,
                        "Artist Four",
                        "Track Four",
                        "Album Four",
                        "Ambient",
                        100.0,
                        "Em",
                        "2019",
                        300,
                        current_time - 600,
                        1,
                        "3",
                        9000000,
                        44100.0,
                        320.0,
                    ),
                ]

                for track in test_tracks:
                    conn.execute(
                        """
                        INSERT INTO history_entry
                        (id, session_id, file_name, portable_id, location_id, artist, name, album,
                         genre, bpm, key, year, length_sec, start_time, played, deck, file_size,
                         file_sample_rate, file_bit_rate)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        track,
                    )

                    conn.commit()
                    # Context manager handles conn.close() automatically

        # Use retry wrapper for Windows file locking compatibility
        nowplaying.utils.sqlite.retry_sqlite_operation(_create_database)

        yield {
            "library_path": library_dir,
            "db_path": db_path,
            "expected_newest": "Artist Three",  # Deck 2, newest among deck leaders
            "expected_oldest": "Artist Four",  # Deck 3, oldest among deck leaders
            "expected_newest_skip_deck2": "Artist Two",  # Skip deck 2, newest remaining (deck 1)
            "expected_only_deck3": "Artist Four",  # Only deck 3 remains
        }


def test_plugin_instantiation(bootstrap):
    """Test basic plugin instantiation"""
    plugin = nowplaying.inputs.serato.Plugin(config=bootstrap)

    assert plugin.pluginname == "serato"
    assert plugin.description == "Serato DJ input"
    assert plugin.validmixmodes() == ["newest", "oldest"]
    assert plugin.getmixmode() == "newest"


@pytest.mark.asyncio
async def test_auto_detection_mocked(bootstrap, serato_master_db):  # pylint: disable=redefined-outer-name
    """Test plugin with mocked auto-detection"""
    plugin = nowplaying.inputs.serato.Plugin(config=bootstrap)

    # Mock the auto-detection method to return our test database
    with unittest.mock.patch.object(
        plugin, "_find_serato_library", return_value=serato_master_db["library_path"]
    ):
        plugin.configure()
        assert plugin.serato_lib_path == serato_master_db["library_path"]


@pytest.mark.asyncio
async def test_no_detection_returns_none(bootstrap):
    """Test plugin when auto-detection finds nothing"""
    plugin = nowplaying.inputs.serato.Plugin(config=bootstrap)

    # Mock the auto-detection to return None
    with unittest.mock.patch.object(plugin, "_find_serato_library", return_value=None):
        plugin.configure()
        assert plugin.serato_lib_path is None


@pytest.mark.asyncio
async def test_newest_mixmode(bootstrap, serato_master_db):  # pylint: disable=redefined-outer-name
    """Test newest mixmode returns most recent track across all decks"""
    plugin = nowplaying.inputs.serato.Plugin(config=bootstrap)

    # Mock auto-detection and configure
    with unittest.mock.patch.object(
        plugin, "_find_serato_library", return_value=serato_master_db["library_path"]
    ):
        plugin.configure()

        # Set mixmode to newest
        plugin.setmixmode("newest")

        # Start the plugin
        await plugin.start()

        try:
            # Get current track
            track = await plugin.getplayingtrack()

            assert track is not None
            assert track["artist"] == serato_master_db["expected_newest"]
            assert track["deck"] == "2"

        finally:
            await plugin.stop()


@pytest.mark.asyncio
async def test_oldest_mixmode(bootstrap, serato_master_db):  # pylint: disable=redefined-outer-name
    """Test oldest mixmode returns oldest track across all decks"""
    plugin = nowplaying.inputs.serato.Plugin(config=bootstrap)

    with unittest.mock.patch.object(
        plugin, "_find_serato_library", return_value=serato_master_db["library_path"]
    ):
        plugin.configure()
        plugin.setmixmode("oldest")

        await plugin.start()

        try:
            track = await plugin.getplayingtrack()

            assert track is not None
            assert track["artist"] == serato_master_db["expected_oldest"]
            assert track["deck"] == "3"

        finally:
            await plugin.stop()


@pytest.mark.asyncio
async def test_deckskip_functionality(bootstrap, serato_master_db):  # pylint: disable=redefined-outer-name
    """Test deckskip excludes specified decks"""
    plugin = nowplaying.inputs.serato.Plugin(config=bootstrap)

    with unittest.mock.patch.object(
        plugin, "_find_serato_library", return_value=serato_master_db["library_path"]
    ):
        plugin.configure()
        plugin.setmixmode("newest")

        # Skip deck 2 (which has the newest track)
        bootstrap.cparser.setValue("serato4/deckskip", ["2"])

        await plugin.start()

        try:
            track = await plugin.getplayingtrack()

            assert track is not None
            assert track["artist"] == serato_master_db["expected_newest_skip_deck2"]
            assert track["deck"] != "2"  # Should not be from skipped deck

        finally:
            await plugin.stop()


@pytest.mark.asyncio
async def test_getplayingtrack_without_handler(bootstrap):
    """Test getplayingtrack returns None when handler not started"""
    plugin = nowplaying.inputs.serato.Plugin(config=bootstrap)

    # Don't start the plugin
    track = await plugin.getplayingtrack()
    assert track is None


@pytest.mark.asyncio
async def test_track_metadata_mapping(bootstrap, serato_master_db):  # pylint: disable=redefined-outer-name
    """Test that track metadata is correctly mapped to nowplaying format"""
    plugin = nowplaying.inputs.serato.Plugin(config=bootstrap)

    with unittest.mock.patch.object(
        plugin, "_find_serato_library", return_value=serato_master_db["library_path"]
    ):
        plugin.configure()
        await plugin.start()

        try:
            track = await plugin.getplayingtrack()

            assert track is not None

            # Verify all expected fields are present and correctly typed
            assert "artist" in track
            assert "title" in track
            assert "album" in track
            assert "genre" in track
            assert "year" in track
            assert "bpm" in track
            assert "key" in track
            assert "duration" in track
            assert "bitrate" in track
            assert "filename" in track
            assert "deck" in track

            # Verify string conversions for numeric fields
            assert isinstance(track["bpm"], str)
            assert isinstance(track["year"], str)
            assert isinstance(track["bitrate"], str)
            assert isinstance(track["duration"], int)  # Duration should be int (seconds)

        finally:
            await plugin.stop()


@pytest.mark.asyncio
async def test_ignores_closed_sessions(bootstrap, serato_master_db):  # pylint: disable=redefined-outer-name
    """Test plugin ignores closed sessions and only uses active sessions"""
    plugin = nowplaying.inputs.serato.Plugin(config=bootstrap)

    with unittest.mock.patch.object(
        plugin, "_find_serato_library", return_value=serato_master_db["library_path"]
    ):
        plugin.configure()

        # Add a closed session with tracks that should be ignored
        with nowplaying.utils.sqlite.sqlite_connection(serato_master_db["db_path"]) as conn:
            # Insert closed session (end_time != -1)
            conn.execute(
                "INSERT INTO history_session (id, start_time, end_time, file_name) "
                "VALUES (2, ?, ?, 'old_session.txt')",
                (1693125000, 1693125600),  # Closed session (ended 10 min after start)
            )

            # Insert track in closed session that should be ignored
            conn.execute(
                """
                INSERT INTO history_entry
                (id, session_id, file_name, artist, name, album, genre, bpm, key, year,
                 length_sec, start_time, played, deck, file_size,
                 file_sample_rate, file_bit_rate)
                VALUES (99, 2, '/music/old_track.mp3', 'Old Artist', 'Old Track', 'Old Album',
                        'Rock', 140.0, 'Am', '2020', 200, ?, 1, '1', 6000000, 44100.0, 320.0)
            """,
                (1693125000 + 60,),  # Track from closed session
            )
            conn.commit()

        await plugin.start()

        try:
            # Get track - should ignore closed session and return from active session
            track = await plugin.getplayingtrack()

            assert track is not None
            # Should be from active session, not the closed one
            assert track["artist"] != "Old Artist"
            assert track["title"] != "Old Track"
            # Should be from the expected active session track
            assert track["artist"] == serato_master_db["expected_newest"]

        finally:
            await plugin.stop()
