#!/usr/bin/env bash
#
# Regenerate updateshas.json with path separator normalization
# This script checks out each historical version and recalculates SHAs
#

set -e

REPO_DIR="/tmp/whats-now-playing"
ORIGINAL_DIR="$(pwd)"
SHAS_FILE="${ORIGINAL_DIR}/nowplaying/resources/updateshas.json"

# All versions from updateshas.json in chronological order
VERSIONS=(
    "2.0.0"
    "2.0.1"
    "3.0.0-rc1"
    "3.0.0-rc2"
    "3.0.0-rc3"
    "3.0.0-rc4"
    "3.0.0-rc5"
    "3.0.0-rc6"
    "3.0.0-rc7"
    "3.0.0-rc8"
    "3.0.0-rc9"
    "3.0.0"
    "3.0.1"
    "3.1.0"
    "3.1.1"
    "3.1.2"
    "3.1.3"
    "4.0.0-rc1"
    "4.0.0-rc2"
    "4.0.0-rc3"
    "4.0.0-rc4"
    "4.0.0-rc5"
    "4.0.0-rc6"
    "4.0.0-rc7"
    "4.0.0-rc8"
    "4.0.1"
    "4.0.2"
    "4.0.3"
    "4.0.4"
    "4.0.5"
    "4.0.6"
    "4.1.0-rc1"
    "4.1.0-rc2"
    "4.1.0-rc3"
    "4.1.0"
    "4.2.0-rc1"
    "4.2.0-rc2"
    "4.2.0-rc3"
    "4.2.0-rc4"
    "4.2.0"
    "5.0.0-preview1"
    "5.0.0-preview2"
    "5.0.0-preview3"
    "5.0.0-preview5"
)

# Backup original updateshas.json
cp "${SHAS_FILE}" "${SHAS_FILE}.backup"
echo "Backed up original updateshas.json to ${SHAS_FILE}.backup"

# Clear existing shas file and start fresh
echo "{}" > "${SHAS_FILE}"

cd "${REPO_DIR}"

for version in "${VERSIONS[@]}"; do
    echo "================================================"
    echo "Processing version: ${version}"
    echo "================================================"

    # Force clean state before checkout to handle .gitattributes line ending changes
    git reset --hard HEAD
    git clean -fd

    # Checkout the version
    git checkout "${version}" 2>/dev/null || {
        echo "Warning: Could not checkout version ${version}, skipping..."
        continue
    }

    # Build templates if build_templates.py exists (for 5.0.0+ versions)
    if [ -f "${REPO_DIR}/tools/build_templates.py" ]; then
        echo "Building templates for version ${version}..."
        cd "${REPO_DIR}"
        python tools/build_templates.py || {
            echo "Warning: Failed to build templates for ${version}"
        }
    fi

    # Run updateshas.py for this version, pointing it to the checked-out repo
    cd "${REPO_DIR}"
    python "${ORIGINAL_DIR}/tools/updateshas.py" "${SHAS_FILE}" "${version}" || true
done

cd "${ORIGINAL_DIR}"

echo "================================================"
echo "Regeneration complete!"
echo "Original file backed up to: ${SHAS_FILE}.backup"
echo "New file at: ${SHAS_FILE}"
echo "================================================"
