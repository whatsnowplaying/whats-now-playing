#!/usr/bin/env bash
# Sign, notarize, and staple a macOS app bundle.
#
# Required env var:
#   MACOS_SIGN_IDENTITY  "Developer ID Application: Name (TEAMID)"
#
# Optional env vars (all three required for notarization):
#   APPLE_ID             Apple ID email
#   APPLE_ID_PASSWORD    App-specific password (from appleid.apple.com)
#   APPLE_TEAM_ID        10-character team ID

set -euo pipefail

APP="${1:?Usage: osxcodesign.sh <path/to/App.app>}"

if [[ -z "${MACOS_SIGN_IDENTITY:-}" ]]; then
  echo "ERROR: MACOS_SIGN_IDENTITY must be set."
  exit 1
fi

echo "=== Signing ${APP} ==="

# Sign all dylibs and Python extension modules from the inside out.
# This must happen before signing the outer bundle.
find "${APP}" \( -name "*.dylib" -o -name "*.so" \) | while read -r f; do
  codesign --force --sign "${MACOS_SIGN_IDENTITY}" \
    --options runtime \
    --entitlements bincomponents/entitlements.plist \
    --timestamp \
    "${f}"
done

# Sign any nested executables other than the main binary
find "${APP}/Contents/MacOS" -type f ! -name "WhatsNowPlaying" | while read -r f; do
  codesign --force --sign "${MACOS_SIGN_IDENTITY}" \
    --options runtime \
    --entitlements bincomponents/entitlements.plist \
    --timestamp \
    "${f}"
done

# Sign the app bundle itself
codesign --force --sign "${MACOS_SIGN_IDENTITY}" \
  --options runtime \
  --entitlements bincomponents/entitlements.plist \
  --timestamp \
  "${APP}"

echo "=== Verifying signature ==="
codesign --verify --deep --strict --verbose=2 "${APP}"
spctl --assess --type execute --verbose "${APP}"

# Notarize only if all three Apple credentials are present
if [[ -n "${APPLE_ID:-}" && -n "${APPLE_ID_PASSWORD:-}" && -n "${APPLE_TEAM_ID:-}" ]]; then
  echo "=== Notarizing ==="
  NOTARIZE_ZIP="${APP%.app}-notarize.zip"
  ditto -c -k --keepParent "${APP}" "${NOTARIZE_ZIP}"

  xcrun notarytool submit "${NOTARIZE_ZIP}" \
    --apple-id "${APPLE_ID}" \
    --password "${APPLE_ID_PASSWORD}" \
    --team-id "${APPLE_TEAM_ID}" \
    --wait

  rm -f "${NOTARIZE_ZIP}"

  echo "=== Stapling ==="
  xcrun stapler staple "${APP}"

  echo "=== Verifying notarization ==="
  spctl --assess --type execute --verbose "${APP}"
else
  echo "=== Skipping notarization (APPLE_ID/APPLE_ID_PASSWORD/APPLE_TEAM_ID not set) ==="
fi
