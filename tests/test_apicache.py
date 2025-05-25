#!/usr/bin/env python3
"""
Unit tests for the API response caching system
"""

import asyncio
import pathlib
import tempfile

import pytest
import pytest_asyncio

import nowplaying.apicache


@pytest_asyncio.fixture
async def temp_cache():
    """Create a temporary cache for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = pathlib.Path(temp_dir)
        cache = nowplaying.apicache.APIResponseCache(cache_dir=cache_dir)
        # Wait for initialization to complete
        await cache._initialize_db()
        yield cache


@pytest.mark.asyncio
async def test_cache_initialization(temp_cache):
    """Test that the cache initializes properly."""
    cache = temp_cache

    # Check that database file exists
    assert cache.db_file.exists()

    # Check that tables are created
    async with cache._lock:
        async with nowplaying.apicache.aiosqlite.connect(cache.db_file) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='api_responses'")
            tables = await cursor.fetchall()
            assert len(tables) == 1

            # Check that indices are created
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
            indices = await cursor.fetchall()
            assert len(indices) == 3  # We create 3 indices


@pytest.mark.asyncio
async def test_cache_key_generation(temp_cache):
    """Test cache key generation."""
    cache = temp_cache

    # Test basic key generation
    key1 = cache._make_cache_key('discogs', 'Nine Inch Nails', 'artist_search')
    key2 = cache._make_cache_key('discogs', 'Nine Inch Nails', 'artist_search')
    assert key1 == key2  # Same input should produce same key

    # Test case insensitivity for artist names
    key3 = cache._make_cache_key('discogs', 'NINE INCH NAILS', 'artist_search')
    key4 = cache._make_cache_key('discogs', '  nine inch nails  ', 'artist_search')
    assert key3 == key4  # Case and whitespace shouldn't matter

    # Test provider case insensitivity
    key5 = cache._make_cache_key('DISCOGS', 'Nine Inch Nails', 'artist_search')
    assert key1 == key5

    # Test different parameters produce different keys
    key6 = cache._make_cache_key('discogs', 'Nine Inch Nails', 'artist_search', {'page': 1})
    key7 = cache._make_cache_key('discogs', 'Nine Inch Nails', 'artist_search', {'page': 2})
    assert key6 != key7

    # Test parameter order doesn't matter
    key8 = cache._make_cache_key('discogs', 'Nine Inch Nails', 'artist_search', {
        'page': 1,
        'limit': 10
    })
    key9 = cache._make_cache_key('discogs', 'Nine Inch Nails', 'artist_search', {
        'limit': 10,
        'page': 1
    })
    assert key8 == key9


@pytest.mark.asyncio
async def test_cache_miss(temp_cache):
    """Test cache miss behavior."""
    cache = temp_cache

    result = await cache.get('discogs', 'Nonexistent Artist', 'artist_search')
    assert result is None


@pytest.mark.asyncio
async def test_cache_put_and_get(temp_cache):
    """Test storing and retrieving data from cache."""
    cache = temp_cache

    test_data = {
        'artist_id': 12345,
        'name': 'Nine Inch Nails',
        'bio': 'Industrial rock band',
        'images': ['image1.jpg', 'image2.jpg']
    }

    # Store data in cache
    await cache.put('discogs', 'Nine Inch Nails', 'artist_search', test_data)

    # Retrieve data from cache
    result = await cache.get('discogs', 'Nine Inch Nails', 'artist_search')
    assert result == test_data


@pytest.mark.asyncio
async def test_cache_ttl_default(temp_cache):
    """Test that TTL defaults work correctly."""
    cache = temp_cache

    test_data = {'test': 'data'}

    # Test provider-specific TTL
    await cache.put('discogs', 'Test Artist', 'search', test_data)

    # Check that correct TTL was applied
    cache_key = cache._make_cache_key('discogs', 'Test Artist', 'search')
    async with cache._lock:
        async with nowplaying.apicache.aiosqlite.connect(cache.db_file) as db:
            cursor = await db.execute(
                "SELECT created_at, expires_at FROM api_responses WHERE cache_key = ?",
                (cache_key, ))
            row = await cursor.fetchone()
            created_at, expires_at = row

            # Should use discogs default TTL (24 hours)
            expected_ttl = cache.DEFAULT_TTL['discogs']
            actual_ttl = expires_at - created_at
            assert abs(actual_ttl - expected_ttl) <= 1  # Allow 1 second variance


@pytest.mark.asyncio
async def test_cache_ttl_custom(temp_cache):
    """Test custom TTL values."""
    cache = temp_cache

    test_data = {'test': 'data'}
    custom_ttl = 300  # 5 minutes

    await cache.put('test_provider', 'Test Artist', 'search', test_data, ttl_seconds=custom_ttl)

    cache_key = cache._make_cache_key('test_provider', 'Test Artist', 'search')
    async with cache._lock:
        async with nowplaying.apicache.aiosqlite.connect(cache.db_file) as db:
            cursor = await db.execute(
                "SELECT created_at, expires_at FROM api_responses WHERE cache_key = ?",
                (cache_key, ))
            row = await cursor.fetchone()
            created_at, expires_at = row

            actual_ttl = expires_at - created_at
            assert abs(actual_ttl - custom_ttl) <= 1


@pytest.mark.asyncio
async def test_cache_expiration(temp_cache):
    """Test that expired cache entries are not returned."""
    cache = temp_cache

    test_data = {'test': 'data'}

    # Store with very short TTL
    await cache.put('test_provider', 'Test Artist', 'search', test_data, ttl_seconds=1)

    # Should be available immediately
    result = await cache.get('test_provider', 'Test Artist', 'search')
    assert result == test_data

    # Wait for expiration
    await asyncio.sleep(2)

    # Should now be expired
    result = await cache.get('test_provider', 'Test Artist', 'search')
    assert result is None


@pytest.mark.asyncio
async def test_cache_access_tracking(temp_cache):
    """Test that access count and last accessed are tracked."""
    cache = temp_cache

    test_data = {'test': 'data'}
    await cache.put('discogs', 'Test Artist', 'search', test_data)

    # First access
    await cache.get('discogs', 'Test Artist', 'search')

    # Second access
    await cache.get('discogs', 'Test Artist', 'search')

    # Check access count
    cache_key = cache._make_cache_key('discogs', 'Test Artist', 'search')
    async with cache._lock:
        async with nowplaying.apicache.aiosqlite.connect(cache.db_file) as db:
            cursor = await db.execute(
                "SELECT access_count, last_accessed FROM api_responses WHERE cache_key = ?",
                (cache_key, ))
            row = await cursor.fetchone()
            access_count, last_accessed = row

            # Should be 3 (1 from put + 2 from gets)
            assert access_count == 3
            assert last_accessed > 0


@pytest.mark.asyncio
async def test_cache_replacement(temp_cache):
    """Test that storing with same key replaces existing data."""
    cache = temp_cache

    original_data = {'version': 1, 'data': 'original'}
    updated_data = {'version': 2, 'data': 'updated'}

    # Store original data
    await cache.put('discogs', 'Test Artist', 'search', original_data)
    result = await cache.get('discogs', 'Test Artist', 'search')
    assert result == original_data

    # Store updated data with same key
    await cache.put('discogs', 'Test Artist', 'search', updated_data)
    result = await cache.get('discogs', 'Test Artist', 'search')
    assert result == updated_data

    # Should only be one entry in database
    cache_key = cache._make_cache_key('discogs', 'Test Artist', 'search')
    async with cache._lock:
        async with nowplaying.apicache.aiosqlite.connect(cache.db_file) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM api_responses WHERE cache_key = ?",
                                      (cache_key, ))
            count = await cursor.fetchone()
            assert count[0] == 1


@pytest.mark.asyncio
async def test_cache_with_params(temp_cache):
    """Test caching with additional parameters."""
    cache = temp_cache

    data1 = {'page': 1, 'results': ['result1', 'result2']}
    data2 = {'page': 2, 'results': ['result3', 'result4']}

    # Store data with different parameters
    await cache.put('discogs', 'Test Artist', 'search', data1, params={'page': 1})
    await cache.put('discogs', 'Test Artist', 'search', data2, params={'page': 2})

    # Retrieve with specific parameters
    result1 = await cache.get('discogs', 'Test Artist', 'search', params={'page': 1})
    result2 = await cache.get('discogs', 'Test Artist', 'search', params={'page': 2})

    assert result1 == data1
    assert result2 == data2


@pytest.mark.asyncio
async def test_cache_empty_data(temp_cache):
    """Test that empty data is not cached."""
    cache = temp_cache

    # Try to cache empty data
    await cache.put('discogs', 'Test Artist', 'search', {})
    await cache.put('discogs', 'Test Artist', 'search', None)

    # Should not be in cache
    result = await cache.get('discogs', 'Test Artist', 'search')
    assert result is None


@pytest.mark.asyncio
async def test_cache_invalid_json(temp_cache):
    """Test handling of data that can't be serialized to JSON."""
    cache = temp_cache

    # Data with non-serializable content
    invalid_data = {'function': lambda x: x}  # Functions aren't JSON serializable

    # Should not raise exception, just not cache
    await cache.put('discogs', 'Test Artist', 'search', invalid_data)

    result = await cache.get('discogs', 'Test Artist', 'search')
    assert result is None


@pytest.mark.asyncio
async def test_cache_concurrent_access(temp_cache):
    """Test concurrent access to cache."""
    cache = temp_cache

    async def store_data(artist_num):
        data = {'artist': f'Artist {artist_num}', 'id': artist_num}
        await cache.put('discogs', f'Artist {artist_num}', 'search', data)
        return await cache.get('discogs', f'Artist {artist_num}', 'search')

    # Run multiple concurrent operations
    tasks = [store_data(i) for i in range(10)]
    results = await asyncio.gather(*tasks)

    # All operations should succeed
    for i, result in enumerate(results):
        expected = {'artist': f'Artist {i}', 'id': i}
        assert result == expected


@pytest.mark.asyncio
async def test_cache_database_error_handling(temp_cache):
    """Test handling of database errors."""
    cache = temp_cache

    # Close the database file to simulate an error
    cache.db_file.unlink()

    # Get should return None on database error
    result = await cache.get('discogs', 'Test Artist', 'search')
    assert result is None


@pytest.mark.asyncio
async def test_cache_stats_collection(temp_cache):
    """Test that cache statistics are collected properly."""
    cache = temp_cache

    # Store multiple entries
    for i in range(5):
        data = {'artist_id': i, 'name': f'Artist {i}'}
        await cache.put('discogs', f'Artist {i}', 'search', data)

    # Access some entries multiple times
    await cache.get('discogs', 'Artist 0', 'search')
    await cache.get('discogs', 'Artist 0', 'search')
    await cache.get('discogs', 'Artist 1', 'search')

    # Check database contains expected data
    async with cache._lock:
        async with nowplaying.apicache.aiosqlite.connect(cache.db_file) as db:
            # Check total entries
            cursor = await db.execute("SELECT COUNT(*) FROM api_responses")
            count = await cursor.fetchone()
            assert count[0] == 5

            # Check access counts
            cursor = await db.execute(
                "SELECT artist_name, access_count FROM api_responses ORDER BY artist_name")
            rows = await cursor.fetchall()

            expected_counts = [
                ('artist 0', 3),  # 1 put + 2 gets
                ('artist 1', 2),  # 1 put + 1 get
                ('artist 2', 1),  # 1 put only
                ('artist 3', 1),  # 1 put only
                ('artist 4', 1),  # 1 put only
            ]

            for i, (artist_name, access_count) in enumerate(rows):
                expected_artist, expected_count = expected_counts[i]
                assert artist_name == expected_artist
                assert access_count == expected_count


@pytest.mark.asyncio
async def test_cache_with_real_data_structure():
    """Test cache with realistic API response data structures."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = pathlib.Path(temp_dir)
        cache = nowplaying.apicache.APIResponseCache(cache_dir=cache_dir)
        await cache._initialize_db()

        # Realistic Discogs API response structure
        discogs_data = {
            'id':
            4223,
            'name':
            'Nine Inch Nails',
            'real_name':
            'Nine Inch Nails',
            'profile':
            'Industrial rock band from Cleveland, Ohio...',
            'images': [{
                'type': 'primary',
                'uri': 'https://example.com/image1.jpg',
                'width': 600,
                'height': 600
            }, {
                'type': 'secondary',
                'uri': 'https://example.com/image2.jpg',
                'width': 400,
                'height': 400
            }],
            'urls': ['https://www.nin.com/'],
            'members': [{
                'name': 'Trent Reznor',
                'active': True
            }]
        }

        # Store and retrieve
        await cache.put('discogs', 'Nine Inch Nails', 'artist/4223', discogs_data)
        result = await cache.get('discogs', 'Nine Inch Nails', 'artist/4223')

        assert result == discogs_data
        assert result['id'] == 4223
        assert len(result['images']) == 2
        assert result['images'][0]['type'] == 'primary'


@pytest.mark.asyncio
async def test_cache_provider_ttl_settings():
    """Test that different providers use appropriate TTL settings."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_dir = pathlib.Path(temp_dir)
        cache = nowplaying.apicache.APIResponseCache(cache_dir=cache_dir)
        await cache._initialize_db()

        test_data = {'test': 'data'}

        # Test each provider's default TTL
        providers_and_ttls = [
            ('discogs', 24 * 60 * 60),  # 24 hours
            ('theaudiodb', 7 * 24 * 60 * 60),  # 7 days
            ('fanarttv', 7 * 24 * 60 * 60),  # 7 days
            ('wikimedia', 24 * 60 * 60),  # 24 hours
            ('unknown_provider', 6 * 60 * 60)  # 6 hours default
        ]

        for provider, expected_ttl in providers_and_ttls:
            await cache.put(provider, 'Test Artist', 'search', test_data)

            cache_key = cache._make_cache_key(provider, 'Test Artist', 'search')
            async with cache._lock:
                async with nowplaying.apicache.aiosqlite.connect(cache.db_file) as db:
                    cursor = await db.execute(
                        "SELECT created_at, expires_at FROM api_responses WHERE cache_key = ?",
                        (cache_key, ))
                    row = await cursor.fetchone()
                    created_at, expires_at = row

                    actual_ttl = expires_at - created_at
                    assert abs(actual_ttl - expected_ttl) <= 1, \
                        f"Provider {provider}: expected {expected_ttl}s, got {actual_ttl}s"


@pytest.mark.asyncio
async def test_cache_binary_data_round_trip(temp_cache):
    """Test that binary data is properly cached and restored."""
    cache = temp_cache

    # Test data with binary content (simulating cover art)
    jpeg_header = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00'
    png_header = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'

    test_data = {
        'title': 'Test Song',
        'artist': 'Test Artist',
        'coverimageraw': jpeg_header + b'fake_jpeg_data' * 100,  # ~1.5KB fake JPEG
        'thumbnail': png_header + b'fake_png_data' * 50,  # ~750B fake PNG
        'metadata': {
            'nested_binary': b'nested_binary_content',
            'normal_field': 'text_content'
        },
        'binary_list': [b'binary1', b'binary2', 'text'],
        'normal_field': 'regular_text'
    }

    # Store the data
    await cache.put('musicbrainz', 'TestArtist', 'recording', test_data)

    # Retrieve the data
    cached_data = await cache.get('musicbrainz', 'TestArtist', 'recording')

    # Verify all fields are correctly restored
    assert cached_data is not None
    assert cached_data['title'] == test_data['title']
    assert cached_data['artist'] == test_data['artist']
    assert cached_data['normal_field'] == test_data['normal_field']

    # Verify binary data integrity
    assert isinstance(cached_data['coverimageraw'], bytes)
    assert cached_data['coverimageraw'] == test_data['coverimageraw']
    assert len(cached_data['coverimageraw']) == len(test_data['coverimageraw'])

    assert isinstance(cached_data['thumbnail'], bytes)
    assert cached_data['thumbnail'] == test_data['thumbnail']

    # Verify nested binary data
    assert isinstance(cached_data['metadata']['nested_binary'], bytes)
    assert cached_data['metadata']['nested_binary'] == test_data['metadata']['nested_binary']
    assert cached_data['metadata']['normal_field'] == test_data['metadata']['normal_field']

    # Verify binary data in lists
    assert isinstance(cached_data['binary_list'][0], bytes)
    assert isinstance(cached_data['binary_list'][1], bytes)
    assert isinstance(cached_data['binary_list'][2], str)
    assert cached_data['binary_list'] == test_data['binary_list']


@pytest.mark.asyncio
async def test_cache_large_binary_data(temp_cache):
    """Test caching of realistically sized binary data (cover art)."""
    cache = temp_cache

    # Simulate a realistic JPEG cover art size (50-100KB is typical)
    large_binary = b'\xff\xd8\xff\xe0\x00\x10JFIF' + b'x' * 75000  # ~75KB fake JPEG

    test_data = {
        'artist': 'Test Artist',
        'album': 'Test Album',
        'coverimageraw': large_binary,
        'title': 'Test Song'
    }

    # Store and retrieve
    await cache.put('musicbrainz', 'TestArtist', 'recording', test_data)
    cached_data = await cache.get('musicbrainz', 'TestArtist', 'recording')

    # Verify large binary data integrity
    assert cached_data is not None
    assert isinstance(cached_data['coverimageraw'], bytes)
    assert len(cached_data['coverimageraw']) == len(large_binary)
    assert cached_data['coverimageraw'] == large_binary
    assert cached_data['coverimageraw'][:10] == b'\xff\xd8\xff\xe0\x00\x10JFIF'  # JPEG header


@pytest.mark.asyncio
async def test_cache_mixed_serializable_data(temp_cache):
    """Test caching of complex data with mix of serializable and binary content."""
    cache = temp_cache

    test_data = {
        'string': 'text',
        'integer': 42,
        'float': 3.14,
        'boolean': True,
        'null': None,
        'list': [1, 2, 'three'],
        'dict': {
            'nested': 'value'
        },
        'binary': b'binary_data',
        'complex_structure': {
            'artists': [{
                'name': 'Artist 1',
                'image': b'artist1_image'
            }, {
                'name': 'Artist 2',
                'image': b'artist2_image'
            }],
            'metadata': {
                'cover': b'cover_image',
                'description': 'Album description'
            }
        }
    }

    # Store and retrieve
    await cache.put('test', 'ComplexArtist', 'metadata', test_data)
    cached_data = await cache.get('test', 'ComplexArtist', 'metadata')

    # Verify all data types are preserved
    assert cached_data['string'] == 'text'
    assert cached_data['integer'] == 42
    assert cached_data['float'] == 3.14
    assert cached_data['boolean'] is True
    assert cached_data['null'] is None
    assert cached_data['list'] == [1, 2, 'three']
    assert cached_data['dict'] == {'nested': 'value'}

    # Verify binary data in complex structures
    assert isinstance(cached_data['binary'], bytes)
    assert cached_data['binary'] == b'binary_data'

    assert isinstance(cached_data['complex_structure']['artists'][0]['image'], bytes)
    assert isinstance(cached_data['complex_structure']['artists'][1]['image'], bytes)
    assert isinstance(cached_data['complex_structure']['metadata']['cover'], bytes)

    assert cached_data['complex_structure']['artists'][0]['name'] == 'Artist 1'
    assert cached_data['complex_structure']['metadata']['description'] == 'Album description'


@pytest.mark.asyncio
async def test_cache_binary_data_base64_encoding(temp_cache):
    """Test that binary data is properly base64 encoded in storage."""
    cache = temp_cache

    binary_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'  # PNG header
    test_data = {'artist': 'Test Artist', 'coverimageraw': binary_data}

    # Store the data
    await cache.put('test', 'TestArtist', 'recording', test_data)

    # Manually check the database storage format
    import aiosqlite
    async with aiosqlite.connect(cache.db_file) as db:
        cursor = await db.execute(
            "SELECT response_data FROM api_responses WHERE artist_name = ?",
            ('testartist', )  # Remember: stored as lowercase and stripped
        )
        row = await cursor.fetchone()

        assert row is not None
        stored_json = row[0]

        # Verify the JSON contains base64 encoded binary data
        import json
        stored_data = json.loads(stored_json)

        # The binary data should be stored as a special object
        cover_data = stored_data['coverimageraw']
        assert isinstance(cover_data, dict)
        assert cover_data['__type__'] == 'bytes'
        assert '__data__' in cover_data

        # Verify we can decode it back
        import base64
        decoded = base64.b64decode(cover_data['__data__'])
        assert decoded == binary_data


@pytest.mark.asyncio
async def test_cache_empty_binary_data(temp_cache):
    """Test handling of empty binary data."""
    cache = temp_cache

    test_data = {
        'artist': 'Test Artist',
        'coverimageraw': b'',  # Empty bytes
        'title': 'Test Song'
    }

    await cache.put('test', 'TestArtist', 'recording', test_data)
    cached_data = await cache.get('test', 'TestArtist', 'recording')

    assert cached_data is not None
    assert isinstance(cached_data['coverimageraw'], bytes)
    assert len(cached_data['coverimageraw']) == 0
    assert cached_data['coverimageraw'] == b''


@pytest.mark.asyncio
async def test_cache_musicbrainz_realistic_data(temp_cache):
    """Test caching of realistic MusicBrainz data with cover art."""
    cache = temp_cache

    # Simulate realistic MusicBrainz response with cover art
    jpeg_data = (b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00'
                 b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07' + b'x' * 1000)

    musicbrainz_data = {
        'musicbrainzrecordingid':
        'c4227696-ea17-46f5-b102-be084da8fb98',
        'title':
        'Computer Blue ("Hallway Speech" version)',
        'artist':
        'Prince',
        'musicbrainzartistid': ['070d193a-845c-479f-980e-bef15710653e'],
        'date':
        '2017-06-23',
        'genres': ['pop'],
        'genre':
        'pop',
        'album':
        'Purple Rain',
        'label':
        'Warner Bros. Records',
        'coverimageraw':
        jpeg_data,  # Binary cover art
        'artistwebsites': [
            'https://www.discogs.com/artist/271351', 'https://www.last.fm/music/Prince',
            'https://www.prince.com/'
        ]
    }

    # Store and retrieve
    await cache.put('musicbrainz', 'Prince', 'recording', musicbrainz_data)
    cached_data = await cache.get('musicbrainz', 'Prince', 'recording')

    # Verify all fields are preserved
    assert cached_data is not None
    assert cached_data['musicbrainzrecordingid'] == musicbrainz_data['musicbrainzrecordingid']
    assert cached_data['title'] == musicbrainz_data['title']
    assert cached_data['artist'] == musicbrainz_data['artist']
    assert cached_data['album'] == musicbrainz_data['album']
    assert cached_data['genres'] == musicbrainz_data['genres']
    assert cached_data['artistwebsites'] == musicbrainz_data['artistwebsites']

    # Verify binary cover art is preserved
    assert isinstance(cached_data['coverimageraw'], bytes)
    assert len(cached_data['coverimageraw']) == len(jpeg_data)
    assert cached_data['coverimageraw'] == jpeg_data
    assert cached_data['coverimageraw'].startswith(b'\xff\xd8\xff\xe0')  # JPEG signature
