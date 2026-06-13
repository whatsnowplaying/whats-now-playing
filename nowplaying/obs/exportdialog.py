#!/usr/bin/env python3
"""OBS scene collection export dialog."""

import contextlib
import logging
import pathlib

import psutil

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
import nowplaying.template_colors
import nowplaying.utils.qt

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
        self._templates: list[tuple[str, str]] = self._load_templates()
        self.setWindowTitle("Export for OBS")
        self.resize(980, 300)
        self._setup_ui()
        self._populate_table()

    def _load_templates(self) -> list[tuple[str, str]]:
        """Return (display_name, url_path) pairs for all available templates.

        Custom templates are listed first with a ★ prefix and use the URL path
        ``custom/<name>.htm``.  Built-in templates follow, keyed by stem only —
        they are copied to custom/ on first export via _ensure_custom_copy().
        """
        custom_dir = nowplaying.template_colors.custom_dir_for_config(self.config.templatedir)
        entries: list[tuple[str, str]] = []
        custom_stems: set[str] = set()
        if custom_dir.exists():
            for tmpl in sorted(custom_dir.glob("*.htm")):
                entries.append((f"★ {tmpl.stem}", f"custom/{tmpl.name}"))
                custom_stems.add(tmpl.stem)
        bundled = nowplaying.template_colors.BUNDLED_TEMPLATE_DIR
        for family, effects in nowplaying.template_colors.TEMPLATE_FAMILIES.items():
            for effect, stem in effects.items():
                if stem in custom_stems:
                    continue
                if not (bundled / f"{stem}.htm").exists():
                    continue
                label = family if effect == "None" else f"{family} — {effect}"
                entries.append((label, stem))
        return entries

    def _ensure_custom_copy(self, stem: str) -> str:
        """Copy a built-in template to custom/ if needed; return its url_path."""
        custom_dir = nowplaying.template_colors.custom_dir_for_config(self.config.templatedir)
        dest = custom_dir / f"{stem}.htm"
        if not dest.exists():
            src = nowplaying.template_colors.BUNDLED_TEMPLATE_DIR / f"{stem}.htm"
            nowplaying.template_colors.save_custom_template(src, custom_dir, {}, name=stem)
        return f"custom/{stem}.htm"

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
        for display, url_path in self._templates:
            combo.addItem(display, userData=url_path)
        preselect = default_path.lstrip("/") or configured_name
        if preselect:
            for i in range(combo.count()):
                if combo.itemData(i) == preselect:
                    combo.setCurrentIndex(i)
                    break
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

            if self._preview_window is None:
                self._preview_window = nowplaying.preview.window.WebPreviewWindow(
                    config=self.config, enable_select_button=True
                )
                self._preview_window.template_selected.connect(self._on_template_selected)

            # Sync the preview window to this row's selected template
            tmpl_widget = self.table.cellWidget(row, _COL_TEMPLATE)
            url_path = (  # type: ignore[union-attr]
                tmpl_widget.currentData() if isinstance(tmpl_widget, QComboBox) else ""
            )
            if url_path:
                filename = pathlib.Path(url_path).name
                for i in range(self._preview_window.template_combo.count()):
                    item_path = self._preview_window.template_combo.itemData(i)
                    if hasattr(item_path, "name") and item_path.name == filename:
                        self._preview_window.template_combo.setCurrentIndex(i)
                        break

            nowplaying.utils.qt.focus_window(self._preview_window)

        return _handler

    @Slot(str)
    def _on_template_selected(self, template_name: str) -> None:
        """Update the template column for the row that launched the preview."""
        if self._preview_row < 0:
            return
        tmpl_widget = self.table.cellWidget(self._preview_row, _COL_TEMPLATE)
        if not isinstance(tmpl_widget, QComboBox):
            return
        signal_stem = pathlib.Path(template_name).stem
        for i in range(tmpl_widget.count()):
            url_path = tmpl_widget.itemData(i)
            if isinstance(url_path, str) and pathlib.Path(url_path).stem == signal_stem:
                tmpl_widget.setCurrentIndex(i)
                return

    def _row_to_source(self, row: int) -> "nowplaying.obs.scenebuilder.OBSSourceDef | None":
        """Read one table row; return OBSSourceDef if checked, else None."""
        include_item = self.table.item(row, _COL_INCLUDE)
        if include_item is None or include_item.checkState() != Qt.CheckState.Checked:
            return None

        name_item = self.table.item(row, _COL_SOURCE)
        name = name_item.text() if name_item else ""

        tmpl_widget = self.table.cellWidget(row, _COL_TEMPLATE)
        url_path = (  # type: ignore[union-attr]
            tmpl_widget.currentData() if isinstance(tmpl_widget, QComboBox) else ""
        )
        if url_path and not url_path.startswith("custom/"):
            url_path = self._ensure_custom_copy(url_path)
        path = f"/{url_path}" if url_path else "/"

        width_widget = self.table.cellWidget(row, _COL_WIDTH)
        width = width_widget.value() if isinstance(width_widget, QSpinBox) else 800

        height_widget = self.table.cellWidget(row, _COL_HEIGHT)
        height = height_widget.value() if isinstance(height_widget, QSpinBox) else 300

        pos_widget = self.table.cellWidget(row, _COL_POSITION)
        hint = pos_widget.currentText() if isinstance(pos_widget, QComboBox) else "bottom"

        return nowplaying.obs.scenebuilder.OBSSourceDef(
            name=name, path=path, width=width, height=height, hint=hint
        )

    @staticmethod
    def _obs_is_running() -> bool:
        """Return True if an OBS Studio process is currently running."""
        obs_names = {"obs64.exe", "obs.exe", "obs", "obs-studio"}
        for proc in psutil.process_iter(["name"]):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                if proc.info["name"] and proc.info["name"].lower() in obs_names:
                    return True
        return False

    @Slot()
    def _on_export(self) -> None:
        """Collect checked rows and call scenebuilder.build_and_save."""
        if self._obs_is_running():
            self.status_label.setText(
                "OBS is running — please quit OBS before exporting, "
                "then relaunch it to load the new scene collection."
            )
            return

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
            self.status_label.setText(
                f"Saved to: {saved_path} "
                f"(scenes: {nowplaying.obs.scenebuilder.MAIN_SCENE_NAME}, "
                f"{nowplaying.obs.scenebuilder.GUESS_GAME_SCENE_NAME}, "
                f"{nowplaying.obs.scenebuilder.GUESS_GAME_BASIC_SCENE_NAME})"
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("OBS export failed: %s", exc)
            self.status_label.setText(f"Error: {exc}")
