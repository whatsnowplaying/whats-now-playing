#!/usr/bin/env python3
"""Integration tests for the Kick module - REFACTORED VERSION."""

import asyncio
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aioresponses import aioresponses

import nowplaying.kick.oauth2
import nowplaying.kick.chat
import nowplaying.kick.launch
import nowplaying.kick.settings


# Fixtures
@pytest.fixture
def kick_integration_config(bootstrap):
    """Create a fully configured integration test config."""
    config = bootstrap
    config.cparser.setValue('kick/clientid', 'test_client_id')
    config.cparser.setValue('kick/secret', 'test_secret')
    config.cparser.setValue('kick/redirecturi', 'http://localhost:8080/callback')
    config.cparser.setValue('kick/channel', 'testchannel')
    config.cparser.setValue('kick/chat', True)
    config.cparser.setValue('kick/accesstoken', 'valid_token')
    config.cparser.setValue('kick/refreshtoken', 'refresh_token')
    config.cparser.setValue('kick/announcedelay', 0.1)  # Fast for testing
    return config


@pytest.fixture
def mock_oauth_success():
    """Create a mock OAuth handler that succeeds."""
    mock_oauth = MagicMock()
    mock_oauth.get_stored_tokens.return_value = ('valid_token', 'refresh_token')
    mock_oauth.validate_token = AsyncMock(return_value=True)
    return mock_oauth


@pytest.fixture
def mock_oauth_failure():
    """Create a mock OAuth handler that fails."""
    mock_oauth = MagicMock()
    mock_oauth.get_stored_tokens.return_value = (None, None)
    mock_oauth.validate_token = AsyncMock(return_value=False)
    return mock_oauth


@pytest.fixture
def kick_templates(bootstrap):
    """Create test template files for integration tests."""
    # Use test directory instead of Documents
    test_template_dir = bootstrap.testdir / 'templates'
    bootstrap.templatedir = test_template_dir
    test_template_dir.mkdir(parents=True, exist_ok=True)

    templates = {
        'announce': test_template_dir / 'kick_announce.txt',
        'track': test_template_dir / 'kickbot_track.txt',
        'artist': test_template_dir / 'kickbot_artist.txt',
        'request': test_template_dir / 'kickbot_request.txt',
    }

    templates['announce'].write_text('Now playing: {{artist}} - {{title}}')
    templates['track'].write_text('Now playing: {{artist}} - {{title}}')
    templates['artist'].write_text('Artist: {{artist}}')
    templates['request'].write_text('Request: {{request}}')

    return templates


@pytest.fixture
def mock_chat_with_oauth(kick_integration_config, mock_oauth_success):
    """Create a chat instance with mocked OAuth."""
    stopevent = asyncio.Event()
    chat = nowplaying.kick.chat.KickChat(config=kick_integration_config, stopevent=stopevent)
    chat.oauth = mock_oauth_success
    return chat, stopevent


@pytest.fixture
def mock_aiohttp_success():
    """Fixture that mocks successful aiohttp responses using aioresponses."""
    with aioresponses() as mock:
        # Setup default success responses for common endpoints
        mock.post("https://kick.com/api/v2/messages/send/testchannel",
                  status=200,
                  payload={'success': True})
        yield mock


@pytest.fixture
def mock_responses():
    """Fixture that provides aioresponses for mocking HTTP calls."""
    with aioresponses() as mock:
        yield mock


class TestKickIntegration:
    """Integration tests for Kick module components."""

    @pytest.mark.asyncio
    async def test_full_authentication_flow(self, kick_integration_config, mock_responses):
        """Test complete OAuth2 authentication flow."""
        config = kick_integration_config

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

        mock_responses.post(f"{oauth.OAUTH_HOST}/oauth/token",
                            status=200,
                            payload=mock_token_response)

        result = await oauth.exchange_code_for_token('test_auth_code', oauth.state)

        assert result == mock_token_response
        assert oauth.access_token == 'test_access_token'
        assert oauth.refresh_token == 'test_refresh_token'

        # Verify tokens were stored in config
        assert config.cparser.value('kick/accesstoken') == 'test_access_token'
        assert config.cparser.value('kick/refreshtoken') == 'test_refresh_token'

    @pytest.mark.asyncio
    async def test_chat_with_oauth_integration(self, mock_chat_with_oauth, mock_responses):
        """Test chat integration with OAuth2."""
        chat, stopevent = mock_chat_with_oauth

        # Test authentication
        result = await chat._authenticate()
        assert result
        assert chat.authenticated

        # Mock message sending endpoint
        mock_responses.post("https://kick.com/api/v2/messages/send/testchannel",
                            status=200,
                            payload={
                                'data': {
                                    'is_sent': True
                                },
                                'message': 'OK'
                            })

        # Test message sending
        result = await chat._send_message("Test message")
        assert result is True

    @pytest.mark.asyncio
    async def test_launch_with_all_components(self, kick_integration_config):
        """Test launch integration with all components."""
        config = kick_integration_config
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

    # Parameterized settings integration tests
    @pytest.mark.parametrize("settings_type", ['main', 'chat'])
    def test_settings_integration_scenarios(self, kick_integration_config, settings_type):
        """Test settings integration for different types."""
        config = kick_integration_config

        if settings_type == 'main':
            settings = nowplaying.kick.settings.KickSettings()
            mock_widget = MagicMock()

            settings.load(config, mock_widget)
            assert isinstance(settings.oauth, nowplaying.kick.oauth2.KickOAuth2)
        else:
            chat_settings = nowplaying.kick.settings.KickChatSettings()
            mock_chat_widget = MagicMock()

            chat_settings.load(config, mock_chat_widget)
            assert chat_settings.widget == mock_chat_widget

    @pytest.mark.asyncio
    async def test_token_refresh_integration(self, kick_integration_config, mock_responses):
        """Test token refresh across components."""
        config = kick_integration_config
        config.cparser.setValue('kick/accesstoken', 'expired_token')

        # Create OAuth2 handler
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)

        # Mock refresh token response
        mock_refresh_response = {
            'access_token': 'new_access_token',
            'refresh_token': 'new_refresh_token'
        }

        mock_responses.post(f"{oauth.OAUTH_HOST}/oauth/token",
                            status=200,
                            payload=mock_refresh_response)

        result = await oauth.refresh_access_token('valid_refresh_token')

        assert result == mock_refresh_response
        assert oauth.access_token == 'new_access_token'

        # Verify new tokens were stored
        assert config.cparser.value('kick/accesstoken') == 'new_access_token'
        assert config.cparser.value('kick/refreshtoken') == 'new_refresh_token'

    @pytest.mark.asyncio
    async def test_announcement_flow_integration(self, kick_integration_config, kick_templates):
        """Test track announcement flow integration."""
        config = kick_integration_config
        config.cparser.setValue('kick/announce', str(kick_templates['announce']))

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

    def test_command_discovery_integration(self, kick_integration_config, kick_templates):
        """Test command template discovery integration."""
        config = kick_integration_config

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
            assert not config.cparser.value(permission, type=bool)
        config.cparser.endGroup()

    # Parameterized error handling tests
    @pytest.mark.parametrize("component,error_scenario,expected_behavior", [
        ('oauth', 'network_error', 'raises_exception'),
        ('chat', 'no_tokens', 'returns_false'),
        ('chat', 'not_authenticated', 'returns_false'),
    ])
    @pytest.mark.asyncio
    async def test_error_handling_scenarios(self, kick_integration_config, component,
                                            error_scenario, expected_behavior):
        """Test error handling across different components and scenarios."""
        config = kick_integration_config

        if component == 'oauth':
            oauth = nowplaying.kick.oauth2.KickOAuth2(config)
            oauth.code_verifier = 'test_verifier'

            with patch('aiohttp.ClientSession') as mock_session:
                mock_session.side_effect = Exception("Network error")

                with pytest.raises(Exception):
                    await oauth.exchange_code_for_token('test_code')

        elif component == 'chat':
            stopevent = asyncio.Event()
            chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)

            if error_scenario == 'no_tokens':
                # Mock OAuth to fail
                mock_oauth = MagicMock()
                mock_oauth.get_stored_tokens.return_value = (None, None)
                chat.oauth = mock_oauth

                result = await chat._authenticate()
                assert not result
                assert not chat.authenticated

            elif error_scenario == 'not_authenticated':
                chat.authenticated = False

                result = await chat._send_message("Test message")
                assert result is False

    @pytest.mark.asyncio
    async def test_config_changes_integration(self, kick_integration_config):
        """Test configuration changes affecting components."""
        config = kick_integration_config

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

    # Parameterized UI widget integration tests
    @pytest.mark.parametrize("widget_type", ['main', 'chat'])
    def test_ui_widget_integration_scenarios(self, widget_type):
        """Test UI widget integration for different widget types."""
        if widget_type == 'main':
            main_settings = nowplaying.kick.settings.KickSettings()
            mock_uihelp = MagicMock()
            mock_widget = MagicMock()

            main_settings.connect(mock_uihelp, mock_widget)

            # Verify button connections
            mock_widget.authenticate_button.clicked.connect.assert_called_once()
            mock_widget.clientid_lineedit.editingFinished.connect.assert_called_once()

        else:
            chat_settings = nowplaying.kick.settings.KickChatSettings()
            mock_chat_widget = MagicMock()
            mock_chat_widget.announce_button = MagicMock()
            mock_chat_widget.add_button = MagicMock()
            mock_chat_widget.del_button = MagicMock()

            chat_settings.connect(MagicMock(), mock_chat_widget)

            # Verify chat widget connections
            mock_chat_widget.announce_button.clicked.connect.assert_called_once()
            mock_chat_widget.add_button.clicked.connect.assert_called_once()
            mock_chat_widget.del_button.clicked.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifecycle_integration(self, kick_integration_config):
        """Test complete component lifecycle."""
        config = kick_integration_config
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
    async def test_malformed_api_responses(self, kick_integration_config):
        """Test handling of malformed API responses."""
        config = kick_integration_config
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        oauth.code_verifier = 'test_verifier'

        # Test malformed JSON response
        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(side_effect=ValueError("Invalid JSON"))

            mock_session.return_value.__aenter__.return_value.post.return_value.__aenter__.\
                return_value = mock_resp

            with pytest.raises(Exception):
                await oauth.exchange_code_for_token('test_code')

    @pytest.mark.asyncio
    async def test_network_timeouts(self, kick_integration_config, mock_oauth_success):
        """Test network timeout handling."""
        config = kick_integration_config
        stopevent = asyncio.Event()
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)
        chat.authenticated = True
        chat.oauth = mock_oauth_success

        # Test timeout during message sending
        with patch('aiohttp.ClientSession') as mock_session:
            mock_session.side_effect = asyncio.TimeoutError("Request timed out")

            result = await chat._send_message("Test message")
            assert result is False

    def test_invalid_template_files(self, kick_integration_config):
        """Test handling of invalid template files."""
        config = kick_integration_config

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

    def test_concurrent_access(self, kick_integration_config):
        """Test concurrent access to components."""
        config = kick_integration_config

        # Test multiple OAuth instances
        oauth1 = nowplaying.kick.oauth2.KickOAuth2(config)
        oauth2 = nowplaying.kick.oauth2.KickOAuth2(config)

        # Both should work independently
        oauth1._generate_pkce_parameters()
        oauth2._generate_pkce_parameters()

        assert oauth1.code_verifier != oauth2.code_verifier
        assert oauth1.state != oauth2.state

    def test_memory_cleanup(self, kick_integration_config):
        """Test memory cleanup on component destruction."""
        config = kick_integration_config
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

    def test_unicode_and_special_characters(self, kick_integration_config):
        """Test handling of unicode and special characters."""
        config = kick_integration_config

        # Create unicode template in test directory
        test_template_dir = config.testdir / 'templates'
        config.templatedir = test_template_dir
        test_template_dir.mkdir(parents=True, exist_ok=True)

        # Test template with unicode
        template_content = 'Now playing: {{artist}} - {{title}} 🎵'
        template_path = test_template_dir / 'unicode_template.txt'
        template_path.write_text(template_content, encoding='utf-8')

        stopevent = asyncio.Event()
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)

        # Test Jinja2 environment can handle unicode
        env = chat.setup_jinja2(pathlib.Path(config.templatedir))
        template = env.get_template('unicode_template.txt')

        result = template.render(artist='Björk', title='Jóga')
        assert 'Björk' in result
        assert 'Jóga' in result
        assert '🎵' in result


class TestKickPerformanceIntegration:
    """Test performance-related integration scenarios."""

    @pytest.mark.asyncio
    async def test_rapid_message_sending(self, mock_chat_with_oauth, mock_aiohttp_success):
        """Test rapid successive message sending."""
        chat, stopevent = mock_chat_with_oauth
        chat.authenticated = True

        # Send multiple messages quickly
        results = await asyncio.gather(*[chat._send_message(f"Message {i}") for i in range(5)])

        # All should succeed
        assert all(results)

    @pytest.mark.asyncio
    async def test_concurrent_authentication_attempts(self, kick_integration_config):
        """Test concurrent authentication attempts."""
        config = kick_integration_config

        # Create multiple launch instances
        launches = [
            nowplaying.kick.launch.KickLaunch(config=config, stopevent=asyncio.Event())
            for _ in range(3)
        ]

        # Mock token validation for all
        for launch in launches:
            launch._validate_kick_token_sync = MagicMock(return_value=True)

        # Authenticate concurrently
        results = await asyncio.gather(*[launch.authenticate() for launch in launches])

        # All should succeed
        assert all(results)

    def test_large_template_processing(self, kick_integration_config):
        """Test processing of large template files."""
        config = kick_integration_config

        # Create large template content in test directory
        test_template_dir = config.testdir / 'templates'
        config.templatedir = test_template_dir
        test_template_dir.mkdir(parents=True, exist_ok=True)

        large_template = 'Now playing: {{artist}} - {{title}}\n' * 1000
        template_path = test_template_dir / 'large_template.txt'
        template_path.write_text(large_template)

        stopevent = asyncio.Event()
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)

        # Should handle large templates without issues
        env = chat.setup_jinja2(pathlib.Path(config.templatedir))
        template = env.get_template('large_template.txt')

        result = template.render(artist='Test Artist', title='Test Song')
        assert len(result) > 10000  # Should be large
        assert 'Test Artist' in result
