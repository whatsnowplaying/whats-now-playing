#!/usr/bin/env python3
"""Preview window for text file output templates"""

import logging
import pathlib

from PySide6.QtCore import QSize, Signal  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import nowplaying.db
import nowplaying.preview.sampledata
import nowplaying.types
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
        enable_select_button: When True, show a "Use This Template" button that
                              emits ``template_selected`` with the chosen filename.
    """

    template_selected = Signal(str)

    def __init__(  # pylint: disable=too-many-arguments
        self,
        config,
        glob_pattern: str = "*.txt",
        config_key: str = "textoutput/txttemplate",
        enable_select_button: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.glob_pattern = glob_pattern
        self.config_key = config_key
        self._enable_select_button = enable_select_button
        self.sample_checkbox = QCheckBox("Sample data")
        self.sample_checkbox.setChecked(False)
        self.sample_checkbox.toggled.connect(self._render)
        self.template_combo = QComboBox()
        self.text_edit = QPlainTextEdit()
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

        self.template_combo.setEditable(False)
        self.template_combo.setMinimumWidth(220)
        self.template_combo.currentIndexChanged.connect(self._on_template_selected)
        toolbar.addWidget(self.template_combo, stretch=1)

        toolbar.addWidget(self.sample_checkbox)

        refresh_button = QPushButton("Refresh")
        refresh_button.setFixedWidth(80)
        refresh_button.clicked.connect(self._render)
        toolbar.addWidget(refresh_button)

        if self._enable_select_button:
            use_button = QPushButton("Use This Template")
            use_button.clicked.connect(self._on_use_template)
            toolbar.addWidget(use_button)

        layout.addLayout(toolbar)

        # ---- text area ----
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

    def _get_metadata(self) -> nowplaying.types.TrackMetadata:
        """Return live metadata if a track is playing and sample data not forced."""
        if not self.sample_checkbox.isChecked():
            try:
                metadb = nowplaying.db.MetadataDB()
                live = metadb.read_last_meta()
                if live and live.get("title"):
                    return live
            except Exception:  # pylint: disable=broad-exception-caught
                logging.debug("Could not read live metadata for preview", exc_info=True)
        bundledir = self.config.getbundledir() if self.config else None
        return nowplaying.preview.sampledata.get_preview_metadata(bundledir)

    def _render(self) -> None:
        """Render the currently selected template with live or sample metadata."""
        tmpl_path = self._current_template_path()

        if tmpl_path and tmpl_path.exists():
            handler = nowplaying.utils.TemplateHandler(filename=str(tmpl_path))
        else:
            handler = nowplaying.utils.TemplateHandler(rawtemplate="{{ artist }} - {{ title }}")

        if not handler.template:
            self.text_edit.setPlainText("No template found; check Now Playing settings.")
            return

        metadata = self._get_metadata()
        try:
            rendered = handler.template.render(**metadata)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            rendered = f"Template error:\n\n{exc}"
            logging.debug("TextPreviewWindow render error for %s: %s", tmpl_path, exc)

        logging.debug("TextPreviewWindow rendered %d chars from %s", len(rendered), tmpl_path)
        self.text_edit.setPlainText(rendered)

    def select_template(self, name: str) -> None:
        """Select a template by filename in the combo box."""
        idx = self.template_combo.findData(name)
        if idx >= 0:
            self.template_combo.setCurrentIndex(idx)

    def _on_template_selected(self) -> None:
        self._render()

    def _on_use_template(self) -> None:
        name = self.template_combo.currentData()
        if name:
            self.template_selected.emit(name)

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:  # pylint: disable=invalid-name,no-self-use
        """preferred initial size"""
        return QSize(600, 300)
