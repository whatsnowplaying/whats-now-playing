# AcoustID/MusicBrainz

The acoustidmb feature attempts to use two freely available resources to
retrieve metadata for untagged files.

[![AcoustID/MusicBrainz Settings](images/acoustidmb.png)](images/acoustidmb.png)

## AcoustID

AcoustID is a project providing a complete audio identification service
based entirely on open-source software. The service is completely free
for non-commercial applications. All you need to do is [register your
application](https://acoustid.org/new-application).

As part of the identification, AcoustID requires

- MusicBrainz enabled.
- [fpcalc binary](https://acoustid.org/chromaprint) installed

Note that AcoustID's database is not as large or as comprehensive as,
for example, Shazam. Additionally, it only samples the beginning of the
song so media with long introductions before the core of the music
starts (e.g., music videos) may not be correctly identified.

## MusicBrainz

MusicBrainz is an open music encyclopedia that collects music metadata
and makes it available to the public. **What's Now Playing** may use
MusicBrainz to fill in missing data beyond what is already tagged, if
enabled.

MusicBrainz aims to be:

> The ultimate source of music information by allowing anyone to
> contribute and releasing the data under open licenses. The universal
> lingua franca for music by providing a reliable and unambiguous form
> of music identification, enabling both people and machines to have
> meaningful conversations about music.

Like Wikipedia, MusicBrainz is maintained by a global community of users
and we want everyone — including you — to participate and contribute.

MusicBrainz is operated by the MetaBrainz Foundation, a California based
501(c)(3) tax-exempt non-profit corporation dedicated to keeping
MusicBrainz free and open source.

## MusicBrainz Instructions

1. Open Settings from the **What's Now Playing** icon
2. Select AcoustID/MusicBrainz from the left-hand column
3. Select `Query MusicBrainz for missing data`
4. Fill in the `MusicBrainz Email Address`
5. If you would like the data fetched to include artist website data,
   then select `Ask MusicBrainz for artist's websites` and which types of websites you would like included.
6. Click Save

The 'Use MusicBrainz when all else fails' button will attempt to try and
figure out extra data based primarily on the artist and title
information. Accuracy is not guaranteed, but in some use cases it may be
enough to get extra information such that [Artist Extras](../extras/index.md)
work without having to use AcoustID.

## AcoustID Instructions

1. Install [fpcacle binary](https://acoustid.org/chromaprint) as
    appropriate for your operating system.
2. Open Settings from the **What's Now Playing** icon
3. Select AcoustID/MusicBrainz from the left-hand column
4. Enable the option
5. Fill in the API Key you received from Acoustid
6. Fill in the `MusicBrainz Email Address`
7. Set the location of the fpcalc executable that was installed.
8. Any additional MusicBrainz configuration
9. Click Save

**What's Now Playing** will now use AcoustID and MusicBrainz to provide
supplementary metadata that was not provided by either the DJ software
or tags that were read from the file.
