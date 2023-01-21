#!/usr/bin/env python3
''' Code to use the OBS Web Socket plugin
    see https://github.com/Palakis/obs-websocket '''

import asyncio
import logging
import logging.config
import sys
import threading

import simpleobsws

logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': True,
})

#pylint: disable=wrong-import-position

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.frozen
import nowplaying.utils


class OBSWebSocketHandler:  #pylint: disable=too-many-instance-attributes
    ''' Talk to OBS directly via WebSocket '''

    def __init__(self, config=None, stopevent=None, testmode=None):
        self.config = config
        self.stopevent = stopevent
        self.testmode = testmode
        self.updateevent = threading.Event()
        self.client = None
        self.metadb = nowplaying.db.MetadataDB()
        self.text = None
        self.obswsport = None
        self.obswssecret = None
        self.obswshost = None
        self.watcher = None
        self.start()
        asyncio.run(self.webclient())

    def start(self):
        ''' run our thread '''

        if self.config.cparser.value('obsws/enabled',
                                     type=bool) and not self.watcher:
            self.watcher = self.metadb.watcher()
            self.watcher.start(customhandler=self.process_update)
            self.process_update(None)

    async def webclient(self):
        ''' run the web client '''

        lasttext = None
        while not self.stopevent.is_set():
            if not self.updateevent.is_set():
                await asyncio.sleep(1)
                continue

            if self.stopevent.is_set():
                break

            if not self.config.cparser.value('obsws/enabled', type=bool):
                await asyncio.sleep(1)
                continue

            source = self.config.cparser.value('obsws/source')
            if not source:
                await asyncio.sleep(1)
                continue

            await self.check_reconnect()
            self.text = self.generate_text()

            if lasttext == self.text:
                await asyncio.sleep(1)
                continue

            try:
                request = simpleobsws.Request('SetInputSettings', {
                    'inputName': source,
                    'inputSettings': {
                        'text': self.text
                    },
                })

                await self.client.call(request)
            except Exception as error:  # pylint: disable=broad-except
                logging.debug(error)
                await self.client.disconnect()

            self.updateevent.clear()

        self.stopevent.clear()
        self.updateevent.clear()
        if self.client:
            await self.client.disconnect()

    def process_update(self, event):  # pylint: disable=unused-argument
        ''' watcher picked up an update, so execute on it '''
        self.text = self.generate_text()
        if self.text:
            self.updateevent.set()

    def generate_text(self, clear=False):
        ''' convert template '''
        metadata = self.metadb.read_last_meta()
        if not metadata:
            return None

        template = self.config.cparser.value('obsws/template')
        if templatehandler := nowplaying.utils.TemplateHandler(
                filename=template):
            return templatehandler.generate(metadatadict=metadata)

        if clear:
            return ''

        return ' {{ artist }} - {{ title }} '

    async def check_reconnect(self):
        ''' check if our params have changed and if so reconnect '''
        obswshost = self.config.cparser.value('obsws/host')
        try:
            obswsport = self.config.cparser.value('obsws/port', type=int)
        except TypeError:
            self.stop()
            return

        obswssecret = self.config.cparser.value('obsws/secret')

        reconnect = False
        if not self.obswshost or self.obswshost != obswshost:
            logging.debug('reconnect')
            reconnect = True

        if not self.obswsport or self.obswsport != obswsport:
            logging.debug('reconnect')
            reconnect = True

        if not self.obswssecret or self.obswssecret != obswssecret:
            logging.debug('reconnect')
            reconnect = True

        if reconnect or not self.client or not self.client.is_identified():
            self.obswssecret = obswssecret
            self.obswsport = obswsport
            self.obswshost = obswshost
            try:
                parameters = simpleobsws.IdentificationParameters(
                    ignoreNonFatalRequestChecks=False)
                self.client = simpleobsws.WebSocketClient(
                    url=f'ws://{self.obswshost}:{self.obswsport}',
                    password=self.obswssecret,
                    identification_parameters=parameters)
                await self.client.connect()
                await self.client.wait_until_identified()
            except Exception as error:  # pylint: disable=broad-except
                # do not stop here in case OBS just isn't running yet
                # (initial launch case)
                logging.debug(error)
                await asyncio.sleep(3)

    def stop(self):
        ''' exit the thread '''
        logging.debug('OBSWS asked to stop')
        self.stopevent.set()
        self.updateevent.set()
        if self.watcher:
            self.watcher.stop()

    def __del__(self):
        logging.debug('Stopping OBSWS')
        self.stop()


def start(stopevent, bundledir, testmode=False):  #pylint: disable=unused-argument
    ''' multiprocessing start hook '''
    threading.current_thread().name = 'obsws'

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
    try:
        OBSWebSocketHandler(  # pylint: disable=unused-variable
            stopevent=stopevent,
            config=config,
            testmode=testmode)
    except Exception as error:  #pylint: disable=broad-except
        logging.error('OBSWebSocket crashed: %s', error, exc_info=True)
        sys.exit(1)
    logging.info('shutting down OBSWebSocket v%s',
                 nowplaying.version.get_versions()['version'])
