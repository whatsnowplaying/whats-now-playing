#!/usr/bin/env python3
"""Configuration upgrade logic"""

import contextlib
import logging
import pathlib
import sys
import time

from PySide6.QtCore import (  # pylint: disable=no-name-in-module
    QCoreApplication,
    QSettings,
    QStandardPaths,
)
from PySide6.QtWidgets import QMessageBox  # pylint: disable=no-name-in-module

import nowplaying.trackrequests
import nowplaying.utils.config_json
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
            backup = backupdir.joinpath(f"{datestr}-config.json")
            nowplaying.utils.config_json.export_config(export_path=backup, settings=config)
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Failed to make a backup: %s", error)
            sys.exit(0)

    def upgrade(self) -> None:
        """variable re-mapping"""
        config = self._getconfig()

        mapping = {
            "acoustidmb/emailaddress": "musicbrainz/emailaddress",
            "acoustidmb/enabled": "musicbrainz/enabled",
            "acoustidmb/websites": "musicbrainz/websites",
            "acoustidmb/bandcamp": "musicbrainz/bandcamp",
            "acoustidmb/homepage": "musicbrainz/homepage",
            "acoustidmb/lastfm": "musicbrainz/lastfm",
            "acoustidmb/musicbrainz": "musicbrainz/musicbrainz",
            "acoustidmb/discogs": "musicbrainz/discogs",
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

        if oldversstr == "5.0.0-preview1":
            self._upgrade_from_5_0_0_preview1(config)

        if oldversion < Version("5.0.0-preview3"):
            self._upgrade_to_5_0_0_preview3(config)

        if oldversion < Version("5.0.0-preview5"):
            self._upgrade_to_5_0_0_preview5(config)
            self._cleanup_old_backup_files()

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
        if config.value("setlist/enabled", type=bool):
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
    def _upgrade_from_5_0_0_preview1(config: QSettings) -> None:
        """Upgrade from 5.0.0-preview1 - Force VirtualDJ database rebuild for schema changes"""

        # This code _only_ happens if they were running 5.0.0-preview1
        # so very limited exposure
        logging.info("Upgrade from 5.0.0-preview1: Cleaning VirtualDJ databases for schema update")

        # Get VirtualDJ database paths
        virtualdj_cache_dir = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]
        ).joinpath("virtualdj")

        if virtualdj_cache_dir.exists():
            # Delete VirtualDJ databases to force clean rebuild with new schema
            virtualdj_songs_db = virtualdj_cache_dir.joinpath("virtualdj-songs.db")
            virtualdj_playlists_db = virtualdj_cache_dir.joinpath("virtualdj-playlists.db")

            databases_removed = []
            for db_path in [virtualdj_songs_db, virtualdj_playlists_db]:
                if db_path.exists():
                    try:
                        db_path.unlink()
                        databases_removed.append(db_path.name)
                        logging.info("Removed VirtualDJ database: %s", db_path.name)
                    except OSError as err:
                        logging.warning(
                            "Failed to remove VirtualDJ database %s: %s", db_path.name, err
                        )

            if databases_removed:
                logging.info("VirtualDJ databases removed: %s", ", ".join(databases_removed))
                # Force rebuild flags
                config.setValue("virtualdj/rebuild_db", True)
                config.setValue("virtualdj/rebuild_playlists_db", True)
            else:
                logging.debug("No VirtualDJ databases found to remove")

    @staticmethod
    def _upgrade_to_5_0_0_preview3(config: QSettings) -> None:
        """Upgrade from 5.0.0-preview3 - Force enable charts"""
        logging.info("Upgrade from 5.0.0-preview3: force enable charts plugin")
        config.setValue("charts/enabled", True)

    @staticmethod
    def _upgrade_to_5_0_0_preview5(config: QSettings) -> None:
        """Upgrade to 5.0.0-preview5 - Migrate Serato config and reset filters"""
        logging.info("Upgrade to 5.0.0-preview5: migrating serato/* config to serato4/*")

        # Keys that should be copied to serato4 for new plugin
        # (serato3 continues using the original serato/ keys)
        serato4_keys = [
            "deckskip",
            "mixmode",
            "url",
            "local",
            "interval",
        ]

        # Only migrate if user currently has serato plugin selected
        current_input = config.value("settings/input")
        if current_input == "serato":
            logging.info(
                "Current input is serato - copying config to serato4 and switching to serato3"
            )

            # Copy keys to serato4 for new plugin (serato3 continues using serato/ keys)
            for key in serato4_keys:
                old_key = f"serato/{key}"
                serato4_key = f"serato4/{key}"

                old_value = config.value(old_key)
                existing_serato4_value = config.value(serato4_key)

                if old_value is not None and existing_serato4_value is None:
                    logging.debug("Copying %s to %s: %s", old_key, serato4_key, old_value)
                    config.setValue(serato4_key, old_value)
                elif old_value is not None:
                    logging.debug("Skipping %s - %s already exists", old_key, serato4_key)

            # Switch input plugin to serato3 (legacy, continues using serato/ keys)
            config.setValue("settings/input", "serato3")
            logging.info("Switched input plugin from serato to serato3")
        else:
            logging.debug("Current input is %s - no migration needed", current_input)

        # Reset filter system to new defaults
        logging.info("Upgrade to 5.0.0-preview5: resetting filter system to new defaults")

        # Remove existing regex filters (simple_filter is new in this release)
        for key in list(config.allKeys()):
            if key.startswith("regex_filter/"):
                logging.debug("Removing old filter key: %s", key)
                config.remove(key)

        # Turn filtering on by default
        config.setValue("settings/stripextras", True)
        logging.info("Enabled title filtering by default")

        # The FilterManager will automatically set up defaults when no simple filter config exists
        # This ensures the default-on phrases are properly enabled

        config.remove("artistextras/cachedir")
        config.remove("artistextras/cachedbfile")
        config.remove("beam/enabled")
        config.remove("beam/remote_key")
        config.remove("remote_port")
        config.remove("remote_server")
        config.remove("control/beam")

    def _cleanup_old_backup_files(self) -> None:
        """Clean up old .bak backup files from pre-5.0.0-preview5"""
        if self.testdir:
            docpath = self.testdir
        else:  # pragma: no cover
            docpath = QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0]

        backupdir = pathlib.Path(docpath).joinpath(
            QCoreApplication.applicationName(), "configbackup"
        )

        if not backupdir.exists():
            return

        logging.info("Cleaning up old backup files from: %s", backupdir)

        removed_files = []
        try:
            for backup_file in backupdir.glob("*.bak"):
                try:
                    backup_file.unlink()
                    removed_files.append(backup_file.name)
                    logging.debug("Removed old backup file: %s", backup_file.name)
                except OSError as error:
                    logging.warning("Failed to remove backup file %s: %s", backup_file.name, error)
        except OSError as error:
            logging.error("Failed to scan backup directory: %s", error)
            return

        if removed_files:
            logging.info(
                "Removed %d old backup files: %s", len(removed_files), ", ".join(removed_files)
            )
        else:
            logging.debug("No old backup files found to clean up")

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
