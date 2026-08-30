#!/usr/bin/env python3
"""Input source selection page for the setup wizard."""

# pylint: disable=no-name-in-module,duplicate-code

import logging

from PySide6.QtWidgets import (
    QButtonGroup,
    QLabel,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)

import nowplaying.config
import nowplaying.inputs
import nowplaying.wizard
from nowplaying.setupwizard._constants import (
    PAGE_INPUT_CONFIG,
    PAGE_OUTPUTS,
    PAGE_REMOTE_OUTPUT,
)
from nowplaying.setupwizard._host import drop_page, setup_wizard


class _ConfigUnavailablePage(nowplaying.wizard.WizardPage):
    """Stand-in for a plugin config page that could not be constructed.

    Says so plainly and lets setup continue: the alternative is trapping the
    user on a page they cannot fix from, and the source is still selectable
    and configurable from Settings afterwards.
    """

    def __init__(self, display_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle(f"Configure {display_name}")
        self.setSubTitle(f"{display_name} could not be set up here.")
        label = QLabel(
            f"What's Now Playing could not load the configuration options for "
            f"{display_name}. Setup will continue and {display_name} stays "
            f"selected, but you will need to finish configuring it in "
            f"Settings, under Input Sources.\n\n"
            f"The details were written to the log."
        )
        label.setWordWrap(True)
        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addStretch()
        self.setLayout(layout)


class _InputSourcePage(QWizardPage):
    """Pick which DJ software What's Now Playing reads from."""

    def __init__(
        self, config: nowplaying.config.ConfigFile, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.setTitle("Select Your DJ Software")
        # (radio_button, short_module_name, display_name)
        self._entries: list[tuple[QRadioButton, str, str]] = []
        self._button_group = QButtonGroup(self)
        # Which plugin the currently registered config page belongs to, so an
        # unchanged selection can be left alone rather than rebuilt.
        self._registered_short_name: str | None = None
        self._setup_ui()

    def _collect(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """Return (detected, undetected) as (short_name, display) pairs.

        A plugin that will not instantiate is dropped: it cannot work as a
        source, so offering it would only let the user pick something broken.
        """
        detected: list[tuple[str, str]] = []
        undetected: list[tuple[str, str]] = []
        plugins = self.config.plugins.get("inputs", {})

        for key in sorted(plugins):
            module = plugins[key]
            short_name = key.replace("nowplaying.inputs.", "")
            try:
                plugin_obj = module.Plugin(config=self.config)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("wizard: could not load input plugin %s", key)
                continue

            display = plugin_obj.displayname
            try:
                found = plugin_obj.detect()
            except Exception:  # pylint: disable=broad-exception-caught
                # Reported here only. detect() throwing is not worth telling the
                # user about: they select the software they own either way, and
                # the plugin's own config page is where a real error belongs.
                logging.exception("wizard: detect() failed for %s", key)
                found = nowplaying.inputs.Detected()

            # Fill blanks with what was found, so the config pages open showing
            # real paths rather than empty fields on a fresh install. Only
            # blanks: a value already there is the user's, not ours to replace.
            for setting_key, value in found.settings.items():
                self.config.record_detected(setting_key, value)

            (detected if found else undetected).append((short_name, display))

        return detected, undetected

    def _add_group(self, layout: QVBoxLayout, heading: str, items: list[tuple[str, str]]) -> None:
        """Add a headed block of radio buttons; no-op for an empty list."""
        if not items:
            return
        label = QLabel(heading)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        layout.addWidget(label)
        for short_name, display in items:
            btn = QRadioButton(display)
            self._entries.append((btn, short_name, display))
            self._button_group.addButton(btn)
            layout.addWidget(btn)
        layout.addSpacing(8)

    def _setup_ui(self) -> None:
        outer = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner_widget = QWidget()
        inner = QVBoxLayout()

        found, missing = self._collect()
        self._add_group(inner, "Found on this computer", found)
        self._add_group(inner, "Everything else", missing)

        inner.addStretch()
        inner_widget.setLayout(inner)
        scroll.setWidget(inner_widget)
        outer.addWidget(scroll)
        self.setLayout(outer)

        # Only auto-pick when there is nothing to get wrong. With several found,
        # picking the alphabetically-first one is a coin toss that silently
        # configures the wrong source, so make the user say which they use.
        if len(found) == 1:
            self._entries[0][0].setChecked(True)

        # No noun: the list runs from DJ software through media players to bare
        # protocols like Icecast, and "7 DJ applications" would be wrong.
        if len(found) > 1:
            self.setSubTitle(
                f"{len(found)} of these are already on this computer. Pick the one you play from."
            )
        elif found:
            self.setSubTitle(
                "One of these is already on this computer, so it is selected. Pick "
                "a different one if that is not what you play from."
            )
        else:
            self.setSubTitle(
                "Nothing was detected automatically, which is normal for several "
                "of these. Choose the software you play from."
            )

        self._button_group.buttonClicked.connect(self._on_selection_changed)

    def initializePage(self) -> None:  # pylint: disable=invalid-name
        """Register the config page for whichever input is preselected on first show."""
        self._on_selection_changed()

    def _on_selection_changed(self) -> None:
        """Rebuild the plugin-specific config page whenever the selection changes.

        A fresh page instance is constructed on each call, so loading from config
        in __init__ is correct — there is no stale-instance risk.
        """
        # Qt caches isComplete() and only re-reads it on this signal. Without
        # this, Next never enables now that nothing is preselected.
        self.completeChanged.emit()

        wizard = setup_wizard(self)
        if wizard is None:
            return

        short_name = self.selected_short_name()
        # Nothing changed, so leave the page standing. Rebuilding it would drop
        # the user's typed path twice over: drop_page() restores the pre-edit
        # value and the replacement loads from config. buttonClicked fires on
        # re-clicking the selected radio, and Qt re-runs initializePage() after
        # any backward move, so this is reached without changing anything.
        if short_name == self._registered_short_name and PAGE_INPUT_CONFIG in wizard.pageIds():
            return

        if PAGE_INPUT_CONFIG in wizard.pageIds():
            drop_page(wizard, PAGE_INPUT_CONFIG, self.config)
        self._registered_short_name = None
        if not short_name:
            return
        module = self.config.plugins.get("inputs", {}).get(f"nowplaying.inputs.{short_name}")
        if not module:
            return
        try:
            plugin_obj = module.Plugin(config=self.config)
            if plugin_obj.wizardpage is None:
                return
            page = plugin_obj.wizardpage(config=self.config)
        except Exception:  # pylint: disable=broad-exception-caught
            # A placeholder rather than nothing: nextId() and _commit() both
            # decide by whether PAGE_INPUT_CONFIG exists, so registering nothing
            # would route the user straight past their own settings.
            logging.exception("wizard: failed to load plugin page for %s", short_name)
            page = _ConfigUnavailablePage(self.selected_display_name())
        else:
            # Set here rather than passed to __init__: every plugin page is
            # __init__(self, config, parent=None) and changing that means editing
            # all of them.
            page.verification_module = module
        # The role page runs before this one, so the destination is already
        # decided by the time any config page is registered.
        page.next_page_override = wizard.after_input_config_page
        wizard.setPage(PAGE_INPUT_CONFIG, page)
        self._registered_short_name = short_name

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
        """Route to the plugin config page if registered, else on to outputs."""
        wizard = setup_wizard(self)
        if wizard and PAGE_INPUT_CONFIG in wizard.pageIds():
            return PAGE_INPUT_CONFIG
        if wizard and wizard.multipc_role == "dj":
            return PAGE_REMOTE_OUTPUT
        return PAGE_OUTPUTS
