# Changelog

## Version 5.2.1 - 2026-05-05

### Bug Fixes

* Fixed incorrect Discord invite link in About window
* Fixed a bug where track detection silently stopped after a system sleep/wake
    cycle or transient error
* Fixed cover art being truncated in EarShot and two-computer setups
* Fixed Wikipedia, MusicBrainz, Discogs, and fanart.tv remembering
    transient errors (rate limits, network failures) as "no data" for
    hours or days, so artist bios, images, and album metadata for the
    affected track stayed blank until the entry expired.  Stale entries
    are cleared automatically on upgrade
* Improved how WNP behaves when Wikipedia is rate-limiting traffic:
    WNP now backs off for as long as Wikipedia asks (honoring their
    Retry-After header) and caps parallel Wikipedia requests, so a
    short throttling window no longer cascades into prolonged missing
    artist data

### Artist Extras

* Discogs and fanart.tv now fetch album cover art when available, using
    data already retrieved during artist lookups (no extra API calls);
    each provider has a new Cover Art checkbox in settings
* MusicBrainz cover art fetching from Cover Art Archive can now be
    toggled via a new checkbox in MusicBrainz settings (enabled by default)

### djay Pro

* BPM, key, and deck number are now read from djay Pro's analysis database
    and included in track metadata
* ISRC codes are now included in track metadata when djay Pro provides
    them, improving downstream metadata lookups
* Configurable analysis delay: how long to wait for djay Pro to make BPM,
    key, and file path available after a track starts
* Configurable deck skip: individual decks can be excluded from reporting
    via checkboxes in settings
* Tracks already playing when WNP launches are silently skipped, preventing
    stale tracks from being re-reported on startup
* These features should work but I lack a full djay Pro license to test:
  * The Twitch `!hasartist` chat command now works with djay Pro
  * Added playlist support: available playlists can now be selected for
      artist queries and roulette requests

### MusicBrainz

* Improved album and album art selection when an album name is provided by
    EarShot iOS and macOS. The canonical studio album is preferred over
    compilations or reissues that happen to contain the same recording.
* Improved album selection for ISRC-only lookups: canonical singles and
    studio releases are preferred over compilations and reissues
* Fixed cover art going permanently missing for a track after a single
    failed fetch from the Cover Art Archive; failed fetches now retry
    on the next play
* Fixed false rate-limit errors when talking to MusicBrainz

## Version 5.2.0 - 2026-05-04

### New Features

* WNP EarShot: new input source for vinyl, CDJs, and analog mixers via
    Shazam-based identification; supports Always-Accept mode as a secondary
    monitor alongside any DJ software source
* OBS Scene Collection exporter: "Export for OBS..." tray menu item generates
    a ready-to-import OBS scene collection with pre-configured browser sources,
    including WebGL and CSS-only Guess Game scenes
* New animated WebGL game board and leaderboard overlays for Guess Game
* Eight new WebGL and effects "Now Playing" overlay templates; see the
    templates documentation for details
* `ws-typing-matrix` rebuilt as a full matrix digital rain canvas animation
    with falling katakana characters
* Template preview now available from Twitch Bot, Kick Bot, Text Output,
    Discord, and Discord channel settings; includes a "Use This Template" button

### Remote Output

* Fixed duplicate Charts submissions when both sender and receiver have
    Charts enabled

### Kick & Twitch

* Stream title can now be updated automatically on each track change using
    a Jinja2 template (requires re-auth if upgrading)
* Twitch broadcaster tokens are no longer cleared on shutdown
* Fixed authentication when the webserver port wasn't 8899

### MPRIS

* Reduced log noise for unavailable D-Bus services and idle state

### UI

* Major overhaul of all settings screens for improved layout and consistency
* Tray icon switches automatically between light and dark variants based on
    OS color scheme; new Auto/Light/Dark override in General settings
* Fixed dark mode rendering on several UI panels on Linux and Windows

### djay Pro

* Fixed one-track-behind detection on Windows; djay Pro writes analysis data
    and history in separate transactions, so track changes now debounce the WAL
    file event to ensure both writes have landed before querying

### VirtualDJ

* Track metadata is now pulled from the local library database for previously
    cataloged tracks
* Key and BPM from the Scan element are captured when not present in track tags
* BPM is now correctly converted from VirtualDJ's internal format

### Platform

* macOS binaries are now code-signed and notarized
* Windows binaries are now signed with Azure Trusted Signing
* Fixed font scaling on Windows and Linux settings screens

### Removed

* Tenor GIF support; use Klipy instead

### Bug Fixes

* Track titles with duplicate parenthetical suffixes (e.g.
    `Song (Radio Edit) (radio edit)`) are now collapsed to a single suffix
* Fixed SQL injection, XSS, and unpinned CI action security issues
* BPM and key now read correctly from M4A files with duplicate fields
* Guess Game menu item is grayed out when Twitch Bot is not configured
* Filenames with en dash separators (e.g. `Artist – Title.mp4`) now split
    correctly when track tags are absent
* YouTube `Artist_-_Title` filenames now split correctly even without a
    YouTube URL in the file tags

### Developer Stuff

* Dependency updates
* **Python 3.10 is no longer supported**; minimum version is now Python 3.11
* **Python 3.14 is now supported**
* Replaced vendored musicbrainzngs with wnpmb: ~3,500 lines of XML-based
    client code replaced with a JSON async client with improved release
    selection, HTTP/2 support, and artist name normalization; fallback
    title-strip matches return artist data only, not a recording ID from the
    stripped title

## Version 5.1.0 - 2026-03-26

### macOS

* This is the last release with pre-built binaries for macOS 11 (Intel) and macOS 12 (Apple Silicon)

### Major New Features

* djay Pro
  * Added basic support for djay Pro
* Guess Game
  * Add a new Twitch chat-based guessing game for your audience
  * System tray toggle to enable or disable the game at runtime
  * Viewers guess the current track via configurable Twitch chat commands
  * Leaderboards, scoring, and personal stats available via chat
  * Real-time OBS overlay support to display game state on stream
  * Support for seeing the current game and leaderboards from the whatsnowplaying.com website
* Last.fm
  * Added support for Last.fm as a source for track metadata

### Minor New Features

* Support Klipy as an alternative to the EOLing Tenor
  * Klipy is preferred when both API keys are configured
* Add support for autodiscovery using Bonjour/Zeroconf for Remote Output and for
    some upcoming feature support
* Add a new /v1/status webserver endpoint
* Requests now support reporting 'for @user'
* Direct link to your version's documentation from the menu bar/system tray

### General Bug Fixes

* Security vulnerability fixes
* SSL certificate verification now uses the system certificate store, fixing
    connection failures on some systems (particularly Windows)
* Major speedup of program launch
* General reliability improvements
* Configuration files can now be exported and imported for portability across systems
  * The exporting machine's home directory is recorded in the config file so paths are
      automatically remapped to the importing machine's home directory
  * Paths that do not exist on the importing system are skipped gracefully, with a
      warnings file generated listing what needs to be manually reconfigured
  * Stale legacy configuration keys from old versions are automatically cleaned up on upgrade
* Smarter upgrade logic
  * Should do a better job of helping you get the correct zip file
  * Linux users now receive correct upgrade notifications
* Found an issue where in some cases changed templates would always trigger an 'update'
    on program launch despite the `.new` file actually being correct.
* Web server template assets (including vendor libraries and guessing game files) now load correctly
* Fixed an issue where Qt SVG support was sometimes unavailable on Windows
* Respinning a request that doesn't have a playlist assigned no longer crashes parts of the system
* Major documentation overhaul
* Minor graphics cleanup
* Arrow overlay now uses a filled arrowhead and wider text area
* Fixed font scaling on Windows in several settings panels

### Artist Extras

* Artist biographies are now deduplicated per session. The same bio will not be shown twice
    during a stream. This can be disabled in settings.
* Last.fm and TheAudioDB can now be used for album art lookup
* TheAudioDB basic features no longer require an API key

### Discord

* Bot Mode and Rich Presence are now independently toggled
* Bot Mode can now post to a channel with cover art

### Denon

* Fixed a crash on certain network environments during device discovery

### Kick and Twitch

* Twitch accounts will now be automatically linked to your Charts profile at startup
  * A warning is shown if the account is already linked to a different Charts profile
* Token refreshes for Kick and Twitch would sometimes get lost
* Twitch and Kick OAuth authentication status is now more accurately reflected in the Settings panel
  * The panel now shows the actual account name(s) associated with authenticated tokens
  * Stale authentication state from a previous session is cleared on startup

### Serato

* Fixed an issue where tracks with null bytes in metadata were not handled correctly
* Add artist-based library query support for Serato 4
  * Search entire library or selected playlists/crates for artist tracks
  * Enhanced crate search and metadata querying capabilities
* Track filename resolution now works correctly using location ID and portable ID mapping
* All Serato library database files are now auto-discovered. Manual path configuration
    is no longer needed
* Changes to better detect when the latest track is playing
* Better support for tracks from streaming services
* Optionally disable tracking of played status

### Traktor

* partially corrupted XML library files no longer cause a complete import failure;
    parsing continues with whatever data was successfully read

### VirtualDJ

* partially corrupted XML library files no longer cause a complete import failure;
    parsing continues with whatever data was successfully read

### Linux

* Linux binary builds are now available

### Developer Stuff

* Dependency updates
* Test fixes
* Update years to 2026
* Getting closer to supporting Python 3.14
* Reduced binary build size by removing unnecessary metadata files
* Rewrote the developer docs and improved `builder.sh`, including the ability to create Linux
    executables.

## Version 5.0.1 - 2025-10-22

This release fixes a critical bug in 5.0.0 that causes it to lock up if the Charts submission fails.

## Version 5.0.0 - 2025-10-20

### ANNOUNCING What's Now Playing Charts

* ANNOUNCING [WHAT'S NOW PLAYING CHARTS](https://whatsnowplaying.com/)!
* Now you can help the community figure out what DJs are ACTUALLY PLAYING on their streams!
* After installing, copy your anonymous key from your client into
  the website to unlock a ton of features!

### Renamed to WhatsNowPlaying

* Quite a few things had already been renamed to use the new name. It was time to finish the job.
* The rename includes the Documents directory. As part of the upgrade, the new
  Documents/WhatsNowPlaying directory will have your previous content also copied into it.

### UI

* Major overhaul of the UI with many pages getting some clean up
* On launch, an arrow will show you where the minimized icon is (relatively) supposed to be
* Tree-structure to help organize various categories
* Many preferences are now in tabs to make them less crowded
* New startup window system shows progress tracking
* AcoustID and MusicBrainz setup split apart

### New Output System

* Remote server support to send results to a central computer to consolidate one or more DJs
  into one set of outputs
* Text Output was moved here
* Set lists are now built in real-time and can be customized

### Twitch

* Switched from deprecated PubSub to WS-EventSub
* Twitch Redemptions and Requests are back
* Authentication system now simplified and self-contained
* Added contextual help system for chat commands (e.g., !track help)

### Requests Overhaul

* Fuzzy matching with customizable threshold for track requests now
  handles some typos and natural language input
* !hasartist chat command to search either entire DB or specific crates/playlists
* Support for animated gifs/memes based upon text from Tenor

### Title Filtering Overhaul

* A new, simplified filter system for removing text from titles has been implemented.
  The newer one is much easier to use without having to do a lot of extra work.
* The complex regex-based filter is still present and available, but upgrading to this
  version will remove existing filters and use a default set of useful filters.

### Web Server

* Removed bundled templates that did not use websockets
* Revamped old templates to remove some sizing and background issues with OBS
* New templates that mirror the boring templates everyone else uses
* New templates with new special effects
* All templates may now be referenced by name (e.g., `/template.htm` -> `/templates/template.htm`)
* ws-gifwords-fade.htm to show GifWords requests
* ws-justthecover.htm to cycle through all of the front covers
* Bundled copies of some common libraries available via the `/vendor` endpoint
* New remote control APIs

### New Template Variables

* discordguild
* has_video
* kickchannel
* lyricist
* now
* timestamp
* today
* track_received
* twitchchannel

### New Features

* Completely revamped documentation website to make it easy to pick your version
* Upgrade downloads are now sent through whatsnowplaying.com/download so that
  users can be pointed to the correct one, see release notes, etc.
* Distribution files now use user-friendly naming (e.g., WhatsNowPlaying-5.0.0-macOS12-AppleSilicon.zip,
  WhatsNowPlaying-5.0.0-Windows.zip) making it easier to identify the correct download for your platform

### Windows Binary Overhaul

* The binaries for Windows now come as a directory rather than a single
    executable.  This was done to speed up launch time by removing the
    need to extract the content.

### Bug fixes

* M3U-based systems (Virtual DJ) file watching fixes
* Wikimedia links did not correctly redirect
* MP4 files with XMP data should get some info now
* Fixed an issue with MP4 reader getting confused if tags are after the media data
* TheAudioDB and ImageCache downloader handle rate limiting
    and other such problems better.
* Kick would invalidate keys if their OAuth server was down... which happens a lot.
    Now if WNP can't connect, it won't invalidate.
* The ability to set the poll watcher time somehow got dropped from the
    Quirks UI along the way

### Removed

* The non-websocket templates have been removed. The code to support your old
    templates is still there, but you should really update.

### Denon

* Many Denon devices using Stagelinq should now be supported

### DJUCED

* Revamped database support
* hasartist support
* Smart playlists should now be supported

### Icecast (butt, Traktor, Mixxx, others)

* Icecast protocol fixes to make it more reliable
* Fixed an issue where files without metadata were not properly doing "dash" separations.
    For example, a title of "The Pixies - Monkey Gone to Heaven" will now get split into
    artist: "The Pixies" title: "Monkey Gone to Heaven" so that proper metadata handling
    from there on out will work. Of course, properly tagged files are way better.

### Serato

* New Dual Serato Support
  * Very basic and experimental support for Serato 4.  Since that is the future of Serato,
      a few renames in the UI have happened to show Serato vs Serato Legacy or Serato3. The
      system will copy over settings from Serato 3 to Serato on upgrade if your current
      input source is Serato.
  * Future releases will attempt to bring it to parity.
* Before the beta drop, some changes to Serato Legacy had already happened:
  * Support for more than one `_Serato_` library path
  * Smart crates now have limited support
  * hasartist support for crates, smart crates, or the full database

### Traktor

* Revamped database support, including automatic database refresh running in the background
* hasartist support

### VirtualDJ

* Revamped database support, including automatic database refresh running in the background
* hasartist support

### Important Internal Changes

* Windows build server is now running on Server 2022
* Python 3.11 is now the base version
* Vendoring (like versioningit) is now required before launching from the dev area
* WinMedia is now using the winrt set of modules
* Python types are slowly getting added
* Added comprehensive TypedDict definitions for track requests
* Improved requests database reliability with retry logic for Windows
* Enhanced PyInstaller build system with automatic module discovery
* Switched to `ruff` code formatter
* Switched to `mkdocs` for website
* New build system for web templates
* Settings UI now has a new generic tab loading system
* Major reorganization of core code in lots of places, with many
    classes and modules getting broken up
* Switched back to vendored TinyTag
