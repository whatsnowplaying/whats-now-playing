# tufup release tooling

Repository-side scripts for managing WNP's TUF auto-update infrastructure.
The app-side client lives in `nowplaying/upgrades/tufup_client.py`.

## What is wired up

* `nowplaying/upgrades/tufup_repo_settings.py` — declarative config: key names, thresholds,
  expiration days.  All four TUF roles currently share one key (see note below).
* `tools/tufup_repo_init.py` — one-time setup.  Generates keys, writes initial
  root / targets / snapshot / timestamp metadata.  Run once when bootstrapping
  a new environment; key material goes into Bitwarden.
* `tools/tufup_repo_add_bundle.py` — per-release manual bundling.  Takes a
  PyInstaller dist directory, packages it as a TUF target, re-signs metadata.
* `tools/tufup_publish.py` — CI publish driver.  Called by
  `.github/workflows/tufup-publish.yaml` on every `release: published` event;
  handles multi-channel signing in a single invocation.
* `nowplaying/upgrades/tufup_client.py` — app-side helpers.  `check_for_update()`
  returns a Client when an update is available; `download_and_apply()` installs
  it in place.
* `nowplaying/upgrades/autoinstall.py` — QThread worker + QProgressDialog that
  drives the download and shows progress to the user.
* The `UpgradeDialog` in `nowplaying/upgrade.py` is fully wired: the charts API
  supplies the `tufup_channel` field, and the Install Now button triggers the
  full tufup flow.
* The production TUF trust anchor (`root.json`) is bundled inside the
  PyInstaller artifact under `nowplaying/resources/tufup/` and seeded into the
  writable state dir on first launch.

## Channels

There is one channel per platform (e.g. `WhatsNowPlaying_macos15_arm`), and every
release, preview or final, is published into it. tufup skips prereleases unless
asked, so clients on the preview track pass `pre="rc"` and stable clients don't.
WNP's `-previewN` tags parse as `rc`.

## Hosting

* **Metadata**: GitHub Pages branch (`gh-pages`), proxied through
  `whatsnowplaying.com/tufup/metadata/`.
* **Targets**: GitHub Releases assets, proxied through
  `whatsnowplaying.com/tufup/targets/` (302 redirect to GH Releases URL).
* **Daily re-sign**: `.github/workflows/tufup-resign.yaml` re-signs
  timestamp/snapshot metadata every 24 hours so they never expire.

## Required releases (upgrade floors)

A target marked "required" is a stepping stone. A client below it installs it
before anything newer in its channel, then picks up the newer release on its
next check. Clients already at or past it ignore the flag. Use it when a
release must run before a later one can, e.g. the last 6.x before 7.0.

* A release event publishes a new release as not required, and leaves the mark
  on one already published, so re-running it can't drop a stepping stone.
* To mark a release required, including one already published, run the
  `tufup publish on release` workflow by hand from `main` with its tag and
  `required` set to `required`; `not required` clears the mark. Tarballs already
  on the release are reused, so their hashes don't change; only the metadata
  entries are replaced.
* Use a final release as the stepping stone. A required preview would only reach
  preview-track clients.
* Every platform channel needs the required release published in it. A channel
  added later won't have it.
* The daily re-sign keeps the flag.

Tufup doesn't consult `/api/v1/check-version`, but the app labels whatever tufup
installs with the version that endpoint reported. Make sure the server offers
the required release to the same clients, so the update dialog names the
release that actually gets installed.

## Known limitations / accepted risks

* **Single key for all TUF roles**: root, targets, snapshot, and timestamp all
  use one key (`wnp_prod_key`) with threshold 1.  TUF best practice is separate
  keys per role with the root key kept offline.  This is accepted as a pragmatic
  trade-off for a single-maintainer project with ~300 users; the risk is that
  key compromise affects all roles simultaneously.  Upgrading to per-role keys
  is a future hardening task.
* **Full-archive replacement**: tufup supports binary delta patches (bsdiff4 /
  HDiff).  We use full-archive replacement.  Patches are an optimization for
  later.

## Running locally

```bash
# Install tufup tooling
pip install -r requirements-tufup.txt

# Initialize a fresh repo (generates keys + initial metadata)
python tools/tufup_repo_init.py

# Bundle a release (point at the pre-zip dist directory)
python tools/tufup_repo_add_bundle.py path/to/dist 5.2.1 macos-arm
```
