#!/usr/bin/env python3
''' JRiver Media Center MCWS API plugin '''


import asyncio
import contextlib
import ipaddress
import logging
from typing import TYPE_CHECKING

import aiohttp
import lxml.etree

from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    import nowplaying.config
    from PySide6.QtWidgets import QWidget


class Plugin(InputPlugin):  #pylint: disable=too-many-instance-attributes
    ''' handler for JRiver Media Center via MCWS API '''

    def __init__(self,
                 config: "nowplaying.config.ConfigFile | None" = None,
                 qsettings: "QWidget | None" = None):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname: str = "JRiver"
        self.host: str | None = None
        self.port: str | None = None
        self.username: str | None = None
        self.password: str | None = None
        self.access_key: str | None = None
        self.token: str | None = None
        self.base_url: str | None = None
        self.session: aiohttp.ClientSession | None = None
        self.mixmode: str = "newest"
        self._connection_failed: bool = False

    async def start(self) -> bool:
        ''' Initialize the plugin and authenticate '''
        self.host = self.config.cparser.value('jriver/host')
        self.port = self.config.cparser.value('jriver/port', '52199')  # Default JRiver port
        self.username = self.config.cparser.value('jriver/username')
        self.password = self.config.cparser.value('jriver/password')
        self.access_key = self.config.cparser.value('jriver/access_key')

        if not self.host:
            logging.error("JRiver host not configured")
            return False

        # Format host for URL (wrap IPv6 addresses in brackets)
        formatted_host = self._format_host_for_url(self.host)
        self.base_url = f"http://{formatted_host}:{self.port}/MCWS/v1"

        # Create aiohttp session
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))

        # Test connection and authenticate
        if await self._test_connection() and await self._authenticate():
            self._connection_failed = False
            return True

        # Don't close session on failed initialization - keep it for auto-recovery
        self._connection_failed = True
        return True  # Return True to allow plugin to be enabled for auto-recovery

    async def _test_connection(self) -> bool:
        ''' Test connection to JRiver server '''
        try:
            url = f"{self.base_url}/Alive"
            async with self.session.get(url) as response:  # pylint: disable=not-async-context-manager
                if response.status == 200:
                    response_text = await response.text()
                    # Parse response to check access key if provided
                    if self.access_key:
                        tree = lxml.etree.fromstring(response_text.encode('utf-8'))  # pylint: disable=c-extension-no-member
                        if access_key_items := tree.xpath('//Item[@Name="AccessKey"]'):
                            if access_key_items[0].text != self.access_key:
                                logging.error("Access key mismatch")
                                return False
                    logging.debug("JRiver server connection successful")
                    return True
                logging.error("JRiver server returned status %d", response.status)
                return False
        except aiohttp.ClientConnectorError:
            logging.debug("JRiver is not running or not accessible at %s", self.base_url)
            return False
        except asyncio.TimeoutError:
            logging.warning("JRiver connection test timed out at %s", self.base_url)
            return False
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot connect to JRiver server: %s", error)
            return False

    async def _authenticate(self) -> bool:
        ''' Authenticate with JRiver server '''
        if not self.username or not self.password:
            logging.debug("No username/password provided, skipping authentication")
            return True

        try:
            url = f"{self.base_url}/Authenticate"
            params = {'Username': self.username, 'Password': self.password}
            async with self.session.get(url, params=params) as response:  # pylint: disable=not-async-context-manager
                if response.status != 200:
                    logging.error("JRiver authentication failed with status %d", response.status)
                    return False

                response_text = await response.text()
                tree = lxml.etree.fromstring(response_text.encode('utf-8'))  # pylint: disable=c-extension-no-member
                if token_items := tree.xpath('//Item[@Name="Token"]'):
                    self.token = token_items[0].text
                    logging.debug("JRiver authentication successful")
                    return True
                logging.error("No token received from JRiver server")
                return False
        except aiohttp.ClientConnectorError:
            logging.debug("JRiver is not running or not accessible at %s for auth", self.base_url)
        except asyncio.TimeoutError:
            logging.warning("JRiver authentication timed out at %s", self.base_url)
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot authenticate with JRiver server: %s", error)

        return False

    async def _attempt_auto_recovery(self) -> bool:
        ''' Attempt to recover from connection failure '''
        if not self._connection_failed:
            return True

        logging.debug("Attempting JRiver auto-recovery")
        if await self._test_connection() and await self._authenticate():
            self._connection_failed = False
            logging.info("JRiver auto-recovery successful")
            return True
        return False

    async def _fetch_playback_info(self) -> str | None:
        ''' Fetch playback info from JRiver API '''
        url = f"{self.base_url}/Playback/Info"
        params = {}
        if self.token:
            params['Token'] = self.token
        if self.access_key:
            params['AccessKey'] = self.access_key

        try:
            async with self.session.get(url, params=params) as response:  # pylint: disable=not-async-context-manager
                if response.status != 200:
                    logging.error("JRiver API returned status %d", response.status)
                    return None
                return await response.text()
        except aiohttp.ClientConnectorError:
            if not self._connection_failed:
                logging.debug("JRiver is not running or not accessible at %s", self.base_url)
                self._connection_failed = True
        except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
            if not self._connection_failed:
                logging.warning("JRiver connection timed out at %s", self.base_url)
                self._connection_failed = True
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot get playing track from JRiver: %s", error)
        return None

    @staticmethod
    def _parse_metadata_xml(response_text: str) -> tuple[TrackMetadata, str | None]:
        ''' Parse JRiver XML response into metadata dict '''
        try:
            tree = lxml.etree.fromstring(response_text.encode('utf-8'))  # pylint: disable=c-extension-no-member
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot parse JRiver response: %s", error)
            return {}, None

        metadata: TrackMetadata = {}
        filekey: str | None = None

        if tree is not None:
            for item in tree.xpath('//Item'):
                if item is None:
                    continue
                name = item.get('Name')
                value = item.text
                if name == 'Artist':
                    metadata['artist'] = value
                elif name == 'Album':
                    metadata['album'] = value
                elif name == 'Name':  # JRiver uses 'Name' for track title
                    metadata['title'] = value
                elif name == 'DurationMS' and value and value.isdigit():
                    metadata['duration'] = int(value) // 1000
                elif name == 'FileKey':
                    filekey = value

        return metadata, filekey

    async def getplayingtrack(self) -> TrackMetadata | None:
        ''' Get currently playing track from JRiver '''
        if not self.base_url or not self.session:
            return None

        # Attempt auto-recovery if needed
        if not await self._attempt_auto_recovery():
            return None

        await asyncio.sleep(.5)

        # Fetch data from JRiver
        response_text = await self._fetch_playback_info()
        if response_text is None:
            return None

        # Parse the XML response
        metadata, filekey = self._parse_metadata_xml(response_text)

        # Get filename if available for local connections
        if filekey and self._is_local_connection():
            if filename := await self._get_filename(filekey):
                metadata['filename'] = filename

        return metadata

    @staticmethod
    def _format_host_for_url(host: str | None) -> str | None:
        ''' Format host for URL construction, wrapping IPv6 addresses in brackets '''
        if not host:
            return host

        # Check if host is already wrapped in brackets (user might have done this)
        if host.startswith('[') and host.endswith(']'):
            return host

        # Try to detect if this is an IPv6 address
        with contextlib.suppress(ValueError):
            ip_addr = ipaddress.ip_address(host)
            # If it's IPv6, wrap in brackets
            if isinstance(ip_addr, ipaddress.IPv6Address):
                return f"[{host}]"
        # Return as-is for IPv4 addresses and hostnames
        return host

    def _is_local_connection(self) -> bool:
        ''' Check if this is a local connection where file paths would be meaningful '''
        if not self.host:
            return False

        # Only consider explicit localhost references as truly local
        local_hosts = ['localhost', '127.0.0.1', '::1']
        if self.host.lower() in local_hosts:
            return True

        # Check for private IP ranges (same-network connections)
        try:
            ip_addr = ipaddress.ip_address(self.host)
            return ip_addr.is_private
        except ValueError:
            # For hostnames, only consider explicit local domain patterns
            # Remote hostnames like 'jriver.example.com' should NOT be treated as local
            host_lower = self.host.lower()
            local_domain_patterns = [
                '.local',  # mDNS/Bonjour local domains (e.g., jriver.local)
                '.lan',  # Common local network domain
                '.home',  # Common home network domain
                '.internal',  # Common internal network domain
            ]
            # Only return True for explicit local domain patterns
            return any(host_lower.endswith(pattern) for pattern in local_domain_patterns)

    @staticmethod
    def _extract_filename_from_xml(response_text: str, filekey: str) -> str | None:
        ''' Extract filename from JRiver XML response '''
        try:
            tree = lxml.etree.fromstring(response_text.encode('utf-8'))  # pylint: disable=c-extension-no-member
        except Exception as error:  # pylint: disable=broad-except
            logging.debug("Cannot parse GetInfo response for FileKey %s: %s", filekey, error)
            return None

        # Handle both Response format (simple) and MPL format (detailed)
        # MPL format: <MPL><Item><Field Name="Filename">...</Field></Item></MPL>
        filename_fields = tree.xpath('//Field[@Name="Filename"]')
        if filename_fields and (filename := filename_fields[0].text):
            return filename

        # Fallback to old Response format: <Response><Item Name="Filename">...</Item></Response>
        filename_items = tree.xpath('//Item[@Name="Filename"]')
        if filename_items and (filename := filename_items[0].text):
            return filename

        logging.debug("No Filename found in GetInfo response for FileKey %s", filekey)
        return None

    async def _get_filename(self, filekey: str) -> str | None:
        ''' Get filename from FileKey using GetInfo API '''
        if not self.session:
            return None

        url = f"{self.base_url}/File/GetInfo"
        params = {'File': filekey}
        if self.token:
            params['Token'] = self.token
        if self.access_key:
            params['AccessKey'] = self.access_key

        try:
            async with self.session.get(url, params=params) as response:  # pylint: disable=not-async-context-manager
                if response.status != 200:
                    logging.debug("GetInfo API returned status %d for FileKey %s",
                                  response.status, filekey)
                    return None
                response_text = await response.text()
                return self._extract_filename_from_xml(response_text, filekey)
        except aiohttp.ClientConnectorError:
            if not self._connection_failed:
                logging.debug("JRiver is not running or not accessible for FileKey %s", filekey)
                self._connection_failed = True
        except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
            if not self._connection_failed:
                logging.debug("JRiver GetInfo timed out for FileKey %s", filekey)
                self._connection_failed = True
        except Exception as error:  # pylint: disable=broad-except
            logging.debug("Cannot get filename for FileKey %s: %s", filekey, error)

        return None

    async def getrandomtrack(self, playlist: str) -> str | None:
        ''' Not implemented for JRiver MCWS '''
        return None

    async def stop(self) -> None:
        ''' Clean up resources '''
        if self.session:
            await self.session.close()
            self.session = None
        self._connection_failed = False

    def defaults(self, qsettings: "QWidget") -> None:
        qsettings.setValue('jriver/host', None)
        qsettings.setValue('jriver/port', '52199')
        qsettings.setValue('jriver/username', None)
        qsettings.setValue('jriver/password', None)
        qsettings.setValue('jriver/access_key', None)

    def validmixmodes(self) -> list[str]:
        ''' let the UI know which modes are valid '''
        return ['newest']

    def setmixmode(self, mixmode: str) -> str:
        ''' set the mixmode '''
        return 'newest'

    def getmixmode(self) -> str:
        ''' get the mixmode '''
        return 'newest'

    def connect_settingsui(self, qwidget: "QWidget", uihelp) -> None:
        ''' connect jriver local dir button '''
        self.qwidget = qwidget
        self.uihelp = uihelp

    def load_settingsui(self, qwidget: "QWidget") -> None:
        ''' draw the plugin's settings page '''
        qwidget.host_lineedit.setText(self.config.cparser.value('jriver/host') or '')
        qwidget.port_lineedit.setText(self.config.cparser.value('jriver/port') or '52199')
        qwidget.username_lineedit.setText(self.config.cparser.value('jriver/username') or '')
        qwidget.password_lineedit.setText(self.config.cparser.value('jriver/password') or '')
        qwidget.access_key_lineedit.setText(self.config.cparser.value('jriver/access_key') or '')

    def save_settingsui(self, qwidget: "QWidget") -> None:
        ''' take the settings page and save it '''
        self.config.cparser.setValue('jriver/host', qwidget.host_lineedit.text().strip())
        self.config.cparser.setValue('jriver/port', qwidget.port_lineedit.text().strip())
        self.config.cparser.setValue('jriver/username', qwidget.username_lineedit.text().strip())
        self.config.cparser.setValue('jriver/password', qwidget.password_lineedit.text().strip())
        self.config.cparser.setValue('jriver/access_key',
                                     qwidget.access_key_lineedit.text().strip())

    def desc_settingsui(self, qwidget: "QWidget") -> None:
        ''' description '''
        qwidget.setText('This plugin provides support for JRiver Media Center via MCWS API. '
                        'Configure the host/IP and port of your JRiver server. '
                        'Username/password are optional if authentication is not required. '
                        'File paths are automatically retrieved for local connections only '
                        '(localhost, private IPs, and .local/.lan/.home/.internal domains).')
