#!/usr/bin/env python3
"""
Async Discogs API Client
~~~~~~~~~~~~~~~~~~~~~~~

A minimal asyncio-based Discogs API client that replaces the vendored discogs_client
with just the functionality needed by the nowplaying application.
"""

import logging
import ssl
from typing import Any
import aiohttp


class DiscogsRelease:  # pylint: disable=too-few-public-methods
    """Represents a Discogs release with its artists."""

    def __init__(self, data: dict[str, Any], client: 'AsyncDiscogsClient | None' = None):
        self.data = data
        self.discogs_id = data.get('id')
        self._client = client
        self._artists_loaded = False
        self.artists = []

        # If we have full release data with artists, use it
        if 'artists' in data and data['artists']:
            self.artists = [DiscogsArtist(artist) for artist in data['artists']]
            self._artists_loaded = True
        else:
            # For search results, create minimal artist from title
            title = data.get('title', '')
            if ' - ' in title:
                artist_name = title.split(' - ')[0]
            else:
                # Fallback: use the entire title as artist name if no dash
                artist_name = title
            artist_data = {
                'name': artist_name,
                'id': None,
                'profile': '',
                'urls': [],
                'images': []
            }
            self.artists = [DiscogsArtist(artist_data)]

    async def load_full_data(self):
        """Load full release data including artist details."""
        if self._artists_loaded or not self.discogs_id or not self._client or not self._client.session:  # pylint: disable=line-too-long
            return

        # Get full release data
        url = f"{self._client.BASE_URL}/releases/{self.discogs_id}"
        try:
            async with self._client.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'artists' in data and data['artists']:
                        # Create artist objects with IDs for further lookup
                        self.artists = [DiscogsArtist(artist) for artist in data['artists']]
                        self._artists_loaded = True
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.debug("Error loading full release data: %s", error)


class DiscogsArtist:  # pylint: disable=too-few-public-methods
    """Represents a Discogs artist with metadata."""

    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.discogs_id = data.get('id')
        self.name = data.get('name', '')
        self.profile_plaintext = data.get('profile', '')
        self.urls = data.get('urls', [])
        self.images = data.get('images', [])


class DiscogsSearchResult:
    """Represents a page of search results."""

    def __init__(self, results: list[dict[str, Any]], client: 'AsyncDiscogsClient | None' = None):
        self.results = []
        for result in results:
            if result.get('type') == 'release':
                self.results.append(DiscogsRelease(result, client))

    def __iter__(self):
        return iter(self.results)

    async def load_full_artist_data(self, max_artists: int = 3):
        """Load full artist data for search results (limited for performance)."""
        loaded_count = 0
        for release in self.results:
            if loaded_count >= max_artists:
                break
            await release.load_full_data()
            # Load full artist data for first artist only (typically what nowplaying needs)
            for i, release_artist in enumerate(release.artists[:1]):  # Only first artist
                if release_artist.discogs_id and release._client:  # pylint: disable=protected-access
                    # Use optimized artist loading with limited images
                    full_artist = await release._client.artist(release_artist.discogs_id,  # pylint: disable=protected-access
                                                               limit_images=5,
                                                               include_bio=True)
                    if full_artist:
                        release.artists[i] = full_artist
                        loaded_count += 1
                        break


class AsyncDiscogsClient:
    """Async Discogs API client."""

    BASE_URL = 'https://api.discogs.com'

    def __init__(self, user_agent: str, user_token: str | None, timeout: int = 10):
        self.user_agent = user_agent
        self.user_token = user_token
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: aiohttp.ClientSession | None = None

        # Create SSL context with proper certificate verification
        self.ssl_context = ssl.create_default_context()

    async def __aenter__(self):
        headers = {'User-Agent': self.user_agent}
        # Only add Authorization header if user_token is not None
        if self.user_token is not None:
            headers['Authorization'] = f'Discogs token={self.user_token}'
        connector = aiohttp.TCPConnector(ssl=self.ssl_context,
                                         keepalive_timeout=1,
                                         enable_cleanup_closed=True)
        self.session = aiohttp.ClientSession(timeout=self.timeout,
                                             headers=headers,
                                             connector=connector)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def search(self,  # pylint: disable=too-many-arguments
                     query: str,
                     artist: str | None = None,
                     search_type: str = 'release',
                     page: int = 1,
                     per_page: int = 50,
                     load_full_artists: bool = True,
                     max_results: int | None = None) -> DiscogsSearchResult:
        """Search for releases, artists, etc."""
        if not self.session:
            raise RuntimeError("Client not initialized - use async context manager")

        params = {'q': query, 'type': search_type, 'page': page, 'per_page': per_page}

        if artist:
            params['artist'] = artist

        url = f"{self.BASE_URL}/database/search"

        try:
            if not self.session:
                return DiscogsSearchResult([], self)
            async with self.session.get(url, params=params) as response:  # pylint: disable=not-async-context-manager
                if response.status == 200:
                    data = await response.json()
                    results = data.get('results', [])

                    # Limit results for performance if specified
                    if max_results:
                        results = results[:max_results]

                    search_result = DiscogsSearchResult(results, self)

                    # Optionally skip full artist loading for performance
                    if load_full_artists:
                        await search_result.load_full_artist_data()

                    return search_result

                logging.warning("Discogs search failed with status %d", response.status)
                return DiscogsSearchResult([], self)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.debug("Discogs search error: %s", error)
            return DiscogsSearchResult([], self)

    async def artist(self,
                     artist_id: int | str,
                     limit_images: int | None = None,
                     include_bio: bool = True) -> DiscogsArtist | None:
        """Get artist by ID with optional image limiting and bio control for performance."""
        if not self.session:
            raise RuntimeError("Client not initialized - use async context manager")

        url = f"{self.BASE_URL}/artists/{artist_id}"

        try:
            async with self.session.get(url) as response:  # pylint: disable=not-async-context-manager
                if response.status == 200:
                    data = await response.json()

                    # Limit images for performance if specified
                    if limit_images is not None and 'images' in data:
                        if limit_images == 0:
                            data['images'] = []
                        else:
                            # Keep primary images first, then limit total
                            primary_images = [
                                img for img in data['images'] if img.get('type') == 'primary'
                            ]
                            other_images = [
                                img for img in data['images'] if img.get('type') != 'primary'
                            ]
                            data['images'] = (primary_images + other_images)[:limit_images]

                    # Remove bio data if not needed for performance
                    if not include_bio and 'profile' in data:
                        data['profile'] = ''

                    return DiscogsArtist(data)

                logging.warning("Discogs artist lookup failed with status %d", response.status)
                return None
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.debug("Discogs artist lookup error: %s", error)
            return None


class AsyncDiscogsClientWrapper:
    """Async-only Discogs client wrapper for nowplaying compatibility."""

    def __init__(self, user_agent: str, user_token: str | None = None):
        self.user_agent = user_agent
        self.user_token = user_token
        self.timeout = 10
        self._need_bio = True
        self._need_images = True

    def set_timeout(self, connect: int = 10, read: int = 10):
        """Set timeout (compatibility method)."""
        self.timeout = max(connect, read)

    async def artist_async(self, artist_id: int | str) -> DiscogsArtist | None:
        """Get artist by ID (async version)."""
        # Use optimization flags to control data fetching
        limit_images = 5 if self._need_images else 0
        include_bio = self._need_bio
        async with AsyncDiscogsClient(self.user_agent, self.user_token, self.timeout) as client:
            return await client.artist(artist_id, limit_images=limit_images,
                                       include_bio=include_bio)

    async def search_async(self,
                           query: str,
                           artist: str | None = None,
                           search_type: str = 'release') -> DiscogsSearchResult:
        """Search for releases (async version)."""
        async with AsyncDiscogsClient(self.user_agent, self.user_token, self.timeout) as client:
            return await client.search(query,
                                       artist,
                                       search_type,
                                       max_results=10,
                                       load_full_artists=True)


# Data models module
class Models:  # pylint: disable=too-few-public-methods
    """Data models module for discogs objects."""
    Release = DiscogsRelease
    Artist = DiscogsArtist


def create_client(user_agent: str, user_token: str | None = None) -> AsyncDiscogsClientWrapper:
    """Factory function for creating discogs clients."""
    return AsyncDiscogsClientWrapper(user_agent, user_token)


def get_optimized_client_for_nowplaying(user_agent: str,
                                        user_token: str | None,
                                        need_bio: bool = True,
                                        need_images: bool = True,
                                        timeout: int = 5) -> AsyncDiscogsClientWrapper:
    """
    Get an optimized Discogs client specifically for nowplaying usage.

    Args:
        user_agent: User agent string for API requests
        user_token: Discogs API token
        need_bio: Whether biography data is needed (affects artist data fetching)
        need_images: Whether image data is needed (affects image limiting)
        timeout: Request timeout in seconds (reduced default for live performance)

    Returns:
        Optimized AsyncDiscogsClientWrapper with performance settings for live use
    """
    client = AsyncDiscogsClientWrapper(user_agent, user_token)
    client.timeout = timeout

    # Store optimization flags for use in search/artist methods
    client._need_bio = need_bio  # pylint: disable=protected-access
    client._need_images = need_images  # pylint: disable=protected-access

    return client
