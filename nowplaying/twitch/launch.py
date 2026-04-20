#!/usr/bin/env python3
"""twitch base launch code"""

import asyncio
import contextlib
import logging
import signal
import nowplaying.db
import nowplaying.twitch.broadcaster
import nowplaying.twitch.chat
import nowplaying.twitch.redemptions
import nowplaying.twitch.utils
import nowplaying.utils
from nowplaying.twitch.constants import (
    BROADCASTER_OAUTH_STATUS_KEY,
    OAUTH_STATUS_EXPIRED,
)


class TwitchLaunch:  # pylint: disable=too-many-instance-attributes
    """handle twitch"""

    def __init__(self, config=None, stopevent: asyncio.Event = None):
        self.config = config
        self.stopevent = stopevent or asyncio.Event()
        self.widgets = None
        self.broadcaster = None
        self.chat = None
        self.redemptions = None
        self.loop = None
        self.twitchlogin = nowplaying.twitch.utils.TwitchLogin(self.config)
        self.tasks = set()

    @staticmethod
    def log_task_exception(task: asyncio.Task):
        """catch and log task exceptions"""
        with contextlib.suppress(asyncio.CancelledError):
            if exception := task.exception():
                task_name = task.get_name() if hasattr(task, "get_name") else str(task)
                logging.exception("Task %s failed: %s", exception, task_name)

    async def bootstrap(self):
        """Authenticate twitch and launch related tasks"""

        signal.signal(signal.SIGINT, self.forced_stop)

        # Now launch the actual tasks...
        if not self.loop:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                self.loop = asyncio.new_event_loop()

        # Pre-authenticate broadcaster token concurrently with startup delay
        # so status is written before the chat task even starts
        auth_task = self.loop.create_task(
            self.twitchlogin.api_login(), name="twitch_broadcaster_auth"
        )
        await asyncio.sleep(5)
        try:
            await asyncio.wait_for(auth_task, timeout=15)
        except asyncio.TimeoutError:
            logging.error("Broadcaster auth timed out; continuing startup")
            self.config.cparser.setValue(BROADCASTER_OAUTH_STATUS_KEY, OAUTH_STATUS_EXPIRED)
            self.config.cparser.sync()
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Broadcaster auth failed: %s; continuing startup", error)
            self.config.cparser.setValue(BROADCASTER_OAUTH_STATUS_KEY, OAUTH_STATUS_EXPIRED)
            self.config.cparser.sync()

        logging.info("Starting Twitch track watcher task")
        task = self.loop.create_task(self._run_track_watcher(), name="twitch_track_watcher")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task.add_done_callback(self.log_task_exception)

        if self.chat:
            logging.info("Starting Twitch chat task")
            task = self.loop.create_task(self.chat.run_chat(self.twitchlogin), name="twitch_chat")
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            task.add_done_callback(self.log_task_exception)
            await asyncio.sleep(5)
        if self.redemptions:
            logging.info("Starting Twitch redemptions task")
            task = self.loop.create_task(
                self.redemptions.run_redemptions(chat=self.chat), name="twitch_redemptions"
            )
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            task.add_done_callback(self.log_task_exception)

    def _on_watcher_event(self, event):  # pylint: disable=unused-argument
        """Watcher callback — schedule a track-change dispatch on the running loop"""
        if not self.loop or not self.loop.is_running():
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._dispatch_track_change(), self.loop)
            future.add_done_callback(
                lambda f: (
                    logging.error("Track watcher dispatch failed: %s", f.exception())
                    if not f.cancelled() and f.exception() is not None
                    else None
                )
            )
        except Exception:  # pylint: disable=broad-except
            logging.exception("Track watcher dispatch failed")

    async def _dispatch_track_change(self) -> None:
        """Dispatch a track-change event to all consumers"""
        if self.broadcaster:
            try:
                await self.broadcaster.on_track_change()
            except Exception:  # pylint: disable=broad-except
                logging.exception("Broadcaster track change handler failed")
        if self.chat:
            try:
                await self.chat.on_track_change()
            except Exception:  # pylint: disable=broad-except
                logging.exception("Chat track change handler failed")

    async def _run_track_watcher(self) -> None:
        """Own the metadb watcher and dispatch track changes to all consumers"""
        metadb = nowplaying.db.MetadataDB()
        watcher = metadb.watcher()
        try:
            watcher.start(customhandler=self._on_watcher_event)
            # Initial dispatch so consumers get the current track on startup
            await self._dispatch_track_change()
            while not nowplaying.utils.safe_stopevent_check(self.stopevent):
                await asyncio.sleep(1)
        finally:
            logging.debug("track watcher stop event received")
            watcher.stop()

    async def _watch_for_exit(self):
        while not nowplaying.utils.safe_stopevent_check(self.stopevent):
            await asyncio.sleep(1)
        await self.stop()

    def start(self):
        """start twitch support"""
        try:
            logging.info("Creating Twitch broadcaster, chat and redemptions objects")
            self.broadcaster = nowplaying.twitch.broadcaster.TwitchBroadcaster(
                config=self.config, stopevent=self.stopevent
            )
            self.chat = nowplaying.twitch.chat.TwitchChat(
                config=self.config, stopevent=self.stopevent
            )
            self.redemptions = nowplaying.twitch.redemptions.TwitchRedemptions(
                config=self.config, stopevent=self.stopevent
            )
            logging.info("Created chat: %s, redemptions: %s", self.chat, self.redemptions)
            if not self.loop:
                try:
                    self.loop = asyncio.get_running_loop()
                except RuntimeError:
                    self.loop = asyncio.new_event_loop()
            task = self.loop.create_task(self.bootstrap())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            task = self.loop.create_task(self._watch_for_exit())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            self.loop.run_forever()
        except Exception:  # pylint: disable=broad-except
            # for line in traceback.format_exc().splitlines():
            #    logging.error(line)
            logging.exception("Twitch support crashed")

    def forced_stop(self, signum, frame):  # pylint: disable=unused-argument
        """caught an int signal so tell the world to stop"""
        self.stopevent.set()

    async def stop(self):
        """stop the twitch support"""
        if self.broadcaster:
            await self.broadcaster.stop()
        if self.redemptions:
            await self.redemptions.stop()
        if self.chat:
            await self.chat.stop()
        await asyncio.sleep(1)
        # Don't revoke tokens on shutdown - preserve them for restart
        # Only clear the in-memory client, don't call api_logout() which revokes tokens
        if nowplaying.twitch.utils.TwitchLogin.OAUTH_CLIENT:
            nowplaying.twitch.utils.TwitchLogin.OAUTH_CLIENT = None
        if self.loop:
            self.loop.stop()
        logging.debug("twitchbot stopped")
