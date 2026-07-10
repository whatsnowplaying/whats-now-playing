#!/usr/bin/env python3
"""tests for the template resolution chain"""

# pylint: disable=redefined-outer-name

import pathlib
import sys
import types

import pytest

from nowplaying.utils import templatepaths


@pytest.fixture
def chaincfg(tmp_path, getroot):
    """config stub with a user tree and the repo bundle"""
    templatedir = tmp_path / "templates"
    for subdir in templatepaths.USER_LAYOUT_SUBDIRS:
        (templatedir / subdir).mkdir(parents=True)
    return types.SimpleNamespace(
        templatedir=templatedir,
        getbundledir=lambda: pathlib.Path(getroot) / "nowplaying",
    )


@pytest.mark.parametrize(
    "name",
    [
        "../../../etc/passwd",
        "/etc/passwd",
        "..",
        "foo/../../etc/passwd",
        "",
        "\\\\foo",
        "..\\..\\windows",
    ],
)
def test_resolve_template_rejects_escapes(chaincfg, name):
    """hostile names never resolve, on any platform"""
    assert templatepaths.resolve_template(chaincfg, name) is None


def test_resolve_in_root_rejects_symlink_escape(tmp_path):
    """a symlink inside the root pointing outside must not resolve"""
    if sys.platform == "win32":
        pytest.skip("symlink creation needs privileges on Windows")
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (root / "sneaky.txt").symlink_to(outside)
    assert templatepaths.resolve_in_root(root, "sneaky.txt") is None


def test_resolve_in_root_legit(getroot):
    """plain names and subpaths inside the root resolve"""
    root = pathlib.Path(getroot) / "nowplaying" / "templates"
    assert templatepaths.resolve_in_root(root, "twitchbot_track.txt")
    assert templatepaths.resolve_in_root(root, "guessgame/guessgame.htm")
    assert templatepaths.resolve_in_root(root, "does-not-exist.txt") is None


def test_chain_precedence_user_beats_synced_beats_bundle(chaincfg):
    """user file wins over synced, synced wins over bundled stock"""
    name = "twitchbot_track.txt"
    bundled = templatepaths.resolve_template(chaincfg, name)
    assert bundled and not templatepaths.is_user_template(chaincfg, bundled)

    synced_copy = chaincfg.templatedir / "synced" / name
    synced_copy.write_text("synced version")
    assert templatepaths.resolve_template(chaincfg, name) == synced_copy

    user_copy = chaincfg.templatedir / "twitch" / name
    user_copy.write_text("user version")
    assert templatepaths.resolve_template(chaincfg, name) == user_copy


def test_resolve_configured_variants(chaincfg, tmp_path):
    """bare names, live absolute paths, and dangling absolute paths"""
    assert templatepaths.resolve_configured(chaincfg, "twitchbot_track.txt")
    external = tmp_path / "external.txt"
    external.write_text("outside the chain")
    assert templatepaths.resolve_configured(chaincfg, str(external)) == external
    dangling = "/gone/away/twitchbot_track.txt"
    resolved = templatepaths.resolve_configured(chaincfg, dangling)
    assert resolved and resolved.name == "twitchbot_track.txt"
    assert templatepaths.resolve_configured(chaincfg, "") is None
    assert templatepaths.resolve_configured(chaincfg, None) is None


def test_list_templates_union_and_shadowing(chaincfg):
    """union covers stock; a user override shadows the stock path"""
    union = templatepaths.list_templates(chaincfg, "twitchbot_*.txt")
    assert "twitchbot_track.txt" in union
    override = chaincfg.templatedir / "twitch" / "twitchbot_track.txt"
    override.write_text("mine")
    union = templatepaths.list_templates(chaincfg, "twitchbot_*.txt")
    assert union["twitchbot_track.txt"] == override


def test_list_display_templates_synced_first(chaincfg):
    """synced entries lead the list and carry the synced flag"""
    (chaincfg.templatedir / "synced" / "mydesign.htm").write_text("x")
    entries = templatepaths.list_display_templates(chaincfg)
    assert entries[0] == ("mydesign.htm", chaincfg.templatedir / "synced" / "mydesign.htm", True)
    assert all(not synced for _, _, synced in entries[1:])


@pytest.mark.parametrize(
    "name,expected",
    [
        ("twitchbot_song.txt", "twitch/twitchbot_song.txt"),
        ("kickbot_song.txt", "kick/kickbot_song.txt"),
        ("setlist-fancy.txt", "setlist/setlist-fancy.txt"),
        ("myoverlay.htm", "web/myoverlay.htm"),
        ("notes.txt", "notes.txt"),
    ],
)
def test_classify_template_name(name, expected):
    """classification matches the migration layout"""
    assert templatepaths.classify_template_name(name) == pathlib.Path(expected)


def test_customize_template(chaincfg):
    """stock copies into the user tree; existing copies are never overwritten"""
    dest = templatepaths.customize_template(chaincfg, "twitchbot_track.txt")
    assert dest == chaincfg.templatedir / "twitch" / "twitchbot_track.txt"
    dest.write_text("edited by user")
    again = templatepaths.customize_template(chaincfg, "twitchbot_track.txt")
    assert again == dest
    assert dest.read_text() == "edited by user"
    assert templatepaths.customize_template(chaincfg, "no-such-template.txt") is None


def test_is_user_template(chaincfg):
    """user tree yes, synced no, bundle no"""
    user = chaincfg.templatedir / "web" / "x.htm"
    user.write_text("x")
    assert templatepaths.is_user_template(chaincfg, user)
    synced = chaincfg.templatedir / "synced" / "y.htm"
    synced.write_text("y")
    assert not templatepaths.is_user_template(chaincfg, synced)
    bundled = templatepaths.resolve_template(chaincfg, "twitchbot_track.txt")
    assert not templatepaths.is_user_template(chaincfg, bundled)
