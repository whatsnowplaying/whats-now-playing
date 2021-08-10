.. Now Playing documentation master file, created by
   sphinx-quickstart on Sat May 29 21:24:23 2021.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to Now Playing's documentation!
=======================================

**Now Playing** is a tool written in Python to retrieve the current/last played song in Serato DJ,
Virtual DJ and other software that writes M3U files, or MPRIS2-compatible software. It allows you
to generate titles such as this one:

.. image:: gallery/images/mtv-with-cover.png
   :target: gallery/images/mtv-with-cover.png
   :alt: Example MTV-style with cover Image

Checkout the `gallery <gallery.html>`_ to see more examples!

Compiled, standalone versions are available for:

* Windows
* macOS (10.13/High Sierra to 10.15/Catalina)

For everyone else, you will need to build and install locally.  See `Developers <developers.html>`_ below.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation
   gallery
   upgrading
   usage
   settings
   input/m3u
   input/mpris2
   input/serato
   output/obswebsocket
   output/twitchbot
   output/webserver
   recognition/index
   recognition/acrcloud
   recognition/acoustidmb
   templatevariables
   developers
   comparisons

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
