# djay Pro Support

djay Pro is DJ software by Algoriddim available for macOS and Windows.

> NOTE: This is basic support with the groundwork in place. Artist query features are not yet implemented.
>
> NOTE: Only tested with djay Pro 5.x on macOS and Windows
>
> NOTE: iOS and Android versions are not supported

## Instructions

[![djay Pro Source Selection](images/djaypro-source-selection.png)](images/djaypro-source-selection.png)

1. Open Settings from the **What's Now Playing** icon
2. Select Core Settings->Source from the left-hand column
3. Select djay Pro from the list of available input sources

[![djay Pro Directory Selection](images/djaypro-dir.png)](images/djaypro-dir.png)

1. Select Input Sources->djay Pro from the left-hand column
2. Enter or, using the button, select the directory where the djay Pro media library is located
   * macOS: `~/Music/djay/djay Media Library.djayMediaLibrary`
   * Windows: `%USERPROFILE%/Music/djay/djay Media Library`
3. Click Save

## How It Works

**What's Now Playing** monitors djay Pro in two ways:

* **NowPlaying.txt file** (macOS): djay Pro writes current track info to this file in real-time
* **Media Library database**: Queries the play history from djay Pro's SQLite database

The plugin automatically uses the appropriate method based on your platform and djay Pro configuration.

## Known Limitations

* Artist query features are not supported
  * The !hasartist Twitch chat command will not work
  * Roulette playlist requests are not available
* Only "newest" mix mode is supported

## Troubleshooting

If tracks are not being detected:

1. Verify the djay Pro media library directory path is correct
2. Check that djay Pro is actively playing tracks
3. Ensure the MediaLibrary.db file exists in the configured directory
4. Try playing a few tracks to populate the play history
5. Check the **What's Now Playing** logs for database connection errors
