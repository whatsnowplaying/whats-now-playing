#!/usr/bin/env python3
"""test templatehandler"""

import os
import re
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


def test_templatehandler_global_functions():
    """Test that TemplateHandler provides now(), today(), and timestamp() global functions"""

    # Test raw template with date/time functions
    raw_template = """
Current time: {{ now() }}
Today's date: {{ today() }}
Full timestamp: {{ timestamp() }}
Artist: {{ artist }}
""".strip()

    handler = nowplaying.utils.TemplateHandler(rawtemplate=raw_template)
    metadata = {"artist": "Test Artist"}

    result = handler.generate(metadata)
    lines = result.strip().split("\n")

    # Verify time format: HH:MM:SS
    time_line = lines[0]
    assert time_line.startswith("Current time: ")
    time_part = time_line.replace("Current time: ", "")
    assert re.match(r"^\d{2}:\d{2}:\d{2}$", time_part), f"Invalid time format: {time_part}"

    # Verify date format: YYYY-MM-DD
    date_line = lines[1]
    assert date_line.startswith("Today's date: ")
    date_part = date_line.replace("Today's date: ", "")
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", date_part), f"Invalid date format: {date_part}"

    # Verify timestamp format: YYYY-MM-DD HH:MM:SS
    timestamp_line = lines[2]
    assert timestamp_line.startswith("Full timestamp: ")
    timestamp_part = timestamp_line.replace("Full timestamp: ", "")
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", timestamp_part), (
        f"Invalid timestamp format: {timestamp_part}"
    )

    # Verify regular template variables still work
    artist_line = lines[3]
    assert artist_line == "Artist: Test Artist"


def test_templatehandler_global_functions_from_file():
    """Test that TemplateHandler provides global functions when loading from file"""

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a template file with date/time functions
        template_file = os.path.join(temp_dir, "datetime_template.txt")
        with open(template_file, "w", encoding="utf-8") as template_fh:
            template_content = (
                "Time: {{ now() }}\n"
                "Date: {{ today() }}\n"
                "Timestamp: {{ timestamp() }}\n"
                "Title: {{ title }}"
            )
            template_fh.write(template_content)

        handler = nowplaying.utils.TemplateHandler(filename=template_file)
        metadata = {"title": "Test Title"}

        result = handler.generate(metadata)
        lines = result.strip().split("\n")

        # Verify all three functions work from file-based templates
        assert lines[0].startswith("Time: ")
        assert re.match(r"^Time: \d{2}:\d{2}:\d{2}$", lines[0])

        assert lines[1].startswith("Date: ")
        assert re.match(r"^Date: \d{4}-\d{2}-\d{2}$", lines[1])

        assert lines[2].startswith("Timestamp: ")
        assert re.match(r"^Timestamp: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", lines[2])

        assert lines[3] == "Title: Test Title"
