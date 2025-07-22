#!/usr/bin/env python3
"""kickbot process"""

import contextlib
import logging
import os
import signal
import sys
import threading

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.frozen
import nowplaying.kick.launch


def stop(pid):
    """stop kickbot"""
    logging.info("sending INT to %s", pid)
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGINT)


def start(stopevent, bundledir, testmode=False):  # pragma: no cover
    """multiprocessing start hook"""
    threading.current_thread().name = "KickBot"

    bundledir = nowplaying.frozen.frozen_init(bundledir)

    if testmode:
        nowplaying.bootstrap.set_qt_names(appname="testsuite")
    else:
        nowplaying.bootstrap.set_qt_names()
    logpath = nowplaying.bootstrap.setuplogging(logname="debug.log", rotate=False)
    config = nowplaying.config.ConfigFile(bundledir=bundledir, logpath=logpath, testmode=testmode)

    logging.info("boot up")
    try:
        kickbot = nowplaying.kick.launch.KickLaunch(stopevent=stopevent, config=config)
        kickbot.start()
    except Exception as error:  # pylint: disable=broad-except
        logging.error("KickBot crashed: %s", error, exc_info=True)
        sys.exit(1)
    logging.info("shutting down kickbot v%s", config.version)
