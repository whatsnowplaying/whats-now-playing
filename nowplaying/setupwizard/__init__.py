#!/usr/bin/env python3
"""First-run setup wizard."""

# pylint: disable=no-name-in-module

import logging
import sys
import typing

from PySide6.QtWidgets import QDialog, QMessageBox, QWidget, QWizard

import nowplaying.config
import nowplaying.wizard
from nowplaying.setupwizard._configure_outputs import _ConfigureOutputsPage
from nowplaying.setupwizard._constants import (
    PAGE_CONFIGURE_OUTPUTS,
    PAGE_FINISH,
    PAGE_INPUT,
    PAGE_INPUT_CONFIG,
    PAGE_MULTIPC,
    PAGE_MULTIPC_ROLE,
    PAGE_OUTPUTS,
    PAGE_REMOTE_OUTPUT,
    PAGE_WELCOME,
)
from nowplaying.setupwizard._finish import _FinishPage
from nowplaying.setupwizard._input_source import _InputSourcePage
from nowplaying.setupwizard._multipc import (
    _MultiPcQuestionPage,
    _MultiPcRolePage,
    _RemoteOutputPage,
)
from nowplaying.setupwizard._outputs import _OutputsPage
from nowplaying.setupwizard._welcome import _WelcomePage

__all__ = [
    "SetupWizard",
    "maybe_show_wizard",
    "PAGE_WELCOME",
    "PAGE_MULTIPC",
    "PAGE_MULTIPC_ROLE",
    "PAGE_INPUT",
    "PAGE_INPUT_CONFIG",
    "PAGE_OUTPUTS",
    "PAGE_CONFIGURE_OUTPUTS",
    "PAGE_REMOTE_OUTPUT",
    "PAGE_FINISH",
]


class SetupWizard(QWizard):  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """First-run setup wizard; shown when config.initialized is False."""

    def __init__(
        self, config: nowplaying.config.ConfigFile, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("What's Now Playing — Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(620, 520)

        self.setButtonText(QWizard.WizardButton.CancelButton, "Finish Later")

        # Multi-PC state set by _MultiPcRolePage.validatePage()
        self.multipc: bool = False
        self.multipc_role: str | None = None  # 'dj', 'display', or None
        self.after_input_config_page: int | None = None  # PAGE_REMOTE_OUTPUT for DJ

        self._welcome_page = _WelcomePage()
        self._multipc_page = _MultiPcQuestionPage()
        self._multipc_role_page = _MultiPcRolePage(config)
        self._input_page = _InputSourcePage(config)
        self._outputs_page = _OutputsPage(config)
        self._configure_page = _ConfigureOutputsPage(config)
        self._remote_output_page = _RemoteOutputPage(config)
        self._finish_page = _FinishPage()

        self.setPage(PAGE_WELCOME, self._welcome_page)
        self.setPage(PAGE_MULTIPC, self._multipc_page)
        self.setPage(PAGE_MULTIPC_ROLE, self._multipc_role_page)
        self.setPage(PAGE_INPUT, self._input_page)
        # PAGE_INPUT_CONFIG is reserved; populated dynamically by _InputSourcePage
        # or _MultiPcRolePage (for the display machine path)
        self.setPage(PAGE_OUTPUTS, self._outputs_page)
        self.setPage(PAGE_CONFIGURE_OUTPUTS, self._configure_page)
        self.setPage(PAGE_REMOTE_OUTPUT, self._remote_output_page)
        self.setPage(PAGE_FINISH, self._finish_page)

        self.setStartId(PAGE_WELCOME)
        self.currentIdChanged.connect(self._on_page_changed)
        self.accepted.connect(self._commit)

    def _update_verification(self, page_id: int, shutting_down: bool = False) -> None:
        """Poll only the page being shown.

        Driven from here rather than the page's own initializePage/cleanupPage:
        a plugin page that overrides those without calling super() would
        otherwise silently never verify, and worse, never stop.
        """
        for known_id in self.pageIds():
            page = self.page(known_id)
            if not isinstance(page, nowplaying.wizard.WizardPage):
                continue
            if known_id == page_id:
                page.start_verification(self.config)
            else:
                page.stop_verification(shutting_down=shutting_down)

    def reject(self) -> None:
        """Say what "Finish Later" actually does before doing it.

        Reached by the Cancel button and by closing the window. This ends the
        process, which is a surprising thing to discover after the fact.
        """
        answer = QMessageBox.question(
            self,
            "Finish setup later?",
            "What's Now Playing needs an input source before it can run, so it "
            "will close now.\n\nSetup starts again the next time you launch it. "
            "Your answers so far will not be saved.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Close,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Close:
            return
        self._restore_committed()
        super().reject()

    def _restore_committed(self) -> None:
        """Undo what verification committed, on every page that committed anything."""
        for known_id in self.pageIds():
            page = self.page(known_id)
            if isinstance(page, nowplaying.wizard.WizardPage):
                page.restore_committed(self.config)

    def done(self, result: int) -> None:
        """Stop every poller before the dialog closes.

        currentIdChanged does not fire on close, so Finish and Cancel would
        both leave a source started -- and start_all_processes() runs moments
        later and would find the port already taken.
        """
        self._update_verification(-1, shutting_down=True)
        super().done(result)

    def _on_page_changed(self, page_id: int) -> None:
        self._update_verification(page_id)
        if page_id == PAGE_FINISH:
            if self.multipc_role == "dj":
                self._finish_page.set_summary(
                    self._input_page.selected_display_name(),
                    ["Remote Output (autodiscovery)"],
                )
            elif self.multipc_role == "display":
                self._finish_page.set_summary(
                    "Remote (receiving from DJ machine)",
                    self._outputs_page.enabled_display_names(),
                )
            else:
                self._finish_page.set_summary(
                    self._input_page.selected_display_name(),
                    self._outputs_page.enabled_display_names(),
                )

    def _commit(self) -> None:  # pylint: disable=too-many-branches,too-many-statements
        """Persist all wizard choices to QSettings and mark initialized."""
        cparser = self.config.cparser

        # Plugin-specific config page (if one was registered) commits itself.
        # Always a WizardPage: either the plugin's own or _ConfigUnavailablePage.
        if PAGE_INPUT_CONFIG in self.pageIds():
            config_page = typing.cast(nowplaying.wizard.WizardPage, self.page(PAGE_INPUT_CONFIG))
            config_page.commit()

        if self.multipc_role == "dj":
            self._commit_dj_machine(cparser)
        elif self.multipc_role == "display":
            self._commit_display_machine(cparser)
        else:
            self._commit_single_machine(cparser)

        self.config.initialized = True
        self.config.save()
        logging.info("wizard: first-run setup complete (role=%s)", self.multipc_role or "single")

    def _commit_dj_machine(self, cparser) -> None:  # pylint: disable=too-many-branches
        """Commit settings for the DJ/source machine in a multi-PC setup."""
        short_name = self._input_page.selected_short_name()
        if short_name:
            cparser.setValue("settings/input", short_name)
            logging.info("wizard: set input source to %s", short_name)

        # Artist extras off — the display machine handles metadata enrichment
        for key in self.config.plugins.get("artistextras", {}):
            sname = key.replace("nowplaying.artistextras.", "")
            cparser.setValue(f"{sname}/enabled", False)

        # Remote Output — the only output on a DJ machine
        self._remote_output_page.commit()

        # System notifications on so the DJ can see track changes going across.
        # The attribute, not the key: _commit() ends with config.save(), which
        # writes settings/notif from config.notif and would undo a bare write.
        self.config.notif = True

    def _commit_display_machine(self, cparser) -> None:  # pylint: disable=too-many-branches
        """Commit settings for the display/streaming machine in a multi-PC setup."""
        cparser.setValue("settings/input", "remote")
        logging.info("wizard: set input source to remote")

        self._commit_outputs(cparser)

        # See the note in _commit_dj_machine: the attribute, not the key.
        self.config.notif = True

    def _commit_single_machine(self, cparser) -> None:  # pylint: disable=too-many-branches
        """Commit settings for a standalone single-machine setup."""
        short_name = self._input_page.selected_short_name()
        if short_name:
            cparser.setValue("settings/input", short_name)
            logging.info("wizard: set input source to %s", short_name)

        # Artist extras are not asked about: defaults() already enables the free
        # services and leaves the paid ones off, so a fresh install gets bios and
        # images for free. Tuning lives behind Guided Setup in Settings.
        self._commit_outputs(cparser)

    def _commit_outputs(self, cparser) -> None:
        """Write outputs selections and credentials to config."""
        op = self._outputs_page
        cparser.setValue("twitchbot/enabled", op.twitch_check.isChecked())

        # Offer the OBS scene once the webserver is actually listening, since
        # the browser sources it writes point straight at it. systemtray picks
        # this up after start_all_processes(); see _handle_pending_obs_export.
        if op.obs_export_check.isChecked():
            cparser.setValue("settings/pending_obs_export", True)

        if op.twitch_check.isChecked():
            cp = self._configure_page
            cparser.setValue("twitchbot/channel", cp.twitch_channel.text().strip())
            # Leaving the box unchecked means "use the bundled application", and a
            # Client ID left over from a previous run would silently override that.
            if cp.uses_own_app:
                cparser.setValue("twitchbot/clientid", cp.twitch_clientid.text().strip())
                cparser.setValue("twitchbot/secret", cp.twitch_secret.text())
            else:
                cparser.setValue("twitchbot/clientid", "")
                cparser.setValue("twitchbot/secret", "")
            cparser.setValue("settings/pending_oauth", "twitch")


def maybe_show_wizard(config: nowplaying.config.ConfigFile) -> None:
    """Show the setup wizard for a fresh install; no-op if already initialized.

    Exits the process if the user cancels a first-run wizard — an unconfigured
    app has nothing useful to do.
    """
    if config.initialized:
        return
    wizard = SetupWizard(config)
    if wizard.exec() != QDialog.DialogCode.Accepted:
        logging.info("First-run wizard cancelled — exiting")
        sys.exit(0)
