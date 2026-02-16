#!/usr/bin/env python3
"""Generic XML background processing utilities for DJ software collections"""

import asyncio
import logging
import pathlib
import sqlite3
import time
import xml.sax
from collections.abc import Callable
from typing import Protocol

import defusedxml.common
import defusedxml.sax

import nowplaying.utils.sqlite


# pylint: disable=missing-function-docstring,invalid-name
class XMLHandler(Protocol):
    """Protocol for XML SAX handlers"""

    def __init__(self, sqlcursor: sqlite3.Cursor) -> None: ...

    def startElement(self, name: str, attrs: dict[str, str]) -> None: ...

    def endElement(self, name: str) -> None: ...


class BackgroundXMLProcessor:  # pylint: disable=too-many-instance-attributes
    """Generic background XML processor with temp database and atomic swap"""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        database_path: pathlib.Path,
        handler_class: type[XMLHandler],
        xml_file_getter: Callable[[], pathlib.Path | None],
        table_schemas: list[str],
        config_key: str,
        config,
    ):
        self.database_path = database_path
        self.temp_database_path = database_path.with_suffix(".db.tmp")
        self.backup_database_path = database_path.with_suffix(".db.backup")
        self.handler_class = handler_class
        self.xml_file_getter = xml_file_getter
        self.table_schemas = table_schemas
        self.config_key = config_key
        self.config = config
        self._shutdown_event = asyncio.Event()

    def db_age_days(self) -> float | None:
        """Return age of database in days, or None if doesn't exist"""
        if not self.database_path.exists():
            return None
        age_seconds = time.time() - self.database_path.stat().st_mtime
        return age_seconds / (24 * 60 * 60)

    def needs_refresh(self, max_age_days: float = 7.0) -> bool:
        """Check if database needs refresh based on age"""
        age = self.db_age_days()
        return age is None or age > max_age_days

    async def _check_and_perform_refresh(self) -> None:
        """Check if refresh is needed and perform it"""
        rebuild_requested: bool = self.config.cparser.value(
            f"{self.config_key}/rebuild_db", type=bool
        )

        # Check if DB needs refresh based on age
        max_age_days = self.config.cparser.value(
            f"{self.config_key}/max_age_days", type=int, defaultValue=7
        )

        if self.needs_refresh(max_age_days):
            rebuild_requested = True

        if not rebuild_requested:
            return

        xml_file = self.xml_file_getter()
        if not xml_file or not xml_file.exists():
            return

        success = await self.background_refresh(xml_file, self.table_schemas)
        if success:
            self.config.cparser.setValue(f"{self.config_key}/rebuild_db", False)

    async def background_refresh_loop(self) -> None:
        """Background refresh polling loop with cancellation support"""
        try:
            while not self._shutdown_event.is_set():
                self.config.cparser.sync()
                await self._check_and_perform_refresh()

                # Wait with cancellation support
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=5)
                    break  # Shutdown requested
                except TimeoutError:
                    continue  # Normal timeout, continue loop

        except asyncio.CancelledError:
            logging.info("Background refresh loop cancelled")
            raise  # Re-raise to properly handle cancellation

    async def background_refresh(self, xml_file: pathlib.Path, table_schemas: list[str]) -> bool:
        """Background refresh with temp database and atomic swap"""
        logging.info("Starting XML database refresh: %s", self.database_path)
        if not xml_file.exists():
            logging.error("XML file (%s) does not exist", xml_file)
            return False

        # Create temp database directory
        self.temp_database_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove any existing temp file
        if self.temp_database_path.exists():
            self.temp_database_path.unlink()

        try:
            # Build temp database using streaming parser
            await asyncio.to_thread(self._build_temp_database, xml_file, table_schemas)

            # Atomic swap: rename temp to live
            if self.temp_database_path.exists():
                # Use retry logic for Windows file locking issues
                await asyncio.to_thread(
                    nowplaying.utils.sqlite.retry_file_operation, self._atomic_swap_inner
                )
                logging.info("XML database refreshed successfully: %s", self.database_path)
                return True
            logging.error("Temp database was not created")
            return False

        except (
            OSError,
            sqlite3.Error,
            xml.sax.SAXException,
            defusedxml.common.DefusedXmlException,
        ) as err:
            logging.exception("Background XML refresh failed with exception: %s", err)
            # Clean up temp file on error
            if self.temp_database_path.exists():
                self.temp_database_path.unlink()
            return False
        except asyncio.CancelledError:
            logging.info("Background XML refresh cancelled")
            # Don't clean up temp file if atomic swap might be in progress
            # The retry logic will handle cleanup appropriately
            logging.info("Skipping temp file cleanup during cancellation to avoid race condition")
            raise  # Re-raise to properly handle cancellation
        except Exception as err:
            logging.error("Unexpected error during XML refresh: %s", err, exc_info=True)
            # Clean up temp file on error
            if self.temp_database_path.exists():
                self.temp_database_path.unlink()
            raise  # Re-raise unexpected errors

    def _build_temp_database(self, xml_file: pathlib.Path, table_schemas: list[str]) -> None:
        """Build temporary database using streaming parser"""
        with nowplaying.utils.sqlite.sqlite_connection(self.temp_database_path) as connection:
            cursor = connection.cursor()

            # Create tables from schemas (use provided schemas or instance schemas)
            schemas_to_use = table_schemas or self.table_schemas
            for schema in schemas_to_use:
                cursor.execute(schema)
            connection.commit()

            # Use streaming SAX parser
            handler = self.handler_class(cursor)
            parser = defusedxml.sax.make_parser()
            parser.setContentHandler(handler)

            try:
                with open(xml_file, "rb") as xmlfile:
                    parser.parse(xmlfile)
            except xml.sax.SAXParseException as exc:
                # XML corruption after valid data (common when DJ software crashes)
                # Parser has already extracted all valid entries before the corruption
                logging.warning(
                    "XML file has trailing corruption (likely from software crash): %s", exc
                )
                logging.info("Continuing with parsed data - check logs if entries seem incomplete")

            # Commit whatever data was successfully parsed
            connection.commit()

    def _atomic_swap_inner(self) -> None:
        """Inner atomic swap operation for retry logic"""
        # Check if swap already completed
        if not self.temp_database_path.exists() and self.database_path.exists():
            logging.debug("Atomic swap appears to have already completed successfully")
            return

        if not self.temp_database_path.exists():
            raise FileNotFoundError(f"Temp database file missing: {self.temp_database_path}")

        if self.database_path.exists():
            # Create backup first
            if self.backup_database_path.exists():
                self.backup_database_path.unlink()
            self.database_path.rename(self.backup_database_path)

        # Atomic rename
        self.temp_database_path.rename(self.database_path)

        # Clean up backup after successful swap
        if self.backup_database_path.exists():
            self.backup_database_path.unlink()

    def shutdown(self) -> None:
        """Signal the background refresh loop to exit cleanly"""
        self._shutdown_event.set()

    def reset_shutdown_event(self) -> None:
        """Reset the shutdown event for reuse"""
        self._shutdown_event.clear()
