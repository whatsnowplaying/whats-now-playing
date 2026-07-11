#!/usr/bin/env python3
"""Template name resolution through the 6.0 search chain.

Templates are addressed by relative name (e.g. ``ws-mtv.htm`` or
``guessgame/guessgame.htm``) and resolved through an ordered chain:

1. ``templatedir/`` — the user's own files and overrides (top level)
2. user function subdirectories — ``web/``, ``twitch/``, ``kick/``,
   ``setlist/`` (organization created by the 6.0 layout migration)
3. ``templatedir/synced/`` — charts-delivered content (the user's named
   editor designs and base template updates newer than the bundle)
4. ``bundledir/templates/`` — WNP-owned stock (txt, guessgame, oauth, vendor)
5. ``wnp_templates`` bundled dir — generated ws-*.htm stock from the wheel

User files beat machine-delivered content, which beats the bundle floor.
Stock content never materializes in the user's directory; presence of a
file outside synced/ means user intent.  See docs/dev/templates-6.0-spec.md.
"""

import os
import pathlib
import shutil
from typing import TYPE_CHECKING

import wnp_templates

if TYPE_CHECKING:
    import nowplaying.config

# user-owned function subdirectories searched after the templatedir root
# (synced/ is machine-managed; guessgame/ is addressed by relative name)
_USER_SUBDIRS = ("web", "twitch", "kick", "plain")

# full 6.0 user-layout directory set; the migration creates these
USER_LAYOUT_SUBDIRS = _USER_SUBDIRS + ("synced", "guessgame")


def search_paths(config: "nowplaying.config.ConfigFile") -> list[pathlib.Path]:
    """Return the ordered template search chain."""
    templatedir = pathlib.Path(config.templatedir)
    paths = [templatedir]
    paths.extend(templatedir / subdir for subdir in _USER_SUBDIRS)
    paths.append(templatedir / "synced")
    if bundledir := config.getbundledir():
        paths.append(pathlib.Path(bundledir) / "templates")
    paths.append(wnp_templates.BUNDLED_TEMPLATE_DIR)
    return paths


def _is_safe_relative_name(name: str) -> bool:
    """Reject names that could escape a search root before any path math."""
    if not name:
        return False
    pure = pathlib.PurePath(name)
    if pure.is_absolute() or pure.drive:
        return False
    return ".." not in pure.parts


def resolve_in_root(root: pathlib.Path, name: str) -> pathlib.Path | None:
    """Safely resolve a relative template name inside a single root.

    Returns the existing file, or None.  Names that escape the root
    (``..``, absolute paths, symlink tricks) are rejected: hostile names
    are dropped before any join, the normalized candidate must stay
    prefixed by the root, and the fully resolved path (symlinks followed)
    must still live inside it.
    """
    if not _is_safe_relative_name(name):
        return None
    try:
        rootstr = str(root.resolve())
    except OSError:
        return None
    candidate = os.path.normpath(os.path.join(rootstr, name))
    if not candidate.startswith(rootstr + os.sep):
        return None
    try:
        resolved = pathlib.Path(candidate).resolve()
        resolved.relative_to(rootstr)
    except (ValueError, OSError):
        return None
    if resolved.is_file():
        return resolved
    return None


def resolve_template(config: "nowplaying.config.ConfigFile", name: str) -> pathlib.Path | None:
    """Resolve a relative template name through the chain.

    Returns the first existing file, or None.  See resolve_in_root() for
    the escape handling applied per root.
    """
    for base in search_paths(config):
        if resolved := resolve_in_root(base, name):
            return resolved
    return None


def resolve_configured(
    config: "nowplaying.config.ConfigFile", value: str | None
) -> pathlib.Path | None:
    """Resolve a template config value to an existing file.

    Values may be bare names (``ws-mtv.htm``, resolved through the chain)
    or absolute paths (honored as-is when the file exists — templates kept
    outside the chain keep working).  An absolute path whose file is gone
    falls back to name resolution, so configs written before 6.0 that
    point at deleted stock copies in templatedir transparently pick up the
    bundled stock instead.
    """
    if not value:
        return None
    path = pathlib.Path(value)
    if path.is_absolute():
        if path.is_file():
            return path
        return resolve_template(config, path.name)
    return resolve_template(config, value)


def list_templates(
    config: "nowplaying.config.ConfigFile", pattern: str = "*"
) -> dict[str, pathlib.Path]:
    """Return the union of templates matching *pattern* across the chain.

    Keyed by relative name; earlier chain entries win, so a user override
    shadows stock and callers see exactly what resolve_template() would
    serve for each name.
    """
    union: dict[str, pathlib.Path] = {}
    for base in search_paths(config):
        if not base.is_dir():
            continue
        for path in sorted(base.glob(pattern)):
            if path.is_file() and path.name not in union:
                union[path.name] = path
    return union


def list_display_templates(
    config: "nowplaying.config.ConfigFile", pattern: str = "*.htm"
) -> list[tuple[str, pathlib.Path, bool]]:
    """Ordered (name, path, is_synced) listing for template-picker UIs.

    Charts-synced entries come first (flagged True), followed by the rest
    of the chain union in name order.  Shared by the preview window and
    the OBS export dialog so their listings cannot diverge.
    """
    synced_dir = pathlib.Path(config.templatedir) / "synced"
    entries: list[tuple[str, pathlib.Path, bool]] = []
    seen: set[str] = set()
    if synced_dir.is_dir():
        for path in sorted(synced_dir.glob(pattern)):
            if path.is_file():
                entries.append((path.name, path, True))
                seen.add(path.name)
    for name, path in sorted(list_templates(config, pattern).items()):
        if name not in seen:
            entries.append((name, path, False))
    return entries


def is_user_template(config: "nowplaying.config.ConfigFile", path: pathlib.Path) -> bool:
    """True when *path* is a user-owned file in the templates directory.

    Content under synced/ is machine-delivered (charts sync) and does not
    count as user-owned.
    """
    templatedir = pathlib.Path(config.templatedir).resolve()
    try:
        relative = path.resolve().relative_to(templatedir)
    except (ValueError, OSError):
        return False
    return not relative.parts or relative.parts[0] != "synced"


# filename prefix -> user function subdirectory; shared with the 6.0
# layout migration so customized copies land where migrated files do
_PREFIX_CLASSIFY = (
    ("twitchbot_", "twitch"),
    ("kickbot_", "kick"),
)


def classify_template_name(name: str) -> pathlib.Path:
    """Return the user-tree relative path where a template named *name* belongs."""
    for prefix, subdir in _PREFIX_CLASSIFY:
        if name.startswith(prefix):
            return pathlib.Path(subdir) / name
    suffix = pathlib.PurePath(name).suffix.lower()
    if suffix in (".htm", ".html"):
        return pathlib.Path("web") / name
    if suffix == ".txt":
        # generic text templates, including setlist-*.txt
        return pathlib.Path("plain") / name
    return pathlib.Path(name)


def customize_template(config: "nowplaying.config.ConfigFile", name: str) -> pathlib.Path | None:
    """Copy the resolved stock template *name* into the user tree for editing.

    Returns the user-tree path, or None when the name does not resolve.
    An existing user copy is returned untouched (never overwritten).
    """
    source = resolve_template(config, name)
    if not source:
        return None
    dest = pathlib.Path(config.templatedir) / classify_template_name(name)
    if dest.exists():
        return dest
    if is_user_template(config, source):
        return source
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return dest
