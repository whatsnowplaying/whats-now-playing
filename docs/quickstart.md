---
render_macros: true
---

# Quickstart

This guide walks you through getting **What's Now Playing** up and running for the first time.

## Step 1: Download and Install

**[Download the latest release](https://whatsnowplaying.com/download)**
for your platform.

See [Platform Notes](#platform-notes) below if you have trouble launching the app.

## Step 2: Connect Your DJ Software

On first launch, **What's Now Playing** attempts to auto-detect your DJ software:

* Software-based sources (Serato, Traktor, Virtual DJ, etc.) are detected from files they
  leave on disk — the software must have been run at least once before auto-detection will work
* Hardware-based sources (Denon StageLinQ) require the device to be connected and
  actively broadcasting on the network
* The first detected source wins — if multiple are found, you can change it afterwards

Before launching, make sure your DJ software has been run at least once. For Traktor, first
launch also includes building a file index — large libraries may take a few minutes.

1. Launch **What's Now Playing** — the Settings window will open automatically
2. Verify or change the auto-detected source under **Core Settings → Source**
3. Follow the setup instructions for your source if needed

See [Input Sources](input/index.md) for per-source setup details.

## Step 3: Verify the Web Server

The built-in web server is enabled by default and runs on port `8899`. You can verify it
is working by opening `http://localhost:8899/` in a browser while a track is playing.

If you need to change the port or other settings, go to **Output & Display → Web Server**.

## Step 4: Add a Browser Source in OBS

1. In OBS Studio, add a new **Browser Source**
2. Set the URL to `http://localhost:8899/`
3. Set the width and height to match your chosen template (check the `width` and `height`
   values in the template files in `Documents/WhatsNowPlaying/templates`)
4. Play a track in your DJ software — track information should appear in OBS

For full details and customization options, see [Web Server](output/webserver.md).

## Step 5: Announce Tracks in Chat (Optional)

**What's Now Playing** can automatically post track announcements to chat when a new song plays.

* **[Twitch Bot](output/twitchbot.md)** — announcements, chat commands (`!track`, `!artist`),
  channel point redemptions, and the Guess Game
* **[Kick Bot](output/kickbot.md)** — track announcement support

## What's Next?

* **[Artist Extras](extras/index.md)** — automatically fetch artist images and biographies
* **[Track Requests](requests.md)** — let viewers request tracks via Twitch chat
* **[Guess Game](output/guessgame.md)** — a chat game where viewers guess the current track
* **[Templates](reference/templatevariables.md)** — customize every aspect of what gets displayed
* **[Charts](output/charts.md)** — track your play history, view listening stats, and unlock the
  online Guess Game board — sign up at <https://whatsnowplaying.com/signup>

---

## Platform Notes

### macOS

Due to security measures in macOS, unsigned apps may require extra steps to open.

* Do not unzip the downloaded package directly to the folder you will run it from.
  Unzip in `Downloads` first, then move `WhatsNowPlaying.app` to `Applications`.
* If the app fails to open, hold **Control** and double-click to open.
* If that does not work, open Terminal and run:
  `sudo xattr -r -d com.apple.quarantine /path/to/WhatsNowPlaying.app`

### Windows

* Windows security may prompt you about an unsigned binary.
  Click **More Info** then **Run Anyway**.

### Linux

* Download the zip for your architecture, extract it, and run the `WhatsNowPlaying` binary.
* A desktop environment is required — this software does not run headless.
* If the binary fails to start, install the following packages (Debian/Ubuntu):

```bash
sudo apt-get install \
  libegl1 \
  libgl1 \
  libdbus-1-3 \
  libfontconfig1 \
  libglib2.0-0 \
  libx11-xcb1 \
  libxcb-cursor0 \
  libxcb-icccm4 \
  libxcb-image0 \
  libxcb-keysyms1 \
  libxcb-randr0 \
  libxcb-render-util0 \
  libxcb-shape0 \
  libxcb-xinerama0 \
  libxcb-xkb1 \
  libxkbcommon-x11-0
```

* If you need to build from source, follow the [developer guide](help/developers.md).

### Other Platforms

Please follow the [developer guide](help/developers.md) to install and run.
