Gallery of Templates
====================

**What's Now Playing** has quite a bit of flexibility in what kind of output
you can generate to the point that there are nearly infinite possibilities.
The text versions are meant to be used to feed other systems and are rather
basic.  E.g., the basic text template generates:

 Utah Saints - Something Good '08

Picking that template, configuring a text source, configuring a scroll filter
on that source, and then writing to it via OBS WebSocket allows one to do:

.. image:: gallery/images/videoloop.webp
   :target: gallery/images/videoloop.webp
   :alt: Scroll demo

For the HTML templates, there are generally two varieties, one that uses
WebSockets (start with ws-)
and those that do not.  WebSocket varieties are more likely to get updates closer
in sync with the rest of your display. However, older software stacks may
not support WebSockets.

AAdditionally, the templates are typically named to have 'fade' or 'nofade'.
'Nofade' generally stay on the screen for the duration of the song.  'Fade'
will appear for a while and then disappear, only to reappear when the song changes:

.. image:: gallery/images/mtvfade.webp
   :target: gallery/images/mtvfade.webp
   :alt: Fading example


Here are some pictures of the bundled HTML template files
being used with an OBS stream.

* cover-title-artist:

.. image:: gallery/images/cover-title-artist.png
   :target: gallery/images/cover-title-artist.png
   :alt: Example cover with just title and artist and solid background Image

* mtv:

.. image:: gallery/images/mtv-no-publisher.png
   :target: gallery/images/mtv-no-publisher.png
   :alt: Example MTV-style with no publisher Image

* mtv-cover:

.. image:: gallery/images/mtv-with-cover.png
   :target: gallery/images/mtv-with-cover.png
   :alt: Example MTV-style with cover Image

The software writes output in UTF-8. That covers the vast majority of characters that one may hit.  Be aware
that OBS and other software may need to have their settings, such as fonts, changed to support
non-ASCII characters!

.. image:: gallery/images/björk.png
   :target: gallery/images/björk.png
   :alt: Björk

.. image:: gallery/images/wham-maxell.png
   :target: gallery/images/wham-maxell.png
   :alt: WHAM! Ad in Japanese

.. image:: gallery/images/prince-signotimes.png
   :target: gallery/images/prince-signotimes.png
   :alt: Prince Peace Sign
