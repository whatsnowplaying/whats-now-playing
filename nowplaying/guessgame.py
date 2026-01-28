#!/usr/bin/env python3
# pylint: disable=too-many-lines
"""Guess game handling for Twitch chat interaction"""

import asyncio
import json
import logging
import pathlib
import sqlite3
import string
import time
from typing import TYPE_CHECKING

import aiosqlite
from PySide6.QtCore import (  # pylint: disable=import-error,no-name-in-module
    QStandardPaths,
)

import nowplaying.utils
import nowplaying.utils.sqlite

if TYPE_CHECKING:
    import nowplaying.config

# Letter frequency groups for scoring
COMMON_LETTERS = set("eaiotusnr")
UNCOMMON_LETTERS = set(string.ascii_lowercase) - COMMON_LETTERS - set("qxzj")
RARE_LETTERS = set("qxzj")

# Characters to always reveal (don't blank out)
AUTO_REVEAL_CHARS = set(" -'&()[]{}.,!?;:0123456789")

# Common words that might be auto-revealed (if configured)
COMMON_WORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "feat",
    "ft",
    "featuring",
    "remix",
    "mix",
    "edit",
    "version",
    "remaster",
    "remastered",
}


class GuessGame:  # pylint: disable=too-many-instance-attributes
    """
    Manage guess game state, scoring, and leaderboards.

    Can be instantiated by multiple processes (TrackPoll, TwitchBot, WebServer)
    and communicates via a shared SQLite database.
    """

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        stopevent: asyncio.Event | None = None,
        testmode: bool = False,
    ):
        self.config = config
        self.stopevent = stopevent
        self.testmode = testmode

        # Database location in persistent app data directory
        self.databasefile = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.AppDataLocation)[0]
        ).joinpath("guessgame", "guessgame.db")

        # Initialize database if needed
        if not self.databasefile.exists():
            self.setupdb()
        else:
            # Migrate leaderboard tables if needed, recreate ephemeral tables
            self._migrate_database()

    def _migrate_database(self):
        """Migrate leaderboard tables if needed, recreate ephemeral tables"""
        with nowplaying.utils.sqlite.sqlite_connection(
            self.databasefile, timeout=30
        ) as connection:
            cursor = connection.cursor()

            # Create schema_version table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
            """)

            # Get current version
            cursor.execute("SELECT version FROM schema_version")
            row = cursor.fetchone()
            current_version = row[0] if row else 0

            # Current target version
            target_version = 1

            if current_version < target_version:
                logging.info(
                    "Migrating guess game database from v%d to v%d",
                    current_version,
                    target_version,
                )

                # Run migrations on preserved tables
                if current_version < 1:
                    # Migration 1: Add track_solved/artist_solved to user_scores if needed
                    # (Currently user_scores doesn't need these, only current_game does)
                    pass

                # Update version
                if current_version == 0:
                    cursor.execute(
                        "INSERT INTO schema_version (version) VALUES (?)", (target_version,)
                    )
                else:
                    cursor.execute("UPDATE schema_version SET version = ?", (target_version,))

                connection.commit()

            # Always recreate ephemeral tables (current_game, guesses, sessions)
            cursor.execute("DROP TABLE IF EXISTS current_game")
            cursor.execute("DROP TABLE IF EXISTS guesses")
            cursor.execute("DROP TABLE IF EXISTS sessions")

            # Recreate ephemeral tables with current schema
            cursor.execute("""
                CREATE TABLE current_game (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    track TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    masked_track TEXT NOT NULL,
                    masked_artist TEXT NOT NULL,
                    revealed_letters TEXT NOT NULL,
                    start_time INTEGER NOT NULL,
                    status TEXT DEFAULT 'active',
                    max_duration INTEGER DEFAULT 180,
                    game_id INTEGER,
                    difficulty_bonus INTEGER DEFAULT 0,
                    track_solved INTEGER DEFAULT 0,
                    artist_solved INTEGER DEFAULT 0,
                    CHECK (id = 1)
                )
            """)

            cursor.execute("""
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

            cursor.execute("""
                CREATE TABLE sessions (
                    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER
                )
            """)

            connection.commit()
            logging.debug("Guess game database migration complete")

    def setupdb(self):
        """Setup the database file for game state and scoring"""
        logging.debug("Setting up guess game database: %s", self.databasefile)
        self.databasefile.parent.mkdir(parents=True, exist_ok=True)

        # If database exists, try to delete it (fresh start)
        if self.databasefile.exists():
            for attempt in range(3):
                try:
                    self.databasefile.unlink()
                    break
                except OSError as error:
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    logging.warning("Could not delete guessgame.db after 3 attempts: %s", error)

        with nowplaying.utils.sqlite.sqlite_connection(
            self.databasefile, timeout=30
        ) as connection:
            cursor = connection.cursor()
            try:
                # Schema version tracking
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY
                    )
                """)
                cursor.execute("INSERT INTO schema_version (version) VALUES (1)")

                # Current game state (single row, id=1)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS current_game (
                        id INTEGER PRIMARY KEY DEFAULT 1,
                        track TEXT NOT NULL,
                        artist TEXT NOT NULL,
                        masked_track TEXT NOT NULL,
                        masked_artist TEXT NOT NULL,
                        revealed_letters TEXT NOT NULL,
                        start_time INTEGER NOT NULL,
                        status TEXT DEFAULT 'active',
                        max_duration INTEGER DEFAULT 180,
                        game_id INTEGER,
                        difficulty_bonus INTEGER DEFAULT 0,
                        track_solved INTEGER DEFAULT 0,
                        artist_solved INTEGER DEFAULT 0,
                        CHECK (id = 1)
                    )
                """)

                # Historical guesses
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS guesses (
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

                # User scores
                cursor.execute("""
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

                # Game history
                cursor.execute("""
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

                # Sessions
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        start_time INTEGER NOT NULL,
                        end_time INTEGER
                    )
                """)

                connection.commit()
                logging.info("Guess game database created successfully")

            except sqlite3.OperationalError as error:
                logging.error("Failed to create guess game database: %s", error)

    def vacuum_database(self):
        """Vacuum the database to reclaim space"""
        if not self.databasefile.exists():
            return
        try:
            with nowplaying.utils.sqlite.sqlite_connection(
                self.databasefile, timeout=30
            ) as connection:
                logging.debug("Vacuuming guess game database...")
                connection.execute("VACUUM")
                connection.commit()
                logging.info("Guess game database vacuumed successfully")
        except sqlite3.Error as error:
            logging.error("Database error during vacuum: %s", error)

    def _get_config(self, key: str, default, value_type=None):
        """Helper to get config values with defaults"""
        if not self.config:
            return default
        full_key = f"guessgame/{key}"
        if value_type:
            return self.config.cparser.value(full_key, type=value_type, defaultValue=default)
        return self.config.cparser.value(full_key, defaultValue=default)

    def is_enabled(self) -> bool:
        """Check if guess game is enabled"""
        return self._get_config("enabled", False, bool)

    @staticmethod
    def _normalize_for_matching(text: str) -> str:
        """
        Normalize text for guess matching.
        Treats &, 'n', 'n, and 'and' as equivalent.
        Strips censoring characters (*, _, -) to handle censored/uncensored variations.

        Args:
            text: Text to normalize

        Returns:
            Normalized text for matching
        """
        # Replace & with 'and' for consistent matching
        normalized = text.replace("&", "and")

        # Handle 'n' and 'n as abbreviations for 'and' (rock 'n' roll, rock 'n roll, rock n roll)
        normalized = normalized.replace(" 'n' ", " and ")
        normalized = normalized.replace(" 'n ", " and ")
        normalized = normalized.replace(" n ", " and ")

        # Strip censoring and punctuation characters to handle variations
        # (e.g., "f***k" matches "fuck", "N.W.A" matches "NWA")
        normalized = normalized.replace("*", "")
        normalized = normalized.replace("_", "")
        normalized = normalized.replace("-", "")
        normalized = normalized.replace(".", "")

        # Clean up multiple spaces
        normalized = normalized.replace("  ", " ").strip()

        return normalized

    @staticmethod
    def _mask_text(text: str, revealed_letters: set[str], auto_reveal_words: bool = False) -> str:
        """
        Mask text with blanks for unrevealed letters.

        Args:
            text: Original text to mask
            revealed_letters: Set of letters that have been guessed
            auto_reveal_words: If True, auto-reveal common words

        Returns:
            Masked text with _ for unrevealed letters
        """
        if not text:
            return ""

        masked = []
        words = text.split()

        for word in words:
            if auto_reveal_words and word.lower() in COMMON_WORDS:
                # Reveal entire common word
                masked.append(word)
            else:
                # Mask individual characters
                masked_word = ""
                for char in word:
                    char_lower = char.lower()
                    if char in AUTO_REVEAL_CHARS:
                        # Always reveal spaces, punctuation, numbers
                        masked_word += char
                    elif char_lower in revealed_letters:
                        # Revealed letter - show it with original case
                        masked_word += char
                    elif char.isalpha():
                        # Unrevealed letter - blank it out
                        masked_word += "_"
                    else:
                        # Other characters (should be covered by AUTO_REVEAL_CHARS)
                        masked_word += char
                masked.append(masked_word)

        return " ".join(masked)

    @staticmethod
    def _calculate_difficulty(track: str, artist: str, revealed_letters: set[str]) -> float:
        """
        Calculate the difficulty of the current game as percentage of letters still hidden.

        Returns:
            Float between 0.0 and 1.0 representing percentage of unrevealed letters
        """
        combined = track + artist

        # Count letters only (not spaces, punctuation, etc)
        total_letters = sum(1 for char in combined if char.isalpha())
        if total_letters == 0:
            return 0.0

        # Count unrevealed letters
        unrevealed_count = sum(
            1 for char in combined if char.isalpha() and char.lower() not in revealed_letters
        )

        return unrevealed_count / total_letters

    def _calculate_points(self, guess: str, guess_type: str, is_first_solver: bool = False) -> int:
        """
        Calculate points for a guess based on type and configuration.

        Args:
            guess: The guessed letter/word
            guess_type: 'letter', 'word', or 'solve'
            is_first_solver: Whether this guess completes the game

        Returns:
            Points awarded (can be negative for wrong guesses)
        """
        if guess_type == "letter":
            # Letter scoring based on frequency
            letter_lower = guess.lower()
            if letter_lower in RARE_LETTERS:
                return self._get_config("points_rare_letter", 3, int)
            if letter_lower in COMMON_LETTERS:
                return self._get_config("points_common_letter", 1, int)
            # Uncommon letters
            return self._get_config("points_uncommon_letter", 2, int)

        if guess_type == "word":
            return self._get_config("points_correct_word", 10, int)

        if guess_type == "solve":
            points = self._get_config("points_complete_solve", 100, int)
            if is_first_solver:
                points += self._get_config("points_first_solver", 50, int)
            return points

        # Wrong guess penalty
        return self._get_config("points_wrong_word", -1, int)

    async def start_new_game(self, track: str, artist: str) -> bool:  # pylint: disable=too-many-locals
        """
        Start a new game for the given track and artist.
        Called by TrackPoll when a new track is detected.

        Args:
            track: Track title
            artist: Artist name

        Returns:
            True if game started successfully
        """
        if not self.is_enabled():
            logging.debug("Guess game disabled, not starting new game")
            return False

        if not track or not artist:
            logging.warning("Cannot start game without track and artist")
            return False

        logging.info("Starting new guess game: %s - %s", artist, track)

        auto_reveal_words = self._get_config("auto_reveal_common_words", False, bool)
        max_duration = self._get_config("maxduration", 180, int)
        difficulty_threshold = self._get_config("difficulty_threshold", 0.70, float)

        # Initial revealed letters (empty set)
        revealed_letters: set[str] = set()

        # Calculate initial masks
        masked_track = self._mask_text(track, revealed_letters, auto_reveal_words)
        masked_artist = self._mask_text(artist, revealed_letters, auto_reveal_words)

        # Calculate difficulty for first solver bonus eligibility
        difficulty = self._calculate_difficulty(track, artist, revealed_letters)
        difficulty_bonus = 1 if difficulty >= difficulty_threshold else 0

        start_time = int(time.time())

        try:
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                cursor = await connection.cursor()

                # Create game history record
                await cursor.execute(
                    """
                    INSERT INTO game_history (track, artist, start_time)
                    VALUES (?, ?, ?)
                """,
                    (track, artist, start_time),
                )

                game_id = cursor.lastrowid

                # Clear and insert current game state
                await cursor.execute("DELETE FROM current_game")
                await cursor.execute(
                    """
                    INSERT INTO current_game
                    (id, track, artist, masked_track, masked_artist, revealed_letters,
                     start_time, status, max_duration, game_id, difficulty_bonus,
                     track_solved, artist_solved)
                    VALUES (1, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, 0, 0)
                """,
                    (
                        track,
                        artist,
                        masked_track,
                        masked_artist,
                        json.dumps(list(revealed_letters)),
                        start_time,
                        max_duration,
                        game_id,
                        difficulty_bonus,
                    ),
                )

                await connection.commit()
                logging.info(
                    "New guess game started (game_id=%s, difficulty=%.2f, bonus=%s)",
                    game_id,
                    difficulty,
                    difficulty_bonus,
                )
                return True

        except sqlite3.Error as error:
            logging.error("Failed to start new game: %s", error)
            return False

    async def process_guess(self, username: str, guess_text: str) -> dict | None:  # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-return-statements
        """
        Process a user's guess and update game state.
        Called by TwitchBot when !guess command received.

        Args:
            username: Username of the guesser
            guess_text: The guessed letter/word/phrase

        Returns:
            Dict with result info, or None if game not active or error occurred
            {
                'correct': bool,
                'guess_type': 'letter'|'word'|'solve'|'wrong',
                'points': int,
                'masked_track': str,
                'masked_artist': str,
                'solved': bool,
                'already_guessed': bool
            }
        """
        if not self.is_enabled():
            return None

        if not username or not guess_text:
            return None

        # Normalize guess
        guess_text = guess_text.strip().lower()
        if not guess_text:
            return None

        try:
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()

                # Get current game state
                await cursor.execute("SELECT * FROM current_game WHERE id = 1")
                game_row = await cursor.fetchone()

                if not game_row or game_row["status"] != "active":
                    logging.debug("No active game for guess from %s", username)
                    return None

                track = game_row["track"]
                artist = game_row["artist"]
                revealed_letters = set(json.loads(game_row["revealed_letters"]))
                game_id = game_row["game_id"]
                difficulty_bonus = game_row["difficulty_bonus"]
                track_solved = bool(game_row["track_solved"])
                artist_solved = bool(game_row["artist_solved"])
                auto_reveal_words = self._get_config("auto_reveal_common_words", False, bool)
                solve_mode = self._get_config("solve_mode", "separate_solves")

                # Determine guess type and correctness
                result = {
                    "correct": False,
                    "guess_type": "wrong",
                    "points": 0,
                    "masked_track": game_row["masked_track"],
                    "masked_artist": game_row["masked_artist"],
                    "solved": False,
                    "already_guessed": False,
                    "track_solved": track_solved,
                    "artist_solved": artist_solved,
                    "solve_type": None,  # "track", "artist", or "both"
                }

                # Single letter guess
                if len(guess_text) == 1 and guess_text.isalpha():
                    if guess_text in revealed_letters:
                        result["already_guessed"] = True
                        return result

                    # Check if letter exists in track or artist
                    combined_lower = (track + artist).lower()
                    if guess_text in combined_lower:
                        # Correct letter
                        result["correct"] = True
                        result["guess_type"] = "letter"
                        revealed_letters.add(guess_text)
                        result["points"] = self._calculate_points(guess_text, "letter")
                    else:
                        # Wrong letter
                        result["correct"] = False
                        result["guess_type"] = "letter"
                        result["points"] = 0  # No penalty for wrong letters

                # Word/phrase guess
                else:
                    track_lower = track.lower()
                    artist_lower = artist.lower()
                    # Normalize for matching (& and 'and' are equivalent)
                    guess_normalized = self._normalize_for_matching(guess_text)
                    track_normalized = self._normalize_for_matching(track_lower)
                    artist_normalized = self._normalize_for_matching(artist_lower)
                    track_match = guess_normalized == track_normalized
                    artist_match = guess_normalized == artist_normalized

                    # Handle different solve modes
                    if solve_mode == "either":
                        # Original behavior: exact match of track OR artist wins
                        if track_match or artist_match:
                            result["correct"] = True
                            result["guess_type"] = "solve"
                            revealed_letters.update(
                                char.lower() for char in track + artist if char.isalpha()
                            )
                            is_first_solver = difficulty_bonus == 1
                            result["points"] = self._calculate_points(
                                guess_text, "solve", is_first_solver
                            )
                            result["solved"] = True
                            result["solve_type"] = "both"
                        elif (
                            guess_normalized in track_normalized
                            or guess_normalized in artist_normalized
                        ):
                            # Correct word within track/artist
                            result["correct"] = True
                            result["guess_type"] = "word"
                            for char in guess_text:
                                if char.isalpha():
                                    revealed_letters.add(char)
                            result["points"] = self._calculate_points(guess_text, "word")
                        else:
                            result["correct"] = False
                            result["guess_type"] = "wrong"
                            result["points"] = self._calculate_points(guess_text, "wrong")

                    elif solve_mode == "both_required":
                        # Must have both track and artist in the guess to win
                        has_both = (
                            track_normalized in guess_normalized
                            and artist_normalized in guess_normalized
                        )
                        if has_both:
                            result["correct"] = True
                            result["guess_type"] = "solve"
                            revealed_letters.update(
                                char.lower() for char in track + artist if char.isalpha()
                            )
                            is_first_solver = difficulty_bonus == 1
                            result["points"] = self._calculate_points(
                                guess_text, "solve", is_first_solver
                            )
                            result["solved"] = True
                            result["solve_type"] = "both"
                        elif (
                            guess_normalized in track_normalized
                            or guess_normalized in artist_normalized
                        ):
                            # Correct word within track/artist
                            result["correct"] = True
                            result["guess_type"] = "word"
                            for char in guess_text:
                                if char.isalpha():
                                    revealed_letters.add(char)
                            result["points"] = self._calculate_points(guess_text, "word")
                        else:
                            result["correct"] = False
                            result["guess_type"] = "wrong"
                            result["points"] = self._calculate_points(guess_text, "wrong")

                    else:  # separate_solves (default)
                        # Track and artist are independent objectives
                        if track_match and not track_solved:
                            # Solved the track
                            result["correct"] = True
                            result["guess_type"] = "solve"
                            result["solve_type"] = "track"
                            track_solved = True
                            result["track_solved"] = True
                            # Reveal all track letters
                            revealed_letters.update(
                                char.lower() for char in track if char.isalpha()
                            )
                            # Award partial solve points
                            complete_solve_points = self._get_config(
                                "points_complete_solve", 100, int
                            )
                            result["points"] = complete_solve_points // 2
                            # Check if game is now complete
                            if artist_solved:
                                result["solved"] = True
                                result["solve_type"] = "both"
                                # Award completion bonus
                                is_first_solver = difficulty_bonus == 1
                                if is_first_solver:
                                    result["points"] += self._get_config(
                                        "points_first_solver", 50, int
                                    )
                        elif artist_match and not artist_solved:
                            # Solved the artist
                            result["correct"] = True
                            result["guess_type"] = "solve"
                            result["solve_type"] = "artist"
                            artist_solved = True
                            result["artist_solved"] = True
                            # Reveal all artist letters
                            revealed_letters.update(
                                char.lower() for char in artist if char.isalpha()
                            )
                            # Award partial solve points
                            complete_solve_points = self._get_config(
                                "points_complete_solve", 100, int
                            )
                            result["points"] = complete_solve_points // 2
                            # Check if game is now complete
                            if track_solved:
                                result["solved"] = True
                                result["solve_type"] = "both"
                                # Award completion bonus
                                is_first_solver = difficulty_bonus == 1
                                if is_first_solver:
                                    result["points"] += self._get_config(
                                        "points_first_solver", 50, int
                                    )
                        elif (track_match and track_solved) or (artist_match and artist_solved):
                            # Already solved this part
                            result["correct"] = False
                            result["guess_type"] = "already_solved"
                            result["points"] = 0
                        elif (
                            guess_normalized in track_normalized
                            or guess_normalized in artist_normalized
                        ):
                            # Correct word within track/artist
                            result["correct"] = True
                            result["guess_type"] = "word"
                            for char in guess_text:
                                if char.isalpha():
                                    revealed_letters.add(char)
                            result["points"] = self._calculate_points(guess_text, "word")
                        else:
                            result["correct"] = False
                            result["guess_type"] = "wrong"
                            result["points"] = self._calculate_points(guess_text, "wrong")

                # Update masked strings
                result["masked_track"] = self._mask_text(
                    track, revealed_letters, auto_reveal_words
                )
                result["masked_artist"] = self._mask_text(
                    artist, revealed_letters, auto_reveal_words
                )

                # Check if game is now completely solved (no more blanks)
                if "_" not in result["masked_track"] and "_" not in result["masked_artist"]:
                    result["solved"] = True
                    if result["guess_type"] != "solve":
                        # Award solve bonus if not already a full solve guess
                        is_first_solver = difficulty_bonus == 1
                        result["points"] += self._calculate_points("", "solve", is_first_solver)
                        result["guess_type"] = "solve"

                # Record guess in history
                timestamp = int(time.time())
                await cursor.execute(
                    """
                    INSERT INTO guesses
                    (game_id, username, guess, guess_type, correct, points_awarded, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        game_id,
                        username,
                        guess_text,
                        result["guess_type"],
                        1 if result["correct"] else 0,
                        result["points"],
                        timestamp,
                    ),
                )

                # Update user scores
                await self._update_user_scores(
                    cursor, username, result["points"], 1 if result["solved"] else 0, timestamp
                )

                # Update current game state
                # Note: difficulty_bonus is preserved from game start - not updated per guess
                await cursor.execute(
                    """
                    UPDATE current_game SET
                        masked_track = ?,
                        masked_artist = ?,
                        revealed_letters = ?,
                        track_solved = ?,
                        artist_solved = ?
                    WHERE id = 1
                """,
                    (
                        result["masked_track"],
                        result["masked_artist"],
                        json.dumps(list(revealed_letters)),
                        1 if track_solved else 0,
                        1 if artist_solved else 0,
                    ),
                )

                # Update game history guess count
                await cursor.execute(
                    """
                    UPDATE game_history SET total_guesses = total_guesses + 1
                    WHERE game_id = ?
                """,
                    (game_id,),
                )

                # If solved, end the game
                if result["solved"]:
                    await cursor.execute("""
                        UPDATE current_game SET status = 'solved'
                        WHERE id = 1
                    """)
                    await cursor.execute(
                        """
                        UPDATE game_history SET
                            end_time = ?,
                            end_reason = 'solved',
                            solver_username = ?
                        WHERE game_id = ?
                    """,
                        (timestamp, username, game_id),
                    )
                    logging.info("Game solved by %s! Points: %d", username, result["points"])

                await connection.commit()
                return result

        except sqlite3.Error as error:
            logging.error("Failed to process guess: %s", error)
            return None

    @staticmethod
    async def _update_user_scores(  # pylint: disable=too-many-arguments
        cursor: aiosqlite.Cursor, username: str, points: int, solves: int, timestamp: int
    ):
        """Update user scores in database (helper method)"""
        # Check if user exists
        await cursor.execute("SELECT username FROM user_scores WHERE username = ?", (username,))
        existing = await cursor.fetchone()

        if existing:
            # Update existing user
            await cursor.execute(
                """
                UPDATE user_scores SET
                    session_score = session_score + ?,
                    all_time_score = all_time_score + ?,
                    session_solves = session_solves + ?,
                    all_time_solves = all_time_solves + ?,
                    session_guesses = session_guesses + 1,
                    all_time_guesses = all_time_guesses + 1,
                    last_updated = ?
                WHERE username = ?
            """,
                (points, points, solves, solves, timestamp, username),
            )
        else:
            # Create new user record
            await cursor.execute(
                """
                INSERT INTO user_scores
                (username, session_score, all_time_score, session_solves,
                 all_time_solves, session_guesses, all_time_guesses, last_updated)
                VALUES (?, ?, ?, ?, ?, 1, 1, ?)
            """,
                (username, points, points, solves, solves, timestamp),
            )

    async def end_game(self, reason: str = "timeout") -> bool:
        """
        End the current game.
        Called by TrackPoll when timer expires or track changes.

        Args:
            reason: 'timeout', 'track_change', or 'solved'

        Returns:
            True if game ended successfully
        """
        if not self.is_enabled():
            return False

        try:
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                cursor = await connection.cursor()

                # Get current game
                await cursor.execute("SELECT game_id, status FROM current_game WHERE id = 1")
                game_row = await cursor.fetchone()

                if not game_row:
                    logging.debug("No active game to end")
                    return False

                game_id, status = game_row

                if status != "active":
                    logging.debug("Game already ended with status: %s", status)
                    return False

                timestamp = int(time.time())

                # Update game status
                await cursor.execute(
                    """
                    UPDATE current_game SET status = ?
                    WHERE id = 1
                """,
                    (reason,),
                )

                # Update game history
                await cursor.execute(
                    """
                    UPDATE game_history SET
                        end_time = ?,
                        end_reason = ?
                    WHERE game_id = ?
                """,
                    (timestamp, reason, game_id),
                )

                await connection.commit()
                logging.info("Game ended: %s (game_id=%s)", reason, game_id)
                return True

        except sqlite3.Error as error:
            logging.error("Failed to end game: %s", error)
            return False

    async def get_current_state(self) -> dict | None:
        """
        Get current game state for WebSocket broadcast.
        Called by WebServer broadcast task.

        Returns:
            Dict with game state or None if no active game
        """
        if not self.is_enabled():
            return None

        try:
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()

                # Get current game
                await cursor.execute("SELECT * FROM current_game WHERE id = 1")
                game_row = await cursor.fetchone()

                if not game_row:
                    return {
                        "status": "waiting",
                        "masked_track": "",
                        "masked_artist": "",
                        "time_remaining": 0,
                        "time_elapsed": 0,
                    }

                current_time = int(time.time())
                elapsed = current_time - game_row["start_time"]
                remaining = max(0, game_row["max_duration"] - elapsed)

                state = {
                    "game_id": game_row["game_id"],
                    "status": game_row["status"],
                    "masked_track": game_row["masked_track"],
                    "masked_artist": game_row["masked_artist"],
                    "time_remaining": remaining,
                    "time_elapsed": elapsed,
                }

                # If game ended, include revealed answers
                if game_row["status"] != "active":
                    state["revealed_track"] = game_row["track"]
                    state["revealed_artist"] = game_row["artist"]

                # Get last guess
                await cursor.execute(
                    """
                    SELECT username, guess, correct, points_awarded
                    FROM guesses
                    WHERE game_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """,
                    (game_row["game_id"],),
                )
                last_guess = await cursor.fetchone()

                if last_guess:
                    state["last_guess"] = {
                        "username": last_guess["username"],
                        "guess": last_guess["guess"],
                        "correct": bool(last_guess["correct"]),
                        "points": last_guess["points_awarded"],
                    }

                # Get solver if solved
                if game_row["status"] == "solved":
                    await cursor.execute(
                        """
                        SELECT solver_username FROM game_history
                        WHERE game_id = ?
                    """,
                        (game_row["game_id"],),
                    )
                    solver_row = await cursor.fetchone()
                    if solver_row and solver_row["solver_username"]:
                        state["current_solver"] = solver_row["solver_username"]

                return state

        except sqlite3.Error as error:
            logging.error("Failed to get current state: %s", error)
            return None

    async def get_leaderboard(
        self, leaderboard_type: str = "session", limit: int = 10
    ) -> list[dict] | None:
        """
        Get leaderboard rankings.

        Args:
            leaderboard_type: 'session' or 'all_time'
            limit: Number of top entries to return

        Returns:
            List of dicts with rank, username, score, solves
        """
        if not self.is_enabled():
            return None

        # Whitelist column names to prevent SQL injection
        column_mapping = {
            "session": ("session_score", "session_solves"),
            "all_time": ("all_time_score", "all_time_solves"),
        }

        if leaderboard_type not in column_mapping:
            logging.error("Invalid leaderboard_type: %s", leaderboard_type)
            return None

        score_col, solves_col = column_mapping[leaderboard_type]

        try:
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()

                # Use validated column names (not from user input directly)
                query = f"""
                    SELECT username, {score_col} as score, {solves_col} as solves
                    FROM user_scores
                    WHERE {score_col} > 0
                    ORDER BY {score_col} DESC, {solves_col} DESC
                    LIMIT ?
                """

                await cursor.execute(query, (limit,))

                rows = await cursor.fetchall()

                leaderboard = []
                for rank, row in enumerate(rows, start=1):
                    leaderboard.append(
                        {
                            "rank": rank,
                            "username": row["username"],
                            "score": row["score"],
                            "solves": row["solves"],
                        }
                    )

                return leaderboard

        except sqlite3.Error as error:
            logging.error("Failed to get leaderboard: %s", error)
            return None

    async def get_user_stats(self, username: str) -> dict | None:
        """
        Get individual user statistics.
        Called by TwitchBot for !mystats command.

        Args:
            username: Username to look up

        Returns:
            Dict with user stats or None if not found
        """
        if not self.is_enabled():
            return None

        try:
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()

                await cursor.execute(
                    """
                    SELECT * FROM user_scores WHERE username = ?
                """,
                    (username,),
                )

                row = await cursor.fetchone()

                if not row:
                    return None

                return {
                    "username": row["username"],
                    "session_score": row["session_score"],
                    "all_time_score": row["all_time_score"],
                    "session_solves": row["session_solves"],
                    "all_time_solves": row["all_time_solves"],
                    "session_guesses": row["session_guesses"],
                    "all_time_guesses": row["all_time_guesses"],
                }

        except sqlite3.Error as error:
            logging.error("Failed to get user stats: %s", error)
            return None

    async def reset_session(self) -> bool:
        """
        Reset session scores for all users.
        Called by TwitchBot on startup.

        Returns:
            True if reset successful
        """
        if not self.is_enabled():
            return False

        try:
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                cursor = await connection.cursor()

                timestamp = int(time.time())

                # Create new session record
                await cursor.execute(
                    """
                    INSERT INTO sessions (start_time) VALUES (?)
                """,
                    (timestamp,),
                )

                # Reset session scores for all users
                await cursor.execute(
                    """
                    UPDATE user_scores SET
                        session_score = 0,
                        session_solves = 0,
                        session_guesses = 0,
                        last_updated = ?
                """,
                    (timestamp,),
                )

                await connection.commit()
                logging.info("Session scores reset")
                return True

        except sqlite3.Error as error:
            logging.error("Failed to reset session: %s", error)
            return False

    async def check_game_timeout(self) -> bool:
        """
        Check if current game has exceeded max duration.
        Called by TrackPoll timer task.

        Returns:
            True if game was timed out, False if still active or no game
        """
        if not self.is_enabled():
            return False

        try:
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()

                await cursor.execute("""
                    SELECT start_time, max_duration, status
                    FROM current_game WHERE id = 1
                """)
                game_row = await cursor.fetchone()

                if not game_row or game_row["status"] != "active":
                    return False

                current_time = int(time.time())
                elapsed = current_time - game_row["start_time"]

                if elapsed >= game_row["max_duration"]:
                    # Game has timed out
                    logging.info("Game timed out after %d seconds", elapsed)
                    await self.end_game(reason="timeout")
                    return True

                return False

        except sqlite3.Error as error:
            logging.error("Failed to check game timeout: %s", error)
            return False

    def clear_leaderboards(self) -> bool:
        """
        Clear all user scores from the leaderboards.
        This deletes all entries from the user_scores table.

        Returns:
            True if cleared successfully, False on error
        """
        try:
            with nowplaying.utils.sqlite.sqlite_connection(
                str(self.databasefile), timeout=30
            ) as connection:
                cursor = connection.cursor()

                # Delete all user scores
                cursor.execute("DELETE FROM user_scores")

                connection.commit()
                logging.info("All leaderboards cleared")
                return True

        except sqlite3.Error as error:
            logging.error("Failed to clear leaderboards: %s", error)
            return False
