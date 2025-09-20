# DataCache Module Documentation

This module provides a unified caching system for the whats-now-playing application,
replacing both the existing `apicache.py` and `imagecache.py` systems with a URL-based, async-first architecture.

## Architecture Overview

The datacache module is designed with performance and multiprocess coordination in mind:

- **URL-based storage**: Uses URLs as primary keys following imagecache pattern for randomimage support
- **Multiprocess coordination**: Database-backed queues work across multiple processes
- **Windows compatibility**: Connection-per-operation SQLite pattern prevents locking issues
- **Async-first**: Built on asyncio/aiohttp with aiosqlite for non-blocking operations
- **Rate limiting**: Token bucket algorithm with per-provider limits (e.g., MusicBrainz 1req/sec)
- **Priority handling**: Immediate (priority=1) vs batch (priority=2) requests

## Module Structure

```code
nowplaying/datacache/
├── __init__.py          # Main interface and convenience functions
├── storage.py           # URL-based storage layer with aiosqlite
├── client.py            # HTTP client with rate limiting and caching
├── providers.py         # Provider-specific interfaces (MusicBrainz, Images, API)
├── rate_limiting.py     # Token bucket rate limiting implementation
└── CLAUDE.md            # This documentation file
```

## Design Principles

### Time-Sensitive Operations

- **Immediate requests**: Direct async calls with `immediate=True` for track polling and live operations
- **Background requests**: Queued with `immediate=False` for pre-caching and non-urgent operations
- **Priority handling**: Database-backed queue with priority levels (immediate=1, batch=2)

### Rate Limiting

- **Token bucket algorithm**: Per-provider rate limiting with configurable requests per second
- **Provider-specific limits**: MusicBrainz 1req/sec, others configurable in rate_limiting.py
- **Non-blocking**: Uses aiohttp for concurrent requests within rate limits

### Data Storage

- **Generic storage**: Single system handles all data types (images, JSON, binary blobs)
- **TTL management**: Configurable time-to-live per data type and provider
- **Size management**: Automatic cleanup and size limits like current imagecache
- **Database vacuum**: Periodic maintenance operations

## Migration Strategy

### Phase 1: Parallel Development

- Develop datacache alongside existing systems
- No disruption to current functionality
- Gradual testing and validation

### Phase 2: Selective Migration

- Start with new features (artist pre-caching)
- Migrate non-critical API calls first
- Keep immediate/critical paths on old system until proven

### Phase 3: Full Migration

- Replace apicache.py usage throughout codebase
- Replace imagecache.py with datacache equivalent
- Remove old systems

## Key Interfaces

### Immediate Requests (for live operations)

```python
# Get providers instance
providers = nowplaying.datacache.get_providers()
await providers.initialize()

# Immediate MusicBrainz search
result = await providers.musicbrainz.search_artists("Daft Punk", immediate=True)

# Immediate image caching
image_result = await providers.images.cache_artist_thumbnail(
    url="https://example.com/image.jpg",
    artist_identifier="daft_punk",
    provider="theaudiodb",
    immediate=True
)
```

### Background Requests (for pre-caching)

```python
# Queue image for background processing
await providers.images.cache_artist_logo(
    url="https://example.com/logo.jpg",
    artist_identifier="daft_punk",
    provider="theaudiodb",
    immediate=False  # Queued for background processing
)
```

### Random Image Support (replacing imagecache.randomimage)

```python
# Get random artist image
random_image = await providers.images.get_random_image(
    artist_identifier="daft_punk",
    image_type="thumbnail"
)

if random_image:
    image_data, metadata, url = random_image
```

## Performance Considerations

### Resource Management

- **Connection-per-operation**: SQLite connections are opened/closed per operation for Windows compatibility
- **Rate-limited concurrency**: Token bucket algorithm prevents overwhelming API providers
- **Database optimization**: aiosqlite with WAL mode for better concurrent access

### DJ Performance Requirements

- **Zero blocking**: Immediate requests must never block track polling
- **Fast lookups**: Sub-100ms cache lookups for live operations
- **Reliability**: Graceful degradation when cache unavailable

## Configuration

The datacache module is designed to work with minimal configuration, using sensible defaults:

- **Database location**: Uses Qt standard cache location (same as imagecache.py)
- **Rate limits**: Built-in provider-specific limits (MusicBrainz: 1req/sec)
- **TTL defaults**: 2 weeks for images, 1 week for API responses, 1 month for MusicBrainz
- **Timeout defaults**: 30s for images/APIs, 15s for MusicBrainz
- **Maintenance**: Automatic cleanup of expired entries on startup

## Future Enhancements

### Artist Pre-caching

- Background processing of VirtualDJ/Traktor databases
- Pre-cache artist lookups for faster live performance
- Smart caching based on DJ usage patterns

### Advanced Features

- **Cache warming**: Proactive loading of likely-needed data
- **Analytics**: Track cache hit rates and performance metrics
- **Compression**: Compress cached data to save space
- **Replication**: Sync cache across multiple instances

## Dependencies

### New Dependencies

- **aiosqlite**: Async SQLite operations for non-blocking database access
- **aiohttp**: HTTP client for async requests (already used by whats-now-playing)

### Existing Dependencies (No Changes Required)

- **sqlite3**: Database schema and sync maintenance operations
- **pathlib**: File system operations

## Testing Strategy

### Comprehensive Test Suite (87 tests across 4 files)

`tests/datacache/test_storage.py`

- URL-based storage and retrieval operations
- Randomimage functionality with multiple images per artist
- TTL expiration and automatic cleanup
- Data serialization (JSON, binary, strings)
- Concurrent access and multiprocess coordination

`tests/datacache/test_client.py`

- HTTP client with aioresponses mocking following project patterns
- Cache hit vs miss behavior
- Rate limiting integration with token bucket algorithm
- Error handling (timeouts, HTTP errors, rate limits)
- Queue processing functionality

`tests/datacache/test_providers.py`

- Provider-specific interfaces (MusicBrainz, Images, API)
- Method parameter validation and URL construction
- Configuration settings and shared client behavior
- Internal mocking with unittest.mock (not HTTP requests)

`tests/datacache/test_integration.py`

- End-to-end workflows with aioresponses
- Complete image caching and randomimage functionality
- Provider filtering and concurrent operations
- API response caching integration

---

## Development Notes

This module is designed to be the long-term caching solution for whats-now-playing. Key goals:

1. **Performance**: Never impact live DJ operations
2. **Reliability**: Graceful error handling and fallbacks
3. **Maintainability**: Clean, modular architecture
4. **Future-proof**: Extensible for new cache types and providers

When modifying this module, always consider the impact on time-sensitive track polling operations.
