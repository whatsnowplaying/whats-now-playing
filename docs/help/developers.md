# Developers

> NOTE: It is HIGHLY RECOMMENDED to use a Python virtual environment (`venv`).
> The package dependencies are tightly pinned and newer versions may not produce
> a correct executable when built with PyInstaller.

## Requirements

* Python 3.11+ for your operating system
* A terminal / development shell
* `git` installed and working

## Setup

Clone the repository and run the dev setup:

```bash
git clone https://github.com/whatsnowplaying/whats-now-playing.git
cd whats-now-playing
./builder.sh dev
```

If your system default Python is unsupported (e.g. 3.14+) or you have multiple
versions installed and need to target a specific supported one, set `PYTHONBIN`
before running the script:

```bash
PYTHONBIN=/usr/local/bin/python3.11 ./builder.sh dev
```

`builder.sh` defaults to `python3` (or `python` on Windows) found on `PATH`.
`PYTHONBIN` overrides that for both the venv creation and all subsequent build steps.

This creates a `venv/` directory in the source tree, installs all dependencies
(including dev and test extras), syncs vendored libraries, writes version info,
sets up NLTK data, compiles templates, and compiles Qt resources.

Re-running `./builder.sh dev` after pulling updates will refresh all of the above
without recreating the venv from scratch.

## Running from Source

Activate the venv and launch:

```bash
source venv/bin/activate        # Windows: venv\Scripts\activate
./wnppyi.py
```

## Running Tests

```bash
pytest
```

## Testing in a Virtual Machine

When running WNP from source inside a VM (e.g. QEMU/KVM on Windows), the
template preview window uses Qt WebEngine (Chromium), which blocklists GPU
features when it detects a software or unrecognised display driver such as
Microsoft Basic Render Driver. WebGL overlays will show a warning banner and
animations will not render.

To override the blocklist and enable software WebGL (ANGLE/WARP or SwiftShader),
set this environment variable before launching:

```bash
# Linux / macOS host shell or Windows cmd
set QTWEBENGINE_CHROMIUM_FLAGS=--ignore-gpu-blocklist   # Windows cmd
export QTWEBENGINE_CHROMIUM_FLAGS=--ignore-gpu-blocklist  # bash
```

Then launch normally (`./wnppyi.py` or the executable). The animations will
render in software — adequate for development and testing.

> NOTE: This flag is intentionally not set by default in WNP itself, because
> bypassing the blocklist on a genuinely broken driver can cause crashes.
> Set it only in development environments where you control the setup.

## Template Preview Limitations

The template preview window works for most templates using sample data, but
some templates depend on live data sources that cannot be simulated:

* **Fanart slideshow** (`ws-artistfanart-slideshow`) — works in preview;
  serves six pre-generated sample images in rotation via the images WebSocket.
* **Gifwords** (`ws-gifwords-fade`) — does not work in preview. Gifwords are
  driven by live track requests that include GIF image data; there is no
  meaningful sample to show without a real request flowing through the system.

## Build Executable

To build a stand-alone executable:

```bash
./builder.sh           # auto-detects platform (macOS or Windows)
./builder.sh macosx    # explicit macOS build
./builder.sh windows   # explicit Windows build
./builder.sh linuxbin  # Linux build via Docker (see below)
```

The script handles the full build pipeline and produces a zip file containing
the binary in the current directory.

### Linux Builds

Linux binaries are built inside a Docker container to ensure compatibility with
older glibc versions (Debian Bullseye / glibc 2.31). This produces a binary that
runs on Ubuntu 20.04 and later.

Requirements:

* Docker installed and running
* `docker buildx` support (included with Docker Desktop and Docker Engine 19.03+)

Run the build:

```bash
./builder.sh linuxbin
```

This builds the Docker image automatically, runs the full PyInstaller pipeline
inside the container, and writes a `WhatsNowPlaying-<version>-Linux-<arch>.zip`
file to the current directory. Output files are owned by the current user.
