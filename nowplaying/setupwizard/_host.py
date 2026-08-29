#!/usr/bin/env python3
"""Helpers for pages that have to reach the wizard hosting them."""

import typing
from typing import TYPE_CHECKING

import nowplaying.wizard

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWizard, QWizardPage  # pylint: disable=no-name-in-module

    import nowplaying.config
    import nowplaying.setupwizard


def setup_wizard(page: "QWizardPage") -> "nowplaying.setupwizard.SetupWizard | None":
    """The wizard hosting this page, or None before it is registered.

    QWizardPage.wizard() is declared as returning QWizard, so reading the flow
    state SetupWizard keeps -- multipc_role, after_input_config_page -- would
    otherwise need getattr or a type: ignore at every site. Only SetupWizard
    ever hosts these pages, so the cast is the honest description.
    """
    return typing.cast("nowplaying.setupwizard.SetupWizard | None", page.wizard())


def drop_page(wizard: "QWizard", page_id: int, config: "nowplaying.config.ConfigFile") -> None:
    """Remove a registered page, undoing whatever its verification committed.

    removePage discards the page object and with it the record of what
    _snapshot_and_commit changed, so switching sources part-way through would
    leave the abandoned one's keys written with nothing left to restore them.
    """
    page = wizard.page(page_id)
    if isinstance(page, nowplaying.wizard.WizardPage):
        page.restore_committed(config)
    wizard.removePage(page_id)
