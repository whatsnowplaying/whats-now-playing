#!/usr/bin/env python3
''' test m3u '''

import os
import logging
import random
import sys
import tempfile

import psutil
import pytest

from PySide2.QtCore import QCoreApplication, QSettings  # pylint: disable=no-name-in-module

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


def make_fake_200_config(trialnum):
    ''' generate v2.0.0 config '''
    if sys.platform == "win32":
        qsettingsformat = QSettings.IniFormat
    else:
        qsettingsformat = QSettings.NativeFormat

    othersettings = QSettings(qsettingsformat, QSettings.UserScope,
                              'com.github.em1ran', 'NowPlaying')
    othersettings.clear()
    othersettings.setValue('settings/configversion', '2.0.0')
    othersettings.setValue('settings/interval', trialnum)
    othersettings.setValue('settings/handler', 'serato')
    othersettings.sync()
    filename = othersettings.fileName()
    del othersettings
    reboot_macosx_prefs()
    assert os.path.exists(filename)
    return filename


def test_version200_to_current():  # pylint: disable=redefined-outer-name
    ''' test old config file '''
    with tempfile.TemporaryDirectory() as newpath:
        trialnum = random.randint(11, 2000) + 0.0
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat
        filename = make_fake_200_config(trialnum)
        backupdir = os.path.join(newpath, 'testsuite', 'configbackup')
        assert not os.path.exists(os.path.join(backupdir))
        reboot_macosx_prefs()
        if sys.platform != 'darwin':
            logging.debug('old file')
            with open(filename, encoding='utf-8') as configfh:
                logging.debug(configfh.readlines())
        nowplaying.bootstrap.set_qt_names(appname='testsuite')
        upgrade = nowplaying.bootstrap.UpgradeConfig(testdir=newpath)  #pylint: disable=unused-variable
        config = QSettings(qsettingsformat, QSettings.UserScope,
                           QCoreApplication.organizationName(),
                           QCoreApplication.applicationName())
        interval = config.value('serato/interval', type=float)
        handler = config.value('settings/input')

        if sys.platform != 'darwin':
            logging.debug('new file')
            with open(config.fileName(), encoding='utf-8') as configfh:
                logging.debug(configfh.readlines())
        os.unlink(filename)
        reboot_macosx_prefs()
        assert interval == trialnum
        assert handler == 'serato'
