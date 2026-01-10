#!/usr/bin/env python3
"""test m3u"""

import os
import sys
import tempfile
import unittest.mock

from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.upgrades.config  # pylint: disable=import-error
from tests.upgrade.upgradetools import reboot_macosx_prefs  # pylint: disable=import-error


def test_noconfigfile():  # pylint: disable=redefined-outer-name
    """test no config file"""
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat
        backupdir = os.path.join(newpath, "testsuite", "configbackup")
        nowplaying.bootstrap.set_qt_names(appname="testsuite")

        # Mock _getoldconfig to return a non-existent config to isolate test from real system
        def mock_getoldconfig(self):
            return QSettings(
                self.qsettingsformat,
                QSettings.UserScope,
                "whatsnowplaying",
                "NonExistentOldApp",  # Use a name that doesn't exist on the system
            )

        with unittest.mock.patch.object(
            nowplaying.upgrades.config.UpgradeConfig, "_getoldconfig", mock_getoldconfig
        ):
            upgrade = nowplaying.upgrades.config.UpgradeConfig(testdir=newpath)  # pylint: disable=unused-variable
            config = QSettings(
                qsettingsformat, QSettings.UserScope, "com.github.whatsnowplaying", "testsuite"
            )
            config.clear()
            config.setValue("fakevalue", "force")
            config.sync()
            filename = config.fileName()

            assert os.path.exists(filename)
            assert not os.path.exists(backupdir)
            config.clear()
            del config
            reboot_macosx_prefs()
            if os.path.exists(filename):
                os.unlink(filename)
            reboot_macosx_prefs()
