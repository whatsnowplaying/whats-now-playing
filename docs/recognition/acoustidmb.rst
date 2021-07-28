Acoustid + MusicBrainz Music Recognition
========================================

The acoustidmb feature attempts to use two freely available resources to retrieve
metadata for untagged files.


AcoustID
--------

AcoustID is a project providing complete audio identification service, based entirely
on open source software.  The service is completely free for non-commercial applications,
all you need to do is `register your application <https://acoustid.org/new-application>`_.

MusicBrainz
-----------

MusicBrainz is an open music encyclopedia that collects music metadata and makes it available to the public.

MusicBrainz aims to be:

    The ultimate source of music information by allowing anyone to contribute and releasing the data under open licenses.
    The universal lingua franca for music by providing a reliable and unambiguous form of music identification, enabling both people and machines to have meaningful conversations about music.

Like Wikipedia, MusicBrainz is maintained by a global community of users and we want everyone — including you — to participate and contribute.

MusicBrainz is operated by the MetaBrainz Foundation, a California based 501(c)(3) tax-exempt non-profit corporation dedicated to keeping MusicBrainz free and open source.

Instructions
------------

#. Install `Chromaprint <https://acoustid.org/chromaprint>`_ as appropriate for your operating system.
#. Open Settings from the Now Playing icon
#. Select Acoustidmb from left-hand column
#. Enable the option
#. Fill in the API Key you received from Acoustid
#. Fill in an email address that MusicBrainz uses as an emergency contact (i.e., too many queries).
#. If needed, set the location of the fpcalc executable that was installed.
#. Click Save

Now Playing will now use Acoustid and MusicBrainz to provide supplementary metadata that was not provided by
either the DJ software or tags that were read from the file.