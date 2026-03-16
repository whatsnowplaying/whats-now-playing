# Last.fm

Last.fm is a music service that tracks listening habits and provides a large community-sourced
database of artist biographies and metadata.

## What Last.fm Provides

* Artist biographies
* Artist website URL
* Album cover art

## Requirements

A free API key from [Last.fm](https://www.last.fm/api) is required. Registration is free with no
rate limits imposed for typical usage.

## Setup

> **Note**: Last.fm settings are under **Artist Data** in the Settings menu.

### Getting an API Key

1. Sign in or register at <https://www.last.fm/join>
2. Visit <https://www.last.fm/api/account/create> to create an API account
3. Fill in the application name and description (any values work for personal use)
4. Copy the **API key** shown on the confirmation page
5. Paste it into the **Last.fm API Key** field in What's Now Playing

### Content Options

Once enabled and an API key is entered, select what to download:

* **Biography** — full artist biography text
* **Album Cover Art** — album artwork fetched by artist and album name. Skipped when cover art is
  already embedded in the track file. Requires the track's album tag to be set.
* **Websites** — the artist's Last.fm profile URL

Enable only what your templates actually use.

### Biography Language

When Biography is enabled, you can set a preferred **Language ISO Code** (e.g. `en`, `de`, `fr`,
`ja`, `zh`). Last.fm has broad multilingual coverage — many popular artists have biographies in
a dozen or more languages.

Enable **Fallback to EN** to use the English biography when your preferred language is not
available for a given artist.

## How Matching Works

Last.fm first attempts to look up the artist by **MusicBrainz Artist ID** when one is present
in the track tags. This is the most accurate method and avoids collisions between artists who
share a name. If no MBID is available, it falls back to a name-based search with autocorrection
enabled.

## Troubleshooting

### No biography returned

* Verify the API key is correct
* Check that the artist exists on [Last.fm](https://www.last.fm) by searching manually
* Last.fm's autocorrection may redirect the name — check what name is returned in the logs

### Wrong biography returned

* This typically happens with the name-based fallback when multiple artists share a name
* Add MusicBrainz Artist IDs to your tracks via audio recognition (Recognition settings)
  to use the more accurate MBID lookup path

### Biography in wrong language

* Verify the **Language ISO Code** is a valid two-letter ISO 639-1 code (e.g. `de` not `DE`)
* Enable **Fallback to EN** if the artist may not have a biography in your preferred language
