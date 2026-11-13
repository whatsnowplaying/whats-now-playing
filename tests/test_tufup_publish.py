#!/usr/bin/env python3
"""tests for tools/tufup_publish.py and tools/tufup_verify_target.py"""

import collections.abc
import functools
import http.server
import importlib.util
import json
import pathlib
import shutil
import threading
import types

import pytest
import tufup.client
import tufup.common
import tufup.repo

import nowplaying.upgrades.tufup_client

CHANNEL = "WhatsNowPlaying_linux_x86_64"
TufupEnv = tuple[types.ModuleType, pathlib.Path, pathlib.Path, pathlib.Path]
TOOL = pathlib.Path(__file__).resolve().parents[1] / "tools" / "tufup_publish.py"


def _load_tool(path: pathlib.Path = TOOL) -> types.ModuleType:
    """load a tools/ script; tools/ is not a package"""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = _load_tool(TOOL.with_name("tufup_verify_target.py"))


@pytest.fixture(name="tufup_env")
def fixture_tufup_env(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> TufupEnv:
    """an initialized throwaway tufup repo, its keystore, and a bundle dir"""
    tool = _load_tool()
    repo_dir = tmp_path / "work" / "repo"
    keys_dir = tmp_path / "keys"
    roles = ("root", "snapshot", "targets", "timestamp")
    # initialize() writes into the cwd's config as well; keep it in tmp_path
    monkeypatch.chdir(tmp_path)
    tufup.repo.Repository(
        app_name="WhatsNowPlaying",
        repo_dir=repo_dir,
        keys_dir=keys_dir,
        key_map={role: [tool.KEY_NAME] for role in roles},
        expiration_days={"root": 365, "snapshot": 7, "targets": 30, "timestamp": 1},
        thresholds=dict.fromkeys(roles, 1),
    ).initialize()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "WhatsNowPlaying").write_text("stub")
    return tool, repo_dir, keys_dir, bundle


def _required_flags(repo_dir: pathlib.Path) -> dict[str, bool]:
    """map version -> required, as tufup's client reads it from targets.json"""
    targets = json.loads((repo_dir / "metadata" / "targets.json").read_text())
    flags: dict[str, bool] = {}
    for path, info in targets["signed"]["targets"].items():
        meta = tufup.common.TargetMeta(target_path=path, custom=info.get("custom"))
        flags[str(meta.version)] = bool(meta.custom_internal.get(tufup.common.KEY_REQUIRED))
    return flags


@pytest.mark.parametrize("required", [False, True])
def test_publish_sets_required(tufup_env: TufupEnv, required: bool) -> None:
    """--required marks the published targets required; default is not required"""
    tool, repo_dir, keys_dir, bundle = tufup_env
    argv = [
        "--version",
        "6.0.0",
        "--keystore",
        str(keys_dir),
        "--repo-dir",
        str(repo_dir),
        "--bundle",
        f"{CHANNEL}:{bundle}",
    ]
    if required:
        argv.append("--required")
    assert tool.main(argv) == 0
    assert _required_flags(repo_dir) == {"6.0.0": required}


def test_publish_marks_existing_release_required(tufup_env: TufupEnv) -> None:
    """--required marks one version, no flag keeps the mark, --not-required clears it"""
    tool, repo_dir, keys_dir, bundle = tufup_env
    common = ["--keystore", str(keys_dir), "--repo-dir", str(repo_dir)]
    for version in ("6.0.0", "6.1.0"):
        assert tool.main(["--version", version, *common, "--bundle", f"{CHANNEL}:{bundle}"]) == 0
    assert _required_flags(repo_dir) == {"6.0.0": False, "6.1.0": False}

    def publish_610(*flag: str) -> None:
        assert (
            tool.main(["--version", "6.1.0", *common, "--bundle", f"{CHANNEL}:{bundle}", *flag])
            == 0
        )

    publish_610("--required")
    assert _required_flags(repo_dir) == {"6.0.0": False, "6.1.0": True}
    # a re-run with neither flag, as a release event does, keeps the mark
    publish_610()
    assert _required_flags(repo_dir) == {"6.0.0": False, "6.1.0": True}
    publish_610("--not-required")
    assert _required_flags(repo_dir) == {"6.0.0": False, "6.1.0": False}


@pytest.mark.parametrize(
    "case,expected",
    [
        ("match", VERIFIER.EXIT_MATCH),
        ("tampered", VERIFIER.EXIT_MISMATCH),
        ("unknown", VERIFIER.EXIT_NO_ENTRY),
    ],
)
def test_verify_target(tufup_env: TufupEnv, case: str, expected: int) -> None:
    """tufup_verify_target.py: match, tampered bytes, and no metadata entry"""
    tool, repo_dir, keys_dir, bundle = tufup_env
    argv = ["--version", "6.0.0", "--keystore", str(keys_dir), "--repo-dir", str(repo_dir)]
    assert tool.main([*argv, "--bundle", f"{CHANNEL}:{bundle}"]) == 0
    targets_json = repo_dir / "metadata" / "targets.json"
    archive = repo_dir / "targets" / f"{CHANNEL}-6.0.0.tar.gz"
    if case == "tampered":
        archive.write_bytes(archive.read_bytes() + b"x")
    elif case == "unknown":
        archive = archive.with_name(f"{CHANNEL}-9.9.9.tar.gz")
        archive.write_bytes(b"x")

    assert VERIFIER.main([str(targets_json), str(archive)]) == expected


@pytest.fixture(name="tufup_server")
def fixture_tufup_server(tufup_env: TufupEnv) -> collections.abc.Iterator[str]:
    """serve the throwaway repo over HTTP, as gh-pages + releases do"""
    repo_dir = tufup_env[1]
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(repo_dir))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    thread.join()
    server.server_close()


# previews and finals share the channel, as the release workflow publishes them
_MIXED = ["5.2.1", "5.2.2-preview1", "5.2.2", "5.2.3-preview1"]


@pytest.mark.parametrize(
    "published,current,prerelease,expected",
    [
        # preview track: newest of either kind
        (_MIXED, "5.2.2-preview1", True, "5.2.3rc1"),
        (_MIXED, "5.2.2", True, "5.2.3rc1"),
        (_MIXED, "5.2.3-preview1", True, None),
        (["5.2.2-preview2", "5.2.2"], "5.2.2-preview2", True, "5.2.2"),
        # stable track never sees previews
        (_MIXED, "5.2.1", False, "5.2.2"),
        (_MIXED, "5.2.2-preview1", False, "5.2.2"),
        (_MIXED, "5.2.2", False, None),
        # a required final stops both tracks before anything newer
        (["5.2.3-preview1", "5.2.3!", "6.0.0-preview1", "6.0.0"], "5.1.0", True, "5.2.3"),
        (["5.2.3-preview1", "5.2.3!", "6.0.0-preview1", "6.0.0"], "5.1.0", False, "5.2.3"),
    ],
)
def test_find_update_real_client(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    tufup_env: TufupEnv,
    tufup_server: str,
    tmp_path: pathlib.Path,
    published: list[str],
    current: str,
    prerelease: bool,
    expected: str | None,
) -> None:
    """tufup's own client finds what the release workflow published, per track"""
    tool, repo_dir, keys_dir, bundle = tufup_env
    for entry in published:
        # a trailing "!" publishes that version --required
        version = entry.rstrip("!")
        argv = ["--version", version, "--keystore", str(keys_dir), "--repo-dir", str(repo_dir)]
        argv += ["--bundle", f"{CHANNEL}:{bundle}"]
        if entry.endswith("!"):
            argv.append("--required")
        assert tool.main(argv) == 0
    state = tmp_path / "state"
    (state / "metadata").mkdir(parents=True)
    (state / "targets").mkdir()
    shutil.copy(repo_dir / "metadata" / "root.json", state / "metadata" / "root.json")
    client = tufup.client.Client(
        app_name=CHANNEL,
        app_install_dir=tmp_path / "app",
        current_version=current,
        metadata_dir=state / "metadata",
        metadata_base_url=f"{tufup_server}/metadata/",
        target_dir=state / "targets",
        target_base_url=f"{tufup_server}/targets/",
    )

    found = nowplaying.upgrades.tufup_client.find_update(client, prerelease=prerelease)

    assert (str(found.version) if found else None) == expected
