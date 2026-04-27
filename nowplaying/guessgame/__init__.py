#!/usr/bin/env python3
# pylint: disable=too-many-lines
"""Guess game handling for Twitch chat interaction"""

import asyncio
import json
import logging
import pathlib
import sqlite3
import time
from typing import TYPE_CHECKING, Any

import aiosqlite

import nowplaying.guessgame.db
import nowplaying.guessgame.scoring
import nowplaying.utils.sqlite
from nowplaying.guessgame.scoring import COMMON_LETTERS, RARE_LETTERS
from nowplaying.guessgame.server import GuessGameServerMixin

if TYPE_CHECKING:
    import nowplaying.config


class GuessGame(GuessGameServerMixin):  # pylint: disable=too-many-instance-attributes
    """
    Manage guess game state, scoring, and leaderboards.

    Can be instantiated by multiple processes (TrackPoll, TwitchBot, WebServer)
    and communicates via a shared SQLite database.
    """

    @staticmethod
    def _get_database_path() -> pathlib.Path:
        """Return the path to the guessgame database file."""
        return nowplaying.guessgame.db.get_database_path()

    @classmethod
    def initialize_database(cls, databasefile: pathlib.Path | None = None) -> None:
        """Initialize or migrate the database.

        Call once from the main process before subprocesses start.
        Accepts an optional databasefile path for testing.
        """
        nowplaying.guessgame.db.initialize_database(databasefile)

    @classmethod
    def vacuum_database(cls) -> None:
        """Vacuum the database to reclaim space."""
        nowplaying.guessgame.db.vacuum_database()

    @classmethod
    def clear_leaderboards(cls) -> bool:
        """
        Clear all user scores from the leaderboards.
        This deletes all entries from the user_scores table.

        Returns:
            True if cleared successfully, False on error
        """
        return nowplaying.guessgame.db.clear_leaderboards()

    @classmethod
    def remove_user_from_alltime(cls, username: str) -> bool:
        """
        Remove a single user from the all-time leaderboard.

        Returns:
            True if removed successfully (including when user did not exist), False on error
        """
        return nowplaying.guessgame.db.remove_user_from_alltime(username)

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        stopevent: asyncio.Event | None = None,
    ):
        self.config = config
        self.stopevent = stopevent
        self.last_game_end_time: float | None = None
        self._http_session = None

        self.databasefile = self._get_database_path()

        excluded_raw = self._get_config("excluded_users", "")
        self._excluded_users: frozenset[str] = frozenset(
            u.strip().lower() for u in excluded_raw.split(",") if u.strip()
        )

    def _get_config(self, key: str, default: Any, value_type: type | None = None) -> Any:
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

    def _process_word_guess(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        guess_text: str,
        guess_normalized: str,
        track: str,
        artist: str,
        track_normalized: str,
        artist_normalized: str,
        revealed_letters: set[str],
        result: dict[str, Any],
    ) -> None:
        """
        Process a word/phrase guess and update result with points and revealed letters.

        Checks if the guess matches words in track or artist, reveals new letters,
        and awards points only if new letters were revealed.

        Args:
            guess_text: Original guess text from user
            guess_normalized: Normalized guess text
            track: Original track name
            artist: Original artist name
            track_normalized: Normalized track name
            artist_normalized: Normalized artist name
            revealed_letters: Set of revealed letters (modified in place)
            result: Result dict (modified in place)
        """
        # Cache the word match results to avoid repeated regex operations
        track_has_word = nowplaying.guessgame.scoring.is_word_match(
            guess_normalized, track_normalized
        )
        artist_has_word = nowplaying.guessgame.scoring.is_word_match(
            guess_normalized, artist_normalized
        )

        if not track_has_word and not artist_has_word:
            return  # Not a word match

        # Track letters before revealing to check if anything new was revealed
        letters_before = revealed_letters.copy()

        # Reveal letters from matched words
        if track_has_word:
            nowplaying.guessgame.scoring.reveal_matching_word_letters(
                guess_normalized, track, track_normalized, revealed_letters
            )
        if artist_has_word:
            nowplaying.guessgame.scoring.reveal_matching_word_letters(
                guess_normalized, artist, artist_normalized, revealed_letters
            )

        # Only award points if new letters were revealed
        if revealed_letters != letters_before:
            result["correct"] = True
            result["guess_type"] = "word"
            result["points"] = self._calculate_points(guess_text, "word")
        else:
            # All letters already revealed - no points
            result["correct"] = False
            result["guess_type"] = "already_guessed"
            result["already_guessed"] = True
            result["points"] = 0

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

    def _mark_guess_as_wrong(self, result: dict, guess_text: str) -> None:
        """
        Mark a guess result as wrong if it's not already correct or already_guessed.

        Args:
            result: The result dictionary to modify
            guess_text: The original guess text for point calculation
        """
        if not result["correct"] and result["guess_type"] != "already_guessed":
            result["correct"] = False
            result["guess_type"] = "wrong"
            result["points"] = self._calculate_points(guess_text, "wrong")

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
        max_duration = self._get_config("maxduration", 120, int)
        difficulty_threshold = self._get_config("difficulty_threshold", 0.70, float)

        # Initial revealed letters (empty set)
        revealed_letters: set[str] = set()

        # Calculate initial masks
        masked_track = nowplaying.guessgame.scoring.mask_text(
            track, revealed_letters, auto_reveal_words
        )
        masked_artist = nowplaying.guessgame.scoring.mask_text(
            artist, revealed_letters, auto_reveal_words
        )

        # Calculate difficulty for first solver bonus eligibility
        difficulty = nowplaying.guessgame.scoring.calculate_difficulty(
            track, artist, revealed_letters
        )
        difficulty_bonus = 1 if difficulty >= difficulty_threshold else 0

        start_time = int(time.time())

        async def _do_start_new_game():
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

                local_game_id = cursor.lastrowid

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
                        local_game_id,
                        difficulty_bonus,
                    ),
                )

                await connection.commit()
                logging.info(
                    "New guess game started (game_id=%s, difficulty=%.2f, bonus=%s)",
                    local_game_id,
                    difficulty,
                    difficulty_bonus,
                )
                return True

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_start_new_game)
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

        async def _do_process_guess():  # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-return-statements
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                cursor = await connection.cursor()

                # Get current game state
                await cursor.execute("SELECT * FROM current_game WHERE id = 1")
                game_row = await cursor.fetchone()

                if not game_row:
                    logging.debug("No game for guess from %s", username)
                    return None

                # Check if game is active or within grace period
                if game_row["status"] != "active":
                    # Game has ended - check if we're within grace period
                    grace_period = self._get_config("grace_period", 5, int)
                    end_time = game_row["end_time"]

                    if not end_time:
                        # Game ended but no end_time recorded (shouldn't happen)
                        logging.debug("Game ended but no end_time for guess from %s", username)
                        return None

                    current_time = int(time.time())
                    # Clamp to 0 to handle clock skew where end_time is in the future
                    elapsed_since_end = max(0, current_time - end_time)

                    if elapsed_since_end >= grace_period:
                        logging.debug(
                            "Game ended %ds ago (grace period: %ds), rejecting guess from %s",
                            elapsed_since_end,
                            grace_period,
                            username,
                        )
                        return None

                    logging.debug(
                        "Accepting guess from %s during grace period (%ds remaining)",
                        username,
                        grace_period - elapsed_since_end,
                    )

                track = game_row["track"]
                artist = game_row["artist"]
                revealed_letters = set(json.loads(game_row["revealed_letters"]))
                game_id = game_row["game_id"]
                difficulty_bonus = game_row["difficulty_bonus"]
                is_first_solver = bool(difficulty_bonus)
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
                    guess_normalized = nowplaying.guessgame.scoring.normalize_for_matching(
                        guess_text
                    )
                    track_normalized = nowplaying.guessgame.scoring.normalize_for_matching(
                        track_lower
                    )
                    artist_normalized = nowplaying.guessgame.scoring.normalize_for_matching(
                        artist_lower
                    )
                    logging.debug(
                        "Guess normalization: guess=%s->%s, artist=%s->%s",
                        repr(guess_text),
                        repr(guess_normalized),
                        repr(artist),
                        repr(artist_normalized),
                    )
                    track_match = guess_normalized == track_normalized
                    artist_match = guess_normalized == artist_normalized
                    # Also treat a guess as a full artist solve when every word in the
                    # normalized artist concatenates to form the guess.
                    # e.g. "rundmc" solves artist "Run‐D.M.C." (normalized "rund m c")
                    if not artist_match:
                        artist_words = artist_normalized.split()
                        seq = nowplaying.guessgame.scoring.find_concatenated_sequence(
                            guess_normalized, artist_words
                        )
                        artist_match = seq == (0, len(artist_words))
                    if not track_match:
                        track_words = track_normalized.split()
                        seq = nowplaying.guessgame.scoring.find_concatenated_sequence(
                            guess_normalized, track_words
                        )
                        track_match = seq == (0, len(track_words))

                    # Handle different solve modes
                    if solve_mode == "either":
                        # Original behavior: exact match of track OR artist wins
                        if track_match or artist_match:
                            result["correct"] = True
                            result["guess_type"] = "solve"
                            revealed_letters.update(
                                char.lower() for char in track + artist if char.isalpha()
                            )
                            result["points"] = self._calculate_points(
                                guess_text, "solve", is_first_solver
                            )
                            result["solved"] = True
                            result["solve_type"] = "both"
                        else:
                            # Try word/phrase match
                            self._process_word_guess(
                                guess_text,
                                guess_normalized,
                                track,
                                artist,
                                track_normalized,
                                artist_normalized,
                                revealed_letters,
                                result,
                            )
                            self._mark_guess_as_wrong(result, guess_text)

                    elif solve_mode == "both_required":
                        # Must have both track and artist in the guess to win
                        has_both = nowplaying.guessgame.scoring.phrase_in_guess(
                            track_normalized, guess_normalized
                        ) and nowplaying.guessgame.scoring.phrase_in_guess(
                            artist_normalized, guess_normalized
                        )
                        if has_both:
                            result["correct"] = True
                            result["guess_type"] = "solve"
                            revealed_letters.update(
                                char.lower() for char in track + artist if char.isalpha()
                            )
                            result["points"] = self._calculate_points(
                                guess_text, "solve", is_first_solver
                            )
                            result["solved"] = True
                            result["solve_type"] = "both"
                        else:
                            # Try word/phrase match
                            self._process_word_guess(
                                guess_text,
                                guess_normalized,
                                track,
                                artist,
                                track_normalized,
                                artist_normalized,
                                revealed_letters,
                                result,
                            )
                            self._mark_guess_as_wrong(result, guess_text)

                    # One-shot solve: guess contains both track and artist
                    elif (
                        not track_solved
                        and not artist_solved
                        and nowplaying.guessgame.scoring.phrase_in_guess(
                            track_normalized, guess_normalized
                        )
                        and nowplaying.guessgame.scoring.phrase_in_guess(
                            artist_normalized, guess_normalized
                        )
                    ):
                        result["correct"] = True
                        result["guess_type"] = "solve"
                        result["solve_type"] = "both"
                        result["track_solved"] = True
                        result["artist_solved"] = True
                        result["solved"] = True
                        revealed_letters.update(
                            char.lower() for char in track + artist if char.isalpha()
                        )
                        result["points"] = self._calculate_points(
                            guess_text, "solve", is_first_solver
                        )

                    # Track and artist are independent objectives
                    elif track_match and not track_solved:
                        # Solved the track
                        result["correct"] = True
                        result["guess_type"] = "solve"
                        result["solve_type"] = "track"
                        track_solved = True
                        result["track_solved"] = True
                        # Reveal all track letters
                        revealed_letters.update(char.lower() for char in track if char.isalpha())
                        # Award partial solve points
                        complete_solve_points = self._get_config("points_complete_solve", 100, int)
                        result["points"] = complete_solve_points // 2
                        # Check if game is now complete
                        if artist_solved:
                            result["solved"] = True
                            result["solve_type"] = "both"
                            # Award completion bonus
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
                        revealed_letters.update(char.lower() for char in artist if char.isalpha())
                        # Award partial solve points
                        complete_solve_points = self._get_config("points_complete_solve", 100, int)
                        result["points"] = complete_solve_points // 2
                        # Check if game is now complete
                        if track_solved:
                            result["solved"] = True
                            result["solve_type"] = "both"
                            # Award completion bonus
                            if is_first_solver:
                                result["points"] += self._get_config(
                                    "points_first_solver", 50, int
                                )
                    elif (track_match and track_solved) or (artist_match and artist_solved):
                        # Already solved this part
                        result["correct"] = False
                        result["guess_type"] = "already_solved"
                        result["points"] = 0
                    else:
                        # Try word/phrase match
                        self._process_word_guess(
                            guess_text,
                            guess_normalized,
                            track,
                            artist,
                            track_normalized,
                            artist_normalized,
                            revealed_letters,
                            result,
                        )
                        self._mark_guess_as_wrong(result, guess_text)

                # Update masked strings
                result["masked_track"] = nowplaying.guessgame.scoring.mask_text(
                    track, revealed_letters, auto_reveal_words
                )
                result["masked_artist"] = nowplaying.guessgame.scoring.mask_text(
                    artist, revealed_letters, auto_reveal_words
                )

                # Check if game is now completely solved (no more blanks)
                if "_" not in result["masked_track"] and "_" not in result["masked_artist"]:
                    result["solved"] = True
                    result["solve_type"] = "both"
                    if result["guess_type"] != "solve":
                        # Award solve bonus if not already a full solve guess
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

                # Update user scores (skip excluded users)
                if username.lower() not in self._excluded_users:
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

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_process_guess)
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

        async def _do_end_game():
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

                # Update game status and end_time
                await cursor.execute(
                    """
                    UPDATE current_game SET status = ?, end_time = ?
                    WHERE id = 1
                """,
                    (reason, timestamp),
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

                # Track when game ended for announcement coordination
                self.last_game_end_time = time.time()
                return True

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_end_game)
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

        async def _do_get_current_state():
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

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(
                _do_get_current_state
            )
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

        async def _do_get_leaderboard():
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

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_get_leaderboard)
        except sqlite3.Error as error:
            logging.error("Failed to get leaderboard: %s", error)
            return None

    async def get_user_stats(self, username: str) -> dict | None:
        """
        Get individual user statistics.
        Called by TwitchBot for !mypoints command.

        Args:
            username: Username to look up

        Returns:
            Dict with user stats or None if not found
        """
        if not self.is_enabled():
            return None

        async def _do_get_user_stats():
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

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_get_user_stats)
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

        async def _do_reset_session():
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

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(_do_reset_session)
        except sqlite3.Error as error:
            logging.error("Failed to reset session: %s", error)
            return False

    async def may_publish(self) -> bool:
        """Return True if the deferred track can now be published (game ended or no game active).

        Called by TrackPoll during same-track idle cycles when a write is deferred.
        A disabled game always grants permission to avoid metadata staying deferred indefinitely.
        """
        if not self.is_enabled():
            return True
        state = await self.get_current_state()
        if not state or state.get("status") in ("solved", "timeout"):
            return True
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

        async def _do_check_game_timeout():
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

        try:
            return await nowplaying.utils.sqlite.retry_sqlite_operation_async(
                _do_check_game_timeout
            )
        except sqlite3.Error as error:
            logging.error("Failed to check game timeout: %s", error)
            return False
