#!/usr/bin/env python3
"""Charts Output Notification Plugin"""

import asyncio
import json
import logging
import pathlib
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

import aiohttp
from PySide6.QtCore import QStandardPaths  # pylint: disable=import-error, no-name-in-module

import nowplaying.db
import nowplaying.version  # pylint: disable=no-name-in-module,import-error
from nowplaying.types import TrackMetadata

from . import NotificationPlugin

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.imagecache


# Base URLs for charts service
LOCAL_BASE_URL = "http://localhost:8000"
PROD_BASE_URL = "https://whatsnowplaying.com"

# HTTP status code handling for charts submissions
HTTP_STATUS_ACTIONS = {
    200: ("success", "debug", "Charts server accepted submission"),
    400: ("drop", "error", "Charts server rejected malformed data"),
    401: ("retry", "error", "Charts server authentication failed"),
    403: ("retry", "error", "Charts server authentication failed"),
    404: ("drop", "error", "Charts server endpoint not found"),
    405: ("drop", "error", "Charts server method not allowed"),
    429: ("retry", "warning", "Charts server rate limited"),
}


def generate_anonymous_key(debug: bool = False) -> str | None:
    """
    Generate an anonymous charts key from the server (standalone function for main process)
    """
    url = (
        "https://localhost:8000/api/v1/request-anonymous-key"
        if debug
        else "https://whatsnowplaying.com/api/v1/request-anonymous-key"
    )

    try:
        data = json.dumps({"version": nowplaying.version.__VERSION__}).encode("utf-8")  # pylint: disable=no-member
        request = urllib.request.Request(url, data=data, method="POST")
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
        self._queue_lock: asyncio.Lock | None = None  # Lazy initialization for event loop
        self._queue_task: asyncio.Task | None = None
        self.base_url = LOCAL_BASE_URL if self.debug else PROD_BASE_URL
        self._session: aiohttp.ClientSession | None = None

    def _get_queue_lock(self) -> asyncio.Lock:
        """Get or create the queue lock (lazy initialization for event loop compatibility)"""
        if self._queue_lock is None:
            self._queue_lock = asyncio.Lock()
        return self._queue_lock

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

        async with self._get_queue_lock():
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

            # Load existing queue (protected by lock to prevent race with _process_queue)
            async with self._get_queue_lock():
                await self._load_queue()

        if self.enabled != oldenabled:
            logging.info("Charts output enabled for localhost:8000")
            async with self._get_queue_lock():
                if self.enabled and self.queue:
                    # Process any queued items when enabling
                    if self._queue_task is None or self._queue_task.done():
                        self._queue_task = asyncio.create_task(self._process_queue())

    async def stop(self) -> None:
        """Clean up the charts output notification plugin"""
        if self.enabled:
            logging.debug("Charts output notifications stopped")
            # Save any remaining queue items
            async with self._get_queue_lock():
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

        # Close aiohttp session
        await self._close_session()

    async def _load_queue(self) -> None:
        """Load queued items from disk"""
        if not self.queue_file or not self.queue_file.exists():
            return

        try:
            with open(self.queue_file, encoding="utf-8") as queue_file:
                queue_data = json.load(queue_file)
                async with self._get_queue_lock():
                    self.queue = queue_data
                    logging.info("Loaded %d queued charts submissions", len(self.queue))
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Failed to load charts queue: %s", exc)
            async with self._get_queue_lock():
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
            async with self._get_queue_lock():
                if not self.queue:
                    break
                queue_item = self.queue[0]  # Get first item

            # Add secret back for sending (not stored in queue)
            charts_data = queue_item.copy()
            if self.key:
                charts_data["secret"] = self.key

            result = await self._send_to_charts(charts_data)
            if result == "success":
                async with self._get_queue_lock():
                    # Remove successfully sent item
                    self.queue.pop(0)
                    await self._save_queue()
                    logging.debug(
                        "Charts submission successful, %d items remaining in queue",
                        len(self.queue),
                    )
            elif result == "drop":
                async with self._get_queue_lock():
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
                async with self._get_queue_lock():
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
        url = f"{self.base_url}/v1/submit"

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

            session = await self._get_session()
            async with session.post(
                url,
                json=charts_data,
                headers={"Content-Type": "application/json"},
            ) as response:
                logging.debug("Sending to %s", url)

                # Handle special case for key rotation
                if response.status == 498:
                    try:
                        rotation_response = await response.json()
                        if await self._handle_key_rotation(rotation_response):
                            return "retry"  # Retry with new key
                        return "drop"  # Rotation failed, drop item
                    except Exception:  # pylint: disable=broad-except
                        logging.exception("Failed to handle key rotation response")
                        return "retry"

                # Handle successful response with optional JSON parsing
                if response.status == 200:
                    try:
                        result = await response.json()
                        logging.debug("Charts server accepted track update: %s", result)
                    except Exception as exc:  # pylint: disable=broad-except
                        logging.warning("Failed to parse charts server response: %s", exc)
                        # Still consider it successful if status was 200
                    return "success"

                # Handle all other status codes using shared logic
                try:
                    error_text = await response.text()
                except Exception:  # pylint: disable=broad-except
                    error_text = ""

                return self._handle_http_response(response.status, error_text)
        except aiohttp.ClientError as exc:
            logging.error("Failed to connect to charts server %s - %s", url, exc)
            return "retry"  # Network issues, retry later
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Unexpected error sending to charts server: %s - %s", url, exc)
            return "retry"  # Unexpected error, retry later

    async def _request_anonymous_key(self) -> str | None:
        """Request an anonymous key from the charts server"""
        url = f"{self.base_url}/api/v1/request-anonymous-key"

        try:
            session = await self._get_session()
            data = {"version": nowplaying.version.__VERSION__}  # pylint: disable=no-member
            async with session.post(
                url, json=data, headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    try:
                        result = await response.json()
                        api_key = result.get("api_key")
                        message = result.get("message", "")
                        if api_key:
                            logging.info("Received anonymous key from charts server: %s", message)
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

    @staticmethod
    def _handle_http_response(status: int, response_text: str = "") -> str:
        """
        Handle HTTP response status codes for charts submissions

        Args:
            status: HTTP status code
            response_text: Response body text for logging

        Returns:
            str: Action to take ("success", "retry", "drop")
        """
        # Check for specific status codes first
        if status in HTTP_STATUS_ACTIONS:
            action, log_level, message = HTTP_STATUS_ACTIONS[status]
            full_message = f"{message} ({status}): {response_text}"

            if log_level == "warning":
                logging.warning(full_message)
            elif log_level == "error":
                logging.error(full_message)
            elif log_level == "info":
                logging.info(full_message)
            elif log_level == "debug":
                logging.debug(full_message)

            return action

        # Handle ranges for unlisted status codes
        if 400 <= status < 500:
            logging.error("Charts server client error %d: %s", status, response_text)
            return "drop"  # Client errors won't resolve by retrying
        logging.error("Charts server error %d: %s", status, response_text)
        return "retry"  # Server errors may recover

    @staticmethod
    def _is_valid_api_key(key: str) -> bool:
        """
        Validate API key format

        Args:
            key: API key to validate

        Returns:
            bool: True if key format is valid
        """
        # API keys should be non-empty strings with reasonable length
        return isinstance(key, str) and len(key.strip()) >= 10

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60)  # 1 minute timeout to prevent blocking
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _close_session(self) -> None:
        """Close aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _rotate_key(self, secret: str, endpoint: str) -> tuple[bool, str | None]:
        """
        Perform the actual key rotation HTTP request

        Args:
            secret: Rotation secret from 498 response
            endpoint: Rotation endpoint from 498 response

        Returns:
            Tuple of (success: bool, new_key: str | None)
        """
        rotate_url = f"{self.base_url}{endpoint}"
        rotation_data = {"old_api_key": self.key, "rotation_secret": secret}

        session = await self._get_session()
        async with session.post(
            rotate_url, json=rotation_data, headers={"Content-Type": "application/json"}
        ) as response:
            if response.status == 200:
                result = await response.json()
                new_key = result.get("new_api_key")
                if new_key and self._is_valid_api_key(new_key):
                    message = result.get("message", "")
                    logging.info("Charts key rotated successfully: %s", message)
                    return True, new_key
                logging.error("Key rotation response missing valid new_api_key")
                return False, None
            if response.status in (401, 403):
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
                return False, None

            try:
                error_text = await response.text()
                logging.error(
                    "Key rotation failed with status %d: %s",
                    response.status,
                    error_text,
                )
            except Exception:  # pylint: disable=broad-except
                logging.error("Key rotation failed with status %d", response.status)
            return False, None

    async def _handle_key_rotation(self, rotation_response: dict) -> bool:
        """
        Handle key rotation when server returns 498 status

        Args:
            rotation_response: JSON response containing rotation details

        Returns:
            bool: True if rotation was successful, False otherwise
        """
        try:
            rotation = rotation_response.get("rotation", {})
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

            # Attempt key rotation
            success, new_key = await self._rotate_key(secret, endpoint)

            if success and new_key and self.config:
                # Save new key
                self.config.cparser.setValue("charts/charts_key", new_key)
                self.config.cparser.sync()
                self.key = new_key
                return True

            if not success:
                # Key is invalid - delete it
                if self.config:
                    self.config.cparser.remove("charts/charts_key")
                    self.config.cparser.sync()
                    self.key = None
                    logging.warning(
                        "Invalid charts key deleted - please get a new key from dashboard"
                    )
                return False
            logging.error("Key rotation succeeded but missing config or key")
            return False

        except Exception:  # pylint: disable=broad-except
            logging.exception("Failed to handle key rotation")
            return False

    def _request_anonymous_key_sync(self) -> str | None:
        """Request an anonymous key from the charts server (synchronous version)"""
        url = f"{self.base_url}/api/v1/request-anonymous-key"

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
