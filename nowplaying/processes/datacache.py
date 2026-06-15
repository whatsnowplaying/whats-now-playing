#!/usr/bin/env python3
"""
DataCache background worker process.

Drains the pending_requests queue: fetches URLs, stores blobs, retries
on failure.  Runs as a peer subprocess alongside trackpoll and webserver,
managed by SubprocessManager.  Shutdown is signalled via stopevent.

Uses a watchdog DBWatcher on the pending_requests database file so new
queue entries wake the worker immediately rather than waiting up to 30 s.
Falls back to 1-second polling when the watcher sees no activity.
"""

import asyncio
import logging
import sys
import threading
from pathlib import Path

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.datacache.client
import nowplaying.db
import nowplaying.frozen
import nowplaying.processes.template_sync
import nowplaying.utils


async def _run(
    stopevent: asyncio.Event,
    config: nowplaying.config.ConfigFile,
    cache_dir: Path | None = None,
    max_concurrent: int = 3,
) -> None:
    """Main async loop: drain the queue until stopevent is set."""
    client = nowplaying.datacache.client.DataCacheClient(cache_dir)
    await client.initialize()
    logging.info("DataCache worker started")
    asyncio.create_task(nowplaying.processes.template_sync.sync_from_charts(config, client))

    # Watch the pending_requests database for writes so new image downloads
    # queued by trackpoll wake the worker immediately instead of sleeping up to 30 s.
    db_path = str(client.queue.database_path)
    watcher = nowplaying.db.DBWatcher(db_path)
    watcher.start()
    last_watcher_time = watcher.updatetime

    try:
        while not nowplaying.utils.safe_stopevent_check(stopevent):
            stats = await client.process_queue(max_concurrent=max_concurrent)

            if stats["processed"] == 0:
                # Poll in 0.1 s slices up to 1 s, breaking early on DB write.
                for _ in range(10):
                    await asyncio.sleep(0.1)
                    if watcher.updatetime != last_watcher_time:
                        break
                    if nowplaying.utils.safe_stopevent_check(stopevent):
                        break
                last_watcher_time = watcher.updatetime
            else:
                logging.debug(
                    "DataCache processed batch: %d processed, %d succeeded, %d failed",
                    stats["processed"],
                    stats["succeeded"],
                    stats["failed"],
                )
                last_watcher_time = watcher.updatetime
                await asyncio.sleep(0.1)
    finally:
        watcher.stop()
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
        asyncio.run(_run(stopevent=stopevent, config=config))
    except Exception as error:  # pylint: disable=broad-except
        logging.error("DataCache worker crashed: %s", error, exc_info=True)
        sys.exit(1)
    logging.info("shutting down datacache v%s", config.version)
