DJUCED Support
==============

** Experimental **

DJUCED is DJ software built by Guillemot Corporation for their line of Hercules controllers.

      NOTE: This source does not support Oldest mix mode.

      NOTE: Only tested with DJUCED 6.0.1

Instructions
------------

#. Open Settings from the **What's Now Playing** icon
#. Select Input Source from the left-hand column
#. Select the DJUCED from the list of available input sources.

.. image:: images/djuced-source-selection.png
   :target: images/djuced-source-selection.png
   :alt: DJUCED Source Selection

#. Select DJUCED from the left-hand column.
#. Enter or, using the button, select the directory where the DJUCED files are located.


.. image:: images/djuced-dir.png
   :target: images/djuced-dir.png
   :alt: DJUCED Directory Selection

#. Click Save
#. In DJUCED, go into Settings -> Record. Turn on Text File Output.
#. Change the Format to be: ``%TI% | %DE% | %AR% | %AL%``

.. image:: images/djuced-textfile-output.png
   :target: images/djuced-textfile-output.png
   :alt: DJUCED Text File Output

#. The file name of the output file is expected to be the default `playing.txt` and as well as stored in the DJUCED directory.
