Templates
=========

**What's Now Playing** handles almost all output via the
`Jinja2 templating system <https://jinja2docs.readthedocs.io/>`_ which
includes an extremely `powerful language <https://jinja2docs.readthedocs.io/en/stable/templates.html>`_
that enables you a full range of customizing the output.

In general, **What's Now Playing** provides a generic set of variables for use in any template. These
values are filled based on a few factors:

* the input source providing its data
* media tag quality
* **What's Now Playing**'s file type and tag compatibility

Some examples:

* An MP3 file missing ID3 tags may only have `title` available.
* Serato in Remote mode, title, and optionally artist are available.
* MP4/M4V files have minimal support currently in **What's Now Playing**, so will not have the label
* VOBS files do not support tagging and will only have information available from the DJ software, if possible

Some outputs (e.g., TwitchBot) may provide additional variables that offer
other, context-sensitive features. See their pages for more information.

Reminder
--------

In order to perform these look ups, certain data is required to be tagged in the media to
make the results remotely accurate.  More data == more better results.  Therefore, media
with ISRC tags will cause MusicBrainz lookups if that service is enabled to fill in
any missing data.

Supported Variables
--------------------

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
   * - artistlongbio
     - Full biography of the artist (from "Artist Extras")
   * - artistshortbio
     - First paragraph of the long bio (from "Artist Extras")
   * - artistwebsites
     - List of URLs for the artist
   * - bitrate
     - Bitrate the file was encoded at
   * - bpm
     - Beats per minute of the song
   * - comments
     - Comments from either the DJ software or the song file, whichever is discovered first
   * - composer
     - Composer of the song
   * - coverurl
     - Relative location to fetch the cover. Note that this will only work when the webserver is active.
   * - date
     - Date (either release date or date of the media)
   * - deck
     - deck # this track is playing on
   * - disc
     - Disc number
   * - discsubtitle
     - disc subtitle (if there is one)
   * - disc_total
     - Total number of discs in album
   * - filename
     - Local filename of the media
   * - genre
     - Genre of the song
   * - hostip
     - IP address of the machine running **What's Now Playing**
   * - hostfqdn
     - Fully qualified hostname of the machine running **What's Now Playing**
   * - hostname
     - Short hostname of the machine running **What's Now Playing**
   * - httpport
     - Port number that is running the web server
   * - isrc
     - List of `International Standard Recording Code <https://isrc.ifpi.org/en/>`_
   * - key
     - Key of the song
   * - label
     - Label of the media.
   * - lang
     - Language used by the media
   * - musicbrainzalbumid
     - MusicBrainz Album Id
   * - musicbrainzartistid
     - List of MusicBrainz Artist Ids
   * - musicbrainzrecordingid
     - MusicBrainz Recording Id
   * - previoustrack
     - See below for more details.
   * - title
     - Title of the media
   * - track
     - Track number on the disc
   * - track_total
     - Total tracks on the disc


Implementation Notes
--------------------

Arrays
^^^^^^

Some fields that might be multi-valued (e.g., genre) will be merged into one. If they
are not merged, the description will specifically say it is a list.

Undefined
^^^^^^^^^

When rendering templates, **What's Now Playing** will set any undefined variables to the empty string.
Instead of having to render a template as:

.. code-block:: jinja

  {% if variable is defined and variable is not none and variable|length %}

This can be short-cut to:

.. code-block:: jinja

  {% if variable %}

since the variable will always be defined. This also means that templates
that incorrectly use the wrong variable name will render, just with an empty
string in place of the expected text.

Previous Track Details
----------------------

The `previoustrack` variable is a list of played tracks in _reverse_ order, starting with
current track at zero. It currently holds just the artist and the title of the
track. Some examples:

.. code-block:: jinja

  {{ previoustrack[0].artist }}

will show the current artist playing.

.. code-block:: jinja

  {{ previoustrack[1].artist }}

will show the previous-to-current artist.

To get the title of the track played 2 tracks ago:

.. code-block:: jinja

  {{ previoustrack[2].title }}

For a more complex example, see the `twitchbot_previoustrack.txt` file
in the templates directory.
