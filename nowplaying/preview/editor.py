#!/usr/bin/env python3
"""Template editor window — thin QWebEngineView shell loading the web editor."""

from PySide6.QtCore import QUrl  # pylint: disable=no-name-in-module
from PySide6.QtWebEngineCore import QWebEngineSettings  # pylint: disable=no-name-in-module
from PySide6.QtWebEngineWidgets import QWebEngineView  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QVBoxLayout, QWidget  # pylint: disable=no-name-in-module


class TemplateEditorWindow(QWidget):  # pylint: disable=too-few-public-methods
    """Template editor: opens the web-based editor served by the local webserver."""

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self.config = config

        port: int = config.cparser.value("weboutput/httpport", type=int)
        url = QUrl(f"http://localhost:{port}/template-editor")

        self.webview = QWebEngineView()
        settings = self.webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.webview)

        self.setWindowTitle("Template Editor")
        self.resize(1300, 860)
        self.webview.setUrl(url)
