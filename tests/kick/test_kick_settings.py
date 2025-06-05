#!/usr/bin/env python3
"""Unit tests for Kick settings functionality - REFACTORED VERSION."""
# pylint: disable=no-member,redefined-outer-name,too-many-arguments,unused-argument,protected-access,import-error,no-name-in-module

import pathlib
from unittest.mock import MagicMock, patch

import pytest
import requests

import nowplaying.kick.settings
import nowplaying.kick.oauth2
import nowplaying.kick.utils
from nowplaying.exceptions import PluginVerifyError


# Fixtures
@pytest.fixture
def mock_kick_widget():
    """Create a mock widget with all Kick UI elements."""
    widget = MagicMock()
    widget.enable_checkbox = MagicMock()
    widget.channel_lineedit = MagicMock()
    widget.clientid_lineedit = MagicMock()
    widget.secret_lineedit = MagicMock()
    widget.redirecturi_lineedit = MagicMock()
    widget.authenticate_button = MagicMock()
    widget.oauth_status_label = MagicMock()
    # Set default text values for the update_oauth_status method
    widget.clientid_lineedit.text.return_value = 'test_client'
    widget.secret_lineedit.text.return_value = 'test_secret'
    widget.redirecturi_lineedit.text.return_value = 'http://localhost:8080'
    return widget


@pytest.fixture
def mock_chat_widget():
    """Create a mock chat widget with command table and controls."""
    widget = MagicMock()
    widget.enable_checkbox = MagicMock()
    widget.announce_lineedit = MagicMock()
    widget.announcedelay_spin = MagicMock()
    widget.command_perm_table = MagicMock()
    widget.command_perm_table.rowCount.return_value = 0
    widget.announce_button = MagicMock()
    widget.add_button = MagicMock()
    widget.del_button = MagicMock()
    return widget


@pytest.fixture
def configured_kick_config(bootstrap):
    """Create a bootstrap config with Kick settings pre-configured."""
    config = bootstrap
    config.cparser.setValue('kick/enabled', True)
    config.cparser.setValue('kick/channel', 'testchannel')
    config.cparser.setValue('kick/clientid', 'test_client_id')
    config.cparser.setValue('kick/secret', 'test_secret')
    config.cparser.setValue('kick/redirecturi', 'http://localhost:8080/callback')
    return config


def test_kick_settings_init():
    """Test KickSettings initialization."""
    settings = nowplaying.kick.settings.KickSettings()

    assert settings.widget is None
    assert settings.oauth is None


def test_kick_settings_connect(mock_kick_widget):
    """Test settings connection."""
    settings = nowplaying.kick.settings.KickSettings()
    mock_uihelp = MagicMock()

    settings.connect(mock_uihelp, mock_kick_widget)

    assert settings.widget == mock_kick_widget
    mock_kick_widget.authenticate_button.clicked.connect.assert_called_once()
    mock_kick_widget.clientid_lineedit.editingFinished.connect.assert_called_once()
    mock_kick_widget.secret_lineedit.editingFinished.connect.assert_called_once()
    mock_kick_widget.redirecturi_lineedit.editingFinished.connect.assert_called_once()


def test_kick_settings_load(configured_kick_config, mock_kick_widget):
    """Test settings loading."""
    settings = nowplaying.kick.settings.KickSettings()

    settings.load(configured_kick_config, mock_kick_widget)

    assert settings.widget == mock_kick_widget
    mock_kick_widget.enable_checkbox.setChecked.assert_called_with(True)
    mock_kick_widget.channel_lineedit.setText.assert_called_with('testchannel')
    mock_kick_widget.clientid_lineedit.setText.assert_called_with('test_client_id')
    mock_kick_widget.secret_lineedit.setText.assert_called_with('test_secret')
    mock_kick_widget.redirecturi_lineedit.setText.assert_called_with(
        'http://localhost:8080/callback')
    assert isinstance(settings.oauth, nowplaying.kick.oauth2.KickOAuth2)


def test_kick_settings_load_default_redirect_uri(bootstrap, mock_kick_widget):
    """Test settings loading with default redirect URI."""
    settings = nowplaying.kick.settings.KickSettings()

    settings.load(bootstrap, mock_kick_widget)

    # Should set default redirect URI
    mock_kick_widget.redirecturi_lineedit.setText.assert_called_with(
        'http://localhost:8080/kickredirect')


@pytest.mark.parametrize(
    "has_changes,should_restart",
    [
        (False, False),  # No changes - no restart
        (True, True),  # Changes - restart kickbot
    ])
def test_kick_settings_save_scenarios(bootstrap, mock_kick_widget, has_changes, should_restart):
    """Test settings saving with and without changes."""
    config = bootstrap
    if not has_changes:
        # Set initial values that match widget values
        config.cparser.setValue('kick/channel', 'testchannel')
        config.cparser.setValue('kick/clientid', 'testclient')
        config.cparser.setValue('kick/secret', 'testsecret')
        config.cparser.setValue('kick/redirecturi', 'testuri')
    else:
        # Set different initial values
        config.cparser.setValue('kick/channel', 'oldchannel')
        config.cparser.setValue('kick/clientid', 'oldclient')
        config.cparser.setValue('kick/secret', 'oldsecret')
        config.cparser.setValue('kick/redirecturi', 'olduri')
        config.cparser.setValue('kick/accesstoken', 'old_token')
        config.cparser.setValue('kick/refreshtoken', 'old_refresh')

    # Setup widget return values
    mock_kick_widget.enable_checkbox.isChecked.return_value = True
    mock_kick_widget.channel_lineedit.text.return_value = 'testchannel'
    mock_kick_widget.clientid_lineedit.text.return_value = 'testclient'
    mock_kick_widget.secret_lineedit.text.return_value = 'testsecret'
    mock_kick_widget.redirecturi_lineedit.text.return_value = 'testuri'

    mock_subprocesses = MagicMock()

    with patch('time.sleep'):  # Speed up test
        nowplaying.kick.settings.KickSettings.save(config, mock_kick_widget, mock_subprocesses)

    if should_restart:
        mock_subprocesses.stop_kickbot.assert_called_once()
        mock_subprocesses.start_kickbot.assert_called_once()
        # Tokens should be cleared
        assert config.cparser.value('kick/accesstoken') is None
        assert config.cparser.value('kick/refreshtoken') is None
    else:
        mock_subprocesses.stop_kickbot.assert_not_called()
        mock_subprocesses.start_kickbot.assert_not_called()


# Parameterized verification tests
@pytest.mark.parametrize(
    "enabled,client_id,secret,redirect_uri,channel,expected_error",
    [
        (False, '', '', '', '', None),  # Disabled - no validation
        (True, '', 'secret', 'http://localhost', 'channel', 'Kick Client ID is required'),
        (True, 'client', '', 'http://localhost', 'channel', 'Kick Client Secret is required'),
        (True, 'client', 'secret', '', 'channel', 'Kick Redirect URI is required'),
        (True, 'client', 'secret', 'http://localhost', '', 'Kick Channel is required'),
        (True, 'client', 'secret', 'invalid_uri', 'channel',
         'Kick Redirect URI must start with http'),
        (True, 'client', 'secret', 'http://localhost', 'channel', None),  # Valid
    ])
def test_kick_settings_verify_scenarios(enabled, client_id, secret, redirect_uri, channel,
                                        expected_error):
    """Test verification with various input combinations."""
    mock_widget = MagicMock()
    mock_widget.enable_checkbox.isChecked.return_value = enabled
    mock_widget.clientid_lineedit.text.return_value = client_id
    mock_widget.secret_lineedit.text.return_value = secret
    mock_widget.redirecturi_lineedit.text.return_value = redirect_uri
    mock_widget.channel_lineedit.text.return_value = channel

    if expected_error:
        with pytest.raises(PluginVerifyError, match=expected_error):
            nowplaying.kick.settings.KickSettings.verify(mock_widget)
    else:
        nowplaying.kick.settings.KickSettings.verify(mock_widget)


def test_kick_settings_authenticate_oauth(bootstrap, mock_kick_widget):
    """Test OAuth authentication."""
    settings = nowplaying.kick.settings.KickSettings()
    settings.widget = mock_kick_widget

    # Mock OAuth
    mock_oauth = MagicMock()
    mock_oauth.open_browser_for_auth.return_value = True
    settings.oauth = mock_oauth

    settings.authenticate_oauth()

    mock_oauth.open_browser_for_auth.assert_called_once()


@pytest.mark.parametrize(
    "has_oauth,has_tokens,token_valid,expected_status",
    [
        (False, False, False, None),  # No OAuth - should not crash
        (True, False, False, 'Not authenticated'),  # No tokens
        (True, True, True, 'called'),  # Valid token - status will be set
        (True, True, False, 'called'),  # Invalid token - status will be set
    ])
def test_kick_settings_update_oauth_status_scenarios(bootstrap, mock_kick_widget, has_oauth,
                                                     has_tokens, token_valid, expected_status):
    """Test OAuth status update with various scenarios."""
    settings = nowplaying.kick.settings.KickSettings()
    settings.widget = mock_kick_widget

    if has_oauth:
        mock_oauth = MagicMock()
        if has_tokens:
            mock_oauth.get_stored_tokens.return_value = ('valid_token', 'refresh_token')
        else:
            mock_oauth.get_stored_tokens.return_value = (None, None)
        settings.oauth = mock_oauth
        with patch('nowplaying.kick.utils.qtsafe_validate_kick_token', return_value=token_valid):
            settings.update_oauth_status()
    else:
        settings.oauth = None
        settings.update_oauth_status()

    if expected_status == 'Not authenticated':
        mock_kick_widget.oauth_status_label.setText.assert_called_with('Not authenticated')
    elif expected_status == 'called':
        assert mock_kick_widget.oauth_status_label.setText.called


# Parameterized token validation tests
@pytest.mark.parametrize(
    "status_code,response_data,exception_type,expected_result",
    [
        (200, {
            'data': {
                'active': True,
                'client_id': 'test_client'
            }
        }, None, True),
        (200, {
            'data': {
                'active': False
            }
        }, None, False),
        (401, {}, None, False),
        (500, {}, None, False),
        (200, {}, requests.RequestException, False),  # Network error
        (200, {}, ValueError, False),  # JSON parsing error
    ])
def test_qtsafe_validate_kick_token_scenarios(status_code, response_data, exception_type,
                                              expected_result):
    """Test Qt-safe token validation with various responses."""
    if exception_type:
        with patch('requests.post', side_effect=exception_type("Test error")):
            result = nowplaying.kick.utils.qtsafe_validate_kick_token('test_token')
    else:
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = response_data

        with patch('requests.post', return_value=mock_response):
            result = nowplaying.kick.utils.qtsafe_validate_kick_token('test_token')

    assert result == expected_result


def test_kick_settings_clear_authentication(bootstrap):
    """Test clearing authentication."""
    settings = nowplaying.kick.settings.KickSettings()

    # Mock OAuth
    mock_oauth = MagicMock()
    settings.oauth = mock_oauth
    settings.update_oauth_status = MagicMock()

    settings.clear_authentication()

    mock_oauth.clear_stored_tokens.assert_called_once()
    settings.update_oauth_status.assert_called_once()


def test_kick_chat_settings_init():
    """Test KickChatSettings initialization."""
    settings = nowplaying.kick.settings.KickChatSettings()

    assert settings.widget is None
    assert settings.KICKBOT_CHECKBOXES == [
        'anyone', 'broadcaster', 'moderator', 'subscriber', 'founder', 'vip'
    ]


@pytest.mark.parametrize("has_buttons", [True, False])
def test_kick_chat_settings_connect_scenarios(mock_chat_widget, has_buttons):
    """Test settings connection with and without buttons."""
    settings = nowplaying.kick.settings.KickChatSettings()
    mock_uihelp = MagicMock()

    if not has_buttons:
        # Remove button attributes
        del mock_chat_widget.announce_button
        del mock_chat_widget.add_button
        del mock_chat_widget.del_button

    # Should not crash regardless
    settings.connect(mock_uihelp, mock_chat_widget)

    assert settings.widget == mock_chat_widget

    if has_buttons:
        mock_chat_widget.announce_button.clicked.connect.assert_called_once()
        mock_chat_widget.add_button.clicked.connect.assert_called_once()
        mock_chat_widget.del_button.clicked.connect.assert_called_once()


@pytest.mark.parametrize("delay_field_type", ['spin', 'lineedit'])
def test_kick_chat_settings_load_delay_field_types(bootstrap, mock_chat_widget, delay_field_type):
    """Test loading with different delay field types."""
    config = bootstrap
    config.cparser.setValue('kick/chat', True)
    config.cparser.setValue('kick/announce', 'test_template.txt')
    config.cparser.setValue('kick/announcedelay', 2.5)

    settings = nowplaying.kick.settings.KickChatSettings()

    # Setup delay field based on type
    if delay_field_type == 'spin':
        mock_chat_widget.announcedelay_spin = MagicMock()
        delattr(mock_chat_widget, 'announce_delay_lineedit')
    else:
        mock_chat_widget.announce_delay_lineedit = MagicMock()
        delattr(mock_chat_widget, 'announcedelay_spin')

    settings.load(config, mock_chat_widget)

    assert settings.widget == mock_chat_widget
    mock_chat_widget.enable_checkbox.setChecked.assert_called_with(True)
    mock_chat_widget.announce_lineedit.setText.assert_called_with('test_template.txt')

    if delay_field_type == 'spin':
        mock_chat_widget.announcedelay_spin.setValue.assert_called_with(2.5)
    else:
        mock_chat_widget.announce_delay_lineedit.setText.assert_called_with('2.5')


@patch('nowplaying.kick.settings.QCheckBox')
@patch('nowplaying.kick.settings.QTableWidgetItem')
def test_kick_chat_settings_load_with_command_table(mock_table_widget_item, mock_qcheckbox,
                                                    bootstrap, mock_chat_widget):
    """Test loading with command permission table."""
    config = bootstrap

    # Create test command configuration
    config.cparser.beginGroup('kickbot-command-track')
    config.cparser.setValue('anyone', True)
    config.cparser.setValue('broadcaster', True)
    config.cparser.setValue('moderator', False)
    config.cparser.endGroup()

    settings = nowplaying.kick.settings.KickChatSettings()

    # Mock command table
    mock_chat_widget.command_perm_table.setRowCount = MagicMock()
    mock_chat_widget.command_perm_table.rowCount.return_value = 1

    settings.load(config, mock_chat_widget)

    # Verify table was reset
    mock_chat_widget.command_perm_table.setRowCount.assert_called_with(0)


@pytest.mark.parametrize(
    "delay_field_type,delay_value,expected_delay",
    [
        ('spin', 2.5, 2.5),
        ('lineedit', '1.5', 1.5),
        ('lineedit', 'invalid', 1.0),  # Invalid value defaults to 1.0
    ])
def test_kick_chat_settings_save_delay_scenarios(bootstrap, mock_chat_widget, delay_field_type,
                                                 delay_value, expected_delay):
    """Test saving with different delay field types and values."""
    config = bootstrap
    mock_chat_widget.enable_checkbox.isChecked.return_value = False
    mock_chat_widget.announce_lineedit.text.return_value = ''

    # Setup delay field based on type
    if delay_field_type == 'spin':
        mock_chat_widget.announcedelay_spin.value.return_value = delay_value
        delattr(mock_chat_widget, 'announce_delay_lineedit')
    else:
        mock_chat_widget.announce_delay_lineedit.text.return_value = delay_value
        delattr(mock_chat_widget, 'announcedelay_spin')

    mock_subprocesses = MagicMock()

    nowplaying.kick.settings.KickChatSettings.save(config, mock_chat_widget, mock_subprocesses)

    assert config.cparser.value('kick/announcedelay', type=float) == expected_delay


def test_kick_chat_settings_save_kickbot_commands(bootstrap, mock_chat_widget):
    """Test saving kickbot command permissions."""
    config = bootstrap

    # Create existing command to be removed
    config.cparser.beginGroup('kickbot-command-oldcommand')
    config.cparser.setValue('anyone', True)
    config.cparser.endGroup()

    mock_chat_widget.command_perm_table.rowCount.return_value = 1

    # Mock table item
    mock_item = MagicMock()
    mock_item.text.return_value = '!newcommand'
    mock_chat_widget.command_perm_table.item.return_value = mock_item

    # Mock checkboxes
    mock_checkbox = MagicMock()
    mock_checkbox.isChecked.return_value = True
    mock_chat_widget.command_perm_table.cellWidget.return_value = mock_checkbox

    nowplaying.kick.settings.KickChatSettings._save_kickbot_commands(config, mock_chat_widget)

    # Old command should be removed
    assert 'kickbot-command-oldcommand' not in config.cparser.childGroups()

    # New command should be saved
    config.cparser.beginGroup('kickbot-command-newcommand')
    assert config.cparser.value('anyone', type=bool)
    config.cparser.endGroup()


# Parameterized verification tests
@pytest.mark.parametrize(
    "enabled,template_path,expected_error",
    [
        (False, '', None),  # Disabled - no validation
        (True, '', 'Kick announcement template is required'),
        (True, 'template.txt', None),  # Valid
    ])
def test_kick_chat_settings_verify_scenarios(enabled, template_path, expected_error):
    """Test verification with various input combinations."""
    mock_widget = MagicMock()
    mock_widget.enable_checkbox.isChecked.return_value = enabled
    mock_widget.announce_lineedit.text.return_value = template_path

    if expected_error:
        with pytest.raises(PluginVerifyError, match=expected_error):
            nowplaying.kick.settings.KickChatSettings.verify(mock_widget)
    else:
        nowplaying.kick.settings.KickChatSettings.verify(mock_widget)


@pytest.mark.parametrize(
    "template_dir_exists,has_templates",
    [
        (False, False),  # No template directory
        (True, False),  # Template directory but no kickbot templates
        (True, True),  # Template directory with kickbot templates
    ])
def test_kick_chat_settings_update_kickbot_commands_scenarios(bootstrap, template_dir_exists,
                                                              has_templates):
    """Test command update with various template directory scenarios."""
    config = bootstrap

    if not template_dir_exists:
        # Set non-existent template directory
        config.templatedir = pathlib.Path('/non/existent/path')
    elif has_templates:
        # Create test template files in test directory
        test_template_dir = config.testdir / 'templates'
        config.templatedir = test_template_dir
        test_template_dir.mkdir(parents=True, exist_ok=True)
        (test_template_dir / 'kickbot_track.txt').write_text('Template content')
        (test_template_dir / 'kickbot_artist.txt').write_text('Template content')

    settings = nowplaying.kick.settings.KickChatSettings()

    # Should not crash in any scenario
    settings.update_kickbot_commands(config)

    if template_dir_exists and has_templates:
        # Should create command entries
        assert 'kickbot-command-track' in config.cparser.childGroups()
        assert 'kickbot-command-artist' in config.cparser.childGroups()

        # Verify default permissions (all disabled)
        config.cparser.beginGroup('kickbot-command-track')
        for checkbox_type in settings.KICKBOT_CHECKBOXES:
            assert not config.cparser.value(checkbox_type, type=bool)
        config.cparser.endGroup()


def test_kick_chat_settings_update_kickbot_commands_existing_command(bootstrap):
    """Test command update doesn't overwrite existing commands."""
    config = bootstrap

    # Create existing command
    config.cparser.beginGroup('kickbot-command-track')
    config.cparser.setValue('anyone', True)
    config.cparser.endGroup()

    # Create template file in test directory
    test_template_dir = config.testdir / 'templates'
    config.templatedir = test_template_dir
    test_template_dir.mkdir(parents=True, exist_ok=True)
    (test_template_dir / 'kickbot_track.txt').write_text('Template content')

    settings = nowplaying.kick.settings.KickChatSettings()

    settings.update_kickbot_commands(config)

    # Existing command should not be overwritten
    config.cparser.beginGroup('kickbot-command-track')
    assert config.cparser.value('anyone', type=bool) is True
    config.cparser.endGroup()


@patch('nowplaying.kick.settings.QCheckBox')
@patch('nowplaying.kick.settings.QTableWidgetItem')
def test_kick_chat_settings_add_kickbot_command_row(mock_table_widget_item, mock_qcheckbox):
    """Test adding a command row to the table."""
    mock_widget = MagicMock()
    mock_widget.command_perm_table.rowCount.return_value = 0

    settings = nowplaying.kick.settings.KickChatSettings()
    settings._add_kickbot_command_row(mock_widget, '!test')

    mock_widget.command_perm_table.insertRow.assert_called_with(0)
    mock_widget.command_perm_table.setItem.assert_called_once()
    # Should call setCellWidget for each checkbox column (6 times)
    assert mock_widget.command_perm_table.setCellWidget.call_count == 6
