#!/usr/bin/env python3
"""
Async MusicBrainz client optimized for nowplaying usage.
Replaces the vendored musicbrainzngs library with only the methods actually used.
"""

import asyncio
import logging
import ssl
import time
from typing import Any

import aiohttp

import nowplaying.utils
from nowplaying.vendor.musicbrainzngs import mbxml

logger = logging.getLogger(__name__)


class MusicBrainzError(Exception):
    """Base exception for MusicBrainz API errors"""


class NetworkError(MusicBrainzError):
    """Network-related errors"""


class ResponseError(MusicBrainzError):
    """API response errors"""


class MusicBrainzClient:  # pylint: disable=too-many-instance-attributes
    """Async MusicBrainz API client with rate limiting and error handling"""

    def __init__(
        self,
        user_agent: str = "whats-now-playing/1.0",
        rate_limit_interval: float = 0.5,
        timeout: int = 15,
        max_retries: int = 2,
    ):
        self.base_url = "https://musicbrainz.org/ws/2"
        self.caa_base_url = "https://coverartarchive.org"
        self.user_agent = user_agent
        self.rate_limit_interval = rate_limit_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self.last_request_time = 0
        self.rate_limit_lock = asyncio.Lock()

    def set_rate_limit(self, limit_or_interval: float = 0.5):
        """Set the rate limit interval between requests"""
        self.rate_limit_interval = limit_or_interval

    def set_useragent(self, app_name: str, app_version: str, contact: str):
        """Set the user agent string"""
        self.user_agent = f"{app_name}/{app_version} ({contact})"

    async def _rate_limit(self):
        """Enforce rate limiting between requests"""
        async with self.rate_limit_lock:
            now = time.time()
            time_since_last = now - self.last_request_time
            if time_since_last < self.rate_limit_interval:
                await asyncio.sleep(self.rate_limit_interval - time_since_last)
            self.last_request_time = time.time()

    async def _make_request(  # pylint: disable=too-many-locals
        self,
        url: str,  # pylint: disable=too-many-branches
        params: dict | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Make an async HTTP request to MusicBrainz API with rate limiting"""
        await self._rate_limit()

        if timeout is None:
            timeout = self.timeout

        # Create SSL context with proper certificate verification
        ssl_context = ssl.create_default_context()

        headers = {"User-Agent": self.user_agent, "Accept": "application/xml"}

        timeout_config = aiohttp.ClientTimeout(total=timeout)

        for attempt in range(self.max_retries + 1):
            try:
                connector = nowplaying.utils.create_http_connector(ssl_context, "musicbrainz")
                async with aiohttp.ClientSession(
                    connector=connector, timeout=timeout_config
                ) as session:
                    async with session.get(url, params=params, headers=headers) as response:
                        if response.status == 200:
                            xml_data = await response.text()
                            # Parse XML response
                            try:
                                return mbxml.parse_message(xml_data)
                            except ValueError as parse_error:
                                raise ResponseError(
                                    f"XML parsing failed: {parse_error}"
                                ) from parse_error
                        elif response.status in (503, 502, 500):
                            # MusicBrainz uses 503/502/500 for rate limiting and server overload
                            # For live performance, we retry once with minimal delay
                            if attempt < self.max_retries:
                                logger.warning(
                                    "Server error %d (rate limit/overload), retrying (attempt %d)",
                                    response.status,
                                    attempt + 1,
                                )
                                await asyncio.sleep(0.5)  # Minimal delay for live performance
                                continue
                            raise NetworkError(
                                f"MusicBrainz server error {response.status} "
                                f"(rate limit or overload)"
                            )
                        else:
                            raise ResponseError(f"HTTP {response.status}: {await response.text()}")

            except TimeoutError as timeout_error:
                if attempt < self.max_retries:
                    logger.debug("Request timeout, retrying (attempt %d)", attempt + 1)
                    continue
                raise NetworkError(
                    f"Request timeout after {self.max_retries} retries"
                ) from timeout_error
            except aiohttp.ClientConnectorError as cert_error:
                raise NetworkError(
                    f"SSL certificate verification failed: {cert_error}"
                ) from cert_error
            except aiohttp.ClientError as client_error:
                if attempt < self.max_retries:
                    logger.debug(
                        "Client error: %s, retrying (attempt %d)", client_error, attempt + 1
                    )
                    continue
                raise NetworkError(f"Request failed: {client_error}") from client_error

        raise NetworkError(f"Failed after {self.max_retries} retries")

    async def _make_image_request(self, url: str, timeout: int | None = None) -> bytes:
        """Make a request for binary image data"""
        await self._rate_limit()

        if timeout is None:
            timeout = self.timeout

        ssl_context = ssl.create_default_context()
        timeout_config = aiohttp.ClientTimeout(total=timeout)

        connector = nowplaying.utils.create_http_connector(ssl_context, "musicbrainz")
        async with aiohttp.ClientSession(connector=connector, timeout=timeout_config) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.read()
                raise ResponseError(f"HTTP {response.status}: {await response.text()}")

    # MusicBrainz API Methods (only the ones actually used by nowplaying)

    async def search_recordings(self, **kwargs) -> dict[str, Any]:
        """Search for recordings"""
        params = {}
        if "query" in kwargs:
            params["query"] = kwargs["query"]
        else:
            query_parts = []
            if "artist" in kwargs:
                query_parts.append(f'artist:"{kwargs["artist"]}"')
            if "recording" in kwargs:
                query_parts.append(f'recording:"{kwargs["recording"]}"')
            params["query"] = " AND ".join(query_parts)

        if "limit" in kwargs:
            params["limit"] = kwargs["limit"]
        if "offset" in kwargs:
            params["offset"] = kwargs["offset"]

        url = f"{self.base_url}/recording"
        return await self._make_request(url, params)

    async def get_recording_by_id(
        self, recording_id: str, includes: list[str] | None = None
    ) -> dict[str, Any]:
        """Get recording by MBID"""
        params = {}
        if includes:
            params["inc"] = "+".join(includes)

        url = f"{self.base_url}/recording/{recording_id}"
        return await self._make_request(url, params)

    async def get_recordings_by_isrc(
        self, isrc: str, includes: list[str] | None = None, release_status: list[str] | None = None
    ) -> dict[str, Any]:
        """Get recordings by ISRC"""
        params = {"query": f"isrc:{isrc}"}
        if includes:
            params["inc"] = "+".join(includes)
        if release_status:
            params["status"] = "|".join(release_status)

        url = f"{self.base_url}/isrc/{isrc}"
        return await self._make_request(url, params)

    async def browse_releases(  # pylint: disable=too-many-arguments
        self,
        recording: str,
        includes: list[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        release_status: list[str] | None = None,
    ) -> dict[str, Any]:
        """Browse releases by recording"""
        params = {"recording": recording}
        if includes:
            params["inc"] = "+".join(includes)
        if limit:
            params["limit"] = str(limit)
        if offset:
            params["offset"] = str(offset)
        if release_status:
            params["status"] = "|".join(release_status)

        url = f"{self.base_url}/release"
        return await self._make_request(url, params)

    async def get_artist_by_id(
        self, artist_id: str, includes: list[str] | None = None
    ) -> dict[str, Any]:
        """Get artist by MBID"""
        params = {}
        if includes:
            params["inc"] = "+".join(includes)

        url = f"{self.base_url}/artist/{artist_id}"
        return await self._make_request(url, params)

    async def search_releases(self, **kwargs) -> dict[str, Any]:
        """Search for releases"""
        params = {}
        if "query" in kwargs:
            params["query"] = kwargs["query"]
        else:
            query_parts = []
            if "artist" in kwargs:
                query_parts.append(f'artist:"{kwargs["artist"]}"')
            if "release" in kwargs:
                query_parts.append(f'release:"{kwargs["release"]}"')
            params["query"] = " AND ".join(query_parts)

        if "limit" in kwargs:
            params["limit"] = kwargs["limit"]
        if "offset" in kwargs:
            params["offset"] = kwargs["offset"]

        url = f"{self.base_url}/release"
        return await self._make_request(url, params)

    async def get_release_by_id(
        self, release_id: str, includes: list[str] | None = None
    ) -> dict[str, Any]:
        """Get release by MBID"""
        params = {}
        if includes:
            params["inc"] = "+".join(includes)

        url = f"{self.base_url}/release/{release_id}"
        return await self._make_request(url, params)

    async def search_release_groups(self, **kwargs) -> dict[str, Any]:
        """Search for release groups"""
        params = {}
        if "query" in kwargs:
            params["query"] = kwargs["query"]
        else:
            query_parts = []
            if "artist" in kwargs:
                query_parts.append(f'artist:"{kwargs["artist"]}"')
            if "releasegroup" in kwargs:
                query_parts.append(f'releasegroup:"{kwargs["releasegroup"]}"')
            params["query"] = " AND ".join(query_parts)

        if "limit" in kwargs:
            params["limit"] = kwargs["limit"]
        if "offset" in kwargs:
            params["offset"] = kwargs["offset"]

        url = f"{self.base_url}/release-group"
        return await self._make_request(url, params)

    async def get_release_group_by_id(
        self, rg_id: str, includes: list[str] | None = None
    ) -> dict[str, Any]:
        """Get release group by MBID"""
        params = {}
        if includes:
            params["inc"] = "+".join(includes)

        url = f"{self.base_url}/release-group/{rg_id}"
        return await self._make_request(url, params)

    # Cover Art Archive functions

    async def get_image_list(self, mbid: str, entity_type: str = "release") -> dict[str, Any]:
        """Get cover art image list for a release or release group"""
        url = f"{self.caa_base_url}/{entity_type}/{mbid}"
        try:
            return await self._make_request(url)
        except ResponseError as response_error:
            if "404" in str(response_error):
                return {}  # No cover art available
            raise

    async def get_image_front(
        self, mbid: str, entity_type: str = "release", size: str = "500"
    ) -> bytes:
        """Get front cover art image"""
        url = f"{self.caa_base_url}/{entity_type}/{mbid}/front-{size}"
        return await self._make_image_request(url)


# Global client instance for backward compatibility
_default_client: MusicBrainzClient | None = None


def get_default_client() -> MusicBrainzClient:
    """Get the default global client instance"""
    global _default_client  # pylint: disable=global-statement
    if _default_client is None:
        _default_client = MusicBrainzClient()
    return _default_client


# Backward compatibility functions that use the default client
async def search_recordings(**kwargs) -> dict[str, Any]:
    """Search for recordings using default client"""
    return await get_default_client().search_recordings(**kwargs)


async def get_recording_by_id(
    recording_id: str, includes: list[str] | None = None
) -> dict[str, Any]:
    """Get recording by MBID using default client"""
    return await get_default_client().get_recording_by_id(recording_id, includes)


async def get_recordings_by_isrc(
    isrc: str,  # pylint: disable=too-many-arguments
    includes: list[str] | None = None,
    release_status: list[str] | None = None,
) -> dict[str, Any]:
    """Get recordings by ISRC using default client"""
    return await get_default_client().get_recordings_by_isrc(isrc, includes, release_status)


async def browse_releases(
    recording: str,  # pylint: disable=too-many-arguments
    includes: list[str] | None = None,
    limit: int | None = None,
    offset: int | None = None,
    release_status: list[str] | None = None,
) -> dict[str, Any]:
    """Browse releases by recording using default client"""
    return await get_default_client().browse_releases(
        recording, includes, limit, offset, release_status
    )


async def get_artist_by_id(artist_id: str, includes: list[str] | None = None) -> dict[str, Any]:
    """Get artist by MBID using default client"""
    return await get_default_client().get_artist_by_id(artist_id, includes)


async def search_releases(**kwargs) -> dict[str, Any]:
    """Search for releases using default client"""
    return await get_default_client().search_releases(**kwargs)


async def get_release_by_id(release_id: str, includes: list[str] | None = None) -> dict[str, Any]:
    """Get release by MBID using default client"""
    return await get_default_client().get_release_by_id(release_id, includes)


async def search_release_groups(**kwargs) -> dict[str, Any]:
    """Search for release groups using default client"""
    return await get_default_client().search_release_groups(**kwargs)


async def get_release_group_by_id(rg_id: str, includes: list[str] | None = None) -> dict[str, Any]:
    """Get release group by MBID using default client"""
    return await get_default_client().get_release_group_by_id(rg_id, includes)


async def get_image_list(mbid: str, entity_type: str = "release") -> dict[str, Any]:
    """Get cover art image list using default client"""
    return await get_default_client().get_image_list(mbid, entity_type)


async def get_image_front(mbid: str, entity_type: str = "release", size: str = "500") -> bytes:
    """Get front cover art image using default client"""
    return await get_default_client().get_image_front(mbid, entity_type, size)


# Configuration functions for backward compatibility
def set_rate_limit(limit_or_interval: float = 0.5):
    """Set the rate limit interval for the default client"""
    get_default_client().set_rate_limit(limit_or_interval)


def set_useragent(app_name: str, app_version: str, contact: str):
    """Set the user agent string for the default client"""
    get_default_client().set_useragent(app_name, app_version, contact)
