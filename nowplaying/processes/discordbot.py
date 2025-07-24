#!/usr/bin/env python3
"""

Discord support code

"""

import asyncio
import contextlib
import logging
import os
import pathlib
import signal
import sys
import threading
from dataclasses import dataclass
from typing import Any

import pypresence
import pypresence.exceptions
import discord

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.frozen
import nowplaying.utils


@dataclass
class DiscordClients:
    """Container for Discord client connections"""

    bot: discord.Client | None = None
    ipc: pypresence.AioPresence | None = None


class DiscordSupport:
    """Work with discord"""

    # Sleep intervals
    DISABLED_SLEEP_INTERVAL = 5  # seconds to sleep when discord is disabled
    UPDATE_INTERVAL = 20  # seconds between updates (discord rate limit: max every 15s)

    def __init__(
        self,
        config: nowplaying.config.ConfigFile | None = None,
        stopevent: asyncio.Event | None = None,
    ) -> None:
        self.config: nowplaying.config.ConfigFile | None = config
        self.stopevent: asyncio.Event | None = stopevent
        self.clients: DiscordClients = DiscordClients()
        self.jinja2: nowplaying.utils.TemplateHandler = nowplaying.utils.TemplateHandler()
        self.tasks: set[asyncio.Task[Any]] = set()
        _ = signal.signal(signal.SIGINT, self.forced_stop)

    async def _setup_bot_client(self) -> None:
        if not self.config:
            return
        token: str | None = self.config.cparser.value("discord/token")
        if not token:
            return

        if self.clients.bot:
            return

        try:
            intents: discord.Intents = discord.Intents.default()
            self.clients.bot = discord.Client(intents=intents)
            await self.clients.bot.login(token)
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Cannot configure bot client: %s", error)
            return

        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        task: asyncio.Task[Any] = loop.create_task(self.clients.bot.connect(reconnect=True))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        while (
            not nowplaying.utils.safe_stopevent_check(self.stopevent)
            and not self.clients.bot.is_ready()
        ):
            await asyncio.sleep(1)
        logging.debug("bot setup")

        # Capture Discord guild information now that bot is ready
        if self.clients.bot.guilds and self.config:
            guild = self.clients.bot.guilds[0]  # Get the first guild the bot is in
            logging.info("Discord bot connected to guild: %s", guild.name)
            self.config.cparser.setValue("discord/guild", guild.name)
            self.config.cparser.sync()

    async def _setup_ipc_client(self) -> None:  # pylint: disable=too-many-return-statements
        if not self.config:
            return
        clientid: str | None = self.config.cparser.value("discord/clientid")
        if not clientid:
            return

        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        try:
            self.clients.ipc = pypresence.AioPresence(clientid, loop=loop)
        except pypresence.exceptions.DiscordNotFound:
            logging.error("Discord client is not running")
            return
        except ConnectionRefusedError:
            logging.error("Cannot connect to discord client.")
            return
        except pypresence.exceptions.DiscordError as error:
            logging.error(error)
            return
        except Exception as error:  # pylint: disable=broad-except
            logging.exception("discordbot: %s", error)
            return
        try:
            await self.clients.ipc.connect()
        except (ConnectionRefusedError, pypresence.exceptions.DiscordNotFound):
            logging.error("pypresence cannot connect; connection refused")
            self.clients.ipc = None
            return
        logging.debug("ipc setup")

    async def _update_bot(self, templateout: str) -> None:
        if not self.config or not self.clients.bot:
            return
        if (
            channelname := self.config.cparser.value("twitchbot/channel")
        ) and self.config.cparser.value("twitchbot/enabled", type=bool):
            activity: discord.BaseActivity = discord.Streaming(
                platform="Twitch", name=templateout, url=f"https://twitch.tv/{channelname}"
            )
        else:
            activity = discord.Game(templateout)
        try:
            await self.clients.bot.change_presence(activity=activity)
        except ConnectionResetError:
            logging.error("Cannot connect to discord.")
            self.clients.bot = None

    async def _update_ipc(self, templateout: str, metadata: dict[str, Any] | None = None) -> None:
        if not self.clients.ipc:
            return
        try:
            # Basic update parameters
            update_params: dict[str, Any] = {"state": "Streaming", "details": templateout}

            if self.config and metadata:
                # Try to use MusicBrainz Cover Art Archive URL first
                large_image: str | None = None
                if musicbrainz_album_id := metadata.get("musicbrainzalbumid"):
                    # Handle case where musicbrainzalbumid might be a list
                    if isinstance(musicbrainz_album_id, list):
                        musicbrainz_album_id = musicbrainz_album_id[0]
                    large_image = (
                        f"https://coverartarchive.org/release/{musicbrainz_album_id}/front"
                    )

                # Fall back to configured asset key if no MusicBrainz ID
                if not large_image:
                    large_image = self.config.cparser.value("discord/large_image_key")

                if large_image:
                    update_params["large_image"] = large_image
                    logging.debug("Discord Rich Presence using image URL: %s", large_image)
                    # Use track title for large image tooltip
                    if metadata.get("title"):
                        update_params["large_text"] = f"♪ {metadata['title']}"

                if small_image_key := self.config.cparser.value("discord/small_image_key"):
                    update_params["small_image"] = small_image_key
                    # Use artist for small image tooltip
                    if metadata.get("artist"):
                        update_params["small_text"] = f"by {metadata['artist']}"

            logging.debug("Discord Rich Presence update params: %s", update_params)
            await self.clients.ipc.update(**update_params)
        except ConnectionRefusedError:
            logging.error("Cannot connect to discord client.")
            self.clients.ipc = None
        except Exception as error:  # pylint: disable=broad-except
            logging.exception("discordbot: %s", error)
            self.clients.ipc = None

    async def connect_clients(self) -> None:
        """(re-)connect clients"""
        if not self.clients.bot:
            await self._setup_bot_client()
        if not self.clients.ipc:
            await self._setup_ipc_client()

    async def start(self) -> None:
        """start the service"""
        metadb, watcher = await self._setup_database()

        try:
            await self._run_service_loop(metadb, watcher)
        finally:
            await self._cleanup_resources(watcher)

    @staticmethod
    async def _setup_database() -> tuple[nowplaying.db.MetadataDB, nowplaying.db.DBWatcher]:
        """setup database and watcher"""
        metadb = nowplaying.db.MetadataDB()
        watcher = metadb.watcher()
        watcher.start()
        return metadb, watcher

    async def _run_service_loop(
        self, metadb: nowplaying.db.MetadataDB, watcher: nowplaying.db.DBWatcher
    ) -> None:
        """main service loop"""
        disabled_sleep_interval = self.DISABLED_SLEEP_INTERVAL
        update_interval = self.UPDATE_INTERVAL

        last_update_time = 0.0

        while not self._should_stop():
            if not self._is_discord_enabled():
                await asyncio.sleep(disabled_sleep_interval)
                continue

            await self.connect_clients()
            await asyncio.sleep(update_interval)

            if last_update_time < watcher.updatetime:
                last_update_time = await self._process_metadata_update(metadb, watcher.updatetime)

    def _should_stop(self) -> bool:
        """check if the service should stop"""
        return self.stopevent is not None and nowplaying.utils.safe_stopevent_check(self.stopevent)

    def _is_discord_enabled(self) -> bool:
        """check if discord integration is enabled"""
        return self.config and self.config.cparser.value("discord/enabled", type=bool)

    async def _process_metadata_update(
        self, metadb: nowplaying.db.MetadataDB, update_time: float
    ) -> float:
        """process metadata update and send to discord clients"""
        template = self.config.cparser.value("discord/template") if self.config else None
        if not template:
            return update_time

        metadata = await metadb.read_last_meta_async()
        if not metadata:
            return update_time

        templateout = self._generate_template_output(template, metadata)
        await self._update_all_clients(templateout, metadata)

        return update_time

    @staticmethod
    def _generate_template_output(template: str, metadata: dict[str, Any]) -> str:
        """generate template output from metadata"""
        templatehandler = nowplaying.utils.TemplateHandler(filename=template)
        return templatehandler.generate(metadata)

    async def _update_all_clients(self, templateout: str, metadata: dict[str, Any]) -> None:
        """update both bot and IPC clients with error handling"""
        await self._safe_update_client("bot", self._update_bot, templateout)
        await self._safe_update_client("ipc", self._update_ipc, templateout, metadata)

    async def _safe_update_client(self, client_type: str, update_func, *args) -> None:
        """safely update a client with consistent error handling"""
        client = getattr(self.clients, client_type)
        if not client:
            return

        try:
            await update_func(*args)
        except (
            ConnectionResetError,
            ConnectionRefusedError,
            discord.HTTPException,
            pypresence.exceptions.DiscordError,
        ) as error:
            logging.error("Discord %s client error: %s", client_type, error)
            setattr(self.clients, client_type, None)
        except Exception:  # pylint: disable=broad-except
            logging.exception("Unexpected error updating %s client", client_type)
            setattr(self.clients, client_type, None)

    async def _cleanup_resources(self, watcher: nowplaying.db.DBWatcher) -> None:
        """cleanup resources on shutdown"""
        watcher.stop()

        # Cancel any remaining tasks
        for task in list(self.tasks):
            if not task.done():
                task.cancel()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

        if self.clients.bot:
            await self.clients.bot.close()

    def forced_stop(self, signum: int, frame: Any) -> None:  # pylint: disable=unused-argument
        """caught an int signal so tell the world to stop"""
        if self.stopevent:
            self.stopevent.set()


def stop(pid: int) -> None:
    """stop the web server -- called from Tray"""
    logging.info("sending INT to %s", pid)
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGINT)


def start(stopevent: asyncio.Event, bundledir: str, testmode: bool = False) -> None:  # pylint: disable=unused-argument
    """multiprocessing start hook"""
    threading.current_thread().name = "DiscordBot"

    bundledir = str(nowplaying.frozen.frozen_init(bundledir))

    if testmode:
        nowplaying.bootstrap.set_qt_names(appname="testsuite")
    else:
        nowplaying.bootstrap.set_qt_names()
    logpath: pathlib.Path = nowplaying.bootstrap.setuplogging(logname="debug.log", rotate=False)
    config: nowplaying.config.ConfigFile = nowplaying.config.ConfigFile(
        bundledir=bundledir, logpath=logpath, testmode=testmode
    )
    logging.info("boot up")
    try:
        discordsupport: DiscordSupport = DiscordSupport(stopevent=stopevent, config=config)
        asyncio.run(discordsupport.start())
    except Exception as error:  # pylint: disable=broad-except
        logging.error("discordbot crashed: %s", error, exc_info=True)
        sys.exit(1)
    logging.info("shutting down discordbot v%s", config.version)
