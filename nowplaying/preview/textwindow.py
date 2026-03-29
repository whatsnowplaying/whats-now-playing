#!/usr/bin/env python3
"""Preview window for text file output templates"""

import logging
import pathlib

from PySide6.QtCore import QSize  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import nowplaying.preview.sampledata
import nowplaying.utils


class TextPreviewWindow(QWidget):  # pylint: disable=too-few-public-methods
    """Standalone non-modal window showing a rendered preview of a text output template.

    Renders the selected template using sample metadata so users can see how
    the output will look without needing a live track.

    Args:
        config: Application config object.
        glob_pattern: Glob pattern for listing templates, e.g. ``"twitchbot_*.txt"``.
                      Defaults to ``"*.txt"`` (all text templates).
        config_key: QSettings key used to preselect the currently configured
                    template, e.g. ``"twitchbot/announce"``.
    """

    def __init__(
        self,
        config,
        glob_pattern: str = "*.txt",
        config_key: str = "textoutput/txttemplate",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.glob_pattern = glob_pattern
        self.config_key = config_key
        self.setWindowTitle("Text Template Preview")
        self.resize(600, 300)
        self._setup_ui()
        self._populate_templates()
        self._render()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # ---- toolbar row ----
        toolbar = QHBoxLayout()

        template_label = QLabel("Template:")
        toolbar.addWidget(template_label)

        self.template_combo = QComboBox()
        self.template_combo.setEditable(False)
        self.template_combo.setMinimumWidth(220)
        self.template_combo.currentIndexChanged.connect(self._on_template_selected)
        toolbar.addWidget(self.template_combo, stretch=1)

        refresh_button = QPushButton("Refresh")
        refresh_button.setFixedWidth(80)
        refresh_button.clicked.connect(self._render)
        toolbar.addWidget(refresh_button)

        layout.addLayout(toolbar)

        # ---- text area ----
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

    def _populate_templates(self) -> None:
        """Fill the combobox with matching template files."""
        templatedir = pathlib.Path(self.config.templatedir)
        templates = sorted(templatedir.glob(self.glob_pattern))

        configured = self.config.cparser.value(self.config_key, defaultValue="")
        configured_name = pathlib.Path(configured).name if configured else ""

        self.template_combo.blockSignals(True)
        if not templates:
            self.template_combo.addItem("(no templates found)", userData=None)
            self.template_combo.setEnabled(False)
            self.text_edit.setEnabled(False)
        else:
            for tmpl in templates:
                self.template_combo.addItem(tmpl.name, userData=tmpl.name)

            if configured_name:
                idx = self.template_combo.findData(configured_name)
                if idx >= 0:
                    self.template_combo.setCurrentIndex(idx)

        self.template_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _current_template_path(self) -> pathlib.Path | None:
        """Return the full path of the selected template, or None."""
        name = self.template_combo.currentData()
        if not name:
            return None
        return pathlib.Path(self.config.templatedir) / name

    def _render(self) -> None:
        """Render the currently selected template with sample metadata."""
        tmpl_path = self._current_template_path()

        if tmpl_path and tmpl_path.exists():
            handler = nowplaying.utils.TemplateHandler(filename=str(tmpl_path))
        else:
            handler = nowplaying.utils.TemplateHandler(rawtemplate="{{ artist }} - {{ title }}")

        bundledir = self.config.getbundledir() if self.config else None
        metadata = nowplaying.preview.sampledata.get_preview_metadata(bundledir)
        rendered = handler.generate(metadata)

        logging.debug("TextPreviewWindow rendered %d chars from %s", len(rendered), tmpl_path)
        self.text_edit.setPlainText(rendered)

    def _on_template_selected(self) -> None:
        self._render()

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:  # pylint: disable=invalid-name,no-self-use
        """preferred initial size"""
        return QSize(600, 300)
