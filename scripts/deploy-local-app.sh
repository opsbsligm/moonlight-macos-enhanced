#!/usr/bin/env bash
# Local acceptance deploy: verify signature, stash the old app in Trash, swap
# atomically, re-verify the installed bytes and record the hashes. Refuses to
# interrupt a running instance. Usage: scripts/deploy-local-app.sh <staged.app> [slug]
set -euo pipefail
SRC="${1:?usage: deploy-local-app.sh /path/to/App.app [slug]}"
SLUG="${2:-manual}"
APP_ID="std.skyhua.MoonlightMac2"
DEST="/Applications/MoonlightEnhanced.app"
BIN="Contents/MacOS/MoonlightEnhanced"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$REPO/build-input-review/$SLUG-install-result.json"

if [[ ! -f "$SRC/$BIN" ]]; then echo "error: staged app has no binary at $SRC/$BIN" >&2; exit 1; fi
codesign --verify --deep --strict --verbose=2 "$SRC" 2>&1 | tail -1

SRC_HASH=$(shasum -a 256 "$SRC/$BIN" | cut -d' ' -f1)
PREV_HASH=""; TRASH=""
if pgrep -x MoonlightEnhanced >/dev/null; then
  echo "error: an instance is running; refusing to interrupt it. Staged app kept at $SRC" >&2
  exit 2
fi
if [[ -d "$DEST" ]]; then
  PREV_HASH=$(shasum -a 256 "$DEST/$BIN" | cut -d' ' -f1)
  TRASH="$HOME/.Trash/.MoonlightEnhanced-before-$SLUG-$(uuidgen | tr -d '-').app"
  mv "$DEST" "$TRASH"
fi
mv "$SRC" "$DEST"
INSTALL_HASH=$(shasum -a 256 "$DEST/$BIN" | cut -d' ' -f1)
[[ "$INSTALL_HASH" == "$SRC_HASH" ]] || { echo "error: installed hash differs" >&2; exit 3; }
codesign --verify --strict --verbose=2 "$DEST" >/dev/null 2>&1 || codesign --verify --deep --strict --verbose=2 "$DEST" >/dev/null 2>&1
open "$DEST"
cat > "$STAMP" <<JSON
{
  "sha256": "$INSTALL_HASH",
  "previousSha256": "$PREV_HASH",
  "trash": "$TRASH",
  "signatureVerified": true,
  "launched": true
}
JSON
echo "installed $INSTALL_HASH (was $PREV_HASH); record $STAMP"
