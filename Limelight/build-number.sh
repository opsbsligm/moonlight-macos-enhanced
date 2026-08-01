#!/bin/sh
# Generates BUILD_NUMBER from git history for CFBundleVersion.
#
# Invocation contexts:
#   - Xcode scheme PreAction (sets SRCROOT/PROJECT_DIR/DERIVED_FILE_DIR)
#   - CI pipeline (called explicitly before xcodebuild)
#
# We prefer writing to DERIVED_FILE_DIR to avoid polluting the tracked
# Version.xcconfig. When DERIVED_FILE_DIR is unavailable (manual invocation),
# we fall back to overwriting Version.xcconfig, matching historical behavior.
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
    # No git available — leave Version.xcconfig untouched (keeps its default).
    exit 0
fi

bundleVersion=$("$git" rev-list --count HEAD 2>/dev/null)
if [ -z "$bundleVersion" ]; then
    # Not a git repo or no commits — keep existing default.
    exit 0
fi

if [ -n "$DERIVED_FILE_DIR" ] && [ -d "$DERIVED_FILE_DIR" ]; then
    # Preferred: write to derived data, no working-tree pollution.
    echo "BUILD_NUMBER = $bundleVersion" > "$DERIVED_FILE_DIR/GeneratedBuildNumber.xcconfig"
elif [ -n "$PROJECT_DIR" ]; then
    # Fallback: historical behavior (overwrites tracked file).
    # CI should clean this with `git checkout -- Limelight/Version.xcconfig`
    # after build, or use DERIVED_FILE_DIR by exporting it.
    echo "BUILD_NUMBER = $bundleVersion" > "$PROJECT_DIR/Limelight/Version.xcconfig"
fi
