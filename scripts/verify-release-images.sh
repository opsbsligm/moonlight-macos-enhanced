#!/usr/bin/env bash
set -euo pipefail

# One command answers "are the images about to be published the images that were
# built", and both the rehearsal in the aggregate job and the release job run
# exactly this line. Writing it twice is how a release gets published through a
# check nobody exercised: the release job only runs on a tag, so the second copy
# would have gone months without running once, and a typo in it would have been
# discovered on the one day it mattered.
SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"

CHECKSUM_DIR="${1:-checksums}"
IMAGES_DIR="${2:-dist}"

if [[ ! -d "$CHECKSUM_DIR" ]]; then
  echo "error: no checksum directory at $CHECKSUM_DIR, so nothing could be verified" >&2
  exit 1
fi
if [[ ! -d "$IMAGES_DIR" ]]; then
  echo "error: no image directory at $IMAGES_DIR, so there is nothing to verify against" >&2
  exit 1
fi

shopt -s nullglob
sidecars=("$CHECKSUM_DIR"/*.sha256)
if (( ${#sidecars[@]} == 0 )); then
  echo "error: $CHECKSUM_DIR holds no .sha256 file; a release with no checksums is unverifiable" >&2
  exit 1
fi

# The two directories belong to whoever called this, so they are made absolute
# before the script moves to its own project root to find the audit.
CHECKSUM_DIR="$(cd "$CHECKSUM_DIR" && pwd)"
IMAGES_DIR="$(cd "$IMAGES_DIR" && pwd)"

cp "${sidecars[@]}" "$IMAGES_DIR"/
cd "$PROJECT_DIR"
python3 scripts/dmg-audit.py --verify-checksums "$IMAGES_DIR"/*.sha256 --search "$IMAGES_DIR"
