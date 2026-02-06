#!/usr/bin/env python3
"""
Serato 4+ SQLite Reader

SQLite database reader for Serato DJ 4.0+ master.sqlite files.
"""

import logging
import pathlib
import sqlite3
import typing as t

import aiosqlite

import nowplaying.utils.sqlite


class Serato4SQLiteReader:
    """SQLite database reader for Serato 4+ master.sqlite files"""

    def __init__(self, db_path: str | pathlib.Path):
        self.db_path = pathlib.Path(db_path)

    async def get_location_mappings(self) -> dict[int, pathlib.Path]:
        """Get mapping of location_id to base file path

        Returns a dictionary mapping location_id to the base path for that location.
        For external libraries, extracts the parent of _Serato_.
        For the local library, returns root path.
        """
        if not self.db_path.exists():
            logging.error("Serato master.sqlite not found at %s", self.db_path)
            return {}

        async def _query_locations() -> dict[int, pathlib.Path]:
            async with aiosqlite.connect(self.db_path) as connection:
                connection.row_factory = aiosqlite.Row

                # Query location_connections view to get database paths for each location
                query = """
                    SELECT location_id, database_uri
                    FROM location_connections
                    WHERE database_uri IS NOT NULL
                """

                cursor = await connection.execute(query)
                rows = await cursor.fetchall()

                location_map = {}
                for row in rows:
                    location_id = row["location_id"]
                    database_uri = row["database_uri"]

                    # For external libraries: database_uri is like
                    # "/Volumes/Music/_Serato_/Library/location.sqlite"
                    # Base path is parent of "_Serato_": "/Volumes/Music/"
                    #
                    # For local library: database_uri is like
                    # "/Users/aw/Library/Application Support/Serato/Library/root.sqlite"
                    # Base path is root "/"
                    db_path = pathlib.Path(database_uri)

                    if "_Serato_" in db_path.parts:
                        # External library - find parent of _Serato_
                        parts = list(db_path.parts)
                        serato_idx = parts.index("_Serato_")
                        base_path = pathlib.Path(*parts[:serato_idx])
                    else:
                        # Local library - portable_id is absolute path without leading /
                        base_path = pathlib.Path("/")

                    location_map[location_id] = base_path

                return location_map

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_query_locations)
        except sqlite3.Error as exc:
            logging.error("Failed to query location mappings: %s", exc)
            return {}

    async def get_library_database_paths(self) -> list[pathlib.Path]:
        """Get all library database paths for artist filtering

        Returns list of paths to root.sqlite or location.sqlite files
        that can be used for querying the full library/crates.
        """
        if not self.db_path.exists():
            logging.error("Serato master.sqlite not found at %s", self.db_path)
            return []

        async def _query_db_paths() -> list[pathlib.Path]:
            async with aiosqlite.connect(self.db_path) as connection:
                connection.row_factory = aiosqlite.Row

                # Query location_connections view to get all database paths
                query = """
                    SELECT database_uri
                    FROM location_connections
                    WHERE database_uri IS NOT NULL
                """

                cursor = await connection.execute(query)
                rows = await cursor.fetchall()

                db_paths = []
                for row in rows:
                    db_path = pathlib.Path(row["database_uri"])
                    if db_path.exists():
                        db_paths.append(db_path)
                    else:
                        logging.debug("Library database not found: %s", db_path)

                return db_paths

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_query_db_paths)
        except sqlite3.Error as exc:
            logging.error("Failed to query library database paths: %s", exc)
            return []

    async def get_latest_tracks_per_deck(self) -> list[dict[str, t.Any]]:
        """Get the most recent track loaded on each deck from current session

        Returns the latest track loaded on each deck from the current session.
        Deck filtering and mixmode logic are applied in Python after retrieving all deck data.
        """
        if not self.db_path.exists():
            logging.error("Serato master.sqlite not found at %s", self.db_path)
            return []

        async def _query_tracks() -> list[dict[str, t.Any]]:
            async with aiosqlite.connect(self.db_path) as connection:
                # Let Serato manage its own journal mode - we're just a read-only client
                connection.row_factory = aiosqlite.Row  # Enable column access by name

                # Get the latest track loaded on each deck from current session
                # Optimized query using window functions instead of correlated subqueries
                # Use portable_id which contains the full relative path
                query = """
                    WITH current_session AS (
                        SELECT id FROM history_session
                        WHERE end_time = -1
                        ORDER BY start_time DESC
                        LIMIT 1
                    ),
                    ranked_tracks AS (
                        SELECT
                            file_name,
                            portable_id,
                            location_id,
                            artist,
                            name as title,
                            album,
                            genre,
                            bpm,
                            key,
                            year,
                            length_sec as duration,
                            start_time,
                            played,
                            deck,
                            file_size as file_bytes,
                            file_sample_rate as sample_rate,
                            file_bit_rate as bitrate,
                            ROW_NUMBER() OVER (
                                PARTITION BY deck
                                ORDER BY start_time DESC
                            ) as rn
                        FROM history_entry
                        WHERE session_id = (SELECT id FROM current_session)
                        AND played = 1
                    )
                    SELECT
                        file_name,
                        portable_id,
                        location_id,
                        artist,
                        title,
                        album,
                        genre,
                        bpm,
                        key,
                        year,
                        duration,
                        start_time,
                        played,
                        deck,
                        file_bytes,
                        sample_rate,
                        bitrate
                    FROM ranked_tracks
                    WHERE rn = 1
                """

                cursor = await connection.execute(query)

                rows = await cursor.fetchall()
                if not rows:
                    return []

                # Convert aiosqlite.Row to dict for easier handling
                return [dict(row) for row in rows]

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_query_tracks)
        except sqlite3.Error as exc:
            logging.error("Failed to query latest tracks per deck: %s", exc)
            return []


class Serato4RootReader:  # pylint: disable=too-few-public-methods
    """SQLite database reader for Serato 4+ root.sqlite files (crates/containers)"""

    def __init__(self, db_path: str | pathlib.Path):
        self.db_path = pathlib.Path(db_path)

    async def has_artist_in_crates(self, artist_name: str, crate_names: list[str]) -> bool:
        """Check if an artist has tracks in any of the specified crates

        Args:
            artist_name: Artist name to search for (case-insensitive)
            crate_names: List of crate names to search in

        Returns:
            True if artist found in any specified crate, False otherwise
        """
        if not self.db_path.exists():
            logging.error("Serato root.sqlite not found at %s", self.db_path)
            return False

        if not crate_names:
            return False

        async def _query_crates() -> bool:
            async with aiosqlite.connect(self.db_path) as connection:
                connection.row_factory = aiosqlite.Row

                # Build placeholders for crate names
                placeholders = ",".join("?" * len(crate_names))

                # Query to find artist in specified crates
                # container_asset links containers (crates) to assets (tracks)
                # Use LOWER() for case-insensitive artist search
                # Note: f-string only used for placeholder count, all user data passed via params
                query = f"""
                    SELECT DISTINCT 1
                    FROM container c
                    INNER JOIN container_asset ca ON c.id = ca.container_id
                    INNER JOIN asset a ON ca.asset_id = a.id
                    WHERE c.name IN ({placeholders})
                    AND LOWER(a.artist) LIKE LOWER(?)
                    LIMIT 1
                """

                # Prepare parameters: crate names + artist search pattern
                params = list(crate_names) + [f"%{artist_name}%"]

                # Safe: all user data in params array, not in query string
                cursor = await connection.execute(query, params)
                row = await cursor.fetchone()

                return row is not None

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_query_crates)
        except sqlite3.Error as exc:
            logging.error("Failed to query artist in crates: %s", exc)
            return False
