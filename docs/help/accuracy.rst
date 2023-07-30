Improving Accuracy
==================

The general rule is:  the more data in, the better data out.  A few metadata tags go a very long way. In order
of most important to least important:

1. `Musicbrainz <https://musicbrainz.org//>`_ Recording IDs
2. `International Standard Recording Codes <https://isrc.ifpi.org/en/>`_ aka ISRCs
3. Album + Artist + Title
4. Artist + Title
5. Title

Even after all of that, sometimes things that you think should be found aren't, such as cover art.
Unlike a lot of software, **What's Now Playing** errs on the side of caution.

For example of what I mean, let's take a real world example.  While
testing some of the audio recognition and metadata downloading capabilities,
`Pet Shop Boys - "Vocal" <https://www.youtube.com/watch?v=qNR8gQAoYCs>`_ was used as an input with no
modification the metadata (so, in other words, very much wrong and very much a mess).
Virtual DJ reported the song came from the album
`Electric <https://musicbrainz.org/release/eeb0aa28-b7c9-4109-b8a6-e08611a6ca84>`_ and
provided the cover art for that album.  **What's Now Playing** with AcoustID enabled reported that
the song was actually "Vocal (Radio Edit)" and appears on the album
`Spex CD #110 <https://musicbrainz.org/release/2ccfa7d1-8918-4c41-9945-e302a6053bd8>`_.
Since (at least as of this writing) that album does not have cover art, no cover art was provided.

Which one is correct? Neither and both. It really depends upon the individual DJ's goals.  From a
software perspective, they are both an answer to the cover art question. It also demonstrates how
a bit of manipulation of the title can yield very different results.

This example is also important when working with systems such as Deezer, Tidal, etc, or even WinMedia as
(ultimately) the source of your music.  In the listing above, we are almost always at #4 since many
pieces of the software involved do not provide the album information.  Since there is no other
information, it can sometimes be a bit hit or miss.

For white labels, mixes, etc, the software will try as much as it can to locate something but that
isn't always successful.  In most cases, artist information is usually available.  For mixes that
are more than one person (e.g., "A vs B"-types), the software will generally pick _one_.

In general, the primary principal thus far has been:  if the actual track can't be found, then supply
artist-level data.  If nothing about the artist can be found, then supply nothing extra.

Note that when it comes to finding the actual track: the more precise the better. For example:

  * The Farm's "All Together Now" vs. "Altogether Now"
  * Prince "Purple Rain" vs. Prince and the Revolution "Purple Rain"

Each of those give slightly different results.

Improving the quality of the data is an ongoing project.  If you see something that you think _should_
work but doesn't, feel free to submit a `bug report <bugreports.html>`_ or visit `discord <../contact.html>`_
