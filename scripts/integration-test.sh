#!/bin/zsh
set -euo pipefail

# Integration test: verify app bundle structure, code signature, and launch
# Usage: scripts/integration-test.sh [path-to-app]

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"

APP_PATH="${1:-${PROJECT_DIR}/build/xcode/derivedData/Build/Products/Release/Moonlight.app}"
PASS=0
FAIL=0

assert_exists() {
  if [[ -e "$1" ]]; then
    echo "  PASS: $2"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $2 (not found: $1)"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  if /usr/libexec/PlistBuddy -c "Print :$2" "$1" >/dev/null 2>&1; then
    echo "  PASS: $3"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $3 (missing key: $2)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Integration Test: Moonlight.app ==="
echo ""

if [[ ! -d "$APP_PATH" ]]; then
  echo "FAIL: App not found at $APP_PATH"
  exit 1
fi

echo "1. Bundle structure"
assert_exists "$APP_PATH/Contents/MacOS/Moonlight" "Executable exists"
assert_exists "$APP_PATH/Contents/Info.plist" "Info.plist exists"
assert_exists "$APP_PATH/Contents/Resources" "Resources directory exists"
assert_exists "$APP_PATH/Contents/Frameworks" "Frameworks directory exists"
assert_exists "$APP_PATH/Contents/_CodeSignature" "Code signature exists"

echo ""
echo "2. Info.plist keys"
assert_contains "$APP_PATH/Contents/Info.plist" "CFBundleIdentifier" "Bundle identifier"
assert_contains "$APP_PATH/Contents/Info.plist" "CFBundleShortVersionString" "Version string"
assert_contains "$APP_PATH/Contents/Info.plist" "CFBundleExecutable" "Executable name"
assert_contains "$APP_PATH/Contents/Info.plist" "LSMinimumSystemVersion" "Minimum system version"

echo ""
echo "3. Code signature"
if codesign -v "$APP_PATH" 2>/dev/null; then
  echo "  PASS: Code signature valid"
  PASS=$((PASS + 1))
else
  echo "  FAIL: Code signature invalid"
  FAIL=$((FAIL + 1))
fi

SIGN_IDENTITY=$(codesign -dvv "$APP_PATH" 2>&1 | grep "Authority\|Identifier" | head -2)
echo "  Info: $SIGN_IDENTITY"

echo ""
echo "4. Executable architecture"
ARCH=$(file "$APP_PATH/Contents/MacOS/Moonlight" 2>/dev/null)
echo "  Info: $ARCH"
if echo "$ARCH" | grep -q "Mach-O"; then
  echo "  PASS: Valid Mach-O binary"
  PASS=$((PASS + 1))
else
  echo "  FAIL: Not a valid Mach-O binary"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "5. Launch test (5 second smoke test)"
LAUNCH_PID=$(open -W -n "$APP_PATH" &; echo $!)
sleep 5

if pgrep -f "Moonlight.app/Contents/MacOS/Moonlight" >/dev/null 2>&1; then
  echo "  PASS: App launched and running"
  PASS=$((PASS + 1))
  pkill -f "Moonlight.app/Contents/MacOS/Moonlight" 2>/dev/null || true
  sleep 1
else
  echo "  FAIL: App did not stay running"
  FAIL=$((FAIL + 1))
fi

# Check for crash logs
CRASH_LOGS=$(ls ~/Library/Logs/DiagnosticReports/Moonlight* 2>/dev/null | wc -l)
if [[ "$CRASH_LOGS" -eq 0 ]]; then
  echo "  PASS: No crash logs found"
  PASS=$((PASS + 1))
else
  echo "  WARN: Crash logs found ($CRASH_LOGS)"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
