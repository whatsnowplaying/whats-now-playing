OBS WebSocket Plug-in
=====================

**What's Now Playing** can use the
`OBS WebSocket Plug-in <https://github.com/Palakis/obs-websocket/>`_ to send results
directly to OBS Studio.

Installation
------------

#. Install and configure the OBS WebSocket Plug-in, keeping track of the port and password.
#. Configure OBS to have a Text source, keeping track of the name of the source name.
#. Open Settings from the **What's Now Playing** icon
#. Select OBS WebSocket from the list of available input sources.

.. image:: images/obsws.png
   :target: images/obsws.png
   :alt: OBS WebSocket Plug-in

#. Check Enable
#. Select which type of Text source was configured.  Generally, GDI+ is only available
   on Windows.
#. Provide the server and port of your OBS installation and the name of the Text Source.
#. Click Save

