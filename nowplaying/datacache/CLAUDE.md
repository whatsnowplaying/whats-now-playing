# DataCache Module Documentation

This module provides a unified caching system for the whats-now-playing application,
replacing both the existing `apicache.py` and `imagecache.py` systems with a URL-based, async-first architecture.

## Architecture Overview

The datacache module is designed with performance and multiprocess coordination in mind:

- **URL-based storage**: Uses URLs as primary keys following the imagecache pattern for randomimage support
- **Multiprocess coordination**: Database-backed queues work across multiple processes
- **Windows compatibility**: Connection-per-operation SQLite pattern prevents locking issues
- **Async-first**: Built on asyncio/aiohttp with aiosqlite for non-blocking operations
- **Rate limiting**: Token bucket algorithm with per-provider limits (e.g., MusicBrainz 1req/sec)
- **Priority handling**: Immediate (priority=1) vs batch (priority=2) requests

## Module Structure

```code
nowplaying/datacache/
├── __init__.py   # Public API and cached_fetch
├── storage.py    # URL-keyed SQLite storage with TTL and blob files
├── client.py     # HTTP client with rate limiting, get_or_fetch, process_queue
├── pending.py    # Database-backed pending request queue
├── queue.py      # Token-bucket rate limiter
├── utils.py      # Shared utilities (redact_url)
└── CLAUDE.md     # This documentation file
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
- **Size management**: Automatic cleanup and size limits like the current imagecache
- **Database vacuum**: Periodic maintenance operations

## Key Interfaces

### Immediate fetch (for live operations)

```python
client = nowplaying.datacache.get_client()
result = await client.get_or_fetch(
    url="https://example.com/image.jpg",
    identifier="daft_punk",
    data_type="artistthumbnail",
    provider="theaudiodb",
    immediate=True,
)
```

### Background fetch (queue for datacache worker process)

```python
await client.get_or_fetch(
    url="https://example.com/logo.jpg",
    identifier="daft_punk",
    data_type="artistlogo",
    provider="theaudiodb",
    immediate=False,
)
```

### Random image retrieval

```python
result = await client.get_random_image(identifier="daft_punk", data_type="artistthumbnail")
if result:
    image_bytes = result.data
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
- randomimage functionality with multiple images per artist
- TTL expiration and automatic cleanup
- Data serialization (JSON, binary, strings)
- Concurrent access and multiprocess coordination

`tests/datacache/test_client.py`

- HTTP client with aioresponses mocking following project patterns
- Cache hit vs miss behavior
- Rate limiting integration with token bucket algorithm
- Error handling (timeouts, HTTP errors, rate limits)
- Queue processing functionality

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
