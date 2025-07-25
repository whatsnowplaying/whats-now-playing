#!/usr/bin/env python3
# pylint: disable=invalid-name
"""image cache"""

import asyncio
import concurrent.futures
import logging
import pathlib
import random
import sqlite3
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

import aiosqlite
import diskcache
import requests_cache

from PySide6.QtCore import QStandardPaths  # pylint: disable=no-name-in-module

import nowplaying.bootstrap
import nowplaying.utils
import nowplaying.version  # pylint: disable=import-error, no-name-in-module

if TYPE_CHECKING:
    import nowplaying.config

MAX_FANART_DOWNLOADS = 50


class ImageCache:
    """database operations for caches"""

    TABLEDEF = """
    CREATE TABLE identifiersha
    (srclocation TEXT PRIMARY KEY,
     cachekey TEXT DEFAULT NULL,
     identifier TEXT NOT NULL,
     imagetype TEXT NOT NULL,
     timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
     );
    """

    def __init__(
        self,
        sizelimit: int = 1,
        initialize: bool = False,
        cachedir: str | pathlib.Path | None = None,
        stopevent: asyncio.Event | None = None,
    ) -> None:
        if not cachedir:
            self.cachedir: pathlib.Path = pathlib.Path(
                QStandardPaths.standardLocations(QStandardPaths.CacheLocation)[0]
            ).joinpath("imagecache")
        else:
            self.cachedir: pathlib.Path = pathlib.Path(cachedir)

        self.cachedir.resolve().mkdir(parents=True, exist_ok=True)
        self.databasefile: pathlib.Path = self.cachedir.joinpath("imagecachev2.db")
        if not self.databasefile.exists():
            initialize = True
        self.httpcachefile: pathlib.Path = self.cachedir.joinpath("http")
        self.cache: diskcache.Cache = diskcache.Cache(
            directory=self.cachedir.joinpath("diskcache"),
            timeout=30,
            eviction_policy="least-frequently-used",
            size_limit=sizelimit * 1024 * 1024 * 1024,
        )
        if initialize:
            self.setup_sql(initialize=True)
        self.session: requests_cache.CachedSession | None = None
        self.logpath: str | pathlib.Path | None = None
        self.stopevent: asyncio.Event | None = stopevent

    def attempt_v1tov2_upgrade(self) -> None:
        """dbv1 to dbv2"""
        v1path = self.databasefile.parent.joinpath("imagecachev1.db")
        if not v1path.exists() or self.databasefile.exists():
            return

        logging.info("Upgrading ImageCache DB from v1 to v2")

        v1path.rename(self.databasefile)

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            cursor = connection.cursor()
            failed = False
            try:
                cursor.execute("ALTER TABLE artistsha RENAME COLUMN url TO srclocation;")
                cursor.execute("ALTER TABLE artistsha RENAME COLUMN artist TO identifier;")
                cursor.execute("ALTER TABLE artistsha RENAME TO identifiersha;")
            except sqlite3.OperationalError as err:
                self._log_sqlite_error(err)
                failed = True

        if failed:
            self.databasefile.unlink()

    def setup_sql(self, initialize: bool = False) -> None:
        """create the database"""

        if initialize and self.databasefile.exists():
            self.databasefile.unlink()

        self.attempt_v1tov2_upgrade()

        if self.databasefile.exists():
            return

        logging.info("Create imagecache db file %s", self.databasefile)
        self.databasefile.resolve().parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            cursor = connection.cursor()

            try:
                cursor.execute(self.TABLEDEF)
            except sqlite3.OperationalError:
                cursor.execute("DROP TABLE identifiersha;")
                cursor.execute(self.TABLEDEF)

        logging.debug("initialize imagecache")
        self.cache.clear()
        self.cache.cull()

    def random_fetch(self, identifier: str, imagetype: str) -> dict[str, str] | None:
        """fetch a random row from a cache for the identifier"""
        normalidentifier = nowplaying.utils.normalize(identifier, sizecheck=0, nospaces=True)
        data = None
        if not self.databasefile.exists():
            self.setup_sql()
            return None

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT * FROM identifiersha
 WHERE identifier=?
 AND imagetype=?
 AND cachekey NOT NULL
 ORDER BY random() LIMIT 1;""",
                    (
                        normalidentifier,
                        imagetype,
                    ),
                )
            except sqlite3.OperationalError as error:
                self._log_sqlite_error(error)
                return None

            row = cursor.fetchone()
            if not row:
                return None

            data = {
                "identifier": row["identifier"],
                "cachekey": row["cachekey"],
                "srclocation": row["srclocation"],
            }
            logging.debug("random got %s/%s/%s", imagetype, row["identifier"], row["cachekey"])

        return data

    def random_image_fetch(self, identifier: str, imagetype: str) -> bytes | None:
        """fetch a random image from an identifier"""
        image: bytes | None = None
        attempts = 0
        max_attempts = 10  # Prevent infinite loops

        while (data := self.random_fetch(identifier, imagetype)) and attempts < max_attempts:
            attempts += 1
            try:
                cache_result = self.cache[data["cachekey"]]
                if isinstance(cache_result, bytes):
                    image = cache_result
                    break  # Success, exit loop
            except KeyError as error:
                logging.error("random: cannot fetch key %s", error)
                self.erase_cachekey(data["cachekey"])
                # Continue to next iteration to try another entry

        if attempts >= max_attempts:
            logging.warning(
                "random_image_fetch: max attempts (%d) reached for %s/%s",
                max_attempts,
                imagetype,
                identifier,
            )
        return image

    def find_srclocation(self, srclocation: str) -> dict[str, str] | None:
        """find database entry by source location"""

        data = None
        if not self.databasefile.exists():
            self.setup_sql()
            return None

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT * FROM identifiersha WHERE srclocation=?""", (srclocation,)
                )
            except sqlite3.OperationalError as error:
                self._log_sqlite_error(error)
                return None

            if row := cursor.fetchone():
                data = {
                    "identifier": row["identifier"],
                    "cachekey": row["cachekey"],
                    "imagetype": row["imagetype"],
                    "srclocation": row["srclocation"],
                    "timestamp": row["timestamp"],
                }
        return data

    def find_cachekey(self, cachekey: str) -> dict[str, str] | None:
        """find database entry by cache key"""

        data = None
        if not self.databasefile.exists():
            self.setup_sql()
            return None

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                _ = cursor.execute("""SELECT * FROM identifiersha WHERE cachekey=?""", (cachekey,))
            except sqlite3.OperationalError:
                return None

            if row := cursor.fetchone():
                data = {
                    "identifier": row["identifier"],
                    "cachekey": row["cachekey"],
                    "srclocation": row["srclocation"],
                    "imagetype": row["imagetype"],
                    "timestamp": row["timestamp"],
                }

        return data

    def get_cache_keys_for_identifier(self, identifier: str, imagetype: str) -> list[str]:
        """get all cache keys for an identifier and image type"""
        cache_keys: list[str] = []

        if not self.databasefile.exists():
            self.setup_sql()
            return cache_keys

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()

            try:
                _ = cursor.execute(
                    """SELECT DISTINCT cachekey FROM identifiersha
                                 WHERE identifier=? AND imagetype=? AND cachekey IS NOT NULL""",
                    (identifier, imagetype),
                )

                cache_keys = [row["cachekey"] for row in cursor.fetchall()]

            except sqlite3.OperationalError as error:
                logging.error(
                    "Error querying cache keys for identifier %s, imagetype %s: %s",
                    identifier,
                    imagetype,
                    error,
                )

        return cache_keys

    def fill_queue(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        identifier: str | None = None,
        imagetype: str | None = None,
        srclocationlist: list[str] | None = None,
    ) -> None:
        """fill the queue"""

        if not self.databasefile.exists():
            self.setup_sql()

        if not config or not imagetype or not srclocationlist or not identifier:
            return

        if "logo" in imagetype:
            maxart: int = config.cparser.value("identifierextras/logos", defaultValue=3, type=int)
        elif "banner" in imagetype:
            maxart = config.cparser.value("identifierextras/banners", defaultValue=3, type=int)
        elif "thumb" in imagetype:
            maxart = config.cparser.value("identifierextras/thumbnails", defaultValue=3, type=int)
        else:
            maxart = config.cparser.value("identifierextras/fanart", defaultValue=20, type=int)

        logging.debug(
            "Putting %s unfiltered for %s/%s",
            min(len(srclocationlist), maxart),
            imagetype,
            identifier,
        )
        normalidentifier = nowplaying.utils.normalize(identifier, sizecheck=0, nospaces=True)
        if normalidentifier:
            for srclocation in random.sample(srclocationlist, min(len(srclocationlist), maxart)):
                self.put_db_srclocation(
                    identifier=normalidentifier, imagetype=imagetype, srclocation=srclocation
                )

    def get_next_dlset(self) -> list[dict[str, str]] | None:
        """get next download set"""

        def dict_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict[str, Any]:
            d: dict[str, Any] = {}
            for idx, col in enumerate(cursor.description):
                d[col[0]] = row[idx]
            return d

        dataset = None
        if not self.databasefile.exists():
            logging.error("imagecache does not exist yet?")
            return None

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = dict_factory
            cursor = connection.cursor()
            try:
                cursor.execute("""SELECT * FROM identifiersha WHERE cachekey IS NULL
 AND EXISTS (SELECT * FROM identifiersha
 WHERE imagetype='artistthumbnail' OR imagetype='artistbanner' OR imagetype='artistlogo')
 ORDER BY TIMESTAMP DESC""")
            except sqlite3.OperationalError as error:
                logging.error(error)
                return None

            dataset = cursor.fetchall()

            if dataset:
                logging.debug("banner/logo/thumbs found")
                return dataset

            try:
                cursor.execute("""SELECT * FROM identifiersha WHERE cachekey IS NULL
ORDER BY TIMESTAMP DESC""")
            except sqlite3.OperationalError as error:
                logging.error(error)
                return None

            dataset = cursor.fetchall()

        if dataset:
            logging.debug("artwork found")
        return dataset

    def put_db_cachekey(  # pylint:disable=too-many-arguments
        self,
        identifier: str,
        srclocation: str,
        imagetype: str,
        cachekey: str | None = None,
        content: bytes | None = None,
    ) -> bool:
        """update imagedb"""

        if not self.databasefile.exists():
            logging.error("imagecache does not exist yet?")
            return False

        if not identifier or not srclocation or not imagetype:
            logging.error(
                "missing parameters: ident %s srcl: %s it: %s", identifier, srclocation, imagetype
            )
            return False

        if not cachekey:
            cachekey = str(uuid.uuid4())

        if content:
            image = nowplaying.utils.image2png(content)
            self.cache[cachekey] = image

        normalidentifier = nowplaying.utils.normalize(identifier, sizecheck=0, nospaces=True)
        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()

            sql = """
INSERT OR REPLACE INTO
 identifiersha(srclocation, identifier, cachekey, imagetype) VALUES(?, ?, ?, ?);
"""
            try:
                cursor.execute(
                    sql,
                    (
                        srclocation,
                        normalidentifier,
                        cachekey,
                        imagetype,
                    ),
                )
            except sqlite3.OperationalError as error:
                self._log_sqlite_error(error)
                return False
        return True

    @staticmethod
    def _log_sqlite_error(error: sqlite3.Error) -> None:
        """extract the error bits"""
        msg = str(error)
        error_code = getattr(error, "sqlite_errorcode", "unknown")
        error_name = error.__class__.__name__
        logging.error("Error %s [Errno %s]: %s", msg, error_code, error_name)

    def put_db_srclocation(
        self, identifier: str, srclocation: str, imagetype: str | None = None
    ) -> None:
        """add source location to database"""

        if not self.databasefile.exists():
            logging.error("imagecache does not exist yet?")
            return

        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()

            sql = """
INSERT INTO
identifiersha(srclocation, identifier, imagetype)
VALUES (?,?,?);
"""
            try:
                cursor.execute(
                    sql,
                    (
                        srclocation,
                        identifier,
                        imagetype,
                    ),
                )
            except sqlite3.IntegrityError as error:
                if "UNIQUE" in str(error):
                    logging.debug("Duplicate srclocation (%s), ignoring", srclocation)
                else:
                    logging.error(error)
            except sqlite3.OperationalError as error:
                logging.error(error)

    def erase_srclocation(self, srclocation: str) -> None:
        """remove source location from database"""

        if not self.databasefile.exists():
            self.setup_sql()
            return

        logging.debug("Erasing %s", srclocation)
        with sqlite3.connect(self.databasefile, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            try:
                cursor.execute("DELETE FROM identifiersha WHERE srclocation=?;", (srclocation,))
            except sqlite3.OperationalError:
                return

    def erase_cachekey(self, cachekey: str) -> None:
        """remove cache key from database and requeue source"""

        if not self.databasefile.exists():
            self.setup_sql()
            return

        data = self.find_cachekey(cachekey)
        if not data:
            return

        # It was retrieved once before so put it back in the queue
        # if it fails in the queue, it will be deleted
        logging.debug(
            "Cache %s  srclocation %s has left cache, requeue it.", cachekey, data["srclocation"]
        )
        self.erase_srclocation(data["srclocation"])
        self.put_db_srclocation(
            identifier=data["identifier"],
            imagetype=data["imagetype"],
            srclocation=data["srclocation"],
        )
        return

    def vacuum_database(self) -> None:
        """Vacuum the image cache database to reclaim space from deleted entries.

        This should be called on application startup to optimize disk usage from previous session.
        """
        if not self.databasefile.exists():
            return

        try:
            with sqlite3.connect(self.databasefile, timeout=30) as connection:
                logging.debug("Vacuuming image cache database...")
                connection.execute("VACUUM")
                connection.commit()
                logging.info("Image cache database vacuumed successfully")
        except sqlite3.Error as error:
            logging.error("Database error during vacuum: %s", error)

    def image_dl(self, imagedict: dict[str, str]) -> None:
        """fetch an image and store it"""
        nowplaying.bootstrap.setuplogging(logdir=self.logpath, rotate=False)
        threading.current_thread().name = "ICFollower"
        logging.getLogger("requests_cache").setLevel(logging.CRITICAL + 1)
        logging.getLogger("aiosqlite").setLevel(logging.CRITICAL + 1)
        session = requests_cache.CachedSession(str(self.httpcachefile))

        logging.debug("Downloading %s %s", imagedict["imagetype"], imagedict["srclocation"])
        try:
            headers = {
                "user-agent": f"whatsnowplaying/{nowplaying.version.__VERSION__}"  # pylint: disable=no-member
                " +https://whatsnowplaying.github.io/"
            }
            dlimage = session.get(imagedict["srclocation"], timeout=5, headers=headers)
        except Exception as error:  # pylint: disable=broad-except
            logging.error("image_dl: %s %s", imagedict["srclocation"], error)
            self.erase_srclocation(imagedict["srclocation"])
            return
        if dlimage.status_code == 200:
            if not self.put_db_cachekey(
                identifier=imagedict["identifier"],
                srclocation=imagedict["srclocation"],
                imagetype=imagedict["imagetype"],
                content=dlimage.content,
            ):
                logging.error("db put failed")
        else:
            logging.error("image_dl: status_code %s", dlimage.status_code)
            self.erase_srclocation(imagedict["srclocation"])
            return

        return

    async def verify_cache_timer(self, stopevent: asyncio.Event) -> None:
        """run verify_cache periodically"""
        await self.verify_cache()
        counter = 0
        while not nowplaying.utils.safe_stopevent_check(stopevent):
            await asyncio.sleep(2)
            counter += 2
            if counter > 3600:
                await self.verify_cache()
                counter = 0

    async def verify_cache(self) -> None:
        """verify the image cache"""
        if not self.databasefile.exists():
            return

        cachekeys = {}

        try:
            logging.debug("Starting image cache verification")
            async with aiosqlite.connect(self.databasefile, timeout=30) as connection:
                connection.row_factory = sqlite3.Row
                sql = "SELECT cachekey, srclocation FROM identifiersha"
                async with connection.execute(sql) as cursor:
                    async for row in cursor:
                        srclocation = row["srclocation"]
                        if srclocation == "STOPWNP":
                            continue
                        cachekeys[row["cachekey"]] = srclocation
        except Exception as err:  # pylint: disable=broad-except
            logging.exception("Error: %s", err)

        startsize = len(cachekeys)
        if not startsize:
            logging.debug("Finished image cache verification: no cache!")
            return

        count = startsize
        # making this two separate operations unlocks the DB
        for key, srclocation in cachekeys.items():
            try:
                image = self.cache[key]  # pylint: disable=unused-variable
            except KeyError:
                count -= 1
                logging.debug("%s/%s expired", key, srclocation)
                self.erase_srclocation(srclocation)
        logging.debug("Finished image cache verification: %s/%s images", count, startsize)

    def queue_process(self, logpath: str | pathlib.Path, maxworkers: int = 5) -> None:
        """Process to download stuff in the background to avoid the GIL"""

        threading.current_thread().name = "ICQueue"
        nowplaying.bootstrap.setuplogging(logdir=logpath, rotate=False)
        self.logpath = logpath
        self.erase_srclocation("STOPWNP")

        # Track recently processed items to avoid duplicates
        recently_processed: dict[str, float] = {}

        with concurrent.futures.ProcessPoolExecutor(max_workers=maxworkers) as executor:
            while not self._queue_should_stop():
                # Get next batch of items to download
                batch = self._get_next_queue_batch(recently_processed)

                if not batch:
                    time.sleep(2)
                    continue

                # Filter out stop signal and process remaining items
                items_to_process = [item for item in batch if item["srclocation"] != "STOPWNP"]
                should_stop = len(items_to_process) != len(batch)  # STOPWNP was found

                # Submit batch for processing if there are items
                if items_to_process:
                    executor.map(self.image_dl, items_to_process)

                # Stop after processing if stop signal was found
                if should_stop:
                    break

                # Mark items as recently processed (only the ones we actually processed)
                current_time = time.time()
                for item in items_to_process:
                    recently_processed[item["srclocation"]] = current_time

                # Clean up old entries from tracking
                self._cleanup_queue_tracking(recently_processed)

                time.sleep(2)

                # Ensure database exists
                if not self.databasefile.exists():
                    self.setup_sql()

        logging.debug("stopping download processes")
        self.erase_srclocation("STOPWNP")

    def _queue_should_stop(self) -> bool:
        """Check if the queue process should stop."""
        return nowplaying.utils.safe_stopevent_check(self.stopevent)

    def _get_next_queue_batch(self, recently_processed: dict[str, float]) -> list[dict[str, str]]:
        """Get next batch of items for queue processing, filtering out recently processed ones."""
        dataset = self.get_next_dlset()
        if not dataset:
            return []

        batch = []
        for entry in dataset:
            srclocation = entry["srclocation"]

            # Always include stop signal
            if srclocation == "STOPWNP":
                batch.append(entry)
                continue

            # Skip if recently processed
            if srclocation in recently_processed:
                logging.debug("skipping recently processed srclocation %s", srclocation)
                continue

            batch.append(entry)

        return batch

    @staticmethod
    def _cleanup_queue_tracking(recently_processed: dict[str, float]) -> None:
        """Remove entries older than 3 minutes from queue processing tracking."""
        current_time = time.time()
        expired_keys = [
            srclocation
            for srclocation, timestamp in recently_processed.items()
            if current_time - timestamp > 180  # 3 minutes
        ]

        for key in expired_keys:
            del recently_processed[key]
            logging.debug("removing %s from recently processed tracking", key)

    def stop_process(self) -> None:
        """stop the bg ImageCache process"""
        logging.debug("imagecache stop_process called")
        self.put_db_srclocation("STOPWNP", "STOPWNP", imagetype="STOPWNP")
        self.cache.close()
        logging.debug("WNP should be set")
