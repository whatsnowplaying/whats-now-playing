#!/usr/bin/env python3
"""Discord settings UI class"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Slot  # pylint: disable=no-name-in-module

import nowplaying.preview.textwindow
import nowplaying.utils.qt

if TYPE_CHECKING:
    import nowplaying.config


class DiscordSettings:
    """Settings UI handler for the Discord integration."""

    def __init__(self) -> None:
        self.config: nowplaying.config.ConfigFile | None = None
        self._widget: Any = None
        self._uihelp: Any = None
        self._template_preview: nowplaying.preview.textwindow.TextPreviewWindow | None = None
        self._channel_template_preview: nowplaying.preview.textwindow.TextPreviewWindow | None = (
            None
        )

    def connect(self, uihelp: Any, widget: Any) -> None:
        """Connect widget signals."""
        self._uihelp = uihelp
        self._widget = widget
        widget.template_button.clicked.connect(self._on_template_button)
        widget.template_preview_button.clicked.connect(self._on_template_preview_button)
        widget.channel_template_button.clicked.connect(self._on_channel_template_button)
        widget.channel_template_preview_button.clicked.connect(
            self._on_channel_template_preview_button
        )
        widget.richpresence_enable_checkbox.toggled.connect(
            lambda _: DiscordSettings._update_fields(widget)
        )
        widget.bot_enable_checkbox.toggled.connect(
            lambda _: DiscordSettings._update_fields(widget)
        )

    def load(
        self,
        config: nowplaying.config.ConfigFile,
        widget: Any,
        _uihelp: Any,
    ) -> None:
        """Load config values into the Discord settings widget."""
        self.config = config
        self._widget = widget
        widget.richpresence_enable_checkbox.setChecked(
            config.cparser.value("discord/richpresence_enabled", type=bool)
        )
        widget.bot_enable_checkbox.setChecked(
            config.cparser.value("discord/bot_enabled", type=bool)
        )
        widget.clientid_lineedit.setText(config.cparser.value("discord/clientid") or "")
        widget.token_lineedit.setText(config.cparser.value("discord/token") or "")
        widget.channel_id_lineedit.setText(config.cparser.value("discord/channel_id") or "")
        widget.channel_attach_image_checkbox.setChecked(
            config.cparser.value("discord/channel_attach_image", type=bool)
        )
        widget.channel_image_size_spinbox.setValue(
            config.cparser.value("discord/channel_image_size", type=int) or 200
        )
        widget.channel_template_lineedit.setText(
            config.cparser.value("discord/channel_template") or ""
        )
        widget.channel_strip_extra_lines_checkbox.setChecked(
            config.cparser.value("discord/channel_strip_extra_lines", type=bool)
        )
        widget.channel_post_as_embed_checkbox.setChecked(
            config.cparser.value("discord/channel_post_as_embed", type=bool)
        )
        widget.template_lineedit.setText(config.cparser.value("discord/template") or "")
        DiscordSettings._update_fields(widget)

    @staticmethod
    def save(
        config: nowplaying.config.ConfigFile,
        widget: Any,
        subprocesses: Any,
    ) -> None:
        """Save Discord widget values to config."""
        old_bot = config.cparser.value("discord/bot_enabled", type=bool)
        old_rp = config.cparser.value("discord/richpresence_enabled", type=bool)
        new_bot = widget.bot_enable_checkbox.isChecked()
        new_rp = widget.richpresence_enable_checkbox.isChecked()

        config.cparser.setValue("discord/richpresence_enabled", new_rp)
        config.cparser.setValue("discord/bot_enabled", new_bot)
        config.cparser.setValue("discord/clientid", widget.clientid_lineedit.text())
        config.cparser.setValue("discord/token", widget.token_lineedit.text())
        config.cparser.setValue("discord/channel_id", widget.channel_id_lineedit.text())
        config.cparser.setValue(
            "discord/channel_attach_image", widget.channel_attach_image_checkbox.isChecked()
        )
        config.cparser.setValue(
            "discord/channel_image_size", widget.channel_image_size_spinbox.value()
        )
        config.cparser.setValue(
            "discord/channel_template", widget.channel_template_lineedit.text()
        )
        config.cparser.setValue(
            "discord/channel_strip_extra_lines",
            widget.channel_strip_extra_lines_checkbox.isChecked(),
        )
        config.cparser.setValue(
            "discord/channel_post_as_embed",
            widget.channel_post_as_embed_checkbox.isChecked(),
        )
        config.cparser.setValue("discord/template", widget.template_lineedit.text())

        if old_bot != new_bot or old_rp != new_rp:
            subprocesses.restart_discordbot()

    @staticmethod
    def defaults(settings: Any) -> None:
        """Write default values for all discord/ keys."""
        settings.setValue("discord/richpresence_enabled", False)
        settings.setValue("discord/bot_enabled", False)
        settings.setValue("discord/clientid", "")
        settings.setValue("discord/token", "")
        settings.setValue("discord/template", "")
        settings.setValue("discord/channel_id", "")
        settings.setValue("discord/channel_attach_image", False)
        settings.setValue("discord/channel_image_size", 200)
        settings.setValue("discord/channel_template", "")
        settings.setValue("discord/channel_strip_extra_lines", False)
        settings.setValue("discord/channel_post_as_embed", False)
        settings.setValue("discord/large_image_key", "")
        settings.setValue("discord/small_image_key", "")

    @staticmethod
    def _update_fields(widget: Any) -> None:
        """Enable/disable fields based on which Discord modes are active."""
        rp_enabled = widget.richpresence_enable_checkbox.isChecked()
        bot_enabled = widget.bot_enable_checkbox.isChecked()
        either_enabled = rp_enabled or bot_enabled

        widget.clientid_label.setEnabled(rp_enabled)
        widget.clientid_lineedit.setEnabled(rp_enabled)

        widget.token_label.setEnabled(bot_enabled)
        widget.token_lineedit.setEnabled(bot_enabled)
        widget.channel_id_label.setEnabled(bot_enabled)
        widget.channel_id_lineedit.setEnabled(bot_enabled)
        widget.channel_attach_image_checkbox.setEnabled(bot_enabled)
        widget.channel_image_size_label.setEnabled(bot_enabled)
        widget.channel_image_size_spinbox.setEnabled(bot_enabled)
        widget.channel_template_label.setEnabled(bot_enabled)
        widget.channel_template_lineedit.setEnabled(bot_enabled)
        widget.channel_template_button.setEnabled(bot_enabled)
        widget.channel_template_preview_button.setEnabled(bot_enabled)
        widget.channel_strip_extra_lines_checkbox.setEnabled(bot_enabled)
        widget.channel_post_as_embed_checkbox.setEnabled(bot_enabled)

        widget.template_label.setEnabled(either_enabled)
        widget.template_lineedit.setEnabled(either_enabled)
        widget.template_button.setEnabled(either_enabled)
        widget.template_preview_button.setEnabled(either_enabled)

    def _show_preview(self, attr: str, config_key: str, on_selected: Any) -> None:
        """Create (if needed) and raise a Discord text template preview window."""
        window: nowplaying.preview.textwindow.TextPreviewWindow | None = getattr(self, attr)
        if window is None:
            window = nowplaying.preview.textwindow.TextPreviewWindow(
                config=self.config,
                config_key=config_key,
                enable_select_button=True,
            )
            window.template_selected.connect(on_selected)
            setattr(self, attr, window)
        window.populate_templates()  # pyright: ignore[reportAttributeAccessIssue]
        nowplaying.utils.qt.focus_window(window)

    @Slot()
    def _on_template_button(self) -> None:
        if self._uihelp and self._widget:
            self._uihelp.template_picker_lineedit(self._widget.template_lineedit)

    @Slot()
    def _on_channel_template_button(self) -> None:
        if self._uihelp and self._widget:
            self._uihelp.template_picker_lineedit(self._widget.channel_template_lineedit)

    @Slot()
    def _on_template_preview_button(self) -> None:
        self._show_preview(
            "_template_preview",
            "discord/template",
            self._on_template_selected,
        )

    @Slot(str)
    def _on_template_selected(self, template_name: str) -> None:
        if self._widget and self.config:
            self._widget.template_lineedit.setText(
                str(pathlib.Path(self.config.templatedir) / template_name)
            )

    @Slot()
    def _on_channel_template_preview_button(self) -> None:
        self._show_preview(
            "_channel_template_preview",
            "discord/channel_template",
            self._on_channel_template_selected,
        )

    @Slot(str)
    def _on_channel_template_selected(self, template_name: str) -> None:
        if self._widget and self.config:
            self._widget.channel_template_lineedit.setText(
                str(pathlib.Path(self.config.templatedir) / template_name)
            )
