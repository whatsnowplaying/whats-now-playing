# Discogs

Discogs is a community-built music database and marketplace covering artists, labels, and releases
across all genres, with particularly strong coverage of vinyl releases and independent or underground
artists.

## What Discogs Provides

* Artist biographies
* Artist images (fan art, thumbnails)
* Artist websites and social media links

## Requirements

Discogs matching requires **both an artist name and an album title** in your track tags.
If either field is missing, the lookup is skipped. The album title is also used to disambiguate
between artists who share the same name.

## Setup

[![Discogs Settings](images/discogs.png)](images/discogs.png)

> **Note**: Discogs settings are under **Artist Data** in the Settings menu.

### Getting a Token

A free Discogs account is all that is required.

1. Log in to [Discogs](https://www.discogs.com) (create a free account if needed)
2. Go to **Settings → Developers**
3. Click **Generate new token**
4. Copy the token and paste it into the **Discogs Token** field in What's Now Playing

[![Discogs Token Generation](images/discogs_token.png)](images/discogs_token.png)

### Content Options

Once enabled and a token is entered, select what to download:

* **Biography** — artist background text
* **Fanart** — larger artist images
* **Thumbnails** — smaller artist images
* **Websites** — artist URLs and social media links

Enable only what your templates actually use. Disabling unused types reduces lookup time
during live sets.

## Troubleshooting

### No results returned

* Confirm the track has both an **artist** and an **album** tag — both are required
* Check that the artist exists on [Discogs.com](https://www.discogs.com) by searching manually
* Verify the token is correct and has not been revoked

### Wrong artist returned

* Discogs matching is text-based — artists with common names can collide
* Adding or correcting the album title in your track tags helps disambiguate

### No biography or images despite correct match

* Not all Discogs artist pages have biographies or images — this is user-contributed content
* Check the artist page on Discogs.com to confirm the content exists there
