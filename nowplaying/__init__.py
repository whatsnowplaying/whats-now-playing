#!/usr/bin/env python3
'''
    Titles for streaming for Serato
'''

import logging
import multiprocessing
import os
import pathlib
import sys

from PySide2.QtCore import QCoreApplication, QStandardPaths, Qt  # pylint: disable=no-name-in-module
from PySide2.QtWidgets import QApplication  # pylint: disable=no-name-in-module

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.systemtray

__version__ = nowplaying.version.get_versions()['version']


def run_bootstrap(bundledir=None):
    ''' bootstrap the app '''

    logpath = os.path.join(
        QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
        QCoreApplication.applicationName(), 'logs')
    pathlib.Path(logpath).mkdir(parents=True, exist_ok=True)
    logpath = os.path.join(logpath, "debug.log")

    nowplaying.bootstrap.setuplogging(logpath=logpath)

    # fail early if metadatadb can't be configured
    metadb = nowplaying.db.MetadataDB()
    metadb.setupsql()

    templatedir = os.path.join(
        QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
        QCoreApplication.applicationName(), 'templates')

    pathlib.Path(templatedir).mkdir(parents=True, exist_ok=True)
    nowplaying.bootstrap.setuptemplates(bundledir=bundledir,
                                        templatedir=templatedir)


def main():
    ''' main entrypoint '''

    multiprocessing.freeze_support()

    # set paths for bundled files
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundledir = getattr(sys, '_MEIPASS',
                            os.path.abspath(os.path.dirname(__file__)))
    else:
        bundledir = os.path.abspath(os.path.dirname(__file__))

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    qapp = QApplication(sys.argv)
    qapp.setOrganizationName('com.github.em1ran')
    qapp.setApplicationName('NowPlaying')
    run_bootstrap(bundledir=bundledir)

    config = nowplaying.config.ConfigFile(bundledir=bundledir)
    logging.getLogger().setLevel(config.loglevel)

    tray = nowplaying.systemtray.Tray()  # pylint: disable=unused-variable
    qapp.setQuitOnLastWindowClosed(False)
    exitval = qapp.exec_()
    logging.info('shutting down v%s',
                 nowplaying.version.get_versions()['version'])
    sys.exit(exitval)


if __name__ == "__main__":
    main()
