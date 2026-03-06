#!/usr/bin/env python3
"""test 5.1.0 config upgrade - removal of legacy keys"""

import os
import sys
import tempfile

from PySide6.QtCore import (  # pylint: disable=no-name-in-module
    QCoreApplication,
    QSettings,
)

from upgradetools import reboot_macosx_prefs  # pylint: disable=import-error

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.upgrades.config  # pylint: disable=import-error


def make_fake_510_preview3_config(grace_period=None):
    """Generate a 5.1.0-preview3 config containing legacy keys that should be removed"""
    if sys.platform == "win32":
        qsettingsformat = QSettings.IniFormat
    else:
        qsettingsformat = QSettings.NativeFormat

    nowplaying.bootstrap.set_qt_names(appname="testsuite")

    settings = QSettings(
        qsettingsformat,
        QSettings.UserScope,
        QCoreApplication.organizationName(),
        QCoreApplication.applicationName(),
    )
    settings.clear()
    reboot_macosx_prefs()
    settings.setValue("settings/configversion", "5.1.0-preview2")
    # Legacy keys that should be stripped by the 5.1.0 upgrade
    settings.setValue("icecast/traktor-collections", "/Users/someone/traktor/collection.nml")
    settings.setValue("remote/remotedb", "/Users/someone/Library/Caches/remote.db")
    settings.setValue("serato/seratodir", "/Users/someone/Library/Application Support/Serato")
    settings.setValue("serato3/libpath", "/Users/someone/Music/_Serato_")
    # A real key that should survive
    settings.setValue("settings/delay", "2.5")
    if grace_period is not None:
        settings.setValue("guessgame/grace_period", grace_period)
    settings.sync()
    filename = settings.fileName()
    del settings
    reboot_macosx_prefs()
    assert os.path.exists(filename)
    return filename


def test_upgrade_510_removes_legacy_keys():
    """Legacy keys are removed and real settings are preserved"""
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat

        _oldfilename = make_fake_510_preview3_config(grace_period=5)

        reboot_macosx_prefs()
        nowplaying.bootstrap.set_qt_names(appname="testsuite")
        _upgrade = nowplaying.upgrades.config.UpgradeConfig(testdir=newpath)  # pylint: disable=unused-variable

        config = QSettings(
            qsettingsformat,
            QSettings.UserScope,
            QCoreApplication.organizationName(),
            QCoreApplication.applicationName(),
        )
        newfilename = config.fileName()
        config.sync()

        # Legacy keys must be gone
        assert config.value("icecast/traktor-collections") is None
        assert config.value("remote/remotedb") is None
        assert config.value("serato/seratodir") is None
        assert config.value("serato3/libpath") is None

        # Real settings must survive
        assert config.value("settings/delay") == "2.5"

        # grace_period=5 should have been bumped to 10
        assert config.value("guessgame/grace_period") in (None, "10", 10)

        config.clear()
        del config
        if os.path.exists(newfilename):
            os.unlink(newfilename)
        reboot_macosx_prefs()


def test_upgrade_510_grace_period_not_changed_if_custom():
    """Grace period is preserved if user set it to something other than the old default of 5"""
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat

        _oldfilename = make_fake_510_preview3_config(grace_period=30)

        reboot_macosx_prefs()
        nowplaying.bootstrap.set_qt_names(appname="testsuite")
        _upgrade = nowplaying.upgrades.config.UpgradeConfig(testdir=newpath)  # pylint: disable=unused-variable

        config = QSettings(
            qsettingsformat,
            QSettings.UserScope,
            QCoreApplication.organizationName(),
            QCoreApplication.applicationName(),
        )
        newfilename = config.fileName()
        config.sync()

        # Custom grace period must be preserved
        assert config.value("guessgame/grace_period") in ("30", 30)

        config.clear()
        del config
        if os.path.exists(newfilename):
            os.unlink(newfilename)
        reboot_macosx_prefs()
