#!/usr/bin/env python3
"""test config upgrade and backup system"""

import json
import os
import random
import string
import sys
import tempfile

from PySide6.QtCore import (  # pylint: disable=no-name-in-module
    QCoreApplication, QSettings)

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.upgrades.config  # pylint: disable=import-error
import nowplaying.utils.config_json  # pylint: disable=import-error
import nowplaying.version  # pylint: disable=no-member,import-error,no-name-in-module
from tests.upgrade.upgradetools import \
    reboot_macosx_prefs  # pylint: disable=import-error


def make_fake_300_config(fakestr):
    """generate v2.0.0 config"""
    if sys.platform == "win32":
        qsettingsformat = QSettings.IniFormat
    else:
        qsettingsformat = QSettings.NativeFormat

    nowplaying.bootstrap.set_qt_names(appname="testsuite")

    othersettings = QSettings(
        qsettingsformat,
        QSettings.UserScope,
        QCoreApplication.organizationName(),
        QCoreApplication.applicationName(),
    )
    othersettings.clear()
    reboot_macosx_prefs()
    othersettings.setValue("settings/configversion", "3.0.0-rc1")
    othersettings.setValue("settings/notdefault", fakestr)
    othersettings.sync()
    filename = othersettings.fileName()
    del othersettings
    reboot_macosx_prefs()
    assert os.path.exists(filename)
    return filename


def verify_json_backup_contains_config(backup_path, expected_values):
    """Verify JSON backup contains expected configuration values"""
    with open(backup_path, "r", encoding="utf-8") as backup_file:
        backup_data = json.load(backup_file)

    # Verify it's a proper backup with metadata
    assert "_export_info" in backup_data
    assert "version" in backup_data["_export_info"]
    # Backup contains current version from nowplaying.version, not the old version
    assert backup_data["_export_info"]["version"] == nowplaying.version.__VERSION__  # pylint: disable=no-member

    # Verify expected values are present
    for key, value in expected_values.items():
        assert backup_data.get(key) == value

    return True


def test_version_300rc1_to_current():  # pylint: disable=redefined-outer-name
    """test old config file upgrade and JSON backup system"""
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat
        teststr = "".join(random.choice(string.ascii_lowercase) for _ in range(5))

        # Verify backup directory doesn't exist yet
        backupdir = os.path.join(newpath, "testsuite", "configbackup")
        assert not os.path.exists(backupdir)

        # Run upgrade which should create JSON backup
        reboot_macosx_prefs()
        nowplaying.bootstrap.set_qt_names(appname="testsuite")
        upgrade = nowplaying.upgrades.config.UpgradeConfig(testdir=newpath)  # pylint: disable=unused-variable

        # Verify upgraded config still has our test value
        config = QSettings(
            qsettingsformat,
            QSettings.UserScope,
            QCoreApplication.organizationName(),
            QCoreApplication.applicationName(),
        )
        newfilename = config.fileName()
        config.sync()
        fakevalue = config.value("settings/notdefault")

        # Verify JSON backup was created and contains original data
        assert os.path.exists(backupdir)
        backup_files = [f for f in os.listdir(backupdir) if f.endswith(".json")]
        assert len(backup_files) == 1

        backup_path = os.path.join(backupdir, backup_files[0])
        expected_values = {"settings/configversion": "3.0.0-rc1", "settings/notdefault": teststr}
        verify_json_backup_contains_config(backup_path, expected_values)

        # Clean up
        config.clear()
        del config
        if os.path.exists(newfilename):
            os.unlink(newfilename)
        reboot_macosx_prefs()

        # Verify upgrade preserved our test data
        assert fakevalue == teststr
