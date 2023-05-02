Quickstart
==========

Platform Notes
--------------

macOS
~~~~~

Due to security measures in macOS Sierra and later, unsigned apps may have limitations
placed on them.  These limitations will prevent them from operating correctly or even
opening at all. Opening the app on High Sierra and newer versions of macOS by following
the steps below. Versions before High Sierra have not been verified and are not currently
supported.

* Do not unzip the downloaded zip package directly to the folder from where you will be
  running it. Instead, unzip it in a location such as the ``Downloads`` folder
  and then move the ``NowPlaying.app`` to your destination folder (e.g.,
  "Applications"). Then run the app from the destination folder.
* If the app fails to open, try holding down the Control key and then double-clicking open.
* If after following the step above the app does not open, open Terminal and type:
  ``sudo xattr -r -d com.apple.quarantine /path/to/NowPlaying.app`` (replace with the
  correct path to the app).

Windows
~~~~~~~

* Microsoft has beefed up Windows security and you may now get prompted about an unsigned
  binary.  Click on 'More Info' and then 'Run Anyway' to launch **What's Now Playing**.

Linux
~~~~~~

Binaries are not provided because of dbus-python, so please follow the `developer guide <help/developers.html>`_
to install in a Python virtual environment.  Note that currently, this software does not run headless.

To use MPRIS2, you *must* have dbus-python installed in your Python virtual environment.

Other Platforms
~~~~~~~~~~~~~~~~
Please follow the `developer guide <help/developers.html>`_ to install and run.

Installation
------------

Here are the steps to get a basic installation working:

#. Download the appropriate binary:

   * Latest stable release:

     * :stabledownloadlink:`macos12_arm` for Apple silicon processors running Monterey or higher
     * :stabledownloadlink:`macos11_intel` for Intel x86 processors running Big Sur or higher
     * :stabledownloadlink:`windows` for Intel x86 or AMD Ryzen processors running Windows 10 or higher

   * Latest preview release (if available):

     * :rcdownloadlink:`macos12_arm` for Apple silicon processors running Monterey or higher
     * :rcdownloadlink:`macos11_intel` for Intel x86 processors running Big Sur or higher
     * :rcdownloadlink:`windows` for Intel x86 or AMD Ryzen processors running Windows 10 or higher

   * or see `All Releases <https://github.com/whatsnowplaying/whats-now-playing/releases/>`_
   * Also of interest, the current `Bug List <https://github.com/whatsnowplaying/whats-now-playing/issues?q=is%3Aissue+is%3Aopen+label%3Abug+sort%3Aupdated-desc>`_

#. Launch the application
#. The software will attempt to pre-configure itself for whatever software you have installed.  Note that in the case of Traktor, this work will including building an index for file lookup. For large Traktor installations, that may take a while.
#. It should bring up the `Settings <settings/general.html>`_ window
#. (Re-)Configure a `Source <input/index.html>`_
#. Save settings.
#. Launch your DJ Software.
#. Bring up OBS or SLOBS or your streaming software.
#. Configure a Browser Source and point it at `http://localhost:8899/`.
#. Bring up your DJ software again and play a song.
#. The Browser Source should have a very simple track information box.

At this point, you are ready to customize via `Templates <reference/templatevariables.html>`_ and enable other features!


