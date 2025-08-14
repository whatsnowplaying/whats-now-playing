# Discogs

Discogs is a comprehensive music database and marketplace that provides artist information, album artwork, and metadata for
**What's Now Playing**. It's particularly strong for electronic music, vinyl releases, and underground/independent artists.

## What Discogs Provides

**Content Types:**

* Artist biographies and detailed information
* Album artwork and artist images (fan art, thumbnails)
* Artist websites and social media links
* Detailed discographies and release information

**Strengths:**

* Excellent coverage of electronic music, vinyl, and independent releases
* Community-driven database with detailed metadata
* High-quality album artwork, especially for vinyl releases
* Good coverage of underground and niche artists

## Setup

[![Discogs Settings](images/discogs.png)](images/discogs.png)

> **Note**: Discogs settings are located under Artist Data in the settings menu.

### API Access

1. Visit [Discogs Developer Settings](https://www.discogs.com/settings/developers)
2. Click "Generate new token"
3. Copy the personal access token
4. Paste it into the **What's Now Playing** Discogs settings

### Media Tags

For best results, your music files should have:

* **Artist name** (required)

* **Album title** (required for accurate matching)

* **Track title** (improves matching accuracy)

## How Discogs Matching Works

### Search Method

Discogs uses text-based search to find artists and releases:

1. Searches for artist name in the Discogs database
2. Attempts to match album titles when available
3. Returns artist information and images from the best match

### Matching Accuracy

* **Good matches**: Well-known artists with standard naming

* **Variable results**: Artists with common names or multiple variations

* **Best results**: When album information helps distinguish between similar artists

## Configuration Options

### Content Selection

* **Enable biographies**: Download artist background information

* **Enable images**: Download artist photos and album artwork

* **Website links**: Include artist websites and social media

### Performance Settings

* **Rate limiting**: Discogs has API rate limits - downloads are automatically throttled

* **Caching**: All responses are cached to minimize API calls

* **Timeout settings**: Configurable timeout for API requests

## Best Practices

### Improve Matching

* Use consistent artist names in your music tags
* Include album titles when possible
* Verify artist names match Discogs database entries
* Consider using MusicBrainz for better artist identification

### API Usage

* Personal access tokens have rate limits - avoid excessive requests
* Respect Discogs [Terms of Use](https://www.discogs.com/developers)
* Consider the marketplace nature - some content is user-generated

## Troubleshooting

### No Results Found

* Verify artist name spelling matches Discogs database
* Check if artist exists on Discogs.com manually
* Try simplifying artist names (remove "The", special characters)
* Ensure API token is valid and has proper permissions

### Poor Quality Results

* Artist names with common words may return incorrect matches
* Consider using album information to improve matching
* Enable MusicBrainz for better artist identification first

### Rate Limit Issues

* Discogs has daily/hourly API limits for personal tokens
* Reduce download frequency if hitting limits
* Consider upgrading Discogs API access if needed

### Missing Content Types

* Not all artists have biographies on Discogs
* Image availability varies by artist popularity
* Community-driven content means some artists have more complete information

## Privacy and Terms

* Review [Discogs Terms of Use](https://www.discogs.com/developers) before use
* Personal access tokens are tied to your Discogs account
* API usage may be subject to Discogs rate limiting and policies
* Content is sourced from the Discogs community database
