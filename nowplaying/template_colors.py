#!/usr/bin/env python3
"""Custom template color management for What's Now Playing.

Reads CSS custom properties (--wnp-* variables) from built templates,
lets callers compile a customized copy into the user's custom/ subdirectory,
and round-trips the saved colors back on load.

Color overrides are stored as a named <style> block inside the .htm file so
the file is self-contained and works directly in OBS without any server-side
injection.
"""

import pathlib
import re

BUNDLED_TEMPLATE_DIR: pathlib.Path = pathlib.Path(__file__).parent / "resources" / "templates"
GUESSGAME_TEMPLATE_DIR: pathlib.Path = pathlib.Path(__file__).parent / "templates" / "guessgame"

_USER_STYLE_ID = "wnp-user-colors"
_VAR_RE = re.compile(r"--(wnp-[\w-]+)\s*:\s*([^;}{]+?)\s*;")
_USER_BLOCK_RE = re.compile(
    r'<style[^>]+id=["\']' + _USER_STYLE_ID + r'["\'][^>]*>.*?</style>',
    re.DOTALL | re.IGNORECASE,
)
_CSS_KEY_RE = re.compile(r"^[\w-]+$")

# Family name → ordered dict of effect_label → template_stem
# The first entry in each family is the canonical (no-effect) variant.
TEMPLATE_FAMILIES: dict[str, dict[str, str]] = {
    "Basic Text": {
        "None": "ws-basic-text",
        "Fade": "ws-basic-text-fade",
        "Explode": "ws-basic-text-explode",
        "Spin": "ws-basic-text-spin",
        "Slide": "ws-basic-text-slide",
        "Anime Elastic": "ws-basic-text-anime-elastic",
        "Anime Bounce": "ws-basic-text-anime-bounce",
        "Anime Stagger": "ws-basic-text-anime-stagger",
    },
    "Generic DJ": {
        "None": "ws-generic-dj",
    },
    "MTV": {
        "None": "ws-mtv",
        "Fade": "ws-mtv-fade",
    },
    "WebGL": {
        "Cube": "ws-webgl-cube",
        "Hologram": "ws-webgl-hologram",
        "Particles": "ws-webgl-particles",
        "Spectrum": "ws-webgl-spectrum",
        "Vinyl": "ws-webgl-vinyl",
        "Wave": "ws-webgl-wave",
    },
}

GUESSGAME_FAMILIES: dict[str, dict[str, str]] = {
    "Guess Game": {"None": "guessgame"},
    "Guess Game Leaderboard": {"None": "guessgame-leaderboard"},
}

# Reverse map: template stem → (family_name, effect_label)
STEM_TO_FAMILY: dict[str, tuple[str, str]] = {
    stem: (family, effect)
    for family, effects in TEMPLATE_FAMILIES.items()
    for effect, stem in effects.items()
}


def get_template_variables(template_path: pathlib.Path) -> dict[str, str]:
    """Return all --wnp-* CSS variables defined in *template_path*.

    Only the first occurrence of each variable name is returned (the default
    defined in the stock template's :root block).  User overrides in the
    wnp-user-colors block are excluded so callers always get the built-in
    default, not a previously saved value.
    """
    text = template_path.read_text(encoding="utf-8")

    # Strip the user block before scanning so we only see stock defaults
    text_no_user = _USER_BLOCK_RE.sub("", text)

    # CSS cascade: last definition wins, so overwrite earlier values
    seen: dict[str, str] = {}
    for match in _VAR_RE.finditer(text_no_user):
        seen[match.group(1)] = match.group(2).strip()
    return seen


def get_user_colors(template_path: pathlib.Path) -> dict[str, str]:
    """Return the user-saved color overrides from *template_path*.

    Returns an empty dict if the template has no saved customizations.
    """
    text = template_path.read_text(encoding="utf-8")
    block_match = _USER_BLOCK_RE.search(text)
    if not block_match:
        return {}
    return {m.group(1): m.group(2).strip() for m in _VAR_RE.finditer(block_match.group())}


def _build_user_style_block(colors: dict[str, str]) -> str:
    lines = ["    :root {"]
    for name, value in colors.items():
        if not _CSS_KEY_RE.match(name):
            raise ValueError(f"Invalid CSS variable name: {name!r}")
        safe_value = value.replace("</", "")
        lines.append(f"        --{name}: {safe_value};")
    lines.append("    }")
    inner = "\n".join(lines)
    return f'<style id="{_USER_STYLE_ID}">\n{inner}\n    </style>'


def save_custom_template(
    source_path: pathlib.Path,
    custom_dir: pathlib.Path,
    colors: dict[str, str],
    name: str | None = None,
) -> pathlib.Path:
    """Write a color-customized copy of *source_path* into *custom_dir*.

    *colors* maps ``wnp-*`` variable names (without leading ``--``) to CSS
    color values, e.g. ``{"wnp-accent-color": "#ff0000"}``.

    *name* overrides the output filename stem; defaults to the source stem.

    Returns the path of the written file.
    """
    custom_dir.mkdir(parents=True, exist_ok=True)
    stem = name if name else source_path.stem
    dest = custom_dir / f"{stem}.htm"

    text = source_path.read_text(encoding="utf-8")

    # Remove any existing user block
    text = _USER_BLOCK_RE.sub("", text)

    style_block = _build_user_style_block(colors)
    text = text.replace("</head>", f"    {style_block}\n</head>", 1)

    dest.write_text(text, encoding="utf-8")
    return dest


def delete_custom_template(custom_dir: pathlib.Path, filename: str) -> None:
    """Remove a custom template file.  No-op if it does not exist."""
    target = custom_dir / filename
    if target.exists():
        target.unlink()


def list_custom_templates(custom_dir: pathlib.Path) -> list[pathlib.Path]:
    """Return sorted list of .htm files in *custom_dir*."""
    if not custom_dir.exists():
        return []
    return sorted(custom_dir.glob("*.htm"))


def custom_dir_for_config(templatedir: str) -> pathlib.Path:
    """Return the custom template directory for the given template directory path."""
    return pathlib.Path(templatedir) / "custom"
