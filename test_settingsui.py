#!/usr/bin/env python3
''' test code '''
# This Python file uses the following encoding: utf-8
import sys
import pathlib
import socket

from PySide6.QtWidgets import QApplication, QWidget  # pylint: disable=no-name-in-module
from PySide6.QtCore import QFile, Slot  # pylint: disable=no-name-in-module
from PySide6.QtUiTools import QUiLoader  # pylint: disable=no-name-in-module

GENERAL = [
    'about', 'general', 'obsws', 'quirks', 'settings', 'source', 'twitchbot',
    'webserver'
]

INPUTS = ['inputs_m3u', 'inputs_mpris2', 'inputs_serato']

ARTISTEXTRAS = [
    'artistextras_discogs', 'artistextras_fanarttv', 'artistextras_theaudiodb'
]

RECOG = ['recognition_acoustidmb']


class SettingsUI(QWidget):  # pylint: disable=too-few-public-methods
    ''' test class '''

    def __init__(self):
        super().__init__()
        self.qtui = None
        self.widgets = {}
        self.uipath = pathlib.Path(__file__)
        self.uipath = self.uipath.parent.joinpath('nowplaying', 'resources')
        self.load_qtui()

    def load_qtui(self):
        ''' load the base UI and wire it up '''

        def _load_ui(uipath, name):
            ''' load a UI file into a widget '''
            loader = QUiLoader()
            ui_file = QFile(uipath.joinpath(f'{name}_ui.ui'))
            ui_file.open(QFile.ReadOnly)
            qwidget = loader.load(ui_file)
            ui_file.close()
            return qwidget

        self.qtui = _load_ui(self.uipath, 'settings')
        for basic in GENERAL + ARTISTEXTRAS + INPUTS + RECOG:
            self.widgets[basic] = _load_ui(self.uipath, f'{basic}')
            try:
                qobject_connector = getattr(self, f'_connect_{basic}_widget')
                qobject_connector(self.widgets[basic])
            except AttributeError:
                pass

            self.qtui.settings_stack.addWidget(self.widgets[basic])
            self._load_list_item(f'{basic}', self.widgets[basic])

        self.qtui.settings_list.currentRowChanged.connect(
            self._set_stacked_display)

    def _connect_recognition_acoustidmb_widget(self, qobject):
        qobject.acoustid_checkbox.clicked.connect(
            self._acoustidmb_checkbox_hook)

    @Slot()
    def _acoustidmb_checkbox_hook(self):
        if self.widgets['recognition_acoustidmb'].acoustid_checkbox.isChecked(
        ):
            self.widgets[
                'recognition_acoustidmb'].musicbrainz_checkbox.setChecked(True)

    def _connect_webserver_widget(self, qobject):  # pylint: disable=no-self-use
        try:
            hostname = socket.gethostname()
            hostip = socket.gethostbyname(hostname)
        except:  # pylint: disable = bare-except
            pass

        if hostname:
            qobject.hostname_label.setText(hostname)
        if hostip:
            qobject.hostip_label.setText(hostip)

    def _connect_source_widget(self, qobject):
        ''' populate the input group box '''
        for text in ['Serato', 'M3U', 'MPRIS2']:
            qobject.sourcelist.addItem(text)
        qobject.currentRowChanged.connect(self._set_source_description)

    def _set_source_description(self, index):
        print('here')
        self.widgets['source'].description.setText(f'You hit {index}.')

    def _load_list_item(self, name, qobject):
        displayname = qobject.property('displayName')
        if not displayname:
            displayname = name.capitalize()
        self.qtui.settings_list.addItem(displayname)

    def _set_stacked_display(self, index):
        self.qtui.settings_stack.setCurrentIndex(index)


if __name__ == "__main__":
    app = QApplication([])
    widget = SettingsUI()
    widget.qtui.show()
    sys.exit(app.exec())
