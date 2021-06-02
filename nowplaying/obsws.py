#!/usr/bin/env python3
''' Code to use the OBS Web Socket plugin
    see https://github.com/Palakis/obs-websocket '''

import logging
import logging.config
#import threading
#import time

import obswebsocket
import obswebsocket.requests

logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': True,
})

#pylint: disable=wrong-import-position

import nowplaying.config
import nowplaying.db
import nowplaying.utils


class OBSWebSocketHandler:  #pylint: disable=too-many-instance-attributes
    ''' Talk to OBS directly via WebSocket '''
    def __init__(self, tray=None):
        self.config = nowplaying.config.ConfigFile()
        self.client = None
        self.metadb = nowplaying.db.MetadataDB()
        self.text = None
        self.obswsport = None
        self.obswssecret = None
        self.obswshost = None
        self.watcher = None
        self.tray = tray

    def start(self):
        ''' run our thread '''

        if self.config.cparser.value('obsws/enabled',
                                     type=bool) and not self.watcher:
            self.watcher = self.metadb.watcher()
            self.watcher.start(customhandler=self.process_update)
            self.process_update(None)

    def process_update(self, event):  # pylint: disable=unused-argument
        ''' watcher picked up an update, so execute on it '''

        source = self.config.cparser.value('obsws/source')
        if source:
            self.check_reconnect()
            self.text = self.generate_text()
            if self.text:
                try:
                    if self.config.cparser.value('obsws/freetype2'):
                        self.client.call(
                            obswebsocket.requests.SetTextFreetype2Properties(
                                source=source, text=self.text))
                    else:
                        self.client.call(
                            obswebsocket.requests.SetTextGDIPlusProperties(
                                source=source, text=self.text))
                except Exception as error:  # pylint: disable=broad-except
                    # there are a lot of uncaught, internal exceptions from
                    # upstream :(

                    logging.debug(error)

    def generate_text(self, clear=False):
        ''' convert template '''
        metadata = self.metadb.read_last_meta()
        if not metadata:
            return None

        template = self.config.cparser.value('obsws/template')
        templatehandler = nowplaying.utils.TemplateHandler(filename=template)
        if templatehandler:
            return templatehandler.generate(metadatadict=metadata)

        if clear:
            return ''

        return ' {{ artist }} - {{ title }} '

    def check_reconnect(self):
        ''' check if our params have changed and if so reconnect '''
        obswshost = self.config.cparser.value('obsws/host')
        try:
            obswsport = self.config.cparser.value('obsws/port', type=int)
        except TypeError:
            self.tray.obswsenable(False)
            self.stop()
            return

        obswssecret = self.config.cparser.value('obsws/secret')

        reconnect = False
        if not self.obswshost or self.obswshost != obswshost:
            reconnect = True

        if not self.obswsport or self.obswsport != obswsport:
            reconnect = True

        if not self.obswssecret or self.obswssecret != obswssecret:
            reconnect = True

        if reconnect:
            self.obswssecret = obswssecret
            self.obswsport = obswsport
            self.obswshost = obswshost
            try:
                self.client = obswebsocket.obsws(obswshost, obswsport,
                                                 obswssecret)
                self.client.connect()
            except Exception as error:  # pylint: disable=broad-except

                # there are a lot of uncaught, internal exceptions from
                # upstream :(
                logging.debug(error)
                self.tray.obswsenable(False)
                self.stop()

    def stop(self):
        ''' exit the thread '''
        logging.debug('OBSWS asked to stop')
        if self.watcher:
            self.watcher.stop()
        if self.client:
            self.client.disconnect()
            self.client = None

    def __del__(self):
        logging.debug('Stopping OBSWS')
        self.stop()
