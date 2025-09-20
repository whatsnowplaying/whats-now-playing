"""
Rate limiting for datacache module.

The queue functionality has been moved to database-backed storage in storage.py.
This module now only contains rate limiting utilities.
"""

import asyncio
import logging
import time


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
        self.last_refill = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self, timeout: float = 30.0) -> bool:
        """
        Acquire a token for API request.

        Args:
            timeout: Maximum time to wait for token

        Returns:
            True if token acquired, False if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
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
        now = time.time()
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


class RateLimiterManager:
    """Manages rate limiters for different providers"""

    def __init__(self):
        self.rate_limiters: dict[str, RateLimiter] = {}
        self._default_rates = {
            "musicbrainz": 1.0,  # 1 request per second
            "discogs": 2.0,  # 2 requests per second
            "fanarttv": 2.0,  # 2 requests per second
            "theaudiodb": 1.0,  # 1 request per second
            "wikimedia": 10.0,  # 10 requests per second
            "images": 5.0,  # 5 requests per second
        }

    def get_limiter(self, provider: str) -> RateLimiter:
        """Get or create rate limiter for provider"""
        if provider not in self.rate_limiters:
            rate = self._default_rates.get(provider, 1.0)
            self.rate_limiters[provider] = RateLimiter(provider, rate)
        return self.rate_limiters[provider]


# Global rate limiter manager instance
_rate_limiter_manager: RateLimiterManager | None = None


def get_rate_limiter_manager() -> RateLimiterManager:
    """Get global rate limiter manager instance"""
    global _rate_limiter_manager
    if _rate_limiter_manager is None:
        _rate_limiter_manager = RateLimiterManager()
    return _rate_limiter_manager
