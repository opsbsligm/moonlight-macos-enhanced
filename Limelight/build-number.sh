#!/bin/sh
# Generates BUILD_NUMBER (and the commit identity) from git for CFBundleVersion
# and the MLGitCommit Info.plist key.
#
# Invocation contexts:
#   - Xcode scheme PreAction (sets SRCROOT/PROJECT_DIR/DERIVED_FILE_DIR)
#   - CI pipeline (called explicitly before xcodebuild)
#
# SINGLE SOURCE OF TRUTH: BUILD_NUMBER = git rev-list --count HEAD.
# This value is written to GeneratedBuildNumber.xcconfig in DERIVED_FILE_DIR.
# Version.xcconfig holds the last-known-good baseline (manually updated on
# release tags) but is NEVER overwritten by this script — this prevents
# dirty working trees and ensures git checkout --clean is reliable.
#
# The commit identity follows the same two channels as BUILD_NUMBER, because the
# two have the same failure mode: a build that announces a number without saying
# which source produced it cannot pin an acceptance claim to a binary.
#
# Note: xcodebuild invoked from the command line does NOT run scheme
# PreActions, so CI must call this script explicitly (see .gitlab-ci.yml).

cd "$SRCROOT" 2>/dev/null || cd "$(dirname "$0")/.."

# Resolve git robustly. `sh /etc/profile; which git` is fragile under CI
# restricted shells; prefer command -v / xcrun.
git=""
if command -v git >/dev/null 2>&1; then
    git="$(command -v git)"
elif xcrun --find git >/dev/null 2>&1; then
    git="$(xcrun --find git)"
fi

if [ -z "$git" ]; then
    # No git available — use Version.xcconfig baseline (keeps its default).
    exit 0
fi

bundleVersion=$("$git" rev-list --count HEAD 2>/dev/null)
if [ -z "$bundleVersion" ]; then
    # Not a git repo or no commits — keep existing default.
    exit 0
fi

# The count is only the truth when the history is complete. A shallow clone
# reports the size of the shallow window instead, so a release prepared in one
# would carry a build number far below the one CI stamps on the same commit.
# Observed on this tree: 71 locally against 1407 from CI, on the same commit.
# --print is the channel CI and the release tooling use, so it refuses rather
# than hand them an identity that is quietly wrong.
if [ "${1:-}" = "--print" ] && \
   [ "$("$git" rev-parse --is-shallow-repository 2>/dev/null)" = "true" ]; then
    echo "error: $PWD is a shallow clone, so rev-list --count HEAD reports $bundleVersion instead of the real total; run: git fetch --unshallow" >&2
    exit 1
fi

# --print-sha mode: emit the full commit sha on stdout and write nothing. A shallow
# clone still resolves HEAD correctly (unlike rev-list --count), so this channel
# needs no shallow guard; anunreadable HEAD prints nothing, and callers must treat
# the absence as "no identity" rather than inventing one.
if [ "${1:-}" = "--print-sha" ]; then
    sha="$("$git" rev-parse HEAD 2>/dev/null)"
    case "$sha" in
        *[!0-9a-f]*|"") exit 0 ;;
    esac
    [ "${#sha}" -eq 40 ] && echo "$sha"
    exit 0
fi

# --print mode: emit the resolved number on stdout and write nothing. CI uses
# this to inject BUILD_NUMBER on the xcodebuild command line, the only channel
# proven to take effect for command-line builds.
if [ "${1:-}" = "--print" ]; then
    echo "$bundleVersion"
    exit 0
fi

# ALWAYS write to DERIVED_FILE_DIR. If not set, derive a reasonable default
# so this script works in manual invocation without polluting the working tree.
OUT_DIR="${DERIVED_FILE_DIR:-${PROJECT_DIR:-$(pwd)}/build/generated}"
mkdir -p "$OUT_DIR" 2>/dev/null
echo "BUILD_NUMBER = $bundleVersion" > "$OUT_DIR/GeneratedBuildNumber.xcconfig"
commit="$("$git" rev-parse HEAD 2>/dev/null)"
case "$commit" in
    *[!0-9a-f]*) commit="" ;;
esac
if [ "${#commit}" -eq 40 ]; then
    echo "ML_GIT_SHA = $commit" >> "$OUT_DIR/GeneratedBuildNumber.xcconfig"
fi
echo "[build-number] BUILD_NUMBER=$bundleVersion -> $OUT_DIR/GeneratedBuildNumber.xcconfig"
