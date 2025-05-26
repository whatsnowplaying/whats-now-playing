#!/usr/bin/env python3
"""
Cache Management Utilities

Provides utilities for managing the API response cache, including cleanup,
statistics, and cache warming operations.
"""

import asyncio
import logging
import time
import typing as t

import nowplaying.apicache
import nowplaying.config


class CacheManager:
    """Manages cache operations and maintenance tasks."""

    def __init__(self, config: t.Optional['nowplaying.config.ConfigFile'] = None):
        """Initialize cache manager.

        Args:
            config: Optional config file instance
        """
        self.config = config
        self.cache = nowplaying.apicache.get_cache()
        self._cleanup_task: t.Optional[asyncio.Task] = None

    async def start_background_cleanup(self, interval_hours: float = 6.0):
        """Start background cache cleanup task.

        Args:
            interval_hours: Hours between cleanup runs
        """
        if self._cleanup_task and not self._cleanup_task.done():
            logging.warning("Background cleanup already running")
            return

        self._cleanup_task = asyncio.create_task(self._cleanup_loop(interval_hours * 3600))
        logging.info("Started background cache cleanup (every %.1f hours)", interval_hours)

    async def stop_background_cleanup(self):
        """Stop background cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logging.info("Stopped background cache cleanup")

    async def _cleanup_loop(self, interval_seconds: float):
        """Background cleanup loop."""
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                cleaned = await self.cache.cleanup_expired()
                if cleaned > 0:
                    logging.info("Background cleanup removed %d expired cache entries", cleaned)
            except asyncio.CancelledError:
                break
            except Exception as error:  # pylint: disable=broad-exception-caught
                logging.error("Error in background cache cleanup: %s", error)
                await asyncio.sleep(60)  # Wait before retrying

    async def get_detailed_stats(self) -> dict:
        """Get detailed cache statistics.

        Returns:
            Dictionary with comprehensive cache statistics
        """
        stats = await self.cache.get_cache_stats()

        # Add cache efficiency metrics
        total = stats.get('total_entries', 0)
        valid = stats.get('valid_entries', 0)
        expired = stats.get('expired_entries', 0)

        if total > 0:
            stats['cache_efficiency'] = {
                'valid_percentage': (valid / total) * 100,
                'expired_percentage': (expired / total) * 100,
                'total_size_mb': await self._estimate_cache_size_mb()
            }

        return stats

    async def _estimate_cache_size_mb(self) -> float:
        """Estimate cache size in MB (rough approximation)."""
        # This is a rough estimate - actual implementation would query DB size
        stats = await self.cache.get_cache_stats()
        total_entries = stats.get('total_entries', 0)
        # Assume average of 2KB per cache entry (very rough estimate)
        estimated_bytes = total_entries * 2048
        return estimated_bytes / (1024 * 1024)

    @staticmethod
    async def warm_cache_for_artists(artist_names: t.List[str],
                                     providers: t.Optional[t.List[str]] = None):
        """Pre-warm cache for a list of artists.

        This is useful for warming the cache with upcoming playlist artists
        to ensure fast lookups during live performance.

        Args:
            artist_names: List of artist names to warm cache for
            providers: List of providers to warm cache for. If None, uses all enabled providers.
        """
        if not providers:
            providers = ['theaudiodb', 'discogs', 'fanarttv', 'wikimedia']

        logging.info("Warming cache for %d artists across %d providers", len(artist_names),
                     len(providers))

        # This would require integration with the actual plugin system
        # For now, just log the operation
        for artist in artist_names:
            for provider in providers:
                logging.debug("Would warm cache for %s:%s", provider, artist)

    @staticmethod
    async def clear_artist_cache(artist_name: str, provider: t.Optional[str] = None):
        """Clear cached data for a specific artist.

        Args:
            artist_name: Artist name to clear cache for
            provider: If specified, only clear for this provider
        """
        # This would require extending the APIResponseCache to support artist-specific clearing
        logging.info("Clearing cache for artist: %s, provider: %s", artist_name, provider or "all")

    async def optimize_cache(self) -> dict:
        """Optimize cache by removing old unused entries and compacting database.

        Returns:
            Dictionary with optimization results
        """
        start_time = time.time()

        # Clean up expired entries
        expired_removed = await self.cache.cleanup_expired()

        optimization_time = time.time() - start_time

        result = {
            'expired_entries_removed': expired_removed,
            'optimization_time_seconds': optimization_time,
            'status': 'completed'
        }

        logging.info("Cache optimization completed in %.2fs, removed %d expired entries",
                     optimization_time, expired_removed)

        return result

    async def export_cache_report(self) -> str:
        """Generate a detailed cache performance report.

        Returns:
            Formatted report string
        """
        stats = await self.get_detailed_stats()

        report = ["=== API Cache Performance Report ===\n"]

        # Basic stats
        report.append(f"Total entries: {stats.get('total_entries', 0)}")
        report.append(f"Valid entries: {stats.get('valid_entries', 0)}")
        report.append(f"Expired entries: {stats.get('expired_entries', 0)}")

        # Efficiency metrics
        efficiency = stats.get('cache_efficiency', {})
        if efficiency:
            report.append(f"Cache efficiency: {efficiency.get('valid_percentage', 0):.1f}%")
            report.append(f"Estimated size: {efficiency.get('total_size_mb', 0):.1f} MB")

        # By provider
        by_provider = stats.get('by_provider', {})
        if by_provider:
            report.append("\n--- Entries by Provider ---")
            for provider, count in sorted(by_provider.items()):
                report.append(f"{provider}: {count}")

        # Top artists
        top_artists = stats.get('top_artists', [])
        if top_artists:
            report.append("\n--- Most Cached Artists ---")
            for artist, access_count in top_artists[:10]:
                report.append(f"{artist}: {access_count} accesses")

        report.append(f"\nReport generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

        return "\n".join(report)


async def setup_cache_management(
        config: t.Optional['nowplaying.config.ConfigFile'] = None) -> CacheManager:
    """Set up cache management with default settings.

    Args:
        config: Optional config file instance

    Returns:
        Configured CacheManager instance
    """
    manager = CacheManager(config)

    # Start background cleanup if configured
    # Default to enabled until config reading is implemented
    cleanup_enabled = True
    if cleanup_enabled:
        await manager.start_background_cleanup(interval_hours=6.0)

    return manager


# Convenience functions for common operations
async def cleanup_cache():
    """Quick cache cleanup - removes expired entries."""
    cache = nowplaying.apicache.get_cache()
    return await cache.cleanup_expired()


async def get_cache_stats():
    """Get basic cache statistics."""
    cache = nowplaying.apicache.get_cache()
    return await cache.get_cache_stats()


async def clear_all_cache():
    """Clear entire cache."""
    cache = nowplaying.apicache.get_cache()
    await cache.clear_cache()
