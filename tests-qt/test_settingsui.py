#!/usr/bin/env python3
''' test settingsui '''

from PySide6.QtCore import Qt  # pylint: disable=import-error, no-name-in-module
from PySide6.QtGui import QAction  # pylint: disable=import-error, no-name-in-module

import nowplaying.settingsui  # pylint: disable=import-error


class MockSubprocesses:
    ''' mock '''

    def restart_webserver(self):
        ''' mock '''

    def restart_obsws(self):
        ''' mock '''

    def stop_twitchbot(self):
        ''' mock '''

    def start_twitchbot(self):
        ''' mock '''


class MockTray:
    ''' mock '''

    def __init__(self, config=None):
        self.config = config
        self.beam = False
        self.settings_action = QAction()
        self.action_pause = QAction()
        self.subprocesses = MockSubprocesses()

    def cleanquit(self):
        ''' mock '''

    def fix_mixmode_menu(self):
        ''' mock '''


def test_settingsui_cancel(bootstrap, qtbot):
    ''' test cancel '''
    config = bootstrap
    tray = MockTray(config)
    settingsui = nowplaying.settingsui.SettingsUI(tray=tray, beam=False)
    qtbot.addWidget(settingsui.qtui)
    qtbot.mouseClick(settingsui.qtui.cancel_button, Qt.MouseButton.LeftButton)


def test_settingsui_save(bootstrap, qtbot):
    ''' test save '''
    config = bootstrap
    tray = MockTray(config)
    settingsui = nowplaying.settingsui.SettingsUI(tray=tray, beam=False)
    qtbot.addWidget(settingsui.qtui)
    item = settingsui.widgets['source'].sourcelist.item(0)
    rect = settingsui.widgets['source'].sourcelist.visualItemRect(item)
    center = rect.center()

    assert settingsui.widgets['source'].sourcelist.itemAt(center).text() == item.text()

    settingsui.widgets['webserver'].enable_checkbox.setChecked(False)

    qtbot.mouseClick(settingsui.widgets['source'].sourcelist.viewport(),
                     Qt.MouseButton.LeftButton,
                     pos=center)
    qtbot.mouseClick(settingsui.qtui.save_button, Qt.MouseButton.LeftButton)
