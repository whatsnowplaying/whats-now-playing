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

# Background presets: (label, hex color)
_BG_PRESETS: list[tuple[str, str]] = [
    ("Dark gray", "#1a1a1a"),
    ("Black", "#000000"),
    ("White", "#ffffff"),
    ("Medium gray", "#808080"),
    ("Chroma green", "#00b140"),
]


class WebPreviewWindow(QWidget):  # pylint: disable=too-few-public-methods,too-many-instance-attributes
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
        self.setWindowTitle("Template Preview")
        self.resize(900, 600)
        self._setup_ui()
        self._populate_templates()
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

        self.url_label.setWordWrap(False)
        toolbar.addWidget(self.url_label, stretch=1)

        toolbar.addWidget(QLabel("BG:"))

        for name, _ in _BG_PRESETS:
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
        layout.setSpacing(4)

        layout.addLayout(self._create_toolbar())

        # ---- WebGL notice (hidden until needed) ----
        self.webgl_notice.setStyleSheet(
            "QFrame { background: #7a4f00; border-radius: 4px; padding: 2px; }"
        )
        notice_layout = QHBoxLayout(self.webgl_notice)
        notice_layout.setContentsMargins(8, 4, 8, 4)
        notice_label = QLabel(
            "WebGL is not available in this environment \u2014 "
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

    def _populate_templates(self) -> None:
        """Fill the combobox with .htm files from the bundled template directory."""
        templatedir = pathlib.Path(self.config.templatedir)
        templates = sorted(templatedir.glob("*.htm"))

        configured = self.config.cparser.value("weboutput/htmltemplate", defaultValue="")
        configured_name = pathlib.Path(configured).name if configured else ""

        self.template_combo.blockSignals(True)
        if not templates:
            self.template_combo.addItem("(no templates found)", userData=None)
            self.template_combo.setEnabled(False)
            self.webview.setEnabled(False)
        else:
            for tmpl in templates:
                self.template_combo.addItem(tmpl.name, userData=tmpl.name)

            # Preselect the currently configured template if it's in the list
            if configured_name:
                idx = self.template_combo.findData(configured_name)
                if idx >= 0:
                    self.template_combo.setCurrentIndex(idx)

        self.template_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    def _clean_url(self, template_name: str) -> str:
        """URL suitable for display and for copying into OBS — no ?preview=1."""
        port = self.config.cparser.value("weboutput/httpport", type=int)
        path = f"/{template_name}" if template_name else "/"
        return f"http://localhost:{port}{path}"

    def _preview_url(self, template_name: str) -> QUrl:
        """URL actually loaded in the webview — includes ?preview=1 and optionally &sample=1."""
        url = self._clean_url(template_name) + "?preview=1"
        if self.sample_checkbox.isChecked():
            url += "&sample=1"
        return QUrl(url)

    def _current_template_name(self) -> str:
        return self.template_combo.currentData() or ""

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _apply_bg(self, index: int) -> None:
        _, color = _BG_PRESETS[index]
        self.webview.page().setBackgroundColor(QColor(color))

    def _load_current(self) -> None:
        name = self._current_template_name()
        self.url_label.setText(self._clean_url(name))
        url = self._preview_url(name)
        logging.debug("WebPreviewWindow loading %s", url.toString())
        self.webview.load(url)

    def _on_template_selected(self) -> None:
        self._load_current()

    def _on_bg_selected(self, index: int) -> None:
        self._apply_bg(index)
        self.webview.reload()

    def _on_load_finished(self, ok: bool) -> None:
        """After page load, probe WebGL availability if the template uses it.

        Detects WebGL templates by checking whether WNPWebGL is defined in the
        page's JS context — all WebGL overlay templates define it, non-WebGL
        templates do not, so no name-based heuristic is needed.
        """
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
        name = self._current_template_name()
        if name:
            self.template_selected.emit(name)

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:  # pylint: disable=invalid-name,no-self-use
        """preferred initial size"""
        return QSize(900, 600)
