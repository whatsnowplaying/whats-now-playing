Virtual DJ
==========

      NOTE: This source does not support Oldest mix mode.

The Virtual DJ input source is a specialized version of the `M3U source <m3u.html>`_
that also provides access to playlists for `Request support <../requests.html>`_ .

.. image:: images/virtualdj.png
   :target: images/virtualdj.png
   :alt: Virtual DJ Settings

On install, the Virtual DJ directories should be set correctly for most
computers.  If they are not set correct, use the 'Select Dir' buttons to
point to the correct ones.

If the History does not exist, then you may need to change the time
on Virtual DJ's history output as well as actually play a track on a
deck long enough for the history file to be created.

Click the Re-read Playlists button to cause **What's Now Playing** to
re-read Virtual DJ's playlists for roulette-style requests.  Be aware that
playlist files are only updated when Virtual DJ is closed.

The `Use Remix Field` option will attempt to ignore the Remix entry that Virtual DJ puts inside the history file.  However, if the media file has the remix data in the track title, that will still be read.  For example, if an MP3 file has ID3 tag data that has "Purple Rain (Are You Depressed Yet Remix)" the full title will be used.

Changing Metadata
-----------------

Be aware that sometimes Virtual DJ will write to the history file in such a way that **What's Now Playing** may appear to go a bit crazy.  In general, this situation appears to happen when changing the tag data in Virtual DJ while **What's Now Playing** is running.  In order to prevent that from happening, it is recommended:

1. Play a track
2. Pause **What's Now Playing** from the menu so that it will ignore history changes.
3. Make your change
4. Play the next track
5. Unpause **What's Now Playing**