#!/usr/bin/env python3
''' kick settings '''

import logging
import time
from typing import Any

import requests

from PySide6.QtWidgets import QCheckBox, QTableWidgetItem  # pylint: disable=no-name-in-module

from nowplaying.exceptions import PluginVerifyError
import nowplaying.config
import nowplaying.kick.oauth2


class KickSettings:
    ''' for settings UI '''

    def __init__(self) -> None:
        self.widget: Any = None
        self.oauth: nowplaying.kick.oauth2.KickOAuth2 | None = None

    def connect(self, uihelp: Any, widget: Any) -> None:  # pylint: disable=unused-argument
        '''  connect kick '''
        self.widget = widget
        widget.authenticate_button.clicked.connect(self.authenticate_oauth)
        widget.clientid_lineedit.editingFinished.connect(self.update_oauth_status)
        widget.secret_lineedit.editingFinished.connect(self.update_oauth_status)
        widget.redirecturi_lineedit.editingFinished.connect(self.update_oauth_status)

    def load(self, config: nowplaying.config.ConfigFile, widget: Any) -> None:
        ''' load the settings window '''
        self.widget = widget
        widget.enable_checkbox.setChecked(config.cparser.value('kick/enabled', type=bool))
        widget.channel_lineedit.setText(config.cparser.value('kick/channel'))
        widget.clientid_lineedit.setText(config.cparser.value('kick/clientid'))
        widget.secret_lineedit.setText(config.cparser.value('kick/secret'))
        widget.redirecturi_lineedit.setText(
            config.cparser.value('kick/redirecturi') or 'http://localhost:8080/kickredirect')

        # Initialize OAuth2 handler
        self.oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        self.update_oauth_status()

    @staticmethod
    def save(config: nowplaying.config.ConfigFile, widget: Any, subprocesses: Any) -> None:
        ''' update the kick settings '''
        oldchannel = config.cparser.value('kick/channel')
        newchannel = widget.channel_lineedit.text()
        oldclientid = config.cparser.value('kick/clientid')
        newclientid = widget.clientid_lineedit.text()
        oldsecret = config.cparser.value('kick/secret')
        newsecret = widget.secret_lineedit.text()
        oldredirecturi = config.cparser.value('kick/redirecturi')
        newredirecturi = widget.redirecturi_lineedit.text()

        config.cparser.setValue('kick/enabled', widget.enable_checkbox.isChecked())
        config.cparser.setValue('kick/channel', newchannel)
        config.cparser.setValue('kick/clientid', newclientid)
        config.cparser.setValue('kick/secret', newsecret)
        config.cparser.setValue('kick/redirecturi', newredirecturi)

        # If critical settings changed, restart kick bot and clear tokens
        if (oldchannel != newchannel) or (oldclientid != newclientid) or (
                oldsecret != newsecret) or (oldredirecturi != newredirecturi):
            # Stop kick bot if running
            subprocesses.stop_kickbot()

            # Clear stored OAuth tokens since config changed
            config.cparser.remove('kick/accesstoken')
            config.cparser.remove('kick/refreshtoken')
            config.cparser.sync()

            time.sleep(2)
            subprocesses.start_kickbot()

    @staticmethod
    def verify(widget: Any) -> None:
        ''' verify the settings are good '''
        if not widget.enable_checkbox.isChecked():
            return

        # Check required fields
        if not widget.clientid_lineedit.text().strip():
            raise PluginVerifyError('Kick Client ID is required')

        if not widget.secret_lineedit.text().strip():
            raise PluginVerifyError('Kick Client Secret is required')

        if not widget.redirecturi_lineedit.text().strip():
            raise PluginVerifyError('Kick Redirect URI is required')

        if not widget.channel_lineedit.text().strip():
            raise PluginVerifyError('Kick Channel is required')

        # Validate redirect URI format
        redirect_uri = widget.redirecturi_lineedit.text().strip()
        if not redirect_uri.startswith('http://') and not redirect_uri.startswith('https://'):
            raise PluginVerifyError('Kick Redirect URI must start with http:// or https://')

    def authenticate_oauth(self) -> None:
        ''' initiate OAuth2 authentication flow '''
        if not self.oauth:
            logging.error('OAuth2 handler not initialized')
            return

        # Update config with current form values
        if self.widget:
            self.oauth.client_id = self.widget.clientid_lineedit.text().strip()
            self.oauth.client_secret = self.widget.secret_lineedit.text().strip()
            self.oauth.redirect_uri = self.widget.redirecturi_lineedit.text().strip()

        # Validate required fields
        if not self.oauth.client_id:
            self.widget.oauth_status_label.setText('Error: Client ID required')
            return
        if not self.oauth.client_secret:
            self.widget.oauth_status_label.setText('Error: Client Secret required')
            return
        if not self.oauth.redirect_uri:
            self.widget.oauth_status_label.setText('Error: Redirect URI required')
            return

        try:
            # Open browser for authentication
            if self.oauth.open_browser_for_auth():
                self.widget.oauth_status_label.setText('Browser opened - complete authentication')
                self.widget.authenticate_button.setText('Authentication in progress...')
                self.widget.authenticate_button.setEnabled(False)

                # Start checking for authentication completion
                # Note: In a real implementation, you'd want to monitor the webserver
                # for the OAuth callback and automatically update the status
                logging.info('Kick OAuth2 authentication initiated')
            else:
                self.widget.oauth_status_label.setText('Failed to open browser')
        except Exception as error:
            logging.error('Kick OAuth2 authentication error: %s', error)
            self.widget.oauth_status_label.setText(f'Authentication error: {error}')

    def update_oauth_status(self) -> None:
        ''' update the OAuth status display '''
        if not self.oauth or not self.widget:
            return

        # Reset button state
        self.widget.authenticate_button.setText('Authenticate with Kick')
        self.widget.authenticate_button.setEnabled(True)

        # Check if we have valid configuration
        client_id = self.widget.clientid_lineedit.text().strip()
        client_secret = self.widget.secret_lineedit.text().strip()
        redirect_uri = self.widget.redirecturi_lineedit.text().strip()

        if not client_id or not client_secret or not redirect_uri:
            self.widget.oauth_status_label.setText('Configuration incomplete')
            return

        # Check for stored tokens and validate them
        access_token, refresh_token = self.oauth.get_stored_tokens()

        if access_token:
            # Validate token synchronously like Twitch does
            if self._qtsafe_validate_kick_token(access_token):
                self.widget.oauth_status_label.setText('Authenticated (valid)')
                self.widget.authenticate_button.setText('Re-authenticate')
            else:
                self.widget.oauth_status_label.setText(
                    'Authentication expired - please re-authenticate')
                self.widget.authenticate_button.setText('Authenticate')
                # Don't auto-clear tokens here - let the user decide
        else:
            self.widget.oauth_status_label.setText('Not authenticated')

    def _qtsafe_validate_kick_token(self, access_token: str) -> bool:
        ''' validate kick token synchronously (like Twitch qtsafe_validate_token) '''
        if not access_token:
            return False

        # Use Kick's token introspect endpoint to validate the token
        url = 'https://api.kick.com/public/v1/token/introspect'
        headers = {'Authorization': f'Bearer {access_token}'}

        try:
            req = requests.post(url, headers=headers, timeout=5)
        except Exception as error:  # pylint: disable=broad-except
            logging.error('Kick token validation check failed: %s', error)
            return False

        if req.status_code == 200:
            try:
                response_data = req.json()
                data = response_data.get('data', {})

                # Check if token is active
                if data.get('active'):
                    client_id = data.get('client_id', 'Unknown')
                    scopes = data.get('scope', 'Unknown')
                    logging.debug('Kick token valid for client: %s, scopes: %s', client_id, scopes)
                    return True
                else:
                    logging.debug('Kick token is inactive')
                    return False
            except Exception as error:  # pylint: disable=broad-except
                logging.error('Kick token validation/bad json: %s', error)
                return False
        elif req.status_code == 401:
            logging.debug('Kick token is invalid/expired')
            return False
        else:
            logging.warning('Kick token validation returned status %s', req.status_code)
            return False

    def clear_authentication(self) -> None:
        ''' clear stored authentication tokens '''
        if self.oauth:
            self.oauth.clear_stored_tokens()
            self.update_oauth_status()
            logging.info('Cleared Kick OAuth2 authentication')


class KickChatSettings:
    ''' Kick chat settings for UI (exactly mirrors TwitchChatSettings pattern) '''

    # Define Kick permission checkboxes (matches table columns)
    KICKBOT_CHECKBOXES: list[str] = [
        'anyone', 'broadcaster', 'moderator', 'subscriber', 'founder', 'vip'
    ]

    def __init__(self) -> None:
        self.widget: Any = None

    def connect(self, uihelp: Any, widget: Any) -> None:
        ''' connect kick chat settings '''
        self.widget = widget
        # Connect template button
        if hasattr(widget, 'announce_button'):
            widget.announce_button.clicked.connect(lambda: uihelp.template_picker_lineedit(
                widget.announce_lineedit, limit='kickbot_*.txt'))

        # Connect add/delete buttons
        if hasattr(widget, 'add_button'):
            widget.add_button.clicked.connect(lambda: uihelp.template_picker_table(
                widget.command_perm_table, limit='kickbot_*.txt'))
        if hasattr(widget, 'del_button'):
            widget.del_button.clicked.connect(
                lambda: uihelp.table_remove_row(widget.command_perm_table))

    def load(self, config: nowplaying.config.ConfigFile, widget: Any) -> None:
        ''' load kick chat settings '''
        self.widget = widget
        widget.enable_checkbox.setChecked(config.cparser.value('kick/chat', type=bool))
        widget.announce_lineedit.setText(config.cparser.value('kick/announce') or '')

        # Handle delay field
        if hasattr(widget, 'announce_delay_lineedit'):
            delay_value = config.cparser.value('kick/announcedelay', type=float) or 1.0
            widget.announce_delay_lineedit.setText(str(delay_value))
        elif hasattr(widget, 'announcedelay_spin'):
            widget.announcedelay_spin.setValue(
                config.cparser.value('kick/announcedelay', type=float) or 1.0)

        # Load permission table
        if hasattr(widget, 'command_perm_table'):
            self._kickbot_command_load(config, widget)

    def _kickbot_command_load(self, config: nowplaying.config.ConfigFile, widget: Any) -> None:
        ''' load kickbot commands into permission table (mirrors TwitchChatSettings) '''
        widget.command_perm_table.setRowCount(0)

        # Load commands from config groups starting with 'kickbot-command-'
        for group in config.cparser.childGroups():
            if group.startswith('kickbot-command-'):
                command = group.replace('kickbot-command-', '!')
                self._add_kickbot_command_row(widget, command)

                config.cparser.beginGroup(group)
                # Set checkbox states for each permission
                for col, checkbox_type in enumerate(self.KICKBOT_CHECKBOXES, 1):
                    checkbox_value = config.cparser.value(checkbox_type, type=bool)
                    checkbox = widget.command_perm_table.cellWidget(
                        widget.command_perm_table.rowCount() - 1, col)
                    if checkbox:
                        checkbox.setChecked(checkbox_value)
                config.cparser.endGroup()

    def _add_kickbot_command_row(self, widget: Any, command: str) -> None:
        ''' add a command row to the permission table (mirrors TwitchChatSettings) '''
        row = widget.command_perm_table.rowCount()
        widget.command_perm_table.insertRow(row)

        # Column 0: Command name
        widget.command_perm_table.setItem(row, 0, QTableWidgetItem(command))

        # Columns 1-6: Permission checkboxes
        for col, checkbox_type in enumerate(self.KICKBOT_CHECKBOXES, 1):
            checkbox = QCheckBox()
            checkbox.setChecked(False)  # Default to disabled
            widget.command_perm_table.setCellWidget(row, col, checkbox)

    @staticmethod
    def save(config: nowplaying.config.ConfigFile, widget: Any, subprocesses: Any) -> None:
        ''' save kick chat settings '''
        config.cparser.setValue('kick/chat', widget.enable_checkbox.isChecked())
        config.cparser.setValue('kick/announce', widget.announce_lineedit.text())

        # Handle delay field
        delay_value = 1.0
        if hasattr(widget, 'announce_delay_lineedit'):
            try:
                delay_value = float(widget.announce_delay_lineedit.text())
            except (ValueError, AttributeError):
                delay_value = 1.0
        elif hasattr(widget, 'announcedelay_spin'):
            delay_value = widget.announcedelay_spin.value()

        config.cparser.setValue('kick/announcedelay', delay_value)

        # Save permission table
        if hasattr(widget, 'command_perm_table'):
            KickChatSettings._save_kickbot_commands(config, widget)

    @staticmethod
    def _save_kickbot_commands(config: nowplaying.config.ConfigFile, widget: Any) -> None:
        ''' save kickbot command permissions (mirrors TwitchChatSettings) '''

        def reset_commands():
            # Clear existing commands
            for group in config.cparser.childGroups():
                if group.startswith('kickbot-command-'):
                    config.cparser.remove(group)

        reset_commands()

        # Save current commands and their permissions
        for row in range(widget.command_perm_table.rowCount()):
            command_item = widget.command_perm_table.item(row, 0)

            if command_item:
                command = command_item.text().strip()
                if command:
                    # Remove ! prefix for group name
                    group_name = f'kickbot-command-{command.replace("!", "")}'
                    config.cparser.beginGroup(group_name)

                    # Save checkbox states for each permission
                    for col, checkbox_type in enumerate(KickChatSettings.KICKBOT_CHECKBOXES, 1):
                        checkbox = widget.command_perm_table.cellWidget(row, col)
                        if checkbox:
                            config.cparser.setValue(checkbox_type, checkbox.isChecked())

                    config.cparser.endGroup()

    @staticmethod
    def verify(widget: Any) -> None:
        ''' verify kick chat settings '''
        if widget.enable_checkbox.isChecked():
            if not widget.announce_lineedit.text().strip():
                raise PluginVerifyError(
                    'Kick announcement template is required when chat is enabled')

    def update_kickbot_commands(self, config: nowplaying.config.ConfigFile) -> None:
        ''' auto-discover kickbot templates and create default commands (mirrors TwitchChatSettings) '''
        template_dir = config.templatedir

        if not template_dir.exists():
            logging.debug('Template directory does not exist: %s', template_dir)
            return

        # Find all kickbot template files
        kickbot_templates = list(template_dir.glob('kickbot_*.txt'))

        if not kickbot_templates:
            logging.debug('No kickbot templates found in %s', template_dir)
            return

        # Create default command entries for templates that don't have config entries
        for template_path in kickbot_templates:
            template_name = template_path.stem  # Remove .txt extension
            command_name = template_name.replace('kickbot_', '')  # Convert kickbot_track -> track
            group_name = f'kickbot-command-{command_name}'

            # Check if this command already exists
            config.cparser.beginGroup(group_name)
            existing_keys = config.cparser.childKeys()
            config.cparser.endGroup()

            if not existing_keys:
                # Create default command entry with all permissions disabled
                config.cparser.beginGroup(group_name)
                for checkbox_type in self.KICKBOT_CHECKBOXES:
                    config.cparser.setValue(checkbox_type, False)
                config.cparser.endGroup()
                logging.info('Auto-created Kick command: !%s -> %s', command_name,
                             template_path.name)
