"""Tab widget management for settings groups"""

from PySide6.QtWidgets import QTabWidget, QWidget  # pylint: disable=no-name-in-module


class SettingsTabWidget(QTabWidget):
    """Custom tab widget for settings groups like Twitch/Kick"""

    def __init__(self, group_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.group_name = group_name
        self.tab_widgets: dict[str, QWidget] = {}

    def add_settings_tab(self, tab_key: str, widget: QWidget, tab_title: str):
        """Add a settings widget as a tab. If tab_key exists, replace the old tab."""
        if tab_key in self.tab_widgets:
            old_widget = self.tab_widgets[tab_key]
            old_index = self.indexOf(old_widget)
            if old_index != -1:
                self.removeTab(old_index)
        index = self.addTab(widget, tab_title)
        self.tab_widgets[tab_key] = widget
        return index

    def get_tab_widget(self, tab_key: str) -> QWidget | None:
        """Get the widget for a specific tab"""
        return self.tab_widgets.get(tab_key)

    def get_current_tab_key(self) -> str | None:
        """Get the key of the currently selected tab"""
        current_widget = self.currentWidget()
        for key, widget in self.tab_widgets.items():
            if widget == current_widget:
                return key
        return None


class TabWidgetManager:
    """Manages tab widgets for settings groups"""

    def __init__(self):
        self.tab_widgets: dict[str, SettingsTabWidget] = {}

    def create_tab_widget(self, group_name: str) -> SettingsTabWidget:
        """Create and store a new tab widget for a group"""
        tab_widget = SettingsTabWidget(group_name)
        self.tab_widgets[group_name] = tab_widget
        return tab_widget

    def get_tab_widget(self, group_name: str) -> SettingsTabWidget | None:
        """Get an existing tab widget"""
        return self.tab_widgets.get(group_name)

    def remove_tab_widget(self, group_name: str):
        """Remove a tab widget"""
        if group_name in self.tab_widgets:
            del self.tab_widgets[group_name]
