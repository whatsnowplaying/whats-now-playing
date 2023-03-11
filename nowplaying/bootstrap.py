#!/usr/bin/env python3
''' bootstrap the app '''

import logging
import logging.handlers
import pathlib
import sys

import pid.utils

from PySide6.QtCore import QCoreApplication, QStandardPaths  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QErrorMessage  # pylint: disable=no-name-in-module


def verify_python_version():
    ''' make sure the correct version of python is being used '''

    if sys.version_info[0] < 3 or (sys.version_info[0] == 3
                                   and sys.version_info[1] < 10):
        msgbox = QErrorMessage()
        msgbox.showMessage('Python Version must be 3.10 or higher.  Exiting.')
        msgbox.show()
        msgbox.exec()
        return False

    return True


def set_qt_names(app=None,
                 domain='com.github.whatsnowplaying',
                 appname='NowPlaying'):
    ''' bootstrap Qt for configuration '''
    #QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    if not app:
        app = QCoreApplication.instance()
    if not app:
        app = QCoreApplication()
    app.setOrganizationDomain(domain)
    app.setOrganizationName('whatsnowplaying')
    app.setApplicationName(appname)


def get_pid_dir():
    ''' pid has bad darwin support '''
    if sys.platform == 'darwin':
        return QStandardPaths.standardLocations(
            QStandardPaths.RuntimeLocation)[0]
    return pid.utils.determine_pid_directory()


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
