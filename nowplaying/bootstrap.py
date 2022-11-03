#!/usr/bin/env python3
''' bootstrap the app '''

import logging
import logging.handlers
import os

from PySide6.QtCore import QCoreApplication  # pylint: disable=no-name-in-module

import nowplaying.upgrade
import nowplaying.version


def set_qt_names(app=None, appname='NowPlaying'):
    ''' bootstrap Qt for configuration '''
    #QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    if not app:
        app = QCoreApplication.instance()
    if not app:
        app = QCoreApplication()
    app.setOrganizationDomain('com.github.whatsnowplaying')
    app.setOrganizationName('whatsnowplaying')
    app.setApplicationName(appname)


def upgrade(bundledir=None):
    ''' do an upgrade of an existing install '''
    logging.debug('Called upgrade')
    myupgrade = nowplaying.upgrade.UpgradeConfig()  #pylint: disable=unused-variable
    myupgrade = nowplaying.upgrade.UpgradeTemplates(bundledir=bundledir)


def setuplogging(logpath=None, rotate=False):
    ''' configure logging '''
    besuretorotate = False

    if os.path.exists(logpath) and rotate:
        besuretorotate = True

    logfhandler = logging.handlers.RotatingFileHandler(filename=logpath,
                                                       backupCount=10,
                                                       encoding='utf-8')
    if besuretorotate:
        logfhandler.doRollover()

    # this loglevel should eventually be tied into config
    # but for now, hard-set at info
    logging.basicConfig(
        format=
        '%(asctime)s %(process)d %(threadName)s %(module)s:%(funcName)s:%(lineno)d '
        + '%(levelname)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S%z',
        handlers=[logfhandler],
        level=logging.DEBUG)
