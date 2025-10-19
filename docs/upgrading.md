# Upgrading

## Download Latest Version

**[Download the latest version](https://whatsnowplaying.com/download)** - The download page will
automatically detect your platform and show you the correct version.

Before upgrading, be sure to check the
[changelog](https://github.com/whatsnowplaying/whats-now-playing/blob/main/CHANGELOG.md)
for any breaking changes and news.

## Upgrading to 5.0.0

### Automatic Directory Migration

When upgrading to 5.0.0, the application will automatically migrate your Documents directory:

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

* Starting with 5.0.0, the system will automatically put an importable
  copy of your config in the `WhatsNowPlaying\configbackup` folder to use for
  recovery.  After the upgrade is successful, you should delete this copy
  as necessary.

## Configuration Recovery (4.2+)

If an upgrade fails or settings are lost, you can restore from a
configuration backup:

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

## From 3.x.x

1. Just install and the software will make the necessary changes.

If you need to downgrade for any reason, you must downgrade to 3.1.2 or
higher after upgrading to a 4.x.x release.

## From 2.x.x

1. Install the last version of 3.x.x from the releases page.
2. Upon launch, most settings will get copied over to their new homes
   in the new Settings screen.
3. Many templates have been added and updated. New templates will be
   copied into the templates directory. For updated templates, there
   are two outcomes:
   * If there have been no changes to the same one in the template
     directory, the updated template file will overwrite the existing
     one.
   * If there have been changes to the one in the template directory,
     the updated one will be put in as `.new` and will likely require
     you to take action. The existing one will be left there, however.
     A pop-up on program launch will also inform you that the conflict
     has happened.

## From 1.x.x

Welcome aboard!

Unfortunately, 1.x.x wasn't built in a way to make it possible to
upgrade from one version to another. So none of your settings are
preserved. You will need to treat it as though it is a fresh install.
