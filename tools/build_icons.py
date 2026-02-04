#!/usr/bin/env python3
"""
Generate all icon and logo files from the source SVG.

This script regenerates all logo and icon files used by the application from
the canonical SVG source file (docs/images/wnp_logo.svg).

Generated files:
- PNG logos at various sizes (docs/images/, site/images/)
- Windows .ico files (bincomponents/, nowplaying/resources/)
- macOS .icns file (bincomponents/)
- Favicon (site/assets/images/)

Requirements:
- Inkscape (for SVG to PNG conversion)
- Pillow (for .ico generation)
- iconutil (macOS only, for .icns generation)
"""

import argparse
import logging
import pathlib
import shutil
import subprocess
import sys
import tempfile

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow", file=sys.stderr)
    sys.exit(1)


def check_inkscape():
    """Check if Inkscape is available."""
    if not shutil.which("inkscape"):
        logging.error("Inkscape is not installed or not in PATH")
        logging.error("Install from: https://inkscape.org/")
        return False
    return True


def check_iconutil():
    """Check if iconutil is available (macOS only)."""
    if not shutil.which("iconutil"):
        logging.warning("iconutil not found - skipping .icns generation (macOS only)")
        return False
    return True


def svg_to_png(svg_path, output_path, width, height):
    """
    Convert SVG to PNG using Inkscape.

    Args:
        svg_path: Path to source SVG file
        output_path: Path for output PNG file
        width: Output width in pixels
        height: Output height in pixels

    Returns:
        True if successful, False otherwise
    """
    try:
        subprocess.run(
            [
                "inkscape",
                str(svg_path),
                "--export-type=png",
                f"--export-filename={output_path}",
                f"--export-width={width}",
                f"--export-height={height}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        logging.info("Generated %s (%dx%d)", output_path.name, width, height)
        return True
    except subprocess.CalledProcessError as error:
        logging.error("Failed to generate %s: %s", output_path.name, error.stderr)
        return False


def create_ico_file(source_png, output_path, sizes):
    """
    Create a Windows .ico file with multiple resolutions.

    Args:
        source_png: Path to high-resolution source PNG
        output_path: Path for output .ico file
        sizes: List of (width, height) tuples for icon sizes

    Returns:
        True if successful, False otherwise
    """
    try:
        img = Image.open(source_png)
        img.save(output_path, format="ICO", sizes=sizes)
        logging.info("Generated %s with %d sizes", output_path.name, len(sizes))
        return True
    except Exception as error:  # pylint: disable=broad-except
        logging.error("Failed to generate %s: %s", output_path.name, error)
        return False


def create_icns_file(temp_dir, png_files, output_path):
    """
    Create a macOS .icns file from PNG files.

    Args:
        temp_dir: Temporary directory for .iconset
        png_files: Dict mapping iconset filenames to PNG paths
        output_path: Path for output .icns file

    Returns:
        True if successful, False otherwise
    """
    if not check_iconutil():
        return False

    try:
        # Create .iconset directory
        iconset_dir = temp_dir / "app.iconset"
        iconset_dir.mkdir()

        # Copy PNG files to iconset with proper naming
        for iconset_name, png_path in png_files.items():
            shutil.copy(png_path, iconset_dir / iconset_name)

        # Generate .icns
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(output_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        logging.info("Generated %s", output_path.name)
        return True
    except subprocess.CalledProcessError as error:
        logging.error("Failed to generate %s: %s", output_path.name, error.stderr)
        return False
    except Exception as error:  # pylint: disable=broad-except
        logging.error("Failed to generate %s: %s", output_path.name, error)
        return False


def generate_png_logos(svg_path, output_dir):
    """Generate PNG logos at various sizes.

    Args:
        svg_path: Path to source SVG file
        output_dir: Base output directory

    Returns:
        True if all logos generated successfully, False otherwise
    """
    logging.info("Generating PNG logos...")
    logo_specs = [
        (882, 882, output_dir / "docs/images/wnp-logo.png"),
        (250, 250, output_dir / "docs/images/wnp-logo-small.png"),
        (882, 882, output_dir / "site/images/wnp-logo.png"),
        (250, 250, output_dir / "site/images/wnp-logo-small.png"),
        (48, 48, output_dir / "site/assets/images/favicon.png"),
    ]

    success = True
    for width, height, output_path in logo_specs:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not svg_to_png(svg_path, output_path, width, height):
            success = False
    return success


def generate_icon_pngs(svg_path, temp_dir):
    """Generate PNG files at all required icon sizes.

    Args:
        svg_path: Path to source SVG file
        temp_dir: Temporary directory for intermediate files

    Returns:
        Tuple of (icon_pngs dict, success bool)
    """
    logging.info("Generating icon sizes...")
    icon_sizes = [16, 32, 48, 64, 128, 256, 512, 1024]
    icon_pngs = {}

    success = True
    for size in icon_sizes:
        png_path = temp_dir / f"icon_{size}x{size}.png"
        if svg_to_png(svg_path, png_path, size, size):
            icon_pngs[size] = png_path
        else:
            success = False

    return icon_pngs, success


def generate_ico_files(icon_pngs, output_dir):
    """Generate Windows .ico files from icon PNGs.

    Args:
        icon_pngs: Dict mapping sizes to PNG paths
        output_dir: Base output directory

    Returns:
        True if successful, False otherwise
    """
    if not icon_pngs:
        return True

    if 1024 not in icon_pngs:
        logging.error("Missing 1024x1024 PNG, cannot generate .ico files")
        return False

    logging.info("Generating Windows .ico files...")
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_files = [
        output_dir / "bincomponents/windows.ico",
        output_dir / "nowplaying/resources/icon.ico",
    ]

    success = True
    for ico_path in ico_files:
        ico_path.parent.mkdir(parents=True, exist_ok=True)
        if not create_ico_file(icon_pngs[1024], ico_path, ico_sizes):
            success = False

    return success


def generate_icns_file(icon_pngs, temp_dir, output_dir):
    """Generate macOS .icns file from icon PNGs.

    Args:
        icon_pngs: Dict mapping sizes to PNG paths
        temp_dir: Temporary directory for iconset
        output_dir: Base output directory

    Returns:
        True if successful, False otherwise
    """
    if not icon_pngs:
        return True

    logging.info("Generating macOS .icns file...")
    icns_path = output_dir / "bincomponents/osx.icns"
    icns_path.parent.mkdir(parents=True, exist_ok=True)

    # Map iconset names to PNG paths, only for sizes that were successfully generated
    iconset_mapping = {
        16: "icon_16x16.png",
        32: ["icon_16x16@2x.png", "icon_32x32.png"],
        64: "icon_32x32@2x.png",
        128: "icon_128x128.png",
        256: ["icon_128x128@2x.png", "icon_256x256.png"],
        512: ["icon_256x256@2x.png", "icon_512x512.png"],
        1024: "icon_512x512@2x.png",
    }

    iconset_files = {}
    for size, names in iconset_mapping.items():
        if size in icon_pngs:
            if isinstance(names, list):
                for name in names:
                    iconset_files[name] = icon_pngs[size]
            else:
                iconset_files[names] = icon_pngs[size]

    if not iconset_files:
        logging.error("No valid icon sizes generated for .icns file")
        return False

    if not create_icns_file(temp_dir, iconset_files, icns_path):
        # Non-fatal on non-macOS systems
        logging.warning("Skipped .icns generation")

    return True


def generate_icon_files(svg_path, temp_dir, output_dir):
    """Generate Windows .ico and macOS .icns files.

    Args:
        svg_path: Path to source SVG file
        temp_dir: Temporary directory for intermediate files
        output_dir: Base output directory

    Returns:
        True if all icons generated successfully, False otherwise
    """
    icon_pngs, pngs_success = generate_icon_pngs(svg_path, temp_dir)
    ico_success = generate_ico_files(icon_pngs, output_dir)
    icns_success = generate_icns_file(icon_pngs, temp_dir, output_dir)

    return pngs_success and ico_success and icns_success


def main():
    """Generate all icon and logo files from SVG source."""
    parser = argparse.ArgumentParser(
        description="Generate icon and logo files from SVG source",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--svg",
        type=pathlib.Path,
        default=pathlib.Path("docs/images/wnp_logo.svg"),
        help="Path to source SVG file (default: docs/images/wnp_logo.svg)",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=pathlib.Path(),
        help="Base output directory (default: current directory)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    # Check dependencies
    if not check_inkscape():
        sys.exit(1)

    # Verify source SVG exists
    svg_path = args.svg
    if not svg_path.exists():
        logging.error("Source SVG not found: %s", svg_path)
        sys.exit(1)

    output_dir = args.output_dir

    # Create temporary directory for intermediate files
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = pathlib.Path(temp_dir_str)

        # Generate all PNG logos
        logos_success = generate_png_logos(svg_path, output_dir)

        # Generate icon files (.ico and .icns)
        icons_success = generate_icon_files(svg_path, temp_dir, output_dir)

        # Copy SVG to resources for Qt to use directly
        logging.info("Copying SVG to resources...")
        svg_dest = output_dir / "nowplaying/resources/wnp_logo.svg"
        svg_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(svg_path, svg_dest)
        logging.info("Copied %s to %s", svg_path.name, svg_dest)

        success = logos_success and icons_success

    if success:
        logging.info("Successfully generated all icon and logo files")
        return 0

    logging.error("Some files failed to generate")
    return 1


if __name__ == "__main__":
    sys.exit(main())
