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
import nowplaying.utils.sqlite
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

        with nowplaying.utils.sqlite.sqlite_connection(
            self.databasefile, timeout=30
        ) as connection:
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

        with nowplaying.utils.sqlite.sqlite_connection(
            self.databasefile, timeout=30
        ) as connection:
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

        with nowplaying.utils.sqlite.sqlite_connection(
            self.databasefile, timeout=30, row_factory=sqlite3.Row
        ) as connection:
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

        with nowplaying.utils.sqlite.sqlite_connection(
            self.databasefile, timeout=30, row_factory=sqlite3.Row
        ) as connection:
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

        with nowplaying.utils.sqlite.sqlite_connection(
            self.databasefile, timeout=30, row_factory=sqlite3.Row
        ) as connection:
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

        with nowplaying.utils.sqlite.sqlite_connection(
            self.databasefile, timeout=30, row_factory=sqlite3.Row
        ) as connection:
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
        if normalidentifier := nowplaying.utils.normalize(
            identifier, sizecheck=0, nospaces=True
        ):
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

        with nowplaying.utils.sqlite.sqlite_connection(
            self.databasefile, timeout=30, row_factory=dict_factory
        ) as connection:
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

        def _do_put():
            with nowplaying.utils.sqlite.sqlite_connection(
                self.databasefile, timeout=30, row_factory=sqlite3.Row
            ) as connection:
                cursor = connection.cursor()

                sql = """
INSERT OR REPLACE INTO
 identifiersha(srclocation, identifier, cachekey, imagetype) VALUES(?, ?, ?, ?);
"""
                cursor.execute(
                    sql,
                    (
                        srclocation,
                        normalidentifier,
                        cachekey,
                        imagetype,
                    ),
                )
                connection.commit()

        try:
            nowplaying.utils.sqlite.retry_sqlite_operation(_do_put)
            return True
        except sqlite3.OperationalError:
            logging.exception("Failed to put cachekey after retries: %s", srclocation)
            return False

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

        def _do_put_srclocation():
            with nowplaying.utils.sqlite.sqlite_connection(
                self.databasefile, timeout=30, row_factory=sqlite3.Row
            ) as connection:
                cursor = connection.cursor()

                sql = """
INSERT INTO
identifiersha(srclocation, identifier, imagetype)
VALUES (?,?,?);
"""
                cursor.execute(
                    sql,
                    (
                        srclocation,
                        identifier,
                        imagetype,
                    ),
                )
                connection.commit()

        try:
            nowplaying.utils.sqlite.retry_sqlite_operation(_do_put_srclocation)
        except sqlite3.IntegrityError as error:
            if "UNIQUE" in str(error):
                logging.debug("Duplicate srclocation (%s), ignoring", srclocation)
            else:
                logging.error(error)
        except sqlite3.OperationalError:
            logging.exception("Failed to put srclocation %s after retries", srclocation)

    def erase_srclocation(self, srclocation: str) -> None:
        """remove source location from database"""

        if not self.databasefile.exists():
            self.setup_sql()
            return

        logging.debug("Erasing %s", srclocation)

        def _do_erase():
            with nowplaying.utils.sqlite.sqlite_connection(
                self.databasefile, timeout=30, row_factory=sqlite3.Row
            ) as connection:
                cursor = connection.cursor()
                cursor.execute("DELETE FROM identifiersha WHERE srclocation=?;", (srclocation,))
                connection.commit()

        try:
            nowplaying.utils.sqlite.retry_sqlite_operation(_do_erase)
        except sqlite3.OperationalError:
            logging.exception("Failed to erase srclocation %s after retries", srclocation)

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
            with nowplaying.utils.sqlite.sqlite_connection(
                self.databasefile, timeout=30
            ) as connection:
                logging.debug("Vacuuming image cache database...")
                connection.execute("VACUUM")
                connection.commit()
                logging.info("Image cache database vacuumed successfully")
        except sqlite3.Error as error:
            logging.error("Database error during vacuum: %s", error)

    def image_dl(self, imagedict: dict[str, str]) -> dict[str, str] | None:
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
                " +http://whatsnowplaying.github.io/"
            }
            dlimage = session.get(imagedict["srclocation"], timeout=5, headers=headers)
        except Exception as error:  # pylint: disable=broad-except
            logging.error("image_dl: %s %s", imagedict["srclocation"], error)
            self.erase_srclocation(imagedict["srclocation"])
            return {"error_type": "network_error", "cooldown": 300}  # 5 minutes for network errors
        if dlimage.status_code == 200:
            if not self.put_db_cachekey(
                identifier=imagedict["identifier"],
                srclocation=imagedict["srclocation"],
                imagetype=imagedict["imagetype"],
                content=dlimage.content,
            ):
                logging.error("db put failed")
        elif dlimage.status_code == 429:
            # Rate limit exceeded - don't erase URL, it's still valid
            logging.warning(
                "image_dl: rate limit exceeded (429) for %s - keeping URL for retry",
                imagedict["srclocation"],
            )
            return {"error_type": "rate_limit", "cooldown": 60}
        elif 400 <= dlimage.status_code < 500:
            # Client errors (404, 403, etc.) - URL is likely invalid, remove it
            logging.error(
                "image_dl: client error %s for %s - removing invalid URL",
                dlimage.status_code,
                imagedict["srclocation"],
            )
            self.erase_srclocation(imagedict["srclocation"])
            return {"error_type": "client_error", "cooldown": 0}  # No retry for client errors
        else:
            # Server errors (500, 503, etc.) - transient issues, keep URL for retry
            logging.warning(
                "image_dl: server error %s for %s - keeping URL for retry",
                dlimage.status_code,
                imagedict["srclocation"],
            )
            return {"error_type": "server_error", "cooldown": 600}  # 10 minutes for server errors

        return None  # Successful download

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

        # Track recently processed items with failure types and cooldown periods
        recently_processed: dict[str, dict] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=maxworkers) as executor:
            while not self._queue_should_stop():
                # Get next batch of items to download
                batch = self._get_next_queue_batch(recently_processed)

                if not batch:
                    # Clean up old entries from tracking when no work available
                    self._cleanup_queue_tracking(recently_processed)
                    time.sleep(5)  # Wait longer when nothing to process
                    continue

                # Filter out stop signal and process remaining items
                items_to_process = [item for item in batch if item["srclocation"] != "STOPWNP"]
                should_stop = len(items_to_process) != len(batch)  # STOPWNP was found

                # If no items to process after filtering, clean up and wait longer
                if not items_to_process and not should_stop:
                    # Clean up old entries from tracking
                    self._cleanup_queue_tracking(recently_processed)
                    time.sleep(5)  # Wait longer when nothing to process
                    continue

                # Submit batch for processing if there are items
                results = []
                if items_to_process:
                    results = list(executor.map(self.image_dl, items_to_process))

                # Stop after processing if stop signal was found
                if should_stop:
                    break

                # Process results and update tracking
                current_time = time.time()
                for i, item in enumerate(items_to_process):
                    result = results[i] if i < len(results) else None
                    self._process_download_result(item, result, recently_processed, current_time)

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

    def _process_download_result(
        self,
        item: dict[str, str],
        result: dict[str, str] | None,
        recently_processed: dict[str, dict],
        current_time: float,
    ) -> None:
        """Process a single download result and update failure tracking."""
        srclocation = item["srclocation"]

        if result is None:
            # Success - no error info returned, reset failure count
            recently_processed[srclocation] = {
                "timestamp": current_time,
                "error_type": "success",
                "cooldown": 30,  # Short cooldown for successful downloads
                "failure_count": 0,
            }
        else:
            # Failure - increment failure count and check limits
            existing_info = recently_processed.get(srclocation, {"failure_count": 0})
            failure_count = existing_info["failure_count"] + 1
            error_type = result["error_type"]

            # Define failure limits for different error types
            failure_limits = {
                "rate_limit": 10,  # Rate limits should eventually resolve
                "server_error": 5,  # Server issues should be temporary
                "network_error": 3,  # Connection issues should resolve quickly
                "client_error": 1,  # Already removed, but just in case
            }

            max_failures = failure_limits.get(error_type, 3)  # Default to 3

            if failure_count >= max_failures:
                # Too many failures - remove URL permanently
                logging.warning(
                    "Removing %s after %d %s failures (limit: %d)",
                    srclocation,
                    failure_count,
                    error_type,
                    max_failures,
                )
                self.erase_srclocation(srclocation)
                # Remove from tracking so it won't be retried
                recently_processed.pop(srclocation, None)
            else:
                # Record failure with updated count
                recently_processed[srclocation] = {
                    "timestamp": current_time,
                    "error_type": error_type,
                    "cooldown": result["cooldown"],
                    "failure_count": failure_count,
                }
                logging.debug(
                    "Recorded failure for %s: %s (attempt %d/%d, cooldown: %d seconds)",
                    srclocation,
                    error_type,
                    failure_count,
                    max_failures,
                    result["cooldown"],
                )

    def _get_next_queue_batch(self, recently_processed: dict[str, dict]) -> list[dict[str, str]]:
        """Get next batch of items for queue processing, filtering out recently processed ones."""
        dataset = self.get_next_dlset()
        if not dataset:
            return []

        batch = []
        current_time = time.time()

        for entry in dataset:
            srclocation = entry["srclocation"]

            # Always include stop signal
            if srclocation == "STOPWNP":
                batch.append(entry)
                continue

            # Skip if recently processed and still in cooldown
            if srclocation in recently_processed:
                failure_info = recently_processed[srclocation]
                time_since_failure = current_time - failure_info["timestamp"]
                cooldown_period = failure_info["cooldown"]

                if time_since_failure < cooldown_period:
                    logging.debug(
                        "skipping %s (failure type: %s, %d seconds remaining)",
                        srclocation,
                        failure_info["error_type"],
                        int(cooldown_period - time_since_failure),
                    )
                    continue

            batch.append(entry)

        return batch

    @staticmethod
    def _cleanup_queue_tracking(recently_processed: dict[str, dict]) -> None:
        """Remove entries past their cooldown period from queue processing tracking."""
        current_time = time.time()
        expired_keys = [
            srclocation
            for srclocation, failure_info in recently_processed.items()
            if current_time - failure_info["timestamp"] > failure_info["cooldown"]
        ]

        for key in expired_keys:
            failure_info = recently_processed[key]
            # Only remove successful downloads and retryable failures from tracking
            # Failed URLs that hit failure limits were already removed from the database
            del recently_processed[key]
            logging.debug(
                "removing %s from recently processed tracking (cooldown expired, %d failures)",
                key,
                failure_info.get("failure_count", 0),
            )

    def close(self) -> None:
        """Close the diskcache to release file handles"""
        self.cache.close()

    def stop_process(self) -> None:
        """stop the bg ImageCache process"""
        logging.debug("imagecache stop_process called")
        self.put_db_srclocation("STOPWNP", "STOPWNP", imagetype="STOPWNP")
        self.close()
        logging.debug("WNP should be set")
