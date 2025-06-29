#!/usr/bin/env python3
''' handle all of the big sub processes used for output '''

import concurrent.futures
import importlib
import logging
import multiprocessing
import typing as t

import nowplaying
import nowplaying.config

from PySide6.QtWidgets import QApplication  # pylint: disable=import-error,no-name-in-module


class SubprocessManager:
    ''' manage all of the subprocesses '''

    def __init__(self,
                 config: nowplaying.config.ConfigFile | None = None,
                 testmode: bool = False):
        self.config = config
        self.testmode = testmode
        self.obswsobj = None
        self.manager = multiprocessing.Manager()
        self.processes: dict[str, dict[str, t.Any]] = {}
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

    def start_all_processes(self, startup_window: 'nowplaying.startup.StartupWindow | None' = None):
        ''' start our various threads '''

        for key, module in self.processes.items():
            if startup_window:
                startup_window.update_progress(f"Starting {key}...")
                QApplication.processEvents()

            module['stopevent'].clear()
            self.start_process(key)

    def stop_all_processes(self) -> None:
        ''' stop all the subprocesses '''

        # Signal all processes to stop first (fast operation)
        for key, module in self.processes.items():
            if module.get('process'):
                logging.debug('Early notifying %s', key)
                module['stopevent'].set()

        # Use ThreadPoolExecutor to parallelize the blocking join operations
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.processes)) as executor:
            # Submit all stop operations to run concurrently
            future_to_process = {
                executor.submit(self._stop_process_parallel, key): key
                for key, process_info in self.processes.items() if process_info.get('process')
            }

            # Wait for all shutdown operations to complete
            for future in concurrent.futures.as_completed(future_to_process, timeout=15):
                process_name = future_to_process[future]
                try:
                    future.result()
                    logging.debug('Successfully stopped %s', process_name)
                except Exception as error:  # pylint: disable=broad-exception-caught
                    logging.error('Error stopping %s: %s', process_name, error)

        if not self.config.cparser.value('control/beam', type=bool):
            self.stop_process('obsws')

    def _start_process(self, processname: str) -> None:
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

    def _stop_process_parallel(self, processname: str) -> None:
        ''' Stop a process - designed for parallel execution '''
        if not self.processes[processname]['process']:
            return

        process = self.processes[processname]['process']
        logging.debug('Waiting for %s', processname)

        # Special handling for twitchbot
        if processname in {'twitchbot'}:
            try:
                func = getattr(self.processes[processname]['module'], 'stop')
                func(process.pid)
            except Exception as error:  # pylint: disable=broad-exception-caught
                logging.error('Error calling stop function for %s: %s', processname, error)

        # Wait for graceful shutdown (reduced since we're parallel)
        process.join(8)

        # Force termination if still alive
        if process.is_alive():
            logging.info('Terminating %s %s forcefully', processname, process.pid)
            process.terminate()
            # Windows processes can take longer to terminate
            process.join(7)

        # Cleanup - be defensive on Windows
        try:
            process.close()
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.debug('Error closing process %s: %s', processname, error)

        del self.processes[processname]['process']
        self.processes[processname]['process'] = None
        logging.debug('%s stopped successfully', processname)

    def _stop_process(self, processname: str) -> None:
        ''' Stop a process - sequential version for individual stops '''
        if self.processes[processname]['process']:
            logging.debug('Notifying %s', processname)
            self.processes[processname]['stopevent'].set()
            self._stop_process_parallel(processname)
        logging.debug('%s should be stopped', processname)

    def start_process(self, processname: str) -> None:
        ''' Start a specific process '''
        if processname == 'twitchbot' and not self.config.cparser.value('twitchbot/enabled',
                                                                        type=bool):
            return
        if processname == 'webserver' and not self.config.cparser.value('weboutput/httpenabled',
                                                                        type=bool):
            return
        if (processname == 'kickbot'
                and not (self.config.cparser.value('kick/enabled', type=bool)
                         and self.config.cparser.value('kick/chat', type=bool))):
            return
        if processname == 'obsws' and not self.config.cparser.value('obsws/enabled', type=bool):
            return
        if processname == 'discordbot' and not self.config.cparser.value('discord/enabled',
                                                                         type=bool):
            return
        # trackpoll always starts - it's the core monitoring process
        self._start_process(processname)

    def stop_process(self, processname: str) -> None:
        ''' Stop a specific process '''
        self._stop_process(processname)

    def restart_process(self, processname: str) -> None:
        ''' Restart a specific process '''
        self.stop_process(processname)
        self.start_process(processname)

    # Legacy methods for backward compatibility
    def start_webserver(self) -> None:
        ''' Start the webserver '''
        self.start_process('webserver')

    def start_kickbot(self) -> None:
        ''' Start the kickbot '''
        self.start_process('kickbot')

    def start_twitchbot(self) -> None:
        ''' Start the twitchbot '''
        self.start_process('twitchbot')

    def stop_webserver(self) -> None:
        ''' Stop the webserver '''
        self.stop_process('webserver')

    def stop_twitchbot(self) -> None:
        ''' Stop the twitchbot '''
        self.stop_process('twitchbot')

    def stop_kickbot(self) -> None:
        ''' Stop the kickbot '''
        self.stop_process('kickbot')

    def restart_webserver(self) -> None:
        ''' Restart the webserver process '''
        self.restart_process('webserver')

    def restart_obsws(self) -> None:
        ''' Restart the obsws process '''
        self.restart_process('obsws')

    def restart_kickbot(self) -> None:
        ''' Restart the kickbot process '''
        self.restart_process('kickbot')
