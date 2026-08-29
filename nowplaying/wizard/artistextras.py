#!/usr/bin/env python3
"""Guided setup wizard for artist information services.

Launched from Artist Extras settings. This is deliberately not part of first-run
setup: the free services are enabled by defaults() already, so a new user gets
biographies and images without answering anything.
"""

# pylint: disable=too-few-public-methods

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QCheckBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from nowplaying.wizard.finish import FinishPage

if TYPE_CHECKING:
    import nowplaying.config

_FINISH_BODY = (
    "Your choices will be saved when you save your settings.\n\n"
    "Artist data is fetched in the background and cached, so the first play of "
    "an artist may lag slightly behind the track change."
)


class _ServicesPage(QWizardPage):
    """Enable services and collect API keys for the ones that need them."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._config = config
        self.setTitle("Artist Information Services")
        self.setSubTitle(
            "These add biographies and artist images to your overlays. The free "
            "ones are already on; the others need an account with that service."
        )

        self.enable_checks: dict[str, QCheckBox] = {}
        self.apikey_edits: dict[str, QLineEdit] = {}

        layout = QVBoxLayout()
        for short_name, display, needs_key in self._services():
            check = QCheckBox(display if needs_key else f"{display}  (free, no API key)")
            check.setChecked(
                bool(
                    config.cparser.value(
                        f"{short_name}/enabled", type=bool, defaultValue=not needs_key
                    )
                )
            )
            self.enable_checks[short_name] = check
            layout.addWidget(check)

            if not needs_key:
                continue
            edit = QLineEdit()
            edit.setPlaceholderText(f"{display} API key")
            edit.setText(str(config.cparser.value(f"{short_name}/apikey", defaultValue="") or ""))
            edit.setEnabled(check.isChecked())
            check.toggled.connect(edit.setEnabled)
            self.apikey_edits[short_name] = edit

            form = QFormLayout()
            form.setContentsMargins(20, 0, 0, 8)
            form.addRow("API key:", edit)
            layout.addLayout(form)

        layout.addStretch()
        self.setLayout(layout)

    def _services(self) -> list[tuple[str, str, bool]]:
        """Return (short_name, display, needs_key), skipping anything unloadable."""
        found: list[tuple[str, str, bool]] = []
        plugins = self._config.plugins.get("artistextras", {})
        for key in sorted(plugins):
            short_name = key.replace("nowplaying.artistextras.", "")
            try:
                plugin_obj = plugins[key].Plugin(config=self._config)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("artistextras wizard: could not load %s", key)
                continue
            found.append((short_name, plugin_obj.displayname, plugin_obj.requires_apikey))
        return found


class _OptionsPage(QWizardPage):
    """The handful of cross-service options worth surfacing."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setTitle("Artwork Preferences")
        self.setSubTitle("These decide what to use when more than one source has something.")

        self.prioritize_network = QCheckBox("Prefer downloaded images over embedded cover art")
        self.prioritize_network.setChecked(
            bool(
                config.cparser.value(
                    "artistextras/prioritizenetworkart", type=bool, defaultValue=False
                )
            )
        )
        self.bio_dedup = QCheckBox("Remove repeated text when several services supply a bio")
        self.bio_dedup.setChecked(
            bool(config.cparser.value("artistextras/bio_dedup", type=bool, defaultValue=True))
        )
        self.coverfornofanart = QCheckBox("Fall back to cover art when there is no artist image")
        self.coverfornofanart.setChecked(
            bool(
                config.cparser.value("artistextras/coverfornofanart", type=bool, defaultValue=True)
            )
        )

        layout = QVBoxLayout()
        for check in (self.prioritize_network, self.bio_dedup, self.coverfornofanart):
            layout.addWidget(check)
        layout.addStretch()
        self.setLayout(layout)


class ArtistExtrasWizard(QWizard):
    """Step-by-step setup wizard for artist information services."""

    def __init__(
        self, config: "nowplaying.config.ConfigFile", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Set Up Artist Information")
        self.setModal(True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)

        self._services_page = _ServicesPage(config)
        self._options_page = _OptionsPage(config)
        self.addPage(self._services_page)
        self.addPage(self._options_page)
        self.addPage(FinishPage("Artist Information Setup Complete", _FINISH_BODY))

    def accept(self) -> None:
        """Write the collected values, then let the launching page reload them.

        Written on accept rather than per page so that cancelling halfway leaves
        the existing configuration alone.
        """
        cparser = self._config.cparser
        for short_name, check in self._services_page.enable_checks.items():
            cparser.setValue(f"{short_name}/enabled", check.isChecked())
            if edit := self._services_page.apikey_edits.get(short_name):
                cparser.setValue(f"{short_name}/apikey", edit.text().strip())
        cparser.setValue(
            "artistextras/prioritizenetworkart", self._options_page.prioritize_network.isChecked()
        )
        cparser.setValue("artistextras/bio_dedup", self._options_page.bio_dedup.isChecked())
        cparser.setValue(
            "artistextras/coverfornofanart", self._options_page.coverfornofanart.isChecked()
        )
        super().accept()
