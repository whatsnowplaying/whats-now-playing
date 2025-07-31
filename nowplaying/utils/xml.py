#!/usr/bin/env python3
"""Generic XML background processing utilities for DJ software collections"""

import asyncio
import logging
import pathlib
import sqlite3
import time
from typing import Protocol

import xml.sax
import defusedxml.sax
import defusedxml.common


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
        xml_file_getter: callable,
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

    async def background_refresh_loop(self) -> None:
        """Background refresh polling loop with cancellation support"""
        try:
            while not self._shutdown_event.is_set():
                self.config.cparser.sync()
                if not self.config.cparser.value(f"{self.config_key}/rebuild_db", type=bool):
                    # Check if DB needs refresh based on age
                    max_age_days = self.config.cparser.value(
                        f"{self.config_key}/max_age_days", type=int, defaultValue=7
                    )
                    if self.needs_refresh(max_age_days):
                        self.config.cparser.setValue(f"{self.config_key}/rebuild_db", True)
                    else:
                        # Wait with cancellation support
                        try:
                            await asyncio.wait_for(self._shutdown_event.wait(), timeout=60 * 5)
                            break  # Shutdown requested
                        except asyncio.TimeoutError:
                            continue  # Normal timeout, continue loop

                xml_file = self.xml_file_getter()
                if not xml_file or not xml_file.exists():
                    logging.error("XML file not found: %s", xml_file)
                    self.config.cparser.setValue(f"{self.config_key}/rebuild_db", False)
                    # Wait with cancellation support
                    try:
                        await asyncio.wait_for(self._shutdown_event.wait(), timeout=60 * 5)
                        break  # Shutdown requested
                    except asyncio.TimeoutError:
                        continue  # Normal timeout, continue loop

                success = await self.background_refresh(xml_file, self.table_schemas)
                if success:
                    self.config.cparser.setValue(f"{self.config_key}/rebuild_db", False)

                # Wait with cancellation support
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=60 * 5)
                    break  # Shutdown requested
                except asyncio.TimeoutError:
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
                await asyncio.to_thread(self._atomic_swap)
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
            logging.error("Background XML refresh failed: %s", err)
            # Clean up temp file on error
            if self.temp_database_path.exists():
                self.temp_database_path.unlink()
            return False
        except asyncio.CancelledError:
            logging.info("Background XML refresh cancelled")
            # Clean up temp file on cancellation
            if self.temp_database_path.exists():
                self.temp_database_path.unlink()
            raise  # Re-raise to properly handle cancellation
        except Exception as err:
            logging.error("Unexpected error during XML refresh: %s", err, exc_info=True)
            # Clean up temp file on error
            if self.temp_database_path.exists():
                self.temp_database_path.unlink()
            raise  # Re-raise unexpected errors

    def _build_temp_database(self, xml_file: pathlib.Path, table_schemas: list[str]) -> None:
        """Build temporary database using streaming parser"""
        with sqlite3.connect(self.temp_database_path) as connection:
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

            with open(xml_file, "rb") as xmlfile:
                parser.parse(xmlfile)

            connection.commit()

    def _atomic_swap(self) -> None:
        """Atomically swap temp database with live database"""
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
