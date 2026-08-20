"""
Rate limiting for datacache module.

The queue functionality has been moved to database-backed storage in storage.py.
This module now only contains rate limiting utilities.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field


class RateLimiter:
    """
    Per-provider rate limiting for API requests.

    Implements token bucket algorithm with configurable rates.
    """

    def __init__(self, provider: str, requests_per_second: float = 1.0):
        self.provider = provider
        self.rate = requests_per_second
        self.capacity = max(1.0, requests_per_second * 2)  # Burst capacity
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, timeout: float = 30.0) -> bool:
        """
        Acquire a token for API request.

        Args:
            timeout: Maximum time to wait for token

        Returns:
            True if token acquired, False if timeout
        """
        start_time = time.monotonic()

        while time.monotonic() - start_time < timeout:
            async with self._lock:
                self._refill_tokens()

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    logging.debug(
                        "Rate limit token acquired for %s (%.1f remaining)",
                        self.provider,
                        self.tokens,
                    )
                    return True

            # Wait before retry
            await asyncio.sleep(0.1)

        logging.warning("Rate limit timeout for provider %s", self.provider)
        return False

    def _refill_tokens(self) -> None:
        """Refill token bucket based on elapsed time"""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.last_refill = now

        # Add tokens based on rate and elapsed time
        tokens_to_add = elapsed * self.rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)

    def available_tokens(self) -> float:
        """Get current number of available tokens"""
        self._refill_tokens()
        return self.tokens

    def time_until_token(self) -> float:
        """Get estimated time until next token is available"""
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.rate


class BandwidthLimiter:
    """Shared byte-rate limit for downloads.

    Same token bucket as RateLimiter, with bytes as the unit instead of requests,
    and one instance for the whole client rather than one per provider: the budget
    models the operator's connection, not a service's politeness rules.

    Metered per streamed chunk rather than per file, so a large download is paced
    as it arrives instead of being paid for afterwards, and Content-Length -- a
    header we would have to take on trust -- never comes into it.

    A limit of 0 disables throttling entirely.  Turning downloads off altogether
    is what disabling artist extras is for.
    """

    def __init__(self, kb_per_second: float = 0.0):
        self.rate = max(0.0, kb_per_second) * 1024
        # One second of burst, so a single 64 KB chunk never deadlocks on a
        # limit smaller than itself.
        self.capacity = max(self.rate, 65536.0)
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        """True when a limit is in force."""
        return self.rate > 0

    def _refill(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.last_refill) * self.rate)
        self.last_refill = now

    async def consume(self, nbytes: int, wait: bool = True) -> None:
        """Account for nbytes, sleeping until the budget allows it.

        wait=False accounts without blocking, for fetches on the live path: a
        track's cover art must never stall behind background artwork, but it still
        spends from the same budget so background work backs off to compensate.
        """
        if not self.enabled or nbytes <= 0:
            return
        while True:
            async with self._lock:
                self._refill()
                if not wait or self.tokens >= nbytes:
                    self.tokens -= nbytes
                    return
                deficit = nbytes - self.tokens
                delay = deficit / self.rate
            await asyncio.sleep(min(delay, 1.0))


@dataclass
class RateLimiterManager:
    """Manages rate limiters for different providers"""

    rate_limiters: dict[str, RateLimiter] = field(default_factory=dict)
    _default_rates: dict[str, float] = field(
        default_factory=lambda: {
            "musicbrainz": 1.0,  # MusicBrainz: 1 req/sec
            "discogs": 2.0,  # Discogs: ~60 req/min authenticated
            "fanarttv": 0.5,  # FanartTV API: 30 req/min
            "theaudiodb": 0.5,  # TheAudioDB API: 30 req/min
            "lastfm": 5.0,  # Last.fm: ~300 req/min
            "cdn": 10.0,  # CDN image downloads: no meaningful limit
            "wikimedia": 10.0,  # Wikimedia: generous
            "images": 5.0,  # Image fetches: internal
        }
    )

    def get_limiter(self, provider: str) -> RateLimiter:
        """Get or create rate limiter for provider"""
        if provider not in self.rate_limiters:
            rate = self._default_rates.get(provider, 1.0)
            self.rate_limiters[provider] = RateLimiter(provider, rate)
        return self.rate_limiters[provider]


# Global rate limiter manager instance
_rate_limiter_manager: RateLimiterManager | None = None  # pylint: disable=invalid-name


def get_rate_limiter_manager() -> RateLimiterManager:
    """Get global rate limiter manager instance"""
    global _rate_limiter_manager  # pylint: disable=global-statement
    if _rate_limiter_manager is None:
        _rate_limiter_manager = RateLimiterManager()
    return _rate_limiter_manager
