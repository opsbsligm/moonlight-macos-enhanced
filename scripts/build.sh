#!/usr/bin/env bash
set -euo pipefail

# Full build orchestration: download deps -> build -> package DMG
# Usage: scripts/build.sh [--no-deps] [--no-dmg] [--debug]

# "${0:A:h}" is a zsh modifier for the script directory, and it reads as an
# unbound variable under bash. Resolving the directory from BASH_SOURCE works on
# both the macOS developer machine and the ubuntu audit runner, so the same
# script is genuinely the single entry point for both.
SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"

CONFIGURATION="Release"
SKIP_DEPS=0
SKIP_DMG=0

for arg in "$@"; do
  case "$arg" in
    --no-deps)  SKIP_DEPS=1 ;;
    --no-dmg)   SKIP_DMG=1 ;;
    --debug)    CONFIGURATION="Debug" ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

DERIVED_DATA_DIR="${PROJECT_DIR}/build/xcode/derivedData"
APP_PATH="${DERIVED_DATA_DIR}/Build/Products/${CONFIGURATION}/Moonlight.app"

# Step 1: Download frameworks if needed
if [[ "$SKIP_DEPS" -eq 0 ]]; then
  echo "=== Step 1: Ensure binary frameworks ==="
  zsh "${SCRIPT_DIR}/download-frameworks.sh"
else
  echo "=== Step 1: Skipping dependency download ==="
fi

# Step 2: Build
echo "=== Step 2: Build (${CONFIGURATION}) ==="
xcodebuild \
  -project "${PROJECT_DIR}/Moonlight.xcodeproj" \
  -scheme "Moonlight for macOS" \
  -configuration "$CONFIGURATION" \
  -derivedDataPath "$DERIVED_DATA_DIR" \
  build

if [[ ! -d "$APP_PATH" ]]; then
  echo "error: Build succeeded but app not found at $APP_PATH" >&2
  exit 1
fi

# Xcode never writes the Info.plist language tables for this project, so without this a local
# build would show a different permission prompt than a downloaded one, and the difference
# would only ever be visible on someone else's machine. The install lives in the signing
# script because that is the last moment the shipped bytes can still change; asking that
# script for just this part needs no signing identity and no full release.
"${SCRIPT_DIR}/codesign-bundle.sh" "$APP_PATH" --install-localizations-only

echo "Build output: $APP_PATH"

# Step 3: Package DMG
if [[ "$SKIP_DMG" -eq 0 && "$CONFIGURATION" == "Release" ]]; then
  echo "=== Step 3: Package DMG ==="
  zsh "${SCRIPT_DIR}/package-dmg.sh" "$APP_PATH"
else
  echo "=== Step 3: Skipping DMG (debug or --no-dmg) ==="
fi

echo "=== Done ==="
