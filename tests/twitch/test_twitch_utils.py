#!/usr/bin/env python3
"""Unit tests for Twitch utils functionality."""

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aioresponses import aioresponses

import nowplaying.twitch.oauth2
import nowplaying.twitch.utils


# Token validation tests
def test_validate_token_sync_with_username_valid():
    """Test token validation with username return for valid token."""
    with patch("requests.get") as mock_get:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"login": "test_user", "client_id": "test_client"}
        mock_get.return_value = mock_response

        result = nowplaying.twitch.oauth2.TwitchOAuth2.validate_token_sync(
            "valid_token", return_username=True
        )
        assert result == "test_user"


def test_validate_token_sync_with_username_invalid():
    """Test token validation with username return for invalid token."""
    with patch("requests.get") as mock_get:
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        result = nowplaying.twitch.oauth2.TwitchOAuth2.validate_token_sync(
            "invalid_token", return_username=True
        )
        assert result is None


def test_validate_token_sync_with_username_network_error():
    """Test token validation with username return for network error."""
    with patch("requests.get") as mock_get:
        mock_get.side_effect = Exception("Network error")

        result = nowplaying.twitch.oauth2.TwitchOAuth2.validate_token_sync(
            "token", return_username=True
        )
        assert result is None


def test_validate_token_sync_boolean_valid():
    """Test token validation with boolean return for valid token."""
    with patch("requests.get") as mock_get:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "client_id": "test_client",
            "login": "test_user",
            "scopes": ["chat:read", "chat:edit"],
        }
        mock_get.return_value = mock_response

        result = nowplaying.twitch.oauth2.TwitchOAuth2.validate_token_sync(
            "valid_oauth_token", return_username=False
        )
        assert result is True


def test_validate_token_sync_boolean_invalid():
    """Test token validation with boolean return for invalid token."""
    with patch("requests.get") as mock_get:
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        result = nowplaying.twitch.oauth2.TwitchOAuth2.validate_token_sync(
            "invalid_token", return_username=False
        )
        assert result is False


def test_validate_token_sync_boolean_missing_fields():
    """Test token validation with boolean return for missing required fields."""
    with patch("requests.get") as mock_get:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "client_id": "test_client"
            # Missing 'login' field
        }
        mock_get.return_value = mock_response

        result = nowplaying.twitch.oauth2.TwitchOAuth2.validate_token_sync(
            "token", return_username=False
        )
        assert result is False


def test_validate_token_sync_boolean_network_error():
    """Test token validation with boolean return for network error."""
    with patch("requests.get") as mock_get:
        mock_get.side_effect = Exception("Network error")

        result = nowplaying.twitch.oauth2.TwitchOAuth2.validate_token_sync(
            "token", return_username=False
        )
        assert result is False


def test_validate_token_sync_boolean_empty():
    """Test token validation with boolean return for empty token."""
    result = nowplaying.twitch.oauth2.TwitchOAuth2.validate_token_sync("", return_username=False)
    assert result is False

    result = nowplaying.twitch.oauth2.TwitchOAuth2.validate_token_sync(None, return_username=False)
    assert result is False


def test_validate_token_sync_boolean_malformed_json():
    """Test token validation with boolean return for malformed JSON response."""
    with patch("requests.get") as mock_get:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "doc", 0)
        mock_get.return_value = mock_response

        result = nowplaying.twitch.oauth2.TwitchOAuth2.validate_token_sync(
            "token", return_username=False
        )
        assert result is False


@pytest.mark.asyncio
async def test_async_validate_token_success():
    """Test async token validation success."""
    mock_oauth = Mock()
    mock_oauth.validate_token_async = AsyncMock(return_value={"login": "test_user"})

    result = await nowplaying.twitch.utils.async_validate_token(mock_oauth, "token")
    assert result == "test_user"


@pytest.mark.asyncio
async def test_async_validate_token_failure():
    """Test async token validation failure."""
    mock_oauth = Mock()
    mock_oauth.validate_token = AsyncMock(return_value=None)

    result = await nowplaying.twitch.utils.async_validate_token(mock_oauth, "token")
    assert result is None


@pytest.mark.asyncio
async def test_async_validate_token_exception():
    """Test async token validation with exception."""
    mock_oauth = Mock()
    mock_oauth.validate_token = AsyncMock(side_effect=Exception("Validation error"))

    result = await nowplaying.twitch.utils.async_validate_token(mock_oauth, "token")
    assert result is None


# TwitchLogin tests
def test_twitch_login_init(bootstrap):
    """Test TwitchLogin initialization."""
    login = nowplaying.twitch.utils.TwitchLogin(bootstrap)
    assert login.config == bootstrap


@pytest.mark.asyncio
async def test_get_oauth_client(bootstrap):
    """Test OAuth client creation."""
    login = nowplaying.twitch.utils.TwitchLogin(bootstrap)

    client = await login.get_oauth_client()
    assert client is not None
    assert isinstance(client, nowplaying.twitch.oauth2.TwitchOAuth2)


@pytest.mark.asyncio
async def test_attempt_token_refresh_success(bootstrap):
    """Test successful token refresh."""
    bootstrap.cparser.setValue("twitchbot/accesstoken", "test_token")
    bootstrap.cparser.setValue("twitchbot/refreshtoken", "test_refresh")

    login = nowplaying.twitch.utils.TwitchLogin(bootstrap)

    # Mock the OAuth client
    with patch.object(login, "get_oauth_client") as mock_get_client:
        mock_oauth = Mock()
        mock_oauth.get_stored_tokens.return_value = ("test_token", "test_refresh")
        mock_oauth.validate_token_async = AsyncMock(return_value={"login": "test_user"})
        mock_get_client.return_value = mock_oauth

        result = await login.attempt_token_refresh()
        assert result is True
        assert mock_oauth.access_token == "test_token"
        assert mock_oauth.refresh_token == "test_refresh"


@pytest.mark.asyncio
async def test_attempt_token_refresh_invalid_token(bootstrap):
    """Test token refresh with invalid token."""
    bootstrap.cparser.setValue("twitchbot/accesstoken", "invalid_token")
    bootstrap.cparser.setValue("twitchbot/refreshtoken", "test_refresh")

    login = nowplaying.twitch.utils.TwitchLogin(bootstrap)

    with patch.object(login, "get_oauth_client") as mock_get_client:
        mock_oauth = Mock()
        mock_oauth.get_stored_tokens.return_value = ("invalid_token", "test_refresh")
        mock_oauth.validate_token_async = AsyncMock(return_value=None)  # Invalid token
        mock_oauth.refresh_access_token_async = AsyncMock(
            return_value={"access_token": "new_token"}
        )
        mock_get_client.return_value = mock_oauth

        result = await login.attempt_token_refresh()
        assert result is True
        mock_oauth.refresh_access_token_async.assert_called_once_with("test_refresh")


@pytest.mark.asyncio
async def test_attempt_token_refresh_no_tokens(bootstrap):
    """Test token refresh with no stored tokens."""
    login = nowplaying.twitch.utils.TwitchLogin(bootstrap)

    with patch.object(login, "get_oauth_client") as mock_get_client:
        mock_oauth = Mock()
        mock_oauth.get_stored_tokens.return_value = (None, None)
        mock_get_client.return_value = mock_oauth

        result = await login.attempt_token_refresh()
        assert result is False


@pytest.mark.asyncio
async def test_initiate_oauth_flow_success(bootstrap):
    """Test OAuth flow initiation success."""
    bootstrap.cparser.setValue("twitchbot/clientid", "test_client")
    bootstrap.cparser.setValue("twitchbot/secret", "test_secret")
    bootstrap.cparser.setValue("webserver/port", 8899)

    login = nowplaying.twitch.utils.TwitchLogin(bootstrap)

    with patch.object(login, "get_oauth_client") as mock_get_client:
        mock_oauth = Mock()
        mock_oauth.client_id = "test_client"
        mock_oauth.client_secret = "test_secret"  # pragma: allowlist secret
        mock_oauth.redirect_uri = None
        mock_oauth.open_browser_for_auth.return_value = True
        mock_get_client.return_value = mock_oauth

        result = await login.initiate_oauth_flow()
        assert result is True
        assert mock_oauth.redirect_uri == "http://localhost:8899/twitchredirect"


@pytest.mark.asyncio
async def test_initiate_oauth_flow_missing_config(bootstrap):
    """Test OAuth flow initiation with missing config."""
    login = nowplaying.twitch.utils.TwitchLogin(bootstrap)

    with patch.object(login, "get_oauth_client") as mock_get_client:
        mock_oauth = Mock()
        mock_oauth.client_id = None  # Missing
        mock_oauth.client_secret = "test_secret"  # pragma: allowlist secret
        mock_get_client.return_value = mock_oauth

        result = await login.initiate_oauth_flow()
        assert result is False


@pytest.mark.asyncio
async def test_api_login_with_valid_tokens(bootstrap):
    """Test API login with valid tokens."""
    login = nowplaying.twitch.utils.TwitchLogin(bootstrap)

    # Set up mock OAuth client like other tests
    mock_oauth = Mock()
    mock_oauth.client_id = "test_client_id"
    mock_oauth.client_secret = "test_client_secret"  # pragma: allowlist secret
    mock_oauth.access_token = "test_access_token"
    mock_oauth.refresh_token = "test_refresh_token"
    nowplaying.twitch.utils.TwitchLogin.OAUTH_CLIENT = mock_oauth

    with (
        patch.object(login, "attempt_token_refresh", return_value=True),
        patch("twitchAPI.twitch.Twitch") as mock_twitch_class,
    ):
        mock_twitch = AsyncMock()
        mock_twitch_class.return_value = mock_twitch

        result = await login.api_login()
        assert result is not None


@pytest.mark.asyncio
async def test_api_login_no_valid_tokens(bootstrap):
    """Test API login with no valid tokens."""
    login = nowplaying.twitch.utils.TwitchLogin(bootstrap)

    with patch.object(login, "attempt_token_refresh", return_value=False):
        result = await login.api_login()
        assert result is None


@pytest.mark.asyncio
async def test_api_logout(bootstrap):
    """Test API logout."""
    login = nowplaying.twitch.utils.TwitchLogin(bootstrap)

    # Set up a mock client
    mock_oauth = Mock()
    mock_oauth.revoke_token = AsyncMock()
    nowplaying.twitch.utils.TwitchLogin.OAUTH_CLIENT = mock_oauth

    await login.api_logout()

    mock_oauth.revoke_token.assert_called_once()
    assert nowplaying.twitch.utils.TwitchLogin.OAUTH_CLIENT is None


@pytest.mark.asyncio
async def test_cache_token_del(bootstrap):
    """Test cache token deletion."""
    bootstrap.cparser.setValue("twitchbot/oldusertoken", "old_token")
    bootstrap.cparser.setValue("twitchbot/oldrefreshtoken", "old_refresh")
    bootstrap.cparser.setValue("twitchbot/accesstoken", "access_token")
    bootstrap.cparser.setValue("twitchbot/refreshtoken", "refresh_token")

    login = nowplaying.twitch.utils.TwitchLogin(bootstrap)

    with patch.object(login, "api_logout") as mock_logout:
        mock_oauth = Mock()
        nowplaying.twitch.utils.TwitchLogin.OAUTH_CLIENT = mock_oauth

        await login.cache_token_del()

        mock_logout.assert_called_once()
        mock_oauth.clear_stored_tokens.assert_called_once()

        # Verify all tokens were removed
        assert bootstrap.cparser.value("twitchbot/oldusertoken") is None
        assert bootstrap.cparser.value("twitchbot/oldrefreshtoken") is None
        assert bootstrap.cparser.value("twitchbot/accesstoken") is None
        assert bootstrap.cparser.value("twitchbot/refreshtoken") is None


# User image retrieval tests using aioresponses
@pytest.mark.asyncio
async def test_get_user_image_success():
    """Test successful user image retrieval."""
    mock_oauth = Mock()
    mock_oauth.access_token = "test_token"
    mock_oauth.client_id = "test_client"
    mock_oauth.api_host = "https://api.twitch.tv/helix"

    with aioresponses() as mock_resp:
        # Mock user data response
        mock_resp.get(
            "https://api.twitch.tv/helix/users?login=test_user",
            payload={"data": [{"profile_image_url": "https://example.com/image.png"}]},
        )

        # Mock image response
        mock_resp.get("https://example.com/image.png", body=b"fake_image_data")

        with patch("nowplaying.utils.image2png", return_value=b"png_data") as mock_image2png:
            result = await nowplaying.twitch.utils.get_user_image(mock_oauth, "test_user")

            assert result == b"png_data"
            mock_image2png.assert_called_once_with(b"fake_image_data")


@pytest.mark.asyncio
async def test_get_user_image_no_user():
    """Test user image retrieval with no user found."""
    mock_oauth = Mock()
    mock_oauth.access_token = "test_token"
    mock_oauth.client_id = "test_client"
    mock_oauth.api_host = "https://api.twitch.tv/helix"

    with aioresponses() as mock_resp:
        mock_resp.get(
            "https://api.twitch.tv/helix/users?login=nonexistent_user",
            payload={"data": []},  # No user found
        )

        result = await nowplaying.twitch.utils.get_user_image(mock_oauth, "nonexistent_user")
        assert result is None


@pytest.mark.asyncio
async def test_get_user_image_error():
    """Test user image retrieval with error."""
    mock_oauth = Mock()
    mock_oauth.access_token = "test_token"
    mock_oauth.client_id = "test_client"
    mock_oauth.api_host = "https://api.twitch.tv/helix"

    with aioresponses() as mock_resp:
        mock_resp.get(
            "https://api.twitch.tv/helix/users?login=test_user",
            exception=Exception("Network error"),
        )

        result = await nowplaying.twitch.utils.get_user_image(mock_oauth, "test_user")
        assert result is None
