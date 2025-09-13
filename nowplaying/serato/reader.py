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


class Serato4SQLiteReader:  # pylint: disable=too-few-public-methods
    """SQLite database reader for Serato 4+ master.sqlite files"""

    def __init__(self, db_path: str | pathlib.Path):
        self.db_path = pathlib.Path(db_path)

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
