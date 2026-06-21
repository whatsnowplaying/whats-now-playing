# Lumia Stream

Lumia Stream integration fires a **nowplaying-switchSong** alert in Lumia Stream each time a new
track becomes live, enabling light shows, overlays, and automations that react to your music.

## What it provides

When a track changes, What's Now Playing sends the following metadata to Lumia Stream:

* **title** - Track title
* **artist** - Artist name
* **album** - Album name
* **label** - Record label
* **bpm** - Tempo in BPM
* **key** - Musical key
* **comment** - Track comment field
* **length** - Duration in seconds
* **id** - ISRC code (if available)
* **image** - Cover art URL (served from What's Now Playing's built-in web server)

## Setup

1. Open Lumia Stream and go to **Settings → Advanced**.
2. Enable the **Developers API** and click **Show Token** to reveal your API token.
3. In What's Now Playing, open **Output & Display → Lumia Stream**.
4. Check **Enable** and paste your token into the **API Token** field.
5. Leave **Port** at the default (`39231`) unless you have changed it in Lumia Stream.

## Configuration

* **Enable** - Turn Lumia Stream integration on or off
* **API Token** - The token from Lumia Stream's Developers API settings (stored securely)
* **Port** - The port Lumia Stream listens on (default: `39231`)

## How it works

When enabled, the plugin sends an HTTP POST to `http://localhost:{port}/api/send` each time a
track changes. The payload fires Lumia Stream's built-in `nowplaying-switchSong` alert type, which
you can map to light commands, overlays, or any other Lumia automation in the Lumia Stream UI.

Cover art is delivered as a URL pointing to What's Now Playing's local web server
(`http://localhost:{webserver-port}/cover.png`), so Lumia Stream can fetch the image directly.
The **Web Server** output must be enabled for cover art to be available.

## Troubleshooting

* **No lights changing** - Confirm Lumia Stream is running and the Developers API is enabled.
* **Authentication failed (401)** - Re-copy the token from Lumia Stream; tokens reset if you
  restart Lumia Stream or regenerate them.
* **Connection refused** - Verify the port matches what Lumia Stream is configured to use.
* **No cover art** - Enable the **Web Server** output so the cover image endpoint is active.
