#!/usr/bin/env python3
"""Real-time Setlist Notification Plugin"""

import logging
import pathlib
import time
from typing import TYPE_CHECKING

import jinja2

import nowplaying.utils
from nowplaying.exceptions import PluginVerifyError
from nowplaying.types import TrackMetadata
from . import NotificationPlugin

if TYPE_CHECKING:
    import nowplaying.config
    import nowplaying.imagecache
    from PySide6.QtWidgets import QWidget
    from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module
    from nowplaying.utils import TemplateHandler


class Plugin(NotificationPlugin):
    """Real-time Setlist Notification Handler"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Real-time Setlist"
        self.enabled = False
        self.template_file: str | None = None
        self.file_pattern: str | None = None
        self.setlist_file: pathlib.Path | None = None
        self.templatehandler: TemplateHandler | None = None

    async def notify_track_change(
        self, metadata: TrackMetadata, imagecache: "nowplaying.imagecache.ImageCache|None" = None
    ) -> None:
        """
        Append track metadata to setlist file when a new track becomes live

        Args:
            metadata: Track metadata including artist, title, etc.
            imagecache: Optional imagecache instance (unused by setlist)
        """

        if not self.enabled:
            return

        try:
            self._setup_handler()

            if not self.templatehandler or not self.setlist_file:
                return

            # Generate text from template
            entry_text = self.templatehandler.generate(metadata)

            # Always append to setlist file
            with open(self.setlist_file, "a", encoding="utf-8") as setlist_fh:
                setlist_fh.write(entry_text)
                # Add newline after each entry if template doesn't include one
                if not entry_text.endswith("\n"):
                    setlist_fh.write("\n")

            logging.info("Real-time setlist entry written to: %s", self.setlist_file)

        except Exception as error:  # pylint: disable=broad-except
            logging.error("Real-time setlist notification failed: %s", error)

    def _setup_handler(self):
        """Set up template handler and output file"""
        if not self.config:
            return

        new_template_file: str | None = self.config.cparser.value(
            "realtimesetlist/template", defaultValue=None
        )
        new_file_pattern: str | None = self.config.cparser.value(
            "realtimesetlist/filepattern", defaultValue=None
        )

        # Check if we're enabled
        if not new_template_file or not new_file_pattern:
            self.enabled = False
            return

        self.enabled = True

        # Generate filename from pattern if it changed
        if new_file_pattern != self.file_pattern:
            self.file_pattern = new_file_pattern
            self._generate_filename()

        # Set up template handler if template changed
        if new_template_file != self.template_file:
            self.template_file = new_template_file
            if pathlib.Path(new_template_file).exists():
                try:
                    self.templatehandler = nowplaying.utils.TemplateHandler(
                        filename=new_template_file
                    )
                    logging.debug("Real-time setlist template loaded: %s", self.template_file)
                except (jinja2.TemplateError, OSError) as error:
                    logging.error(
                        "Failed to load real-time setlist template %s: %s",
                        new_template_file,
                        error,
                    )
                    self.enabled = False
                    return
            else:
                logging.error("Template file not found: %s", new_template_file)
                self.enabled = False

        # Make sure we have a setlist file even if pattern didn't change
        if not self.setlist_file and self.file_pattern:
            self._generate_filename()

    def _generate_filename(self):
        """Generate the setlist filename from the pattern"""
        if not self.config or not self.file_pattern:
            return

        # Get setlist directory
        setlist_dir = pathlib.Path(self.config.getsetlistdir())
        setlist_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename using strftime for date/time patterns
        filename = time.strftime(self.file_pattern)
        self.setlist_file = setlist_dir / filename

        logging.debug("Real-time setlist file: %s", self.setlist_file)

    async def start(self) -> None:
        """Initialize the real-time setlist notification plugin"""
        if self.config:
            self._setup_handler()

        if not self.enabled:
            return

        logging.debug("Real-time setlist notifications started")

    async def stop(self) -> None:
        """Clean up the real-time setlist notification plugin"""
        if self.enabled:
            logging.debug("Real-time setlist notifications stopped")

    def defaults(self, qsettings: "QSettings"):
        """Set default configuration values"""
        # Set some sensible defaults
        qsettings.setValue("realtimesetlist/template", "")
        qsettings.setValue("realtimesetlist/filepattern", "setlist-%Y%m%d-%H%M%S.txt")

    def load_settingsui(self, qwidget: "QWidget"):
        """Load settings into UI"""
        # Check if real-time setlist is effectively enabled
        template_file = self.config.cparser.value("realtimesetlist/template", defaultValue="")
        file_pattern = self.config.cparser.value("realtimesetlist/filepattern", defaultValue="")
        qwidget.enable_checkbox.setChecked(bool(template_file and file_pattern))

        qwidget.template_lineedit.setText(
            self.config.cparser.value("realtimesetlist/template", defaultValue="")
        )

        qwidget.filepattern_lineedit.setText(
            self.config.cparser.value(
                "realtimesetlist/filepattern", defaultValue="setlist-%Y%m%d-%H%M%S.txt"
            )
        )

    def save_settingsui(self, qwidget: "QWidget"):
        """Save settings from UI"""
        self.config.cparser.setValue("realtimesetlist/template", qwidget.template_lineedit.text())
        self.config.cparser.setValue(
            "realtimesetlist/filepattern", qwidget.filepattern_lineedit.text()
        )

    def verify_settingsui(self, qwidget: "QWidget") -> bool:
        """Verify settings"""
        if qwidget.enable_checkbox.isChecked():
            template_path = qwidget.template_lineedit.text().strip()
            file_pattern = qwidget.filepattern_lineedit.text().strip()

            if not template_path:
                raise PluginVerifyError(
                    "Template file path is required when real-time setlist is enabled"
                )
            if not file_pattern:
                raise PluginVerifyError(
                    "File pattern is required when real-time setlist is enabled"
                )
            if not pathlib.Path(template_path).exists():
                raise PluginVerifyError(f"Template file does not exist: {template_path}")

            # Test file pattern with strftime
            try:
                _ = time.strftime(file_pattern)
            except ValueError as err:
                raise PluginVerifyError(f"Invalid file pattern: {err}") from err

        return True

    def connect_settingsui(self, qwidget: "QWidget", uihelp):
        """Connect UI elements to their handlers"""
        qwidget.template_button.clicked.connect(
            lambda: uihelp.template_picker_lineedit(
                qwidget.template_lineedit, limit="setlist-*.txt"
            )
        )

    def desc_settingsui(self, qwidget: "QWidget"):
        """Description for settings UI"""
        qwidget.setText(
            "Generate a real-time setlist that appends each track as it plays, "
            "using a customizable template and filename pattern with date/time formatting"
        )
