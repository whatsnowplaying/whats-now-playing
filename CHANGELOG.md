
# Changelog

## Version 5.1.0 - 2026-03-26

* macOS
  * This is the last release with pre-built binaries for macOS 11 (Intel) and macOS 12 (Apple Silicon)

* Major New Features
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

* Minor New Features
  * Support Klipy as an alternative to the EOLing Tenor
    * Klipy is preferred when both API keys are configured
  * Add support for autodiscovery using Bonjour/Zeroconf for Remote Output and for
    some upcoming feature support
  * Add a new /v1/status webserver endpoint
  * Requests now support reporting 'for @user'
  * Direct link to your version's documentation from the menu bar/system tray

* General Bug Fixes
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

* Artist Extras
  * Artist biographies are now deduplicated per session. The same bio will not be shown twice
    during a stream. This can be disabled in settings.
  * Last.fm and TheAudioDB can now be used for album art lookup
  * TheAudioDB basic features no longer require an API key

* Discord
  * Bot Mode and Rich Presence are now independently toggled
  * Bot Mode can now post to a channel with cover art

* Denon
  * Fixed a crash on certain network environments during device discovery

* Kick and Twitch
  * Twitch accounts will now be automatically linked to your Charts profile at startup
    * A warning is shown if the account is already linked to a different Charts profile
  * Token refreshes for Kick and Twitch would sometimes get lost
  * Twitch and Kick OAuth authentication status is now more accurately reflected in the Settings panel
    * The panel now shows the actual account name(s) associated with authenticated tokens
    * Stale authentication state from a previous session is cleared on startup

* Serato
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

* Traktor
  * partially corrupted XML library files no longer cause a complete import failure;
    parsing continues with whatever data was successfully read

* VirtualDJ
  * partially corrupted XML library files no longer cause a complete import failure;
    parsing continues with whatever data was successfully read

* Linux
  * Linux binary builds are now available

* Developer Stuff
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

* New Features
  * ANNOUNCING [WHAT'S NOW PLAYING CHARTS](https://whatsnowplaying.com/)!
    * Now you can help the community figure out what DJs are ACTUALLY
      PLAYING on their streams!
    * After installing, copy your anonymous key from your client into
      the website to unlock a ton of features!

  * Everything renamed to WhatsNowPlaying
    * Quite a few things had already been renamed to use the new
      name.  It was time to finish the job.
    * The rename includes the Documents directory.  As part of the
      upgrade, the new Documents/WhatsNowPlaying directory will
      have your previous content also copied into it.

  * Many UI element upgrades
    * Major overhaul of the UI with many pages getting some clean up
    * On launch, an arrow will show you where the minimized icon is
      (relatively) supposed to be
    * Tree-structure to help organize various categories
    * Many preferences are now in tabs to make them less crowded
    * New startup window system shows progress tracking
    * AcoustID and MusicBrainz setup split apart

  * New Output System
    * Remote server support to send results to a central computer
      to consolidate one or more DJs into one set of outputs
    * Text Output was moved here
    * Set lists are now built in real-time and can be customized

  * Twitch
    * Switched from deprecated PubSub to WS-EventSub
    * Twitch Redemptions and Requests are back
    * Authentication system now simplified and self-contained
    * Added contextual help system for chat commands (e.g., !track help)

  * Requests Overhaul
    * Fuzzy matching with customizable threshold for track requests now
      handles some typos and natural language input
    * !hasartist chat command to search either entire
      DB or specific crates/playlists
    * Support for animated gifs/memes based upon text from Tenor

  * Title Filtering Overhaul
    * A new, simplified filter system for removing text from titles has been
      implemented. The newer one is much easier to use without having to do
      a lot of extra work.
    * The complex regex-based filter is still present and available, but
      upgrading to this version will remove existing filters and use
      a default set of useful filters.

  * Web Server changes
    * Removed bundled templates that did not use websockets
    * Revamped old templates to remove some sizing and background issues with OBS
    * New templates that mirror the boring templates everyone else uses
    * New templates with new special effects
    * All templates may now be referenced by name (e.g, `/template.htm` -> `/templates/template.htm`)
    * ws-gifwords-fade.htm to show GifWords requests
    * ws-justthecover.htm to cycle through all of the front covers
    * Bundled copies of some common libraries available via the `/vendor` endpoint
    * New remote control APIs

  * Several new template variables
    * discordguild
    * has_video
    * kickchannel
    * lyricist
    * now
    * timestamp
    * today
    * track_received
    * twitchchannel

  * Completely revamped documentation website to make it easy to pick your version
  * Upgrade downloads are now sent through whatsnowplaying.com/download so that
    users can be pointed to the correct one, see release notes, etc.
  * Distribution files now use user-friendly naming (e.g., WhatsNowPlaying-5.0.0-macOS12-AppleSilicon.zip,
    WhatsNowPlaying-5.0.0-Windows.zip) making it easier to identify the correct download for your platform

* Windows Binary Overhaul
  * The binaries for Windows now come as a directory rather than a single
    executable.  This was done to speed up launch time by removing the
    need to extract the content.

* Bug fixes
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

* Removed
  * The non-websocket templates have been removed. The code to support your old
    templates is still there, but you should really update.

* Denon
  * Many Denon devices using Stagelinq should now be supported

* DJUCED
  * Revamped database support
  * hasartist support
  * Smart playlists should now be supported

* Icecast (butt, Traktor, MIXX, others)
  * Icecast protocol fixes to make it more reliable
  * Fixed an issue where files without metadata were not properly doing "dash" separations.
    For example, a title of "The Pixies - Monkey Gone to Heaven" will now get split into
    artist: "The Pixies" title: "Monkey Gone to Heaven" so that proper metadata handling
    from there on out will work. Of course, properly tagged files are way better.

* Serato
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

* Traktor
  * Revamped database support, including automatic database refresh running in the background
  * hasartist support

* Virtual DJ
  * Revamped database support, including automatic database refresh running in the background
  * hasartist support

* Important Internal Changes
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
