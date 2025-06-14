#!/usr/bin/env python3
"""
Async Wikipedia/Wikidata client
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A minimal asyncio-based Wikipedia/Wikidata client that replaces wptools
with just the functionality needed by the nowplaying application.
"""
# pylint: disable=not-async-context-manager

import logging
import ssl
from typing import Any
import aiohttp

import nowplaying.utils


class WikiPage:  # pylint: disable=too-few-public-methods
    """Represents a Wikipedia page with its data."""

    def __init__(self, entity: str, lang: str = 'en'):
        self.entity = entity
        self.lang = lang
        self.data: dict[str, Any] = {}
        self._images: list[dict[str, str]] = []

    def images(self, fields: list[str] | None = None) -> list[dict[str, Any]]:
        """Return images with specified fields, mimicking wptools behavior."""
        if fields is None:
            return self._images
        return [{k: img.get(k) for k in fields if k in img} for img in self._images]


class AsyncWikiClient:
    """Async Wikipedia/Wikidata client."""

    def __init__(self, timeout: int = 30):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: aiohttp.ClientSession | None = None
        # Create SSL context with proper certificate verification
        self.ssl_context = ssl.create_default_context()

    async def __aenter__(self):
        connector = nowplaying.utils.create_http_connector(self.ssl_context)
        self.session = aiohttp.ClientSession(timeout=self.timeout, connector=connector)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _get_wikidata_info(self,
                                 entity: str,
                                 lang: str,
                                 include_sitelinks: bool = False) -> dict[str, Any]:
        """Get Wikidata entity information with optional sitelinks."""
        url = "https://www.wikidata.org/w/api.php"
        props = 'claims|descriptions'
        if include_sitelinks:
            props += '|sitelinks'

        params = {'action': 'wbgetentities', 'ids': entity, 'format': 'json', 'props': props}

        if not self.session:
            return {}
        async with self.session.get(url, params=params) as response:
            data = await response.json()

            if 'entities' not in data or entity not in data['entities']:
                return {}

            entity_data = data['entities'][entity]
            result = {'claims': {}}

            # Extract claims (P434 = MusicBrainz, P1953 = Discogs, P18 = Image)
            if 'claims' in entity_data:
                claims = entity_data['claims']
                if 'P434' in claims:  # MusicBrainz Artist ID
                    result['claims']['P434'] = [
                        claim['mainsnak']['datavalue']['value'] for claim in claims['P434']
                        if 'datavalue' in claim['mainsnak']
                    ]
                if 'P1953' in claims:  # Discogs Artist ID
                    result['claims']['P1953'] = [
                        claim['mainsnak']['datavalue']['value'] for claim in claims['P1953']
                        if 'datavalue' in claim['mainsnak']
                    ]
                if 'P18' in claims:  # Image
                    result['claims']['P18'] = [
                        claim['mainsnak']['datavalue']['value'] for claim in claims['P18']
                        if 'datavalue' in claim['mainsnak']
                    ]

            # Extract description
            if 'descriptions' in entity_data and lang in entity_data['descriptions']:
                result['description'] = entity_data['descriptions'][lang]['value']

            # Extract sitelinks if requested
            if include_sitelinks and 'sitelinks' in entity_data:
                result['sitelinks'] = entity_data['sitelinks']

            return result

    async def _get_wikipedia_extract(self,  # pylint: disable=too-many-return-statements
                                     entity: str,
                                     lang: str,
                                     sitelinks: dict | None = None) -> str | None:
        """Get Wikipedia page extract using sitelinks (fetched separately if not provided)."""
        if sitelinks is None:
            # Fallback: fetch sitelinks separately if not provided
            url = "https://www.wikidata.org/w/api.php"
            params = {
                'action': 'wbgetentities',
                'ids': entity,
                'format': 'json',
                'props': 'sitelinks'
            }

            if not self.session:
                return None
            async with self.session.get(url, params=params) as response:
                data = await response.json()

                if 'entities' not in data or entity not in data['entities']:
                    return None

                entity_data = data['entities'][entity]
                sitelinks = entity_data.get('sitelinks', {})

        # Look for the Wikipedia page in the specified language
        wiki_key = f"{lang}wiki"
        if not sitelinks or wiki_key not in sitelinks:
            return None

        page_title = sitelinks[wiki_key]['title']

        # Now get the extract from Wikipedia
        wiki_url = f"https://{lang}.wikipedia.org/w/api.php"
        extract_params = {
            'action': 'query',
            'format': 'json',
            'titles': page_title,
            'prop': 'extracts',
            'exintro': '1',
            'explaintext': '1',
            'exsectionformat': 'plain'
        }

        if not self.session:
            return None
        async with self.session.get(wiki_url, params=extract_params) as response:
            data = await response.json()

            if 'query' not in data or 'pages' not in data['query']:
                return None

            pages = data['query']['pages']
            return next(
                (page_data['extract'] for page_data in pages.values() if 'extract' in page_data),
                None
            )

    async def _get_wikidata_images(self, entity: str) -> list[dict[str, str]]:
        """Get images directly from Wikidata entity."""
        images = []

        # Get Wikidata entity with claims
        url = "https://www.wikidata.org/w/api.php"
        params = {'action': 'wbgetentities', 'ids': entity, 'format': 'json', 'props': 'claims'}

        if not self.session:
            return images
        async with self.session.get(url, params=params) as response:
            data = await response.json()

            if 'entities' not in data or entity not in data['entities']:
                return images

            entity_data = data['entities'][entity]
            claims = entity_data.get('claims', {})

            # Get P18 (image) claims
            if 'P18' in claims:
                for claim in claims['P18']:
                    if 'mainsnak' in claim and 'datavalue' in claim['mainsnak']:
                        filename = claim['mainsnak']['datavalue']['value']
                        # Convert to Commons URL
                        img_url = await self._get_commons_image_url(filename)
                        if img_url:
                            images.append({'kind': 'wikidata-image', 'url': img_url})

        return images

    async def _get_commons_image_url(self, filename: str) -> str | None:
        """Get Commons image URL from filename."""
        # Query Commons for the image URL
        commons_url = "https://commons.wikimedia.org/w/api.php"
        params = {
            'action': 'query',
            'format': 'json',
            'titles': f'File:{filename}',
            'prop': 'imageinfo',
            'iiprop': 'url'
        }

        try:
            if not self.session:
                return None
            async with self.session.get(commons_url, params=params) as response:
                data = await response.json()

                if 'query' not in data or 'pages' not in data['query']:
                    return None

                pages = data['query']['pages']
                return next(
                    (page_data['imageinfo'][0].get('url')
                     for page_data in pages.values()
                     if 'imageinfo' in page_data and page_data['imageinfo']),
                    None
                )
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    async def _get_wikipedia_images(self,  # pylint: disable=too-many-locals
                                    entity: str,
                                    lang: str,
                                    sitelinks: dict | None = None) -> list[dict[str, str]]:
        """Get images from Wikipedia page using sitelinks (fetched separately if not provided)."""
        if sitelinks is None:
            # Fallback: fetch sitelinks separately if not provided
            url = "https://www.wikidata.org/w/api.php"
            params = {
                'action': 'wbgetentities',
                'ids': entity,
                'format': 'json',
                'props': 'sitelinks'
            }

            if not self.session:
                return []
            async with self.session.get(url, params=params) as response:
                data = await response.json()

                if 'entities' not in data or entity not in data['entities']:
                    return []

                entity_data = data['entities'][entity]
                sitelinks = entity_data.get('sitelinks', {})

        wiki_key = f"{lang}wiki"
        if not sitelinks or wiki_key not in sitelinks:
            return []

        page_title = sitelinks[wiki_key]['title']

        # Get images from Wikipedia page using pageimages API (cleaner, no UI icons)
        wiki_url = f"https://{lang}.wikipedia.org/w/api.php"
        image_params = {
            'action': 'query',
            'format': 'json',
            'titles': page_title,
            'prop': 'pageimages',
            'piprop': 'original|name',
            'pithumbsize': 500,
            'pilicense': 'any'  # Include both free and fair-use images
        }

        images = []

        if not self.session:
            return images
        async with self.session.get(wiki_url, params=image_params) as response:
            data = await response.json()

            if 'query' not in data or 'pages' not in data['query']:
                return images

            pages = data['query']['pages']
            for page_data in pages.values():
                # Add pageimage (main representative image) if available
                if 'original' in page_data:
                    images.append({
                        'kind': 'wikidata-image',  # Keep same kind for compatibility
                        'url': page_data['original']['source']
                    })

                # Add thumbnail if available and no original
                elif 'thumbnail' in page_data:
                    images.append({
                        'kind': 'query-thumbnail',
                        'url': page_data['thumbnail']['source']
                    })

        return images

    async def _get_image_url(self, filename: str, lang: str) -> str | None:
        """Get the actual URL for an image file."""
        wiki_url = f"https://{lang}.wikipedia.org/w/api.php"
        params = {
            'action': 'query',
            'format': 'json',
            'titles': filename,
            'prop': 'imageinfo',
            'iiprop': 'url'
        }

        try:
            if not self.session:
                return None
            async with self.session.get(wiki_url, params=params) as response:
                data = await response.json()

                if 'query' not in data or 'pages' not in data['query']:
                    return None

                pages = data['query']['pages']
                return next(
                    (page_data['imageinfo'][0].get('url')
                     for page_data in pages.values()
                     if 'imageinfo' in page_data and page_data['imageinfo']),
                    None
                )
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    async def get_page(self,  # pylint: disable=too-many-arguments
                       entity: str,
                       lang: str = 'en',
                       fetch_bio: bool = True,
                       fetch_images: bool = True,
                       max_images: int = 10) -> WikiPage:
        """Get a Wikipedia page by Wikidata entity ID with selective fetching."""
        wiki_page = WikiPage(entity, lang)

        try:
            # Get Wikidata info, including sitelinks if we need bio or images
            include_sitelinks = fetch_bio or fetch_images
            wikidata_info = await self._get_wikidata_info(entity, lang, include_sitelinks)
            wiki_page.data.update(wikidata_info)

            # Extract sitelinks for reuse
            sitelinks = wikidata_info.get('sitelinks') if include_sitelinks else None

            # Only fetch bio if requested - reuse sitelinks to avoid extra API call
            if fetch_bio:
                extract = await self._get_wikipedia_extract(entity, lang, sitelinks)
                if extract:
                    wiki_page.data['extext'] = extract

            # Only fetch images if requested - reuse sitelinks to avoid extra API call
            if fetch_images:
                wikidata_images = await self._get_wikidata_images(entity)
                wikipedia_images = await self._get_wikipedia_images(entity, lang, sitelinks)
                # Limit total images for performance
                all_images = wikidata_images + wikipedia_images
                wiki_page._images = all_images[:max_images]  # pylint: disable=protected-access

        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.debug("Error fetching page data for %s: %s", entity, error)

        return wiki_page


async def get_page_async(entity: str,  # pylint: disable=too-many-arguments
                         lang: str = 'en',
                         timeout: int = 5,
                         need_bio: bool = True,
                         need_images: bool = True,
                         max_images: int = 5) -> WikiPage:
    """
    Async function for nowplaying wikimedia plugin.

    Args:
        entity: Wikidata entity ID (e.g., 'Q11647')
        lang: Language code for Wikipedia content
        timeout: Request timeout in seconds (reduced default for live performance)
        need_bio: Whether to fetch biography/extract
        need_images: Whether to fetch images
        max_images: Maximum number of images to fetch for performance

    Returns:
        WikiPage with optimized data fetching based on actual needs
    """
    async with AsyncWikiClient(timeout=timeout) as client:
        return await client.get_page(entity, lang, need_bio, need_images, max_images)
