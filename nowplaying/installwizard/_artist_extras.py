#!/usr/bin/env python3
"""Artist extras configuration page for the installation wizard."""

# pylint: disable=no-name-in-module

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)

import nowplaying.config


class _ArtistExtrasPage(QWizardPage):  # pylint: disable=too-few-public-methods
    """Configure artist information services."""

    def __init__(
        self, config: nowplaying.config.ConfigFile, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.setTitle("Artist Information Sources")
        self.setSubTitle(
            "Choose which services to use for artist biographies and images. "
            "Free services need no API key and are enabled by default."
        )
        self.enable_checks: dict[str, QCheckBox] = {}
        self.apikey_edits: dict[str, QLineEdit] = {}
        self.prioritize_network: QCheckBox
        self.bio_dedup: QCheckBox
        self.coverfornofanart: QCheckBox
        self._setup_ui()

    def _setup_ui(self) -> None:  # pylint: disable=too-many-statements,too-many-locals
        outer = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner_widget = QWidget()
        inner = QVBoxLayout()

        services_group = QGroupBox("Services")
        services_layout = QVBoxLayout()

        for key in sorted(self.config.plugins.get("artistextras", {})):
            module = self.config.plugins["artistextras"][key]
            short_name = key.replace("nowplaying.artistextras.", "")
            try:
                plugin_obj = module.Plugin(config=self.config)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.debug("wizard: could not load artistextras plugin %s", key)
                continue

            display = plugin_obj.displayname
            needs_key = plugin_obj.requires_apikey
            current_enabled = bool(
                self.config.cparser.value(
                    f"{short_name}/enabled", type=bool, defaultValue=not needs_key
                )
            )

            row = QWidget()
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 4, 0, 4)

            if not needs_key:
                check = QCheckBox(f"{display}  — free, no API key required")
                check.setChecked(True)
            else:
                check = QCheckBox(display)
                check.setChecked(current_enabled)

            self.enable_checks[short_name] = check
            row_layout.addWidget(check)

            if needs_key:
                key_label = QLabel("API Key:")
                key_edit = QLineEdit()
                key_edit.setPlaceholderText(f"{display} API key")
                key_edit.setText(
                    str(self.config.cparser.value(f"{short_name}/apikey", defaultValue="") or "")
                )
                key_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.apikey_edits[short_name] = key_edit
                key_edit.setEnabled(check.isChecked())
                check.toggled.connect(key_edit.setEnabled)
                row_layout.addWidget(key_label)
                row_layout.addWidget(key_edit)

            row.setLayout(row_layout)
            services_layout.addWidget(row)

        services_group.setLayout(services_layout)
        inner.addWidget(services_group)

        common_group = QGroupBox("Common Settings")
        common_layout = QVBoxLayout()

        self.prioritize_network = QCheckBox("Prefer downloaded images over embedded cover art")
        self.prioritize_network.setChecked(
            bool(
                self.config.cparser.value(
                    "artistextras/prioritizenetworkart", type=bool, defaultValue=False
                )
            )
        )
        common_layout.addWidget(self.prioritize_network)

        self.bio_dedup = QCheckBox("Deduplicate artist bios across services")
        self.bio_dedup.setChecked(
            bool(self.config.cparser.value("artistextras/bio_dedup", type=bool, defaultValue=True))
        )
        common_layout.addWidget(self.bio_dedup)

        self.coverfornofanart = QCheckBox(
            "Use cover art as fallback when no artist image is available"
        )
        self.coverfornofanart.setChecked(
            bool(
                self.config.cparser.value(
                    "artistextras/coverfornofanart", type=bool, defaultValue=True
                )
            )
        )
        common_layout.addWidget(self.coverfornofanart)

        common_group.setLayout(common_layout)
        inner.addWidget(common_group)

        inner.addStretch()
        inner_widget.setLayout(inner)
        scroll.setWidget(inner_widget)
        outer.addWidget(scroll)
        self.setLayout(outer)

    def enabled_display_names(self) -> list[str]:
        """Return display labels for all enabled services (for summary page)."""
        names = []
        for key in sorted(self.config.plugins.get("artistextras", {})):
            module = self.config.plugins["artistextras"][key]
            short_name = key.replace("nowplaying.artistextras.", "")
            check = self.enable_checks.get(short_name)
            if check and check.isChecked():
                try:
                    plugin_obj = module.Plugin(config=self.config)
                    names.append(plugin_obj.displayname)
                except Exception:  # pylint: disable=broad-exception-caught
                    names.append(short_name)
        return names
