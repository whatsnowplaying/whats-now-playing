#!/usr/bin/env python3
"""Multi-PC setup pages for the setup wizard."""

# pylint: disable=no-name-in-module

import logging

from PySide6.QtWidgets import (
    QButtonGroup,
    QFormLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

import nowplaying.config
from nowplaying.setupwizard._constants import (
    PAGE_FINISH,
    PAGE_INPUT,
    PAGE_INPUT_CONFIG,
    PAGE_MULTIPC_ROLE,
    PAGE_REMOTE_OUTPUT,
)
from nowplaying.setupwizard._host import drop_page, setup_wizard


class _MultiPcQuestionPage(QWizardPage):
    """Ask whether this is a single-machine or multi-PC setup."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Single or Multi-PC Setup")
        self.setSubTitle("Tell us how you have What's Now Playing deployed.")

        self._single = QRadioButton("Single PC")
        single_detail = QLabel("My DJ software and streaming outputs run on the same machine.")
        single_detail.setWordWrap(True)
        single_detail.setIndent(20)

        self._multi = QRadioButton("Multiple computers")
        multi_detail = QLabel(
            "My DJ software runs on one machine; I stream or display track info from another."
        )
        multi_detail.setWordWrap(True)
        multi_detail.setIndent(20)

        self._single.setChecked(True)

        self._group = QButtonGroup(self)
        self._group.addButton(self._single)
        self._group.addButton(self._multi)

        layout = QVBoxLayout()
        layout.addWidget(self._single)
        layout.addWidget(single_detail)
        layout.addSpacing(8)
        layout.addWidget(self._multi)
        layout.addWidget(multi_detail)
        layout.addStretch()
        self.setLayout(layout)

    def _is_multipc(self) -> bool:
        return self._multi.isChecked()

    def validatePage(self) -> bool:  # pylint: disable=invalid-name
        """Store the single/multi choice on the wizard for later pages to read."""
        wizard = setup_wizard(self)
        if wizard is not None:
            wizard.multipc = self._is_multipc()
            if not wizard.multipc:
                # Reset role in case user went back and changed answer
                wizard.multipc_role = None
                wizard.after_input_config_page = None
        return True

    def nextId(self) -> int:  # pylint: disable=invalid-name
        """Single-PC goes straight to input selection; multi-PC asks role next."""
        if self._is_multipc():
            return PAGE_MULTIPC_ROLE
        return PAGE_INPUT


class _MultiPcRolePage(QWizardPage):
    """Ask which role this machine plays in a multi-PC setup."""

    def __init__(
        self, config: nowplaying.config.ConfigFile, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._remote_page_registered: bool = False
        self.setTitle("Which Machine Is This?")
        self.setSubTitle("Each machine gets configured for the role you pick here.")

        self._dj = QRadioButton("DJ / Source machine")
        dj_detail = QLabel(
            "This computer runs your DJ software. It will detect the playing track "
            "and send the information to your display machine."
        )
        dj_detail.setWordWrap(True)
        dj_detail.setIndent(20)

        self._display = QRadioButton("Display / Streaming machine")
        display_detail = QLabel(
            "This computer connects to OBS, Twitch, Kick, and other outputs. "
            "It will receive track information from the DJ machine."
        )
        display_detail.setWordWrap(True)
        display_detail.setIndent(20)

        self._dj.setChecked(True)

        self._group = QButtonGroup(self)
        self._group.addButton(self._dj)
        self._group.addButton(self._display)

        layout = QVBoxLayout()
        layout.addWidget(self._dj)
        layout.addWidget(dj_detail)
        layout.addSpacing(12)
        layout.addWidget(self._display)
        layout.addWidget(display_detail)
        layout.addStretch()
        self.setLayout(layout)

    def _is_display(self) -> bool:
        return self._display.isChecked()

    def validatePage(self) -> bool:  # pylint: disable=invalid-name
        """Store the role on the wizard and prepare dynamic pages."""
        wizard = setup_wizard(self)
        if wizard is None:
            return True

        if self._is_display():
            wizard.multipc_role = "display"
            wizard.after_input_config_page = None
            self._remote_page_registered = self._register_remote_input_page(wizard)
        else:
            wizard.multipc_role = "dj"
            wizard.after_input_config_page = PAGE_REMOTE_OUTPUT
            # Clear any remote input page left from a previous display selection
            if PAGE_INPUT_CONFIG in wizard.pageIds():
                drop_page(wizard, PAGE_INPUT_CONFIG, self._config)
        return True

    def _register_remote_input_page(self, wizard: QWizard) -> bool:
        """Auto-register the Remote input's wizard page for the display machine path.

        Returns True if the page was successfully registered, False otherwise.
        """
        module = self._config.plugins.get("inputs", {}).get("nowplaying.inputs.remote")
        if not module:
            logging.warning("wizard: remote input plugin not found")
            return False
        try:
            plugin_obj = module.Plugin(config=self._config)
            if plugin_obj.wizardpage is not None:
                if PAGE_INPUT_CONFIG in wizard.pageIds():
                    drop_page(wizard, PAGE_INPUT_CONFIG, self._config)
                page = plugin_obj.wizardpage(config=self._config)
                # Same handoff _InputSourcePage does; without it the display
                # machine is the one path that never verifies.
                page.verification_module = module
                wizard.setPage(PAGE_INPUT_CONFIG, page)
                return True
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("wizard: failed to register remote input page")
        return False

    def nextId(self) -> int:  # pylint: disable=invalid-name
        """Display machine goes to Remote input config if registered, else input picker."""
        if self._is_display():
            return PAGE_INPUT_CONFIG if self._remote_page_registered else PAGE_INPUT
        return PAGE_INPUT


class _RemoteOutputPage(QWizardPage):
    """Configure Remote Output so this DJ machine can push tracks to the display machine."""

    def __init__(
        self, config: nowplaying.config.ConfigFile, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._config = config
        self.setTitle("Remote Output")
        self.setSubTitle(
            "This machine will send its tracks to the display machine, and finds "
            "it on the local network with no address to enter."
        )

        explain = QLabel(
            "The display machine needs What's Now Playing running too. Start them "
            "in either order, since this one keeps looking."
        )
        explain.setWordWrap(True)

        self._secret = QLineEdit()
        self._secret.setPlaceholderText("optional, must match the display machine")
        self._secret.setText(str(self._config.cparser.value("remote/remote_key", defaultValue="")))

        form = QFormLayout()
        form.addRow("Shared secret:", self._secret)

        layout = QVBoxLayout()
        layout.addWidget(explain)
        layout.addSpacing(12)
        layout.addLayout(form)
        layout.addStretch()
        self.setLayout(layout)

    def nextId(self) -> int:  # pylint: disable=invalid-name,no-self-use
        """DJ path ends at Finish after this page."""
        return PAGE_FINISH

    def commit(self) -> None:
        """Write Remote Output config to QSettings."""
        self._config.cparser.setValue("remote/enabled", True)
        self._config.cparser.setValue("remote/autodiscover", True)
        self._config.cparser.setValue("remote/remote_key", self._secret.text().strip())
