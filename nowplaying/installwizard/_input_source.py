#!/usr/bin/env python3
"""Input source selection page for the installation wizard."""

# pylint: disable=no-name-in-module,duplicate-code

import logging

from PySide6.QtWidgets import (
    QButtonGroup,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)

import nowplaying.config
from nowplaying.installwizard._constants import PAGE_ARTISTEXTRAS, PAGE_INPUT_CONFIG


class _InputSourcePage(QWizardPage):
    """Pick which DJ software What's Now Playing reads from."""

    def __init__(
        self, config: nowplaying.config.ConfigFile, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.setTitle("Select Your DJ Software")
        self.setSubTitle(
            "Choose the software What's Now Playing should read track "
            "information from. Software detected on this computer is "
            "marked with ✓."
        )
        # (radio_button, short_module_name, display_name)
        self._entries: list[tuple[QRadioButton, str, str]] = []
        self._button_group = QButtonGroup(self)
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner_widget = QWidget()
        inner = QVBoxLayout()

        plugins = self.config.plugins.get("inputs", {})
        first_detected: QRadioButton | None = None

        for key in sorted(plugins):
            module = plugins[key]
            short_name = key.replace("nowplaying.inputs.", "")
            try:
                plugin_obj = module.Plugin(config=self.config)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("wizard: could not load input plugin %s", key)
                continue

            display = plugin_obj.displayname
            detected = False
            try:
                detected = bool(plugin_obj.install())
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("wizard: install() failed for %s", key)

            label = f"✓  {display}" if detected else f"    {display}"
            btn = QRadioButton(label)
            self._entries.append((btn, short_name, display))
            self._button_group.addButton(btn)
            inner.addWidget(btn)

            if detected and first_detected is None:
                first_detected = btn

        inner.addStretch()
        inner_widget.setLayout(inner)
        scroll.setWidget(inner_widget)
        outer.addWidget(scroll)
        self.setLayout(outer)

        if first_detected is not None:
            first_detected.setChecked(True)
        elif self._entries:
            self._entries[0][0].setChecked(True)

        self._button_group.buttonClicked.connect(self._on_selection_changed)

    def initializePage(self) -> None:  # pylint: disable=invalid-name
        """Register the config page for whichever input is preselected on first show."""
        self._on_selection_changed()

    def _on_selection_changed(self) -> None:
        """Rebuild the plugin-specific config page whenever the selection changes."""
        wizard = self.wizard()
        if wizard is None:
            return
        if PAGE_INPUT_CONFIG in wizard.pageIds():
            wizard.removePage(PAGE_INPUT_CONFIG)
        short_name = self.selected_short_name()
        if not short_name:
            return
        module = self.config.plugins.get("inputs", {}).get(f"nowplaying.inputs.{short_name}")
        if not module:
            return
        try:
            plugin_obj = module.Plugin(config=self.config)
            if plugin_obj.wizardpage is not None:
                page = plugin_obj.wizardpage(config=self.config)
                wizard.setPage(PAGE_INPUT_CONFIG, page)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("wizard: no wizard page for %s", short_name)

    def selected_short_name(self) -> str | None:
        """Return the short module name of the selected input plugin."""
        for btn, short_name, _ in self._entries:
            if btn.isChecked():
                return short_name
        return None

    def selected_display_name(self) -> str:
        """Return the human-readable name of the selected input plugin."""
        for btn, _, display in self._entries:
            if btn.isChecked():
                return display
        return ""

    def isComplete(self) -> bool:  # pylint: disable=invalid-name
        """Page is complete when a radio button is selected."""
        return self.selected_short_name() is not None

    def nextId(self) -> int:  # pylint: disable=invalid-name
        """Route to the plugin config page if one was registered, else artist extras."""
        wizard = self.wizard()
        if wizard and PAGE_INPUT_CONFIG in wizard.pageIds():
            return PAGE_INPUT_CONFIG
        return PAGE_ARTISTEXTRAS
