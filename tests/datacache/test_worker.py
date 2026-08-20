#!/usr/bin/env python3
"""tests for the datacache worker process"""

import unittest.mock

import pytest

import nowplaying.processes.datacache


def _config(value: int | None) -> unittest.mock.MagicMock:
    """A config whose artistextras/processes is value, or absent when None."""
    config = unittest.mock.MagicMock()
    config.cparser.value.side_effect = lambda key, **kwargs: (
        value if value is not None else kwargs.get("defaultValue")
    )
    return config


@pytest.mark.parametrize(
    "configured,expected",
    [
        (5, 5),  # the shipped default
        (1, 1),  # lower bound
        (10, 10),  # the ceiling
        (0, 1),  # zero would stall the queue entirely
        (-3, 1),  # negative is meaningless
        (500, 10),  # a typo must not open hundreds of connections
        (None, 5),  # absent falls back to the shipped default
    ],
)
def test_concurrency_from_config(configured, expected):
    """artistextras/processes drives concurrency, clamped to a usable range.

    The setting is a free-form integer field, so out-of-range values reach here
    rather than being stopped by the widget.
    """
    assert (
        nowplaying.processes.datacache._concurrency_from_config(  # pylint: disable=protected-access
            _config(configured)
        )
        == expected
    )
