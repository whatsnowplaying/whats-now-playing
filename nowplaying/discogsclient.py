#!/usr/bin/env python3
"""
Async Discogs API Client
~~~~~~~~~~~~~~~~~~~~~~~

A minimal asyncio-based Discogs API client that replaces the vendored discogs_client
with just the functionality needed by the nowplaying application.
"""

import asyncio
import logging
import ssl
from typing import Dict, List, Optional, Any, Union
import aiohttp


class DiscogsRelease:
    """Represents a Discogs release with its artists."""
    
    def __init__(self, data: Dict[str, Any], client: Optional['AsyncDiscogsClient'] = None):
        self.data = data
        self.id = data.get('id')
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
        if self._artists_loaded or not self.id or not self._client:
            return
        
        # Get full release data
        url = f"{self._client.BASE_URL}/releases/{self.id}"
        try:
            async with self._client.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'artists' in data and data['artists']:
                        # Create artist objects with IDs for further lookup
                        self.artists = [DiscogsArtist(artist) for artist in data['artists']]
                        self._artists_loaded = True
        except Exception as e:
            logging.debug("Error loading full release data: %s", e)


class DiscogsArtist:
    """Represents a Discogs artist with metadata."""
    
    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.id = data.get('id')
        self.name = data.get('name', '')
        self.profile_plaintext = data.get('profile', '')
        self.urls = data.get('urls', [])
        self.images = data.get('images', [])


class DiscogsSearchResult:
    """Represents a page of search results."""
    
    def __init__(self, results: List[Dict[str, Any]], client: Optional['AsyncDiscogsClient'] = None):
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
                if release_artist.id:
                    if release._client:
                        # Use optimized artist loading with limited images
                        full_artist = await release._client.artist(release_artist.id, limit_images=5)
                        if full_artist:
                            release.artists[i] = full_artist
                            loaded_count += 1
                            break


class AsyncDiscogsClient:
    """Async Discogs API client."""
    
    BASE_URL = 'https://api.discogs.com'
    
    def __init__(self, user_agent: str, user_token: str, timeout: int = 10):
        self.user_agent = user_agent
        self.user_token = user_token
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Create SSL context with proper certificate verification
        self.ssl_context = ssl.create_default_context()
    
    async def __aenter__(self):
        headers = {
            'User-Agent': self.user_agent,
            'Authorization': f'Discogs token={self.user_token}'
        }
        connector = aiohttp.TCPConnector(ssl=self.ssl_context)
        self.session = aiohttp.ClientSession(
            timeout=self.timeout, 
            headers=headers, 
            connector=connector
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search(self, query: str, artist: Optional[str] = None, 
                    type: str = 'release', page: int = 1, per_page: int = 50,
                    load_full_artists: bool = True, max_results: int = None) -> DiscogsSearchResult:
        """Search for releases, artists, etc."""
        if not self.session:
            raise RuntimeError("Client not initialized - use async context manager")
        
        params = {
            'q': query,
            'type': type,
            'page': page,
            'per_page': per_page
        }
        
        if artist:
            params['artist'] = artist
        
        url = f"{self.BASE_URL}/database/search"
        
        try:
            async with self.session.get(url, params=params) as response:
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
                else:
                    logging.warning("Discogs search failed with status %d", response.status)
                    return DiscogsSearchResult([], self)
        except Exception as e:
            logging.debug("Discogs search error: %s", e)
            return DiscogsSearchResult([], self)
    
    async def artist(self, artist_id: Union[int, str], limit_images: int = None) -> Optional[DiscogsArtist]:
        """Get artist by ID with optional image limiting for performance."""
        if not self.session:
            raise RuntimeError("Client not initialized - use async context manager")
        
        url = f"{self.BASE_URL}/artists/{artist_id}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Limit images for performance if specified
                    if limit_images and 'images' in data:
                        # Keep primary images first, then limit total
                        primary_images = [img for img in data['images'] if img.get('type') == 'primary']
                        other_images = [img for img in data['images'] if img.get('type') != 'primary']
                        data['images'] = (primary_images + other_images)[:limit_images]
                    
                    return DiscogsArtist(data)
                else:
                    logging.warning("Discogs artist lookup failed with status %d", response.status)
                    return None
        except Exception as e:
            logging.debug("Discogs artist lookup error: %s", e)
            return None


class CompatibilityDiscogsClient:
    """
    Synchronous compatibility wrapper that mimics the old discogs_client interface.
    
    This provides backward compatibility with the existing discogs plugin.
    """
    
    def __init__(self, user_agent: str, user_token: str = None):
        self.user_agent = user_agent
        self.user_token = user_token
        self.timeout = 10
    
    def set_timeout(self, connect: int = 10, read: int = 10):
        """Set timeout (compatibility method)."""
        self.timeout = max(connect, read)
    
    def search(self, query: str, artist: Optional[str] = None, type: str = 'release') -> 'SearchResultPage':
        """Search for releases (sync wrapper)."""
        async def _search():
            async with AsyncDiscogsClient(self.user_agent, self.user_token, self.timeout) as client:
                # Use optimized search for nowplaying: limit results and artists loaded
                results = await client.search(query, artist, type, max_results=10, load_full_artists=True)
                return results
        
        return SearchResultPage(_run_async(_search()))
    
    def artist(self, artist_id: Union[int, str]) -> Optional[DiscogsArtist]:
        """Get artist by ID (sync wrapper)."""
        async def _get_artist():
            async with AsyncDiscogsClient(self.user_agent, self.user_token, self.timeout) as client:
                # Limit images for nowplaying performance (typically only need 1 thumbnail + a few fanart)
                return await client.artist(artist_id, limit_images=5)
        
        return _run_async(_get_artist())


class SearchResultPage:
    """Compatibility wrapper for search results that provides .page() method."""
    
    def __init__(self, result: DiscogsSearchResult):
        self.result = result
    
    def page(self, page_num: int = 1):
        """Return the search result (compatibility method)."""
        return self.result


def _run_async(coro):
    """Run async function in sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're already in an async context, we need to run in a thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        # No event loop, create one
        return asyncio.run(coro)


# Compatibility class for the models module
class models:
    """Compatibility module for discogs models."""
    Release = DiscogsRelease
    Artist = DiscogsArtist


def Client(user_agent: str, user_token: str = None) -> CompatibilityDiscogsClient:
    """Factory function for backward compatibility."""
    return CompatibilityDiscogsClient(user_agent, user_token)


def get_optimized_client_for_nowplaying(user_agent: str, user_token: str, 
                                       need_bio: bool = True, need_images: bool = True,
                                       timeout: int = 5) -> CompatibilityDiscogsClient:
    """
    Get an optimized Discogs client specifically for nowplaying usage.
    
    Args:
        user_agent: User agent string for API requests
        user_token: Discogs API token
        need_bio: Whether biography data is needed (affects artist data fetching)
        need_images: Whether image data is needed (affects image limiting)
        timeout: Request timeout in seconds (reduced default for live performance)
        
    Returns:
        Optimized CompatibilityDiscogsClient with performance settings for live use
    """
    client = CompatibilityDiscogsClient(user_agent, user_token)
    client.timeout = timeout
    
    # Store optimization flags for use in search/artist methods
    client._need_bio = need_bio
    client._need_images = need_images
    
    return client