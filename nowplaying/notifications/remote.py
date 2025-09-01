#!/usr/bin/env python3
"""Remote Output Notification Plugin"""

import contextlib
import logging
from typing import TYPE_CHECKING

import aiohttp

import nowplaying.db
from nowplaying.exceptions import PluginVerifyError
from nowplaying.types import TrackMetadata

from . import NotificationPlugin

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings  # pylint: disable=no-name-in-module
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.imagecache


class Plugin(NotificationPlugin):
    """Remote Output Notification Handler"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Remote Output"
        self.enabled = False
        self.server = "remotehost"
        self.port = 8899
        self.key: str | None = None

    async def notify_track_change(
        self, metadata: TrackMetadata, imagecache: "nowplaying.imagecache.ImageCache|None" = None
    ) -> None:
        """
        Send track metadata to remote server when a new track becomes live

        Args:
            metadata: Track metadata including artist, title, etc.
            imagecache: Optional imagecache instance (unused by remote output)
        """

        # get a fresh config
        await self.start()
        if not self.enabled:
            return

        # Prepare metadata with secret for authentication
        remote_data = self._strip_blobs_metadata(metadata)
        if self.key:
            remote_data["secret"] = self.key

        # Prepare debug data without secret
        debug_data = dict(remote_data)
        if "secret" in debug_data:
            debug_data["secret"] = "***REDACTED***"

        # Debug: write JSON to file to inspect
        # try:
        #     debug_file = "/tmp/remote_debug.json"
        #     with open(debug_file, "w", encoding="utf-8") as fnout:
        #         json.dump(debug_data, fnout, indent=2)
        #     logging.info("Debug: wrote remote data to %s", debug_file)
        # except Exception:  # pylint: disable=broad-except
        #     logging.exception("Failed to write debug JSON")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://{self.server}:{self.port}/v1/remoteinput", json=remote_data
                ) as response:
                    logging.debug("Sending to %s:%s", self.server, self.port)
                    if response.status == 200:
                        try:
                            result = await response.json()
                            dbid = result.get("dbid")
                            logging.debug("Remote server accepted track update, dbid: %s", dbid)
                        except Exception as exc:  # pylint: disable=broad-except
                            logging.warning("Failed to parse remote server response: %s", exc)
                    elif response.status == 403:
                        logging.error("Remote server authentication failed - check remote secret")
                    elif response.status == 405:
                        logging.error("Remote server method not allowed - check endpoint")
                    else:
                        try:
                            error_text = await response.text()
                            logging.error(
                                "Remote server error %d: %s", response.status, error_text
                            )
                        except Exception:  # pylint: disable=broad-except
                            logging.error("Remote server returned status %d", response.status)
        except aiohttp.ClientError as exc:
            logging.error(
                "Failed to connect to remote server %s:%s - %s", self.server, self.port, exc
            )
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Unexpected error sending to remote server: %s", exc)

    @staticmethod
    def _strip_blobs_metadata(metadata: TrackMetadata) -> TrackMetadata:
        """Strip binary blob data and local system metadata for remote transmission"""
        remote_data = metadata.copy()

        # Remove all blob fields
        for key in nowplaying.db.METADATABLOBLIST:
            remote_data.pop(key, None)

        # Remove any remaining binary data
        bytes_keys = [key for key, value in remote_data.items() if isinstance(value, bytes)]
        for key in bytes_keys:
            logging.error("%s was dropped from remote_data (bytes)", key)
            remote_data.pop(key, None)

        # Remove local system metadata that shouldn't be sent to remote systems
        local_system_fields = [
            "httpport",
            "hostname",
            "hostfqdn",
            "hostip",
            "ipaddress",
            "previoustrack",
            "dbid",
            "cache_warmed",
        ]
        for key in local_system_fields:
            remote_data.pop(key, None)

        return remote_data

    async def start(self) -> None:
        """Initialize the remote output notification plugin"""
        oldenabled = self.enabled
        if self.config:
            self.enabled = self.config.cparser.value(
                "remote/enabled", type=bool, defaultValue=False
            )
            self.server = self.config.cparser.value(
                "remote/remote_server", defaultValue="remotehost"
            )
            self.port = self.config.cparser.value(
                "remote/remote_port", type=int, defaultValue=8899
            )
            self.key = self.config.cparser.value("remote/remote_key")

        if self.enabled != oldenabled:
            logging.info("Remote output enabled for %s:%d", self.server, self.port)

    async def stop(self) -> None:
        """Clean up the remote output notification plugin"""
        if self.enabled:
            logging.debug("Remote output notifications stopped")

    def defaults(self, qsettings: "QSettings"):
        """Set default configuration values"""
        qsettings.setValue("remote/enabled", False)
        qsettings.setValue("remote/remote_server", "remotehost")
        qsettings.setValue("remote/remote_port", 8899)
        qsettings.setValue("remote/remote_key", "")

    def load_settingsui(self, qwidget: "QWidget"):
        """Load settings into UI"""
        qwidget.enable_checkbox.setChecked(
            self.config.cparser.value("remote/enabled", type=bool, defaultValue=False)
        )
        qwidget.server_lineedit.setText(
            self.config.cparser.value("remote/remote_server", defaultValue="remotehost")
        )
        qwidget.port_lineedit.setText(
            str(self.config.cparser.value("remote/remote_port", type=int, defaultValue=8899))
        )
        qwidget.secret_lineedit.setText(
            self.config.cparser.value("remote/remote_key", defaultValue="")
        )

    def save_settingsui(self, qwidget: "QWidget"):
        """Save settings from UI"""
        self.config.cparser.setValue("remote/enabled", qwidget.enable_checkbox.isChecked())
        self.config.cparser.setValue("remote/remote_server", qwidget.server_lineedit.text())
        with contextlib.suppress(ValueError):
            port = int(qwidget.port_lineedit.text())
            self.config.cparser.setValue("remote/remote_port", port)
        self.config.cparser.setValue("remote/remote_key", qwidget.secret_lineedit.text())

    def verify_settingsui(self, qwidget: "QWidget"):
        """Verify settings"""
        if qwidget.enable_checkbox.isChecked():
            if not qwidget.server_lineedit.text().strip():
                raise PluginVerifyError(
                    "Remote server address is required when remote output is enabled"
                )
            try:
                port = int(qwidget.port_lineedit.text())
                if not 1 <= port <= 65535:
                    raise PluginVerifyError("Remote port must be between 1 and 65535")
            except ValueError as err:
                raise PluginVerifyError("Remote port must be a valid number") from err
        return True

    def desc_settingsui(self, qwidget: "QWidget"):
        """Description for settings UI"""
        qwidget.setText(
            "Send track metadata to remote What's Now Playing server when tracks change"
        )
