# How Do I

## Improve Results (cover art, biography, etc)

See the page on [Accuracy](accuracy.md)

## Change the Twitch command from `!track` to `!song`?

The Twitch commands are all read directly from files. So copying one
file to another is an easy way to add commands:

1. Copy the `Documents/WhatsNowPlaying/templates/twitchbot_track.txt`
   file to `twitchbot_song.txt`
2. Restart **What's Now Playing**
3. Go into Twitch Chat settings and set the permissions as required.

## Change the time Twitch announcements happen?

Under Settings -\> Twitch Chat there is an 'Announce Delay' field that
takes number of seconds to wait before announcing to chat. To things to
keep in mind:

1. It takes partial seconds, so .5 would be half of a second.
2. This delay is **in addition** to the write delay under General.
   Therefore if Write Delay is 5 seconds and Twitch Chat Announce Delay
   is 5 seconds, it should be approximately 10 seconds from the track
   being switched out before the message goes out.

## Put artist biographies in Twitch chat?

1. Enable [Twitchbot](../output/twitchbot.md)
2. Enable one of the [Artist Extras](../extras/index.md) that supports
   biographies.
3. If your track metadata only has artist and title, you may need to
   [Enable Recognition](../recognition/index.md)
4. Edit your Twitch Chat announce template to include either
   `{{ artistshortbio }}` or `{{ artistlongbio }}`
5. Restart **What's Now Playing**

## Put artist graphics on my OBS/SLOBS/SE.Live/etc?

Configure a `Browser Source` for your scene and put in one of the
Supported URLs that is listed on the [Webserver](../output/webserver.md)
page.

## Stop autoposting the track info in Twitch chat?

1. Under Settings -\> Twitch Chat, set the announce template to be empty.
2. Save

## Back up my settings or transfer them to a new machine?

1. On the source machine, open Settings → General
2. Click **Export Configuration** and save the JSON file somewhere safe
3. On the destination machine, open Settings → General
4. Click **Import Configuration** and select the JSON file
5. Save and restart **What's Now Playing**

File paths that don't exist on the new machine are skipped automatically. A
`_import_warnings.txt` file is created next to the import file listing any paths
that need to be reconfigured manually.

> [!WARNING]
> The exported file contains API keys, passwords, and other sensitive data.
> Store it securely and delete it when no longer needed.

## Set up the Guess Game?

1. Make sure [TwitchBot](../output/twitchbot.md) is configured and connected
2. Make sure the [Webserver](../output/webserver.md) is enabled
3. Open Settings → Guess Game and configure to your liking, then Save
4. Enable the game from the menu bar (macOS) or system tray (Windows) by
   clicking **Guess Game**
5. To show the game state in OBS, add a Browser source pointed at
   `http://localhost:8899/guessgame/guessgame.htm`
6. To show leaderboards, add a Browser source pointed at
   `http://localhost:8899/guessgame/guessgame-leaderboard.htm?type=session`
   or `?type=all_time`

See the full [Guess Game](../output/guessgame.md) documentation for scoring,
templates, and customization options.

## Show the Guess Game online at whatsnowplaying.com?

1. Sign up at <https://whatsnowplaying.com> and copy your API key
2. Add the API key under Settings → Charts
3. Make sure the Guess Game is enabled (see above)
4. Under Settings → Guess Game → Advanced, ensure **Send to Server** is enabled
5. Your game board will be available at
   `https://whatsnowplaying.com/guessgame/(your-twitch-username)`

## Speed up track changes by disabling artist extras?

Artist extras (biographies, images, etc.) make network calls to external services
on every track change, which can add several seconds of delay. To disable them:

1. Open Settings → Artist Extras
2. Uncheck every service you don't need (Discogs, FanartTV, TheAudioDB, Wikimedia)
3. Save

If you only use artist extras for specific outputs (e.g. a biography in Twitch chat
but not in OBS), you can leave just that one service enabled and disable the rest to
reduce the number of API calls made per track.
