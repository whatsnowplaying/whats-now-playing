#!/usr/bin/env python3
"""Unit tests for Kick chat functionality."""
# pylint: disable=protected-access,import-error,no-member,no-else-return

import asyncio
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aioresponses import aioresponses

import nowplaying.kick.chat  #pylint: disable=no-name-in-module
import nowplaying.kick.settings  #pylint: disable=no-name-in-module
import nowplaying.kick.constants
from nowplaying.exceptions import PluginVerifyError  #pylint: disable=no-name-in-module


def test_kickchat_init_with_config(bootstrap):
    """Test KickChat initialization with config."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member

    assert chat.config == config
    assert chat.stopevent == stopevent
    assert chat.watcher is None
    assert chat.oauth is None
    assert not chat.authenticated
    assert chat.api_base == "https://api.kick.com/public/v1"
    assert isinstance(chat.jinja2, nowplaying.kick.chat.jinja2.Environment)  #pylint: disable=no-member


def test_kickchat_init_without_config():
    """Test KickChat initialization without config."""
    chat = nowplaying.kick.chat.KickChat()  #pylint: disable=no-member

    assert chat.config is None
    assert isinstance(chat.stopevent, asyncio.Event)


@pytest.mark.parametrize("refresh_succeeds,expected_result", [
    (True, True),   # Authentication succeeds
    (False, False), # Authentication fails
])
@pytest.mark.asyncio
async def test_kickchat_authenticate(bootstrap, refresh_succeeds, expected_result):
    """Test authentication success and failure scenarios."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member

    with patch('nowplaying.kick.utils.attempt_token_refresh',
               new_callable=AsyncMock) as mock_refresh:
        mock_refresh.return_value = refresh_succeeds

        result = await chat._authenticate()

        assert result == expected_result
        assert chat.authenticated == expected_result
        mock_refresh.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_kickchat_send_message_success(bootstrap):
    """Test successful message sending."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member
    chat.authenticated = True

    # Mock OAuth2 handler
    mock_oauth = MagicMock()
    mock_oauth.get_stored_tokens.return_value = ('access_token', 'refresh_token')
    chat.oauth = mock_oauth

    # Mock successful API response
    with aioresponses() as mock_resp:
        mock_resp.post('https://api.kick.com/public/v1/chat',
                       status=200,
                       payload={
                           "data": {
                               "is_sent": True
                           },
                           "message": "OK"
                       })

        result = await chat._send_message("Test message")  # pylint: disable=protected-access

        assert result is True


@pytest.mark.asyncio
async def test_kickchat_send_message_not_authenticated(bootstrap):
    """Test message sending when not authenticated."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member
    chat.authenticated = False

    result = await chat._send_message("Test message")  # pylint: disable=protected-access

    assert result is False


@pytest.mark.asyncio
async def test_kickchat_send_message_api_error(bootstrap):
    """Test message sending with API error."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member
    chat.authenticated = True

    # Mock OAuth2 handler
    mock_oauth = MagicMock()
    mock_oauth.get_stored_tokens.return_value = ('access_token', 'refresh_token')
    chat.oauth = mock_oauth

    # Mock failed API response
    with aioresponses() as mock_resp:
        mock_resp.post('https://api.kick.com/public/v1/chat',
                       status=400,
                       payload={"message": "Invalid request"})

        result = await chat._send_message("Test message")  # pylint: disable=protected-access

        assert result is False


@pytest.mark.asyncio
async def test_kickchat_send_message_token_expired(bootstrap):
    """Test message sending with expired token."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member
    chat.authenticated = True

    # Mock OAuth2 handler
    mock_oauth = MagicMock()
    mock_oauth.get_stored_tokens.return_value = ('access_token', 'refresh_token')
    chat.oauth = mock_oauth

    # Mock 401 response (token expired)
    with aioresponses() as mock_resp:
        mock_resp.post('https://api.kick.com/public/v1/chat',
                       status=401,
                       payload={"message": "Unauthorized"})

        result = await chat._send_message("Test message")  # pylint: disable=protected-access

        assert result is False
        assert chat.authenticated is False


@pytest.mark.asyncio
async def test_kickchat_send_message_smart_splitting(bootstrap):
    """Test message splitting for messages longer than KICK_MESSAGE_LIMIT."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member
    chat.authenticated = True

    # Mock OAuth2 handler
    mock_oauth = MagicMock()
    mock_oauth.get_stored_tokens.return_value = ('access_token', 'refresh_token')
    chat.oauth = mock_oauth

    # Create a long message that exceeds KICK_MESSAGE_LIMIT (500 chars)
    long_message = "This is a very long message. " * 20  # ~600 characters
    assert len(long_message) > nowplaying.kick.constants.KICK_MESSAGE_LIMIT  #pylint: disable=no-member

    # Mock _send_single_message to track calls
    with patch.object(chat, '_send_single_message', new_callable=AsyncMock) as mock_send_single:
        mock_send_single.return_value = True

        result = await chat._send_message(long_message)  # pylint: disable=protected-access

        # Verify the message was split and sent in multiple parts
        assert result is True
        assert mock_send_single.call_count > 1  # Should be called multiple times

        # Verify each part is within the limit
        for call in mock_send_single.call_args_list:
            message_part = call[0][0]  # First argument of each call
            assert len(message_part) <= nowplaying.kick.constants.KICK_MESSAGE_LIMIT
            assert message_part.strip()  # Should not be empty

        # Verify content preservation - reconstruct message from parts
        sent_parts = [call[0][0] for call in mock_send_single.call_args_list]
        reconstructed = ' '.join(sent_parts)

        # Should preserve essential content (allowing for some spacing differences)
        assert "This is a very long message" in reconstructed


@pytest.mark.asyncio
async def test_kickchat_send_message_empty_content(bootstrap):
    """Test message sending with empty or whitespace-only content."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member
    chat.authenticated = True

    # Mock OAuth2 handler
    mock_oauth = MagicMock()
    mock_oauth.get_stored_tokens.return_value = ('access_token', 'refresh_token')
    chat.oauth = mock_oauth

    # Test empty message
    result = await chat._send_message("")  # pylint: disable=protected-access
    assert result is False

    # Test whitespace-only message
    result = await chat._send_message("   \n\t   ")  # pylint: disable=protected-access
    assert result is False


@pytest.mark.asyncio
async def test_kickchat_process_announcement_no_metadata(bootstrap):
    """Test track announcement with no metadata."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member
    chat.authenticated = True

    # Mock metadb to return None
    chat.metadb.read_last_meta_async = AsyncMock(return_value=None)

    await chat._process_announcement()  # pylint: disable=protected-access

    # Should not crash, just return early


@pytest.mark.asyncio
async def test_kickchat_async_announce_track_no_template(bootstrap):
    """Test track announcement with no template configured."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member
    chat.authenticated = True

    # No announcement template configured
    config.cparser.setValue('kick/announce', '')

    # Mock metadb to return metadata
    mock_metadata = {'artist': 'Test Artist', 'title': 'Test Title'}
    chat.metadb.read_last_meta_async = AsyncMock(return_value=mock_metadata)

    await chat._process_announcement()  # pylint: disable=protected-access

    # Should not crash, just return early


@pytest.mark.asyncio
async def test_kickchat_async_announce_track_success(bootstrap):
    """Test successful track announcement."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member
    chat.authenticated = True

    # Configure announcement template in test directory
    test_template_dir = config.testdir / 'testsuite' / 'templates'
    test_template_dir.mkdir(parents=True, exist_ok=True)
    template_path = test_template_dir / 'test_announce.txt'
    template_path.write_text('Now playing: {{artist}} - {{title}}')
    config.cparser.setValue('kick/announce', str(template_path))

    # Mock metadb to return metadata
    mock_metadata = {'artist': 'Test Artist', 'title': 'Test Title'}
    chat.metadb.read_last_meta_async = AsyncMock(return_value=mock_metadata)

    # Mock send_message
    chat._send_message = AsyncMock(return_value=True)  # pylint: disable=protected-access

    await chat._process_announcement()  # pylint: disable=protected-access

    # Verify message was sent
    chat._send_message.assert_called_once_with('Now playing: Test Artist - Test Title')


@pytest.mark.asyncio
async def test_kickchat_async_announce_track_same_track(bootstrap):
    """Test track announcement skipped for same track."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member
    chat.authenticated = True

    # Set last announced track
    chat.last_announced['artist'] = 'Test Artist'
    chat.last_announced['title'] = 'Test Title'

    # Mock metadb to return same metadata
    mock_metadata = {'artist': 'Test Artist', 'title': 'Test Title'}
    chat.metadb.read_last_meta_async = AsyncMock(return_value=mock_metadata)

    # Mock send_message
    chat._send_message = AsyncMock(return_value=True)

    await chat._process_announcement()  # pylint: disable=protected-access

    # Verify message was NOT sent (same track)
    chat._send_message.assert_not_called()


@pytest.mark.asyncio
async def test_kickchat_delay_write(bootstrap):
    """Test announcement delay."""
    config = bootstrap
    config.cparser.setValue('kick/announcedelay', 0.01)  # Fast delay for tests

    stopevent = asyncio.Event()
    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member

    # This should not raise an exception and should delay appropriately
    await chat._delay_write()


@pytest.mark.asyncio
async def test_kickchat_delay_write_invalid_value(bootstrap):
    """Test announcement delay with invalid value."""
    config = bootstrap
    config.cparser.setValue('kick/announcedelay', 'invalid')

    stopevent = asyncio.Event()
    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member

    # Should fall back to default 1.0 seconds
    await chat._delay_write()


def test_kickchat_setup_jinja2(bootstrap):
    """Test Jinja2 environment setup."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member
    template_dir = pathlib.Path(bootstrap.templatedir)

    jinja_env = chat.setup_jinja2(template_dir)

    assert isinstance(jinja_env, nowplaying.kick.chat.jinja2.Environment)
    assert jinja_env.trim_blocks


def test_kickchat_finalize_method():
    """Test _finalize static method."""
    assert nowplaying.kick.chat.KickChat._finalize('test') == 'test'  #pylint: disable=no-member
    assert nowplaying.kick.chat.KickChat._finalize(None) == ''  #pylint: disable=no-member
    assert nowplaying.kick.chat.KickChat._finalize('') == ''  #pylint: disable=no-member


@pytest.mark.asyncio
async def test_kickchat_stop(bootstrap):
    """Test chat stop functionality."""
    config = bootstrap
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member
    chat.authenticated = True

    # Mock watcher
    mock_watcher = MagicMock()
    chat.watcher = mock_watcher

    # Add mock task
    mock_task = MagicMock()
    chat.tasks.add(mock_task)

    await chat.stop()

    # Verify cleanup
    mock_task.cancel.assert_called_once()
    mock_watcher.stop.assert_called_once()
    assert chat.authenticated is False


@pytest.mark.asyncio
async def test_kickchat_run_chat_disabled(bootstrap):
    """Test run_chat when chat is disabled."""
    config = bootstrap
    config.cparser.setValue('kick/chat', False)
    stopevent = asyncio.Event()

    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  #pylint: disable=no-member

    # Mock OAuth2 handler
    mock_oauth = MagicMock()

    # Set stop event immediately to exit loop
    stopevent.set()

    await chat.run_chat(mock_oauth)

    # Should exit early without doing anything



# Settings tests
def test_kickchat_settings_init():
    """Test KickChatSettings initialization."""
    settings = nowplaying.kick.settings.KickChatSettings()  #pylint: disable=no-member

    assert settings.widget is None


def test_kickchat_settings_connect():
    """Test settings connection."""
    settings = nowplaying.kick.settings.KickChatSettings()  #pylint: disable=no-member
    mock_uihelp = MagicMock()
    mock_widget = MagicMock()

    settings.connect(mock_uihelp, mock_widget)

    assert settings.widget == mock_widget


def test_kickchat_settings_load(bootstrap):
    """Test settings loading."""
    config = bootstrap
    config.cparser.setValue('kick/chat', True)
    config.cparser.setValue('kick/announce', 'test_template.txt')
    config.cparser.setValue('kick/announcedelay', 2.5)

    settings = nowplaying.kick.settings.KickChatSettings()  #pylint: disable=no-member
    mock_widget = MagicMock()

    settings.load(config, mock_widget)

    assert settings.widget == mock_widget
    mock_widget.enable_checkbox.setChecked.assert_called_with(True)
    mock_widget.announce_lineedit.setText.assert_called_with('test_template.txt')


def test_kickchat_settings_save(bootstrap):
    """Test settings saving."""
    config = bootstrap
    mock_widget = MagicMock()
    mock_widget.enable_checkbox.isChecked.return_value = True
    mock_widget.announce_lineedit.text.return_value = 'new_template.txt'
    # Setup announce_delay_lineedit for delay handling
    mock_widget.announce_delay_lineedit.text.return_value = '3.0'
    mock_subprocesses = MagicMock()

    # Patch hasattr to return False only for command_perm_table, True for announce_delay_lineedit
    def mock_hasattr(obj, attr):  # pylint: disable=unused-argument
        if attr == 'command_perm_table':
            return False
        elif attr == 'announce_delay_lineedit':
            return True
        return False

    with patch('nowplaying.kick.settings.hasattr', side_effect=mock_hasattr):
        nowplaying.kick.settings.KickChatSettings.save(config, mock_widget, mock_subprocesses)

    assert config.cparser.value('kick/chat', type=bool)
    assert config.cparser.value('kick/announce') == 'new_template.txt'
    assert config.cparser.value('kick/announcedelay', type=float) == 3.0


def test_kickchat_settings_verify_enabled_no_template():
    """Test settings verification fails when enabled but no template."""
    mock_widget = MagicMock()
    mock_widget.enable_checkbox.isChecked.return_value = True
    mock_widget.announce_lineedit.text.return_value = ''

    with pytest.raises(PluginVerifyError, match='Kick announcement template is required'):
        nowplaying.kick.settings.KickChatSettings.verify(mock_widget)  #pylint: disable=no-member


def test_kickchat_settings_verify_disabled():
    """Test settings verification passes when disabled."""
    mock_widget = MagicMock()
    mock_widget.enable_checkbox.isChecked.return_value = False

    # Should not raise an exception
    nowplaying.kick.settings.KickChatSettings.verify(mock_widget)  #pylint: disable=no-member


def test_kickchat_settings_verify_enabled_with_template():
    """Test settings verification passes when enabled with template."""
    mock_widget = MagicMock()
    mock_widget.enable_checkbox.isChecked.return_value = True
    mock_widget.announce_lineedit.text.return_value = 'template.txt'

    # Should not raise an exception
    nowplaying.kick.settings.KickChatSettings.verify(mock_widget)  #pylint: disable=no-member
