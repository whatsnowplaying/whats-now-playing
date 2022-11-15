#!/usr/bin/env python3
''' a mostly untested driver for Denon StagelinQ '''

import asyncio
import logging
import os
import select
import socket
import time

import PyStageLinQ.Device
import PyStageLinQ.EngineServices
import PyStageLinQ.MessageClasses
import PyStageLinQ.DataClasses
import PyStageLinQ.ErrorCodes
import PyStageLinQ.Network
import PyStageLinQ.Token

import nowplaying.hostmeta
from nowplaying.inputs import InputPlugin
from nowplaying.exceptions import PluginVerifyError
import nowplaying.utils
import nowplaying.version

# https://datatracker.ietf.org/doc/html/rfc8216


class PyStagelinQDriver:
    ''' Custom driver for PyStageLinQ module '''
    REQUESTSERVICEPORT = 0
    STAGELINQ_DISCOVERY_PORT = 51337
    ANNOUNCE_IP = "169.254.255.255"

    def __init__(self, new_device_found_callback):
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
        with socket.socket(socket.AF_INET,
                           socket.SOCK_DGRAM) as discovery_socket:
            discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST,
                                        1)
            try:

                discovery_socket.sendto(discovery_frame,
                                        (PyStagelinQDriver.ANNOUNCE_IP, 51337))
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
        discoversocket.bind(("", PyStagelinQDriver.STAGELINQ_DISCOVERY_PORT
                             ))  # bind socket to all interfaces
        discoversocket.setblocking(False)

        loop_timeout = time.time() + timeout

        while True:
            await asyncio.sleep(0.1)
            dataavailable = select.select([discoversocket], [], [], 0)
            if dataavailable[0]:
                data, addr = discoversocket.recvfrom(discoverbuffersize)
                ipaddr = addr[0]
                discovery_frame = PyStageLinQ.MessageClasses.StageLinQDiscovery(
                )

                if PyStageLinQ.ErrorCodes.PyStageLinQError.STAGELINQOK != discovery_frame.decode(
                        data):
                    # something went wrong
                    continue

                # Devices found, setting new timeout
                loop_timeout = time.time() + timeout

                if 0 == discovery_frame.Port:
                    # If port is 0 there are no services to request
                    continue

                if self.name == discovery_frame.device_name:
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
                    self.new_device_found_callback(
                        ipaddr, discovery_frame,
                        stagelinq_device.get_services())

            if time.time() > loop_timeout:
                print("No devices found within timeout")
                return PyStageLinQ.ErrorCodes.DISCOVERYTIMEOUT

    def subscribe_to_statemap(self, state_map_service, subscription_list,
                              data_available_callback):
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

    async def _subscribe_to_statemap(self, statemapservice, subscription_list,
                                     data_available_callback):
        state_map = PyStageLinQ.EngineServices.StateMapSubscription(
            statemapservice, data_available_callback, subscription_list)
        await state_map.Subscribe(self.owntoken)

        self.tasks.add(state_map.get_task())


class Plugin(InputPlugin):
    ''' handler for NowPlaying '''

    metadata = {'artist': None, 'title': None, 'filename': None}

    def __init__(self, config=None, qsettings=None):
        super().__init__(config=config, qsettings=qsettings)
        self.mixmode = "newest"
        self.driver = None
        self.qwidget = None
        self._reset_meta()

    @staticmethod
    def _reset_meta():
        Plugin.metadata = {'artist': None, 'title': None, 'filename': None}

    async def _setup_watcher(self):
        ''' set up a custom watch on the m3u dir so meta info
            can update on change'''

        self.driver = PyStagelinQDriver(self.update_track)

    def update_track(self):
        pass

    async def start(self):
        ''' setup the watcher to run in a separate thread '''
        await self._setup_watcher()

    async def getplayingtrack(self):
        ''' wrapper to call getplayingtrack '''

        # just in case called without calling start...
        await self.start()
        return Plugin.metadata

    def defaults(self, qsettings):  #pylint: disable=no-self-use
        ''' no settings to set '''

    def validmixmodes(self):  #pylint: disable=no-self-use
        ''' let the UI know which modes are valid '''
        return ['newest']

    def setmixmode(self, mixmode):  #pylint: disable=no-self-use
        ''' set the mixmode '''
        return 'newest'

    def getmixmode(self):  #pylint: disable=no-self-use
        ''' get the mixmode '''
        return 'newest'

    async def stop(self):
        ''' stop the m3u plugin '''
        self._reset_meta()
        if self.driver:
            self.driver.stop()
            self.driver = None

    def on_m3u_dir_button(self):
        ''' filename button clicked action'''

    def connect_settingsui(self, qwidget):
        ''' connect m3u button to filename picker'''

    def load_settingsui(self, qwidget):
        ''' draw the plugin's settings page '''

    def verify_settingsui(self, qwidget):
        ''' no verification to do '''

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''

    def desc_settingsui(self, qwidget):
        ''' description '''
        qwidget.setText(
            'Stagelinq is a protocol used by some Denon controllers.')
