#!/usr/bin/env python3
"""First install notification dialog with visual arrow overlay"""

import logging
import math
import sys
import time

from PySide6.QtCore import QPropertyAnimation, QRect, Qt, QTimer, QEasingCurve  # pylint: disable=no-name-in-module
from PySide6.QtGui import (  # pylint: disable=no-name-in-module
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QApplication,
    QGraphicsOpacityEffect,
    QMessageBox,
    QWidget,
)


class FirstInstallArrowOverlay(QWidget):  # pylint: disable=too-many-instance-attributes
    """Visual arrow overlay that points to system tray/menu bar location."""

    def __init__(self, platform_location: str = "auto", tray_icon=None):
        super().__init__()
        self.platform_location = self._detect_platform_location(platform_location)
        self.tray_icon = tray_icon
        self.arrow_scale = 1.0  # Still used for scale animation

        # Setup window properties
        self._setup_window()

        # Setup Qt-based animations (replaces manual timers)
        self._setup_qt_animations()

        # Auto-dismiss timer
        self.dismiss_timer = QTimer()
        self.dismiss_timer.setSingleShot(True)
        self.dismiss_timer.timeout.connect(self.close)

        logging.info("FirstInstallArrowOverlay created for %s", self.platform_location)

    @staticmethod
    def _detect_platform_location(location: str) -> str:
        """Detect platform-specific location for the arrow."""
        if location != "auto":
            return location

        if sys.platform == "darwin":
            return "menu_bar"
        return "system_tray"

    def _setup_window(self) -> None:
        """Setup window properties for full-screen transparent overlay."""
        # Make window frameless, transparent, and always on top
        # Use stronger flags to ensure it appears above menu bar on macOS
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.X11BypassWindowManagerHint  # Linux compatibility
            | Qt.WindowType.WindowDoesNotAcceptFocus  # Don't steal focus
            | Qt.WindowType.WindowTransparentForInput  # Allow clicks to pass through
        )

        # Enable transparency
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        # Make it full screen
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.geometry()
            self.setGeometry(screen_geometry)

        # Close on any click
        self.mousePressEvent = lambda event: self.close()  # pylint: disable=invalid-name

    def _setup_qt_animations(self) -> None:
        """Setup hardware-accelerated Qt animations."""
        # Opacity animation using QGraphicsOpacityEffect
        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)

        # Pulsing opacity animation
        self.opacity_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.opacity_animation.setDuration(2000)  # 2 second full cycle
        self.opacity_animation.setStartValue(0.3)  # Minimum opacity
        self.opacity_animation.setEndValue(1.0)  # Maximum opacity
        self.opacity_animation.setEasingCurve(QEasingCurve.Type.InOutSine)  # Smooth easing
        self.opacity_animation.setLoopCount(-1)  # Infinite loop

        # Scale animation - still use timer for math-based scaling
        # (Could be improved further with QGraphicsTransform, but this is simpler)
        self.scale_timer = QTimer()
        self.scale_timer.timeout.connect(self._animate_scale)
        self.scale_timer.start(50)  # Less frequent updates since opacity is handled by Qt

        # Start the animations
        self.opacity_animation.start()

    def _animate_scale(self) -> None:
        """Animate arrow scale for breathing effect."""
        # Use sin wave for smooth scaling
        self.arrow_scale = 0.9 + 0.1 * math.sin(time.time() * 3)
        self.update()  # Still need this for scale changes

    def _get_arrow_position(self) -> tuple[int, int]:  # pylint: disable=invalid-name
        """Calculate arrow position based on platform and tray icon location."""
        # pylint: disable=invalid-name  # x,y coordinate variables are conventional
        # Use actual tray icon position if available
        if self.tray_icon:
            try:
                tray_geometry = self.tray_icon.geometry()
                if tray_geometry.isValid():
                    # Point to the center of the tray icon with slight offset for arrow visibility
                    tray_center_x = tray_geometry.x() + tray_geometry.width() // 2
                    tray_center_y = tray_geometry.y() + tray_geometry.height() // 2

                    if self.platform_location == "menu_bar":
                        # macOS: Arrow points up-right to menu bar icon
                        # Position arrow well below menu bar to avoid being hidden behind it
                        x = tray_center_x - 80
                        y = 120  # Much lower to ensure entire arrow is visible below menu bar
                    else:
                        # Windows/Linux: Arrow points down-right to system tray icon
                        # Position arrow above and left of the icon
                        x = tray_center_x - 80
                        y = tray_center_y - 50  # Reduced from 60 to point closer

                    logging.debug(
                        "Using tray icon position: tray=(%d,%d), arrow=(%d,%d)",
                        tray_center_x,
                        tray_center_y,
                        x,
                        y,
                    )
                    return x, y
            except (AttributeError, RuntimeError) as exc:
                logging.debug("Could not get tray icon geometry: %s", exc)

        # Fallback to screen-based positioning if tray icon unavailable
        screen = QApplication.primaryScreen()
        if not screen:
            return 100, 100

        if self.platform_location == "menu_bar":
            # macOS: Point to a reasonable area in the menu bar
            screen_rect = screen.geometry()

            # Less aggressive positioning - more toward center-right of menu bar
            x = screen_rect.width() - 300  # Back away from the edge
            y = 120  # Lower down, closer to where user can actually see

        else:
            # Windows/Linux: Use availableGeometry to account for taskbar
            available_rect = screen.availableGeometry()
            screen_rect = screen.geometry()

            # Calculate taskbar position by comparing available vs full geometry
            taskbar_at_bottom = available_rect.height() < screen_rect.height()
            taskbar_at_right = available_rect.width() < screen_rect.width()

            if taskbar_at_bottom:
                # Taskbar at bottom (most common)
                taskbar_height = screen_rect.height() - available_rect.height()
                x = screen_rect.width() - 100  # System tray is usually far right
                y = screen_rect.height() - taskbar_height - 40  # Just above taskbar
            elif taskbar_at_right:
                # Taskbar at right
                taskbar_width = screen_rect.width() - available_rect.width()
                x = screen_rect.width() - taskbar_width - 40  # Just left of taskbar
                y = screen_rect.height() - 100
            else:
                # Fallback to bottom-right
                x = screen_rect.width() - 150
                y = screen_rect.height() - 150

        logging.debug("Using fallback screen positioning: (%d,%d)", x, y)
        return x, y

    def _get_arrow_direction(self) -> str:
        """Get arrow direction based on platform."""
        if self.platform_location == "menu_bar":
            return "up_right"  # Point up and to the right
        return "down_right"  # Point down and to the right

    def paintEvent(self, event) -> None:  # pylint: disable=invalid-name,unused-argument
        """Paint the arrow and instructional text."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Get arrow position and direction
        arrow_x, arrow_y = self._get_arrow_position()
        direction = self._get_arrow_direction()

        # Draw semi-transparent background circle
        self._draw_background_circle(painter, arrow_x, arrow_y)

        # Draw the arrow
        self._draw_arrow(painter, arrow_x, arrow_y, direction)

        # Draw instructional text
        self._draw_text(painter, arrow_x, arrow_y)

    def _draw_background_circle(self, painter: QPainter, x: int, y: int) -> None:  # pylint: disable=invalid-name
        """Draw a subtle background circle around the arrow."""
        # Set up semi-transparent brush (opacity handled by Qt effect)
        circle_color = QColor(0, 150, 255, 50)  # Fixed alpha, Qt handles overall opacity
        brush = QBrush(circle_color)
        painter.setBrush(brush)
        painter.setPen(Qt.PenStyle.NoPen)

        # Draw circle
        radius = int(60 * self.arrow_scale)
        painter.drawEllipse(x - radius, y - radius, radius * 2, radius * 2)

    def _draw_arrow(self, painter: QPainter, x: int, y: int, direction: str) -> None:  # pylint: disable=invalid-name
        """Draw the arrow pointing in the specified direction."""
        # Set up arrow color and pen (opacity handled by Qt effect)
        arrow_color = QColor(255, 100, 0, 255)  # Orange arrow, full alpha
        pen = QPen(arrow_color, 10)  # Much thicker line for better visibility
        brush = QBrush(arrow_color)
        painter.setPen(pen)
        painter.setBrush(brush)

        # Scale the arrow
        scale = self.arrow_scale

        if direction == "up_right":
            # Simple clean arrow pointing up and right (for macOS menu bar)
            # Draw arrow shaft (line from bottom-left to top-right)
            shaft_start_x = x
            shaft_start_y = y
            shaft_end_x = x + 60 * scale
            shaft_end_y = y - 60 * scale
            painter.drawLine(shaft_start_x, shaft_start_y, shaft_end_x, shaft_end_y)

            # Draw arrowhead at the end
            head_size = 20 * scale
            # Top part of arrowhead
            painter.drawLine(
                shaft_end_x, shaft_end_y, shaft_end_x - head_size, shaft_end_y + head_size * 0.5
            )
            # Right part of arrowhead
            painter.drawLine(
                shaft_end_x, shaft_end_y, shaft_end_x - head_size * 0.5, shaft_end_y + head_size
            )

        else:  # down_right
            # Simple clean arrow pointing down and right (for Windows/Linux system tray)
            # Draw arrow shaft (line from top-left to bottom-right)
            shaft_start_x = x
            shaft_start_y = y
            shaft_end_x = x + 60 * scale
            shaft_end_y = y + 60 * scale
            painter.drawLine(shaft_start_x, shaft_start_y, shaft_end_x, shaft_end_y)

            # Draw arrowhead at the end
            head_size = 20 * scale
            # Bottom part of arrowhead
            painter.drawLine(
                shaft_end_x, shaft_end_y, shaft_end_x - head_size, shaft_end_y - head_size * 0.5
            )
            # Right part of arrowhead
            painter.drawLine(
                shaft_end_x, shaft_end_y, shaft_end_x - head_size * 0.5, shaft_end_y - head_size
            )

    def _draw_text(self, painter: QPainter, x: int, y: int) -> None:  # pylint: disable=invalid-name
        """Draw instructional text near the arrow."""
        # Set up text properties (opacity handled by Qt effect)
        text_color = QColor(255, 255, 255, 200)  # White text, fixed alpha
        painter.setPen(QPen(text_color))

        font = QFont("Arial", 14, QFont.Weight.Bold)
        painter.setFont(font)

        # Platform-specific text
        if self.platform_location == "menu_bar":
            text = "What's Now Playing\nis running here!"
            text_x = x - 120
            text_y = y + 80
        else:
            text = "What's Now Playing\nis running here!"
            text_x = x - 120
            text_y = y - 80

        # Draw text with background for better visibility
        text_rect = QRect(text_x - 10, text_y - 30, 140, 50)

        # Semi-transparent background (opacity handled by Qt effect)
        bg_color = QColor(0, 0, 0, 100)  # Fixed alpha
        painter.fillRect(text_rect, bg_color)

        # Draw the text
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

    def show_with_timer(self, duration_ms: int = 5000) -> None:
        """Show the overlay and automatically dismiss after specified duration."""
        self.show()
        self.dismiss_timer.start(duration_ms)
        logging.info("FirstInstallArrowOverlay shown for %d ms", duration_ms)

    def closeEvent(self, event) -> None:  # pylint: disable=invalid-name
        """Handle close event."""
        logging.info("FirstInstallArrowOverlay closed")
        # Stop Qt animations
        self.opacity_animation.stop()
        self.scale_timer.stop()
        self.dismiss_timer.stop()
        super().closeEvent(event)


def should_show_reminder_dialog(config) -> bool:
    """Check if reminder dialog should be shown for returning users.

    Shows reminder if:
    - App is initialized (not first install)
    - Dialog was never shown before, OR
    - It's been more than 30 days since last dialog

    This helps users who may have tried older versions and are returning.
    """
    if not config.initialized:
        return False  # First install dialog will be shown instead

    last_dialog_shown = config.cparser.value("settings/last_dialog_shown", defaultValue="")
    if not last_dialog_shown:
        return True  # Never shown before - show for returning users from older versions

    try:
        # Parse timestamp format YYYYMMDDHHMMSS
        last_shown_time = time.strptime(last_dialog_shown, "%Y%m%d%H%M%S")
        last_shown_timestamp = time.mktime(last_shown_time)
        current_timestamp = time.time()

        # Show reminder if it's been more than 30 days since last dialog
        days_since_shown = (current_timestamp - last_shown_timestamp) / (24 * 60 * 60)
        return days_since_shown >= 30

    except (ValueError, TypeError):
        # If timestamp is malformed, show the dialog
        return True


def show_first_install_dialog(config=None, is_reminder: bool = False, tray_icon=None) -> None:
    """Show first-install notification dialog with platform-specific instructions."""
    dialog_type = "reminder" if is_reminder else "first-install"
    logging.info("Showing %s notification dialog", dialog_type)

    # Platform-specific message content
    if sys.platform == "darwin":
        platform_name = "macOS"
        location_text = "menu bar (top of screen)"
        icon_description = "menu bar icon"
        click_instruction = "Click the icon to access Settings, Pause/Resume, and other options"
    else:  # Windows and Linux
        platform_name = "Windows" if sys.platform == "win32" else "your system"
        location_text = "system tray (bottom-right corner)"
        icon_description = "system tray icon"
        click_instruction = (
            "Right-click the icon to access Settings, Pause/Resume, and other options"
        )

    if is_reminder:
        title = "What's Now Playing - Reminder"
        message = (
            f"<b>What's Now Playing is running!</b><br><br>"
            f"In case you've forgotten, What's Now Playing is running in the background "
            f"on {platform_name}.<br><br>"
            f"<b>To access the app:</b><br>"
            f"• Look for the What's Now Playing {icon_description} in your {location_text}<br>"
            f"• {click_instruction}<br><br>"
            f"The app continues running in the background even when you close this window."
        )
    else:
        title = "What's Now Playing - Setup Complete"
        message = (
            f"<b>Setup Complete!</b><br><br>"
            f"What's Now Playing is now running in the background on {platform_name}.<br><br>"
            f"<b>To access the app:</b><br>"
            f"• Look for the What's Now Playing {icon_description} in your {location_text}<br>"
            f"• {click_instruction}<br><br>"
            f"The app will continue running in the background even when you close this window."
        )

    # Create and configure the message box
    msgbox = QMessageBox()
    msgbox.setWindowTitle(title)
    msgbox.setTextFormat(Qt.TextFormat.RichText)
    msgbox.setText(message)
    msgbox.setStandardButtons(QMessageBox.StandardButton.Ok)
    msgbox.setIcon(QMessageBox.Icon.Information)

    # Make dialog stay on top and require acknowledgment
    msgbox.setWindowFlags(msgbox.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

    # Show visual arrow overlay BEFORE showing dialog so they appear together
    arrow_overlay = _show_arrow_overlay(tray_icon)

    # Show dialog and wait for user acknowledgment
    msgbox.exec()

    # Close the arrow overlay when dialog is dismissed
    if arrow_overlay:
        arrow_overlay.close()

    # Save timestamp when dialog was shown (if config is available)
    if config:
        current_timestamp = time.strftime("%Y%m%d%H%M%S")
        config.cparser.setValue("settings/last_dialog_shown", current_timestamp)
        config.cparser.sync()
        logging.info("Saved dialog shown timestamp: %s", current_timestamp)

    logging.info("%s notification dialog acknowledged by user", dialog_type)


def _show_arrow_overlay(tray_icon=None) -> FirstInstallArrowOverlay | None:
    """Show animated arrow overlay pointing to system tray/menu bar location."""
    try:
        overlay = FirstInstallArrowOverlay(tray_icon=tray_icon)
        overlay.show()  # Show without auto-dismiss timer

        # Force window to appear on top of everything including menu bar
        overlay.raise_()
        overlay.activateWindow()

        # Process events to ensure the overlay renders
        QApplication.processEvents()

        return overlay

    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Arrow overlay is nice-to-have, don't crash if it fails
        logging.warning("Failed to show arrow overlay: %s", exc)
        return None
