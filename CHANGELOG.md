
# Changelog

## Version 3.0.0 - in progress

* basic/complex.txt renamed to basic/complex-plain.txt
* basic/complex.htm renamed to basic/complex-web.htm
* template macros:
  * year has been replaced with date
  * publisher has been replaced with label
* Rewrite the documentation and move it to ReStructuredText
* Add upgrade code path.
* Rebuild the webserver.
* Add support for m3u files, which should enable Virtual DJ support.
* Add a TwitchBot, including the ability to announce track changes.
* Rework some of the templates.
* Add support for MPRIS2 on Linux
* Support Big Sur and Monterey
* Added support for writing to the [OBS Web Socket
  plugin](https://github.com/Palakis/obs-websocket)
* Revamped settings user interface
* Now write data to a sqlite DB while running and switch all
  output timing based upon writes, enabling multiprocess
  handling
* Add ability to ignore decks in Serato, especially useful
  for scratch DJs
* Ability to use two different music recognition services
  so that untagged files now have metadata
* Significant code re-organization/cleanup/bug fixes/unit tests ...

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
