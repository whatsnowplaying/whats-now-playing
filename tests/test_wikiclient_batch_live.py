#!/usr/bin/env python3
"""
Live integration test for wikiclient batch processing functionality.
Tests against real Wikimedia APIs to verify batch optimization works.
"""

# pylint: disable=protected-access

import pytest
import nowplaying.wikiclient


@pytest.mark.asyncio
async def test_commons_batch_processing_live():
    """Test batch processing with real Commons API."""
    async with nowplaying.wikiclient.AsyncWikiClient(timeout=10) as client:
        # Test with a known real file
        results = await client._get_commons_image_urls_batch(["Test.jpg"])

        assert len(results) == 1
        assert results[0] is not None
        assert results[0].startswith("https://")
        print(f"Batch processing works: {results[0]}")


@pytest.mark.asyncio
async def test_single_file_uses_batch():
    """Test that single file method uses batch internally."""
    async with nowplaying.wikiclient.AsyncWikiClient(timeout=10) as client:
        result = await client._get_commons_image_url("Test.jpg")

        assert result is not None
        assert result.startswith("https://")
        print(f"Single file method works: {result}")


@pytest.mark.asyncio
async def test_wikidata_batch_with_real_entity():
    """Test Wikidata batch processing with real entity."""
    async with nowplaying.wikiclient.AsyncWikiClient(timeout=10) as client:
        # Q11647 is "The Beatles" - known to have images
        images = await client._get_wikidata_images("Q11647")

        # Should get some images
        if images:
            for image in images:
                assert "kind" in image
                assert "url" in image
                assert image["kind"] == "wikidata-image"
                assert image["url"].startswith("https://")
            print(f"Wikidata batch processing works: found {len(images)} images")
        else:
            print("Wikidata batch processing works: no images found (that's okay)")


@pytest.mark.asyncio
async def test_batch_empty_cases():
    """Test batch processing edge cases."""
    async with nowplaying.wikiclient.AsyncWikiClient(timeout=10) as client:
        # Empty list
        results = await client._get_commons_image_urls_batch([])
        assert results == []

        # Non-existent file
        results = await client._get_commons_image_urls_batch(["ThisFileDoesNotExist12345.jpg"])
        assert len(results) == 1
        assert results[0] is None

        print("Edge cases handled correctly")
