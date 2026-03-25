#!/usr/bin/env python3
"""Remote Output Notification Plugin"""

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

import aiohttp

import nowplaying.db
import nowplaying.mdns_discovery
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
        self._discovered_services: list[nowplaying.mdns_discovery.DiscoveredService] | None = None
        self._scan_task: asyncio.Task[None] | None = None

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

    async def _background_scan_loop(self) -> None:
        """Periodically refresh the list of discovered WNP services."""
        while True:
            await asyncio.sleep(60)
            try:
                self._discovered_services = (
                    await nowplaying.mdns_discovery.discover_whatsnowplaying_services_async()
                )
            except Exception:  # pylint: disable=broad-except
                logging.debug("Background mDNS scan error", exc_info=True)

    async def start(self) -> None:
        """Initialize the remote output notification plugin"""
        oldenabled = self.enabled
        if self.config:
            self.enabled = self.config.cparser.value(
                "remote/enabled", type=bool, defaultValue=False
            )
            autodiscover = self.config.cparser.value(
                "remote/autodiscover", type=bool, defaultValue=False
            )
            self.server = self.config.cparser.value(
                "remote/remote_server", defaultValue="remotehost"
            )
            self.port = self.config.cparser.value(
                "remote/remote_port", type=int, defaultValue=8899
            )
            self.key = self.config.cparser.value("remote/remote_key")

            if autodiscover:
                # Do initial scan if none has been done yet
                if self._discovered_services is None:
                    self._discovered_services = (
                        await nowplaying.mdns_discovery.discover_whatsnowplaying_services_async()
                    )

                # Maintain background refresh task
                if self._scan_task is None or self._scan_task.done():
                    self._scan_task = asyncio.create_task(self._background_scan_loop())

                services = self._discovered_services
                if len(services) == 1:
                    service = services[0]
                    self.server = service.addresses[0] if service.addresses else service.host
                    self.port = service.port
                elif len(services) > 1:
                    # Check if saved server/port matches a discovered service
                    match = next(
                        (
                            s
                            for s in services
                            if (s.addresses[0] if s.addresses else s.host) == self.server
                            and s.port == self.port
                        ),
                        None,
                    )
                    service = match or services[0]
                    self.server = service.addresses[0] if service.addresses else service.host
                    self.port = service.port
                    if not match:
                        logging.warning(
                            "Multiple WNP instances found (%d); using %s:%d. "
                            "Open Remote Output settings to select one.",
                            len(services),
                            self.server,
                            self.port,
                        )
                else:
                    logging.warning("Auto-discovery: no WNP services found on the network")
                    self.enabled = False
            else:
                # Cancel background scan when autodiscover is turned off
                if self._scan_task and not self._scan_task.done():
                    self._scan_task.cancel()
                self._scan_task = None
                self._discovered_services = None

        if self.enabled != oldenabled:
            logging.info("Remote output enabled for %s:%d", self.server, self.port)

    async def stop(self) -> None:
        """Clean up the remote output notification plugin"""
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
        self._scan_task = None
        if self.enabled:
            logging.debug("Remote output notifications stopped")

    def defaults(self, qsettings: "QSettings"):  # pylint: disable=no-self-use
        """Set default configuration values"""
        qsettings.setValue("remote/enabled", False)
        qsettings.setValue("remote/autodiscover", False)
        qsettings.setValue("remote/remote_server", "remotehost")
        qsettings.setValue("remote/remote_port", 8899)
        qsettings.setValue("remote/remote_key", "")

    def _populate_discovered_combobox(self, qwidget: "QWidget") -> None:
        """Populate the combobox from cached discovered services."""
        qwidget.discovered_combobox.clear()
        if not self._discovered_services:
            return
        saved_server = self.config.cparser.value("remote/remote_server", defaultValue="")
        saved_port = self.config.cparser.value("remote/remote_port", type=int, defaultValue=8899)
        for i, service in enumerate(self._discovered_services):
            addr = service.addresses[0] if service.addresses else service.host
            qwidget.discovered_combobox.addItem(
                f"{service.host} ({addr}:{service.port})", userData=(addr, service.port)
            )
            if addr == saved_server and service.port == saved_port:
                qwidget.discovered_combobox.setCurrentIndex(i)

    def _scan_for_servers(self, qwidget: "QWidget") -> None:
        """Synchronous scan triggered from the settings UI scan button."""
        services = nowplaying.mdns_discovery.discover_whatsnowplaying_services(timeout=2.0)
        self._discovered_services = services
        # Cancel the background task so it resets its 60-second timer from now
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
            self._scan_task = None
        self._populate_discovered_combobox(qwidget)
        if services:
            qwidget.scan_status_label.setText(f"{len(services)} server(s) found")
            if len(services) == 1:
                qwidget.discovered_combobox.setCurrentIndex(0)
        else:
            qwidget.scan_status_label.setText("No servers found")

    @staticmethod
    def _on_service_selected(qwidget: "QWidget", index: int) -> None:
        """Fill server/port fields when a service is chosen from the combobox."""
        if data := qwidget.discovered_combobox.itemData(index):
            server, port = data
            qwidget.server_lineedit.setText(server)
            qwidget.port_lineedit.setText(str(port))

    def load_settingsui(self, qwidget: "QWidget"):
        """Load settings into UI"""
        qwidget.enable_checkbox.setChecked(
            self.config.cparser.value("remote/enabled", type=bool, defaultValue=False)
        )
        qwidget.autodiscover_checkbox.setChecked(
            self.config.cparser.value("remote/autodiscover", type=bool, defaultValue=False)
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

        self._populate_discovered_combobox(qwidget)

        qwidget.scan_button.clicked.connect(lambda: self._scan_for_servers(qwidget))
        qwidget.discovered_combobox.currentIndexChanged.connect(
            lambda idx: self._on_service_selected(qwidget, idx)
        )
        qwidget.autodiscover_checkbox.stateChanged.connect(
            lambda: self._update_field_states(qwidget)
        )
        self._update_field_states(qwidget)

    def save_settingsui(self, qwidget: "QWidget"):
        """Save settings from UI"""
        self.config.cparser.setValue("remote/enabled", qwidget.enable_checkbox.isChecked())
        self.config.cparser.setValue(
            "remote/autodiscover", qwidget.autodiscover_checkbox.isChecked()
        )
        self.config.cparser.setValue("remote/remote_server", qwidget.server_lineedit.text())
        with contextlib.suppress(ValueError):
            port = int(qwidget.port_lineedit.text())
            self.config.cparser.setValue("remote/remote_port", port)
        self.config.cparser.setValue("remote/remote_key", qwidget.secret_lineedit.text())

    @staticmethod
    def _update_field_states(qwidget: "QWidget") -> None:
        """Show scan widgets and disable manual fields when autodiscover is active."""
        autodiscover = qwidget.autodiscover_checkbox.isChecked()
        qwidget.scan_button.setVisible(autodiscover)
        qwidget.scan_status_label.setVisible(autodiscover)
        qwidget.discovered_combobox.setVisible(autodiscover)
        qwidget.server_lineedit.setEnabled(not autodiscover)
        qwidget.port_lineedit.setEnabled(not autodiscover)

    def verify_settingsui(self, qwidget: "QWidget"):
        """Verify settings"""
        if qwidget.enable_checkbox.isChecked():
            # Only require server/port if autodiscover is not enabled
            if not qwidget.autodiscover_checkbox.isChecked():
                if not qwidget.server_lineedit.text().strip():
                    raise PluginVerifyError(
                        "Remote server address is required when remote output is enabled "
                        "(or enable auto-discover)"
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
