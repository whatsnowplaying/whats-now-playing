# Templates

**What's Now Playing** handles almost all output via the [Jinja2
templating system](https://jinja.palletsprojects.com/en/stable/) which includes an
extremely [powerful
language](https://jinja.palletsprojects.com/en/stable/templates/)
that gives you a full range of options for customizing the output.

**What's Now Playing** provides a generic set of variables for use in any template,
but **not all variables will be populated in every situation**. What is available
depends on several factors:

- **Input source**: different DJ software exposes different metadata
- **Media tag quality**: files with missing or incomplete tags will have empty fields
- **Enabled features**: variables like `requester` are only set when the Requests
  feature is active; `artistlongbio` only when Artist Extras is configured;
  `acoustidid` only when AcoustID recognition is enabled
- **File format compatibility**: some formats have limited tag support
- **Tag presence**: fields like `originalyear`, `composer`, or `lyricist` are only
  set when the track's file or DJ software actually provides them

Unpopulated variables are always set to an empty string rather than being undefined,
so templates can safely use `{% raw %}{% if variable %}{% endraw %}` to check before displaying. See the
[Undefined](#undefined) section below for details.

Some outputs (e.g., TwitchBot) provide additional context-specific variables beyond
this list. See their individual pages for more information.

## Reminder

In order to perform these lookups, certain data is required to be tagged in the media for a minimum
level of accuracy. More data == better results. Therefore, media with ISRC tags will cause
MusicBrainz lookups if that service is enabled to fill in any missing data.

## Supported Variables

| Variable | Description |
| ---- | ---- |
| album | Album track comes from |
| albumartist | Artist listed on the album |
| acoustidid | AcoustID fingerprint identifier (if recognition is enabled) |
| artist | Artist for the song |
| artistlongbio | Full biography of the artist (from "Artist Extras") |
| artistshortbio | First paragraph of the long bio (from "Artist Extras") |
| artistwebsites | List of URLs for the artist |
| bitrate | Bitrate the file was encoded at |
| bpm | Beats per minute of the song |
| comments | Comments from either the DJ software or the song file, whichever is discovered first |
| composer | Composer of the song |
| coverurl | Relative location to fetch the cover. Note that this will only work when the webserver is active. |
| date | Date (either release date or date of the media) |
| deck | Deck # this track is playing on |
| disc | Disc number |
| discsubtitle | disc subtitle (if there is one) |
| disc_total | Total number of discs in album |
| discordguild | Discord guild/server name (if bot is connected) |
| duration | Total expected track time in seconds |
| duration_hhmmss | Same as duration but in `HH:MM:SS` format (so 1 minute 30 seconds becomes 01:30) |
| filename | Local filename of the media |
| genre | Genre of the song |
| has_video | `True` if the file contains video content, `False` for audio-only files |
| hostip | IP address of the machine running **What's Now Playing** |
| hostfqdn | Fully qualified hostname of the machine running **What's Now Playing** |
| hostname | Short hostname of the machine running **What's Now Playing** |
| httpport | Port number that is running the web server |
| isrc | List of [International Standard Recording Code](https://isrc.ifpi.org/en/) |
| key | Key of the song |
| kickchannel | Kick channel name (if configured) |
| label | Label of the media |
| lang | Language used by the media |
| lyricist | Lyricist of the song |
| musicbrainzalbumid | MusicBrainz Album Id |
| musicbrainzartistid | List of MusicBrainz Artist Ids |
| musicbrainzrecordingid | MusicBrainz Recording Id |
| now() | Current time in HH:MM:SS format (function call) |
| originalyear | Original release year of the song |
| previoustrack | See [Previous Track Details](#previous-track-details) below |
| publisher | Publisher of the media |
| requestdisplayname | Display name of the viewer who requested this track |
| requestedfor | Viewer the track was requested for (e.g. from `!track song for @user`) |
| requester | Twitch username of the viewer who requested this track |
| source_agent_name | Name of the DJ software providing the track (e.g. `traktor`, `serato`) |
| source_agent_version | Version of the DJ software (if available) |
| timestamp() | Current date and time in YYYY-MM-DD HH:MM:SS format (function call) |
| title | Title of the media |
| today() | Current date in YYYY-MM-DD format (function call) |
| track | Track number on the disc |
| track_total | Total tracks on the disc |
| twitchchannel | Twitch channel name (if configured) |
| year | Release year of the media |

## Implementation Notes

### Arrays

Some fields that might be multi-valued (e.g., genre) will be merged into
one. If they are not merged, the description will specifically say it is
a list.

### Undefined

When rendering templates, **What's Now Playing** will set any undefined
variables to the empty string. Instead of having to render a template
as:

``` jinja
{% raw %}
{% if variable is defined and variable is not none and variable|length %}
{% endraw %}
```

This can be short-cut to:

``` jinja
{% raw %}
{% if variable %}
{% endraw %}
```

since the variable will always be defined. This also means that
templates that incorrectly use the wrong variable name will render, just
with an empty string in place of the expected text.

## Previous Track Details

The `previoustrack` variable is a list of recently played tracks, newest first.
Index `0` is the current track, index `1` is the one before it, and so on.
It holds the artist and title of each track. Some examples:

To show the current artist playing:

``` jinja
{{ previoustrack[0].artist }}
```

To show the previous-to-current artist:

``` jinja
{{ previoustrack[1].artist }}
```

To get the title of the track played 2 tracks ago:

``` jinja
{{ previoustrack[2].title }}
```

For a more complex example, see the
`twitchbot_previoustrack.txt` file in the
templates directory.

## Time Functions

**What's Now Playing** provides several time-related functions that can be called in
templates to add timestamps. These are particularly useful for setlists and logging
when tracks were played:

| Function | Example Output | Description |
| ---------- | ---------------- | ----------- |
| `now()` | `14:32:15` | Current time when the template is rendered |
| `today()` | `2023-12-15` | Current date when the template is rendered |
| `timestamp()` | `2023-12-15 14:32:15` | Current date and time when the template is rendered |

### Examples

To create a setlist with timestamps showing when each track started:

``` jinja
{{ now() }} - {{ artist }} - {{ title }}
```

To include both date and time:

``` jinja
{{ timestamp() }} | {{ artist }} - {{ title }}
```

To add the current date to each track entry:

``` jinja
{{ today() }}: {{ artist }} - {{ title }}
```

These functions are evaluated each time a template is rendered, so each track will get
the timestamp from when it started playing. Note that templates are rendered once per
track, so any content in the template will be repeated for every track.
