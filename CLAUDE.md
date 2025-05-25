# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Testing
- `pytest` - Run all tests (both tests-qt and tests directories)
- `pytest tests/` - Run only non-Qt tests
- `pytest tests-qt/` - Run only Qt-based tests  
- `pytest tests/test_specific.py` - Run a single test file
- `pytest -k "test_name"` - Run tests matching pattern

### Code Quality
- `pylint nowplaying/` - Run linting on the main package
- `pyright` - Type checking (configured in pyproject.toml)
- `yapf --diff .` - Check code formatting
- `yapf -i .` - Apply code formatting

### Build and Distribution
- `python -m nowplaying` - Run the application from source
- `pyinstaller nowplaying.pyproject` - Build standalone executable

## Architecture Overview

This is a Python/Qt6 desktop application for streaming DJs to display "now playing" information from various DJ software.

### Core Components

**Main Application Flow:**
- `nowplaying/__main__.py` - Entry point, handles PID locking and Qt app lifecycle
- `nowplaying/bootstrap.py` - Logging setup and initial configuration
- `nowplaying/systemtray.py` - System tray interface and main UI controller
- `nowplaying/config.py` - Configuration management using Qt QSettings

**Plugin Architecture:**
- `nowplaying/plugin.py` - Base plugin class (WNPBasePlugin)
- Input plugins in `nowplaying/inputs/` - Read track data from DJ software (Serato, Traktor, etc.)
- Output processes in `nowplaying/processes/` - Send data to various destinations (OBS, Twitch, Discord)
- Artist extras in `nowplaying/artistextras/` - Fetch additional metadata (Discogs, FanartTV, etc.)
- Recognition plugins in `nowplaying/recognition/` - Audio fingerprinting for track identification

**Key Subsystems:**
- Template system for customizable output formatting
- SQLite database for metadata caching (`db.py`)
- API response caching system (`apicache.py`) with TTL support for external services
- WebSocket server for real-time data streaming
- Track request system for audience interaction
- Async Wikipedia/Wikidata client (`wikiclient.py`) optimized for live performance

### Testing Setup

The test suite uses pytest with Qt support and includes fixtures for:
- Temporary configuration directories (`bootstrap` fixture)
- Qt application lifecycle management
- Cross-platform preference cleanup (especially macOS caching)

Key testing patterns:
- Tests are split into `tests/` (non-Qt) and `tests-qt/` (Qt-dependent)
- Custom markers for specialized test configurations
- Coverage reporting configured to exclude vendor code and generated files

### Development Notes

- Qt6/PySide6 is used for the GUI framework
- Configuration uses Qt's QSettings with cross-platform support
- Plugins are dynamically loaded and follow a common interface pattern
- The application uses multiprocessing for background tasks
- Vendor dependencies are managed in `nowplaying/vendor/` to avoid conflicts

**Import Style Guidelines:**
- For non-vendored code, prefer explicit module imports over `from` imports
- Example: Use `import nowplaying.wikiclient` instead of `from nowplaying import wikiclient`
- This improves code clarity and reduces namespace pollution

### Performance Requirements

This application handles time-sensitive data retrieval and display that must be available as soon as possible to sync with live music performance. When developing:

**Critical Performance Considerations:**
- Minimize blocking operations in the main data flow paths
- Avoid network calls in time-critical polling/update cycles
- Test performance impacts of any changes that affect track detection or output delivery
- Be mindful of polling intervals and update frequencies
- Prioritize low-latency data paths from input plugins to output processes

**Real-time Components:**
- Track polling system (`processes/trackpoll.py`) for continuous DJ software monitoring
- WebSocket streaming for immediate data delivery to OBS and other outputs
- Direct file format parsing to avoid API dependencies during live performance
- Caching systems (metadata DB, image cache, API cache) to prevent repeated lookups during shows
- Optimized Wikipedia/Wikidata client with configuration-based selective fetching to minimize API calls

### External API Integration

**Wikipedia/Wikidata Client (`wikiclient.py`):**
- Async client replacing wptools with performance optimizations for live use
- Configuration-aware selective fetching (only fetches bio/images if enabled)
- Combined API requests to reduce call count by 40-60% 
- Reduced timeouts (5s) and image limits (5 max) for live performance
- Uses existing `apicache.py` system (24-hour TTL) for response caching
- Provides both async interface and sync compatibility wrapper
- SSL certificate handling for reliability across environments

**Discogs Client (`discogsclient.py`):**
- Async client replacing vendored `discogs_client` library with performance optimizations
- Full backward compatibility as drop-in replacement for `nowplaying.vendor.discogs_client`
- Configuration-aware optimization based on enabled plugin features (bio/images)
- Performance limits: 10 search results max, 5 images per artist, 3 artists loaded per search
- Automatic full artist data loading with smart filtering (primary images prioritized)
- Reduced timeouts (5s default) and API call optimization for live performance
- Proper SSL context handling and configurable timeouts
- Reduces dependency footprint by eliminating large vendored library
- Uses aiohttp for non-blocking API calls with 6-20% performance improvement

**Usage Patterns:**
- Use `get_page_for_nowplaying()` for optimized Wikipedia data fetching
- Use `get_optimized_client_for_nowplaying()` for performance-tuned Discogs access
- Both clients automatically adapt behavior based on plugin configuration settings
- Discogs client is a transparent replacement - existing plugin code unchanged
- Both clients maintain backward compatibility with existing sync interfaces
- Both leverage existing `apicache.py` system for response caching
- Performance optimizations are automatic - no manual configuration required