# Upgrading

## Download Latest Version

**[Download the latest version](https://whatsnowplaying.com/download)** - The download page will
automatically detect your platform and show you the correct version.

Before upgrading, be sure to check the
[changelog](https://github.com/whatsnowplaying/whats-now-playing/blob/main/CHANGELOG.md)
for any breaking changes and news.

## Upgrading from 3.x or 4.x to 5.0.0

### Automatic Directory Migration

The application will automatically migrate your Documents directory:

* **Old location**: `Documents/NowPlaying`
* **New location**: `Documents/WhatsNowPlaying`

**What happens during migration:**

* A dialog will notify you about the migration process
* All templates, custom files, and directories will be copied to the new location
* Log files (.log) and temporary files (.new) are excluded from the copy
* Configuration paths pointing to the old directory are automatically updated
* Your old `Documents/NowPlaying` directory remains as a backup
* The migration only runs once - subsequent launches will use the new directory

**After upgrading:**

* You can safely delete the old `Documents/NowPlaying` directory once you've verified everything works
* If you need to downgrade, your old directory is still available

### Configuration Backup

The system will automatically put an importable copy of your config in the
`WhatsNowPlaying/configbackup` folder for recovery. After the upgrade is successful,
you should delete this copy as necessary.

### Configuration Recovery

If an upgrade fails or settings are lost, you can restore from a configuration backup:

1. **Export before upgrading** (recommended):
   * Open Settings → General → **Export Configuration**
   * Save the JSON file to a secure location
2. **Import if needed** (only if settings are lost):
   * Open Settings → General → **Import Configuration**
   * Select your exported JSON file
   * Save and restart the application

> [!WARNING]
> Only import configurations when necessary. Normal upgrades preserve
> settings automatically. Configuration files contain sensitive data -
> store securely and delete when no longer needed.

## Upgrading from 2.x to 5.0.0

**Important**: You must upgrade to version 3.1.2 first, then upgrade to 5.0.0.

1. Install version 3.1.2 from the releases page
2. Launch the application - settings will be migrated automatically
3. Then upgrade to 5.0.0

## Upgrading from 1.x to 5.0.0

Unfortunately, 1.x.x wasn't built to support upgrades. You will need to treat this as a fresh install -
none of your settings will be preserved.
