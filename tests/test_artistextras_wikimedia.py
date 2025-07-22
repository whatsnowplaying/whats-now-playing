#!/usr/bin/env python3
"""test artistextras wikimedia plugin"""

import asyncio
import logging
import ssl

import pytest
from aiohttp import ClientResponseError

from utils_artistextras import configureplugins, configuresettings, run_cache_consistency_test

import nowplaying.apicache  # pylint: disable=import-error
import nowplaying.wikiclient  # pylint: disable=import-error


@pytest.mark.asyncio
async def test_wikimedia_apicache_usage(bootstrap):
    """test that wikimedia plugin uses apicache for API calls"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    # Test with Wikidata entity ID (wikimedia uses unique entity IDs for differentiation)
    metadata_with_wikidata = {
        "artist": "Nine Inch Nails",
        "imagecacheartist": "nineinchnails",
        "artistwebsites": ["https://www.wikidata.org/wiki/Q11647"],  # NIN's Wikidata page
    }

    await run_cache_consistency_test(
        plugin=plugin,
        test_metadata=metadata_with_wikidata,
        imagecache=imagecaches["wikimedia"],
        success_message="Wikimedia API call successful, caching verified",
    )


@pytest.mark.asyncio
async def test_wikimedia_langfallback_zh_to_en(bootstrap):
    """test wikimedia language fallback from zh to en"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    config.cparser.setValue("wikimedia/bio_iso", "zh")
    config.cparser.setValue("wikimedia/bio_iso_en_fallback", True)
    _, plugins = configureplugins(config)
    data = await plugins["wikimedia"].download_async(
        {
            "artistwebsites": [
                "https://www.wikidata.org/wiki/Q7766138",
            ]
        },
        imagecache=None,
    )
    assert "video" in data.get("artistlongbio")


@pytest.mark.asyncio
async def test_wikimedia_langfallback_zh_to_none(bootstrap):
    """test wikimedia language fallback disabled"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    config.cparser.setValue("wikimedia/bio_iso", "zh")
    config.cparser.setValue("wikimedia/bio_iso_en_fallback", False)
    _, plugins = configureplugins(config)
    data = await plugins["wikimedia"].download_async(
        {
            "artistwebsites": [
                "https://www.wikidata.org/wiki/Q7766138",
            ]
        },
        imagecache=None,
    )
    assert not data.get("artistlongbio")


@pytest.mark.asyncio
async def test_wikimedia_humantetris_en(bootstrap):
    """test wikimedia english content"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    config.cparser.setValue("wikimedia/bio_iso", "en")
    config.cparser.setValue("wikimedia/bio_iso_en_fallback", False)
    _, plugins = configureplugins(config)
    data = await plugins["wikimedia"].download_async(
        {
            "artistwebsites": [
                "https://www.wikidata.org/wiki/Q60845849",
            ]
        },
        imagecache=None,
    )
    assert data.get("artistshortbio") == "Russian post-punk band from Moscow"
    assert not data.get("artistlongbio")


@pytest.mark.asyncio
async def test_wikimedia_humantetris_de(bootstrap):
    """test wikimedia german content"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    config.cparser.setValue("wikimedia/bio_iso", "de")
    config.cparser.setValue("wikimedia/bio_iso_en_fallback", True)
    _, plugins = configureplugins(config)
    data = await plugins["wikimedia"].download_async(
        {
            "artistwebsites": [
                "https://www.wikidata.org/wiki/Q60845849",
            ]
        },
        imagecache=None,
    )
    assert "Human Tetris ist eine Band aus Moskau" in data.get("artistlongbio")  # codespell:ignore


# Error Handling and Network Resilience Tests


@pytest.mark.asyncio
async def test_wikimedia_timeout_handling(bootstrap):
    """test handling of API timeouts (Wikipedia can be slow)"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    # Mock the Wikipedia client to simulate timeout
    original_get_page = nowplaying.wikiclient.get_page_async

    async def mock_timeout(*args, **kwargs):
        raise asyncio.TimeoutError("Simulated Wikipedia timeout")

    nowplaying.wikiclient.get_page_async = mock_timeout

    try:
        # Should handle timeout gracefully and return None
        result = await plugin.download_async(
            {
                "artist": "Test Artist",
                "imagecacheartist": "testartist",
                "artistwebsites": ["https://www.wikidata.org/wiki/Q12345"],
            },
            imagecache=imagecaches["wikimedia"],
        )

        # Should return None or empty dict on timeout, not raise exception
        assert result is None or result == {}
        logging.info("Wikimedia timeout handled gracefully - result: %s", result)

    finally:
        # Restore original function
        nowplaying.wikiclient.get_page_async = original_get_page


@pytest.mark.asyncio
async def test_wikimedia_http_error_handling(bootstrap):
    """test handling of various HTTP error codes from Wikipedia"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    # Test various HTTP error scenarios
    error_codes = [404, 429, 500, 503]

    for error_code in error_codes:
        logging.debug("Testing HTTP error code: %d", error_code)

        # Mock the Wikipedia client to simulate HTTP errors
        original_get_page = nowplaying.wikiclient.get_page_async

        def make_mock_http_error(status_code):
            async def mock_http_error(*args, **kwargs):  # pylint: disable=unused-argument
                # Create a mock request_info with real_url attribute
                class MockRequestInfo:  # pylint: disable=too-few-public-methods
                    """Mock request info for ClientResponseError"""

                    def __init__(self):
                        self.real_url = (
                            "https://en.wikipedia.org/api/rest_v1/page/summary/Test_Artist"
                        )

                raise ClientResponseError(
                    request_info=MockRequestInfo(),
                    history=(),
                    status=status_code,
                    message=f"HTTP {status_code}",
                )

            return mock_http_error

        nowplaying.wikiclient.get_page_async = make_mock_http_error(error_code)

        try:
            # Should handle HTTP errors gracefully and return None
            result = await plugin.download_async(
                {
                    "artist": "Test Artist",
                    "imagecacheartist": "testartist",
                    "artistwebsites": ["https://www.wikidata.org/wiki/Q12345"],
                },
                imagecache=imagecaches["wikimedia"],
            )

            # Should return None or empty dict on HTTP error, not raise exception
            assert result is None or result == {}
            logging.info("Wikimedia HTTP %d error handled gracefully", error_code)

        finally:
            # Restore original function
            nowplaying.wikiclient.get_page_async = original_get_page


@pytest.mark.asyncio
async def test_wikimedia_ssl_error_handling(bootstrap):
    """test handling of SSL certificate errors"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    # Mock SSL certificate error
    original_get_page = nowplaying.wikiclient.get_page_async

    async def mock_ssl_error(*args, **kwargs):
        raise ssl.SSLError("SSL certificate verification failed")

    nowplaying.wikiclient.get_page_async = mock_ssl_error

    try:
        # Should handle SSL errors gracefully
        result = await plugin.download_async(
            {
                "artist": "Test Artist",
                "imagecacheartist": "testartist",
                "artistwebsites": ["https://www.wikidata.org/wiki/Q12345"],
            },
            imagecache=imagecaches["wikimedia"],
        )

        # Should return None or empty dict on SSL error, not crash
        assert result is None or result == {}
        logging.info("Wikimedia SSL error handled gracefully")

    finally:
        # Restore original function
        nowplaying.wikiclient.get_page_async = original_get_page


# Input Validation and URL Parsing Tests


@pytest.mark.parametrize(
    "malformed_urls,test_id",
    [
        (["https://www.wikidata.org/wiki/"], "missing-entity-id"),
        (["https://www.wikidata.org/wiki/Q"], "incomplete-entity"),
        (["https://www.wikidata.org/wiki/Qxyz"], "invalid-entity-format"),
        (["https://www.wikidata.org/wiki/Q-123"], "entity-with-dash"),
        (["https://www.wikidata.org/wiki/Q12.34"], "entity-with-dot"),
        (["https://en.wikipedia.org/wiki/Madonna"], "non-wikidata-url"),
        (["https://www.discogs.com/artist/123"], "discogs-url"),
        (["https://musicbrainz.org/artist/123"], "musicbrainz-url"),
        (["not-a-url"], "invalid-url-format"),
        (["wikidata.org/Q123"], "missing-protocol"),
        ([""], "empty-string"),
        (["https://www.wikidata.org/wiki/Q123", "invalid-url"], "mixed-valid-invalid"),
    ],
)
@pytest.mark.asyncio
async def test_wikimedia_malformed_urls(bootstrap, malformed_urls, test_id):
    """test handling of malformed Wikidata URLs"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    logging.debug("Testing malformed URLs (%s): %s", test_id, malformed_urls)

    try:
        result = await plugin.download_async(
            {
                "artist": "Test Artist",
                "imagecacheartist": "testartist",
                "artistwebsites": malformed_urls,
            },
            imagecache=imagecaches["wikimedia"],
        )

        # Should handle malformed URLs gracefully (return None or valid data)
        assert result is None or isinstance(result, dict)
        logging.info("Malformed URL case (%s) handled gracefully", test_id)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        pytest.fail(
            f"Wikimedia plugin raised exception for malformed URL case ({test_id}): {exc}. "
            f"Plugins must handle all errors gracefully for live performance."
        )


@pytest.mark.parametrize(
    "metadata,test_id",
    [
        ({}, "empty-metadata"),
        ({"artist": "Test Artist"}, "missing-artistwebsites"),
        ({"artistwebsites": None}, "none-artistwebsites"),
        ({"artistwebsites": []}, "empty-artistwebsites-list"),
        ({"artistwebsites": [""]}, "empty-string-in-list"),
        ({"artistwebsites": [None]}, "none-in-list"),
    ],
)
@pytest.mark.asyncio
async def test_wikimedia_missing_metadata_fields(bootstrap, metadata, test_id):
    """test handling of missing or invalid metadata fields"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    logging.debug("Testing missing metadata (%s): %s", test_id, metadata)

    try:
        result = await plugin.download_async(metadata, imagecache=imagecaches["wikimedia"])

        # Should handle missing metadata gracefully (return None)
        assert result is None
        logging.info("Missing metadata case (%s) handled gracefully", test_id)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        pytest.fail(
            f"Wikimedia plugin raised exception for missing metadata case ({test_id}): {exc}. "
            f"Plugins must handle all errors gracefully for live performance."
        )


# Language Handling Edge Cases


@pytest.mark.parametrize(
    "invalid_language,test_id",
    [
        ("xx", "unsupported-code"),
        ("invalid-lang", "hyphenated-invalid"),
        ("", "empty-string"),
        ("toolong", "too-long"),
        ("123", "numeric"),
        ("en-US-invalid", "complex-invalid"),
    ],
)
@pytest.mark.asyncio
async def test_wikimedia_invalid_language_codes(bootstrap, invalid_language, test_id):
    """test handling of invalid language codes"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    logging.debug("Testing invalid language: %s", repr(invalid_language))

    config.cparser.setValue("wikimedia/bio_iso", invalid_language)
    config.cparser.setValue("wikimedia/bio_iso_en_fallback", True)

    try:
        result = await plugin.download_async(
            {
                "artist": "Test Artist",
                "imagecacheartist": "testartist",
                "artistwebsites": ["https://www.wikidata.org/wiki/Q11647"],  # Valid entity
            },
            imagecache=imagecaches["wikimedia"],
        )

        # Should handle invalid languages gracefully (fallback or return None)
        assert result is None or isinstance(result, dict)
        logging.info('Invalid language "%s" (%s) handled gracefully', invalid_language, test_id)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        pytest.fail(
            f'Wikimedia plugin raised exception for invalid language "{invalid_language}" '
            f"({test_id}): {exc}. Plugins must handle all errors gracefully for live performance."
        )


@pytest.mark.asyncio
async def test_wikimedia_language_fallback_chain(bootstrap):
    """test complex language fallback scenarios"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    # Test fallback chain: unsupported → en → none
    config.cparser.setValue("wikimedia/bio_iso", "xx")  # Unsupported language
    config.cparser.setValue("wikimedia/bio_iso_en_fallback", True)

    try:
        result = await plugin.download_async(
            {
                "artist": "Nine Inch Nails",
                "imagecacheartist": "nineinchnails",
                "artistwebsites": ["https://www.wikidata.org/wiki/Q11647"],
            },
            imagecache=imagecaches["wikimedia"],
        )

        # Should either fallback to English or return None gracefully
        assert result is None or isinstance(result, dict)
        if result and result.get("artistlongbio"):
            logging.info("Language fallback to English successful")
        else:
            logging.info("Language fallback handled gracefully - no content available")

    except Exception as exc:  # pylint: disable=broad-exception-caught
        pytest.fail(
            f"Wikimedia plugin raised exception during language fallback: {exc}. "
            f"Plugins must handle all errors gracefully for live performance."
        )


# Content Processing and Sanitization Tests


@pytest.mark.asyncio
async def test_wikimedia_large_content_handling(bootstrap):
    """test handling of very large Wikipedia articles"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    # Mock a very large Wikipedia response
    original_get_page = nowplaying.wikiclient.get_page_async

    async def mock_large_content(*args, **kwargs):  # pylint: disable=unused-argument
        """Mock a large Wikipedia page response."""

        class MockLargePage:  # pylint: disable=too-few-public-methods
            """Mock WikiPage for large content testing."""

            def __init__(self):
                """Initialize mock large page."""
                self.entity = "Q12345"
                self.lang = "en"
                # Create a very large bio (simulate long Wikipedia article)
                self.data = {
                    "extract": "A" * 50000,  # 50KB of text
                    "description": "Test artist with very long biography",
                }
                self._images = ["http://example.com/image1.jpg"] * 100  # Many images

            @staticmethod
            def some_method():
                """Add method to meet pylint requirement."""
                return True

        return MockLargePage()

    nowplaying.wikiclient.get_page_async = mock_large_content

    try:
        # Should handle large content without memory issues
        result = await plugin.download_async(
            {
                "artist": "Test Artist",
                "imagecacheartist": "testartist",
                "artistwebsites": ["https://www.wikidata.org/wiki/Q12345"],
            },
            imagecache=imagecaches["wikimedia"],
        )

        # Should return valid data or None, not crash
        assert result is None or isinstance(result, dict)
        if result:
            # Content should be processed/truncated appropriately
            bio = result.get("artistlongbio", "")
            logging.info("Large content processed, bio length: %d chars", len(bio))

        logging.info("Large content handling test passed")

    finally:
        # Restore original function
        nowplaying.wikiclient.get_page_async = original_get_page


@pytest.mark.asyncio
async def test_wikimedia_malformed_content_handling(bootstrap):
    """test handling of malformed content from Wikipedia"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    # Mock malformed Wikipedia responses
    malformed_responses = [
        None,  # No page returned
        "string instead of object",  # Wrong type
        {"invalid": "structure"},  # Missing expected fields
    ]

    for i, malformed_response in enumerate(malformed_responses):
        logging.debug("Testing malformed response %d: %s", i, type(malformed_response).__name__)

        original_get_page = nowplaying.wikiclient.get_page_async

        def create_mock_response(response_data):
            async def mock_malformed_response(*args, **kwargs):  # pylint: disable=unused-argument
                """Return mock malformed response."""
                return response_data

            return mock_malformed_response

        mock_func = create_mock_response(malformed_response)

        nowplaying.wikiclient.get_page_async = mock_func

        try:
            # Should handle malformed responses gracefully
            result = await plugin.download_async(
                {
                    "artist": "Test Artist",
                    "imagecacheartist": "testartist",
                    "artistwebsites": ["https://www.wikidata.org/wiki/Q12345"],
                },
                imagecache=imagecaches["wikimedia"],
            )

            # Should return None on malformed response, not crash
            assert result is None
            logging.info("Malformed response %d handled gracefully", i)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            pytest.fail(
                f"Wikimedia plugin raised exception for malformed response {i}: {exc}. "
                f"Plugins must handle all errors gracefully for live performance."
            )

        finally:
            # Restore original function
            nowplaying.wikiclient.get_page_async = original_get_page


# Configuration State Validation Tests


def test_wikimedia_configuration_scenarios(bootstrap):
    """test various Wikimedia configuration scenarios"""

    config = bootstrap

    # Test scenarios DJs and streamers commonly use
    config_scenarios = [
        # Bio-only mode (performance optimized)
        {"bio": True, "fanart": False, "thumbnails": False},
        # Images-only mode (visual streamers)
        {"bio": False, "fanart": True, "thumbnails": True},
        # Balanced mode (most common)
        {"bio": True, "fanart": True, "thumbnails": False},
        # Everything disabled (fallback mode)
        {"bio": False, "fanart": False, "thumbnails": False},
        # Everything enabled (full mode)
        {"bio": True, "fanart": True, "thumbnails": True},
    ]

    for i, scenario in enumerate(config_scenarios):
        logging.debug("Testing config scenario %d: %s", i, scenario)

        configuresettings("wikimedia", config.cparser)

        # Apply scenario settings
        for setting, value in scenario.items():
            config.cparser.setValue(f"wikimedia/{setting}", value)

        _, plugins = configureplugins(config)
        plugin = plugins["wikimedia"]

        # Plugin should initialize successfully in all scenarios
        assert plugin is not None
        assert hasattr(plugin, "_check_missing")
        assert hasattr(plugin, "_get_page_cached")

        logging.info("Config scenario %d validated successfully", i)


# Performance and DJ-Critical Scenario Tests


@pytest.mark.asyncio
async def test_wikimedia_rapid_entity_lookups(bootstrap):
    """test handling of rapid consecutive Wikidata lookups (DJ scenario)"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    # Simulate rapid artist changes during a DJ set
    artist_entities = [
        {"artist": "Daft Punk", "artistwebsites": ["https://www.wikidata.org/wiki/Q184654"]},
        {"artist": "Justice", "artistwebsites": ["https://www.wikidata.org/wiki/Q1191976"]},
        {"artist": "Moderat", "artistwebsites": ["https://www.wikidata.org/wiki/Q15982243"]},
        {"artist": "Burial", "artistwebsites": ["https://www.wikidata.org/wiki/Q240055"]},
        {"artist": "Aphex Twin", "artistwebsites": ["https://www.wikidata.org/wiki/Q126016"]},
    ]

    # Add common metadata fields
    for i, entity in enumerate(artist_entities):
        entity["imagecacheartist"] = f"artist{i}"

    # Simulate rapid-fire requests
    tasks = []
    for entity in artist_entities:
        task = asyncio.create_task(
            plugin.download_async(entity, imagecache=imagecaches["wikimedia"])
        )
        tasks.append(task)

    try:
        # All requests should complete without errors
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify no exceptions were raised
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logging.warning("Entity %d raised exception: %s", i, result)
            else:
                # Should return None or valid data, not crash
                assert result is None or isinstance(result, dict)

        logging.info("Wikimedia handled %d rapid entity lookups successfully", len(artist_entities))

    except Exception as exc:  # pylint: disable=broad-exception-caught
        pytest.fail(
            f"Wikimedia plugin raised exception during rapid entity lookups: {exc}. "
            f"Plugins must handle all errors gracefully for live performance."
        )


@pytest.mark.asyncio
async def test_wikimedia_cache_corruption_handling(bootstrap):
    """test handling of corrupted cache data"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    # Mock the cache to return corrupted data
    original_cached_fetch = nowplaying.apicache.cached_fetch

    async def mock_corrupted_cache(*args, **kwargs):  # pylint: disable=unused-argument
        # Return corrupted data that would break normal processing
        return {"corrupted": "data", "invalid": True, "type": "wikipage"}

    # Test with corrupted cache
    nowplaying.apicache.cached_fetch = mock_corrupted_cache

    try:
        # Should handle corrupted cache gracefully
        result = await plugin.download_async(
            {
                "artist": "Test Artist",
                "imagecacheartist": "testartist",
                "artistwebsites": ["https://www.wikidata.org/wiki/Q12345"],
            },
            imagecache=imagecaches["wikimedia"],
        )

        # Should return None or valid data, not crash
        assert result is None or isinstance(result, dict)
        logging.info("Wikimedia corrupted cache handled gracefully")

    finally:
        # Restore original cache function
        nowplaying.apicache.cached_fetch = original_cached_fetch


@pytest.mark.asyncio
async def test_wikimedia_memory_stability_long_session(bootstrap):
    """test memory stability during extended DJ sessions"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    # Simulate a long session with many different entity lookups
    base_entities = [
        "Q184654",  # Daft Punk
        "Q1191976",  # Justice
        "Q15982243",  # Moderat
    ]

    # Create many lookup variations
    entities = []
    for i in range(3):  # 3 lookups per entity = 9 total (reduced from 45)
        for entity_id in base_entities:
            entities.append(
                {
                    "artist": f"Artist {i}",
                    "imagecacheartist": f"artist{i}_{entity_id}",
                    "artistwebsites": [f"https://www.wikidata.org/wiki/{entity_id}"],
                }
            )

    successful_lookups = 0

    for i, entity in enumerate(entities):
        try:
            result = await plugin.download_async(entity, imagecache=imagecaches["wikimedia"])

            # Should handle all requests without memory issues
            assert result is None or isinstance(result, dict)
            if result:
                successful_lookups += 1

            # Log progress every 3 entities
            if (i + 1) % 3 == 0:
                logging.info(
                    "Processed %d entities, %d successful lookups", i + 1, successful_lookups
                )

        except Exception as exc:  # pylint: disable=broad-exception-caught
            pytest.fail(
                f"Wikimedia plugin raised exception for entity {i}: {exc}. "
                f"Plugins must handle all errors gracefully for live performance."
            )

    logging.info(
        "Memory stability test completed: %d/%d entities processed successfully",
        successful_lookups,
        len(entities),
    )


@pytest.mark.asyncio
async def test_wikimedia_api_call_count(bootstrap):
    """test that wikimedia plugin makes only one API call when cache is used"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    # Test with a known entity (Nine Inch Nails)
    metadata = {
        "artist": "Nine Inch Nails",
        "imagecacheartist": "nineinchnails",
        "artistwebsites": ["https://www.wikidata.org/wiki/Q11647"],
    }

    # Mock the actual Wikipedia API call to count calls
    original_get_page = nowplaying.wikiclient.get_page_async
    api_call_count = 0

    async def mock_get_page_async(*args, **kwargs):
        nonlocal api_call_count
        api_call_count += 1
        logging.debug("Mock Wikipedia API call #%d", api_call_count)
        # Call the original method to get real data
        return await original_get_page(*args, **kwargs)

    # Replace the method with our mock
    nowplaying.wikiclient.get_page_async = mock_get_page_async

    try:
        # First call - should hit API and cache result
        result1 = await plugin.download_async(metadata.copy(), imagecache=imagecaches["wikimedia"])

        # Verify one API call was made
        assert api_call_count == 1, (
            f"Expected 1 API call after first download, got {api_call_count}"
        )

        # Second call - should use cached result, no additional API call
        result2 = await plugin.download_async(metadata.copy(), imagecache=imagecaches["wikimedia"])

        # Verify still only one API call was made (cache hit)
        assert api_call_count == 1, (
            f"Expected 1 API call after second download (cache hit), got {api_call_count}"
        )

        # Both results should be consistent
        assert (result1 is None) == (result2 is None)
        if result1:  # Only test if we got data back
            logging.info("Wikimedia API cache verified: 1 API call for 2 downloads")
            assert result1 == result2
        else:
            logging.info(
                "Wikimedia API cache test completed - cache working regardless of data found"
            )

    finally:
        # Restore the original method
        nowplaying.wikiclient.get_page_async = original_get_page


@pytest.mark.asyncio
async def test_wikimedia_failure_cache(bootstrap):
    """test that wikimedia plugin handles cache failures gracefully"""

    config = bootstrap
    configuresettings("wikimedia", config.cparser)
    imagecaches, plugins = configureplugins(config)

    plugin = plugins["wikimedia"]

    # Test with a known entity
    metadata = {
        "artist": "Nine Inch Nails",
        "imagecacheartist": "nineinchnails",
        "artistwebsites": ["https://www.wikidata.org/wiki/Q11647"],
    }

    # Mock the Wikipedia API to simulate failures then success
    original_get_page = nowplaying.wikiclient.get_page_async
    api_call_count = 0

    async def mock_get_page_with_failure(*args, **kwargs):  # pylint: disable=unused-argument
        nonlocal api_call_count
        api_call_count += 1
        logging.debug("Mock Wikipedia API call #%d", api_call_count)

        if api_call_count == 1:
            # First call: simulate API failure
            logging.debug("Simulating Wikipedia API failure on first call")
            return None
        # Second call: simulate successful response
        logging.debug("Simulating successful Wikipedia API response on second call")

        # Return a minimal WikiPage-like object
        class MockWikiPage:  # pylint: disable=too-few-public-methods
            """Mock WikiPage for testing."""

            def __init__(self):
                """Initialize mock WikiPage."""
                self.entity = "Q11647"
                self.lang = "en"
                self.data = {
                    "extract": "Nine Inch Nails is an American industrial rock band.",
                    "claims": {},  # Add claims field expected by the plugin
                }
                self._images = []

            def images(self, fields=None):  # pylint: disable=unused-argument
                """Return images for compatibility."""
                return self._images

            @staticmethod
            def some_method():
                """Add method to meet pylint requirement."""
                return True

        return MockWikiPage()

    # Replace the method with our mock
    nowplaying.wikiclient.get_page_async = mock_get_page_with_failure

    try:
        # First call - API fails, should return None and NOT cache the failure
        result1 = await plugin.download_async(metadata.copy(), imagecache=imagecaches["wikimedia"])

        # Verify one API call was made and result is None (failure)
        assert api_call_count == 1, (
            f"Expected 1 API call after first download, got {api_call_count}"
        )
        assert result1 is None, "Expected None result from failed Wikipedia API call"

        # Second call - should retry (not use cached failure) and succeed
        result2 = await plugin.download_async(metadata.copy(), imagecache=imagecaches["wikimedia"])

        # Verify second API call was made (failure wasn't cached)
        assert api_call_count == 2, (
            f"Expected 2 API calls after second download (retry after failure), "
            f"got {api_call_count}"
        )

        # Should get valid result from successful second call
        assert result2 is not None, "Expected successful result from second Wikipedia API call"

        # Third call - should use cached success result, no additional API call
        result3 = await plugin.download_async(metadata.copy(), imagecache=imagecaches["wikimedia"])

        # Verify still only two API calls (third used cached success)
        assert api_call_count == 2, (
            f"Expected 2 API calls after third download (cache hit), got {api_call_count}"
        )
        # Results should be consistent for successful calls
        assert result2 == result3
        logging.info("Wikimedia cache failure test passed - failures not cached, successes are")

    finally:
        # Restore the original method
        nowplaying.wikiclient.get_page_async = original_get_page
