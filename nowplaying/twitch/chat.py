#!/usr/bin/env python3
# pylint: disable=too-many-lines
"""handle twitch chat"""

import asyncio
import datetime
import fnmatch
import logging
import os
import pathlib
import platform
import socket
import traceback
from typing import Any

import aiohttp  # pylint: disable=import-error
import aiohttp.client_exceptions
import jinja2  # pylint: disable=import-error
from PySide6.QtCore import (  # pylint: disable=import-error, no-name-in-module
    QCoreApplication,
    QStandardPaths,
    Slot,
)
from PySide6.QtWidgets import (  # pylint: disable=import-error, no-name-in-module
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
)
from twitchAPI.chat import (  # pylint: disable=import-error
    Chat,
    ChatCommand,
    ChatEvent,
    ChatMessage,
)
from twitchAPI.oauth import validate_token  # pylint: disable=import-error
from twitchAPI.twitch import Twitch  # pylint: disable=import-error
from twitchAPI.type import AuthScope  # pylint: disable=import-error

import nowplaying.config
import nowplaying.db
import nowplaying.guessgame
import nowplaying.inputs
import nowplaying.pluginimporter
import nowplaying.trackrequests
import nowplaying.twitch.oauth2
import nowplaying.twitch.utils
import nowplaying.utils
from nowplaying.exceptions import PluginVerifyError
from nowplaying.twitch.constants import (
    SPLITMESSAGETEXT,
    TWITCH_MESSAGE_LIMIT,
    TWITCHBOT_CHECKBOXES,
)
from nowplaying.types import TrackMetadata

LASTANNOUNCED = {"artist": None, "title": None}


class TwitchChat:  # pylint: disable=too-many-instance-attributes
    """handle twitch chat"""

    def __init__(
        self, config: "nowplaying.config.ConfigFile" = None, stopevent: asyncio.Event = None
    ):
        self.config = config
        self.stopevent = stopevent
        self.watcher = None
        self.requests = nowplaying.trackrequests.Requests(config=config, stopevent=stopevent)
        self.guessgame = nowplaying.guessgame.GuessGame(config=config, stopevent=stopevent)
        self.metadb = nowplaying.db.MetadataDB()
        self.templatedir = pathlib.Path(
            QStandardPaths.standardLocations(QStandardPaths.DocumentsLocation)[0]
        ).joinpath(QCoreApplication.applicationName(), "templates")
        self.jinja2 = self.setup_jinja2(self.templatedir)
        self.jinja2ann = self.setup_jinja2(self.templatedir)
        self.anndir: pathlib.Path | str | None = None
        self.twitch: Twitch = None
        self.twitchcustom = False
        self.chat = None
        self.tasks = set()
        self.starttime = datetime.datetime.now(datetime.timezone.utc)
        self.timeout = aiohttp.ClientTimeout(total=60)
        self.modernmeerkat_greeted = False

        self.input: nowplaying.inputs.InputPlugin | None = None
        self.previousinput: str | None = None
        self.plugins: dict = {}

    def _setup_input_plugins(self):
        """Initialize input plugins (without starting them) - called lazily"""
        if not self.plugins:
            self.plugins = nowplaying.pluginimporter.import_plugins(nowplaying.inputs)

    async def switch_input_plugin(self):
        """Handle user switching source input while running (without starting the plugin)"""
        # Lazy initialization - only setup plugins when actually needed
        self._setup_input_plugins()

        if not self.previousinput or self.previousinput != self.config.cparser.value(
            "settings/input"
        ):
            if self.input:
                logging.debug("Switching from %s input plugin", self.previousinput)

            self.previousinput: str | None = self.config.cparser.value("settings/input")
            if not self.previousinput:
                self.input = None
                return False

            self.input = self.plugins[f"nowplaying.inputs.{self.previousinput}"].Plugin(
                config=self.config
            )
            logging.debug("Switched to %s input plugin (not started)", self.previousinput)
            if not self.input:
                return False

        return True

    async def _token_validation(self):
        """check for separate chat token (for bot accounts)"""
        token = self.config.cparser.value("twitchbot/chattoken")
        if not token:
            return None

        # Clean up legacy oauth: prefix
        token = self._clean_token_format(token)

        logging.debug("validating separate chat token")
        try:
            valid = await validate_token(token)
            if valid.get("status") == 401:
                logging.debug("Chat token expired, attempting refresh")
                return await self._refresh_chat_token()
        except Exception as error:  # pylint: disable=broad-except
            logging.error("cannot validate chat token: %s", error)
            return None

        return token

    def _clean_token_format(self, token: str) -> str:
        """Remove legacy oauth: prefix from token"""
        if "oauth:" in token:
            token = token.replace("oauth:", "")
            self.config.cparser.setValue("twitchbot/chattoken", token)
        return token

    async def _refresh_chat_token(self) -> str | None:
        """Attempt to refresh the chat token"""
        chat_refresh_token: str = self.config.cparser.value("twitchbot/chatrefreshtoken")
        if not chat_refresh_token:
            self._clear_expired_chat_token()
            logging.error("Chat token expired and no refresh token available")
            return None

        try:
            oauth = nowplaying.twitch.oauth2.TwitchOAuth2(self.config)
            token_response = await oauth.refresh_access_token_async(chat_refresh_token)
            return self._save_refreshed_chat_tokens(token_response)
        except Exception as refresh_error:  # pylint: disable=broad-except
            logging.error("Failed to refresh chat token: %s", refresh_error)
            self._clear_invalid_chat_tokens()
            return None

    def _save_refreshed_chat_tokens(self, token_response: dict[str, str]) -> str | None:
        """Save refreshed chat tokens to config"""
        new_access_token = token_response.get("access_token")
        new_refresh_token = token_response.get("refresh_token")

        if not new_access_token:
            self._clear_invalid_chat_tokens()
            logging.error("Chat token refresh failed - no access token")
            return None

        self.config.cparser.setValue("twitchbot/chattoken", new_access_token)
        if new_refresh_token:
            self.config.cparser.setValue("twitchbot/chatrefreshtoken", new_refresh_token)
        self.config.save()
        logging.info("Successfully refreshed chat token")
        return new_access_token

    def _clear_expired_chat_token(self) -> None:
        """Clear expired chat token (but keep refresh token)"""
        self.config.cparser.remove("twitchbot/chattoken")
        self.config.save()

    def _clear_invalid_chat_tokens(self) -> None:
        """Clear all invalid chat tokens from config"""
        self.config.cparser.remove("twitchbot/chattoken")
        self.config.cparser.remove("twitchbot/chatrefreshtoken")
        self.config.save()

    async def _try_custom_token(self, token: str):
        """if a custom token has been provided, try it."""
        if self.twitch and self.twitchcustom:
            await self.twitch.close()
        if token:
            try:
                tokenval = await validate_token(token)
                if tokenval.get("status") == 401:
                    logging.error(tokenval["message"])
                else:
                    # don't really care if the token's clientid
                    # doesn't match the given clientid since
                    # Chat() never uses the clientid other than
                    # to do a user lookup
                    self.twitchcustom = False
                    self.twitch = await Twitch(
                        tokenval["client_id"], authenticate_app=False, session_timeout=self.timeout
                    )
                    self.twitch.auto_refresh_auth = False
                    await self.twitch.set_user_authentication(
                        token=token,
                        scope=[AuthScope.CHAT_READ, AuthScope.CHAT_EDIT],
                        validate=False,
                    )
                    self.twitchcustom = True
            except Exception:  # pylint: disable=broad-except
                for line in traceback.format_exc().splitlines():
                    logging.error(line)

    async def run_chat(self, twitchlogin: nowplaying.twitch.utils.TwitchLogin):
        """Main twitch chat loop - manages authentication and connection"""
        # Wait for chat to be enabled
        await self._wait_for_chat_enabled()

        if nowplaying.utils.safe_stopevent_check(self.stopevent):
            return

        # Reset guess game session scores
        if self.guessgame:
            try:
                await self.guessgame.reset_session()
                logging.info("Guess game session reset")
            except Exception as error:  # pylint: disable=broad-except
                logging.error("Failed to reset guess game session: %s", error)

        loggedin = False
        while not nowplaying.utils.safe_stopevent_check(self.stopevent):
            # Check connection status
            if await self._check_connection_status(loggedin):
                await self.stop()
                loggedin = False

            # Handle logged-in state
            if loggedin:
                if await self._handle_logged_in_state():
                    loggedin = False
                    continue
                continue

            # Attempt authentication and setup
            try:
                if await self._authenticate_and_setup_chat(twitchlogin):
                    loggedin = True
                    await self._start_chat_monitoring()
                else:
                    await asyncio.sleep(60)
            except (aiohttp.client_exceptions.ClientConnectorError, socket.gaierror) as error:
                logging.error(error)
                await asyncio.sleep(60)
            except Exception:  # pylint: disable=broad-except
                for line in traceback.format_exc().splitlines():
                    logging.error(line)
                await asyncio.sleep(60)

        await self._cleanup_on_exit(twitchlogin)

    async def _wait_for_chat_enabled(self) -> None:
        """Wait for chat to be enabled in configuration"""
        while not self.config.cparser.value(
            "twitchbot/chat", type=bool
        ) and not nowplaying.utils.safe_stopevent_check(self.stopevent):
            await asyncio.sleep(1)
            self.config.get()

    async def _check_connection_status(self, loggedin: bool) -> bool:
        """Check if we've lost connection and need to reconnect"""
        if loggedin and self.chat and not self.chat.is_connected():
            logging.error("No longer logged into chat")
            return True
        return False

    async def _handle_logged_in_state(self) -> bool:
        """Handle periodic checks when logged in, returns True if reconnection needed"""
        await asyncio.sleep(60)

        # Check if a new chat token was added while we were using OAuth2
        if not self.twitchcustom:  # Only if we're using OAuth2, not custom token
            new_chat_token = await self._token_validation()
            if new_chat_token:
                logging.info("New chat token detected - switching to bot account")
                await self.stop()
                return True  # Need to reconnect
        return False

    async def _authenticate_and_setup_chat(
        self, twitchlogin: nowplaying.twitch.utils.TwitchLogin
    ) -> bool:
        """Try all authentication methods and setup chat if successful"""
        # Try authentication methods in priority order
        if not await self._try_authentication_methods(twitchlogin):
            logging.error("No valid credentials to start Twitch Chat support.")
            return False

        # Validate channel configuration
        channel = self.config.cparser.value("twitchbot/channel")
        if not channel or not channel.strip():
            logging.error("Twitch channel not configured. Cannot start chat support.")
            return False

        # Setup chat connection and commands
        await self._setup_chat_connection(channel.strip())
        return True

    async def _try_authentication_methods(
        self, twitchlogin: nowplaying.twitch.utils.TwitchLogin
    ) -> bool:
        """Try authentication methods in priority order"""
        # First priority: Try separate chat token (for bot accounts)
        token = await self._token_validation()
        if token:
            logging.debug("attempting to use separate chat token")
            await self._try_custom_token(token)
            if self.twitch:
                return True

        # Second priority: Try OAuth2 tokens (unified single account)
        if await self._try_oauth2_authentication():
            return True

        # Third priority: Try main login
        logging.debug("attempting to use main login")
        self.twitch = await twitchlogin.api_login()
        self.twitchcustom = False
        if self.twitch:
            return True

        # If all fail, clear cached tokens
        await twitchlogin.cache_token_del()
        return False

    async def _try_oauth2_authentication(self) -> bool:
        """Try OAuth2 token authentication"""
        logging.debug("attempting to use OAuth2 token")
        oauth = nowplaying.twitch.oauth2.TwitchOAuth2(self.config)
        access_token, _ = oauth.get_stored_tokens()

        if access_token and nowplaying.twitch.oauth2.TwitchOAuth2.validate_token_sync(
            access_token, return_username=False
        ):
            logging.debug("Using OAuth2 token for chat")
            await self._try_custom_token(access_token)
            return self.twitch is not None
        return False

    async def _setup_chat_connection(self, channel: str) -> None:
        """Setup chat connection with event handlers and commands"""
        self.chat = await Chat(self.twitch, initial_channel=[channel])
        self.chat.register_event(ChatEvent.MESSAGE, self.on_twitchchat_incoming_message)
        self.chat.register_command(
            "whatsnowplayingversion", self.on_twitchchat_whatsnowplayingversion
        )

        # Register custom commands from configuration
        for configitem in self.config.cparser.childGroups():
            if "twitchbot-command-" in configitem:
                command = configitem.replace("twitchbot-command-", "")
                self.chat.register_command(command, self.on_twitchchat_message)

        self.chat.start()

    async def _start_chat_monitoring(self) -> None:
        """Start the chat monitoring task"""
        try:
            loop = asyncio.get_running_loop()
        except Exception as error:  # pylint: disable=broad-except
            logging.error(error)
            await asyncio.sleep(10)
            return

        await asyncio.sleep(1)
        task = loop.create_task(self._setup_timer())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _cleanup_on_exit(self, twitchlogin: nowplaying.twitch.utils.TwitchLogin) -> None:
        """Clean up resources when exiting"""
        if self.twitch:
            if self.twitchcustom:
                await self.twitch.close()
            else:
                await twitchlogin.api_logout()

    async def on_twitchchat_incoming_message(self, msg: ChatMessage):
        """handle incoming chat messages for special responses"""
        # Check for modernmeerkat greeting (once per program launch)
        if not self.modernmeerkat_greeted and msg.user.display_name.lower() == "modernmeerkat":
            self.modernmeerkat_greeted = True
            try:
                await self.chat.send_message(
                    self.config.cparser.value("twitchbot/channel"),
                    f"Hello @{msg.user.display_name}",
                )
                logging.info("Greeted modernmeerkat user: %s", msg.user.display_name)
            except Exception as error:  # pylint: disable=broad-except
                logging.error("Failed to send modernmeerkat greeting: %s", error)

    async def on_twitchchat_message(self, msg: ChatMessage):
        """twitch chatbot incoming message"""
        self.config.get()
        commandchar = self.config.cparser.value("twitchbot/commandchar")
        if not commandchar:
            commandchar = "!"
            self.config.cparser.setValue("twitchbot/commandchar", "!")
        if msg.text[:1] == commandchar:
            await self.do_command(msg)

    async def on_twitchchat_whatsnowplayingversion(self, cmd: ChatCommand):
        """handle !whatsnowplayingversion"""
        inputsource = self.config.cparser.value("settings/input")
        delta = datetime.datetime.now(datetime.timezone.utc) - self.starttime
        plat = platform.platform()
        content = (
            f"whatsnowplaying v{self.config.version} by @modernmeerkat. "
            f"Using {inputsource} on {plat}. Running for {delta}."
        )
        try:
            await cmd.reply(content)
        except Exception:  # pylint: disable=broad-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            await self.chat.send_message(self.config.cparser.value("twitchbot/channel"), content)

    def check_command_perms(self, profile: dict, command: str):
        """given the profile, check if the command is allowed to be executed"""
        self.config.get()

        # shortcut the 'anyone' commands
        if self.config.cparser.value(f"twitchbot-command-{command}/anyone", type=bool):
            return True

        self.config.cparser.beginGroup(f"twitchbot-command-{command}")
        perms = {
            key: self.config.cparser.value(key, type=bool)
            for key in self.config.cparser.childKeys()
        }
        self.config.cparser.endGroup()

        if perms:
            for usertype, allowed in perms.items():
                try:
                    if allowed and profile.get(usertype) and int(profile[usertype]) > 0:
                        return True
                except (TypeError, ValueError):
                    logging.error(
                        "Unexpected value for user badge: %s = %s", usertype, profile[usertype]
                    )
            return False
        return True

    async def do_command(  # pylint: disable=unused-argument,too-many-branches
        self, msg: ChatMessage
    ):
        """process a command"""

        commandchar = self.config.cparser.value("twitchbot/commandchar") or "!"
        metadata = {"cmduser": msg.user.display_name, "cmdchar": commandchar}
        commandlist = msg.text[1:].split()
        metadata["cmdname"] = commandlist[0] if commandlist else ""
        metadata["cmdtarget"] = []
        if len(commandlist) > 1:
            for usercheck in commandlist[1:]:
                if usercheck[0] == "@":
                    metadata["cmdtarget"].append(usercheck[1:])
                else:
                    metadata["cmdtarget"].append(usercheck)

        # Check if this is a help request: first and only parameter matches help keyword
        help_keyword: str = self.config.cparser.value(
            "twitchbot/helpkeyword", defaultValue="help", type=str
        )
        help_keyword = help_keyword.lower()
        is_help_request = len(commandlist) == 2 and commandlist[1].lower() == help_keyword

        if is_help_request:
            cmdfile = f"twitchbot_{commandlist[0]}_{help_keyword}.txt"
        else:
            cmdfile = f"twitchbot_{commandlist[0]}.txt"

        if not self.check_command_perms(msg.user.badges, commandlist[0]):
            return

        # Handle guess game commands
        guess_command = self.config.cparser.value(
            "guessgame/command", defaultValue="guess", type=str
        )
        stats_command = self.config.cparser.value(
            "guessgame/statscommand", defaultValue="mystats", type=str
        )

        if commandlist[0].lower() == guess_command.lower() and not is_help_request:
            if reply := await self.handle_guess(commandlist[1:], msg.user.display_name):
                metadata |= reply
        elif commandlist[0].lower() == stats_command.lower() and not is_help_request:
            if reply := await self.handle_guessstats(msg.user.display_name):
                metadata |= reply

        # Only process track requests if this is NOT a help request
        if (
            not is_help_request
            and self.config.cparser.value("settings/requests", type=bool)
            and self.config.cparser.value("twitchbot/chatrequests", type=bool)
        ):
            if reply := await self.handle_request(
                commandlist[0], commandlist[1:], msg.user.display_name
            ):
                metadata |= reply

        await self._post_template(msg=msg, templatein=cmdfile, moremetadata=metadata)

    async def redemption_to_chat_request_bridge(self, command: ChatCommand, reqdata):
        """respond in chat when a redemption request triggers"""
        if self.config.cparser.value(
            "twitchbot/chatrequests", type=bool
        ) and self.config.cparser.value("twitchbot/chat", type=bool):
            cmdfile = f"twitchbot_{command}.txt"
            await self._post_template(templatein=cmdfile, moremetadata=reqdata)

    async def handle_request(self, command: str, params, username: str):  # pylint: disable=unused-argument
        """handle the channel point redemption"""
        reply = None
        logging.debug("got command: %s", command)
        commandlist = " ".join(params)
        if commandlist:
            logging.debug("got commandlist: %s", commandlist)
        if setting := await self.requests.find_command(command):
            logging.debug("Found setting for command %s: %s", command, setting)
            try:
                setting["userimage"] = await nowplaying.twitch.utils.get_user_image(
                    self.twitch, username
                )
            except Exception as err:  # pylint: disable=broad-except
                logging.debug("Failed to get user image for %s: %s", username, err)
                setting["userimage"] = None
            if setting.get("type") == "Generic":
                reply = await self.requests.user_track_request(setting, username, commandlist)
            elif setting.get("type") == "Roulette":
                reply = await self.requests.user_roulette_request(
                    setting, username, commandlist[1:]
                )
            elif setting.get("type") == "GifWords":
                reply = await self.requests.gifwords_request(setting, username, commandlist)
            elif setting.get("type") == "ArtistQuery":
                logging.debug("Calling artist_query_request for %s", commandlist)
                reply = await self.requests.artist_query_request(setting, username, commandlist)
        return reply

    async def handle_guess(self, params: list, username: str) -> dict | None:
        """Handle guess game command"""
        if not self.guessgame:
            return None

        if not params:
            return {"guess_error": "Please provide a guess (letter or word)"}

        guess_text = " ".join(params)
        result = await self.guessgame.process_guess(username, guess_text)

        if not result:
            return {"guess_error": "No active game right now"}

        # Build response metadata for template
        response = {
            "guess_user": username,
            "guess_text": guess_text,
            "guess_correct": result["correct"],
            "guess_points": result["points"],
            "guess_type": result["guess_type"],
            "guess_masked_track": result["masked_track"],
            "guess_masked_artist": result["masked_artist"],
            "guess_solved": result["solved"],
            "guess_solve_type": result.get("solve_type"),
            "guess_track_solved": result.get("track_solved", False),
            "guess_artist_solved": result.get("artist_solved", False),
        }

        if result.get("already_guessed"):
            response["guess_already_guessed"] = True

        if result["guess_type"] == "already_solved":
            response["guess_already_solved"] = True

        return response

    async def handle_guessstats(self, username: str) -> dict | None:
        """Handle stats request command"""
        if not self.guessgame:
            return None

        stats = await self.guessgame.get_user_stats(username)

        if not stats:
            return {"stats_user": username, "stats_none": True}

        return {
            "stats_user": username,
            "stats_session_score": stats["session_score"],
            "stats_all_time_score": stats["all_time_score"],
            "stats_session_solves": stats["session_solves"],
            "stats_all_time_solves": stats["all_time_solves"],
            "stats_session_guesses": stats["session_guesses"],
            "stats_all_time_guesses": stats["all_time_guesses"],
        }

    @staticmethod
    def _finalize(variable: Any) -> Any | str:
        """helper routine to avoid NoneType exceptions"""
        if variable is not None:
            return variable
        return ""

    def setup_jinja2(self, directory: str | pathlib.Path) -> jinja2.Environment:
        """set up the environment"""
        return jinja2.Environment(
            loader=jinja2.FileSystemLoader(directory), finalize=self._finalize, trim_blocks=True
        )

    async def _setup_timer(self):
        """need to watch the metadata db to know to send announcement"""
        # Prevent multiple watcher instances
        if self.watcher is not None:
            logging.debug("Twitch chat watcher already exists, stopping previous instance")
            self.watcher.stop()
            self.watcher = None

        self.watcher = self.metadb.watcher()
        self.watcher.start(customhandler=self._announce_track)
        await self._async_announce_track()
        while not nowplaying.utils.safe_stopevent_check(self.stopevent):
            await asyncio.sleep(1)

        logging.debug("watcher stop event received")
        if self.watcher:
            self.watcher.stop()
            self.watcher = None

    async def _delay_write(self):
        """handle the twitch chat delay"""
        try:
            delay = self.config.cparser.value(
                "twitchbot/announcedelay", type=float, defaultValue=1.0
            )
        except ValueError:
            delay = 1.0
        logging.debug("got delay of %s", delay)
        await asyncio.sleep(delay)

    @staticmethod
    def _split_message_smart(message: str, max_length: int = TWITCH_MESSAGE_LIMIT) -> list[str]:
        """intelligently split long messages at sentence or word boundaries"""
        return nowplaying.utils.smart_split_message(message, max_length)

    def _announce_track(self, event):  # pylint: disable=unused-argument
        logging.debug("watcher event called")
        try:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._async_announce_track())
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
            except Exception:  # pylint: disable=broad-except
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self._async_announce_track())
        except Exception:  # pylint: disable=broad-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            logging.error("watcher failed")

    async def _async_announce_track(self):
        """announce new tracks"""
        global LASTANNOUNCED  # pylint: disable=global-statement, global-variable-not-assigned

        try:
            self.config.get()

            if self.chat and not self.chat.is_connected():
                logging.error("Twitch chat is not connected. Cannot announce.")
                return

            anntemplstr: str = self.config.cparser.value("twitchbot/announce")
            if not anntemplstr:
                logging.error("Announcement template is not defined.")
                return

            anntemplpath = pathlib.Path(anntemplstr)
            if not anntemplpath.exists():
                logging.error("Announcement template %s does not exist.", anntemplstr)
                return

            if not self.anndir or self.anndir != anntemplpath.parent:
                self.anndir = anntemplpath.parent
                self.jinja2ann = self.setup_jinja2(self.anndir)

            metadata = await self.metadb.read_last_meta_async()

            if not metadata:
                logging.debug("No metadata to announce")
                return

            # don't announce empty content
            if not metadata["artist"] and not metadata["title"]:
                logging.warning("Both artist and title are empty; skipping announcement")
                return

            if (
                metadata["artist"] == LASTANNOUNCED["artist"]
                and metadata["title"] == LASTANNOUNCED["title"]
            ):
                logging.warning(
                    "Same artist and title or doubled event notification; skipping announcement."
                )
                return

            LASTANNOUNCED["artist"] = metadata["artist"]
            LASTANNOUNCED["title"] = metadata["title"]

            await self._delay_write()

            logging.info("Announcing %s", anntemplpath)

            await self._post_template(templatein=anntemplpath, jinja2driver=self.jinja2ann)
        except Exception:  # pylint: disable=broad-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)

    async def _post_template(
        self,
        msg: ChatMessage | None = None,
        templatein: str | pathlib.Path = None,
        moremetadata: dict[str, Any] | None = None,
        jinja2driver: jinja2.Environment | None = None,
    ) -> None:
        """take a template, fill it in, and post it"""
        # Validate inputs and setup
        if not self._validate_template_inputs(templatein):
            logging.warning("No template input provided to _post_template; skipping post.")
            return

        jinja2driver = jinja2driver or self.jinja2

        # Prepare metadata
        metadata = await self._prepare_template_metadata(moremetadata)

        # Get template name
        template = self._resolve_template_name(templatein)
        if not template:
            return

        if message := self._render_template(template, metadata, jinja2driver):
            # Send messages
            await self._send_template_messages(message, msg)

    def _validate_template_inputs(self, templatein: Any) -> bool:
        """Validate template posting inputs"""
        if not templatein:
            return False
        if not self.chat:
            logging.debug("Twitch chat is not configured?!?")
            return False
        return True

    async def _prepare_template_metadata(self, moremetadata: dict[str, str]) -> TrackMetadata:
        """Prepare metadata for template rendering"""
        metadata = await self.metadb.read_last_meta_async() or {}
        if "coverimageraw" in metadata:
            del metadata["coverimageraw"]
        metadata["cmdtarget"] = None
        metadata["startnewmessage"] = SPLITMESSAGETEXT

        if moremetadata:
            metadata |= moremetadata

        return metadata

    def _resolve_template_name(self, templatein: pathlib.Path | str) -> str | None:
        """Resolve template name from input path or string"""
        if isinstance(templatein, pathlib.Path):
            if not templatein.is_file():
                logging.debug("%s is not a file.", str(templatein))
                return None
            return templatein.name
        if not self.templatedir.joinpath(templatein).is_file():
            logging.debug("%s is not a file.", templatein)
            return None
        return templatein

    @staticmethod
    def _render_template(
        template: str, metadata: TrackMetadata, jinja2driver: jinja2.Environment
    ) -> str | None:
        """Render template with metadata"""
        try:
            j2template = jinja2driver.get_template(template)
            return j2template.render(metadata)
        except Exception as error:  # pylint: disable=broad-except
            logging.error("template %s rendering failure: %s", template, error)
        return None

    async def _send_template_messages(self, message: str, msg: ChatMessage | None = None) -> None:
        """Send rendered template messages to chat"""
        messages = message.split(SPLITMESSAGETEXT)
        try:
            for content in messages:
                if not self.chat or not self.chat.is_connected():
                    logging.error("Twitch chat is not connected. Not sending message.")
                    return

                await self._send_content_parts(content.strip(), msg)
        except ConnectionResetError:
            logging.debug("Twitch appears to be down.  Cannot send message.")
        except Exception:  # pylint: disable=broad-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
            logging.error("Unknown problem.")

    async def _send_content_parts(self, content: str, msg: ChatMessage | None = None) -> None:
        """Send content parts with smart splitting"""
        content_parts = self._split_message_smart(content)
        if len(content_parts) > 1:
            logging.info("Message split into %d parts for Twitch limits", len(content_parts))

        for part in content_parts:
            if not part.strip():
                continue
            await self._send_single_message_part(part, msg)

    async def _send_single_message_part(self, part: str, msg: ChatMessage | None = None) -> None:
        """Send a single message part using reply or direct message"""
        if not self.chat:
            return
        if msg and self.config.cparser.value("twitchbot/usereplies", type=bool):
            try:
                await msg.reply(part)
            except Exception:  # pylint: disable=broad-except
                for line in traceback.format_exc().splitlines():
                    logging.error(line)
                await self.chat.send_message(self.config.cparser.value("twitchbot/channel"), part)
        else:
            await self.chat.send_message(self.config.cparser.value("twitchbot/channel"), part)

    async def stop(self):
        """stop the twitch chat support"""
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        if self.chat:
            self.chat.stop()
        self.chat = None
        logging.debug("chat stopped")


class TwitchChatSettings:
    """for settings UI"""

    def __init__(self):
        self.widget = None
        self.uihelp = None

    def connect(self, uihelp, widget):
        """connect twitchbot"""
        self.widget = widget
        self.uihelp = uihelp
        widget.announce_button.clicked.connect(self.on_announce_button)
        widget.add_button.clicked.connect(self.on_add_button)
        widget.del_button.clicked.connect(self.on_del_button)

    @Slot()
    def on_announce_button(self):
        """twitchbot announce button clicked action"""
        self.uihelp.template_picker_lineedit(
            self.widget.announce_lineedit, limit="twitchbot_*.txt"
        )

    def _twitchbot_command_load(self, command=None, **kwargs):
        if not command:
            return

        row = self.widget.command_perm_table.rowCount()
        self.widget.command_perm_table.insertRow(row)
        cmditem = QTableWidgetItem(command)
        self.widget.command_perm_table.setItem(row, 0, cmditem)

        checkbox = []
        for column, cbtype in enumerate(TWITCHBOT_CHECKBOXES):  # pylint: disable=unused-variable
            checkbox = QCheckBox()
            if cbtype in kwargs:
                checkbox.setChecked(kwargs[cbtype])
            else:
                checkbox.setChecked(True)
            self.widget.command_perm_table.setCellWidget(row, column + 1, checkbox)

    @Slot()
    def on_add_button(self):
        """twitchbot add button clicked action"""
        filename = self.uihelp.template_picker(limit="twitchbot_*.txt")
        if not filename:
            return

        filename = os.path.basename(filename)
        filename = filename.replace("twitchbot_", "")
        command = filename.replace(".txt", "")

        self._twitchbot_command_load(command)

    @Slot()
    def on_del_button(self):
        """twitchbot del button clicked action"""
        if items := self.widget.command_perm_table.selectedIndexes():
            self.widget.command_perm_table.removeRow(items[0].row())

    def load(self, config, widget, uihelp):  # pylint: disable=unused-argument
        """load the settings window"""

        self.widget = widget

        def clear_table(widget):
            widget.clearContents()
            rows = widget.rowCount()
            for row in range(rows, -1, -1):
                widget.removeRow(row)

        clear_table(widget.command_perm_table)

        for configitem in config.cparser.childGroups():
            setting = {}
            if "twitchbot-command-" in configitem:
                command = configitem.replace("twitchbot-command-", "")
                setting["command"] = command
                for box in TWITCHBOT_CHECKBOXES:
                    setting[box] = config.cparser.value(
                        f"{configitem}/{box}", defaultValue=False, type=bool
                    )
                self._twitchbot_command_load(**setting)

        widget.enable_checkbox.setChecked(config.cparser.value("twitchbot/chat", type=bool))
        widget.command_perm_table.resizeColumnsToContents()
        widget.announce_lineedit.setText(config.cparser.value("twitchbot/announce"))
        widget.commandchar_lineedit.setText(config.cparser.value("twitchbot/commandchar"))
        widget.announce_delay_lineedit.setText(config.cparser.value("twitchbot/announcedelay"))
        widget.helpkeyword_lineedit.setText(
            config.cparser.value("twitchbot/helpkeyword", defaultValue="help")
        )
        widget.replies_checkbox.setChecked(config.cparser.value("twitchbot/usereplies", type=bool))

    @staticmethod
    def save(config, widget, subprocesses):  # pylint: disable=unused-argument
        """update the twitch settings"""

        def reset_commands(widget, config):
            for configitem in config.allKeys():
                if "twitchbot-command-" in configitem:
                    config.remove(configitem)

            rowcount = widget.rowCount()
            for row in range(rowcount):
                item = widget.item(row, 0)
                cmd = item.text()
                cmd = f"twitchbot-command-{cmd}"
                for column, cbtype in enumerate(TWITCHBOT_CHECKBOXES):
                    item = widget.cellWidget(row, column + 1)
                    value = item.isChecked()
                    config.setValue(f"{cmd}/{cbtype}", value)

        # oldenabled = config.cparser.value('twitchbot/chat', type=bool)
        newenabled = widget.enable_checkbox.isChecked()

        config.cparser.setValue("twitchbot/chat", newenabled)

        config.cparser.setValue("twitchbot/announce", widget.announce_lineedit.text())
        config.cparser.setValue("twitchbot/commandchar", widget.commandchar_lineedit.text())

        config.cparser.setValue("twitchbot/announcedelay", widget.announce_delay_lineedit.text())
        config.cparser.setValue("twitchbot/helpkeyword", widget.helpkeyword_lineedit.text())
        config.cparser.setValue("twitchbot/usereplies", widget.replies_checkbox.isChecked())

        reset_commands(widget.command_perm_table, config.cparser)

    @staticmethod
    def update_twitchbot_commands(config):
        """make sure all twitchbot_ files have a config entry"""
        filelist = os.listdir(config.templatedir)
        existing = config.cparser.childGroups()
        alert = False

        if not config.cparser.value("twitchbot/chat", type=bool):
            anntemplstr = config.cparser.value("twitchbot/announce")
            if not anntemplstr:
                anntemplpath = config.templatedir.joinpath("twitchbot_track.txt")
                if anntemplpath.exists():
                    config.cparser.setValue("twitchbot/announce", str(anntemplpath))

        for file in filelist:
            if not fnmatch.fnmatch(file, "twitchbot_*.txt"):
                continue

            # Skip help template files
            if "_help.txt" in file:
                continue

            command = file.replace("twitchbot_", "").replace(".txt", "")
            command = f"twitchbot-command-{command}"

            if command not in existing:
                alert = True
                logging.debug("creating %s", command)
                for box in TWITCHBOT_CHECKBOXES:
                    config.cparser.setValue(f"{command}/{box}", False)
        if alert and not config.testmode:
            dialog = ChatTemplateUpgradeDialog()
            dialog.exec()

    @staticmethod
    def verify(widget):
        """verify the settings are good"""
        char = widget.commandchar_lineedit.text()
        if char and char[0] in ["/", "."]:
            raise PluginVerifyError("Twitch command character cannot start with / or .")


class ChatTemplateUpgradeDialog(QDialog):  # pylint: disable=too-few-public-methods
    """Qt Dialog for informing user about template changes"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("What's Now Playing Templates")
        dialogbuttons = QDialogButtonBox.Ok
        self.buttonbox = QDialogButtonBox(dialogbuttons)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)
        self.setModal(True)
        self.layout = QVBoxLayout()
        message = QLabel("Twitch Chat permissions have been added or changed.")
        self.layout.addWidget(message)
        self.layout.addWidget(self.buttonbox)
        self.setLayout(self.layout)
