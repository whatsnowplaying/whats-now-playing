#!/usr/bin/env python3
"""build a new upgradetable.py"""

import argparse
import hashlib
import json
import logging
import os
import pathlib
import sys


def checksum(filename):
    """generate sha512, normalizing line endings for text files"""
    hashfunc = hashlib.sha512()

    # Check if file is likely a text file based on extension
    text_extensions = {'.htm', '.html', '.css', '.js', '.txt', '.md', '.json', '.xml'}
    file_ext = os.path.splitext(filename)[1].lower()

    if file_ext in text_extensions:
        # Text file: normalize line endings
        try:
            with open(filename, "r", encoding="utf-8") as fileh:
                content = fileh.read().replace("\r\n", "\n").replace("\r", "\n")
                hashfunc.update(content.encode("utf-8"))
        except UnicodeDecodeError:
            # Fall back to binary mode if UTF-8 fails
            with open(filename, "rb") as fileh:
                while chunk := fileh.read(128 * hashfunc.block_size):
                    hashfunc.update(chunk)
    else:
        # Binary file: hash as-is
        with open(filename, "rb") as fileh:
            while chunk := fileh.read(128 * hashfunc.block_size):
                hashfunc.update(chunk)

    return hashfunc.hexdigest()


def main():  # pylint: disable=too-many-statements
    """build a new file"""
    parser = argparse.ArgumentParser(description="Build template hash file for upgrade detection")
    parser.add_argument("shafile", help="Path to the updateshas.json file")
    parser.add_argument("versions", nargs="+", help="Git versions to process")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not pathlib.Path(args.shafile).parent.exists():
        logging.error(
            "Directory for shafile does not exist: %s", pathlib.Path(args.shafile).parent
        )
        sys.exit(1)

    # Load existing hashes
    oldshas = {}
    if os.path.exists(args.shafile):
        try:
            with open(args.shafile, encoding="utf-8") as fhin:
                oldshas = json.loads(fhin.read())
            logging.info("Loaded existing hashes from %s", args.shafile)
        except (json.JSONDecodeError, OSError) as error:
            logging.error("Failed to load existing hash file: %s", error)
            sys.exit(1)

    # Process each version
    for version in args.versions:
        logging.info("Processing version: %s", version)
        templates_dir = pathlib.Path("nowplaying", "templates")
        if not templates_dir.exists():
            logging.warning("Templates directory not found for version %s", version)
            continue

        try:
            _process_template_directory(templates_dir, templates_dir, oldshas, version)
        except OSError as error:
            logging.error("Failed to process templates for version %s: %s", version, error)
            continue

    # Write updated hashes
    try:
        with open(args.shafile, "w", encoding="utf-8") as fhout:
            fhout.write(json.dumps(oldshas, indent=2, sort_keys=True))
        logging.info("Updated hash file written to %s", args.shafile)
    except OSError as error:
        logging.error("Failed to write hash file: %s", error)
        sys.exit(1)


def _process_template_directory(base_dir, current_dir, oldshas, version):
    """recursively process template directories"""

    for apppath in current_dir.iterdir():
        # Skip files/directories that shouldn't be processed
        if apppath.name in {'.gitignore', '.DS_Store', 'Thumbs.db', '.git'}:
            continue

        if apppath.is_dir():
            # Recursively process subdirectories
            _process_template_directory(base_dir, apppath, oldshas, version)
            continue

        # Use relative path from base templates directory
        relative_path = str(apppath.relative_to(base_dir))

        if relative_path not in oldshas:
            oldshas[relative_path] = {}

        try:
            hexd = checksum(apppath)
        except OSError as error:
            logging.warning("Failed to read %s: %s", relative_path, error)
            continue

        # Check if this hash already exists for any version
        hash_exists = any(sha == hexd for sha in oldshas[relative_path].values())
        if hash_exists:
            logging.debug("Hash for %s already exists, skipping", relative_path)
            continue

        oldshas[relative_path][version] = hexd
        logging.debug("Added hash for %s version %s", relative_path, version)


if __name__ == "__main__":
    main()
