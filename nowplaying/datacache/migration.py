"""
Migration utilities for transitioning from apicache/imagecache to datacache.

Provides tools and strategies for:
- Safe parallel operation during migration
- Data migration from existing cache systems
- Backward compatibility wrappers
- Step-by-step migration plan
"""

import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Any

from .storage import DataStorage


class MigrationManager:
    """
    Manages migration from existing cache systems to datacache.

    Supports parallel operation and gradual transition to minimize
    risk of disrupting live DJ operations.
    """

    def __init__(self, storage: DataStorage, legacy_cache_dir: Path):
        self.storage = storage
        self.legacy_cache_dir = legacy_cache_dir

    async def migrate_apicache_data(  # pylint: disable=too-many-locals,too-many-nested-blocks
        self, apicache_db_path: Path
    ) -> dict[str, int]:
        """
        Migrate data from existing apicache.py SQLite database.

        Args:
            apicache_db_path: Path to existing apicache database

        Returns:
            Dictionary with migration statistics
        """
        stats = {"records_found": 0, "records_migrated": 0, "records_skipped": 0, "errors": 0}

        if not apicache_db_path.exists():
            logging.warning("Legacy apicache database not found: %s", apicache_db_path)
            return stats

        try:
            # Open legacy database (sync operation)
            legacy_conn = sqlite3.connect(str(apicache_db_path))
            cursor = legacy_conn.cursor()

            # Query existing cache entries
            cursor.execute(
                """
                SELECT url, response_data, created_at, expires_at
                FROM cache_responses
                WHERE expires_at > ?
            """,
                (asyncio.get_event_loop().time(),),
            )

            rows = cursor.fetchall()
            stats["records_found"] = len(rows)

            # Migrate each record
            for url, response_data, _created_at, expires_at in rows:
                try:
                    # Parse provider and data type from URL
                    provider, data_type = MigrationManager._parse_legacy_url(url)

                    if provider and data_type:
                        # Calculate remaining TTL
                        current_time = asyncio.get_event_loop().time()
                        ttl_seconds = max(0, int(expires_at - current_time))

                        if ttl_seconds > 0:
                            # Migrate to new cache
                            # Create identifier from URL for new API
                            identifier = f"legacy_api_{abs(hash(url)) % 1000000}"
                            success = await self.storage.store(
                                url=url,
                                identifier=identifier,
                                data_type=data_type,
                                provider=provider,
                                data_value=response_data,
                                ttl_seconds=ttl_seconds,
                                metadata={
                                    "migrated_from": "apicache",
                                    "original_url": url,
                                    "migrated_at": current_time,
                                },
                            )

                            if success:
                                stats["records_migrated"] += 1
                            else:
                                stats["errors"] += 1
                        else:
                            stats["records_skipped"] += 1  # Expired
                    else:
                        stats["records_skipped"] += 1  # Unknown provider

                except Exception as error:  # pylint: disable=broad-exception-caught
                    logging.error("Migration error for URL %s: %s", url, error)
                    stats["errors"] += 1

            legacy_conn.close()

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("APICache migration failed: %s", error)
            stats["errors"] += 1

        logging.info("APICache migration completed: %s", stats)
        return stats

    async def migrate_imagecache_data(  # pylint: disable=too-many-nested-blocks
        self, imagecache_dir: Path
    ) -> dict[str, int]:
        """
        Migrate data from existing imagecache directory structure.

        Args:
            imagecache_dir: Path to existing imagecache directory

        Returns:
            Dictionary with migration statistics
        """
        stats = {"files_found": 0, "files_migrated": 0, "files_skipped": 0, "errors": 0}

        if not imagecache_dir.exists():
            logging.warning("Legacy imagecache directory not found: %s", imagecache_dir)
            return stats

        try:
            # Find all cached image files
            for image_file in imagecache_dir.rglob("*"):
                if image_file.is_file() and MigrationManager._is_image_file(image_file):
                    stats["files_found"] += 1

                    try:
                        # Parse image metadata from filename/path
                        provider, data_type, identifier = MigrationManager._parse_image_path(
                            image_file
                        )

                        if provider and data_type:
                            # Read image data
                            image_data = image_file.read_bytes()

                            # Store in new cache
                            # Create synthetic URL for image data
                            synthetic_url = f"file://{image_file}"
                            success = await self.storage.store(
                                url=synthetic_url,
                                identifier=identifier,
                                data_type=data_type,
                                provider=provider,
                                data_value=image_data,
                                ttl_seconds=30 * 24 * 3600,  # 30 days default
                                metadata={
                                    "migrated_from": "imagecache",
                                    "original_file": str(image_file),
                                    "file_size": len(image_data),
                                    "migrated_at": asyncio.get_event_loop().time(),
                                },
                            )

                            if success:
                                stats["files_migrated"] += 1
                            else:
                                stats["errors"] += 1
                        else:
                            stats["files_skipped"] += 1

                    except Exception as error:  # pylint: disable=broad-exception-caught
                        logging.error("Image migration error for %s: %s", image_file, error)
                        stats["errors"] += 1

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("ImageCache migration failed: %s", error)
            stats["errors"] += 1

        logging.info("ImageCache migration completed: %s", stats)
        return stats

    @staticmethod
    def _parse_legacy_url(url: str) -> tuple[str, str]:  # pylint: disable=too-many-return-statements
        """Parse provider and data type from legacy API URL"""
        # Map legacy URLs to provider/data_type pairs
        if "musicbrainz.org" in url:
            if "/artist" in url:
                return "musicbrainz", "artist"
            if "/recording" in url:
                return "musicbrainz", "recording"
        if "discogs.com" in url:
            return "discogs", "search"
        if "fanart.tv" in url:
            return "fanarttv", "images"
        if "theaudiodb.com" in url:
            return "theaudiodb", "artist"
        if "en.wikipedia.org" in url:
            return "wikimedia", "page"

        return "", ""  # Unknown provider

    @staticmethod
    def _parse_image_path(image_path: Path) -> tuple[str, str, str]:
        """Parse provider, data type, and identifier from image path"""
        # Example: imagecache/fanart/artist/12345_fanart.jpg
        parts = image_path.parts

        if len(parts) >= 3:
            # Extract provider from parent directories
            provider = ""
            data_type = ""
            identifier = image_path.stem

            for part in parts:
                if part in ["fanart", "fanarttv"]:
                    provider = "fanarttv"
                elif part in ["theaudiodb", "audiodb"]:
                    provider = "theaudiodb"
                elif part in ["discogs"]:
                    provider = "discogs"
                elif part in ["artist", "album", "thumb", "banner"]:
                    data_type = part

            return provider, data_type, identifier

        return "", "", ""

    @staticmethod
    def _is_image_file(file_path: Path) -> bool:
        """Check if file is an image based on extension"""
        image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
        return file_path.suffix.lower() in image_extensions


class CompatibilityWrapper:
    """
    Provides backward compatibility for existing code during migration.

    Allows existing apicache.py and imagecache.py usage to work with
    the new datacache system during the transition period.
    """

    def __init__(self, storage: DataStorage):
        self.storage = storage

    async def apicache_get(self, url: str) -> Any:
        """
        Compatibility method for apicache.get() calls.

        Maps legacy API cache requests to new datacache system.
        """
        # Try to retrieve from new cache using URL
        cached = await self.storage.retrieve_by_url(url)
        if cached:
            data, _metadata = cached
            return data  # Return data only

        # If not in new cache, would fall back to legacy behavior
        # or make new API call through provider system
        return None

    async def imagecache_get(self, identifier: str, image_type: str) -> bytes | None:
        """
        Compatibility method for imagecache.get_image() calls.

        Maps legacy image cache requests to new datacache system.
        """
        # Try to retrieve from new cache using identifier
        results = await self.storage.retrieve_by_identifier(
            identifier=identifier, data_type=image_type, random=True
        )
        if results and isinstance(results, tuple):
            data, _metadata, _url = results
            if isinstance(data, bytes):
                return data  # Return image bytes

        return None


# Migration Plan Documentation
MIGRATION_PLAN = """
DATACACHE MIGRATION STRATEGY

Phase 1: Parallel Development (CURRENT)
========================================
✓ Develop datacache module alongside existing systems
✓ No disruption to current functionality
✓ Gradual testing and validation
✓ Create migration utilities and compatibility wrappers

Phase 2: Selective Migration (NEXT)
===================================
□ Start with NEW features (artist pre-caching)
□ Migrate non-critical API calls first
□ Add compatibility wrappers for existing code
□ Keep immediate/critical paths on old system until proven
□ Monitor performance and reliability

Critical Success Criteria for Phase 2:
- Zero impact on track polling performance
- All existing functionality continues to work
- Cache hit rates maintained or improved
- No increase in API call volumes

Phase 3: Full Migration (FUTURE)
================================
□ Replace apicache.py usage throughout codebase
□ Replace imagecache.py with datacache equivalent
□ Remove old systems and dependencies
□ Clean up compatibility wrappers

Migration Commands:
==================
# Migrate existing cache data
python -c "
import asyncio
from nowplaying.datacache.migration import MigrationManager
from nowplaying.datacache.storage import DataStorage
from pathlib import Path

async def migrate():
    # Use standard Qt cache location
    storage = DataStorage()
    await storage.initialize()

    manager = MigrationManager(storage, Path('cache'))

    # Migrate API cache
    api_stats = await manager.migrate_apicache_data(Path('cache/apicache.sqlite'))
    print('API Cache Migration:', api_stats)

    # Migrate image cache
    img_stats = await manager.migrate_imagecache_data(Path('cache/imagecache'))
    print('Image Cache Migration:', img_stats)

    await storage.close()

asyncio.run(migrate())
"

Integration Points:
==================
1. Replace apicache.cached_fetch() calls with providers.api.cache_api_response()
2. Replace imagecache.get_image() calls with providers.images.get_random_image()
3. Replace imagecache.randomimage() calls with providers.images.get_random_image()
4. Add queue_url_fetch() calls for pre-caching operations
5. Update configuration system to support datacache settings

Rollback Strategy:
==================
- Keep old cache systems intact during migration
- Use feature flags to control datacache usage
- Monitor error rates and performance metrics
- Quick rollback to legacy systems if issues arise

Testing Strategy:
================
1. Unit tests for all datacache components
2. Integration tests with existing provider APIs
3. Performance benchmarks vs existing systems
4. Load testing with realistic DJ usage patterns
5. Cache consistency validation

Risk Mitigation:
===============
- Parallel operation minimizes disruption risk
- Backward compatibility maintains existing functionality
- Gradual rollout allows early issue detection
- Comprehensive logging for debugging migration issues
- Feature flags for quick disable if problems occur
"""
