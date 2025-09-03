#!/usr/bin/env python3
"""Test first install notification dialog functionality"""

# pylint: disable=unused-argument, unused-variable, protected-access,no-value-for-parameter, no-value-for-parameter, invalid-name

import time
from unittest.mock import Mock, patch

import pytest
from PySide6.QtWidgets import QApplication  # pylint: disable=no-name-in-module

import nowplaying.firstinstall


@pytest.fixture(name="qapp")
def qapp_fixture():
    """Provide QApplication instance for Qt tests."""
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


@patch("nowplaying.firstinstall.QMessageBox")
@patch("nowplaying.firstinstall.Qt")
def test_show_first_install_dialog_macos(mock_qt, mock_messagebox, qapp):
    """Test dialog content on macOS."""
    mock_msgbox_instance = Mock()
    mock_msgbox_instance.windowFlags.return_value = Mock()
    mock_messagebox.return_value = mock_msgbox_instance

    with patch("sys.platform", "darwin"), patch("nowplaying.firstinstall._show_arrow_overlay"):
        nowplaying.firstinstall.show_first_install_dialog()

    # Verify QMessageBox was created and configured
    mock_messagebox.assert_called_once()
    mock_msgbox_instance.setWindowTitle.assert_called_once_with(
        "What's Now Playing - Setup Complete"
    )

    # Check that macOS-specific text was used
    call_args = mock_msgbox_instance.setText.call_args[0][0]
    assert "macOS" in call_args
    assert "menu bar (top of screen)" in call_args
    assert "menu bar icon" in call_args

    # Verify dialog properties
    mock_msgbox_instance.setTextFormat.assert_called_once()
    mock_msgbox_instance.setStandardButtons.assert_called_once()
    mock_msgbox_instance.setIcon.assert_called_once()
    mock_msgbox_instance.setWindowFlags.assert_called_once()
    mock_msgbox_instance.exec.assert_called_once()


@patch("nowplaying.firstinstall.QMessageBox")
@patch("nowplaying.firstinstall.Qt")
def test_show_first_install_dialog_windows(mock_qt, mock_messagebox, qapp):
    """Test dialog content on Windows."""
    mock_msgbox_instance = Mock()
    mock_msgbox_instance.windowFlags.return_value = Mock()
    mock_messagebox.return_value = mock_msgbox_instance

    with patch("sys.platform", "win32"), patch("nowplaying.firstinstall._show_arrow_overlay"):
        nowplaying.firstinstall.show_first_install_dialog()

    # Check that Windows-specific text was used
    call_args = mock_msgbox_instance.setText.call_args[0][0]
    assert "Windows" in call_args
    assert "system tray (bottom-right corner)" in call_args
    assert "system tray icon" in call_args


@patch("nowplaying.firstinstall.QMessageBox")
@patch("nowplaying.firstinstall.Qt")
def test_show_first_install_dialog_linux(mock_qt, mock_messagebox, qapp):
    """Test dialog content on Linux."""
    mock_msgbox_instance = Mock()
    mock_msgbox_instance.windowFlags.return_value = Mock()
    mock_messagebox.return_value = mock_msgbox_instance

    with patch("sys.platform", "linux"), patch("nowplaying.firstinstall._show_arrow_overlay"):
        nowplaying.firstinstall.show_first_install_dialog()

    # Check that generic system text was used for Linux
    call_args = mock_msgbox_instance.setText.call_args[0][0]
    assert "your system" in call_args
    assert "system tray (bottom-right corner)" in call_args
    assert "system tray icon" in call_args


@patch("nowplaying.firstinstall.QMessageBox")
@patch("nowplaying.firstinstall.Qt")
def test_dialog_properties(mock_qt, mock_messagebox, qapp):
    """Test that dialog has correct properties set."""
    mock_msgbox_instance = Mock()
    mock_msgbox_instance.windowFlags.return_value = Mock()
    mock_messagebox.return_value = mock_msgbox_instance

    with patch("nowplaying.firstinstall._show_arrow_overlay"):
        nowplaying.firstinstall.show_first_install_dialog()

    # Verify dialog methods are called (specific enum values are mocked)
    mock_msgbox_instance.setStandardButtons.assert_called_once()
    mock_msgbox_instance.setIcon.assert_called_once()
    mock_msgbox_instance.setTextFormat.assert_called_once()


@patch("nowplaying.firstinstall.logging")
@patch("nowplaying.firstinstall.QMessageBox")
@patch("nowplaying.firstinstall.Qt")
def test_logging_calls(mock_qt, mock_messagebox, mock_logging, qapp):
    """Test that appropriate logging calls are made."""
    mock_msgbox_instance = Mock()
    mock_msgbox_instance.windowFlags.return_value = Mock()
    mock_messagebox.return_value = mock_msgbox_instance

    with patch("nowplaying.firstinstall._show_arrow_overlay"):
        nowplaying.firstinstall.show_first_install_dialog()

    # Verify logging calls
    mock_logging.info.assert_any_call("Showing %s notification dialog", "first-install")
    mock_logging.info.assert_any_call(
        "%s notification dialog acknowledged by user", "first-install"
    )


def test_dialog_content_completeness(qapp):
    """Test that dialog contains all required information."""
    with (
        patch("nowplaying.firstinstall.QMessageBox") as mock_messagebox,
        patch("nowplaying.firstinstall.Qt") as mock_qt,
    ):
        mock_msgbox_instance = Mock()
        mock_msgbox_instance.windowFlags.return_value = Mock()
        mock_messagebox.return_value = mock_msgbox_instance

        with patch("nowplaying.firstinstall._show_arrow_overlay"):
            nowplaying.firstinstall.show_first_install_dialog()

        call_args = mock_msgbox_instance.setText.call_args[0][0]

        # Verify essential content is present
        assert "Setup Complete" in call_args
        assert "running in the background" in call_args
        assert "To access the app" in call_args
        assert (
            "Click the icon" in call_args or "Right-click the icon" in call_args
        )  # Platform-specific
        assert "Settings" in call_args
        assert "continue running" in call_args


def test_reminder_dialog_content(qapp):
    """Test reminder dialog has appropriate content."""
    with (
        patch("nowplaying.firstinstall.QMessageBox") as mock_messagebox,
        patch("nowplaying.firstinstall.Qt") as mock_qt,
    ):
        mock_msgbox_instance = Mock()
        mock_msgbox_instance.windowFlags.return_value = Mock()
        mock_messagebox.return_value = mock_msgbox_instance

        with patch("nowplaying.firstinstall._show_arrow_overlay"):
            nowplaying.firstinstall.show_first_install_dialog(is_reminder=True)

        # Check title is for reminder
        mock_msgbox_instance.setWindowTitle.assert_called_once_with(
            "What's Now Playing - Reminder"
        )

        # Check reminder-specific content
        call_args = mock_msgbox_instance.setText.call_args[0][0]
        assert "What's Now Playing is running!" in call_args
        assert "In case you've forgotten" in call_args


def test_should_show_reminder_dialog_first_time():
    """Test reminder dialog logic for users who never had it shown."""
    config = Mock()
    config.initialized = True
    config.cparser.value.return_value = ""  # No previous dialog timestamp

    assert nowplaying.firstinstall.should_show_reminder_dialog(config) is True


def test_should_show_reminder_dialog_not_initialized():
    """Test reminder dialog not shown for uninitialized (first install) users."""
    config = Mock()
    config.initialized = False

    assert nowplaying.firstinstall.should_show_reminder_dialog(config) is False


def test_should_show_reminder_dialog_recent():
    """Test reminder dialog not shown if recently shown."""

    config = Mock()
    config.initialized = True
    # Set timestamp to 1 day ago (should not show - within 30 days)
    recent_timestamp = time.strftime("%Y%m%d%H%M%S", time.localtime(time.time() - 86400))
    config.cparser.value.return_value = recent_timestamp

    assert nowplaying.firstinstall.should_show_reminder_dialog(config) is False


def test_should_show_reminder_dialog_old():
    """Test reminder dialog shown if it's been more than 30 days."""

    config = Mock()
    config.initialized = True
    # Set timestamp to 31 days ago (should show - beyond 30 days)
    old_timestamp = time.strftime("%Y%m%d%H%M%S", time.localtime(time.time() - 31 * 86400))
    config.cparser.value.return_value = old_timestamp

    assert nowplaying.firstinstall.should_show_reminder_dialog(config) is True


def test_should_show_reminder_dialog_malformed_timestamp():
    """Test reminder dialog shown if timestamp is malformed."""
    config = Mock()
    config.initialized = True
    config.cparser.value.return_value = "malformed_timestamp"

    assert nowplaying.firstinstall.should_show_reminder_dialog(config) is True


def test_config_timestamp_saved(qapp):
    """Test that dialog shown timestamp is saved to config."""
    config = Mock()

    with (
        patch("nowplaying.firstinstall.QMessageBox") as mock_messagebox,
        patch("nowplaying.firstinstall.Qt") as mock_qt,
        patch("nowplaying.firstinstall.time") as mock_time,
        patch("nowplaying.firstinstall._show_arrow_overlay") as mock_arrow,
    ):
        mock_msgbox_instance = Mock()
        mock_msgbox_instance.windowFlags.return_value = Mock()
        mock_messagebox.return_value = mock_msgbox_instance

        mock_time.strftime.return_value = "20240101123456"

        nowplaying.firstinstall.show_first_install_dialog(config=config)

        # Verify timestamp was saved
        config.cparser.setValue.assert_called_with("settings/last_dialog_shown", "20240101123456")
        config.cparser.sync.assert_called_once()

        # Verify arrow overlay was called
        mock_arrow.assert_called_once()


def test_arrow_overlay_platform_detection():
    """Test arrow overlay platform detection."""
    overlay_class = nowplaying.firstinstall.FirstInstallArrowOverlay
    instance = overlay_class.__new__(overlay_class)

    # Test auto detection (should return menu_bar on macOS)
    with patch("sys.platform", "darwin"):
        result = instance._detect_platform_location("auto")
        assert result == "menu_bar"

    # Test Windows detection
    with patch("sys.platform", "win32"):
        result = instance._detect_platform_location("auto")
        assert result == "system_tray"

    # Test override
    result = instance._detect_platform_location("system_tray")
    assert result == "system_tray"


def test_arrow_overlay_position_calculation(qapp):
    """Test arrow overlay position calculation."""

    with patch("nowplaying.firstinstall.QApplication") as mock_app:
        mock_screen = Mock()
        mock_screen_rect = Mock()
        mock_screen_rect.width.return_value = 1920
        mock_screen_rect.height.return_value = 1080
        mock_screen.geometry.return_value = mock_screen_rect

        # Mock available geometry (for system tray calculations)
        mock_available_rect = Mock()
        mock_available_rect.width.return_value = 1920
        mock_available_rect.height.return_value = 1040  # 40 pixels for taskbar
        mock_screen.availableGeometry.return_value = mock_available_rect

        mock_app.primaryScreen.return_value = mock_screen

        overlay_class = nowplaying.firstinstall.FirstInstallArrowOverlay
        instance = overlay_class.__new__(overlay_class)
        instance.platform_location = "menu_bar"
        instance.tray_icon = None  # No tray icon, will use fallback positioning

        x, y = instance._get_arrow_position()
        # Should use fallback positioning for menu bar
        assert x == 1920 - 300  # 1620 (updated fallback logic)
        assert y == 120

        # Test system tray positioning
        instance.platform_location = "system_tray"
        x, y = instance._get_arrow_position()
        # Should use fallback positioning for system tray
        assert x == 1920 - 100  # 1820 (updated fallback logic)
        assert y == 1000  # screen_height - taskbar_height - 40 = 1080 - 40 - 40 = 1000


def test_arrow_overlay_direction():
    """Test arrow overlay direction detection."""
    overlay_class = nowplaying.firstinstall.FirstInstallArrowOverlay
    instance = overlay_class.__new__(overlay_class)

    # Menu bar should point up-right
    instance.platform_location = "menu_bar"
    direction = instance._get_arrow_direction()
    assert direction == "up_right"

    # System tray should point down-right
    instance.platform_location = "system_tray"
    direction = instance._get_arrow_direction()
    assert direction == "down_right"


@patch("nowplaying.firstinstall.FirstInstallArrowOverlay")
def test_show_arrow_overlay_error_handling(mock_overlay_class, qapp):
    """Test that arrow overlay errors don't crash the application."""
    # Make overlay creation raise an exception
    mock_overlay_class.side_effect = Exception("Mock overlay error")

    with patch("nowplaying.firstinstall.logging") as mock_logging:
        # Should not raise exception
        nowplaying.firstinstall._show_arrow_overlay()

        # Should log warning
        mock_logging.warning.assert_called_once()


def test_arrow_overlay_integration_with_dialog(qapp):
    """Test that arrow overlay is shown WITH first-install dialog and closed after."""
    config = Mock()
    mock_overlay = Mock()

    with (
        patch("nowplaying.firstinstall.QMessageBox") as mock_messagebox,
        patch("nowplaying.firstinstall.Qt") as mock_qt,
        patch("nowplaying.firstinstall._show_arrow_overlay") as mock_arrow,
    ):
        mock_msgbox_instance = Mock()
        mock_msgbox_instance.windowFlags.return_value = Mock()
        mock_messagebox.return_value = mock_msgbox_instance

        # Mock arrow overlay return
        mock_arrow.return_value = mock_overlay

        nowplaying.firstinstall.show_first_install_dialog(config=config)

        # Verify arrow overlay was shown BEFORE dialog
        mock_arrow.assert_called_once()

        # Verify overlay was closed after dialog
        mock_overlay.close.assert_called_once()


def test_arrow_overlay_integration_handles_none_gracefully(qapp):
    """Test that dialog works correctly when arrow overlay fails to create."""
    config = Mock()

    with (
        patch("nowplaying.firstinstall.QMessageBox") as mock_messagebox,
        patch("nowplaying.firstinstall.Qt") as mock_qt,
        patch("nowplaying.firstinstall._show_arrow_overlay") as mock_arrow,
    ):
        mock_msgbox_instance = Mock()
        mock_msgbox_instance.windowFlags.return_value = Mock()
        mock_messagebox.return_value = mock_msgbox_instance

        # Mock arrow overlay failure (returns None)
        mock_arrow.return_value = None

        # Should not raise exception
        nowplaying.firstinstall.show_first_install_dialog(config=config)

        # Verify arrow overlay was attempted
        mock_arrow.assert_called_once()

        # Dialog should still work normally
        mock_msgbox_instance.exec.assert_called_once()


def test_arrow_overlay_tray_icon_positioning(qapp):
    """Test arrow overlay positioning using actual tray icon geometry."""

    # Mock tray icon with known geometry
    mock_tray_icon = Mock()
    mock_geometry = Mock()
    mock_geometry.isValid.return_value = True
    mock_geometry.x.return_value = 1850  # Near right edge
    mock_geometry.y.return_value = 10  # Near top (macOS menu bar)
    mock_geometry.width.return_value = 20
    mock_geometry.height.return_value = 20
    mock_tray_icon.geometry.return_value = mock_geometry

    overlay_class = nowplaying.firstinstall.FirstInstallArrowOverlay
    instance = overlay_class.__new__(overlay_class)
    instance.platform_location = "menu_bar"
    instance.tray_icon = mock_tray_icon

    x, y = instance._get_arrow_position()

    # Should position arrow based on tray icon center with offset
    tray_center_x = 1850 + 20 // 2  # 1860
    tray_center_y = 10 + 20 // 2  # 20 (not used for macOS positioning)
    expected_x = tray_center_x - 80  # 1780
    expected_y = 120  # Fixed position below menu bar for macOS

    assert x == expected_x
    assert y == expected_y


def test_arrow_overlay_tray_icon_positioning_system_tray(qapp):
    """Test arrow overlay positioning for Windows/Linux system tray."""

    # Mock tray icon with known geometry (system tray position)
    mock_tray_icon = Mock()
    mock_geometry = Mock()
    mock_geometry.isValid.return_value = True
    mock_geometry.x.return_value = 1880  # Far right edge
    mock_geometry.y.return_value = 1050  # Near bottom
    mock_geometry.width.return_value = 16
    mock_geometry.height.return_value = 16
    mock_tray_icon.geometry.return_value = mock_geometry

    overlay_class = nowplaying.firstinstall.FirstInstallArrowOverlay
    instance = overlay_class.__new__(overlay_class)
    instance.platform_location = "system_tray"
    instance.tray_icon = mock_tray_icon

    x, y = instance._get_arrow_position()

    # Should position arrow based on tray icon center with offset
    tray_center_x = 1880 + 16 // 2  # 1888
    tray_center_y = 1050 + 16 // 2  # 1058
    expected_x = tray_center_x - 80  # 1808
    expected_y = tray_center_y - 50  # 1008

    assert x == expected_x
    assert y == expected_y


def test_arrow_overlay_tray_icon_fallback(qapp):
    """Test arrow overlay fallback when tray icon geometry is invalid."""

    # Mock tray icon with invalid geometry
    mock_tray_icon = Mock()
    mock_geometry = Mock()
    mock_geometry.isValid.return_value = False
    mock_tray_icon.geometry.return_value = mock_geometry

    # Mock screen for fallback positioning
    with patch("nowplaying.firstinstall.QApplication") as mock_app:
        mock_screen = Mock()
        mock_screen_rect = Mock()
        mock_screen_rect.width.return_value = 1920
        mock_screen_rect.height.return_value = 1080
        mock_screen.geometry.return_value = mock_screen_rect
        mock_app.primaryScreen.return_value = mock_screen

        overlay_class = nowplaying.firstinstall.FirstInstallArrowOverlay
        instance = overlay_class.__new__(overlay_class)
        instance.platform_location = "menu_bar"
        instance.tray_icon = mock_tray_icon

        x, y = instance._get_arrow_position()

        # Should fall back to screen-based positioning
        assert x == 1920 - 300  # 1620
        assert y == 120
