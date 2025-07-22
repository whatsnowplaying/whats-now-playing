#!/usr/bin/env python3
"""Startup window for showing initialization progress"""

import contextlib
import logging
import pathlib
from typing import Any

from PySide6.QtCore import Qt, QTimer  # pylint: disable=import-error,no-name-in-module
from PySide6.QtWidgets import QApplication  # pylint: disable=import-error,no-name-in-module
from PySide6.QtGui import QFont, QIcon  # pylint: disable=import-error,no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=import-error,no-name-in-module
    QDialog,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
)
from PySide6.QtGui import QPixmap, QKeyEvent  # pylint: disable=import-error,no-name-in-module

import nowplaying


class StartupWindow(QDialog):  # pylint: disable=too-many-instance-attributes
    """Startup window showing initialization progress."""

    def __init__(self, bundledir: str = None, **kwargs) -> None:
        super().__init__()
        self.bundledir = pathlib.Path(bundledir) if bundledir else None
        self.progress_value = 0
        self.max_steps = 10  # More detailed steps now
        self.drag_position = None  # For window dragging

        self._failsafe_timeout_ms = kwargs.get("failsafe_timeout_ms", 30000)  # Default 30 seconds
        self._failsafe_warning_ms = kwargs.get("failsafe_warning_ms", 5000)  # Warn 5 seconds before

        self._setup_ui()
        self._center_window()

        # Auto-close timer as failsafe (configurable)
        self.failsafe_timer = QTimer()
        self.failsafe_timer.timeout.connect(self.accept)
        self.failsafe_timer.setSingleShot(True)
        self.failsafe_timer.start(self._failsafe_timeout_ms)

        # Warning timer to notify user before failsafe triggers
        self.failsafe_warning_timer = QTimer()
        self.failsafe_warning_timer.setSingleShot(True)
        self.failsafe_warning_timer.timeout.connect(self._show_failsafe_warning)
        self.failsafe_warning_timer.start(self._failsafe_timeout_ms - self._failsafe_warning_ms)

        logging.debug("Startup window initialized")

    def _setup_ui(self) -> None:  # pylint: disable=too-many-statements
        """Set up the startup window UI."""
        self.setWindowTitle("Starting What's Now Playing - Press Escape to cancel")
        self.setModal(True)
        self.setFixedSize(400, 240)  # Slightly taller for close button and warning label

        # Remove window decorations for splash-like appearance
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

        # Find icon file once
        iconfile = self._find_icon_file()

        # Set window icon (though not visible due to frameless window)
        if iconfile and iconfile.exists():
            self.setWindowIcon(QIcon(str(iconfile)))

        # Enable focus to receive keyboard events
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(30, 10, 30, 25)

        # Add close button at the top right for accessibility
        top_layout = QHBoxLayout()
        top_layout.addStretch()  # Push button to the right

        self.close_button = QPushButton("X")
        self.close_button.setFixedSize(20, 20)
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.1);
                border: none;
                color: gray;
                font-weight: bold;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: rgba(255, 0, 0, 0.3);
                color: white;
            }
            QPushButton:pressed {
                background-color: rgba(255, 0, 0, 0.5);
            }
        """)
        self.close_button.setToolTip("Close (or press Escape)")
        self.close_button.clicked.connect(self.accept)

        top_layout.addWidget(self.close_button)
        layout.addLayout(top_layout)

        # Icon label (if icon found)
        if iconfile and iconfile.exists():
            icon_label = QLabel()
            pixmap = QPixmap(str(iconfile))
            # Scale icon to reasonable size for splash screen
            scaled_pixmap = pixmap.scaled(
                48,
                48,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon_label.setPixmap(scaled_pixmap)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_label)
            layout.addSpacing(2)

        # Title label
        title_label = QLabel("What's Now Playing")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: rgba(0, 0, 0, 0.7);")  # Semi-transparent black text
        title_label.setFixedHeight(20)  # Constrain the label height to just what's needed
        layout.addWidget(title_label)

        # Add extra spacing after title
        layout.addSpacing(2)

        # Status label
        self.status_label = QLabel("Initializing...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(self.max_steps)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Warning label for failsafe notification (initially hidden)
        self.failsafe_warning_label = QLabel("")
        self.failsafe_warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.failsafe_warning_label.setStyleSheet("color: red; font-size: 10px;")
        self.failsafe_warning_label.setWordWrap(True)
        layout.addWidget(self.failsafe_warning_label)

        # Version label (small, bottom)
        try:
            version_label = QLabel(f"Version {nowplaying.__version__}")
            version_font = QFont()
            version_font.setPointSize(8)
            version_label.setFont(version_font)
            version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            version_label.setStyleSheet("color: gray;")
            layout.addWidget(version_label)
        except AttributeError:
            # If version isn't available, just skip it
            pass

    def _center_window(self) -> None:
        """Center the window on the screen."""
        if screen := self.screen():
            screen_geometry = screen.availableGeometry()
            window_geometry = self.frameGeometry()
            center_point = screen_geometry.center()
            window_geometry.moveCenter(center_point)
            self.move(window_geometry.topLeft())

    def _find_icon_file(self) -> pathlib.Path | None:
        """Find the icon file using the same logic as ConfigFile."""
        # Try different possible locations for the icon
        search_dirs = []

        # Add bundledir if available
        if self.bundledir:
            search_dirs.extend([self.bundledir, self.bundledir / "resources"])

        # Add standard nowplaying locations
        with contextlib.suppress(ImportError, AttributeError):
            nowplaying_dir = pathlib.Path(nowplaying.__file__).parent
            search_dirs.extend([nowplaying_dir / "resources", nowplaying_dir.parent / "resources"])
        # Search for icon files
        for testdir in search_dirs:
            if not testdir.exists():
                continue
            for testfilename in ["icon.ico", "windows.ico"]:
                testfile = testdir / testfilename
                if testfile.exists():
                    logging.debug("Found icon file at %s", testfile)
                    return testfile

        logging.debug("No icon file found")
        return None

    def update_progress(self, step: str, progress: int | None = None) -> None:
        """Update the progress display.

        Args:
            step: Description of current step
            progress: Optional specific progress value (0-max_steps)
        """
        logging.debug("Startup progress: %s", step)

        # Update status text
        self.status_label.setText(step)

        # Update progress bar
        if progress is not None:
            self.progress_value = min(progress, self.max_steps)
        else:
            self.progress_value = min(self.progress_value + 1, self.max_steps)

        self.progress_bar.setValue(self.progress_value)

        # Process events to keep UI responsive during long operations
        QApplication.processEvents()

    def complete_startup(self) -> None:
        """Mark startup as complete and close window."""
        logging.debug("Startup complete, closing startup window")
        self.update_progress("Startup complete", self.max_steps)

        # Small delay to show completion, then close
        QTimer.singleShot(500, self.accept)

    def show_error(self, error_message: str) -> None:
        """Show an error message and keep window open.

        Args:
            error_message: Error message to display
        """
        logging.error("Startup error: %s", error_message)
        self.status_label.setText(f"Error: {error_message}")
        self.status_label.setStyleSheet("color: red;")

        # Cancel failsafe timer since we have an error
        self.failsafe_timer.stop()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # pylint: disable=invalid-name
        """Handle key press events for accessibility."""
        if event.key() == Qt.Key.Key_Escape:
            logging.debug("Startup window closed via Escape key")
            self.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # pylint: disable=invalid-name
        """Handle mouse press for window dragging."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # pylint: disable=invalid-name
        """Handle mouse move for window dragging."""
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def _show_failsafe_warning(self) -> None:
        """Show warning that window will auto-close soon."""
        warning_seconds = self._failsafe_warning_ms // 1000
        self.failsafe_warning_label.setText(
            f"Initialization is taking longer than expected. "
            f"This window will close in {warning_seconds} seconds."
        )
        logging.warning(
            "Startup taking longer than expected, auto-closing in %d seconds", warning_seconds
        )

    def closeEvent(self, event: Any) -> None:  # pylint: disable=invalid-name
        """Handle close event."""
        logging.debug("Startup window closed")
        self.failsafe_timer.stop()
        if hasattr(self, "failsafe_warning_timer"):
            self.failsafe_warning_timer.stop()
        super().closeEvent(event)
