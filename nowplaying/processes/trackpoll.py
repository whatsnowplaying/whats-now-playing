#!/usr/bin/env python3
"""thread to poll music player"""

import asyncio
import contextlib
import datetime
import logging
import multiprocessing
import os
import pathlib
import signal
import socket
import sys
import threading
import time
from typing import Any

import nowplaying.config
import nowplaying.db
import nowplaying.frozen
import nowplaying.imagecache
import nowplaying.inputs
import nowplaying.metadata
import nowplaying.notifications
import nowplaying.pluginimporter
import nowplaying.trackrequests
import nowplaying.utils
import nowplaying.version  # pylint: disable=import-error,no-name-in-module
from nowplaying.types import TrackMetadata

COREMETA = ["artist", "filename", "title"]


class TrackPoll:  # pylint: disable=too-many-instance-attributes
    """
    Do the heavy lifting of reading from the DJ software
    """

    def __init__(
        self,
        stopevent: asyncio.Event | None = None,
        config: nowplaying.config.ConfigFile | None = None,
        testmode: bool = False,
    ):
        """Initialize core polling components only - use create_with_plugins() for full setup"""
        self.datestr = time.strftime("%Y%m%d-%H%M%S")
        self.stopevent = stopevent
        # we can't use asyncio's because it doesn't work on Windows
        _ = signal.signal(signal.SIGINT, self.forced_stop)
        if testmode and config:
            self.config = config
        else:
            self.config = nowplaying.config.ConfigFile()
        self.currentmeta: TrackMetadata = {}
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
        self._resetcurrent()
        self.testmode = testmode

        # Core polling components
        self.input: nowplaying.inputs.InputPlugin | None = None
        self.previousinput: str | None = None
        self.inputname: str | None = None
        self.tasks: set[asyncio.Task[Any]] = set()
        self.metadataprocessors = nowplaying.metadata.MetadataProcessors(config=self.config)

        # Plugin components - initialized separately
        self.plugins: dict = {}
        self.notification_plugins: dict = {}
        self.active_notifications: list = []
        self.imagecache: nowplaying.imagecache.ImageCache | None = None
        self.icprocess = None
        self.trackrequests: nowplaying.trackrequests.Requests | None = None

    @classmethod
    def create_with_plugins(
        cls,
        stopevent: asyncio.Event | None = None,
        config: nowplaying.config.ConfigFile | None = None,
        testmode: bool = False,
    ) -> "TrackPoll":
        """Factory method to create TrackPoll with full plugin initialization"""
        instance = cls(stopevent, config, testmode)
        instance._setup_plugins()
        return instance

    def _setup_plugins(self):
        """Initialize all plugin subsystems"""
        self._setup_input_plugins()
        self._setup_imagecache()
        self._setup_trackrequests()
        self._setup_notifications()

        # Start the polling loop
        self.create_tasks()
        if not self.testmode:
            self.loop.run_forever()

    def _setup_input_plugins(self):
        """Initialize input plugins"""
        self.plugins = nowplaying.pluginimporter.import_plugins(nowplaying.inputs)

    def _setup_trackrequests(self):
        """Initialize track request system"""
        self.trackrequests = nowplaying.trackrequests.Requests(
            config=self.config, stopevent=self.stopevent
        )
        self.trackrequests.clear_roulette_artist_dupes()

    def _resetcurrent(self):
        """reset the currentmeta to blank"""
        for key in COREMETA:
            self.currentmeta[f"fetched{key}"] = None

    def create_tasks(self):
        """create the asyncio tasks"""
        task = self.loop.create_task(self.run())
        task.add_done_callback(self.tasks.discard)
        self.tasks.add(task)
        if self.trackrequests:
            task = self.loop.create_task(self.trackrequests.watch_for_respin(self.stopevent))
            task.add_done_callback(self.tasks.discard)
            self.tasks.add(task)
        if self.imagecache:
            task = self.loop.create_task(self.imagecache.verify_cache_timer(self.stopevent))
            task.add_done_callback(self.tasks.discard)
            self.tasks.add(task)

    async def switch_input_plugin(self):
        """handle user switching source input while running"""
        if not self.previousinput or self.previousinput != self.config.cparser.value(
            "settings/input"
        ):
            if self.input:
                logging.info("stopping %s", self.previousinput)
                await self.input.stop()
            self.previousinput: str | None = self.config.cparser.value("settings/input")
            self.input = self.plugins[f"nowplaying.inputs.{self.previousinput}"].Plugin(
                config=self.config
            )
            logging.info("Starting %s plugin", self.previousinput)
            if not self.input:
                return False

            try:
                await self.input.start()
            except Exception as error:  # pylint: disable=broad-except
                logging.error("cannot start %s: %s", self.previousinput, error)
                return False

        return True

    async def run(self):
        """track polling process"""

        threading.current_thread().name = "TrackPoll"
        socket.setdefaulttimeout(5.0)

        # Start notification plugins
        await self._start_notification_plugins()

        if not self.config.cparser.value("settings/input", defaultValue=None):
            logging.debug("Waiting for user to configure source input.")

        # sleep until we have something to do
        while (
            not nowplaying.utils.safe_stopevent_check(self.stopevent)
            and not self.config.getpause()
            and not self.config.cparser.value("settings/input", defaultValue=None)
        ):
            await asyncio.sleep(0.5)
            self.config.get()

        while not nowplaying.utils.safe_stopevent_check(self.stopevent):
            await asyncio.sleep(0.5)
            self.config.get()

            if not await self.switch_input_plugin():
                continue

            try:
                await self.gettrack()
            except Exception as error:  # pylint: disable=broad-except
                logging.error("Failed attempting to get a track: %s", error, exc_info=True)

        if not self.testmode and self.config.cparser.value("setlist/enabled", type=bool):
            nowplaying.db.create_setlist(self.config)
        await self.stop()
        logging.debug("Trackpoll stopped gracefully.")

    async def stop(self):
        """stop trackpoll thread gracefully"""
        logging.debug("Stopping trackpoll")
        self.stopevent.set()
        if self.imagecache:
            logging.debug("stopping imagecache")
            self.imagecache.stop_process()
        if self.icprocess:
            logging.debug("joining imagecache")
            self.icprocess.join()
        if self.input:
            await self.input.stop()
        self.plugins = None
        loop = asyncio.get_running_loop()
        if not self.testmode:
            loop.stop()

    def forced_stop(self, signum, frame):  # pylint: disable=unused-argument
        """caught an int signal so tell the world to stop"""
        self.stopevent.set()

    def _verify_filename(self, metadata: TrackMetadata) -> TrackMetadata:
        """verify filename actual exists and/or needs path substitution"""
        if metadata.get("filename"):
            filepath = pathlib.Path(metadata["filename"])
            if not filepath.exists():
                metadata["filename"] = nowplaying.utils.songpathsubst(
                    self.config, metadata["filename"]
                )
                filepath = pathlib.Path(metadata["filename"])
                if not filepath.exists():
                    logging.error("cannot find %s; removing from metadata", metadata["filename"])
                    del metadata["filename"]
        return metadata

    def _check_title_for_path(self, title: str | None, filename: str) -> tuple[str | None, str]:
        """if title actually contains a filename, move it to filename"""

        if not title:
            return title, filename

        if title == filename:
            return None, filename

        if ("\\" in title or "/" in title) and pathlib.Path(
            nowplaying.utils.songpathsubst(self.config, title)
        ).exists():
            if not filename:
                logging.debug("Copied title to filename")
                filename = title
            logging.debug("Wiping title because it is actually a filename")
            title = None

        return title, filename

    @staticmethod
    def _ismetaempty(metadata: TrackMetadata) -> bool:
        """need at least one value"""

        if not metadata:
            return True

        return not any(key in metadata and metadata[key] for key in COREMETA)

    def _ismetasame(self, metadata: TrackMetadata) -> bool:
        """same as current check"""
        if not self.currentmeta:
            return False

        for key in COREMETA:
            fetched = f"fetched{key}"
            if (
                key in metadata
                and fetched in self.currentmeta
                and metadata[key] != self.currentmeta[fetched]
            ):
                return False
        return True

    @staticmethod
    def _isignored(metadata: TrackMetadata) -> bool:
        """bail out if the text NPIGNORE appears in the comment field"""
        if metadata.get("comments") and "NPIGNORE" in metadata["comments"]:
            return True
        return False

    async def checkskip(self, nextmeta: TrackMetadata) -> bool:
        """check if this metadata is meant to be skipped"""
        if not nextmeta:
            return False

        for skiptype in ["comment", "genre"]:
            skipdata = self.config.cparser.value(f"trackskip/{skiptype}", defaultValue=None)
            if not skipdata:
                continue
            if skipdata in nextmeta.get(skiptype, ""):
                return True
        return False

    async def _fill_inmetadata(self, metadata: TrackMetadata) -> TrackMetadata:  # pylint: disable=too-many-branches
        """keep a copy of our fetched data"""

        # Fill in as much metadata as possible. everything
        # after this expects artist, filename, and title are expected to exist
        # so if they don't, make them at least an empty string, keeping what
        # the input actually gave as 'fetched' to compare with what
        # was given before to shortcut all of this work in the future

        if not metadata:
            return {}

        for key in COREMETA:
            fetched = f"fetched{key}"
            if key in metadata:
                if isinstance(metadata[key], str):
                    metadata[fetched] = metadata[key].strip()
                else:
                    metadata[fetched] = metadata[key]
            else:
                metadata[fetched] = None

        if metadata.get("filename"):
            metadata = self._verify_filename(metadata)

        if metadata.get("title"):
            (metadata["title"], metadata["filename"]) = self._check_title_for_path(
                metadata["title"], metadata.get("filename")
            )

        for key in COREMETA:
            if key in metadata and not metadata[key]:
                del metadata[key]

        try:
            metadata = await self.metadataprocessors.getmoremetadata(
                metadata=metadata, imagecache=self.imagecache
            )
            if duration := metadata.get("duration"):
                metadata["duration_hhmmss"] = nowplaying.utils.humanize_time(duration)
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("Ignoring metadataprocessor failure (%s).", err)

        for key in COREMETA:
            if key not in metadata:
                logging.info("Track missing %s data, setting it to blank.", key)
                metadata[key] = ""
        return metadata

    async def gettrack(  # pylint: disable=too-many-branches,too-many-statements
        self,
    ):
        """get currently playing track, returns None if not new or not found"""

        # check paused state
        while self.config.getpause() and not nowplaying.utils.safe_stopevent_check(self.stopevent):
            await asyncio.sleep(0.5)

        if nowplaying.utils.safe_stopevent_check(self.stopevent) or not self.input:
            return

        try:
            nextmeta = await self.input.getplayingtrack() or {}
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("Failed during getplayingtrack() (%s)", err)
            await asyncio.sleep(1)
            return

        if self._ismetaempty(nextmeta) or self._ismetasame(nextmeta) or self._isignored(nextmeta):
            return

        # fill in the blanks and make it live
        oldmeta = self.currentmeta
        fill_start_time = time.time()
        try:
            self.currentmeta = await self._fill_inmetadata(nextmeta)
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("Ignoring the %s crash and just keep going!", err)
            await asyncio.sleep(1)
            self.currentmeta = nextmeta

        fill_duration = time.time() - fill_start_time
        logging.debug("_fill_inmetadata took %.3f seconds", fill_duration)

        # Set timestamp and version when track is accepted as current
        self.currentmeta["track_received"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        self.currentmeta["version"] = nowplaying.version.__VERSION__  # pylint: disable=no-member

        logging.info(
            "Potential new track: %s / %s", self.currentmeta["artist"], self.currentmeta["title"]
        )

        if await self.checkskip(nextmeta):
            logging.info("Skipping %s / %s", self.currentmeta["artist"], self.currentmeta["title"])
            return

        # Get configured delay for optimization calculations
        try:
            configured_delay = self.config.cparser.value(
                "settings/delay", type=float, defaultValue=1.0
            )
        except ValueError:
            configured_delay = 1.0

        if not self.currentmeta.get("cache_warmed", False):
            # try to interleave downloads in-between the delay
            await self._half_delay_write(fill_duration)  # Use fill duration for first delay
            await self._process_imagecache()
            self._start_artistfanartpool()
            await self._half_delay_write()  # Normal delay for second half
            await self._process_imagecache()
            self._start_artistfanartpool()
            # Reduce sleep by any remaining fill duration beyond the configured delay
            sleep_time = max(0.0, 0.5 - max(0.0, fill_duration - configured_delay))
            await asyncio.sleep(sleep_time)
        else:
            # cache was already warmed so just go for it
            await self._half_delay_write(fill_duration)  # Use fill duration for first delay
            await self._half_delay_write()  # Normal delay for second half

        # checkagain
        nextcheck = await self.input.getplayingtrack() or {}
        if not self._ismetaempty(nextcheck) and not self._ismetasame(nextcheck):
            logging.info("Track changed during delay, skipping")
            self.currentmeta = oldmeta
            return

        if self.config.cparser.value("settings/requests", type=bool):
            if data := await self.trackrequests.get_request(self.currentmeta):
                self.currentmeta.update(data)

        if not self.currentmeta.get("cache_warmed", False):
            self._start_artistfanartpool()
        self._artfallbacks()

        if not self.testmode:
            metadb = nowplaying.db.MetadataDB()
            await metadb.write_to_metadb(metadata=self.currentmeta)
        await self._notify_plugins()

    def _setup_notifications(self):
        """Initialize notification plugins"""
        self.notification_plugins = nowplaying.pluginimporter.import_plugins(
            nowplaying.notifications
        )
        for plugin_name, plugin_class in self.notification_plugins.items():
            try:
                plugin_instance = plugin_class.Plugin(config=self.config)
                self.active_notifications.append(plugin_instance)
                logging.debug("Loaded notification plugin: %s", plugin_name)
            except Exception as err:  # pylint: disable=broad-except
                logging.error("Failed to load notification plugin %s: %s", plugin_name, err)

    async def _start_notification_plugins(self):
        """Start all notification plugins"""
        for plugin in self.active_notifications:
            plugin_name = plugin.__class__.__name__
            try:
                await plugin.start()
                logging.debug("Started notification plugin: %s", plugin_name)
            except Exception as err:  # pylint: disable=broad-except
                logging.error("Failed to start notification plugin %s: %s", plugin_name, err)

    async def _notify_plugins(self):
        """notify all active notification plugins of track change"""
        if not self.active_notifications:
            return

        # Fire-and-forget notification plugins to prevent blocking track polling
        for plugin in self.active_notifications:
            plugin_name = plugin.__class__.__name__

            async def notify_plugin_safe(plugin_instance, plugin_instance_name):
                """Wrapper to safely call plugin with error handling"""
                try:
                    await plugin_instance.notify_track_change(
                        self.currentmeta, imagecache=self.imagecache
                    )
                except Exception as err:  # pylint: disable=broad-except
                    logging.error("Notification plugin %s failed: %s", plugin_instance_name, err)

            # Create task and manage its lifecycle to prevent garbage collection
            task = asyncio.create_task(notify_plugin_safe(plugin, plugin_name))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    def _artfallbacks(self):
        if (
            self.config.cparser.value("artistextras/coverfornologos", type=bool)
            and not self.currentmeta.get("artistlogoraw")
            and self.currentmeta.get("coverimageraw")
        ):
            self.currentmeta["artistlogoraw"] = self.currentmeta["coverimageraw"]

        if (
            self.config.cparser.value("artistextras/coverfornothumbs", type=bool)
            and not self.currentmeta.get("artistthumbnailraw")
            and self.currentmeta.get("coverimageraw")
        ):
            self.currentmeta["artistthumbnailraw"] = self.currentmeta["coverimageraw"]

        if not self.currentmeta.get("coverimageraw") and self.imagecache:
            if imagetype := self.config.cparser.value("artistextras/nocoverfallback"):
                imagetype = imagetype.lower()
                if imagetype != "none" and self.currentmeta.get("imagecacheartist"):
                    self.currentmeta["coverimageraw"] = self.imagecache.random_image_fetch(
                        identifier=self.currentmeta["imagecacheartist"],
                        imagetype=f"artist{imagetype}",
                    )

    async def _half_delay_write(self, elapsed_time: float = 0.0):
        try:
            delay = self.config.cparser.value("settings/delay", type=float, defaultValue=1.0)
        except ValueError:
            delay = 1.0
        delay /= 2

        # Reduce delay by time already spent processing
        actual_delay = max(0.0, delay - elapsed_time)
        logging.debug(
            "got half-delay of %ss (reduced by %.3fs elapsed, sleeping %.3fs)",
            delay,
            elapsed_time,
            actual_delay,
        )
        await asyncio.sleep(actual_delay)

    def _setup_imagecache(self):
        if not self.config.cparser.value("artistextras/enabled", type=bool):
            return

        workers = self.config.cparser.value("artistextras/processes", type=int)
        sizelimit = self.config.cparser.value("artistextras/cachesize", type=int)

        self.imagecache = nowplaying.imagecache.ImageCache(
            sizelimit=sizelimit, stopevent=self.stopevent
        )
        self.config.cparser.setValue("artistextras/cachedbfile", self.imagecache.databasefile)

        # Vacuum the imagecache database on startup to reclaim space from previous session
        try:
            self.imagecache.vacuum_database()
            logging.debug("Image cache database vacuumed successfully on startup")
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Error vacuuming image cache database on startup: %s", error)

        self.icprocess = multiprocessing.Process(
            target=self.imagecache.queue_process,
            name="ICProcess",
            args=(
                self.config.logpath,
                workers,
            ),
        )
        self.icprocess.start()

    def _start_artistfanartpool(self):
        if not self.config.cparser.value("artistextras/enabled", type=bool):
            return

        if self.currentmeta.get("artistfanarturls"):
            # imagecache handles deduplication at the database level via UNIQUE constraints
            self.imagecache.fill_queue(
                config=self.config,
                identifier=self.currentmeta["artist"],
                imagetype="artistfanart",
                srclocationlist=self.currentmeta["artistfanarturls"],
            )
            del self.currentmeta["artistfanarturls"]

    async def _process_imagecache(self):
        if not self.currentmeta.get("artist") or not self.config.cparser.value(
            "artistextras/enabled", type=bool
        ):
            return

        async def fill_in_async():
            """Async wrapper to fetch images with task management"""
            tryagain = False

            if not self.imagecache:
                logging.debug(
                    "Artist Extras was enabled without restart; skipping image downloads"
                )
                return True

            # Create tasks for each image type to fetch concurrently
            image_tasks = []
            image_keys = ["artistthumbnail", "artistlogo", "artistbanner"]

            for key in image_keys:
                rawkey = f"{key}raw"
                if not self.currentmeta.get(rawkey):

                    async def fetch_image_task(image_key: str, raw_key: str):
                        """Task to fetch a single image type"""
                        try:
                            # Run the synchronous fetch in executor to avoid blocking
                            loop = asyncio.get_running_loop()
                            image = await loop.run_in_executor(
                                None,
                                self.imagecache.random_image_fetch,
                                self.currentmeta["artist"],
                                image_key,
                            )
                            return raw_key, image
                        except Exception as err:  # pylint: disable=broad-except
                            logging.debug("Error fetching %s: %s", image_key, err)
                            return raw_key, None

                    task = asyncio.create_task(fetch_image_task(key, rawkey))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
                    image_tasks.append(task)

            # Wait for all image fetch tasks to complete
            if image_tasks:
                results = await asyncio.gather(*image_tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, Exception):
                        logging.debug("Image fetch task failed: %s", result)
                        tryagain = True
                        continue

                    rawkey, image = result
                    if not image:
                        logging.debug(
                            "did not get an image for %s %s",
                            rawkey,
                            self.currentmeta["artist"],
                        )
                        tryagain = True
                    else:
                        self.currentmeta[rawkey] = image

            return tryagain

        # try to give it a bit more time if it doesn't complete the first time
        if not await fill_in_async():
            await fill_in_async()


def stop(pid):
    """stop the web server -- called from Tray"""
    logging.info("sending INT to %s", pid)
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGINT)


def start(stopevent, bundledir, testmode=False):  # pylint: disable=unused-argument
    """multiprocessing start hook"""
    threading.current_thread().name = "TrackPoll"

    bundledir = nowplaying.frozen.frozen_init(bundledir)

    if testmode:
        nowplaying.bootstrap.set_qt_names(appname="testsuite")
    else:
        nowplaying.bootstrap.set_qt_names()
    logpath = nowplaying.bootstrap.setuplogging(logname="debug.log", rotate=False)
    config = nowplaying.config.ConfigFile(bundledir=bundledir, logpath=logpath, testmode=testmode)
    try:
        TrackPoll.create_with_plugins(  # pylint: disable=unused-variable
            stopevent=stopevent, config=config, testmode=testmode
        )
    except Exception as error:  # pylint: disable=broad-except
        logging.error("TrackPoll crashed: %s", error, exc_info=True)
        sys.exit(1)
    logging.info("shutting down trackpoll v%s", config.version)
