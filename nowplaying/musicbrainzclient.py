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
from typing import Optional, Dict, Any, List
import xml.etree.ElementTree as etree

import aiohttp

# Import the XML parser from the vendored library since it's already available
from nowplaying.vendor.musicbrainzngs import mbxml

logger = logging.getLogger(__name__)

# MusicBrainz API configuration
_base_url = "https://musicbrainz.org/ws/2"
_caa_base_url = "https://coverartarchive.org"
_user_agent = "whats-now-playing/1.0"
_max_retries = 2
_timeout = 15
_rate_limit_interval = 0.5  # seconds between requests
_last_request_time = 0
_rate_limit_lock = asyncio.Lock()


class MusicBrainzError(Exception):
    """Base exception for MusicBrainz API errors"""


class NetworkError(MusicBrainzError):
    """Network-related errors"""


class ResponseError(MusicBrainzError):
    """API response errors"""


def set_rate_limit(limit_or_interval: float = 0.5):
    """Set the rate limit interval between requests"""
    global _rate_limit_interval
    _rate_limit_interval = limit_or_interval


def set_useragent(app_name: str, app_version: str, contact: str):
    """Set the user agent string"""
    global _user_agent
    _user_agent = f"{app_name}/{app_version} ({contact})"


async def _rate_limit():
    """Enforce rate limiting between requests"""
    global _last_request_time
    async with _rate_limit_lock:
        now = time.time()
        time_since_last = now - _last_request_time
        if time_since_last < _rate_limit_interval:
            await asyncio.sleep(_rate_limit_interval - time_since_last)
        _last_request_time = time.time()


async def _make_request(url: str,
                        params: Optional[Dict] = None,
                        timeout: Optional[int] = None) -> Dict[str, Any]:
    """Make an async HTTP request to MusicBrainz API with rate limiting"""
    await _rate_limit()

    if timeout is None:
        timeout = _timeout

    # Create SSL context with proper certificate verification
    ssl_context = ssl.create_default_context()

    headers = {'User-Agent': _user_agent, 'Accept': 'application/xml'}

    timeout_config = aiohttp.ClientTimeout(total=timeout)

    for attempt in range(_max_retries + 1):
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
                        except etree.ParseError as e:
                            raise ResponseError(f"Invalid XML response: {e}") from e
                    elif response.status == 404:
                        return {}  # Not found - return empty dict
                    elif response.status == 503:
                        if attempt < _max_retries:
                            # Service unavailable - wait and retry
                            wait_time = 2**attempt
                            logger.debug("MusicBrainz 503 error, retrying in %ss", wait_time)
                            await asyncio.sleep(wait_time)
                            continue
                        raise NetworkError("MusicBrainz service unavailable (503)")
                    else:
                        raise ResponseError(f"HTTP {response.status}: {await response.text()}")

        except asyncio.TimeoutError:
            if attempt < _max_retries:
                logger.debug("Request timeout, retrying (attempt %d)", attempt + 1)
                continue
            raise NetworkError(f"Request timeout after {_max_retries} retries") from None
        except aiohttp.ClientConnectorCertificateError as e:
            raise NetworkError(f"SSL certificate verification failed: {e}") from e
        except aiohttp.ClientError as e:
            if attempt < _max_retries:
                logger.debug("Client error: %s, retrying (attempt %d)", e, attempt + 1)
                continue
            raise NetworkError(f"Request failed: {e}") from e

    raise NetworkError(f"Failed after {_max_retries} retries")


async def _make_image_request(url: str, timeout: Optional[int] = None) -> bytes:
    """Make a request for binary image data"""
    await _rate_limit()

    if timeout is None:
        timeout = _timeout

    ssl_context = ssl.create_default_context()
    timeout_config = aiohttp.ClientTimeout(total=timeout)

    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout_config) as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.read()
            raise ResponseError(f"HTTP {response.status}: {await response.text()}")


# MusicBrainz API Methods (only the ones actually used by nowplaying)


async def search_recordings(**kwargs) -> Dict[str, Any]:
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

    url = f"{_base_url}/recording"
    return await _make_request(url, params)


async def get_recording_by_id(recording_id: str,
                              includes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Get recording by MBID"""
    params = {}
    if includes:
        params['inc'] = '+'.join(includes)

    url = f"{_base_url}/recording/{recording_id}"
    return await _make_request(url, params)


async def get_recordings_by_isrc(isrc: str,
                                 includes: Optional[List[str]] = None,
                                 release_status: Optional[List[str]] = None) -> Dict[str, Any]:
    """Get recordings by ISRC"""
    params = {'query': f'isrc:{isrc}'}
    if includes:
        params['inc'] = '+'.join(includes)
    if release_status:
        params['status'] = '|'.join(release_status)

    url = f"{_base_url}/isrc/{isrc}"
    return await _make_request(url, params)


async def browse_releases(recording: str,
                          includes: Optional[List[str]] = None,
                          limit: Optional[int] = None,
                          offset: Optional[int] = None,
                          release_status: Optional[List[str]] = None) -> Dict[str, Any]:
    """Browse releases by recording"""
    params = {'recording': recording}
    if includes:
        params['inc'] = '+'.join(includes)
    if limit:
        params['limit'] = limit
    if offset:
        params['offset'] = offset
    if release_status:
        params['status'] = '|'.join(release_status)

    url = f"{_base_url}/release"
    return await _make_request(url, params)


async def get_artist_by_id(artist_id: str, includes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Get artist by MBID"""
    params = {}
    if includes:
        params['inc'] = '+'.join(includes)

    url = f"{_base_url}/artist/{artist_id}"
    return await _make_request(url, params)


async def search_releases(**kwargs) -> Dict[str, Any]:
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

    url = f"{_base_url}/release"
    return await _make_request(url, params)


async def get_release_by_id(release_id: str,
                            includes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Get release by MBID"""
    params = {}
    if includes:
        params['inc'] = '+'.join(includes)

    url = f"{_base_url}/release/{release_id}"
    return await _make_request(url, params)


async def search_release_groups(**kwargs) -> Dict[str, Any]:
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

    url = f"{_base_url}/release-group"
    return await _make_request(url, params)


async def get_release_group_by_id(rg_id: str,
                                  includes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Get release group by MBID"""
    params = {}
    if includes:
        params['inc'] = '+'.join(includes)

    url = f"{_base_url}/release-group/{rg_id}"
    return await _make_request(url, params)


# Cover Art Archive functions


async def get_image_list(mbid: str, entity_type: str = 'release') -> Dict[str, Any]:
    """Get cover art image list for a release or release group"""
    url = f"{_caa_base_url}/{entity_type}/{mbid}"
    try:
        return await _make_request(url)
    except ResponseError as e:
        if "404" in str(e):
            return {}  # No cover art available
        raise


async def get_image_front(mbid: str, entity_type: str = 'release', size: str = '500') -> bytes:
    """Get front cover art image"""
    url = f"{_caa_base_url}/{entity_type}/{mbid}/front-{size}"
    return await _make_image_request(url)


async def get_image_back(mbid: str, entity_type: str = 'release', size: str = '500') -> bytes:
    """Get back cover art image"""
    url = f"{_caa_base_url}/{entity_type}/{mbid}/back-{size}"
    return await _make_image_request(url)
