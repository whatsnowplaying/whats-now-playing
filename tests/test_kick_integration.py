#!/usr/bin/env python3
"""Integration tests for the Kick module."""

import asyncio
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import nowplaying.kick.oauth2
import nowplaying.kick.chat
import nowplaying.kick.launch
import nowplaying.kick.settings


class TestKickIntegration:
    """Integration tests for Kick module components."""

    @pytest.mark.asyncio
    async def test_full_authentication_flow(self, bootstrap):
        """Test complete OAuth2 authentication flow."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/secret', 'test_secret')
        config.cparser.setValue('kick/redirecturi', 'http://localhost:8080/callback')
        
        # Create OAuth2 handler
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        # Test authorization URL generation
        auth_url = oauth.get_authorization_url()
        assert 'client_id=test_client_id' in auth_url
        assert oauth.code_verifier is not None
        assert oauth.state is not None
        
        # Mock successful token exchange
        mock_token_response = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token'
        }
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_token_response)
            
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_resp
            
            result = await oauth.exchange_code_for_token('test_auth_code', oauth.state)
            
            assert result == mock_token_response
            assert oauth.access_token == 'test_access_token'
            assert oauth.refresh_token == 'test_refresh_token'
            
            # Verify tokens were stored in config
            assert config.cparser.value('kick/accesstoken') == 'test_access_token'
            assert config.cparser.value('kick/refreshtoken') == 'test_refresh_token'

    @pytest.mark.asyncio
    async def test_chat_with_oauth_integration(self, bootstrap):
        """Test chat integration with OAuth2."""
        config = bootstrap
        config.cparser.setValue('kick/chat', True)
        config.cparser.setValue('kick/channel', 'testchannel')
        config.cparser.setValue('kick/accesstoken', 'valid_token')
        config.cparser.setValue('kick/refreshtoken', 'refresh_token')
        
        stopevent = asyncio.Event()
        
        # Create OAuth2 handler
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        # Create chat handler
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        
        # Mock OAuth methods
        oauth.get_stored_tokens = MagicMock(return_value=('valid_token', 'refresh_token'))
        oauth.validate_token = AsyncMock(return_value=True)
        
        # Test authentication
        chat.oauth = oauth
        result = await chat._authenticate()
        assert result is True
        assert chat.authenticated is True
        
        # Mock successful message sending
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.text = AsyncMock(return_value='{"data":{"is_sent":true},"message":"OK"}')
            
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_resp
            
            result = await chat._send_message("Test message")
            assert result is True

    @pytest.mark.asyncio
    async def test_launch_with_all_components(self, bootstrap):
        """Test launch integration with all components."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/accesstoken', 'valid_token')
        config.cparser.setValue('kick/chat', True)
        config.cparser.setValue('kick/channel', 'testchannel')
        
        stopevent = asyncio.Event()
        
        # Create launch handler
        launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)
        
        # Mock token validation to succeed
        launch._validate_kick_token_sync = MagicMock(return_value=True)
        
        # Test authentication
        result = await launch.authenticate()
        assert result is True
        
        # Test that chat is initialized in start method
        with patch.object(launch, 'bootstrap', new_callable=AsyncMock):
            with patch.object(launch, '_watch_for_exit', new_callable=AsyncMock):
                with patch('asyncio.get_running_loop') as mock_get_loop:
                    mock_loop = MagicMock()
                    mock_loop.create_task.return_value = MagicMock()
                    mock_loop.run_forever = MagicMock(side_effect=KeyboardInterrupt)
                    mock_get_loop.return_value = mock_loop
                    
                    try:
                        launch.start()
                    except KeyboardInterrupt:
                        pass
                    
                    # Verify chat was initialized
                    assert isinstance(launch.chat, nowplaying.kick.chat.KickChat)

    def test_settings_integration(self, bootstrap):
        """Test settings integration between main and chat settings."""
        config = bootstrap
        
        # Test main settings
        main_settings = nowplaying.kick.settings.KickSettings()
        mock_widget = MagicMock()
        
        main_settings.load(config, mock_widget)
        assert isinstance(main_settings.oauth, nowplaying.kick.oauth2.KickOAuth2)
        
        # Test chat settings
        chat_settings = nowplaying.kick.settings.KickChatSettings()
        mock_chat_widget = MagicMock()
        
        chat_settings.load(config, mock_chat_widget)
        assert chat_settings.widget == mock_chat_widget

    @pytest.mark.asyncio
    async def test_token_refresh_integration(self, bootstrap):
        """Test token refresh across components."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/accesstoken', 'expired_token')
        config.cparser.setValue('kick/refreshtoken', 'valid_refresh_token')
        
        # Create OAuth2 handler
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        
        # Mock refresh token response
        mock_refresh_response = {
            'access_token': 'new_access_token',
            'refresh_token': 'new_refresh_token'
        }
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_refresh_response)
            
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_resp
            
            result = await oauth.refresh_access_token('valid_refresh_token')
            
            assert result == mock_refresh_response
            assert oauth.access_token == 'new_access_token'
            
            # Verify new tokens were stored
            assert config.cparser.value('kick/accesstoken') == 'new_access_token'
            assert config.cparser.value('kick/refreshtoken') == 'new_refresh_token'

    @pytest.mark.asyncio
    async def test_announcement_flow_integration(self, bootstrap):
        """Test track announcement flow integration."""
        config = bootstrap
        config.cparser.setValue('kick/chat', True)
        config.cparser.setValue('kick/channel', 'testchannel')
        config.cparser.setValue('kick/announcedelay', 0.1)  # Fast for testing
        
        # Create template file
        template_path = bootstrap.templatedir / 'kick_announce.txt'
        template_path.write_text('Now playing: {{artist}} - {{title}}')
        config.cparser.setValue('kick/announce', str(template_path))
        
        stopevent = asyncio.Event()
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        chat.authenticated = True
        
        # Mock metadata
        mock_metadata = {'artist': 'Test Artist', 'title': 'Test Song'}
        chat.metadb.read_last_meta_async = AsyncMock(return_value=mock_metadata)
        
        # Mock message sending
        chat._send_message = AsyncMock(return_value=True)
        
        # Test announcement
        await chat._async_announce_track()
        
        # Verify message was sent with rendered template
        chat._send_message.assert_called_once_with('Now playing: Test Artist - Test Song')
        
        # Verify last announced was updated
        assert nowplaying.kick.chat.LASTANNOUNCED['artist'] == 'Test Artist'
        assert nowplaying.kick.chat.LASTANNOUNCED['title'] == 'Test Song'

    def test_command_discovery_integration(self, bootstrap):
        """Test command template discovery integration."""
        config = bootstrap
        
        # Create kickbot template files
        template_dir = pathlib.Path(bootstrap.templatedir)
        (template_dir / 'kickbot_track.txt').write_text('Now playing: {{artist}} - {{title}}')
        (template_dir / 'kickbot_artist.txt').write_text('Artist: {{artist}}')
        (template_dir / 'kickbot_request.txt').write_text('Request: {{request}}')
        
        # Create settings and update commands
        chat_settings = nowplaying.kick.settings.KickChatSettings()
        chat_settings.update_kickbot_commands(config)
        
        # Verify commands were created
        groups = config.cparser.childGroups()
        assert 'kickbot-command-track' in groups
        assert 'kickbot-command-artist' in groups
        assert 'kickbot-command-request' in groups
        
        # Verify default permissions (all disabled)
        config.cparser.beginGroup('kickbot-command-track')
        for permission in chat_settings.KICKBOT_CHECKBOXES:
            assert config.cparser.value(permission, type=bool) is False
        config.cparser.endGroup()

    @pytest.mark.asyncio
    async def test_error_handling_integration(self, bootstrap):
        """Test error handling across components."""
        config = bootstrap
        
        # Test OAuth with network error
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        oauth.code_verifier = 'test_verifier'
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_session.side_effect = Exception("Network error")
            
            with pytest.raises(Exception):
                await oauth.exchange_code_for_token('test_code')
        
        # Test chat with authentication failure
        stopevent = asyncio.Event()
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        
        # Mock OAuth to fail
        mock_oauth = MagicMock()
        mock_oauth.get_stored_tokens.return_value = (None, None)
        chat.oauth = mock_oauth
        
        result = await chat._authenticate()
        assert result is False
        assert chat.authenticated is False
        
        # Test message sending when not authenticated
        result = await chat._send_message("Test message")
        assert result is False

    @pytest.mark.asyncio
    async def test_config_changes_integration(self, bootstrap):
        """Test configuration changes affecting components."""
        config = bootstrap
        
        # Initial configuration
        config.cparser.setValue('kick/clientid', 'old_client_id')
        config.cparser.setValue('kick/channel', 'oldchannel')
        config.cparser.setValue('kick/accesstoken', 'old_token')
        
        # Test settings save with changes
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = True
        mock_widget.channel_lineedit.text.return_value = 'newchannel'
        mock_widget.clientid_lineedit.text.return_value = 'new_client_id'
        mock_widget.secret_lineedit.text.return_value = 'secret'
        mock_widget.redirecturi_lineedit.text.return_value = 'http://localhost:8080'
        
        mock_subprocesses = MagicMock()
        
        with patch('time.sleep'):  # Speed up test
            nowplaying.kick.settings.KickSettings.save(config, mock_widget, mock_subprocesses)
        
        # Verify kickbot was restarted due to changes
        mock_subprocesses.stop_kickbot.assert_called_once()
        mock_subprocesses.start_kickbot.assert_called_once()
        
        # Verify tokens were cleared due to config changes
        assert config.cparser.value('kick/accesstoken') is None

    def test_ui_widget_integration(self, bootstrap):
        """Test UI widget integration."""
        # Test main settings widget connection
        main_settings = nowplaying.kick.settings.KickSettings()
        mock_uihelp = MagicMock()
        mock_widget = MagicMock()
        
        main_settings.connect(mock_uihelp, mock_widget)
        
        # Verify button connections
        mock_widget.authenticate_button.clicked.connect.assert_called_once()
        mock_widget.clientid_lineedit.editingFinished.connect.assert_called_once()
        
        # Test chat settings widget connection
        chat_settings = nowplaying.kick.settings.KickChatSettings()
        mock_chat_widget = MagicMock()
        mock_chat_widget.announce_button = MagicMock()
        mock_chat_widget.add_button = MagicMock()
        mock_chat_widget.del_button = MagicMock()
        
        chat_settings.connect(mock_uihelp, mock_chat_widget)
        
        # Verify chat widget connections
        mock_chat_widget.announce_button.clicked.connect.assert_called_once()
        mock_chat_widget.add_button.clicked.connect.assert_called_once()
        mock_chat_widget.del_button.clicked.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifecycle_integration(self, bootstrap):
        """Test complete component lifecycle."""
        config = bootstrap
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/accesstoken', 'valid_token')
        config.cparser.setValue('kick/chat', True)
        config.cparser.setValue('kick/channel', 'testchannel')
        
        stopevent = asyncio.Event()
        
        # Create and start launch
        launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)
        launch._validate_kick_token_sync = MagicMock(return_value=True)
        
        # Test bootstrap
        with patch('signal.signal'):
            await launch.bootstrap()
        
        # Verify chat was created
        assert launch.chat is not None
        
        # Test stop
        launch.chat.stop = AsyncMock()
        await launch.stop()
        
        # Verify cleanup
        launch.chat.stop.assert_called_once()


class TestKickModuleEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_malformed_api_responses(self, bootstrap):
        """Test handling of malformed API responses."""
        config = bootstrap
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        oauth.code_verifier = 'test_verifier'
        
        # Test malformed JSON response
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(side_effect=ValueError("Invalid JSON"))
            
            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.return_value = mock_resp
            
            with pytest.raises(Exception):
                await oauth.exchange_code_for_token('test_code')

    @pytest.mark.asyncio
    async def test_network_timeouts(self, bootstrap):
        """Test network timeout handling."""
        config = bootstrap
        stopevent = asyncio.Event()
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        chat.authenticated = True
        
        # Mock OAuth
        mock_oauth = MagicMock()
        mock_oauth.get_stored_tokens.return_value = ('token', 'refresh')
        chat.oauth = mock_oauth
        
        # Test timeout during message sending
        with patch('aiohttp.ClientSession') as mock_session:
            mock_session.side_effect = asyncio.TimeoutError("Request timed out")
            
            result = await chat._send_message("Test message")
            assert result is False

    def test_invalid_template_files(self, bootstrap):
        """Test handling of invalid template files."""
        config = bootstrap
        
        # Create invalid template path
        config.cparser.setValue('kick/announce', '/nonexistent/template.txt')
        
        stopevent = asyncio.Event()
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        chat.authenticated = True
        
        # Mock metadata
        mock_metadata = {'artist': 'Test', 'title': 'Test'}
        chat.metadb.read_last_meta_async = AsyncMock(return_value=mock_metadata)
        
        # Test announcement with invalid template - should not crash
        async def test_announcement():
            await chat._async_announce_track()
        
        # Should not raise exception
        asyncio.run(test_announcement())

    def test_concurrent_access(self, bootstrap):
        """Test concurrent access to components."""
        config = bootstrap
        
        # Test multiple OAuth instances
        oauth1 = nowplaying.kick.oauth2.KickOAuth2(config)
        oauth2 = nowplaying.kick.oauth2.KickOAuth2(config)
        
        # Both should work independently
        oauth1._generate_pkce_parameters()
        oauth2._generate_pkce_parameters()
        
        assert oauth1.code_verifier != oauth2.code_verifier
        assert oauth1.state != oauth2.state

    def test_memory_cleanup(self, bootstrap):
        """Test memory cleanup on component destruction."""
        config = bootstrap
        stopevent = asyncio.Event()
        
        # Create components
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)
        
        # Add tasks
        mock_task = MagicMock()
        chat.tasks.add(mock_task)
        launch.tasks.add(mock_task)
        
        # Test cleanup
        async def test_cleanup():
            await chat.stop()
            await launch.stop()
        
        asyncio.run(test_cleanup())
        
        # Verify tasks were cancelled
        mock_task.cancel.assert_called()

    def test_unicode_and_special_characters(self, bootstrap):
        """Test handling of unicode and special characters."""
        # Test template with unicode
        template_content = 'Now playing: {{artist}} - {{title}} 🎵'
        template_path = bootstrap.templatedir / 'unicode_template.txt'
        template_path.write_text(template_content, encoding='utf-8')
        
        config = bootstrap
        stopevent = asyncio.Event()
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        
        # Test Jinja2 environment can handle unicode
        env = chat.setup_jinja2(pathlib.Path(bootstrap.templatedir))
        template = env.get_template('unicode_template.txt')
        
        result = template.render(artist='Björk', title='Jóga')
        assert 'Björk' in result
        assert 'Jóga' in result
        assert '🎵' in result