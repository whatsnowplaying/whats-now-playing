#!/usr/bin/env python3
"""tests for the per-artist image count caps in artistextras"""

import pathlib
import tempfile

import pytest
import pytest_asyncio

import nowplaying.artistextras
import nowplaying.datacache
from tests.utils_images import png_bytes

MINIMAL_PNG = png_bytes()


def _plugin(config) -> nowplaying.artistextras.ArtistExtrasPlugin:
    """A bare plugin bound to a real config, bypassing plugin bootstrap.

    The config comes from the bootstrap fixture rather than a mock: _trim_to_wanted
    reads artistextras/<data_type> with no fallback of its own, so the thing worth
    testing is that a real ConfigFile answers those reads.
    """
    plugin = nowplaying.artistextras.ArtistExtrasPlugin.__new__(
        nowplaying.artistextras.ArtistExtrasPlugin
    )
    plugin.config = config
    return plugin


async def _store(client, identifier: str, imagetype: str, count: int) -> None:
    """Put count images of imagetype into the cache for identifier."""
    for index in range(count):
        await client.storage.store(
            url=f"https://example.com/{identifier}/{imagetype}/{index}.png",
            identifier=identifier,
            data_type=imagetype,
            provider="cdn",
            data_value=MINIMAL_PNG,
            ttl_seconds=3600,
        )


@pytest_asyncio.fixture(name="client")
async def client_fixture():
    """A DataCacheClient backed by a throwaway directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        client = nowplaying.datacache.DataCacheClient(pathlib.Path(temp_dir))
        await client.initialize()
        yield client
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wanted,already_cached,offered,expected",
    [
        (6, 0, 10, 6),  # fresh artist: take the allowance
        (6, 2, 10, 4),  # partially filled: only the shortfall
        (6, 6, 10, 0),  # satisfied: contribute nothing
        (6, 9, 10, 0),  # already over (concurrent first play): never negative
        (0, 0, 10, 0),  # zero disables the type entirely
        (6, 0, 3, 3),  # provider offers fewer than allowed
    ],
)
async def test_trim_to_wanted(  # pylint: disable=too-many-arguments
    bootstrap, client, wanted, already_cached, offered, expected
):
    """Only the shortfall between wanted and cached is queued."""
    bootstrap.cparser.setValue("artistextras/artistlogo", wanted)
    plugin = _plugin(bootstrap)
    await _store(client, "wnpmockartist", "artistlogo", already_cached)
    urls = [f"https://cdn.example.com/new/{i}.png" for i in range(offered)]

    trimmed = await plugin._trim_to_wanted(  # pylint: disable=protected-access
        client, "wnpmockartist", "artistlogo", urls
    )
    assert len(trimmed) == expected
    # the provider ranks best-first, so the survivors must be the head of the list
    assert trimmed == urls[:expected]


@pytest.mark.asyncio
async def test_count_is_shared_across_providers(bootstrap, client):
    """The cap counts every provider's contributions, not each one separately."""
    bootstrap.cparser.setValue("artistextras/artistlogo", 6)
    plugin = _plugin(bootstrap)
    # theaudiodb got there first and filled four slots
    await _store(client, "wnpmockartist", "artistlogo", 4)

    urls = [f"https://cdn.example.com/fanarttv/{i}.png" for i in range(10)]
    trimmed = await plugin._trim_to_wanted(  # pylint: disable=protected-access
        client, "wnpmockartist", "artistlogo", urls
    )
    assert len(trimmed) == 2, "a second provider may only fill the remaining slots"


@pytest.mark.asyncio
async def test_cap_is_per_artist(bootstrap, client):
    """One artist filling its allowance does not starve another."""
    bootstrap.cparser.setValue("artistextras/artistlogo", 6)
    plugin = _plugin(bootstrap)
    await _store(client, "wnpmockartist1", "artistlogo", 6)

    urls = [f"https://cdn.example.com/new/{i}.png" for i in range(10)]
    assert not await plugin._trim_to_wanted(  # pylint: disable=protected-access
        client, "wnpmockartist1", "artistlogo", urls
    )
    assert (
        len(
            await plugin._trim_to_wanted(  # pylint: disable=protected-access
                client, "wnpmockartist2", "artistlogo", urls
            )
        )
        == 6
    )


@pytest.mark.asyncio
async def test_cap_is_per_image_type(bootstrap, client):
    """Filling one type does not consume another type's allowance."""
    bootstrap.cparser.setValue("artistextras/artistlogo", 6)
    bootstrap.cparser.setValue("artistextras/artistthumbnail", 6)
    plugin = _plugin(bootstrap)
    await _store(client, "wnpmockartist", "artistlogo", 6)

    urls = [f"https://cdn.example.com/new/{i}.png" for i in range(10)]
    assert (
        len(
            await plugin._trim_to_wanted(  # pylint: disable=protected-access
                client, "wnpmockartist", "artistthumbnail", urls
            )
        )
        == 6
    )


@pytest.mark.asyncio
async def test_uncapped_type_passes_through(bootstrap, client):
    """front_cover has no per-artist count; it must pass through untouched."""
    plugin = _plugin(bootstrap)
    urls = [f"https://cdn.example.com/new/{i}.png" for i in range(10)]
    trimmed = await plugin._trim_to_wanted(  # pylint: disable=protected-access
        client, "wnpmockartist", "front_cover", urls
    )
    assert trimmed == urls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "imagetype,expected",
    [
        ("artistbanner", 6),
        ("artistlogo", 6),
        ("artistthumbnail", 6),
        ("artistfanart", 50),
    ],
)
async def test_shipped_defaults_apply(bootstrap, client, imagetype, expected):
    """An untouched config caps at the shipped default.

    _trim_to_wanted passes no defaultValue, so a type whose default went
    unregistered would read 0 and silently queue nothing at all.
    """
    plugin = _plugin(bootstrap)
    urls = [f"https://cdn.example.com/new/{i}.png" for i in range(100)]

    trimmed = await plugin._trim_to_wanted(  # pylint: disable=protected-access
        client, "wnpmockartist", imagetype, urls
    )
    assert len(trimmed) == expected


def test_every_capped_type_has_a_default(bootstrap):
    """Each capped type must have a default registered, per the config.py rule."""
    for imagetype in nowplaying.datacache.utils.CAPPED_IMAGE_TYPES:
        key = f"artistextras/{imagetype}"
        assert bootstrap.cparser.value(key, type=int) > 0, f"{key} has no usable default"
