#!/usr/bin/env python3
"""
Async Wikipedia/Wikidata client
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A minimal asyncio-based Wikipedia/Wikidata client that replaces wptools
with just the functionality needed by the nowplaying application.
"""
# pylint: disable=not-async-context-manager

import asyncio
import logging
import ssl
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import aiohttp

import nowplaying
import nowplaying.utils


class WikiRateLimitError(aiohttp.ClientError):
    """Raised when a Wikimedia endpoint returns HTTP 429.

    Subclasses aiohttp.ClientError so existing (aiohttp.ClientError, TimeoutError)
    handlers in get_page and in wikimedia.py treat it as a transient failure
    and skip caching the empty result.
    """


class WikiPage:  # pylint: disable=too-few-public-methods
    """Represents a Wikipedia page with its data."""

    def __init__(self, entity: str, lang: str = "en"):
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
    """Async Wikipedia/Wikidata client.

    Honours the Wikimedia client guidance:
    - Sends a contact-bearing User-Agent (see __aenter__).
    - Respects 429 + Retry-After across all Wikimedia endpoints (wikidata,
      wikipedia, commons) via a class-level cooldown.  Rate limiting is
      per-IP so the cooldown is shared between every instance in this
      process.
    - Caps concurrent requests to three with a class-level semaphore.
    """

    # Cooldown shared across all instances.  Updated when any request returns
    # 429, checked before every request.
    _rate_limit_until: float = 0.0
    # Wikimedia asks clients to limit concurrent requests to 3 or fewer.
    _concurrency_semaphore: asyncio.Semaphore = asyncio.Semaphore(3)
    # Used when a 429 arrives without a parseable Retry-After header.
    _DEFAULT_RETRY_AFTER_SECONDS = 60.0

    def __init__(self, timeout: int = 30):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: aiohttp.ClientSession | None = None
        # Create SSL context with proper certificate verification
        self.ssl_context = ssl.create_default_context()

    @classmethod
    def _raise_if_rate_limited(cls) -> None:
        """Raise WikiRateLimitError if we are inside a 429-induced cooldown."""
        # Monotonic clock — NTP / DST adjustments must not shorten or extend
        # cooldowns mid-flight.
        now = time.monotonic()
        if now < cls._rate_limit_until:
            remaining = cls._rate_limit_until - now
            raise WikiRateLimitError(f"Wikimedia cooldown active; {remaining:.0f}s remaining")

    @staticmethod
    def _parse_retry_after(retry_after_header: str | None) -> float | None:
        """Parse a Retry-After header value into a delay in seconds.

        Returns None on missing / unparsable input.  RFC 9110 allows two
        forms: delta-seconds (an integer) and HTTP-date.  We accept both.
        Negative or already-past dates collapse to 0 (caller bumps to a
        minimum tick).
        """
        if not retry_after_header:
            return None
        try:
            return float(retry_after_header)
        except (TypeError, ValueError):
            pass
        try:
            target = parsedate_to_datetime(retry_after_header)
        except (TypeError, ValueError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return max((target - datetime.now(timezone.utc)).total_seconds(), 0.0)

    @classmethod
    def _record_rate_limit(cls, retry_after_header: str | None) -> float:
        """Record a 429 hit and return the chosen backoff in seconds.

        Honours the Retry-After header in either delta-seconds or HTTP-date
        form (RFC 9110).  Missing or unparsable values fall back to the
        default.  Values are floored at 1 second so we always wait at least
        a tick.
        """
        delay = cls._parse_retry_after(retry_after_header)
        if delay is None:
            delay = cls._DEFAULT_RETRY_AFTER_SECONDS
        delay = max(delay, 1.0)
        cls._rate_limit_until = time.monotonic() + delay
        logging.warning(
            "Wikimedia returned 429; backing off all Wikimedia requests for %.0fs",
            delay,
        )
        return delay

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET a Wikimedia JSON endpoint with shared rate-limit handling.

        Caps process-wide concurrency at three, raises WikiRateLimitError if
        we are in cooldown (either preemptively or after a fresh 429), and
        raises on other non-200 statuses so callers can decide whether to
        skip caching.
        """
        if not self.session:
            raise RuntimeError("AsyncWikiClient not initialized - use as async context manager")
        self._raise_if_rate_limited()
        async with self._concurrency_semaphore:
            async with self.session.get(url, params=params) as response:
                if response.status == 429:
                    self._record_rate_limit(response.headers.get("Retry-After"))
                    raise WikiRateLimitError(
                        f"429 from {response.url}; "
                        f"Retry-After={response.headers.get('Retry-After')!r}"
                    )
                response.raise_for_status()
                return await response.json()

    def _handle_redirect(self, data: dict, entity: str) -> dict | None:  # pylint: disable=no-self-use
        """Handle Wikidata entity redirects."""
        if entity in data["entities"]:
            return data["entities"][entity]
        entities = list(data["entities"].keys())
        if len(entities) == 1:
            logging.debug("Following redirect from %s to %s", entity, entities[0])
            return data["entities"][entities[0]]
        if len(entities) > 1:
            logging.warning(
                "Ambiguous redirect for entity %s: multiple entities returned (%s).",
                entity,
                ", ".join(entities),
            )
            return None
        return None

    async def __aenter__(self):
        connector = nowplaying.utils.create_http_connector(self.ssl_context)
        # Set proper headers required by Wikimedia APIs
        headers = {
            "User-Agent": f"WhatNowPlaying/{nowplaying.__version__} "
            "(https://github.com/whatsnowplaying/whats-now-playing; "
            "wnp@"
            "effectivemachines.com) aiohttp/3.12.0",
        }
        self.session = aiohttp.ClientSession(
            timeout=self.timeout, connector=connector, headers=headers
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _get_wikidata_info(
        self, entity: str, lang: str, include_sitelinks: bool = False
    ) -> dict[str, Any]:
        """Get Wikidata entity information with optional sitelinks."""
        url = "https://www.wikidata.org/w/api.php"
        props = "claims|descriptions"
        if include_sitelinks:
            props += "|sitelinks"

        params = {"action": "wbgetentities", "ids": entity, "format": "json", "props": props}

        data = await self._get_json(url, params)

        if "entities" not in data:
            return {}

        entity_data = self._handle_redirect(data, entity)
        if not entity_data:
            return {}
        result = {"claims": {}}

        # Extract claims (P434 = MusicBrainz, P1953 = Discogs, P18 = Image)
        if "claims" in entity_data:
            claims = entity_data["claims"]
            if "P434" in claims:  # MusicBrainz Artist ID
                result["claims"]["P434"] = [
                    claim["mainsnak"]["datavalue"]["value"]
                    for claim in claims["P434"]
                    if "datavalue" in claim["mainsnak"]
                ]
            if "P1953" in claims:  # Discogs Artist ID
                result["claims"]["P1953"] = [
                    claim["mainsnak"]["datavalue"]["value"]
                    for claim in claims["P1953"]
                    if "datavalue" in claim["mainsnak"]
                ]
            if "P18" in claims:  # Image
                result["claims"]["P18"] = [
                    claim["mainsnak"]["datavalue"]["value"]
                    for claim in claims["P18"]
                    if "datavalue" in claim["mainsnak"]
                ]

        # Extract description
        if "descriptions" in entity_data and lang in entity_data["descriptions"]:
            result["description"] = entity_data["descriptions"][lang]["value"]

        # Extract sitelinks if requested
        if include_sitelinks and "sitelinks" in entity_data:
            result["sitelinks"] = entity_data["sitelinks"]

        return result

    async def _get_wikipedia_extract(  # pylint: disable=too-many-return-statements
        self, entity: str, lang: str, sitelinks: dict | None = None
    ) -> str | None:
        """Get Wikipedia page extract using sitelinks (fetched separately if not provided)."""
        if sitelinks is None:
            # Fallback: fetch sitelinks separately if not provided
            url = "https://www.wikidata.org/w/api.php"
            params = {
                "action": "wbgetentities",
                "ids": entity,
                "format": "json",
                "props": "sitelinks",
            }

            data = await self._get_json(url, params)

            if "entities" not in data:
                return None

            entity_data = self._handle_redirect(data, entity)
            if not entity_data:
                return None
            sitelinks = entity_data.get("sitelinks", {})

        # Look for the Wikipedia page in the specified language
        wiki_key = f"{lang}wiki"
        if not sitelinks or wiki_key not in sitelinks:
            return None

        page_title = sitelinks[wiki_key]["title"]

        # Now get the extract from Wikipedia
        wiki_url = f"https://{lang}.wikipedia.org/w/api.php"
        extract_params = {
            "action": "query",
            "format": "json",
            "titles": page_title,
            "prop": "extracts",
            "exintro": "1",
            "explaintext": "1",
            "exsectionformat": "plain",
        }

        data = await self._get_json(wiki_url, extract_params)

        if "query" not in data or "pages" not in data["query"]:
            return None

        pages = data["query"]["pages"]
        return next(
            (page_data["extract"] for page_data in pages.values() if "extract" in page_data),
            None,
        )

    async def _get_wikidata_images(self, entity: str) -> list[dict[str, str]]:
        """Get images directly from Wikidata entity with batch processing."""
        images = []

        # Get Wikidata entity with claims
        url = "https://www.wikidata.org/w/api.php"
        params = {"action": "wbgetentities", "ids": entity, "format": "json", "props": "claims"}

        data = await self._get_json(url, params)

        if "entities" not in data:
            return images

        entity_data = self._handle_redirect(data, entity)
        if not entity_data:
            return images
        claims = entity_data.get("claims", {})

        # Get P18 (image) claims
        if "P18" in claims:
            if filenames := [
                claim["mainsnak"]["datavalue"]["value"]
                for claim in claims["P18"]
                if "mainsnak" in claim and "datavalue" in claim["mainsnak"]
            ]:
                image_urls = await self._get_commons_image_urls_batch(filenames)
                for img_url in image_urls:
                    if img_url:
                        images.append({"kind": "wikidata-image", "url": img_url})

        return images

    async def _get_commons_image_urls_batch(self, filenames: list[str]) -> list[str | None]:
        """Get Commons image URLs for multiple filenames in a single batch API call."""
        if not filenames or not self.session:
            return []

        # Create pipe-separated list of file titles for batch query, URL-encoding each filename
        titles = "|".join(f"File:{quote(filename, safe='')}" for filename in filenames)

        commons_url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "titles": titles,
            "prop": "imageinfo",
            "iiprop": "url",
        }

        try:
            data = await self._get_json(commons_url, params)
        except (aiohttp.ClientError, TimeoutError):
            # Includes WikiRateLimitError; the cooldown is already recorded
            # inside _get_json so the rest of the pipeline will skip future
            # Wikimedia requests until it expires.
            logging.debug("Batch Commons image URL fetch failed, skipping images")
            return []

        if "query" not in data or "pages" not in data["query"]:
            return []

        pages = data["query"]["pages"]
        results = []

        # Maintain order by matching against original filenames
        for filename in filenames:
            file_title = f"File:{filename}"
            url = next(
                (
                    page_data["imageinfo"][0].get("url")
                    for page_data in pages.values()
                    if (
                        page_data.get("title") == file_title
                        and "imageinfo" in page_data
                        and page_data["imageinfo"]
                    )
                ),
                None,
            )
            results.append(url)

        return results

    async def _get_commons_image_url(self, filename: str) -> str | None:
        """Get Commons image URL from filename (single file convenience method)."""
        results = await self._get_commons_image_urls_batch([filename])
        return results[0] if results else None

    async def _get_wikipedia_images(  # pylint: disable=too-many-locals,too-many-return-statements
        self, entity: str, lang: str, sitelinks: dict | None = None
    ) -> list[dict[str, str]]:
        """Get images from Wikipedia page using sitelinks (fetched separately if not provided)."""
        if sitelinks is None:
            # Fallback: fetch sitelinks separately if not provided
            url = "https://www.wikidata.org/w/api.php"
            params = {
                "action": "wbgetentities",
                "ids": entity,
                "format": "json",
                "props": "sitelinks",
            }

            data = await self._get_json(url, params)

            if "entities" not in data:
                return []

            entity_data = self._handle_redirect(data, entity)
            if not entity_data:
                return []
            sitelinks = entity_data.get("sitelinks", {})

        wiki_key = f"{lang}wiki"
        if not sitelinks or wiki_key not in sitelinks:
            return []

        page_title = sitelinks[wiki_key]["title"]

        # Get images from Wikipedia page using pageimages API (cleaner, no UI icons)
        wiki_url = f"https://{lang}.wikipedia.org/w/api.php"
        image_params = {
            "action": "query",
            "format": "json",
            "titles": page_title,
            "prop": "pageimages",
            "piprop": "original|name",
            "pithumbsize": 500,
            "pilicense": "any",  # Include both free and fair-use images
        }

        images: list[dict[str, str]] = []

        data = await self._get_json(wiki_url, image_params)

        if "query" not in data or "pages" not in data["query"]:
            return images

        pages = data["query"]["pages"]
        for page_data in pages.values():
            # Add pageimage (main representative image) if available
            if "original" in page_data:
                images.append(
                    {
                        "kind": "wikidata-image",  # Keep same kind for compatibility
                        "url": page_data["original"]["source"],
                    }
                )

            # Add thumbnail if available and no original
            elif "thumbnail" in page_data:
                images.append({"kind": "query-thumbnail", "url": page_data["thumbnail"]["source"]})

        return images

    async def get_page(  # pylint: disable=too-many-arguments
        self,
        entity: str,
        lang: str = "en",
        fetch_bio: bool = True,
        fetch_images: bool = True,
        max_images: int = 10,
    ) -> WikiPage:
        """Get a Wikipedia page by Wikidata entity ID with selective fetching.

        Raises on transient failures of the primary Wikidata lookup (e.g.
        HTTP 429 rate limits) so callers can avoid caching a poisoned empty
        result. Secondary best-effort fetches (extract, images) swallow
        their own errors and contribute whatever data they were able to
        retrieve.
        """
        wiki_page = WikiPage(entity, lang)

        # Primary Wikidata lookup - if this fails, the page is unusable.
        # Let the exception propagate so callers do not cache the empty result.
        include_sitelinks = fetch_bio or fetch_images
        wikidata_info = await self._get_wikidata_info(entity, lang, include_sitelinks)
        wiki_page.data.update(wikidata_info)

        # Extract sitelinks for reuse
        sitelinks = wikidata_info.get("sitelinks") if include_sitelinks else None

        # Secondary fetches are best-effort: a partial page is still cacheable.
        # Catch only network/HTTP errors here so unexpected bugs in our parsers
        # (KeyError, TypeError, etc.) still propagate and get noticed.  Log at
        # warning so repeated upstream failures show up in normal logs.
        if fetch_bio:
            try:
                extract = await self._get_wikipedia_extract(entity, lang, sitelinks)
                if extract:
                    wiki_page.data["extext"] = extract
            except (aiohttp.ClientError, TimeoutError) as error:
                logging.warning("Wikipedia extract fetch failed for %s: %s", entity, error)

        if fetch_images:
            try:
                wikidata_images = await self._get_wikidata_images(entity)
                wikipedia_images = await self._get_wikipedia_images(entity, lang, sitelinks)
                # Limit total images for performance
                all_images = wikidata_images + wikipedia_images
                wiki_page._images = all_images[:max_images]  # pylint: disable=protected-access
            except (aiohttp.ClientError, TimeoutError) as error:
                logging.warning("Wikipedia image fetch failed for %s: %s", entity, error)

        return wiki_page


async def get_page_async(  # pylint: disable=too-many-arguments
    entity: str,
    lang: str = "en",
    timeout: int = 5,
    need_bio: bool = True,
    need_images: bool = True,
    max_images: int = 5,
) -> WikiPage:
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
