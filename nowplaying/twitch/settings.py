#!/usr/bin/env python3
''' twitch settings '''

import logging
import time

from PySide6.QtWidgets import QMessageBox, QApplication  # pylint: disable=no-name-in-module
from PySide6.QtCore import QTimer  # pylint: disable=no-name-in-module

from nowplaying.exceptions import PluginVerifyError

import nowplaying.twitch.utils
import nowplaying.twitch.oauth2
from nowplaying.twitch.constants import CHAT_BOT_SCOPE_STRINGS


class TwitchSettings:
    ''' for settings UI '''

    def __init__(self):
        self.widget = None
        self.uihelp = None
        self.oauth = None
        self.status_timer = None

    def connect(self, uihelp, widget):
        '''  connect twitch '''
        self.widget = widget
        self.uihelp = uihelp

        # Connect OAuth buttons - dual token support
        if hasattr(widget, 'copy_broadcaster_auth_button'):
            widget.copy_broadcaster_auth_button.clicked.connect(self._copy_broadcaster_auth_link)
        if hasattr(widget, 'copy_chat_auth_button'):
            widget.copy_chat_auth_button.clicked.connect(self._copy_chat_auth_link)

        # Backward compatibility for old single button UI
        if hasattr(widget, 'copy_auth_link_button'):
            widget.copy_auth_link_button.clicked.connect(self._copy_auth_link)

        if hasattr(widget, 'clientid_lineedit'):
            widget.clientid_lineedit.editingFinished.connect(self.update_oauth_status)
        if hasattr(widget, 'secret_lineedit'):
            widget.secret_lineedit.editingFinished.connect(self.update_oauth_status)
        if hasattr(widget, 'redirecturi_lineedit'):
            widget.redirecturi_lineedit.editingFinished.connect(self.update_oauth_status)

    def load(self, config, widget):
        ''' load the settings window '''
        self.widget = widget
        widget.enable_checkbox.setChecked(config.cparser.value('twitchbot/enabled', type=bool))
        widget.clientid_lineedit.setText(config.cparser.value('twitchbot/clientid'))
        widget.channel_lineedit.setText(config.cparser.value('twitchbot/channel'))
        widget.secret_lineedit.setText(config.cparser.value('twitchbot/secret'))

        # Display redirect URI info (dynamically generated, not stored)
        port = config.cparser.value('webserver/port', type=int) or 8899
        redirect_uri = f'http://localhost:{port}/twitchredirect'

        if hasattr(widget, 'redirecturi_lineedit'):
            widget.redirecturi_lineedit.setText(redirect_uri)

        # Initialize single OAuth2 handler
        self.oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config)
        self.update_oauth_status()
        self.update_token_name()

        # Start periodic status updates for real-time refresh detection
        # Stop any existing timer first to prevent multiple timers
        self.stop_status_timer()
        self.start_status_timer()

    @staticmethod
    def save(config, widget, subprocesses):
        ''' update the twitch settings '''
        oldchannel = config.cparser.value('twitchbot/channel')
        newchannel = widget.channel_lineedit.text()
        oldclientid = config.cparser.value('twitchbot/clientid')
        newclientid = widget.clientid_lineedit.text()
        oldsecret = config.cparser.value('twitchbot/secret')
        newsecret = widget.secret_lineedit.text()

        config.cparser.setValue('twitchbot/enabled', widget.enable_checkbox.isChecked())
        config.cparser.setValue('twitchbot/channel', newchannel)
        config.cparser.setValue('twitchbot/clientid', newclientid)
        config.cparser.setValue('twitchbot/secret', newsecret)

        # Redirect URI is dynamically generated, not stored in config

        # Note: Chat token changes don't require restart - chat.py handles token changes dynamically
        if (oldchannel != newchannel) or (oldclientid != newclientid) or (oldsecret != newsecret):
            subprocesses.stop_twitchbot()
            # Clean up old token storage
            config.cparser.remove('twitchbot/oldusertoken')
            config.cparser.remove('twitchbot/oldrefreshtoken')
            # Keep OAuth2 tokens (don't remove accesstoken/refreshtoken)
            config.cparser.sync()
            time.sleep(5)
            subprocesses.start_twitchbot()

    @staticmethod
    def verify(widget):
        ''' verify the settings are good '''
        if not widget.enable_checkbox.isChecked():
            return

        # Check required fields
        if not widget.clientid_lineedit.text().strip():
            raise PluginVerifyError('Twitch Client ID is required')

        if not widget.secret_lineedit.text().strip():
            raise PluginVerifyError('Twitch Client Secret is required')

        # Redirect URI is dynamically generated - no validation needed

        if not widget.channel_lineedit.text().strip():
            raise PluginVerifyError('Twitch Channel is required')

    def update_token_name(self):
        ''' update the token name in the UI based on both token types '''
        broadcaster_status = "Not authenticated"
        chat_status = "Not authenticated"

        # Check OAuth2 broadcaster token
        if self.oauth:
            access_token, _ = self.oauth.get_stored_tokens()
            if (access_token
                    and nowplaying.twitch.utils.qtsafe_validate_twitch_oauth_token(access_token)):
                if oauth_username := self._get_oauth_username(access_token):
                    broadcaster_status = f'{oauth_username} (Broadcaster)'

        # Check separate chat token
        chat_token = self.oauth.config.cparser.value('twitchbot/chattoken') if self.oauth else None
        if chat_token and nowplaying.twitch.utils.qtsafe_validate_twitch_oauth_token(chat_token):
            if chat_username := self._get_oauth_username(chat_token):
                chat_status = f'{chat_username} (Chat Bot)'

        # Display combined status showing both tokens
        if broadcaster_status != "Not authenticated" and chat_status != "Not authenticated":
            # Both tokens present
            self.widget.chatbot_username_line.setText(f'🎥 {broadcaster_status} | 💬 {chat_status}')
        elif broadcaster_status != "Not authenticated":
            # Only broadcaster token
            self.widget.chatbot_username_line.setText(f'🎥 {broadcaster_status} (also for chat)')
        elif chat_status != "Not authenticated":
            # Only chat token (unusual but possible)
            self.widget.chatbot_username_line.setText(f'💬 {chat_status} (no broadcaster auth)')
        else:
            # No tokens
            self.widget.chatbot_username_line.setText('Not authenticated')

    def _get_oauth_username(self, access_token):
        ''' Get username from OAuth2 token using existing validation function '''
        # Reuse the existing token validation logic
        username = nowplaying.twitch.utils.qtsafe_validate_token(access_token)
        return username

    def update_oauth_status(self):
        ''' update the OAuth status display '''
        if not self.oauth or not self.widget:
            return

        # Check if we have valid configuration
        client_id = self.widget.clientid_lineedit.text().strip()
        client_secret = self.widget.secret_lineedit.text().strip()

        if not client_id or not client_secret:
            if hasattr(self.widget, 'oauth_status_label'):
                self.widget.oauth_status_label.setText('Configuration incomplete')
            # Disable copy buttons if configuration is incomplete
            if hasattr(self.widget, 'copy_broadcaster_auth_button'):
                self.widget.copy_broadcaster_auth_button.setEnabled(False)
            if hasattr(self.widget, 'copy_chat_auth_button'):
                self.widget.copy_chat_auth_button.setEnabled(False)
            # Backward compatibility
            if hasattr(self.widget, 'copy_auth_link_button'):
                self.widget.copy_auth_link_button.setEnabled(False)
            return

        # Check for stored tokens and validate them
        access_token, refresh_token = self.oauth.get_stored_tokens()
        chat_token = self.oauth.config.cparser.value('twitchbot/chattoken')

        # Build detailed status message
        broadcaster_valid = (
            access_token
            and nowplaying.twitch.utils.qtsafe_validate_twitch_oauth_token(access_token))
        chat_valid = (chat_token
                      and nowplaying.twitch.utils.qtsafe_validate_twitch_oauth_token(chat_token))

        # Update button states with status-aware messaging
        if hasattr(self.widget, 'copy_broadcaster_auth_button'):
            if broadcaster_valid:
                self.widget.copy_broadcaster_auth_button.setText('✅ Broadcaster Authenticated')
            else:
                self.widget.copy_broadcaster_auth_button.setText('Copy Broadcaster Auth URL')
            self.widget.copy_broadcaster_auth_button.setEnabled(True)
        if hasattr(self.widget, 'copy_chat_auth_button'):
            if chat_valid:
                self.widget.copy_chat_auth_button.setText('✅ Chat Bot Authenticated')
            else:
                self.widget.copy_chat_auth_button.setText('Copy Chat Bot Auth URL')
            self.widget.copy_chat_auth_button.setEnabled(True)
        # Backward compatibility
        if hasattr(self.widget, 'copy_auth_link_button'):
            self.widget.copy_auth_link_button.setText('Copy Auth URL')
            self.widget.copy_auth_link_button.setEnabled(True)

        if broadcaster_valid and chat_valid:
            status_text = 'Broadcaster + Chat Bot authenticated'
        elif broadcaster_valid and not chat_valid:
            status_text = 'Broadcaster authenticated (handles chat too)'
        elif not broadcaster_valid and chat_valid:
            status_text = 'Chat Bot authenticated (no broadcaster)'
        elif access_token and not broadcaster_valid:
            # Token is expired - check if we can refresh
            if refresh_token:
                status_text = 'Refreshing expired broadcaster token...'
            else:
                status_text = 'Broadcaster token expired - re-authentication needed'
        else:
            status_text = 'Not authenticated'

        if hasattr(self.widget, 'oauth_status_label'):
            self.widget.oauth_status_label.setText(status_text)

        # Update account name display
        self.update_token_name()

    def start_status_timer(self):
        ''' Start periodic status updates to catch automatic token refresh '''
        if not self.status_timer:
            # Set widget as parent so Qt automatically cleans up timer on widget destruction
            parent = self.widget if self.widget else None
            self.status_timer = QTimer(parent)
            self.status_timer.timeout.connect(self.update_oauth_status)
            # Check every 5 seconds for token status changes
            self.status_timer.start(5000)

    def stop_status_timer(self):
        ''' Stop periodic status updates '''
        if self.status_timer:
            self.status_timer.stop()
            self.status_timer = None

    def cleanup(self):
        ''' Clean up resources when settings UI is closed '''
        self.stop_status_timer()

    def clear_authentication(self):
        ''' clear stored authentication tokens (OAuth2 and chat) '''
        if self.oauth:
            self.oauth.clear_stored_tokens()
            # Also clear chat tokens
            self.oauth.config.cparser.remove('twitchbot/chattoken')
            self.oauth.config.cparser.remove('twitchbot/chatrefreshtoken')
            self.oauth.config.save()
        self.update_oauth_status()
        logging.info('Cleared Twitch OAuth2 and chat authentication')

    def _copy_auth_link(self):
        ''' generate and copy authentication URL to clipboard '''
        if not self.oauth:
            logging.error('OAuth2 handler not initialized')
            return

        # Update OAuth client with current form values
        if self.widget:
            self.oauth.client_id = self.widget.clientid_lineedit.text().strip()
            self.oauth.client_secret = self.widget.secret_lineedit.text().strip()

            # Use single redirect URI
            port = self.oauth.config.cparser.value('webserver/port', type=int) or 8899
            self.oauth.redirect_uri = f'http://localhost:{port}/twitchredirect'

        # Validate required fields
        if not self.oauth.client_id:
            if hasattr(self.widget, 'oauth_status_label'):
                self.widget.oauth_status_label.setText('Error: Client ID required')
            return
        if not self.oauth.client_secret:
            if hasattr(self.widget, 'oauth_status_label'):
                self.widget.oauth_status_label.setText('Error: Client Secret required')
            return

        try:
            # Generate the auth URL without opening browser
            auth_url = self.oauth.get_authorization_url()

            # Copy to clipboard
            clipboard = QApplication.clipboard()
            clipboard.setText(auth_url)

            if hasattr(self.widget, 'oauth_status_label'):
                self.widget.oauth_status_label.setText('Auth URL copied to clipboard')

            # Show success dialog with the URL
            if self.uihelp and hasattr(self.uihelp, 'qtui'):
                msgbox = QMessageBox(self.uihelp.qtui)
                msgbox.setWindowTitle('Authentication URL Copied')
                msgbox.setIcon(QMessageBox.Information)
                msgbox.setText('✅ Authentication URL Copied to Clipboard')
                msgbox.setInformativeText(
                    'The authentication URL has been copied to your clipboard.\n\n'
                    'Next steps:\n'
                    '1. Open your browser\n'
                    '2. IMPORTANT: Make sure you are logged into the correct Twitch account\n'
                    '   (If you want a bot account, log into that account first)\n'
                    '3. Paste and visit the copied URL\n'
                    '4. Complete the authorization\n'
                    '5. The token will be automatically saved\n\n'
                    f'URL: {auth_url[:60]}{"..." if len(auth_url) > 60 else ""}')
                msgbox.exec()

            logging.info('Twitch OAuth2 authentication URL copied to clipboard')

        except (OSError, ValueError) as error:
            logging.error('Failed to generate auth URL: %s', error)
            if hasattr(self.widget, 'oauth_status_label'):
                self.widget.oauth_status_label.setText(f'Error generating URL: {error}')
        except Exception:
            logging.exception('Unexpected error during Twitch OAuth2 URL generation')
            raise

    def _copy_broadcaster_auth_link(self):
        ''' generate and copy broadcaster authentication URL to clipboard '''
        self._copy_auth_link_with_message(
            token_type='broadcaster',
            success_title='Broadcaster Authentication URL Copied',
            success_message=(
                'The broadcaster authentication URL has been copied to your clipboard.\n\n'
                'This will authenticate your main streaming account for:\n'
                '• Channel Points redemptions\n'
                '• API access\n'
                '• Chat (if no separate bot account is configured)\n\n'
                'Next steps:\n'
                '1. Open your browser\n'
                '2. IMPORTANT: Make sure you are logged into your MAIN STREAMING ACCOUNT\n'
                '3. Paste and visit the copied URL\n'
                '4. Complete the authorization\n'
                '5. The token will be automatically saved'))

    def _copy_chat_auth_link(self):
        ''' generate and copy chat bot authentication URL to clipboard '''
        self._copy_auth_link_with_message(
            token_type='chat',
            success_title='Chat Bot Authentication URL Copied',
            success_message=(
                'The chat bot authentication URL has been copied to your clipboard.\n\n'
                'This will authenticate a separate bot account for:\n'
                '• Chat messages only\n'
                '• Commands and responses\n\n'
                'Next steps:\n'
                '1. Open your browser\n'
                '2. IMPORTANT: Make sure you are logged into your BOT ACCOUNT\n'
                '   (Not your main streaming account!)\n'
                '3. Paste and visit the copied URL\n'
                '4. Complete the authorization\n'
                '5. The token will be automatically saved\n\n'
                'Note: If you don\'t want a separate bot account, you can skip this\n'
                'and use only the broadcaster authentication.'))

    def _copy_auth_link_with_message(self,
                                     token_type='broadcaster',
                                     success_title='',
                                     success_message=''):
        ''' generate and copy authentication URL with custom message '''
        if not self.oauth:
            logging.error('OAuth2 handler not initialized')
            return

        # Update OAuth client with current form values
        if self.widget:
            self.oauth.client_id = self.widget.clientid_lineedit.text().strip()
            self.oauth.client_secret = self.widget.secret_lineedit.text().strip()

            # Use appropriate redirect URI based on token type
            port = self.oauth.config.cparser.value('webserver/port', type=int) or 8899
            if token_type == 'chat':
                self.oauth.redirect_uri = f'http://localhost:{port}/twitchchatredirect'
            else:
                self.oauth.redirect_uri = f'http://localhost:{port}/twitchredirect'

        # Validate required fields
        if not self.oauth.client_id:
            if hasattr(self.widget, 'oauth_status_label'):
                self.widget.oauth_status_label.setText('Error: Client ID required')
            return
        if not self.oauth.client_secret:
            if hasattr(self.widget, 'oauth_status_label'):
                self.widget.oauth_status_label.setText('Error: Client Secret required')
            return

        try:
            # Generate the auth URL with appropriate scopes
            if token_type == 'chat':
                auth_url = self.oauth.get_authorization_url(CHAT_BOT_SCOPE_STRINGS)
            else:
                auth_url = self.oauth.get_authorization_url()  # Uses broadcaster scopes by default

            # Copy to clipboard
            clipboard = QApplication.clipboard()
            clipboard.setText(auth_url)

            if hasattr(self.widget, 'oauth_status_label'):
                self.widget.oauth_status_label.setText(
                    f'{token_type.title()} auth URL copied to clipboard')

            # Show success dialog with the URL
            if self.uihelp and hasattr(self.uihelp, 'qtui'):
                msgbox = QMessageBox(self.uihelp.qtui)
                msgbox.setWindowTitle(success_title)
                msgbox.setIcon(QMessageBox.Information)
                msgbox.setText(f'✅ {success_title}')
                msgbox.setInformativeText(
                    f'{success_message}\n\n'
                    f'URL: {auth_url[:60]}{"..." if len(auth_url) > 60 else ""}')
                msgbox.exec()

            logging.info('Twitch %s OAuth2 authentication URL copied to clipboard', token_type)

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error('Failed to generate %s auth URL: %s', token_type, error)
            if hasattr(self.widget, 'oauth_status_label'):
                self.widget.oauth_status_label.setText(
                    f'Error generating {token_type} URL: {error}')
