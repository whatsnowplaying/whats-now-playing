# Feature Overview

**What's Now Playing (WNP)** is a free, open-source application for Windows,
macOS, and Linux that reads live track data from DJ software and sends it
anywhere your audience can see it — overlays, chat bots, Discord, text files,
and more.

## Setup

On first launch, WNP **automatically detects** which DJ software you are using —
no manual source selection required for most setups. Software-based sources
(Serato, Traktor, Virtual DJ, etc.) are detected from files they write to disk.
Hardware-based sources (Denon StageLinQ) are detected from the network. The
detected source is shown in **Core Settings → Source** and can be changed at
any time.

## Input Sources

WNP reads track data directly from DJ software and media players. No manual
updates required.

### DJ Software

* **Serato DJ** — full library support, crate/playlist queries, streaming
  services, artist search
* **Traktor** — database integration with background refresh, artist search
* **Virtual DJ** — history and playlist database with background refresh,
  artist search
* **Denon DJ** (StagelinQ protocol) — direct network connection to supported
  hardware
* **djay Pro** — track detection and metadata
* **DJUCED** — database integration, smart playlists, artist search
* **JRiver Media Center** — via network API
* **MIXXX** — via MPRIS2 (Linux) or Windows Media API (Windows)

### Protocol-Based Sources

* **Icecast** — receives metadata from butt, Traktor, MIXXX, and other
  Icecast-compatible streaming sources
* **Remote API** — HTTP-based input for MegaSeg, Radiologik, and other
  software with HTTP output support
* **M3U playlists** — file-based input for any software that writes M3U files

### System-Level Sources

* **Windows Media API** — reads from Spotify, Amazon Music, SoundCloud,
  Windows Media Player, and any other Windows media application
* **MPRIS2** (Linux) — reads from VLC, Rhythmbox, Spotify, and any
  MPRIS2-compatible player

### [Vinyl, CDJs & Analog Mixers](https://whatsnowplaying.com/earshot)

* **[EarShot](https://whatsnowplaying.com/earshot)** — companion app for macOS, iOS, and
  watchOS that uses Shazam-based audio identification to detect tracks playing on
  vinyl decks, standalone CDJs, Rekordbox, and analog mixers, then sends them to
  WNP automatically over the local network. No software integration with the
  hardware required. Requires WNP 5.2.0 or later.

### [Remote WNP Instance](input/remote.md)

* One WNP instance can receive track data from another WNP instance over the
  network, allowing a central streaming PC to consolidate output from one or
  more DJ machines. Supports auto-discovery via Bonjour/Zeroconf.

## Track Recognition

For tracks that are untagged or missing metadata:

* **[AcoustID](recognition/acoustid.md)** — audio fingerprinting to identify tracks by sound
* **[MusicBrainz](recognition/musicbrainz.md)** — look up detailed track and artist metadata by fingerprint
  or ID

## Artist Data Enrichment

WNP can automatically fetch additional artist information to enhance displays:

* **[Discogs](extras/discogs.md)** — artist biographies and images
* **[TheAudioDB](extras/theaudiodb.md)** — artist biographies, images, and album art (free tier
  available without API key)
* **[FanArt.TV](extras/fanarttv.md)** — high-quality fan art, artist logos, and background images
* **[Wikimedia / Wikipedia](extras/wikimedia.md)** — artist biographies and images
* **[Last.fm](extras/lastfm.md)** — album art lookup
* **MusicBrainz** — artist website links, IDs, and relationship data

Artist biographies are deduplicated per session — the same bio will not be
shown twice during a stream.

## Outputs and Display

### OBS Integration

* **OBS WebSocket** — push track data directly to OBS text sources in
  real time
* **Browser Sources** — serve custom HTML overlays via the built-in web
  server for display in OBS or any browser
* **OBS Scene Export** — generate a ready-to-import OBS 28+ scene collection
  JSON file from the system tray ("Export for OBS…"). Select which browser
  sources to include, choose the template for each, set dimensions and layout
  hints (fill, top, bottom, left, right, center), and preview each template
  before exporting. The file is saved directly to the OBS scenes directory
  (auto-detected per platform) so it appears in OBS immediately without
  manual file copying.

### Web Server

WNP includes a built-in web server that serves customizable browser-based
overlays using the Jinja2 template engine. Supports:

* Real-time updates via WebSockets
* Full HTML, CSS, and JavaScript customization
* Bundled template library with multiple styles
* Access to all track metadata as template variables
* Remote control APIs

### Text Output

Write track data to plain text files for use with any software that can read
a text file, including older OBS setups and streaming tools.

### Set Lists

Real-time set list generation as tracks are played, available as a template
variable and exportable.

## Chat Bot Integration

### Twitch Bot

* Automatic track announcements when tracks change
* Configurable announcement templates with full Jinja2 support
* Chat commands for viewers: `!track`, `!artist`, `!album`, and more
* Contextual help via `!track help`
* Channel point redemption support
* Per-command permission controls (broadcaster, moderator, subscriber, VIP)
* Cooldown timers per command and per user

### Kick Bot

* Automatic track announcements when tracks change
* Configurable announcement templates

### Discord Bot

* Track announcements posted to a Discord channel
* Optional cover art in announcements
* Rich Presence support (independently toggleable from Bot Mode)

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

### Filters

Clean up track metadata before output:

* Remove unwanted text from titles (e.g. "(Radio Edit)", "feat. ...",
  "- Original Mix")
* Configurable via the UI with a simple rule system
* Works across all outputs simultaneously

### Track Skip

Automatically skip tracks matching configurable metadata rules — for example,
skip any track with "SKIP" in the genre field.

### Multi-Value Fields

Handles multi-value metadata fields (multiple artists, multiple ISRCs) across
MP3, FLAC, M4A, and AIFF formats.

## Charts and Analytics

**[What's Now Playing Charts](https://whatsnowplaying.com/)** is an optional
community service that tracks what DJs are playing across streams:

* WNP automatically submits track data using an anonymous API key generated
  on first run — no account required to contribute
* Create an account (via Twitch or Kick login) to unlock a personal DJ profile
* View your play history, top tracks, and session stats
* Community charts showing top tracks and artists across all streamers
* Time-filtered views (24h, 7d, 30d, all time) by platform and genre
* Online Guess Game leaderboard integration

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
