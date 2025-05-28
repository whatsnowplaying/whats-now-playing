# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Development Commands

### Testing

- `pytest` - Run all tests (both tests-qt and tests directories)
- `pytest tests/` - Run only non-Qt tests
- `pytest tests-qt/` - Run only Qt-based tests
- `pytest tests/test_specific.py` - Run a single test file
- `pytest -k "test_name"` - Run tests matching pattern

### Code Quality

- `pylint nowplaying/` - Run linting on the main package
- `pyright` - Type checking (configured in pyproject.toml)
- `yapf --diff .` - Check code formatting
- `yapf -i .` - Apply code formatting

### Build and Distribution

- `python -m nowplaying` - Run the application from source
- `pyinstaller nowplaying.pyproject` - Build standalone executable

### Git and Pull Requests

**CRITICAL**: This repository is a fork of `e1miran/Now-Playing-Serato`.

- **NEVER** create pull requests against the upstream `e1miran/Now-Playing-Serato` repository
- **ALWAYS** create pull requests within this fork using: `gh pr create --repo whatsnowplaying/whats-now-playing`
- All development and PRs should stay within the `whatsnowplaying` organization

## Architecture Overview

This is a Python 3.10/Qt6 desktop application for streaming DJs to display "now
playing" information from various DJ software.

### Core Components

**Main Application Flow:**

- `nowplaying/__main__.py` - Entry point, handles PID locking and Qt app
  lifecycle
- `nowplaying/bootstrap.py` - Logging setup and initial configuration
- `nowplaying/systemtray.py` - System tray interface and main UI controller
- `nowplaying/config.py` - Configuration management using Qt QSettings

**Plugin Architecture:**

- `nowplaying/plugin.py` - Base plugin class (WNPBasePlugin)
- Input plugins in `nowplaying/inputs/` - Read track data from DJ software
  (Serato, Traktor, etc.)
- Output processes in `nowplaying/processes/` - Send data to various
  destinations (OBS, Twitch, Discord)
- Artist extras in `nowplaying/artistextras/` - Fetch additional metadata
  (Discogs, FanartTV, etc.)
- Recognition plugins in `nowplaying/recognition/` - Audio fingerprinting for
  track identification

**Key Subsystems:**

- Template system for customizable output formatting
- SQLite database for metadata caching (`db.py`)
- API response caching system (`apicache.py`) with TTL support for external
  services
- WebSocket server for real-time data streaming
- Track request system for audience interaction
- Async Wikipedia/Wikidata client (`wikiclient.py`) optimized for live
  performance

### Testing Setup

The test suite uses pytest with Qt support and includes fixtures for:

- Temporary configuration directories (`bootstrap` fixture)
- Qt application lifecycle management
- Cross-platform preference cleanup (especially macOS caching)

Key testing patterns:

- Tests are split into `tests/` (non-Qt) and `tests-qt/` (Qt-dependent)
- Async tests use `@pytest.mark.asyncio` with `asyncio_mode = "strict"`
- Custom markers for specialized test configurations
- Coverage reporting configured to exclude vendor code and generated files
- `asyncio_default_fixture_loop_scope = "function"` for proper async test
  isolation

**Test Architecture and Shared Utilities:**

- Shared test utilities in `tests/utils_artistextras.py` for artistextras
  plugin testing
- Centralized pytest.mark.skipif decorators for API key requirements:
  - `skip_no_discogs_key`, `skip_no_fanarttv_key`, `skip_no_theaudiodb_key`, `skip_no_acoustid_key`
- Reusable cache testing helpers: `run_cache_consistency_test()`,
  `run_api_call_count_test()`, `run_failure_cache_test()`
- Standard plugin configuration helpers: `configureplugins()`, `configuresettings()`

**Reliability Testing for DJ Critical Components:**

Since most DJs rely on Discogs for metadata, comprehensive reliability
testing is essential:

- **Error handling tests**: Network timeouts, HTTP errors, malformed responses
- **Input validation tests**: Special characters, Unicode, long strings, edge cases
- **Live performance scenarios**: Rapid track changes, timeout recovery, memory stability
- **DJ-specific genre testing**: Electronic music with symbols (µ-Ziq),
  featuring artists, international accents
- **Configuration validation**: Performance vs visual configs commonly used by DJs
- **Cache failure scenarios**: Corrupted data handling, TTL expiration,
  cleanup on errors

**Critical DJ Software Requirement - No Exceptions During Live Performance:**

DJ software cannot crash during live performances. All artistextras plugins must
handle ALL error conditions gracefully (return None/empty data) rather than
raising exceptions. Tests enforce this with `pytest.fail()` if any exceptions
occur:

```python
try:
    result = await plugin.download_async(metadata, imagecache=imagecache)
    assert result is None or isinstance(result, dict)
except Exception as exc:  # pylint: disable=broad-exception-caught
    pytest.fail(f'Plugin raised exception: {exc}. '
               f'Plugins must handle all errors gracefully for live performance.')
```

**Testing Best Practices:**

- Always run `pylint` after adding new tests to maintain code quality
- Use `pytest.fail()` instead of logging warnings when plugins raise exceptions
- Test malformed data extensively - DJs encounter inconsistent metadata
- Focus on edge cases that could occur during live DJ sets
- Use proper import organization (all imports at top of file, not inline)
- Mock external API calls to test error conditions reliably
- Test both happy path and failure scenarios for production reliability
- Use meaningful test names that clearly indicate what scenario is being tested

**Test Coverage Requirements for Artistextras Plugins:**

Each artistextras plugin should have comprehensive test coverage including:

1. **API Call Count Tests** - Verify caching works (1 API call, 2+ downloads)
2. **Cache Consistency Tests** - Verify repeated calls return identical data
3. **Error Handling Tests** - Malformed responses, timeouts, HTTP errors
4. **Input Validation Tests** - Invalid metadata, malformed URLs, edge cases
5. **DJ Performance Tests** - Rapid track changes, memory stability
6. **Configuration Tests** - Various DJ setups (bio-only, images-only, etc.)
7. **Fallback Tests** - Invalid MBIDs → name-based search (TheAudioDB)
8. **Duplicate Artist Tests** - Handle multiple artists with same name (Madonna)

Key files with comprehensive coverage examples:

- `tests/test_artistextras_discogs.py` (~1200 lines, 30+ tests)
- `tests/test_artistextras_wikimedia.py` (20+ tests covering edge cases)
- `tests/test_artistextras_theaudiodb.py` (includes critical fallback testing)
- `tests/test_musicbrainz.py` (25+ tests for complex artist scenarios)

### Development Notes

- Qt6/PySide6 is used for the GUI framework
- Configuration uses Qt's QSettings with cross-platform support
- Plugins are dynamically loaded and follow a common interface pattern
- The application uses multiprocessing for background tasks
- Vendor dependencies are managed in `nowplaying/vendor/` to avoid conflicts

**Python Version and Type Annotations:**

- Target Python 3.10 as the base version
- Use Python 3.10+ union syntax (`X | Y`) instead of `Union[X, Y]`
- Use Python 3.10+ optional syntax (`X | None`) instead of `Optional[X]`
- Use built-in generics (`dict`, `list`) instead of `typing.Dict`, `typing.List`

**Import Style Guidelines:**

- For non-vendored code, prefer explicit module imports over `from` imports
- Example: Use `import nowplaying.wikiclient` instead of
  `from nowplaying import wikiclient`
- This improves code clarity and reduces namespace pollution
- **CRITICAL**: NEVER import modules in the middle of functions! Always add
  imports at the top of the file. Check existing imports before adding new ones
  to avoid duplicates.

### Performance Requirements

This application handles time-sensitive data retrieval and display that must be
available as soon as possible to sync with live music performance. When
developing:

**Critical Performance Considerations:**

- Minimize blocking operations in the main data flow paths
- Avoid network calls in time-critical polling/update cycles
- Test performance impacts of any changes that affect track detection or output
  delivery
- Be mindful of polling intervals and update frequencies
- Prioritize low-latency data paths from input plugins to output processes

**Real-time Components:**

- Track polling system (`processes/trackpoll.py`) for continuous DJ software
  monitoring
- WebSocket streaming for immediate data delivery to OBS and other outputs
- Direct file format parsing to avoid API dependencies during live performance
- Caching systems (metadata DB, image cache, API cache) to prevent repeated
  lookups during shows
- Optimized Wikipedia/Wikidata client with configuration-based selective
  fetching to minimize API calls

### External API Integration

**Wikipedia/Wikidata Client (`wikiclient.py`):**

- Async client replacing wptools with performance optimizations for live use
- Configuration-aware selective fetching (only fetches bio/images if enabled)
- Combined API requests to reduce call count by 40-60%
- Reduced timeouts (5s) and image limits (5 max) for live performance
- Uses existing `apicache.py` system (24-hour TTL) for response caching
- Provides both async interface and sync compatibility wrapper
- SSL certificate handling for reliability across environments

**Discogs Client (`discogsclient.py`):**

- Async client replacing vendored `discogs_client` library with performance
  optimizations
- Full backward compatibility as drop-in replacement for
  `nowplaying.vendor.discogs_client`
- Configuration-aware optimization based on enabled plugin features
  (bio/images)
- Performance limits: 10 search results max, 5 images per artist, 3 artists
  loaded per search
- Automatic full artist data loading with smart filtering (primary images
  prioritized)
- Reduced timeouts (5s default) and API call optimization for live performance
- Proper SSL context handling and configurable timeouts
- Reduces dependency footprint by eliminating large vendored library
- Uses aiohttp for non-blocking API calls with 6-20% performance improvement
- Configurable strict album matching (`musicbrainz/strict_album_matching`) to
  control precision vs recall tradeoffs

**MusicBrainz Client (`musicbrainzclient.py`):**

- Streamlined async client replacing vendored `musicbrainzngs` library
- Implements only the 9 methods actually used by nowplaying for minimal
  footprint
- Optimized for live performance with 15-second timeouts and reduced complexity
- Full async/await support with aiohttp for non-blocking API calls
- Proper SSL certificate verification with Python 3.11.12 + aiohttp 3.12.0
- XML response parsing with error handling for API reliability
- Integrates with existing `apicache.py` system for response caching via
  `musicbrainz.py`
- Eliminates large vendored dependency while maintaining full functionality

**Async Performance Architecture:**

- **ZERO THREADS**: Complete elimination of ThreadPoolExecutor and
  concurrent.futures
- All artist plugins (`discogs.py`, `theaudiodb.py`, `fanarttv.py`,
  `wikimedia.py`) converted to async
- Native async execution in `metadata.py` with pure `asyncio.create_task()`
  concurrency
- **Performance gains**: 20-60 seconds (sequential blocking) → 5-15 seconds
  (concurrent async)
- Dynamic timeout calculation and early completion detection for optimized
  processing
- Configuration-aware selective fetching across all plugins to minimize API
  calls
- Unified async interface with `download_async()` method across all plugins
- Multiple dedicated aiohttp sessions per service for maximum parallel
  performance
- **Pure async-only architecture**: All legacy sync methods removed from
  artistextras plugins

**SSL Certificate Handling:**

- All async clients use proper SSL certificate verification (no workarounds
  needed)
- Resolved with Python 3.11.12 + aiohttp 3.12.0 + updated CA certificates
- Eliminated permissive SSL fallbacks that were needed in older environment

**Usage Patterns:**

- Use `get_page_for_nowplaying()` for optimized Wikipedia data fetching
- Use `get_optimized_client_for_nowplaying()` for performance-tuned Discogs
  access
- All async clients automatically adapt behavior based on plugin configuration
  settings
- Clients maintain backward compatibility with existing sync interfaces where
  needed
- All leverage existing `apicache.py` system for response caching
- Performance optimizations are automatic - no manual configuration required

**API Response Caching (`apicache.py`):**

- Fast SQLite-based cache for external API responses with TTL support using
  aiosqlite
- Comprehensive caching integration across all artistextras plugins
- Provides `cached_fetch()` unified interface for consistent caching patterns
- Provider-specific TTL settings: Discogs (24h), TheAudioDB/FanartTV (7d),
  Wikimedia (24h)
- Advanced duplicate artist handling with unique cache key strategies:

  - **Discogs**: Artist+album combination caching with object reconstruction
    for search results
  - **TheAudioDB**: Two-level caching (search results + individual artist IDs)
    to prevent collisions
  - **FanartTV**: MusicBrainz ID-based caching (optimal - globally unique
    identifiers)
  - **Wikimedia**: Wikidata entity+language caching with WikiPage object
    reconstruction

- Artist name normalization for consistent cache lookups (handles case
  variations like "sELF" vs "Self")
- JSON serialization with custom object reconstruction to preserve API client
  object behavior
- Race condition prevention with proper async database initialization
- Cache statistics and cleanup capabilities for maintenance
- Thread-safe with asyncio.Lock for concurrent access
- Global instance available via `get_cache_instance()` for application-wide
  use
- Cache files stored in Qt standard cache location, not in project directory
- Binary data serialization support with base64 encoding for MusicBrainz
  cover art data
- SQLite VACUUM operations on application shutdown to reclaim disk space
- GUI "Clear Cache" button in Artist Extras settings clears both API cache and
  image cache files

**Duplicate Artist Resolution:**

Critical for DJ applications where artist names often collide (e.g., multiple
"Madonna" artists):

- **Discogs**: Uses album title in cache key (`search_title_{album}`) to
  distinguish between artists
- **TheAudioDB**: Implements two-level caching strategy:
  - Level 1: `search_{artist_name}` caches raw search API responses
  - Level 2: `artist_{theaudiodb_id}` caches filtered individual artist data by
    unique ID
- **FanartTV**: Inherently handles duplicates via MusicBrainz ID requirements
  (`music/{mbid}`)
- **Wikimedia**: Uses Wikidata entity IDs (`{entity_id}_{lang}`) for perfect
  disambiguation
- Comprehensive unit tests validate caching behavior with duplicate artist
  scenarios
- Object reconstruction ensures cached data maintains same interface as live
  API responses
