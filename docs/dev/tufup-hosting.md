# Tufup Hosting Plan

How WNP serves TUF metadata and binaries to clients running the auto-update
path.  Forward-looking: nothing here is live yet.  Tracks task #3.

## Topology

```text
  Client (tufup.Client)
      |
      |  HTTPS GET
      v
  whatsnowplaying.com  (charts server / edge proxy)
      |
      +---  /tufup/metadata/*  --->  GitHub Pages
      |                              (gh-pages branch, /tufup/metadata/ subdir)
      |
      +---  /tufup/targets/*   --->  GitHub Releases asset URL
                                     (whatsnowplaying/whats-now-playing repo)
```

Two upstream origins, one client-facing host.  Clients only ever hit
`whatsnowplaying.com` so the proxy controls cache headers, TLS, and (if
ever needed) origin switches.

## URL layout

| Client URL                                                       | Origin                                                                                          |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `https://whatsnowplaying.com/tufup/metadata/root.json`           | `https://whatsnowplaying.github.io/whats-now-playing/tufup/metadata/root.json`                  |
| `https://whatsnowplaying.com/tufup/metadata/timestamp.json`      | (same pattern, gh-pages)                                                                        |
| `https://whatsnowplaying.com/tufup/metadata/snapshot.json`       | (same pattern, gh-pages)                                                                        |
| `https://whatsnowplaying.com/tufup/metadata/targets.json`        | (same pattern, gh-pages)                                                                        |
| `https://whatsnowplaying.com/tufup/metadata/N.root.json`         | (same pattern, gh-pages — N = root version for key rotation)                                    |
| `https://whatsnowplaying.com/tufup/targets/<target_filename>`    | `https://github.com/whatsnowplaying/whats-now-playing/releases/download/<version>/<filename>`   |

`<target_filename>` is the tufup-generated archive name, e.g.
`WhatsNowPlaying_macos15_arm-5.2.1.tar.gz`.  The proxy needs to map this
to the corresponding GH Release tag, which is the version embedded in
the filename.  See "Target URL rewrite" below.

## FastAPI routes (for the charts team)

`whatsnowplaying.com` is a FastAPI app, so the proxy lives as route
handlers.  Two routes, one for metadata (streaming proxy to GH Pages),
one for targets (302 redirect to GH Releases).  Sketch using `httpx` for
the upstream call — pick whichever async HTTP client the charts app
already pulls in.

```python
import re
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
import httpx

router = APIRouter(prefix="/tufup", tags=["tufup"])

GH_PAGES_ORIGIN = "https://whatsnowplaying.github.io/whats-now-playing/tufup/metadata"
GH_RELEASES_BASE = "https://github.com/whatsnowplaying/whats-now-playing/releases/download"

# Per-file cache TTLs.  timestamp.json must be short (clients poll for
# it to detect updates); other metadata is signed daily so an hour-ish
# is fine; root.json is immutable per-version (rotation publishes a
# new N.root.json rather than mutating existing files).
_CACHE_CONTROL = {
    "timestamp.json": "public, max-age=60, must-revalidate",
    "snapshot.json": "public, max-age=900",
    "targets.json": "public, max-age=900",
}
# root.json and N.root.json
_ROOT_CACHE_CONTROL = "public, max-age=86400, immutable"


@router.get("/metadata/{filename:path}")
async def tufup_metadata(filename: str, request: Request) -> StreamingResponse:
    """Proxy TUF metadata from GH Pages.

    Stream upstream rather than buffering — metadata files are small but
    this keeps the handler memory-flat regardless of size.
    """
    # Defense in depth: TUF filenames are well-defined.  Reject anything
    # that doesn't look like metadata so we don't accidentally proxy
    # arbitrary paths under the gh-pages tree.
    if not re.fullmatch(r"(?:\d+\.)?(?:root|timestamp|snapshot|targets)\.json", filename):
        raise HTTPException(status_code=404)

    if filename in _CACHE_CONTROL:
        cache_control = _CACHE_CONTROL[filename]
    elif filename.endswith("root.json"):
        cache_control = _ROOT_CACHE_CONTROL
    else:
        cache_control = "public, max-age=60"  # safe default

    upstream_url = f"{GH_PAGES_ORIGIN}/{filename}"
    client = httpx.AsyncClient(timeout=10.0)  # or reuse an app-scoped client
    upstream = await client.get(upstream_url)
    if upstream.status_code != 200:
        await client.aclose()
        raise HTTPException(status_code=upstream.status_code)

    async def body():
        try:
            yield upstream.content
        finally:
            await client.aclose()

    return StreamingResponse(
        body(),
        media_type="application/json",
        headers={"Cache-Control": cache_control},
    )


# Tufup target filenames: <channel>-<version>.tar.gz
# <channel> = WhatsNowPlaying_<os_or_platform>[_<extras>] (no dashes in segments)
# <version> = N.N.N optionally followed by -<prerelease tag>
_TARGET_RE = re.compile(
    r"^(?P<channel>WhatsNowPlaying_[A-Za-z0-9_]+)"
    r"-(?P<version>\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)"
    r"\.tar\.gz$"
)


@router.get("/targets/{filename}")
async def tufup_target(filename: str) -> RedirectResponse:
    """Redirect to the matching GH Releases asset.

    Filename pattern is locked by tufup's repo bundler, so we can parse
    out the release tag from the filename rather than maintaining a
    separate channel-to-tag mapping.
    """
    match = _TARGET_RE.match(filename)
    if not match:
        raise HTTPException(status_code=404)

    version = match.group("version")
    upstream = f"{GH_RELEASES_BASE}/{version}/{filename}"
    # 302 + 1-day cache: the filename-to-tag mapping is stable for the
    # lifetime of the release.
    return RedirectResponse(
        upstream,
        status_code=302,
        headers={"Cache-Control": "public, max-age=86400"},
    )
```

Notes:

* The metadata handler uses a per-request `httpx.AsyncClient` for
  simplicity; a real implementation should reuse a single app-scoped
  client (or `app.state.http_client`) to avoid the connection-pool
  setup cost on every request.
* The target handler issues a 302 rather than streaming, so the charts
  server never proxies a 200+ MB binary.  tufup follows redirects
  natively.  Switch to a streaming proxy only if you want to hide
  the GH origin.
* The `_TARGET_RE` segment regex `[A-Za-z0-9_]+` allows underscores
  inside the channel name (e.g. `WhatsNowPlaying_macos15_arm_prerelease`)
  but no dashes — which keeps the channel/version split unambiguous,
  since `-` is the channel/version separator.
* Both routes return `404` rather than `5xx` on bad input so probes and
  malformed clients don't pollute error metrics.

### Cache header summary

| File                            | Cache-Control                              |
| ------------------------------- | ------------------------------------------ |
| `timestamp.json`                | `public, max-age=60, must-revalidate`      |
| `snapshot.json`, `targets.json` | `public, max-age=900`                      |
| `root.json`, `N.root.json`      | `public, max-age=86400, immutable`         |
| `/tufup/targets/*` (302)        | `public, max-age=86400` (on the redirect)  |

If per-file headers are awkward, default everything to `max-age=60` and
revisit later.  Erring short is safe; erring long breaks update
detection.

### TLS / SNI

Both upstream origins are GitHub-managed and require SNI:

* `whatsnowplaying.github.io` — GH Pages cert
* `objects.githubusercontent.com` — GH Releases cert (where the 302
  lands after the initial redirect)

The charts app should not pin origin certs; both rotate independently
under GitHub's standard PKI.

## Publishing workflow

### Metadata --> gh-pages

Signed metadata lives in the **`tufup/metadata/`** subdir on the
**`gh-pages`** branch.  Because this is a **project Pages** site (not a
user/org site), GitHub serves it under the repo-name prefix:

```text
gh-pages branch path:  tufup/metadata/timestamp.json
URL on GH Pages:       https://whatsnowplaying.github.io/whats-now-playing/tufup/metadata/timestamp.json
                                                       ^^^^^^^^^^^^^^^^^^
                                                       project-pages prefix
                                                       (= repo name)
```

The FastAPI metadata route's `GH_PAGES_ORIGIN` constant has to include
this prefix — easy to drop when copying example configs from user-site
Pages setups.

### Coexistence with the existing docs deploy

The `docs-deploy.yaml` workflow uses `mike` for versioned docs and a
"Update root-level files" step that touches only `404.html`,
`robots.txt`, and `llms.txt`.  Neither operates on sibling top-level
directories, so `tufup/` is safe alongside them.  The redirects already
on gh-pages don't interfere either:

* `index.html` at the gh-pages root does a JS+meta-refresh redirect to
  `latest/`.  Only fires when a browser hits `/` — TUF clients fetch
  named files (`tufup/metadata/timestamp.json` etc.), so this never
  trips.
* `404.html` has client-side JS for falling back from preview-version
  URLs (`5.0.0-preview1/...`) to the matching stable docs.  The regex
  is anchored to that pattern, so `/tufup/...` 404s render as plain
  404s — no rewrite, no metadata-fetch surprises.

Verify after the first dual-deploy that a subsequent `mike deploy`
hasn't touched `tufup/` (`git diff` against the previous gh-pages tip).

A new GH Actions job runs after each release and pushes signed metadata
into `gh-pages:tufup/metadata/`.

Sketch:

```yaml
# .github/workflows/tufup-publish.yaml (not yet implemented — task #12)
on:
  release:
    types: [published]

jobs:
  publish-metadata:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@... { ref: gh-pages, fetch-depth: 0 }
      - name: Pull signed metadata from build artifact
        # The tag-build workflow (macOS/Windows/Linux) produces signed
        # metadata as an artifact.  Pull it down here.
        ...
      - name: Commit to gh-pages
        run: |
          mkdir -p tufup/metadata
          cp -r $METADATA_DIR/* tufup/metadata/
          git add tufup/metadata
          git commit -m "tufup: publish metadata for ${{ github.event.release.tag_name }}"
          git push
```

The `docs-deploy.yaml` workflow uses `mike` which only touches
versioned-doc subdirs + root-level `404.html`/`robots.txt`/`llms.txt`,
so it should not collide with `/tufup/`.  Worth verifying after the
first dual-deploy.

### Targets --> GH Releases

Already exists — the release-pipeline workflow uploads platform zips on
tag.  The only change needed: the **filename** must match the tufup
convention (`<channel>-<version>.tar.gz`) so the proxy regex catches it,
and the archive must be a tufup-generated tarball, not a raw zip.

That's tracked separately in task #12 (CI: tufup bundling step alongside
zip uploads).  Until #12 lands, this hosting setup serves nothing
because there are no tufup-format targets to serve.

### Daily re-sign (task #5)

`timestamp.json` expires after 1 day (per `.tufup-repo-config`).  A
scheduled GH Actions cron runs `tufup-repo-cli refresh` and pushes a
fresh `timestamp.json` to `gh-pages:/tufup/metadata/`.  This needs the
timestamp key available to CI — see task #9 (production key management).

## Platform-specific update safety

Once the proxy + signing chain works, three OS-level pitfalls govern
whether the actual in-place update succeeds.  Capturing them here so
they don't get re-discovered every six months.

### macOS: sign + notarize + staple BEFORE archiving

The binaries that go into a tufup tar.gz must be fully signed,
notarized, and stapled *before* `tufup targets add` runs (or before
the equivalent Python API call in `tufup_publish.py`).  Tufup itself
doesn't strip Apple signatures — they're inside the binary, they
round-trip through `.tar.gz` fine — but if the binary was unstapled
when archived, the post-update `.app` will only pass Gatekeeper via
the online ticket-lookup fallback.  That works, but only when the
user is online at first launch post-update.  Stapling before archive
means offline Gatekeeper passes too.

### macOS: never binary-patch a signed .app bundle

Tufup supports `bsdiff4` patches between versions to ship smaller
deltas.  For a signed `.app` bundle, the byte-level differential
can shift internal file layout in subtle ways that invalidate the
code signature even when the on-disk content looks identical.

**Our config disables patching** (`"binary_diff": null` in
`.tufup-repo-config`, and any helper script must pass
`skip_patch=True`).  Don't enable binary patching without first
verifying signed-bundle compatibility on a fresh macOS install.

### Windows: writable install dir + Authenticode

Authenticode signatures are embedded in the PE file and survive
`tar.gz` round-trip natively.  The two real gates are:

* **UAC.** Apps installed in `C:\Program Files` can't be overwritten
  without elevation.  Tufup writes to the running app's install dir
  (`Path(sys.executable).resolve().parent`); if that path isn't
  writable by the current process, the update fails mid-extract.
  The client gates "Install Now" on `os.access(install_dir, os.W_OK)`
  to avoid this — see `nowplaying/upgrade.py:_writable_install_dir`.
  Users in elevated-only install paths see the same UX as users on
  EOL channels: View Downloads + Remind Me Later only.

* **SmartScreen / Defender.** Freshly written executables can trigger
  AV scans or SmartScreen on first launch.  Not strictly an update
  bug, but worth knowing it's normal user-visible friction.  An EV
  code-signing cert reduces SmartScreen friction; a standard cert
  needs to build reputation per signing-key over time.

### Linux: no equivalent OS-level signature gate

No Gatekeeper / SmartScreen / Authenticode equivalent fires on
self-extracted updates.  Update-time concerns reduce to "does the
binary still work after extraction" — i.e., are the file permissions
preserved, is the shebang intact, etc.  Python's `tarfile` round-trip
preserves POSIX mode bits with PAX format (which tufup uses), so
this generally just works.

## Client-side wiring

Once the proxy is live, `nowplaying/upgrades/tufup_client.py`:

```python
TUFUP_METADATA_BASE_URL: str = "https://whatsnowplaying.com/tufup/metadata/"
TUFUP_TARGET_BASE_URL: str = "https://whatsnowplaying.com/tufup/targets/"
```

Both currently point at `updates.whatsnowplaying.example/...` placeholders.
Flip them in the same PR that turns on the publishing workflow.

## Verification checklist

Before announcing auto-update to users, verify end-to-end:

* [ ] `curl https://whatsnowplaying.com/tufup/metadata/timestamp.json` returns
      200 with reasonable `Cache-Control`.
* [ ] `curl -I https://whatsnowplaying.com/tufup/targets/<known-target>`
      returns 302 to a `github.com/.../releases/download/...` URL.
* [ ] Following that redirect downloads the expected binary.
* [ ] A WNP build pointed at the new URLs successfully:
      * fetches metadata
      * validates signatures against the bundled root.json trust anchor
      * downloads + verifies a target
      * applies it in place (covered by task #10 — Gatekeeper / Windows
        code-signing verification)
* [ ] `timestamp.json` cache TTL is short enough that a re-signed
      version is visible to clients within ~5 min of publish.

## Open dependencies

* Task #5 — Scheduled daily timestamp.json re-sign (needs hosting first,
  then cron + key access)
* Task #9 — Production key management (timestamp + snapshot keys need
  to be available to CI for re-sign; root key stays offline)
* Task #10 — In-place replacement verified under macOS Gatekeeper /
  Windows code signing
* Task #12 — CI tufup bundling step (produces the targets this hosting
  setup serves)
