#!/usr/bin/env python3
"""
Serato Remote Handler

Shared async remote functionality for scraping Serato Live Playlists from serato.com.
Used by both serato3 (legacy) and serato (4+) plugins.

Remote mode always returns "newest" track - no mixmode logic needed.
"""

import logging
import re
import time
import typing as t

import aiohttp
import lxml.html


class SeratoRemoteHandler:
    """Shared async handler for Serato Live Playlists web scraping"""

    def __init__(self, url: str, poll_interval: float = 30.0):
        """Initialize remote handler

        Args:
            url: Serato Live Playlist URL (serato.com/playlists/...)
            poll_interval: How often to poll (used for backoff timing)
        """
        self.url = url
        self.poll_interval = poll_interval

        # Circuit breaker state for network failures
        self.network_failure_count = 0
        self.backoff_until = 0.0

        # Track extraction state to reduce log spam
        self.last_extracted_track: str | None = None
        self.last_extraction_method: str | None = None

        # Current track data
        self.current_track: dict[str, t.Any] = {}

    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate that URL is a valid Serato Live Playlist URL"""
        if not url:
            return False

        # Check for expected serato.com playlist patterns
        valid_patterns = ["https://serato.com/playlists", "http://serato.com/playlists"]

        return any(pattern in url for pattern in valid_patterns) and len(url) >= 30

    async def get_current_track(self) -> dict[str, t.Any] | None:
        """Get the currently playing track from Live Playlists

        Returns:
            dict with 'artist' and 'title' keys, or None if no track found
        """
        # Circuit breaker: check if we should back off due to recent failures
        if not self._can_make_request():
            return None

        # Fetch the page with error handling
        page_text = await self._fetch_page()
        if not page_text:
            return None

        if track_text := self._extract_track_from_page(page_text):
            # Parse and store the track data
            self._parse_track_text(track_text)
            return self.current_track.copy() if self.current_track else None

        return None

    def _can_make_request(self) -> bool:
        """Check if we can make a request based on circuit breaker state"""
        current_time = time.time()
        return current_time >= self.backoff_until

    async def _fetch_page(self) -> str | None:
        """Fetch the page with network error handling"""
        current_time = time.time()
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.url) as response:
                    page_text = await response.text()

            # Success: reset failure tracking
            self.network_failure_count = 0
            self.backoff_until = 0
            return page_text
        except Exception as error:  # pylint: disable=broad-exception-caught
            self._handle_network_failure(current_time, error)
            return None

    def _handle_network_failure(self, current_time: float, error):
        """Handle network failure with live DJ-friendly backoff"""
        self.network_failure_count += 1

        # Live DJ backoff: 1s, 2s, 3s, then max 5s
        if self.network_failure_count <= 3:
            backoff_seconds = self.network_failure_count
        else:
            backoff_seconds = 5
        self.backoff_until = current_time + backoff_seconds

        # Reduce log spam: only log every 10th error after first few
        should_log = self.network_failure_count <= 3 or self.network_failure_count % 10 == 0

        if should_log:
            if self.network_failure_count == 1:
                logging.error("Cannot process %s: %s", self.url, error)
            else:
                logging.error(
                    "Cannot process %s: %s (failure #%d, backing off for %ds)",
                    self.url,
                    error,
                    self.network_failure_count,
                    backoff_seconds,
                )

    def _extract_track_from_page(self, page_text: str) -> str | None:
        """Extract track information from the page"""
        try:
            tree = lxml.html.fromstring(page_text)
            # Try methods in order of reliability
            extraction_methods = [
                ("JavaScript+XPath", lambda: self._extract_by_js_id(page_text, tree)),
                ("Positional XPath", lambda: self._extract_by_position(tree)),
                ("Pattern matching", lambda: self._extract_by_pattern(tree)),
                ("Text search", lambda: self._extract_by_text_search(tree)),
            ]

            for method_name, method_func in extraction_methods:
                try:
                    if track_text := method_func():
                        # Only log when track or method changes to reduce spam
                        if (
                            track_text != self.last_extracted_track
                            or method_name != self.last_extraction_method
                        ):
                            logging.debug("Successfully extracted track using: %s", method_name)
                            self.last_extracted_track = track_text
                            self.last_extraction_method = method_name
                        return track_text
                except Exception as method_error:  # pylint: disable=broad-exception-caught
                    logging.debug("Method %s failed: %s", method_name, method_error)
                    continue
            return None
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Cannot process %s: %s", self.url, error)
            return None

    def _extract_by_js_id(self, page_text: str, tree) -> str | None:
        """Extract track using JavaScript track ID (most robust)"""
        if not (track_id_match := re.search(r"end_track_id:\s*(\d+)", page_text)):
            return None
        current_track_id = track_id_match[1]
        track_xpath = (
            f'//div[@id="track_{current_track_id}"]//div[@class="playlist-trackname"]/text()'
        )
        if result := tree.xpath(track_xpath):
            track_text = result[0]
            if track_text != self.last_extracted_track:
                logging.debug("Method 1 success: JavaScript+XPath (track_%s)", current_track_id)
                self.last_extracted_track = track_text
            return track_text
        return None

    @staticmethod
    def _extract_by_position(tree) -> str | None:
        """Extract track using positional XPath (fallback)"""
        if result := tree.xpath('(//div[@class="playlist-trackname"]/text())[1]'):
            logging.debug("Method 2 success: Positional XPath")
            return result[0]
        return None

    @staticmethod
    def _extract_by_pattern(tree) -> str | None:
        """Extract track using text pattern matching (regex fallback)"""
        track_divs = tree.xpath('//div[contains(@class, "playlist-track")]')
        for track_div in track_divs[:3]:  # Check first 3 tracks
            text_content = track_div.text_content()
            # Look for "Artist - Title" pattern
            if (match := re.search(r"([^-\n]+)\s*-\s*([^-\n]+)", text_content)) and len(
                match[0].strip()
            ) > 10:  # Reasonable length
                result = match[0].strip()
                logging.debug("Method 3 success: Text pattern matching")
                return result
        return None

    @staticmethod
    def _extract_by_text_search(tree) -> str | None:
        """Extract track using fallback text search (last resort)"""
        all_text = tree.xpath('//text()[contains(., " - ")]')
        for text in all_text:
            cleaned = text.strip()
            if len(cleaned) > 10 and all(
                skip not in cleaned.lower() for skip in ["copyright", "serato", "playlist"]
            ):
                logging.debug("Method 4 success: Text fallback search")
                return cleaned
        return None

    def _parse_track_text(self, track_text: str) -> None:
        """Parse track text and store in current_track"""
        # Clean up the text (copied from serato3 logic)
        tdat = str(track_text).strip()
        for char in ["['", "']", "[]", "\\n", "\\t", '["', '"]']:
            tdat = tdat.replace(char, "")
        tdat = tdat.strip()

        if not tdat:
            self.current_track = {}
            return

        # Parse artist and title
        if " - " not in tdat:
            artist = None
            title = tdat.strip()
        else:
            # Split on ' - ' and hope artist/title doesn't have similar split
            artist, title = tdat.split(" - ", 1)

        # Clean up artist
        if not artist or artist == ".":
            artist = None
        else:
            artist = artist.strip()

        # Clean up title
        if not title or title == ".":
            title = None
        else:
            title = title.strip()

        # Store the results
        if title or artist:
            self.current_track = {}
            if artist:
                self.current_track["artist"] = artist
            if title:
                self.current_track["title"] = title
        else:
            self.current_track = {}
