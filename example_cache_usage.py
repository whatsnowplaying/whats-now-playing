#!/usr/bin/env python3
"""
Example: Using the API Response Caching System

This example demonstrates how to use nowplaying's API response caching
system to speed up artist metadata lookups during live DJ performances.
"""

import asyncio
import logging
import time
import traceback

import nowplaying.apicache

# Configure logging to see cache hits/misses
logging.basicConfig(level=logging.DEBUG)


async def simulate_api_call(artist_name: str, delay: float = 2.0) -> dict:
    """Simulate a slow API call."""
    print(f"  🔄 Making API call for {artist_name} (simulating {delay}s delay)...")
    await asyncio.sleep(delay)
    return {
        'artist': artist_name,
        'bio': f'This is the biography for {artist_name}',
        'genres': ['Electronic', 'Dance'],
        'formed_year': 2010
    }


async def demo_basic_caching():
    """Demonstrate basic cache operations."""
    print("=== Basic Caching Demo ===")

    cache = nowplaying.apicache.get_cache()

    # First lookup - cache miss
    print("\n1. First lookup (cache miss):")
    start_time = time.time()
    data = await cache.get('demo', 'Daft Punk', 'artist_info')
    if data is None:
        data = await simulate_api_call('Daft Punk')
        await cache.put('demo', 'Daft Punk', 'artist_info', data)
    elapsed = time.time() - start_time
    print(f"   ⏱️  Time: {elapsed:.2f}s")
    print(f"   📄 Data: {data}")

    # Second lookup - cache hit
    print("\n2. Second lookup (cache hit):")
    start_time = time.time()
    data = await cache.get('demo', 'Daft Punk', 'artist_info')
    elapsed = time.time() - start_time
    print(f"   ⏱️  Time: {elapsed:.2f}s")
    print(f"   📄 Data: {data}")


async def demo_cached_fetch():
    """Demonstrate using the cached_fetch function (used by plugins)."""
    print("\n\n=== Cached Fetch Demo ===")

    async def fetch_artist_bio(artist_name: str) -> dict:
        return await simulate_api_call(artist_name, delay=1.5)

    # First call - cache miss
    print("\n1. First cached_fetch call (cache miss):")
    start_time = time.time()
    data = await nowplaying.apicache.cached_fetch(
        provider='demo',
        artist_name='Deadmau5',
        endpoint='artist_bio',
        fetch_func=lambda: fetch_artist_bio('Deadmau5'),
        ttl_seconds=300
    )
    elapsed = time.time() - start_time
    print(f"   ⏱️  Time: {elapsed:.2f}s")
    print(f"   📄 Data: {data}")

    # Second call - cache hit
    print("\n2. Second cached_fetch call (cache hit):")
    start_time = time.time()
    data = await nowplaying.apicache.cached_fetch(
        provider='demo',
        artist_name='Deadmau5',
        endpoint='artist_bio',
        fetch_func=lambda: fetch_artist_bio('Deadmau5'),
        ttl_seconds=300
    )
    elapsed = time.time() - start_time
    print(f"   ⏱️  Time: {elapsed:.2f}s")
    print(f"   📄 Data: {data}")


async def demo_cache_stats():
    """Demonstrate cache statistics and cleanup."""
    print("\n\n=== Cache Statistics Demo ===")

    cache = nowplaying.apicache.get_cache()
    test_artists = ['Calvin Harris', 'Swedish House Mafia', 'Avicii']

    print(f"\n1. Adding test data for {len(test_artists)} artists...")
    for artist in test_artists:
        data = await simulate_api_call(artist, delay=0.1)  # Fast for demo
        await cache.put('demo', artist, 'artist_info', data)

    # Get statistics
    print("\n2. Cache statistics:")
    stats = await cache.get_cache_stats()
    print(f"   📊 Total entries: {stats.get('total_entries', 0)}")
    print(f"   ✅ Valid entries: {stats.get('valid_entries', 0)}")
    print(f"   🗑️  Expired entries: {stats.get('expired_entries', 0)}")
    print(f"   🎯 Cache hit potential: {stats.get('cache_hit_potential', 'N/A')}")

    # Show by provider
    by_provider = stats.get('by_provider', {})
    if by_provider:
        print("\n3. Entries by provider:")
        for provider, count in sorted(by_provider.items()):
            print(f"   {provider}: {count}")

    # Show top artists
    top_artists = stats.get('top_artists', [])
    if top_artists:
        print("\n4. Most accessed artists:")
        for artist, access_count in top_artists[:5]:
            print(f"   {artist}: {access_count} accesses")

    # Cleanup expired entries
    print("\n5. Cleanup expired entries:")
    cleaned = await cache.cleanup_expired()
    print(f"   🧹 Cleaned up {cleaned} expired entries")


async def demo_performance_comparison():
    """Compare performance with and without caching."""
    print("\n\n=== Performance Comparison ===")

    cache = nowplaying.apicache.get_cache()
    test_artists = ['Martin Garrix', 'Tiësto', 'Armin van Buuren', 'Above & Beyond']

    # Without caching
    print("\n1. Without caching:")
    start_time = time.time()
    for artist in test_artists:
        await simulate_api_call(artist, delay=0.5)
    no_cache_time = time.time() - start_time
    print(f"   ⏱️  Total time: {no_cache_time:.2f}s")

    # With caching - first run (cache misses)
    print("\n2. With caching - first run (cache misses):")
    start_time = time.time()
    for artist in test_artists:
        data = await cache.get('demo', artist, 'performance_test')
        if data is None:
            data = await simulate_api_call(artist, delay=0.5)
            await cache.put('demo', artist, 'performance_test', data)
    first_cache_time = time.time() - start_time
    print(f"   ⏱️  Total time: {first_cache_time:.2f}s")

    # With caching - second run (cache hits)
    print("\n3. With caching - second run (cache hits):")
    start_time = time.time()
    for artist in test_artists:
        data = await cache.get('demo', artist, 'performance_test')
        if data is None:
            data = await simulate_api_call(artist, delay=0.5)
            await cache.put('demo', artist, 'performance_test', data)
    second_cache_time = time.time() - start_time
    print(f"   ⏱️  Total time: {second_cache_time:.2f}s")

    # Performance summary
    speedup = no_cache_time / second_cache_time if second_cache_time > 0 else 0
    print(f"\n📈 Performance improvement: {speedup:.1f}x faster with cache")


async def main():
    """Run all demos."""
    print("🚀 API Response Caching Demo")
    print("=" * 50)

    try:
        await demo_basic_caching()
        await demo_cached_fetch()
        await demo_cache_stats()
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


if __name__ == '__main__':
    asyncio.run(main())
