#!/usr/bin/env python3
"""SQLite utility functions for nowplaying"""

import asyncio
import logging
import random
import sqlite3
import time
from typing import Any, Awaitable, Callable


def retry_sqlite_operation(
    operation_func: Callable[[], Any],
    max_retries: int = 10,
    base_delay: float = 0.1,
    jitter: float = 0.05,
) -> Any:
    """
    Retry SQLite operations with exponential backoff and jitter for database lock issues.

    Args:
        operation_func: The function to execute.
        max_retries: Maximum number of retries (default: 10).
        base_delay: Base delay in seconds (default: 0.1).
        jitter: Maximum jitter in seconds to add to delay (default: 0.05).

    Returns:
        The result of operation_func() if successful.

    Raises:
        sqlite3.OperationalError: If all retries are exhausted.
    """
    for attempt in range(max_retries):
        try:
            return operation_func()
        except sqlite3.OperationalError as error:
            if "database is locked" in str(error).lower() and attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                delay += random.uniform(0, jitter)
                logging.debug(
                    "Database locked, retry %d/%d after %.3fs (with jitter)",
                    attempt + 1,
                    max_retries,
                    delay,
                )
                time.sleep(delay)
                continue
            logging.exception("SQLite operation failed after retries")
            raise


async def retry_sqlite_operation_async(
    operation_func: Callable[[], Awaitable[Any]],
    max_retries: int = 10,
    base_delay: float = 0.1,
    jitter: float = 0.05,
) -> Any:
    """
    Retry async SQLite operations with exponential backoff and jitter for database lock issues.

    Args:
        operation_func: The async function to execute.
        max_retries: Maximum number of retries (default: 10).
        base_delay: Base delay in seconds (default: 0.1).
        jitter: Maximum jitter in seconds to add to delay (default: 0.05).

    Returns:
        The result of await operation_func() if successful.

    Raises:
        sqlite3.OperationalError: If all retries are exhausted.
    """
    for attempt in range(max_retries):
        try:
            return await operation_func()
        except sqlite3.OperationalError as error:
            if "database is locked" in str(error).lower() and attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                delay += random.uniform(0, jitter)
                logging.debug(
                    "Database locked, retry %d/%d after %.3fs (with jitter)",
                    attempt + 1,
                    max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            logging.exception("SQLite operation failed after retries")
            raise
