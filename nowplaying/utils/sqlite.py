#!/usr/bin/env python3
"""SQLite utility functions for nowplaying"""

import asyncio
import contextlib
import logging
import os
import random
import sqlite3
import time
from collections.abc import Awaitable, Callable, Iterator
from typing import Any


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


def retry_file_operation(
    operation_func: Callable[[], Any],
    max_retries: int = 10,
    base_delay: float = 0.1,
    jitter: float = 0.05,
) -> Any:
    """
    Retry file operations with exponential backoff for Windows file locking issues.

    Args:
        operation_func: The function to execute.
        max_retries: Maximum number of retries (default: 10).
        base_delay: Base delay in seconds (default: 0.1).
        jitter: Maximum jitter in seconds to add to delay (default: 0.05).

    Returns:
        The result of operation_func() if successful.

    Raises:
        OSError: If all retries are exhausted.
    """
    for attempt in range(max_retries):
        try:
            return operation_func()
        except OSError as error:
            # Check for Windows file locking errors
            if (
                os.name == "nt"
                and hasattr(error, "winerror")
                and error.winerror == 32  # ERROR_SHARING_VIOLATION  # pylint: disable=no-member
                and attempt < max_retries - 1
            ):
                delay = base_delay * (2**attempt)
                delay += random.uniform(0, jitter)
                logging.debug(
                    "Windows file locked, retry %d/%d after %.3fs (with jitter): %s",
                    attempt + 1,
                    max_retries,
                    delay,
                    error,
                )
                time.sleep(delay)
                continue
            logging.exception("File operation failed after retries")
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


@contextlib.contextmanager
def sqlite_connection(
    database_path: str, timeout: int = 10, row_factory=None
) -> Iterator[sqlite3.Connection]:
    """Context manager for sqlite3 connections that properly handles cleanup in Python 3.13.

    This wrapper uses nested context managers to ensure both proper transaction handling
    and proper connection cleanup, avoiding ResourceWarnings in Python 3.13.

    Args:
        database_path: Path to SQLite database file
        timeout: Connection timeout in seconds
        row_factory: Optional row factory (e.g., sqlite3.Row)

    Yields:
        sqlite3.Connection object ready for use

    Example:
        with sqlite_connection("path/to/db.sqlite", row_factory=sqlite3.Row) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM table")
            rows = cursor.fetchall()
            cursor.close()
    """
    with contextlib.closing(sqlite3.connect(database_path, timeout=timeout)) as connection:
        if row_factory:
            connection.row_factory = row_factory
        with connection:
            yield connection
