#!/usr/bin/env python3
"""
config file parsing/handling
"""

import contextlib
import json
import logging
import os
import pathlib
import re
import ssl
import sys
import time
from types import ModuleType

from PySide6.QtCore import (  # pylint: disable=no-name-in-module
    QCoreApplication,
    QSettings,
    QStandardPaths,
)
from PySide6.QtWidgets import QWidget  # pylint: disable=no-name-in-module

import nowplaying.artistextras
import nowplaying.inputs
import nowplaying.notifications
import nowplaying.pluginimporter
import nowplaying.recognition

# IMPORTANT: Import compatibility shim FIRST to handle old AuthScope enums in Qt config
import nowplaying.twitch.compat
import nowplaying.types
import nowplaying.version  # pylint: disable=no-name-in-module,import-error


class ConfigFile:  # pylint: disable=too-many-instance-attributes, too-many-public-methods
    """read and write to config.ini"""

    BUNDLEDIR: pathlib.Path | None = None

    def __init__(  # pylint: disable=too-many-arguments
        self,
        bundledir: str | pathlib.Path | None = None,
        logpath: str | None = None,
        reset: bool = False,
        testmode: bool = False,
    ):
        self.version: str = nowplaying.version.__VERSION__  # pylint: disable=no-member
        self.testmode: bool = testmode
        self.userdocs: pathlib.Path = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0]
        )
        self.basedir: pathlib.Path = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
            QCoreApplication.applicationName(),
        )
        self.initialized: bool = False
        self.logpath: pathlib.Path = self.basedir.joinpath("logs", "debug.log")
        if logpath:
            self.logpath = pathlib.Path(logpath)

        self.templatedir: pathlib.Path = self.basedir.joinpath("templates")

        if not ConfigFile.BUNDLEDIR and bundledir:
            ConfigFile.BUNDLEDIR = pathlib.Path(bundledir)

        logging.info("Logpath: %s", self.logpath)
        logging.info("Templates: %s", self.templatedir)
        logging.info("Bundle: %s", ConfigFile.BUNDLEDIR)
        logging.debug("SSL_CERT_FILE=%s", os.environ.get("SSL_CERT_FILE"))
        logging.debug("SSL CA FILE=%s", ssl.get_default_verify_paths().cafile)

        self.qsettingsformat: QSettings.Format = QSettings.NativeFormat
        if sys.platform == "win32":
            self.qsettingsformat = QSettings.IniFormat

        self.cparser: QSettings = QSettings(
            self.qsettingsformat,
            QSettings.UserScope,
            QCoreApplication.organizationName(),
            QCoreApplication.applicationName(),
        )
        logging.info("configuration: %s", self.cparser.fileName())
        self.notif: bool = False
        self.txttemplate: str = str(self.templatedir.joinpath("basic-plain.txt"))
        self.loglevel: str = "DEBUG"

        self.plugins: dict[str, dict[str, ModuleType]] = {}
        self.pluginobjs: nowplaying.types.PluginObjs = {
            "inputs": {},
            "artistextras": {},
            "notifications": {},
            "recognition": {},
        }

        self._force_set_statics()

        self._initial_plugins()

        self.defaults()
        if reset:
            # Preserve charts key across reset
            charts_key = self.cparser.value("charts/charts_key", defaultValue="")
            self.cparser.clear()
            self._force_set_statics()
            # Restore charts key if it existed
            if charts_key:
                self.cparser.setValue("charts/charts_key", charts_key)
                logging.info("Preserved charts key across configuration reset")
            self.save()
        else:
            self.get()

        self.iconfile: pathlib.Path | None = self.find_icon_file()
        self.uidir: pathlib.Path | None = self.find_ui_file()
        self.lastloaddate: int = 0
        self.setlistdir: str | None = None
        self.striprelist: list[re.Pattern[str]] = []
        self.testdir: pathlib.Path | None = None

    def _force_set_statics(self) -> None:
        """make sure these are always set"""
        if self.testmode:
            self.cparser.setValue("testmode/enabled", True)

    def reset(self) -> None:
        """forcibly go back to defaults"""
        logging.debug("config reset")
        self.__init__(bundledir=ConfigFile.BUNDLEDIR, reset=True)  # pylint: disable=unnecessary-dunder-call

    def get(self) -> None:
        """refresh values"""

        self.cparser.sync()
        with contextlib.suppress(TypeError):
            self.loglevel = self.cparser.value("settings/loglevel")

        with contextlib.suppress(TypeError):
            self.notif = self.cparser.value("settings/notif", type=bool)
        self.txttemplate = self.cparser.value("textoutput/txttemplate", defaultValue=None)

        with contextlib.suppress(TypeError):
            self.initialized = self.cparser.value("settings/initialized", type=bool)

    def validate_source(self, plugin: str) -> ModuleType | None:
        """verify the source input"""
        return self.plugins["inputs"].get(f"nowplaying.inputs.{plugin}")

    def defaults(self) -> None:
        """default values for things"""
        logging.debug("set defaults")

        settings = QSettings(
            self.qsettingsformat,
            QSettings.SystemScope,
            QCoreApplication.organizationName(),
            QCoreApplication.applicationName(),
        )

        self._defaults_artistextras(settings)
        self._defaults_recognition(settings)
        self._defaults_general_settings(settings)
        self._defaults_output(settings)
        self._defaults_chat_services(settings)
        self._defaults_quirks(settings)
        self._defaults_requests(settings)
        self._defaults_plugins(settings)

    def _initial_plugins(self) -> None:
        self.plugins["inputs"] = nowplaying.pluginimporter.import_plugins(nowplaying.inputs)
        self.pluginobjs["inputs"] = {}
        self.plugins["recognition"] = nowplaying.pluginimporter.import_plugins(
            nowplaying.recognition
        )
        self.pluginobjs["recognition"] = {}

        self.plugins["artistextras"] = nowplaying.pluginimporter.import_plugins(
            nowplaying.artistextras
        )
        self.pluginobjs["artistextras"] = {}

        self.plugins["notifications"] = nowplaying.pluginimporter.import_plugins(
            nowplaying.notifications
        )
        self.pluginobjs["notifications"] = {}

    @staticmethod
    def _defaults_artistextras(settings: QSettings) -> None:
        """default values for artist extras"""
        settings.setValue("artistextras/enabled", True)
        for field in ["banners", "logos", "thumbnails"]:
            settings.setValue(f"artistextras/{field}", 2)

        settings.setValue("musicbrainz/enabled", True)
        settings.setValue("musicbrainz/fallback", True)

        settings.setValue("artistextras/fanart", 10)
        settings.setValue("artistextras/processes", 5)
        settings.setValue("artistextras/cachesize", 5)
        settings.setValue("artistextras/fanartdelay", 8)
        settings.setValue("artistextras/coverfornofanart", True)
        settings.setValue("artistextras/coverfornologos", False)
        settings.setValue("artistextras/coverfornothumbs", True)
        settings.setValue("artistextras/nocoverfallback", "none")

    @staticmethod
    def _defaults_recognition(settings: QSettings) -> None:
        """default values for recognition"""
        settings.setValue("recognition/replacetitle", False)
        settings.setValue("recognition/replaceartist", False)
        settings.setValue("setlist/enabled", False)

    def _defaults_general_settings(self, settings: QSettings) -> None:
        """default values for general settings"""
        settings.setValue("settings/delay", "1.0")
        settings.setValue("settings/initialized", False)
        settings.setValue("settings/loglevel", self.loglevel)
        settings.setValue("settings/notif", self.notif)
        settings.setValue("settings/stripextras", False)

    def _defaults_output(self, settings: QSettings) -> None:
        """default values for output settings"""
        settings.setValue("textoutput/file", None)
        settings.setValue("textoutput/txttemplate", self.txttemplate)
        settings.setValue("textoutput/clearonstartup", True)
        settings.setValue("textoutput/fileappend", False)

        settings.setValue("obsws/enabled", False)
        settings.setValue("obsws/host", "localhost")
        settings.setValue("obsws/port", "4455")
        settings.setValue("obsws/secret", "")
        settings.setValue("obsws/source", "")
        settings.setValue("obsws/template", str(self.templatedir.joinpath("basic-plain.txt")))

        settings.setValue(
            "weboutput/htmltemplate", str(self.templatedir.joinpath("basic-web.htm"))
        )
        settings.setValue(
            "weboutput/artistbannertemplate",
            str(self.templatedir.joinpath("ws-artistbanner-nofade.htm")),
        )
        settings.setValue(
            "weboutput/artistlogotemplate",
            str(self.templatedir.joinpath("ws-artistlogo-nofade.htm")),
        )
        settings.setValue(
            "weboutput/artistthumbnailtemplate",
            str(self.templatedir.joinpath("ws-artistthumb-nofade.htm")),
        )
        settings.setValue(
            "weboutput/artistfanarttemplate",
            str(self.templatedir.joinpath("ws-artistfanart-nofade.htm")),
        )
        settings.setValue(
            "weboutput/gifwordstemplate", str(self.templatedir.joinpath("ws-gifwords-fade.htm"))
        )
        settings.setValue(
            "weboutput/requestertemplate", str(self.templatedir.joinpath("ws-requests.htm"))
        )
        settings.setValue("weboutput/httpenabled", True)
        settings.setValue("weboutput/httpport", "8899")
        settings.setValue("weboutput/once", True)

    def _defaults_chat_services(self, settings: QSettings) -> None:
        """default values for chat services"""
        settings.setValue("twitchbot/enabled", False)
        settings.setValue("kick/enabled", False)
        settings.setValue("kick/chat", False)
        settings.setValue("kick/announce", str(self.templatedir.joinpath("kickbot_track.txt")))
        settings.setValue("kick/announcedelay", 1.0)

    @staticmethod
    def _defaults_quirks(settings: QSettings) -> None:
        """default values for quirks"""
        settings.setValue("quirks/pollingobserver", False)
        settings.setValue("quirks/pollinginterval", 5.0)
        settings.setValue("quirks/filesubst", False)
        settings.setValue("quirks/slashmode", "nochange")

    @staticmethod
    def _defaults_requests(settings: QSettings) -> None:
        """default values for requests"""
        settings.setValue("request-0/command", "request")
        settings.setValue("request-0/twitchtext", "")
        settings.setValue("request-0/type", "Generic")
        settings.setValue("request-0/displayname", "Song Request")
        settings.setValue("request-0/playlist", "")

        settings.setValue("request-1/command", "hasartist")
        settings.setValue("request-1/twitchtext", "")
        settings.setValue("request-1/type", "ArtistQuery")
        settings.setValue("request-1/displayname", "Artist Library Check")
        settings.setValue("request-1/playlist", "")

    def _defaults_plugins(self, settings: QSettings) -> None:
        """configure the defaults for plugins"""
        self.pluginobjs = {}
        for plugintype, plugtypelist in self.plugins.items():
            self.pluginobjs[plugintype] = {}
            removelist = []
            for key in plugtypelist:
                self.pluginobjs[plugintype][key] = self.plugins[plugintype][key].Plugin(
                    config=self, qsettings=settings
                )
                if self.testmode or self.pluginobjs[plugintype][key].available:
                    self.pluginobjs[plugintype][key].defaults(settings)
                else:
                    removelist.append(key)
            for key in removelist:
                del self.pluginobjs[plugintype][key]
                del self.plugins[plugintype][key]

    def plugins_connect_settingsui(self, qtwidgets: dict[str, QWidget], uihelp: object) -> None:
        """configure the defaults for plugins"""
        # qtwidgets = list of qtwidgets, identified as [plugintype_pluginname]
        for plugintype, plugtypelist in self.plugins.items():
            for key in plugtypelist:
                widgetkey = key.split(".")[-1]
                self.pluginobjs[plugintype][key].connect_settingsui(
                    qtwidgets[f"{plugintype}_{widgetkey}"], uihelp
                )

    def plugins_load_settingsui(self, qtwidgets: dict[str, QWidget]) -> None:
        """configure the defaults for plugins"""
        for plugintype, plugtypelist in self.plugins.items():
            for key in plugtypelist:
                widgetkey = key.split(".")[-1]
                if qtwidgets[f"{plugintype}_{widgetkey}"]:
                    self.pluginobjs[plugintype][key].load_settingsui(
                        qtwidgets[f"{plugintype}_{widgetkey}"]
                    )

    def plugins_verify_settingsui(self, inputname: str, qtwidgets: dict[str, QWidget]) -> None:
        """configure the defaults for plugins"""
        for plugintype, plugtypelist in self.plugins.items():
            for key in plugtypelist:
                widgetkey = key.split(".")[-1]
                if (
                    (widgetkey == inputname and plugintype == "inputs")
                    or (plugintype != "inputs")
                    and qtwidgets[f"{plugintype}_{widgetkey}"]
                ):
                    self.pluginobjs[plugintype][key].verify_settingsui(
                        qtwidgets[f"{plugintype}_{widgetkey}"]
                    )

    def plugins_save_settingsui(self, qtwidgets: dict[str, QWidget]) -> None:
        """configure the defaults for input plugins"""
        for plugintype, plugtypelist in self.plugins.items():
            for key in plugtypelist:
                widgetkey = key.split(".")[-1]
                if qtwidgets[f"{plugintype}_{widgetkey}"]:
                    self.pluginobjs[plugintype][key].save_settingsui(
                        qtwidgets[f"{plugintype}_{widgetkey}"]
                    )

    def plugins_description(self, plugintype: str, plugin: str, qtwidget: QWidget) -> None:
        """configure the defaults for input plugins"""
        if qtwidget:
            self.pluginobjs[plugintype][f"nowplaying.{plugintype}.{plugin}"].desc_settingsui(
                qtwidget
            )

    # pylint: disable=too-many-arguments
    def put(self, initialized: bool, notif: bool, loglevel: str) -> None:
        """Save the configuration file"""

        self.initialized = initialized
        self.loglevel = loglevel
        self.notif = notif

        self.save()

    def save(self) -> None:
        """save the current set"""

        self.cparser.setValue("settings/initialized", self.initialized)
        self.cparser.setValue("settings/lastsavedate", time.strftime("%Y%m%d%H%M%S"))
        self.cparser.setValue("settings/loglevel", self.loglevel)
        self.cparser.setValue("settings/notif", self.notif)

        self.cparser.sync()

    def find_icon_file(self) -> pathlib.Path | None:
        """try to find our icon"""

        if not ConfigFile.BUNDLEDIR:
            logging.error("bundledir not set in config")
            return None

        for testdir in [
            ConfigFile.BUNDLEDIR,
            ConfigFile.BUNDLEDIR.joinpath("bin"),
            ConfigFile.BUNDLEDIR.joinpath("resources"),
        ]:
            for testfilename in ["icon.ico", "windows.ico"]:
                testfile = testdir.joinpath(testfilename)
                if testfile.exists():
                    logging.debug("iconfile at %s", testfile)
                    return testfile

        if not self.testmode:
            self.testmode = self.cparser.value("testmode/enabled")

        if not self.testmode:
            logging.error("Unable to find the icon file. Death only follows.")
        return None

    def find_ui_file(self) -> pathlib.Path | None:
        """try to find our icon"""

        if not ConfigFile.BUNDLEDIR:
            logging.error("bundledir not set in config")
            return None

        for testdir in [
            ConfigFile.BUNDLEDIR,
            ConfigFile.BUNDLEDIR.joinpath("bin"),
            ConfigFile.BUNDLEDIR.joinpath("resources"),
        ]:
            testfile = testdir.joinpath("settings_ui.ui")
            if testfile.exists():
                logging.debug("ui file at %s", testfile)
                return testdir

        if not self.testmode:
            self.testmode = self.cparser.value("testmode/enabled")

        if not self.testmode:
            logging.error("Unable to find the ui dir. Death only follows.")
        return None

    def pause(self) -> None:
        """Pause system"""
        self.cparser.setValue("control/paused", True)
        logging.warning("NowPlaying is currently paused.")

    def unpause(self) -> None:
        """unpause system"""
        self.cparser.setValue("control/paused", False)
        logging.warning("NowPlaying is no longer paused.")

    def getpause(self) -> bool | None:
        """Get the pause status"""
        return self.cparser.value("control/paused", type=bool)

    def validmixmodes(self) -> list[str]:
        """get valid mixmodes"""
        plugin = self.cparser.value("settings/input")
        inputplugin = self.plugins["inputs"][f"nowplaying.inputs.{plugin}"].Plugin(config=self)
        return inputplugin.validmixmodes()

    def setmixmode(self, mixmode: str) -> str:
        """set the mixmode by calling the plugin"""

        plugin = self.cparser.value("settings/input")
        inputplugin = self.plugins["inputs"][f"nowplaying.inputs.{plugin}"].Plugin(config=self)
        return inputplugin.setmixmode(mixmode)

    def getmixmode(self) -> str:
        """get current mix mode"""
        plugin = self.cparser.value("settings/input")
        inputplugin = self.plugins["inputs"][f"nowplaying.inputs.{plugin}"].Plugin(config=self)
        return inputplugin.getmixmode()

    @staticmethod
    def getbundledir() -> pathlib.Path | None:
        """get the bundle dir"""
        return ConfigFile.BUNDLEDIR

    def getsetlistdir(self) -> str:
        """get the setlist directory"""
        if not self.setlistdir:
            self.setlistdir = os.path.join(
                QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
                QCoreApplication.applicationName(),
                "setlists",
            )
        return self.setlistdir

    def getregexlist(self) -> list[re.Pattern[str]]:
        """get the regex title filter"""
        try:
            if self.lastloaddate == 0 or self.lastloaddate < (
                self.cparser.value("settings/lastsavedate", type=int) or 0
            ):
                self.striprelist = [
                    re.compile(self.cparser.value(configitem))
                    for configitem in self.cparser.allKeys()
                    if "regex_filter/" in configitem
                ]
                self.lastloaddate = self.cparser.value("settings/lastsavedate", type=int)
        except re.error as error:
            logging.error("Filter error with '%s': %s", error.pattern, error.msg)
        return self.striprelist

    def export_config(self, export_path: pathlib.Path) -> bool:
        """
        Export configuration to JSON file.

        WARNING: Exported file contains sensitive data including API keys,
        tokens, passwords, and system paths. Store securely and do not share.

        Args:
            export_path: Path where to save the exported configuration

        Returns:
            True if export successful, False otherwise
        """
        try:
            # Sync to ensure we have latest settings
            self.cparser.sync()

            # Use childGroups() and childKeys() to avoid system preferences contamination
            # that can occur with allKeys() on macOS
            config_data = {}

            # Settings to exclude from export
            exclude_patterns = [
                "settings/initialized",
                "settings/lastsavedate",
                "control/paused",
                "testmode/",
                # Cache-related settings that should be rebuilt
                "cache/",
                "db/",
                "artistextras/cachedbfile",  # Cache file paths should be rebuilt
            ]

            # Get keys from each configuration group (avoids system preferences)
            for group in self.cparser.childGroups():
                self.cparser.beginGroup(group)
                group_keys = self.cparser.childKeys()

                for key in group_keys:
                    full_key = f"{group}/{key}"

                    # Skip excluded settings
                    if any(full_key.startswith(pattern) for pattern in exclude_patterns):
                        continue

                    value = self.cparser.value(key)

                    # Convert QSettings types to JSON-serializable types
                    if (
                        isinstance(value, bool)
                        or value is not None
                        and isinstance(value, (int, float, str))
                    ):
                        pass  # bools are fine
                    elif value is None:
                        value = None
                    elif isinstance(value, list):
                        # Convert list items to strings
                        value = [str(item) for item in value]
                    else:
                        # Convert everything else to string
                        value = str(value)

                    config_data[full_key] = value

                self.cparser.endGroup()

            # Add metadata about the export
            export_metadata = {
                "_export_info": {
                    "version": self.version,
                    "export_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "application": QCoreApplication.applicationName(),
                    "organization": QCoreApplication.organizationName(),
                    "warning": "This file contains sensitive data including API keys and passwords",
                }
            }

            # Combine metadata and config
            full_export = export_metadata | config_data

            # Write to file with restrictive permissions
            _ = export_path.write_text(json.dumps(full_export, indent=2, sort_keys=True))

            # Set restrictive file permissions (user read/write only)
            # On Windows, this may not work as expected but won't fail
            try:
                export_path.chmod(0o600)
            except (OSError, NotImplementedError):
                # Windows may not support Unix-style permissions, but file is still created
                logging.debug("Could not set restrictive file permissions (platform limitation)")

            logging.info("Configuration exported to: %s", export_path)
            return True

        except (OSError, TypeError, ValueError) as error:
            logging.error("Failed to export configuration: %s", error)
            return False

    def import_config(self, import_path: pathlib.Path) -> bool:
        """
        Import configuration from JSON file.

        This will overwrite current settings with imported values.
        Runtime state and cache settings are automatically excluded.

        Args:
            import_path: Path to the JSON configuration file

        Returns:
            True if import successful, False otherwise
        """
        try:
            if not import_path.exists():
                logging.error("Import file does not exist: %s", import_path)
                return False

            # Load the JSON data
            import_data = json.loads(import_path.read_text())

            # Check if this looks like a valid export
            if "_export_info" not in import_data:
                logging.warning("Import file may not be a valid configuration export")

            # Log import info
            if "_export_info" in import_data:
                export_info = import_data["_export_info"]
                logging.info(
                    "Importing config from version %s, exported on %s",
                    export_info.get("version", "unknown"),
                    export_info.get("export_date", "unknown"),
                )
                # Remove metadata before processing
                del import_data["_export_info"]

            # Clear cache and runtime settings before import
            cache_patterns = [
                "settings/initialized",
                "settings/lastsavedate",
                "control/paused",
                "testmode/",
                "cache/",
                "db/",
            ]

            for pattern in cache_patterns:
                keys_to_remove = [key for key in self.cparser.allKeys() if key.startswith(pattern)]
                for key in keys_to_remove:
                    self.cparser.remove(key)

            # Import all settings from the file
            for key, value in import_data.items():
                self.cparser.setValue(key, value)

            # Sync and refresh our internal state
            self.cparser.sync()
            self.get()  # Refresh internal variables

            logging.info("Configuration imported successfully from: %s", import_path)
            return True

        except json.JSONDecodeError as error:
            logging.error("Invalid JSON in import file: %s", error)
            return False
        except (OSError, KeyError, ValueError) as error:
            logging.error("Failed to import configuration: %s", error)
            return False
