#!/usr/bin/env python3
''' twitch base launch code '''

import asyncio
import logging
import signal

import nowplaying.twitch.chat
#import nowplaying.twitch.redemptions
import nowplaying.twitch.utils
import nowplaying.utils




class TwitchLaunch:  # pylint: disable=too-many-instance-attributes
    ''' handle twitch  '''

    def __init__(self, config=None, stopevent: asyncio.Event = None):
        self.config = config
        self.stopevent = stopevent or asyncio.Event()
        self.widgets = None
        self.chat = None
        #self.redemptions = None
        self.loop = None
        self.twitchlogin = nowplaying.twitch.utils.TwitchLogin(self.config)
        self.tasks = set()

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
            task = self.loop.create_task(self.chat.run_chat(self.twitchlogin))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            await asyncio.sleep(5)
        #if self.redemptions:
        #    task = self.loop.create_task(
        #        self.redemptions.run_redemptions(self.twitchlogin, self.chat))
        #    self.tasks.add(task)
        #    task.add_done_callback(self.tasks.discard)

    async def _watch_for_exit(self):
        while not nowplaying.utils.safe_stopevent_check(self.stopevent):
            await asyncio.sleep(1)
        await self.stop()

    def start(self):
        ''' start twitch support '''
        try:
            self.chat = nowplaying.twitch.chat.TwitchChat(config=self.config,
                                                          stopevent=self.stopevent)
            #self.redemptions = nowplaying.twitch.redemptions.TwitchRedemptions(
            #    config=self.config, stopevent=self.stopevent)
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
        #if self.redemptions:
        #    await self.redemptions.stop()
        if self.chat:
            await self.chat.stop()
        await asyncio.sleep(1)
        await self.twitchlogin.api_logout()
        if self.loop:
            self.loop.stop()
        logging.debug('twitchbot stopped')
