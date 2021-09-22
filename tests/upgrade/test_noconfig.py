#!/usr/bin/env python3
''' test m3u '''

import os
import logging
import sys
import tempfile

import psutil
import pytest

from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module

import nowplaying.bootstrap  # pylint: disable=import-error

if sys.platform == 'darwin':
    import pwd


def reboot_macosx_prefs():
    ''' work around Mac OS X's preference caching '''
    if sys.platform == 'darwin':
        for process in psutil.process_iter():
            if 'cfprefsd' in process.name() and pwd.getpwuid(
                    os.getuid()).pw_name == process.username():
                process.terminate()
                process.wait()


@pytest.fixture(autouse=True, scope="function")
def move_old_config():
    ''' make sure the old em1ran config is out of the way '''
    if sys.platform == "win32":
        qsettingsformat = QSettings.IniFormat
    else:
        qsettingsformat = QSettings.NativeFormat

    othersettings = QSettings(qsettingsformat, QSettings.UserScope,
                              'com.github.em1ran', 'NowPlaying')
    renamed = False
    reboot_macosx_prefs()
    if os.path.exists(othersettings.fileName()):
        logging.warning('Moving old em1ran config around')
        os.rename(othersettings.fileName(), othersettings.fileName() + '.bak')
        renamed = True
    reboot_macosx_prefs()
    yield
    if renamed:
        logging.warning('Moving old em1ran back')
        os.rename(othersettings.fileName() + '.bak', othersettings.fileName())
    reboot_macosx_prefs()


def test_noconfigfile():  # pylint: disable=redefined-outer-name
    ''' test no config file '''
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat
        backupdir = os.path.join(newpath, 'testsuite', 'configbackup')
        nowplaying.bootstrap.set_qt_names(appname='testsuite')
        upgrade = nowplaying.bootstrap.UpgradeConfig(testdir=newpath)  #pylint: disable=unused-variable
        config = QSettings(qsettingsformat, QSettings.UserScope,
                           'com.github.whatsnowplaying', 'testsuite')
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
