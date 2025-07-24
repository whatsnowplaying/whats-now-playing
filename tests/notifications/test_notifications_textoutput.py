#!/usr/bin/env python3
"""test the text output notification plugin"""

import pathlib
import tempfile
import unittest.mock

import pytest
import pytest_asyncio

import nowplaying.config
import nowplaying.exceptions
import nowplaying.notifications.textoutput


@pytest_asyncio.fixture
async def textoutput_plugin(bootstrap):  # pylint: disable=redefined-outer-name
    """bootstrap a text output notification plugin"""
    config = bootstrap
    plugin = nowplaying.notifications.textoutput.Plugin(config=config)
    await plugin.start()
    try:
        yield plugin
    finally:
        await plugin.stop()


@pytest.mark.asyncio
async def test_textoutput_plugin_disabled(textoutput_plugin):  # pylint: disable=redefined-outer-name
    """test text output plugin when disabled (no file/template configured)"""
    textoutput_plugin.config.cparser.setValue("textoutput/file", "")
    textoutput_plugin.config.cparser.setValue("textoutput/txttemplate", "")
    await textoutput_plugin.start()

    metadata = {"artist": "Test Artist", "title": "Test Title", "filename": "test.mp3"}

    # Should do nothing when disabled
    await textoutput_plugin.notify_track_change(metadata)


@pytest.mark.asyncio
async def test_textoutput_plugin_no_output_file(textoutput_plugin):  # pylint: disable=redefined-outer-name
    """test text output plugin without output file configured"""
    textoutput_plugin.config.cparser.setValue("textoutput/file", "")
    textoutput_plugin.config.cparser.setValue("textoutput/txttemplate", "/path/to/template.txt")
    await textoutput_plugin.start()

    metadata = {"artist": "Test Artist", "title": "Test Title", "filename": "test.mp3"}

    # Should do nothing when no output file
    await textoutput_plugin.notify_track_change(metadata)


@pytest.mark.asyncio
async def test_textoutput_plugin_no_template_file(textoutput_plugin):  # pylint: disable=redefined-outer-name
    """test text output plugin without template file configured"""
    textoutput_plugin.config.cparser.setValue("textoutput/file", "/path/to/output.txt")
    textoutput_plugin.config.cparser.setValue("textoutput/txttemplate", "")
    await textoutput_plugin.start()

    metadata = {"artist": "Test Artist", "title": "Test Title", "filename": "test.mp3"}

    # Should do nothing when no template file
    await textoutput_plugin.notify_track_change(metadata)


@pytest.mark.asyncio
async def test_textoutput_plugin_enabled_writes_file(textoutput_plugin):  # pylint: disable=redefined-outer-name
    """test text output plugin writes file when enabled"""
    with tempfile.TemporaryDirectory() as temp_dir:
        output_file = str(pathlib.Path(temp_dir) / "output.txt")
        template_file = str(pathlib.Path(temp_dir) / "template.txt")

        # Create a simple template
        with open(template_file, "w", encoding="utf-8") as tfio:
            tfio.write("Artist: {{ artist }}\nTitle: {{ title }}")

        textoutput_plugin.config.cparser.setValue("textoutput/file", output_file)
        textoutput_plugin.config.cparser.setValue("textoutput/txttemplate", template_file)
        await textoutput_plugin.start()

        metadata = {"artist": "Test Artist", "title": "Test Title", "filename": "test.mp3"}

        await textoutput_plugin.notify_track_change(metadata)

        # Verify output file was written with correct content
        with open(output_file, "r", encoding="utf-8") as tfio:
            content = tfio.read()
        assert content == "Artist: Test Artist\nTitle: Test Title"


@pytest.mark.asyncio
async def test_textoutput_plugin_template_reload(textoutput_plugin):  # pylint: disable=redefined-outer-name
    """test text output plugin reloads template when changed"""
    with tempfile.TemporaryDirectory() as temp_dir:
        output_file = str(pathlib.Path(temp_dir) / "output.txt")
        template_file1 = str(pathlib.Path(temp_dir) / "template1.txt")
        template_file2 = str(pathlib.Path(temp_dir) / "template2.txt")

        # Create templates
        with open(template_file1, "w", encoding="utf-8") as tfio:
            tfio.write("Template 1: {{ artist }}")
        with open(template_file2, "w", encoding="utf-8") as tfio:
            tfio.write("Template 2: {{ title }}")

        # Configure and start with first template
        textoutput_plugin.config.cparser.setValue("textoutput/file", output_file)
        textoutput_plugin.config.cparser.setValue("textoutput/txttemplate", template_file1)
        await textoutput_plugin.start()

        metadata = {"artist": "Test Artist", "title": "Test Title"}

        # First notify should use existing template handler (created during start)
        await textoutput_plugin.notify_track_change(metadata)

        # Verify first template was written
        with open(output_file, "r", encoding="utf-8") as tfio:
            content = tfio.read()
        assert content == "Template 1: Test Artist"

        # Change template file in config (this triggers reload)
        textoutput_plugin.config.cparser.setValue("textoutput/txttemplate", template_file2)

        await textoutput_plugin.notify_track_change(metadata)

        # Verify second template was written
        with open(output_file, "r", encoding="utf-8") as tfio:
            content = tfio.read()
        assert content == "Template 2: Test Title"


@pytest.mark.asyncio
async def test_textoutput_plugin_handles_write_error(textoutput_plugin):  # pylint: disable=redefined-outer-name
    """test text output plugin handles write errors gracefully"""
    with tempfile.TemporaryDirectory() as temp_dir:
        output_file = str(pathlib.Path(temp_dir) / "output.txt")
        template_file = str(pathlib.Path(temp_dir) / "template.txt")

        # Create template
        with open(template_file, "w", encoding="utf-8") as tfio:
            tfio.write("{{ artist }} - {{ title }}")

        textoutput_plugin.config.cparser.setValue("textoutput/file", output_file)
        textoutput_plugin.config.cparser.setValue("textoutput/txttemplate", template_file)
        await textoutput_plugin.start()

        metadata = {"artist": "Test Artist", "title": "Test Title"}

        # Set output file to a non-existent directory to cause write error
        textoutput_plugin.output_file = "/nonexistent/directory/output.txt"

        # Should handle error gracefully without raising
        await textoutput_plugin.notify_track_change(metadata)


@pytest.mark.asyncio
async def test_textoutput_plugin_start_clears_file_on_startup(textoutput_plugin):  # pylint: disable=redefined-outer-name
    """test text output plugin clears file on start when clearonstartup is enabled"""
    with tempfile.TemporaryDirectory() as temp_dir:
        output_file = str(pathlib.Path(temp_dir) / "output.txt")
        template_file = str(pathlib.Path(temp_dir) / "template.txt")

        # Create template
        with open(template_file, "w", encoding="utf-8") as tfio:
            tfio.write("{{ artist }}")

        # Create existing output file with content
        with open(output_file, "w", encoding="utf-8") as tfio:
            tfio.write("existing content")

        textoutput_plugin.config.cparser.setValue("textoutput/file", output_file)
        textoutput_plugin.config.cparser.setValue("textoutput/txttemplate", template_file)
        textoutput_plugin.config.cparser.setValue("textoutput/clearonstartup", True)

        await textoutput_plugin.start()

        # Should clear the file
        with open(output_file, "r", encoding="utf-8") as tfio:
            content = tfio.read()
        assert content == ""


def test_textoutput_plugin_load_settingsui():
    """test load_settingsui method"""
    config = nowplaying.config.ConfigFile(testmode=True)
    config.cparser.setValue("textoutput/file", "/path/to/output.txt")
    config.cparser.setValue("textoutput/txttemplate", "/path/to/template.txt")
    config.cparser.setValue("textoutput/fileappend", True)
    config.cparser.setValue("textoutput/clearonstartup", False)

    plugin = nowplaying.notifications.textoutput.Plugin(config=config)

    # Mock UI widget with correct attribute names
    mock_widget = unittest.mock.Mock()
    mock_widget.textoutput_lineedit = unittest.mock.Mock()
    mock_widget.texttemplate_lineedit = unittest.mock.Mock()
    mock_widget.append_checkbox = unittest.mock.Mock()
    mock_widget.clear_checkbox = unittest.mock.Mock()

    plugin.load_settingsui(mock_widget)

    # Should load file paths and checkbox states
    mock_widget.textoutput_lineedit.setText.assert_called_once_with("/path/to/output.txt")
    mock_widget.texttemplate_lineedit.setText.assert_called_once_with("/path/to/template.txt")
    mock_widget.append_checkbox.setChecked.assert_called_once_with(True)
    mock_widget.clear_checkbox.setChecked.assert_called_once_with(False)


def test_textoutput_plugin_save_settingsui():
    """test save_settingsui method"""
    config = nowplaying.config.ConfigFile(testmode=True)
    plugin = nowplaying.notifications.textoutput.Plugin(config=config)

    # Mock UI widget with correct attribute names
    mock_widget = unittest.mock.Mock()
    mock_widget.textoutput_lineedit = unittest.mock.Mock()
    mock_widget.textoutput_lineedit.text.return_value = "/new/output.txt"
    mock_widget.texttemplate_lineedit = unittest.mock.Mock()
    mock_widget.texttemplate_lineedit.text.return_value = "/new/template.txt"
    mock_widget.append_checkbox = unittest.mock.Mock()
    mock_widget.append_checkbox.isChecked.return_value = True
    mock_widget.clear_checkbox = unittest.mock.Mock()
    mock_widget.clear_checkbox.isChecked.return_value = False

    plugin.save_settingsui(mock_widget)

    # Should save file paths and checkbox states to config
    assert config.cparser.value("textoutput/file") == "/new/output.txt"
    assert config.cparser.value("textoutput/txttemplate") == "/new/template.txt"
    assert config.cparser.value("textoutput/fileappend", type=bool) is True
    assert config.cparser.value("textoutput/clearonstartup", type=bool) is False


def test_textoutput_plugin_verify_settingsui_missing_file():
    """test verify_settingsui with missing output file"""
    config = nowplaying.config.ConfigFile(testmode=True)
    plugin = nowplaying.notifications.textoutput.Plugin(config=config)

    # Mock UI widget with template but no output file
    mock_widget = unittest.mock.Mock()
    mock_widget.textoutput_lineedit = unittest.mock.Mock()
    mock_widget.textoutput_lineedit.text.return_value = ""
    mock_widget.texttemplate_lineedit = unittest.mock.Mock()
    mock_widget.texttemplate_lineedit.text.return_value = "/path/to/template.txt"

    with pytest.raises(
        nowplaying.exceptions.PluginVerifyError, match="Output file path is required"
    ):
        plugin.verify_settingsui(mock_widget)


def test_textoutput_plugin_verify_settingsui_missing_template():
    """test verify_settingsui with missing template file"""
    config = nowplaying.config.ConfigFile(testmode=True)
    plugin = nowplaying.notifications.textoutput.Plugin(config=config)

    # Mock UI widget with output file but no template
    mock_widget = unittest.mock.Mock()
    mock_widget.textoutput_lineedit = unittest.mock.Mock()
    mock_widget.textoutput_lineedit.text.return_value = "/path/to/output.txt"
    mock_widget.texttemplate_lineedit = unittest.mock.Mock()
    mock_widget.texttemplate_lineedit.text.return_value = ""

    with pytest.raises(
        nowplaying.exceptions.PluginVerifyError, match="Template file path is required"
    ):
        plugin.verify_settingsui(mock_widget)


def test_textoutput_plugin_verify_settingsui_nonexistent_template():
    """test verify_settingsui with nonexistent template file"""
    config = nowplaying.config.ConfigFile(testmode=True)
    plugin = nowplaying.notifications.textoutput.Plugin(config=config)

    # Mock UI widget with valid file but nonexistent template
    mock_widget = unittest.mock.Mock()
    mock_widget.textoutput_lineedit = unittest.mock.Mock()
    mock_widget.textoutput_lineedit.text.return_value = "/path/to/output.txt"
    mock_widget.texttemplate_lineedit = unittest.mock.Mock()
    mock_widget.texttemplate_lineedit.text.return_value = "/nonexistent/template.txt"

    with pytest.raises(
        nowplaying.exceptions.PluginVerifyError, match="Template file does not exist"
    ):
        plugin.verify_settingsui(mock_widget)


def test_textoutput_plugin_verify_settingsui_valid():
    """test verify_settingsui with valid configuration"""
    config = nowplaying.config.ConfigFile(testmode=True)
    plugin = nowplaying.notifications.textoutput.Plugin(config=config)

    with tempfile.TemporaryDirectory() as temp_dir:
        template_file = str(pathlib.Path(temp_dir) / "template.txt")
        with open(template_file, "w", encoding="utf-8") as tfio:
            tfio.write("{{ artist }}")

        # Mock UI widget with valid configuration
        mock_widget = unittest.mock.Mock()
        mock_widget.textoutput_lineedit = unittest.mock.Mock()
        mock_widget.textoutput_lineedit.text.return_value = "/path/to/output.txt"
        mock_widget.texttemplate_lineedit = unittest.mock.Mock()
        mock_widget.texttemplate_lineedit.text.return_value = template_file

        # Should not raise any exception
        plugin.verify_settingsui(mock_widget)


def test_textoutput_plugin_desc_settingsui():
    """test desc_settingsui method"""
    config = nowplaying.config.ConfigFile(testmode=True)
    plugin = nowplaying.notifications.textoutput.Plugin(config=config)

    # Mock UI widget
    mock_widget = unittest.mock.Mock()

    plugin.desc_settingsui(mock_widget)

    # Should set description text
    mock_widget.setText.assert_called_once()
    call_args = mock_widget.setText.call_args[0][0]
    assert "track metadata" in call_args
    assert "text file" in call_args
    assert "template" in call_args
