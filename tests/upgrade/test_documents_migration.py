#!/usr/bin/env python3
"""test Documents directory migration"""

import os
import pathlib
import sys
import tempfile
import unittest.mock

from PySide6.QtCore import QSettings, QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.bootstrap
import nowplaying.upgrades.config
from tests.upgrade.upgradetools import reboot_macosx_prefs


def test_documents_migration():
    """test Documents/NowPlaying -> Documents/WhatsNowPlaying migration"""
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat

        # Set up mock Documents directory structure
        mock_docs = pathlib.Path(newpath) / "Documents"
        mock_docs.mkdir()
        old_dir = mock_docs / "NowPlaying"
        old_dir.mkdir()

        # Create some mock template files and files that should be ignored
        (old_dir / "templates").mkdir()
        (old_dir / "templates" / "test.txt").write_text("test template")
        (old_dir / "custom.html").write_text("<html>test</html>")
        (old_dir / "debug.log").write_text("old log file")
        (old_dir / "config.new").write_text("new config file")

        # Set up "old" config with paths pointing to old directory (simulate NowPlaying app)
        nowplaying.bootstrap.set_qt_names(appname="testsuite-old")
        oldconfig = QSettings(
            qsettingsformat, QSettings.UserScope, "whatsnowplaying", "testsuite-old"
        )
        oldconfig.clear()

        # Add some config values with old paths
        old_template_path = str(old_dir / "custom.html")
        oldconfig.setValue("weboutput/htmltemplate", old_template_path)
        oldconfig.setValue("textoutput/file", str(old_dir / "output.txt"))
        oldconfig.sync()
        old_filename = oldconfig.fileName()
        del oldconfig
        reboot_macosx_prefs()

        # Mock _getoldconfig to read our testsuite-old config (simulating old NowPlaying)
        def mock_getoldconfig(self):
            return QSettings(
                self.qsettingsformat,
                QSettings.UserScope,
                "whatsnowplaying",
                "testsuite-old",  # Read testsuite-old instead of production NowPlaying
            )

        # Mock QStandardPaths to return our temp directory and mock message box
        with (
            unittest.mock.patch.object(
                QStandardPaths, "standardLocations", return_value=[str(mock_docs)]
            ),
            unittest.mock.patch.object(
                nowplaying.upgrades.config.UpgradeConfig, "_getoldconfig", mock_getoldconfig
            ),
            unittest.mock.patch("nowplaying.upgrades.config.QMessageBox"),
        ):
            # Set up "new" app name for migration target
            nowplaying.bootstrap.set_qt_names(appname="testsuite")

            # Create upgrade instance which triggers migration
            nowplaying.upgrades.config.UpgradeConfig(testdir=newpath)

            # Verify new directory was created
            new_dir = mock_docs / "WhatsNowPlaying"
            assert new_dir.exists()
            assert (new_dir / "templates").exists()
            assert (new_dir / "templates" / "test.txt").exists()
            assert (new_dir / "custom.html").exists()

            # Verify .log and .new files were NOT copied
            assert not (new_dir / "debug.log").exists()
            assert not (new_dir / "config.new").exists()

            # Re-open config to check rewritten paths
            config = QSettings(
                qsettingsformat, QSettings.UserScope, "whatsnowplaying", "testsuite"
            )

            new_html_template = config.value("weboutput/htmltemplate")
            assert new_html_template is not None, "weboutput/htmltemplate was not migrated"
            assert "WhatsNowPlaying" in new_html_template
            assert str(new_dir / "custom.html") == new_html_template

            new_output_file = config.value("textoutput/file")
            assert new_output_file is not None, "textoutput/file was not migrated"
            assert "WhatsNowPlaying" in new_output_file
            assert str(new_dir / "output.txt") == new_output_file

        config.clear()
        del config
        reboot_macosx_prefs()

        # Clean up old config
        if os.path.exists(old_filename):
            os.unlink(old_filename)
        reboot_macosx_prefs()


def test_documents_migration_already_exists():
    """test Documents migration when new templates already exists"""
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat

        # Set up both old and new directories with templates
        mock_docs = pathlib.Path(newpath) / "Documents"
        mock_docs.mkdir()
        old_dir = mock_docs / "NowPlaying"
        old_dir.mkdir()
        (old_dir / "templates").mkdir()
        new_dir = mock_docs / "WhatsNowPlaying"
        new_dir.mkdir()
        (new_dir / "templates").mkdir()

        # Create different content in each
        (old_dir / "templates" / "old.txt").write_text("old")
        (new_dir / "templates" / "new.txt").write_text("new")

        nowplaying.bootstrap.set_qt_names(appname="testsuite")
        config = QSettings(qsettingsformat, QSettings.UserScope, "whatsnowplaying", "testsuite")
        config.clear()

        # Mock QStandardPaths and message box
        with (
            unittest.mock.patch.object(
                QStandardPaths, "standardLocations", return_value=[str(mock_docs)]
            ),
            unittest.mock.patch("nowplaying.upgrades.config.QMessageBox"),
        ):
            upgrade = nowplaying.upgrades.config.UpgradeConfig(testdir=newpath)
            upgrade._migrate_documents_directory(config)  # pylint: disable=protected-access

            # Verify new templates directory still only has its original content
            assert (new_dir / "templates" / "new.txt").exists()
            assert not (new_dir / "templates" / "old.txt").exists()

        config.clear()
        del config
        reboot_macosx_prefs()


def test_documents_migration_no_old_templates():
    """test Documents migration when old templates don't exist"""
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat

        mock_docs = pathlib.Path(newpath) / "Documents"
        mock_docs.mkdir()
        # Create old directory but no templates subdirectory
        old_dir = mock_docs / "NowPlaying"
        old_dir.mkdir()

        nowplaying.bootstrap.set_qt_names(appname="testsuite")
        config = QSettings(qsettingsformat, QSettings.UserScope, "whatsnowplaying", "testsuite")
        config.clear()

        # Mock QStandardPaths and message box
        with (
            unittest.mock.patch.object(
                QStandardPaths, "standardLocations", return_value=[str(mock_docs)]
            ),
            unittest.mock.patch("nowplaying.upgrades.config.QMessageBox"),
        ):
            upgrade = nowplaying.upgrades.config.UpgradeConfig(testdir=newpath)
            upgrade._migrate_documents_directory(config)  # pylint: disable=protected-access

            # Verify migration didn't happen (no templates to migrate)
            new_dir = mock_docs / "WhatsNowPlaying"
            # new_dir might exist from other setup, but templates shouldn't
            if new_dir.exists():
                assert not (new_dir / "templates").exists() or not any(
                    (new_dir / "templates").iterdir()
                )

        config.clear()
        del config
        reboot_macosx_prefs()


def test_path_rewriting():
    """test config path rewriting logic"""
    with tempfile.TemporaryDirectory() as newpath:
        if sys.platform == "win32":
            qsettingsformat = QSettings.IniFormat
        else:
            qsettingsformat = QSettings.NativeFormat

        nowplaying.bootstrap.set_qt_names(appname="testsuite")
        config = QSettings(qsettingsformat, QSettings.UserScope, "whatsnowplaying", "testsuite")
        config.clear()

        # Set up config with various path types
        old_path = "/Users/test/Documents/NowPlaying"
        config.setValue("weboutput/htmltemplate", f"{old_path}/templates/custom.html")
        config.setValue("textoutput/file", f"{old_path}/output.txt")
        config.setValue("discord/template", f"{old_path}/discord.txt")
        config.setValue("someother/setting", "not a path")
        config.sync()

        with unittest.mock.patch("nowplaying.upgrades.config.QMessageBox"):
            upgrade = nowplaying.upgrades.config.UpgradeConfig(testdir=newpath)
            new_path = "/Users/test/Documents/WhatsNowPlaying"
            upgrade._rewrite_documents_paths(config, old_path, new_path)  # pylint: disable=protected-access

        # Verify paths were rewritten
        assert config.value("weboutput/htmltemplate") == f"{new_path}/templates/custom.html"
        assert config.value("textoutput/file") == f"{new_path}/output.txt"
        assert config.value("discord/template") == f"{new_path}/discord.txt"
        assert config.value("someother/setting") == "not a path"

        config.clear()
        del config
        reboot_macosx_prefs()
