# Remote Services

A common streaming configuration is to have more than one computer
involved, such as one computer working as the DJ machine and one computer
for processing the stream.  In some very advanced configurations, there
might even be more than on DJ on different computers swapping back and
forth!

**What's Now Playing** supports a configuration where each setup has
their own app configuration running.  One or more installations on
DJ computers send the track information to a central one.  That
central one will then perform any additional lookups and send the
output to anything configured such as Twitch.

## Settings

* Server Side

1. You will need to enable the web server
2. Also in webserver, you may optionally set a Secret that is required to be set on any
   other **What's Now Playing** installation that talks to it
3. Set the Input to be 'Remote'
4. It is recommended to enable Artist Extras on the Server

* Client Side

1. Go to 'Remote Output'
2. Enable it
3. Set the Server to be either the hostname or IP address of the computer
   acting as the server
4. Set the port to be the server's webserver port
5. If the Server has a Secret set, you will need to set that as well

> NOTE: Some content, such as cover art, will not be sent to the remote server.

## Advanced API Usage

The remote server exposes a REST API endpoint at `/v1/remoteinput` that can
accept metadata submissions from external sources beyond the built-in Remote Output plugin.

### Endpoint: `/v1/remoteinput`

**Methods:** `GET`, `POST`

**Authentication:** Optional secret key (configured via `remote/remote_key` setting)

#### Request Format

**POST (JSON):**

```json
{
  "artist": "Artist Name",
  "title": "Track Title",
  "album": "Album Name",
  "secret": "your_secret_key"
}
```

**GET (Query Parameters):**

```url
/v1/remoteinput?artist=Artist%20Name&title=Track%20Title&album=Album%20Name&secret=your_secret_key
```

#### Response Format

**Success (200):**

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

> **Note:** The `warnings` field is only included if data validation issues occurred (e.g., field truncation).

**Error Responses:**

* `400`: Invalid JSON or query parameters
* `403`: Missing or invalid secret key
* `408`: Metadata processing timeout (30 seconds)
* `500`: Server error during processing

#### Input Validation & Processing

The API includes several validation and processing features:

1. **Field Length Limits:** String fields are truncated to 1000 characters
2. **Null Byte Stripping:** Removes null bytes (`\x00`) from string values
3. **Field Whitelisting:** Filters out system fields like `hostname`, `dbid`, binary data
4. **Full Metadata Processing:** Runs complete metadata enrichment including:
   * MusicBrainz lookups
   * Artist extras (biography, images)
   * Recognition services
   * Image processing

#### Supported Fields

The API accepts any metadata fields that the Remote Output plugin sends, including:

* Basic track info: `artist`, `title`, `album`
* Identifiers: `isrc`, `musicbrainzartistid`, `musicbrainzrecordingid`
* Additional: `genre`, `date`, `composer`, `lyricist`, `bpm`, `key`
* And many others (see Remote Output plugin for complete list)

Fields like `coverimageraw`, `hostname`, `httpport`, `filename`, and other system/binary data are automatically filtered out for security reasons.

#### DJ Software Integration Examples

**Configuration Notes:**
- Replace `localhost:8899` with your server's hostname and webserver port
- If a secret is configured, add `&secret=your_secret_key` to the URL

**MegaSeg (Logging → Send track info to server):**

```url
http://localhost:8899/v1/remoteinput?title=%Title%&artist=%Artist%&album=%Album%&year=%Year%&duration=%LengthSeconds%&bpm=%BPM%&composer=%Composer%&lyricist=%Lyricist%&publisher=%Publisher%
```

**Radiologik (Publishing → Network & Serial → GET URL):**

```url
http://localhost:8899/v1/remoteinput?title=<t>&artist=<a>&album=<l>&isrc=<i>&composer=<comp>&publisher=<p>&year=<y>&duration=<s>&comment=<c>
```

## Other Settings

It should be noted that there is no protection against multiple Twitch chat bots,
multiple Kick bots, etc.  This can result in double posts and other weirdness.
On the client computers, you will want to turn off such services.  Here is a
non-complete list of things to check:

* Artist Extras
* Discord
* Kick Chat
* Twitch (Chat and Requests)

Note that Recognition services such as AcoustID support are required to run
on the client computer as they need access to the local file for those systems
that provide access to it.
