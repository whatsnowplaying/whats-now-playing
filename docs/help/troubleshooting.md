# Troubleshooting

Software is made by imperfect humans and thus tends to reflect that reality.
Here are some tips and tricks to help you out.

Also check the current [Bug List](https://github.com/whatsnowplaying/whats-now-playing/issues?q=is%3Aissue+is%3Aopen+label%3Abug+sort%3Aupdated-desc)
to see if any known problems apply to your situation, or join the
[Discord](https://discord.gg/bGdgm64Erb) to get help from the community.

## General Tips

* Start **What's Now Playing** first in your stack, before your DJ software and OBS.
  By the time OBS is up, both **What's Now Playing** and your DJ software will have
  finished their housekeeping tasks.
* Shut down **What's Now Playing** between sessions. Because it lives in the menu bar
  or system tray it is easy to forget it is running.
* Letting the app run when the computer goes to sleep has been shown to cause problems.
  Restart the app after waking from sleep if things seem stuck.

## Tracks Not Updating

* Confirm your DJ software is set as the Source under Core Settings → Source.
* Make sure your DJ software is actually playing — most inputs only detect tracks that
  are actively playing, not just loaded.
* Try increasing the Write Delay under Core Settings → General if updates appear too early
  in your mix.
* Some DJ software behaves differently depending on whether a hardware controller
  is connected. If tracks are not being detected, try with and without your controller
  attached to narrow down the cause.
* **What's Now Playing** tries to honor your crossfader position — if the fader is
  cut to one side, the track on the other deck may not be reported. Make sure the
  fader is in a position that reflects the track you expect to see.
* Check the logs (see below) for any errors related to your input plugin.

## OBS Display Not Updating

* Refresh the Browser source in OBS (right-click → Refresh).
* Confirm the Webserver is enabled and running on the correct port under Output & Display → Webserver.
* Make sure the Browser source URL matches your configured port (default: `8899`).

## Timing and Stream Delay

* There is inherent delay between when your computer plays a track and when it appears
  on-stream. Different devices receive content at different times — Apple TV viewers,
  for example, may see track info up to a minute after you started playing it.
* Kick and Twitch use different CDN locations worldwide, so you may need different
  announce delays per service under their respective settings.
* You do not need to be streaming to participate in Twitch chat. This means you can
  run **What's Now Playing** and test chat announcements without going live — useful
  for dialing in timing.

## Configuration Problems

* If settings appear corrupted or lost, restore from a backup:
  * Open Core Settings → General → **Import Configuration**
  * Select a JSON file from `Documents/WhatsNowPlaying/configbackup/` (created
    automatically before each upgrade) or a manual export you made previously
* If the app fails to start after an upgrade, check the logs for errors before
  reinstalling.

## Finding the Logs

Logs are written to `Documents/WhatsNowPlaying/logs/`. If you are reporting a bug,
including the relevant log file will help enormously. The logging level can be
adjusted under Core Settings → General → Logging Level.
