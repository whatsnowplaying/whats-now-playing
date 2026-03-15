# fanart.tv

fanart.tv is a community-driven database of curated, high-quality images for artists across all genres.

## What fanart.tv Provides

* Artist banners
* Artist fan art (background images)
* Artist logos (HD where available)
* Artist thumbnails

## Requirements

fanart.tv looks up artists exclusively by **MusicBrainz Artist ID**. If a track has no MusicBrainz
Artist ID, the lookup is skipped. IDs can come from:

* Tags already embedded in your music files
* Audio recognition via AcoustID or MusicBrainz recognition (configured under Recognition settings)

## Setup

[![fanart.tv Settings](images/fanarttv.png)](images/fanarttv.png)

> **Note**: fanart.tv settings are under **Artist Data** in the Settings menu.

### Getting an API Key

1. [Create a free account](https://fanart.tv/wp-login.php?action=register) on fanart.tv
2. Log in and get your personal API key at [fanart.tv/get-an-api-key](https://fanart.tv/get-an-api-key/)
3. Paste it into the **fanart.tv API Key** field in What's Now Playing

### Content Options

Once enabled and an API key is entered, select what to download:

* **Banners** — wide horizontal artist banner images
* **Fanart** — large background/fan art images
* **Logos** — artist logo graphics (HD version used when available)
* **Thumbnails** — artist photos and thumbnails

## Troubleshooting

### No images returned

* Confirm the track has a MusicBrainz Artist ID
* Check using a tag editor, or enable audio recognition under Recognition settings
* Verify the API key is correct
* Check that the artist has images on [fanart.tv](https://fanart.tv); not all artists
  have community-contributed artwork
