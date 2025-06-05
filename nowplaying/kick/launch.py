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

    async def bootstrap(self) -> None:
        ''' Authenticate kick and launch related tasks '''

        signal.signal(signal.SIGINT, self.forced_stop)

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
            # Check if we have stored tokens
            access_token, refresh_token = self.oauth.get_stored_tokens()

            if not access_token:
                logging.error(
                    'No Kick access token stored - please authenticate via Settings first')
                return False

            logging.info('Validating stored Kick token...')

            # Validate token using simple sync validation
            if nowplaying.kick.utils.qtsafe_validate_kick_token(access_token):
                logging.info('Kick token is valid - proceeding with chat')
                return True

            # Token invalid - try refresh if available
            if refresh_token:
                logging.info('Token invalid, attempting automatic refresh...')
                try:
                    _ = await self.oauth.refresh_access_token(refresh_token)

                    # Re-validate the refreshed token
                    new_access_token, _ = self.oauth.get_stored_tokens()
                    if new_access_token and nowplaying.kick.utils.qtsafe_validate_kick_token(
                            new_access_token):
                        logging.info('Token refreshed successfully - proceeding with chat')
                        return True

                    logging.error('Refreshed token is still invalid')

                except Exception as error:  # pylint: disable=broad-exception-caught
                    logging.error('Failed to refresh Kick token: %s', error)
                    logging.error('Please re-authenticate via Settings -> Kick -> Authenticate')
            else:
                logging.error('No refresh token available for automatic renewal')
                logging.error('Please re-authenticate via Settings -> Kick -> Authenticate')

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error('Kick authentication error: %s', error)

        return False

    async def _watch_for_exit(self) -> None:
        ''' watch for exit signal '''
        while not self.stopevent.is_set():
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
