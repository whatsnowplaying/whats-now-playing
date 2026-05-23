# Tufup Production Key Management

How signing keys are managed for the tufup auto-update path.  Tracks
task #9.

## Design

| Role           | Key            | Signs                                                          |
| -------------- | -------------- | -------------------------------------------------------------- |
| All four roles | `wnp_prod_key` | `root.json`, `targets.json`, `snapshot.json`, `timestamp.json` |

* **One ed25519 key** signs every role, threshold 1.
* **Two copies**:
  * Hot: GH Actions secret `TUFUP_KEY` — what CI workflows read.
  * Cold: secure note in self-hosted Bitwarden — disaster recovery.
* No passphrase layer — Bitwarden vault encryption + master password
  is the at-rest protection.  GH Actions secret store is the at-rest
  protection on the CI side.
* No on-disk persistence outside of those two stores.  The private
  key only ever exists in plaintext on disk in tmpfs during a CI
  workflow run.

### Why so simple?

Solo maintainer, ~300 users.  The TUF security model's main value at
this scale is "binaries are cryptographically signed; a compromised
CDN can't push tampered code."  That works fine with one key.

The elaborate "root offline + 4 separate keys + multi-sig + encrypted
in git" stack is upgrade-able later via `tufup keys ... add` /
`replace` without re-bootstrapping.  Doing it now would be operational
overhead with no realistic threat to mitigate against.

What's given up vs. the elaborate stack:

* A stolen CI key can rotate root and push malicious updates.
  But a stolen CI key on the elaborate stack can also push malicious
  updates (just can't rotate root) — practical attack outcome is
  similar.
* No multi-sig recovery from a single lost key.

What's kept:

* All actual TUF benefits: signed metadata + signed targets, clients
  reject tampered updates, no CDN-level compromise vector.
* Recovery from total key loss: ship a new bundled `root.json` in
  the next release; users update via manual download.

## Bootstrap

One-time setup that replaces the spike key with the production key.

### 1. Edit `.tufup-repo-config`

```json
{
    "app_name": "WhatsNowPlaying_macos15_arm",
    "app_version_attr": "nowplaying.version.__VERSION__",
    "binary_diff": null,
    "encrypted_keys": [],
    "expiration_days": {
        "root": 365,
        "snapshot": 7,
        "targets": 30,
        "timestamp": 1
    },
    "key_map": {
        "root":      ["wnp_prod_key"],
        "snapshot":  ["wnp_prod_key"],
        "targets":   ["wnp_prod_key"],
        "timestamp": ["wnp_prod_key"]
    },
    "keys_dir": "/Users/aw/.wnp-tufup-prod/keystore",
    "repo_dir": "/Users/aw/.wnp-tufup-prod/repository",
    "thresholds": {"root": 1, "snapshot": 1, "targets": 1, "timestamp": 1}
}
```

The config has absolute paths and stays untracked (gitignore'd, see
"Config file management" below).

### 2. Generate the key + sign initial metadata

```bash
mkdir -p ~/.wnp-tufup-prod/{repository,keystore}

# tufup init prompts:
#   - "Found existing configuration. Modify?" -> n
#   - "Overwrite key pair?" -> y (first time)
# No passphrase prompt (encrypted_keys is empty).
tufup init
```

After this, `~/.wnp-tufup-prod/keystore/` has `wnp_prod_key` (plain
PEM) and `wnp_prod_key.pub`.  `repository/metadata/` has freshly
signed `root.json`, `targets.json`, `snapshot.json`, `timestamp.json`.

### 3. Back up the key in Bitwarden

* Create a Bitwarden secure note: `wnp_prod_key`.
* Attach the file `~/.wnp-tufup-prod/keystore/wnp_prod_key`.
* (Optional but useful) attach `wnp_prod_key.pub` too — saves a
  keyid lookup later.
* Confirm 2FA is on the Bitwarden account.
* Confirm the Bitwarden server itself is backed up off-host (ZFS
  send/recv to another pool).

### 4. Upload the key to GitHub Actions secrets

```bash
gh secret set TUFUP_KEY < ~/.wnp-tufup-prod/keystore/wnp_prod_key
```

Repeat for any GH environment that gates release / cron workflows.

### 5. Replace the bundled trust anchor

The PyInstaller bundle ships `nowplaying/resources/tufup/root.json`
(task #1).  Replace the spike copy with the production one:

```bash
cp ~/.wnp-tufup-prod/repository/metadata/root.json \
   nowplaying/resources/tufup/root.json
```

Commit + push.  Any client built from this commit onward trusts only
the production key.

### 6. Re-sign existing 5.2.0 metadata

The 5.2.0 test metadata on `gh-pages:tufup/metadata/` is currently
signed with the spike key.  Re-sign it with the production key (the
multi-channel workaround from task #14 / `feedback_tufup_multichannel`
memory applies — use the Python API, not `tufup targets add` in a
loop).  Push the re-signed metadata to gh-pages.

### 7. Decommission spike

```bash
rm -rf ~/.wnp-tufup-spike/
```

## CI signing pattern

Each release workflow (and the daily re-sign cron) restores the key
into the runner's tmpfs at the start of the job:

```yaml
- name: Restore signing key
  env:
    TUFUP_KEY: ${{ secrets.TUFUP_KEY }}
  run: |
    mkdir -p "${RUNNER_TEMP}/keystore"
    chmod 700 "${RUNNER_TEMP}/keystore"
    printf '%s' "$TUFUP_KEY" > "${RUNNER_TEMP}/keystore/wnp_prod_key"
    chmod 600 "${RUNNER_TEMP}/keystore/wnp_prod_key"
    cp tools/tufup-pubkeys/wnp_prod_key.pub "${RUNNER_TEMP}/keystore/"
```

The keystore dir is in `${RUNNER_TEMP}` (tmpfs) — gone when the
workflow ends.  Don't write keys to `${{ github.workspace }}`
(could end up in artifacts).

## Rotation

When the key may be compromised or as routine hygiene:

```bash
# Generate the replacement
tufup keys wnp_prod_key_v2 -c

# Replace in all roles (signs new root.json with both keys for the
# rotation step, then publishes)
tufup keys wnp_prod_key_v2 replace wnp_prod_key ~/.wnp-tufup-prod/keystore

# Update Bitwarden + GH Actions secret with the new key
gh secret set TUFUP_KEY < ~/.wnp-tufup-prod/keystore/wnp_prod_key_v2

# After confirming clients see the new root.json, delete the old key
rm ~/.wnp-tufup-prod/keystore/wnp_prod_key
```

After rotation, the next client release should re-bundle the new
`root.json` from `repository/metadata/root.json`.  Existing installs
walk forward through `N.root.json` automatically.

## Recovery scenarios

| Scenario                   | Recovery                                                                                                                                                       |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Lost GH Actions secret     | Restore from Bitwarden; `gh secret set TUFUP_KEY < restored_file`                                                                                              |
| Lost Bitwarden vault       | Restore from your ZFS send/recv backup of the Vaultwarden server                                                                                               |
| Lost both (GH + Bitwarden) | Generate a brand-new key, ship next client release with a new bundled `root.json`. Existing installs are stranded on the old root and must manually reinstall. |
| Suspected key compromise   | Rotate immediately (see above), audit signed metadata for tampering                                                                                            |

## Config file management

`.tufup-repo-config` has absolute local paths (`/Users/aw/...`).  Keep
it untracked.  A template version with placeholder paths could be
committed under e.g. `tools/tufup-repo-config.template.json` if useful
for handing off; defer until there's a second person who needs it.

## Open dependencies for full production cutover

* Task #1 — bundled root.json done with spike key; replace per
  step 5 above before any release ships with tufup enabled.
* Task #5 — daily re-sign cron uses `secrets.TUFUP_KEY`.
* Task #12 — CI tufup bundling uses `secrets.TUFUP_KEY` on each
  release.
* Decision: when do we actually flip from spike to production?
  Aligned with the first release that ships tufup client code
  (5.2.1 or later).  Current spike metadata on prod gh-pages can
  stay spike-signed until that flip — no client trusts it anyway.
