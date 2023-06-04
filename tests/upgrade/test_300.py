#!/usr/bin/env python3
''' test m3u '''

import hashlib
import os
import random
import string
import sys
import tempfile

import psutil

from PySide6.QtCore import QCoreApplication, QSettings  # pylint: disable=no-name-in-module

import nowplaying.bootstrap  # pylint: disable=import-error
import nowplaying.upgrade  # pylint: disable=import-error

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


def make_fake_300_config(fakestr):
    ''' generate v2.0.0 config '''
    if sys.platform == "win32":
        qsettingsformat = QSettings.IniFormat
    else:
        qsettingsformat = QSettings.NativeFormat

    nowplaying.bootstrap.set_qt_names(appname='testsuite')

    othersettings = QSettings(qsettingsformat, QSettings.UserScope,
                              QCoreApplication.organizationName(),
                              QCoreApplication.applicationName())
    othersettings.clear()
    reboot_macosx_prefs()
    othersettings.setValue('settings/configversion', '3.0.0-rc1')
    othersettings.setValue('settings/notdefault', fakestr)
    othersettings.sync()
    filename = othersettings.fileName()
    del othersettings
    reboot_macosx_prefs()
    assert os.path.exists(filename)
    return filename


def checksum(filename):
    ''' generate sha512 . See also build-update-sha.py '''
    hashfunc = hashlib.sha512()
    with open(filename, 'rb') as fileh:
        while chunk := fileh.read(128 * hashfunc.block_size):
            hashfunc.update(chunk)
    return hashfunc.hexdigest()


def test_version_300rc1_to_current():  # pylint: disable=redefined-outer-name
    ''' test old config file '''
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat
        teststr = ''.join(random.choice(string.ascii_lowercase) for _ in range(5))
        oldfilename = make_fake_300_config(teststr)
        oldchecksum = checksum(oldfilename)
        backupdir = os.path.join(newpath, 'testsuite', 'configbackup')
        assert not os.path.exists(os.path.join(backupdir))
        reboot_macosx_prefs()
        nowplaying.bootstrap.set_qt_names(appname='testsuite')
        upgrade = nowplaying.upgrade.UpgradeConfig(testdir=newpath)  #pylint: disable=unused-variable
        config = QSettings(qsettingsformat, QSettings.UserScope,
                           QCoreApplication.organizationName(), QCoreApplication.applicationName())
        newfilename = config.fileName()
        config.sync()
        fakevalue = config.value('settings/notdefault')
        files = os.listdir(backupdir)
        backupchecksum = checksum(os.path.join(backupdir, files[0]))
        config.clear()
        del config
        if os.path.exists(newfilename):
            os.unlink(newfilename)
        reboot_macosx_prefs()
        assert oldchecksum == backupchecksum
        assert fakevalue == teststr
