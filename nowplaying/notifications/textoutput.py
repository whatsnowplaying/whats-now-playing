#!/usr/bin/env python3
"""Text Output Notification Plugin"""

import logging
import pathlib
from typing import TYPE_CHECKING

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
    """Text Output Notification Handler"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Text Output"
        self.enabled = False
        self.output_file: str | None = None
        self.template_file: str | None = None
        self.txttemplatehandler: TemplateHandler | None = None

    async def notify_track_change(
        self, metadata: TrackMetadata, imagecache: "nowplaying.imagecache.ImageCache|None" = None
    ) -> None:
        """
        Write track metadata to text file when a new track becomes live

        Args:
            metadata: Track metadata including artist, title, etc.
            imagecache: Optional imagecache instance (unused by text output)
        """

        self._setup_handler()
        if not self.enabled or not self.output_file:
            return

        try:
            # check to see if changed
            self._setup_handler()

            if not self.txttemplatehandler:
                return

            # Generate text from template
            txttemplate = self.txttemplatehandler.generate(metadata)

            # Determine write mode based on append setting
            if self.config and self.config.cparser.value("textoutput/fileappend", type=bool):
                mode = "a"
            else:
                mode = "w"

            # Write to text file (need to specifically open as utf-8 for pyinstaller)
            with open(self.output_file, mode, encoding="utf-8") as textfh:
                textfh.write(txttemplate)

            logging.debug("Text output written to: %s", self.output_file)

        except Exception as error:  # pylint: disable=broad-except
            logging.error("Text output notification failed: %s", error)

    def _setup_handler(self):
        new_output_file: str | None = self.config.cparser.value(
            "textoutput/file", defaultValue=None
        )
        new_template_file: str | None = self.config.cparser.value(
            "textoutput/txttemplate", defaultValue=None
        )

        if not new_output_file:
            self.enabled = False
            return

        self.enabled = True
        if new_output_file != self.output_file:
            self.output_file = new_output_file

        if not new_template_file:
            self.txttemplatehandler = nowplaying.utils.TemplateHandler(
                rawtemplate="{{ artist }} - {{ title }}"
            )
        elif new_template_file != self.template_file:
            self.template_file = new_template_file
            self.txttemplatehandler = nowplaying.utils.TemplateHandler(filename=new_template_file)
            logging.debug("Text output template reloaded: %s", self.template_file)

    async def start(self) -> None:
        """Initialize the text output notification plugin"""
        if self.config:
            self._setup_handler()

        if not self.enabled:
            return

        # Clear text file on startup if configured
        if (
            self.config
            and self.config.cparser.value("textoutput/clearonstartup", type=bool)
            and self.output_file
        ):
            try:
                with open(self.output_file, "w", encoding="utf-8") as textfh:
                    _ = textfh.write("")
                logging.debug("Text output file cleared on startup: %s", self.output_file)
            except Exception as error:  # pylint: disable=broad-except
                logging.error("Failed to clear text output file: %s", error)
        else:
            logging.debug("Text output disabled - missing file or template configuration")

    async def stop(self) -> None:
        """Clean up the text output notification plugin"""
        if self.enabled:
            logging.debug("Text output notifications stopped")

    def defaults(self, qsettings: "QSettings"):
        """Set default configuration values"""
        # Text output uses existing textoutput/* keys, so no defaults needed here

    def load_settingsui(self, qwidget: "QWidget"):
        """Load settings into UI"""
        if hasattr(qwidget, "enable_checkbox"):
            # Check if text output is effectively enabled
            output_file = self.config.cparser.value("textoutput/file", defaultValue="")
            template_file = self.config.cparser.value("textoutput/txttemplate", defaultValue="")
            qwidget.enable_checkbox.setChecked(bool(output_file and template_file))

        if hasattr(qwidget, "file_lineedit"):
            qwidget.file_lineedit.setText(
                self.config.cparser.value("textoutput/file", defaultValue="")
            )

        if hasattr(qwidget, "template_lineedit"):
            qwidget.template_lineedit.setText(
                self.config.cparser.value("textoutput/txttemplate", defaultValue="")
            )

    def save_settingsui(self, qwidget: "QWidget"):
        """Save settings from UI"""
        if hasattr(qwidget, "file_lineedit"):
            self.config.cparser.setValue("textoutput/file", qwidget.file_lineedit.text())

        if hasattr(qwidget, "template_lineedit"):
            self.config.cparser.setValue("textoutput/txttemplate", qwidget.template_lineedit.text())

    def verify_settingsui(self, qwidget: "QWidget") -> bool:
        """Verify settings"""
        if hasattr(qwidget, "enable_checkbox") and qwidget.enable_checkbox.isChecked():
            if hasattr(qwidget, "file_lineedit") and not qwidget.file_lineedit.text().strip():
                raise PluginVerifyError("Output file path is required when text output is enabled")

            if (
                hasattr(qwidget, "template_lineedit")
                and not qwidget.template_lineedit.text().strip()
            ):
                raise PluginVerifyError(
                    "Template file path is required when text output is enabled"
                )

            # Verify template file exists
            if hasattr(qwidget, "template_lineedit"):
                template_path = qwidget.template_lineedit.text().strip()
                if template_path and not pathlib.Path(template_path).exists():
                    raise PluginVerifyError(f"Template file does not exist: {template_path}")
        return True

    def desc_settingsui(self, qwidget: "QWidget"):
        """Description for settings UI"""
        qwidget.setText(
            "Write track metadata to a text file using a customizable template when tracks change"
        )
