#!/usr/bin/env python3
"""Integration tests for the Kick module - REFACTORED VERSION."""

import asyncio
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aioresponses import aioresponses

import nowplaying.kick.oauth2  # pylint: disable=import-error,no-name-in-module
import nowplaying.kick.chat  # pylint: disable=import-error,no-name-in-module
import nowplaying.kick.launch  # pylint: disable=import-error,no-name-in-module
import nowplaying.kick.settings  # pylint: disable=import-error,no-name-in-module
from nowplaying.kick.constants import OAUTH_HOST  # pylint: disable=import-error,no-name-in-module


# Fixtures
@pytest.fixture
def kick_integration_config(bootstrap):
    """Create a fully configured integration test config."""
    config = bootstrap
    config.cparser.setValue("kick/clientid", "test_client_id")
    config.cparser.setValue("kick/secret", "test_secret")
    config.cparser.setValue("kick/redirecturi", "http://localhost:8080/callback")
    config.cparser.setValue("kick/channel", "testchannel")
    config.cparser.setValue("kick/chat", True)
    config.cparser.setValue("kick/accesstoken", "valid_token")
    config.cparser.setValue("kick/refreshtoken", "refresh_token")
    config.cparser.setValue("kick/announcedelay", 0.1)  # Fast for testing
    return config


@pytest.fixture
def kick_templates(kick_integration_config):  # pylint: disable=redefined-outer-name
    """Create test template files for integration tests."""
    config = kick_integration_config
    # Bootstrap fixture already sets up templatedir, just use it
    config.templatedir.mkdir(parents=True, exist_ok=True)

    templates = {
        "announce": config.templatedir / "kick_announce.txt",
        "track": config.templatedir / "kickbot_track.txt",
        "artist": config.templatedir / "kickbot_artist.txt",
        "request": config.templatedir / "kickbot_request.txt",
    }

    templates["announce"].write_text("Now playing: {{artist}} - {{title}}")
    templates["track"].write_text("Now playing: {{artist}} - {{title}}")
    templates["artist"].write_text("Artist: {{artist}}")
    templates["request"].write_text("Request: {{request}}")

    return templates


@pytest.fixture
def mock_chat_with_oauth(kick_integration_config):  # pylint: disable=redefined-outer-name
    """Create a chat instance for integration testing."""
    stopevent = asyncio.Event()
    chat = nowplaying.kick.chat.KickChat(config=kick_integration_config, stopevent=stopevent)  # pylint: disable=no-member
    return chat, stopevent


@pytest.fixture
def mock_aiohttp_success():
    """Fixture that mocks successful aiohttp responses using aioresponses."""
    with aioresponses() as mock:
        # Setup default success responses for common endpoints (repeat=True for multiple calls)
        mock.post(
            "https://api.kick.com/public/v1/chat",
            status=200,
            payload={"success": True},
            repeat=True,
        )
        yield mock


@pytest.fixture
def mock_responses():
    """Fixture that provides aioresponses for mocking HTTP calls."""
    with aioresponses() as mock:
        yield mock


@pytest.mark.asyncio
async def test_full_authentication_flow(kick_integration_config, mock_responses):  # pylint: disable=redefined-outer-name
    """Test complete OAuth2 authentication flow."""
    config = kick_integration_config

    # Create OAuth2 handler
    oauth = nowplaying.kick.oauth2.KickOAuth2(config)  # pylint: disable=no-member
    # Set redirect URI dynamically (as done in real usage)
    oauth.redirect_uri = "http://localhost:8080/callback"

    # Test authorization URL generation
    auth_url = oauth.get_authorization_url()
    assert "client_id=test_client_id" in auth_url
    assert oauth.code_verifier is not None
    assert oauth.state is not None

    # Mock successful token exchange
    mock_token_response = {
        "access_token": "test_access_token",
        "refresh_token": "test_refresh_token",
    }

    mock_responses.post(f"{OAUTH_HOST}/oauth/token", status=200, payload=mock_token_response)

    result = await oauth.exchange_code_for_token("test_auth_code", oauth.state)

    assert result == mock_token_response
    assert oauth.access_token == "test_access_token"
    assert oauth.refresh_token == "test_refresh_token"

    # Save tokens manually (as the caller is responsible for saving)
    new_access_token = result.get("access_token")
    new_refresh_token = result.get("refresh_token")
    if new_access_token:
        config.cparser.setValue("kick/accesstoken", new_access_token)
        if new_refresh_token:
            config.cparser.setValue("kick/refreshtoken", new_refresh_token)
        config.save()

    # Verify tokens were stored in config
    assert config.cparser.value("kick/accesstoken") == "test_access_token"
    assert config.cparser.value("kick/refreshtoken") == "test_refresh_token"


@pytest.mark.asyncio
async def test_chat_with_oauth_integration(mock_chat_with_oauth, mock_responses):  # pylint: disable=redefined-outer-name
    """Test chat integration with OAuth2."""
    chat, _ = mock_chat_with_oauth

    # Mock the consolidated token refresh function
    with patch(
        "nowplaying.kick.utils.attempt_token_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        mock_refresh.return_value = True

        # Test authentication
        result = await chat._authenticate()  # pylint: disable=protected-access
        assert result
        assert chat.authenticated

    # Mock message sending endpoint
    mock_responses.post(
        "https://api.kick.com/public/v1/chat",
        status=200,
        payload={"data": {"is_sent": True}, "message": "OK"},
    )

    # Test message sending
    result = await chat._send_message("Test message")  # pylint: disable=protected-access
    assert result is True


# Parameterized settings integration tests
@pytest.mark.parametrize("settings_type", ["main", "chat"])
def test_settings_integration_scenarios(kick_integration_config, settings_type):  # pylint: disable=redefined-outer-name
    """Test settings integration for different types."""
    config = kick_integration_config

    if settings_type == "main":
        settings = nowplaying.kick.settings.KickSettings()  # pylint: disable=no-member

        # Create a very explicit mock to avoid AsyncMock contamination
        mock_widget = MagicMock(
            spec=[
                "enable_checkbox",
                "channel_lineedit",
                "clientid_lineedit",
                "secret_lineedit",
                "redirecturi_label",
                "authenticate_button",
                "oauth_status_label",
            ]
        )

        # Ensure all text methods return proper strings
        mock_widget.clientid_lineedit.text.return_value = "test_client"
        mock_widget.secret_lineedit.text.return_value = "test_secret"
        mock_widget.channel_lineedit.text.return_value = "testchannel"

        mock_uihelp = MagicMock()
        settings.load(config, mock_widget, mock_uihelp)
        assert isinstance(settings.oauth, nowplaying.kick.oauth2.KickOAuth2)  # pylint: disable=no-member
    else:
        chat_settings = nowplaying.kick.settings.KickChatSettings()  # pylint: disable=no-member
        mock_chat_widget = MagicMock()

        mock_uihelp = MagicMock()
        chat_settings.load(config, mock_chat_widget, mock_uihelp)
        assert chat_settings.widget == mock_chat_widget


@pytest.mark.asyncio
async def test_token_refresh_integration(kick_integration_config, mock_responses):  # pylint: disable=redefined-outer-name
    """Test token refresh across components."""
    config = kick_integration_config
    config.cparser.setValue("kick/accesstoken", "expired_token")

    # Create OAuth2 handler
    oauth = nowplaying.kick.oauth2.KickOAuth2(config)  # pylint: disable=no-member

    # Mock refresh token response
    mock_refresh_response = {
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
    }

    mock_responses.post(f"{OAUTH_HOST}/oauth/token", status=200, payload=mock_refresh_response)

    result = await oauth.refresh_access_token_async("valid_refresh_token")

    assert result == mock_refresh_response
    assert oauth.access_token == "new_access_token"

    # Save tokens manually (as the caller is responsible for saving)
    new_access_token = result.get("access_token")
    new_refresh_token = result.get("refresh_token")
    if new_access_token:
        config.cparser.setValue("kick/accesstoken", new_access_token)
        if new_refresh_token:
            config.cparser.setValue("kick/refreshtoken", new_refresh_token)
        config.save()

    # Verify new tokens were stored
    assert config.cparser.value("kick/accesstoken") == "new_access_token"
    assert config.cparser.value("kick/refreshtoken") == "new_refresh_token"


@pytest.mark.asyncio
async def test_announcement_flow_integration(kick_integration_config, kick_templates):  # pylint: disable=redefined-outer-name
    """Test track announcement flow integration."""
    config = kick_integration_config
    config.cparser.setValue("kick/announce", str(kick_templates["announce"]))

    stopevent = asyncio.Event()
    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  # pylint: disable=no-member
    chat.authenticated = True

    # Mock metadata
    mock_metadata = {"artist": "Test Artist", "title": "Test Song"}
    chat.metadb.read_last_meta_async = AsyncMock(return_value=mock_metadata)

    # Mock message sending
    chat._send_message = AsyncMock(return_value=True)  # pylint: disable=protected-access

    # Test announcement
    await chat._process_announcement()  # pylint: disable=protected-access

    # Verify message was sent with rendered template
    chat._send_message.assert_called_once_with("Now playing: Test Artist - Test Song")  # pylint: disable=protected-access

    # Verify last announced was updated
    assert chat.last_announced["artist"] == "Test Artist"
    assert chat.last_announced["title"] == "Test Song"


def test_command_discovery_integration(kick_integration_config, kick_templates):  # pylint: disable=redefined-outer-name,unused-argument
    """Test command template discovery integration."""
    config = kick_integration_config

    # Create settings and update commands
    chat_settings = nowplaying.kick.settings.KickChatSettings()  # pylint: disable=no-member
    chat_settings.update_kickbot_commands(config)

    # Verify commands were created
    groups = config.cparser.childGroups()
    assert "kickbot-command-track" in groups
    assert "kickbot-command-artist" in groups
    assert "kickbot-command-request" in groups

    # Verify default permissions (all disabled)
    config.cparser.beginGroup("kickbot-command-track")
    for permission in chat_settings.KICKBOT_CHECKBOXES:
        assert not config.cparser.value(permission, type=bool)
    config.cparser.endGroup()


# Parameterized error handling tests
@pytest.mark.parametrize(
    "component,error_scenario,expected_behavior",
    [
        ("oauth", "network_error", "raises_exception"),
        ("chat", "no_tokens", "returns_false"),
        ("chat", "not_authenticated", "returns_false"),
    ],
)
@pytest.mark.asyncio
async def test_error_handling_scenarios(  # pylint: disable=redefined-outer-name
    kick_integration_config, component, error_scenario, expected_behavior
):
    """Test error handling across different components and scenarios."""
    config = kick_integration_config

    if component == "oauth":
        oauth = nowplaying.kick.oauth2.KickOAuth2(config)  # pylint: disable=no-member
        oauth.code_verifier = "test_verifier"

        # Use aioresponses to mock network error
        with aioresponses() as mock:
            mock.post(f"{OAUTH_HOST}/oauth/token", exception=Exception("Network error"))

            if expected_behavior == "raises_exception":
                with pytest.raises(Exception):
                    await oauth.exchange_code_for_token("test_code")
            else:
                # If we expect different behavior, implement it here
                result = await oauth.exchange_code_for_token("test_code")
                assert result is False  # or other expected behavior

    elif component == "chat":
        stopevent = asyncio.Event()
        chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  # pylint: disable=no-member

        if error_scenario == "no_tokens":
            # Mock OAuth to fail
            mock_oauth = MagicMock()
            mock_oauth.get_stored_tokens.return_value = (None, None)
            chat.oauth = mock_oauth

            result = await chat._authenticate()  # pylint: disable=protected-access

            if expected_behavior == "returns_false":
                assert not result
                assert not chat.authenticated

        elif error_scenario == "not_authenticated":
            chat.authenticated = False

            result = await chat._send_message("Test message")  # pylint: disable=protected-access

            if expected_behavior == "returns_false":
                assert result is False


@pytest.mark.asyncio
async def test_config_changes_integration(kick_integration_config):  # pylint: disable=redefined-outer-name
    """Test configuration changes affecting components."""
    config = kick_integration_config

    # Initial configuration
    config.cparser.setValue("kick/clientid", "old_client_id")
    config.cparser.setValue("kick/channel", "oldchannel")
    config.cparser.setValue("kick/accesstoken", "old_token")

    # Test settings save with changes
    mock_widget = MagicMock()
    mock_widget.enable_checkbox.isChecked.return_value = True
    mock_widget.channel_lineedit.text.return_value = "newchannel"
    mock_widget.clientid_lineedit.text.return_value = "new_client_id"
    mock_widget.secret_lineedit.text.return_value = "secret"
    mock_widget.redirecturi_lineedit.text.return_value = "http://localhost:8080"

    mock_subprocesses = MagicMock()

    with patch("nowplaying.kick.settings.QTimer.singleShot") as mock_timer:
        # Configure the mock to immediately call the callback
        mock_timer.side_effect = lambda delay, callback: callback()
        nowplaying.kick.settings.KickSettings.save(config, mock_widget, mock_subprocesses)  # pylint: disable=no-member

    # Verify kickbot was restarted due to changes
    mock_subprocesses.stop_kickbot.assert_called_once()
    mock_subprocesses.start_kickbot.assert_called_once()

    # Verify tokens were cleared due to config changes
    assert config.cparser.value("kick/accesstoken") is None


# Parameterized UI widget integration tests
@pytest.mark.parametrize("widget_type", ["main", "chat"])
def test_ui_widget_integration_scenarios(widget_type):
    """Test UI widget integration for different widget types."""
    if widget_type == "main":
        main_settings = nowplaying.kick.settings.KickSettings()  # pylint: disable=no-member
        mock_uihelp = MagicMock()
        mock_widget = MagicMock()

        main_settings.connect(mock_uihelp, mock_widget)

        # Verify button connections
        mock_widget.authenticate_button.clicked.connect.assert_called_once()
        mock_widget.clientid_lineedit.editingFinished.connect.assert_called_once()

    else:
        chat_settings = nowplaying.kick.settings.KickChatSettings()  # pylint: disable=no-member
        mock_chat_widget = MagicMock()
        mock_chat_widget.announce_button = MagicMock()
        mock_chat_widget.add_button = MagicMock()
        mock_chat_widget.del_button = MagicMock()

        chat_settings.connect(MagicMock(), mock_chat_widget)

        # Verify chat widget connections
        mock_chat_widget.announce_button.clicked.connect.assert_called_once()
        mock_chat_widget.add_button.clicked.connect.assert_called_once()
        mock_chat_widget.del_button.clicked.connect.assert_called_once()


# Test edge cases and error conditions


@pytest.mark.asyncio
async def test_malformed_api_responses(kick_integration_config):  # pylint: disable=redefined-outer-name
    """Test handling of malformed API responses."""
    config = kick_integration_config
    oauth = nowplaying.kick.oauth2.KickOAuth2(config)  # pylint: disable=no-member
    oauth.code_verifier = "test_verifier"

    # Test malformed JSON response using aioresponses
    with aioresponses() as mock:
        mock.post(f"{OAUTH_HOST}/oauth/token", status=200, body="invalid json content")

        with pytest.raises(Exception):
            await oauth.exchange_code_for_token("test_code")


@pytest.mark.asyncio
async def test_network_timeouts(kick_integration_config):  # pylint: disable=redefined-outer-name
    """Test network timeout handling."""
    config = kick_integration_config
    stopevent = asyncio.Event()
    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  # pylint: disable=no-member
    chat.authenticated = True

    # Mock OAuth for message sending
    mock_oauth = MagicMock()
    mock_oauth.get_stored_tokens.return_value = ("valid_token", "refresh_token")
    chat.oauth = mock_oauth

    # Test timeout during message sending using aioresponses
    with aioresponses() as mock:
        mock.post(
            "https://api.kick.com/public/v1/chat",
            exception=asyncio.TimeoutError("Request timed out"),
        )

        result = await chat._send_message("Test message")  # pylint: disable=protected-access
        assert result is False


def test_invalid_template_files(kick_integration_config):  # pylint: disable=redefined-outer-name
    """Test handling of invalid template files."""
    config = kick_integration_config

    # Create invalid template path
    config.cparser.setValue("kick/announce", "/nonexistent/template.txt")

    stopevent = asyncio.Event()
    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  # pylint: disable=no-member
    chat.authenticated = True

    # Mock metadata
    mock_metadata = {"artist": "Test", "title": "Test"}
    chat.metadb.read_last_meta_async = AsyncMock(return_value=mock_metadata)

    # Test announcement with invalid template - should not crash
    async def test_announcement():
        await chat._process_announcement()  # pylint: disable=protected-access

    # Should not raise exception
    asyncio.run(test_announcement())


def test_concurrent_access(kick_integration_config):  # pylint: disable=redefined-outer-name
    """Test concurrent access to components."""
    config = kick_integration_config

    # Test multiple OAuth instances
    oauth1 = nowplaying.kick.oauth2.KickOAuth2(config)  # pylint: disable=no-member
    oauth2 = nowplaying.kick.oauth2.KickOAuth2(config)  # pylint: disable=no-member

    # Both should work independently
    oauth1._generate_pkce_parameters()  # pylint: disable=protected-access
    oauth2._generate_pkce_parameters()  # pylint: disable=protected-access

    assert oauth1.code_verifier != oauth2.code_verifier
    assert oauth1.state != oauth2.state


def test_memory_cleanup(kick_integration_config):  # pylint: disable=redefined-outer-name
    """Test memory cleanup on component destruction."""
    config = kick_integration_config
    stopevent = asyncio.Event()

    # Create components
    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  # pylint: disable=no-member
    launch = nowplaying.kick.launch.KickLaunch(config=config, stopevent=stopevent)  # pylint: disable=no-member

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


def test_unicode_and_special_characters(kick_integration_config):  # pylint: disable=redefined-outer-name
    """Test handling of unicode and special characters."""
    config = kick_integration_config

    # Bootstrap already sets up templatedir, just use it
    config.templatedir.mkdir(parents=True, exist_ok=True)

    # Test template with unicode
    template_content = "Now playing: {{artist}} - {{title}} 🎵"
    template_path = config.templatedir / "unicode_template.txt"
    template_path.write_text(template_content, encoding="utf-8")

    stopevent = asyncio.Event()
    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  # pylint: disable=no-member

    # Test Jinja2 environment can handle unicode
    env = chat.setup_jinja2(pathlib.Path(config.templatedir))
    template = env.get_template("unicode_template.txt")

    result = template.render(artist="Björk", title="Jóga")
    assert "Björk" in result
    assert "Jóga" in result
    assert "🎵" in result


# Test performance-related integration scenarios


@pytest.mark.asyncio
async def test_rapid_message_sending(mock_chat_with_oauth, mock_aiohttp_success):  # pylint: disable=redefined-outer-name,unused-argument
    """Test rapid successive message sending."""
    chat, _ = mock_chat_with_oauth
    chat.authenticated = True

    # Mock OAuth for message sending
    mock_oauth = MagicMock()
    mock_oauth.get_stored_tokens.return_value = ("valid_token", "refresh_token")
    chat.oauth = mock_oauth

    # Send multiple messages quickly
    results = await asyncio.gather(*[chat._send_message(f"Message {i}") for i in range(5)])  # pylint: disable=protected-access

    # All should succeed
    assert all(results)


@pytest.mark.asyncio
async def test_concurrent_authentication_attempts(kick_integration_config):  # pylint: disable=redefined-outer-name
    """Test concurrent authentication attempts."""
    config = kick_integration_config

    # Create multiple launch instances
    launches = [
        nowplaying.kick.launch.KickLaunch(config=config, stopevent=asyncio.Event())  # pylint: disable=no-member
        for _ in range(3)
    ]

    # Mock the consolidated token refresh function
    with patch(
        "nowplaying.kick.utils.attempt_token_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        mock_refresh.return_value = True

        # Authenticate concurrently
        results = await asyncio.gather(*[launch.authenticate() for launch in launches])

    # All should succeed
    assert all(results)


def test_large_template_processing(kick_integration_config):  # pylint: disable=redefined-outer-name
    """Test processing of large template files."""
    config = kick_integration_config

    # Bootstrap already sets up templatedir, just use it
    config.templatedir.mkdir(parents=True, exist_ok=True)

    large_template = "Now playing: {{artist}} - {{title}}\n" * 1000
    template_path = config.templatedir / "large_template.txt"
    template_path.write_text(large_template)

    stopevent = asyncio.Event()
    chat = nowplaying.kick.chat.KickChat(config=config, stopevent=stopevent)  # pylint: disable=no-member

    # Should handle large templates without issues
    env = chat.setup_jinja2(pathlib.Path(config.templatedir))
    template = env.get_template("large_template.txt")

    result = template.render(artist="Test Artist", title="Test Song")
    assert len(result) > 10000  # Should be large
    assert "Test Artist" in result
