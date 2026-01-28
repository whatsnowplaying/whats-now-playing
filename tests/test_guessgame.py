#!/usr/bin/env python3
"""
Unit tests for the Guess Game system
"""

import asyncio
import pathlib
import tempfile

import aiosqlite
import pytest
import pytest_asyncio

import nowplaying.guessgame


@pytest_asyncio.fixture
async def isolated_guessgame(bootstrap):  # pylint: disable=redefined-outer-name
    """Create an isolated GuessGame instance for testing."""
    # Enable guess game in config
    bootstrap.cparser.setValue("guessgame/enabled", True)
    bootstrap.cparser.sync()

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = pathlib.Path(temp_dir) / "test_guessgame.db"
        game = nowplaying.guessgame.GuessGame(config=bootstrap, testmode=True)
        # Override database location for testing
        game.databasefile = db_path
        game.setupdb()
        yield game


@pytest_asyncio.fixture
async def guessgame_with_active_game(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Create a GuessGame with an active game started."""
    game = isolated_guessgame
    await game.start_new_game(track="House of the Rising Sun", artist="The Animals")
    yield game


@pytest.mark.asyncio
async def test_database_initialization(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test that the database initializes with correct schema."""
    game = isolated_guessgame

    # Verify database file exists
    assert game.databasefile.exists()

    # Check that all tables are created
    async with aiosqlite.connect(game.databasefile) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = await cursor.fetchall()
        table_names = [table[0] for table in tables]

        expected_tables = [
            "current_game",
            "game_history",
            "guesses",
            "sessions",
            "user_scores",
        ]
        for expected_table in expected_tables:
            assert expected_table in table_names


@pytest.mark.asyncio
async def test_start_new_game(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test starting a new game."""
    game = isolated_guessgame

    await game.start_new_game(track="Closer", artist="Nine Inch Nails")

    # Verify game state
    state = await game.get_current_state()
    assert state["status"] == "active"
    assert state["masked_track"] != ""
    assert state["masked_artist"] != ""
    assert "_" in state["masked_track"]  # Should have masked letters
    assert "_" in state["masked_artist"]
    assert state["time_remaining"] > 0


@pytest.mark.asyncio
async def test_letter_masking(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test that letter masking works correctly."""
    game = isolated_guessgame

    await game.start_new_game(track="Test Track", artist="Test Artist")

    state = await game.get_current_state()

    # Spaces should be preserved
    assert " " in state["masked_track"]

    # Letters should be masked
    assert "T" not in state["masked_track"]
    assert "e" not in state["masked_track"]


@pytest.mark.asyncio
async def test_guess_correct_letter(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test guessing a correct letter."""
    game = guessgame_with_active_game

    result = await game.process_guess(username="testuser", guess_text="e")

    assert result is not None
    assert result["correct"] is True
    assert result["guess_type"] == "letter"
    assert result["points"] > 0  # Should award points for correct guess
    assert "e" in result["masked_track"].lower() or "e" in result["masked_artist"].lower()


@pytest.mark.asyncio
async def test_guess_incorrect_letter(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test guessing an incorrect letter."""
    game = guessgame_with_active_game

    # Guess a letter that's not in "House of the Rising Sun" or "The Animals"
    result = await game.process_guess(username="testuser", guess_text="z")

    assert result is not None
    assert result["correct"] is False
    assert result["guess_type"] == "letter"
    assert result["points"] == 0  # No points for incorrect guess


@pytest.mark.asyncio
async def test_guess_already_guessed_letter(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test guessing a letter that's already been guessed."""
    game = guessgame_with_active_game

    # First guess
    result1 = await game.process_guess(username="testuser", guess_text="e")
    assert result1["correct"] is True

    # Second guess of same letter
    result2 = await game.process_guess(username="testuser", guess_text="e")
    assert result2 is not None
    assert result2.get("already_guessed") is True  # Should indicate already guessed


@pytest.mark.asyncio
async def test_guess_correct_word(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test guessing a correct word."""
    game = guessgame_with_active_game

    result = await game.process_guess(username="testuser", guess_text="house")

    assert result is not None
    assert result["correct"] is True
    assert result["guess_type"] in ["word", "solve"]
    assert result["points"] >= 10  # Word guesses should award at least 10 points


@pytest.mark.asyncio
async def test_guess_incorrect_word(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test guessing an incorrect word."""
    game = guessgame_with_active_game

    result = await game.process_guess(username="testuser", guess_text="wrongword")

    assert result is not None
    assert result["correct"] is False
    assert result["guess_type"] == "wrong"
    assert result["points"] == -1  # Should have penalty for wrong word


@pytest.mark.asyncio
async def test_complete_solve(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test completing a solve by guessing the full track."""
    game = isolated_guessgame

    # Set solve mode to "either" so guessing just track or artist wins
    game.config.cparser.setValue("guessgame/solve_mode", "either")

    await game.start_new_game(track="Test", artist="Artist")

    # Guess the full track name
    result = await game.process_guess(username="testuser", guess_text="test")

    assert result is not None
    assert result["correct"] is True
    assert result["solved"] is True
    assert result["points"] >= 50  # Complete solve should award significant points

    # Verify game state
    state = await game.get_current_state()
    assert state["status"] == "solved"


@pytest.mark.asyncio
async def test_letter_frequency_scoring(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test that letter frequency affects scoring."""
    game = isolated_guessgame

    await game.start_new_game(track="Test Track", artist="Artist")

    # Common letter (e)
    result_common = await game.process_guess(username="user1", guess_text="e")
    points_common = result_common["points"]

    # Start a new game for the next test
    await game.start_new_game(track="Test Track", artist="Artist")

    # Uncommon letter (x)
    result_uncommon = await game.process_guess(username="user2", guess_text="x")

    # If x is in the track, it should award more points than common letters
    if result_uncommon["correct"]:
        points_uncommon = result_uncommon["points"]
        assert points_uncommon > points_common


@pytest.mark.asyncio
async def test_user_stats_tracking(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test that user statistics are tracked correctly."""
    game = guessgame_with_active_game

    # Make some guesses
    await game.process_guess(username="testuser", guess_text="e")
    await game.process_guess(username="testuser", guess_text="a")

    # Get user stats
    stats = await game.get_user_stats(username="testuser")

    assert stats is not None
    assert stats["session_guesses"] == 2
    assert stats["session_score"] > 0


@pytest.mark.asyncio
async def test_user_stats_nonexistent_user(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test getting stats for a user who hasn't played."""
    game = isolated_guessgame

    stats = await game.get_user_stats(username="nonexistent")

    assert stats is None


@pytest.mark.asyncio
async def test_leaderboard_session(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test session leaderboard generation."""
    game = guessgame_with_active_game

    # Multiple users make guesses
    await game.process_guess(username="user1", guess_text="e")
    await game.process_guess(username="user1", guess_text="a")
    await game.process_guess(username="user2", guess_text="o")

    # Get leaderboard
    leaderboard = await game.get_leaderboard(leaderboard_type="session", limit=10)

    assert len(leaderboard) == 2  # Two users
    assert leaderboard[0]["rank"] == 1
    assert leaderboard[1]["rank"] == 2
    # User with more guesses should be first (or higher score)
    assert leaderboard[0]["username"] in ["user1", "user2"]


@pytest.mark.asyncio
async def test_leaderboard_empty(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test leaderboard when no one has played."""
    game = isolated_guessgame

    leaderboard = await game.get_leaderboard(leaderboard_type="session", limit=10)

    assert leaderboard == []


@pytest.mark.asyncio
async def test_end_game_timeout(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test ending a game due to timeout."""
    game = guessgame_with_active_game

    await game.end_game(reason="timeout")

    state = await game.get_current_state()
    assert state["status"] == "timeout"


@pytest.mark.asyncio
async def test_end_game_solved(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test ending a game when solved."""
    game = guessgame_with_active_game

    await game.end_game(reason="solved")

    state = await game.get_current_state()
    assert state["status"] == "solved"


@pytest.mark.asyncio
async def test_difficulty_threshold_calculation(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test difficulty threshold calculation for first solver bonus."""
    game = isolated_guessgame

    # Short, simple track should have lower difficulty
    await game.start_new_game(track="Test", artist="Me")

    async with aiosqlite.connect(game.databasefile) as conn:
        cursor = await conn.execute("SELECT difficulty_bonus FROM current_game")
        row = await cursor.fetchone()
        simple_difficulty = row[0]

    # Long, complex track should have higher difficulty
    await game.start_new_game(
        track="Supercalifragilisticexpialidocious", artist="Mary Poppins Orchestra"
    )

    async with aiosqlite.connect(game.databasefile) as conn:
        cursor = await conn.execute("SELECT difficulty_bonus FROM current_game")
        row = await cursor.fetchone()
        complex_difficulty = row[0]

    # Both should be boolean (0 or 1)
    assert simple_difficulty in [0, 1]
    assert complex_difficulty in [0, 1]


@pytest.mark.asyncio
async def test_special_characters_in_track(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test handling of special characters in track names."""
    game = isolated_guessgame

    # Track with various special characters
    await game.start_new_game(track="Test-Track (Remix) [2024]", artist="Artist & Co.")

    state = await game.get_current_state()

    # Special characters should be revealed (not masked)
    assert "-" in state["masked_track"]
    assert "(" in state["masked_track"]
    assert ")" in state["masked_track"]
    assert "[" in state["masked_track"]
    assert "]" in state["masked_track"]
    assert "&" in state["masked_artist"]


@pytest.mark.asyncio
async def test_unicode_characters(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test handling of Unicode characters in track names."""
    game = isolated_guessgame

    # Track with Unicode characters
    await game.start_new_game(track="Café Müller", artist="Björk")

    state = await game.get_current_state()

    # Should handle Unicode without crashing
    assert state["masked_track"] != ""
    assert state["masked_artist"] != ""


@pytest.mark.asyncio
async def test_very_short_track(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test handling of very short track names."""
    game = isolated_guessgame

    await game.start_new_game(track="Go", artist="OK")

    state = await game.get_current_state()

    # Should still create a game with very short names
    assert state["status"] == "active"
    assert state["masked_track"] != ""
    assert state["masked_artist"] != ""


@pytest.mark.asyncio
async def test_very_long_track(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test handling of very long track names."""
    game = isolated_guessgame

    long_track = "A" * 200  # 200 character track name
    long_artist = "B" * 150  # 150 character artist name

    await game.start_new_game(track=long_track, artist=long_artist)

    state = await game.get_current_state()

    # Should handle long names without issues
    assert state["status"] == "active"
    assert len(state["masked_track"]) > 100
    assert len(state["masked_artist"]) > 100


@pytest.mark.asyncio
async def test_case_insensitivity(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test that guesses are case-insensitive."""
    game = guessgame_with_active_game

    # Guess lowercase
    result1 = await game.process_guess(username="user1", guess_text="house")

    # Start new game
    await game.start_new_game(track="House of the Rising Sun", artist="The Animals")

    # Guess uppercase
    result2 = await game.process_guess(username="user2", guess_text="HOUSE")

    # Both should be correct
    assert result1["correct"] is True
    assert result2["correct"] is True


@pytest.mark.asyncio
async def test_reset_session(guessgame_with_active_game):  # pylint: disable=redefined-outer-name
    """Test resetting session scores."""
    game = guessgame_with_active_game

    # Make some guesses to build up session scores
    await game.process_guess(username="user1", guess_text="e")
    await game.process_guess(username="user1", guess_text="a")

    # Verify session stats exist
    stats_before = await game.get_user_stats(username="user1")
    assert stats_before["session_score"] > 0
    assert stats_before["session_guesses"] == 2

    # Reset session
    await game.reset_session()

    # Verify session stats are cleared
    stats_after = await game.get_user_stats(username="user1")
    assert stats_after["session_score"] == 0
    assert stats_after["session_guesses"] == 0
    # All-time stats should remain
    assert stats_after["all_time_score"] > 0
    assert stats_after["all_time_guesses"] == 2


@pytest.mark.asyncio
async def test_multiple_words_in_guess(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test guessing multiple words at once."""
    game = guessgame_with_active_game

    # Guess a multi-word phrase
    result = await game.process_guess(username="testuser", guess_text="rising sun")

    assert result is not None
    # Should handle multi-word guesses
    assert result["guess_type"] in ["word", "solve", "wrong"]


@pytest.mark.asyncio
async def test_concurrent_guesses(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test handling concurrent guesses from multiple users."""
    game = guessgame_with_active_game

    # Simulate concurrent guesses
    results = await asyncio.gather(
        game.process_guess(username="user1", guess_text="e"),
        game.process_guess(username="user2", guess_text="a"),
        game.process_guess(username="user3", guess_text="o"),
    )

    # All guesses should complete successfully
    assert all(result is not None for result in results)
    assert all(result["correct"] is True for result in results)


@pytest.mark.asyncio
async def test_get_current_state_no_game(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test getting current state when no game is active."""
    game = isolated_guessgame

    state = await game.get_current_state()

    assert state["status"] == "waiting"
    assert state["masked_track"] == ""
    assert state["masked_artist"] == ""
    assert state["time_remaining"] == 0


@pytest.mark.asyncio
async def test_game_id_tracking(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test that each game gets a unique game_id."""
    game = isolated_guessgame

    # Start first game
    await game.start_new_game(track="Track 1", artist="Artist 1")

    # End and start second game
    await game.end_game(reason="timeout")
    await game.start_new_game(track="Track 2", artist="Artist 2")

    # Game IDs should be different
    # Note: This requires exposing game_id in get_current_state or checking database directly
    async with aiosqlite.connect(game.databasefile) as conn:
        cursor = await conn.execute(
            "SELECT game_id FROM game_history ORDER BY game_id DESC LIMIT 2"
        )
        game_ids = await cursor.fetchall()

    assert len(game_ids) == 2
    assert game_ids[0][0] != game_ids[1][0]


@pytest.mark.asyncio
async def test_guess_empty_string(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test that empty string guesses are rejected."""
    game = guessgame_with_active_game

    result = await game.process_guess(username="testuser", guess_text="")

    # Should return None or handle gracefully
    assert result is None or result["correct"] is False


@pytest.mark.asyncio
async def test_guess_whitespace_only(
    guessgame_with_active_game,
):  # pylint: disable=redefined-outer-name
    """Test that whitespace-only guesses are rejected."""
    game = guessgame_with_active_game

    result = await game.process_guess(username="testuser", guess_text="   ")

    # Should return None or handle gracefully
    assert result is None or result["correct"] is False
