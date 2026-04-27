---
render_macros: true
---

# Quickstart

This guide walks you through getting **What's Now Playing** up and running for the first time.

## Step 1: Download and Install

**[Download the latest release](https://whatsnowplaying.com/download)**
for your platform.

Linux users: see [Linux Setup](help/linux.md) if the app fails to start.

## Step 2: Connect Your DJ Software

**Start your DJ software first**, then launch **What's Now Playing**. WNP auto-detects
your software on startup, so it needs to already be running or have been run at least once.

1. Launch your DJ software and let it fully start up.
2. Launch **What's Now Playing**. The Settings window will open automatically. For some DJ
   software, WNP builds a file index on first run — allow a few minutes for large libraries.
3. Verify or change the auto-detected source under **Core Settings → Source**
4. Follow the setup instructions for your source if needed

A few things to know about auto-detection:

* Software-based sources (Serato, Traktor, Virtual DJ, etc.) are detected from files they
  leave on disk — the software must have been run at least once
* Hardware-based sources (Denon StageLinQ) require the device to be connected and
  actively broadcasting on the network
* The first detected source wins. If multiple are found, you can change it afterwards.
* For **vinyl decks, standalone CDJs, Rekordbox, and analog mixers** (optional):
  [WNP EarShot](https://whatsnowplaying.com/earshot) is a separate companion app that
  identifies tracks via Shazam and sends them to WNP automatically. Only needed if
  your setup does not use DJ software.

See [Input Sources](input/index.md) for per-source setup details.

## Step 3: Verify the Web Server

The built-in web server is enabled by default and runs on port `8899`. You can verify it
is working by opening `http://localhost:8899/` in a browser while a track is playing.

If you need to change the port or other settings, go to **Output & Display → Web Server**.

## Step 4: Set Up OBS

**What's Now Playing** can generate a ready-to-import OBS scene collection with all your
browser sources pre-configured — no manual URL copying or source sizing required.

> NOTE: This requires OBS Studio 28 or later.

1. **Quit OBS Studio** if it is running
2. In **What's Now Playing**, click the system tray icon and choose **Export for OBS...**
3. Review the list of sources. For each one you can choose the template, set the
   width/height, and pick a canvas position. Click **Preview** on any row to see
   how a template looks before committing.
4. Click **Export**
5. Relaunch OBS Studio — the new **WhatsNowPlaying** scene collection will appear
   under **Scene Collection** in the menu bar

WNP ships with 15 browser overlay templates (including 6 WebGL animated effects) and
36 text templates for Twitch, Kick, and plain text output, all ready to use without
any editing. The exported collection contains pre-built scenes for your overlays and
the Guess Game (including WebGL-enhanced versions). Copy the individual browser sources
into your own scenes as needed.

See [Export for OBS](output/obs-export.md) for full details.

If you prefer to set up OBS manually, see [Web Server](output/webserver.md) for
instructions on adding a Browser Source by hand.

> **That's it for basic setup.** If you just want a track overlay in OBS, you're done.
> Everything below is optional. See the [Gallery](gallery/index.md) to browse all included templates.

## Step 5: Announce Tracks in Chat (Optional)

**What's Now Playing** can automatically post track announcements to chat when a new song plays.

* **[Twitch Bot](output/twitchbot.md)**: announcements, chat commands (`!track`, `!artist`),
  channel point redemptions, and the Guess Game
* **[Kick Bot](output/kickbot.md)**: track announcement support

## What's Next?

* **[Artist Extras](extras/index.md)**: automatically fetch artist images and biographies
* **[Track Requests](requests.md)**: let viewers request tracks via Twitch chat
* **[Guess Game](output/guessgame.md)**: a chat game where viewers guess the current track
* **[Templates](reference/templatevariables.md)**: customize every aspect of what gets displayed
* **[Charts](output/charts.md)**: track your play history, view listening stats, and unlock the
  online Guess Game board — sign up at <https://whatsnowplaying.com/signup>
