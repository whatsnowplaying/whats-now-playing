#!/usr/bin/env python3
''' NowPlaying as run via python -m '''
#import faulthandler
import logging
import multiprocessing
import socket
import sys

from PySide6.QtCore import QCoreApplication, Qt  # pylint: disable=no-name-in-module
from PySide6.QtGui import QIcon  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QApplication  # pylint: disable=no-name-in-module

import nowplaying
import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.frozen
import nowplaying.systemtray
import nowplaying.upgrade

# pragma: no cover
#
# as of now, there isn't really much here to test... basic bootstrap stuff
#


def run_bootstrap(bundledir=None):
    ''' bootstrap the app '''
    # we are in a hurry to get results.  If it takes longer than
    # 5 seconds, consider it a failure and move on.  At some
    # point this should be configurable but this is good enough for now
    socket.setdefaulttimeout(5.0)
    logpath = nowplaying.bootstrap.setuplogging(rotate=True)
    logging.info('starting up v%s',
                 nowplaying.version.get_versions()['version'])
    nowplaying.upgrade.upgrade(bundledir=bundledir)

    # fail early if metadatadb can't be configured
    metadb = nowplaying.db.MetadataDB()
    metadb.setupsql()
    return logpath


def actualmain(beam=False):
    ''' main entrypoint '''

    multiprocessing.freeze_support()
    #faulthandler.enable()

    bundledir = nowplaying.frozen.frozen_init(None)

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)

    nowplaying.bootstrap.set_qt_names()
    logpath = run_bootstrap(bundledir=bundledir)

    if not nowplaying.bootstrap.verify_python_version():
        sys.exit(1)

    config = nowplaying.config.ConfigFile(logpath=logpath, bundledir=bundledir)
    logging.getLogger().setLevel(config.loglevel)
    logging.captureWarnings(True)
    tray = nowplaying.systemtray.Tray(beam=beam)  # pylint: disable=unused-variable
    icon = QIcon(str(config.iconfile))
    qapp.setWindowIcon(icon)
    exitval = qapp.exec_()
    logging.info('shutting down v%s',
                 nowplaying.version.get_versions()['version'])
    sys.exit(exitval)


def main():
    ''' Normal mode '''
    actualmain(beam=False)


def beammain():
    ''' beam mode '''
    actualmain(beam=True)


if __name__ == '__main__':
    main()
