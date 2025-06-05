#!/usr/bin/env python3
"""Unit tests for Kick settings functionality."""

import pathlib
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

import nowplaying.kick.settings
import nowplaying.kick.oauth2
from nowplaying.exceptions import PluginVerifyError


class TestKickSettings:
    """Test cases for KickSettings class."""

    def test_init(self):
        """Test KickSettings initialization."""
        settings = nowplaying.kick.settings.KickSettings()
        
        assert settings.widget is None
        assert settings.oauth is None

    def test_connect(self):
        """Test settings connection."""
        settings = nowplaying.kick.settings.KickSettings()
        mock_uihelp = MagicMock()
        mock_widget = MagicMock()
        
        settings.connect(mock_uihelp, mock_widget)
        
        assert settings.widget == mock_widget
        mock_widget.authenticate_button.clicked.connect.assert_called_once()
        mock_widget.clientid_lineedit.editingFinished.connect.assert_called_once()
        mock_widget.secret_lineedit.editingFinished.connect.assert_called_once()
        mock_widget.redirecturi_lineedit.editingFinished.connect.assert_called_once()

    def test_load(self, bootstrap):
        """Test settings loading."""
        config = bootstrap
        config.cparser.setValue('kick/enabled', True)
        config.cparser.setValue('kick/channel', 'testchannel')
        config.cparser.setValue('kick/clientid', 'test_client_id')
        config.cparser.setValue('kick/secret', 'test_secret')
        config.cparser.setValue('kick/redirecturi', 'http://localhost:8080/callback')
        
        settings = nowplaying.kick.settings.KickSettings()
        mock_widget = MagicMock()
        
        settings.load(config, mock_widget)
        
        assert settings.widget == mock_widget
        mock_widget.enable_checkbox.setChecked.assert_called_with(True)
        mock_widget.channel_lineedit.setText.assert_called_with('testchannel')
        mock_widget.clientid_lineedit.setText.assert_called_with('test_client_id')
        mock_widget.secret_lineedit.setText.assert_called_with('test_secret')
        mock_widget.redirecturi_lineedit.setText.assert_called_with('http://localhost:8080/callback')
        assert isinstance(settings.oauth, nowplaying.kick.oauth2.KickOAuth2)

    def test_load_default_redirect_uri(self, bootstrap):
        """Test settings loading with default redirect URI."""
        config = bootstrap
        # Don't set redirect URI
        
        settings = nowplaying.kick.settings.KickSettings()
        mock_widget = MagicMock()
        
        settings.load(config, mock_widget)
        
        # Should set default redirect URI
        mock_widget.redirecturi_lineedit.setText.assert_called_with('http://localhost:8080/kickredirect')

    def test_save_no_changes(self, bootstrap):
        """Test settings saving with no changes."""
        config = bootstrap
        config.cparser.setValue('kick/channel', 'oldchannel')
        config.cparser.setValue('kick/clientid', 'oldclient')
        config.cparser.setValue('kick/secret', 'oldsecret')
        config.cparser.setValue('kick/redirecturi', 'olduri')
        
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = True
        mock_widget.channel_lineedit.text.return_value = 'oldchannel'
        mock_widget.clientid_lineedit.text.return_value = 'oldclient'
        mock_widget.secret_lineedit.text.return_value = 'oldsecret'
        mock_widget.redirecturi_lineedit.text.return_value = 'olduri'
        
        mock_subprocesses = MagicMock()
        
        nowplaying.kick.settings.KickSettings.save(config, mock_widget, mock_subprocesses)
        
        # Should not restart kickbot or clear tokens
        mock_subprocesses.stop_kickbot.assert_not_called()
        mock_subprocesses.start_kickbot.assert_not_called()

    def test_save_with_changes(self, bootstrap):
        """Test settings saving with changes."""
        config = bootstrap
        config.cparser.setValue('kick/channel', 'oldchannel')
        config.cparser.setValue('kick/clientid', 'oldclient')
        config.cparser.setValue('kick/secret', 'oldsecret')
        config.cparser.setValue('kick/redirecturi', 'olduri')
        config.cparser.setValue('kick/accesstoken', 'old_token')
        config.cparser.setValue('kick/refreshtoken', 'old_refresh')
        
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = True
        mock_widget.channel_lineedit.text.return_value = 'newchannel'
        mock_widget.clientid_lineedit.text.return_value = 'newclient'
        mock_widget.secret_lineedit.text.return_value = 'newsecret'
        mock_widget.redirecturi_lineedit.text.return_value = 'newuri'
        
        mock_subprocesses = MagicMock()
        
        with patch('time.sleep'):  # Speed up test
            nowplaying.kick.settings.KickSettings.save(config, mock_widget, mock_subprocesses)
        
        # Should restart kickbot and clear tokens
        mock_subprocesses.stop_kickbot.assert_called_once()
        mock_subprocesses.start_kickbot.assert_called_once()
        assert config.cparser.value('kick/accesstoken') is None
        assert config.cparser.value('kick/refreshtoken') is None

    def test_verify_disabled(self):
        """Test settings verification when disabled."""
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = False
        
        # Should not raise exception
        nowplaying.kick.settings.KickSettings.verify(mock_widget)

    def test_verify_missing_client_id(self):
        """Test settings verification with missing client ID."""
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = True
        mock_widget.clientid_lineedit.text.return_value = ''
        
        with pytest.raises(PluginVerifyError, match='Kick Client ID is required'):
            nowplaying.kick.settings.KickSettings.verify(mock_widget)

    def test_verify_missing_secret(self):
        """Test settings verification with missing secret."""
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = True
        mock_widget.clientid_lineedit.text.return_value = 'test_client'
        mock_widget.secret_lineedit.text.return_value = ''
        
        with pytest.raises(PluginVerifyError, match='Kick Client Secret is required'):
            nowplaying.kick.settings.KickSettings.verify(mock_widget)

    def test_verify_missing_redirect_uri(self):
        """Test settings verification with missing redirect URI."""
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = True
        mock_widget.clientid_lineedit.text.return_value = 'test_client'
        mock_widget.secret_lineedit.text.return_value = 'test_secret'
        mock_widget.redirecturi_lineedit.text.return_value = ''
        
        with pytest.raises(PluginVerifyError, match='Kick Redirect URI is required'):
            nowplaying.kick.settings.KickSettings.verify(mock_widget)

    def test_verify_missing_channel(self):
        """Test settings verification with missing channel."""
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = True
        mock_widget.clientid_lineedit.text.return_value = 'test_client'
        mock_widget.secret_lineedit.text.return_value = 'test_secret'
        mock_widget.redirecturi_lineedit.text.return_value = 'http://localhost:8080'
        mock_widget.channel_lineedit.text.return_value = ''
        
        with pytest.raises(PluginVerifyError, match='Kick Channel is required'):
            nowplaying.kick.settings.KickSettings.verify(mock_widget)

    def test_verify_invalid_redirect_uri(self):
        """Test settings verification with invalid redirect URI."""
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = True
        mock_widget.clientid_lineedit.text.return_value = 'test_client'
        mock_widget.secret_lineedit.text.return_value = 'test_secret'
        mock_widget.redirecturi_lineedit.text.return_value = 'invalid_uri'
        mock_widget.channel_lineedit.text.return_value = 'testchannel'
        
        with pytest.raises(PluginVerifyError, match='Kick Redirect URI must start with http'):
            nowplaying.kick.settings.KickSettings.verify(mock_widget)

    def test_verify_valid_settings(self):
        """Test settings verification with valid settings."""
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = True
        mock_widget.clientid_lineedit.text.return_value = 'test_client'
        mock_widget.secret_lineedit.text.return_value = 'test_secret'
        mock_widget.redirecturi_lineedit.text.return_value = 'http://localhost:8080'
        mock_widget.channel_lineedit.text.return_value = 'testchannel'
        
        # Should not raise exception
        nowplaying.kick.settings.KickSettings.verify(mock_widget)

    def test_authenticate_oauth(self, bootstrap):
        """Test OAuth authentication."""
        config = bootstrap
        settings = nowplaying.kick.settings.KickSettings()
        mock_widget = MagicMock()
        settings.widget = mock_widget
        
        # Mock OAuth
        mock_oauth = MagicMock()
        mock_oauth.open_browser_for_auth.return_value = True
        settings.oauth = mock_oauth
        
        settings.authenticate_oauth()
        
        mock_oauth.open_browser_for_auth.assert_called_once()

    def test_update_oauth_status_no_oauth(self, bootstrap):
        """Test OAuth status update with no OAuth handler."""
        settings = nowplaying.kick.settings.KickSettings()
        mock_widget = MagicMock()
        settings.widget = mock_widget
        settings.oauth = None
        
        # Should not crash
        settings.update_oauth_status()

    def test_update_oauth_status_no_tokens(self, bootstrap):
        """Test OAuth status update with no stored tokens."""
        settings = nowplaying.kick.settings.KickSettings()
        mock_widget = MagicMock()
        settings.widget = mock_widget
        
        # Mock OAuth with no tokens
        mock_oauth = MagicMock()
        mock_oauth.get_stored_tokens.return_value = (None, None)
        settings.oauth = mock_oauth
        
        settings.update_oauth_status()
        
        mock_widget.status_label.setText.assert_called_with('Not authenticated')

    def test_update_oauth_status_valid_token(self, bootstrap):
        """Test OAuth status update with valid token."""
        settings = nowplaying.kick.settings.KickSettings()
        mock_widget = MagicMock()
        settings.widget = mock_widget
        
        # Mock OAuth with valid token
        mock_oauth = MagicMock()
        mock_oauth.get_stored_tokens.return_value = ('valid_token', 'refresh_token')
        settings.oauth = mock_oauth
        settings._qtsafe_validate_kick_token = MagicMock(return_value=True)
        
        settings.update_oauth_status()
        
        # Should show authenticated status
        assert mock_widget.status_label.setText.called

    def test_qtsafe_validate_kick_token_success(self, bootstrap):
        """Test Qt-safe token validation success."""
        settings = nowplaying.kick.settings.KickSettings()
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'data': {
                'active': True,
                'client_id': 'test_client',
                'scope': 'user:read chat:write'
            }
        }
        
        with patch('requests.post', return_value=mock_response):
            result = settings._qtsafe_validate_kick_token('test_token')
            
            assert result is True

    def test_qtsafe_validate_kick_token_inactive(self, bootstrap):
        """Test Qt-safe token validation with inactive token."""
        settings = nowplaying.kick.settings.KickSettings()
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'data': {
                'active': False
            }
        }
        
        with patch('requests.post', return_value=mock_response):
            result = settings._qtsafe_validate_kick_token('test_token')
            
            assert result is False

    def test_qtsafe_validate_kick_token_error(self, bootstrap):
        """Test Qt-safe token validation with error."""
        settings = nowplaying.kick.settings.KickSettings()
        
        with patch('requests.post', side_effect=requests.RequestException("Network error")):
            result = settings._qtsafe_validate_kick_token('test_token')
            
            assert result is False

    def test_clear_authentication(self, bootstrap):
        """Test clearing authentication."""
        settings = nowplaying.kick.settings.KickSettings()
        
        # Mock OAuth
        mock_oauth = MagicMock()
        settings.oauth = mock_oauth
        settings.update_oauth_status = MagicMock()
        
        settings.clear_authentication()
        
        mock_oauth.clear_stored_tokens.assert_called_once()
        settings.update_oauth_status.assert_called_once()


class TestKickChatSettings:
    """Test cases for KickChatSettings class."""

    def test_init(self):
        """Test KickChatSettings initialization."""
        settings = nowplaying.kick.settings.KickChatSettings()
        
        assert settings.widget is None
        assert settings.KICKBOT_CHECKBOXES == ['anyone', 'broadcaster', 'moderator', 'subscriber', 'founder', 'vip']

    def test_connect_with_buttons(self):
        """Test settings connection with all buttons present."""
        settings = nowplaying.kick.settings.KickChatSettings()
        mock_uihelp = MagicMock()
        mock_widget = MagicMock()
        
        # Mock button attributes
        mock_widget.announce_button = MagicMock()
        mock_widget.add_button = MagicMock()
        mock_widget.del_button = MagicMock()
        
        settings.connect(mock_uihelp, mock_widget)
        
        assert settings.widget == mock_widget
        mock_widget.announce_button.clicked.connect.assert_called_once()
        mock_widget.add_button.clicked.connect.assert_called_once()
        mock_widget.del_button.clicked.connect.assert_called_once()

    def test_connect_without_buttons(self):
        """Test settings connection without buttons."""
        settings = nowplaying.kick.settings.KickChatSettings()
        mock_uihelp = MagicMock()
        mock_widget = MagicMock()
        
        # Remove button attributes
        del mock_widget.announce_button
        del mock_widget.add_button
        del mock_widget.del_button
        
        # Should not crash
        settings.connect(mock_uihelp, mock_widget)
        
        assert settings.widget == mock_widget

    def test_load_basic_settings(self, bootstrap):
        """Test loading basic chat settings."""
        config = bootstrap
        config.cparser.setValue('kick/chat', True)
        config.cparser.setValue('kick/announce', 'test_template.txt')
        config.cparser.setValue('kick/announcedelay', 2.5)
        
        settings = nowplaying.kick.settings.KickChatSettings()
        mock_widget = MagicMock()
        
        # Mock delay field as spin box
        mock_widget.announcedelay_spin = MagicMock()
        del mock_widget.announce_delay_lineedit
        
        settings.load(config, mock_widget)
        
        assert settings.widget == mock_widget
        mock_widget.enable_checkbox.setChecked.assert_called_with(True)
        mock_widget.announce_lineedit.setText.assert_called_with('test_template.txt')
        mock_widget.announcedelay_spin.setValue.assert_called_with(2.5)

    def test_load_with_lineedit_delay(self, bootstrap):
        """Test loading with line edit delay field."""
        config = bootstrap
        config.cparser.setValue('kick/announcedelay', 3.0)
        
        settings = nowplaying.kick.settings.KickChatSettings()
        mock_widget = MagicMock()
        
        # Mock delay field as line edit
        mock_widget.announce_delay_lineedit = MagicMock()
        del mock_widget.announcedelay_spin
        
        settings.load(config, mock_widget)
        
        mock_widget.announce_delay_lineedit.setText.assert_called_with('3.0')

    @patch('nowplaying.kick.settings.QCheckBox')
    @patch('nowplaying.kick.settings.QTableWidgetItem')
    def test_load_with_command_table(self, mock_table_item, mock_checkbox, bootstrap):
        """Test loading with command permission table."""
        config = bootstrap
        
        # Create test command configuration
        config.cparser.beginGroup('kickbot-command-track')
        config.cparser.setValue('anyone', True)
        config.cparser.setValue('broadcaster', True)
        config.cparser.setValue('moderator', False)
        config.cparser.endGroup()
        
        settings = nowplaying.kick.settings.KickChatSettings()
        mock_widget = MagicMock()
        
        # Mock command table
        mock_widget.command_perm_table = MagicMock()
        mock_widget.command_perm_table.setRowCount = MagicMock()
        mock_widget.command_perm_table.rowCount.return_value = 1
        
        # Mock checkboxes
        mock_checkbox_anyone = MagicMock()
        mock_checkbox_broadcaster = MagicMock()
        mock_widget.command_perm_table.cellWidget.side_effect = [
            mock_checkbox_anyone, mock_checkbox_broadcaster, None, None, None, None
        ]
        
        settings.load(config, mock_widget)
        
        # Verify table was reset and command was loaded
        mock_widget.command_perm_table.setRowCount.assert_called_with(0)

    def test_kickbot_command_load(self, bootstrap):
        """Test loading kickbot commands into table."""
        config = bootstrap
        
        # Create test command
        config.cparser.beginGroup('kickbot-command-track')
        config.cparser.setValue('anyone', True)
        config.cparser.setValue('broadcaster', False)
        config.cparser.endGroup()
        
        settings = nowplaying.kick.settings.KickChatSettings()
        mock_widget = MagicMock()
        mock_widget.command_perm_table = MagicMock()
        mock_widget.command_perm_table.setRowCount = MagicMock()
        mock_widget.command_perm_table.rowCount.return_value = 1
        
        # Mock add command row
        settings._add_kickbot_command_row = MagicMock()
        
        settings._kickbot_command_load(config, mock_widget)
        
        mock_widget.command_perm_table.setRowCount.assert_called_with(0)
        settings._add_kickbot_command_row.assert_called_with(mock_widget, '!track')

    @patch('nowplaying.kick.settings.QCheckBox')
    @patch('nowplaying.kick.settings.QTableWidgetItem')
    def test_add_kickbot_command_row(self, mock_table_item, mock_checkbox, bootstrap):
        """Test adding a command row to the table."""
        settings = nowplaying.kick.settings.KickChatSettings()
        mock_widget = MagicMock()
        mock_widget.command_perm_table = MagicMock()
        mock_widget.command_perm_table.rowCount.return_value = 0
        
        settings._add_kickbot_command_row(mock_widget, '!test')
        
        mock_widget.command_perm_table.insertRow.assert_called_with(0)
        mock_widget.command_perm_table.setItem.assert_called_once()
        # Should call setCellWidget for each checkbox column (6 times)
        assert mock_widget.command_perm_table.setCellWidget.call_count == 6

    def test_save_basic_settings(self, bootstrap):
        """Test saving basic chat settings."""
        config = bootstrap
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = True
        mock_widget.announce_lineedit.text.return_value = 'new_template.txt'
        mock_widget.announcedelay_spin.value.return_value = 2.5
        
        # Remove line edit delay field
        del mock_widget.announce_delay_lineedit
        
        mock_subprocesses = MagicMock()
        
        nowplaying.kick.settings.KickChatSettings.save(config, mock_widget, mock_subprocesses)
        
        assert config.cparser.value('kick/chat', type=bool) is True
        assert config.cparser.value('kick/announce') == 'new_template.txt'
        assert config.cparser.value('kick/announcedelay', type=float) == 2.5

    def test_save_with_lineedit_delay(self, bootstrap):
        """Test saving with line edit delay field."""
        config = bootstrap
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = False
        mock_widget.announce_lineedit.text.return_value = ''
        mock_widget.announce_delay_lineedit.text.return_value = '1.5'
        
        # Remove spin box delay field
        del mock_widget.announcedelay_spin
        
        mock_subprocesses = MagicMock()
        
        nowplaying.kick.settings.KickChatSettings.save(config, mock_widget, mock_subprocesses)
        
        assert config.cparser.value('kick/announcedelay', type=float) == 1.5

    def test_save_invalid_delay(self, bootstrap):
        """Test saving with invalid delay value."""
        config = bootstrap
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = False
        mock_widget.announce_lineedit.text.return_value = ''
        mock_widget.announce_delay_lineedit.text.return_value = 'invalid'
        
        # Remove spin box delay field
        del mock_widget.announcedelay_spin
        
        mock_subprocesses = MagicMock()
        
        nowplaying.kick.settings.KickChatSettings.save(config, mock_widget, mock_subprocesses)
        
        # Should default to 1.0
        assert config.cparser.value('kick/announcedelay', type=float) == 1.0

    def test_save_kickbot_commands(self, bootstrap):
        """Test saving kickbot command permissions."""
        config = bootstrap
        
        # Create existing command to be removed
        config.cparser.beginGroup('kickbot-command-oldcommand')
        config.cparser.setValue('anyone', True)
        config.cparser.endGroup()
        
        mock_widget = MagicMock()
        mock_widget.command_perm_table = MagicMock()
        mock_widget.command_perm_table.rowCount.return_value = 1
        
        # Mock table item
        mock_item = MagicMock()
        mock_item.text.return_value = '!newcommand'
        mock_widget.command_perm_table.item.return_value = mock_item
        
        # Mock checkboxes
        mock_checkbox = MagicMock()
        mock_checkbox.isChecked.return_value = True
        mock_widget.command_perm_table.cellWidget.return_value = mock_checkbox
        
        nowplaying.kick.settings.KickChatSettings._save_kickbot_commands(config, mock_widget)
        
        # Old command should be removed
        assert not config.cparser.childGroups().__contains__('kickbot-command-oldcommand')
        
        # New command should be saved
        config.cparser.beginGroup('kickbot-command-newcommand')
        assert config.cparser.value('anyone', type=bool) is True
        config.cparser.endGroup()

    def test_verify_enabled_no_template(self):
        """Test verification fails when enabled but no template."""
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = True
        mock_widget.announce_lineedit.text.return_value = ''
        
        with pytest.raises(PluginVerifyError, match='Kick announcement template is required'):
            nowplaying.kick.settings.KickChatSettings.verify(mock_widget)

    def test_verify_disabled(self):
        """Test verification passes when disabled."""
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = False
        
        # Should not raise exception
        nowplaying.kick.settings.KickChatSettings.verify(mock_widget)

    def test_verify_enabled_with_template(self):
        """Test verification passes when enabled with template."""
        mock_widget = MagicMock()
        mock_widget.enable_checkbox.isChecked.return_value = True
        mock_widget.announce_lineedit.text.return_value = 'template.txt'
        
        # Should not raise exception
        nowplaying.kick.settings.KickChatSettings.verify(mock_widget)

    def test_update_kickbot_commands_no_template_dir(self, bootstrap):
        """Test command update with no template directory."""
        config = bootstrap
        # Set non-existent template directory
        config.templatedir = pathlib.Path('/non/existent/path')
        
        settings = nowplaying.kick.settings.KickChatSettings()
        
        # Should not crash
        settings.update_kickbot_commands(config)

    def test_update_kickbot_commands_no_templates(self, bootstrap):
        """Test command update with no kickbot templates."""
        config = bootstrap
        
        settings = nowplaying.kick.settings.KickChatSettings()
        
        # Should not crash (no kickbot_*.txt files in template dir)
        settings.update_kickbot_commands(config)

    def test_update_kickbot_commands_with_templates(self, bootstrap):
        """Test command update with kickbot templates."""
        config = bootstrap
        
        # Create test template files
        template_dir = pathlib.Path(bootstrap.templatedir)
        (template_dir / 'kickbot_track.txt').write_text('Template content')
        (template_dir / 'kickbot_artist.txt').write_text('Template content')
        
        settings = nowplaying.kick.settings.KickChatSettings()
        
        settings.update_kickbot_commands(config)
        
        # Should create command entries
        assert 'kickbot-command-track' in config.cparser.childGroups()
        assert 'kickbot-command-artist' in config.cparser.childGroups()
        
        # Verify default permissions (all disabled)
        config.cparser.beginGroup('kickbot-command-track')
        for checkbox_type in settings.KICKBOT_CHECKBOXES:
            assert config.cparser.value(checkbox_type, type=bool) is False
        config.cparser.endGroup()

    def test_update_kickbot_commands_existing_command(self, bootstrap):
        """Test command update doesn't overwrite existing commands."""
        config = bootstrap
        
        # Create existing command
        config.cparser.beginGroup('kickbot-command-track')
        config.cparser.setValue('anyone', True)
        config.cparser.endGroup()
        
        # Create template file
        template_dir = pathlib.Path(bootstrap.templatedir)
        (template_dir / 'kickbot_track.txt').write_text('Template content')
        
        settings = nowplaying.kick.settings.KickChatSettings()
        
        settings.update_kickbot_commands(config)
        
        # Existing command should not be overwritten
        config.cparser.beginGroup('kickbot-command-track')
        assert config.cparser.value('anyone', type=bool) is True
        config.cparser.endGroup()