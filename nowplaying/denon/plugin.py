#!/usr/bin/env python3
"""
Denon DJ StagelinQ Main Plugin

This module contains the main plugin class that coordinates all the StagelinQ components.
It handles the plugin lifecycle, UI integration, and high-level coordination between
the protocol handler, connection manager, and metadata processor.
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import nowplaying.upgrades
from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata

from .connection import ConnectionManager
from .metadata import MetadataProcessor
from .protocol import StagelinqProtocol
from .types import DenonDevice, DenonState

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.uihelp

# Seconds before retrying a device that failed to connect or had no StateMap
FAILURE_BACKOFF_SECONDS = 30.0


class DenonPlugin(InputPlugin):  # pylint: disable=too-many-instance-attributes
    """Denon DJ StagelinQ input plugin"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Denon DJ"

        # Initialize components
        self.token = StagelinqProtocol.generate_token()
        self.connection_manager = ConnectionManager(self.token)
        self.metadata_processor = MetadataProcessor(config)

        # Plugin state
        self._discovery_timeout = 5.0
        # tokens with a connection attempt currently in flight
        self._attempting: set[bytes] = set()
        # monotonic deadline before which a failed device is not retried
        self._backoff_until: dict[bytes, float] = {}
        # references to in-flight setup/cleanup tasks; pruned on reconcile
        self._setup_tasks: set[asyncio.Task] = set()

    def install(self) -> bool:
        """Auto-install detection - StagelinQ devices are network-based"""
        # Cannot auto-detect network devices, user must configure manually
        return False

    def get_source_agent_data(self) -> dict:
        """Return source agent data including device software version from StagelinQ discovery."""
        data = super().get_source_agent_data()
        # Devices can run mixed firmware; report the lowest version present
        # so the choice is deterministic rather than connection-order luck
        versions = [
            conn.device.software_version
            for conn in self.connection_manager.active.values()
            if conn.device.software_version
        ]
        if versions:
            try:
                lowest = min(versions, key=nowplaying.upgrades.Version)
            except ValueError:
                # Firmware strings are not guaranteed to parse as semver;
                # fall back to lexicographic, still deterministic
                lowest = min(versions)
            data["source_agent_version"] = lowest
        return data

    def defaults(self, qsettings: "QSettings | None"):
        """Set default configuration values"""
        qsettings.setValue("denon/discovery_timeout", 5.0)
        qsettings.setValue("denon/deckskip", "")

    def connect_settingsui(self, qwidget: "QWidget", uihelp: "nowplaying.uihelp.UIHelp"):
        """Connect UI elements"""
        self.qwidget = qwidget
        self.uihelp = uihelp

    def load_settingsui(self, qwidget: "QWidget"):
        """Load configuration values into UI"""
        timeout = self.config.cparser.value(
            "denon/discovery_timeout", type=float, defaultValue=5.0
        )
        qwidget.denon_timeout_spinbox.setValue(timeout)

        # Load deck skip settings
        self._load_deckskip_settings(qwidget)

    def save_settingsui(self, qwidget: "QWidget"):
        """Save UI values to configuration"""
        self.config.cparser.setValue(
            "denon/discovery_timeout", qwidget.denon_timeout_spinbox.value()
        )

        # Save deck skip settings
        self._save_deckskip_settings(qwidget)

    def _load_deckskip_settings(self, qwidget: "QWidget"):
        """Load deck skip checkbox settings"""
        deckskip = self.config.cparser.value("denon/deckskip")

        # Reset all checkboxes first
        qwidget.denon_deck1_skip_checkbox.setChecked(False)
        qwidget.denon_deck2_skip_checkbox.setChecked(False)
        qwidget.denon_deck3_skip_checkbox.setChecked(False)
        qwidget.denon_deck4_skip_checkbox.setChecked(False)

        if not deckskip:
            return

        if not isinstance(deckskip, list):
            deckskip = list(deckskip)

        # Set checkboxes for decks that should be skipped
        if "1" in deckskip:
            qwidget.denon_deck1_skip_checkbox.setChecked(True)
        if "2" in deckskip:
            qwidget.denon_deck2_skip_checkbox.setChecked(True)
        if "3" in deckskip:
            qwidget.denon_deck3_skip_checkbox.setChecked(True)
        if "4" in deckskip:
            qwidget.denon_deck4_skip_checkbox.setChecked(True)

    def _save_deckskip_settings(self, qwidget: "QWidget"):
        """Save deck skip checkbox settings"""
        deckskip = []

        if qwidget.denon_deck1_skip_checkbox.isChecked():
            deckskip.append("1")
        if qwidget.denon_deck2_skip_checkbox.isChecked():
            deckskip.append("2")
        if qwidget.denon_deck3_skip_checkbox.isChecked():
            deckskip.append("3")
        if qwidget.denon_deck4_skip_checkbox.isChecked():
            deckskip.append("4")

        self.config.cparser.setValue("denon/deckskip", deckskip)

    def desc_settingsui(self, qwidget: "QWidget"):
        """Provide plugin description"""
        qwidget.setText(
            "Denon DJ StagelinQ protocol support for compatible Denon DJ mixers and players. "
            "Requires devices to be on the same network."
        )

    def validmixmodes(self) -> list[str]:
        """Valid mix modes for Denon DJ plugin"""
        return ["newest", "oldest"]

    def setmixmode(self, mixmode: str) -> str:
        """Set the mix mode"""
        return self.metadata_processor.set_mixmode(mixmode)

    def getmixmode(self) -> str:
        """Get the current mix mode"""
        return self.metadata_processor.get_mixmode()

    async def start(self):
        """Initialize the StagelinQ connection"""
        logging.info("Starting Denon StagelinQ plugin")

        try:
            # Start continuous announcement task
            announce_task = asyncio.create_task(self.connection_manager.send_announcements())
            self.connection_manager.tasks.append(announce_task)

            # Start device discovery and connection task
            connect_task = asyncio.create_task(self._find_and_connect())
            self.connection_manager.tasks.append(connect_task)

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.error("Failed to start Denon plugin: %s", err)

    async def _find_and_connect(self):
        """Continuously discover devices and connect to any new ones"""
        try:
            while True:
                try:
                    self._discovery_timeout = self.config.cparser.value(
                        "denon/discovery_timeout", type=float, defaultValue=5.0
                    )

                    # Discover devices
                    devices = await self.connection_manager.discover_devices(
                        self._discovery_timeout
                    )
                    logging.debug(
                        "Discovery pass found %d connectable device(s); %d connected",
                        len(devices),
                        len(self.connection_manager.active),
                    )
                    self._reconcile_devices(devices)
                    await asyncio.sleep(10.0)

                except Exception:  # pylint: disable=broad-exception-caught
                    logging.exception("Error in device discovery")
                    await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            logging.debug("Device discovery cancelled")
            raise

    def _reconcile_devices(self, devices: list[DenonDevice]) -> None:
        """Spawn connection attempts for newly discovered devices"""
        self._setup_tasks = {task for task in self._setup_tasks if not task.done()}
        now = time.monotonic()

        for device in devices:
            if device.token in self.connection_manager.active:
                continue
            if device.token in self._attempting:
                continue
            if now < self._backoff_until.get(device.token, 0.0):
                continue

            logging.info(
                "Discovered Denon device: %s (%s) at %s",
                device.name,
                device.software_name,
                device.ipaddr,
            )
            self._attempting.add(device.token)
            self._setup_tasks.add(asyncio.create_task(self._setup_device(device)))

    async def _setup_device(self, device: DenonDevice) -> None:
        """Run one connection attempt, applying backoff on failure"""
        try:
            if not await self._connect_and_monitor_device(device):
                self._backoff_until[device.token] = time.monotonic() + FAILURE_BACKOFF_SECONDS
                logging.info("Will retry %s in %.0f seconds", device.name, FAILURE_BACKOFF_SECONDS)
            else:
                self._backoff_until.pop(device.token, None)
        finally:
            self._attempting.discard(device.token)

    async def _connect_and_monitor_device(self, device: DenonDevice) -> bool:
        """Connect to a device and start monitoring. Returns True on success."""
        try:
            # Devices only trust peers whose announcements they have seen;
            # we broadcast every second from startup and discovery itself
            # takes several seconds, so a short settle is enough
            await asyncio.sleep(1.0)
            logging.info("Connecting to Denon device: %s at %s", device.name, device.ipaddr)

            # Get available services
            services = await self.connection_manager.connect_to_device(device)

            logging.debug("Device %s offers %d services:", device.name, len(services))
            for service in services:
                logging.debug("  - %s on port %d", service.name, service.port)

            state_service = next(
                (service for service in services if service.name == "StateMap"),
                None,
            )
            if not state_service:
                logging.warning(
                    "StateMap service not available on %s (found %d other services)",
                    device.name,
                    len(services),
                )
                # Release the connection and its keepalive task; otherwise
                # every failed attempt leaks a socket and a 250ms timer
                await self.connection_manager.disconnect_device(device.token)
                return False

            # Successfully connected
            self.metadata_processor.register_device(device)

            # Start monitoring track states, tagging updates with the
            # emitting device so multi-device state stays separated
            monitor_task = asyncio.create_task(
                self.connection_manager.monitor_state_changes(
                    device,
                    state_service,
                    lambda state: self._on_state_update(device.token, state),
                )
            )
            monitor_task.add_done_callback(lambda task: self._on_monitor_task_done(task, device))
            if conn := self.connection_manager.active.get(device.token):
                conn.monitor_task = monitor_task

            logging.info("Successfully connected to %s", device.name)
            return True

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.warning("Failed to connect to device %s: %s", device.name, err)
            await self.connection_manager.disconnect_device(device.token)
            return False

    def _on_state_update(self, token: bytes, state: DenonState) -> None:
        """Handle state updates from the connection manager"""
        self.metadata_processor.update_state(token, state)

    def _on_monitor_task_done(self, task, device: DenonDevice):
        """Called when a device's monitoring task finishes (connection loss)"""
        if task.cancelled():
            return

        # Retrieve the exception so asyncio does not later emit a spurious
        # "Task exception was never retrieved" traceback into user logs
        if exc := task.exception():
            logging.debug("Monitor for %s ended with: %s", device.name, exc)

        logging.info("Connection lost to %s; will reconnect on next discovery", device.name)
        self.metadata_processor.unregister_device(device.token)

        # Close out the device's remaining connection state; the ongoing
        # discovery loop reconnects it once it reannounces. Keep a task
        # reference so it is neither garbage-collected nor orphaned.
        cleanup_task = asyncio.create_task(self.connection_manager.disconnect_device(device.token))
        self._setup_tasks.add(cleanup_task)

    async def stop(self):
        """Stop the plugin and cleanup"""
        logging.info("Stopping Denon StagelinQ plugin")
        for task in self._setup_tasks:
            task.cancel()
        if self._setup_tasks:
            await asyncio.gather(*self._setup_tasks, return_exceptions=True)
        self._setup_tasks.clear()
        self._attempting.clear()
        await self.connection_manager.cleanup()

    async def getrandomtrack(self, playlist: str) -> str | None:
        """Get random track from playlist - not supported by StagelinQ"""
        return None

    async def getplayingtrack(self) -> TrackMetadata | None:
        """Get the currently playing track metadata"""
        return self.metadata_processor.get_playing_track()
