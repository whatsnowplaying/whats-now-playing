#!/usr/bin/env python3
"""system tray"""

import logging
import sqlite3

from PySide6.QtCore import QFileSystemWatcher  # pylint: disable=no-name-in-module
from PySide6.QtGui import QAction, QActionGroup, QIcon  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QApplication,
    QErrorMessage,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

import nowplaying.apicache
import nowplaying.config
import nowplaying.db
import nowplaying.firstinstall
import nowplaying.notifications.charts
import nowplaying.oauth2
import nowplaying.settingsui
import nowplaying.subprocesses
import nowplaying.trackrequests
import nowplaying.twitch.chat

LASTANNOUNCED: dict[str, str | None] = {"artist": None, "title": None}


class Tray:  # pylint: disable=too-many-instance-attributes
    """System Tray object"""

    def __init__(self, startup_window: "nowplaying.startup.StartupWindow | None" = None) -> None:
        self.startup_window = startup_window

        # Initialize attributes that will be set later
        self.watcher = None
        self.requestswindow = None

        # Core initialization
        self._initialize_core_components()

        # UI setup
        self._setup_about_window()
        if not self.aboutwindow:  # Early return if about window failed
            return

        # System setup
        self._setup_database_and_processes()

        # Charts initialization
        self._setup_charts_key()

        # Settings and finalization
        self.settingswindow = None
        self._setup_settings_window()
        if not self.settingswindow:  # Early return if settings window failed
            return

        self._setup_tray_menu()
        self._finalize_initialization()

    def _initialize_core_components(self) -> None:
        """Initialize core configuration and tray components."""
        self._update_startup_progress("Loading configuration...")

        self.config = nowplaying.config.ConfigFile()

        # Clean up any stray temporary OAuth2 credentials from previous sessions
        self._update_startup_progress("Cleaning OAuth2 credentials...")
        nowplaying.oauth2.OAuth2Client.cleanup_stray_temp_credentials(self.config)
        self.icon = QIcon(str(self.config.iconfile))
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.icon)
        self.tray.setToolTip("Now Playing ▶")
        self.tray.setVisible(True)
        self.menu = QMenu()

    def _setup_about_window(self) -> None:
        """Setup the about window and action."""
        self._update_startup_progress("Loading about window...")

        self.aboutwindow = nowplaying.settingsui.load_widget_ui(self.config, "about")
        if not self.aboutwindow:
            self._show_installation_error("about_ui.ui")
            return

        nowplaying.settingsui.about_version_text(self.config, self.aboutwindow)
        self.about_action = QAction("About What's Now Playing")
        self.menu.addAction(self.about_action)
        self.about_action.setEnabled(True)
        self.about_action.triggered.connect(self.aboutwindow.show)

    def _setup_database_and_processes(self) -> None:
        """Setup database optimization and process manager."""
        self._update_startup_progress("Optimizing database...")
        self._vacuum_databases_on_startup()

        self._update_startup_progress("Initializing process manager...")
        self.subprocesses = nowplaying.subprocesses.SubprocessManager(self.config)

    def _setup_settings_window(self) -> None:
        """Setup the settings window."""
        self._update_startup_progress("Loading settings interface...")

        try:
            self.settingswindow = nowplaying.settingsui.SettingsUI(tray=self)
        except (RuntimeError, OSError, ImportError) as error:
            logging.error("Failed to create settings window: %s", error, exc_info=True)
            self._show_installation_error("settings UI files")
            self.settingswindow = None

    def _show_settings(self) -> None:
        """Show settings window and bring it to the front."""
        self.settingswindow.show()
        if self.settingswindow.qtui:
            self.settingswindow.qtui.raise_()
            self.settingswindow.qtui.activateWindow()
            self.settingswindow.qtui.setFocus()

    def _setup_tray_menu(self) -> None:
        """Setup all tray menu actions and structure."""
        # Settings and Requests actions
        self.settings_action = QAction("Settings")
        self.settings_action.triggered.connect(self._show_settings)
        self.menu.addAction(self.settings_action)

        self.request_action = QAction("Requests")
        self.request_action.triggered.connect(self._requestswindow)
        self.request_action.setEnabled(True)
        self.menu.addAction(self.request_action)
        self.menu.addSeparator()

        # Mix mode actions
        self.action_newestmode = QAction("Newest")
        self.action_oldestmode = QAction("Oldest")
        self.mixmode_actiongroup = QActionGroup(self.tray)
        self._configure_newold_menu()
        self.menu.addSeparator()

        # Pause and Exit actions
        self.action_pause = QAction()
        self._configure_pause_menu()
        self.menu.addSeparator()

        self.action_exit = QAction("Exit")
        self.action_exit.triggered.connect(self.cleanquit)
        self.menu.addAction(self.action_exit)

        # Finalize menu
        self.tray.setContextMenu(self.menu)
        self.tray.show()

    def _finalize_initialization(self) -> None:
        """Complete the initialization process."""
        self.config.get()

        # Handle installer dialogs
        self._handle_installer_dialogs()

        # Final UI setup
        self._update_startup_progress("Finalizing setup...")
        self.action_pause.setText("Pause")
        self.action_pause.setEnabled(True)
        self.fix_mixmode_menu()

        # Settings and process startup
        self._update_startup_progress("Initializing settings...")
        self.settingswindow.post_tray_init()

        self._update_startup_progress("Starting processes...")
        self.subprocesses.start_all_processes(startup_window=self.startup_window)

        # Setup file watcher and requests
        self._setup_file_watcher()
        self.requestswindow = None
        self._configure_twitchrequests()

        # Check if reminder dialog should be shown for returning users
        self._check_reminder_dialog()

    def _handle_installer_dialogs(self) -> None:
        """Handle installer dialogs that may require window hiding."""
        if self.startup_window:
            self.startup_window.hide()
        self.installer()
        if self.startup_window:
            self.startup_window.show()

    def _setup_file_watcher(self) -> None:
        """Setup file system watcher for track notifications."""
        metadb = nowplaying.db.MetadataDB()
        self.watcher = QFileSystemWatcher()
        self.watcher.addPath(str(metadb.databasefile))
        self.watcher.fileChanged.connect(self.tracknotify)

    def _update_startup_progress(self, message: str) -> None:
        """Update startup window progress if available."""
        if self.startup_window:
            self.startup_window.update_progress(message)
            QApplication.processEvents()

    def _configure_twitchrequests(self) -> None:
        self.requestswindow = nowplaying.trackrequests.Requests(config=self.config)
        self.requestswindow.initial_ui()

    def _check_reminder_dialog(self) -> None:
        """Check if reminder dialog should be shown for returning users."""
        if nowplaying.firstinstall.should_show_reminder_dialog(self.config):
            logging.info("Showing reminder dialog for returning user")
            nowplaying.firstinstall.show_first_install_dialog(
                config=self.config, is_reminder=True, tray_icon=self.tray
            )

    @staticmethod
    def _show_installation_error(ui_file: str) -> None:
        """Show error dialog for corrupt installation"""
        msgbox = QErrorMessage()
        msgbox.showMessage(
            f"Critical error: Failed to load {ui_file}. "
            "Installation appears corrupt. Please reinstall the application."
        )
        msgbox.show()
        msgbox.exec()
        if app := QApplication.instance():
            app.exit(1)

    def _vacuum_databases_on_startup(self) -> None:
        """Vacuum databases on startup to reclaim space from previous session"""
        logging.debug("Starting database vacuum operations on startup")

        # Vacuum API cache database
        try:
            nowplaying.apicache.APIResponseCache.vacuum_database_file()
            logging.debug("API cache database vacuumed successfully")
        except (sqlite3.Error, OSError) as error:
            logging.error("Error vacuuming API cache: %s", error, exc_info=True)

        # Skip metadata database vacuum - it gets cleared on every startup anyway

        # Vacuum requests database (will be created later, so check if available)
        try:
            if hasattr(self, "requestswindow") and self.requestswindow:
                self.requestswindow.vacuum_database()
                logging.debug("Requests database vacuumed successfully")
        except (sqlite3.Error, AttributeError) as error:
            logging.error("Error vacuuming requests database: %s", error, exc_info=True)

        logging.debug("Database vacuum operations completed")

    def _setup_charts_key(self) -> None:
        """Generate anonymous charts key if none exists"""
        self._update_startup_progress("Setting up Charts service...")
        existing_key = self.config.cparser.value("charts/charts_key", defaultValue="")
        if not existing_key:
            if anonymous_key := nowplaying.notifications.charts.generate_anonymous_key():
                self.config.cparser.setValue("charts/charts_key", anonymous_key)
                self.config.cparser.sync()  # Ensure key is written to disk immediately
                logging.info("Generated and saved anonymous charts key during startup")
            else:
                logging.warning("Failed to generate anonymous key during startup")

    def _requestswindow(self) -> None:
        if self.config.cparser.value("settings/requests", type=bool) and self.requestswindow:
            self.requestswindow.raise_window()

    def _configure_newold_menu(self) -> None:
        self.action_newestmode.setCheckable(True)
        self.action_newestmode.setEnabled(True)
        self.action_oldestmode.setCheckable(True)
        self.action_oldestmode.setEnabled(False)
        self.menu.addAction(self.action_newestmode)
        self.menu.addAction(self.action_oldestmode)
        self.mixmode_actiongroup.addAction(self.action_newestmode)
        self.mixmode_actiongroup.addAction(self.action_oldestmode)
        self.action_newestmode.triggered.connect(self.newestmixmode)
        self.action_oldestmode.triggered.connect(self.oldestmixmode)

    def _configure_pause_menu(self) -> None:
        self.action_pause.triggered.connect(self.pause)
        self.menu.addAction(self.action_pause)
        self.action_pause.setEnabled(False)

    def webenable(self, status: bool) -> None:
        """If the web server gets in trouble, we need to tell the user"""
        if not status:
            self.settingswindow.disable_web()
            self._show_settings()
            self.pause()

    def obswsenable(self, status: bool) -> None:
        """If the OBS WebSocket gets in trouble, we need to tell the user"""
        if not status:
            self.settingswindow.disable_obsws()
            self._show_settings()
            self.pause()

    def unpause(self) -> None:
        """unpause polling"""
        self.config.unpause()
        self.action_pause.setText("Pause")
        self.action_pause.triggered.connect(self.pause)

    def pause(self) -> None:
        """pause polling"""
        self.config.pause()
        self.action_pause.setText("Resume")
        self.action_pause.triggered.connect(self.unpause)

    def fix_mixmode_menu(self) -> None:
        """update the mixmode based upon current rules"""
        plugins = self.config.cparser.value("settings/input", defaultValue=None)
        if not plugins:
            return

        validmixmodes = self.config.validmixmodes()

        if "oldest" in validmixmodes:
            self.action_oldestmode.setEnabled(True)
        else:
            self.action_oldestmode.setEnabled(False)

        if "newest" in validmixmodes:
            self.action_newestmode.setEnabled(True)
        else:
            self.action_newestmode.setEnabled(False)

        if self.config.getmixmode() == "newest":
            self.action_newestmode.setChecked(True)
            self.action_oldestmode.setChecked(False)
        else:
            self.action_oldestmode.setChecked(True)
            self.action_newestmode.setChecked(False)

    def oldestmixmode(self) -> None:
        """enable active mixing"""
        self.config.setmixmode("oldest")
        self.fix_mixmode_menu()

    def newestmixmode(self) -> None:
        """enable passive mixing"""
        self.config.setmixmode("newest")
        self.fix_mixmode_menu()

    def tracknotify(self) -> None:
        """signal handler to update the tooltip"""
        global LASTANNOUNCED  # pylint: disable=global-statement, global-variable-not-assigned

        self.config.get()
        if self.config.notif:
            metadb = nowplaying.db.MetadataDB()
            metadata = metadb.read_last_meta()
            if not metadata:
                return

            # don't announce empty content
            artist = metadata.get("artist", "")
            title = metadata.get("title", "")

            if not artist and not title:
                logging.warning("Both artist and title are empty; skipping notify")
                return

            if artist == LASTANNOUNCED["artist"] and title == LASTANNOUNCED["title"]:
                return

            LASTANNOUNCED["artist"] = artist
            LASTANNOUNCED["title"] = title

            tip = f"{artist} - {title}"
            self.tray.setIcon(self.icon)
            self.tray.showMessage("Now Playing ▶ ", tip, icon=QSystemTrayIcon.MessageIcon.NoIcon)
            self.tray.show()

    def exit_everything(self) -> None:
        """quit app and cleanup"""

        logging.debug("Starting shutdown")
        if self.requestswindow:
            self.requestswindow.close_window()

        self.action_pause.setEnabled(False)
        self.request_action.setEnabled(False)
        self.action_newestmode.setEnabled(False)
        self.action_oldestmode.setEnabled(False)
        self.settings_action.setEnabled(False)

        self.subprocesses.stop_all_processes()

        # Clean up any stray temporary OAuth2 credentials before shutdown
        nowplaying.oauth2.OAuth2Client.cleanup_stray_temp_credentials(self.config)

        # Database vacuum operations moved to startup for better performance

    def fresh_start_quit(self) -> None:
        """wipe the current config"""
        self.exit_everything()
        self.config.initialized = False
        self.config.cparser.sync()
        for key in self.config.cparser.allKeys():
            self.config.cparser.remove(key)
        self.config.cparser.sync()

        self._exit_app()

    def cleanquit(self) -> None:
        """quit app and cleanup"""

        self.exit_everything()
        self.config.get()
        if not self.config.initialized:
            self.config.cparser.clear()
            self.config.cparser.sync()

        self._exit_app()

    def import_quit(self) -> None:
        """imported a new config"""
        self.exit_everything()
        self._exit_app()

    def _exit_app(self) -> None:
        """actually exit"""
        app = QApplication.instance()
        logging.info("shutting qapp down v%s", self.config.version)
        if app:
            app.exit(0)

    def installer(self) -> None:
        """make some guesses as to what the user needs"""
        plugin: str | None = self.config.cparser.value("settings/input", defaultValue=None)
        if plugin and not self.config.validate_source(plugin):
            self.config.cparser.remove("settings/input")
            msgbox = QErrorMessage()
            msgbox.showMessage(f"Configured source {plugin} is not supported. Reconfiguring.")
            msgbox.show()
            msgbox.exec()
        elif not plugin:
            msgbox = QMessageBox()
            msgbox.setText(
                "New installation! Thanks! Determining setup. This operation may take a bit!"
            )
            msgbox.show()
            msgbox.exec()
        else:
            return

        plugins = self.config.pluginobjs["inputs"]

        for plugin in plugins:
            if plugins[plugin].install():
                self.config.cparser.setValue("settings/input", plugin.split(".")[-1])
                break

        twitchchatsettings = nowplaying.twitch.chat.TwitchChatSettings()
        twitchchatsettings.update_twitchbot_commands(self.config)

        msgbox = QMessageBox()
        msgbox.setText(
            "Basic configuration hopefully in place. "
            "Bringing up the Settings windows. "
            " Please check the Source is correct for"
            " your DJ software."
        )
        msgbox.show()
        msgbox.exec()

        self._show_settings()
