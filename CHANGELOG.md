
# Changelog

## Version 4.1.0 - Unreleased

* IMPORTANT! SOME SETTINGS WILL BE CHANGED:
  * Artist Extras support is now on
  * Musicbrainz support and Musicbrainz fallback is now on
  * The new Wikimedia support is now on (see below)
* IMPORTANT! 'artistthumb' has been renamed to 'artistthumbnail'
  in the metadata. For most users, this change is invisible, but
  if you use the API directly, be aware of this change.
* IMPORTANT! All of the default templates have had their formatting
  cleaned up here and there.  Additionally, many of the `ws-` files
  have had their CSS cleaned up so that they scale more much more
  proportionaly to the browser window. In OBS, you will likely need
  to remove any excess CSS in the Properties setting in order for
  them to work correctly.  This change makes it possible to use,
  for example, the rotating artist fanart collection in place of
  artist thumbnails as well as have a better chance of success with
  extremely long track titles.
* EXPERIMENTAL! Added support for DJUCED DJ software!
* EXPERIMENTAL! Special handling for Youtube downloaded content that
  hasn't been properly tagged.
* EXPERIMENTAL! When doing some data lookups, if a song is a remix
  then fallback to the non-remixed version to at least try to locate
  artist data.
* Added Wikimedia as a source if the wikidata entity URL is available
  as an artist website, such as if Musicbrainz website data is selected.
* Reworked metadata gathering again and likely lost some performance in the
  process.  But the higher quality sources should now be picked first.
* Discogs should now honor Discogs artist URLs if they are available
  in the artist website data.
* With the last two in mind, discogs and wikidata links from Musicbrainz
  will always be present in the website data if Musicbrainz is turned on.
* Fixed some issues with 'The' disappearing from artist names.
* Musicbrainz lookups should be much more reliable when certain tags
  are defined.
* If covers cannot be found, other artwork may now be substituted via the
  artistextras settings.
* A new websocket example template (`ws-justthecoverhtm`) that just shows
  the cover is now available.
* Template variable 'genres' has been added as a _list_ as opposed to
  'genre' which is a single string.  Only Musicbrainz currently supports
  filling in the 'genres' variable.
* It should now do a better job of using various manipulations of names.
  For example, MӨЯIS BLΛK will also trigger searches for Moris Blak
  in many places. Probably not perfect, but something is better than
  nothing.
* Better support for "artist feat. artist" and other forms of multiple
  artists working together.  However, as a trade-off, some identification
  features that used to work no longer do. For example, "Prince & The
  Revolution" will get recognized for "Purple Rain", but just
  "Prince" may not.)
* theaudiodb language fallback should now work better.
* Added a new twitchbot template that shows track and bio information
  as a more complex example of what can be done with the twitch bot.
* Twitch chat now has a default announcement template that will be set
  on new installs.
* If `Original Date` or `Original Year` tags are able to be read, those
  will be used in place of `Date` and `Year` tags.
* Some comments metadata tags that were not being read correctly should have
  a higher chance of success now.
* Internal: Changed the method by which the software looks for the 'Documents'
  folder on new installs because Windows 11 really wants you to use
  OneDrive.
* Internal: Artwork caching should now work much better when substitutions
  are being done using recognition with the new `imagecacheartist` DB value.
* Internal: Greatly improved a lot of out timeout problems by adding some
  timeout values to many of the 3rd party frameworks in use.  As a result,
  there are a lot more customized bits rather than using off-the-shelf
  components. :(
* Internal: The usual dependency updates.

## Version 4.0.6 - 2023-06-15

* Setlists were not getting created.
* Fresh installs would not actually install.

## Version 4.0.5 - 2023-06-09

* Musicbrainz fill-in feature should be less crash-prone
* Ability to force Twitch chat bot to post rather than reply
* Twitch bot permissions should be more reliable
* Quite a few small bug fixes all over that could potentially lead to crashes
* Dependency fixes as usual
* Some log cleanup
* Minor perf enhancements here and there
* Experimental: duration/duration_hhmmss
* keep menu item running longer so users do not think the app is actually
  shut down
* document the windows media support
* change source code line length to 100
* change how plugins are defined

## Version 4.0.4 - 2023-05-07

* Experimental feature: Given an option to use Musicbrainz to fill in missing
  metadata based only on artist and title (and album if available).
* Add support for AVIF graphics. At some point, all of the templates will be
  updated to handle multiple formats so be prepared!
* On Windows, the ability to read from Windows Media Transport compatible
  software, such as Amazon Music, Soundcloud, and likely others. (Ironically,
  Windows Media Player doesn't appear to use it for whatever reason.)
* Ability to disable reading Virtual DJ remix fields from the M3U history file.
  This feature has no impact on what is read from the media itself. In other words,
  if the MP3 is tagged with '(Remix)' that will still show up.
* Twitch redemptions using the 'Twofer' format now has the track title as optional.
* The internal twitch lock should now be less likely to deadlock.
* Some log messages have been bumped up from debut to error.
* Unit tests ran during development have been improved.
* Rework the development process; now almost entirely `pyproject.yaml`-based.
* Some major doc changes here and there.
* Rework and simplify some of the internals of plugins.
* Along with that, sources that do not have the required operating
  system component installed won't show up as a possible selection in the UI.
* The usual dependency updates that should improve program speed and dependability.

## Version 4.0.3 - 2023-03-26

* Force binaries to build with Python 3.10 as 3.11 causes problems.
* Verify the image cache at startup and every hour
* Fixed some bugs around base64 encoding in the webserver
  that would trigger a 500 HTTP error
* missed an await in trackrequest that cause it to go awol
* Quiet down the logging of Virtual DJ playlist import
* Try to make the artistextras artwork handling consistent when
  artist names are in disagreement. (Part 1)
* Change TCP timeouts in artistextras to be based on track delay times
  if possible
* Fix some edge-case crashes with artistextras
* Push the discord more :D
* Enhanced the automated testing of some parts of the code base
* More dependency updates
* Add some debug messages for some rare issues
* JSON test source now supports random tracks

## Version 4.0.2 - 2023-03-12

* Some dependency updates which should improve a few edge-case problems.
* Prevent the app from being accidentally launched twice.
* On new installs, the webserver is now enabled by default.
* Some internal cleanup/simplification.
* Some dialog changes for new installs.
* Twitch chatbot token should now auto-strip 'oauth:' again if that is put into
  the settings field.

## Version 4.0.1 - 2023-03-02

* Do not crash if a Native Instruments directory exists
  without a Traktor installation.
* Log the platform in the debug log.
* Make the installer actually install.

## Version 4.0.0 - 2023-02-27

### Major Changes

* New logic for first-time users to attempt pre-configuring
  some things.  This change also removes the requirement
  of having a file that has to be written.
* Support for Icecast which enables butt, MIXXX,
  and many, many more.
* New support specifically for Traktor and Virtual DJ.
* OBS Websocket v5 support for OBS Studio v28+. Older versions
  of OBS Websocket are not supported.
* Twitch support major overhaul! New UI and support for
  track requests via channel point redemptions or chat or both.
* Additionally, Twitch support for randomized requests
  tied to crates/playlists.
* New Discord support to update a bot's status
* Upgrades from v1 and v2 are no longer supported.  You will need
  to upgrade to v3 first if you wish to save your settings.
* The plain text file output now supports append!
* Webserver supports serving static content from the NowPlaying/httpstatic
  directory.  Useful for when you want to add logos to the web templates.
* There wis now a check for newer versions of the software being available!

### Internal/Minor Changes

* New About menu item, new icon, and new logo!
* Minor website redesign and direct download links in Quickstart.
* Some new and updated templates to clean up some things and to
  show off the new features.
* Cover art should now be shown when using Tidal on Serato.
* Using other streaming services on Serato should no longer break
  some of the artist features.
* Virtual DJ's custom m3u entries will now attempt to be used,
  enabling external services such as Deezer.
* Major structural changes internally over a series of
  code changes so that TrackPoll may support asyncio. A
  side benefit has been that various parts of the system
  are just generally faster, more efficient.
* Metadata processing finally got some (simple) parallelization.
* Subprocess handling is now much more streamlined and should
  be less impacted by crashes.
* Speaking of crashes, many edge-case crashes have been eliminated.
* Along the same line, quite a few general concurrency issues fixed.
* SSL certificate authority file is now built into the binary
  to prevent weird SSL errors.
* Serato processing has gotten a major overhaul.
* Artist URLs should now be normalized as well as better
  de-duplication (e.g., http vs. https to the same site)
* Moved various bits of source around in the source tree
  to ease maintenance.
* MusicBrainz should be more reliable in a few cases.
* A few more things are now using pathlib.
* Better error reporting/capturing for a few things.
* A simple JSON-based source plug-in to help test things out.
* The usual doc updates to with the changes.
* Several rounds of dependency updates.
* Some updates for logging to better capture problems when they occur
  and better status reporting in others.  Plus some logs have been removed
  entirely.
* Python v3.10 is now required.

## Version 3.1.3 - 2023-01-03

* Allow downgrade from v4.0.0
* Fix issues with some closed websocket connections
* Fix some crashes if the setlist is empty
* Verify expected version of python if building from scratch

## Version 3.1.2 - 2022-11-03

* Reworked filtering support to use user-supplied regular expressions.
  * If the title filtering added in 3.1.0 was enabled, it will be
    converted to use the new regular expression support.
* Beginning support for setlists:
  * New previoustrack template variable.
  * Example !previoustrack Twitchbot command to give users ability to
    query the track list.
  * New option to write the complete setlist to a file for either your
    own recording keeping or to share on social media or whatever.
* Upgraded all web templates to jquery 3.6.1
* Added some new example websocket templates

## Version 3.1.1 - 2022-10-17

* AcoustID and MusicBrainz may now run independently! If you
  would like MB support but would like to disable AcoustID,
  please check out the new settings window.  Note that
  AcoustID requires MusicBrainz support to be turned on and
  will enforce that.
* If MusicBrainz Artist IDs are present, they will trigger
  artist website URL downloads if MusicBrainz support is enabled.
* There was a bug with enabling Artist Extras and not restarting
  causing (effectively) a hang.  Turning on Artist Extras still
  requires a restart but it should no longer crash the first
  time.
* Twitch bot messages may now be split up by using `{{ startnewmessage }}`
  as a template variable.
* Mixmode (Newest/Oldest) got some fixes that now make it correctly
  unavailable/set for various types of drivers.
* 'Official Music Video' is now removed when clean/explicit/dirty is
  also removed.
* Some docs updates to clarify some things.
* The Qt test code got a major overhaul to improve debugging the UI.

## Version 3.1.0 - 2022-09-29

* IMPORTANT! Big Twichbot changes:

  * help, hug, and so have been removed. Removing those from your
    local install will not re-install on relaunch.
  * whatsnowplayingversion command has been added.  This command is
    a built into the source code to help with debugging
    installs. It cannot be removed or disabled.
  * A new example !artistshortbio command for the biographies
    support.
  * On startup, all of the existing twitchbot_ files will be analyzed
    and added to the preferences pane with a default of **DISABLED**.
    You will need to re-enable any that you wish to use.  Command files
    added while the software is running will be available immediately
    but then next startup will be disabled.
  * trackdetail got some minor cleanup.

* New experimental feature: artist extras

  * Banners
  * Biographies
  * Fan art
  * Logos
  * Thumbnails

  * Also bundled are some new web server template files that may be used
    as examples for your own stream.

* New experimental feature: Track title filtering

  * Some DJ pools will add 'clean', 'dirty', or 'explicit' entries to
    track titles.  There is now a feature to attempt to remove those
    descriptors from the track title.

* 'artistwebsites' variable has been added and is a list of websites that have
  been either pulled from the tag or from external sources.
* MusicBrainz artist IDs and ISRCs are now lists of IDs. Additionally, Files
  tagged with an ISRC or MusicBrainz Recording IDs should now properly
  short-cut AcoustID DB lookups.
* In several places, locks were switch to be context-based to remove
  resource leakage due to bugs in Python.
* Fixed some leaks that would prevent multiple launches.
* Metadata for date, label, and some MusicBrainz IDs were not always correct.
* More metadata information from FLAC files.
* A bit of tuning on the acoustid recognition code.
* Will now try looking up artists without 'The' attached
* Some log tuning, but also produce more logs with new features and for
  better debugging ability ...
* PNG converter should be less noisy and a bit faster.
* Python 3.9 is now required.
* Some documentation updates.

## Version 3.0.2 - 2022-07-12

* Fix some PyInstaller binary packaging issues

## Version 3.0.1 - 2022-07-12

* Serato will no longer register tracks that
  aren't marked as 'played' in the Serato session files.
* Removed ACRCloud support.
* MPRIS2 albums are now properly handled as strings.
* Upgraded to Qt 6, which appears to have fixed a few UI issues.
* Fix link to quirks doc.
* Slightly different name matching logic that should be
  more consistent for some tracks when trying to use
  recognition tools.
* If the track changes during the delay, do not report it.
  Instead, repeat the cycle and make sure it is consistent
  for the entirety of the delay period.
* Updated various dependencies to fix some security
  and reliability issues.
* Some documentation updates.
* Python version updated to 3.9
* Upgrades for some CI bits.

## Version 3.0.0 - 2021-11-27

* Significant reworking of the code base that allows
  for many more features to be added and be much less
  crash-prone.
* Completely revamped user settings to handle all
  of the new features
* Settings should now move from one version to another when upgrading.
* Bundled example template changes:
  * Most of the examples have been rewritten
  * basic/complex.txt renamed to basic/complex-plain.txt
  * basic/complex.htm renamed to basic/complex-web.htm
  * New WebSocket-based examples (ws-) allow for near realtime
    updates
* Template macro changes:
  * `year` has been replaced with `date`
  * `publisher` has been replaced with `label`
  * `hostfqdn`, `hostip`, `hostname`, `httpport` have been added for
    better webserver support
  * `musicbrainzalbumid`, `musicbrainzartistid`, `musicbrainzrecordingid`
    have been added when either audio recognition is enabled or
    already present in tags
  * `discsubtitle` has been added
* Ability to use two different music recognition services
  so that untagged or even tagged files now have metadata
* Documentation updates:
  * [New home](https://whatsnowplaying.github.io/)!
  * Major documentation overhaul
  * Move it from Markdown to ReStructuredText
* Outputs:
  * Rewritten webserver backend to be more efficient and support
    WebSockets.
  * Add a TwitchBot, including the ability to announce track changes
  * Added support for writing to the [OBS Web Socket
    plugin](https://github.com/Palakis/obs-websocket)
  * Now write data to a sqlite DB while running and switch all
    output timing based upon writes, enabling multiprocess
    handling
* Inputs:
  * Added ability to support more than just Serato
  * Add support for m3u files, which should enable Virtual DJ support
  * Add support for MPRIS2 on Linux
  * Add ability to ignore some decks in Serato local mode
* macOS support for Big Sur, Monterey, and Apple M1
* Improved support for `mp4` and `m4v` files

## Version 2.0.1 - 2021-05-27

* Better support for AIFF and FLAC
* Major fix for processing Windows' Serato session files

## Version 2.0.0 - 2021-04-07

* Main program name change: SeratoNowPlaying -> NowPlaying
* Fixed licensing
  * Added a proper license file
  * Switched to PySide2 and added a NOTICE file for it
* No longer need to pre-create the text file that gets written.
* New HTTP Server built for users who need fade-in/fade-out and other effects
* Rewritten local mode:
  * Cover art in HTTP mode
  * Better character encoding for non-Latin titles
  * Oldest and Newest modes for picking the oldest or newest
    track loaded on a deck
  * Significantly more data available to write out!
* Templated output instead of hard-coded output settings. Upon first
  launch, a new NowPlaying directory will appear in your Documents folder.
  Inside that will be a templates directory that has the example
  templates.
* Logging infrastructure to help debug: currently turned down. Future
  versions will have the ability to crank up the noise.
* Configuration system has been completely revamped.
  * Settings will now survive between software upgrades.
  * Added a 'Reset' button to get you back to defaults.
  * They are now stored in system-friendly ways (e.g., Library/Preferences
    in OS X).
  * Defaults are much more likely to be correct for your system.
* Major internal, structural changes to allow for easier ability to add new features.
* Now installable via pip
* Significant documentation updates
* Binaries should now report their versions in Get Info/Properties
* Many, many bug fixes... but probably new ones added too.

## Version 1.4.0 - 2020-10-21

* Fix for issue where Settings UI window did not fit on smaller resolution screens.
  The window is now re-sizeable and scrolling is enabled.
* Augmented the suffix and prefix functionality. The Artist and Song data chunks
  now can have independent suffixes and prefixes.
* Added version number to Settings window title bar.

## Version 1.3.0 - 2020-10-17

* Added ability to read latest track info from Serato library history log. User
  now can choose  between local or remote (Serato Live Playlists) polling
  methods.
* Fix for issue where app would not launch on Windows due to not being able to
  create config.ini.
* Changed polling method for increased efficiency.
* Other enhancements due to new code and functionality.

## Version 1.2.0 - 2020-10-17

## Version 1.1.0 - 2020-09-25

## Version 1.0.0 - 2020-09-22
