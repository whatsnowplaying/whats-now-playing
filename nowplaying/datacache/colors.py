"""Extract color palettes from cover art for display and lighting use."""

import asyncio
import colorsys
import io
import logging
from collections import Counter

from PIL import Image

SAT_MIN = 0.20
VAL_MIN = 0.18
SV_MIN = 0.10
HUE_SEP = 20 / 360

# data_types where color extraction is meaningful
COLOR_EXTRACT_TYPES = frozenset({"front_cover", "artistthumbnail", "artistfanart", "artistbanner"})


def _load_rgb(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
    bg.paste(img, mask=img.split()[3])
    img = bg.convert("RGB")
    img.thumbnail((200, 200), Image.Resampling.LANCZOS)
    return img


def _quantize_candidates(img: Image.Image) -> list[tuple]:
    """Return (count, h, s, v, r, g, b) tuples sorted by count descending."""
    quantized = img.quantize(colors=24, method=Image.Quantize.MEDIANCUT)
    palette_flat = quantized.getpalette()[:72]
    counts = Counter(quantized.get_flattened_data())
    candidates = []
    for idx, count in counts.items():
        r, g, b = palette_flat[idx * 3], palette_flat[idx * 3 + 1], palette_flat[idx * 3 + 2]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        candidates.append((count, h, s, v, r, g, b))
    candidates.sort(reverse=True)
    return candidates


def _hue_diverse(candidates: list[tuple], max_colors: int) -> list[tuple]:
    """Walk candidates by frequency, enforce minimum hue separation."""
    selected = []
    for item in candidates:
        _, h, *_ = item
        min_dist = min(
            (min(abs(h - sh), 1 - abs(h - sh)) for _, sh, *_ in selected),
            default=1.0,
        )
        if min_dist > HUE_SEP:
            selected.append(item)
        if len(selected) >= max_colors:
            break
    return selected


def _extract_palettes_sync(data: bytes, max_colors: int = 6) -> dict[str, str]:
    try:
        img = _load_rgb(data)
        candidates = _quantize_candidates(img)

        # ── display palette: minimal filter, just strip near-black and near-white ──
        display = [
            c for c in candidates if not (c[3] < 0.05) and not (c[3] > 0.97 and c[2] < 0.05)
        ]
        display_colors = [
            f"#{r:02x}{g:02x}{b:02x}" for _, _, _, _, r, g, b in display[:max_colors]
        ]

        # ── lighting palette: tiered vibrant filter ──
        vibrant = [
            c for c in candidates if c[2] >= SAT_MIN and c[3] >= VAL_MIN and c[2] * c[3] >= SV_MIN
        ]
        selected = _hue_diverse(vibrant, max_colors)
        if selected:
            palette_type = "vibrant"
        else:
            less_strict = [c for c in candidates if c[3] > 0.15]
            selected = _hue_diverse(less_strict, max_colors)[:4]
            palette_type = "desaturated" if selected else "monochrome"
            if not selected:
                selected = candidates[:4]

        # Most vibrant first so consumers can take [0] without scanning.
        selected.sort(key=lambda c: c[2] * c[3], reverse=True)
        lighting_colors = [f"#{r:02x}{g:02x}{b:02x}" for _, _, _, _, r, g, b in selected]

        return {
            "cover_palette": ",".join(display_colors),
            "cover_palette_lighting": ",".join(lighting_colors),
            "cover_palette_type": palette_type,
        }
    except Exception:  # pylint: disable=broad-except
        logging.exception("Color palette extraction failed")
        return {
            "cover_palette": "",
            "cover_palette_lighting": "",
            "cover_palette_type": "",
        }


async def extract_palettes(data: bytes, max_colors: int = 6) -> dict[str, str]:
    """Return display palette, lighting palette, and palette type for image bytes.

    Returns a dict with keys:
      cover_palette          — comma-separated hex, minimal filtering (for graphics)
      cover_palette_lighting — comma-separated hex, vibrant only (for stage lights)
      cover_palette_type     — 'vibrant' | 'desaturated' | 'monochrome'
    """
    return await asyncio.to_thread(_extract_palettes_sync, data, max_colors)
