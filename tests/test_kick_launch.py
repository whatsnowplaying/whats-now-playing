#!/usr/bin/env python3
"""Unit tests for Kick launch functionality."""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

import nowplaying.kick.launch
import nowplaying.kick.oauth2
import nowplaying.kick.chat


class TestKickLaunch:
    """Test cases for KickLaunch class."""

    def test_init_with_config(self, bootstrap):
        """Test KickLaunch initialization with config."""
        config = bootstrap
        stopevent = asyncio.Event()
        
        launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)
        
        assert launch.config == config
        assert launch.stopevent == stopevent
        assert launch.widgets is None
        assert launch.chat is None
        assert launch.loop is None
        assert isinstance(launch.oauth, nowplaying.kick.oauth2.KickOAuth2)
        assert len(launch.tasks) == 0

    def test_init_without_stopevent(self, bootstrap):
        """Test KickLaunch initialization without stopevent."""
        config = bootstrap
        
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        assert launch.config == config
        assert isinstance(launch.stopevent, asyncio.Event)

    def test_init_without_config(self):
        """Test KickLaunch initialization without config."""
        launch = nowplaying.kick.launch.KickLaunch()
        
        assert launch.config is None
        assert isinstance(launch.stopevent, asyncio.Event)

    def test_validate_kick_token_sync_success(self, bootstrap):
        """Test successful synchronous token validation."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'data': {
                'active': True,
                'client_id': 'test_client',
                'scope': 'user:read chat:write',
                'token_type': 'user'
            }
        }
        
        with patch('requests.post', return_value=mock_response):
            result = launch._validate_kick_token_sync('test_token')
            
            assert result is True

    def test_validate_kick_token_sync_inactive(self, bootstrap):
        """Test token validation with inactive token."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'data': {
                'active': False
            }
        }
        
        with patch('requests.post', return_value=mock_response):
            result = launch._validate_kick_token_sync('test_token')
            
            assert result is False

    def test_validate_kick_token_sync_no_token(self, bootstrap):
        """Test token validation with no token."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        result = launch._validate_kick_token_sync('')
        
        assert result is False

    def test_validate_kick_token_sync_401(self, bootstrap):
        """Test token validation with 401 response."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        mock_response = MagicMock()
        mock_response.status_code = 401
        
        with patch('requests.post', return_value=mock_response):
            result = launch._validate_kick_token_sync('test_token')
            
            assert result is False

    def test_validate_kick_token_sync_403(self, bootstrap):
        """Test token validation with 403 response."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        mock_response = MagicMock()
        mock_response.status_code = 403
        
        with patch('requests.post', return_value=mock_response):
            result = launch._validate_kick_token_sync('test_token')
            
            assert result is False

    def test_validate_kick_token_sync_other_error(self, bootstrap):
        """Test token validation with other HTTP error."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        mock_response = MagicMock()
        mock_response.status_code = 500
        
        with patch('requests.post', return_value=mock_response):
            result = launch._validate_kick_token_sync('test_token')
            
            assert result is False

    def test_validate_kick_token_sync_exception(self, bootstrap):
        """Test token validation with network exception."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        with patch('requests.post', side_effect=requests.RequestException("Network error")):
            result = launch._validate_kick_token_sync('test_token')
            
            assert result is False

    def test_validate_kick_token_sync_json_error(self, bootstrap):
        """Test token validation with JSON parsing error."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        
        with patch('requests.post', return_value=mock_response):
            result = launch._validate_kick_token_sync('test_token')
            
            assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_no_token(self, bootstrap):
        """Test authentication with no stored token."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        # Mock OAuth to return no tokens
        launch.oauth.get_stored_tokens = MagicMock(return_value=(None, None))
        
        result = await launch.authenticate()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_valid_token(self, bootstrap):
        """Test authentication with valid token."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        # Mock OAuth to return valid token
        launch.oauth.get_stored_tokens = MagicMock(return_value=('valid_token', 'refresh_token'))
        launch._validate_kick_token_sync = MagicMock(return_value=True)
        
        result = await launch.authenticate()
        
        assert result is True

    @pytest.mark.asyncio
    async def test_authenticate_refresh_token_success(self, bootstrap):
        """Test authentication with token refresh."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        # Mock OAuth to return invalid token first, then valid after refresh
        launch.oauth.get_stored_tokens = MagicMock()
        launch.oauth.get_stored_tokens.side_effect = [
            ('invalid_token', 'refresh_token'),  # First call
            ('new_valid_token', 'refresh_token')  # After refresh
        ]
        launch._validate_kick_token_sync = MagicMock()
        launch._validate_kick_token_sync.side_effect = [False, True]  # Invalid, then valid
        launch.oauth.refresh_access_token = AsyncMock()
        
        result = await launch.authenticate()
        
        assert result is True
        launch.oauth.refresh_access_token.assert_called_once_with('refresh_token')

    @pytest.mark.asyncio
    async def test_authenticate_refresh_token_failure(self, bootstrap):
        """Test authentication with token refresh failure."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        # Mock OAuth to return invalid token
        launch.oauth.get_stored_tokens = MagicMock(return_value=('invalid_token', 'refresh_token'))
        launch._validate_kick_token_sync = MagicMock(return_value=False)
        launch.oauth.refresh_access_token = AsyncMock(side_effect=Exception("Refresh failed"))
        
        result = await launch.authenticate()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_no_refresh_token(self, bootstrap):
        """Test authentication with no refresh token available."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        # Mock OAuth to return invalid token with no refresh token
        launch.oauth.get_stored_tokens = MagicMock(return_value=('invalid_token', None))
        launch._validate_kick_token_sync = MagicMock(return_value=False)
        
        result = await launch.authenticate()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_exception(self, bootstrap):
        """Test authentication with unexpected exception."""
        config = bootstrap
        launch = nowplaying.kick.launch.KickLaunch(config=config)
        
        # Mock OAuth to raise exception
        launch.oauth.get_stored_tokens = MagicMock(side_effect=Exception("Unexpected error"))
        
        result = await launch.authenticate()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_bootstrap_authentication_failure(self, bootstrap):
        """Test bootstrap with authentication failure."""
        config = bootstrap
        stopevent = asyncio.Event()
        launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)
        
        # Mock authentication to fail
        launch.authenticate = AsyncMock(return_value=False)
        
        with patch('signal.signal'):
            await launch.bootstrap()
        
        # Should return early without starting tasks
        assert len(launch.tasks) == 0

    @pytest.mark.asyncio
    async def test_bootstrap_success(self, bootstrap):
        """Test successful bootstrap."""
        config = bootstrap
        stopevent = asyncio.Event()
        launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)
        
        # Mock authentication to succeed
        launch.authenticate = AsyncMock(return_value=True)
        
        # Mock chat
        mock_chat = MagicMock()
        mock_chat.run_chat = AsyncMock()
        launch.chat = mock_chat
        
        with patch('signal.signal'):
            with patch('asyncio.get_running_loop') as mock_get_loop:
                mock_loop = MagicMock()
                mock_task = MagicMock()
                mock_loop.create_task.return_value = mock_task
                mock_get_loop.return_value = mock_loop
                
                await launch.bootstrap()
                
                # Verify task was created and added
                mock_loop.create_task.assert_called()
                assert mock_task in launch.tasks

    def test_forced_stop(self, bootstrap):
        """Test forced stop signal handler."""
        config = bootstrap
        stopevent = asyncio.Event()
        launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)
        
        assert not stopevent.is_set()
        
        launch.forced_stop(signal.SIGINT, None)
        
        assert stopevent.is_set()

    @pytest.mark.asyncio
    async def test_stop(self, bootstrap):
        """Test stop functionality."""
        config = bootstrap
        stopevent = asyncio.Event()
        launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)
        
        # Mock chat
        mock_chat = AsyncMock()
        launch.chat = mock_chat
        
        # Mock loop
        mock_loop = MagicMock()
        launch.loop = mock_loop
        
        await launch.stop()
        
        # Verify cleanup
        mock_chat.stop.assert_called_once()
        mock_loop.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_no_chat(self, bootstrap):
        """Test stop with no chat instance."""
        config = bootstrap
        stopevent = asyncio.Event()
        launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)
        
        # Mock loop
        mock_loop = MagicMock()
        launch.loop = mock_loop
        
        await launch.stop()
        
        # Should not raise exception
        mock_loop.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_watch_for_exit(self, bootstrap):
        """Test watch for exit functionality."""
        config = bootstrap
        stopevent = asyncio.Event()
        launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)
        
        # Mock stop method
        launch.stop = AsyncMock()
        
        # Set stop event after short delay
        async def set_stop_event():
            await asyncio.sleep(0.01)
            stopevent.set()
        
        # Run both tasks
        await asyncio.gather(
            launch._watch_for_exit(),
            set_stop_event()
        )
        
        # Verify stop was called
        launch.stop.assert_called_once()

    def test_start_initialization(self, bootstrap):
        """Test start method initialization."""
        config = bootstrap
        stopevent = asyncio.Event()
        launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)
        
        # Mock loop and methods to avoid actually running
        with patch('asyncio.get_running_loop') as mock_get_loop:
            with patch.object(launch, 'bootstrap', new_callable=AsyncMock):
                with patch.object(launch, '_watch_for_exit', new_callable=AsyncMock):
                    mock_loop = MagicMock()
                    mock_task = MagicMock()
                    mock_loop.create_task.return_value = mock_task
                    mock_loop.run_forever = MagicMock(side_effect=KeyboardInterrupt)
                    mock_get_loop.return_value = mock_loop
                    
                    try:
                        launch.start()
                    except KeyboardInterrupt:
                        pass
                    
                    # Verify chat was initialized
                    assert isinstance(launch.chat, nowplaying.kick.chat.KickChat)
                    assert launch.loop == mock_loop

    def test_start_with_new_event_loop(self, bootstrap):
        """Test start method with new event loop."""
        config = bootstrap
        stopevent = asyncio.Event()
        launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)
        
        # Mock methods to avoid actually running
        with patch('asyncio.get_running_loop', side_effect=RuntimeError("No running loop")):
            with patch('asyncio.new_event_loop') as mock_new_loop:
                with patch.object(launch, 'bootstrap', new_callable=AsyncMock):
                    with patch.object(launch, '_watch_for_exit', new_callable=AsyncMock):
                        mock_loop = MagicMock()
                        mock_task = MagicMock()
                        mock_loop.create_task.return_value = mock_task
                        mock_loop.run_forever = MagicMock(side_effect=KeyboardInterrupt)
                        mock_new_loop.return_value = mock_loop
                        
                        try:
                            launch.start()
                        except KeyboardInterrupt:
                            pass
                        
                        # Verify new loop was created
                        mock_new_loop.assert_called_once()
                        assert launch.loop == mock_loop


class TestKickLaunchModuleFunctions:
    """Test module-level functions in kick.launch."""

    @patch('nowplaying.kick.launch.KickLaunch')
    @patch('nowplaying.frozen.frozen_init')
    @patch('nowplaying.bootstrap.set_qt_names')
    @patch('nowplaying.bootstrap.setuplogging')
    @patch('nowplaying.config.ConfigFile')
    @patch('threading.current_thread')
    def test_start_function(self, mock_thread, mock_config, mock_logging, 
                           mock_set_names, mock_frozen, mock_kick_launch):
        """Test module start function."""
        mock_stopevent = MagicMock()
        mock_bundledir = "/test/bundle"
        
        # Mock objects
        mock_frozen.return_value = mock_bundledir
        mock_logging.return_value = "/test/logs"
        mock_config_instance = MagicMock()
        mock_config.return_value = mock_config_instance
        mock_launch_instance = MagicMock()
        mock_kick_launch.return_value = mock_launch_instance
        
        # Call function
        nowplaying.kick.launch.start(
            stopevent=mock_stopevent, 
            bundledir=mock_bundledir, 
            testmode=True
        )
        
        # Verify calls
        mock_frozen.assert_called_once_with(mock_bundledir)
        mock_set_names.assert_called_once_with(appname='testsuite')
        mock_logging.assert_called_once_with(logname='debug.log', rotate=False)
        mock_config.assert_called_once_with(
            bundledir=mock_bundledir, 
            logpath="/test/logs", 
            testmode=True
        )
        mock_kick_launch.assert_called_once_with(
            config=mock_config_instance, 
            stopevent=mock_stopevent
        )
        mock_launch_instance.start.assert_called_once()

    @patch('nowplaying.kick.launch.KickLaunch')
    @patch('nowplaying.frozen.frozen_init')
    @patch('nowplaying.bootstrap.set_qt_names')
    @patch('nowplaying.bootstrap.setuplogging')
    @patch('nowplaying.config.ConfigFile')
    @patch('threading.current_thread')
    def test_start_function_not_testmode(self, mock_thread, mock_config, mock_logging,
                                        mock_set_names, mock_frozen, mock_kick_launch):
        """Test module start function without testmode."""
        mock_stopevent = MagicMock()
        
        # Mock objects
        mock_frozen.return_value = "/bundle"
        mock_logging.return_value = "/logs"
        mock_config_instance = MagicMock()
        mock_config.return_value = mock_config_instance
        mock_launch_instance = MagicMock()
        mock_kick_launch.return_value = mock_launch_instance
        
        # Call function
        nowplaying.kick.launch.start(stopevent=mock_stopevent)
        
        # Verify set_qt_names called without appname
        mock_set_names.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_launch_kickbot_function(self, bootstrap):
        """Test launch_kickbot async function."""
        config = bootstrap
        stopevent = asyncio.Event()
        
        with patch('nowplaying.kick.launch.KickLaunch') as mock_kick_launch:
            mock_launch_instance = MagicMock()
            mock_launch_instance.bootstrap = AsyncMock()
            mock_kick_launch.return_value = mock_launch_instance
            
            await nowplaying.kick.launch.launch_kickbot(config=config, stopevent=stopevent)
            
            mock_kick_launch.assert_called_once_with(config=config, stopevent=stopevent)
            mock_launch_instance.bootstrap.assert_called_once()

    @pytest.mark.asyncio
    async def test_launch_kickbot_function_exception(self, bootstrap):
        """Test launch_kickbot async function with exception."""
        config = bootstrap
        stopevent = asyncio.Event()
        
        with patch('nowplaying.kick.launch.KickLaunch') as mock_kick_launch:
            mock_launch_instance = MagicMock()
            mock_launch_instance.bootstrap = AsyncMock(side_effect=Exception("Test error"))
            mock_kick_launch.return_value = mock_launch_instance
            
            # Should not raise exception
            await nowplaying.kick.launch.launch_kickbot(config=config, stopevent=stopevent)