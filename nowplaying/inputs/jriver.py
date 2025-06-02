#!/usr/bin/env python3
''' JRiver Media Center MCWS API plugin '''

import asyncio
import logging

import aiohttp
import lxml.etree

from nowplaying.inputs import InputPlugin

class Plugin(InputPlugin):  #pylint: disable=too-many-instance-attributes
    ''' handler for JRiver Media Center via MCWS API '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "JRiver Media Center"
        self.host = None
        self.port = None
        self.username = None
        self.password = None
        self.access_key = None
        self.token = None
        self.base_url = None
        self.session = None
        self.mixmode = "newest"
        self.testmode = False

    async def start(self):
        ''' Initialize the plugin and authenticate '''
        self.host = self.config.cparser.value('jriver/host')
        self.port = self.config.cparser.value('jriver/port', '52199')  # Default JRiver port
        self.username = self.config.cparser.value('jriver/username')
        self.password = self.config.cparser.value('jriver/password')
        self.access_key = self.config.cparser.value('jriver/access_key')

        if not self.host:
            logging.error("JRiver host not configured")
            return False

        self.base_url = f"http://{self.host}:{self.port}/MCWS/v1"
        
        # Create aiohttp session
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))

        # Test connection and authenticate
        if await self._test_connection() and await self._authenticate():
            return True
        return False

    async def _test_connection(self):
        ''' Test connection to JRiver server '''
        try:
            url = f"{self.base_url}/Alive"
            async with self.session.get(url) as response:
                if response.status == 200:
                    response_text = await response.text()
                    # Parse response to check access key if provided
                    if self.access_key:
                        tree = lxml.etree.fromstring(response_text)
                        access_key_items = tree.xpath('//Item[@Name="AccessKey"]')
                        if access_key_items:
                            server_access_key = access_key_items[0].text
                            if server_access_key != self.access_key:
                                logging.error("Access key mismatch")
                                return False
                    logging.debug("JRiver server connection successful")
                    return True
                logging.error("JRiver server returned status %d", response.status)
                return False
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot connect to JRiver server: %s", error)
            return False

    async def _authenticate(self):
        ''' Authenticate with JRiver server '''
        if not self.username or not self.password:
            logging.debug("No username/password provided, skipping authentication")
            return True

        try:
            url = f"{self.base_url}/Authenticate"
            params = {
                'Username': self.username,
                'Password': self.password
            }
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    response_text = await response.text()
                    tree = lxml.etree.fromstring(response_text)
                    token_items = tree.xpath('//Item[@Name="Token"]')
                    if token_items:
                        self.token = token_items[0].text
                        logging.debug("JRiver authentication successful")
                        return True
                    logging.error("No token received from JRiver server")
                    return False
                logging.error("JRiver authentication failed with status %d", response.status)
                return False
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot authenticate with JRiver server: %s", error)
            return False

    async def getplayingtrack(self):
        ''' Get currently playing track from JRiver '''
        if not self.base_url:
            return None

        await asyncio.sleep(.5)
        try:
            url = f"{self.base_url}/Playback/Info"
            params = {}
            if self.token:
                params['Token'] = self.token

            async with self.session.get(url, params=params) as response:
                if response.status != 200:
                    logging.error("JRiver API returned status %d", response.status)
                    return None
                
                response_text = await response.text()

        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot get playing track from JRiver: %s", error)
            return None

        try:
            tree = lxml.etree.fromstring(response_text)
        except Exception as error:
            logging.error("Cannot parse JRiver response: %s", error)
            return None

        # Extract metadata from JRiver XML response
        metadata = {}

        # Parse the XML items
        for item in tree.xpath('//Item'):
            name = item.get('Name')
            value = item.text
            if name == 'Artist':
                metadata['artist'] = value
            elif name == 'Album':
                metadata['album'] = value
            elif name == 'Name':  # JRiver uses 'Name' for track title
                metadata['title'] = value
            elif name == 'DurationMS':
                # Convert milliseconds to seconds
                if value and value.isdigit():
                    metadata['duration'] = int(value) // 1000

        return metadata

    async def getrandomtrack(self, playlist):
        ''' Not implemented for JRiver MCWS '''
        return None

    async def stop(self):
        ''' Clean up resources '''
        if self.session:
            await self.session.close()
            self.session = None

    def defaults(self, qsettings):
        qsettings.setValue('jriver/host', None)
        qsettings.setValue('jriver/port', '52199')
        qsettings.setValue('jriver/username', None)
        qsettings.setValue('jriver/password', None)
        qsettings.setValue('jriver/access_key', None)

    def validmixmodes(self):
        ''' let the UI know which modes are valid '''
        return ['newest']

    def setmixmode(self, mixmode):
        ''' set the mixmode '''
        return 'newest'

    def getmixmode(self):
        ''' get the mixmode '''
        return 'newest'

    def connect_settingsui(self, qwidget, uihelp):
        ''' connect jriver local dir button '''
        self.qwidget = qwidget
        self.uihelp = uihelp

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''
        qwidget.host_lineedit.setText(self.config.cparser.value('jriver/host') or '')
        qwidget.port_lineedit.setText(self.config.cparser.value('jriver/port') or '52199')
        qwidget.username_lineedit.setText(self.config.cparser.value('jriver/username') or '')
        qwidget.password_lineedit.setText(self.config.cparser.value('jriver/password') or '')
        qwidget.access_key_lineedit.setText(self.config.cparser.value('jriver/access_key') or '')

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''
        self.config.cparser.setValue('jriver/host', qwidget.host_lineedit.text())
        self.config.cparser.setValue('jriver/port', qwidget.port_lineedit.text())
        self.config.cparser.setValue('jriver/username', qwidget.username_lineedit.text())
        self.config.cparser.setValue('jriver/password', qwidget.password_lineedit.text())
        self.config.cparser.setValue('jriver/access_key', qwidget.access_key_lineedit.text())

    def desc_settingsui(self, qwidget):
        ''' description '''
        qwidget.setText('This plugin provides support for JRiver Media Center via MCWS API. '
                       'Configure the host/IP and port of your JRiver server. '
                       'Username/password are optional if authentication is not required.')
