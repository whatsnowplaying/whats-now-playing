# General Info About Music Recognition

> NOTE: This feature is only available when using a local music source
> that provides individual files. It will not work when DJing from
> external sources.

In general, music recognition is primarily for DJs that do not have
their music fully tagged. This feature may have some significant impacts
on **What's Now Playing**'s general performance:

- Extra network bandwidth and access are required to consult with online
  databases.
- Extra CPU and RAM will be required to generate the 'fingerprint' that
  helps identify the song.
- Extra time will be required for all of this extra work, adding delays
  to the display.

Music recognition technologies will never be perfect and will
occasionally provide surprising results. Tagging your files, even with
minimal information, will give the best outcome.

## Available Recognition Services

Configure music recognition services to identify untagged tracks:

- **[AcoustID](acoustid.md)** - Audio fingerprinting service for track identification
- **[MusicBrainz](musicbrainz.md)** - Open music encyclopedia for enhanced metadata

These services can be used together or independently:

- **AcoustID only**: Identifies tracks using audio fingerprinting, returns basic metadata
- **MusicBrainz only**: Enhances existing track info with additional metadata (fallback mode)
- **Both enabled**: AcoustID identifies tracks, MusicBrainz provides enhanced metadata (recommended)

Click on the services above for detailed configuration instructions.
