#!/usr/bin/env python3
''' handle kick chat '''

import asyncio
import datetime
import logging
import pathlib
from typing import Any

import aiohttp
import jinja2

from PySide6.QtCore import QCoreApplication, QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.config
import nowplaying.db
import nowplaying.kick.oauth2
import nowplaying.utils

SPLITMESSAGETEXT = '****SPLITMESSSAGEHERE****'
KICK_MESSAGE_LIMIT = 500  # Character limit for Kick messages


class KickChat:  # pylint: disable=too-many-instance-attributes
    ''' handle kick chat '''

    def __init__(self,
                 config: nowplaying.config.ConfigFile | None = None,
                 stopevent: asyncio.Event | None = None) -> None:
        self.config = config
        self.stopevent = stopevent or asyncio.Event()
        self.watcher: Any = None
        self.metadb: nowplaying.db.MetadataDB = nowplaying.db.MetadataDB()
        self.templatedir = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0]).joinpath(
                QCoreApplication.applicationName(), 'templates')
        self.jinja2: jinja2.Environment = self.setup_jinja2(self.templatedir)
        self.jinja2ann: jinja2.Environment = self.setup_jinja2(self.templatedir)
        self.anndir: pathlib.Path | None = None
        self.oauth: nowplaying.kick.oauth2.KickOAuth2 | None = None
        self.tasks: set[asyncio.Task[Any]] = set()
        self.starttime: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)
        self.timeout: aiohttp.ClientTimeout = aiohttp.ClientTimeout(total=60)
        self.authenticated: bool = False
        self._watcher_lock: asyncio.Lock = asyncio.Lock()
        self._watcher_running: bool = False
        self.last_announced: dict[str, str | None] = {'artist': None, 'title': None}

        # Kick API endpoints
        self.api_base: str = "https://api.kick.com/public/v1"

    async def _authenticate(self) -> bool:
        ''' authenticate with kick using stored tokens '''
        if not self.oauth:
            self.oauth = nowplaying.kick.oauth2.KickOAuth2(self.config)

        # Check if we have valid tokens
        access_token, refresh_token = self.oauth.get_stored_tokens()
        if access_token:
            # Validate the token
            validation_result = await self.oauth.validate_token(access_token)
            if validation_result:
                self.authenticated = True
                logging.info('Kick chat authentication successful')
                return True

            if refresh_token:
                # Try to refresh the token
                try:
                    await self.oauth.refresh_access_token(refresh_token)
                    self.authenticated = True
                    logging.info('Kick chat token refreshed successfully')
                    return True
                except Exception as error:# pylint: disable=broad-exception-caught
                    logging.warning('Failed to refresh Kick token: %s', error)

        logging.error('No valid Kick tokens available for chat')
        return False

    async def _send_message(self, message: str) -> bool:
        ''' send a message to kick chat using official API '''
        logging.info('Attempting to send message to Kick chat: "%s"', message)

        if not self.authenticated:
            logging.error('Cannot send message: not authenticated')
            return False

        access_token, _ = self.oauth.get_stored_tokens()
        if not access_token:
            logging.error('Cannot send message: no access token')
            return False

        # Clean up message content to avoid JSON issues
        if not message or not message.strip():
            logging.warning('Empty message content, skipping send')
            return False

        # Remove control characters and ensure valid UTF-8
        cleaned_message = ''.join(char for char in message if ord(char) >= 32 or char in '\n\r\t')

        # Use smart splitting instead of truncation
        message_parts = nowplaying.utils.smart_split_message(cleaned_message, KICK_MESSAGE_LIMIT)

        if len(message_parts) > 1:
            logging.info('Message split into %d parts for Kick limits', len(message_parts))

        # Send all message parts with rate limiting
        success = True
        for i, part in enumerate(message_parts):
            if not await self._send_single_message(part):
                success = False
                logging.error('Failed to send message part %d/%d', i + 1, len(message_parts))

            # Add delay between message parts to avoid rate limiting/spam detection
            # Skip delay after the last message
            if i < len(message_parts) - 1:
                await asyncio.sleep(1.0)  # 1 second delay between parts

        return success

    async def _send_single_message(self, message: str) -> bool:
        ''' send a single message to kick chat (internal method) '''
        access_token, _ = self.oauth.get_stored_tokens()
        if not access_token:
            return False

        try:
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }

            # Use correct Kick API format from documentation
            # For bots: broadcaster_user_id is not required, type should be 'bot'
            data = {'content': message, 'type': 'bot'}

            url = f"{self.api_base}/chat"  # POST /public/v1/chat
            logging.debug('Sending message to: %s', url)
            logging.debug('Message content: %r', message)
            logging.debug('Message data: %s', data)
            # Log headers with sensitive data redacted
            safe_headers = {k: ('Bearer ***' if k == 'Authorization' and v.startswith('Bearer ')
                               else v) for k, v in headers.items()}
            logging.debug('Headers: %s', safe_headers)

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, headers=headers, json=data) as response:
                    response_text = await response.text()
                    logging.debug('Send message API response: status=%s, body=%s', response.status,
                                  response_text)

                    if response.status in [200, 201]:
                        logging.info('Successfully sent message to Kick chat: "%s"', message)
                        return True

                    if response.status == 401:
                        self.authenticated = False
                        logging.warning('Kick token expired while sending message')
                        return False

                    if response.status == 403:
                        logging.error(
                            'Forbidden to send message - check bot permissions in channel')
                        return False

                    logging.error('Failed to send message: %s - %s', response.status,
                                  response_text)
                    return False

        except Exception as error: # pylint: disable=broad-exception-caught
            logging.exception('Error sending message to Kick: %s', error)
            return False

    async def run_chat(self, oauth_handler: nowplaying.kick.oauth2.KickOAuth2) -> None:
        ''' main chat loop '''
        self.oauth = oauth_handler

        # Wait for chat to be enabled
        while (not self.config.cparser.value('kick/chat', type=bool) and 
               not nowplaying.utils.safe_stopevent_check(self.stopevent)):
            await asyncio.sleep(1)
            self.config.get()

        if nowplaying.utils.safe_stopevent_check(self.stopevent):
            return

        connected = False
        while not nowplaying.utils.safe_stopevent_check(self.stopevent):

            if connected and not self.authenticated:
                logging.error('Lost Kick authentication')
                connected = False

            if connected:
                await asyncio.sleep(60)
                continue

            try:
                # Authenticate
                if not await self._authenticate():
                    await asyncio.sleep(60)
                    continue

                # Get channel name for display purposes
                channel_name: str = self.config.cparser.value('kick/channel')
                if not channel_name:
                    logging.error('No Kick channel configured')
                    await asyncio.sleep(60)
                    continue

                logging.info('Successfully authenticated with Kick. Channel: %s', channel_name)

                # Send test message to verify connection
                test_message = f'🤖 Kick bot connected! Now monitoring {channel_name} for commands.'
                test_sent = await self._send_message(test_message)
                if test_sent:
                    logging.info('Test message sent successfully to Kick chat')
                else:
                    logging.warning('Failed to send test message to Kick chat')

                connected = True

                # Start announcement timer only (no chat polling)
                loop = asyncio.get_running_loop()

                # Announcement timer
                task = loop.create_task(self._setup_timer())
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)

                logging.info('Kick chat announcements enabled for channel: %s', channel_name)

            except Exception as error: # pylint: disable=broad-exception-caught
                logging.exception('Kick chat error: %s', error)
                await asyncio.sleep(60)
                continue

    @staticmethod
    def _finalize(variable: Any) -> str:
        ''' helper routine to avoid NoneType exceptions '''
        if variable:
            return variable
        return ''

    def setup_jinja2(self, directory: pathlib.Path) -> jinja2.Environment:
        ''' set up the jinja2 environment '''
        return jinja2.Environment(loader=jinja2.FileSystemLoader(directory),
                                  finalize=self._finalize,
                                  trim_blocks=True)

    async def _setup_timer(self) -> None:
        ''' setup announcement timer '''
        async with self._watcher_lock:
            # Prevent multiple watcher instances with proper synchronization
            if self._watcher_running:
                logging.debug('Kick chat watcher already running, skipping setup')
                return

            if self.watcher is not None:
                logging.debug('Kick chat watcher already exists, stopping previous instance')
                self.watcher.stop()
                self.watcher = None

            self.watcher = self.metadb.watcher()
            self.watcher.start(customhandler=self._announce_track)
            self._watcher_running = True

        await self._process_announcement()
        while not nowplaying.utils.safe_stopevent_check(self.stopevent):
            await asyncio.sleep(1)

        logging.debug('Kick chat watcher stop event received')
        async with self._watcher_lock:
            if self.watcher:
                self.watcher.stop()
                self.watcher = None
            self._watcher_running = False

    def _announce_track(self, event: Any) -> None:  # pylint: disable=unused-argument
        ''' handle track change announcements '''
        logging.debug('Kick chat watcher event called')
        try:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._process_announcement())
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
            except Exception:  # pylint: disable=broad-exception-caught
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self._process_announcement())
        except Exception as error: # pylint: disable=broad-exception-caught
            logging.exception('Kick chat announcement error: %s', error)

    async def _process_announcement(self) -> None:
        ''' process track announcement logic '''

        self.config.get()

        if not self.authenticated:
            logging.debug('Kick chat not authenticated. Cannot announce.')
            return

        template_path = self._get_announcement_template()
        if not template_path:
            return

        metadata = await self._prepare_metadata()
        if not metadata:
            return

        if self._is_duplicate_announcement(metadata):
            return

        self._update_last_announced(metadata)
        await self._send_announcement(template_path, metadata)

    def _get_announcement_template(self) -> pathlib.Path | None:
        ''' get and validate announcement template '''
        anntemplstr = self.config.cparser.value('kick/announce')
        if not anntemplstr:
            logging.debug('Kick announcement template is not defined.')
            return None

        anntemplpath = pathlib.Path(anntemplstr)
        if not anntemplpath.exists():
            logging.error('Kick announcement template %s does not exist.', anntemplstr)
            return None

        if not self.anndir or self.anndir != anntemplpath.parent:
            self.anndir = anntemplpath.parent
            self.jinja2ann = self.setup_jinja2(self.anndir)

        return anntemplpath

    async def _prepare_metadata(self) -> dict | None:
        ''' prepare metadata for announcement '''
        metadata = await self.metadb.read_last_meta_async()
        if not metadata:
            logging.debug('No metadata available for Kick announcement')
            return None

        # Add startnewmessage support like Twitch
        if 'coverimageraw' in metadata:
            del metadata['coverimageraw']
        metadata['startnewmessage'] = SPLITMESSAGETEXT
        return metadata


    def _is_duplicate_announcement(self, metadata: dict) -> bool:
        ''' check if this is a duplicate announcement '''
        return (self.last_announced['artist'] == metadata.get('artist')
                and self.last_announced['title'] == metadata.get('title'))


    def _update_last_announced(self, metadata: dict) -> None:
        ''' update last announced track '''
        self.last_announced['artist'] = metadata.get('artist')
        self.last_announced['title'] = metadata.get('title')


    async def _send_announcement(self, template_path: pathlib.Path, metadata: dict) -> None:
        ''' generate and send announcement '''
        try:
            template = self.jinja2ann.get_template(template_path.name)
            announcement = template.render(metadata)

            if not announcement.strip():
                return

            await self._delay_write()
            sent_parts = await self._send_announcement_parts(announcement)
            logging.info('Sent Kick chat announcement (%d parts)', sent_parts)

        except Exception as error: # pylint: disable=broad-exception-caught
            logging.exception('Error generating Kick announcement: %s', error)

    async def _send_announcement_parts(self, announcement: str) -> int:
        ''' send announcement parts with rate limiting '''
        messages = announcement.split(SPLITMESSAGETEXT)
        sent_parts = 0

        for i, message_part in enumerate(messages):
            stripped_part = message_part.strip()
            if not stripped_part:
                continue

            await self._send_message(stripped_part)
            sent_parts += 1

            # Add delay between announcement parts to avoid rate limiting
            if i < len(messages) - 1:
                await asyncio.sleep(1.5)  # Slightly longer delay for announcements

        return sent_parts

    async def _delay_write(self) -> None:
        ''' handle the kick chat delay '''
        try:
            delay = self.config.cparser.value('kick/announcedelay', type=float, defaultValue=1.0)
        except ValueError:
            delay = 1.0
        logging.debug('Kick chat delay: %s seconds', delay)
        await asyncio.sleep(delay)

    async def stop(self) -> None:
        ''' stop kick chat '''
        logging.debug('Stopping Kick chat')

        # Cancel all tasks
        for task in self.tasks:
            task.cancel()

        # Stop watcher and clear reference with proper synchronization
        async with self._watcher_lock:
            if self.watcher:
                self.watcher.stop()
                self.watcher = None
            self._watcher_running = False

        self.authenticated = False
