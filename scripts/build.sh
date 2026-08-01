#!/bin/zsh
set -euo pipefail

# Full build orchestration: download deps -> build -> package DMG
# Usage: scripts/build.sh [--no-deps] [--no-dmg] [--debug]

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"

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

echo "Build output: $APP_PATH"

# Step 3: Package DMG
if [[ "$SKIP_DMG" -eq 0 && "$CONFIGURATION" == "Release" ]]; then
  echo "=== Step 3: Package DMG ==="
  zsh "${SCRIPT_DIR}/package-dmg.sh" "$APP_PATH"
else
  echo "=== Step 3: Skipping DMG (debug or --no-dmg) ==="
fi

echo "=== Done ==="
