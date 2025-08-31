#!/usr/bin/env python3
"""Charts Output Notification Plugin"""

import asyncio
import json
import logging
import pathlib
from typing import TYPE_CHECKING
import urllib.request
import urllib.error

import aiohttp
from PySide6.QtCore import QStandardPaths  # pylint: disable=import-error, no-name-in-module

import nowplaying.db
from nowplaying.types import TrackMetadata

from . import NotificationPlugin

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.imagecache


def generate_anonymous_key(debug: bool = False) -> str | None:
    """
    Generate an anonymous charts key from the server (standalone function for main process)
    """
    url = (
        "https://localhost:8000api/v1/request-anonymous-key"
        if debug
        else "https://whatsnowplaying.com/api/v1/request-anonymous-key"
    )

    try:
        request = urllib.request.Request(url, method="POST")
        request.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status == 200:
                response_data = response.read()
                result = json.loads(response_data)
                api_key = result.get("api_key")
                message = result.get("message", "")
                if api_key:
                    logging.info("Received anonymous key from charts server: %s", message)
                    return api_key
                logging.error("Charts server returned response without api_key")
                return None
            try:
                error_data = response.read()
                error_response = json.loads(error_data)
                error_detail = error_response.get("detail", "Unknown error")
                logging.error(
                    "Charts server returned status %d: %s", response.status, error_detail
                )
            except Exception:  # pylint: disable=broad-except
                logging.error(
                    "Charts server returned status %d for anonymous key request",
                    response.status,
                )
            return None
    except urllib.error.URLError as exc:
        logging.error("Failed to connect to charts server %s: %s", url, exc)
        return None
    except Exception as exc:  # pylint: disable=broad-except
        logging.error("Failed to request anonymous key from charts server: %s", exc)
        return None


class Plugin(NotificationPlugin):  # pylint: disable=too-many-instance-attributes
    """Charts Output Notification Handler"""

    # Maximum number of items to keep in queue to prevent unbounded growth
    MAX_QUEUE_SIZE = 1000

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        self.debug = False  # Initialize before super() since defaults() needs it
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Charts"
        self.enabled = True  # Default enabled
        self.key: str | None = None
        self.queue: list[TrackMetadata] = []
        self.queue_file: pathlib.Path | None = None
        self._queue_lock = asyncio.Lock()
        self._queue_task: asyncio.Task | None = None

    async def notify_track_change(
        self, metadata: TrackMetadata, imagecache: "nowplaying.imagecache.ImageCache|None" = None
    ) -> None:
        """
        Send track metadata to charts server when a new track becomes live

        Args:
            metadata: Track metadata including artist, title, etc.
            imagecache: Optional imagecache instance (unused by charts output)
        """

        # get a fresh config
        await self.start()
        if not self.enabled:
            return

        # Prepare metadata for charts submission
        charts_data = self._strip_blobs_metadata(metadata)
        if self.key:
            charts_data["secret"] = self.key

        # Add to queue (without secret) and try to send
        queue_data = charts_data.copy()
        if "secret" in queue_data:
            del queue_data["secret"]

        async with self._queue_lock:
            # Limit queue size to prevent unbounded growth during server outages
            if len(self.queue) >= self.MAX_QUEUE_SIZE:
                # Remove oldest item to maintain size limit
                dropped_item = self.queue.pop(0)
                logging.warning(
                    "Charts queue full (%d items), dropping oldest item: %s - %s",
                    self.MAX_QUEUE_SIZE,
                    dropped_item.get("artist", "Unknown Artist"),
                    dropped_item.get("title", "Unknown Title"),
                )

            self.queue.append(queue_data)
            await self._save_queue()

        # Start queue processing if not already running
        if self._queue_task is None or self._queue_task.done():
            self._queue_task = asyncio.create_task(self._process_queue())

    @staticmethod
    def _strip_blobs_metadata(metadata: TrackMetadata) -> TrackMetadata:
        """Strip binary blob data and local system metadata for charts transmission"""
        charts_data = metadata.copy()

        # Remove all blob fields
        for key in nowplaying.db.METADATABLOBLIST:
            charts_data.pop(key, None)

        # Remove any remaining binary data
        bytes_keys = [key for key, value in charts_data.items() if isinstance(value, bytes)]
        for key in bytes_keys:
            charts_data.pop(key, None)

        # Remove local system metadata that shouldn't be sent to charts systems
        local_system_fields = [
            "httpport",
            "hostname",
            "hostfqdn",
            "hostip",
            "ipaddress",
            "previoustrack",
            "dbid",
            "cache_warmed",
            "filename",  # Security: Never send local file paths to remote systems
        ]
        for key in local_system_fields:
            charts_data.pop(key, None)

        # Remove bio, website, image, and comment fields that aren't needed for charts
        extra_fields = [
            "artistlongbio",
            "artistshortbio",
            "artistwebsites",
            "coverimagetype",
            "imagecacheartist",
            "imagecachealbum",
            "comments",
            "comment",
            "coverurl",
            "artistfanarturls",
            "fpcalcfingerprint",
            "fpcalcduration",
        ]
        for key in extra_fields:
            charts_data.pop(key, None)

        return charts_data

    async def start(self) -> None:
        """Initialize the charts output notification plugin"""
        oldenabled = self.enabled
        if self.config:
            self.enabled = self.config.cparser.value(
                "charts/enabled", type=bool, defaultValue=True
            )
            self.key = self.config.cparser.value("charts/charts_key")

            # Key should have been generated in defaults() - if still missing, disable charts
            if not self.key:
                logging.warning("No charts key available - charts will be disabled")
                self.enabled = False

            # Set up queue file path
            cache_dir = pathlib.Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation))
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.queue_file = cache_dir / "charts_queue.json"

            # Load existing queue
            await self._load_queue()

        if self.enabled != oldenabled:
            logging.info("Charts output enabled for localhost:8000")
            async with self._queue_lock:
                if self.enabled and self.queue:
                    # Process any queued items when enabling
                    if self._queue_task is None or self._queue_task.done():
                        self._queue_task = asyncio.create_task(self._process_queue())

    async def stop(self) -> None:
        """Clean up the charts output notification plugin"""
        if self.enabled:
            logging.debug("Charts output notifications stopped")
            # Save any remaining queue items
            async with self._queue_lock:
                await self._save_queue()

            # Cancel and clean up the queue processing task if running
            if self._queue_task is not None and not self._queue_task.done():
                self._queue_task.cancel()
                try:
                    await self._queue_task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # pylint: disable=broad-except
                    logging.error("Error while stopping queue task: %s", exc)
                self._queue_task = None

    async def _load_queue(self) -> None:
        """Load queued items from disk"""
        if not self.queue_file or not self.queue_file.exists():
            return

        try:
            with open(self.queue_file, encoding="utf-8") as queue_file:
                queue_data = json.load(queue_file)
                async with self._queue_lock:
                    self.queue = queue_data
                    logging.info("Loaded %d queued charts submissions", len(self.queue))
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Failed to load charts queue: %s", exc)
            async with self._queue_lock:
                self.queue = []

    async def _save_queue(self) -> None:
        """Save queued items to disk"""
        if not self.queue_file:
            return

        try:
            if self.queue:
                # Save queue to file
                with open(self.queue_file, "w", encoding="utf-8") as queue_file:
                    json.dump(self.queue, queue_file, indent=2)
            # Delete file when queue is empty
            elif self.queue_file.exists():
                self.queue_file.unlink()
                logging.debug("Deleted empty charts queue file")
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Failed to save charts queue: %s", exc)

    async def _process_queue(self) -> None:
        """Process queued submissions"""
        # Refresh config to get latest key and debug flag
        if self.config:
            self.key = self.config.cparser.value("charts/charts_key")

        while True:
            async with self._queue_lock:
                if not self.queue:
                    break
                queue_item = self.queue[0]  # Get first item

            # Add secret back for sending (not stored in queue)
            charts_data = queue_item.copy()
            if self.key:
                charts_data["secret"] = self.key

            result = await self._send_to_charts(charts_data)
            if result == "success":
                async with self._queue_lock:
                    # Remove successfully sent item
                    self.queue.pop(0)
                    await self._save_queue()
                    logging.debug(
                        "Charts submission successful, %d items remaining in queue",
                        len(self.queue),
                    )
            elif result == "drop":
                async with self._queue_lock:
                    # Drop the problematic item and continue
                    dropped_item = self.queue.pop(0)
                    await self._save_queue()
                    logging.warning(
                        "Dropped charts submission due to client error: %s - %s, %d remaining",
                        dropped_item.get("artist", "Unknown Artist"),
                        dropped_item.get("title", "Unknown Title"),
                        len(self.queue),
                    )
            else:  # result == "retry"
                # Failed to send, leave in queue and stop processing
                async with self._queue_lock:
                    logging.debug(
                        "Charts submission failed, %d items remaining in queue",
                        len(self.queue),
                    )
                break

            # Small delay between submissions (outside lock)
            await asyncio.sleep(0.1)

    async def _send_to_charts(  # pylint: disable=too-many-statements,too-many-return-statements,too-many-branches
        self, charts_data: TrackMetadata
    ) -> str:
        """
        Send a single item to charts server

        Returns:
            "success": Item sent successfully, remove from queue and continue
            "retry": Failed to send, keep in queue and stop processing (retry later)
            "drop": Drop this item from queue and continue processing
        """
        # Choose URL based on debug flag
        url = (
            "http://localhost:8000/v1/submit"
            if self.debug
            else "https://whatsnowplaying.com/v1/submit"
        )

        try:
            # Remove non-JSON-serializable fields to prevent submission failures
            non_serializable_keys = []
            for key, value in charts_data.items():
                if not isinstance(value, (str, int, float, bool, list, dict, type(None))):
                    non_serializable_keys.append(key)
                    logging.warning(
                        "Removing non-JSON-serializable field %s: %s (%s)", key, value, type(value)
                    )

            for key in non_serializable_keys:
                charts_data.pop(key, None)

            # Debug: log data being sent (without secret)
            debug_data = dict(charts_data)
            if "secret" in debug_data:
                debug_data["secret"] = "***REDACTED***"
            logging.info("Charts submission data keys: %s", list(debug_data.keys()))
            logging.debug("Charts submission data: %s", debug_data)

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.post(
                    url,
                    json=charts_data,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    logging.debug("Sending to %s", url)
                    if response.status == 200:
                        try:
                            result = await response.json()
                            logging.debug("Charts server accepted track update: %s", result)
                            return "success"
                        except Exception as exc:  # pylint: disable=broad-except
                            logging.warning("Failed to parse charts server response: %s", exc)
                            return "success"  # Still consider it successful if status was 200
                    elif response.status == 400:
                        try:
                            error_text = await response.text()
                            logging.error(
                                "Charts server rejected malformed data (400): %s", error_text
                            )
                        except Exception:  # pylint: disable=broad-except
                            logging.error("Charts server rejected malformed data (400)")
                        return "drop"  # Drop malformed data, continue processing
                    elif response.status == 401:
                        try:
                            error_text = await response.text()
                            logging.error(
                                "Charts server authentication failed (401): %s", error_text
                            )
                        except Exception:  # pylint: disable=broad-except
                            logging.error("Charts server authentication failed (401)")
                        return "retry"  # Stop processing, auth needs to be fixed
                    elif response.status == 403:
                        try:
                            error_text = await response.text()
                            logging.error(
                                "Charts server authentication failed (403): %s", error_text
                            )
                        except Exception:  # pylint: disable=broad-except
                            logging.error("Charts server authentication failed (403)")
                        return "retry"  # Stop processing, auth needs to be fixed
                    elif response.status == 498:
                        # Key rotation required
                        try:
                            rotation_response = await response.json()
                            if await self._handle_key_rotation(rotation_response):
                                return "retry"  # Retry with new key
                            else:
                                return "drop"  # Rotation failed, drop item
                        except Exception as exc:  # pylint: disable=broad-except
                            logging.error("Failed to handle key rotation response: %s", exc)
                            return "retry"
                    elif response.status == 404:
                        try:
                            error_text = await response.text()
                            logging.error("Charts server endpoint not found (404): %s", error_text)
                        except Exception:  # pylint: disable=broad-except
                            logging.error("Charts server endpoint not found (404)")
                        return "drop"  # Drop item, endpoint won't change
                    elif response.status == 405:
                        try:
                            error_text = await response.text()
                            logging.error("Charts server method not allowed (405): %s", error_text)
                        except Exception:  # pylint: disable=broad-except
                            logging.error(
                                "Charts server method not allowed (405) - check endpoint"
                            )
                        return "drop"  # Drop item, method won't change
                    elif response.status == 429:
                        try:
                            error_text = await response.text()
                            logging.warning("Charts server rate limited (429): %s", error_text)
                        except Exception:  # pylint: disable=broad-except
                            logging.warning("Charts server rate limited (429)")
                        return "retry"  # Stop processing, retry later with backoff
                    elif 400 <= response.status < 500:
                        # Other 4xx client errors - drop the item
                        try:
                            error_text = await response.text()
                            logging.error(
                                "Charts server client error %d: %s", response.status, error_text
                            )
                        except Exception:  # pylint: disable=broad-except
                            logging.error("Charts server client error %d", response.status)
                        return "drop"  # Drop item, client error won't resolve by retrying
                    else:
                        # 5xx server errors - retry later
                        try:
                            error_text = await response.text()
                            logging.error(
                                "Charts server error %d: %s", response.status, error_text
                            )
                        except Exception:  # pylint: disable=broad-except
                            logging.error("Charts server returned status %d", response.status)
                        return "retry"  # Retry later, server may recover
        except aiohttp.ClientError as exc:
            logging.error("Failed to connect to charts server %s - %s", url, exc)
            return "retry"  # Network issues, retry later
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Unexpected error sending to charts server: %s - %s", url, exc)
            return "retry"  # Unexpected error, retry later

    async def _request_anonymous_key(self) -> str | None:
        """Request an anonymous key from the charts server"""
        url = (
            "http://localhost:8000/api/v1/request-anonymous-key"
            if self.debug
            else "https://whatsnowplaying.com/api/v1/request-anonymous-key"
        )

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.post(url) as response:
                    if response.status == 200:
                        try:
                            result = await response.json()
                            api_key = result.get("api_key")
                            message = result.get("message", "")
                            if api_key:
                                logging.info(
                                    "Received anonymous key from charts server: %s", message
                                )
                                return api_key
                            logging.error("Charts server returned response without api_key")
                            return None
                        except Exception as exc:  # pylint: disable=broad-except
                            logging.error("Failed to parse anonymous key response: %s", exc)
                            return None
                    else:
                        try:
                            error_response = await response.json()
                            error_detail = error_response.get("detail", "Unknown error")
                            logging.error(
                                "Charts server returned status %d: %s",
                                response.status,
                                error_detail,
                            )
                        except Exception:  # pylint: disable=broad-except
                            logging.error(
                                "Charts server returned status %d for anonymous key request",
                                response.status,
                            )
                        return None
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Failed to request anonymous key from charts server: %s", exc)
            return None

    async def _handle_key_rotation(self, rotation_response: dict) -> bool:
        """
        Handle key rotation when server returns 498 status

        Args:
            rotation_response: JSON response containing rotation details

        Returns:
            bool: True if rotation was successful, False otherwise
        """
        try:
            logging.debug("Full 498 rotation response: %s", rotation_response)
            rotation = rotation_response.get("rotation", {})
            logging.debug("Extracted rotation object: %s", rotation)
            secret = rotation.get("secret")
            endpoint = rotation.get("endpoint", "/v1/rotate-key")
            expires_in = rotation.get("expires_in", 900)

            if not secret:
                logging.error("Key rotation response missing secret")
                logging.error(
                    "Expected 'rotation.secret' but got rotation keys: %s",
                    list(rotation.keys()) if rotation else "None",
                )
                return False

            logging.info("Charts key rotation required, expires in %d seconds", expires_in)

            # Choose URL based on debug flag
            base_url = "http://localhost:8000" if self.debug else "https://whatsnowplaying.com"
            rotate_url = f"{base_url}{endpoint}"

            # Prepare rotation request
            rotation_data = {"old_api_key": self.key, "rotation_secret": secret}

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.post(
                    rotate_url, json=rotation_data, headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        new_key = result.get("new_api_key")
                        message = result.get("message", "")
                        if new_key and self.config:
                            # Save new key
                            self.config.cparser.setValue("charts/charts_key", new_key)
                            self.config.cparser.sync()
                            self.key = new_key
                            logging.info("Charts key rotated successfully: %s", message)
                            return True
                        else:
                            logging.error("Key rotation response missing new_api_key")
                            return False
                    elif response.status in (401, 403):
                        # Key is completely invalid - delete it
                        try:
                            error_text = await response.text()
                            logging.error(
                                "Key rotation failed - key no longer valid (%d): %s",
                                response.status,
                                error_text,
                            )
                        except Exception:  # pylint: disable=broad-except
                            logging.error(
                                "Key rotation failed - key no longer valid (%d)", response.status
                            )

                        # Clear the invalid key from config
                        if self.config:
                            self.config.cparser.remove("charts/charts_key")
                            self.config.cparser.sync()
                            self.key = None
                            logging.warning(
                                "Invalid charts key deleted - please get a new key from dashboard"
                            )
                        return False
                    else:
                        try:
                            error_text = await response.text()
                            logging.error(
                                "Key rotation failed with status %d: %s",
                                response.status,
                                error_text,
                            )
                        except Exception:  # pylint: disable=broad-except
                            logging.error("Key rotation failed with status %d", response.status)
                        return False

        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Failed to rotate charts key: %s", exc)
            return False

    def _request_anonymous_key_sync(self) -> str | None:
        """Request an anonymous key from the charts server (synchronous version)"""
        url = (
            "http://localhost:8000/api/v1/request-anonymous-key"
            if self.debug
            else "https://whatsnowplaying.com/api/v1/request-anonymous-key"
        )

        try:
            request = urllib.request.Request(url, method="POST")
            request.add_header("Content-Type", "application/json")

            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status == 200:
                    response_data = response.read()
                    result = json.loads(response_data)
                    api_key = result.get("api_key")
                    message = result.get("message", "")
                    if api_key:
                        logging.info("Received anonymous key from charts server: %s", message)
                        return api_key
                    logging.error("Charts server returned response without api_key")
                    return None
                try:
                    error_data = response.read()
                    error_response = json.loads(error_data)
                    error_detail = error_response.get("detail", "Unknown error")
                    logging.error(
                        "Charts server returned status %d: %s", response.status, error_detail
                    )
                except Exception:  # pylint: disable=broad-except
                    logging.error(
                        "Charts server returned status %d for anonymous key request",
                        response.status,
                    )
                return None
        except urllib.error.URLError as exc:
            logging.error("Failed to connect to charts server %s: %s", url, exc)
            return None
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Failed to request anonymous key from charts server: %s", exc)
            return None

    def defaults(self, qsettings: "QSettings"):
        """Set default configuration values"""
        qsettings.setValue("charts/enabled", True)
        qsettings.setValue("charts/charts_key", "")

    def load_settingsui(self, qwidget: "QWidget"):
        """Load settings into UI"""
        qwidget.enable_checkbox.setChecked(
            self.config.cparser.value("charts/enabled", type=bool, defaultValue=True)
        )
        qwidget.secret_lineedit.setText(
            self.config.cparser.value("charts/charts_key", defaultValue="")
        )

    def save_settingsui(self, qwidget: "QWidget"):
        """Save settings from UI"""
        self.config.cparser.setValue("charts/enabled", qwidget.enable_checkbox.isChecked())
        self.config.cparser.setValue("charts/charts_key", qwidget.secret_lineedit.text())

    def verify_settingsui(self, qwidget: "QWidget"):
        """Verify settings"""
        # No verification needed - anonymous key will be auto-generated if empty
        return True

    def desc_settingsui(self, qwidget: "QWidget"):
        """Description for settings UI"""
        qwidget.setText(
            "Send track metadata to charts server at localhost:8000/v1/submit when tracks change"
        )
