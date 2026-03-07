#!/usr/bin/env python3
"""Artist bio history database for deduplication across tracks within a session"""

import logging
import pathlib
import sqlite3
import time

import aiosqlite
from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.utils.sqlite

SCHEMA_VERSION = 1


class ArtistBioHistory:
    """
    Tracks which artist bios have been shown during the current session.

    Stored in a separate SQLite database so it persists across track changes
    without triggering the metadata DB watchers.  Keyed by MBID when available,
    falling back to (normalised) artist name.

    Each entry also stores the track (track_artist, track_title) on which the bio
    was shown, so double-detection (same track firing twice via filesystem events)
    does not suppress the bio.  ``has_been_shown`` returns True only when the bio
    was shown for a *different* track earlier in the session.
    """

    @staticmethod
    def _get_database_path() -> pathlib.Path:
        return pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.AppDataLocation)[0]
        ).joinpath("artistbio", "artistbio.db")

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.dbpath = self._get_database_path()
        self._ensure_database()

    def _ensure_database(self) -> None:
        """Create database and tables if they do not already exist."""
        self.dbpath.parent.mkdir(parents=True, exist_ok=True)
        try:
            with nowplaying.utils.sqlite.sqlite_connection(str(self.dbpath), timeout=30) as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS bio_history (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        artist_name TEXT NOT NULL COLLATE NOCASE,
                        mbid        TEXT,
                        session_id  TEXT NOT NULL,
                        bio_text    TEXT,
                        shown_at    INTEGER NOT NULL,
                        track_artist TEXT NOT NULL DEFAULT '',
                        track_title  TEXT NOT NULL DEFAULT ''
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_bio_history_v2
                        ON bio_history(artist_name, session_id, track_artist, track_title);
                    CREATE INDEX IF NOT EXISTS idx_bio_mbid
                        ON bio_history(mbid) WHERE mbid IS NOT NULL;
                """)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM schema_version")
                if cursor.fetchone()[0] == 0:
                    cursor.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
                conn.commit()
                logging.debug("Artist bio history database initialised at %s", self.dbpath)
        except sqlite3.Error as error:
            logging.error("Failed to initialise artist bio history database: %s", error)

    async def has_been_shown(
        self,
        artist_name: str,
        mbid: str | None = None,
        track: tuple[str, str] | None = None,
    ) -> bool:
        """Return True if this artist's bio was shown in the session for a *different* track.

        When ``track`` (artist, title) is supplied the query excludes any entry that was
        recorded for the same track.  This lets a second pipeline run triggered by the
        same filesystem event (double-detection) pass through without being suppressed.

        Checks by MBID first (globally unique), then falls back to artist name.
        When an MBID is provided both are checked so a name-only entry recorded on
        a previous track still counts as seen.
        """
        norm_artist = track[0] if track else ""
        norm_title = track[1] if track else ""
        use_track_filter = bool(norm_artist and norm_title)
        try:
            async with aiosqlite.connect(str(self.dbpath)) as conn:
                if use_track_filter:
                    if mbid:
                        cursor = await conn.execute(
                            """SELECT id FROM bio_history
                               WHERE (mbid = ? OR artist_name = ?) AND session_id = ?
                                 AND NOT (track_artist = ? AND track_title = ?)""",
                            (mbid, artist_name, self.session_id, norm_artist, norm_title),
                        )
                    else:
                        cursor = await conn.execute(
                            """SELECT id FROM bio_history
                               WHERE artist_name = ? AND session_id = ?
                                 AND NOT (track_artist = ? AND track_title = ?)""",
                            (artist_name, self.session_id, norm_artist, norm_title),
                        )
                else:
                    if mbid:
                        cursor = await conn.execute(
                            """SELECT id FROM bio_history
                               WHERE (mbid = ? OR artist_name = ?) AND session_id = ?""",
                            (mbid, artist_name, self.session_id),
                        )
                    else:
                        cursor = await conn.execute(
                            """SELECT id FROM bio_history
                               WHERE artist_name = ? AND session_id = ?""",
                            (artist_name, self.session_id),
                        )
                row = await cursor.fetchone()
                return row is not None
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Error checking artist bio history: %s", error)
            return False

    async def record_shown(
        self,
        artist_name: str,
        mbid: str | None,
        bio_text: str | None,
        track: tuple[str, str] | None = None,
    ) -> None:
        """Record that this artist's bio was shown in the current session."""
        norm_artist = track[0] if track else ""
        norm_title = track[1] if track else ""
        try:
            async with aiosqlite.connect(str(self.dbpath)) as conn:
                await conn.execute(
                    """INSERT OR REPLACE INTO bio_history
                       (artist_name, mbid, session_id, bio_text, shown_at,
                        track_artist, track_title)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        artist_name,
                        mbid,
                        self.session_id,
                        bio_text,
                        int(time.time()),
                        norm_artist,
                        norm_title,
                    ),
                )
                await conn.commit()
                logging.debug("Recorded bio shown for %s (mbid=%s)", artist_name, mbid)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Error recording artist bio history: %s", error)
