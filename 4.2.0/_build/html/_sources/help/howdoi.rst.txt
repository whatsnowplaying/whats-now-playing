How Do I...
===========

Improve Results (cover art, biography, etc)
-------------------------------------------

See the page on `Accuracy <accuracy.html>`_

Change the Twitch command from `!track` to `!song`?
---------------------------------------------------

The Twitch commands are all read directly from files.  So copying one file to another is an easy way to add commands:

1. Copy the `Documents/NowPlaying/templates/twitchbot_track.txt` file to `twitchbot_song.txt`
2. Restart **What's Now Playing**
3. Go into Twitch Chat settings and set the permissions as required.

Change the time Twitch announcements happen?
--------------------------------------------

Under Settings -> Twitch Chat there is an 'Announce Delay' field that takes number of seconds to wait before announcing to chat.  To things to keep in mind:

1. It takes partial seconds, so `.5` would be half of a second.
2. This delay is **in addition** to the write delay under General.  Therefore if Write Delay is 5 seconds and Twitch Chat Announce Delay is 5 seconds, it should be approximately 10 seconds from the track being switched out before the message goes out.

Put artist biographies in Twitch chat?
--------------------------------------

1. Enable `Twitchbot <output/twitchbot.html>`_
2. Enable one of the `Artist Extras <extras/index.html>`_ that supports biographies.
3. If your track metadata only has artist and title, you may need to `Enable Recognition <recognition/index.html>`_
4. Edit your Twitch Chat announce template to include either ``{{ artistshortbio }}`` or ``{{ artistlongbio }}``
5. Restart **What's Now Playing**

Put artist graphics on my OBS/SLOBS/SE.Live/etc?
------------------------------------------------

Configure a ``Browser Source`` for your scene and put in one of the Supported URLs that is listed on the `Webserver <output/webserver.html>`_ page.

Stop autoposting the track info in Twitch chat?
-----------------------------------------------

1. Under Settings -> Twitch Chat, set the announce template to be empty.
2. Save
