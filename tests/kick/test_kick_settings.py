#!/usr/bin/env python3
"""Unit tests for Kick settings functionality."""
# pylint: disable=no-member

from unittest.mock import MagicMock

import pytest

import nowplaying.kick.settings
from nowplaying.exceptions import PluginVerifyError


def test_kick_settings_init():
    """Test KickSettings initialization."""
    settings = nowplaying.kick.settings.KickSettings()
    assert settings.widget is None
    assert settings.oauth is None


def test_kick_chat_settings_init():
    """Test KickChatSettings initialization."""
    settings = nowplaying.kick.settings.KickChatSettings()
    assert settings.widget is None


def test_kick_chat_settings_verify_enabled_no_template():
    """Test settings verification fails when enabled but no template."""
    mock_widget = MagicMock()
    mock_widget.enable_checkbox.isChecked.return_value = True
    mock_widget.announce_lineedit.text.return_value = ""

    with pytest.raises(PluginVerifyError, match="Kick announcement template is required"):
        nowplaying.kick.settings.KickChatSettings.verify(mock_widget)


def test_kick_chat_settings_verify_disabled():
    """Test settings verification passes when disabled."""
    mock_widget = MagicMock()
    mock_widget.enable_checkbox.isChecked.return_value = False

    # Should not raise an exception
    nowplaying.kick.settings.KickChatSettings.verify(mock_widget)


def test_kick_chat_settings_verify_enabled_with_template():
    """Test settings verification passes when enabled with template."""
    mock_widget = MagicMock()
    mock_widget.enable_checkbox.isChecked.return_value = True
    mock_widget.announce_lineedit.text.return_value = "template.txt"

    # Should not raise an exception
    nowplaying.kick.settings.KickChatSettings.verify(mock_widget)
