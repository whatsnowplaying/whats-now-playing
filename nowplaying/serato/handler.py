#!/usr/bin/env python3
"""
Serato 4+ Handler

Handler for Serato 4+ SQLite database monitoring and track detection.
"""

import asyncio
import logging
import pathlib
import typing as t

from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from .reader import Serato4SQLiteReader


class Serato4Handler:  # pylint: disable=too-many-instance-attributes
    """Handler for Serato 4+ SQLite database monitoring and track detection"""

    def __init__(
        self,
        serato_lib_path: str | pathlib.Path,
        pollingobserver: bool = False,
        polling_interval: float = 1.0,
    ):
        self.serato_lib_path = pathlib.Path(serato_lib_path)
        self.master_db_path = self.serato_lib_path / "master.sqlite"
        self.sqlite_reader = Serato4SQLiteReader(self.master_db_path)

        # File watching setup
        self.observer: Observer | None = None
        self.event_handler: PatternMatchingEventHandler | None = None
        self.pollingobserver = pollingobserver
        self.polling_interval = polling_interval
        self.tasks = set()

        # Track change detection
        self.last_track_data: dict[str, t.Any] | None = None
        self.current_track: dict[str, t.Any] | None = None
        self._last_db_change_time: float = 0
        self._db_change_debounce_delay: float = 0.5  # 500ms debounce

    async def start(self):
        """perform any startup tasks"""
        # if self.seratodir and self.mode == "local":
        await self._setup_watcher()

    async def _setup_watcher(self):
        logging.debug("setting up watcher")
        self.event_handler = PatternMatchingEventHandler(
            patterns=["master*"],
            ignore_patterns=[".DS_Store"],
            ignore_directories=True,
            case_sensitive=False,
        )
        self.event_handler.on_modified = self.process_sessions

        if self.pollingobserver:
            self.observer = PollingObserver(timeout=self.polling_interval)
            logging.debug("Using polling observer with %s second interval", self.polling_interval)
        else:
            self.observer = Observer()
            logging.debug("Using fsevent observer")

        _ = self.observer.schedule(
            self.event_handler,
            str(self.serato_lib_path),
            recursive=False,
        )
        self.observer.start()

        # process what is already there
        await self._async_process_sessions()

    async def stop(self):
        """Stop the handler and clean up resources"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

        # Cancel any pending tasks
        for task in self.tasks.copy():
            task.cancel()
        self.tasks.clear()

    def process_sessions(self, event):
        """handle incoming session file updates"""
        logging.debug("processing %s", event)
        try:
            loop = asyncio.get_running_loop()
            logging.debug("got a running loop")
            task = loop.create_task(self._async_process_sessions())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

        except RuntimeError:
            loop = asyncio.new_event_loop()
            logging.debug("created a loop")
            loop.run_until_complete(self._async_process_sessions())

    async def _async_process_sessions(self):
        """Handle database file changes with debouncing to avoid rapid-fire events"""

        try:
            loop = asyncio.get_running_loop()
            logging.debug("Got running event loop, creating task")
            task = loop.create_task(self._async_check_track_change())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            logging.debug("Created new event loop")
            loop.run_until_complete(self._async_check_track_change())
            loop.close()

    async def _async_check_track_change(self) -> None:
        """Async method to check for track changes - called from file watcher"""
        try:
            # Get all deck data and find the most recent overall track for change detection
            deck_tracks = await self.sqlite_reader.get_latest_tracks_per_deck()
            logging.info(deck_tracks)
            new_track_data = None
            if deck_tracks:
                # Find the track with the latest start_time for file change detection
                new_track_data = max(deck_tracks, key=lambda t: t.get("start_time", 0))

            # Compare with last known track
            if self._has_track_changed(new_track_data):
                logging.debug("Track change detected in Serato 4")
                self.last_track_data = self.current_track
                self.current_track = new_track_data
                logging.info(
                    "Track changed: %s - %s",
                    new_track_data.get("artist", "Unknown") if new_track_data else None,
                    new_track_data.get("title", "Unknown") if new_track_data else None,
                )

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.error("Error checking track change: %s", exc)

    async def _check_track_change(self) -> None:
        """Check if the current track has changed (compatibility method)"""
        await self._async_check_track_change()

    def _has_track_changed(self, new_track: dict[str, t.Any] | None) -> bool:
        """Check if track data represents a different track"""
        if not new_track and not self.current_track:
            return False

        if not new_track or not self.current_track:
            return True

        # Compare key fields that indicate a track change
        key_fields = ["file_name", "artist", "title", "start_time"]
        for field in key_fields:
            if new_track.get(field) != self.current_track.get(field):
                return True

        return False

    async def get_current_track_by_mixmode(
        self, mixmode: str = "newest", deckskip: list[str] | None = None
    ) -> dict[str, t.Any] | None:
        """Get the current track based on mixmode and deck skip settings"""
        # Get the latest track from each deck (excluding skipped decks)
        deck_tracks = await self.sqlite_reader.get_latest_tracks_per_deck(deckskip=deckskip)

        if not deck_tracks:
            return None

        # Apply mixmode logic to select the appropriate track
        if mixmode == "oldest":
            # Find the track with the earliest start_time
            selected_track = min(deck_tracks, key=lambda t: t.get("start_time", 0))
        else:  # newest
            # Find the track with the latest start_time
            selected_track = max(deck_tracks, key=lambda t: t.get("start_time", 0))

        # Update internal track state for change detection
        if self._has_track_changed(selected_track):
            logging.debug("Track change detected via mixmode selection")
            self.last_track_data = self.current_track
            self.current_track = selected_track

        return selected_track
