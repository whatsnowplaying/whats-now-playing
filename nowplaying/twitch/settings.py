#!/usr/bin/env python3
"""twitch settings"""

import logging
import pathlib
import time

from PySide6.QtCore import QTimer, Slot  # pylint: disable=no-name-in-module

import nowplaying.authwizard
import nowplaying.preview.textwindow
import nowplaying.twitch.oauth2
import nowplaying.utils.qt
from nowplaying.exceptions import PluginVerifyError
from nowplaying.twitch.constants import (
    BROADCASTER_OAUTH_STATUS_KEY,
    BROADCASTER_USERNAME_KEY,
    CHAT_OAUTH_STATUS_KEY,
    CHAT_USERNAME_KEY,
    OAUTH_STATUS_AUTHENTICATED,
    OAUTH_STATUS_EXPIRED,
)


class TwitchSettings:
    """for settings UI"""

    def __init__(self):
        self.widget = None
        self.uihelp = None
        self.oauth = None
        self.status_timer = None
        self._streamtitle_preview_window: (
            nowplaying.preview.textwindow.TextPreviewWindow | None
        ) = None

    def connect(self, uihelp, widget):
        """connect twitch"""
        self.widget = widget
        self.uihelp = uihelp

        widget.authenticate_button.clicked.connect(self._launch_auth_wizard)
        widget.clientid_lineedit.editingFinished.connect(self.update_oauth_status)
        widget.secret_lineedit.editingFinished.connect(self.update_oauth_status)

        # Stream title
        widget.streamtitle_checkbox.toggled.connect(self._on_streamtitle_toggled)
        widget.streamtitle_button.clicked.connect(self.on_streamtitle_button)
        widget.streamtitle_preview_button.clicked.connect(self.on_streamtitle_preview_button)

    def load(self, config, widget, uihelp):  # pylint: disable=unused-argument
        """load the settings window"""
        self.widget = widget
        widget.enable_checkbox.setChecked(config.cparser.value("twitchbot/enabled", type=bool))
        widget.channel_lineedit.setText(config.cparser.value("twitchbot/channel"))
        widget.clientid_lineedit.setText(config.cparser.value("twitchbot/clientid") or "")
        widget.secret_lineedit.setText(config.cparser.value("twitchbot/secret") or "")

        streamtitle_enabled = config.cparser.value("twitchbot/streamtitle_enabled", type=bool)
        widget.streamtitle_checkbox.setChecked(streamtitle_enabled)
        widget.streamtitle_lineedit.setText(
            config.cparser.value("twitchbot/streamtitle", defaultValue="")
        )
        widget.streamtitle_lineedit.setEnabled(streamtitle_enabled)
        widget.streamtitle_button.setEnabled(streamtitle_enabled)
        widget.streamtitle_preview_button.setEnabled(streamtitle_enabled)

        # Redirect URI info is displayed as static text in UI instructions

        # Initialize single OAuth2 handler
        self.oauth = nowplaying.twitch.oauth2.TwitchOAuth2(config)

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
        newclientid = widget.clientid_lineedit.text().strip()
        oldsecret = config.cparser.value("twitchbot/secret")
        newsecret = widget.secret_lineedit.text()

        config.cparser.setValue("twitchbot/enabled", widget.enable_checkbox.isChecked())
        config.cparser.setValue("twitchbot/channel", newchannel)
        config.cparser.setValue("twitchbot/clientid", newclientid)
        config.cparser.setValue("twitchbot/secret", newsecret)
        config.cparser.setValue(
            "twitchbot/streamtitle_enabled", widget.streamtitle_checkbox.isChecked()
        )
        config.cparser.setValue(
            "twitchbot/streamtitle", widget.streamtitle_lineedit.text().strip()
        )

        if (oldchannel != newchannel) or (oldclientid != newclientid) or (oldsecret != newsecret):
            subprocesses.stop_twitchbot()
            config.cparser.remove("twitchbot/oldusertoken")
            config.cparser.remove("twitchbot/oldrefreshtoken")
            config.cparser.sync()
            time.sleep(5)
            subprocesses.start_twitchbot()

    @staticmethod
    def verify(widget):
        """verify the settings are good"""
        if not widget.enable_checkbox.isChecked():
            return

        if not widget.channel_lineedit.text().strip():
            raise PluginVerifyError("Twitch Channel is required")
        # Client ID and Secret are optional — blank uses the bundled WNP app (port 8899 only)

    @staticmethod
    def _broadcaster_status_text(status: str, username: str, has_token: bool) -> str:
        if username:
            return username
        if status == OAUTH_STATUS_AUTHENTICATED:
            return "authenticated"
        if status == OAUTH_STATUS_EXPIRED:
            return "token expired — re-authenticate"
        if has_token:
            return "connecting..."
        return "Not authenticated"

    @staticmethod
    def _chat_status_text(status: str, username: str, has_token: bool) -> str:
        if username:
            return username
        if status == OAUTH_STATUS_AUTHENTICATED:
            return "authenticated"
        if status == OAUTH_STATUS_EXPIRED:
            return "token expired — re-authenticate"
        if has_token:
            return "connecting..."
        return "Using broadcaster account"

    def _read_token_statuses(self) -> tuple[str, str, bool, bool]:
        """Read broadcaster and chat token statuses and token presence from cparser."""
        cparser = self.oauth.config.cparser
        broadcaster = str(cparser.value(BROADCASTER_OAUTH_STATUS_KEY, defaultValue=""))
        chat = str(cparser.value(CHAT_OAUTH_STATUS_KEY, defaultValue=""))
        has_broadcaster = bool(cparser.value("twitchbot/accesstoken", defaultValue=""))
        has_chat = bool(cparser.value("twitchbot/chattoken", defaultValue=""))
        return broadcaster, chat, has_broadcaster, has_chat

    def update_oauth_status(self):
        """update the OAuth status display from cached cparser values"""
        if not self.oauth or not self.oauth.config or not self.widget:
            return

        # Update client_id/secret from UI in case user changed them
        self.oauth.client_id = self.widget.clientid_lineedit.text().strip() or self.oauth.client_id
        self.oauth.client_secret = self.widget.secret_lineedit.text().strip()

        cparser = self.oauth.config.cparser
        broadcaster_status, chat_status, has_broadcaster, has_chat = self._read_token_statuses()
        broadcaster_name = str(cparser.value(BROADCASTER_USERNAME_KEY, defaultValue=""))
        chat_name = str(cparser.value(CHAT_USERNAME_KEY, defaultValue=""))

        self.widget.oauth_status_label.setText(
            self._broadcaster_status_text(broadcaster_status, broadcaster_name, has_broadcaster)
        )
        self.widget.chat_status_label.setText(
            self._chat_status_text(chat_status, chat_name, has_chat)
        )

        btn_text = (
            "Re-authenticate..."
            if broadcaster_status == OAUTH_STATUS_AUTHENTICATED
            else "Auth Wizard..."
        )
        self.widget.authenticate_button.setText(btn_text)

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

    def _on_streamtitle_toggled(self, enabled: bool) -> None:
        """Enable/disable stream title template widgets based on checkbox state"""
        self.widget.streamtitle_lineedit.setEnabled(enabled)
        self.widget.streamtitle_button.setEnabled(enabled)
        self.widget.streamtitle_preview_button.setEnabled(enabled)

    @Slot()
    def on_streamtitle_button(self) -> None:
        """Open template file picker for stream title"""
        self.uihelp.template_picker_lineedit(
            self.widget.streamtitle_lineedit, limit="twitchbot_*.txt"
        )

    @Slot()
    def on_streamtitle_preview_button(self) -> None:
        """Open or raise the stream title template preview window"""
        if self._streamtitle_preview_window is None:
            self._streamtitle_preview_window = nowplaying.preview.textwindow.TextPreviewWindow(
                config=self.oauth.config,
                glob_pattern="twitchbot_*.txt",
                config_key="twitchbot/streamtitle",
                enable_select_button=True,
            )
            self._streamtitle_preview_window.template_selected.connect(
                self._on_streamtitle_template_selected
            )
        self._streamtitle_preview_window.populate_templates()
        current = pathlib.Path(self.widget.streamtitle_lineedit.text()).name
        if current:
            self._streamtitle_preview_window.select_template(current)
        nowplaying.utils.qt.focus_window(self._streamtitle_preview_window)

    @Slot(str)
    def _on_streamtitle_template_selected(self, template_name: str) -> None:
        self.widget.streamtitle_lineedit.setText(
            str(pathlib.Path(self.oauth.config.templatedir) / template_name)
        )

    def clear_authentication(self):
        """clear stored authentication tokens (OAuth2 and chat)"""
        if self.oauth:
            self.oauth.clear_all_authentication()
        self.update_oauth_status()

    def _launch_auth_wizard(self) -> None:
        """Open the authentication wizard for Twitch."""
        if not self.oauth:
            return
        wizard = nowplaying.authwizard.AuthWizard(self.oauth.config, ["twitch"])
        wizard.exec()
        self.update_oauth_status()
