# Serato 4+

> Using older Serato versions? See [Serato 3.x](serato3.md)

## Setup

1. Open Settings from the **What's Now Playing** icon
2. Select Core Settings->Source from the left-hand column
3. Select "Serato" from the list of available input sources
4. Select Input Sources->Serato from the left-hand column

## Configuration

TODO: put image here

### Local Mode (Recommended)

Select **Local** if **What's Now Playing** runs on the same computer as Serato:

* **Database Status**: Shows whether your Serato library was found automatically
* **Ignore Deck(s)**: Check any decks you want to skip (1, 2, 3, 4)
* **Mix Mode**:
  * **Newest**: Show the most recently started track
  * **Oldest**: Show the longest-playing track

No other setup is required - the plugin finds your Serato library automatically.

### Remote Mode

Select **Remote** if **What's Now Playing** runs on a different computer than Serato:

1. **In Serato**: Enable Live Playlists
   * Go to Setup → Expansion Pack tab
   * Check "Enable Live Playlists"
   * Click "Start Live Playlist" in the History panel

2. **In your web browser**: Make the playlist public
   * Serato opens your Live Playlist webpage
   * Click "Edit Details"
   * Change visibility to "Public"
   * Copy the playlist URL

3. **In What's Now Playing**:
   * Paste the URL into the URL field
   * Set polling interval (30 seconds is recommended)

> **Note:** Remote mode only provides artist and title information.

## Troubleshooting

### "No Serato 4+ installation found"

* Make sure Serato DJ Pro/Lite 4.0+ is installed
* Run Serato at least once after installation
* Restart **What's Now Playing**

### Tracks not showing up

* Make sure tracks are actually playing (not just loaded)
* Check that your crossfader isn't cutting off the track
* Verify your DJ controller is working properly in Serato

### Tracks updating slowly

* Go to Settings → Quirks
* Enable "Use Polling Observer"
* Set polling interval to 1.0 seconds
