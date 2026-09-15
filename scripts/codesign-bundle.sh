#!/usr/bin/env bash
set -euo pipefail

# Ad-hoc sign everything the app bundle embeds, from the inside out.
#
# The bundle shipped unsigned and stayed that way because nothing read it back:
# the main executable carried no signature at all, and the vendored frameworks
# carried their upstream signature over a layout this repository then changed
# (the universal merge replaces a signed binary with `lipo -create`, and the
# framework headers the seal listed are not shipped), so every one of them
# reported `file missing` and failed verification. On Apple Silicon that is the
# category of thing that shows up as the loader refusing a framework, and a
# release page cannot tell anyone which of these two shapes a download has.
#
# No signing identity is required and none is pretended: `-s -` is the ad-hoc
# identity, which seals the bundle so tampering is detectable and so that a
# framework is allowed to load. It does not satisfy Gatekeeper -- nothing without
# a Developer ID and notarization does -- and launch-code-audit.py reports that
# part as what it is instead of letting it read as either success or failure.
#
# Usage: scripts/codesign-bundle.sh path/to/Moonlight.app
SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)"

APP="${1:-}"
if [[ -z "$APP" || ! -d "$APP" ]]; then
  echo "error: pass an .app bundle to sign; got '${APP:-<nothing>}'" >&2
  exit 1
fi

CODESIGN="$(command -v codesign || echo /usr/bin/codesign)"
if [[ ! -x "$CODESIGN" ]]; then
  echo "error: codesign is not available, so the bundle cannot be signed" >&2
  exit 1
fi

sign() {
  local target="$1"
  # The old signature goes first, on purpose. Retagging in place and keeping the
  # previous designated requirement left `codesign --verify` reporting `file
  # modified` on the framework that was retagged, because the requirement and the
  # flags belonged to a build whose bytes are no longer there. Removing first and
  # signing fresh is what makes the whole bundle verify.
  local entitlements=()
  local captured
  captured="$(mktemp)"
  if "$CODESIGN" "-d" "--entitlements" "-" "$target" 2>/dev/null >"$captured" \
     && grep -q "<key>" "$captured"; then
    entitlements=(--entitlements "$captured")
  fi
  "$CODESIGN" --remove-signature "$target" 2>/dev/null || true
  # `--preserve-metadata=entitlements` keeps any entitlement the object already
  # carries. Nothing in this bundle has one today; the flag is here so that adding
  # one later cannot silently be dropped by the retag. Entitlements are read from
  # the object before the signature is dropped, so the order above is load-bearing.
  # `${a[@]+...}` because the runner's bash is 3.2, where an empty array under
  # `set -u` is an unbound variable rather than nothing at all.
  "$CODESIGN" --force --sign - ${entitlements[@]+"${entitlements[@]}"} --timestamp=none "$target"
  rm -f "$captured"
  echo "signed $(basename "$target")"
}

# Frameworks and plug-ins first: an outer signature seals the bytes of the inner
# ones, so signing the app before its contents would seal a state that is about
# to change. Versioned frameworks are signed at the versions directory, which is
# what the bundle's own layout resolves to.
while IFS= read -r nested; do
  case "$nested" in
    */Versions/A/*.framework|*/Versions/A/*.framework/Versions/A) sign "$nested" ;;
    *) sign "$nested" ;;
  esac
done < <(
  find "$APP/Contents" -depth \( -name '*.framework' -o -name '*.dylib' \
       -o -name '*.xpc' -o -name '*.bundle' \) \
    \( -path '*/Contents/Frameworks/*' -o -path '*/Contents/PlugIns/*' \
       -o -path '*/Contents/Libraries/*' \) -print 2>/dev/null || true
)

# Helper tools live outside the framework tree and are executed by launchd, not
# by the loader, so they need their own signature rather than the app's seal.
# `+111` is BSD find and GNU find spells the same test differently, and this
# script runs on a macOS runner while the portability rule in the workflow audit
# reads every script in this directory, so the executability test is done by the
# shell instead of by a flag only one find understands.
while IFS= read -r helper; do
  [[ -x "$helper" ]] && sign "$helper"
done < <(find "$APP/Contents/Library/LaunchServices" -type f 2>/dev/null || true)

# And the bundle last, which is what seals everything above.
sign "$APP"
