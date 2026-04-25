#!/usr/bin/env python3
"""
DataCache background worker process.

Drains the pending_requests queue: fetches URLs, stores blobs, retries
on failure.  Runs as a peer subprocess alongside trackpoll and webserver,
managed by SubprocessManager.  Shutdown is signalled via stopevent.
"""

import asyncio
import logging
import sys
import threading
from pathlib import Path

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.datacache.client
import nowplaying.frozen
import nowplaying.utils


async def _run(
    stopevent: asyncio.Event,
    cache_dir: Path | None = None,
    max_concurrent: int = 3,
) -> None:
    """Main async loop: drain the queue until stopevent is set."""
    client = nowplaying.datacache.client.DataCacheClient(cache_dir)
    await client.initialize()
    logging.info("DataCache worker started")

    consecutive_empty = 0

    try:
        while not nowplaying.utils.safe_stopevent_check(stopevent):
            stats = await client.process_queue(max_concurrent=max_concurrent)

            if stats["processed"] == 0:
                consecutive_empty += 1
                sleep_time = min(1.0 * (2 ** min(consecutive_empty - 1, 4)), 30.0)
                await asyncio.sleep(sleep_time)
            else:
                consecutive_empty = 0
                logging.debug(
                    "DataCache processed batch: %d processed, %d succeeded, %d failed",
                    stats["processed"],
                    stats["succeeded"],
                    stats["failed"],
                )
                await asyncio.sleep(0.1)
    finally:
        await client.close()
        logging.info("DataCache worker stopped")


def start(stopevent: asyncio.Event, bundledir: str, testmode: bool = False) -> None:
    """multiprocessing start hook"""
    threading.current_thread().name = "DataCache"

    bundledir = nowplaying.frozen.frozen_init(bundledir)

    if testmode:
        nowplaying.bootstrap.set_qt_names(appname="testsuite")
    else:
        nowplaying.bootstrap.set_qt_names()
    logpath = nowplaying.bootstrap.setuplogging(logname="debug.log", rotate=False)
    config = nowplaying.config.ConfigFile(bundledir=bundledir, logpath=logpath, testmode=testmode)
    logging.info("boot up")

    try:
        asyncio.run(_run(stopevent=stopevent))
    except Exception as error:  # pylint: disable=broad-except
        logging.error("DataCache worker crashed: %s", error, exc_info=True)
        sys.exit(1)
    logging.info("shutting down datacache v%s", config.version)
