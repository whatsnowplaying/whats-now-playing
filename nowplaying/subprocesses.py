#!/usr/bin/env python3
''' handle all of the big sub processes used for output '''

import importlib
import logging
import multiprocessing


class SubprocessManager:
    ''' manage all of the subprocesses '''

    def __init__(self, config=None, testmode=False):
        self.config = config
        self.testmode = testmode
        self.obswsobj = None
        self.manager = multiprocessing.Manager()
        self.processes = {}
        if self.config.cparser.value('control/beam', type=bool):
            processlist = ['trackpoll', 'beamsender']
        else:
            processlist = [
                'trackpoll', 'obsws', 'twitchbot', 'discordbot', 'webserver'
            ]

        for name in processlist:
            self.processes[name] = {
                'module':
                importlib.import_module(f'nowplaying.processes.{name}'),
                'process': None,
                'stopevent': self.manager.Event(),
            }

    def start_all_processes(self):
        ''' start our various threads '''

        for key, module in self.processes.items():
            module['stopevent'].clear()
            func = getattr(self, f'start_{key}')
            func()

    def stop_all_processes(self):
        ''' stop all the subprocesses '''

        for key, module in self.processes.items():
            if module.get('process'):
                logging.debug('Early notifying %s', key)
                module['stopevent'].set()

        for key in self.processes:
            func = getattr(self, f'stop_{key}')
            func()

        if not self.config.cparser.value('control/beam', type=bool):
            self.stop_obsws()

    def _process_start(self, processname):
        ''' Start trackpoll '''
        if not self.processes[processname]['process']:
            logging.info('Starting %s', processname)
            self.processes[processname]['stopevent'].clear()
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
            del self.processes[processname]['process']
            self.processes[processname]['process'] = None
        logging.debug('%s should be stopped', processname)

    def start_discordbot(self):
        ''' Start discordbot '''
        self._process_start('discordbot')

    def stop_discordbot(self):
        ''' stop discordbot '''
        self._process_stop('discordbot')

    def start_beamsender(self):
        ''' Start beamsender '''
        self._process_start('beamsender')

    def stop_beamsender(self):
        ''' stop beamsender '''
        self._process_stop('beamsender')

    def start_obsws(self):
        ''' Start obsws '''
        self._process_start('obsws')

    def stop_obsws(self):
        ''' stop obsws '''
        self._process_stop('obsws')

    def start_trackpoll(self):
        ''' Start trackpoll '''
        self._process_start('trackpoll')

    def stop_trackpoll(self):
        ''' stop trackpoll '''
        self._process_stop('trackpoll')

    def start_twitchbot(self):
        ''' Start the twitchbot '''
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

    def restart_discordbot(self):
        ''' handle starting or restarting the discordbot process '''
        self.stop_discordbot()
        self.start_discordbot()

    def restart_obsws(self):
        ''' handle starting or restarting the obsws process '''
        self.stop_obsws()
        self.start_obsws()

    def restart_trackpoll(self):
        ''' handle starting or restarting the trackpoll process '''
        self.stop_trackpoll()
        self.start_trackpoll()

    def restart_webserver(self):
        ''' handle starting or restarting the webserver process '''
        self.stop_webserver()
        self.start_webserver()

    def restart_twitchbot(self):
        ''' handle starting or restarting the twitchbot process '''
        self.stop_twitchbot()
        self.start_twitchbot()
