# Wikimedia

Wikimedia provides artist biographies and images sourced from Wikipedia and Wikimedia Commons.
No API key is required.

## What Wikimedia Provides

* Artist biographies (from Wikipedia)
* Artist images (fan art, thumbnails from Wikimedia Commons)
* Artist websites

## Requirements

Wikimedia identifies artists by looking for a **Wikidata URL** in the artist's website list.
This URL can come from a `website` tag embedded in the music file, or from the **MusicBrainz**
plugin, which extracts Wikidata links from MusicBrainz artist relationship data. If no Wikidata
URL is present in the artist information, the lookup is skipped.

For best results, enable MusicBrainz alongside Wikimedia.

## Setup

[![Wikimedia Settings](images/wikimedia.png)](images/wikimedia.png)

> **Note**: Wikimedia settings are under **Artist Data** in the Settings menu.

Wikimedia is enabled by default and requires no API key or account.

### Content Options

* **Fanart** — larger images from Wikimedia Commons
* **Thumbnails** — smaller images from Wikimedia Commons
* **Websites** — artist website URLs
* **Biography** — Wikipedia article text

Enable only what your templates actually use.

### Biography Language

When Biography is enabled, set a **Language ISO Code** (e.g. `EN`, `DE`, `FR`) to request
the Wikipedia article in that language. Enable **Fallback to EN** to use the English article
when your preferred language is not available.

## Troubleshooting

### No results returned

* Confirm another Artist Extras plugin is enabled and returning website data — Wikimedia
  needs a Wikidata URL from the artist's website list to perform a lookup
* Check that the artist has a Wikipedia article

### No biography despite a match

* Not all Wikidata entries link to a Wikipedia article in your preferred language
* Enable **Fallback to EN** to broaden coverage
