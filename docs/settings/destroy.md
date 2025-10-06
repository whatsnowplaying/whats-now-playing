# Destroy Configuration

⚠️ **DANGER**: This is a destructive operation that cannot be undone.

> **Note**: Destroy Configuration is located under System in the settings menu.

## What This Does

The Destroy Configuration feature completely removes your existing **What's Now Playing** configuration and exits the
program. This is a nuclear option for when your configuration becomes hopelessly broken and you want to start
completely fresh.

## Important Notes

* **All settings will be lost**: Input sources, output configurations, API keys, templates, and all other settings

* **Documents folder remains**: Your WhatsNowPlaying directory in Documents (containing templates, logs, etc.) will
  not be deleted

* **Cannot be undone**: There is no way to recover your configuration after using this feature

* **Program exits**: The application will close after destroying the configuration

## How to Use

1. Check the "Are you sure?" checkbox
2. Click the "START OVER" button
3. The program will immediately destroy the configuration and exit

## When to Use This

* Configuration files are corrupted and causing crashes
* Settings are in an inconsistent state that cannot be fixed through normal means
* You want to completely start over with a clean slate
* Troubleshooting has failed and a fresh start is needed

## Alternatives to Consider

Before using Destroy Configuration, consider these less destructive options:

* Reset specific settings to defaults through their individual panels
* Export your current configuration before destroying it (if possible)
* Check the troubleshooting documentation for common configuration issues
* Manually edit configuration files if you know what you're doing

## After Using Destroy

After the configuration is destroyed and you restart **What's Now Playing**:

1. You'll be prompted to set up your input source again
2. All settings will be at their default values
3. You'll need to reconfigure all output destinations, API keys, and preferences
4. Your templates and other files in Documents/WhatsNowPlaying will still be available
