#!/usr/bin/env python3
''' kick base launch code '''

import asyncio
import logging
import signal
import threading
from typing import Any

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.frozen
import nowplaying.kick.chat
import nowplaying.kick.oauth2
import nowplaying.kick.utils


class KickLaunch:  # pylint: disable=too-many-instance-attributes
    ''' handle kick integration '''

    def __init__(self,
                 config: nowplaying.config.ConfigFile | None = None,
                 stopevent: asyncio.Event | None = None) -> None:
        self.config = config
        self.stopevent = stopevent or asyncio.Event()
        self.widgets: Any = None
        self.chat: nowplaying.kick.chat.KickChat | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.oauth: nowplaying.kick.oauth2.KickOAuth2 = nowplaying.kick.oauth2.KickOAuth2(
            self.config)
        self.tasks: set[asyncio.Task[Any]] = set()

        # Register signal handler in main thread during initialization
        signal.signal(signal.SIGINT, self.forced_stop)

    async def bootstrap(self) -> None:
        ''' Authenticate kick and launch related tasks '''

        # Authenticate with Kick
        if not await self.authenticate():
            logging.error('Failed to authenticate with Kick')
            return

        # Now launch the actual tasks...
        if not self.loop:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                self.loop = asyncio.new_event_loop()

        await asyncio.sleep(5)

        # Launch chat if enabled
        if self.chat:
            task = self.loop.create_task(self.chat.run_chat(self.oauth))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            await asyncio.sleep(5)

    async def authenticate(self) -> bool:
        ''' authenticate with Kick using stored tokens (no browser interaction) '''
        try:
            # Use consolidated token refresh function
            if await nowplaying.kick.utils.attempt_token_refresh(self.config):
                logging.info('Kick token is valid - proceeding with chat')
                return True

            logging.error('Please re-authenticate via Settings -> Kick -> Authenticate')

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error('Kick authentication error: %s', error)

        return False

    async def _watch_for_exit(self) -> None:
        ''' watch for exit signal '''
        while not nowplaying.utils.safe_stopevent_check(self.stopevent):
            await asyncio.sleep(1)
        await self.stop()

    def start(self) -> None:
        ''' start kick support '''
        try:
            # Initialize chat
            self.chat = nowplaying.kick.chat.KickChat(config=self.config, stopevent=self.stopevent)

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
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception('Kick support crashed')

    def forced_stop(self, signum: int, frame: Any) -> None:  # pylint: disable=unused-argument
        ''' caught an int signal so tell the world to stop '''
        self.stopevent.set()

    async def stop(self) -> None:
        ''' stop the kick support '''
        # Stop chat
        if self.chat:
            await self.chat.stop()

        await asyncio.sleep(1)

        # Don't logout automatically - preserve tokens for next run
        # await self.oauth.revoke_token()

        if self.loop:
            self.loop.stop()
        logging.debug('kickbot stopped')


def start(stopevent: asyncio.Event | None = None,
          bundledir: str | None = None,
          testmode: bool = False) -> None:
    ''' multiprocessing start hook '''
    threading.current_thread().name = 'KickBot'

    bundledir = nowplaying.frozen.frozen_init(bundledir)

    if testmode:
        nowplaying.bootstrap.set_qt_names(appname='testsuite')
    else:
        nowplaying.bootstrap.set_qt_names()

    logpath = nowplaying.bootstrap.setuplogging(logname='debug.log', rotate=False)
    config = nowplaying.config.ConfigFile(bundledir=bundledir, logpath=logpath, testmode=testmode)

    logging.info('Kick bot starting up')

    try:
        kicklaunch = KickLaunch(config=config, stopevent=stopevent)
        kicklaunch.start()
    except KeyboardInterrupt:
        logging.info('Kick bot interrupted')
    except Exception: # pylint: disable=broad-exception-caught
        logging.exception('Kick bot crashed')


async def launch_kickbot(config: nowplaying.config.ConfigFile | None = None,
                         stopevent: asyncio.Event | None = None) -> None:
    ''' launch kickbot for asyncio integration '''
    try:
        kicklaunch = KickLaunch(config=config, stopevent=stopevent)
        await kicklaunch.bootstrap()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception('Kick bot launch failed')

    logging.info('Kick bot shutting down')


if __name__ == "__main__":
    start()
