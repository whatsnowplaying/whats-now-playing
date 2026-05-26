#!/usr/bin/env python3
"""Tests for nowplaying.upgrades.tufup_client.

None of these tests use qtbot — they live in tests/ (not tests-qt/).
QStandardPaths works because the root conftest.py calls set_qt_names()
which creates a QCoreApplication before any test runs.
"""

import pathlib
from unittest import mock

# pylint: disable=protected-access

import pytest

from nowplaying.upgrades import tufup_client


# ---------------------------------------------------------------------------
# _seed_trust_anchor
# ---------------------------------------------------------------------------


def test_seed_trust_anchor_copies_root_json(tmp_path):
    """Copies bundled root.json into metadata_dir on first launch."""
    bundle = tmp_path / "bundle"
    src = bundle / "resources" / "tufup"
    src.mkdir(parents=True)
    (src / "root.json").write_text('{"signed": {}}')

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    with mock.patch("nowplaying.frozen.frozen_init", return_value=str(bundle)):
        tufup_client._seed_trust_anchor(metadata_dir)

    assert (metadata_dir / "root.json").exists()
    assert (metadata_dir / "root.json").read_text() == '{"signed": {}}'


def test_seed_trust_anchor_skips_if_already_present(tmp_path):
    """Does not overwrite an existing root.json."""
    bundle = tmp_path / "bundle"
    src = bundle / "resources" / "tufup"
    src.mkdir(parents=True)
    (src / "root.json").write_text("new")

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    existing = metadata_dir / "root.json"
    existing.write_text("original")

    with mock.patch("nowplaying.frozen.frozen_init", return_value=str(bundle)):
        tufup_client._seed_trust_anchor(metadata_dir)

    assert existing.read_text() == "original"


def test_seed_trust_anchor_silent_when_source_missing(tmp_path):
    """Does not raise if the bundled root.json is absent."""
    bundle = tmp_path / "empty-bundle"
    bundle.mkdir()
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    with mock.patch("nowplaying.frozen.frozen_init", return_value=str(bundle)):
        tufup_client._seed_trust_anchor(metadata_dir)

    assert not (metadata_dir / "root.json").exists()


# ---------------------------------------------------------------------------
# _default_state_dir
# ---------------------------------------------------------------------------


def test_default_state_dir_ends_with_tufup():
    """Returns a path whose final component is 'tufup'."""
    result = tufup_client._default_state_dir()
    assert isinstance(result, pathlib.Path)
    assert result.name == "tufup"


def test_default_state_dir_fallback_on_empty_locations():
    """Falls back to ~/.local/share/WhatsNowPlaying/tufup when Qt returns nothing."""
    with mock.patch(
        "nowplaying.upgrades.tufup_client.QStandardPaths.standardLocations",
        return_value=[],
    ):
        result = tufup_client._default_state_dir()
    assert result.name == "tufup"
    assert "WhatsNowPlaying" in str(result)


# ---------------------------------------------------------------------------
# _WIN_BATCH_TEMPLATE
# ---------------------------------------------------------------------------


def test_win_batch_template_uses_wait_process():
    """Batch script uses Wait-Process (not sleep) to wait for parent exit."""
    template = tufup_client._WIN_BATCH_TEMPLATE
    assert "Wait-Process" in template
    assert "timeout /t" not in template


def test_win_batch_template_format_substitution():
    """Template .format() produces the expected key substrings."""
    result = tufup_client._WIN_BATCH_TEMPLATE.format(
        pid=1234,
        src_dir=r"C:\staging",
        dst_dir=r"C:\install",
        version="5.1.0",
        exe=r"C:\install\WhatsNowPlaying.exe",
    )
    assert "1234" in result
    assert r"C:\staging" in result
    assert r"C:\install" in result
    assert "WhatsNowPlaying-5.1.0.exe" in result
    assert r"C:\install\WhatsNowPlaying.exe" in result
    assert "robocopy" in result


# ---------------------------------------------------------------------------
# mark_prefetch_complete / has_cached_update
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["5.2.1", "5.3.0-rc1", "6.0.0"])
def test_has_cached_update_false_when_no_sentinel(tmp_path, version):
    """Returns False when no sentinel file has been written."""
    state_dir = tmp_path / "tufup"
    assert not tufup_client.has_cached_update(version, state_dir)


def test_has_cached_update_false_after_wrong_version_prefetched(tmp_path):
    """Returns False when the sentinel records a different version."""
    state_dir = tmp_path / "tufup"
    tufup_client.mark_prefetch_complete("5.2.0", state_dir)
    assert not tufup_client.has_cached_update("5.2.1", state_dir)


def test_has_cached_update_true_after_correct_version_prefetched(tmp_path):
    """Returns True when the sentinel matches the requested version."""
    state_dir = tmp_path / "tufup"
    tufup_client.mark_prefetch_complete("5.2.1", state_dir)
    assert tufup_client.has_cached_update("5.2.1", state_dir)


def test_mark_prefetch_complete_creates_sentinel_file(tmp_path):
    """Sentinel file is created in state_dir/targets/.prefetch_version."""
    state_dir = tmp_path / "tufup"
    tufup_client.mark_prefetch_complete("9.9.9", state_dir)
    sentinel = state_dir / "targets" / tufup_client._PREFETCH_SENTINEL
    assert sentinel.exists()
    assert sentinel.read_text(encoding="utf-8").strip() == "9.9.9"


def test_mark_prefetch_complete_overwrites_stale_sentinel(tmp_path):
    """A second prefetch for a new version updates the sentinel."""
    state_dir = tmp_path / "tufup"
    tufup_client.mark_prefetch_complete("5.2.0", state_dir)
    tufup_client.mark_prefetch_complete("5.2.1", state_dir)
    assert tufup_client.has_cached_update("5.2.1", state_dir)
    assert not tufup_client.has_cached_update("5.2.0", state_dir)


# ---------------------------------------------------------------------------
# check_for_update
# ---------------------------------------------------------------------------


def test_check_for_update_returns_none_on_exception(tmp_path):
    """Returns None when tufup raises (network error, bad metadata, etc.)."""
    with mock.patch(
        "nowplaying.upgrades.tufup_client.build_client",
        side_effect=Exception("network error"),
    ):
        result = tufup_client.check_for_update(tmp_path, channel="WhatsNowPlaying_test")
    assert result is None


def test_check_for_update_returns_none_when_no_update(tmp_path):
    """Returns None when the client reports no update available."""
    fake_client = mock.MagicMock()
    fake_client.check_for_updates.return_value = False
    with mock.patch(
        "nowplaying.upgrades.tufup_client.build_client",
        return_value=fake_client,
    ):
        result = tufup_client.check_for_update(tmp_path, channel="WhatsNowPlaying_test")
    assert result is None


def test_check_for_update_returns_client_when_update_available(tmp_path):
    """Returns the client when an update is found."""
    fake_client = mock.MagicMock()
    fake_client.check_for_updates.return_value = True
    with mock.patch(
        "nowplaying.upgrades.tufup_client.build_client",
        return_value=fake_client,
    ):
        result = tufup_client.check_for_update(tmp_path, channel="WhatsNowPlaying_test")
    assert result is fake_client
