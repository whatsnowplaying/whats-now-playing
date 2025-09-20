"""
Background workers for datacache operations.

This module provides async workers that process queued requests
in the background without blocking live DJ operations.
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any

from .client import DataCacheClient
from .queue import RateLimiterManager


class DataCacheWorker:  # pylint: disable=too-many-instance-attributes
    """
    Background worker for processing datacache requests.

    Handles queued requests with proper rate limiting and error handling.
    Designed to run continuously without impacting live DJ performance.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_concurrent: int = 3,
        batch_size: int = 10,
        worker_id: str = "worker",
    ):
        self.client = DataCacheClient(cache_dir)
        self.rate_limiters = RateLimiterManager()
        self.max_concurrent = max_concurrent
        self.batch_size = batch_size
        self.worker_id = worker_id
        self.running = False
        self._shutdown_event = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Start the background worker"""
        if self.running:
            return

        await self.client.initialize()
        self.running = True
        self._shutdown_event.clear()

        logging.info("DataCache worker %s starting", self.worker_id)

        # Setup signal handlers for graceful shutdown
        if sys.platform != "win32":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._signal_handler)

        # Start the main worker loop
        await self._worker_loop()

    def _signal_handler(self) -> None:
        """Handle shutdown signals"""
        logging.info("DataCache worker %s received shutdown signal", self.worker_id)
        asyncio.create_task(self.shutdown())

    async def shutdown(self) -> None:
        """Gracefully shutdown the worker"""
        if not self.running:
            return

        logging.info("DataCache worker %s shutting down", self.worker_id)
        self.running = False
        self._shutdown_event.set()

        # Cancel all running tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        await self.client.close()
        logging.info("DataCache worker %s shutdown complete", self.worker_id)

    async def _worker_loop(self) -> None:
        """Main worker processing loop"""
        consecutive_empty_batches = 0

        while self.running:
            try:
                # Process a batch of requests
                stats = await self._process_batch()

                if stats["processed"] == 0:
                    consecutive_empty_batches += 1
                    # Exponential backoff when queue is empty
                    sleep_time = min(1.0 * (2 ** min(consecutive_empty_batches - 1, 4)), 30.0)
                    await asyncio.sleep(sleep_time)
                else:
                    consecutive_empty_batches = 0
                    logging.debug(
                        "Worker %s processed batch: %d processed, %d succeeded, %d failed",
                        self.worker_id,
                        stats["processed"],
                        stats["succeeded"],
                        stats["failed"],
                    )
                    # Short pause between non-empty batches
                    await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                logging.info("Worker %s cancelled", self.worker_id)
                break
            except Exception as error:  # pylint: disable=broad-except
                logging.error("Worker %s error in main loop: %s", self.worker_id, error)
                await asyncio.sleep(5.0)  # Back off on errors

    async def _process_batch(self) -> dict[str, Any]:
        """Process a batch of requests concurrently"""
        stats = {"processed": 0, "succeeded": 0, "failed": 0}

        # Collect batch of requests
        requests = []
        for _ in range(self.batch_size):
            request = await self.client.storage.get_next_request()
            if request:
                requests.append(request)
            else:
                break

        if not requests:
            return stats

        # Process requests concurrently (up to max_concurrent)
        semaphore = asyncio.Semaphore(self.max_concurrent)
        tasks = []

        for request in requests:
            task = asyncio.create_task(self._process_request_with_semaphore(request, semaphore))
            self._tasks.add(task)
            tasks.append(task)

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Update stats and cleanup
        for i, result in enumerate(results):
            stats["processed"] += 1
            if isinstance(result, Exception):
                logging.error("Worker %s task failed: %s", self.worker_id, result)
                stats["failed"] += 1
            elif result:
                stats["succeeded"] += 1
            else:
                stats["failed"] += 1

            # Remove completed task from tracking
            self._tasks.discard(tasks[i])

        return stats

    async def _process_request_with_semaphore(
        self, request: dict[str, Any], semaphore: asyncio.Semaphore
    ) -> bool:
        """Process a single request with concurrency control"""
        async with semaphore:
            return await self._process_request(request)

    async def _process_request(self, request: dict[str, Any]) -> bool:
        """Process a single request"""
        request_id = request["request_id"]
        provider = request["provider"]
        request_key = request["request_key"]
        params = request["params"]

        try:
            # Apply rate limiting for this provider
            rate_limiter = self.rate_limiters.get_limiter(provider)
            await rate_limiter.acquire()

            if request_key == "fetch_url":
                # URL fetch request
                success = await self._handle_url_fetch(request_id, provider, params)
            else:
                logging.warning("Unknown request key: %s", request_key)
                success = False

            # Mark request as completed
            await self.client.storage.complete_request(request_id, success=success)
            return success

        except asyncio.CancelledError:
            # Worker is shutting down - mark request as failed so it can be retried
            await self.client.storage.complete_request(request_id, success=False)
            raise
        except Exception as error:  # pylint: disable=broad-except
            logging.error(
                "Worker %s error processing request %s: %s", self.worker_id, request_id, error
            )
            await self.client.storage.complete_request(request_id, success=False)
            return False

    async def _handle_url_fetch(
        self, request_id: str, provider: str, params: dict[str, Any]
    ) -> bool:
        """Handle a URL fetch request"""
        try:
            url = params["url"]
            identifier = params["identifier"]
            data_type = params["data_type"]
            timeout = params.get("timeout", 30.0)
            retries = params.get("retries", 3)
            ttl_seconds = params.get("ttl_seconds")
            metadata = params.get("metadata")

            # Check if already cached (might have been fetched by another worker)
            cached_result = await self.client.storage.retrieve_by_url(url)
            if cached_result:
                logging.debug("Request %s already cached, skipping", request_id)
                return True

            # Fetch and store the data
            result = await self.client._fetch_and_store(  # pylint: disable=protected-access
                url=url,
                identifier=identifier,
                data_type=data_type,
                provider=provider,
                timeout=timeout,
                retries=retries,
                ttl_seconds=ttl_seconds,
                metadata=metadata,
            )

            if result:
                logging.debug("Successfully fetched and cached: %s", url)
                return True
            logging.warning("Failed to fetch URL: %s", url)
            return False

        except Exception as error:  # pylint: disable=broad-except
            logging.error("Error handling URL fetch for %s: %s", request_id, error)
            return False


class DataCacheWorkerManager:
    """
    Manager for multiple datacache workers.

    Coordinates multiple workers for improved throughput while maintaining
    rate limits and resource constraints.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        num_workers: int = 2,
        max_concurrent_per_worker: int = 3,
    ):
        self.cache_dir = cache_dir
        self.num_workers = num_workers
        self.max_concurrent_per_worker = max_concurrent_per_worker
        self.workers: list[DataCacheWorker] = []
        self.running = False

    async def start(self) -> None:
        """Start all workers"""
        if self.running:
            return

        logging.info("Starting %d datacache workers", self.num_workers)

        # Create and start workers
        for i in range(self.num_workers):
            worker = DataCacheWorker(
                cache_dir=self.cache_dir,
                max_concurrent=self.max_concurrent_per_worker,
                worker_id=f"worker_{i}",
            )
            self.workers.append(worker)

        # Start all workers concurrently
        start_tasks = [worker.start() for worker in self.workers]
        await asyncio.gather(*start_tasks)

        self.running = True
        logging.info("All datacache workers started")

    async def shutdown(self) -> None:
        """Shutdown all workers"""
        if not self.running:
            return

        logging.info("Shutting down datacache workers")

        # Shutdown all workers concurrently
        shutdown_tasks = [worker.shutdown() for worker in self.workers]
        await asyncio.gather(*shutdown_tasks, return_exceptions=True)

        self.workers.clear()
        self.running = False
        logging.info("All datacache workers shut down")

    async def get_stats(self) -> dict[str, Any]:
        """Get statistics from all workers"""
        # This would require workers to maintain stats
        # For now, just return basic info
        return {
            "num_workers": len(self.workers),
            "running": self.running,
        }


# Standalone worker entry point
async def run_datacache_worker(
    cache_dir: Path | None = None,
    worker_id: str = "standalone",
    max_concurrent: int = 3,
) -> None:
    """
    Run a standalone datacache worker.

    This function can be used to run a worker in a separate process
    or as part of the main application.
    """
    worker = DataCacheWorker(
        cache_dir=cache_dir,
        max_concurrent=max_concurrent,
        worker_id=worker_id,
    )

    try:
        await worker.start()
    except KeyboardInterrupt:
        logging.info("Worker interrupted, shutting down")
    finally:
        await worker.shutdown()


# Example usage for background processing:
#
# # In the main application
# worker_manager = DataCacheWorkerManager(num_workers=2)
# await worker_manager.start()
#
# # Queue some requests
# providers = get_providers()
# await providers.images.cache_artist_thumbnail(
#     url="https://example.com/image.jpg",
#     artist_identifier="daft_punk",
#     provider="example",
#     immediate=False  # This will queue the request
# )
#
# # Workers will automatically process the queue
# # When shutting down:
# await worker_manager.shutdown()
