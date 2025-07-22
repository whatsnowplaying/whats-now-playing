#!/usr/bin/env python3
"""Unit tests for Twitch OAuth2 functionality - following Kick OAuth2 test pattern."""

import asyncio
import base64
import hashlib
from unittest.mock import patch

import pytest
from aioresponses import aioresponses

import nowplaying.twitch.oauth2  # pylint: disable=import-error,no-name-in-module
from nowplaying.twitch.constants import API_HOST, OAUTH_HOST

# pylint: disable=redefined-outer-name, too-many-arguments, unused-argument


# Fixtures
@pytest.fixture
def configured_oauth(bootstrap):  # pylint: disable=redefined-outer-name
    """Create OAuth2 instance with test configuration."""
    config = bootstrap
    config.cparser.setValue("twitchbot/clientid", "test_client_id")
    config.cparser.setValue("twitchbot/secret", "test_secret")
    # Redirect URI is no longer stored in config - it's set dynamically by callers
    oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config)  # pylint: disable=no-member
    # Set redirect_uri directly on the OAuth object for tests that need it
    oauth.redirect_uri = "http://localhost:8899/twitchredirect"
    return oauth


@pytest.fixture
def oauth_with_pkce(configured_oauth):  # pylint: disable=redefined-outer-name
    """Create OAuth2 instance with PKCE parameters generated."""
    oauth = configured_oauth
    oauth._generate_pkce_parameters()  # pylint: disable=protected-access
    return oauth


@pytest.fixture
def mock_responses():
    """Fixture that provides aioresponses for mocking HTTP calls."""
    with aioresponses() as mock:
        yield mock


# Basic OAuth2 functionality tests
def test_init_basic(bootstrap):  # pylint: disable=redefined-outer-name
    """Test basic OAuth2 initialization without preset redirect URI."""
    config = bootstrap
    config.cparser.setValue("twitchbot/clientid", "test_client_id")
    config.cparser.setValue("twitchbot/secret", "test_secret")

    oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config)  # pylint: disable=no-member

    assert oauth.client_id == "test_client_id"
    assert oauth.client_secret == "test_secret"  # pragma: allowlist secret
    # Redirect URI is dynamically set by calling code, not stored in config
    assert oauth.redirect_uri is None
    assert oauth.code_verifier is None
    assert oauth.code_challenge is None
    assert oauth.state is None


def test_init_with_config(configured_oauth):  # pylint: disable=redefined-outer-name
    """Test OAuth2 initialization with config and test fixture setup."""
    oauth = configured_oauth

    assert oauth.client_id == "test_client_id"
    assert oauth.client_secret == "test_secret"  # pragma: allowlist secret
    # Redirect URI is set by the fixture for tests that need it
    assert oauth.redirect_uri == "http://localhost:8899/twitchredirect"
    assert oauth.code_verifier is None
    assert oauth.code_challenge is None
    assert oauth.state is None


def test_init_without_config():
    """Test OAuth2 initialization without config."""
    oauth = nowplaying.twitch.oauth2.TwitchOAuth2()  # pylint: disable=no-member

    assert oauth.config is not None
    assert hasattr(oauth.config, "cparser")  # Check it's a config-like object
    # Redirect URI should be None when no config is provided
    assert oauth.redirect_uri is None


def test_generate_pkce_parameters(configured_oauth):  # pylint: disable=redefined-outer-name
    """Test PKCE parameter generation."""
    oauth = configured_oauth

    oauth._generate_pkce_parameters()  # pylint: disable=protected-access

    # Verify code verifier is generated
    assert oauth.code_verifier is not None
    assert len(oauth.code_verifier) >= 43
    assert len(oauth.code_verifier) <= 128

    # Verify code challenge is generated correctly
    assert oauth.code_challenge is not None
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(oauth.code_verifier.encode("utf-8")).digest())
        .decode("utf-8")
        .rstrip("=")
    )
    assert oauth.code_challenge == expected_challenge

    # Verify state is generated
    assert oauth.state is not None
    assert len(oauth.state) >= 43


# Parameterized authorization URL tests
@pytest.mark.parametrize(
    "client_id,redirect_uri,expected_error",
    [
        (None, "http://localhost:8899", "Client ID is required"),
        ("", "http://localhost:8899", "Client ID is required"),  # Empty string
        ("   ", "http://localhost:8899", "Client ID is required"),  # Whitespace only
        (
            "client with spaces",
            "http://localhost:8899",
            "Client ID contains invalid characters",
        ),  # Spaces
        (
            "client@invalid",
            "http://localhost:8899",
            "Client ID contains invalid characters",
        ),  # Special chars
        (
            "client\nwith\nnewlines",
            "http://localhost:8899",
            "Client ID contains invalid characters",
        ),  # Newlines
        (
            "client\twith\ttabs",
            "http://localhost:8899",
            "Client ID contains invalid characters",
        ),  # Tabs
        (
            "client#with$symbols%",
            "http://localhost:8899",
            "Client ID contains invalid characters",
        ),  # Various symbols
        ("test_client", None, "Redirect URI is required"),
        ("test_client", "http://localhost:8899", None),  # Success
        ("  valid_client  ", "http://localhost:8899", None),  # Success with trimming
    ],
)
def test_get_authorization_url_scenarios(  # pylint: disable=redefined-outer-name
    bootstrap, client_id, redirect_uri, expected_error
):
    """Test authorization URL generation with various configurations."""
    config = bootstrap
    if client_id:
        config.cparser.setValue("twitchbot/clientid", client_id)

    oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config)  # pylint: disable=no-member

    # Set redirect_uri directly on the object (no longer stored in config)
    if redirect_uri:
        oauth.redirect_uri = redirect_uri

    if expected_error:
        with pytest.raises(ValueError, match=expected_error):
            oauth.get_authorization_url()
    else:
        auth_url = oauth.get_authorization_url()

        assert auth_url.startswith("https://id.twitch.tv/oauth2/authorize?")
        # Use trimmed client_id for URL validation since validation normalizes it
        expected_client_id = client_id.strip() if client_id else client_id
        assert f"client_id={expected_client_id}" in auth_url
        assert "response_type=code" in auth_url
        encoded_uri = redirect_uri.replace(":", "%3A").replace("/", "%2F")
        assert f"redirect_uri={encoded_uri}" in auth_url
        assert "scope=chat%3Aread+chat%3Aedit" in auth_url
        assert "code_challenge_method=S256" in auth_url
        assert "force_verify=false" in auth_url
        assert oauth.code_verifier is not None
        assert oauth.state is not None


# Parameterized browser opening tests
@pytest.mark.parametrize("browser_succeeds", [True, False])
@patch("webbrowser.open")
def test_open_browser_for_auth_scenarios(mock_open, configured_oauth, browser_succeeds):  # pylint: disable=redefined-outer-name
    """Test browser opening with success and failure scenarios."""
    oauth = configured_oauth

    if not browser_succeeds:
        mock_open.side_effect = OSError("Browser error")

    result = oauth.open_browser_for_auth()

    assert result == browser_succeeds
    mock_open.assert_called_once()


# Parameterized token exchange tests
@pytest.mark.parametrize(
    "has_verifier,state_matches,response_status,response_data,should_succeed",
    [
        (False, True, 200, {"access_token": "token"}, False),  # No verifier
        (True, False, 200, {"access_token": "token"}, False),  # State mismatch
        (True, True, 400, {}, False),  # HTTP error
        (True, True, 200, {"access_token": "token", "refresh_token": "refresh"}, True),  # Success
    ],
)
@pytest.mark.asyncio
async def test_exchange_code_for_token_scenarios(  # pylint: disable=redefined-outer-name
    configured_oauth,
    mock_responses,
    has_verifier,
    state_matches,
    response_status,
    response_data,
    should_succeed,
):
    """Test token exchange with various scenarios."""
    oauth = configured_oauth

    if has_verifier:
        oauth.code_verifier = "test_verifier"
        oauth.state = "expected_state"

    test_state = "expected_state" if state_matches else "wrong_state"

    if should_succeed:
        # Success case - setup mock and verify result
        mock_responses.post(
            f"{OAUTH_HOST}/oauth2/token", status=response_status, payload=response_data
        )

        result = await oauth.exchange_code_for_token("test_code", test_state)
        assert result == response_data
        assert oauth.access_token == "token"
        assert oauth.refresh_token == "refresh"

    elif response_status != 200:
        # HTTP error case
        mock_responses.post(f"{OAUTH_HOST}/oauth2/token", status=response_status, body="Error")

        with pytest.raises(Exception):
            await oauth.exchange_code_for_token("test_code", test_state)

    else:
        # ValueError cases (no verifier, state mismatch) - no HTTP mock needed
        with pytest.raises(ValueError):
            await oauth.exchange_code_for_token("test_code", test_state)


# Parameterized refresh token tests
@pytest.mark.parametrize(
    "has_refresh_token,response_status,response_data,should_succeed",
    [
        (False, 200, {"access_token": "new_token"}, False),  # No refresh token
        (True, 400, {}, False),  # HTTP error
        (
            True,
            200,
            {"access_token": "new_token", "refresh_token": "new_refresh"},
            True,
        ),  # Success
    ],
)
@pytest.mark.asyncio
async def test_refresh_access_token_scenarios(
    bootstrap,
    configured_oauth,
    mock_responses,
    has_refresh_token,
    response_status,
    response_data,
    should_succeed,
):
    """Test token refresh with various scenarios."""
    oauth = configured_oauth

    if has_refresh_token:
        oauth.config.cparser.setValue("twitchbot/refreshtoken", "test_refresh_token")
        refresh_token = "test_refresh_token"
    else:
        refresh_token = None

    if should_succeed:
        mock_responses.post(
            f"{OAUTH_HOST}/oauth2/token", status=response_status, payload=response_data
        )

        result = await oauth.refresh_access_token_async(refresh_token)
        assert result == response_data
        assert oauth.access_token == "new_token"
        assert oauth.refresh_token == "new_refresh"
    else:
        if has_refresh_token:
            # HTTP error case
            mock_responses.post(f"{OAUTH_HOST}/oauth2/token", status=response_status, body="Error")

        with pytest.raises((ValueError, Exception)):
            await oauth.refresh_access_token_async(refresh_token)


# Parameterized token validation tests
@pytest.mark.parametrize(
    "response_status,response_data,expected_result",
    [
        (
            200,
            {"client_id": "test_client", "login": "test_user"},
            {"client_id": "test_client", "login": "test_user"},
        ),
        (401, {}, None),  # Unauthorized
        (500, {}, None),  # Server error
    ],
)
@pytest.mark.asyncio
async def test_validate_token_scenarios(
    configured_oauth,
    mock_responses,
    response_status,  # pylint: disable=redefined-outer-name
    response_data,
    expected_result,
):
    """Test token validation with various responses."""
    oauth = configured_oauth

    if response_status == 200:
        mock_responses.get(
            f"{OAUTH_HOST}/oauth2/validate", status=response_status, payload=response_data
        )
    else:
        mock_responses.get(f"{OAUTH_HOST}/oauth2/validate", status=response_status, body="Error")

    result = await oauth.validate_token_async("test_token")
    assert result == expected_result


# Test user info endpoint (Twitch-specific)
@pytest.mark.parametrize(
    "response_status,response_data,expected_result",
    [
        (
            200,
            {"data": [{"id": "12345", "login": "test_user", "display_name": "TestUser"}]},
            {"id": "12345", "login": "test_user", "display_name": "TestUser"},
        ),
        (401, {}, None),  # Unauthorized
        (200, {"data": []}, None),  # No user data
    ],
)
@pytest.mark.asyncio
async def test_get_user_info_scenarios(
    configured_oauth, mock_responses, response_status, response_data, expected_result
):
    """Test user info retrieval with various responses."""
    oauth = configured_oauth

    if response_status == 200:
        mock_responses.get(f"{API_HOST}/users", status=response_status, payload=response_data)
    else:
        mock_responses.get(f"{API_HOST}/users", status=response_status, body="Error")

    result = await oauth.get_user_info_async("test_token")
    assert result == expected_result


# Parameterized stored tokens tests
@pytest.mark.parametrize(
    "access_token,refresh_token",
    [
        ("stored_access", "stored_refresh"),  # Both tokens present
        (None, None),  # No tokens stored
        ("access_only", None),  # Only access token
        (None, "refresh_only"),  # Only refresh token
    ],
)
def test_get_stored_tokens_scenarios(bootstrap, access_token, refresh_token):  # pylint: disable=redefined-outer-name
    """Test getting stored tokens with various configurations."""
    config = bootstrap
    if access_token:
        config.cparser.setValue("twitchbot/accesstoken", access_token)
    if refresh_token:
        config.cparser.setValue("twitchbot/refreshtoken", refresh_token)

    oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config)  # pylint: disable=no-member
    result_access, result_refresh = oauth.get_stored_tokens()

    assert result_access == access_token
    assert result_refresh == refresh_token


def test_clear_stored_tokens(configured_oauth):  # pylint: disable=redefined-outer-name
    """Test clearing stored tokens."""
    oauth = configured_oauth
    oauth.config.cparser.setValue("twitchbot/accesstoken", "stored_access")
    oauth.config.cparser.setValue("twitchbot/refreshtoken", "stored_refresh")
    oauth.access_token = "current_access"
    oauth.refresh_token = "current_refresh"

    oauth.clear_stored_tokens()

    assert oauth.access_token is None
    assert oauth.refresh_token is None
    assert oauth.config.cparser.value("twitchbot/accesstoken") is None
    assert oauth.config.cparser.value("twitchbot/refreshtoken") is None


# Parameterized token revocation tests
@pytest.mark.parametrize(
    "has_client_id,has_token,response_status,should_clear_tokens",
    [
        (False, False, 200, False),  # No client ID or token - should not crash
        (True, True, 200, True),  # Success - should clear tokens
        (True, True, 400, False),  # HTTP error - should NOT clear tokens
    ],
)
@pytest.mark.asyncio
async def test_revoke_token_scenarios(  # pylint: disable=redefined-outer-name, too-many-arguments
    bootstrap, mock_responses, has_client_id, has_token, response_status, should_clear_tokens
):
    """Test token revocation with various scenarios."""
    config = bootstrap
    if has_client_id:
        config.cparser.setValue("twitchbot/clientid", "test_client_id")
    if has_token:
        config.cparser.setValue("twitchbot/accesstoken", "test_token")

    oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config)  # pylint: disable=no-member

    token_to_revoke = "test_token" if has_token else None

    if has_client_id and has_token:
        # Setup mock response for cases where we have credentials
        mock_responses.post(f"{OAUTH_HOST}/oauth2/revoke", status=response_status)

    # Should not raise exception in any case
    await oauth.revoke_token(token_to_revoke)

    if should_clear_tokens:
        assert oauth.access_token is None
        assert oauth.refresh_token is None
        assert oauth.config.cparser.value("twitchbot/accesstoken") is None
        assert oauth.config.cparser.value("twitchbot/refreshtoken") is None
    else:
        # For error cases, tokens should remain if they were set
        if has_token:
            assert oauth.config.cparser.value("twitchbot/accesstoken") == "test_token"


# Edge cases and error conditions tests


@pytest.mark.asyncio
async def test_json_parsing_error(oauth_with_pkce, mock_responses):  # pylint: disable=redefined-outer-name
    """Test handling of JSON parsing errors."""
    oauth = oauth_with_pkce

    # Mock response with invalid JSON
    mock_responses.post(f"{OAUTH_HOST}/oauth2/token", status=200, body="invalid json content")

    with pytest.raises(Exception):
        await oauth.exchange_code_for_token("test_code")


@pytest.mark.asyncio
async def test_network_timeout(oauth_with_pkce, mock_responses):  # pylint: disable=redefined-outer-name
    """Test network timeout handling."""
    oauth = oauth_with_pkce

    # Mock a timeout by using an exception
    mock_responses.post(
        f"{OAUTH_HOST}/oauth2/token", exception=asyncio.TimeoutError("Request timed out")
    )

    with pytest.raises(asyncio.TimeoutError):
        await oauth.exchange_code_for_token("test_code", oauth.state)


def test_pkce_parameter_uniqueness(configured_oauth):  # pylint: disable=redefined-outer-name
    """Test that PKCE parameters are unique across instances."""
    oauth1 = configured_oauth
    oauth2 = nowplaying.twitch.oauth2.TwitchOAuth2(oauth1.config)  # pylint: disable=no-member

    oauth1._generate_pkce_parameters()  # pylint: disable=protected-access
    oauth2._generate_pkce_parameters()  # pylint: disable=protected-access

    assert oauth1.code_verifier != oauth2.code_verifier
    assert oauth1.code_challenge != oauth2.code_challenge
    assert oauth1.state != oauth2.state


def test_pkce_challenge_calculation(configured_oauth):  # pylint: disable=redefined-outer-name
    """Test PKCE code challenge calculation correctness."""
    oauth = configured_oauth

    # Set known verifier for predictable challenge
    oauth.code_verifier = "test_verifier_123456789"
    oauth._generate_pkce_parameters()  # pylint: disable=protected-access

    # Manually calculate expected challenge
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(oauth.code_verifier.encode("utf-8")).digest())
        .decode("utf-8")
        .rstrip("=")
    )

    assert oauth.code_challenge == expected_challenge


def test_pkce_challenge_calculation_independent():
    """Test PKCE code challenge calculation logic independently."""
    code_verifier = "test_verifier_123456789"
    # Manually calculate expected challenge
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("utf-8")).digest())
        .decode("utf-8")
        .rstrip("=")
    )

    # Call the calculation logic directly from the base class
    actual_challenge = nowplaying.twitch.oauth2.TwitchOAuth2.calculate_pkce_challenge(code_verifier)

    assert actual_challenge == expected_challenge


@pytest.mark.parametrize(
    "client_id,expected_result,should_raise",
    [
        ("valid_client", "valid_client", False),  # Valid client ID
        ("  valid_client  ", "valid_client", False),  # Trimmed whitespace
        ("valid-client-123", "valid-client-123", False),  # Valid with hyphens and numbers
        ("valid_client_456", "valid_client_456", False),  # Valid with underscores
        (None, None, True),  # None client ID
        ("", None, True),  # Empty string
        ("   ", None, True),  # Whitespace only
        ("client with spaces", None, True),  # Spaces
        ("client@invalid", None, True),  # @ symbol
        ("client#test", None, True),  # # symbol
        ("client$test", None, True),  # $ symbol
        ("client%test", None, True),  # % symbol
        ("client\ntest", None, True),  # Newline
        ("client\ttest", None, True),  # Tab
        ("client\rtest", None, True),  # Carriage return
    ],
)
def test_client_id_validation(client_id, expected_result, should_raise):
    """Test client ID validation logic independently."""
    if should_raise:
        with pytest.raises(ValueError):
            nowplaying.twitch.oauth2.TwitchOAuth2.validate_client_id(client_id)
    else:
        result = nowplaying.twitch.oauth2.TwitchOAuth2.validate_client_id(client_id)
        assert result == expected_result


@pytest.mark.parametrize(
    "invalid_config_key",
    [
        "twitchbot/clientid",
        "twitchbot/secret",
    ],
)
def test_missing_config_handling(bootstrap, invalid_config_key):  # pylint: disable=redefined-outer-name
    """Test handling of missing configuration values."""
    config = bootstrap
    # Set all required config except one
    config.cparser.setValue("twitchbot/clientid", "test_client")
    config.cparser.setValue("twitchbot/secret", "test_secret")

    # Remove the specified config key
    config.cparser.remove(invalid_config_key)

    oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config)  # pylint: disable=no-member
    # Set redirect URI directly (no longer from config)
    oauth.redirect_uri = "http://localhost"

    # Should handle missing config gracefully
    if invalid_config_key == "twitchbot/clientid":
        with pytest.raises(ValueError, match="Client ID is required"):
            oauth.get_authorization_url()
    else:
        # Missing secret shouldn't prevent URL generation
        auth_url = oauth.get_authorization_url()
        assert "client_id=test_client" in auth_url


def test_missing_redirect_uri_handling(bootstrap):  # pylint: disable=redefined-outer-name
    """Test handling of missing redirect URI."""
    config = bootstrap
    config.cparser.setValue("twitchbot/clientid", "test_client")
    config.cparser.setValue("twitchbot/secret", "test_secret")

    oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config)  # pylint: disable=no-member
    # Don't set redirect_uri - should fail

    with pytest.raises(ValueError, match="Redirect URI is required"):
        oauth.get_authorization_url()
