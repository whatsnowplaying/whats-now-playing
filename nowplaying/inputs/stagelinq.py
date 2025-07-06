#!/usr/bin/env python3
''' a mostly untested driver for Denon StagelinQ '''

import asyncio
import logging
import select
import socket
import time
from typing import TYPE_CHECKING

import PyStageLinQ.Device
import PyStageLinQ.EngineServices
import PyStageLinQ.MessageClasses
import PyStageLinQ.DataClasses
import PyStageLinQ.ErrorCodes
import PyStageLinQ.Network
import PyStageLinQ.Token

import nowplaying.hostmeta
import nowplaying.utils
import nowplaying.version
from nowplaying.inputs import InputPlugin
from nowplaying.exceptions import PluginVerifyError
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

# https://datatracker.ietf.org/doc/html/rfc8216


class PyStagelinQDriver:
    ''' Custom driver for PyStageLinQ module '''
    REQUESTSERVICEPORT = 0
    STAGELINQ_DISCOVERY_PORT = 51337
    ANNOUNCE_IP = "169.254.255.255"

    def __init__(self, new_device_found_callback: callable):
        self.owntoken = PyStageLinQ.Token.StageLinQToken()
        self.discovery_info = None
        self.owntoken.generate_token()
        self.discovery_info = PyStageLinQ.DataClasses.StageLinQDiscoveryData(
            Token=self.owntoken,
            DeviceName=nowplaying.hostmeta.gethostmeta()['hostname'],
            ConnectionType=PyStageLinQ.MessageClasses.ConnectionTypes.HOWDY,
            SwName="whatsnowplaying",
            SwVersion=nowplaying.version.get_versions()['version'],
            ReqServicePort=PyStagelinQDriver.REQUESTSERVICEPORT)

        self.device_list = PyStageLinQ.Device.DeviceList()

        self.tasks = set()
        self.found_services = []
        self.new_services_available = False

        self.active_services = []

        self.devices_with_services_pending_list = []
        self.devices_with_services_pending = False
        self.devices_with_services_lock = asyncio.Lock()

        self.new_device_found_callback = new_device_found_callback

    def _announce_self(self):
        discovery = PyStageLinQ.MessageClasses.StageLinQDiscovery()
        discovery_frame = discovery.encode(self.discovery_info)
        self._send_discovery_frame(discovery_frame)

    def _send_discovery_frame(self, discovery_frame):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as discovery_socket:
            discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:

                discovery_socket.sendto(discovery_frame, (PyStagelinQDriver.ANNOUNCE_IP, 51337))
            except PermissionError:
                raise Exception(
                    f"Cannot write to IP {PyStagelinQDriver.ANNOUNCE_IP}, this error could be due to that there is no network cart set up with this IP range"
                )

    async def _discover_stagelinq_device(self, timeout=10):
        """
        This function is used to find StageLinQ device announcements.
        """
        # Local Constants
        discoverbuffersize = 8192

        # Create socket
        discoversocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        discoversocket.bind(
            ("", PyStagelinQDriver.STAGELINQ_DISCOVERY_PORT))  # bind socket to all interfaces
        discoversocket.setblocking(False)

        loop_timeout = time.time() + timeout

        while True:
            await asyncio.sleep(0.1)
            dataavailable = select.select([discoversocket], [], [], 0)
            if dataavailable[0]:
                data, addr = discoversocket.recvfrom(discoverbuffersize)
                ipaddr = addr[0]
                discovery_frame = PyStageLinQ.MessageClasses.StageLinQDiscovery()

                if PyStageLinQ.ErrorCodes.PyStageLinQError.STAGELINQOK != discovery_frame.decode(
                        data):
                    # something went wrong
                    continue

                # Devices found, setting new timeout
                loop_timeout = time.time() + timeout

                if 0 == discovery_frame.Port:
                    # If port is 0 there are no services to request
                    continue

                if self.discovery_info.DeviceName == discovery_frame.device_name:
                    # Ourselves, ignore
                    continue

                device_registered = self.device_list.find_registered_device(
                    discovery_frame.get_data())
                if device_registered:
                    continue
                stagelinq_device = PyStageLinQ.Network.StageLinQService(
                    ipaddr, discovery_frame, self.owntoken, None)
                service_tasks = await stagelinq_device.get_tasks()

                for task in service_tasks:
                    self.tasks.add(task)

                self.device_list.register_device(stagelinq_device)
                await stagelinq_device.wait_for_services(timeout=1)

                if self.new_device_found_callback is not None:
                    self.new_device_found_callback(ipaddr, discovery_frame,
                                                   stagelinq_device.get_services())

            if time.time() > loop_timeout:
                print("No devices found within timeout")
                return PyStageLinQ.ErrorCodes.DISCOVERYTIMEOUT

    def subscribe_to_statemap(self, state_map_service, subscription_list: list[str],
                              data_available_callback: callable):
        """
        This function is used to subscribe to a statemap service provided by a StageLinQ device.
                :param state_map_service: This parameter is used to determine if
                :param subscription_list: list of serivces that the application wants to subscribe to
                :param data_available_callback: Callback for when data is available from StageLinQ device
        """
        if state_map_service.service != "StateMap":
            raise Exception("Service is not StateMap!")

        # Defer task creation to avoid blocking the calling function
        asyncio.create_task(
            self._subscribe_to_statemap(state_map_service, subscription_list,
                                        data_available_callback))

    async def _subscribe_to_statemap(self, statemapservice, subscription_list: list[str],
                                     data_available_callback: callable):
        state_map = PyStageLinQ.EngineServices.StateMapSubscription(statemapservice,
                                                                    data_available_callback,
                                                                    subscription_list)
        await state_map.Subscribe(self.owntoken)

        self.tasks.add(state_map.get_task())


class Plugin(InputPlugin):
    ''' handler for NowPlaying '''

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.displayname = "Denon StagelinQ"
        self.mixmode = "newest"
        self.driver: PyStagelinQDriver | None = None
        self.qwidget: "QWidget" | None = None
        self.metadata: TrackMetadata = {}
        self.active_services: list = []
        self.current_track: TrackMetadata = {}

    def _reset_meta(self):
        self.metadata = {}
        self.current_track = {}

    async def _setup_watcher(self):
        ''' set up StagelinQ driver and device discovery '''
        self.driver = PyStagelinQDriver(self.on_device_found)
        # Start discovery
        discovery_task = asyncio.create_task(self.driver._discover_stagelinq_device())
        # Don't await here - let it run in background

    def on_device_found(self, ip_addr: str, discovery_frame, services: list):
        ''' handle when a new StagelinQ device is found '''
        logging.info(f"Found StagelinQ device at {ip_addr}: {discovery_frame.device_name}")
        self.active_services = services
        # Subscribe to StateMap services for track data
        for service in services:
            if service.service == "StateMap":
                self.subscribe_to_track_data(service)

    def subscribe_to_track_data(self, state_map_service):
        ''' subscribe to track data from StateMap service '''
        subscription_list = [
            "PlayerEntity_PlayState", "PlayerEntity_TrackArtistName", "PlayerEntity_TrackTitle",
            "PlayerEntity_TrackAlbumName", "PlayerEntity_TrackFileName"
        ]
        self.driver.subscribe_to_statemap(state_map_service, subscription_list, self.on_track_data)

    def on_track_data(self, data: dict):
        ''' handle incoming track data from StagelinQ '''
        logging.debug(f"Received track data: {data}")
        # Update metadata based on StagelinQ data
        if "PlayerEntity_TrackArtistName" in data:
            self.current_track['artist'] = data["PlayerEntity_TrackArtistName"]
        if "PlayerEntity_TrackTitle" in data:
            self.current_track['title'] = data["PlayerEntity_TrackTitle"]
        if "PlayerEntity_TrackAlbumName" in data:
            self.current_track['album'] = data["PlayerEntity_TrackAlbumName"]
        if "PlayerEntity_TrackFileName" in data:
            self.current_track['filename'] = data["PlayerEntity_TrackFileName"]

        self.metadata = self.current_track.copy()

    async def start(self):
        ''' setup the watcher to run in a separate thread '''
        await self._setup_watcher()

    async def getplayingtrack(self) -> TrackMetadata | None:
        ''' wrapper to call getplayingtrack '''
        # just in case called without calling start...
        if not self.driver:
            await self.start()
        return self.metadata if self.metadata else None

    def defaults(self, qsettings):
        ''' set default settings '''
        # No specific settings needed for StagelinQ yet
        pass

    def validmixmodes(self) -> list[str]:
        ''' let the UI know which modes are valid '''
        return ['newest']

    def setmixmode(self, mixmode: str) -> str:
        ''' set the mixmode '''
        return 'newest'

    def getmixmode(self) -> str:
        ''' get the mixmode '''
        return 'newest'

    async def stop(self):
        ''' stop the StagelinQ plugin '''
        self._reset_meta()
        if self.driver:
            # Stop any running tasks
            for task in self.driver.tasks:
                if not task.done():
                    task.cancel()
            self.driver = None

    def connect_settingsui(self, qwidget: "QWidget", uihelp):
        ''' connect any UI elements '''
        self.qwidget = qwidget
        self.uihelp = uihelp

    def load_settingsui(self, qwidget: "QWidget"):
        ''' draw the plugin's settings page '''
        # No specific settings UI needed yet
        pass

    def verify_settingsui(self, qwidget: "QWidget") -> bool:
        ''' no verification to do '''
        return True

    def save_settingsui(self, qwidget: "QWidget"):
        ''' take the settings page and save it '''
        # No specific settings to save yet
        pass

    def desc_settingsui(self, qwidget: "QWidget"):
        ''' description '''
        qwidget.setText(
            'StagelinQ is a protocol used by Denon DJ controllers and software. '
            'This plugin automatically discovers and connects to StagelinQ-enabled devices '
            'on the network to retrieve currently playing track information.')
