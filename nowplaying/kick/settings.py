#!/usr/bin/env python3
''' kick settings '''

import logging
import os
from typing import Any

from PySide6.QtWidgets import QCheckBox, QTableWidgetItem  # pylint: disable=no-name-in-module
from PySide6.QtCore import Slot, QTimer  # pylint: disable=no-name-in-module

from nowplaying.exceptions import PluginVerifyError
import nowplaying.config
import nowplaying.kick.oauth2
import nowplaying.kick.utils


class KickSettings:
    ''' for settings UI '''

    def __init__(self) -> None:
        self.widget: Any = None
        self.oauth: nowplaying.kick.oauth2.KickOAuth2 | None = None
        self.refresh_token: str | None = None
        self.status_timer: QTimer | None = None

    def connect(self, uihelp: Any, widget: Any) -> None:  # pylint: disable=unused-argument
        '''  connect kick '''
        self.widget = widget
        widget.authenticate_button.clicked.connect(self.authenticate_oauth)
        widget.clientid_lineedit.editingFinished.connect(self.update_oauth_status)
        widget.secret_lineedit.editingFinished.connect(self.update_oauth_status)

    def load(self, config: nowplaying.config.ConfigFile, widget: Any) -> None:
        ''' load the settings window '''
        self.widget = widget
        widget.enable_checkbox.setChecked(config.cparser.value('kick/enabled', type=bool))
        widget.channel_lineedit.setText(config.cparser.value('kick/channel'))
        widget.clientid_lineedit.setText(config.cparser.value('kick/clientid'))
        widget.secret_lineedit.setText(config.cparser.value('kick/secret'))

        # Always set redirect URI to match webserver port (not user-configurable)
        webserver_port = config.cparser.value('weboutput/httpport', '8899')
        redirect_uri = f'http://localhost:{webserver_port}/kickredirect'
        widget.redirecturi_label.setText(redirect_uri)

        # Initialize OAuth2 handler
        self.oauth = nowplaying.kick.oauth2.KickOAuth2(config)
        self.update_oauth_status()
        # Timer disabled to prevent blocking main thread
        # self.start_status_timer()

    @staticmethod
    def save(config: nowplaying.config.ConfigFile, widget: Any, subprocesses: Any) -> None:
        ''' update the kick settings '''
        oldchannel = config.cparser.value('kick/channel')
        newchannel = widget.channel_lineedit.text()
        oldclientid = config.cparser.value('kick/clientid')
        newclientid = widget.clientid_lineedit.text()
        oldsecret = config.cparser.value('kick/secret')
        newsecret = widget.secret_lineedit.text()
        config.cparser.setValue('kick/enabled', widget.enable_checkbox.isChecked())
        config.cparser.setValue('kick/channel', newchannel)
        config.cparser.setValue('kick/clientid', newclientid)
        config.cparser.setValue('kick/secret', newsecret)
        # Note: redirect URI is not saved - it's always generated from webserver port

        # If critical settings changed, restart kick bot and clear tokens
        if (oldchannel != newchannel) or (oldclientid != newclientid) or (oldsecret != newsecret):
            # Stop kick bot if running
            subprocesses.stop_kickbot()

            # Clear stored OAuth tokens since config changed
            config.cparser.remove('kick/accesstoken')
            config.cparser.remove('kick/refreshtoken')
            config.cparser.sync()

            # Use QTimer for non-blocking delay to keep UI responsive
            QTimer.singleShot(2000, subprocesses.start_kickbot)

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

        if not widget.channel_lineedit.text().strip():
            raise PluginVerifyError('Kick Channel is required')

        # Note: redirect URI validation removed - it's auto-generated and not user-configurable

    def authenticate_oauth(self) -> None:
        ''' initiate OAuth2 authentication flow '''
        if not self.oauth:
            logging.error('OAuth2 handler not initialized')
            return

        # Update config with current form values
        if self.widget:
            self.oauth.client_id = self.widget.clientid_lineedit.text().strip()
            self.oauth.client_secret = self.widget.secret_lineedit.text().strip()
            # Redirect URI is set dynamically by webserver, not stored here
            self.oauth.redirect_uri = self.widget.redirecturi_label.text().strip()

        # Validate required fields
        if not self.oauth.client_id:
            self.widget.oauth_status_label.setText('Error: Client ID required')
            return
        if not self.oauth.client_secret:
            self.widget.oauth_status_label.setText('Error: Client Secret required')
            return
        # Note: redirect URI is always valid since it's auto-generated

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
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error('Kick OAuth2 authentication error: %s', error)
            self.widget.oauth_status_label.setText(f'Authentication error: {error}')

    def start_status_timer(self) -> None:
        ''' Start periodic status updates to catch automatic token refresh '''
        if not self.status_timer:
            self.status_timer = QTimer()
            self.status_timer.timeout.connect(self.update_oauth_status)
            # Check every 30 seconds for token status changes
            self.status_timer.start(30000)

    def stop_status_timer(self) -> None:
        ''' Stop periodic status updates '''
        if self.status_timer:
            self.status_timer.stop()
            self.status_timer = None

    def cleanup(self) -> None:
        ''' Clean up resources when settings UI is closed '''
        self.stop_status_timer()

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
        # Note: redirect URI is always valid since it's auto-generated

        if not client_id or not client_secret:
            self.widget.oauth_status_label.setText('Configuration incomplete')
            return

        # Check for stored tokens and validate them
        access_token, refresh_token = self.oauth.get_stored_tokens()

        if access_token:
            # Validate token synchronously like Twitch does
            if nowplaying.kick.oauth2.KickOAuth2.validate_token_sync(access_token):
                self.widget.oauth_status_label.setText('Authenticated')
                self.widget.authenticate_button.setText('Re-authenticate')
            elif refresh_token:
                self.widget.oauth_status_label.setText('Refreshing expired token...')
            else:
                self.widget.oauth_status_label.setText('Token expired - re-authentication needed')
                self.widget.authenticate_button.setText('Authenticate')
        else:
            self.widget.oauth_status_label.setText('Not authenticated')

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
        self.uihelp: Any = None

    def connect(self, uihelp: Any, widget: Any) -> None:
        ''' connect kick chat settings '''
        self.widget = widget
        self.uihelp = uihelp
        # Connect buttons with hasattr checks for robustness
        if hasattr(widget, 'announce_button'):
            widget.announce_button.clicked.connect(self.on_announce_button)
        if hasattr(widget, 'add_button'):
            widget.add_button.clicked.connect(self.on_add_button)
        if hasattr(widget, 'del_button'):
            widget.del_button.clicked.connect(self.on_del_button)

    @Slot()
    def on_announce_button(self) -> None:
        ''' kick announce button clicked action '''
        self.uihelp.template_picker_lineedit(self.widget.announce_lineedit, limit='kickbot_*.txt')

    @Slot()
    def on_add_button(self) -> None:
        ''' kick add button clicked action '''
        filename = self.uihelp.template_picker(limit='kickbot_*.txt')
        if not filename:
            return

        filename = os.path.basename(filename)
        filename = filename.replace('kickbot_', '')
        command = filename.replace('.txt', '')

        self._add_kickbot_command_row(self.widget, f'!{command}')

    @Slot()
    def on_del_button(self) -> None:
        ''' kick del button clicked action '''
        if items := self.widget.command_perm_table.selectedIndexes():
            self.widget.command_perm_table.removeRow(items[0].row())

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

                config.cparser.beginGroup(group)
                # Read permission values from config
                permissions = {}
                for checkbox_type in self.KICKBOT_CHECKBOXES:
                    permissions[checkbox_type] = config.cparser.value(checkbox_type, type=bool)
                config.cparser.endGroup()

                # Add row with permissions
                self._add_kickbot_command_row(widget, command, **permissions)

    def _add_kickbot_command_row(self, widget: Any, command: str, **kwargs: Any) -> None:
        ''' add a command row to the permission table (mirrors TwitchChatSettings) '''
        row = widget.command_perm_table.rowCount()
        widget.command_perm_table.insertRow(row)

        # Column 0: Command name
        widget.command_perm_table.setItem(row, 0, QTableWidgetItem(command))

        # Columns 1-6: Permission checkboxes
        for col, checkbox_type in enumerate(self.KICKBOT_CHECKBOXES, 1):
            checkbox = QCheckBox()
            if checkbox_type in kwargs:
                checkbox.setChecked(kwargs[checkbox_type])
            else:
                checkbox.setChecked(False)  # Default to disabled for new commands
            widget.command_perm_table.setCellWidget(row, col, checkbox)

    @staticmethod
    def save(config: nowplaying.config.ConfigFile, widget: Any, subprocesses: Any) -> None:
        ''' save kick chat settings '''
        oldchat = config.cparser.value('kick/chat', type=bool)
        oldannounce = config.cparser.value('kick/announce')

        newchat = widget.enable_checkbox.isChecked()
        newannounce = widget.announce_lineedit.text()

        config.cparser.setValue('kick/chat', newchat)
        config.cparser.setValue('kick/announce', newannounce)

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

        # If chat settings changed, restart kick bot
        if (oldchat != newchat) or (oldannounce != newannounce):
            subprocesses.stop_kickbot()
            # Use QTimer for non-blocking delay to keep UI responsive
            QTimer.singleShot(2000, subprocesses.start_kickbot)

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

            if command_item and (command := command_item.text().strip()):
                # Remove ! prefix for group name
                group_name = f'kickbot-command-{command.replace("!", "")}'
                config.cparser.beginGroup(group_name)

                # Save checkbox states for each permission
                for col, checkbox_type in enumerate(KickChatSettings.KICKBOT_CHECKBOXES, 1):
                    if checkbox := widget.command_perm_table.cellWidget(row, col):
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
        ''' auto-discover kickbot templates and create default commands '''
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
