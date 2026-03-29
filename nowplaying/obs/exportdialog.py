#!/usr/bin/env python3
"""OBS scene collection export dialog."""

import logging
import pathlib

# pylint: disable=no-name-in-module
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QHeaderView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import nowplaying.obs.scenebuilder
import nowplaying.preview.window

logger = logging.getLogger(__name__)

_HINT_OPTIONS = ["fill", "top", "bottom", "left", "right", "center"]

_COL_INCLUDE = 0
_COL_SOURCE = 1
_COL_TEMPLATE = 2
_COL_WIDTH = 3
_COL_HEIGHT = 4
_COL_POSITION = 5
_COL_PREVIEW = 6


class OBSExportDialog(QDialog):  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """Dialog for selecting and exporting OBS browser sources."""

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.port: int = config.cparser.value("weboutput/httpport", type=int, defaultValue=8899)
        self._preview_window: nowplaying.preview.window.WebPreviewWindow | None = None
        self._preview_row: int = -1
        self._templates: list[str] = self._load_templates()
        self.setWindowTitle("Export for OBS")
        self.resize(980, 300)
        self._setup_ui()
        self._populate_table()

    def _load_templates(self) -> list[str]:
        """Return sorted list of .htm template filenames from the template directory."""
        templatedir = pathlib.Path(self.config.templatedir)
        return sorted(t.name for t in templatedir.glob("*.htm"))

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Include", "Source", "Template", "Width", "Height", "Position", "Preview"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_INCLUDE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_SOURCE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_TEMPLATE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_WIDTH, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_HEIGHT, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_POSITION, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_PREVIEW, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(_COL_WIDTH, 75)
        self.table.setColumnWidth(_COL_HEIGHT, 75)
        self.table.setColumnWidth(_COL_PREVIEW, 75)
        layout.addWidget(self.table)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        button_box = QDialogButtonBox()
        self.export_button = button_box.addButton("Export", QDialogButtonBox.ButtonRole.AcceptRole)
        close_button = button_box.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        self.export_button.clicked.connect(self._on_export)
        close_button.clicked.connect(self.reject)
        layout.addWidget(button_box)

    def _make_template_combo(self, default_path: str, configured_name: str) -> QComboBox:
        """Build a template-selector combo preselecting the given path's template."""
        combo = QComboBox()
        for tmpl in self._templates:
            combo.addItem(tmpl)
        preselect = default_path.lstrip("/") or configured_name
        if preselect:
            idx = combo.findText(preselect)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        return combo

    def _populate_table(self) -> None:
        sources = nowplaying.obs.scenebuilder.DEFAULT_SOURCES
        self.table.setRowCount(len(sources))

        configured = self.config.cparser.value("weboutput/htmltemplate", defaultValue="")
        configured_name = pathlib.Path(configured).name if configured else ""

        for row, source in enumerate(sources):
            include_item = QTableWidgetItem()
            include_item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, _COL_INCLUDE, include_item)

            name_item = QTableWidgetItem(source.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, _COL_SOURCE, name_item)

            self.table.setCellWidget(
                row, _COL_TEMPLATE, self._make_template_combo(source.path, configured_name)
            )

            width_spin = QSpinBox()
            width_spin.setRange(1, 7680)
            width_spin.setValue(source.width)
            self.table.setCellWidget(row, _COL_WIDTH, width_spin)

            height_spin = QSpinBox()
            height_spin.setRange(1, 7680)
            height_spin.setValue(source.height)
            self.table.setCellWidget(row, _COL_HEIGHT, height_spin)

            pos_combo = QComboBox()
            for hint in _HINT_OPTIONS:
                pos_combo.addItem(hint)
            pos_combo.setCurrentText(source.hint)
            self.table.setCellWidget(row, _COL_POSITION, pos_combo)

            preview_btn = QPushButton("Preview")
            preview_btn.clicked.connect(self._make_preview_handler(row))
            self.table.setCellWidget(row, _COL_PREVIEW, preview_btn)

        # Shrink table to fit rows exactly
        self.table.resizeRowsToContents()
        row_height = self.table.rowHeight(0)
        header_height = self.table.horizontalHeader().height()
        self.table.setFixedHeight(header_height + row_height * len(sources) + 2)

    def _make_preview_handler(self, row: int):
        """Return a slot closure that opens a preview for the given row's template."""

        @Slot()
        def _handler():
            self._preview_row = row
            tmpl_widget = self.table.cellWidget(row, _COL_TEMPLATE)
            tmpl_name = tmpl_widget.currentText() if tmpl_widget else ""  # type: ignore[union-attr]

            if self._preview_window is None:
                self._preview_window = nowplaying.preview.window.WebPreviewWindow(
                    config=self.config, enable_select_button=True
                )
                self._preview_window.template_selected.connect(self._on_template_selected)

            # Sync the preview window to this row's selected template
            if tmpl_name:
                idx = self._preview_window.template_combo.findData(tmpl_name)
                if idx >= 0:
                    self._preview_window.template_combo.setCurrentIndex(idx)

            self._preview_window.show()
            self._preview_window.raise_()
            self._preview_window.activateWindow()

        return _handler

    @Slot(str)
    def _on_template_selected(self, template_name: str) -> None:
        """Update the template column for the row that launched the preview."""
        if self._preview_row < 0:
            return
        tmpl_widget = self.table.cellWidget(self._preview_row, _COL_TEMPLATE)
        if tmpl_widget:
            idx = tmpl_widget.findText(template_name)  # type: ignore[union-attr]
            if idx >= 0:
                tmpl_widget.setCurrentIndex(idx)  # type: ignore[union-attr]

    def _row_to_source(self, row: int) -> "nowplaying.obs.scenebuilder.OBSSourceDef | None":
        """Read one table row; return OBSSourceDef if checked, else None."""
        include_item = self.table.item(row, _COL_INCLUDE)
        if include_item is None or include_item.checkState() != Qt.CheckState.Checked:
            return None

        name_item = self.table.item(row, _COL_SOURCE)
        name = name_item.text() if name_item else ""

        tmpl_widget = self.table.cellWidget(row, _COL_TEMPLATE)
        tmpl_name = tmpl_widget.currentText() if tmpl_widget else ""  # type: ignore[union-attr]
        path = f"/{tmpl_name}" if tmpl_name else "/"

        width_widget = self.table.cellWidget(row, _COL_WIDTH)
        width = width_widget.value() if width_widget else 800  # type: ignore[union-attr]

        height_widget = self.table.cellWidget(row, _COL_HEIGHT)
        height = height_widget.value() if height_widget else 300  # type: ignore[union-attr]

        pos_widget = self.table.cellWidget(row, _COL_POSITION)
        hint = pos_widget.currentText() if pos_widget else "bottom"  # type: ignore[union-attr]

        return nowplaying.obs.scenebuilder.OBSSourceDef(
            name=name, path=path, width=width, height=height, hint=hint
        )

    @Slot()
    def _on_export(self) -> None:
        """Collect checked rows and call scenebuilder.build_and_save."""
        sources = [
            src
            for row in range(self.table.rowCount())
            if (src := self._row_to_source(row)) is not None
        ]

        if not sources:
            self.status_label.setText("Select at least one source.")
            return

        try:
            saved_path = nowplaying.obs.scenebuilder.build_and_save(sources, self.port)
            self.status_label.setText(f"Saved to: {saved_path}")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OBS export failed: %s", exc)
            self.status_label.setText(f"Error: {exc}")
