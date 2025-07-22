#!/usr/bin/env python3
"""test templatehandler"""

import os
import tempfile

import pytest

import nowplaying.utils  # pylint: disable=import-error
import nowplaying.notifications.textoutput  # pylint: disable=import-error


@pytest.mark.parametrize(
    "template_file,metadata,expected_checks",
    [
        # Basic template with full metadata
        (
            "simple.txt",
            {"artist": "this is an artist", "title": "this is the title"},
            [("this is an artist", 0), ("this is the title", 1)],
        ),
        # Empty metadata should result in empty content
        ("simple.txt", {}, [("", 0, "strip")]),
        # Missing template file should show error message
        (
            "missing.txt",
            {"artist": "this is an artist", "title": "this is the title"},
            [("No template found", 0)],
        ),
        # No template file (None) should show error message
        (
            None,
            {"artist": "this is an artist", "title": "this is the title"},
            [("No template found", 0)],
        ),
        # Track and disc handling - values should show
        ("tracktest.txt", {"track": "1", "disc": "1"}, [("Track: 1", 0), ("Disc: 1", 1)]),
        # Track and disc handling - empty values should not show
        (
            "tracktest.txt",
            {"track": "", "disc": ""},
            [("Track:", 0, "not_in"), ("Disc:", 0, "not_in")],
        ),
        # Track and disc handling - None values should not show
        ("tracktest.txt", {}, [("Track:", 0, "not_in"), ("Disc:", 0, "not_in")]),
    ],
)
@pytest.mark.asyncio
async def test_template_processing(template_file, metadata, expected_checks, bootstrap, getroot):
    """Test template processing with various scenarios"""
    with tempfile.TemporaryDirectory() as newpath:
        filename = os.path.join(newpath, "test.txt")

        # Handle template file path
        if template_file:
            template_path = os.path.join(getroot, "tests", "templates", template_file)
        else:
            template_path = None

        # Create and configure text output plugin
        plugin = nowplaying.notifications.textoutput.Plugin(config=bootstrap)
        plugin.config.cparser.setValue("textoutput/file", filename)
        if template_path:
            plugin.config.cparser.setValue("textoutput/txttemplate", template_path)
        await plugin.start()

        # Write the metadata using the plugin
        await plugin.notify_track_change(metadata)

        # Read the output file
        with open(filename, encoding="utf-8") as tempfh:
            content = tempfh.readlines()

        # Check expected content
        for check in expected_checks:
            expected_text = check[0]
            line_num = check[1]
            check_type = check[2] if len(check) > 2 else "in"

            if check_type == "strip":
                assert content[line_num].strip() == expected_text
            elif check_type == "not_in":
                assert expected_text not in content[line_num]
            else:  # default "in"
                assert expected_text in content[line_num]


@pytest.mark.asyncio
async def test_clear_template(bootstrap):
    """Test clearing template functionality"""
    with tempfile.TemporaryDirectory() as newpath:
        filename = os.path.join(newpath, "test.txt")

        # Create and configure text output plugin
        plugin = nowplaying.notifications.textoutput.Plugin(config=bootstrap)
        plugin.config.cparser.setValue("textoutput/file", filename)
        plugin.config.cparser.setValue("textoutput/clearonstartup", True)
        # Don't set template file to test the clear functionality
        await plugin.start()

        # File should be empty after clear
        with open(filename, encoding="utf-8") as tempfh:
            content = tempfh.read()

        assert content == ""
