#!/usr/bin/env python3
''' handle all of the big sub processes used for output '''

import importlib
import logging
import multiprocessing

import nowplaying.obsws
import nowplaying.db


class SubprocessManager:
    ''' manage all of the subprocesses '''

    def __init__(self, config=None, testmode=False):
        self.config = config
        self.testmode = testmode
        self.obswsobj = None
        self.manager = multiprocessing.Manager()
        self.processes = {}
        for name in ['trackpoll', 'twitchbot', 'webserver']:
            self.processes[name] = {
                'module':
                importlib.import_module(f'nowplaying.processes.{name}'),
                'process': None,
                'stopevent': self.manager.Event(),
            }

    def start_all_processes(self):
        ''' start our various threads '''

        for key in self.processes:
            func = getattr(self, f'start_{key}')
            func()

        # Start the OBS WebSocket thread
        self.obswsobj = nowplaying.obsws.OBSWebSocketHandler(tray=self)
        if self.config.cparser.value('obsws/enabled', type=bool):
            self.start_obsws()

    def stop_all_processes(self):
        ''' stop all the subprocesses '''

        for key in self.processes:  #pylint: disable=consider-using-dict-items
            if self.processes[key]['process']:
                logging.debug('Early notifying %s', key)
                self.processes[key]['stopevent'].set()

        for key in self.processes:
            func = getattr(self, f'stop_{key}')
            func()

        self.stop_obsws()

    def start_obsws(self):
        ''' start the obs ws thread '''
        if self.obswsobj:
            self.obswsobj.start()

    def stop_obsws(self):
        ''' stop the obs ws thread '''
        if self.obswsobj:
            self.obswsobj.stop()

    def restart_obsws(self):
        ''' bounce the obsws connection '''
        self.stop_obsws()
        self.start_obsws()

    def _process_start(self, processname):
        ''' Start trackpoll '''
        if not self.processes[processname]['process']:
            logging.info('Starting %s', processname)
            self.processes[processname]['process'] = multiprocessing.Process(
                target=getattr(self.processes[processname]['module'], 'start'),
                name=processname,
                args=(
                    self.processes[processname]['stopevent'],
                    self.config.getbundledir(),
                    self.testmode,
                ))
            self.processes[processname]['process'].start()

    def _process_stop(self, processname):
        if self.processes[processname]['process']:
            logging.debug('Notifying %s', processname)
            self.processes[processname]['stopevent'].set()
            if processname in ['twitchbot']:
                func = getattr(self.processes[processname]['module'], 'stop')
                func(self.processes[processname]['process'].pid)
            logging.debug('Waiting for %s', processname)
            self.processes[processname]['process'].join(10)
            if self.processes[processname]['process'].is_alive():
                logging.info('Terminating %s %s forcefully', processname,
                             self.processes[processname]['process'].pid)
                self.processes[processname]['process'].terminate()
            self.processes[processname]['process'].join(5)
            self.processes[processname]['process'].close()
            self.processes[processname]['process'] = None

    def start_trackpoll(self):
        ''' Start trackpoll '''
        self._process_start('trackpoll')

    def stop_trackpoll(self):
        ''' stop trackpoll '''
        self._process_stop('trackpoll')

    def start_twitchbot(self):
        ''' Start the webserver '''
        if self.config.cparser.value('twitchbot/enabled', type=bool):
            self._process_start('twitchbot')

    def stop_twitchbot(self):
        ''' stop the twitchbot process '''
        self._process_stop('twitchbot')

    def start_webserver(self):
        ''' Start the webserver '''
        if self.config.cparser.value('weboutput/httpenabled', type=bool):
            self._process_start('webserver')

    def stop_webserver(self):
        ''' stop the web process '''
        self._process_stop('webserver')

    def restart_trackpoll(self):
        ''' handle starting or restarting the webserver process '''
        self.stop_trackpoll()
        self.start_trackpoll()

    def restart_webserver(self):
        ''' handle starting or restarting the webserver process '''
        self.stop_webserver()
        self.start_webserver()

    def restart_twitchbot(self):
        ''' handle starting or restarting the webserver process '''
        self.stop_twitchbot()
        self.start_twitchbot()
