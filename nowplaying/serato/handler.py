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
        self._db_needs_refresh: bool = True  # Flag set by watchdog, checked by async methods
        self._cached_deck_tracks: list[dict[str, t.Any]] = []  # Cache all deck data

    async def start(self):
        """perform any startup tasks"""
        await self._setup_watcher()

    async def _setup_watcher(self):
        logging.debug("setting up watcher")
        self.event_handler = PatternMatchingEventHandler(
            patterns=["master*"],
            ignore_patterns=[".DS_Store", "*.sqlite-shm"],
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

        # process what is already there - trigger initial refresh
        self._db_needs_refresh = True

    async def stop(self):
        """Stop the handler and clean up resources"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

        # Cancel any pending tasks and wait for them to finish
        if self.tasks:
            for task in self.tasks.copy():
                task.cancel()

            # Wait for all cancelled tasks to complete cleanup
            await asyncio.gather(*self.tasks, return_exceptions=True)

        self.tasks.clear()

    def process_sessions(self, event):
        """handle incoming session file updates"""
        logging.debug("processing %s", event)
        # Simple synchronous processing - just set a flag that async methods can check
        self._db_needs_refresh = True

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
        # Only query database if refresh flag is set (database changed)
        if self._db_needs_refresh:
            try:
                # Query database once, get ALL decks (no deckskip filter at SQL level)
                self._cached_deck_tracks = await self.sqlite_reader.get_latest_tracks_per_deck()

                # Update change detection with the most recent overall track
                if self._cached_deck_tracks:
                    new_track_data = max(
                        self._cached_deck_tracks, key=lambda t: t.get("start_time", 0)
                    )

                    if self._has_track_changed(new_track_data):
                        logging.debug("Track change detected in Serato 4")
                        self.last_track_data = self.current_track
                        self.current_track = new_track_data
                        logging.info(
                            "Track changed: %s - %s",
                            new_track_data.get("artist", "Unknown"),
                            new_track_data.get("title", "Unknown"),
                        )

                # Clear the refresh flag after successful processing
                self._db_needs_refresh = False

            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.error("Error checking track change: %s", exc)
                # Don't clear the flag on error - we'll try again next time
                return None

        # Apply deck skip filter in Python (fast, uses cached data)
        if deckskip:
            deck_tracks = [
                track
                for track in self._cached_deck_tracks
                if str(track.get("deck")) not in deckskip
            ]
        else:
            deck_tracks = self._cached_deck_tracks

        if not deck_tracks:
            return None

        # Apply mixmode logic to select the appropriate track (fast, in-memory)
        if mixmode == "oldest":
            # Find the track with the earliest start_time
            selected_track = min(deck_tracks, key=lambda t: t.get("start_time", 0))
        else:  # newest
            # Find the track with the latest start_time
            selected_track = max(deck_tracks, key=lambda t: t.get("start_time", 0))

        return selected_track
