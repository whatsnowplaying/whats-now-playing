# tufup release tooling

Repository-side scripts for managing WNP's TUF auto-update infrastructure.
The app-side client lives in `nowplaying/upgrades/tufup_client.py`.

## What is wired up

* `tools/tufup_repo_settings.py` — declarative config: key names, thresholds,
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

## Hosting

* **Metadata**: GitHub Pages branch (`gh-pages`), proxied through
  `whatsnowplaying.com/tufup/metadata/`.
* **Targets**: GitHub Releases assets, proxied through
  `whatsnowplaying.com/tufup/targets/` (302 redirect to GH Releases URL).
* **Daily re-sign**: `.github/workflows/tufup-resign.yaml` re-signs
  timestamp/snapshot metadata every 24 hours so they never expire.

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
