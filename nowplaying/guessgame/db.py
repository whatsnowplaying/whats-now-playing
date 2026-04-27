#!/usr/bin/env python3
"""Guess game database management"""

import logging
import pathlib
import sqlite3

from PySide6.QtCore import (  # pylint: disable=import-error,no-name-in-module
    QStandardPaths,
)

import nowplaying.utils.sqlite


def get_database_path() -> pathlib.Path:
    """Return the path to the guessgame database file."""
    return pathlib.Path(
        QStandardPaths.standardLocations(QStandardPaths.AppDataLocation)[0]
    ).joinpath("guessgame", "guessgame.db")


def initialize_database(databasefile: pathlib.Path | None = None) -> None:
    """Initialize or migrate the database.

    Call once from the main process before subprocesses start.
    Accepts an optional databasefile path for testing.
    """
    if databasefile is None:
        databasefile = get_database_path()

    logging.debug("Initializing guess game database: %s", databasefile)
    try:
        databasefile.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        logging.error("Failed to create guess game database directory: %s", error)
        return

    try:
        with nowplaying.utils.sqlite.sqlite_connection(
            str(databasefile), timeout=30
        ) as connection:
            cursor = connection.cursor()

            # Persistent tables: schema_version tracks migrations
            _ = cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
            """)

            # Get/set schema version and run any pending migrations
            cursor.execute("SELECT version FROM schema_version")
            row = cursor.fetchone()
            current_version = row[0] if row else 0
            target_version = 1

            if current_version < target_version:
                logging.info(
                    "Migrating guess game database from v%d to v%d",
                    current_version,
                    target_version,
                )
                # Add future migration steps here as needed
                if current_version == 0:
                    _ = cursor.execute(
                        "INSERT INTO schema_version (version) VALUES (?)", (target_version,)
                    )
                else:
                    _ = cursor.execute("UPDATE schema_version SET version = ?", (target_version,))
                connection.commit()

            # Persistent tables: survive app restarts
            _ = cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_scores (
                    username TEXT COLLATE NOCASE PRIMARY KEY,
                    session_score INTEGER DEFAULT 0,
                    all_time_score INTEGER DEFAULT 0,
                    session_solves INTEGER DEFAULT 0,
                    all_time_solves INTEGER DEFAULT 0,
                    session_guesses INTEGER DEFAULT 0,
                    all_time_guesses INTEGER DEFAULT 0,
                    last_updated INTEGER NOT NULL
                )
            """)

            _ = cursor.execute("""
                CREATE TABLE IF NOT EXISTS game_history (
                    game_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    track TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER,
                    end_reason TEXT,
                    solver_username TEXT COLLATE NOCASE,
                    total_guesses INTEGER DEFAULT 0
                )
            """)

            # Ephemeral tables: always recreate on startup to clear previous session state
            _ = cursor.execute("DROP TABLE IF EXISTS current_game")
            _ = cursor.execute("DROP TABLE IF EXISTS guesses")
            _ = cursor.execute("DROP TABLE IF EXISTS sessions")

            _ = cursor.execute("""
                CREATE TABLE current_game (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    track TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    masked_track TEXT NOT NULL,
                    masked_artist TEXT NOT NULL,
                    revealed_letters TEXT NOT NULL,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER,
                    status TEXT DEFAULT 'active',
                    max_duration INTEGER DEFAULT 180,
                    game_id INTEGER,
                    difficulty_bonus INTEGER DEFAULT 0,
                    track_solved INTEGER DEFAULT 0,
                    artist_solved INTEGER DEFAULT 0,
                    CHECK (id = 1)
                )
            """)

            _ = cursor.execute("""
                CREATE TABLE guesses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER NOT NULL,
                    username TEXT COLLATE NOCASE NOT NULL,
                    guess TEXT NOT NULL,
                    guess_type TEXT NOT NULL,
                    correct INTEGER NOT NULL,
                    points_awarded INTEGER NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            """)

            _ = cursor.execute("""
                CREATE TABLE sessions (
                    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER
                )
            """)

            connection.commit()
            logging.debug("Guess game database initialization complete")
    except (OSError, sqlite3.Error) as error:
        logging.error("Failed to initialize guess game database: %s", error)


def vacuum_database() -> None:
    """Vacuum the database to reclaim space."""
    databasefile = get_database_path()
    if not databasefile.exists():
        return
    try:
        with nowplaying.utils.sqlite.sqlite_connection(
            str(databasefile), timeout=30
        ) as connection:
            logging.debug("Vacuuming guess game database...")
            _ = connection.execute("VACUUM")
            connection.commit()
            logging.info("Guess game database vacuumed successfully")
    except sqlite3.Error as error:
        logging.error("Database error during vacuum: %s", error)


def clear_leaderboards() -> bool:
    """
    Clear all user scores from the leaderboards.
    This deletes all entries from the user_scores table.

    Returns:
        True if cleared successfully, False on error
    """
    try:
        with nowplaying.utils.sqlite.sqlite_connection(
            str(get_database_path()), timeout=30
        ) as connection:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM user_scores")
            connection.commit()
            logging.info("All leaderboards cleared")
            return True

    except sqlite3.Error as error:
        logging.error("Failed to clear leaderboards: %s", error)
        return False


def remove_user_from_alltime(username: str) -> bool:
    """
    Remove a single user from the all-time leaderboard.

    Returns:
        True if removed successfully (including when user did not exist), False on error
    """
    if not username:
        return False
    try:
        with nowplaying.utils.sqlite.sqlite_connection(
            str(get_database_path()), timeout=30
        ) as connection:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM user_scores WHERE username = ? COLLATE NOCASE",
                (username,),
            )
            connection.commit()
            if cursor.rowcount > 0:
                logging.info("Removed user %s from all-time leaderboard", username)
            else:
                logging.info("User %s not found in all-time leaderboard", username)
            return True
    except sqlite3.Error as error:
        logging.error("Failed to remove user %s from leaderboard: %s", username, error)
        return False
