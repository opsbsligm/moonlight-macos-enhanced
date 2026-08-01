#!/bin/zsh
set -euo pipefail

# Download binary frameworks required for building Moonlight
# These are gitignored due to size and must be fetched before building

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"

XCFRAMEWORKS_DIR="${PROJECT_DIR}/xcframeworks"
OPENSSL_DIR="${PROJECT_DIR}/Packages/OpenSSL.xcframework"

XCFRAMEWORKS_URL="https://github.com/coofdy/moonlight-mobile-deps/releases/download/latest/moonlight-apple-xcframeworks.zip"
OPENSSL_URL="https://github.com/krzyzanowskim/OpenSSL/releases/download/3.6.0001/OpenSSL.xcframework.zip"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "=== Downloading xcframeworks (FFmpeg, Opus, SDL2, OpenSSL) ==="
if [[ -d "$XCFRAMEWORKS_DIR" && $(ls -A "$XCFRAMEWORKS_DIR" 2>/dev/null | wc -l) -gt 0 ]]; then
  echo "xcframeworks/ already exists, skipping download"
else
  curl -L --fail -o "$TMP_DIR/xcframeworks.zip" "$XCFRAMEWORKS_URL"
  mkdir -p "$XCFRAMEWORKS_DIR"
  unzip -o "$TMP_DIR/xcframeworks.zip" -d "$XCFRAMEWORKS_DIR"
  echo "xcframeworks downloaded to $XCFRAMEWORKS_DIR"
fi

echo "=== Downloading OpenSSL.xcframework ==="
if [[ -d "$OPENSSL_DIR" ]]; then
  echo "OpenSSL.xcframework already exists, skipping download"
else
  curl -L --fail -o "$TMP_DIR/openssl.zip" "$OPENSSL_URL"
  mkdir -p "${PROJECT_DIR}/Packages"
  unzip -o "$TMP_DIR/openssl.zip" -d "${PROJECT_DIR}/Packages/"
  echo "OpenSSL.xcframework downloaded to $OPENSSL_DIR"
fi

echo "=== All frameworks ready ==="
