#!/bin/zsh
set -euo pipefail

# Download binary frameworks required for building Moonlight.
# These are gitignored due to size and must be fetched before building.
#
# This script is the single source of truth for dependency preparation: both a
# developer machine and CI run exactly these steps. CI used to duplicate the
# download inline, which silently drifted and left Packages/OpenSSL.xcframework
# and libs/openssl absent, so every pipeline run failed before compiling.
# The layout checks at the bottom turn that class of failure into a clear error.

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"

XCFRAMEWORKS_DIR="${PROJECT_DIR}/xcframeworks"
OPENSSL_DIR="${PROJECT_DIR}/Packages/OpenSSL.xcframework"
LIBS_DIR="${PROJECT_DIR}/libs"

XCFRAMEWORKS_URL="https://github.com/coofdy/moonlight-mobile-deps/releases/download/latest/moonlight-apple-xcframeworks.zip"
OPENSSL_URL="https://github.com/krzyzanowskim/OpenSSL/releases/download/3.6.0001/OpenSSL.xcframework.zip"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

fail() {
  echo "error: $*" >&2
  exit 1
}

# An .xcframework is only valid when its own directory holds Info.plist.
# Unzipping with the wrong -d target leaves one extra level
# (OpenSSL.xcframework/OpenSSL.xcframework), which Xcode can still stumble
# through locally while Package.swift points at the outer shell. Flatten it so
# the resolved bundle is the one the manifest names.
flatten_if_nested() {
  local target="$1"
  local name
  name=$(basename "$target")
  [[ -f "${target}/Info.plist" ]] && return 0
  if [[ ! -f "${target}/${name}/Info.plist" ]]; then
    return 1
  fi
  if [[ $(ls -A "$target" | wc -l | tr -d ' ') -ne 1 ]]; then
    fail "${target} is not an .xcframework (no Info.plist) and holds more than one entry, so the nested bundle cannot be flattened automatically"
  fi
  echo "flattening nested bundle: ${target}/${name} -> ${target}"
  mv "$target" "${TMP_DIR}/unflattened"
  mv "${TMP_DIR}/unflattened/${name}" "$target"
}

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

flatten_if_nested "$OPENSSL_DIR" || fail "${OPENSSL_DIR} is missing"
[[ -f "${OPENSSL_DIR}/Info.plist" ]] || \
  fail "${OPENSSL_DIR} has no Info.plist; Packages/OpenSSL-Package/Package.swift resolves its binary target to this exact directory"

# moonlight-common.xcodeproj resolves OpenSSL headers through HEADER_SEARCH_PATHS "../libs/**".
# common-c includes <openssl/*.h> while the vendored Umbrella headers include <OpenSSL/*.h>,
# so expose the framework Headers directory under both spellings. Without this step a fresh
# clone fails to compile moonlight-common because libs/ is gitignored by design.
echo "=== Linking OpenSSL headers into libs/ ==="
OPENSSL_HEADERS=$(find "$XCFRAMEWORKS_DIR/OpenSSL.xcframework" "$OPENSSL_DIR" \
  -path '*macos*arm64_x86_64/OpenSSL.framework/Versions/A/Headers' -type d 2>/dev/null | head -1)

if [[ -z "$OPENSSL_HEADERS" ]]; then
  echo "error: no macOS OpenSSL headers found under xcframeworks/ or Packages/" >&2
  exit 1
fi

mkdir -p "$LIBS_DIR"
for spelling in openssl OpenSSL; do
  # On case-insensitive volumes the second spelling already resolves to the first.
  if [[ ! -e "$LIBS_DIR/$spelling" ]]; then
    ln -s "$OPENSSL_HEADERS" "$LIBS_DIR/$spelling"
    echo "libs/$spelling -> $OPENSSL_HEADERS"
  else
    echo "libs/$spelling already present"
  fi
done

# A dangling symlink reads as "present" to [[ -e ]] only when it resolves, but a
# symlink copied from a stale tree can point at a path that no longer exists.
# Verify the header actually opens, because a broken libs/openssl fails much
# later inside moonlight-common with a message that names neither of these steps.
for spelling in openssl OpenSSL; do
  [[ -f "${LIBS_DIR}/${spelling}/evp.h" ]] || \
    fail "libs/${spelling}/evp.h is not readable; the symlink is stale, remove libs/ and rerun"
done

echo "=== All frameworks ready ==="
