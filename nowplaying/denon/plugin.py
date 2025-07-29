#!/usr/bin/env python3
"""
Denon DJ StagelinQ Main Plugin

This module contains the main plugin class that coordinates all the StagelinQ components.
It handles the plugin lifecycle, UI integration, and high-level coordination between
the protocol handler, connection manager, and metadata processor.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from nowplaying.inputs import InputPlugin
from nowplaying.types import TrackMetadata

from .connection import ConnectionManager
from .metadata import MetadataProcessor
from .protocol import StagelinqProtocol
from .types import DenonDevice, DenonService, DenonState

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.uihelp


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
        self.current_device: DenonDevice | None = None
        self.current_service: DenonService | None = None
        self._discovery_timeout = 5.0

    def install(self) -> bool:
        """Auto-install detection - StagelinQ devices are network-based"""
        # Cannot auto-detect network devices, user must configure manually
        return False

    def defaults(self, qsettings: "QSettings | None"):
        """Set default configuration values"""
        qsettings.setValue("denon/discovery_timeout", 5.0)
        qsettings.setValue("denon/deckskip", None)

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

            # Try to connect to a device
            await self._find_and_connect()

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.error("Failed to start Denon plugin: %s", err)

    async def _find_and_connect(self):
        """Find devices and connect to the first available one"""
        while True:
            try:
                self._discovery_timeout = self.config.cparser.value(
                    "denon/discovery_timeout", type=float, defaultValue=5.0
                )

                # Discover devices
                devices = await self.connection_manager.discover_devices(self._discovery_timeout)

                if devices:
                    logging.info("Found %d Denon device(s)", len(devices))

                    # Give devices time to receive multiple announcements before connecting
                    # The devices need to know who we are first
                    logging.debug("Waiting for devices to receive our announcements...")
                    await asyncio.sleep(3.0)  # Wait longer for devices to trust us

                    # Try each device until we find one with StateMap
                    for device in devices:
                        logging.debug("Trying device: %s (%s)", device.name, device.software_name)
                        success = await self._connect_and_monitor_device(device)
                        if success:
                            # Successfully connected, exit the retry loop
                            return

                # No devices found or connection failed, wait before trying again
                logging.debug("No devices found, retrying in 10 seconds...")
                await asyncio.sleep(10.0)

            except Exception as err:  # pylint: disable=broad-exception-caught
                logging.error("Error in device discovery: %s", err)
                await asyncio.sleep(10.0)

    async def _connect_and_monitor_device(self, device: DenonDevice) -> bool:
        """Connect to a device and start monitoring. Returns True on success."""
        try:
            logging.info("Connecting to Denon device: %s at %s", device.name, device.ipaddr)

            # Get available services
            services = await self.connection_manager.connect_to_device(device)

            logging.debug("Device offers %d services:", len(services))
            for service in services:
                logging.debug("  - %s on port %d", service.name, service.port)

            state_service = next(
                (service for service in services if service.name == "StateMap"),
                None,
            )
            if not state_service:
                logging.warning(
                    "StateMap service not available on device (found %d other services)",
                    len(services),
                )
                # Connection manager will handle cleanup
                return False

            # Successfully connected
            self.current_device = device
            self.current_service = state_service

            # Start monitoring track states
            monitor_task = asyncio.create_task(
                self.connection_manager.monitor_state_changes(
                    device, state_service, self._on_state_update
                )
            )
            monitor_task.add_done_callback(self._on_monitor_task_done)
            self.connection_manager.tasks.append(monitor_task)

            logging.info("Successfully connected to %s", device.name)
            return True

        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.debug("Failed to connect to device %s: %s", device.name, err)
            return False

    def _on_state_update(self, state: DenonState) -> None:
        """Handle state updates from the connection manager"""
        self.metadata_processor.update_state(state)

    def _on_monitor_task_done(self, task):
        """Called when monitoring task finishes (due to connection loss)"""
        if not task.cancelled():
            # Task finished due to error, not cancellation
            logging.info("Connection lost, will attempt to reconnect")
            self.current_device = None
            self.current_service = None

            # Start reconnection task
            reconnect_task = asyncio.create_task(self._find_and_connect())
            self.connection_manager.tasks.append(reconnect_task)

    async def stop(self):
        """Stop the plugin and cleanup"""
        logging.info("Stopping Denon StagelinQ plugin")
        await self.connection_manager.cleanup()

    async def getrandomtrack(self, playlist: str) -> str | None:
        """Get random track from playlist - not supported by StagelinQ"""
        return None

    async def getplayingtrack(self) -> TrackMetadata | None:
        """Get the currently playing track metadata"""
        return self.metadata_processor.get_playing_track()
