#!/usr/bin/env python3
''' twitch base launch code '''


import asyncio
import contextlib
import logging
import signal

import nowplaying.twitch.chat
import nowplaying.twitch.redemptions
import nowplaying.twitch.utils
import nowplaying.utils




class TwitchLaunch:  # pylint: disable=too-many-instance-attributes
    ''' handle twitch  '''

    def __init__(self, config=None, stopevent: asyncio.Event = None):
        self.config = config
        self.stopevent = stopevent or asyncio.Event()
        self.widgets = None
        self.chat = None
        self.redemptions = None
        self.loop = None
        self.twitchlogin = nowplaying.twitch.utils.TwitchLogin(self.config)
        self.tasks = set()

    def log_task_exception(self, task: asyncio.Task):
        ''' catch and log task exceptions '''
        with contextlib.suppress(asyncio.CancelledError):
            if exception := task.exception():
                task_name = task.get_name() if hasattr(task, 'get_name') else str(task)
                logging.exception("Task %s failed", task_name)

    async def bootstrap(self):
        ''' Authenticate twitch and launch related tasks '''

        signal.signal(signal.SIGINT, self.forced_stop)

        # Now launch the actual tasks...
        if not self.loop:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                self.loop = asyncio.new_event_loop()
        await asyncio.sleep(5)
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
                self.redemptions.run_redemptions(chat=self.chat), name="twitch_redemptions")
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            task.add_done_callback(self.log_task_exception)

    async def _watch_for_exit(self):
        while not nowplaying.utils.safe_stopevent_check(self.stopevent):
            await asyncio.sleep(1)
        await self.stop()

    def start(self):
        ''' start twitch support '''
        try:
            logging.info("Creating Twitch chat and redemptions objects")
            self.chat = nowplaying.twitch.chat.TwitchChat(config=self.config,
                                                          stopevent=self.stopevent)
            self.redemptions = nowplaying.twitch.redemptions.TwitchRedemptions(
                config=self.config, stopevent=self.stopevent)
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
            #for line in traceback.format_exc().splitlines():
            #    logging.error(line)
            logging.exception('Twitch support crashed')

    def forced_stop(self, signum, frame):  # pylint: disable=unused-argument
        ''' caught an int signal so tell the world to stop '''
        self.stopevent.set()

    async def stop(self):
        ''' stop the twitch support '''
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
        logging.debug('twitchbot stopped')
