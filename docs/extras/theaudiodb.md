# TheAudioDB

TheAudioDB is a community-driven database of artist information and images.

## What TheAudioDB Provides

* Artist banners
* Artist fan art (background images)
* Artist logos
* Artist thumbnails
* Artist websites and social media links
* Artist biographies
* Album cover art

## Requirements

An API key from [TheAudioDB](https://www.theaudiodb.com) is required. A free tier is available
using `123` as the API key, limited to 30 requests per minute. Higher limits are available via
a Patreon subscription.

## Setup

[![TheAudioDB Settings](images/theaudiodb.png)](images/theaudiodb.png)

> **Note**: TheAudioDB settings are under **Artist Data** in the Settings menu.

### Getting an API Key

1. Subscribe via [TheAudioDB on Patreon](https://www.patreon.com/theaudiodb)
2. Follow the instructions provided to receive your API key
3. Paste it into the **TheAudioDB API Key** field in What's Now Playing

### Content Options

Once enabled and an API key is entered, select what to download:

* **Biography** — artist background text
* **Banners** — wide horizontal artist banner images
* **Cover Art** — album artwork fetched by artist and album name. Skipped when cover art is already
  embedded in the track file. Requires the track's album tag to be set.
* **Fanart** — large background/fan art images
* **Logos** — artist logo graphics
* **Thumbnails** — artist photos and thumbnails
* **Websites** — artist URLs and social media links

Enable only what your templates actually use.

### Biography Language

When Biography is enabled, you can set a preferred **Language ISO Code** (e.g. `EN`, `DE`, `FR`).
Enable **Fallback to EN** to use the English biography when your preferred language is not available.

## How Matching Works

TheAudioDB first attempts to look up the artist by **MusicBrainz Artist ID**. If no MBID is
present in the track tags, it falls back to a text search by artist name. The MBID path
is more accurate and avoids collisions between artists who share a name.

## Troubleshooting

### No results returned

* Verify the API key is correct and your Patreon subscription is active
* Check that the artist exists on [TheAudioDB.com](https://www.theaudiodb.com) by searching manually

### Wrong artist returned

* This typically happens with the name-based fallback when multiple artists share a name
* Add MusicBrainz Artist IDs to your tracks via audio recognition (Recognition settings)
  to use the more accurate MBID lookup path

### No biography or images despite correct match

* Not all artists in TheAudioDB have complete information — this is community-contributed content
* Check the artist page on TheAudioDB.com to confirm the content exists there
