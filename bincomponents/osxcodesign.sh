#!/usr/bin/env bash
set -euo pipefail
# Notarize and staple a macOS app bundle.
# Signing is handled by PyInstaller via codesign_identity on EXE.
#
# Required env var:
#   MACOS_SIGN_IDENTITY  "Developer ID Application: Name (TEAMID)"
#
# Optional env vars (all three required for notarization):
#   APPLE_ID             Apple ID email
#   APPLE_ID_PASSWORD    App-specific password (from appleid.apple.com)
#   APPLE_TEAM_ID        10-character team ID

APP="${1:?Usage: osxcodesign.sh <path/to/App.app>}"

if [[ -z "${MACOS_SIGN_IDENTITY:-}" ]]; then
  echo "ERROR: MACOS_SIGN_IDENTITY must be set."
  exit 1
fi

echo "=== Verifying signature ==="
codesign --verify --deep --strict --verbose=2 "${APP}"

# Notarize only if all three Apple credentials are present
if [[ -n "${APPLE_ID:-}" && -n "${APPLE_ID_PASSWORD:-}" && -n "${APPLE_TEAM_ID:-}" ]]; then
  echo "=== Notarizing ==="
  NOTARIZE_ZIP="${APP%.app}-notarize.zip"
  ditto -c -k --keepParent "${APP}" "${NOTARIZE_ZIP}"

  NOTARIZE_RESULT=$(xcrun notarytool submit "${NOTARIZE_ZIP}" \
    --apple-id "${APPLE_ID}" \
    --password "${APPLE_ID_PASSWORD}" \
    --team-id "${APPLE_TEAM_ID}" \
    --wait --output-format json) || {
    echo "ERROR: notarytool submit failed (exit $?)"
    echo "${NOTARIZE_RESULT}"
    exit 1
  }
  NOTARIZE_ID=$(echo "${NOTARIZE_RESULT}" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
  NOTARIZE_STATUS=$(echo "${NOTARIZE_RESULT}" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "Notarization status: ${NOTARIZE_STATUS} (id: ${NOTARIZE_ID})"

  if [[ "${NOTARIZE_STATUS}" != "Accepted" ]]; then
    echo "=== Notarization log ==="
    xcrun notarytool log "${NOTARIZE_ID}" \
      --apple-id "${APPLE_ID}" \
      --password "${APPLE_ID_PASSWORD}" \
      --team-id "${APPLE_TEAM_ID}"
    echo "ERROR: Notarization failed with status: ${NOTARIZE_STATUS}"
    exit 1
  fi

  rm -f "${NOTARIZE_ZIP}"

  echo "=== Stapling ==="
  xcrun stapler staple "${APP}"

  echo "=== Verifying notarization ==="
  spctl --assess --type execute --verbose "${APP}"
else
  echo "=== Skipping notarization (APPLE_ID/APPLE_ID_PASSWORD/APPLE_TEAM_ID not set) ==="
fi
