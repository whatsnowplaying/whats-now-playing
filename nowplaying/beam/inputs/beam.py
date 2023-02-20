#!/usr/bin/env python3
''' JSON Input Plugin definition, used for testing '''

import asyncio
import base64
import copy
import datetime
import logging
import platform
import socket
import struct
import threading
import weakref
import traceback

import aiohttp
from aiohttp.test_utils import get_unused_port_socket
from aiohttp import web, WSCloseCode
import requests

from PySide6.QtWidgets import QTableWidgetItem  # pylint: disable=no-name-in-module

import nowplaying.db
from nowplaying.inputs import InputPlugin
import nowplaying.trackrequests

METADATA = {}


class Plugin(InputPlugin):  # pylint: disable = too-many-instance-attributes
    ''' base class of input plugins '''

    def __init__(self, config=None, qsettings=None):
        ''' no custom init '''
        super().__init__(config=config, qsettings=qsettings)
        self.stopevent = None
        self.port = None
        self.ipaddr = None
        self.idname = None
        self.loop = None
        self.testmode = False
        self.site = None
        self.trackrequests = nowplaying.trackrequests.Requests(
            config=self.config, stopevent=self.stopevent)
        self.tasks = set()

    def install(self):
        ''' auto-install '''
        return False

#### Settings UI methods

    def defaults(self, qsettings):
        ''' (re-)set the default configuration values for this plugin '''

    def _update_current(self):

        def clear_table(widget):
            widget.clearContents()
            rows = widget.rowCount()
            for row in range(rows, -1, -1):
                widget.removeRow(row)

        def row_load(host_status, **kwargs):
            row = host_status.rowCount()
            host_status.insertRow(row)

            valuelist = ['time', 'clientname', 'ipaddr', 'source', 'version']

            for column, cbtype in enumerate(valuelist):
                host_status.setItem(
                    row, column, QTableWidgetItem(str(kwargs.get(cbtype, ''))))
            host_status.resizeColumnsToContents()

        port = self.config.cparser.value('control/beamport', type=int)

        if not port:
            return

        try:
            beamhosts = requests.get(f'http://localhost:{port}/v1/beamhosts',
                                     timeout=3)
        except Exception as error:  #pylint: disable=broad-except
            logging.error('unable to get beam hosts: %s', error)
            return

        clear_table(self.qwidget.host_status)

        self.qwidget.port_label.setText(f'Listening on port {port}')
        data = beamhosts.json()
        # see _beam_client_data()

        for _, values in data.items():
            row_load(self.qwidget.host_status, **values)

    def connect_settingsui(self, qwidget, uihelp):
        ''' connect any UI elements such as buttons '''
        self.qwidget = qwidget
        self.uihelp = uihelp
        self.qwidget.refresh_button.clicked.connect(self._update_current)

    def load_settingsui(self, qwidget):
        ''' load values from config and populate page '''

    def verify_settingsui(self, qwidget):  #pylint: disable=no-self-use
        ''' verify the values in the UI prior to saving '''

    def save_settingsui(self, qwidget):
        ''' take the settings page and save it '''

    def desc_settingsui(self, qwidget):
        ''' provide a description for the plugins page '''
        qwidget.setText('Use this source when another computer is running'
                        ' the What\'s Now Playing Beam program')

#### Mix Mode menu item methods

    def validmixmodes(self):  #pylint: disable=no-self-use
        ''' tell ui valid mixmodes '''
        return ['newest']

    def setmixmode(self, mixmode):  #pylint: disable=no-self-use
        ''' handle user switching the mix mode: TBD '''
        return 'newest'

    def getmixmode(self):  #pylint: disable=no-self-use
        ''' return what the current mixmode is set to '''
        return 'newest'

#### Data feed methods

    async def getplayingtrack(self):
        ''' Get the currently playing track '''
        return METADATA

    async def getrandomtrack(self, playlist):
        ''' not supported '''
        return None


#### Control methods

    async def start(self):
        ''' any initialization before actual polling starts '''
        if not self.stopevent:
            self.stopevent = threading.Event()
        else:
            self.stopevent.clear()
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._broadcast_location())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task = loop.create_task(self._start_server())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _broadcast_location(self):
        ''' announce the port '''

        while not self.port and not self.stopevent.is_set():
            await asyncio.sleep(1)

        while not self.stopevent.is_set():
            idname = platform.node()
            namelen = len(idname)
            interfaces = socket.getaddrinfo(host=socket.gethostname(),
                                            port=None,
                                            family=socket.AF_INET)
            allips = [ip[-1][0] for ip in interfaces]
            msg = struct.pack(f'<II{namelen}s', self.port, namelen,
                              idname.encode())
            logging.debug('Broadcasting %s %s', idname, self.port)
            for ipaddr in allips:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                     socket.IPPROTO_UDP)  # UDP
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((ipaddr, 0))
                try:
                    sock.sendto(msg, ("255.255.255.255", 8008))
                except Exception as error:  #pylint: disable=broad-except
                    logging.debug(error)
                sock.close()
            await asyncio.sleep(10)

    async def _process_metadata(self, request, json):
        ''' handle incoming metadata update '''
        global METADATA  #pylint: disable=global-statement

        prefilter = {
            k: v
            for k, v in json['metadata'].items()
            if v is not None and k not in [
                'artistbannerraw',
                'artistfanartraw',
                'artistlogoraw',
                'artistlongbio',
                'artistshortbio',
                'artistthumbraw',
                'coverurl',
                'dbid',
                'filename',
                'hostfqdn',
                'hostip',
                'hostname',
                'httpport',
                'previoustrack',
            ]
        }

        prefilter = self._unbase64ifier(prefilter)

        METADATA = prefilter
        self._update_beamhosts(request, json)

    async def _process_pong(self, request, json):
        ''' client responded to alive '''
        clientname = json.get('clientname')
        logging.debug('got a pong from %s ', clientname)
        self._update_beamhosts(request, json)
        request.app['beamhosts'][clientname] = copy.copy(json)
        request.app['beamhosts'][clientname]['ipaddr'] = request.remote
        if request.app['beamhosts'][clientname].get('metadata'):
            del request.app['beamhosts'][clientname]['metadata']

    @staticmethod
    def _update_beamhosts(request, datadict):
        clientname = datadict.get('clientname')
        request.app['beamhosts'][clientname] = {
            'time': datetime.datetime.now().isoformat(),
            'clientname': clientname,
            'version': datadict.get('version'),
            'source': datadict.get('source'),
            'ipaddr': request.remote
        }

    @staticmethod
    async def _beamv1_hosts(request):
        ''' return the local info '''
        return web.json_response(request.app['beamhosts'])

    async def _beamv1_receiver(self, request):

        handlers = {
            'METADATA': self._process_metadata,
            'PONG': self._process_pong,
        }

        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        request.app['websockets'].add(websocket)
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._beamv1_pingpong(websocket))
        tasks = {task}
        task.add_done_callback(tasks.discard)

        task = loop.create_task(self._beamv1_trackrequest(websocket))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

        try:
            async for msg in websocket:
                if msg.type == aiohttp.WSMsgType.ERROR:
                    self.port = None
                    self.ipaddr = None
                    logging.error('ws connection closed with exception %s',
                                  websocket.exception())
                    break

                if self.stopevent.is_set() or websocket.closed:
                    break

                json = msg.json()
                if msgtype := json.get('msgtype'):
                    if routine := handlers.get(msgtype):
                        await routine(request, json)
                        continue
                    logging.error('Unknown msgtype: %s', msgtype)
                    continue
                logging.error('Do not know how to handle %s', json)

        except Exception as error:  #pylint: disable=broad-except
            logging.error('Websocket handler error: %s', error)
        finally:
            request.app['websockets'].discard(websocket)

        return websocket

    async def _beamv1_pingpong(self, websocket):
        logging.debug('here %s', websocket)
        while not self.stopevent.is_set() and not websocket.closed:
            try:
                await websocket.send_json({'msgtype': 'PING'})
            except:  #pylint: disable=bare-except
                pass
            await asyncio.sleep(5 * 60)

    async def _beamv1_trackrequest(self, websocket):
        ''' read the track requests, send them to our client, and then erase '''
        try:
            while not self.stopevent.is_set() and not websocket.closed:
                entries = []
                async for row in self.trackrequests.get_all_generator():
                    await websocket.send_json({
                        'msgtype': 'REQUEST',
                        'request': row
                    })
                    entries.append(row['reqid'])
                for entry in entries:
                    self.trackrequests.erase_id(entry)
                await asyncio.sleep(5)
        except:  #pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)

    def _create_runner(self):
        ''' setup http routing '''
        threading.current_thread().name = 'BeamServer-runner'
        app = web.Application()
        app['websockets'] = weakref.WeakSet()
        app.on_startup.append(self._on_startup)
        app.on_cleanup.append(self._on_cleanup)
        app.on_shutdown.append(self._on_shutdown)
        app.add_routes([
            web.get('/v1/beam', self._beamv1_receiver),
            web.get('/v1/beamhosts', self._beamv1_hosts)
        ])
        return web.AppRunner(app)

    async def _start_server(self):
        ''' start our server '''
        runner = self._create_runner()
        await runner.setup()
        socketinfo = get_unused_port_socket(host='0.0.0.0')
        self.port = socketinfo.getsockname()[1]
        logging.debug('Setting port to %s', self.port)
        self.config.cparser.setValue('control/beamport', self.port)
        self.site = web.SockSite(runner, socketinfo)
        task = asyncio.create_task(self.stopeventtask())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        await self.site.start()

    async def _on_startup(self, app):
        ''' setup app connections '''
        app['config'] = nowplaying.config.ConfigFile(testmode=self.testmode)
        app['beamhosts'] = {}

    @staticmethod
    async def _on_shutdown(app):
        ''' handle shutdown '''
        for websocket in set(app['websockets']):
            await websocket.close(code=WSCloseCode.GOING_AWAY,
                                  message='Server shutdown')

    @staticmethod
    async def _on_cleanup(app):
        ''' cleanup the app '''
        app['watcher'].stop()

    async def stop_server(self, request):
        ''' stop our server '''
        self.stopevent.set()
        await request.app.shutdown()
        await request.app.cleanup()
        self.loop.stop()

    async def stopeventtask(self):
        ''' task to wait for the stop event '''
        while not self.stopevent.is_set():
            await asyncio.sleep(.5)
        if self.site:
            await self.site.stop()

    @staticmethod
    def _unbase64ifier(metadata):
        ''' replace all the base64 data with raw data '''
        for key in nowplaying.db.METADATABLOBLIST:
            if metadata.get(key):
                newkey = key.replace('base64', 'raw')
                metadata[newkey] = base64.b64decode(metadata[key])
                del metadata[key]
        return metadata

    async def stop(self):
        ''' stopping either the entire program or just this
            input '''
        self.stopevent.set()
