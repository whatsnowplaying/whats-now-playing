#!/usr/bin/env python3
"""test 6.0.0-preview1 config upgrade - artwork limits are reset, not preserved"""

import os
import sys
import tempfile

import pytest
from PySide6.QtCore import (  # pylint: disable=no-name-in-module
    QCoreApplication,
    QSettings,
)

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.upgrades.config  # pylint: disable=import-error
import tests.utils_prefs  # pylint: disable=import-error

_RESET_KEYS = {
    "artistextras/cachesize": 20,
    "artistextras/banners": 6,
    "artistextras/logos": 6,
    "artistextras/thumbnails": 6,
    "artistextras/fanart": 50,
}


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
    settings.setValue("settings/configversion", version)
    if extra_keys:
        for key, value in extra_keys.items():
            settings.setValue(key, value)
    settings.sync()
    filename = settings.fileName()
    del settings
    assert os.path.exists(filename)
    return filename


def _read_config() -> QSettings:
    """Reopen the testsuite config after the upgrade has run."""
    if sys.platform == "win32":
        qsettingsformat = QSettings.IniFormat
    else:
        qsettingsformat = QSettings.NativeFormat
    nowplaying.bootstrap.set_qt_names(appname="testsuite")
    return QSettings(
        qsettingsformat,
        QSettings.UserScope,
        QCoreApplication.organizationName(),
        QCoreApplication.applicationName(),
    )


@pytest.mark.parametrize("key,expected", sorted(_RESET_KEYS.items()))
def test_upgrade_600_overwrites_stored_artwork_limits(key, expected):
    """A stored value is replaced, not preserved.

    These settings were unread between the imagecache migration and 6.0.0, so a
    stored number reflects an old default rather than a choice that ever took
    effect.  The upgrade deliberately plows over it.
    """
    with tempfile.TemporaryDirectory() as newpath:
        # a value deliberately different from both the old and new defaults
        _make_config("5.2.0", {key: 999})

        nowplaying.upgrades.config.UpgradeConfig(testdir=newpath)
        config = _read_config()
        try:
            assert config.value(key, type=int) == expected
        finally:
            config.clear()
            filename = config.fileName()
            del config
            tests.utils_prefs.remove_prefs_domain(filename)


def test_upgrade_600_sets_limits_when_absent():
    """A config predating these keys gains all of them."""
    with tempfile.TemporaryDirectory() as newpath:
        _make_config("5.2.0")

        nowplaying.upgrades.config.UpgradeConfig(testdir=newpath)
        config = _read_config()
        try:
            for key, expected in _RESET_KEYS.items():
                assert config.value(key, type=int) == expected, f"{key} not set"
        finally:
            config.clear()
            filename = config.fileName()
            del config
            tests.utils_prefs.remove_prefs_domain(filename)
