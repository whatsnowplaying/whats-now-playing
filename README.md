# What's Now Playing

![Logo](docs/images/wnp-logo-small.png?raw=true)

**What's Now Playing** retrieves live track information from DJ
software and displays it on streams, in chat, or anywhere else you need it.

**[Start here: Complete Documentation & Setup Guide](http://whatsnowplaying.github.io/)**

## Supported Software

**DJ Software:** Serato DJ, Traktor, Virtual DJ, Denon DJ (StagelinQ), djay Pro, DJUCED, MIXXX

**Media Players:** JRiver Media Center, Windows Media API (Spotify, Amazon Music, and more),
MPRIS2-compatible players (Linux)

**Via Icecast:** butt and other Icecast-compatible sources

**Via Remote API:** MegaSeg, Radiologik, and other apps with HTTP output

**File-based:** M3U playlists

**Via EarShot:** Vinyl decks, standalone CDJs, Rekordbox, and analog mixers —
using Shazam-based audio identification on macOS, iOS, and watchOS

## Two-Computer Setup

WNP supports the common scenario where DJ software runs on one machine and
OBS/streaming runs on another. The Remote Output feature uses Bonjour/Zeroconf
auto-discovery with no IP configuration needed. See the
[Remote Output docs](https://whatsnowplaying.github.io/whats-now-playing/latest/input/remote/)
for details.

## Download

[Get the latest release](https://github.com/whatsnowplaying/whats-now-playing/releases)
in binary or source forms.

## Quick Links

- **[Quickstart Guide](http://whatsnowplaying.github.io/quickstart/)** - Get up and running
- **[Feature Overview](http://whatsnowplaying.github.io/features/)** - Everything WNP can do
- **[Gallery](http://whatsnowplaying.github.io/gallery/)** - See it in action
- **[Charts](https://whatsnowplaying.com/signup)** — track your play history, view listening stats,
  and unlock the online Guess Game board
- **[Discord Community](https://discord.gg/bGdgm64Erb)** - Get help and share setups

---

## For Developers

This is an open-source Python application using Qt6 for the interface. See
the [developer documentation](http://whatsnowplaying.github.io/help/developers/)
for contributing guidelines and architecture details.
