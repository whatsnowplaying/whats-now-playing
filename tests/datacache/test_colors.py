"""Tests for cover art color palette extraction."""

import io
import re

import pytest
from PIL import Image

import nowplaying.datacache.colors

HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


def _make_png(rgb: tuple[int, int, int], size: int = 50) -> bytes:
    img = Image.new("RGB", (size, size), rgb)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rgb,expected_type",
    [
        ((200, 50, 50), "vibrant"),  # saturated red: s≈0.75, v≈0.78
        ((180, 170, 165), "desaturated"),  # muted neutral: s≈0.08, v≈0.71
        ((20, 20, 20), "monochrome"),  # near-black: v≈0.08, below all thresholds
    ],
)
async def test_extract_palettes_palette_type(rgb, expected_type):
    """palette_type classification matches saturation/value of the source color."""
    result = await nowplaying.datacache.colors.extract_palettes(_make_png(rgb))
    assert result["cover_palette_type"] == expected_type


@pytest.mark.asyncio
async def test_extract_palettes_returns_all_keys():
    """extract_palettes always returns all three expected keys."""
    result = await nowplaying.datacache.colors.extract_palettes(_make_png((100, 150, 200)))
    assert set(result.keys()) == {"cover_palette", "cover_palette_lighting", "cover_palette_type"}


@pytest.mark.asyncio
async def test_extract_palettes_hex_format():
    """Colors in both palette fields are valid lowercase hex strings."""
    result = await nowplaying.datacache.colors.extract_palettes(_make_png((200, 50, 50)))
    for field in ("cover_palette", "cover_palette_lighting"):
        assert result[field], f"{field} should not be empty for a vibrant image"
        for color in result[field].split(","):
            assert HEX_RE.match(color), f"bad hex color in {field}: {color!r}"


@pytest.mark.asyncio
async def test_extract_palettes_max_colors():
    """Neither palette field returns more than 6 colors."""
    result = await nowplaying.datacache.colors.extract_palettes(_make_png((200, 50, 50)))
    for field in ("cover_palette", "cover_palette_lighting"):
        colors = [c for c in result[field].split(",") if c]
        assert len(colors) <= 6, f"{field} returned more than 6 colors"


@pytest.mark.asyncio
async def test_extract_palettes_rgba_transparency():
    """RGBA images with transparency are handled without error."""
    img = Image.new("RGBA", (50, 50), (200, 50, 50, 128))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    result = await nowplaying.datacache.colors.extract_palettes(buf.getvalue())
    assert result["cover_palette_type"] in ("vibrant", "desaturated", "monochrome")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_data", [b"not an image", b""])
async def test_extract_palettes_bad_input_no_exception(bad_data):
    """Invalid or empty input returns empty strings without raising."""
    result = await nowplaying.datacache.colors.extract_palettes(bad_data)
    assert result["cover_palette"] == ""
    assert result["cover_palette_lighting"] == ""
    assert result["cover_palette_type"] == ""


def test_color_extract_types_includes_image_types():
    """COLOR_EXTRACT_TYPES covers the expected image data types."""
    expected = {"front_cover", "artistthumbnail", "artistfanart", "artistbanner"}
    assert expected == nowplaying.datacache.colors.COLOR_EXTRACT_TYPES


def test_color_extract_types_excludes_logo():
    """artistlogo is excluded from color extraction."""
    assert "artistlogo" not in nowplaying.datacache.colors.COLOR_EXTRACT_TYPES
