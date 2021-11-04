Quirks
======

Under some very specialized circumstances, it may be necessary to 'nudge' ``Now Playing``
to do something particularly special in order to get the desired impact.  The options
under quirks allow one to do just that.  In general, however, users should stick with
the defaults for optimal performance.

File System Notification Method
-------------------------------

By default, ``Now Playing`` uses operating system facilities to let it know when input
files have changed.  If ``Now Playing`` is running on a different host than the
DJ software and ``Now Playing`` has been configured to read the DJ software's directory
over a network mount (such as SMB) ``Now Playing`` may not get notified that a file
has changed.  Selecting the `poll` option will force the application to perform a manual
file system check.  The drawbacks to this method is that more CPU and disk IO is performed
as well as being on delay to get updates.  However, events will not be missed.

      NOTE: Changing this value REQUIRES a restart of the ``Now Playing`` software.


Song Path Substitution
----------------------

Similar to the prior issue, the DJ software's files may reference a file path that is
not the same as what ``Now Playing`` has access.  Setting these values will allow you
to do a 'search and replace' of any song files that are referenced.

For example:

  - Starting File Path is set to `/Volumes/Music/`
  - Replacement File Path is set to `/Macintosh HD/Music/`

The DJ software says that it read `/Volumes/Music/Blondie/Heart_of_Glass.mp3`.  ``Now Playing``
will instead interpret that the filename is actually
`/Macintosh HD/Music/Blondie/Heart_of_Glass.mp3` when reading extra tags, performing recognition, etc.

      NOTE: This quirk is not supported with MPRIS2.
