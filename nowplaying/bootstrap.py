#!/usr/bin/env python3
"""bootstrap the app"""

import logging
import logging.handlers
import pathlib
import sys
import time

from PySide6.QtCore import QCoreApplication, QStandardPaths  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QErrorMessage  # pylint: disable=no-name-in-module


def verify_python_version():
    """make sure the correct version of python is being used"""

    if sys.version_info[0] < 3 or (sys.version_info[0] == 3 and sys.version_info[1] < 10):
        msgbox = QErrorMessage()
        msgbox.showMessage("Python Version must be 3.10 or higher.  Exiting.")
        msgbox.show()
        msgbox.exec()
        return False

    return True


def already_running():
    """errorbox if app is already running"""
    msgbox = QErrorMessage()
    msgbox.showMessage("What's Now Playing appears to be already running or still shutting down.")
    msgbox.show()
    msgbox.exec()


def set_qt_names(
    app: QCoreApplication | None = None,
    domain: str = "com.github.whatsnowplaying",
    appname: str = "NowPlaying",
):
    """bootstrap Qt for configuration"""
    # QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    if not app:
        app = QCoreApplication.instance()
    if not app:
        app = QCoreApplication()
    app.setOrganizationDomain(domain)
    app.setOrganizationName("whatsnowplaying")
    app.setApplicationName(appname)


def setuplogging(
    logdir: pathlib.Path | str | None = None, logname: str = "debug.log", rotate: bool = False
) -> pathlib.Path:
    """configure logging"""
    if logdir:
        logpath = pathlib.Path(logdir)
        if logpath.is_file():
            logname = logpath.name
            logpath = logpath.parent
    else:
        logpath = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0],
            QCoreApplication.applicationName(),
        ).joinpath("logs")
    logpath.mkdir(parents=True, exist_ok=True)
    logfile = logpath.joinpath(logname)

    besuretorotate = bool(logfile.exists() and rotate)
    logfhandler = logging.handlers.RotatingFileHandler(
        filename=logfile, backupCount=10, encoding="utf-8"
    )
    if besuretorotate:
        # Try log rotation with retry logic for Windows file handle delays
        for attempt in range(3):
            try:
                logfhandler.doRollover()
                break
            except OSError as error:
                if attempt < 2:  # Don't sleep on the last attempt
                    time.sleep(0.5 * (attempt + 1))  # 0.5s, then 1.0s
                    continue
                # Final attempt failed - continue without rotation rather than crash
                logging.warning(
                    "Could not rotate log file after 3 attempts "
                    "(previous instance may still be shutting down): %s",
                    error,
                )

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(process)d %(processName)s/%(threadName)s "
        + "%(module)s:%(funcName)s:%(lineno)d %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        handlers=[logfhandler],
        level=logging.DEBUG,
    )
    logging.captureWarnings(True)
    return logpath
