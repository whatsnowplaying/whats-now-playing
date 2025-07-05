#!/usr/bin/env python3
''' NowPlaying as run via python -m '''

#import faulthandler
import logging
import multiprocessing
import platform
import socket
import sys

from PySide6.QtCore import QCoreApplication, Qt  # pylint: disable=import-error, no-name-in-module
from PySide6.QtGui import QIcon  # pylint: disable=import-error, no-name-in-module
from PySide6.QtWidgets import QApplication  # pylint: disable=import-error, no-name-in-module

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.frozen
import nowplaying.singleinstance
import nowplaying.startup
import nowplaying.systemtray
import nowplaying.upgrade

#
# as of now, there isn't really much here to test... basic bootstrap stuff
#


def run_bootstrap(bundledir=None):  # pragma: no cover
    ''' bootstrap the app '''
    # we are in a hurry to get results.  If it takes longer than
    # 5 seconds, consider it a failure and move on.  At some
    # point this should be configurable but this is good enough for now
    socket.setdefaulttimeout(5.0)
    logpath = nowplaying.bootstrap.setuplogging(rotate=True)
    plat = platform.platform()
    logging.info('starting up v%s on %s', nowplaying.__version__, plat)
    nowplaying.upgrade.upgrade(bundledir=bundledir)
    logging.debug('ending upgrade')

    # fail early if metadatadb can't be configured
    metadb = nowplaying.db.MetadataDB()
    metadb.setupsql()
    return logpath


def actualmain(beam=False):  # pragma: no cover
    ''' main entrypoint '''

    multiprocessing.freeze_support()
    #faulthandler.enable()

    bundledir = nowplaying.frozen.frozen_init(None)
    exitval = 1
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    nowplaying.bootstrap.set_qt_names()
    try:
        with nowplaying.singleinstance.SingleInstance():
            logpath = run_bootstrap(bundledir=bundledir)

            if not nowplaying.bootstrap.verify_python_version():
                sys.exit(1)

            # Show startup window AFTER bootstrap but BEFORE heavy initialization
            startup_window = nowplaying.startup.StartupWindow(bundledir=bundledir)
            startup_window.show()
            startup_window.update_progress("Initializing configuration...")
            qapp.processEvents()  # Force UI update

            config = nowplaying.config.ConfigFile(logpath=logpath, bundledir=bundledir)
            logging.getLogger().setLevel(config.loglevel)
            logging.captureWarnings(True)

            startup_window.update_progress("Starting system tray...")
            qapp.processEvents()

            tray = nowplaying.systemtray.Tray(beam=beam, startup_window=startup_window)  # pylint: disable=unused-variable
            icon = QIcon(str(config.iconfile))
            qapp.setWindowIcon(icon)

            # Close startup window if it still exists
            if startup_window and startup_window.isVisible():
                startup_window.complete_startup()

            exitval = qapp.exec_()
            logging.info('shutting main down v%s', config.version)
    except nowplaying.singleinstance.AlreadyRunningError:
        nowplaying.bootstrap.already_running()

    sys.exit(exitval)


def main():  # pragma: no cover
    ''' Normal mode '''
    actualmain(beam=False)


def beammain():  # pragma: no cover
    ''' beam mode '''
    actualmain(beam=True)


if __name__ == '__main__':
    main()
