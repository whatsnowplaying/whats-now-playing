#!/usr/bin/env python3
''' test m3u '''

import os
import sys
import tempfile

from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module

from tests.upgrade.upgradetools import reboot_macosx_prefs  # pylint: disable=import-error

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.upgrade  # pylint: disable=import-error


def test_noconfigfile():  # pylint: disable=redefined-outer-name
    ''' test no config file '''
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat
        backupdir = os.path.join(newpath, 'testsuite', 'configbackup')
        nowplaying.bootstrap.set_qt_names(appname='testsuite')
        upgrade = nowplaying.upgrade.UpgradeConfig(testdir=newpath)  #pylint: disable=unused-variable
        config = QSettings(qsettingsformat, QSettings.UserScope, 'com.github.whatsnowplaying',
                           'testsuite')
        config.clear()
        config.setValue('fakevalue', 'force')
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
