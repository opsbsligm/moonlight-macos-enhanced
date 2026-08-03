#!/bin/sh
# Generates BUILD_NUMBER from git history for CFBundleVersion.
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

# ALWAYS write to DERIVED_FILE_DIR. If not set, derive a reasonable default
# so this script works in manual invocation without polluting the working tree.
OUT_DIR="${DERIVED_FILE_DIR:-${PROJECT_DIR:-$(pwd)}/build/generated}"
mkdir -p "$OUT_DIR" 2>/dev/null
echo "BUILD_NUMBER = $bundleVersion" > "$OUT_DIR/GeneratedBuildNumber.xcconfig"
echo "[build-number] BUILD_NUMBER=$bundleVersion -> $OUT_DIR/GeneratedBuildNumber.xcconfig"
