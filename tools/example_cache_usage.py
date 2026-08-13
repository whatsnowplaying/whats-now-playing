#!/usr/bin/env python3
"""
Example: Using the datacache system

This example demonstrates how to use nowplaying's unified datacache to speed up
artist metadata lookups during live DJ performances.  datacache replaced the old
apicache and imagecache modules; see nowplaying/datacache/CLAUDE.md.

Runs against a throwaway directory so it never touches your real cache.
"""

import asyncio
import logging
import pathlib
import tempfile
import time
import traceback

import orjson

import nowplaying.bootstrap
import nowplaying.datacache

# Configure logging to see cache hits/misses
logging.basicConfig(level=logging.DEBUG)


async def simulate_api_call(artist_name: str, delay: float = 2.0) -> dict:
    """Simulate a slow API call."""
    print(f"  🔄 Making API call for {artist_name} (simulating {delay}s delay)...")
    await asyncio.sleep(delay)
    return {
        "artist": artist_name,
        "bio": f"This is the biography for {artist_name}",
        "genres": ["Electronic", "Dance"],
        "formed_year": 2010,
    }


async def demo_cached_fetch():
    """Demonstrate cached_fetch(), the high-level entry point plugins use."""
    print("=== Cached Fetch Demo ===")

    async def fetch_artist_bio(artist_name: str) -> dict:
        return await simulate_api_call(artist_name, delay=1.5)

    for label in ("1. First cached_fetch call (cache miss):", "2. Second call (cache hit):"):
        print(f"\n{label}")
        start_time = time.time()
        data = await nowplaying.datacache.cached_fetch(
            provider="demo",
            artist_name="Deadmau5",
            endpoint="artist_bio",
            fetch_func=lambda: fetch_artist_bio("Deadmau5"),
            ttl_seconds=300,
        )
        print(f"   ⏱️  Time: {time.time() - start_time:.2f}s")
        print(f"   📄 Data: {data}")


async def demo_storage_layer(storage: nowplaying.datacache.DataStorage):
    """Demonstrate the byte-level storage layer underneath cached_fetch().

    Unlike the old apicache, datacache is keyed by URL rather than by a
    (provider, artist, endpoint) triple, and stores bytes rather than dicts --
    so callers do their own encoding.
    """
    print("\n\n=== Storage Layer Demo ===")

    url = "https://example.invalid/api/artist/daft-punk"
    payload = await simulate_api_call("Daft Punk", delay=0.1)

    print("\n1. Storing bytes under a URL key:")
    entry = await storage.store(
        url=url,
        identifier="Daft Punk",
        data_type="api_response",
        provider="demo",
        data_value=orjson.dumps(payload),
        ttl_seconds=300,
    )
    print(f"   🔑 cachekey: {entry.cachekey if entry else '<store failed>'}")
    print(f"   🧾 mime_type: {entry.mime_type if entry else 'n/a'}")

    print("\n2. Retrieving by URL:")
    start_time = time.time()
    cached = await storage.retrieve_by_url(url)
    print(f"   ⏱️  Time: {time.time() - start_time:.2f}s")
    if cached:
        print(f"   📄 Data: {orjson.loads(cached.data)}")
        print(f"   📟 status_code: {cached.status_code}")


async def demo_maintenance(cache_dir: pathlib.Path, storage):
    """Demonstrate expiry cleanup and startup maintenance."""
    print("\n\n=== Maintenance Demo ===")

    print("\n1. Cleaning up expired entries:")
    cleaned = await storage.cleanup_expired()
    print(f"   🧹 Removed {cleaned} expired entries")

    print("\n2. Startup maintenance (what systemtray runs at launch):")
    stats = nowplaying.datacache.run_maintenance(cache_dir)
    for key, value in sorted(stats.items()):
        print(f"   📊 {key}: {value}")


async def demo_performance_comparison():
    """Compare performance with and without caching."""
    print("\n\n=== Performance Comparison ===")

    test_artists = ["Martin Garrix", "Tiësto", "Armin van Buuren", "Above & Beyond"]

    async def cached_round() -> float:
        start = time.time()
        for artist in test_artists:
            await nowplaying.datacache.cached_fetch(
                provider="demo",
                artist_name=artist,
                endpoint="performance_test",
                fetch_func=lambda a=artist: simulate_api_call(a, delay=0.5),
                ttl_seconds=300,
            )
        return time.time() - start

    print("\n1. Without caching:")
    start_time = time.time()
    for artist in test_artists:
        await simulate_api_call(artist, delay=0.5)
    no_cache_time = time.time() - start_time
    print(f"   ⏱️  Total time: {no_cache_time:.2f}s")

    print("\n2. With caching - first run (cache misses):")
    print(f"   ⏱️  Total time: {await cached_round():.2f}s")

    print("\n3. With caching - second run (cache hits):")
    second_cache_time = await cached_round()
    print(f"   ⏱️  Total time: {second_cache_time:.2f}s")

    speedup = no_cache_time / second_cache_time if second_cache_time > 0 else 0
    print(f"\n📈 Performance improvement: {speedup:.1f}x faster with cache")


async def main():
    """Run all demos against a throwaway cache directory."""
    print("🚀 datacache Demo")
    print("=" * 50)

    nowplaying.bootstrap.set_qt_names()

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = pathlib.Path(tmpdir)
        # cached_fetch() resolves storage via get_client().storage, so it is the
        # DataCacheClient singleton -- not set_shared_storage() -- that has to point
        # at the throwaway directory, or this demo writes into the real cache.
        nowplaying.datacache.reset_client()
        client = nowplaying.datacache.get_client(cache_dir)
        await client.initialize()
        storage = client.storage

        try:
            await demo_cached_fetch()
            await demo_storage_layer(storage)
            await demo_maintenance(cache_dir, storage)
            await demo_performance_comparison()

            print("\n\n✅ Demo completed successfully!")
            print("\n💡 Key benefits:")
            print("   • Dramatically faster lookups for cached artists")
            print("   • Reduces API rate limiting issues")
            print("   • Better performance during live DJ sets")
            print("   • Automatic cleanup of expired entries")
            print("   • Used by all artist metadata plugins")

        except Exception as error:  # pylint: disable=broad-exception-caught
            print(f"\n❌ Demo failed: {error}")
            traceback.print_exc()
        finally:
            await client.close()
            nowplaying.datacache.reset_client()


if __name__ == "__main__":
    asyncio.run(main())
