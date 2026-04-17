#!/usr/bin/env python3
"""test 5.2.0 config upgrade"""

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


def _make_config(version: str, extra_keys: dict | None = None) -> str:
    """Create a QSettings config at the given version with optional extra keys."""
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
    settings.setValue("settings/configversion", version)
    if extra_keys:
        for key, value in extra_keys.items():
            settings.setValue(key, value)
    settings.sync()
    filename = settings.fileName()
    del settings
    reboot_macosx_prefs()
    assert os.path.exists(filename)
    return filename


def test_upgrade_520_removes_tenorkey():
    """upgrade to 5.2.0 strips the gifwords/tenorkey setting"""
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat

        _oldfilename = _make_config(
            "5.1.0",
            {"gifwords/tenorkey": "some-tenor-api-key", "settings/delay": "2.5"},
        )

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

        assert config.value("gifwords/tenorkey") is None
        assert config.value("settings/delay") == "2.5"

        config.clear()
        del config
        if os.path.exists(newfilename):
            os.unlink(newfilename)
        reboot_macosx_prefs()


def test_upgrade_520_fixes_missing_basic_web_htm(tmp_path):
    """upgrade to 5.2.0 replaces basic-web.htm with ws-frosted-glass.htm when file is absent"""
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        old_template = str(templates_dir / "basic-web.htm")
        expected_template = str(templates_dir / "ws-frosted-glass.htm")

        _oldfilename = _make_config(
            "5.1.0",
            {"weboutput/htmltemplate": old_template},
        )

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

        assert config.value("weboutput/htmltemplate") == expected_template

        config.clear()
        del config
        if os.path.exists(newfilename):
            os.unlink(newfilename)
        reboot_macosx_prefs()


def test_upgrade_520_preserves_basic_web_htm_if_file_exists(tmp_path):
    """upgrade to 5.2.0 must not replace basic-web.htm if the file still exists on disk"""
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        old_template_path = templates_dir / "basic-web.htm"
        old_template_path.write_text("<!-- existing template -->")
        old_template = str(old_template_path)

        _oldfilename = _make_config(
            "5.1.0",
            {"weboutput/htmltemplate": old_template},
        )

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

        assert config.value("weboutput/htmltemplate") == old_template

        config.clear()
        del config
        if os.path.exists(newfilename):
            os.unlink(newfilename)
        reboot_macosx_prefs()


def test_upgrade_520_preserves_other_template():
    """upgrade to 5.2.0 does not modify htmltemplate when it is not basic-web.htm"""
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat

        existing_template = "/Users/dj/Documents/WhatsNowPlaying/templates/my-custom.htm"

        _oldfilename = _make_config(
            "5.1.0",
            {"weboutput/htmltemplate": existing_template},
        )

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

        assert config.value("weboutput/htmltemplate") == existing_template

        config.clear()
        del config
        if os.path.exists(newfilename):
            os.unlink(newfilename)
        reboot_macosx_prefs()
