# Templates 6.0 Architecture Specification

Status: draft
Target: 6.0.0 (breaking change release)
Supersedes: the `template-sync` branch design; portions ported forward per the
"Relationship to the template-sync branch" section below.

## Problem Statement

The pre-6.0 template system mixes three owners in one flat directory
(`Documents/WhatsNowPlaying/templates/`):

* **App-owned stock** — copied there at startup by `UpgradeTemplates`
* **Charts-owned sync output** — named templates written to `synced/`
* **User-owned customizations** — hand edits, in place, indistinguishable from stale stock

Because ownership is mixed, every upgrade needs a checksum ledger
(`resources/updateshas.json`) to distinguish "stale stock copy" from "user
edit", and the `.new`-file alert dance to avoid clobbering customizations.
The charts sync mechanism added on the `template-sync` branch writes newer
templates into the same directory, which the ledger cannot recognize —
every synced file gets flagged as "customized" and produces `.new` spam on
every launch.

Additional problems:

* Stock htm templates became generated artifacts (built by wnp-templates)
  but are still treated as hand-editable files
* 30+ generated htm files, fonts, and jquery are copied into a folder that
  OneDrive/iCloud syncs, causing Windows file-locking churn
* `wnp_templates` package data (bundled htm, vendor.yaml) is not collected
  by PyInstaller, so any runtime code path reading
  `wnp_templates.BUNDLED_TEMPLATE_DIR` breaks in the frozen app

## Design Principles

1. **Ownership determines location.** App-owned stock lives in the bundle
   and never materializes in the user's Documents. Presence of a file in
   the user tree *means* user intent.
2. **The URL namespace is the API for htm content.** OBS browser sources
   point at `http://localhost:PORT/{name}.htm`. Name-based resolution keeps
   every OBS scene working regardless of filesystem layout.
3. **The filesystem is the API only for hand-edited files** (txt chat
   templates and user-created commands).
4. **The bundle is the floor; charts sync is the updater.** Every install
   works offline out of the box; sync freshens web templates in the
   background. (Templates + vendor are ~660 KB against a 320 MB
   distribution — shipping them costs nothing.)

## Directory Layout

```text
Documents/WhatsNowPlaying/templates/      <- user-owned content only
    twitch/                               <- twitchbot_*.txt overrides + user commands
    kick/                                 <- kickbot_*.txt overrides + user commands
    setlist/                              <- setlist-*.txt overrides
    web/                                  <- ws-*.htm user overrides
    synced/                               <- charts-managed named templates
    guessgame/                            <- guessgame overrides (existing pattern)
Documents/WhatsNowPlaying/templates_pre6/ <- frozen archive created by migration
```

Files keep their current names inside the function subdirectories
(`twitch/twitchbot_track.txt`, not `twitch/track.txt`) to minimize the
config-migration surface.

App-owned stock ships in the bundle at `bundledir/templates/` exactly as
today (populated at build time; see "Build Pipeline").

## Resolution Chain

All template reads resolve a *name* through, in order:

1. `templatedir/` and `templatedir/{function}/` (user overrides and
   user-created files — user files always win)
2. `templatedir/synced/` (charts-delivered: the user's named editor
   designs and base template updates newer than the bundle)
3. `bundledir/templates/` (stock)

Implementation notes:

* jinja2 `FileSystemLoader` accepts a list of search paths with
  first-match-wins semantics — the txt chain is a loader-configuration
  change, not a resolution framework
* `webserver.py` guessgame handling (prefer user dir, fall back to bundle)
  already implements this pattern; 6.0 makes it universal
* Vendor files (`/vendor/` route) are bundle-only. Fonts and JS libraries
  do not change between template updates; there is no user-override case.
* Absolute paths stored in config are still honored when the file exists,
  so templates kept entirely outside the chain keep working

## Content Classes

| Class | Examples | Stock location | Customization model |
| --- | --- | --- | --- |
| Generated web templates | `ws-*.htm` | bundle | template editor + charts sync; hand-edit via copy-to-customize |
| Chat/text templates | `twitchbot_*.txt`, `kickbot_*.txt`, `setlist-*.txt` | bundle | hand-edit via copy-to-customize |
| Command registries | `twitchbot_{cmd}.txt`, `kickbot_{cmd}.txt` | bundle + user union | file presence registers command (see below) |
| Charts named templates | `synced/*.htm` | charts server | template editor on charts |
| Infrastructure | `oauth/*.htm`, `whatsnowplaying-websocket.js`, `vendor/` | bundle | none (bundle-only) |
| Guessgame | `guessgame/*` | bundle | existing override pattern |

## Copy-to-Customize

### Model 1: config-keyed templates

Settings rows that point a config key at a template file
(`weboutput/htmltemplate`, `obsws/template`, `twitchbot/announce`,
`twitchbot/streamtitle`, `kick/announce`, setlist format, discord) gain a
"Customize..." action: copy the resolved stock file into the appropriate
user subdirectory and repoint the config key. Pickers list the union of the
chain with a stock/customized indicator.

### Model 2: filesystem-as-registry (twitch/kick commands)

Today `update_twitchbot_commands()` scans templatedir for
`twitchbot_*.txt`; each file's existence registers a chat command. This
pattern is preserved with one change: the scan becomes a **union** of
`bundledir/templates/` stock and `templatedir/twitch/`, per-name user file
wins. Users still add `!mycommand` by dropping `twitchbot_mycommand.txt`
into their twitch directory (or via a UI action). Help files
(`*_help.txt`) pair by naming convention and ride the same union.

Semantic change: deleting a stock command's file no longer removes the
command (the bundle copy resurfaces in the union). Disabling becomes a
first-class toggle in the settings UI, backed by the existing
`twitchbot-command-{name}/` permission config groups.

## Charts Sync Roles

* `sync_from_charts()` (requires API key): fetches the user's named
  templates from the charts editor, assembles them, writes to
  `templatedir/synced/`. Manifest file tracks written names for stale
  cleanup. **Unchanged from the template-sync branch.**
* `sync_base_templates()` (public endpoint): downloads base `ws-*.htm`
  files into `templatedir/synced/` — only when the server version differs
  from what the chain currently serves and the current file is not a
  user-owned override. A manifest (`.wnp_base_sync.json`) records what
  this sync wrote; entries are removed once a newer app bundle serves the
  same content. Sync never writes outside `synced/` — everything else in
  the user tree is user-owned.
* Vendor assets (fonts, JS) are bundle-only for 6.0. Syncing them at
  runtime is a possible future project (would need webserver vendor-route
  changes to serve from a synced location).

Both remain fire-and-forget background tasks started from datacache; all
errors logged and swallowed (offline-safe).

## Build Pipeline

`tools/build_templates.py` (run by builder.sh before PyInstaller):

* copies `ws-*.htm` from the installed `wnp_templates` wheel into
  `nowplaying/templates/`
* downloads vendor files from `wnp_templates.VENDOR_FILES` CDN URLs into
  `nowplaying/templates/vendor/`

The PyInstaller spec entry `('nowplaying/templates/*', 'templates/')`
copies matched directories recursively (verified against the shipped 5.2.0
zip), so no spec change is required.

Any runtime consumer of stock templates reads `bundledir/templates/`, never
`wnp_templates` package data (which PyInstaller does not collect). The
template editor endpoints on the `template-sync` branch that read
`wnp_templates.BUNDLED_TEMPLATE_DIR` must be reworked to use the bundle
path.

## Migration (6.0 first launch)

One-time pass, using `updateshas.json` as the classifier:

1. Walk the existing flat `templates/` tree; hash every file
2. Hash matches any known stock version in the ledger -> untouched stock
   copy -> do not carry forward (bundle serves it)
3. Hash matches nothing -> user's work -> move into the new structure
   (classified by filename pattern: `twitchbot_*` -> `twitch/`, etc.) and
   rewrite any config keys pointing at the old absolute path
4. `*.new` files -> delete
5. Rename the old directory to `templates_pre6` as the recovery archive
6. Files that cannot be classified by pattern go to the top level of the
   new tree (still resolvable, still archived in `templates_pre6`)

After migration, `UpgradeTemplates`, the `.new` mechanism, and
`updateshas.json` generation (`tools/updateshas.py`,
`tools/regenerate_shas.sh`, the "Update shas" release step) are retired.
The ledger file itself ships one final time in 6.0 to power the migration.

## Config Changes

* Template-path config keys store bare names resolved through the chain;
  absolute paths remain honored when the file exists (external templates)
* Defaults in `config.py` `_defaults_*()` change from
  `templatedir.joinpath(...)` absolute paths to names
* Migration rewrites existing stored paths: dangling paths to stock ->
  name; paths to carried-forward customizations -> new location

## Retired Components

* `UpgradeTemplates` (`nowplaying/upgrades/templates.py`) and the startup
  copy-everything flow
* `.new` conflict files and the "Updated templates have been placed" alert
* `updateshas.json` ledger maintenance (kept read-only for migration)
* Runtime vendor download in `sync_base_templates()`
* `nowplaying/resources/templates/` (vestigial, zero references)

## Relationship to the template-sync Branch

Implementation restarts from `main` (32 commits ahead). Ported by diff from
`template-sync`:

* `nowplaying/processes/template_sync.py` — `sync_from_charts()` intact;
  `sync_base_templates()` pruned of vendor download
* wnp-templates package switch — `template_colors.py` shim, dependency,
  `template-src/` + old builder deletion, `docs/macros.py`, CI step removal
* New `tools/build_templates.py`
* Review/cherry-pick: guessgame htm changes, `obs/exportdialog.py`,
  `preview/window.py` fixes

Prerequisite: main's 13 dynamic-background templates (commit `88ca7b5e`)
must be ported into wnp-templates (release 0.1.3) before `template-src/`
can be deleted, or they are lost.

## Open Questions

* Whether a read-only `examples/` export should exist for the text-editor
  crowd, or pickers + copy-to-customize are sufficient (current position:
  no examples directory)
* Exact UI treatment of the stock/customized indicator and disable toggle
  in twitch/kick settings
* Whether `synced/` should also participate in txt resolution (current
  position: htm only)
