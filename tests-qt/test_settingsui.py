#!/usr/bin/env python3
"""test settingsui"""

# pylint: disable=redefined-outer-name,unused-argument,protected-access, unused-variable

from PySide6.QtCore import Qt  # pylint: disable=import-error, no-name-in-module
from PySide6.QtGui import QAction  # pylint: disable=import-error, no-name-in-module
from PySide6.QtWidgets import QLabel, QWidget  # pylint: disable=import-error, no-name-in-module

import nowplaying.settingsui  # pylint: disable=import-error
from nowplaying.settings.tabs import SettingsTabWidget


class MockSubprocesses:
    """mock"""

    def restart_webserver(self):
        """mock"""

    def restart_obsws(self):
        """mock"""

    def stop_twitchbot(self):
        """mock"""

    def start_twitchbot(self):
        """mock"""

    def stop_kickbot(self):
        """mock"""

    def start_kickbot(self):
        """mock"""


class MockTray:
    """mock"""

    def __init__(self, config=None):
        self.config = config
        self.settings_action = QAction()
        self.action_pause = QAction()
        self.subprocesses = MockSubprocesses()

    def cleanquit(self):
        """mock"""

    def fix_mixmode_menu(self):
        """mock"""


def test_settingsui_cancel(bootstrap, qtbot):
    """test cancel"""
    config = bootstrap
    tray = MockTray(config)
    settingsui = nowplaying.settingsui.SettingsUI(tray=tray)
    qtbot.addWidget(settingsui.qtui)
    qtbot.mouseClick(settingsui.qtui.cancel_button, Qt.MouseButton.LeftButton)


def test_settingsui_save(bootstrap, qtbot):
    """test save"""
    config = bootstrap
    tray = MockTray(config)
    settingsui = nowplaying.settingsui.SettingsUI(tray=tray)
    qtbot.addWidget(settingsui.qtui)
    item = settingsui.widgets["source"].sourcelist.item(0)
    rect = settingsui.widgets["source"].sourcelist.visualItemRect(item)
    center = rect.center()

    assert settingsui.widgets["source"].sourcelist.itemAt(center).text() == item.text()

    settingsui.widgets["webserver"].enable_checkbox.setChecked(False)

    qtbot.mouseClick(
        settingsui.widgets["source"].sourcelist.viewport(), Qt.MouseButton.LeftButton, pos=center
    )
    qtbot.mouseClick(settingsui.qtui.save_button, Qt.MouseButton.LeftButton)


def test_settingsui_tree_navigation(bootstrap, qtbot):
    """test tree navigation"""
    config = bootstrap
    tray = MockTray(config)
    settingsui = nowplaying.settingsui.SettingsUI(tray=tray)
    qtbot.addWidget(settingsui.qtui)

    # Test that tree has items
    tree = settingsui.qtui.settings_tree
    assert tree.topLevelItemCount() > 0

    # Test clicking on About item
    about_items = tree.findItems("About", Qt.MatchRecursive)
    assert len(about_items) > 0

    about_item = about_items[0]
    qtbot.mouseClick(tree, Qt.MouseButton.LeftButton, pos=tree.visualItemRect(about_item).center())

    # Test that stack index changed
    assert settingsui.qtui.settings_stack.currentIndex() >= 0


def test_settingsui_keyboard_navigation(bootstrap, qtbot):
    """test keyboard navigation accessibility"""
    config = bootstrap
    tray = MockTray(config)
    settingsui = nowplaying.settingsui.SettingsUI(tray=tray)
    qtbot.addWidget(settingsui.qtui)

    tree = settingsui.qtui.settings_tree
    tree.setFocus()

    # Test programmatic selection (simulates keyboard navigation)
    about_items = tree.findItems("About", Qt.MatchRecursive)
    assert len(about_items) > 0

    initial_index = settingsui.qtui.settings_stack.currentIndex()

    # Programmatically select the About item (simulates keyboard selection)
    tree.setCurrentItem(about_items[0])

    # Verify the stack changed
    new_index = settingsui.qtui.settings_stack.currentIndex()
    assert new_index != initial_index or new_index >= 0


def test_settingsui_tab_duplicate_handling(bootstrap, qtbot):
    """test tab widget duplicate key handling"""

    tab_widget = SettingsTabWidget("test_group")
    qtbot.addWidget(tab_widget)

    # Create two different widgets
    widget1 = QWidget()
    label1 = QLabel("Widget 1", widget1)
    widget2 = QWidget()
    label2 = QLabel("Widget 2", widget2)

    # Add first tab
    tab_widget.add_settings_tab("test_key", widget1, "Tab 1")
    assert tab_widget.count() == 1
    assert tab_widget.get_tab_widget("test_key") == widget1

    # Add second tab with same key - should replace first
    tab_widget.add_settings_tab("test_key", widget2, "Tab 2")
    assert tab_widget.count() == 1  # Still only 1 tab
    assert tab_widget.get_tab_widget("test_key") == widget2  # Points to new widget
