#!/usr/bin/env python3
"""First-run installation wizard."""

# pylint: disable=no-name-in-module

import logging
import sys

from PySide6.QtWidgets import QDialog, QWidget, QWizard

import nowplaying.config
from nowplaying.installwizard._artist_extras import _ArtistExtrasPage
from nowplaying.installwizard._configure_outputs import _ConfigureOutputsPage
from nowplaying.installwizard._constants import (
    PAGE_ARTISTEXTRAS,
    PAGE_CONFIGURE_OUTPUTS,
    PAGE_FINISH,
    PAGE_INPUT,
    PAGE_INPUT_CONFIG,
    PAGE_OUTPUTS,
    PAGE_WELCOME,
)
from nowplaying.installwizard._finish import _FinishPage
from nowplaying.installwizard._input_source import _InputSourcePage
from nowplaying.installwizard._outputs import _OutputsPage
from nowplaying.installwizard._welcome import _WelcomePage

__all__ = [
    "InstallWizard",
    "maybe_show_wizard",
    "PAGE_WELCOME",
    "PAGE_INPUT",
    "PAGE_INPUT_CONFIG",
    "PAGE_ARTISTEXTRAS",
    "PAGE_OUTPUTS",
    "PAGE_CONFIGURE_OUTPUTS",
    "PAGE_FINISH",
]


class InstallWizard(QWizard):  # pylint: disable=too-few-public-methods
    """First-run setup wizard; shown when config.initialized is False."""

    def __init__(
        self, config: nowplaying.config.ConfigFile, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("What's Now Playing — Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(620, 520)

        self._welcome_page = _WelcomePage()
        self._input_page = _InputSourcePage(config)
        self._extras_page = _ArtistExtrasPage(config)
        self._outputs_page = _OutputsPage(config)
        self._configure_page = _ConfigureOutputsPage(self._outputs_page, config)
        self._finish_page = _FinishPage()

        self.setPage(PAGE_WELCOME, self._welcome_page)
        self.setPage(PAGE_INPUT, self._input_page)
        # PAGE_INPUT_CONFIG is reserved; populated dynamically by _InputSourcePage
        self.setPage(PAGE_ARTISTEXTRAS, self._extras_page)
        self.setPage(PAGE_OUTPUTS, self._outputs_page)
        self.setPage(PAGE_CONFIGURE_OUTPUTS, self._configure_page)
        self.setPage(PAGE_FINISH, self._finish_page)

        self.setStartId(PAGE_WELCOME)
        self.currentIdChanged.connect(self._on_page_changed)
        self.accepted.connect(self._commit)

    def _on_page_changed(self, page_id: int) -> None:
        if page_id == PAGE_FINISH:
            self._finish_page.set_summary(
                self._input_page.selected_display_name(),
                self._extras_page.enabled_display_names(),
                self._outputs_page.enabled_display_names(),
            )

    def _commit(self) -> None:  # pylint: disable=too-many-branches,too-many-statements
        """Persist all wizard choices to QSettings and mark initialized."""
        cparser = self.config.cparser

        # Plugin-specific config page (if one was registered) commits itself
        if PAGE_INPUT_CONFIG in self.pageIds():
            self.page(PAGE_INPUT_CONFIG).commit()

        short_name = self._input_page.selected_short_name()
        if short_name:
            cparser.setValue("settings/input", short_name)
            logging.info("wizard: set input source to %s", short_name)

        for key in self.config.plugins.get("artistextras", {}):
            sname = key.replace("nowplaying.artistextras.", "")
            check = self._extras_page.enable_checks.get(sname)
            if check is not None:
                cparser.setValue(f"{sname}/enabled", check.isChecked())
            edit = self._extras_page.apikey_edits.get(sname)
            if edit is not None:
                cparser.setValue(f"{sname}/apikey", edit.text().strip())

        cparser.setValue(
            "artistextras/prioritizenetworkart",
            self._extras_page.prioritize_network.isChecked(),
        )
        cparser.setValue("artistextras/bio_dedup", self._extras_page.bio_dedup.isChecked())
        cparser.setValue(
            "artistextras/coverfornofanart",
            self._extras_page.coverfornofanart.isChecked(),
        )

        op = self._outputs_page
        cparser.setValue("weboutput/httpenabled", op.weboverlay_check.isChecked())
        cparser.setValue("obsws/enabled", op.obsws_check.isChecked())
        cparser.setValue("twitchbot/enabled", op.twitch_check.isChecked())
        cparser.setValue("kick/enabled", op.kick_check.isChecked())
        cparser.setValue("discord/bot_enabled", op.discord_bot_check.isChecked())
        cparser.setValue("discord/richpresence_enabled", op.discord_rp_check.isChecked())

        if op.needs_credentials():
            cp = self._configure_page
            if op.obsws_check.isChecked():
                cparser.setValue("obsws/host", cp.obsws_host.text().strip() or "localhost")
                cparser.setValue("obsws/port", cp.obsws_port.text().strip() or "4455")
                cparser.setValue("obsws/secret", cp.obsws_secret.text())
            if op.twitch_check.isChecked():
                cparser.setValue("twitchbot/channel", cp.twitch_channel.text().strip())
                cparser.setValue("twitchbot/clientid", cp.twitch_clientid.text().strip())
                cparser.setValue("twitchbot/secret", cp.twitch_secret.text())
            if op.kick_check.isChecked():
                cparser.setValue("kick/channel", cp.kick_channel.text().strip())
                cparser.setValue("kick/clientid", cp.kick_clientid.text().strip())
                cparser.setValue("kick/secret", cp.kick_secret.text())
            if op.discord_bot_check.isChecked():
                cparser.setValue("discord/token", cp.discord_token.text().strip())
                cparser.setValue("discord/channel_id", cp.discord_channel_id.text().strip())
            if op.discord_rp_check.isChecked():
                cparser.setValue("discord/clientid", cp.discord_clientid.text().strip())

        pending_oauth = []
        if op.twitch_check.isChecked():
            pending_oauth.append("twitch")
        if op.kick_check.isChecked():
            pending_oauth.append("kick")
        if pending_oauth:
            cparser.setValue("settings/pending_oauth", ",".join(pending_oauth))

        self.config.initialized = True
        self.config.save()
        logging.info("wizard: first-run setup complete")


def maybe_show_wizard(config: nowplaying.config.ConfigFile) -> None:
    """Show the setup wizard for a fresh install; no-op if already initialized.

    Exits the process if the user cancels a first-run wizard — an unconfigured
    app has nothing useful to do.
    """
    if config.initialized:
        return
    wizard = InstallWizard(config)
    if wizard.exec() != QDialog.DialogCode.Accepted:
        logging.info("First-run wizard cancelled — exiting")
        sys.exit(0)
