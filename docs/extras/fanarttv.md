# FanArt.TV

FanArt.TV is a community-driven project that provides high-quality curated artwork for music and other media. It
specializes in professional-grade images including banners, logos, fan art, and thumbnails that are perfect for
streaming and visual displays.

## What FanArt.TV Provides

**Content Types:**

* High-quality artist banners
* Professional fan art and background images
* Stylized artist logos
* Artist thumbnails and photos

**Strengths:**

* Curated, high-quality artwork reviewed by the community
* Professional-grade images suitable for streaming
* Consistent image quality and resolution standards
* Wide coverage of popular artists across all genres

**Requirements:**

* Requires MusicBrainz Artist IDs in your music tags
* Works best with well-known mainstream artists
* Limited coverage for very obscure or new artists

## Setup

[![FanArt.TV Settings](images/fanarttv.png)](images/fanarttv.png)

> **Note**: FanArt.TV settings are located under Artist Data in the settings menu.

### API Access

1. Visit [FanArt.TV API Key Registration](https://fanart.tv/get-an-api-key/)
2. Create an account and request an API key
3. Copy your API key once approved
4. Paste it into the **What's Now Playing** FanArt.TV settings

### MusicBrainz Integration

FanArt.TV **requires** MusicBrainz Artist IDs to function:

1. Enable MusicBrainz in Recognition settings
2. Ensure your music files have artist/title/album tags
3. Let MusicBrainz identify artists and add MusicBrainz IDs
4. FanArt.TV uses these IDs to find matching artwork

## How FanArt.TV Works

### Lookup Process

1. **What's Now Playing** gets MusicBrainz Artist ID from track metadata
2. Queries FanArt.TV database using the MusicBrainz ID
3. Downloads available artwork for that specific artist
4. Caches images locally for fast access

### Quality Control

* All artwork is community-reviewed before acceptance
* Images meet specific quality and resolution standards
* Multiple image variations available for most artists
* Consistent styling and professional appearance

## Configuration Options

### Content Selection

* **Enable banners**: Download artist banner images

* **Enable fan art**: Download background/fan art images  

* **Enable logos**: Download artist logo graphics

* **Enable thumbnails**: Download artist photos/thumbnails

### Image Preferences

* **Image limits**: Control how many images to download per artist

* **Resolution preferences**: Available images meet FanArt.TV quality standards

* **Caching**: All images are cached locally to minimize API calls

## Best Practices

### Improve Coverage

* Use music files with complete MusicBrainz integration
* Ensure artist names match MusicBrainz database entries
* Keep music library well-tagged with artist/album/title information
* Enable AcoustID for automatic MusicBrainz ID population

### Optimize Performance

* Let MusicBrainz run first to populate Artist IDs
* FanArt.TV works best as a secondary service after MusicBrainz
* Cache settings help reduce API calls during live sets

## Troubleshooting

### No Images Found

* **Check MusicBrainz IDs**: Verify tracks have MusicBrainz Artist IDs

* **Enable MusicBrainz**: Required for FanArt.TV to work

* **Artist coverage**: Not all artists have FanArt.TV artwork

* **API key validity**: Ensure API key is active and correct

### Poor Image Quality

* FanArt.TV maintains high quality standards - poor images are rare
* If images appear low quality, they may be from other services
* Check that FanArt.TV is actually being used (not Discogs/TheAudioDB)

### Missing Artist Coverage

* FanArt.TV focuses on popular/mainstream artists
* Obscure or very new artists may not have coverage
* Consider using Discogs or TheAudioDB for broader artist coverage
* Community-driven - coverage depends on volunteer contributions

### API Issues

* **Rate limits**: FanArt.TV has API rate limiting

* **API key expired**: Check if API key needs renewal

* **Network issues**: Verify internet connectivity

* **Service downtime**: Check FanArt.TV service status

## Integration with Other Services

FanArt.TV works best alongside other Artist Extras services:

* **Use with MusicBrainz**: Required for Artist ID lookup

* **Complement Discogs**: FanArt.TV for quality, Discogs for coverage

* **Combine with TheAudioDB**: Different image types and artist coverage

* **Fallback strategy**: Configure multiple services for comprehensive coverage

## Community and Quality

* **Volunteer-driven**: Community members contribute and review artwork

* **Quality standards**: All images meet resolution and quality requirements

* **Regular updates**: New artwork added regularly by the community

* **Professional focus**: Designed for media centers and streaming applications
