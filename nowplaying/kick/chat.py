#!/usr/bin/env python3
''' handle kick chat '''

import asyncio
import datetime
import logging
import pathlib
from typing import Any

import aiohttp
import jinja2
import nltk

from PySide6.QtCore import QCoreApplication, QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.config
import nowplaying.db
from nowplaying.exceptions import PluginVerifyError
import nowplaying.kick.oauth2

LASTANNOUNCED: dict[str, str | None] = {'artist': None, 'title': None}
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

        # Kick API endpoints
        self.api_base: str = "https://api.kick.com/public/v1"

        # Initialize NLTK for smart message splitting
        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            logging.info('Downloading NLTK punkt tokenizer for message splitting')
            nltk.download('punkt', quiet=True)

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
            elif refresh_token:
                # Try to refresh the token
                try:
                    await self.oauth.refresh_access_token(refresh_token)
                    self.authenticated = True
                    logging.info('Kick chat token refreshed successfully')
                    return True
                except Exception as error:
                    logging.warning('Failed to refresh Kick token: %s', error)

        logging.error('No valid Kick tokens available for chat')
        return False

    def _split_message_smart(self, message: str, max_length: int = KICK_MESSAGE_LIMIT) -> list[str]:
        ''' intelligently split long messages at sentence or word boundaries '''
        if len(message) <= max_length:
            return [message]

        messages = []

        try:
            # Try to split at sentence boundaries first
            sentences = nltk.sent_tokenize(message)
            current_chunk = ""

            for sentence in sentences:
                # If a single sentence is too long, split it at word boundaries
                if len(sentence) > max_length:
                    if current_chunk:
                        messages.append(current_chunk.strip())
                        current_chunk = ""

                    # Split long sentence at word boundaries
                    words = sentence.split()
                    word_chunk = ""
                    for word in words:
                        if len(word_chunk + " " + word) > max_length:
                            if word_chunk:
                                messages.append(word_chunk.strip())
                                word_chunk = word
                            else:
                                # Single word is too long, just truncate it
                                messages.append(word[:max_length-3] + "...")
                                word_chunk = ""
                        else:
                            word_chunk = word_chunk + " " + word if word_chunk else word

                    if word_chunk:
                        messages.append(word_chunk.strip())

                # Check if adding this sentence would exceed the limit
                elif len(current_chunk + " " + sentence) > max_length:
                    if current_chunk:
                        messages.append(current_chunk.strip())
                        current_chunk = sentence
                    else:
                        # Single sentence fits, but no room for more
                        messages.append(sentence.strip())
                else:
                    current_chunk = current_chunk + " " + sentence if current_chunk else sentence

            # Add any remaining text
            if current_chunk:
                messages.append(current_chunk.strip())

        except Exception as error:
            logging.warning('NLTK splitting failed, falling back to simple split: %s', error)
            # Fallback to simple word boundary splitting
            words = message.split()
            current_chunk = ""
            for word in words:
                if len(current_chunk + " " + word) > max_length:
                    if current_chunk:
                        messages.append(current_chunk.strip())
                        current_chunk = word
                    else:
                        messages.append(word[:max_length-3] + "...")
                        current_chunk = ""
                else:
                    current_chunk = current_chunk + " " + word if current_chunk else word

            if current_chunk:
                messages.append(current_chunk.strip())

        return [msg for msg in messages if msg.strip()]

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
        message_parts = self._split_message_smart(cleaned_message, KICK_MESSAGE_LIMIT)

        if len(message_parts) > 1:
            logging.info('Message split into %d parts for Kick limits', len(message_parts))

        # Send all message parts
        success = True
        for i, part in enumerate(message_parts):
            if not await self._send_single_message(part):
                success = False
                logging.error('Failed to send message part %d/%d', i+1, len(message_parts))

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
            logging.debug('Headers: %s', headers)

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, headers=headers, json=data) as response:
                    response_text = await response.text()
                    logging.debug('Send message API response: status=%s, body=%s', response.status,
                                  response_text)

                    if response.status in [200, 201]:
                        logging.info('Successfully sent message to Kick chat: "%s"', message)
                        return True
                    elif response.status == 401:
                        self.authenticated = False
                        logging.warning('Kick token expired while sending message')
                        return False
                    elif response.status == 403:
                        logging.error(
                            'Forbidden to send message - check bot permissions in channel')
                        return False
                    else:
                        logging.error('Failed to send message: %s - %s', response.status,
                                      response_text)
                        return False

        except Exception as error:
            logging.exception('Error sending message to Kick: %s', error)
            return False

    async def run_chat(self, oauth_handler: nowplaying.kick.oauth2.KickOAuth2) -> None:
        ''' main chat loop '''
        self.oauth = oauth_handler

        # Wait for chat to be enabled
        while not self.config.cparser.value('kick/chat', type=bool) and not self.stopevent.is_set():
            await asyncio.sleep(1)
            self.config.get()

        if self.stopevent.is_set():
            return

        connected = False
        while not self.stopevent.is_set():

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

            except Exception as error:
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
        self.watcher = self.metadb.watcher()
        self.watcher.start(customhandler=self._announce_track)
        await self._async_announce_track()
        while not self.stopevent.is_set():
            await asyncio.sleep(1)

        logging.debug('Kick chat watcher stop event received')
        self.watcher.stop()

    def _announce_track(self, event: Any) -> None:  # pylint: disable=unused-argument
        ''' handle track change announcements '''
        logging.debug('Kick chat watcher event called')
        try:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._async_announce_track())
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
            except Exception:  # pylint: disable=broad-except
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self._async_announce_track())
        except Exception as error:
            logging.exception('Kick chat announcement error: %s', error)

    async def _async_announce_track(self) -> None:
        ''' announce new tracks '''
        global LASTANNOUNCED

        try:
            self.config.get()

            if not self.authenticated:
                logging.debug('Kick chat not authenticated. Cannot announce.')
                return

            anntemplstr = self.config.cparser.value('kick/announce')
            if not anntemplstr:
                logging.debug('Kick announcement template is not defined.')
                return

            anntemplpath = pathlib.Path(anntemplstr)
            if not anntemplpath.exists():
                logging.error('Kick announcement template %s does not exist.', anntemplstr)
                return

            if not self.anndir or self.anndir != anntemplpath.parent:
                self.anndir = anntemplpath.parent
                self.jinja2ann = self.setup_jinja2(self.anndir)

            # Get current track metadata
            metadata = await self.metadb.read_last_meta_async()
            if not metadata:
                logging.debug('No metadata available for Kick announcement')
                return

            # Add startnewmessage support like Twitch
            if 'coverimageraw' in metadata:
                del metadata['coverimageraw']
            metadata['startnewmessage'] = SPLITMESSAGETEXT

            # Check if track changed
            if (LASTANNOUNCED['artist'] == metadata.get('artist')
                    and LASTANNOUNCED['title'] == metadata.get('title')):
                return

            # Update last announced
            LASTANNOUNCED['artist'] = metadata.get('artist')
            LASTANNOUNCED['title'] = metadata.get('title')

            # Generate announcement
            try:
                template = self.jinja2ann.get_template(anntemplpath.name)
                announcement = template.render(metadata)

                if announcement.strip():
                    await self._delay_write()

                    # Split message on startnewmessage tag like Twitch
                    messages = announcement.split(SPLITMESSAGETEXT)
                    for message_part in messages:
                        if message_part.strip():
                            await self._send_message(message_part.strip())

                    logging.info('Sent Kick chat announcement (%d parts)', len([m for m in messages if m.strip()]))

            except Exception as error:
                logging.exception('Error generating Kick announcement: %s', error)

        except Exception as error:
            logging.exception('Kick announcement error: %s', error)

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

        # Stop watcher
        if self.watcher:
            self.watcher.stop()

        self.authenticated = False


# Settings class for UI integration
class KickChatSettings:
    ''' Kick chat settings for UI '''

    def __init__(self) -> None:
        self.widget: Any = None

    def connect(self, uihelp: Any, widget: Any) -> None:
        ''' connect kick chat settings '''
        self.widget = widget
        # Connect any specific UI elements if needed

    def load(self, config: nowplaying.config.ConfigFile, widget: Any) -> None:
        ''' load kick chat settings '''
        self.widget = widget
        widget.chat_checkbox.setChecked(config.cparser.value('kick/chat', type=bool))
        widget.announce_lineedit.setText(config.cparser.value('kick/announce'))
        widget.announcedelay_spin.setValue(
            config.cparser.value('kick/announcedelay', type=float) or 1.0)

    @staticmethod
    def save(config: nowplaying.config.ConfigFile, widget: Any, subprocesses: Any) -> None:
        ''' save kick chat settings '''
        config.cparser.setValue('kick/chat', widget.chat_checkbox.isChecked())
        config.cparser.setValue('kick/announce', widget.announce_lineedit.text())
        config.cparser.setValue('kick/announcedelay', widget.announcedelay_spin.value())

    @staticmethod
    def verify(widget: Any) -> None:
        ''' verify kick chat settings '''
        if widget.chat_checkbox.isChecked():
            if not widget.announce_lineedit.text():
                raise PluginVerifyError(
                    'Kick announcement template is required when chat is enabled')
