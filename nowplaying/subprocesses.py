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
            processlist = ['trackpoll', 'obsws', 'twitchbot', 'discordbot', 'webserver', 'kickbot']

        for name in processlist:
            self.processes[name] = {
                'module': importlib.import_module(f'nowplaying.processes.{name}'),
                'process': None,
                'stopevent': self.manager.Event(),
            }

    def start_all_processes(self):
        ''' start our various threads '''

        for key, module in self.processes.items():
            module['stopevent'].clear()
            self.start_process(key)

    def stop_all_processes(self):
        ''' stop all the subprocesses '''

        for key, module in self.processes.items():
            if module.get('process'):
                logging.debug('Early notifying %s', key)
                module['stopevent'].set()

        for key in self.processes:
            self.stop_process(key)

        if not self.config.cparser.value('control/beam', type=bool):
            self.stop_process('obsws')

    def _start_process(self, processname):
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

    def _stop_process(self, processname):
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

    def start_process(self, processname):
        ''' Start a specific process '''
        if processname == 'twitchbot' and not self.config.cparser.value('twitchbot/enabled',
                                                                         type=bool):
            return
        if processname == 'webserver' and not self.config.cparser.value('weboutput/httpenabled',
                                                                         type=bool):
            return
        if (processname == 'kickbot' and
                not (self.config.cparser.value('kick/enabled', type=bool) and
                     self.config.cparser.value('kick/chat', type=bool))):
            return
        self._start_process(processname)

    def stop_process(self, processname):
        ''' Stop a specific process '''
        self._stop_process(processname)

    def restart_process(self, processname):
        ''' Restart a specific process '''
        self.stop_process(processname)
        self.start_process(processname)

    # Legacy methods for backward compatibility
    def start_webserver(self):
        ''' Start the webserver '''
        self.start_process('webserver')

    def stop_webserver(self):
        ''' Stop the webserver '''
        self.stop_process('webserver')

    def stop_twitchbot(self):
        ''' Stop the twitchbot '''
        self.stop_process('twitchbot')

    def stop_kickbot(self):
        ''' Stop the kickbot '''
        self.stop_process('kickbot')

    def restart_webserver(self):
        ''' Restart the webserver process '''
        self.restart_process('webserver')

    def restart_obsws(self):
        ''' Restart the obsws process '''
        self.restart_process('obsws')

    def restart_kickbot(self):
        ''' Restart the kickbot process '''
        self.restart_process('kickbot')
