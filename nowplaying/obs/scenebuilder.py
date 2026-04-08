#!/usr/bin/env python3
"""Build and save OBS 28+ scene collection JSON for WhatsNowPlaying sources."""

import datetime
import json
import logging
import os
import pathlib
import platform
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class OBSSourceDef:
    """Definition of a single OBS browser source."""

    name: str
    path: str
    width: int
    height: int
    hint: str


DEFAULT_SOURCES: list[OBSSourceDef] = [
    OBSSourceDef("Now Playing", "/", 1500, 200, "bottom"),
    OBSSourceDef("Artist Fan Art", "/ws-artistfanart-nofade.htm", 1920, 1080, "fill"),
    OBSSourceDef("Artist Banner", "/ws-artistbanner-nofade.htm", 1500, 300, "top"),
    OBSSourceDef("Artist Thumbnail", "/ws-artistthumb-nofade.htm", 200, 200, "center"),
    OBSSourceDef("Artist Logo", "/ws-artistlogo-nofade.htm", 480, 200, "right"),
]

GUESSGAME_SOURCES: list[OBSSourceDef] = [
    OBSSourceDef("Guess Game", "/guessgame/guessgame.htm", 800, 500, "center"),
    OBSSourceDef(
        "Session Leaderboard",
        "/guessgame/guessgame-leaderboard.htm?type=session",
        550,
        700,
        "left",
    ),
    OBSSourceDef(
        "All-Time Leaderboard",
        "/guessgame/guessgame-leaderboard.htm?type=all_time",
        550,
        700,
        "right",
    ),
]

_CANVAS_W = 1920.0
_CANVAS_H = 1080.0

_CSS = "body { background-color: rgba(0, 0, 0, 0); margin: 0px auto; overflow: hidden; }"


def _calculate_placement(
    source: OBSSourceDef,
    canvas_w: float = _CANVAS_W,
    canvas_h: float = _CANVAS_H,
) -> tuple[float, float, float, float]:
    """Return (x, y, scale_x, scale_y) for the given source hint.

    All hints scale relative to the canvas dimensions.
    """
    hint = source.hint
    if hint == "fill":
        return 0.0, 0.0, canvas_w / source.width, canvas_h / source.height
    if hint == "top":
        return 0.0, 0.0, 1.0, 1.0
    if hint == "bottom":
        return 0.0, canvas_h - source.height, 1.0, 1.0
    if hint == "left":
        return 0.0, (canvas_h - source.height) / 2.0, 1.0, 1.0
    if hint == "right":
        return canvas_w - source.width, (canvas_h - source.height) / 2.0, 1.0, 1.0
    # center
    pos_x = (canvas_w - source.width) / 2.0
    pos_y = (canvas_h - source.height) / 2.0
    return pos_x, pos_y, 1.0, 1.0


def get_obs_scenes_dir() -> pathlib.Path | None:
    """Return the OBS scenes directory for the current platform, or None if absent."""
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return None
        candidate = pathlib.Path(appdata) / "obs-studio" / "basic" / "scenes"
    elif system == "Darwin":
        candidate = (
            pathlib.Path.home()
            / "Library"
            / "Application Support"
            / "obs-studio"
            / "basic"
            / "scenes"
        )
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME", "")
        config_base = pathlib.Path(xdg_config) if xdg_config else pathlib.Path.home() / ".config"
        candidate = config_base / "obs-studio" / "basic" / "scenes"

    if candidate.is_dir():
        return candidate
    return None


def _make_browser_source(source: OBSSourceDef, port: int) -> dict:
    """Return the OBS JSON dict for one browser_source."""
    url = f"http://localhost:{port}{source.path}"
    return {
        "balance": 0.5,
        "deinterlace_field_order": 0,
        "deinterlace_mode": 0,
        "enabled": True,
        "flags": 0,
        "hotkeys": {
            "libobs.mute": [],
            "libobs.unmute": [],
            "libobs.push-to-mute": [],
            "libobs.push-to-talk": [],
            "ObsBrowser.Refresh": [],
        },
        "id": "browser_source",
        "mixers": 255,
        "monitoring_type": 0,
        "muted": False,
        "name": f"WNP {source.name}",
        "private_settings": {},
        "push-to-mute": False,
        "push-to-mute-delay": 0,
        "push-to-talk": False,
        "push-to-talk-delay": 0,
        "settings": {
            "css": _CSS,
            "height": source.height,
            "url": url,
            "width": source.width,
        },
        "sync": 0,
        "versioned_id": "browser_source",
        "volume": 1.0,
    }


def _make_scene_item(source: OBSSourceDef, item_id: int) -> dict:
    """Return one scene items entry for the scene source settings."""
    pos_x, pos_y, scale_x, scale_y = _calculate_placement(source)
    return {
        "align": 5,
        "blend_method": "default",
        "blend_type": "normal",
        "bounds": {"x": 0.0, "y": 0.0},
        "bounds_align": 0,
        "bounds_crop": False,
        "bounds_type": 0,
        "crop_bottom": 0,
        "crop_left": 0,
        "crop_right": 0,
        "crop_top": 0,
        "group_item_backup": False,
        "id": item_id,
        "locked": False,
        "name": f"WNP {source.name}",
        "pos": {"x": pos_x, "y": pos_y},
        "private_settings": {},
        "rot": 0.0,
        "scale": {"x": scale_x, "y": scale_y},
        "scale_filter": "disable",
        "scale_ref": {"x": _CANVAS_W, "y": _CANVAS_H},
        "show_transition": {"duration": 0},
        "hide_transition": {"duration": 0},
        "visible": True,
    }


def _make_scene_source(sources: list[OBSSourceDef], scene_name: str) -> dict:
    """Return the scene source dict that references all browser sources."""
    # fill sources first (rendered behind), others after
    ordered = sorted(sources, key=lambda s: 0 if s.hint == "fill" else 1)
    items = [_make_scene_item(s, idx + 1) for idx, s in enumerate(ordered)]
    return {
        "balance": 0.5,
        "deinterlace_field_order": 0,
        "deinterlace_mode": 0,
        "enabled": True,
        "flags": 0,
        "hotkeys": {},
        "id": "scene",
        "mixers": 0,
        "monitoring_type": 0,
        "muted": False,
        "name": scene_name,
        "private_settings": {},
        "push-to-mute": False,
        "push-to-mute-delay": 0,
        "push-to-talk": False,
        "push-to-talk-delay": 0,
        "settings": {
            "custom_size": False,
            "id_counter": len(sources),
            "items": items,
        },
        "sync": 0,
        "versioned_id": "scene",
        "volume": 1.0,
    }


def build_and_save(sources: list[OBSSourceDef], port: int) -> pathlib.Path:
    """Build the OBS 28+ scene collection JSON and save it.

    Tries the native OBS scenes directory first; falls back to
    ~/Documents/WhatsNowPlaying/obs_scenes.

    Returns the path of the saved file.
    """
    now = datetime.datetime.now()
    filename = now.strftime("WNP-%Y-%m-%d-%H%M%S.json")
    date_label = now.strftime("%Y-%m-%d")

    obs_dir = get_obs_scenes_dir()
    if obs_dir is not None:
        save_dir = obs_dir
        logger.info("saving OBS scene collection to OBS directory: %s", save_dir)
    else:
        save_dir = pathlib.Path.home() / "Documents" / "WhatsNowPlaying" / "obs_scenes"
        save_dir.mkdir(parents=True, exist_ok=True)
        logger.info("OBS scenes dir not found; saving to: %s", save_dir)

    browser_sources = [_make_browser_source(s, port) for s in sources]
    gg_browser_sources = [_make_browser_source(s, port) for s in GUESSGAME_SOURCES]
    scene_source = _make_scene_source(sources, "WNP Sources")
    gg_scene_source = _make_scene_source(GUESSGAME_SOURCES, "WNP Guess Game")

    collection = {
        "current_program_scene": "WNP Sources",
        "current_scene": "WNP Sources",
        "current_transition": "Fade",
        "groups": [],
        "modules": {},
        "name": f"WhatsNowPlaying {date_label}",
        "preview_locked": False,
        "quick_transitions": [],
        "saved_projectors": [],
        "scaling_enabled": False,
        "scene_order": [{"name": "WNP Sources"}, {"name": "WNP Guess Game"}],
        "sources": browser_sources + gg_browser_sources + [scene_source, gg_scene_source],
        "transition_duration": 300,
        "transitions": [],
    }

    save_path = save_dir / filename
    with open(save_path, "w", encoding="utf-8") as outfile:
        json.dump(collection, outfile, indent=4)

    logger.info("OBS scene collection saved: %s", save_path)
    return save_path
