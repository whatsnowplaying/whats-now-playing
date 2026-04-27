# Linux Setup

## Running the Binary

Download the zip for your architecture, extract it, and run the `WhatsNowPlaying` binary.

A desktop environment is required. This software does not run headless.

## Missing Dependencies

If the binary fails to start, install the following packages (Debian/Ubuntu):

```bash
sudo apt-get install \
  libegl1 \
  libgl1 \
  libdbus-1-3 \
  libfontconfig1 \
  libglib2.0-0 \
  libx11-xcb1 \
  libxcb-cursor0 \
  libxcb-icccm4 \
  libxcb-image0 \
  libxcb-keysyms1 \
  libxcb-randr0 \
  libxcb-render-util0 \
  libxcb-shape0 \
  libxcb-xinerama0 \
  libxcb-xkb1 \
  libxkbcommon-x11-0
```

## Building from Source

If you need to build from source, follow the [developer guide](developers.md).
