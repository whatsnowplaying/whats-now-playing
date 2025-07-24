#!/usr/bin/env python3
"""Configuration upgrade logic"""

import contextlib
import logging
import pathlib
import shutil
import sys
import time

from PySide6.QtCore import (  # pylint: disable=no-name-in-module
    QCoreApplication,
    QSettings,
    QStandardPaths,
)
from PySide6.QtWidgets import QMessageBox  # pylint: disable=no-name-in-module

import nowplaying.trackrequests
import nowplaying.version  # pylint: disable=import-error, no-name-in-module

from . import Version


class UpgradeConfig:
    """methods to upgrade from old configs to new configs"""

    def __init__(self, testdir: str | pathlib.Path | None = None):
        if sys.platform == "win32":
            self.qsettingsformat = QSettings.IniFormat
        else:
            self.qsettingsformat = QSettings.NativeFormat

        self.testdir = testdir
        self.upgrade()

    def _getconfig(self) -> QSettings:
        return QSettings(
            self.qsettingsformat,
            QSettings.UserScope,
            QCoreApplication.organizationName(),
            QCoreApplication.applicationName(),
        )

    def backup_config(self) -> None:
        """back up the old config"""
        config = self._getconfig()
        source = config.fileName()
        datestr = time.strftime("%Y%m%d-%H%M%S")
        if self.testdir:
            docpath = self.testdir
        else:  # pragma: no cover
            docpath = QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0]
        backupdir = pathlib.Path(docpath).joinpath(
            QCoreApplication.applicationName(), "configbackup"
        )

        logging.info("Making a backup of config prior to upgrade: %s", backupdir)
        try:
            pathlib.Path(backupdir).mkdir(parents=True, exist_ok=True)
            backup = backupdir.joinpath(f"{datestr}-config.bak")
            shutil.copyfile(source, backup)
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Failed to make a backup: %s", error)
            sys.exit(0)

    def upgrade(self) -> None:
        """variable re-mapping"""
        config = self._getconfig()

        mapping = {
            "acoustidmb/emailaddress": "musicbrainz/emailaddress",
            "acoustidmb/enabled": "musicbrainz/enabled",
            "twitchbot/enabled": "twitchbot/chat",
            "twitchbot/token": "twitchbot/chattoken",
        }
        sourcepath = pathlib.Path(config.fileName())

        if not sourcepath.exists():
            logging.debug("new install!")
            return

        config.setValue("twitchbot/oldscopes", "")
        config.remove("twitchbot/oldscopes")
        config.sync()

        # these got moved in 3.1.0
        npsqldb = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]
        ).joinpath("npsql.db")
        npsqldb.unlink(missing_ok=True)
        webdb = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]
        ).joinpath("web.db")
        webdb.unlink(missing_ok=True)

        oldversstr: str = config.value("settings/configversion", defaultValue="3.0.0")

        thisverstr = nowplaying.version.__VERSION__  # pylint: disable=no-member
        oldversion = Version(oldversstr)
        thisversion = Version(thisverstr)

        if oldversion == thisversion:
            logging.debug("equivalent config file versions")
            return

        # only save requests if the versions are the same
        # otherwise nuke it
        nowplaying.trackrequests.Requests(upgrade=True)

        if oldversion > thisversion:
            logging.warning("Running an older version with a newer config...")
            return

        self.backup_config()

        logging.info("Upgrading config from %s to %s", oldversstr, thisverstr)

        rawconfig = QSettings(str(sourcepath), self.qsettingsformat)

        # Run version-specific upgrades
        if oldversstr in {"3.1.0", "3.1.1"}:
            self._upgrade_filters(rawconfig)

        if int(oldversstr[0]) < 4 and config.value("settings/input") == "m3u":
            self._upgrade_m3u(rawconfig)

        if oldversion < Version("4.0.5"):
            self._upgrade_to_4_0_5(config, rawconfig)

        if oldversion < Version("4.1.0"):
            self._upgrade_to_4_1_0(config)

        if oldversion < Version("4.2.1"):
            self._upgrade_to_4_2_1(config)

        if oldversion < Version("4.3.0"):
            self._upgrade_to_4_3_0(config)

        self._oldkey_to_newkey(rawconfig, config, mapping)

        config.setValue("settings/configversion", thisverstr)
        config.sync()

    @staticmethod
    def _upgrade_to_4_0_5(config: QSettings, rawconfig: QSettings) -> None:
        """Upgrade to version 4.0.5"""
        oldusereplies = rawconfig.value("twitchbot/usereplies")
        if not oldusereplies:
            logging.info("Setting twitchbot to use replies by default")
            config.setValue("twitchbot/usereplies", True)

    @staticmethod
    def _upgrade_to_4_1_0(config: QSettings) -> None:
        """Upgrade to version 4.1.0"""
        for key in [
            "acoustidmb/discogs",
            "artistextras/enabled",
            "musicbrainz/enabled",
            "musicbrainz/fallback",
        ]:
            if not config.value(key, type=bool):
                logging.info("Upgrade to 4.1.0 defaults: enabled %s ", key)
                config.setValue(key, True)

    @staticmethod
    def _upgrade_to_4_2_1(config: QSettings) -> None:
        """Upgrade to version 4.2.1 - Ensure backward compatibility for dual-token system"""
        access_token = config.value("twitchbot/accesstoken")
        chat_token = config.value("twitchbot/chattoken")

        # If we have OAuth2 tokens but no separate chat token, ensure compatibility
        if access_token and not chat_token:
            logging.info(
                "Upgrade to 4.2.1: OAuth2 tokens will be used for both "
                "broadcaster and chat functionality"
            )
            # No changes needed - the dual-token system automatically falls back
            # This is just for logging the compatibility behavior

    @staticmethod
    def _upgrade_to_4_3_0(config: QSettings) -> None:
        """Upgrade to version 4.3.0 - Migrate old setlist setting to new real-time setlist"""
        old_setlist_enabled = config.value("setlist/enabled", type=bool)
        if old_setlist_enabled:
            logging.info("Upgrade to 4.3.0: Converting old setlist to real-time setlist")
            # Enable real-time setlist with default file pattern
            config.setValue("realtimesetlist/filepattern", "setlist-%Y%m%d-%H%M%S.txt")
            # Set up template path - will be created by template upgrade system
            user_template_dir = pathlib.Path(
                QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
                QCoreApplication.applicationName(),
                "templates",
            )
            template_path = user_template_dir.joinpath("setlist-table.txt")
            config.setValue("realtimesetlist/template", str(template_path))
            # Disable old setlist
            config.setValue("setlist/enabled", False)

    @staticmethod
    def _upgrade_filters(config: QSettings) -> None:
        """setup the recommended filters (3.1.0/3.1.1)"""
        if config.value("settings/stripextras", type=bool) and not config.value("regex_filter/0"):
            stripworldlist = ["clean", "dirty", "explicit", "official music video"]
            joinlist = "|".join(stripworldlist)
            config.setValue("regex_filter/0", f" \\((?i:{joinlist})\\)")
            config.setValue("regex_filter/1", f" - (?i:{joinlist}$)")
            config.setValue("regex_filter/2", f" \\[(?i:{joinlist})\\]")

    def _upgrade_m3u(self, config: QSettings) -> None:
        """convert m3u to virtualdj and maybe other stuff in the future?"""
        if "VirtualDJ" in config.value("m3u/directory"):
            historypath = pathlib.Path(config.value("m3u/directory"))
            config.setValue("virtualdj/history", config.value("m3u/directory"))
            config.setValue("virtualdj/playlists", str(historypath.parent.joinpath("Playlists")))
            config.setValue("settings/input", "virtualdj")
            if not self.testdir:
                msgbox = QMessageBox()
                msgbox.setText("M3U has been converted to VirtualDJ.")
                msgbox.show()
                msgbox.exec()

    @staticmethod
    def _oldkey_to_newkey(
        oldconfig: QSettings, newconfig: QSettings, mapping: dict[str, str]
    ) -> None:
        """remap keys"""
        for oldkey, newkey in mapping.items():
            logging.debug("processing %s - %s", oldkey, newkey)
            newval = None
            with contextlib.suppress(Exception):
                newval = oldconfig.value(newkey)
            if newval:
                logging.debug("%s already has value %s", newkey, newval)
                continue

            try:
                oldval = oldconfig.value(oldkey)
            except Exception:  # pylint: disable=broad-except
                logging.debug("%s vs %s: skipped, no new value", oldkey, newkey)
                continue

            if oldval:
                logging.debug("Setting %s from %s", newkey, oldkey)
                newconfig.setValue(newkey, oldval)
            else:
                logging.debug("%s does not exist", oldkey)
