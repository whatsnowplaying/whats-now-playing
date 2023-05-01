#!/usr/bin/env python3
''' BeamSender process

* listen for an announcement from our server
* stream metadata db info to the server

'''

import asyncio
import base64
import logging
import logging.config
import os
import platform
import signal
import socket
import struct
import sys
import threading
import time
import traceback

import aiohttp
from aiohttp import ClientSession

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.db
import nowplaying.frozen
import nowplaying.trackrequests


class BeamHandler():  # pylint: disable=too-many-instance-attributes
    ''' send the local track information to a server '''

    def __init__(self,
                 bundledir=None,
                 config=None,
                 stopevent=None,
                 testmode=False):
        threading.current_thread().name = 'BeamSender'
        self.testmode = testmode
        if not config:
            config = nowplaying.config.ConfigFile(bundledir=bundledir,
                                                  testmode=testmode)
        self.config = config
        self.stopevent = stopevent
        self.tasks = set()
        self.watcher = None
        self.metadb = None
        self.idname = None
        self.port = None
        self.ipaddr = None
        self.connection = None
        self.requests = nowplaying.trackrequests.Requests(
            config=self.config, stopevent=self.stopevent)
        signal.signal(signal.SIGINT, self.forced_stop)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()

        task = loop.create_task(self._find_beam())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task = loop.create_task(self._websocket_client())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task = loop.create_task(self._start_watcher())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task = loop.create_task(self._stop(loop))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        loop.run_forever()

    def _remove_control(self):
        self.config.cparser.remove('control/beamserverip')
        self.config.cparser.remove('control/beamservername')
        self.config.cparser.remove('control/beamserverport')
        self.port = None
        self.idname = None
        self.ipaddr = None

    async def _stop(self, loop):
        while not self.stopevent.is_set():
            await asyncio.sleep(.5)

        await self.stop_server()
        loop.stop()

    async def _start_watcher(self):
        self.metadb = nowplaying.db.MetadataDB()
        self.watcher = self.metadb.watcher()
        self.watcher.start()

    async def _websocket_client(self):
        ''' start the websocket client '''

        try:
            while not self.watcher and not self.stopevent.is_set():
                await asyncio.sleep(1)
                logging.debug('waiting for a watcher')

            logging.debug('starting ws client')

            loop = asyncio.get_running_loop()
            tasks = set()
            while not self.stopevent.is_set():
                if not self.port and not self.ipaddr:
                    await asyncio.sleep(1)
                    logging.debug('waiting to hear from beam server')
                    continue

                url = f'ws://{self.ipaddr}:{self.port}/v1/beam'
                try:
                    async with ClientSession().ws_connect(url) as connection:
                        while not self.stopevent.is_set(
                        ) and not connection.closed:
                            if not tasks:
                                task = loop.create_task(
                                    self._websocket_listener(connection))
                                tasks.add(task)
                                task.add_done_callback(tasks.discard)
                                task = loop.create_task(
                                    self._websocket_metadata_write(connection))
                                tasks.add(task)
                                task.add_done_callback(tasks.discard)
                            await asyncio.sleep(1)
                    logging.debug('beam connection closed')
                    for task in tasks:
                        task.cancel(task)
                    self._remove_control()
                    await asyncio.sleep(1)
                except aiohttp.client_exceptions.ClientConnectorError as error:
                    logging.debug(error)
                    self._remove_control()

        except:  # pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)

    async def _websocket_listener(self, connection):

        handlers = {
            'REQUEST': self._request_handler,
            'PING': self._ping_handler,
        }

        while not self.stopevent.is_set() and not connection.closed:
            await asyncio.sleep(1)
            async for msg in connection:
                if msg.type == aiohttp.WSMsgType.ERROR:
                    self._remove_control()
                    break

                jsondata = msg.json()
                if msgtype := jsondata.get('msgtype'):
                    if routine := handlers.get(msgtype):
                        await routine(connection, jsondata)
                        continue
                    logging.error('Unknown msgtype: %s', msgtype)
                    continue
                logging.error('Do not know how to handle %s', jsondata)

    async def _websocket_metadata_write(self, connection):
        mytime = 0
        while not self.stopevent.is_set() and not connection.closed:
            if mytime < self.watcher.updatetime:
                mytime = await self._wss_do_update(connection)
            await asyncio.sleep(1)

    async def _find_beam(self):
        ''' keep track of the remote host '''

        def udp_recvfrom(loop, sock, n_bytes, fut=None, registered=False):
            filedes = sock.fileno()
            if fut is None:
                fut = loop.create_future()
            if registered:
                loop.remove_reader(filedes)

            try:
                data, addr = sock.recvfrom(n_bytes)
            except (BlockingIOError, InterruptedError):
                loop.add_reader(filedes, udp_recvfrom, loop, sock, n_bytes,
                                fut, True)
            else:
                fut.set_result((data, addr))
            return fut

        try:
            loop = asyncio.get_event_loop()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, 0)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setblocking(False)
            sock.bind(('0.0.0.0', 8008))

            logging.debug('starting to listen for beam server')
            while not self.stopevent.is_set():
                await asyncio.sleep(1)

                data, addr = await udp_recvfrom(loop, sock, 1024)

                if self.ipaddr and self.port and self.idname:
                    continue

                ipaddr = addr[0]
                port, length = struct.unpack('<II', data[:8])
                idname = struct.unpack_from(f'<{length}s', data, 8)[0]
                idname = idname.decode('utf-8')
                if port != self.port:
                    logging.debug('updating port to %s', port)
                    self.port = port
                    self.config.cparser.setValue('control/beamserverport',
                                                 self.port)

                if idname != self.idname:
                    logging.debug('updating idname to %s', idname)
                    self.idname = idname
                    self.config.cparser.setValue('control/beamservername',
                                                 self.idname)

                if ipaddr != self.ipaddr:
                    logging.debug('updating ipaddr to %s', ipaddr)
                    self.ipaddr = ipaddr
                    self.config.cparser.setValue('control/beamserverip',
                                                 self.ipaddr)

        except:  # pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)
        if sock:
            sock.close()

    async def stopeventtask(self):
        ''' task to wait for the stop event '''
        while not self.stopevent.is_set():
            await asyncio.sleep(.5)
        await self.forced_stop()

    @staticmethod
    def _base64ifier(metadata):
        ''' replace all the binary data with base64 data '''
        for key in nowplaying.db.METADATABLOBLIST:
            if metadata.get(key):
                newkey = key.replace('raw', 'base64')
                metadata[newkey] = base64.b64encode(
                    metadata[key]).decode('utf-8')
                del metadata[key]
        return metadata

    async def _ping_handler(self, websocket, msgdata):  #pylint: disable=unused-argument
        ''' handle inbound requests '''
        logging.debug('got a ping from beam server')
        beamdata = await self._beam_client_data()
        beamdata['msgtype'] = 'PONG'
        await websocket.send_json(beamdata)

    async def _request_handler(self, websocket, msgdata):  #pylint: disable=unused-argument
        ''' handle inbound requests '''
        reqdata = msgdata.get('request')
        logging.debug('Would process request %s', reqdata)
        # nothing happens with the reply since the beamserver should have
        # taken care of it
        try:
            if reqdata.get('type') == 'Generic':
                await self.requests.user_track_request(
                    reqdata, reqdata.get('username'),
                    reqdata.get('user_input'))
            elif reqdata.get('type') == 'Roulette':
                await self.requests.user_roulette_request(
                    reqdata, reqdata.get('username'),
                    reqdata.get('user_input'))
        except:  #pylint: disable=bare-except
            for line in traceback.format_exc().splitlines():
                logging.error(line)

    async def _beam_client_data(self):
        return {
            'clientname': platform.node(),
            'version': self.config.version,
            'source': self.config.cparser.value('settings/input'),
        }

    async def _wss_do_update(self, connection):
        # early launch can be a bit weird so
        # pause a bit
        prefilter = None

        while not prefilter and not self.stopevent.is_set(
        ) and not connection.closed:
            if self.stopevent.is_set() or connection.closed:
                return 0
            prefilter = self.metadb.read_last_meta()
            await asyncio.sleep(1)

        metadata = {
            k: v
            for k, v in prefilter.items() if v is not None and k not in [
                'artistbannerraw',
                'artistfanartraw',
                'artistlogoraw',
                'artistlongbio',
                'artistshortbio',
                'artistthumbraw',
                'dbid',
                'coverurl',
                'filename',
                'hostfqdn',
                'hostip',
                'hostname',
                'httpport',
                'previoustrack',
            ]
        }

        beamdata = await self._beam_client_data()
        beamdata['msgtype'] = 'METADATA'
        beamdata['metadata'] = self._base64ifier(metadata)
        if connection.closed:
            return 0
        logging.debug('Beaming to %s:%s', self.ipaddr, self.port)
        await connection.send_json(beamdata)
        return time.time()

    async def stop_server(self):
        ''' stop our server '''
        if self.watcher:
            self.watcher.stop()

    def forced_stop(self, signum=None, frame=None):  # pylint: disable=unused-argument
        ''' caught an int signal so tell the world to stop '''
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        except Exception as error:  # pylint: disable=broad-except
            logging.info(error)

        task = loop.create_task(self.stop_server())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        if self.stopevent:
            self.stopevent.set()


def stop(pid):
    ''' stop the web server -- called from Tray '''
    logging.info('sending INT to %s', pid)
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        pass


def start(stopevent=None, bundledir=None, testmode=False):
    ''' multiprocessing start hook '''
    threading.current_thread().name = 'BeamSender'

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    bundledir = nowplaying.frozen.frozen_init(bundledir)

    if testmode:
        nowplaying.bootstrap.set_qt_names(appname='testsuite')
        testmode = True
    else:
        testmode = False
        nowplaying.bootstrap.set_qt_names()
    logpath = nowplaying.bootstrap.setuplogging(logname='debug.log',
                                                rotate=False)
    config = nowplaying.config.ConfigFile(bundledir=bundledir,
                                          logpath=logpath,
                                          testmode=testmode)

    logging.info('boot up')

    try:
        beamserver = BeamHandler(  # pylint: disable=unused-variable
            config=config,
            stopevent=stopevent,
            testmode=testmode)
    except Exception as error:  #pylint: disable=broad-except
        logging.error('BeamSender crashed: %s', error, exc_info=True)
        sys.exit(1)
    sys.exit(0)
