#!/usr/bin/env python3
"""
Caching Decorator for Artist API Calls

Provides decorators to easily add caching to artist metadata API functions.
"""

import asyncio
import functools
import logging
import typing as t

from nowplaying.apicache import get_cache


def cache_api_response(provider: str,
                       endpoint: str,
                       ttl_seconds: t.Optional[int] = None,
                       artist_key: str = 'artist',
                       cache_empty: bool = False):
    """Decorator to add caching to API response functions.

    Args:
        provider: API provider name (e.g., 'discogs', 'theaudiodb')
        endpoint: API endpoint or operation identifier
        ttl_seconds: Cache TTL in seconds. If None, uses provider default.
        artist_key: Key in function kwargs that contains the artist name
        cache_empty: Whether to cache empty/None responses

    Usage:
        @cache_api_response('discogs', 'artist_info', ttl_seconds=3600)
        async def fetch_artist_info(artist, session):
            # Your API call here
            return api_response

        # Or for sync functions (they'll be wrapped in async):
        @cache_api_response('theaudiodb', 'artist_bio')
        def fetch_artist_bio(artist):
            # Your API call here
            return api_response
    """

    def decorator(func):

        def _extract_artist_name(args, kwargs):
            """Extract artist name from function arguments."""
            # Try to get artist from kwargs first
            if artist_key in kwargs:
                return kwargs[artist_key]

            # Fall back to positional arguments
            if not args:
                return None

            # Common patterns: first arg is often artist name or metadata dict
            if isinstance(args[0], str):
                return args[0]
            if isinstance(args[0], dict) and 'artist' in args[0]:
                return args[0]['artist']
            if len(args) > 1 and isinstance(args[1], str):
                return args[1]

            return None

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            artist_name = _extract_artist_name(args, kwargs)

            if not artist_name:
                logging.warning("Could not extract artist name for caching in %s", func.__name__)
                # Fall back to calling original function
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                return func(*args, **kwargs)

            cache = get_cache()

            # Try to get from cache first
            cached_result = await cache.get(provider, artist_name, endpoint)
            if cached_result is not None:
                return cached_result

            # Cache miss - call original function
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                # Cache the result if it's not empty or if we're caching empty results
                if result is not None or cache_empty:
                    await cache.put(provider, artist_name, endpoint, result, ttl_seconds)

                return result

            except Exception as error:
                logging.error("Error in cached function %s: %s", func.__name__, error)
                raise

        # For sync functions, we need to handle them specially
        if asyncio.iscoroutinefunction(func):
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For sync functions, we need to run in an event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're already in an async context, schedule as task
                    return asyncio.create_task(async_wrapper(*args, **kwargs))
                # No loop running, run directly
                return loop.run_until_complete(async_wrapper(*args, **kwargs))
            except RuntimeError:
                # No event loop, create one
                return asyncio.run(async_wrapper(*args, **kwargs))

        return sync_wrapper

    return decorator


def cache_artist_data(provider: str, ttl_seconds: t.Optional[int] = None):
    """Simplified decorator for artist data fetching functions.

    Assumes the function takes artist name as first parameter and returns
    artist data dictionary.

    Args:
        provider: API provider name
        ttl_seconds: Cache TTL in seconds

    Usage:
        @cache_artist_data('discogs', ttl_seconds=3600)
        def get_artist_info(artist_name):
            return {'bio': '...', 'genres': [...]}
    """
    return cache_api_response(provider, 'artist_data', ttl_seconds, artist_key='artist_name')


async def cached_fetch(provider: str,
                       artist_name: str,
                       endpoint: str,
                       fetch_func: t.Callable[[], t.Awaitable[dict]],
                       ttl_seconds: t.Optional[int] = None) -> t.Optional[dict]:
    """Utility function for manual cache-or-fetch operations.

    Args:
        provider: API provider name
        artist_name: Artist name being queried
        endpoint: API endpoint identifier
        fetch_func: Async function to call on cache miss
        ttl_seconds: Cache TTL in seconds

    Returns:
        Cached or fresh data

    Usage:
        async def fetch_data():
            return await some_api_call()

        data = await cached_fetch('discogs', 'Artist Name', 'bio', fetch_data)
    """
    cache = get_cache()

    # Try cache first
    cached_data = await cache.get(provider, artist_name, endpoint)
    if cached_data is not None:
        return cached_data

    # Cache miss - fetch fresh data
    try:
        fresh_data = await fetch_func()
        if fresh_data is not None:
            await cache.put(provider, artist_name, endpoint, fresh_data, ttl_seconds)
        return fresh_data
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.error("Error fetching data for %s:%s:%s - %s", provider, artist_name, endpoint,
                      error)
        return None


def make_cache_key(provider: str, artist_name: str, endpoint: str) -> str:
    """Generate a cache key for manual cache operations.

    Args:
        provider: API provider name
        artist_name: Artist name
        endpoint: API endpoint identifier

    Returns:
        Cache key string
    """
    cache = get_cache()
    return cache._make_cache_key(provider, artist_name, endpoint)  # pylint: disable=protected-access


async def invalidate_artist_cache(artist_name: str, provider: t.Optional[str] = None):
    """Invalidate cached data for a specific artist.

    Args:
        artist_name: Artist name to invalidate
        provider: If specified, only invalidate for this provider
    """
    # This would require extending the APIResponseCache class to support
    # artist-specific invalidation. For now, log the request.
    logging.info("Cache invalidation requested for artist: %s, provider: %s", artist_name, provider
                 or "all")
    # TODO: Implement artist-specific cache invalidation
