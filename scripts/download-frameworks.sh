#!/usr/bin/env bash
set -euo pipefail

# Download binary frameworks required for building Moonlight.
# These are gitignored due to size and must be fetched before building.
#
# This script is the single source of truth for dependency preparation: both a
# developer machine and CI run exactly these steps. CI used to duplicate the
# download inline, which silently drifted and left Packages/OpenSSL.xcframework
# and libs/openssl absent, so every pipeline run failed before compiling.
# The layout checks at the bottom turn that class of failure into a clear error.

# "${0:A:h}" is a zsh modifier for the script directory, and it reads as an
# unbound variable under bash. Resolving the directory from BASH_SOURCE works on
# both the macOS developer machine and the ubuntu audit runner, so the same
# script is genuinely the single entry point for both.
SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"

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

# A completed download and an archive that arrived whole are two different claims,
# and the pipeline used to make only the first one. unzip -o on a zip whose tail is
# missing can still leave a directory tree behind, and the layout checks downstream
# then blamed the archive for a truncated transfer. Testing the archive is the cheap
# way to keep those two messages apart.
verify_archive() {
  local path="$1"
  [[ -s "$path" ]] || return 1
  unzip -t -qq "$path" >/dev/null 2>&1
}

# One runner that could not connect to github.com for nine seconds turned both macOS
# builds red, and nothing about the failure was reproducible: curl had no retry and no
# stall limit, so the whole build ended on a single connect attempt and a human had to
# push again. Downloads retry connection failures, give up on a connection that never
# opens rather than one that merely paused, abandon a transfer that has stalled, and
# re-fetch an archive that arrives incomplete.
fetch_archive() {
  local url="$1" out="$2" attempt
  for attempt in 1 2 3; do
    if curl -L --fail --connect-timeout 15 --max-time 900 \
         --speed-limit 1024 --speed-time 60 \
         --retry 5 --retry-all-errors --retry-connrefused \
         -o "$out" "$url" && verify_archive "$out"; then
      return 0
    fi
    echo "warning: ${url} did not arrive whole (attempt ${attempt})" >&2
    rm -f "$out"
  done
  return 1
}

# An .xcframework is only valid when its own directory holds Info.plist.
# Unzipping with the wrong -d target leaves one extra level
# (OpenSSL.xcframework/OpenSSL.xcframework), which Xcode can still stumble
# through locally while Package.swift points at the outer shell. Flatten it so
# the resolved bundle is the one the manifest names.
# The xcframeworks archive is only needed when the bundles it provides are
# absent. The old probe asked whether xcframeworks/ was non-empty, and the
# repository commits xcframeworks/.gitignore on purpose so the directory exists
# in a clean checkout, so on every clean checkout the answer was "already
# prepared" and nothing was ever downloaded. Readiness now means the bundles the
# build links against are present with their own Info.plist.
REQUIRED_BUNDLES="FFmpeg.xcframework Opus.xcframework SDL2.xcframework"

missing_bundles() {
  local dir="$1" bundle missing=""
  for bundle in $REQUIRED_BUNDLES; do
    if [[ ! -f "${dir}/${bundle}/Info.plist" ]]; then
      missing="${missing:+${missing} }${bundle}"
    fi
  done
  printf '%s' "$missing"
}

# Searching two roots with one find call fails the whole pipeline whenever one
# root is absent, and head -1 closes the pipe early, which also fails it. Under
# set -euo pipefail both killed the script before its own error message could
# print, so a missing dependency looked like an unexplained exit 1.
first_openssl_headers() {
  local root hit
  for root in "$@"; do
    [[ -d "$root" ]] || continue
    hit=$(find "$root" -type d -path '*macos*arm64_x86_64/OpenSSL.framework/Versions/A/Headers' 2>/dev/null | head -n 1 || true)
    if [[ -n "$hit" ]]; then
      printf '%s' "$hit"
      return 0
    fi
  done
  return 1
}

# moonlight-common includes <openssl/*.h> while the vendored umbrella headers
# include <OpenSSL/*.h>, and libs/ is gitignored by design, so both spellings are
# exposed as links to one Headers directory.
link_openssl_headers() {
  local headers="$1" libs_dir="$2" spelling
  [[ -d "$headers" ]] || fail "no such headers directory: ${headers}"
  mkdir -p "$libs_dir"
  for spelling in openssl OpenSSL; do
    # On a case-insensitive volume the second spelling already resolves.
    if [[ ! -e "${libs_dir}/${spelling}" ]]; then
      ln -s "$headers" "${libs_dir}/${spelling}"
      echo "${libs_dir}/${spelling} -> ${headers}"
    else
      echo "${libs_dir}/${spelling} already present"
    fi
  done
}

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

# The flattening rule above is the only thing standing between a mistargeted
# unzip and a manifest that points at an empty directory, so it is exercised here
# on three layouts before anything is downloaded. No network, no arguments needed.
if [[ "${1:-}" == "--self-test" ]]; then
  case_dir=$(mktemp -d)
  trap 'rm -rf "$case_dir"' EXIT

  mkdir -p "$case_dir/good/OpenSSL.xcframework"
  touch "$case_dir/good/OpenSSL.xcframework/Info.plist"
  flatten_if_nested "$case_dir/good/OpenSSL.xcframework" || {
    echo "self-test: rejected a valid bundle" >&2; exit 1; }
  [[ -f "$case_dir/good/OpenSSL.xcframework/Info.plist" ]] || {
    echo "self-test: moved a valid bundle" >&2; exit 1; }

  mkdir -p "$case_dir/nested/OpenSSL.xcframework/OpenSSL.xcframework"
  touch "$case_dir/nested/OpenSSL.xcframework/OpenSSL.xcframework/Info.plist"
  flatten_if_nested "$case_dir/nested/OpenSSL.xcframework" || {
    echo "self-test: refused to flatten a nested bundle" >&2; exit 1; }
  [[ -f "$case_dir/nested/OpenSSL.xcframework/Info.plist" ]] || {
    echo "self-test: flattening left the manifest target empty" >&2; exit 1; }

  mkdir -p "$case_dir/broken/OpenSSL.xcframework"
  if flatten_if_nested "$case_dir/broken/OpenSSL.xcframework" 2>/dev/null; then
    echo "self-test: accepted a directory that is not an .xcframework" >&2; exit 1;
  fi

  # Readiness has to be judged by the bundles, not by the directory existing:
  # the placeholder .gitignore the repository commits makes an unprepared
  # directory look prepared to any emptiness test.
  mkdir -p "$case_dir/placeholder/xcframeworks"
  : > "$case_dir/placeholder/xcframeworks/.gitignore"
  missing=$(missing_bundles "$case_dir/placeholder/xcframeworks")
  [[ "$missing" == "FFmpeg.xcframework Opus.xcframework SDL2.xcframework" ]] || {
    echo "self-test: a directory holding only .gitignore counted as prepared (missing: ${missing:-none})" >&2; exit 1; }

  for bundle in $REQUIRED_BUNDLES; do
    mkdir -p "$case_dir/complete/xcframeworks/${bundle}"
    touch "$case_dir/complete/xcframeworks/${bundle}/Info.plist"
  done
  [[ -z "$(missing_bundles "$case_dir/complete/xcframeworks")" ]] || {
    echo "self-test: a complete tree reported $(missing_bundles "$case_dir/complete/xcframeworks") as missing" >&2; exit 1; }

  mv "$case_dir/complete/xcframeworks/Opus.xcframework/Info.plist" "$TMP_DIR/parked-Info.plist"
  [[ "$(missing_bundles "$case_dir/complete/xcframeworks")" == "Opus.xcframework" ]] || {
    echo "self-test: a bundle without Info.plist did not count as missing" >&2; exit 1; }

  # The header search has to survive an absent root and a truncated result, the
  # two shapes that used to abort the script in silence.
  mkdir -p "$case_dir/headers/Packages/OpenSSL.xcframework/macos-arm64_x86_64/OpenSSL.framework/Versions/A/Headers"
  mkdir -p "$case_dir/headers/Packages/OpenSSL.xcframework/macos-arm64_x86_64-simulator/OpenSSL.framework/Versions/A/Headers"
  found=$(first_openssl_headers \
    "$case_dir/headers/xcframeworks/OpenSSL.xcframework" \
    "$case_dir/headers/Packages/OpenSSL.xcframework" | head -1) || {
    echo "self-test: an absent first root aborted the header search" >&2; exit 1; }
  [[ -d "$found" && "$found" == *"/macos-arm64_x86_64/OpenSSL.framework/Versions/A/Headers" ]] || {
    echo "self-test: header search returned ${found:-nothing}" >&2; exit 1; }

  link_openssl_headers "$found" "$case_dir/headers/libs"
  [[ -e "$case_dir/headers/libs/openssl" && -e "$case_dir/headers/libs/OpenSSL" ]] || {
    echo "self-test: the header links do not resolve under both spellings" >&2; exit 1; }

  if first_openssl_headers "$case_dir/headers/nowhere" "$case_dir/headers/also-nowhere"; then
    echo "self-test: the header search reported success with nothing to find" >&2; exit 1;
  fi

  # A truncated transfer has to be refused by the fetch, not by the layout check
  # three steps later, so the accept/reject pair is exercised on real archives.
  mkdir -p "$case_dir/payload/inner"
  head -c 4096 /dev/urandom > "$case_dir/payload/inner/blob"
  (cd "$case_dir/payload" && zip -qr "$case_dir/good.zip" inner) || {
    echo "self-test: could not build an archive to test" >&2; exit 1; }
  verify_archive "$case_dir/good.zip" || {
    echo "self-test: rejected a complete archive" >&2; exit 1; }
  local_size=$(wc -c < "$case_dir/good.zip" | tr -d ' ')
  head -c "$(( local_size - 200 ))" "$case_dir/good.zip" > "$case_dir/short.zip"
  if verify_archive "$case_dir/short.zip" 2>/dev/null; then
    echo "self-test: accepted an archive with its tail missing" >&2; exit 1;
  fi
  : > "$case_dir/empty.zip"
  if verify_archive "$case_dir/empty.zip" 2>/dev/null; then
    echo "self-test: accepted an empty file as a download" >&2; exit 1;
  fi

  echo "dependency layout self-test passed"
  exit 0
fi

echo "=== Downloading xcframeworks (FFmpeg, Opus, SDL2, OpenSSL) ==="
xcframeworks_missing=$(missing_bundles "$XCFRAMEWORKS_DIR")
if [[ -z "$xcframeworks_missing" ]]; then
  echo "xcframeworks/ holds ${REQUIRED_BUNDLES}, skipping download"
else
  fetch_archive "$XCFRAMEWORKS_URL" "$TMP_DIR/xcframeworks.zip" || \
    fail "could not download ${XCFRAMEWORKS_URL}: the host refused or the transfer never completed"
  mkdir -p "$XCFRAMEWORKS_DIR"
  unzip -o "$TMP_DIR/xcframeworks.zip" -d "$XCFRAMEWORKS_DIR"
  echo "xcframeworks downloaded to $XCFRAMEWORKS_DIR"
  xcframeworks_missing=$(missing_bundles "$XCFRAMEWORKS_DIR")
  [[ -z "$xcframeworks_missing" ]] || \
    fail "the archive did not provide ${xcframeworks_missing}; xcframeworks/ holds $(ls -A "$XCFRAMEWORKS_DIR" | tr '\n' ' ')"
fi

echo "=== Downloading OpenSSL.xcframework ==="
if [[ -f "$OPENSSL_DIR/Info.plist" ]]; then
  echo "OpenSSL.xcframework already holds a manifest, skipping download"
else
  fetch_archive "$OPENSSL_URL" "$TMP_DIR/openssl.zip" || \
    fail "could not download ${OPENSSL_URL}: the host refused or the transfer never completed"
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
OPENSSL_HEADERS=$(first_openssl_headers "$XCFRAMEWORKS_DIR/OpenSSL.xcframework" "$OPENSSL_DIR") || OPENSSL_HEADERS=""

if [[ -z "$OPENSSL_HEADERS" ]]; then
  echo "error: no macOS OpenSSL headers found under ${XCFRAMEWORKS_DIR}/OpenSSL.xcframework or ${OPENSSL_DIR}" >&2
  exit 1
fi

link_openssl_headers "$OPENSSL_HEADERS" "$LIBS_DIR"

# A dangling symlink reads as "present" to [[ -e ]] only when it resolves, but a
# symlink copied from a stale tree can point at a path that no longer exists.
# Verify the header actually opens, because a broken libs/openssl fails much
# later inside moonlight-common with a message that names neither of these steps.
for spelling in openssl OpenSSL; do
  [[ -f "${LIBS_DIR}/${spelling}/evp.h" ]] || \
    fail "libs/${spelling}/evp.h is not readable; the symlink is stale, remove libs/ and rerun"
done

echo "=== All frameworks ready ==="
