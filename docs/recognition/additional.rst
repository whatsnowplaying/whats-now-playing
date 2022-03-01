Additional Resources
====================

Now Playing includes the capability to download additional, relevant
content made by various online communities in real-time that highlight
the artist being played:

.. csv-table:: Image Resources
   :header: "Type", "WebSocket URL", "Raw Image URL", "WS Height", "WS Width", "General Quality", "Description"

   "Banners", "/artistbanner.htm", "/artistbanner.png", "200px", "No Max", "High", "Image usually with picture and name of artist."
   "Fan Art", "/artistfanart.htm", "", "800px", "1280px", "Varies", "Most sites curate these to be of higher quality but low quality images do get in"
   "Logos", "/artistlogo.htm", "/artistlogo.png",  "200px", "480px", "High", "Stylized text or image that represents the artist"
   "Thumbnails", "/artistthumb.htm", "/artistthumb.png", "480px", "200px", "Varies", "Image of the artist"

Notes:

  - Raw image URLs are not scaled and represent the original format as downloaded.
  - Most fan art tends to be in widescreen.

Additionally, a biography of the artist may now be provided in the 'artistbio' macro. These biographies are
also written by fans and may be brief or fairly detailed.

Important!
----------

It is important to note that only fan art is downloaded in the background.  All of the other content will
block track announcements until they are finished.  There is, however, are several caches used that should
speed up the time for frequently accessed content.


Discogs
-------

Provides: Biographies, Fan art, and Thumbnails

`Discogs <https://www.discogs.com>`_ is a well-known source for music release information, a
marketplace, and more. Be aware of Discogs Terms of Use as linked to on
their `API Page <https://www.discogs.com/developers>`_. All you need to do is
`Get a personal access token <https://www.discogs.com/settings/developers>`_.


fanart.tv
-----------

Provides: Banners, Fan art, Logos, and Thumbnails

`fanart.tv <https://www.fanart.tv>`_ is a community project to provide high quality
artwork for music and other media. It requires music be tagged with
`MusicBrainz <https://www.musicbrainz.org>`_ artist ids or for the audio recognition
system to try to find them for you in real-time. You will need an
`API Key <https://fanart.tv/get-an-api-key/>`_ in order to use this service.


TheAudioDB
-----------

Provides: Banners, Biographies, Fan art, Logos, and Thumbnails

`TheAudioDB <https://www.theaudiodb.com>`_ is a community project to provide high quality
artwork and other metadata for music. If `MusicBrainz <https://www.musicbrainz.org>`_
artist ids are available, it will use that information to increase accuracy. You will need an
`API Key <https://www.theaudiodb.com/api_guide.php>`_ in order to use this service.

