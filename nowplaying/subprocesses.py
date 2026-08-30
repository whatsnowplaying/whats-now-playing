#!/usr/bin/env python3
"""handle all of the big sub processes used for output"""

import concurrent.futures
import importlib
import logging
import multiprocessing
import typing as t

from PySide6.QtCore import Qt  # pylint: disable=import-error,no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=import-error,no-name-in-module
    QApplication,
    QMessageBox,
)

import nowplaying
import nowplaying.config
import nowplaying.utils.network

PROCESS_NAMES: list[str] = [
    "trackpoll",
    "datacache",
    "obsws",
    "twitchbot",
    "discordbot",
    "webserver",
    "kickbot",
]


class SubprocessManager:
    """manage all of the subprocesses"""

    def __init__(self, config: nowplaying.config.ConfigFile | None = None, testmode: bool = False):
        self.config = config
        self.testmode = testmode
        self.obswsobj = None
        self.manager = multiprocessing.Manager()
        self.processes: dict[str, dict[str, t.Any]] = {}
        for name in PROCESS_NAMES:
            self.processes[name] = {
                "module": importlib.import_module(f"nowplaying.processes.{name}"),
                "process": None,
                "stopevent": self.manager.Event(),
            }

    def start_all_processes(
        self, startup_window: "nowplaying.startup.StartupWindow | None" = None
    ):
        """start our various threads"""

        # Clear OAuth status so subprocesses write fresh values after authenticating
        for key in (
            "twitchbot/broadcaster_oauth_status",
            "twitchbot/broadcaster_username",
            "twitchbot/chat_oauth_status",
            "twitchbot/chat_username",
            "kick/oauth_status",
        ):
            self.config.cparser.remove(key)
        self.config.cparser.sync()

        for key, module in self.processes.items():
            if startup_window:
                startup_window.update_progress(f"Starting {key}...")
                QApplication.processEvents()

            module["stopevent"].clear()
            self.start_process(key)

    def stop_all_processes(self) -> None:
        """stop all the subprocesses"""

        # Signal all processes to stop first (fast operation)
        for key, module in self.processes.items():
            if module.get("process"):
                logging.debug("Early notifying %s", key)
                module["stopevent"].set()

        # Use ThreadPoolExecutor to parallelize the blocking join operations
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.processes)) as executor:
            # Submit all stop operations to run concurrently
            future_to_process = {
                executor.submit(self._stop_process_parallel, key): key
                for key, process_info in self.processes.items()
                if process_info.get("process")
            }

            # Wait for all shutdown operations to complete
            for future in concurrent.futures.as_completed(future_to_process, timeout=15):
                process_name = future_to_process[future]
                try:
                    future.result()
                    logging.debug("Successfully stopped %s", process_name)
                except Exception as error:  # pylint: disable=broad-exception-caught
                    logging.error("Error stopping %s: %s", process_name, error)

        self.stop_process("obsws")

    def _start_process(self, processname: str) -> None:
        """Start trackpoll"""
        if not self.processes[processname]["process"]:
            logging.info("Starting %s", processname)
            self.processes[processname]["stopevent"].clear()
            self.processes[processname]["process"] = multiprocessing.Process(
                target=self.processes[processname]["module"].start,
                name=processname,
                args=(
                    self.processes[processname]["stopevent"],
                    self.config.getbundledir(),
                    self.testmode,
                ),
            )
            self.processes[processname]["process"].start()

    def _stop_process_parallel(self, processname: str) -> None:
        """Stop a process - designed for parallel execution"""
        if not self.processes[processname]["process"]:
            return

        process = self.processes[processname]["process"]
        logging.debug("Waiting for %s", processname)

        # Special handling for twitchbot
        if processname in {"twitchbot"}:
            try:
                func = self.processes[processname]["module"].stop
                func(process.pid)
            except Exception as error:  # pylint: disable=broad-exception-caught
                logging.error("Error calling stop function for %s: %s", processname, error)

        # Wait for graceful shutdown (reduced since we're parallel)
        process.join(8)

        # Force termination if still alive
        if process.is_alive():
            logging.info("Terminating %s %s forcefully", processname, process.pid)
            process.terminate()
            # Windows processes can take longer to terminate
            process.join(7)

        # Cleanup - be defensive on Windows
        try:
            process.close()
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.debug("Error closing process %s: %s", processname, error)

        del self.processes[processname]["process"]
        self.processes[processname]["process"] = None
        logging.debug("%s stopped successfully", processname)

    def _stop_process(self, processname: str) -> None:
        """Stop a process - sequential version for individual stops"""
        if self.processes[processname]["process"]:
            logging.debug("Notifying %s", processname)
            self.processes[processname]["stopevent"].set()
            self._stop_process_parallel(processname)
        logging.debug("%s should be stopped", processname)

    @staticmethod
    def _check_port_available(host: str, port: int) -> bool:
        """Check if a port is available for binding"""
        return nowplaying.utils.network.port_available(port, host)

    def start_process(self, processname: str) -> None:
        """Start a specific process"""
        if processname == "twitchbot" and not self.config.cparser.value(
            "twitchbot/enabled", type=bool
        ):
            return
        if processname == "webserver" and not self.config.cparser.value(
            "weboutput/httpenabled", type=bool
        ):
            return
        if processname == "kickbot" and not (
            self.config.cparser.value("kick/enabled", type=bool)
            and self.config.cparser.value("kick/chat", type=bool)
        ):
            return
        if processname == "obsws" and not self.config.cparser.value("obsws/enabled", type=bool):
            return
        if processname == "discordbot" and not (
            self.config.cparser.value("discord/bot_enabled", type=bool)
            or self.config.cparser.value("discord/richpresence_enabled", type=bool)
        ):
            return

        # Check port availability for webserver before starting (skip in testmode)
        if processname == "webserver" and not self.testmode:
            host = self.config.cparser.value("weboutput/httphost", defaultValue="127.0.0.1")
            port = self.config.cparser.value("weboutput/httpport", type=int, defaultValue=8899)
            if not self._check_port_available(host, port):
                logging.error("Cannot start webserver: port %s:%s is already in use", host, port)
                self._port_busy_dialog(
                    "Web Server Error",
                    f"Cannot start web server:\nPort {host}:{port} is already in use.\n\n"
                    f"Please close any application using this port or change the port in "
                    f"Settings → Web Server.",
                )
                return

        # Icecast and Traktor bind inside trackpoll, which cannot raise a dialog
        # from a subprocess, and start_port() only logs a failed bind. Warn here
        # and start anyway: the source is unusable but the rest of WNP is not.
        if processname == "trackpoll" and not self.testmode:
            self._warn_if_input_port_busy()

        # trackpoll always starts - it's the core monitoring process
        self._start_process(processname)

    def _warn_if_input_port_busy(self) -> None:
        """Say so when the configured input cannot bind the port it needs."""
        if not self.config:
            return
        port = self.config.input_required_port()
        if port is None or nowplaying.utils.network.port_available(port):
            return
        logging.error("input source cannot bind port %s; it is already in use", port)
        self._port_busy_dialog(
            "Track Source Error",
            f"Nothing can be received on port {port}: it is already in use by "
            f"another application.\n\nClose that application, or set a different "
            f"port in Settings under Input Source and in your DJ software.",
        )

    @staticmethod
    def _port_busy_dialog(title: str, text: str) -> None:
        """Blocking, always on top: a port conflict is worth interrupting startup for."""
        dialog = QMessageBox(
            QMessageBox.Critical,
            title,
            text,
            QMessageBox.Ok,
            QApplication.activeWindow(),
        )
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)
        dialog.exec()

    def stop_process(self, processname: str) -> None:
        """Stop a specific process"""
        self._stop_process(processname)

    def restart_process(self, processname: str) -> None:
        """Restart a specific process"""
        self.stop_process(processname)
        self.start_process(processname)

    # Legacy methods for backward compatibility
    def start_webserver(self) -> None:
        """Start the webserver"""
        self.start_process("webserver")

    def start_kickbot(self) -> None:
        """Start the kickbot"""
        self.start_process("kickbot")

    def start_twitchbot(self) -> None:
        """Start the twitchbot"""
        self.start_process("twitchbot")

    def stop_webserver(self) -> None:
        """Stop the webserver"""
        self.stop_process("webserver")

    def stop_twitchbot(self) -> None:
        """Stop the twitchbot"""
        self.stop_process("twitchbot")

    def stop_kickbot(self) -> None:
        """Stop the kickbot"""
        self.stop_process("kickbot")

    def restart_webserver(self) -> None:
        """Restart the webserver process"""
        self.restart_process("webserver")

    def restart_obsws(self) -> None:
        """Restart the obsws process"""
        self.restart_process("obsws")

    def restart_kickbot(self) -> None:
        """Restart the kickbot process"""
        self.restart_process("kickbot")

    def restart_discordbot(self) -> None:
        """Restart the discordbot process"""
        self.restart_process("discordbot")
