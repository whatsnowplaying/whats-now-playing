#!/usr/bin/env python3
''' pytest fixtures '''

import logging
import os
import pathlib
import shutil
import sys
import tempfile

import pytest
from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.bootstrap
import nowplaying.config

# if sys.platform == 'darwin':
#     import psutil
#     import pwd

# DO NOT CHANGE THIS TO BE com.github.whatsnowplaying
# otherwise your actual bits will disappear!
DOMAIN = 'com.github.whatsnowplaying.testsuite'

try:
    from pytest_cov.embed import cleanup_on_sigterm
except ImportError:
    pass
else:
    cleanup_on_sigterm()


def reboot_macosx_prefs():
    ''' work around Mac OS X's preference caching '''
    if sys.platform == 'darwin':
        os.system(f'defaults delete {DOMAIN}')
        #
        # old method:
        #
        # for process in psutil.process_iter():
        #     try:
        #         if 'cfprefsd' in process.name() and pwd.getpwuid(
        #                 os.getuid()).pw_name == process.username():
        #             process.terminate()
        #             process.wait()
        #     except psutil.NoSuchProcess:
        #         pass


@pytest.fixture
def getroot(pytestconfig):
    ''' get the base of the source tree '''
    return pytestconfig.rootpath


@pytest.fixture
def bootstrap(getroot):  # pylint: disable=redefined-outer-name
    ''' bootstrap a configuration '''
    with tempfile.TemporaryDirectory() as newpath:
        bundledir = pathlib.Path(getroot).joinpath('nowplaying')
        nowplaying.bootstrap.set_qt_names(domain=DOMAIN, appname='testsuite')
        config = nowplaying.config.ConfigFile(bundledir=bundledir, logpath=newpath, testmode=True)
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
    config = QSettings(qsettingsformat, QSettings.SystemScope, QCoreApplication.organizationName(),
                       QCoreApplication.applicationName())
    config.clear()
    config.sync()

    cachedir = pathlib.Path(QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0])
    if 'testsuite' in cachedir.name and cachedir.exists():
        logging.info('Removing %s', cachedir)
        shutil.rmtree(cachedir)

    config = QSettings(qsettingsformat, QSettings.UserScope, QCoreApplication.organizationName(),
                       QCoreApplication.applicationName())
    config.clear()
    config.sync()
    filename = pathlib.Path(config.fileName())
    del config
    if filename.exists():
        filename.unlink()
    reboot_macosx_prefs()
    if filename.exists():
        filename.unlink()
    reboot_macosx_prefs()
    if filename.exists():
        logging.error('Still exists, wtf?')
    yield filename
    if filename.exists():
        filename.unlink()
    reboot_macosx_prefs()
    if filename.exists():
        filename.unlink()
    reboot_macosx_prefs()
