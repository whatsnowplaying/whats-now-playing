
Developers
==========

       NOTE: For people familiar with Python, it is HIGHLY RECOMMENDED that you use and
       build with venv due to the restrictive requirements of the tested packages listing.
       While newer versions MAY work, there is no guarantee that PyInstaller and other
       utilities will build a proper executable.

Development Requirements
------------------------

To locally build and install **What's Now Playing**\ , you will need the following:

#. Python for your operating system (3.10 or 3.11 is required.  3.12 has issues)
#. Access to a development shell (e.g., /Applications/Utility/Terminal on OS X)
#. ``git`` installed and working

Linux Pre-work
^^^^^^^^^^^^^^

If you are on Linux, it is recommended that you install dbus-python at
the system level first to get the basic OS requirements put in
place first.  For example, for Debian-style systems:

.. code-block:: bash

   sudo apt-get install python-dbus

macOS Pre-work
^^^^^^^^^^^^^^

You will need a working, modern ICU library:

1. ``brew install icu4c``
2. ``export PKG_CONFIG_PATH=/usr/homebrew/opt/icu4c/lib/pkgconfig``

Commands
--------

.. code-block:: bash

   python -m venv (virtualenv directory)
   source (virtualenv directory)/bin/activate
   git clone https://github.com/whastnowplaying/whats-now-playing.git
   cd whats-now-playing
   git checkout [version]
   pip install ".[dev,docs,osspecials,test]

At this point, you should be able to run the software from the shell:

.. code-block:: bash

   NowPlaying

Build Executable
----------------

To build a stand-alone executable, there is a helper script to do all the work:

* macOS

.. code-block:: bash

   builder.sh macosx

* Windows


.. code-block:: bash

   builder.sh windows

* Other

.. code-block:: bash

   builder.sh

This bash script will:

1. Create a venv
2. Install the contents of the venv
3. Run PyInstaller

In the end you should have a zip file with your newly built binary.

There should now be a ``dist`` directory and inside that directory will be
either a ``NowPlaying.app`` on OS X or just a ``NowPlaying`` single file.
