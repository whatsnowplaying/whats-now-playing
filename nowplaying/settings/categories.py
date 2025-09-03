"""Settings categories and tree structure management"""

import logging
from dataclasses import dataclass, field

from PySide6.QtWidgets import QTreeWidgetItem  # pylint: disable=no-name-in-module


@dataclass
class SettingsCategory:
    """Represents a settings category in the tree"""

    name: str
    display_name: str
    items: list[str] = field(default_factory=list)
    tree_item: QTreeWidgetItem | None = None

    def add_item(self, item_name: str) -> None:
        """Add an item to this category"""
        if item_name not in self.items:
            self.items.append(item_name)


@dataclass
class TabGroup:
    """Represents a tabbed group within a category"""

    name: str
    display_name: str
    tabs: dict[str, str]  # {tab_key: display_name}


class SettingsCategoryManager:
    """Manages the hierarchical structure of settings categories"""

    def __init__(self):
        self.categories: list[SettingsCategory] = []
        self.tab_groups: list[TabGroup] = []
        # Mapping of plugin types to their target category names
        self.plugin_type_mapping = {
            "inputs": "inputs",
            "recognition": "recognition",
            "artistextras": "artistdata",
            "notifications": "output",
        }
        self._init_categories()

    def _init_categories(self):
        """Initialize the default category structure"""

        # About will be handled separately as a standalone item, not a category

        # Core Settings
        self.categories.append(
            SettingsCategory("core", "Core Settings", ["general", "source", "filter", "trackskip"])
        )

        # Output & Display
        self.categories.append(
            SettingsCategory("output", "Output & Display", ["textoutput", "webserver", "obsws"])
        )

        # Streaming & Chat (with tab groups)
        streaming_category = SettingsCategory("streaming", "Streaming & Chat", [])
        self.categories.append(streaming_category)

        # Define tab groups for streaming platforms
        self.tab_groups.extend(
            [
                TabGroup("twitch_group", "Twitch", {"twitch": "Settings", "twitchchat": "Chat"}),
                TabGroup("kick_group", "Kick", {"kick": "Settings", "kickchat": "Chat"}),
            ]
        )

        # Add individual items for streaming category
        streaming_category.add_item("requests")
        streaming_category.add_item("discordbot")

        # Artist Data
        self.categories.append(SettingsCategory("artistdata", "Artist Data", ["artistextras"]))

        # Input Sources
        self.categories.append(
            SettingsCategory(
                "inputs",
                "Input Sources",
                [],  # Will be populated dynamically with plugin inputs
            )
        )

        # Recognition
        self.categories.append(
            SettingsCategory(
                "recognition",
                "Recognition",
                [],  # Will be populated dynamically with recognition plugins
            )
        )

        # System
        self.categories.append(SettingsCategory("system", "System", ["quirks", "destroy"]))

    def get_category_for_item(self, item_name: str) -> SettingsCategory | None:
        """Find which category contains the given item"""
        # Check tab groups first
        for tab_group in self.tab_groups:
            if item_name in tab_group.tabs:
                # Find the streaming category
                for category in self.categories:
                    if category.name == "streaming":
                        return category

        # Check regular categories
        for category in self.categories:
            if item_name in category.items:
                return category

        return None

    def get_tab_group_for_item(self, item_name: str) -> TabGroup | None:
        """Find which tab group contains the given item"""
        for tab_group in self.tab_groups:
            if item_name in tab_group.tabs:
                return tab_group
        return None

    def add_plugin_item(self, plugin_type: str, item_name: str):
        """Add a plugin item to the appropriate category"""
        target_category_name = self.plugin_type_mapping.get(plugin_type)
        if target_category_name:
            if target_category := next(
                (c for c in self.categories if c.name == target_category_name), None
            ):
                target_category.add_item(f"{plugin_type}_{item_name}")
        else:
            # Log unknown plugin types for future extension
            logging.debug("Unknown plugin type '%s', skipping item '%s'", plugin_type, item_name)

    def get_item_hierarchy(self, item_name: str) -> tuple[str | None, str | None, str | None]:
        """Get the hierarchy path for an item (category, tab_group, item)"""

        if tab_group := self.get_tab_group_for_item(item_name):
            return ("streaming", tab_group.name, item_name)

        if category := self.get_category_for_item(item_name):
            return (category.name, None, item_name)

        return (None, None, item_name)
