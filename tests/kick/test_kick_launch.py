#!/usr/bin/env python3
"""Unit tests for Kick launch functionality - REFACTORED VERSION."""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests


import nowplaying.kick.oauth2  # pylint: disable=import-error,no-name-in-module,no-member
import nowplaying.kick.launch  # pylint: disable=import-error,no-name-in-module,no-member
import nowplaying.kick.utils  # pylint: disable=import-error,no-name-in-module,no-member

# Fixtures
@pytest.fixture
def kick_launch(bootstrap):
    """Create a KickLaunch instance with bootstrap config."""
    return nowplaying.kick.launch.KickLaunch(config=bootstrap) # pylint: disable=no-member


@pytest.fixture
def kick_launch_with_stopevent(bootstrap):
    """Create a KickLaunch instance with bootstrap config and stopevent."""
    stopevent = asyncio.Event()
    launch = nowplaying.kick.launch.KickLaunch(config=bootstrap, stopevent=stopevent) # pylint: disable=no-member
    return launch, stopevent


def test_init_with_config(bootstrap):
    """Test KickLaunch initialization with config."""
    stopevent = asyncio.Event()

    launch = nowplaying.kick.launch.KickLaunch(config=bootstrap, stopevent=stopevent) # pylint: disable=no-member

    assert launch.config == bootstrap
    assert launch.stopevent == stopevent
    assert launch.widgets is None
    assert launch.chat is None
    assert launch.loop is None
    assert isinstance(launch.oauth, nowplaying.kick.oauth2.KickOAuth2) # pylint: disable=no-member
    assert len(launch.tasks) == 0


def test_init_without_stopevent(kick_launch):  # pylint: disable=redefined-outer-name
    """Test KickLaunch initialization without stopevent."""
    launch = kick_launch

    assert isinstance(launch.stopevent, asyncio.Event)


def test_init_without_config():
    """Test KickLaunch initialization without config."""
    launch = nowplaying.kick.launch.KickLaunch() # pylint: disable=no-member

    assert launch.config is None
    assert isinstance(launch.stopevent, asyncio.Event)


# Parameterized token validation tests
@pytest.mark.parametrize(
    "status_code,response_data,expected_result",
    [
        # Success case
        (200, {
            'data': {
                'active': True,
                'client_id': 'test_client',
                'scope': 'user:read chat:write'
            }
        }, True),
        # Inactive token
        (200, {
            'data': {
                'active': False
            }
        }, False),
        # HTTP error codes
        (401, {}, False),
        (403, {}, False),
        (500, {}, False),
    ])
def test_validate_kick_token_sync_responses(kick_launch, status_code, response_data, # pylint: disable=redefined-outer-name,unused-argument
                                            expected_result):
    """Test token validation with various HTTP responses."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = response_data

    with patch('requests.post', return_value=mock_response):
        result = nowplaying.kick.utils.qtsafe_validate_kick_token('test_token')  # pylint: disable=no-member

        assert result == expected_result


@pytest.mark.parametrize("token,expected_result", [
    ('', False),
    (None, False),
])
def test_validate_kick_token_sync_invalid_input(kick_launch, token, expected_result): # pylint: disable=redefined-outer-name,unused-argument
    """Test token validation with invalid inputs."""
    result = nowplaying.kick.utils.qtsafe_validate_kick_token(token)  # pylint: disable=no-member
    assert result == expected_result


@pytest.mark.parametrize("exception_type,exception_msg", [
    (requests.RequestException, "Network error"),
    (ValueError, "Invalid JSON"),
])
def test_validate_kick_token_sync_exceptions(kick_launch, exception_type, exception_msg): # pylint: disable=redefined-outer-name,unused-argument
    """Test token validation with various exceptions."""
    if exception_type == ValueError:
        # JSON parsing error
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = exception_type(exception_msg)

        with patch('requests.post', return_value=mock_response):
            result = nowplaying.kick.utils.qtsafe_validate_kick_token('test_token')  # pylint: disable=no-member
    else:
        # Network error
        with patch('requests.post', side_effect=exception_type(exception_msg)):
            result = nowplaying.kick.utils.qtsafe_validate_kick_token('test_token')  # pylint: disable=no-member

    assert not result


# Parameterized authentication tests
@pytest.mark.parametrize(
    "stored_tokens,token_validation,refresh_succeeds,expected_result",
    [
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
async def test_authenticate_scenarios(kick_launch, stored_tokens, token_validation, # pylint: disable=redefined-outer-name
                                      refresh_succeeds, expected_result):
    """Test authentication with various scenarios."""
    # Setup mocks
    kick_launch.oauth.get_stored_tokens = MagicMock()

    if refresh_succeeds is not None:
        # Test refresh scenarios
        kick_launch.oauth.get_stored_tokens.side_effect = [
            stored_tokens,  # First call
            ('new_valid_token',
             stored_tokens[1]) if refresh_succeeds else stored_tokens  # After refresh
        ]
        with patch('nowplaying.kick.utils.qtsafe_validate_kick_token') as mock_validate:
            mock_validate.side_effect = [False, refresh_succeeds]

            if refresh_succeeds:
                kick_launch.oauth.refresh_access_token = AsyncMock()
            else:
                kick_launch.oauth.refresh_access_token = AsyncMock(
                    side_effect=Exception("Refresh failed"))

            result = await kick_launch.authenticate()
            assert result == expected_result
    else:
        # Simple scenarios
        kick_launch.oauth.get_stored_tokens.return_value = stored_tokens
        with patch('nowplaying.kick.utils.qtsafe_validate_kick_token') as mock_validate:
            if token_validation is not None:
                mock_validate.return_value = token_validation

            result = await kick_launch.authenticate()
            assert result == expected_result


@pytest.mark.asyncio
async def test_authenticate_exception(kick_launch): # pylint: disable=redefined-outer-name
    """Test authentication with unexpected exception."""
    kick_launch.oauth.get_stored_tokens = MagicMock(side_effect=Exception("Unexpected error"))

    result = await kick_launch.authenticate()
    assert not result


def test_forced_stop(kick_launch_with_stopevent): # pylint: disable=redefined-outer-name
    """Test forced stop signal handler."""
    launch, stopevent = kick_launch_with_stopevent

    assert not stopevent.is_set()
    launch.forced_stop(signal.SIGINT, None)
    assert stopevent.is_set()


@pytest.mark.parametrize(
    "has_chat,has_loop",
    [
        (True, True),  # Both chat and loop present
        (False, True),  # No chat, but has loop
        (True, False),  # Has chat, no loop
        (False, False),  # Neither present
    ])
@pytest.mark.asyncio
async def test_stop_scenarios(kick_launch_with_stopevent, has_chat, has_loop): # pylint: disable=redefined-outer-name
    """Test stop functionality with different configurations."""
    launch, _ = kick_launch_with_stopevent  # stopevent not used in this test

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
async def test_watch_for_exit(kick_launch_with_stopevent): # pylint: disable=redefined-outer-name
    """Test watch for exit functionality."""
    launch, stopevent = kick_launch_with_stopevent

    # Mock stop method
    launch.stop = AsyncMock()

    # Set stop event after short delay
    async def set_stop_event():
        await asyncio.sleep(0.01)
        stopevent.set()

    # Run both tasks
    await asyncio.gather(launch._watch_for_exit(), set_stop_event())  # pylint: disable=protected-access

    # Verify stop was called
    launch.stop.assert_called_once()


# Module-level function tests
@pytest.mark.parametrize("testmode,expected_appname", [
    (True, 'testsuite'),
    (False, None),
])
@patch('nowplaying.kick.launch.KickLaunch')
@patch('nowplaying.frozen.frozen_init')
@patch('nowplaying.bootstrap.set_qt_names')
@patch('nowplaying.bootstrap.setuplogging')
@patch('nowplaying.config.ConfigFile')
def test_start_function(mock_config, mock_logging, mock_set_names, mock_frozen,  # pylint: disable=too-many-arguments
                        mock_kick_launch, testmode, expected_appname):
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
        nowplaying.kick.launch.start(stopevent=mock_stopevent, # pylint: disable=no-member
                                     bundledir=mock_bundledir,
                                     testmode=testmode)
    else:
        nowplaying.kick.launch.start(stopevent=mock_stopevent) # pylint: disable=no-member

    # Verify calls
    if expected_appname:
        mock_set_names.assert_called_once_with(appname=expected_appname)
    else:
        mock_set_names.assert_called_once_with()

    mock_launch_instance.start.assert_called_once()


@pytest.mark.parametrize("exception_raised", [True, False])
@pytest.mark.asyncio
async def test_launch_kickbot_function(bootstrap, exception_raised): # pylint: disable=redefined-outer-name
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
        await nowplaying.kick.launch.launch_kickbot(config=bootstrap, stopevent=stopevent) # pylint: disable=no-member

        mock_kick_launch.assert_called_once_with(config=bootstrap, stopevent=stopevent)
        mock_launch_instance.bootstrap.assert_called_once()
