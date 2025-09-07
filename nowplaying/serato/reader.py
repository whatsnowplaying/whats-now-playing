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

    async def get_latest_tracks_per_deck(
        self, deckskip: list[str] | None = None
    ) -> list[dict[str, t.Any]]:
        """Get the most recent track loaded on each deck from current session

        Returns the latest track loaded on each deck from the current session.
        Mixmode logic is applied in Python after retrieving all deck data.
        """
        if not self.db_path.exists():
            logging.error("Serato master.sqlite not found at %s", self.db_path)
            return []

        async def _query_tracks() -> list[dict[str, t.Any]]:
            async with aiosqlite.connect(self.db_path) as connection:
                # Use WAL mode for better concurrent access with Serato
                await connection.execute("PRAGMA journal_mode=WAL")
                connection.row_factory = aiosqlite.Row  # Enable column access by name

                # Get the latest track loaded on each deck from current session
                # Simple query - just return what's loaded, regardless of play state
                query = """
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
                        file_bit_rate as bitrate
                    FROM history_entry h1
                    WHERE h1.session_id = (
                        SELECT id FROM history_session
                        WHERE end_time = -1
                        ORDER BY start_time DESC
                        LIMIT 1
                    )
                    AND h1.played = 1
                    AND h1.start_time = (
                        SELECT MAX(h2.start_time)
                        FROM history_entry h2
                        WHERE h2.deck = h1.deck
                        AND h2.session_id = h1.session_id
                        AND h2.played = 1
                    )
                """

                params = []
                if deckskip:
                    placeholders = ",".join("?" * len(deckskip))
                    query += f" AND h1.deck NOT IN ({placeholders})"
                    params.extend(deckskip)

                cursor = await connection.execute(query, params)

                rows = await cursor.fetchall()
                if not rows:
                    return []

                # Convert aiosqlite.Row to dict for easier handling
                tracks = []
                for row in rows:
                    track_data = dict(row)
                    tracks.append(track_data)

                return tracks

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_query_tracks)
        except sqlite3.Error as exc:
            logging.error("Failed to query latest tracks per deck: %s", exc)
            return []
