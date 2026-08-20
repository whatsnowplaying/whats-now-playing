#!/usr/bin/env python3
"""Input Plugin definition"""

import contextlib
import sys
from typing import TYPE_CHECKING

import nowplaying.datacache
import nowplaying.datacache.utils
import nowplaying.utils
from nowplaying.plugin import WNPBasePlugin
from nowplaying.types import TrackMetadata

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    import nowplaying.config
    import nowplaying.datacache.client

_IMAGE_TTL = 14 * 24 * 3600  # 14 days — images change infrequently

# Queue priority by data type: lower = fetched sooner.
# cover > logos/banners/thumbs > fanart mirrors the imagecache scheme.
# Within each tier, newest-queued (currently playing) comes first.
_IMAGE_PRIORITY: dict[str, int] = {
    "front_cover": 2,
    "artistthumbnail": 3,
    "artistlogo": 3,
    "artistbanner": 3,
    "artistfanart": 4,
}

# Types with a per-artist cap, each read from artistextras/<data_type>.
# front_cover is the exception: it is per-album rather than per-artist, and one
# album has one cover, so there is nothing to cap.
#
# Every retrieval path uses random=True, so for the single-image types more art
# is worse, not better: the provider returns its list best-first, and each extra
# entry dilutes the good one in the rotation.  Fanart is the exception -- variety
# is the whole point there -- hence its much larger default.
_CAPPED_IMAGE_TYPES: frozenset[str] = nowplaying.datacache.utils.IMAGE_DATA_TYPES - {"front_cover"}


class ArtistExtrasPlugin(WNPBasePlugin):
    """base class of plugins"""

    def __init__(
        self,
        config: "nowplaying.config.ConfigFile | None" = None,
        qsettings: "QWidget | None" = None,
    ):
        super().__init__(config=config, qsettings=qsettings)
        self.plugintype: str = "artistextras"
        self._datacache_client: "nowplaying.datacache.client.DataCacheClient | None" = None

    def _get_datacache_client(self) -> "nowplaying.datacache.client.DataCacheClient":
        """Return the shared DataCacheClient, creating it on first use."""
        if self._datacache_client is None:
            self._datacache_client = nowplaying.datacache.get_client()
        return self._datacache_client

    requires_apikey: bool = True

    #### Plug-in methods

    async def download_async(  #  pylint: disable=no-self-use,unused-argument
        self, metadata: TrackMetadata | None = None
    ) -> TrackMetadata | None:
        """return metadata (async version) - override this in async plugins"""
        return None

    def providerinfo(self) -> list[str] | None:  # pylint: disable=no-self-use, unused-argument
        """return list of what is provided by this recognition system"""
        return None

    #### Utilities

    async def queue_artist_image(
        self,
        identifier: str,
        imagetype: str,
        urls: list[str],
        provider: str,  # pylint: disable=unused-argument
    ) -> None:
        """Queue artist image URLs into datacache for background download."""
        normalidentifier = nowplaying.utils.normalize(identifier, sizecheck=0, nospaces=True)
        if not normalidentifier or not urls:
            return
        client = self._get_datacache_client()
        urls = await self._trim_to_wanted(client, normalidentifier, imagetype, urls)
        if not urls:
            return
        # First URL gets the type's normal priority (best image by popularity).
        # Remaining URLs are deferred to fanart priority so a mix of types
        # downloads before the bulk of any single type.
        first_priority = _IMAGE_PRIORITY.get(imagetype, 3)
        bulk_priority = _IMAGE_PRIORITY["artistfanart"]
        for i, url in enumerate(urls):
            await client.get_or_fetch(
                nowplaying.datacache.FetchRequest(
                    url=url,
                    identifier=normalidentifier,
                    data_type=imagetype,
                    provider="cdn",
                    immediate=False,
                    ttl_seconds=_IMAGE_TTL,
                    negative_ttl=3600,
                    queue_priority=first_priority if i == 0 else bulk_priority,
                )
            )

    async def _trim_to_wanted(
        self,
        client: "nowplaying.datacache.client.DataCacheClient",
        identifier: str,
        imagetype: str,
        urls: list[str],
    ) -> list[str]:
        """Drop URLs beyond the configured count already cached for this artist.

        The count is per artist and per type across every provider, not per
        provider: several services supply the same type, so a per-call limit
        multiplies by however many are enabled.

        Providers run concurrently, so on an artist's first play each one sees an
        empty cache and contributes its full allowance.  That overshoot is
        deliberate -- later plays see the filled cache and add nothing, so the
        count settles rather than binding exactly, and it avoids a queue lookup on
        the live path.
        """
        if imagetype not in _CAPPED_IMAGE_TYPES:
            return urls
        # config.defaults() registers artistextras/<data_type> for each of these on
        # every ConfigFile build, so there is no default to repeat here.
        wanted = self.config.cparser.value(f"artistextras/{imagetype}", type=int)
        if wanted <= 0:
            return []
        existing = len(await client.storage.get_cache_keys_for_identifier(identifier, imagetype))
        return urls[: max(0, wanted - existing)]

    async def queue_front_cover(
        self,
        artist: str,
        album: str,
        cover_url: str,
        provider: str,  # pylint: disable=unused-argument
    ) -> None:
        """Queue a cover art URL into datacache for background download."""
        norm_artist = nowplaying.utils.normalize(artist, sizecheck=0, nospaces=True)
        norm_album = nowplaying.utils.normalize(album, sizecheck=0, nospaces=True)
        if not norm_artist or not norm_album or not cover_url:
            return
        identifier = f"{norm_artist}_{norm_album}"
        client = self._get_datacache_client()
        await client.get_or_fetch(
            nowplaying.datacache.FetchRequest(
                url=cover_url,
                identifier=identifier,
                data_type="front_cover",
                provider="cdn",
                immediate=False,
                queue_priority=_IMAGE_PRIORITY["front_cover"],
                ttl_seconds=_IMAGE_TTL,
            )
        )

    def calculate_delay(self) -> float:
        """determine a reasonable, minimal delay"""

        delay: float = 10.0

        with contextlib.suppress(ValueError):
            delay = self.config.cparser.value("settings/delay", type=float, defaultValue=10.0)

        if sys.platform == "win32":
            delay = max(delay / 2, 10)
        else:
            delay = max(delay / 2, 5)

        return delay
