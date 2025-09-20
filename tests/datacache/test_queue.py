"""
Unit tests for datacache queue and rate limiting.

Tests the rate limiting functionality and queue management.
"""

import asyncio
import time

import pytest

import nowplaying.datacache.queue


@pytest.mark.asyncio
async def test_rate_limiter_basic_functionality():
    """Test basic rate limiter token acquisition"""
    limiter = nowplaying.datacache.queue.RateLimiter("test", requests_per_second=2.0)

    # Should have tokens available initially
    assert limiter.available_tokens() > 0

    # Should be able to acquire token immediately
    success = await limiter.acquire(timeout=1.0)
    assert success is True

    # Should have fewer tokens after acquisition
    assert limiter.available_tokens() < limiter.capacity


@pytest.mark.asyncio
async def test_rate_limiter_token_refill():
    """Test that tokens refill over time"""
    limiter = nowplaying.datacache.queue.RateLimiter("test", requests_per_second=10.0)

    # Exhaust tokens quickly by consuming the exact capacity
    initial_tokens = limiter.available_tokens()
    capacity = int(limiter.capacity)

    # Exhaust all tokens at once to avoid refill during loop
    for _ in range(capacity):
        success = await limiter.acquire(timeout=0.01)  # Very short timeout
        if not success:
            break

    # Should have very few tokens left (allow for some refill during acquire calls)
    remaining = limiter.available_tokens()
    assert remaining < initial_tokens / 2  # Should be significantly depleted

    # Wait for substantial refill
    await asyncio.sleep(0.3)  # 300ms should allow ~3 tokens at 10/sec

    # Should have significantly more tokens now
    refilled_tokens = limiter.available_tokens()
    assert refilled_tokens > remaining + 1.0  # Should have gained at least 1 token


@pytest.mark.asyncio
async def test_rate_limiter_timeout():
    """Test rate limiter timeout when no tokens available"""
    limiter = nowplaying.datacache.queue.RateLimiter("test", requests_per_second=1.0)

    # Exhaust tokens
    limiter.tokens = 0.0

    # Should timeout quickly
    start_time = time.time()
    success = await limiter.acquire(timeout=0.1)
    elapsed = time.time() - start_time

    assert success is False
    assert elapsed >= 0.1  # Should have waited at least timeout duration
    assert elapsed < 0.2  # But not much longer


@pytest.mark.asyncio
async def test_rate_limiter_capacity_limit():
    """Test that tokens don't exceed capacity"""
    limiter = nowplaying.datacache.queue.RateLimiter("test", requests_per_second=1.0)

    # Wait longer than needed to fill capacity
    await asyncio.sleep(0.5)
    limiter._refill_tokens()

    # Should not exceed capacity
    assert limiter.available_tokens() <= limiter.capacity


def test_rate_limiter_time_until_token():
    """Test time estimation for next token"""
    limiter = nowplaying.datacache.queue.RateLimiter("test", requests_per_second=2.0)

    # With tokens available, should be immediate
    limiter.tokens = 5.0
    assert limiter.time_until_token() == 0.0

    # With no tokens, should estimate based on rate
    limiter.tokens = 0.0
    time_estimate = limiter.time_until_token()
    expected_time = 1.0 / 2.0  # 1 token / 2 tokens per second = 0.5 seconds
    assert abs(time_estimate - expected_time) < 0.01


def test_rate_limiter_manager_get_limiter():
    """Test rate limiter manager creates and reuses limiters"""
    manager = nowplaying.datacache.queue.RateLimiterManager()

    # Should create new limiter
    limiter1 = manager.get_limiter("test_provider")
    assert limiter1.provider == "test_provider"

    # Should reuse existing limiter
    limiter2 = manager.get_limiter("test_provider")
    assert limiter1 is limiter2

    # Different provider should get different limiter
    limiter3 = manager.get_limiter("other_provider")
    assert limiter3 is not limiter1


def test_rate_limiter_manager_default_rates():
    """Test that manager uses correct default rates for known providers"""
    manager = nowplaying.datacache.queue.RateLimiterManager()

    # Test known provider rates
    mb_limiter = manager.get_limiter("musicbrainz")
    assert mb_limiter.rate == 1.0  # 1 req/sec for MusicBrainz

    discogs_limiter = manager.get_limiter("discogs")
    assert discogs_limiter.rate == 2.0  # 2 req/sec for Discogs

    fanarttv_limiter = manager.get_limiter("fanarttv")
    assert fanarttv_limiter.rate == 2.0  # 2 req/sec for FanartTV

    theaudiodb_limiter = manager.get_limiter("theaudiodb")
    assert theaudiodb_limiter.rate == 1.0  # 1 req/sec for TheAudioDB

    wikimedia_limiter = manager.get_limiter("wikimedia")
    assert wikimedia_limiter.rate == 10.0  # 10 req/sec for Wikimedia

    # Unknown provider should get default
    unknown_limiter = manager.get_limiter("unknown_provider")
    assert unknown_limiter.rate == 1.0  # Default rate


def test_get_rate_limiter_manager_singleton():
    """Test rate limiter manager singleton behavior"""
    manager1 = nowplaying.datacache.queue.get_rate_limiter_manager()
    manager2 = nowplaying.datacache.queue.get_rate_limiter_manager()

    assert manager1 is manager2


@pytest.mark.asyncio
async def test_rate_limiter_concurrent_access():
    """Test rate limiter with concurrent requests"""
    limiter = nowplaying.datacache.queue.RateLimiter("concurrent", requests_per_second=5.0)

    # Create multiple concurrent acquisition tasks
    async def acquire_token():
        return await limiter.acquire(timeout=1.0)

    # Start many concurrent tasks
    tasks = [acquire_token() for _ in range(10)]
    results = await asyncio.gather(*tasks)

    # Most should succeed (some may timeout due to rate limiting)
    successful = sum(1 for result in results if result)
    assert successful >= 3  # At least a few should succeed
    assert successful <= 10  # Not all may succeed due to rate limiting


@pytest.mark.asyncio
async def test_rate_limiter_realistic_musicbrainz_scenario():
    """Test rate limiter with realistic MusicBrainz usage pattern"""
    limiter = nowplaying.datacache.queue.RateLimiter("musicbrainz", requests_per_second=1.0)

    # Simulate making several requests over time
    request_times = []

    for i in range(3):
        start_time = time.time()
        success = await limiter.acquire(timeout=5.0)
        end_time = time.time()

        assert success is True
        request_times.append(end_time - start_time)

        # Don't sleep after last request
        if i < 2:
            await asyncio.sleep(0.1)  # Small gap between requests

    # First request should be immediate
    assert request_times[0] < 0.1

    # Subsequent requests may have had to wait
    # (depending on token availability and timing)


@pytest.mark.asyncio
async def test_rate_limiter_burst_capacity():
    """Test that burst capacity allows multiple immediate requests"""
    limiter = nowplaying.datacache.queue.RateLimiter("burst", requests_per_second=1.0)

    # Limiter should allow burst up to capacity
    # (capacity = max(1.0, rate * 2) = 2.0 for 1.0 req/sec)

    # Should be able to make 2 requests immediately
    success1 = await limiter.acquire(timeout=0.1)
    success2 = await limiter.acquire(timeout=0.1)

    assert success1 is True
    assert success2 is True

    # Third request should timeout (no tokens left)
    success3 = await limiter.acquire(timeout=0.1)
    assert success3 is False


@pytest.mark.asyncio
async def test_rate_limiter_different_providers_independent():
    """Test that different providers have independent rate limits"""
    manager = nowplaying.datacache.queue.RateLimiterManager()

    mb_limiter = manager.get_limiter("musicbrainz")
    discogs_limiter = manager.get_limiter("discogs")

    # Exhaust MusicBrainz tokens
    while mb_limiter.available_tokens() >= 1.0:
        await mb_limiter.acquire(timeout=0.1)

    # Discogs should still have tokens
    assert discogs_limiter.available_tokens() >= 1.0

    # Should be able to acquire from Discogs
    success = await discogs_limiter.acquire(timeout=0.1)
    assert success is True
