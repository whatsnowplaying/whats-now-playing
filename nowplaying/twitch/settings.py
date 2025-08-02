#!/usr/bin/env python3
"""twitch settings"""

import logging
import time

from PySide6.QtWidgets import QMessageBox, QApplication  # pylint: disable=no-name-in-module
from PySide6.QtCore import QTimer  # pylint: disable=no-name-in-module

from nowplaying.exceptions import PluginVerifyError

import nowplaying.twitch.oauth2


class TwitchSettings:
    """for settings UI"""

    def __init__(self):
        self.widget = None
        self.uihelp = None
        self.oauth = None
        self.status_timer = None

    def connect(self, uihelp, widget):
        """connect twitch"""
        self.widget = widget
        self.uihelp = uihelp

        # Connect OAuth buttons - dual token support
        if hasattr(widget, "copy_broadcaster_auth_button"):
            widget.copy_broadcaster_auth_button.clicked.connect(self._copy_broadcaster_auth_link)
        if hasattr(widget, "copy_chat_auth_button"):
            widget.copy_chat_auth_button.clicked.connect(self._copy_chat_auth_link)

        # Backward compatibility for old single button UI
        if hasattr(widget, "copy_auth_link_button"):
            widget.copy_auth_link_button.clicked.connect(self._copy_auth_link)

        if hasattr(widget, "clientid_lineedit"):
            widget.clientid_lineedit.editingFinished.connect(self.update_oauth_status)
        if hasattr(widget, "secret_lineedit"):
            widget.secret_lineedit.editingFinished.connect(self.update_oauth_status)
        if hasattr(widget, "redirecturi_lineedit"):
            widget.redirecturi_lineedit.editingFinished.connect(self.update_oauth_status)

    def load(self, config, widget, uihelp):  # pylint: disable=unused-argument
        """load the settings window"""
        self.widget = widget
        widget.enable_checkbox.setChecked(config.cparser.value("twitchbot/enabled", type=bool))
        widget.clientid_lineedit.setText(config.cparser.value("twitchbot/clientid"))
        widget.channel_lineedit.setText(config.cparser.value("twitchbot/channel"))
        widget.secret_lineedit.setText(config.cparser.value("twitchbot/secret"))

        # Display redirect URI info (dynamically generated, not stored)
        if hasattr(widget, "redirecturi_lineedit"):
            redirect_uri = self.oauth.get_redirect_uri("broadcaster") if self.oauth else ""
            widget.redirecturi_lineedit.setText(redirect_uri)

        # Initialize single OAuth2 handler
        self.oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config)
        self.update_oauth_status()
        self.update_token_name()

        # Start periodic status updates for real-time refresh detection
        # Stop any existing timer first to prevent multiple timers
        self.stop_status_timer()
        # Timer disabled to prevent blocking main thread
        # self.start_status_timer()

    @staticmethod
    def save(config, widget, subprocesses):
        """update the twitch settings"""
        oldchannel = config.cparser.value("twitchbot/channel")
        newchannel = widget.channel_lineedit.text()
        oldclientid = config.cparser.value("twitchbot/clientid")
        newclientid = widget.clientid_lineedit.text()
        oldsecret = config.cparser.value("twitchbot/secret")
        newsecret = widget.secret_lineedit.text()

        config.cparser.setValue("twitchbot/enabled", widget.enable_checkbox.isChecked())
        config.cparser.setValue("twitchbot/channel", newchannel)
        config.cparser.setValue("twitchbot/clientid", newclientid)
        config.cparser.setValue("twitchbot/secret", newsecret)

        # Redirect URI is dynamically generated, not stored in config

        # Note: Chat token changes don't require restart - chat.py handles token changes dynamically
        if (oldchannel != newchannel) or (oldclientid != newclientid) or (oldsecret != newsecret):
            subprocesses.stop_twitchbot()
            # Clean up old token storage
            config.cparser.remove("twitchbot/oldusertoken")
            config.cparser.remove("twitchbot/oldrefreshtoken")
            # Keep OAuth2 tokens (don't remove accesstoken/refreshtoken)
            config.cparser.sync()
            time.sleep(5)
            subprocesses.start_twitchbot()

    @staticmethod
    def verify(widget):
        """verify the settings are good"""
        if not widget.enable_checkbox.isChecked():
            return

        # Check required fields
        if not widget.clientid_lineedit.text().strip():
            raise PluginVerifyError("Twitch Client ID is required")

        if not widget.secret_lineedit.text().strip():
            raise PluginVerifyError("Twitch Client Secret is required")

        # Redirect URI is dynamically generated - no validation needed

        if not widget.channel_lineedit.text().strip():
            raise PluginVerifyError("Twitch Channel is required")

    def update_token_name(self):
        """update the token name in the UI based on both token types"""
        if not self.oauth:
            self.widget.chatbot_username_line.setText("Not authenticated")
            return

        # Get OAuth status from service
        status = self.oauth.get_oauth_status()

        broadcaster_username = status["broadcaster_username"]
        chat_username = status["chat_username"]
        broadcaster_valid = status["broadcaster_valid"]
        chat_valid = status["chat_valid"]

        # Display combined status showing both tokens
        if broadcaster_valid and chat_valid:
            # Both tokens present
            self.widget.chatbot_username_line.setText(
                f"🎥 {broadcaster_username} (Broadcaster) | 💬 {chat_username} (Chat Bot)"
            )
        elif broadcaster_valid:
            # Only broadcaster token
            self.widget.chatbot_username_line.setText(
                f"🎥 {broadcaster_username} (Broadcaster, also for chat)"
            )
        elif chat_valid:
            # Only chat token (unusual but possible)
            self.widget.chatbot_username_line.setText(
                f"💬 {chat_username} (Chat Bot, no broadcaster auth)"
            )
        else:
            # No tokens
            self.widget.chatbot_username_line.setText("Not authenticated")

    def update_oauth_status(self):
        """update the OAuth status display"""
        if not self.oauth or not self.widget:
            return

        # Update OAuth client with current form values
        self.oauth.client_id = self.widget.clientid_lineedit.text().strip()
        self.oauth.client_secret = self.widget.secret_lineedit.text().strip()

        # Check if configuration is complete
        if not self.oauth.is_configuration_complete():
            if hasattr(self.widget, "oauth_status_label"):
                self.widget.oauth_status_label.setText("Configuration incomplete")
            # Disable copy buttons if configuration is incomplete
            self._set_auth_buttons_enabled(False)
            return

        # Get OAuth status from service
        status = self.oauth.get_oauth_status()

        # Update button states with status-aware messaging
        self._update_auth_button_states(status)

        # Update status label
        if hasattr(self.widget, "oauth_status_label"):
            self.widget.oauth_status_label.setText(status["status_text"])

        # Update account name display
        self.update_token_name()

    def _set_auth_buttons_enabled(self, enabled: bool) -> None:
        """Enable or disable authentication buttons"""
        if hasattr(self.widget, "copy_broadcaster_auth_button"):
            self.widget.copy_broadcaster_auth_button.setEnabled(enabled)
        if hasattr(self.widget, "copy_chat_auth_button"):
            self.widget.copy_chat_auth_button.setEnabled(enabled)
        # Backward compatibility
        if hasattr(self.widget, "copy_auth_link_button"):
            self.widget.copy_auth_link_button.setEnabled(enabled)

    def _update_auth_button_states(self, status: dict) -> None:
        """Update authentication button text and states based on OAuth status"""
        broadcaster_valid = status["broadcaster_valid"]
        chat_valid = status["chat_valid"]

        # Update button states with status-aware messaging
        if hasattr(self.widget, "copy_broadcaster_auth_button"):
            if broadcaster_valid:
                self.widget.copy_broadcaster_auth_button.setText("✅ Broadcaster Authenticated")
            else:
                self.widget.copy_broadcaster_auth_button.setText("Copy Broadcaster Auth URL")
            self.widget.copy_broadcaster_auth_button.setEnabled(True)

        if hasattr(self.widget, "copy_chat_auth_button"):
            if chat_valid:
                self.widget.copy_chat_auth_button.setText("✅ Chat Bot Authenticated")
            else:
                self.widget.copy_chat_auth_button.setText("Copy Chat Bot Auth URL")
            self.widget.copy_chat_auth_button.setEnabled(True)

        # Backward compatibility
        if hasattr(self.widget, "copy_auth_link_button"):
            self.widget.copy_auth_link_button.setText("Copy Auth URL")
            self.widget.copy_auth_link_button.setEnabled(True)

    def start_status_timer(self):
        """Start periodic status updates to catch automatic token refresh"""
        if not self.status_timer:
            # Set widget as parent so Qt automatically cleans up timer on widget destruction
            parent = self.widget or None
            self.status_timer = QTimer(parent)
            self.status_timer.timeout.connect(self.update_oauth_status)
            # Check every 5 seconds for token status changes
            self.status_timer.start(5000)

    def stop_status_timer(self):
        """Stop periodic status updates"""
        if self.status_timer:
            self.status_timer.stop()
            self.status_timer = None

    def cleanup(self):
        """Clean up resources when settings UI is closed"""
        self.stop_status_timer()

    def clear_authentication(self):
        """clear stored authentication tokens (OAuth2 and chat)"""
        if self.oauth:
            self.oauth.clear_all_authentication()
        self.update_oauth_status()

    def _copy_auth_link(self):
        """generate and copy authentication URL to clipboard (backward compatibility)"""
        self._copy_auth_link_with_message(
            token_type="broadcaster",
            success_title="Authentication URL Copied",
            success_message=(
                "The authentication URL has been copied to your clipboard.\n\n"
                "Next steps:\n"
                "1. Open your browser\n"
                "2. IMPORTANT: Make sure you are logged into the correct Twitch account\n"
                "   (If you want a bot account, log into that account first)\n"
                "3. Paste and visit the copied URL\n"
                "4. Complete the authorization\n"
                "5. The token will be automatically saved"
            ),
        )

    def _copy_broadcaster_auth_link(self):
        """generate and copy broadcaster authentication URL to clipboard"""
        self._copy_auth_link_with_message(
            token_type="broadcaster",
            success_title="Broadcaster Authentication URL Copied",
            success_message=(
                "The broadcaster authentication URL has been copied to your clipboard.\n\n"
                "This will authenticate your main streaming account for:\n"
                "• Channel Points redemptions\n"
                "• API access\n"
                "• Chat (if no separate bot account is configured)\n\n"
                "Next steps:\n"
                "1. Open your browser\n"
                "2. IMPORTANT: Make sure you are logged into your MAIN STREAMING ACCOUNT\n"
                "3. Paste and visit the copied URL\n"
                "4. Complete the authorization\n"
                "5. The token will be automatically saved"
            ),
        )

    def _copy_chat_auth_link(self):
        """generate and copy chat bot authentication URL to clipboard"""
        self._copy_auth_link_with_message(
            token_type="chat",
            success_title="Chat Bot Authentication URL Copied",
            success_message=(
                "The chat bot authentication URL has been copied to your clipboard.\n\n"
                "This will authenticate a separate bot account for:\n"
                "• Chat messages only\n"
                "• Commands and responses\n\n"
                "Next steps:\n"
                "1. Open your browser\n"
                "2. IMPORTANT: Make sure you are logged into your BOT ACCOUNT\n"
                "   (Not your main streaming account!)\n"
                "3. Paste and visit the copied URL\n"
                "4. Complete the authorization\n"
                "5. The token will be automatically saved\n\n"
                "Note: If you don't want a separate bot account, you can skip this\n"
                "and use only the broadcaster authentication."
            ),
        )

    def _copy_auth_link_with_message(
        self, token_type="broadcaster", success_title="", success_message=""
    ):
        """generate and copy authentication URL with custom message"""
        if not self.oauth or not self.widget:
            logging.error("OAuth2 handler not initialized")
            return

        # Update OAuth client with current form values
        self.oauth.client_id = self.widget.clientid_lineedit.text().strip()
        self.oauth.client_secret = self.widget.secret_lineedit.text().strip()

        # Validate configuration
        if not self.oauth.is_configuration_complete():
            if hasattr(self.widget, "oauth_status_label"):
                self.widget.oauth_status_label.setText("Error: Configuration incomplete")
            return

        try:
            # Generate the auth URL using OAuth service
            auth_url = self.oauth.get_auth_url(token_type)
            if not auth_url:
                if hasattr(self.widget, "oauth_status_label"):
                    self.widget.oauth_status_label.setText(f"Error generating {token_type} URL")
                return

            # Copy to clipboard
            clipboard = QApplication.clipboard()
            clipboard.setText(auth_url)

            if hasattr(self.widget, "oauth_status_label"):
                self.widget.oauth_status_label.setText(
                    f"{token_type.title()} auth URL copied to clipboard"
                )

            # Show success dialog with the URL
            if self.uihelp and hasattr(self.uihelp, "qtui"):
                msgbox = QMessageBox(self.uihelp.qtui)
                msgbox.setWindowTitle(success_title)
                msgbox.setIcon(QMessageBox.Icon.Information)
                msgbox.setText(f"✅ {success_title}")
                msgbox.setInformativeText(
                    f"{success_message}\n\n"
                    f"URL: {auth_url[:60]}{'...' if len(auth_url) > 60 else ''}"
                )
                msgbox.exec()

            logging.info("Twitch %s OAuth2 authentication URL copied to clipboard", token_type)

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Failed to generate %s auth URL: %s", token_type, error)
            if hasattr(self.widget, "oauth_status_label"):
                self.widget.oauth_status_label.setText(
                    f"Error generating {token_type} URL: {error}"
                )
