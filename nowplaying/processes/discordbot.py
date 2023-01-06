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

import discord

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.utils
import nowplaying.version


class DiscordSupport:
    ''' Work with discord '''

    def __init__(self, config=None, stopevent=None):
        self.config = config
        self.stopevent = stopevent
        self.intents = discord.Intents.default()
        self.client = discord.Client(intents=self.intents)
        self.activity = None
        self.jinja2 = nowplaying.utils.TemplateHandler()

    async def update_activity(self):
        ''' keep the bot's presence updated '''

        try:
            metadb = nowplaying.db.MetadataDB()
            watcher = metadb.watcher()
            watcher.start()

            mytime = 0
            while not self.stopevent.is_set():
                await asyncio.sleep(1)

                if not self.client.is_ready():
                    continue

                if mytime < watcher.updatetime:
                    template = self.config.cparser.value('discord/template')
                    if not template:
                        continue

                    metadata = metadb.read_last_meta()
                    if not metadata:
                        continue

                    templatehandler = nowplaying.utils.TemplateHandler(
                        filename=template)
                    mytime = watcher.updatetime
                    templateout = templatehandler.generate(metadata)
                    if channelname := self.config.cparser.value(
                            'twitchbot/channel') and self.config.cparser.value(
                                'twitchbot/enabled', type=bool):
                        activity = discord.Streaming(
                            platform='Twitch',
                            name=templateout,
                            url=f'https://twitch.tv/{channelname}')
                    else:
                        activity = discord.Game(name=templateout, )
                    await self.client.change_presence(activity=activity)
                    # discord will lock out if updates more than every 15 seconds
                    await asyncio.sleep(14)

        except:  #pylint: disable=bare-except
            logging.debug(traceback.format_exc())

    async def start(self):
        ''' start the service '''
        loop = asyncio.get_running_loop()
        token = self.config.cparser.value('discord/token')
        await self.client.login(token)
        task = loop.create_task(self.client.connect(reconnect=True))
        tasks = {task}
        task.add_done_callback(tasks.discard)

        while not self.client.is_ready():
            await asyncio.sleep(1)

        task = loop.create_task(self.update_activity())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

        while not self.stopevent.is_set():
            await asyncio.sleep(1)
        await self.client.close()


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

    if not bundledir:
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            bundledir = getattr(sys, '_MEIPASS',
                                os.path.abspath(os.path.dirname(__file__)))
        else:
            bundledir = os.path.abspath(os.path.dirname(__file__))

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
    logging.info('shutting down discordbot v%s',
                 nowplaying.version.get_versions()['version'])
