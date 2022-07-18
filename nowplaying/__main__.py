#!/usr/bin/env python3
''' NowPlaying as run via python -m '''
#import faulthandler
import asyncio
import functools
import logging
import multiprocessing
import os
import pathlib
import socket
import sys

from PySide6.QtCore import QCoreApplication, QStandardPaths, Qt  # pylint: disable=no-name-in-module
from PySide6.QtGui import QIcon  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QApplication  # pylint: disable=no-name-in-module

import qasync

import nowplaying
import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.systemtray

# pragma: no cover
#
# as of now, there isn't really much here to test... basic bootstrap stuff
#


def run_bootstrap(bundledir=None):
    ''' bootstrap the app '''

    logpath = os.path.join(
        QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
        QCoreApplication.applicationName(), 'logs')
    pathlib.Path(logpath).mkdir(parents=True, exist_ok=True)
    logpath = os.path.join(logpath, "debug.log")

    # we are in a hurry to get results.  If it takes longer than
    # 5 seconds, consider it a failure and move on.  At some
    # point this should be configurable but this is good enough for now
    socket.setdefaulttimeout(5.0)
    nowplaying.bootstrap.setuplogging(logpath=logpath)

    nowplaying.bootstrap.upgrade(bundledir=bundledir)

    # fail early if metadatadb can't be configured
    metadb = nowplaying.db.MetadataDB()
    metadb.setupsql()


async def asyncmain(bundledir):
    ''' entrypoint post asyncio run '''

    def close_future(future, loop):
        loop.call_later(10, future.cancel)
        future.cancel()

    loop = asyncio.get_event_loop()
    qapp = QApplication.instance()
    qapp.setQuitOnLastWindowClosed(False)
    nowplaying.bootstrap.set_qt_names()
    run_bootstrap(bundledir=bundledir)
    future = asyncio.Future()
    config = nowplaying.config.ConfigFile(bundledir=bundledir)
    logging.getLogger().setLevel(config.loglevel)
    logging.captureWarnings(True)
    tray = nowplaying.systemtray.Tray()  # pylint: disable=unused-variable
    icon = QIcon(config.iconfile)
    qapp.setWindowIcon(icon)

    if hasattr(qapp, "aboutToQuit"):
        getattr(qapp, "aboutToQuit").connect(
            functools.partial(close_future, future, loop))

    logging.info('shutting down v%s',
                 nowplaying.version.get_versions()['version'])
    await future


def main():
    ''' main entrypoint '''

    multiprocessing.freeze_support()
    #faulthandler.enable()

    # set paths for bundled files
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundledir = getattr(sys, '_MEIPASS',
                            os.path.abspath(os.path.dirname(__file__)))
    else:
        bundledir = os.path.abspath(os.path.dirname(__file__))

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    try:
        qasync.run(asyncmain(bundledir))
    except asyncio.exceptions.CancelledError:
        sys.exit(0)


if __name__ == '__main__':
    main()
