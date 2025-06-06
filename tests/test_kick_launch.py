#!/usr/bin/env python3
"""Unit tests for Kick launch functionality - REFACTORED VERSION."""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

import nowplaying.kick.launch
import nowplaying.kick.oauth2
import nowplaying.kick.chat


# Fixtures
@pytest.fixture
def kick_launch(bootstrap):
    """Create a KickLaunch instance with bootstrap config."""
    return nowplaying.kick.launch.KickLaunch(config=bootstrap)


@pytest.fixture
def kick_launch_with_stopevent(bootstrap):
    """Create a KickLaunch instance with bootstrap config and stopevent."""
    stopevent = asyncio.Event()
    launch = nowplaying.kick.launch.KickLaunch(config=bootstrap, stopevent=stopevent)
    return launch, stopevent


class TestKickLaunch:
    """Test cases for KickLaunch class."""

    def test_init_with_config(self, bootstrap):
        """Test KickLaunch initialization with config."""
        stopevent = asyncio.Event()
        
        launch = nowplaying.kick.launch.KickLaunch(config=bootstrap, stopevent=stopevent)
        
        assert launch.config == bootstrap
        assert launch.stopevent == stopevent
        assert launch.widgets is None
        assert launch.chat is None
        assert launch.loop is None
        assert isinstance(launch.oauth, nowplaying.kick.oauth2.KickOAuth2)
        assert len(launch.tasks) == 0

    def test_init_without_stopevent(self, kick_launch):
        """Test KickLaunch initialization without stopevent."""
        launch = kick_launch
        
        assert isinstance(launch.stopevent, asyncio.Event)

    def test_init_without_config(self):
        """Test KickLaunch initialization without config."""
        launch = nowplaying.kick.launch.KickLaunch()
        
        assert launch.config is None
        assert isinstance(launch.stopevent, asyncio.Event)

    # Parameterized token validation tests
    @pytest.mark.parametrize("status_code,response_data,expected_result", [
        # Success case
        (200, {'data': {'active': True, 'client_id': 'test_client', 'scope': 'user:read chat:write'}}, True),
        # Inactive token
        (200, {'data': {'active': False}}, False),
        # HTTP error codes
        (401, {}, False),
        (403, {}, False),
        (500, {}, False),
    ])
    def test_validate_kick_token_sync_responses(self, kick_launch, status_code, response_data, expected_result):
        """Test token validation with various HTTP responses."""
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = response_data
        
        with patch('requests.post', return_value=mock_response):
            result = kick_launch._validate_kick_token_sync('test_token')
            
            assert result == expected_result

    @pytest.mark.parametrize("token,expected_result", [
        ('', False),
        (None, False),
    ])
    def test_validate_kick_token_sync_invalid_input(self, kick_launch, token, expected_result):
        """Test token validation with invalid inputs."""
        result = kick_launch._validate_kick_token_sync(token)
        assert result == expected_result

    @pytest.mark.parametrize("exception_type,exception_msg", [
        (requests.RequestException, "Network error"),
        (ValueError, "Invalid JSON"),
    ])
    def test_validate_kick_token_sync_exceptions(self, kick_launch, exception_type, exception_msg):
        """Test token validation with various exceptions."""
        if exception_type == ValueError:
            # JSON parsing error
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.side_effect = exception_type(exception_msg)
            
            with patch('requests.post', return_value=mock_response):
                result = kick_launch._validate_kick_token_sync('test_token')
        else:
            # Network error
            with patch('requests.post', side_effect=exception_type(exception_msg)):
                result = kick_launch._validate_kick_token_sync('test_token')
        
        assert not result

    # Parameterized authentication tests
    @pytest.mark.parametrize("stored_tokens,token_validation,refresh_succeeds,expected_result", [
        # No tokens
        ((None, None), None, None, False),
        # Valid token
        (('valid_token', 'refresh_token'), True, None, True),
        # Invalid token, no refresh token
        (('invalid_token', None), False, None, False),
        # Invalid token, refresh succeeds
        (('invalid_token', 'refresh_token'), False, True, True),
        # Invalid token, refresh fails
        (('invalid_token', 'refresh_token'), False, False, False),
    ])
    @pytest.mark.asyncio
    async def test_authenticate_scenarios(self, kick_launch, stored_tokens, token_validation, refresh_succeeds, expected_result):
        """Test authentication with various scenarios."""
        # Setup mocks
        kick_launch.oauth.get_stored_tokens = MagicMock()
        
        if refresh_succeeds is not None:
            # Test refresh scenarios
            kick_launch.oauth.get_stored_tokens.side_effect = [
                stored_tokens,  # First call
                ('new_valid_token', stored_tokens[1]) if refresh_succeeds else stored_tokens  # After refresh
            ]
            kick_launch._validate_kick_token_sync = MagicMock()
            kick_launch._validate_kick_token_sync.side_effect = [False, refresh_succeeds]
            
            if refresh_succeeds:
                kick_launch.oauth.refresh_access_token = AsyncMock()
            else:
                kick_launch.oauth.refresh_access_token = AsyncMock(side_effect=Exception("Refresh failed"))
        else:
            # Simple scenarios
            kick_launch.oauth.get_stored_tokens.return_value = stored_tokens
            if token_validation is not None:
                kick_launch._validate_kick_token_sync = MagicMock(return_value=token_validation)
        
        result = await kick_launch.authenticate()
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_authenticate_exception(self, kick_launch):
        """Test authentication with unexpected exception."""
        kick_launch.oauth.get_stored_tokens = MagicMock(side_effect=Exception("Unexpected error"))
        
        result = await kick_launch.authenticate()
        assert not result

    @pytest.mark.parametrize("auth_result,expected_tasks", [
        (False, 0),  # Authentication fails, no tasks
        (True, 1),   # Authentication succeeds, task created
    ])
    @pytest.mark.asyncio
    async def test_bootstrap_scenarios(self, kick_launch_with_stopevent, auth_result, expected_tasks):
        """Test bootstrap with different authentication results."""
        launch, stopevent = kick_launch_with_stopevent
        
        # Mock authentication
        launch.authenticate = AsyncMock(return_value=auth_result)
        
        if auth_result:
            # Mock chat and loop for success case
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
                    
                    assert len(launch.tasks) == expected_tasks
                    if expected_tasks > 0:
                        assert mock_task in launch.tasks
        else:
            with patch('signal.signal'):
                await launch.bootstrap()
                assert len(launch.tasks) == expected_tasks

    def test_forced_stop(self, kick_launch_with_stopevent):
        """Test forced stop signal handler."""
        launch, stopevent = kick_launch_with_stopevent
        
        assert not stopevent.is_set()
        launch.forced_stop(signal.SIGINT, None)
        assert stopevent.is_set()

    @pytest.mark.parametrize("has_chat,has_loop", [
        (True, True),   # Both chat and loop present
        (False, True),  # No chat, but has loop
        (True, False),  # Has chat, no loop  
        (False, False), # Neither present
    ])
    @pytest.mark.asyncio
    async def test_stop_scenarios(self, kick_launch_with_stopevent, has_chat, has_loop):
        """Test stop functionality with different configurations."""
        launch, stopevent = kick_launch_with_stopevent
        
        # Setup mocks based on parameters
        if has_chat:
            mock_chat = AsyncMock()
            launch.chat = mock_chat
        
        if has_loop:
            mock_loop = MagicMock()
            launch.loop = mock_loop
        
        await launch.stop()
        
        # Verify appropriate methods were called
        if has_chat:
            mock_chat.stop.assert_called_once()
        if has_loop:
            mock_loop.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_watch_for_exit(self, kick_launch_with_stopevent):
        """Test watch for exit functionality."""
        launch, stopevent = kick_launch_with_stopevent
        
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

    @pytest.mark.parametrize("has_running_loop", [True, False])
    def test_start_scenarios(self, kick_launch_with_stopevent, has_running_loop):
        """Test start method with and without existing event loop."""
        launch, stopevent = kick_launch_with_stopevent
        
        # Common mocks
        mock_loop = MagicMock()
        mock_task = MagicMock()
        mock_loop.create_task.return_value = mock_task
        mock_loop.run_forever = MagicMock(side_effect=KeyboardInterrupt)
        
        with patch.object(launch, 'bootstrap', new_callable=AsyncMock):
            with patch.object(launch, '_watch_for_exit', new_callable=AsyncMock):
                if has_running_loop:
                    with patch('asyncio.get_running_loop', return_value=mock_loop):
                        try:
                            launch.start()
                        except KeyboardInterrupt:
                            pass
                else:
                    with patch('asyncio.get_running_loop', side_effect=RuntimeError("No running loop")):
                        with patch('asyncio.new_event_loop', return_value=mock_loop):
                            try:
                                launch.start()
                            except KeyboardInterrupt:
                                pass
                
                # Verify initialization
                assert isinstance(launch.chat, nowplaying.kick.chat.KickChat)
                assert launch.loop == mock_loop


class TestKickLaunchModuleFunctions:
    """Test module-level functions in kick.launch."""

    @pytest.mark.parametrize("testmode,expected_appname", [
        (True, 'testsuite'),
        (False, None),
    ])
    @patch('nowplaying.kick.launch.KickLaunch')
    @patch('nowplaying.frozen.frozen_init')
    @patch('nowplaying.bootstrap.set_qt_names')
    @patch('nowplaying.bootstrap.setuplogging') 
    @patch('nowplaying.config.ConfigFile')
    @patch('threading.current_thread')
    def test_start_function(self, mock_thread, mock_config, mock_logging, 
                           mock_set_names, mock_frozen, mock_kick_launch,
                           testmode, expected_appname):
        """Test module start function with different testmode values."""
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
        if testmode:
            nowplaying.kick.launch.start(
                stopevent=mock_stopevent, 
                bundledir=mock_bundledir, 
                testmode=testmode
            )
        else:
            nowplaying.kick.launch.start(stopevent=mock_stopevent)
        
        # Verify calls
        if expected_appname:
            mock_set_names.assert_called_once_with(appname=expected_appname)
        else:
            mock_set_names.assert_called_once_with()
        
        mock_launch_instance.start.assert_called_once()

    @pytest.mark.parametrize("exception_raised", [True, False])
    @pytest.mark.asyncio
    async def test_launch_kickbot_function(self, bootstrap, exception_raised):
        """Test launch_kickbot async function with and without exceptions."""
        stopevent = asyncio.Event()
        
        with patch('nowplaying.kick.launch.KickLaunch') as mock_kick_launch:
            mock_launch_instance = MagicMock()
            
            if exception_raised:
                mock_launch_instance.bootstrap = AsyncMock(side_effect=Exception("Test error"))
            else:
                mock_launch_instance.bootstrap = AsyncMock()
            
            mock_kick_launch.return_value = mock_launch_instance
            
            # Should not raise exception in either case
            await nowplaying.kick.launch.launch_kickbot(config=bootstrap, stopevent=stopevent)
            
            mock_kick_launch.assert_called_once_with(config=bootstrap, stopevent=stopevent)
            mock_launch_instance.bootstrap.assert_called_once()