#!/usr/bin/env python3
"""
Test utilities for simulating specific aiohttp client-side exceptions.

aiointercept (unlike aioresponses) can only simulate a dropped connection via
exception=True, which always surfaces to the client as the base
aiohttp.ClientConnectionError. Production code that branches on a more
specific exception type (aiohttp.ClientConnectorError, TimeoutError,
aiohttp.ServerTimeoutError, ...) can't be exercised precisely through that
mechanism, so tests that need to validate one of those specific except
branches should patch the request call directly with simulate_client_exception
instead.
"""

import contextlib
from collections.abc import Generator
from unittest.mock import AsyncMock, patch


@contextlib.contextmanager
def simulate_client_exception(exc: BaseException) -> Generator[None]:
    """Make the next aiohttp.ClientSession request raise *exc*.

    Patches aiohttp.ClientSession._request directly, so no real socket
    connection is attempted and the raised exception's type is preserved
    exactly, unlike aiointercept's exception=True which always raises
    aiohttp.ClientConnectionError.
    """
    with patch("aiohttp.ClientSession._request", AsyncMock(side_effect=exc)):
        yield
