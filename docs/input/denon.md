# Denon DJ

> NOTE: Both Newest and Oldest mix modes are supported.

The Denon DJ input source uses the StagelinQ protocol to connect directly
to Denon DJ equipment over your local network. This provides real-time
track information and playback status from compatible Denon DJ mixers and players.

StagelinQ is Denon's proprietary network protocol that allows DJ software
and hardware to communicate track metadata, mixer state, and timing information.
**What's Now Playing** connects as a StagelinQ client to monitor your Denon DJ
equipment and automatically detect which track is currently playing based on
fader positions and playback state.

## Supported Equipment

This input source works with Denon DJ hardware that supports the StagelinQ protocol, including:

- Denon DJ Prime series mixers (Prime 2, Prime 4, Prime Go/Go+)
- Denon DJ standalone players (SC5000, SC6000)
- Potentially other StagelinQ-compatible Denon DJ equipment

## Features

- **Real-time Track Detection**: Monitors all decks simultaneously and selects
the currently audible track based on fader positions and crossfader state
- **Intelligent Fader Logic**: Considers both channel faders and crossfader
position to determine which track is actually audible to the audience
- **Deck Filtering**: Option to ignore specific decks (useful for pre-cueing or inactive decks)
- **Mix Mode Support**: Choose between "newest" (most recently started) or "oldest" (earliest started)
when multiple tracks are audible

## Instructions

1. Ensure your Denon DJ equipment and computer running **What's Now Playing** are connected to the same network
2. Open Settings from the **What's Now Playing** icon
3. Select Core Settings->Source from the left-hand column
4. Select Denon DJ from the list of available input sources
5. Select Input Sources->Denon from the left-hand column
6. Select Denon DJ from the left-hand column to configure settings
7. Adjust Discovery Timeout if needed (default 5 seconds is usually sufficient)
8. Configure deck skip options if desired
9. Click Save

## Configuration

### Discovery Timeout

The Discovery Timeout setting controls how long **What's Now Playing** waits to
discover Denon DJ devices on the network during startup. The default value
of 5 seconds works well for most network configurations. You may need to increase
this value on slower networks or if devices take longer to respond.

### Deck Skip Settings

Use the deck skip checkboxes to ignore specific decks during track detection. This is useful when:

- Using certain decks only for pre-cueing or effects
- Running backing tracks on specific decks that shouldn't be announced
- Working with a multi-deck setup where only certain decks contain music for the audience

Checked decks will be completely ignored by **What's Now Playing**, even if they are playing and audible.

## How Track Selection Works

**What's Now Playing** uses advanced logic to determine which track is "now playing" by analyzing:

1. **Play State**: Only considers decks that are actively playing
2. **Channel Fader Position**: Tracks with very low fader levels (below 10% effective volume) are filtered out
3. **Crossfader Position**: Considers how the crossfader affects the audibility of
left-side decks (1 & 3) vs right-side decks (2 & 4)
4. **Volume Priority**: When multiple tracks are audible, prioritizes the loudest track
5. **Mix Mode**: Among tracks of similar volume, selects either the newest or oldest based on your mix mode setting

This intelligent selection ensures that **What's Now Playing** accurately reflects
what your audience is actually hearing, not just what decks happen to be playing.

## Troubleshooting

### No Devices Found

If **What's Now Playing** cannot discover your Denon DJ equipment:

1. Verify both devices are on the same network
2. Check that your Denon DJ equipment has StagelinQ enabled (usually enabled by default)
3. Try increasing the Discovery Timeout setting
4. Restart **What's Now Playing** to retry device discovery
5. Check your network firewall settings

### Incorrect Track Detection

If the wrong track is being detected as "now playing":

1. Check your deck skip settings to make sure you haven't accidentally skipped the deck you want to monitor
2. Verify your fader positions as tracks with very low faders are filtered out
3. Review your crossfader position as it significantly affects which decks are considered audible
4. Try switching between "newest" and "oldest" mix modes to see which works better for your style

### Connection Drops

If the connection to your Denon DJ equipment drops frequently:

1. Use a wired network connection if possible
2. Check for network congestion or interference
3. Ensure your Denon DJ equipment has the latest firmware
4. **What's Now Playing** will automatically attempt to reconnect when connections are lost
