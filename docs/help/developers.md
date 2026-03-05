# Developers

> NOTE: It is HIGHLY RECOMMENDED to use a Python virtual environment (`venv`).
> The package dependencies are tightly pinned and newer versions may not produce
> a correct executable when built with PyInstaller.

## Requirements

* Python 3.10–3.13 for your operating system (3.14+ is not yet supported)
* A terminal / development shell
* `git` installed and working

## Setup

Clone the repository and run the dev setup:

```bash
git clone https://github.com/whatsnowplaying/whats-now-playing.git
cd whats-now-playing
./builder.sh dev
```

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

See [CLAUDE.md](https://github.com/whatsnowplaying/whats-now-playing/blob/main/CLAUDE.md)
for more detail on the test suite layout and code quality tools.

## Build Executable

To build a stand-alone executable:

```bash
./builder.sh           # auto-detects platform
./builder.sh macosx    # explicit platform
./builder.sh windows
```

The script handles the full build pipeline and produces a zip file containing
the binary in the current directory.
