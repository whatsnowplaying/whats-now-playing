Templates
=========

Now Playing handles almost all output via the `Jinja2 templating system <https://jinja2docs.readthedocs.io/>`_ which
includes an extremely `powerful language <https://jinja2docs.readthedocs.io/en/stable/templates.html>`_ that enables you a
full range of customizing the output.

In general, Now Playing provides a generic set of variables that can be used in any template. These values are filled in
dependent upon the input source and whether the media has been appropriately tagged.  Some examples:

* An MP3 file missing ID3 tags may only have `title` available.
* Serato in Remote mode, title and optionally artist are available.

Additionally, some outputs (e.g., TwitchBot) may provide additional variables that provide additional, context-sensitive features.
See their individual pages for more information.


.. list-table::
   :header-rows: 1

   * - Variable
     - Description
   * - album
     - Album track comes from
   * - albumartist
     - Artist listed on the album
   * - artist
     - Artist for the song
   * - bitrate
     - Bitrate the file was encoded at
   * - bpm
     - Beats per minute of the song
   * - composer
     - Composer of the song
   * - coverurl
     - Relative location to fetch the cover. Note that this will only work when the webserver is active.
   * - disc
     - Disc number
   * - disc_total
     - Total number of discs in album
   * - filename
     - Local filename of the media
   * - genre
     - Genre of the song
   * - key
     - Key of the song
   * - lang
     - Language used by the media
   * - publisher
     - Publisher of the media
   * - title
     - Title of the media
   * - track
     - Track number on the disc
   * - track_total
     - Total tracks on the disc
   * - year
     - Year or date of the media
