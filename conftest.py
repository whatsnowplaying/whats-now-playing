#!/usr/bin/env python3
''' pytest fixtures '''

import logging
import os
import sys

import psutil
import pytest
from PySide6.QtCore import QCoreApplication, QSettings  # pylint: disable=no-name-in-module

import nowplaying.bootstrap
import nowplaying.config

if sys.platform == 'darwin':
    import pwd

try:
    from pytest_cov.embed import cleanup_on_sigterm
except ImportError:
    pass
else:
    cleanup_on_sigterm()


def reboot_macosx_prefs():
    ''' work around Mac OS X's preference caching '''
    if sys.platform == 'darwin':
        for process in psutil.process_iter():
            if 'cfprefsd' in process.name() and pwd.getpwuid(
                    os.getuid()).pw_name == process.username():
                process.terminate()
                process.wait()


@pytest.fixture
def getroot(pytestconfig):
    ''' get the base of the source tree '''
    return pytestconfig.rootpath


@pytest.fixture
def bootstrap(getroot):  # pylint: disable=redefined-outer-name
    ''' bootstrap a configuration '''
    bundledir = os.path.join(getroot, 'nowplaying')
    nowplaying.bootstrap.set_qt_names(appname='testsuite')
    config = nowplaying.config.ConfigFile(bundledir=bundledir, testmode=True)
    config.cparser.setValue('acoustidmb/enabled', False)
    config.cparser.sync()
    yield config


#
# OS X has a lot of caching wrt preference files
# so we have do a lot of work to make sure they
# don't stick around
#
@pytest.fixture(autouse=True, scope="function")
def clear_old_testsuite():
    ''' clear out old testsuite configs '''
    if sys.platform == "win32":
        qsettingsformat = QSettings.IniFormat
    else:
        qsettingsformat = QSettings.NativeFormat

    nowplaying.bootstrap.set_qt_names(appname='testsuite')
    config = QSettings(qsettingsformat, QSettings.SystemScope,
                       QCoreApplication.organizationName(),
                       QCoreApplication.applicationName())
    config.clear()
    config.sync()

    config = QSettings(qsettingsformat, QSettings.UserScope,
                       QCoreApplication.organizationName(),
                       QCoreApplication.applicationName())
    config.clear()
    config.sync()
    filename = config.fileName()
    del config
    if os.path.exists(filename):
        os.unlink(filename)
    reboot_macosx_prefs()
    if os.path.exists(filename):
        os.unlink(filename)
    reboot_macosx_prefs()
    if os.path.exists(filename):
        logging.error('Still exists, wtf?')
    yield filename
    if os.path.exists(filename):
        os.unlink(filename)
    reboot_macosx_prefs()
    if os.path.exists(filename):
        os.unlink(filename)
    reboot_macosx_prefs()
