#!/usr/bin/env python3
"""Unit tests for Twitch chat functionality."""
# pylint: disable=protected-access

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import nowplaying.twitch.chat  # pylint: disable=import-error
from nowplaying.exceptions import PluginVerifyError  # pylint: disable=import-error


class MockUser:  # pylint: disable=too-few-public-methods
    """Mock Twitch user for testing."""

    def __init__(self, display_name, badges=None):
        self.display_name = display_name
        self.badges = badges or {}


class MockMessage:  # pylint: disable=too-few-public-methods
    """Mock Twitch message for testing."""

    def __init__(self, user, text=""):
        self.user = user
        self.text = text


@pytest.mark.asyncio
async def test_modernmeerkat_greeting_sent_once(bootstrap):
    """Test that modernmeerkat gets greeted exactly once per program launch."""
    config = bootstrap
    stopevent = asyncio.Event()

    # Set up the chat channel for testing
    config.cparser.setValue("twitchbot/channel", "testchannel")

    # Create TwitchChat instance
    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)
    chat.chat = AsyncMock()  # Mock the actual chat connection

    # Initial state
    assert chat.modernmeerkat_greeted is False

    # modernmeerkat user sends message
    modernmeerkat_user = MockUser("modernmeerkat")
    message = MockMessage(modernmeerkat_user)

    await chat.on_twitchchat_incoming_message(message)  # pylint: disable=no-member

    # Verify greeting was sent
    chat.chat.send_message.assert_called_once_with("testchannel", "Hello @modernmeerkat")
    assert chat.modernmeerkat_greeted is True


@pytest.mark.asyncio
async def test_modernmeerkat_no_duplicate_greeting(bootstrap):
    """Test that modernmeerkat doesn't get greeted twice."""
    config = bootstrap
    stopevent = asyncio.Event()

    config.cparser.setValue("twitchbot/channel", "testchannel")

    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)
    chat.chat = AsyncMock()

    # Set as already greeted
    chat.modernmeerkat_greeted = True

    # modernmeerkat user sends another message
    modernmeerkat_user = MockUser("modernmeerkat")
    message = MockMessage(modernmeerkat_user)

    await chat.on_twitchchat_incoming_message(message)  # pylint: disable=no-member

    # Verify no greeting was sent
    chat.chat.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_modernmeerkat_case_insensitive(bootstrap):
    """Test that modernmeerkat matching is case insensitive but exact."""
    config = bootstrap
    stopevent = asyncio.Event()

    config.cparser.setValue("twitchbot/channel", "testchannel")

    # Only exact matches should trigger greeting (case insensitive)
    valid_cases = [
        "modernmeerkat",
        "ModernMeerkat",
        "MODERNMEERKAT",
    ]

    for username in valid_cases:
        # Create fresh chat instance for each test
        chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)
        chat.chat = AsyncMock()

        user = MockUser(username)
        message = MockMessage(user)

        await chat.on_twitchchat_incoming_message(message)  # pylint: disable=no-member

        # Verify greeting was sent
        chat.chat.send_message.assert_called_once_with("testchannel", f"Hello @{username}")
        assert chat.modernmeerkat_greeted is True


@pytest.mark.asyncio
async def test_regular_users_no_greeting(bootstrap):
    """Test that regular users don't trigger the modernmeerkat greeting."""
    config = bootstrap
    stopevent = asyncio.Event()

    config.cparser.setValue("twitchbot/channel", "testchannel")

    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)
    chat.chat = AsyncMock()

    regular_users = [
        "someuser",
        "viewer123",
        "chatbot",
        "moderator",
        "meerkat",  # partial match shouldn't trigger
        "modern",  # partial match shouldn't trigger
        "modernmeerkatbot",  # should not trigger (was bug)
        "modernmeerkat_fan",  # should not trigger
        "TheModernMeerkat",  # should not trigger (prefix)
        "modernmeerkat123",  # should not trigger (suffix)
    ]

    for username in regular_users:
        user = MockUser(username)
        message = MockMessage(user)

        await chat.on_twitchchat_incoming_message(message)  # pylint: disable=no-member

    # Verify no greetings were sent for any regular users
    chat.chat.send_message.assert_not_called()
    assert chat.modernmeerkat_greeted is False


@pytest.mark.asyncio
async def test_greeting_error_handling(bootstrap):
    """Test that greeting errors are handled gracefully."""
    config = bootstrap
    stopevent = asyncio.Event()

    config.cparser.setValue("twitchbot/channel", "testchannel")

    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)
    chat.chat = AsyncMock()

    # Configure mock to raise an exception
    chat.chat.send_message.side_effect = Exception("Network error")

    modernmeerkat_user = MockUser("modernmeerkat")
    message = MockMessage(modernmeerkat_user)

    # Should not raise an exception
    await chat.on_twitchchat_incoming_message(message)  # pylint: disable=no-member

    # State should still be updated even if sending fails
    assert chat.modernmeerkat_greeted is True


def test_twitch_chat_initialization(bootstrap):
    """Test TwitchChat initialization includes modernmeerkat_greeted."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)

    # Verify initial state
    assert chat.modernmeerkat_greeted is False
    assert chat.config is config
    assert chat.stopevent is stopevent


def setup_generic_commands(config):
    """Setup a bunch of default commands to test against."""
    for command in nowplaying.twitch.chat.TWITCHBOT_CHECKBOXES:
        cmd = f"twitchbot-command-{command}"
        for checkbox in nowplaying.twitch.chat.TWITCHBOT_CHECKBOXES:
            if command == checkbox:
                config.cparser.setValue(f"{cmd}cmd/{checkbox}", True)
            else:
                config.cparser.setValue(f"{cmd}cmd/{checkbox}", False)


@pytest.mark.asyncio
async def test_command_permissions(bootstrap):
    """Test command permission checking (comprehensive functionality)."""
    config = bootstrap
    stopevent = asyncio.Event()

    setup_generic_commands(config)
    config.cparser.sync()
    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)

    streamerprofile = {"broadcaster": "1", "subscriber": "9"}
    moderatorprofile = {"moderator": "1", "subscriber": "24"}
    hypetrainprofile = {"vip": "1", "subscriber": "3012", "hype-train": "1"}

    for profile in [streamerprofile, moderatorprofile, hypetrainprofile]:
        for box in nowplaying.twitch.chat.TWITCHBOT_CHECKBOXES:
            if box == "anyone" or profile.get(box):
                assert chat.check_command_perms(profile, f"{box}cmd")
            else:
                assert not chat.check_command_perms(profile, f"{box}cmd")

    stopevent.set()


def test_settings_initialization():
    """Test TwitchChatSettings initialization."""
    settings = nowplaying.twitch.chat.TwitchChatSettings()
    assert settings.widget is None
    assert settings.uihelp is None


def test_verify_command_character():
    """Test command character verification."""
    # Mock widget with invalid command characters
    mock_widget = MagicMock()

    # Test invalid characters
    for invalid_char in ["/", "."]:
        mock_widget.commandchar_lineedit.text.return_value = invalid_char

        with pytest.raises(PluginVerifyError) as exc_info:
            nowplaying.twitch.chat.TwitchChatSettings.verify(mock_widget)

        assert "cannot start with / or ." in str(exc_info.value)

    # Test valid character
    mock_widget.commandchar_lineedit.text.return_value = "!"
    # Should not raise an exception
    nowplaying.twitch.chat.TwitchChatSettings.verify(mock_widget)


@pytest.mark.asyncio
async def test_help_command_detection(bootstrap):
    """Test that help parameter triggers help template."""
    config = bootstrap
    stopevent = asyncio.Event()

    config.cparser.setValue("twitchbot/commandchar", "!")

    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)
    chat._post_template = AsyncMock()
    chat.check_command_perms = MagicMock(return_value=True)

    user = MockUser("testuser")
    message = MockMessage(user, "!track help")

    await chat.do_command(message)

    # Should call _post_template with help template
    chat._post_template.assert_called_once()
    _, kwargs = chat._post_template.call_args
    assert kwargs["templatein"] == "twitchbot_track_help.txt"

    stopevent.set()


@pytest.mark.asyncio
async def test_help_command_case_insensitive(bootstrap):
    """Test that help detection is case insensitive."""
    config = bootstrap
    stopevent = asyncio.Event()

    config.cparser.setValue("twitchbot/commandchar", "!")

    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)
    chat._post_template = AsyncMock()
    chat.check_command_perms = MagicMock(return_value=True)

    user = MockUser("testuser")

    for help_text in ["help", "HELP", "Help", "hElP"]:
        message = MockMessage(user, f"!track {help_text}")

        await chat.do_command(message)

        # Should call _post_template with help template
        chat._post_template.assert_called_with(
            msg=message,
            templatein="twitchbot_track_help.txt",
            moremetadata={
                "cmduser": "testuser",
                "cmdchar": "!",
                "cmdname": "track",
                "cmdtarget": [help_text],
            },
        )
        chat._post_template.reset_mock()

    stopevent.set()


@pytest.mark.asyncio
async def test_help_must_be_only_parameter(bootstrap):
    """Test that help must be the first and only parameter."""
    config = bootstrap
    stopevent = asyncio.Event()

    config.cparser.setValue("twitchbot/commandchar", "!")

    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)
    chat._post_template = AsyncMock()
    chat.check_command_perms = MagicMock(return_value=True)

    user = MockUser("testuser")

    # These should NOT trigger help
    test_cases = [
        "!track help me",  # Extra parameter
        "!track something help",  # Help not first
        "!track",  # No parameters
    ]

    for command_text in test_cases:
        message = MockMessage(user, command_text)

        await chat.do_command(message)

        # Should use normal template, not help
        chat._post_template.assert_called_once()
        _, kwargs = chat._post_template.call_args
        assert kwargs["templatein"] == "twitchbot_track.txt"
        chat._post_template.reset_mock()

    stopevent.set()


@pytest.mark.asyncio
async def test_different_commands_help(bootstrap):
    """Test help works with different command names."""
    config = bootstrap
    stopevent = asyncio.Event()

    config.cparser.setValue("twitchbot/commandchar", "!")

    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)
    chat._post_template = AsyncMock()
    chat.check_command_perms = MagicMock(return_value=True)

    user = MockUser("testuser")

    test_cases = [
        ("!request help", "twitchbot_request_help.txt"),
        ("!artistshortbio help", "twitchbot_artistshortbio_help.txt"),
        ("!previoustrack help", "twitchbot_previoustrack_help.txt"),
        ("!trackdetail help", "twitchbot_trackdetail_help.txt"),
    ]

    for command_text, expected_template in test_cases:
        message = MockMessage(user, command_text)

        await chat.do_command(message)

        chat._post_template.assert_called_once()
        _, kwargs = chat._post_template.call_args
        assert kwargs["templatein"] == expected_template
        chat._post_template.reset_mock()

    stopevent.set()


@pytest.mark.asyncio
async def test_command_metadata_variables(bootstrap):
    """Test that cmdchar and cmdname are set correctly in metadata."""
    config = bootstrap
    stopevent = asyncio.Event()

    config.cparser.setValue("twitchbot/commandchar", "?")

    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)
    chat._post_template = AsyncMock()
    chat.check_command_perms = MagicMock(return_value=True)

    user = MockUser("testuser")
    message = MockMessage(user, "?song help")

    await chat.do_command(message)

    chat._post_template.assert_called_once()
    _, kwargs = chat._post_template.call_args

    # Check template
    assert kwargs["templatein"] == "twitchbot_song_help.txt"

    # Check metadata
    metadata = kwargs["moremetadata"]
    assert metadata["cmdchar"] == "?"
    assert metadata["cmdname"] == "song"
    assert metadata["cmduser"] == "testuser"
    assert metadata["cmdtarget"] == ["help"]

    stopevent.set()


@pytest.mark.asyncio
async def test_configurable_help_keyword(bootstrap):
    """Test that help keyword can be configured for different languages."""
    config = bootstrap
    stopevent = asyncio.Event()

    # Set custom help keyword (e.g., French "aide")
    config.cparser.setValue("twitchbot/commandchar", "!")
    config.cparser.setValue("twitchbot/helpkeyword", "aide")

    chat = nowplaying.twitch.chat.TwitchChat(config=config, stopevent=stopevent)
    chat._post_template = AsyncMock()
    chat.check_command_perms = MagicMock(return_value=True)

    user = MockUser("testuser")

    # Test with configured keyword
    message = MockMessage(user, "!track aide")
    await chat.do_command(message)

    chat._post_template.assert_called_once()
    _, kwargs = chat._post_template.call_args
    assert kwargs["templatein"] == "twitchbot_track_aide.txt"

    chat._post_template.reset_mock()

    # Test that "help" no longer works
    message = MockMessage(user, "!track help")
    await chat.do_command(message)

    chat._post_template.assert_called_once()
    _, kwargs = chat._post_template.call_args
    assert kwargs["templatein"] == "twitchbot_track.txt"  # Normal template, not help

    stopevent.set()
