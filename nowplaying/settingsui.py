#!/usr/bin/env python3
"""user interface to configure"""

# pylint: disable=too-many-lines

import contextlib
import glob
import json
import logging
import os
import pathlib
import re
from typing import TYPE_CHECKING

import PySide6.QtXml  # pylint: disable=unused-import, import-error

# pylint: disable=no-name-in-module
from PySide6.QtCore import QFile, QStandardPaths, Qt, Slot
from PySide6.QtGui import QIcon
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QErrorMessage,
    QFileDialog,
    QListWidgetItem,
    QMessageBox,
    QTabWidget,
    QTreeWidgetItem,
    QWidget,
)

import nowplaying.config
import nowplaying.hostmeta
import nowplaying.musicbrainz.plugin
import nowplaying.settings.categories
import nowplaying.settings.tabs
from nowplaying.exceptions import PluginVerifyError

try:
    import nowplaying.qtrc  # pylint: disable=import-error, no-name-in-module
except ModuleNotFoundError:
    pass
import nowplaying.kick.settings
import nowplaying.trackrequests
import nowplaying.twitch.chat
import nowplaying.twitch.settings
import nowplaying.uihelp
import nowplaying.utils

if TYPE_CHECKING:
    import nowplaying.tray

LOGGING_COMBOBOX = ["DEBUG", "INFO", "WARNING", "ERROR", "FATAL", "CRITICAL"]
NOCOVER_COMBOBOX = ["None", "Fanart", "Logo", "Thumbnail"]


# settings UI
class SettingsUI(QWidget):  # pylint: disable=too-many-public-methods, too-many-instance-attributes
    """create settings form window"""

    def __init__(self, tray: "nowplaying.tray.Tray"):
        self.config = nowplaying.config.ConfigFile()
        if not self.config:
            logging.error("FATAL ERROR: Cannot get configuration!")
            raise RuntimeError("Cannot get configuration")
        self.tray = tray
        super().__init__()
        self.qtui = None
        self.errormessage = None
        self.widgets = {}
        self.settingsclasses = {
            "twitch": nowplaying.twitch.settings.TwitchSettings(),
            "twitchchat": nowplaying.twitch.chat.TwitchChatSettings(),
            "kick": nowplaying.kick.settings.KickSettings(),
            "kickchat": nowplaying.kick.settings.KickChatSettings(),
            "requests": nowplaying.trackrequests.TrackRequestSettings(),
            "recognition_musicbrainz": nowplaying.musicbrainz.plugin.Plugin(config=self.config),
        }

        # New tree structure managers
        self.category_manager = nowplaying.settings.categories.SettingsCategoryManager()
        self.tab_manager = nowplaying.settings.tabs.TabWidgetManager()
        self.tree_item_mapping = {}  # Maps tree items to widget keys

        self.uihelp = None
        self.ui_populated = False  # Track if UI widgets are populated with config data
        self.load_qtui()
        if not self.config.iconfile:
            self.tray.cleanquit()
        if self.qtui:
            self.qtui.setWindowIcon(QIcon(str(self.config.iconfile)))

    def post_tray_init(self):
        """after the systemtray is fully loaded, do this"""

        # if system hasn't been initialized, then
        # twitch chat files are irrelevant
        if self.config.initialized:
            self.settingsclasses["twitchchat"].update_twitchbot_commands(self.config)
            self.settingsclasses["kickchat"].update_kickbot_commands(self.config)

            # Validate stored OAuth2 tokens and update UI status
            self._validate_all_oauth_tokens()

    def _validate_all_oauth_tokens(self):
        """Validate all stored OAuth2 tokens and update UI status"""
        try:
            # Validate Twitch OAuth2 tokens (broadcaster + chat)
            if "twitch" in self.settingsclasses:
                twitch_settings = self.settingsclasses["twitch"]
                if hasattr(twitch_settings, "update_oauth_status"):
                    twitch_settings.update_oauth_status()

            # Validate Kick OAuth2 tokens
            if "kick" in self.settingsclasses:
                kick_settings = self.settingsclasses["kick"]
                if hasattr(kick_settings, "update_oauth_status"):
                    kick_settings.update_oauth_status()

            logging.debug("OAuth2 token validation completed during settings UI initialization")
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Error during OAuth2 token validation: %s", error)

    def _setup_widgets(self, uiname):
        self.widgets[uiname] = load_widget_ui(self.config, f"{uiname}")
        if not self.widgets[uiname]:
            return

        with contextlib.suppress(AttributeError):
            qobject_connector = getattr(self, f"_connect_{uiname}_widget")
            qobject_connector(self.widgets[uiname])
        self.qtui.settings_stack.addWidget(self.widgets[uiname])
        # Note: Tree structure will be built later in _build_settings_tree()

    def load_qtui(self):  # pylint: disable=too-many-branches, too-many-statements
        """load the base UI and wire it up"""

        self.qtui = load_widget_ui(self.config, "settings")
        self.uihelp = nowplaying.uihelp.UIHelp(self.config, self.qtui)

        baseuis = [
            "general",
            "source",
            "filter",
            "trackskip",
            "webserver",
            "twitch",
            "twitchchat",
            "kick",
            "kickchat",
            "requests",
            "artistextras",
            "obsws",
            "discordbot",
            "quirks",
        ]

        for uiname in baseuis:
            self._setup_widgets(uiname)

        pluginuis = {}
        pluginuinames = []
        # Create mapping from display names to module names for inputs
        self.input_display_to_module = {}

        for plugintype, pluginlist in self.config.plugins.items():
            pluginuis[plugintype] = []
            for key in pluginlist:
                pkey = key.replace(f"nowplaying.{plugintype}.", "")
                pluginuis[plugintype].append(pkey)
                pluginuinames.append(f"{plugintype}_{pkey}")
                if plugintype == "inputs":
                    display_name = self.config.pluginobjs[plugintype][key].displayname
                    self.input_display_to_module[display_name.lower()] = pkey
                    self.widgets["source"].sourcelist.addItem(display_name)
                self._setup_widgets(f"{plugintype}_{pkey}")

        # Connect the source list signal once after all items are added
        self.widgets["source"].sourcelist.currentRowChanged.connect(self._set_source_description)

        # Manually add MusicBrainz settings widget (not a discoverable plugin)
        self._setup_widgets("recognition_musicbrainz")

        self._setup_widgets("destroy")
        self._setup_widgets("about")

        for key in [
            "twitch",
            "twitchchat",
            "kick",
            "kickchat",
            "requests",
        ]:
            self.settingsclasses[key].load(self.config, self.widgets[key], self.uihelp)
            self.settingsclasses[key].connect(self.uihelp, self.widgets[key])

        # Handle MusicBrainz plugin using standard plugin interface
        if self.widgets["recognition_musicbrainz"]:
            mb_plugin = self.settingsclasses["recognition_musicbrainz"]
            mb_plugin.load_settingsui(self.widgets["recognition_musicbrainz"])
            mb_plugin.connect_settingsui(self.widgets["recognition_musicbrainz"], self.uihelp)

        self._connect_plugins()
        self._build_settings_tree()

        self.qtui.settings_tree.itemClicked.connect(self._on_tree_item_clicked)
        self.qtui.settings_tree.currentItemChanged.connect(self._on_tree_selection_changed)
        self.qtui.cancel_button.clicked.connect(self.on_cancel_button)
        self.qtui.reset_button.clicked.connect(self.on_reset_button)
        self.qtui.save_button.clicked.connect(self.on_save_button)
        self.errormessage = QErrorMessage(self.qtui)

        # Select "About" as the default
        about_items = self.qtui.settings_tree.findItems("About", Qt.MatchRecursive)
        if about_items:
            self.qtui.settings_tree.setCurrentItem(about_items[0])
            self._on_tree_item_clicked(about_items[0], 0)

        # Populate UI with config data during initialization to avoid delay on show()
        self.upd_win()
        self.ui_populated = True

    def _build_settings_tree(self):
        """Build the hierarchical tree structure for settings"""
        self.qtui.settings_tree.clear()
        self.tree_item_mapping = {}

        # Add "About" as a standalone top-level item first
        if "about" in self.widgets and self.widgets["about"]:
            about_item = QTreeWidgetItem(["About"])
            self.qtui.settings_tree.addTopLevelItem(about_item)
            self.tree_item_mapping[about_item] = "about"

        # Add plugins to appropriate categories first
        for plugintype, pluginlist in self.config.plugins.items():
            for key in pluginlist:
                pkey = key.replace(f"nowplaying.{plugintype}.", "")
                display_name = self.config.pluginobjs[plugintype][key].displayname
                self.category_manager.add_plugin_item(plugintype, pkey)

        # Manually add MusicBrainz to recognition category
        self.category_manager.add_plugin_item("recognition", "musicbrainz")

        # Create tree structure for categories
        for category in self.category_manager.categories:
            category_item = QTreeWidgetItem([category.display_name])
            category.tree_item = category_item
            self.qtui.settings_tree.addTopLevelItem(category_item)

            if category.name == "streaming":
                # Handle streaming category with tab groups
                self._build_streaming_category(category_item)
            else:
                # Handle regular categories
                for item_name in category.items:
                    if item_name in self.widgets:
                        item_widget = self.widgets[item_name]
                        if item_widget:  # Only add if widget exists
                            display_name = self._get_display_name(item_name, item_widget)
                            child_item = QTreeWidgetItem([display_name])
                            category_item.addChild(child_item)
                            self.tree_item_mapping[child_item] = item_name
                        else:
                            logging.debug("Widget '%s' is None, skipping", item_name)

    def _build_streaming_category(self, category_item):
        """Build the streaming category with tab groups"""

        # Add tab groups (Twitch, Kick)
        for tab_group in self.category_manager.tab_groups:
            group_item = QTreeWidgetItem([tab_group.display_name])
            category_item.addChild(group_item)

            # Create tab widget for this group
            tab_widget = self.tab_manager.create_tab_widget(tab_group.name)

            # Add tabs to the widget
            for tab_key, tab_display in tab_group.tabs.items():
                if tab_key in self.widgets:
                    tab_widget.add_settings_tab(tab_key, self.widgets[tab_key], tab_display)

            # Only add tab widget to stack if it has tabs
            if tab_widget.count() > 0:
                # Map the group item to the tab widget
                self.tree_item_mapping[group_item] = tab_group.name
                # Add tab widget to stack
                self.qtui.settings_stack.addWidget(tab_widget)
            else:
                logging.debug("Tab widget '%s' is empty, skipping", tab_group.name)

        # Add standalone items in streaming category
        for item_name in ["requests", "discordbot"]:
            if item_name in self.widgets and self.widgets[item_name]:
                display_name = self._get_display_name(item_name, self.widgets[item_name])
                child_item = QTreeWidgetItem([display_name])
                category_item.addChild(child_item)
                self.tree_item_mapping[child_item] = item_name

    @staticmethod
    def _get_display_name(item_name, widget):
        """Get display name for an item"""
        display_name = None
        if widget:
            display_name = widget.property("displayName")

        if not display_name:
            if "_" in item_name:
                display_name = item_name.split("_")[1].capitalize()
            else:
                display_name = item_name.capitalize()
        return display_name

    def _on_tree_item_clicked(self, item, _column):
        """Handle tree item clicks"""
        self._navigate_to_item(item)

    def _on_tree_selection_changed(self, current, _previous):
        """Handle tree selection changes (keyboard navigation, programmatic selection)"""
        if current:
            self._navigate_to_item(current)

    def _navigate_to_item(self, item):
        """Navigate to the content for the given tree item"""
        if item not in self.tree_item_mapping:
            return
        mapped_value = self.tree_item_mapping[item]

        # Check if it's a tab group
        if mapped_value in [tg.name for tg in self.category_manager.tab_groups]:
            if tab_widget := self.tab_manager.get_tab_widget(mapped_value):
                # Find the index in the stack
                stack_index = self.qtui.settings_stack.indexOf(tab_widget)
                if stack_index >= 0:
                    self.qtui.settings_stack.setCurrentIndex(stack_index)
        elif mapped_value in self.widgets:
            widget = self.widgets[mapped_value]
            stack_index = self.qtui.settings_stack.indexOf(widget)
            if stack_index >= 0:
                self.qtui.settings_stack.setCurrentIndex(stack_index)

    def _connect_destroy_widget(self, qobject):
        qobject.startover_button.clicked.connect(self.fresh_start)

    def _connect_general_widget(self, qobject):
        """connect the export/import buttons"""
        qobject.export_config_button.clicked.connect(self.on_export_config_button)
        qobject.import_config_button.clicked.connect(self.on_import_config_button)

    def _connect_webserver_widget(self, qobject):
        """file in the hostname/ip and connect the template button"""

        data = nowplaying.hostmeta.gethostmeta()

        if data["hostfqdn"]:
            qobject.hostname_label.setText(data["hostfqdn"])
        if data["hostip"]:
            qobject.hostip_label.setText(data["hostip"])

        qobject.template_button.clicked.connect(self.on_html_template_button)

    def _connect_discordbot_widget(self, qobject):
        """connect the artistextras buttons to non-built-ins"""
        qobject.template_button.clicked.connect(self.on_discordbot_template_button)

    def _connect_artistextras_widget(self, qobject):
        """connect the artistextras buttons to non-built-ins"""
        qobject.clearcache_button.clicked.connect(self.on_artistextras_clearcache_button)

    def _connect_obsws_widget(self, qobject):
        """connect obsws button to template picker"""
        qobject.template_button.clicked.connect(self.on_obsws_template_button)

    def _connect_filter_widget(self, qobject):
        """connect regex filter to template picker"""
        qobject.add_recommended_button.clicked.connect(self.on_filter_add_recommended_button)
        qobject.test_button.clicked.connect(self.on_filter_test_button)
        qobject.add_button.clicked.connect(self.on_filter_regex_add_button)
        qobject.del_button.clicked.connect(self.on_filter_regex_del_button)

    def _connect_plugins(self):
        """tell config to trigger plugins to update windows"""
        self.config.plugins_connect_settingsui(self.widgets, self.uihelp)

    def _set_source_description(self, index):
        item = self.widgets["source"].sourcelist.item(index)
        display_name = item.text().lower()
        plugin = self.input_display_to_module.get(display_name, display_name)
        self.config.plugins_description("inputs", plugin, self.widgets["source"].description)

    def upd_win(self):
        """update the settings window"""
        self.config.get()
        about_version_text(self.config, self.widgets["about"])

        self.widgets["general"].delay_lineedit.setText(
            str(self.config.cparser.value("settings/delay"))
        )
        self.widgets["general"].notify_checkbox.setChecked(self.config.notif)

        self._upd_win_recognition()
        self._upd_win_input()
        self._upd_win_plugins()

        self._upd_win_artistextras()
        self._upd_win_filters()
        self._upd_win_trackskip()
        self._upd_win_webserver()
        self._upd_win_obsws()
        self._upd_win_discordbot()
        self._upd_win_quirks()

        for key in [
            "twitch",
            "twitchchat",
            "kick",
            "requests",
        ]:
            self.settingsclasses[key].load(self.config, self.widgets[key], self.uihelp)

    def _upd_win_artistextras(self):
        self.widgets["artistextras"].coverart_combobox.clear()
        self.widgets["artistextras"].coverart_combobox.addItems(NOCOVER_COMBOBOX)
        current = self.config.cparser.value("artistextras/nocoverfallback", type=str) or "None"
        currentval = NOCOVER_COMBOBOX.index(current.capitalize())
        self.widgets["artistextras"].coverart_combobox.setCurrentIndex(currentval)
        self.widgets["artistextras"].artistextras_checkbox.setChecked(
            self.config.cparser.value("artistextras/enabled", type=bool)
        )
        self.widgets["artistextras"].missingfanart_checkbox.setChecked(
            self.config.cparser.value("artistextras/coverfornofanart", type=bool)
        )
        self.widgets["artistextras"].missinglogos_checkbox.setChecked(
            self.config.cparser.value("artistextras/coverfornologos", type=bool)
        )
        self.widgets["artistextras"].missingthumbs_checkbox.setChecked(
            self.config.cparser.value("artistextras/coverfornothumbs", type=bool)
        )

        for art in ["banners", "processes", "fanart", "logos", "thumbnails", "sizelimit"]:
            guiattr = getattr(self.widgets["artistextras"], f"{art}_spin")
            guiattr.setValue(self.config.cparser.value(f"artistextras/{art}", type=int))

    def _upd_win_filters(self):
        """update the filter settings"""
        self.widgets["filter"].stripextras_checkbox.setChecked(
            self.config.cparser.value("settings/stripextras", type=bool)
        )

        self.widgets["filter"].regex_list.clear()

        for configitem in self.config.cparser.allKeys():
            if "regex_filter/" in configitem:
                self._filter_regex_load(regex=self.config.cparser.value(configitem))

    def _upd_win_trackskip(self):
        """update the trackskip settings to match config"""
        self.widgets["trackskip"].comment_lineedit.setText(
            self.config.cparser.value("trackskip/comment")
        )
        self.widgets["trackskip"].genre_lineedit.setText(
            self.config.cparser.value("trackskip/genre")
        )

    def _upd_win_recognition(self):
        self.widgets["general"].recog_title_checkbox.setChecked(
            self.config.cparser.value("recognition/replacetitle", type=bool)
        )
        self.widgets["general"].recog_artist_checkbox.setChecked(
            self.config.cparser.value("recognition/replaceartist", type=bool)
        )
        self.widgets["general"].recog_artistwebsites_checkbox.setChecked(
            self.config.cparser.value("recognition/replaceartistwebsites", type=bool)
        )

    def _upd_win_input(self):
        """this is totally wrong and will need to get dealt
        with as part of ui code redesign"""
        currentinput = self.config.cparser.value("settings/input")

        target_display_name = next(
            (
                display_name
                for display_name, module_name in self.input_display_to_module.items()
                if module_name == currentinput
            ),
            None,
        )
        # Fallback: if no mapping found, try to find by the stored
        # value directly (for backward compatibility)
        search_term = target_display_name or currentinput

        curbutton = self.widgets["source"].sourcelist.findItems(search_term, Qt.MatchContains)
        if curbutton:
            self.widgets["source"].sourcelist.setCurrentItem(curbutton[0])
        else:
            logging.warning(
                "Could not find a matching display name or module name for input '%s'. "
                "UI selection will not be set. Display names: %s, Module names: %s",
                currentinput,
                list(self.input_display_to_module.keys()),
                list(self.input_display_to_module.values()),
            )
            self.widgets["source"].sourcelist.setCurrentItem(None)

    def _upd_win_webserver(self):
        """update the webserver settings to match config"""
        self.widgets["webserver"].enable_checkbox.setChecked(
            self.config.cparser.value("weboutput/httpenabled", type=bool)
        )
        self.widgets["webserver"].port_lineedit.setText(
            str(self.config.cparser.value("weboutput/httpport"))
        )
        self.widgets["webserver"].template_lineedit.setText(
            self.config.cparser.value("weboutput/htmltemplate")
        )
        self.widgets["webserver"].once_checkbox.setChecked(
            self.config.cparser.value("weboutput/once", type=bool)
        )
        self.widgets["webserver"].remote_secret_lineedit.setText(
            self.config.cparser.value("remote/remote_key", type=str, defaultValue="")
        )

    def _upd_win_obsws(self):
        """update the obsws settings to match config"""
        self.widgets["obsws"].enable_checkbox.setChecked(
            self.config.cparser.value("obsws/enabled", type=bool)
        )
        self.widgets["obsws"].source_lineedit.setText(self.config.cparser.value("obsws/source"))
        self.widgets["obsws"].host_lineedit.setText(self.config.cparser.value("obsws/host"))
        self.widgets["obsws"].port_lineedit.setText(str(self.config.cparser.value("obsws/port")))
        self.widgets["obsws"].secret_lineedit.setText(self.config.cparser.value("obsws/secret"))
        self.widgets["obsws"].template_lineedit.setText(
            self.config.cparser.value("obsws/template")
        )

    def _upd_win_discordbot(self):
        """update the obsws settings to match config"""
        self.widgets["discordbot"].enable_checkbox.setChecked(
            self.config.cparser.value("discord/enabled", type=bool)
        )
        self.widgets["discordbot"].clientid_lineedit.setText(
            self.config.cparser.value("discord/clientid")
        )
        self.widgets["discordbot"].token_lineedit.setText(
            self.config.cparser.value("discord/token")
        )
        self.widgets["discordbot"].template_lineedit.setText(
            self.config.cparser.value("discord/template")
        )

    def _upd_win_quirks(self):
        """update the quirks settings to match config"""

        def _set_quirks_modes(arg0, arg1, arg2):
            self.widgets["quirks"].slash_nochange.setChecked(arg0)
            self.widgets["quirks"].slash_toback.setChecked(arg1)
            self.widgets["quirks"].slash_toforward.setChecked(arg2)

        # file system notification method
        if self.config.cparser.value("quirks/pollingobserver", type=bool):
            self.widgets["quirks"].fs_events_button.setChecked(False)
            self.widgets["quirks"].fs_poll_button.setChecked(True)
        else:
            self.widgets["quirks"].fs_events_button.setChecked(True)
            self.widgets["quirks"].fs_poll_button.setChecked(False)

        # s,in,out,g
        self.widgets["quirks"].song_subst_checkbox.setChecked(
            self.config.cparser.value("quirks/filesubst", type=bool)
        )
        self.widgets["quirks"].song_in_path_lineedit.setText(
            self.config.cparser.value("quirks/filesubstin")
        )
        self.widgets["quirks"].song_out_path_lineedit.setText(
            self.config.cparser.value("quirks/filesubstout")
        )

        slashmode = self.config.cparser.value("quirks/slashmode") or "nochange"

        if slashmode == "nochange":
            _set_quirks_modes(True, False, False)
        elif slashmode == "toforward":
            _set_quirks_modes(False, False, True)
        elif slashmode == "toback":
            _set_quirks_modes(False, True, False)

    def _upd_win_plugins(self):
        """tell config to trigger plugins to update windows"""
        self.config.plugins_load_settingsui(self.widgets)

    def disable_web(self):
        """if the web server gets in trouble, this gets called"""
        self.refresh_ui()
        self.widgets["webserver"].enable_checkbox.setChecked(False)
        self.upd_conf()
        if self.errormessage:
            self.errormessage.showMessage("HTTP Server settings are invalid. Bad port?")

    def disable_obsws(self):
        """if the OBS WebSocket gets in trouble, this gets called"""
        self.refresh_ui()
        self.widgets["obsws"].enable_checkbox.setChecked(False)
        self.upd_conf()
        self.refresh_ui()
        if self.errormessage:
            self.errormessage.showMessage(
                "OBS WebServer settings are invalid. Bad port? Wrong password?"
            )

    def upd_conf(self):
        """update the configuration"""

        self.config.cparser.setValue(
            "settings/delay", self.widgets["general"].delay_lineedit.text()
        )
        loglevel = self.widgets["general"].logging_combobox.currentText()

        self._upd_conf_input()

        self.config.put(
            initialized=True,
            notif=self.widgets["general"].notify_checkbox.isChecked(),
            loglevel=loglevel,
        )

        logging.getLogger().setLevel(loglevel)

        self._upd_conf_external_services()
        self._upd_conf_artistextras()
        self._upd_conf_filters()
        self._upd_conf_trackskip()
        self._upd_conf_webserver()
        self._upd_conf_obsws()
        self._upd_conf_quirks()
        self._upd_conf_discordbot()
        self._upd_conf_kickbot()

        self._upd_conf_recognition()
        self._upd_conf_input()
        self._upd_conf_plugins()
        self.config.cparser.sync()

    def _upd_conf_external_services(self):
        """Update external service configurations (Twitch, Kick, etc.)"""
        for key in [
            "twitch",
            "twitchchat",
            "kick",
            "kickchat",
            "requests",
        ]:
            self.settingsclasses[key].save(self.config, self.widgets[key], self.tray.subprocesses)

    def _upd_conf_trackskip(self):
        self.config.cparser.setValue(
            "trackskip/genre", self.widgets["trackskip"].genre_lineedit.text()
        )
        self.config.cparser.setValue(
            "trackskip/comment", self.widgets["trackskip"].comment_lineedit.text()
        )

    def _upd_conf_artistextras(self):
        self.config.cparser.setValue(
            "artistextras/enabled", self.widgets["artistextras"].artistextras_checkbox.isChecked()
        )
        self.config.cparser.setValue(
            "artistextras/coverfornofanart",
            self.widgets["artistextras"].missingfanart_checkbox.isChecked(),
        )
        self.config.cparser.setValue(
            "artistextras/coverfornologos",
            self.widgets["artistextras"].missinglogos_checkbox.isChecked(),
        )
        self.config.cparser.setValue(
            "artistextras/coverfornothumbs",
            self.widgets["artistextras"].missingthumbs_checkbox.isChecked(),
        )

        for art in ["banners", "processes", "fanart", "logos", "thumbnails", "fanartdelay"]:
            guiattr = getattr(self.widgets["artistextras"], f"{art}_spin")
            self.config.cparser.setValue(f"artistextras/{art}", guiattr.value())

        current = self.widgets["artistextras"].coverart_combobox.currentText()
        self.config.cparser.setValue("artistextras/nocoverfallback", current.lower())

    def _upd_conf_recognition(self):
        self.config.cparser.setValue(
            "recognition/replacetitle", self.widgets["general"].recog_title_checkbox.isChecked()
        )
        self.config.cparser.setValue(
            "recognition/replaceartist", self.widgets["general"].recog_artist_checkbox.isChecked()
        )
        self.config.cparser.setValue(
            "recognition/replaceartistwebsites",
            self.widgets["general"].recog_artistwebsites_checkbox.isChecked(),
        )

    def _upd_conf_input(self):
        """find the text of the currently selected handler"""
        if curbutton := self.widgets["source"].sourcelist.currentItem():
            display_name = curbutton.text().lower()
            module_name = self.input_display_to_module.get(display_name, display_name)
            logging.debug(
                "Input selection: display_name='%s', module_name='%s', mapping=%s",
                display_name,
                module_name,
                self.input_display_to_module,
            )
            self.config.cparser.setValue("settings/input", module_name)

    def _upd_conf_plugins(self):
        """tell config to trigger plugins to update"""
        self.config.plugins_save_settingsui(self.widgets)

        # Handle MusicBrainz plugin separately
        if self.widgets["recognition_musicbrainz"]:
            self.settingsclasses["recognition_musicbrainz"].save_settingsui(
                self.widgets["recognition_musicbrainz"]
            )

    def _upd_conf_webserver(self):
        """update the webserver settings"""
        # Check to see if our web settings changed
        # from what we initially had.  if so
        # need to trigger the webthread to reset
        # itself.  Hitting stop makes it go through
        # the loop again

        oldenabled = self.config.cparser.value("weboutput/httpenabled", type=bool)
        oldport = self.config.cparser.value("weboutput/httpport", type=int)

        httpenabled = self.widgets["webserver"].enable_checkbox.isChecked()
        if httpporttext := self.widgets["webserver"].port_lineedit.text():
            httpport = int(httpporttext)
        else:
            httpport = 8899

        self.config.cparser.setValue("weboutput/httpenabled", httpenabled)
        self.config.cparser.setValue("weboutput/httpport", httpport)
        self.config.cparser.setValue(
            "weboutput/htmltemplate", self.widgets["webserver"].template_lineedit.text()
        )
        self.config.cparser.setValue(
            "weboutput/once", self.widgets["webserver"].once_checkbox.isChecked()
        )
        self.config.cparser.setValue(
            "remote/remote_key", self.widgets["webserver"].remote_secret_lineedit.text()
        )

        if oldenabled != httpenabled or oldport != httpport:
            self.tray.subprocesses.restart_webserver()

    def _upd_conf_obsws(self):
        """update the obsws settings"""

        oldenabled = self.config.cparser.value("obsws/enabled", type=bool)
        newenabled = self.widgets["obsws"].enable_checkbox.isChecked()

        self.config.cparser.setValue("obsws/source", self.widgets["obsws"].source_lineedit.text())
        self.config.cparser.setValue("obsws/host", self.widgets["obsws"].host_lineedit.text())
        self.config.cparser.setValue("obsws/port", self.widgets["obsws"].port_lineedit.text())
        self.config.cparser.setValue("obsws/secret", self.widgets["obsws"].secret_lineedit.text())
        self.config.cparser.setValue(
            "obsws/template", self.widgets["obsws"].template_lineedit.text()
        )
        self.config.cparser.setValue("obsws/enabled", newenabled)

        if oldenabled != newenabled:
            self.tray.subprocesses.restart_obsws()

    def _upd_conf_discordbot(self):
        """update the discord settings"""

        enabled = self.widgets["discordbot"].enable_checkbox.isChecked()

        self.config.cparser.setValue(
            "discord/clientid", self.widgets["discordbot"].clientid_lineedit.text()
        )
        self.config.cparser.setValue(
            "discord/token", self.widgets["discordbot"].token_lineedit.text()
        )
        self.config.cparser.setValue(
            "discord/template", self.widgets["discordbot"].template_lineedit.text()
        )
        self.config.cparser.setValue("discord/enabled", enabled)

    def _upd_conf_kickbot(self):
        """update the kickbot settings"""

        old_enabled = self.config.cparser.value("kick/enabled", type=bool)
        old_chat = self.config.cparser.value("kick/chat", type=bool)

        new_enabled = self.widgets["kick"].enable_checkbox.isChecked()
        new_chat = self.widgets["kickchat"].enable_checkbox.isChecked()

        # The individual settings save methods handle their own config values
        # We just need to check if the overall enable/disable state changed
        # and restart the kickbot if needed

        if (old_enabled != new_enabled) or (old_chat != new_chat):
            self.tray.subprocesses.restart_kickbot()

    def verify_regex_filters(self):
        """verify the regex filters are real"""
        widget = self.widgets["filter"].regex_list

        rowcount = widget.count()
        for row in range(rowcount):
            item = self.widgets["filter"].regex_list.item(row).text()
            try:
                re.compile(item)
            except re.error as error:
                self.errormessage.showMessage(f"Filter error with '{item}': {error.msg}")
                return False
        return True

    def _upd_conf_filters(self):
        """update the filter settings"""

        def reset_filters(widget, config):
            for configitem in config.allKeys():
                if "regex_filter/" in configitem:
                    config.remove(configitem)

            rowcount = widget.count()
            for row in range(rowcount):
                item = widget.item(row)
                config.setValue(f"regex_filter/{row}", item.text())

        if not self.verify_regex_filters():
            return

        self.config.cparser.setValue(
            "settings/stripextras", self.widgets["filter"].stripextras_checkbox.isChecked()
        )
        reset_filters(self.widgets["filter"].regex_list, self.config.cparser)

    def _upd_conf_quirks(self):
        """update the quirks settings to match config"""

        # file system notification method
        self.config.cparser.value(
            "quirks/pollingobserver", self.widgets["quirks"].fs_poll_button.isChecked()
        )

        # s,in,out,g
        self.config.cparser.setValue(
            "quirks/filesubst", self.widgets["quirks"].song_subst_checkbox.isChecked()
        )

        if self.widgets["quirks"].slash_toback.isChecked():
            self.config.cparser.setValue("quirks/slashmode", "toback")
        if self.widgets["quirks"].slash_toforward.isChecked():
            self.config.cparser.setValue("quirks/slashmode", "toforward")
        if self.widgets["quirks"].slash_nochange.isChecked():
            self.config.cparser.setValue("quirks/slashmode", "nochange")

        self.config.cparser.setValue(
            "quirks/filesubstin", self.widgets["quirks"].song_in_path_lineedit.text()
        )
        self.config.cparser.setValue(
            "quirks/filesubstout", self.widgets["quirks"].song_out_path_lineedit.text()
        )

    @Slot()
    def fresh_start(self):
        """trigger a fresh start"""
        if self.widgets["destroy"].areyousure_checkbox.isChecked():
            self.tray.fresh_start_quit()

    @Slot()
    def on_artistextras_clearcache_button(self):
        """clear the cache button was pushed"""
        # Clear image cache
        cachedbfile = self.config.cparser.value("artistextras/cachedbfile")
        if cachedbfile:
            cachedbfilepath = pathlib.Path(cachedbfile)
            if cachedbfilepath.exists() and "imagecache" in str(cachedbfile):
                logging.debug("Deleting image cache: %s", cachedbfilepath)
                cachedbfilepath.unlink()

        # Clear API cache
        api_cache_dir = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.StandardLocation.CacheLocation)[0]
        ).joinpath("api_cache")
        api_cache_file = api_cache_dir / "api_responses.db"
        if api_cache_file.exists():
            logging.debug("Deleting API cache: %s", api_cache_file)
            api_cache_file.unlink()

    @Slot()
    def on_discordbot_template_button(self):
        """discordbot template button clicked action"""
        if self.uihelp:
            self.uihelp.template_picker_lineedit(self.widgets["discordbot"].template_lineedit)

    @Slot()
    def on_obsws_template_button(self):
        """obsws template button clicked action"""
        if self.uihelp:
            self.uihelp.template_picker_lineedit(self.widgets["obsws"].template_lineedit)

    @Slot()
    def on_html_template_button(self):
        """html template button clicked action"""
        if self.uihelp:
            self.uihelp.template_picker_lineedit(
                self.widgets["webserver"].template_lineedit, limit="*.htm *.html"
            )

    def _filter_regex_load(self, regex=None):
        """setup the filter table"""
        regexitem = QListWidgetItem()
        if regex:
            regexitem.setText(regex)
        regexitem.setFlags(
            Qt.ItemIsEditable
            | Qt.ItemIsEnabled
            | Qt.ItemIsDragEnabled
            | Qt.ItemIsSelectable
            | Qt.ItemIsUserCheckable
        )
        self.widgets["filter"].regex_list.addItem(regexitem)

    @Slot()
    def on_filter_regex_add_button(self):
        """filter add button clicked action"""
        self._filter_regex_load("new")

    @Slot()
    def on_filter_regex_del_button(self):
        """filter del button clicked action"""
        if items := self.widgets["filter"].regex_list.selectedItems():
            for item in items:
                self.widgets["filter"].regex_list.takeItem(
                    self.widgets["filter"].regex_list.row(item)
                )

    @Slot()
    def on_filter_test_button(self):
        """filter add button clicked action"""

        if not self.verify_regex_filters():
            return

        title = self.widgets["filter"].test_lineedit.text()
        striprelist = []
        rowcount = self.widgets["filter"].regex_list.count()
        for row in range(rowcount):
            item = self.widgets["filter"].regex_list.item(row).text()
            striprelist.append(re.compile(item))
        result = nowplaying.utils.titlestripper_advanced(title=title, title_regex_list=striprelist)
        self.widgets["filter"].result_label.setText(result)
        result = nowplaying.utils.titlestripper_advanced(
            title=title, title_regex_list=self.config.getregexlist()
        )
        self.widgets["filter"].existing_label.setText(result)
        self.widgets["filter"].result_label.update()

    @Slot()
    def on_filter_add_recommended_button(self):
        """load some recommended settings"""
        stripworldlist = ["clean", "dirty", "explicit", "official music video"]
        joinlist = "|".join(stripworldlist)

        self._filter_regex_load(f" \\((?i:{joinlist})\\)")
        self._filter_regex_load(f" - (?i:{joinlist}$)")
        self._filter_regex_load(f" \\[(?i:{joinlist})\\]")

    @Slot()
    def on_cancel_button(self):
        """cancel button clicked action"""
        self._cleanup_settings_classes()
        if self.tray:
            self.tray.settings_action.setEnabled(True)
        self.refresh_ui()
        if self.qtui:
            self.qtui.close()

        if (
            not self.config.cparser.value("settings/input", defaultValue=None)
            or not self.config.initialized
        ):
            self.tray.cleanquit()

    @Slot()
    def on_reset_button(self):
        """cancel button clicked action"""
        self.config.reset()
        SettingsUI.httpenabled = self.config.cparser.value("weboutput/httpenabled", type=bool)
        SettingsUI.httpport = self.config.cparser.value("weboutput/httpport", type=int)
        self.refresh_ui()

    @Slot()
    def on_save_button(self):
        """save button clicked action"""
        inputtext = None
        if curbutton := self.widgets["source"].sourcelist.currentItem():
            inputtext = curbutton.text().lower()

        if not inputtext:
            if self.errormessage:
                self.errormessage.showMessage("No source has been chosen")
            return

        try:
            self.config.plugins_verify_settingsui(inputtext, self.widgets)

            # Handle MusicBrainz plugin separately
            if self.widgets["recognition_musicbrainz"]:
                self.settingsclasses["recognition_musicbrainz"].verify_settingsui(
                    self.widgets["recognition_musicbrainz"]
                )
        except PluginVerifyError as error:
            if self.errormessage:
                self.errormessage.showMessage(error.message)
            return

        if not self.widgets["source"].sourcelist.currentItem():
            if self.errormessage:
                self.errormessage.showMessage("File to write is required")
            return

        if not self.verify_regex_filters():
            return

        for key in [
            "twitch",
            "twitchchat",
            "kick",
            "kickchat",
            "requests",
        ]:
            try:
                self.settingsclasses[key].verify(self.widgets[key])
            except PluginVerifyError as error:
                if self.errormessage:
                    self.errormessage.showMessage(error.message)
                return

        self.config.unpause()
        self.upd_conf()
        self.close()
        self.tray.fix_mixmode_menu()
        self.tray.action_pause.setText("Pause")
        self.tray.action_pause.setEnabled(True)

    def show(self):
        """show the system tray"""
        if self.tray:
            self.tray.settings_action.setEnabled(False)
        if self.qtui:
            self.qtui.show()
            self.qtui.setFocus()
        # UI is already populated during initialization, no need to update on show
        # Only update if UI hasn't been populated yet (fallback)
        if not self.ui_populated:
            self.upd_win()
            self.ui_populated = True

    def refresh_ui(self):
        """Refresh the UI when config has actually changed"""
        self.upd_win()
        self.ui_populated = True

    def _cleanup_settings_classes(self):
        """Clean up resources from settings classes when UI is closed"""
        for settings_class in self.settingsclasses.values():
            if hasattr(settings_class, "cleanup"):
                try:
                    settings_class.cleanup()
                except Exception as error:  # pylint: disable=broad-exception-caught
                    logging.error(
                        "Error cleaning up settings class %s: %s",
                        type(settings_class).__name__,
                        error,
                    )

    def close(self):
        """close the system tray"""
        self._cleanup_settings_classes()
        self.tray.settings_action.setEnabled(True)
        if self.qtui:
            self.qtui.hide()

    def exit(self):
        """exit the tray"""
        self._cleanup_settings_classes()
        if self.qtui:
            self.qtui.close()

    def closeEvent(self, event):  # pylint: disable=invalid-name
        """Handle window close event (X button)"""
        self._cleanup_settings_classes()
        super().closeEvent(event)

    @Slot()
    def on_export_config_button(self):
        """handle export configuration button"""
        try:
            # Get save file path from user
            suggested_name = f"nowplaying_config_{self.config.version.replace('.', '_')}.json"
            default_dir = QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0]

            file_path = self.uihelp.save_file_picker(
                title="Export Configuration",
                startdir=os.path.join(default_dir, suggested_name),
                filter_str="JSON Files (*.json);;All Files (*)",
            )

            if file_path:
                export_path = pathlib.Path(file_path)
                if self.config.export_config(export_path):
                    QMessageBox.information(
                        self.qtui,
                        "Export Successful",
                        f"Configuration exported to:\n{export_path}\n\n"
                        "⚠️ WARNING: This file contains sensitive data including API keys "
                        "and passwords. Store it securely and do not share it.",
                    )
                else:
                    QMessageBox.critical(
                        self.qtui,
                        "Export Failed",
                        "Failed to export configuration. Check the logs for details.",
                    )
        except (OSError, PermissionError, FileNotFoundError) as error:
            logging.error("Export configuration error: %s", error)
            QMessageBox.critical(self.qtui, "Export Error", f"An error occurred: {error}")

    @Slot()
    def on_import_config_button(self):
        """handle import configuration button"""
        try:
            # Confirm with user since this overwrites settings
            reply = QMessageBox.question(
                self.qtui,
                "Import Configuration",
                "This will overwrite your current settings with those from the imported file.\n\n"
                "Are you sure you want to continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if reply != QMessageBox.Yes:
                return

            # Get file path from user
            default_dir = QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0]

            file_path, _ = QFileDialog.getOpenFileName(
                self.qtui,
                "Import Configuration",
                default_dir,
                "JSON Files (*.json);;All Files (*)",
            )

            if file_path:
                import_path = pathlib.Path(file_path)
                if self.config.import_config(import_path):
                    QMessageBox.information(
                        self.qtui,
                        "Import Successful",
                        f"Configuration imported from:\n{import_path}\n\n"
                        "The application may need to be restarted for all changes to take effect.",
                    )
                    # Refresh the UI to show imported settings
                    self.load_ui()
                else:
                    QMessageBox.critical(
                        self.qtui,
                        "Import Failed",
                        "Failed to import configuration. Check the logs for details.",
                    )
        except (OSError, PermissionError, FileNotFoundError, json.JSONDecodeError) as error:
            logging.error("Import configuration error: %s", error)
            QMessageBox.critical(self.qtui, "Import Error", f"An error occurred: {error}")


def about_version_text(config, qwidget):
    """set the version text for about box"""
    qwidget.program_label.setText(
        '<html><head/><body><p align="center"><span style=" font-size:24pt; font-weight:700;">'
        f"What's Now Playing v{config.version}</span></p></body></html>"
    )


def load_widget_ui(config, name):
    """load a UI file into a widget, supporting both single files and tabbed interfaces"""

    # First try to load single UI file (existing behavior)
    single_path = config.uidir.joinpath(f"{name}_ui.ui")
    if single_path.exists():
        return _load_single_ui_file(single_path, name)

    # If single file doesn't exist, try to find tabbed UI files
    tab_files = _find_tab_ui_files(config.uidir, name)
    if tab_files:
        return _load_tabbed_ui_files(tab_files, name)

    # Neither single nor tabbed files found
    return None


def _load_single_ui_file(path, name):
    """Load a single UI file"""
    loader = QUiLoader()
    ui_file = QFile(str(path))
    ui_file.open(QFile.ReadOnly)
    try:
        qwidget = loader.load(ui_file)
    except RuntimeError as error:
        logging.warning("Unable to load the UI for %s: %s", name, error)
        return None
    ui_file.close()
    return qwidget


def _find_tab_ui_files(uidir, name):
    """Find all tab UI files for a given plugin name"""

    pattern = str(uidir.joinpath(f"{name}_*_ui.ui"))
    tab_files = glob.glob(pattern)

    if not tab_files:
        return []

    # Sort by filename to ensure consistent tab order
    tab_files.sort()

    # Extract tab names from filenames for logging
    tab_names = []
    for filepath in tab_files:
        filename = pathlib.Path(filepath).stem  # e.g., "inputs_serato_connection_ui"
        # Extract tab name: inputs_serato_connection_ui -> connection
        parts = filename.split("_")
        if len(parts) >= 3 and parts[-1] == "ui":
            tab_name = "_".join(parts[2:-1])  # Everything between plugin name and 'ui'
            tab_names.append(tab_name)
        else:
            tab_names.append(f"tab_{len(tab_names)}")

    logging.debug("Found tab UI files for %s: %s", name, tab_names)
    return list(zip(tab_files, tab_names))


def _load_tabbed_ui_files(tab_files, name):
    """Load multiple tab UI files into a QTabWidget"""
    tab_widget = QTabWidget()
    loader = QUiLoader()

    for filepath, tab_name in tab_files:
        ui_file = QFile(filepath)
        ui_file.open(QFile.ReadOnly)
        try:
            if tab_content := loader.load(ui_file):
                # Use the tab name from filename, but could be overridden by windowTitle in XML
                display_name = (
                    tab_content.windowTitle()
                    if hasattr(tab_content, "windowTitle") and tab_content.windowTitle()
                    else tab_name.replace("_", " ").title()
                )
                tab_widget.addTab(tab_content, display_name)
                logging.debug("Added tab '%s' for %s from %s", display_name, name, filepath)
        except RuntimeError as error:
            logging.warning("Unable to load tab UI file %s for %s: %s", filepath, name, error)
        finally:
            ui_file.close()

    if tab_widget.count() == 0:
        logging.warning("No valid tab UI files loaded for %s", name)
        return None

    logging.info("Loaded %d tabs for %s", tab_widget.count(), name)
    return tab_widget
