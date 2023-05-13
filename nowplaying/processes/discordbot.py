#!/usr/bin/env python3
'''

Discord support code

'''

import asyncio
import logging
import logging.config
import logging.handlers
import os
import signal
import sys
import threading
import traceback

import pypresence
import discord

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.frozen
import nowplaying.utils


class DiscordSupport:
    ''' Work with discord '''

    def __init__(self, config=None, stopevent=None):
        self.config = config
        self.stopevent = stopevent
        self.client = {}
        self.jinja2 = nowplaying.utils.TemplateHandler()
        self.tasks = set()
        signal.signal(signal.SIGINT, self.forced_stop)

    async def _setup_bot_client(self):
        token = self.config.cparser.value('discord/token')
        if not token:
            return

        if self.client.get('bot'):
            return

        try:
            intents = discord.Intents.default()
            self.client['bot'] = discord.Client(intents=intents)
            await self.client['bot'].login(token)
        except Exception as error:  #pylint: disable=broad-except
            logging.error('Cannot configure bot client: %s', error)
            return

        loop = asyncio.get_running_loop()
        task = loop.create_task(self.client['bot'].connect(reconnect=True))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        while not self.stopevent.is_set() and not self.client['bot'].is_ready(
        ):
            await asyncio.sleep(1)
        logging.debug('bot setup')

    async def _setup_ipc_client(self):
        clientid = self.config.cparser.value('discord/clientid')
        if not clientid:
            return

        loop = asyncio.get_running_loop()
        try:
            self.client['ipc'] = pypresence.AioPresence(clientid, loop=loop)
        except pypresence.exceptions.DiscordNotFound:
            logging.error('Discord client is not running')
            return
        except ConnectionRefusedError:
            logging.error('Cannot connect to discord client.')
            return
        except pypresence.exceptions.DiscordError as error:
            logging.error(error)
            return
        except:  # pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            return
        try:
            await self.client['ipc'].connect()
        except ConnectionRefusedError:
            logging.error('pypresence cannot connect; connection refused')
            del self.client['ipc']
            return
        logging.debug('ipc setup')

    async def _update_bot(self, templateout):
        if channelname := self.config.cparser.value(
                'twitchbot/channel') and self.config.cparser.value(
                    'twitchbot/enabled', type=bool):
            activity = discord.Streaming(
                platform='Twitch',
                name=templateout,
                url=f'https://twitch.tv/{channelname}')
        else:
            activity = discord.Game(templateout)
        try:
            await self.client['bot'].change_presence(activity=activity)
        except ConnectionResetError:
            logging.error('Cannot connect to discord.')
            del self.client['bot']

    async def _update_ipc(self, templateout):
        try:
            await self.client['ipc'].update(state='Streaming',
                                            details=templateout)
        except ConnectionRefusedError:
            logging.error('Cannot connect to discord client.')
            del self.client['ipc']
        except:  # pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            del self.client['ipc']

    async def connect_clients(self):
        ''' (re-)connect clients '''
        client = {
            'bot': self._setup_bot_client,
            'ipc': self._setup_ipc_client,
        }

        for mode, func in client.items():  # pylint: disable=consider-using-dict-items
            if not self.client.get(mode):
                await func()

    async def start(self):
        ''' start the service '''

        client = {
            'bot': self._update_bot,
            'ipc': self._update_ipc,
        }

        metadb = nowplaying.db.MetadataDB()
        watcher = metadb.watcher()
        watcher.start()

        mytime = 0

        while not self.stopevent.is_set():
            if not self.config.cparser.value('discord/enabled', type=bool):
                await asyncio.sleep(5)
                continue

            await self.connect_clients()
            # discord will lock out if updates more than every 15 seconds
            await asyncio.sleep(20)

            if mytime < watcher.updatetime:
                template = self.config.cparser.value('discord/template')
                if not template:
                    continue

                metadata = await metadb.read_last_meta_async()
                if not metadata:
                    continue

                templatehandler = nowplaying.utils.TemplateHandler(
                    filename=template)
                mytime = watcher.updatetime
                templateout = templatehandler.generate(metadata)
                for mode, func in client.items():
                    if self.client.get(mode):
                        try:
                            await func(templateout)

                        except:  #pylint: disable=bare-except
                            for line in traceback.format_exc().splitlines():
                                logging.error(line)
                            del self.client[mode]
        watcher.stop()
        if self.client.get('bot'):  # pylint: disable=consider-using-dict-items
            await self.client['bot'].close()

    def forced_stop(self, signum, frame):  # pylint: disable=unused-argument
        ''' caught an int signal so tell the world to stop '''
        self.stopevent.set()


def stop(pid):
    ''' stop the web server -- called from Tray '''
    logging.info('sending INT to %s', pid)
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        pass


def start(stopevent, bundledir, testmode=False):  #pylint: disable=unused-argument
    ''' multiprocessing start hook '''
    threading.current_thread().name = 'DiscordBot'

    bundledir = nowplaying.frozen.frozen_init(bundledir)

    if testmode:
        nowplaying.bootstrap.set_qt_names(appname='testsuite')
    else:
        nowplaying.bootstrap.set_qt_names()
    logpath = nowplaying.bootstrap.setuplogging(logname='debug.log',
                                                rotate=False)
    config = nowplaying.config.ConfigFile(bundledir=bundledir,
                                          logpath=logpath,
                                          testmode=testmode)
    logging.info('boot up')
    try:
        discordsupport = DiscordSupport(stopevent=stopevent, config=config)
        asyncio.run(discordsupport.start())
    except Exception as error:  #pylint: disable=broad-except
        logging.error('discordbot crashed: %s', error, exc_info=True)
        sys.exit(1)
    logging.info('shutting down discordbot v%s', config.version)
