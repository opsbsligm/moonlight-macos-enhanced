#!/usr/bin/env bash
# Local acceptance deploy: verify signature, stash the old app in Trash, swap
# with rollback on installation failure, re-verify the bytes and record hashes. Refuses to
# interrupt a running instance. Usage: scripts/deploy-local-app.sh <staged.app> [slug]
set -euo pipefail
SRC="${1:?usage: deploy-local-app.sh /path/to/App.app [slug]}"
SLUG="${2:-manual}"
APP_ID="std.skyhua.MoonlightMac2"
DEST="/Applications/MoonlightEnhanced.app"
BIN="Contents/MacOS/MoonlightEnhanced"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$REPO/build-input-review/$SLUG-install-result.json"
mkdir -p "$(dirname "$STAMP")"

if [[ ! -f "$SRC/$BIN" ]]; then echo "error: staged app has no binary at $SRC/$BIN" >&2; exit 1; fi
codesign --verify --deep --strict --verbose=2 "$SRC" 2>&1 | tail -1

SRC_HASH=$(shasum -a 256 "$SRC/$BIN" | cut -d' ' -f1)
PREV_HASH=""; TRASH=""
if pgrep -x MoonlightEnhanced >/dev/null; then
  echo "error: an instance is running; refusing to interrupt it. Staged app kept at $SRC" >&2
  exit 2
fi
# Keep both versions recoverable if the move, verification or report fails.
# Do not roll back after launching: that would move a running app bundle.
rollback() {
  local result=$?
  trap - EXIT
  if [[ "$result" -ne 0 && -n "$TRASH" && -d "$TRASH" ]]; then
    if [[ -d "$DEST" ]]; then
      if [[ ! -e "$SRC" ]]; then
        mv "$DEST" "$SRC" || return "$result"
      else
        echo "error: cannot restore old app while destination and staging both exist; old app: $TRASH" >&2
        return "$result"
      fi
    fi
    mv "$TRASH" "$DEST" || return "$result"
    echo "restored previous app; staged app kept at $SRC" >&2
  fi
  return "$result"
}
trap rollback EXIT
if [[ -d "$DEST" ]]; then
  PREV_HASH=$(shasum -a 256 "$DEST/$BIN" | cut -d' ' -f1)
  TRASH="$HOME/.Trash/.MoonlightEnhanced-before-$SLUG-$(uuidgen | tr -d '-').app"
  mv "$DEST" "$TRASH"
fi
mv "$SRC" "$DEST"
INSTALL_HASH=$(shasum -a 256 "$DEST/$BIN" | cut -d' ' -f1)
[[ "$INSTALL_HASH" == "$SRC_HASH" ]] || { echo "error: installed hash differs" >&2; exit 3; }
codesign --verify --strict --verbose=2 "$DEST" >/dev/null 2>&1 || codesign --verify --deep --strict --verbose=2 "$DEST" >/dev/null 2>&1
write_report() {
python3 - "$STAMP" "$INSTALL_HASH" "$PREV_HASH" "$TRASH" "$1" <<'PY'
import json, os, sys, tempfile
path, installed, previous, trash, launched = sys.argv[1:]
report = dict(sha256=installed, previousSha256=previous, trash=trash,
              signatureVerified=True, launched=launched == 'true')
fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.install-')
try:
    with os.fdopen(fd, 'w') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
}
write_report false
trap - EXIT
open "$DEST"
# Launch requested successfully; this is not proof of runtime/UI acceptance.
write_report true
echo "installed $INSTALL_HASH (was $PREV_HASH); record $STAMP"
