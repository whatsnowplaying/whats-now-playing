# API Reference

**What's Now Playing** provides a REST API through its built-in webserver for programmatic access to track
information and remote input functionality.

## Base URL

All API endpoints are available at: `http://hostname:port/v1/`

Where `hostname` and `port` match your webserver configuration.

## Authentication

Some endpoints require authentication via a secret key. When configured, include the secret in your request:

- **GET requests**: Add `&secret=your_api_key` to query parameters
- **POST requests**: Include `"secret": "your_api_key"` in JSON body

## Endpoints

### GET /v1/last

Returns the currently playing track metadata.

**Authentication**: None required

**Response**: JSON object with current track information

```json
{
  "artist": "Artist Name",
  "title": "Track Title",
  "album": "Album Name",
  "genre": "Electronic",
  "date": "2023",
  "coverurl": "cover.png"
}
```

### GET|POST /v1/remoteinput

Accepts track metadata submissions from remote sources for the [Remote Input](../input/remote.md) system.

**Authentication**: Optional secret key (if configured)

**Methods**: `GET`, `POST`

#### POST Request (JSON)

```json
{
  "artist": "Artist Name",
  "title": "Track Title",
  "album": "Album Name",
  "secret": "your_api_key"
}
```

#### GET Request (Query Parameters)

```url
/v1/remoteinput?artist=Artist%20Name&title=Track%20Title&album=Album%20Name&secret=your_api_key
```

#### Response Format

**Success (200)**:

```json
{
  "dbid": 12345,
  "processed_metadata": {
    "artist": "Artist Name",
    "title": "Track Title",
    "album": "Album Name",
    "artistlongbio": "Artist biography...",
    "coverurl": "cover.png",
    "date": "2023",
    "genre": "Electronic"
  },
  "warnings": [
    "Field 'title' truncated from 1500 to 1000 characters"
  ]
}
```

> **Note:** The `warnings` field is only included if data validation issues occurred.

**Error Responses**:

- `400`: Invalid JSON or query parameters
- `403`: Missing or invalid secret key
- `408`: Metadata processing timeout (30 seconds)
- `500`: Server error during processing

#### Supported Fields

The API accepts any metadata fields that the Remote Output plugin sends, including:

- **Basic track info**: `artist`, `title`, `album`
- **Identifiers**: `isrc`, `musicbrainzartistid`, `musicbrainzrecordingid`
- **Additional metadata**: `genre`, `date`, `composer`, `lyricist`, `bpm`, `key`, `publisher`
- **Technical info**: `duration`, `bitrate`, `samplerate`

**Filtered fields**: Binary data, system fields (`hostname`, `dbid`, `filename`), and other
security-sensitive information are automatically removed.

#### Input Validation

The API includes automatic validation and processing:

1. **Field Length Limits**: String fields are truncated to 1000 characters
2. **Null Byte Stripping**: Removes null bytes (`\x00`) from string values
3. **Security Filtering**: Blocks system fields and binary data
4. **Full Metadata Processing**: Runs complete enrichment including MusicBrainz lookups, artist extras, and recognition services

### GET /v1/images/ws

WebSocket endpoint for real-time image updates (cover art slideshow functionality).

**Authentication**: None required

**Protocol**: WebSocket

Connect to `ws://hostname:port/v1/images/ws` for continuous image update stream.

## DJ Software Integration

Many DJ applications can send track information directly via HTTP requests. See the
[Remote Input documentation](../input/remote.md#dj-software-integration-examples) for specific configuration
examples.

## Error Handling

All endpoints return appropriate HTTP status codes:

- `200`: Success
- `400`: Bad request (invalid parameters)
- `403`: Authentication failed
- `404`: Endpoint not found
- `408`: Request timeout
- `500`: Internal server error

Error responses include a JSON object with an `error` field describing the issue.
