#!/usr/bin/env python3
"""Embedded browser preview window for webserver templates"""

import logging
import pathlib

from PySide6.QtCore import QSize, QUrl, Signal  # pylint: disable=no-name-in-module
from PySide6.QtGui import QColor  # pylint: disable=no-name-in-module
from PySide6.QtWebEngineCore import QWebEngineSettings  # pylint: disable=no-name-in-module
from PySide6.QtWebEngineWidgets import QWebEngineView  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import nowplaying.preview
import nowplaying.template_colors


class WebPreviewWindow(QWidget):  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """Standalone non-modal window showing a live preview of a webserver template.

    The preview loads the template via the local webserver with ``?preview=1``
    appended, which causes the server to render using the last known metadata
    or fall back to sample data when nothing is playing.

    The URL label shows the clean URL (without ``?preview=1``) so users can
    copy it directly into OBS or a browser.

    When ``enable_select_button=True`` a "Use This Template" button is shown;
    clicking it emits ``template_selected(name)`` with the current template
    filename so callers can update their own state.
    """

    template_selected = Signal(str)

    def __init__(self, config, parent=None, enable_select_button: bool = False) -> None:
        super().__init__(parent)
        self.config = config
        self._enable_select_button = enable_select_button
        self.template_combo = QComboBox()
        self.url_label = QLabel()
        self.bg_combo = QComboBox()
        self.sample_checkbox = QCheckBox("Sample data")
        self.webgl_notice = QFrame()
        self.webview = QWebEngineView()
        self._effect_combo = QComboBox()
        self._current_family: str | None = None
        self.setWindowTitle("Template Preview")
        self.resize(900, 650)
        self._setup_ui()
        self.populate_templates()
        self._on_template_selected()
        self._load_current()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _create_toolbar(self) -> QHBoxLayout:
        """Build and return the toolbar layout."""
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("Template:"))

        self.template_combo.setEditable(False)
        self.template_combo.setMinimumWidth(220)
        self.template_combo.currentIndexChanged.connect(self._on_template_selected)
        toolbar.addWidget(self.template_combo)

        self._effect_combo.setEditable(False)
        self._effect_combo.setMinimumWidth(120)
        self._effect_combo.currentIndexChanged.connect(self._on_effect_selected)
        self._effect_combo.setVisible(False)
        toolbar.addWidget(self._effect_combo)

        self.url_label.setWordWrap(False)
        toolbar.addWidget(self.url_label, stretch=1)

        toolbar.addWidget(QLabel("BG:"))

        for name, _ in nowplaying.preview.BG_PRESETS:
            self.bg_combo.addItem(name)
        self.bg_combo.currentIndexChanged.connect(self._on_bg_selected)
        toolbar.addWidget(self.bg_combo)

        self.sample_checkbox.setChecked(False)
        self.sample_checkbox.toggled.connect(self._load_current)
        toolbar.addWidget(self.sample_checkbox)

        refresh_button = QPushButton("Refresh")
        refresh_button.setFixedWidth(80)
        refresh_button.clicked.connect(self._reload)
        toolbar.addWidget(refresh_button)

        if self._enable_select_button:
            use_button = QPushButton("Use This Template")
            use_button.clicked.connect(self._on_use_template)
            toolbar.addWidget(use_button)

        return toolbar

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)

        layout.addLayout(self._create_toolbar())

        # ---- WebGL notice (hidden until needed) ----
        self.webgl_notice.setStyleSheet(
            "QFrame { background: #7a4f00; border-radius: 4px; padding: 2px; }"
        )
        notice_layout = QHBoxLayout(self.webgl_notice)
        notice_layout.setContentsMargins(8, 4, 8, 4)
        notice_label = QLabel(
            "WebGL is not available in this environment — "
            "the animation will not render. "
            "The text overlay will still work in OBS if the viewer's GPU supports WebGL."
        )
        notice_label.setStyleSheet("color: #ffe0a0;")
        notice_label.setWordWrap(True)
        notice_layout.addWidget(notice_label)
        self.webgl_notice.setVisible(False)
        layout.addWidget(self.webgl_notice)

        # ---- browser ----
        settings = self.webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        self.webview.loadFinished.connect(self._on_load_finished)  # type: ignore[attr-defined]
        self._apply_bg(0)
        layout.addWidget(self.webview)

    def _preselect_configured_template(self, configured_stem: str) -> None:
        """Preselect the combo entry matching *configured_stem*."""
        if not configured_stem:
            return
        if configured_stem in nowplaying.template_colors.STEM_TO_FAMILY:
            family_name, _ = nowplaying.template_colors.STEM_TO_FAMILY[configured_stem]
            idx = self.template_combo.findText(family_name)
            if idx >= 0:
                self.template_combo.setCurrentIndex(idx)
            return
        for i in range(self.template_combo.count()):
            item_path = self.template_combo.itemData(i)
            if isinstance(item_path, pathlib.Path) and item_path.stem == configured_stem:
                self.template_combo.setCurrentIndex(i)
                break

    def populate_templates(self) -> None:
        """Fill the combobox with families, standalone templates, and custom templates."""
        templatedir = pathlib.Path(self.config.templatedir)
        custom_dir = nowplaying.template_colors.custom_dir_for_config(self.config.templatedir)

        configured = self.config.cparser.value("weboutput/htmltemplate", defaultValue="")
        configured_stem = pathlib.Path(configured).stem if configured else ""

        # Stems that belong to a family — hidden from the main combo
        family_stems: set[str] = {
            stem
            for effects in nowplaying.template_colors.TEMPLATE_FAMILIES.values()
            for stem in effects.values()
        }

        self.template_combo.blockSignals(True)
        self.template_combo.clear()

        custom_templates = sorted(custom_dir.glob("*.htm")) if custom_dir.exists() else []
        stock_templates = sorted(templatedir.glob("*.htm"))

        if not stock_templates and not custom_templates:
            self.template_combo.addItem("(no templates found)", userData=None)
            self.template_combo.setEnabled(False)
            self.webview.setEnabled(False)
            self.template_combo.blockSignals(False)
            return

        self.template_combo.setEnabled(True)
        self.webview.setEnabled(True)

        # Custom templates always shown individually
        for tmpl in custom_templates:
            self.template_combo.addItem(f"★ {tmpl.stem}", userData=tmpl)

        # Family entries (one per family, using the canonical/None-effect stem)
        for family_name, effects in nowplaying.template_colors.TEMPLATE_FAMILIES.items():
            canonical_stem = next(iter(effects.values()))
            canonical_path = templatedir / f"{canonical_stem}.htm"
            if canonical_path.exists():
                self.template_combo.addItem(family_name, userData=family_name)

        # Standalone stock templates (not part of any family)
        for tmpl in stock_templates:
            if tmpl.stem not in family_stems:
                self.template_combo.addItem(tmpl.name, userData=tmpl)

        self._preselect_configured_template(configured_stem)
        self.template_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    def _template_url_name(self, template_path: pathlib.Path) -> str:
        """Return the URL path segment for *template_path* relative to templatedir."""
        templatedir = pathlib.Path(self.config.templatedir)
        try:
            return template_path.relative_to(templatedir).as_posix()
        except ValueError:
            return template_path.name

    def _clean_url(self, url_name: str) -> str:
        """URL suitable for display and for copying into OBS -- no ?preview=1."""
        port = self.config.cparser.value("weboutput/httpport", type=int)
        path = f"/{url_name}" if url_name else "/"
        return f"http://localhost:{port}{path}"

    def _preview_url(self, url_name: str) -> QUrl:
        """URL actually loaded in the webview -- includes ?preview=1 and optionally &sample=1."""
        url = self._clean_url(url_name) + "?preview=1"
        if self.sample_checkbox.isChecked():
            url += "&sample=1"
        return QUrl(url)

    def _current_template_path(self) -> pathlib.Path | None:
        """Return the .htm path for the current family+effect or standalone selection."""
        item_data = self.template_combo.currentData()
        templatedir = pathlib.Path(self.config.templatedir)

        if isinstance(item_data, str):
            # Family entry — resolve via effect combo
            family_name = item_data
            effects = nowplaying.template_colors.TEMPLATE_FAMILIES.get(family_name, {})
            effect_label = self._effect_combo.currentText() or next(iter(effects), "")
            stem = effects.get(effect_label, "")
            if stem:
                return templatedir / f"{stem}.htm"
            return None

        # Standalone or custom — item_data is already a Path
        return item_data if isinstance(item_data, pathlib.Path) else None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _apply_bg(self, index: int) -> None:
        _, color = nowplaying.preview.BG_PRESETS[index]
        self.webview.page().setBackgroundColor(QColor(color))

    def _load_current(self) -> None:
        path = self._current_template_path()
        if path is None:
            return
        url_name = self._template_url_name(path)
        self.url_label.setText(self._clean_url(url_name))
        url = self._preview_url(url_name)
        logging.debug("WebPreviewWindow loading %s", url.toString())
        self.webview.load(url)

    def _on_template_selected(self) -> None:
        """Handle template combo change — populate effect combo if it's a family."""
        item_data = self.template_combo.currentData()

        if isinstance(item_data, str):
            # Family entry
            self._current_family = item_data
            self._populate_effect_combo(item_data)
        else:
            # Standalone or custom template
            self._current_family = None
            self._effect_combo.setVisible(False)

        self._load_current()

    def _populate_effect_combo(self, family_name: str) -> None:
        """Fill the effect combo for the given family and show it."""
        effects = nowplaying.template_colors.TEMPLATE_FAMILIES.get(family_name, {})
        self._effect_combo.blockSignals(True)
        self._effect_combo.clear()
        for label in effects:
            self._effect_combo.addItem(label)
        self._effect_combo.blockSignals(False)
        self._effect_combo.setVisible(len(effects) > 1)

    def _on_effect_selected(self) -> None:
        """Handle effect combo change."""
        self._load_current()

    def _on_bg_selected(self, index: int) -> None:
        self._apply_bg(index)
        self.webview.reload()

    def _on_load_finished(self, ok: bool) -> None:
        """After page load, probe WebGL availability."""
        if not ok:
            return
        self.webview.page().runJavaScript(
            "(function(){"
            " if (typeof WNPWebGL === 'undefined') return true;"
            " var c = document.createElement('canvas');"
            " return !!(c.getContext('webgl') || c.getContext('experimental-webgl'));"
            "})()",
            self._on_webgl_check_result,
        )

    def _on_webgl_check_result(self, has_webgl: bool) -> None:
        self.webgl_notice.setVisible(not has_webgl)

    def _reload(self) -> None:
        self.webview.reload()

    def _on_use_template(self) -> None:
        path = self._current_template_path()
        if path:
            self.template_selected.emit(self._template_url_name(path))

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # pylint: disable=invalid-name
        """Refresh template list each time the window becomes visible."""
        super().showEvent(event)
        self.populate_templates()

    def sizeHint(self) -> QSize:  # pylint: disable=invalid-name,no-self-use
        """preferred initial size"""
        return QSize(900, 650)
