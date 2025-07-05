#!/usr/bin/env python3
""" Startup window for showing initialization progress """

import logging
import pathlib
from typing import Any

from PySide6.QtCore import Qt, QTimer  # pylint: disable=import-error,no-name-in-module
from PySide6.QtGui import QFont, QIcon  # pylint: disable=import-error,no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=import-error,no-name-in-module
    QDialog, QLabel, QProgressBar, QVBoxLayout)
from PySide6.QtGui import QPixmap  # pylint: disable=import-error,no-name-in-module

import nowplaying


class StartupWindow(QDialog):
    """Startup window showing initialization progress."""

    def __init__(self, bundledir: str = None) -> None:
        super().__init__()
        self.bundledir = pathlib.Path(bundledir) if bundledir else None
        self.progress_value = 0
        self.max_steps = 10  # More detailed steps now

        self._setup_ui()
        self._center_window()

        # Auto-close timer as failsafe (30 seconds max)
        self.failsafe_timer = QTimer()
        self.failsafe_timer.timeout.connect(self.accept)
        self.failsafe_timer.setSingleShot(True)
        self.failsafe_timer.start(30000)  # 30 seconds

        logging.debug("Startup window initialized")

    def _setup_ui(self) -> None:
        """Set up the startup window UI."""
        self.setWindowTitle("Starting What's Now Playing")
        self.setModal(True)
        self.setFixedSize(400, 200)

        # Remove window decorations for splash-like appearance
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)

        # Find icon file once
        iconfile = self._find_icon_file()

        # Set window icon (though not visible due to frameless window)
        if iconfile and iconfile.exists():
            self.setWindowIcon(QIcon(str(iconfile)))

        # Main layout
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(30, 10, 30, 25)

        # Icon label (if icon found)
        if iconfile and iconfile.exists():
            icon_label = QLabel()
            pixmap = QPixmap(str(iconfile))
            # Scale icon to reasonable size for splash screen
            scaled_pixmap = pixmap.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)
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
        # Get screen geometry
        screen = self.screen()
        if screen:
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
            search_dirs.extend([self.bundledir, self.bundledir / 'resources'])

        # Add standard nowplaying locations
        try:
            nowplaying_dir = pathlib.Path(nowplaying.__file__).parent
            search_dirs.extend([nowplaying_dir / 'resources', nowplaying_dir.parent / 'resources'])
        except (ImportError, AttributeError):
            pass

        # Search for icon files
        for testdir in search_dirs:
            if not testdir.exists():
                continue
            for testfilename in ['icon.ico', 'windows.ico']:
                testfile = testdir / testfilename
                if testfile.exists():
                    logging.debug('Found icon file at %s', testfile)
                    return testfile

        logging.debug('No icon file found')
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
            self.progress_value = progress
        else:
            self.progress_value += 1

        self.progress_bar.setValue(self.progress_value)

        # Force UI update
        self.repaint()

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

    def closeEvent(self, event: Any) -> None:  # pylint: disable=invalid-name
        """Handle close event."""
        logging.debug("Startup window closed")
        self.failsafe_timer.stop()
        super().closeEvent(event)
