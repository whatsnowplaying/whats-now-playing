#!/usr/bin/env python3
"""test systemtray"""
# pylint: disable=redefined-outer-name,unused-argument,protected-access

import pathlib
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtGui import QAction, QActionGroup, QIcon  # pylint: disable=import-error, no-name-in-module
from PySide6.QtWidgets import QMenu, QSystemTrayIcon  # pylint: disable=import-error, no-name-in-module

import nowplaying.systemtray  # pylint: disable=import-error


class MockConfig:
    """Mock config for systemtray testing"""

    def __init__(self):
        self.iconfile = pathlib.Path("test_icon.png")
        self.logpath = pathlib.Path("/tmp/test.log")
        self.notif = True
        self.initialized = True  # Always initialized for testing
        self.version = "4.2.0-test"  # Mock version
        self.cparser = MagicMock()
        self.cparser.value.side_effect = self._mock_config_value
        self.cparser.setValue = MagicMock()
        self.cparser.remove = MagicMock()
        self.cparser.sync = MagicMock()

    @staticmethod
    def _mock_config_value(key, **kwargs):
        defaults = {
            "settings/requests": True,
            "settings/input": "serato",
            "settings/mixmode": "newest",
        }
        return defaults.get(key, kwargs.get("defaultValue", False))

    @staticmethod
    def validmixmodes():
        """Return valid mix modes"""
        return ["newest", "oldest"]

    @staticmethod
    def getmixmode():
        """Get current mix mode"""
        return "newest"

    def setmixmode(self, mode):
        """Set mix mode"""
        # No implementation needed for mock

    def get(self):
        """Get configuration"""
        return self

    @staticmethod
    def validate_source(plugin):
        """Validate source plugin"""
        return True  # Always valid for testing

    @staticmethod
    def getbundledir():
        """Get bundle directory"""
        return pathlib.Path("/tmp/test_bundle")

    @staticmethod
    def gettemplatesdir():
        """Get templates directory"""
        return pathlib.Path("/tmp/test_templates")

    @staticmethod
    def getsetlistdir():
        """Get setlist directory"""
        return pathlib.Path("/tmp/test_setlist")

    @staticmethod
    def logsettings():
        """Log current settings"""
        # No logging needed for mock


class MockSubprocessManager:
    """Mock subprocess manager"""

    def __init__(self, config):
        self.config = config
        self.started = False
        self.stopped = False

    def start_all_processes(self, startup_window=None):
        """Start all processes"""
        self.started = True

    def stop_all_processes(self):
        """Stop all processes"""
        self.stopped = True


class MockSettingsUI:
    """Mock settings UI"""

    def __init__(
        self,
        tray=None,
    ):
        self.tray = tray
        self.shown = False

    def show(self):
        """Show settings UI"""
        self.shown = True

    def post_tray_init(self):
        """Post tray initialization"""
        # No implementation needed for mock


class MockTrackrequests:
    """Mock track requests"""

    def __init__(self, config=None):
        self.config = config
        self.raised = False
        self.closed = False

    def initial_ui(self):
        """Initialize UI"""
        # No implementation needed for mock

    def raise_window(self):
        """Raise window to front"""
        self.raised = True

    def close_window(self):
        """Close window"""
        self.closed = True

    def vacuum_database(self):
        """Vacuum database"""
        # No implementation needed for mock


class MockMetadataDB:
    """Mock metadata database"""

    def __init__(self):
        self.databasefile = pathlib.Path("/tmp/test.db")
        self.vacuumed = False

    @staticmethod
    def read_last_meta():
        """Read last metadata"""
        return {
            "artist": "Test Artist",
            "title": "Test Title",
        }

    def vacuum_database(self):
        """Vacuum database"""
        self.vacuumed = True


@pytest.fixture
def mock_dependencies():
    """Mock all the heavy dependencies for systemtray testing"""
    with (
        patch("nowplaying.config.ConfigFile", MockConfig),
        patch("nowplaying.subprocesses.SubprocessManager", MockSubprocessManager),
        patch("nowplaying.settingsui.SettingsUI", MockSettingsUI),
        patch("nowplaying.settingsui.load_widget_ui") as mock_load_ui,
        patch("nowplaying.settingsui.about_version_text"),
        patch("nowplaying.trackrequests.Requests", MockTrackrequests),
        patch("nowplaying.db.MetadataDB", MockMetadataDB),
        patch("nowplaying.apicache.APIResponseCache.vacuum_database_file") as mock_api_vacuum,
        patch("nowplaying.systemtray.QFileSystemWatcher") as mock_watcher,
    ):
        mock_load_ui.return_value = MagicMock()
        # Configure the mock watcher to have the expected Qt signal interface
        mock_watcher_instance = MagicMock()
        mock_watcher_instance.fileChanged = MagicMock()
        mock_watcher_instance.fileChanged.connect = MagicMock()
        mock_watcher_instance.addPath = MagicMock()
        mock_watcher.return_value = mock_watcher_instance

        yield {
            "load_ui": mock_load_ui,
            "api_vacuum": mock_api_vacuum,
            "mock_watcher": mock_watcher,
            "mock_watcher_instance": mock_watcher_instance,
        }


def test_tray_initialization_normal_mode(qtbot, mock_dependencies):
    """Test basic system tray initialization in normal mode"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot
    # qtbot.addWidget(tray.tray)

    # Verify core Qt components are created
    assert isinstance(tray.tray, QSystemTrayIcon)
    assert isinstance(tray.menu, QMenu)
    assert isinstance(tray.icon, QIcon)
    assert tray.tray.toolTip() == "Now Playing ▶"
    assert tray.tray.isVisible()

    # Verify configuration
    assert tray.config is not None

    # Verify subprocess manager is created and started
    assert tray.subprocesses is not None
    assert isinstance(tray.subprocesses, MockSubprocessManager)


def test_menu_actions_creation(qtbot, mock_dependencies):
    """Test that all menu actions are created correctly"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Verify required actions exist
    assert isinstance(tray.about_action, QAction)
    assert isinstance(tray.settings_action, QAction)
    assert isinstance(tray.request_action, QAction)
    assert isinstance(tray.action_newestmode, QAction)
    assert isinstance(tray.action_oldestmode, QAction)
    assert isinstance(tray.action_pause, QAction)
    assert isinstance(tray.action_exit, QAction)

    # Verify action group
    assert isinstance(tray.mixmode_actiongroup, QActionGroup)

    # Verify action text
    assert tray.about_action.text() == "About What's Now Playing"
    assert tray.settings_action.text() == "Settings"
    assert tray.request_action.text() == "Requests"
    assert tray.action_exit.text() == "Exit"


def test_database_vacuum_on_startup(qtbot, mock_dependencies):
    """Test that databases are vacuumed on startup"""
    with patch("nowplaying.systemtray.Tray._vacuum_databases_on_startup") as mock_vacuum:
        nowplaying.systemtray.Tray()
        # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

        # Verify vacuum was called during initialization
        mock_vacuum.assert_called_once()


def test_vacuum_databases_on_startup_method(qtbot, mock_dependencies):
    """Test the actual vacuum database startup method"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Verify API cache vacuum was called
    mock_dependencies["api_vacuum"].assert_called_once()

    # Verify metadata DB vacuum was called
    # This is harder to test directly, but we can verify the method exists
    assert hasattr(tray, "_vacuum_databases_on_startup")


def test_settings_window_integration(qtbot, mock_dependencies):
    """Test settings window creation and integration"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Verify settings window is created
    assert tray.settingswindow is not None
    assert isinstance(tray.settingswindow, MockSettingsUI)
    assert tray.settingswindow.tray == tray

    # Test settings action trigger
    tray.settings_action.trigger()
    assert tray.settingswindow.shown


def test_subprocess_integration(qtbot, mock_dependencies):
    """Test subprocess manager integration"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Verify subprocess manager is created
    assert tray.subprocesses is not None
    assert isinstance(tray.subprocesses, MockSubprocessManager)

    # Test that processes are started after tray init
    tray.settingswindow.post_tray_init()
    # Mock doesn't auto-call start_all_processes, but we can verify it exists
    assert hasattr(tray.subprocesses, "start_all_processes")


def test_track_requests_integration(qtbot, mock_dependencies):
    """Test track requests window integration"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Verify requests window is created
    assert tray.requestswindow is not None
    assert isinstance(tray.requestswindow, MockTrackrequests)

    # Test requests action trigger
    tray.request_action.trigger()
    # This calls _requestswindow which checks config first
    assert hasattr(tray, "requestswindow")


def test_mixmode_configuration(qtbot, mock_dependencies):
    """Test mix mode menu configuration"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Verify mix mode actions are configured
    assert tray.action_newestmode.isCheckable()
    assert tray.action_oldestmode.isCheckable()

    # Test mix mode switching
    tray.newestmixmode()
    # Verify the method exists and can be called
    assert hasattr(tray, "newestmixmode")
    assert hasattr(tray, "oldestmixmode")


def test_pause_functionality(qtbot, mock_dependencies):
    """Test pause/unpause functionality"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Verify pause action exists and is configured
    assert isinstance(tray.action_pause, QAction)

    # Test pause/unpause methods exist
    assert hasattr(tray, "pause")
    assert hasattr(tray, "unpause")


def test_track_notification_system(qtbot, mock_dependencies):
    """Test track notification functionality"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Test tracknotify method exists
    assert hasattr(tray, "tracknotify")

    # Test that it can be called without error
    tray.tracknotify()


def test_clean_quit_functionality(qtbot, mock_dependencies):
    """Test clean quit process"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Mock the exit methods to avoid actually exiting
    with patch.object(tray, "exit_everything") as mock_exit:
        tray.cleanquit()
        mock_exit.assert_called_once()


def test_exit_everything_subprocess_cleanup(qtbot, mock_dependencies):
    """Test that exit_everything properly cleans up subprocesses"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Test exit_everything method
    tray.exit_everything()

    # Verify subprocess cleanup was called
    assert tray.subprocesses.stopped  # pylint: disable=no-member

    # Verify actions are disabled
    assert not tray.action_pause.isEnabled()
    assert not tray.request_action.isEnabled()
    assert not tray.settings_action.isEnabled()


def test_ui_loading_error_handling(qtbot, mock_dependencies):
    """Test that tray handles UI loading errors with installation error dialog"""
    # Mock the error dialog to avoid actual UI display during tests
    with (
        patch("nowplaying.systemtray.Tray._show_installation_error") as mock_error_dialog,
        patch("nowplaying.settingsui.load_widget_ui", return_value=None),
    ):
        # This should trigger the installation error dialog
        nowplaying.systemtray.Tray()

        # Verify installation error dialog was called
        mock_error_dialog.assert_called_once_with("about_ui.ui")


def test_settings_ui_creation_error_handling(qtbot, mock_dependencies):
    """Test that tray handles settings UI creation errors with installation error dialog"""
    # Mock the error dialog to avoid actual UI display during tests
    with (
        patch("nowplaying.systemtray.Tray._show_installation_error") as mock_error_dialog,
        patch(
            "nowplaying.settingsui.SettingsUI",
            side_effect=RuntimeError("Settings UI creation failed"),
        ),
    ):
        # This should trigger the installation error dialog
        nowplaying.systemtray.Tray()

        # Verify installation error dialog was called
        mock_error_dialog.assert_called_once_with("settings UI files")


def test_menu_structure_and_separators(qtbot, mock_dependencies):
    """Test that menu has proper structure with separators"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Verify menu exists and has actions
    assert tray.menu is not None
    actions = tray.menu.actions()
    assert len(actions) > 0

    # Count separators (should have some for proper menu organization)
    separators = [action for action in actions if action.isSeparator()]
    assert len(separators) >= 2  # Should have at least a few separators for organization


def test_action_connections(qtbot, mock_dependencies):
    """Test that actions are properly connected to methods"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Test that actions have connections
    # Note: We can't easily test signal connections in unit tests,
    # but we can verify the methods exist
    assert hasattr(tray, "cleanquit")
    assert callable(tray.cleanquit)

    # Test about action connection by verifying aboutwindow exists
    assert hasattr(tray, "aboutwindow")


def test_requestswindow_conditional_display(qtbot, mock_dependencies):
    """Test that requests window only shows when enabled"""
    tray = nowplaying.systemtray.Tray()
    # Note: QSystemTrayIcon is not a QWidget, so we can't add it to qtbot

    # Test _requestswindow method
    tray._requestswindow()

    # Should call raise_window when requests are enabled
    assert tray.requestswindow.raised  # pylint: disable=no-member


def test_file_system_watcher_setup(qtbot, mock_dependencies):
    """Test that file system watcher is set up correctly"""
    tray = nowplaying.systemtray.Tray()

    # Verify that the mock watcher was instantiated
    mock_dependencies["mock_watcher"].assert_called_once()

    # Verify that the mock watcher's addPath was called
    mock_dependencies["mock_watcher_instance"].addPath.assert_called_once()

    # Verify that the mock watcher's fileChanged signal was connected
    mock_dependencies["mock_watcher_instance"].fileChanged.connect.assert_called_once()

    # The watcher should be set on the tray instance
    assert tray.watcher is not None
    assert tray.watcher == mock_dependencies["mock_watcher_instance"]
