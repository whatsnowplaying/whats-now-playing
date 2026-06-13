#!/usr/bin/env python3
"""Web-based template editor HTTP handlers."""

import logging
import pathlib

from aiohttp import web

import nowplaying.template_colors

_DERIVED_VARS: frozenset[str] = frozenset({"wnp-accent-glow-low", "wnp-accent-glow-high"})

_VAR_GROUP: dict[str, str] = {
    "wnp-bg-color": "Global",
    "wnp-card-bg": "Global",
    "wnp-accent-color": "Global",
    "wnp-border-color": "Global",
    "wnp-shadow-color": "Global",
    "wnp-font-family": "Global",
    "wnp-text-align": "Global",
    "wnp-text-shadow": "Global",
    "wnp-cover-display": "Global",
    "wnp-line-display": "Global",
    "wnp-badge-display": "Global",
    "wnp-album-display": "Global",
    "wnp-label-display": "Global",
    "wnp-text-title": "Title",
    "wnp-bg-title": "Title",
    "wnp-font-title": "Title",
    "wnp-size-title": "Title",
    "wnp-text-artist": "Artist",
    "wnp-bg-artist": "Artist",
    "wnp-font-artist": "Artist",
    "wnp-size-artist": "Artist",
    "wnp-text-album": "Album",
    "wnp-bg-album": "Album",
    "wnp-font-album": "Album",
    "wnp-size-album": "Album",
    "wnp-text-label": "Label",
    "wnp-bg-label": "Label",
    "wnp-font-label": "Label",
    "wnp-size-label": "Label",
    "wnp-text-badge": "Badge",
    "wnp-bg-badge": "Badge",
    "wnp-size-badge": "Badge",
    "wnp-gg-bg-active": "Game",
    "wnp-gg-bg-solved": "Game",
    "wnp-gg-bg-timeout": "Game",
    "wnp-gg-bg-session": "Game",
    "wnp-gg-bg-alltime": "Game",
    "wnp-gg-text": "Game",
    "wnp-gg-label": "Game",
    "wnp-gg-timer": "Game",
    "wnp-gg-timer-low": "Game",
    "wnp-gg-session-accent": "Game",
    "wnp-gg-alltime-accent": "Game",
    "wnp-gg-font-family": "Game",
}

_VAR_LABELS: dict[str, str] = {
    "wnp-accent-color": "Accent",
    "wnp-card-bg": "Card BG",
    "wnp-bg-color": "Background",
    "wnp-text-title": "Color",
    "wnp-text-artist": "Color",
    "wnp-text-album": "Color",
    "wnp-text-label": "Color",
    "wnp-bg-title": "BG",
    "wnp-bg-artist": "BG",
    "wnp-bg-album": "BG",
    "wnp-bg-label": "BG",
    "wnp-font-title": "Font",
    "wnp-font-artist": "Font",
    "wnp-font-album": "Font",
    "wnp-font-label": "Font",
    "wnp-border-color": "Border",
    "wnp-shadow-color": "Shadow Color",
    "wnp-text-align": "Text Align",
    "wnp-text-shadow": "Text Shadow",
    "wnp-cover-display": "Cover Art",
    "wnp-line-display": "Divider Line",
    "wnp-badge-display": "Badge",
    "wnp-album-display": "Album",
    "wnp-label-display": "Label",
    "wnp-size-title": "Size",
    "wnp-size-artist": "Size",
    "wnp-size-album": "Size",
    "wnp-size-label": "Size",
    "wnp-size-badge": "Size",
    "wnp-text-badge": "Color",
    "wnp-bg-badge": "BG",
    "wnp-font-family": "Font Family",
    "wnp-gg-bg-active": "Active BG",
    "wnp-gg-bg-solved": "Solved BG",
    "wnp-gg-bg-timeout": "Timeout BG",
    "wnp-gg-bg-session": "Session Board BG",
    "wnp-gg-bg-alltime": "All-Time Board BG",
    "wnp-gg-text": "Text",
    "wnp-gg-label": "Labels",
    "wnp-gg-timer": "Timer",
    "wnp-gg-timer-low": "Timer (Low)",
    "wnp-gg-session-accent": "Session Accent",
    "wnp-gg-alltime-accent": "All-Time Accent",
    "wnp-gg-font-family": "Font Family",
}


def _var_type(name: str) -> str:
    if name.endswith("-display"):
        return "toggle"
    if name.endswith("-shadow"):
        return "shadow"
    if name == "wnp-text-align":
        return "align"
    if name.startswith("wnp-size"):
        return "size"
    if name.startswith("wnp-font") or name.endswith("-family"):
        return "font"
    return "color"


class TemplateEditorHandler:
    """Handles all /template-editor and /api/v1/editor/* routes."""

    def __init__(self, config_key: web.AppKey) -> None:
        self.config_key = config_key
        self._index_html: str | None = None

    async def index_handler(self, request: web.Request) -> web.Response:
        """Serve the editor SPA."""
        if self._index_html is None:
            config = request.app[self.config_key]
            html_path = config.getbundledir() / "webserver" / "editor_static" / "index.html"
            self._index_html = html_path.read_text(encoding="utf-8")
        return web.Response(content_type="text/html", text=self._index_html)

    @staticmethod
    async def api_templates_handler(_request: web.Request) -> web.Response:
        """Return all template families and effects that are available on disk."""
        bundled = nowplaying.template_colors.BUNDLED_TEMPLATE_DIR
        result: dict[str, dict[str, str]] = {}
        for family, effects in nowplaying.template_colors.TEMPLATE_FAMILIES.items():
            available = {
                label: stem
                for label, stem in effects.items()
                if (bundled / f"{stem}.htm").exists()
            }
            if available:
                result[family] = available
        return web.json_response(result)

    async def api_vars_handler(self, request: web.Request) -> web.Response:
        """Return CSS variables (defaults + user overrides) for a template stem."""
        stem = request.match_info.get("stem", "")
        if stem not in nowplaying.template_colors.STEM_TO_FAMILY:
            return web.Response(status=404, text="Unknown template")

        bundled = nowplaying.template_colors.BUNDLED_TEMPLATE_DIR
        template_path = bundled / f"{stem}.htm"
        defaults = nowplaying.template_colors.get_template_variables(template_path)

        config = request.app[self.config_key]
        custom_path = pathlib.Path(config.templatedir) / "custom" / f"{stem}.htm"
        user = (
            nowplaying.template_colors.get_user_colors(custom_path) if custom_path.exists() else {}
        )

        payload = {
            name: {
                "default": default_val,
                "user": user.get(name),
                "type": _var_type(name),
                "label": _VAR_LABELS.get(name, name),
                "group": _VAR_GROUP.get(name, "Global"),
            }
            for name, default_val in defaults.items()
            if name not in _DERIVED_VARS
        }
        return web.json_response(payload)

    async def api_save_handler(self, request: web.Request) -> web.Response:
        """Write user CSS variable overrides into a custom template file."""
        stem = request.match_info.get("stem", "")
        if stem not in nowplaying.template_colors.STEM_TO_FAMILY:
            return web.Response(status=404, text="Unknown template")

        try:
            body = await request.json()
            colors: dict[str, str] = body.get("vars", {})
        except Exception:  # pylint: disable=broad-exception-caught
            return web.Response(status=400, text="Invalid JSON")

        config = request.app[self.config_key]
        source_path = nowplaying.template_colors.BUNDLED_TEMPLATE_DIR / f"{stem}.htm"
        custom_dir = pathlib.Path(config.templatedir) / "custom"

        try:
            nowplaying.template_colors.save_custom_template(source_path, custom_dir, colors)
        except ValueError as err:
            return web.Response(status=400, text=str(err))
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.exception("api_save_handler failed for %s: %s", stem, err)
            return web.Response(status=500, text="Save failed")

        return web.json_response({"ok": True})

    async def api_reset_handler(self, request: web.Request) -> web.Response:
        """Delete the user's custom template file, reverting to stock defaults."""
        stem = request.match_info.get("stem", "")
        if stem not in nowplaying.template_colors.STEM_TO_FAMILY:
            return web.Response(status=404, text="Unknown template")

        config = request.app[self.config_key]
        custom_path = pathlib.Path(config.templatedir) / "custom" / f"{stem}.htm"
        try:
            if custom_path.exists():
                custom_path.unlink()
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.exception("api_reset_handler failed for %s: %s", stem, err)
            return web.Response(status=500, text="Reset failed")

        return web.json_response({"ok": True})

    async def api_timing_get_handler(self, request: web.Request) -> web.Response:
        """Return timing settings (hide_after, repeat_animation, delay_update) for a stem."""
        stem = request.match_info.get("stem", "")
        if stem not in nowplaying.template_colors.STEM_TO_FAMILY:
            return web.Response(status=404, text="Unknown template")

        config = request.app[self.config_key]
        return web.json_response(
            {
                "hide_after": config.cparser.value(
                    f"weboutput/templates/{stem}/hide_after", type=int, defaultValue=0
                ),
                "repeat_animation": config.cparser.value(
                    f"weboutput/templates/{stem}/repeat_animation", type=int, defaultValue=0
                ),
                "delay_update": config.cparser.value(
                    f"weboutput/templates/{stem}/delay_update", type=int, defaultValue=0
                ),
            }
        )

    async def api_timing_save_handler(self, request: web.Request) -> web.Response:
        """Persist timing settings for a stem to QSettings."""
        stem = request.match_info.get("stem", "")
        if stem not in nowplaying.template_colors.STEM_TO_FAMILY:
            return web.Response(status=404, text="Unknown template")

        try:
            body = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.Response(status=400, text="Invalid JSON")

        if not isinstance(body, dict):
            return web.Response(status=400, text="Invalid JSON")

        config = request.app[self.config_key]
        try:
            values = {
                key: int(body.get(key, 0))
                for key in ("hide_after", "repeat_animation", "delay_update")
            }
        except (TypeError, ValueError):
            return web.Response(status=400, text="Timing values must be integers")

        for key, val in values.items():
            config.cparser.setValue(f"weboutput/templates/{stem}/{key}", val)
        config.cparser.sync()
        return web.json_response({"ok": True})
