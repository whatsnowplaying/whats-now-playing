#!/usr/bin/env python3
"""
Async MusicBrainz client optimized for nowplaying usage.
Replaces the vendored musicbrainzngs library with only the methods actually used.
"""

import asyncio
import io
import logging
import ssl
import time
from typing import Any
import xml.etree.ElementTree as etree

import aiohttp

# Import the XML parser from the vendored library since it's already available
from nowplaying.vendor.musicbrainzngs import mbxml

logger = logging.getLogger(__name__)

# MusicBrainz API configuration
_BASE_URL = "https://musicbrainz.org/ws/2"
_CAA_BASE_URL = "https://coverartarchive.org"
_USER_AGENT = "whats-now-playing/1.0"
_MAX_RETRIES = 2
_TIMEOUT = 15
_RATE_LIMIT_INTERVAL = 0.5  # seconds between requests
_LAST_REQUEST_TIME = 0
_rate_limit_lock = asyncio.Lock()


class MusicBrainzError(Exception):
    """Base exception for MusicBrainz API errors"""


class NetworkError(MusicBrainzError):
    """Network-related errors"""


class ResponseError(MusicBrainzError):
    """API response errors"""


def set_rate_limit(limit_or_interval: float = 0.5):
    """Set the rate limit interval between requests"""
    global _RATE_LIMIT_INTERVAL
    _RATE_LIMIT_INTERVAL = limit_or_interval


def set_useragent(app_name: str, app_version: str, contact: str):
    """Set the user agent string"""
    global _USER_AGENT
    _USER_AGENT = f"{app_name}/{app_version} ({contact})"


async def _rate_limit():
    """Enforce rate limiting between requests"""
    global _LAST_REQUEST_TIME
    async with _rate_limit_lock:
        now = time.time()
        time_since_last = now - _LAST_REQUEST_TIME
        if time_since_last < _RATE_LIMIT_INTERVAL:
            await asyncio.sleep(_RATE_LIMIT_INTERVAL - time_since_last)
        _LAST_REQUEST_TIME = time.time()


async def _make_request(url: str,
                        params: dict | None = None,
                        timeout: int | None = None) -> dict[str, Any]:
    """Make an async HTTP request to MusicBrainz API with rate limiting"""
    await _rate_limit()

    if timeout is None:
        timeout = _TIMEOUT

    # Create SSL context with proper certificate verification
    ssl_context = ssl.create_default_context()

    headers = {'User-Agent': _USER_AGENT, 'Accept': 'application/xml'}

    timeout_config = aiohttp.ClientTimeout(total=timeout)

    for attempt in range(_MAX_RETRIES + 1):
        try:
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector,
                                             timeout=timeout_config,
                                             headers=headers) as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        content = await response.text()
                        try:
                            # Parse XML response using the existing mbxml parser
                            # mbxml.parse_message expects a file-like object
                            return mbxml.parse_message(io.StringIO(content))
                        except etree.ParseError as parse_error:
                            raise ResponseError(
                                f"Invalid XML response: {parse_error}") from parse_error
                    elif response.status == 404:
                        return {}  # Not found - return empty dict
                    elif response.status == 503:
                        if attempt < _MAX_RETRIES:
                            # Service unavailable - wait and retry
                            wait_time = 2**attempt
                            logger.debug("MusicBrainz 503 error, retrying in %ss", wait_time)
                            await asyncio.sleep(wait_time)
                            continue
                        raise NetworkError("MusicBrainz service unavailable (503)")
                    else:
                        raise ResponseError(f"HTTP {response.status}: {await response.text()}")

        except asyncio.TimeoutError:
            if attempt < _MAX_RETRIES:
                logger.debug("Request timeout, retrying (attempt %d)", attempt + 1)
                continue
            raise NetworkError(f"Request timeout after {_MAX_RETRIES} retries") from None
        except aiohttp.ClientConnectorCertificateError as cert_error:
            raise NetworkError(f"SSL certificate verification failed: {cert_error}") from cert_error  # pylint: disable=bad-exception-cause
        except aiohttp.ClientError as client_error:
            if attempt < _MAX_RETRIES:
                logger.debug("Client error: %s, retrying (attempt %d)", client_error, attempt + 1)
                continue
            raise NetworkError(f"Request failed: {client_error}") from client_error

    raise NetworkError(f"Failed after {_MAX_RETRIES} retries")


async def _make_image_request(url: str, timeout: int | None = None) -> bytes:
    """Make a request for binary image data"""
    await _rate_limit()

    if timeout is None:
        timeout = _TIMEOUT

    ssl_context = ssl.create_default_context()
    timeout_config = aiohttp.ClientTimeout(total=timeout)

    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout_config) as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.read()
            raise ResponseError(f"HTTP {response.status}: {await response.text()}")


# MusicBrainz API Methods (only the ones actually used by nowplaying)


async def search_recordings(**kwargs) -> dict[str, Any]:
    """Search for recordings"""
    params = {}
    if 'query' in kwargs:
        params['query'] = kwargs['query']
    else:
        query_parts = []
        if 'artist' in kwargs:
            query_parts.append(f'artist:"{kwargs["artist"]}"')
        if 'recording' in kwargs:
            query_parts.append(f'recording:"{kwargs["recording"]}"')
        if 'release' in kwargs:
            query_parts.append(f'release:"{kwargs["release"]}"')
        params['query'] = ' AND '.join(query_parts)

    if 'limit' in kwargs:
        params['limit'] = kwargs['limit']
    if 'offset' in kwargs:
        params['offset'] = kwargs['offset']

    url = f"{_BASE_URL}/recording"
    return await _make_request(url, params)


async def get_recording_by_id(recording_id: str,
                              includes: list[str] | None = None) -> dict[str, Any]:
    """Get recording by MBID"""
    params = {}
    if includes:
        params['inc'] = '+'.join(includes)

    url = f"{_BASE_URL}/recording/{recording_id}"
    return await _make_request(url, params)


async def get_recordings_by_isrc(isrc: str,
                                 includes: list[str] | None = None,
                                 release_status: list[str] | None = None) -> dict[str, Any]:
    """Get recordings by ISRC"""
    params = {'query': f'isrc:{isrc}'}
    if includes:
        params['inc'] = '+'.join(includes)
    if release_status:
        params['status'] = '|'.join(release_status)

    url = f"{_BASE_URL}/isrc/{isrc}"
    return await _make_request(url, params)


async def browse_releases(recording: str,
                          includes: list[str] | None = None,
                          limit: int | None = None,
                          offset: int | None = None,
                          release_status: list[str] | None = None) -> dict[str, Any]:
    """Browse releases by recording"""
    params = {'recording': recording}
    if includes:
        params['inc'] = '+'.join(includes)
    if limit:
        params['limit'] = str(limit)
    if offset:
        params['offset'] = str(offset)
    if release_status:
        params['status'] = '|'.join(release_status)

    url = f"{_BASE_URL}/release"
    return await _make_request(url, params)


async def get_artist_by_id(artist_id: str, includes: list[str] | None = None) -> dict[str, Any]:
    """Get artist by MBID"""
    params = {}
    if includes:
        params['inc'] = '+'.join(includes)

    url = f"{_BASE_URL}/artist/{artist_id}"
    return await _make_request(url, params)


async def search_releases(**kwargs) -> dict[str, Any]:
    """Search for releases"""
    params = {}
    if 'query' in kwargs:
        params['query'] = kwargs['query']
    else:
        query_parts = []
        if 'artist' in kwargs:
            query_parts.append(f'artist:"{kwargs["artist"]}"')
        if 'release' in kwargs:
            query_parts.append(f'release:"{kwargs["release"]}"')
        params['query'] = ' AND '.join(query_parts)

    if 'limit' in kwargs:
        params['limit'] = kwargs['limit']
    if 'offset' in kwargs:
        params['offset'] = kwargs['offset']

    url = f"{_BASE_URL}/release"
    return await _make_request(url, params)


async def get_release_by_id(release_id: str, includes: list[str] | None = None) -> dict[str, Any]:
    """Get release by MBID"""
    params = {}
    if includes:
        params['inc'] = '+'.join(includes)

    url = f"{_BASE_URL}/release/{release_id}"
    return await _make_request(url, params)


async def search_release_groups(**kwargs) -> dict[str, Any]:
    """Search for release groups"""
    params = {}
    if 'query' in kwargs:
        params['query'] = kwargs['query']
    else:
        query_parts = []
        if 'artist' in kwargs:
            query_parts.append(f'artist:"{kwargs["artist"]}"')
        if 'releasegroup' in kwargs:
            query_parts.append(f'releasegroup:"{kwargs["releasegroup"]}"')
        params['query'] = ' AND '.join(query_parts)

    if 'limit' in kwargs:
        params['limit'] = kwargs['limit']
    if 'offset' in kwargs:
        params['offset'] = kwargs['offset']

    url = f"{_BASE_URL}/release-group"
    return await _make_request(url, params)


async def get_release_group_by_id(rg_id: str, includes: list[str] | None = None) -> dict[str, Any]:
    """Get release group by MBID"""
    params = {}
    if includes:
        params['inc'] = '+'.join(includes)

    url = f"{_BASE_URL}/release-group/{rg_id}"
    return await _make_request(url, params)


# Cover Art Archive functions


async def get_image_list(mbid: str, entity_type: str = 'release') -> dict[str, Any]:
    """Get cover art image list for a release or release group"""
    url = f"{_CAA_BASE_URL}/{entity_type}/{mbid}"
    try:
        return await _make_request(url)
    except ResponseError as response_error:
        if "404" in str(response_error):
            return {}  # No cover art available
        raise


async def get_image_front(mbid: str, entity_type: str = 'release', size: str = '500') -> bytes:
    """Get front cover art image"""
    url = f"{_CAA_BASE_URL}/{entity_type}/{mbid}/front-{size}"
    return await _make_image_request(url)


async def get_image_back(mbid: str, entity_type: str = 'release', size: str = '500') -> bytes:
    """Get back cover art image"""
    url = f"{_CAA_BASE_URL}/{entity_type}/{mbid}/back-{size}"
    return await _make_image_request(url)
