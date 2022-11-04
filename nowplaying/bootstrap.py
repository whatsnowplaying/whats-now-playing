#!/usr/bin/env python3
''' bootstrap the app '''

import logging
import logging.handlers
import pathlib

from PySide6.QtCore import QCoreApplication, QStandardPaths  # pylint: disable=no-name-in-module


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


def setuplogging(logdir=None, logname='debug.log', rotate=False):
    ''' configure logging '''
    besuretorotate = False

    if logdir:
        logpath = pathlib.Path(logdir)
        if logpath.is_file():
            logname = logpath.name
            logpath = logpath.parent
    else:
        logpath = pathlib.Path(
            QStandardPaths.standardLocations(
                QStandardPaths.DocumentsLocation)[0],
            QCoreApplication.applicationName()).joinpath('logs')
    logpath.mkdir(parents=True, exist_ok=True)
    logfile = logpath.joinpath(logname)

    if logfile.exists() and rotate:
        besuretorotate = True

    logfhandler = logging.handlers.RotatingFileHandler(filename=logfile,
                                                       backupCount=10,
                                                       encoding='utf-8')
    if besuretorotate:
        logfhandler.doRollover()

    logging.basicConfig(
        format=
        '%(asctime)s %(process)d %(processName)s/%(threadName)s %(module)s:%(funcName)s:%(lineno)d '
        + '%(levelname)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S%z',
        handlers=[logfhandler],
        level=logging.DEBUG)
    logging.captureWarnings(True)
    return logpath
