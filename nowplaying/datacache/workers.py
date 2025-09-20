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


class DataCacheWorker:
    """
    Background worker for processing datacache requests.

    Handles queued requests with proper rate limiting and error handling.
    Designed to run continuously without impacting live DJ performance.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_concurrent: int = 3,
        worker_id: str = "worker",
    ):
        self.client = DataCacheClient(cache_dir)
        self.max_concurrent = max_concurrent
        self.worker_id = worker_id
        self.running = False
        self._shutdown_event = asyncio.Event()

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

        await self.client.close()
        logging.info("DataCache worker %s shutdown complete", self.worker_id)

    async def _worker_loop(self) -> None:
        """Main worker processing loop"""
        consecutive_empty_batches = 0

        while self.running:
            try:
                stats = await self.client.process_queue(max_concurrent=self.max_concurrent)

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
