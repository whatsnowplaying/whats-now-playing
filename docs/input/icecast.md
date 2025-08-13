# Icecast

[Icecast](https://icecast.org/) is a popular system to stream audio over the Internet.

> NOTE: This source does not support Oldest mix mode.

Icecast is best for:

- Software without dedicated What's Now Playing support (like MIXXX)
- Generic audio streaming applications (like butt)
- Custom setups where other inputs don't work

## Instructions

[![icecast-input-source](images/icecast-source-selection.png)](images/icecast-source-selection.png)

1. Open Settings from the **What's Now Playing** icon
2. Select Core Settings->Source from the left-hand column
3. Select Icecast from the list of available input sources

[![icecast-mode-selection-none.png](images/icecast-mode-selection-none.png)](images/icecast-mode-selection-none.png)

1. Select Input Sources->Icecast from the left-hand column
2. If necessary, change the port from 8000 to another port, such
   as 5001. (Hint: port 8000 appears to be used on macOS.)
3. Click Save
4. If you changed the Icecast port, restart **What's Now Playing**

## Settings For MIXXX

> NOTE: MIXXX allows for significant screen customization. These images
> come from the 'Late Night' setting. Your display may be different.

1. Configure **What's Now Playing** as above
2. In Preferences, go to Live Broadcasting

[![icecast-mixxx-preferences.png](images/icecast-mixxx-preferences.png)](images/icecast-mixxx-preferences.png)

1. Under Server Connection:
   1. Set the address to 127.0.0.1 for the same machine, otherwise
      change to the IP address of the machine that is running **What's
      Now Playing**. (HINT: IP Address is visible on **What's Now
      Playing**'s Webserver setting page)
   2. Change the Port to match the port in **What's Now Playing**'s
      Iceast settings page.
2. Under Encoding, change the format to be 32 kbps, Ogg Vorbis, Mono.
3. Select 'OK' to exit Preferences
4. Back on the main MIXXX screen, activate Icecast broadcasting:

[![icecast-mixxx-activate.png](images/icecast-mixxx-activate.png)](images/icecast-mixxx-activate.png)

1. Click the 'On-Air' option. It may appear as above or as an antenna.
2. It should change to a solid color, usually green. On error (there is
   usually a pop-up window), double check all settings in **What's Now
   Playing** and MIXXX to make sure they match.

## Settings for butt

Under Audio, be sure that Ogg Vorbis is selected:

[![icecast-butt-audio.png](images/icecast-butt-audio.png)](images/icecast-butt-audio.png)

Under Stream, if using the 'Update song name from application', be sure
to use 'Title - Artist' mode.

[![icecast-butt-stream.png](images/icecast-butt-stream.png)](images/icecast-butt-stream.png)
