#!/usr/bin/env python3
''' test code '''
# This Python file uses the following encoding: utf-8
import sys
import os
import socket

from PySide2.QtWidgets import QApplication, QWidget  # pylint: disable=no-name-in-module
from PySide2.QtCore import QFile  # pylint: disable=no-name-in-module
from PySide2.QtUiTools import QUiLoader  # pylint: disable=no-name-in-module


class SettingsUI(QWidget): # pylint: disable=too-few-public-methods
    ''' test class '''
    def __init__(self):
        super(SettingsUI, self).__init__()
        self.load_ui()

        try:
            hostname = socket.gethostname()
            hostip = socket.gethostbyname(hostname)
        except:  # pylint: disable = bare-except
            hostname = 'Unknown Hostname'
            hostip = 'Unknown IP'

        self.ui.network_info_label.setText(
            f'Hostname: {hostname} / IP: {hostip}')

    def load_ui(self):
        ''' load the UI '''
        loader = QUiLoader()
        path = os.path.join(os.path.dirname(__file__), "nowplaying",
                            "resources", "settings.ui")
        ui_file = QFile(path)
        ui_file.open(QFile.ReadOnly)
        self.qtui = loader.load(ui_file)
        ui_file.close()


if __name__ == "__main__":
    app = QApplication([])
    widget = SettingsUI()
    widget.qtui.show()
    sys.exit(app.exec_())
