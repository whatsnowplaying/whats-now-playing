#!/usr/bin/env python3
"""Beam/Remote output settings UI module."""

import logging
from typing import TYPE_CHECKING

from nowplaying.exceptions import PluginVerifyError

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget  # pylint: disable=import-error, no-name-in-module
    import nowplaying.uihelp
    import nowplaying.config


class BeamSettings:
    """Handles beam/remote output settings UI."""

    def __init__(self):
        self.config = None
        self.widget = None

    def connect(
            self,
            uihelp: 'nowplaying.uihelp.UIHelp',  # pylint: disable=unused-argument
            widget: 'QWidget'):
        """Connect the beam settings UI."""
        self.widget = widget

        # Connect signals
        if hasattr(widget, 'enable_checkbox'):
            widget.enable_checkbox.toggled.connect(self._on_enable_toggled)

    def load(self, config: 'nowplaying.config.ConfigFile', widget: 'QWidget'):
        """Load the beam settings UI."""
        self.config = config
        self.widget = widget

        # Set checkbox state
        enabled = config.cparser.value('remote/enabled', type=bool, defaultValue=False)
        widget.enable_checkbox.setChecked(enabled)

        # Set server
        server = config.cparser.value('remote/remote_server', type=str, defaultValue='remotehost')
        widget.server_lineedit.setText(server)

        # Set port
        port = config.cparser.value('remote/remote_port', type=int, defaultValue=8899)
        widget.port_lineedit.setText(str(port))

        # Set secret
        secret = config.cparser.value('remote/remote_key', type=str, defaultValue='')
        widget.secret_lineedit.setText(secret)

        # Update UI state based on enabled
        self._on_enable_toggled(enabled)

    def _on_enable_toggled(self, enabled: bool):
        """Handle enable checkbox toggle."""
        if not self.widget:
            return

        # Enable/disable other controls based on checkbox state
        self.widget.server_lineedit.setEnabled(enabled)
        self.widget.port_lineedit.setEnabled(enabled)
        self.widget.secret_lineedit.setEnabled(enabled)
        self.widget.server_label.setEnabled(enabled)
        self.widget.port_label.setEnabled(enabled)
        self.widget.secret_label.setEnabled(enabled)

    def save_settings(self):
        """Save settings to configuration."""
        if not self.config or not self.widget:
            return

        # Save enabled state
        enabled = self.widget.enable_checkbox.isChecked()
        self.config.cparser.setValue('remote/enabled', enabled)

        # Save server
        server = self.widget.server_lineedit.text().strip()
        if not server:
            server = 'localhost'
        self.config.cparser.setValue('remote/remote_server', server)

        # Save port
        port_text = self.widget.port_lineedit.text().strip()
        try:
            port = int(port_text) if port_text else 8080
        except ValueError:
            logging.warning('Invalid port number: %s, using default 8080', port_text)
            port = 8080
        self.config.cparser.setValue('remote/remote_port', port)

        # Save secret
        secret = self.widget.secret_lineedit.text().strip()
        self.config.cparser.setValue('remote/remote_key', secret)

        logging.debug('Beam settings saved: enabled=%s, server=%s, port=%d', enabled, server, port)

    @staticmethod
    def verify(widget: 'QWidget') -> bool:
        """Verify beam settings."""
        # Basic validation - could be extended later
        if widget.enable_checkbox.isChecked():
            if not widget.server_lineedit.text().strip():
                raise PluginVerifyError("Server field is required when beam output is enabled")
        return True
