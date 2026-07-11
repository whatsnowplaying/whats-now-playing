# Feature Overview

**What's Now Playing (WNP)** is a free, open-source DJ stream metadata bridge
for Windows, macOS, and Linux that reads live track data from DJ software and
sends it anywhere your audience can see it: overlays, chat bots, Discord, text
files, and more. It is used by everyone from hobby Twitch streamers to
professional event DJs and internet radio stations.

## Setup

On first launch, WNP **automatically detects** which DJ software you are using,
with no manual source selection required for most setups. Software-based sources
(Serato, Traktor, Virtual DJ, etc.) are detected from files they write to disk.
Hardware-based sources (Denon StageLinQ) are detected from the network. The
detected source is shown in **Core Settings → Source** and can be changed at
any time.

## Multi-Computer Setup

Many DJs stream from a dedicated PC while running their DJ software on a
separate laptop. WNP is built for this. The **Remote Output** feature
automatically sends live track data from 2 or more DJ machines to a central
WNP instance over the local network, covering everything from a simple
DJ-laptop/streaming-PC split to a full multi-DJ event where each performer's
laptop feeds the same streaming machine.

* No IP addresses to configure; uses Bonjour/Zeroconf auto-discovery
* No port forwarding needed; works on any home or venue network
* Works across platforms (DJ laptop on macOS, streaming PC on Windows, or
  any combination)
* 2 or more DJ machines can all send to a single central instance simultaneously
* Install WNP on each machine, point the DJ machines at the central one,
  and it just works

See [Remote Output](input/remote.md) for setup details.

## Input Sources

WNP reads track data directly from DJ software and media players. No manual
updates required.

### DJ Software

* **[Serato DJ](input/serato.md)** — full library support, crate/playlist queries, streaming
  services, artist search
* **[Traktor](input/traktor.md)** — database integration with background refresh, artist search
* **[Virtual DJ](input/virtualdj.md)** — history and playlist database with background refresh,
  artist search
* **[Denon DJ](input/denon.md)** (StagelinQ protocol) — direct network connection to supported
  hardware
* **[djay Pro](input/djaypro.md)** — track detection and metadata
* **[DJUCED](input/djuced.md)** — database integration, smart playlists, artist search
* **[JRiver Media Center](input/jriver.md)** — via network API
* **[MIXXX](input/mixxx.md)** — via MPRIS2 (Linux) or Windows Media API (Windows)

### Protocol-Based Sources

* **[Icecast](input/icecast.md)** — receives metadata from butt, Traktor, MIXXX, and other
  Icecast-compatible streaming sources
* **Remote API** — HTTP-based input for MegaSeg, Radiologik, and other
  software with HTTP output support
* **[M3U playlists](input/m3u.md)** — file-based input for any software that writes M3U files

### System-Level Sources

* **[Windows Media API](input/winmedia.md)** — reads from Spotify, Amazon Music, SoundCloud,
  Windows Media Player, and any other Windows media application
* **[MPRIS2](input/mpris2.md)** (Linux) — reads from VLC, Rhythmbox, Spotify, and any
  MPRIS2-compatible player

### [Vinyl, CDJs & Analog Mixers](https://whatsnowplaying.com/earshot)

* **[WNP EarShot](https://whatsnowplaying.com/earshot)** — companion app for macOS, iOS, and
  watchOS that uses Shazam-based audio identification to detect tracks playing on
  vinyl decks, standalone CDJs, Rekordbox, and analog mixers, then sends them to
  WNP automatically over the local network. No software integration with the
  hardware required.
* **[Always-Accept mode](input/earshot.md)** — enabled by default. When EarShot identifies a track it
  overrides the active DJ software source automatically, with no manual source switching
  required mid-set. Can be disabled for setups where EarShot should only be used as the
  primary source.

### [Remote WNP Instance](input/remote.md)

* A central WNP instance can receive track data from two or more DJ machines
  simultaneously over the network, covering everything from a simple
  DJ-laptop/streaming-PC split to a full multi-DJ event.
  Supports auto-discovery via Bonjour/Zeroconf.

## Track Recognition

For tracks that are untagged or missing metadata:

* **[AcoustID](recognition/acoustid.md)** — audio fingerprinting to identify tracks by sound
* **[MusicBrainz](recognition/musicbrainz.md)** — look up detailed track and artist metadata by fingerprint
  or ID

## Cover Art and Artist Enrichment

WNP automatically downloads cover art and artist images as each track plays —
no manual uploads or per-track tagging required.  Sources are queried in
priority order; the first provider with usable data wins.  Multiple providers
can be enabled together for fallback coverage.

| Source                                              | Bio | Artist images | Cover art | API key  |
| --------------------------------------------------- | --- | ------------- | --------- | -------- |
| **[Cover Art Archive](recognition/musicbrainz.md)** |     |               | ✓         | none     |
| **[Wikimedia / Wikipedia](extras/wikimedia.md)**    | ✓   | ✓             |           | none     |
| **[TheAudioDB](extras/theaudiodb.md)**              | ✓   | ✓             | ✓         | bundled  |
| **[Discogs](extras/discogs.md)**                    | ✓   | ✓             | ✓         | free\*   |
| **[FanArt.TV](extras/fanarttv.md)**                 |     | ✓ (HD)        | ✓         | free\*   |
| **[Last.fm](extras/lastfm.md)**                     |     |               | ✓         | free\*   |

\* Free signup required for an API key.  Last.fm's free tier is
non-commercial; commercial broadcasters should consult their licence.

Artist biographies are deduplicated per session; the same bio will not be
shown twice during a stream.

## Outputs and Display

### OBS Integration

* **[OBS WebSocket](output/obswebsocket.md)** — push track data directly to OBS text sources in
  real time
* **[Browser Sources](output/webserver.md)** — serve custom HTML overlays via the built-in web
  server for display in OBS or any browser
* **[OBS Scene Export](output/obs-export.md)** — generate a ready-to-import OBS 28+ scene collection
  JSON file from the system tray ("Export for OBS…"). Select which browser
  sources to include, choose the template for each, set dimensions and layout
  hints (fill, top, bottom, left, right, center), and preview each template
  before exporting. The file is saved directly to the OBS scenes directory
  (auto-detected per platform) so it appears in OBS immediately without
  manual file copying.

### [Web Server](output/webserver.md)

WNP includes a built-in web server that serves customizable browser-based
overlays using the Jinja2 template engine. Supports:

* Real-time updates via WebSockets
* Full HTML, CSS, and JavaScript customization
* 45 bundled OBS browser overlay templates, including animated WebGL/canvas effects
* 13 full-screen [dynamic background templates](gallery/dynamic-backgrounds.md) that
  automatically adapt to cover art palette colors via WebGL
* Access to all track metadata as template variables
* Remote control APIs

### [Text Output](output/textoutput.md)

Write track data to plain text files for use with any software that can read
a text file, including older OBS setups and streaming tools.

### Set Lists

Real-time set list generation as tracks are played, available as a template
variable and exportable.

## Chat Bot Integration

### [Twitch Bot](output/twitchbot.md)

* Automatic track announcements when tracks change
* 36 bundled announcement and response templates for Twitch, Kick, and text output
* Configurable announcement templates with full Jinja2 support
* Chat commands for viewers: `!track`, `!artist`, `!album`, and more
* Contextual help via `!track help`
* Channel point redemption support
* Automatic stream title updates on each track change using a Jinja2 template
* Per-command permission controls (broadcaster, moderator, subscriber, VIP)
* Cooldown timers per command and per user

### [Kick Bot](output/kickbot.md)

* Automatic track announcements when tracks change
* Configurable announcement templates

### [Discord Bot](output/discord.md)

* Track announcements posted to a Discord channel
* Optional cover art in announcements
* Rich Presence support (independently toggleable from Bot Mode)

### [Lumia Stream](output/lumiastream.md)

* Dedicated Lumia Stream plugin exposes 26 track metadata variables including title, artist,
  BPM, key, cover art URL, and cover art color palettes
* Fires a **Track Changed** alert on every track change for light shows, overlays, and automations
* Install by downloading the `.lumiaplugin` file from the plugin repository and adding it
  manually in Lumia Stream

## Audience Engagement

### [Guess Game](output/guessgame.md)

A Twitch chat-based guessing game where viewers try to identify the current
track. Features include:

* Viewers guess artist and/or title via chat commands
* Configurable scoring and timing
* Leaderboards and personal stats accessible via chat commands
* Real-time OBS overlay showing game state
* Integration with the whatsnowplaying.com online leaderboard
* System tray toggle to enable or disable at runtime

### [Track Requests](requests.md)

Viewers can request tracks directly from Twitch chat:

* Fuzzy matching handles typos and natural language (e.g. 'anything by Nine
  Inch Nails')
* `!hasartist` command to check if an artist is in the library
* Supports searching the full library or specific crates/playlists
* Channel point redemption support
* Moderation queue with approve/reject controls
* Animated GIF/meme responses via Klipy

## Metadata Processing

### Template System

All outputs use the Jinja2 template engine with access to a rich set of
[template variables](reference/templatevariables.md) including artist, title,
album, artwork, biographies, MusicBrainz IDs, timestamps, and more.

Built-in templates ship inside the application and are always current with
the release — nothing needs to be copied into your Documents folder. Your
templates directory holds only files you create or customize, organized
into `twitch/`, `kick/`, `setlist/`, and `web/` subfolders; a file there
overrides the built-in template of the same name. The template chooser in
every settings page lists built-in and customized templates together, with
a "Customize a Copy" button that places an editable copy in the right
folder. Template updates and designs saved in the online template editor
arrive automatically in the `synced/` folder, and upgrading from an older
release reorganizes your existing templates automatically (originals are
kept in `templates_pre6`).

### [Filters](settings/filter.md)

Clean up track metadata before output:

* Remove unwanted text from titles (e.g. "(Radio Edit)", "feat. ...",
  "- Original Mix")
* Configurable via the UI with a simple rule system
* Works across all outputs simultaneously

### [Track Skip](settings/trackskip.md)

Automatically skip tracks matching configurable metadata rules. For example,
skip any track with "SKIP" in the genre field.

### Multi-Value Fields

Handles multi-value metadata fields (multiple artists, multiple ISRCs) across
MP3, FLAC, M4A, and AIFF formats.

## Charts and Analytics

**[What's Now Playing Charts](https://whatsnowplaying.com/)** is an optional
community service that tracks what DJs are playing across streams. It is free,
requires no account to start, and is built into WNP with no configuration needed.

* WNP automatically submits track data using an anonymous API key generated
  on first run, with no account required to contribute
* Create an account (via Twitch or Kick login) to unlock a public DJ profile at
  `whatsnowplaying.com/profile/(your-username)` showing:
  * Play statistics: total plays, unique songs, and unique artists
  * Top 10 tracks and artists with play counts
  * Genre profile: auto-generated breakdown of your sets by genre and subgenre
  * DJ setlists from recent streams, downloadable in multiple formats
  * Recent track feed with artist, album, and timestamp
  * Replay: year-in-review analytics for your streams
* Community charts showing top tracks and artists across all streamers
* Online Guess Game leaderboard integration
* [Chat Token](https://whatsnowplaying.com/docs/chat-token): a read-only token for displaying
  the currently playing track in Nightbot, StreamElements, Streamlabs Cloudbot, or any chatbot
  supporting URL fetching

## Platform Support

* **Windows** 10 and later
* **macOS** 11 (Big Sur) and later
* **Linux** — native binary builds available

## Configuration and Portability

* Export and import configuration as JSON for moving between systems
* Home directory paths are automatically remapped on import
* Stale legacy configuration keys are automatically cleaned up on upgrade

## References

* [Template Variables](reference/templatevariables.md) — full list of available metadata variables
* [Input Sources](input/index.md) — detailed setup for each DJ software integration
* [Output & Display](output/index.md) — OBS, web server, text output, and set lists
* [Artist Data](extras/index.md) — Discogs, FanArt.TV, TheAudioDB, Wikimedia
* [API Reference](reference/api.md) — web server REST API
