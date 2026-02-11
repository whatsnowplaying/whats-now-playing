#!/usr/bin/env python3
# pylint: disable=too-many-lines
"""
Unit tests for the Guess Game system
"""

import asyncio
import pathlib
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
import pytest_asyncio
from freezegun import freeze_time

import nowplaying.guessgame


@pytest_asyncio.fixture
async def isolated_guessgame(bootstrap):  # pylint: disable=redefined-outer-name
    """Create an isolated GuessGame instance for testing."""
    # Enable guess game in config
    bootstrap.cparser.setValue("guessgame/enabled", True)
    bootstrap.cparser.sync()

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = pathlib.Path(temp_dir) / "test_guessgame.db"
        stopevent = asyncio.Event()
        game = nowplaying.guessgame.GuessGame(config=bootstrap, stopevent=stopevent, testmode=True)
        # Override database location for testing
        game.databasefile = db_path
        game.setupdb()
        yield game
        stopevent.set()  # Signal stop when test completes


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


@pytest.mark.asyncio
async def test_word_boundary_matching(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test that word guesses match only at word boundaries, not as substrings."""
    game = isolated_guessgame

    # Start game with "Simple Minds" / "Out on the Catwalk"
    # The word "in" appears as a substring in "Minds" but should only match as a word
    await game.start_new_game(track="Out on the Catwalk", artist="Simple Minds")

    # Guess "in" - should NOT match because "in" is not a complete word in "Minds"
    result = await game.process_guess(username="testuser", guess_text="in")

    # Should be rejected as wrong guess (not found as complete word)
    assert result is not None
    assert result["correct"] is False
    assert result["guess_type"] == "wrong"

    # Guess "on" - should match as complete word in "Out on the Catwalk"
    result = await game.process_guess(username="testuser", guess_text="on")

    assert result is not None
    assert result["correct"] is True
    assert result["guess_type"] == "word"
    # Letters 'o' and 'n' should be revealed
    assert "o" in result["masked_track"].lower() or "o" in result["masked_artist"].lower()
    assert "n" in result["masked_track"].lower() or "n" in result["masked_artist"].lower()


@pytest.mark.asyncio
async def test_quotes_in_artist_name(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test that artists with quotes in their name match correctly without quotes in guess."""
    game = isolated_guessgame

    # Start game with artist that has quotes in the name
    await game.start_new_game(track="Amish Paradise", artist='"Weird Al" Yankovic')

    # Guess without quotes should match
    result = await game.process_guess(username="testuser", guess_text="weird al yankovic")

    assert result is not None
    assert result["correct"] is True
    assert result["guess_type"] == "solve"
    assert result["artist_solved"] is True

    # Also test word matching
    game2 = isolated_guessgame
    await game2.start_new_game(track="Amish Paradise", artist='"Weird Al" Yankovic')

    # Guess "weird al" as a word should match
    result = await game2.process_guess(username="testuser", guess_text="weird al")

    assert result is not None
    assert result["correct"] is True
    assert result["guess_type"] == "word"


@pytest.mark.asyncio
async def test_parentheses_in_track_name(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test that tracks with parentheses match correctly without parentheses in guess."""
    game = isolated_guessgame

    # Start game with track that has parentheses (and apostrophe)
    await game.start_new_game(
        track="(I'm always touched) by your presence, dear", artist="Blondie"
    )

    # Guess without parentheses or apostrophe should match
    result = await game.process_guess(
        username="testuser", guess_text="im always touched by your presence dear"
    )

    assert result is not None
    assert result["correct"] is True
    assert result["guess_type"] == "solve"
    assert result["track_solved"] is True

    # Test with square brackets too
    game2 = isolated_guessgame
    await game2.start_new_game(track="[Bonus Track] Amazing Song", artist="Test Artist")

    result = await game2.process_guess(username="testuser", guess_text="bonus track amazing song")

    assert result is not None
    assert result["correct"] is True
    assert result["guess_type"] == "solve"


@pytest.mark.asyncio
async def test_hyphenated_artist_name(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test that artists with hyphens like Alt-J match correctly."""
    game = isolated_guessgame

    # Start game with hyphenated artist
    await game.start_new_game(track="Breezeblocks", artist="Alt-J")

    # Guess with hyphen should match
    result = await game.process_guess(username="testuser", guess_text="alt-j")

    assert result is not None
    assert result["correct"] is True
    assert result["guess_type"] == "solve"
    assert result["artist_solved"] is True

    # Test without hyphen should also match
    game2 = isolated_guessgame
    await game2.start_new_game(track="Breezeblocks", artist="Alt-J")

    result = await game2.process_guess(username="testuser", guess_text="altj")

    assert result is not None
    assert result["correct"] is True
    assert result["guess_type"] == "solve"

    # Test as word match (not full artist name)
    game3 = isolated_guessgame
    await game3.start_new_game(track="Some Track", artist="Alt-J")

    result = await game3.process_guess(username="testuser", guess_text="alt")

    # "alt" is only part of "altj" after normalization, should NOT match as word
    assert result is not None
    assert result["correct"] is False


@pytest.mark.asyncio
async def test_accented_characters_in_name(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test that accented characters like é are revealed when user guesses without accent."""
    game = isolated_guessgame

    # Start game with accented name
    await game.start_new_game(track="Nothing Compares 2 U", artist="Sinéad O'Connor")

    # Guess "sinead" without accent should reveal "Sinéad" including the é
    result = await game.process_guess(username="testuser", guess_text="sinead")

    assert result is not None
    assert result["correct"] is True
    assert result["guess_type"] == "word"
    # Check that the é was revealed in the masked artist
    assert "sinéad" in result["masked_artist"].lower()
    # Should not have underscores in the first word anymore
    assert not any(c == "_" for c in result["masked_artist"].split()[0])

    # Now guess "oconnor" - should also work
    result2 = await game.process_guess(username="testuser", guess_text="oconnor")

    assert result2 is not None
    assert result2["correct"] is True
    assert result2["guess_type"] == "word"
    # Check that O'Connor was fully revealed
    assert "o'connor" in result2["masked_artist"].lower()

    # Test with apostrophe
    game2 = isolated_guessgame
    await game2.start_new_game(track="Nothing Compares 2 U", artist="Sinéad O'Connor")
    result3 = await game2.process_guess(username="testuser", guess_text="o'connor")

    assert result3 is not None
    assert result3["correct"] is True
    assert result3["guess_type"] == "word"

    # Test with the actual track that has quotes and parentheses
    game3 = isolated_guessgame
    await game3.start_new_game(
        track='"The Emperor\'s New Clothes (Live in 1990)"', artist="Sinéad O'Connor"
    )
    result4 = await game3.process_guess(username="testuser", guess_text="oconnor")

    assert result4 is not None
    assert result4["correct"] is True, f"Expected correct, got {result4}"
    assert result4["guess_type"] == "word"


@pytest.mark.asyncio
async def test_comma_in_numbers(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test that commas in numbers are handled correctly (10,000 matches 10000)."""
    game = isolated_guessgame

    # Start game with comma in artist name
    await game.start_new_game(track="Because the Night", artist="10,000 Maniacs")

    # Guess without comma should match
    result = await game.process_guess(username="testuser", guess_text="10000 maniacs")

    assert result is not None
    assert result["correct"] is True
    assert result["guess_type"] == "solve"
    assert result["artist_solved"] is True


@pytest.mark.asyncio
async def test_multi_word_guess(isolated_guessgame):  # pylint: disable=redefined-outer-name
    """Test that multi-word guesses reveal all letters in the matched words."""
    game = isolated_guessgame

    # Start game with a track
    await game.start_new_game(track="The Road to Mandalay", artist="Robbie Williams")

    # Guess "road to" should reveal letters from both "Road" and "to"
    result = await game.process_guess(username="testuser", guess_text="road to")

    assert result is not None
    assert result["correct"] is True
    assert result["guess_type"] == "word"
    # Check that both "road" and "to" are revealed in masked track
    masked = result["masked_track"].lower()
    assert "road" in masked
    assert " to " in masked or masked.endswith(" to")
    # Verify no underscores in "road" or "to"
    words = result["masked_track"].split()
    for i, word in enumerate(words):
        if word.lower() in ["road", "to"]:
            assert "_" not in word, f"Word '{word}' at position {i} should be fully revealed"


@pytest.mark.asyncio
async def test_no_points_for_already_revealed_words(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test that guessing already-revealed words doesn't award points."""
    game = isolated_guessgame

    # Start game with a track
    await game.start_new_game(track="The Road to Mandalay", artist="Robbie Williams")

    # First guess "road" - should award points
    result1 = await game.process_guess(username="testuser", guess_text="road")

    assert result1 is not None
    assert result1["correct"] is True
    assert result1["guess_type"] == "word"
    assert result1["points"] == 10  # Default word points

    # Guess all letters in "road" individually
    await game.process_guess(username="testuser", guess_text="r")
    await game.process_guess(username="testuser", guess_text="o")
    await game.process_guess(username="testuser", guess_text="a")
    await game.process_guess(username="testuser", guess_text="d")

    # Now guess "road" again - should NOT award points since all letters revealed
    result2 = await game.process_guess(username="testuser", guess_text="road")

    assert result2 is not None
    assert result2["correct"] is False
    assert result2["already_guessed"] is True
    assert result2["points"] == 0


@pytest.mark.asyncio
async def test_send_game_state_disabled_when_config_off(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test that _send_single_update respects guessgame/send_to_server config"""
    game = isolated_guessgame

    # Disable sending to server
    game.config.cparser.setValue("guessgame/send_to_server", False)
    # pragma: allowlist secret
    game.config.cparser.setValue("charts/charts_key", "test_secret_key_12345")

    # Start game
    await game.start_new_game(track="Test Song", artist="Test Artist")

    # Mock aiohttp to verify it's NOT called
    with patch("aiohttp.ClientSession") as mock_session:
        # Call _send_single_update directly
        success, sleep_duration = await game._send_single_update()  # pylint: disable=protected-access

        # Verify it returned False (not sent) and a reasonable sleep duration
        assert success is False
        assert sleep_duration == 5

        # Verify no HTTP calls were made
        mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_send_game_state_requires_api_key(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test that _send_single_update requires charts/charts_key to be configured"""
    game = isolated_guessgame

    # Enable sending but no API key
    game.config.cparser.setValue("guessgame/send_to_server", True)
    game.config.cparser.setValue("charts/charts_key", "")  # Empty key

    # Start game
    await game.start_new_game(track="Test Song", artist="Test Artist")

    # Mock aiohttp to verify it's NOT called
    with patch("aiohttp.ClientSession") as mock_session:
        # Call _send_single_update directly
        success, sleep_duration = await game._send_single_update()  # pylint: disable=protected-access

        # Verify it returned False (not sent) and a longer sleep duration
        assert success is False
        assert sleep_duration == 10

        # Verify no HTTP calls were made (no valid API key)
        mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_send_game_state_sends_correct_payload(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test that _send_single_update sends correct payload format"""
    game = isolated_guessgame

    # Configure for sending
    game.config.cparser.setValue("guessgame/send_to_server", True)
    # pragma: allowlist secret
    game.config.cparser.setValue("charts/charts_key", "test_secret_key_12345")

    # Start game
    await game.start_new_game(track="Test Song", artist="Test Artist")

    # Mock aiohttp
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value="")
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.closed = False

    with patch("aiohttp.ClientSession", return_value=mock_session):
        # Call _send_single_update directly
        success, sleep_duration = await game._send_single_update()  # pylint: disable=protected-access

        # Verify it returned True (sent) and sleep duration for active game
        assert success is True
        assert sleep_duration == 2

        # Verify HTTP call was made
        assert mock_session.post.called
        call_args = mock_session.post.call_args

        # Check URL
        assert "/api/guessgame/update" in call_args[0][0]

        # Check payload structure
        payload = call_args[1]["json"]
        # pragma: allowlist secret
        assert "secret" in payload
        # pragma: allowlist secret
        assert payload["secret"] == "test_secret_key_12345"  # pragma: allowlist secret
        assert "game_status" in payload
        assert payload["game_status"] == "active"


@pytest.mark.asyncio
async def test_send_game_state_handles_http_errors(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test that send_game_state_to_server handles HTTP errors gracefully"""
    game = isolated_guessgame

    # Configure for sending
    game.config.cparser.setValue("guessgame/send_to_server", True)
    # pragma: allowlist secret
    game.config.cparser.setValue("charts/charts_key", "test_secret_key_12345")

    # Start game
    await game.start_new_game(track="Test Song", artist="Test Artist")

    # Mock aiohttp with error response
    mock_response = AsyncMock()
    mock_response.status = 500  # Server error
    mock_response.text = AsyncMock(return_value="Internal Server Error")
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_session.closed = False

    with patch("aiohttp.ClientSession", return_value=mock_session):
        # Call _send_single_update directly - it should handle the error gracefully
        success, sleep_duration = await game._send_single_update()  # pylint: disable=protected-access

        # Verify it completed successfully despite HTTP 500 error
        assert success is True  # Still returns True because request was sent
        assert sleep_duration == 2  # Active game sleep duration

        # Verify HTTP call was made despite error (shouldn't crash)
        assert mock_session.post.called


@pytest.mark.asyncio
async def test_send_game_state_includes_leaderboards(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test that send_game_state_to_server includes leaderboard data"""
    game = isolated_guessgame

    # Configure for sending
    game.config.cparser.setValue("guessgame/send_to_server", True)
    # pragma: allowlist secret
    game.config.cparser.setValue("charts/charts_key", "test_secret_key_12345")

    # Start game and create some user activity
    await game.start_new_game(track="Test Song", artist="Test Artist")
    await game.process_guess(username="player1", guess_text="e")
    await game.process_guess(username="player2", guess_text="t")

    # Mock aiohttp
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value="")
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.closed = False

    with patch("aiohttp.ClientSession", return_value=mock_session):
        # Call _send_single_update directly
        success, sleep_duration = await game._send_single_update()  # pylint: disable=protected-access

        # Verify it succeeded
        assert success is True
        assert sleep_duration == 2

        # Verify leaderboard data is included
        assert mock_session.post.called
        payload = mock_session.post.call_args[1]["json"]

        assert "game_state" in payload
        game_state = payload["game_state"]
        assert "session_leaderboard" in game_state
        assert "all_time_leaderboard" in game_state


@pytest.mark.asyncio
async def test_grace_period_accepts_guesses(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test that guesses are accepted during grace period after game ends"""
    game = isolated_guessgame

    # Set a 10 second grace period
    game.config.cparser.setValue("guessgame/grace_period", 10)

    # Start and end a game at t=1000
    with freeze_time("2024-01-01 12:00:00") as frozen_time:
        await game.start_new_game(track="Test Song", artist="Test Artist")
        await game.end_game(reason="timeout")

        # Move forward 5 seconds (within 10s grace period)
        frozen_time.tick(delta=5)

        # Try to guess
        result = await game.process_guess(username="player1", guess_text="e")

        # Should accept the guess
        assert result is not None
        assert "correct" in result


@pytest.mark.asyncio
async def test_grace_period_rejects_after_expiry(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test that guesses are rejected after grace period expires"""
    game = isolated_guessgame

    # Set a 10 second grace period
    game.config.cparser.setValue("guessgame/grace_period", 10)

    # Start and end a game at t=1000
    with freeze_time("2024-01-01 12:00:00") as frozen_time:
        await game.start_new_game(track="Test Song", artist="Test Artist")
        await game.end_game(reason="timeout")

        # Move forward 15 seconds (beyond 10s grace period)
        frozen_time.tick(delta=15)

        # Try to guess
        result = await game.process_guess(username="player1", guess_text="e")

        # Should reject the guess
        assert result is None


@pytest.mark.asyncio
async def test_grace_period_default_value(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test that grace period defaults to 5 seconds"""
    game = isolated_guessgame

    # Don't set grace_period - should use default of 5

    # Start and end a game
    await game.start_new_game(track="Test Song", artist="Test Artist")
    await game.end_game(reason="timeout")

    # Immediately try to guess (within default 5s grace period)
    result = await game.process_guess(username="player1", guess_text="e")

    # Should accept the guess (within default grace period)
    assert result is not None


@pytest.mark.asyncio
async def test_grace_period_handles_clock_skew(
    isolated_guessgame,
):  # pylint: disable=redefined-outer-name
    """Test that grace period handles clock skew where end_time is in the future"""
    game = isolated_guessgame

    # Set a 10 second grace period
    game.config.cparser.setValue("guessgame/grace_period", 10)

    # Start and end a game at t=2000
    with freeze_time("2024-01-01 12:00:00") as frozen_time:
        frozen_time.tick(delta=2000)
        await game.start_new_game(track="Test Song", artist="Test Artist")
        await game.end_game(reason="timeout")

        # Move backward in time to t=1995 (simulating clock skew where end_time is in future)
        frozen_time.move_to("2024-01-01 12:00:00")
        frozen_time.tick(delta=1995)

        # Try to guess - even though end_time is 5 seconds in the future,
        # clamping should make elapsed_since_end=0, so we're within grace period
        result = await game.process_guess(username="player1", guess_text="e")

        # Should accept the guess (elapsed clamped to 0, within grace period)
        assert result is not None
        assert "correct" in result
