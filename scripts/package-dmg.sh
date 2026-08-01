#!/bin/zsh
set -euo pipefail

# Package Moonlight.app into a DMG for distribution
# Usage: scripts/package-dmg.sh [path-to-app] [output-dmg]

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"

APP_PATH="${1:-${PROJECT_DIR}/build/xcode/derivedData/Build/Products/Release/Moonlight.app}"
OUTPUT_DMG="${2:-${PROJECT_DIR}/build/Moonlight.dmg}"
APP_NAME=$(basename "$APP_PATH" .app)

if [[ ! -d "$APP_PATH" ]]; then
  echo "error: App not found at $APP_PATH" >&2
  exit 1
fi

echo "Packaging $APP_NAME.app into DMG..."

VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP_PATH/Contents/Info.plist" 2>/dev/null || echo "1.0.0")
BUILD_NUM=$(/usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$APP_PATH/Contents/Info.plist" 2>/dev/null || echo "1")
DMG_NAME="Moonlight-${VERSION}-build${BUILD_NUM}.dmg"
OUTPUT_DMG="${OUTPUT_DMG%.*}_${VERSION}-build${BUILD_NUM}.dmg"

STAGING_DIR=$(mktemp -d -t moonlight-dmg)
trap 'rm -rf "$STAGING_DIR"' EXIT

# Copy app and create Applications symlink
cp -R "$APP_PATH" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

# Create the DMG
hdiutil create \
  -volname "Moonlight" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  -imagekey zlib-level=9 \
  "$OUTPUT_DMG"

echo "DMG created: $OUTPUT_DMG"
echo "Size: $(du -h "$OUTPUT_DMG" | cut -f1)"
