
# Changelog

## Version 3.1.2 - In progress

* Beginning support for setlists:
  * New previoustrack template variable.
  * Example !previoustrack Twitchbot command to give users ability to
    query the track list.
  * New option to write the complete setlist to a file for either your
    own recording keeping or to share on social media or whatever.

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
