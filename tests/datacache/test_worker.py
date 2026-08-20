#!/usr/bin/env python3
"""tests for the datacache worker process"""

import pytest

import nowplaying.processes.datacache


@pytest.mark.parametrize(
    "configured,expected",
    [
        (5, 5),  # the shipped default
        (1, 1),  # lower bound
        (10, 10),  # the ceiling
        (0, 1),  # zero would stall the queue entirely
        (-3, 1),  # negative is meaningless
        (500, 10),  # a typo must not open hundreds of connections
    ],
)
def test_concurrency_from_config(bootstrap, configured, expected):
    """artistextras/processes drives concurrency, clamped to a usable range.

    The setting is a free-form integer field, so out-of-range values reach here
    rather than being stopped by the widget.
    """
    bootstrap.cparser.setValue("artistextras/processes", configured)
    assert (
        nowplaying.processes.datacache._concurrency_from_config(  # pylint: disable=protected-access
            bootstrap
        )
        == expected
    )


def test_concurrency_defaults_when_unset(bootstrap):
    """With nothing stored, the shipped default applies rather than 0 or 1."""
    bootstrap.cparser.remove("artistextras/processes")
    assert (
        nowplaying.processes.datacache._concurrency_from_config(  # pylint: disable=protected-access
            bootstrap
        )
        == 5
    )
