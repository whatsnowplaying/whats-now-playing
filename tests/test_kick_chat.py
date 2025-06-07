#!/usr/bin/env python3
"""Unit tests for Kick chat functionality."""

import asyncio
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiohttp
from aioresponses import aioresponses

import nowplaying.kick.chat
import nowplaying.kick.oauth2
from nowplaying.exceptions import PluginVerifyError


class TestKickChat:
    """Test cases for KickChat class."""

    def test_init_with_config(self, bootstrap):
        """Test KickChat initialization with config."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)

        assert chat.config == config
        assert chat.stopevent == stopevent
        assert chat.watcher is None
        assert chat.oauth is None
        assert not chat.authenticated
        assert chat.api_base == "https://api.kick.com/public/v1"
        assert isinstance(chat.jinja2, nowplaying.kick.chat.jinja2.Environment)

    def test_init_without_config(self):
        """Test KickChat initialization without config."""
        chat = nowplaying.kick.chat.KickChat()

        assert chat.config is None
        assert isinstance(chat.stopevent, asyncio.Event)

    @pytest.mark.asyncio
    async def test_authenticate_success(self, bootstrap):
        """Test successful authentication."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)

        # Mock OAuth2 handler
        mock_oauth = MagicMock()
        mock_oauth.get_stored_tokens.return_value = ('access_token', 'refresh_token')
        mock_oauth.validate_token = AsyncMock(return_value=True)
        chat.oauth = mock_oauth

        result = await chat._authenticate()

        assert result
        assert chat.authenticated

    @pytest.mark.asyncio
    async def test_authenticate_no_tokens(self, bootstrap):
        """Test authentication failure with no tokens."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)

        # Mock OAuth2 handler with no tokens
        mock_oauth = MagicMock()
        mock_oauth.get_stored_tokens.return_value = (None, None)
        chat.oauth = mock_oauth

        result = await chat._authenticate()

        assert not result
        assert chat.authenticated is False

    @pytest.mark.asyncio
    async def test_authenticate_token_refresh(self, bootstrap):
        """Test authentication with token refresh."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)

        # Mock OAuth2 handler with invalid token that needs refresh
        mock_oauth = MagicMock()
        mock_oauth.get_stored_tokens.return_value = ('invalid_token', 'refresh_token')
        mock_oauth.validate_token = AsyncMock(return_value=False)
        mock_oauth.refresh_access_token = AsyncMock()
        chat.oauth = mock_oauth

        result = await chat._authenticate()

        assert result is True
        assert chat.authenticated is True
        mock_oauth.refresh_access_token.assert_called_once_with('refresh_token')

    @pytest.mark.asyncio
    async def test_send_message_success(self, bootstrap):
        """Test successful message sending."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
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

            result = await chat._send_message("Test message")

            assert result is True

    @pytest.mark.asyncio
    async def test_send_message_not_authenticated(self, bootstrap):
        """Test message sending when not authenticated."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        chat.authenticated = False

        result = await chat._send_message("Test message")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_api_error(self, bootstrap):
        """Test message sending with API error."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
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

            result = await chat._send_message("Test message")

            assert result is False

    @pytest.mark.asyncio
    async def test_send_message_token_expired(self, bootstrap):
        """Test message sending with expired token."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
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

            result = await chat._send_message("Test message")

            assert result is False
            assert chat.authenticated is False

    @pytest.mark.asyncio
    async def test_send_message_smart_splitting(self, bootstrap):
        """Test message splitting for messages longer than KICK_MESSAGE_LIMIT."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        chat.authenticated = True

        # Mock OAuth2 handler
        mock_oauth = MagicMock()
        mock_oauth.get_stored_tokens.return_value = ('access_token', 'refresh_token')
        chat.oauth = mock_oauth

        # Create a long message that exceeds KICK_MESSAGE_LIMIT (500 chars)
        long_message = "This is a very long message. " * 20  # ~600 characters
        assert len(long_message) > nowplaying.kick.chat.KICK_MESSAGE_LIMIT

        # Mock _send_single_message to track calls
        with patch.object(chat, '_send_single_message', new_callable=AsyncMock) as mock_send_single:
            mock_send_single.return_value = True

            result = await chat._send_message(long_message)

            # Verify the message was split and sent in multiple parts
            assert result is True
            assert mock_send_single.call_count > 1  # Should be called multiple times

            # Verify each part is within the limit
            for call in mock_send_single.call_args_list:
                message_part = call[0][0]  # First argument of each call
                assert len(message_part) <= nowplaying.kick.chat.KICK_MESSAGE_LIMIT
                assert message_part.strip()  # Should not be empty

            # Verify content preservation - reconstruct message from parts
            sent_parts = [call[0][0] for call in mock_send_single.call_args_list]
            reconstructed = ' '.join(sent_parts)

            # Should preserve essential content (allowing for some spacing differences)
            assert "This is a very long message" in reconstructed

    @pytest.mark.asyncio
    async def test_send_message_empty_content(self, bootstrap):
        """Test message sending with empty or whitespace-only content."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        chat.authenticated = True

        # Mock OAuth2 handler
        mock_oauth = MagicMock()
        mock_oauth.get_stored_tokens.return_value = ('access_token', 'refresh_token')
        chat.oauth = mock_oauth

        # Test empty message
        result = await chat._send_message("")
        assert result is False

        # Test whitespace-only message
        result = await chat._send_message("   \n\t   ")
        assert result is False

    @pytest.mark.asyncio
    async def test_async_announce_track_no_metadata(self, bootstrap):
        """Test track announcement with no metadata."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        chat.authenticated = True

        # Mock metadb to return None
        chat.metadb.read_last_meta_async = AsyncMock(return_value=None)

        await chat._async_announce_track()

        # Should not crash, just return early

    @pytest.mark.asyncio
    async def test_async_announce_track_no_template(self, bootstrap):
        """Test track announcement with no template configured."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        chat.authenticated = True

        # No announcement template configured
        config.cparser.setValue('kick/announce', '')

        # Mock metadb to return metadata
        mock_metadata = {'artist': 'Test Artist', 'title': 'Test Title'}
        chat.metadb.read_last_meta_async = AsyncMock(return_value=mock_metadata)

        await chat._async_announce_track()

        # Should not crash, just return early

    @pytest.mark.asyncio
    async def test_async_announce_track_success(self, bootstrap):
        """Test successful track announcement."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
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
        chat._send_message = AsyncMock(return_value=True)

        await chat._async_announce_track()

        # Verify message was sent
        chat._send_message.assert_called_once_with('Now playing: Test Artist - Test Title')

    @pytest.mark.asyncio
    async def test_async_announce_track_same_track(self, bootstrap):
        """Test track announcement skipped for same track."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        chat.authenticated = True

        # Set last announced track
        nowplaying.kick.chat.LASTANNOUNCED['artist'] = 'Test Artist'
        nowplaying.kick.chat.LASTANNOUNCED['title'] = 'Test Title'

        # Mock metadb to return same metadata
        mock_metadata = {'artist': 'Test Artist', 'title': 'Test Title'}
        chat.metadb.read_last_meta_async = AsyncMock(return_value=mock_metadata)

        # Mock send_message
        chat._send_message = AsyncMock(return_value=True)

        await chat._async_announce_track()

        # Verify message was NOT sent (same track)
        chat._send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_delay_write(self, bootstrap):
        """Test announcement delay."""
        config = bootstrap
        config.cparser.setValue('kick/announcedelay', 2.0)

        stopevent = asyncio.Event()
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)

        # This should not raise an exception and should delay appropriately
        await chat._delay_write()

    @pytest.mark.asyncio
    async def test_delay_write_invalid_value(self, bootstrap):
        """Test announcement delay with invalid value."""
        config = bootstrap
        config.cparser.setValue('kick/announcedelay', 'invalid')

        stopevent = asyncio.Event()
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)

        # Should fall back to default 1.0 seconds
        await chat._delay_write()

    def test_setup_jinja2(self, bootstrap):
        """Test Jinja2 environment setup."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        template_dir = pathlib.Path(bootstrap.templatedir)

        jinja_env = chat.setup_jinja2(template_dir)

        assert isinstance(jinja_env, nowplaying.kick.chat.jinja2.Environment)
        assert jinja_env.trim_blocks

    def test_finalize_method(self):
        """Test _finalize static method."""
        assert nowplaying.kick.chat.KickChat._finalize('test') == 'test'
        assert nowplaying.kick.chat.KickChat._finalize(None) == ''
        assert nowplaying.kick.chat.KickChat._finalize('') == ''

    @pytest.mark.asyncio
    async def test_stop(self, bootstrap):
        """Test chat stop functionality."""
        config = bootstrap
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
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
    async def test_run_chat_disabled(self, bootstrap):
        """Test run_chat when chat is disabled."""
        config = bootstrap
        config.cparser.setValue('kick/chat', False)
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)

        # Mock OAuth2 handler
        mock_oauth = MagicMock()

        # Set stop event immediately to exit loop
        stopevent.set()

        await chat.run_chat(mock_oauth)

        # Should exit early without doing anything

    @pytest.mark.asyncio
    async def test_run_chat_no_channel(self, bootstrap):
        """Test run_chat with no channel configured."""
        config = bootstrap
        config.cparser.setValue('kick/chat', True)
        config.cparser.setValue('kick/channel', '')
        stopevent = asyncio.Event()

        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        chat._authenticate = AsyncMock(return_value=True)

        # Mock OAuth2 handler
        mock_oauth = MagicMock()

        # Create a task that will exit after short delay
        async def stop_after_delay():
            await asyncio.sleep(0.1)
            stopevent.set()

        # Run both tasks concurrently
        await asyncio.gather(chat.run_chat(mock_oauth), stop_after_delay(), return_exceptions=True)


class TestKickChatSettings:
    """Test cases for KickChatSettings class."""

    def test_init(self):
        """Test KickChatSettings initialization."""
        settings = nowplaying.kick.chat.KickChatSettings()

        assert settings.widget is None

    def test_connect(self, bootstrap):
        """Test settings connection."""
        settings = nowplaying.kick.chat.KickChatSettings()
        mock_uihelp = MagicMock()
        mock_widget = MagicMock()

        settings.connect(mock_uihelp, mock_widget)

        assert settings.widget == mock_widget

    def test_load(self, bootstrap):
        """Test settings loading."""
        config = bootstrap
        config.cparser.setValue('kick/chat', True)
        config.cparser.setValue('kick/announce', 'test_template.txt')
        config.cparser.setValue('kick/announcedelay', 2.5)

        settings = nowplaying.kick.chat.KickChatSettings()
        mock_widget = MagicMock()

        settings.load(config, mock_widget)

        assert settings.widget == mock_widget
        mock_widget.chat_checkbox.setChecked.assert_called_with(True)
        mock_widget.announce_lineedit.setText.assert_called_with('test_template.txt')
        mock_widget.announcedelay_spin.setValue.assert_called_with(2.5)

    def test_save(self, bootstrap):
        """Test settings saving."""
        config = bootstrap
        mock_widget = MagicMock()
        mock_widget.chat_checkbox.isChecked.return_value = True
        mock_widget.announce_lineedit.text.return_value = 'new_template.txt'
        mock_widget.announcedelay_spin.value.return_value = 3.0
        mock_subprocesses = MagicMock()

        nowplaying.kick.chat.KickChatSettings.save(config, mock_widget, mock_subprocesses)

        assert config.cparser.value('kick/chat', type=bool)
        assert config.cparser.value('kick/announce') == 'new_template.txt'
        assert config.cparser.value('kick/announcedelay', type=float) == 3.0

    def test_verify_enabled_no_template(self, bootstrap):
        """Test settings verification fails when enabled but no template."""
        mock_widget = MagicMock()
        mock_widget.chat_checkbox.isChecked.return_value = True
        mock_widget.announce_lineedit.text.return_value = ''

        with pytest.raises(PluginVerifyError, match='Kick announcement template is required'):
            nowplaying.kick.chat.KickChatSettings.verify(mock_widget)

    def test_verify_disabled(self, bootstrap):
        """Test settings verification passes when disabled."""
        mock_widget = MagicMock()
        mock_widget.chat_checkbox.isChecked.return_value = False

        # Should not raise an exception
        nowplaying.kick.chat.KickChatSettings.verify(mock_widget)

    def test_verify_enabled_with_template(self, bootstrap):
        """Test settings verification passes when enabled with template."""
        mock_widget = MagicMock()
        mock_widget.chat_checkbox.isChecked.return_value = True
        mock_widget.announce_lineedit.text.return_value = 'template.txt'

        # Should not raise an exception
        nowplaying.kick.chat.KickChatSettings.verify(mock_widget)
