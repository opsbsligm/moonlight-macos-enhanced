#!/usr/bin/env bash
# Mirror scripts/apple_toolchain.py: clang and SDK must come from the same vendor,
# so the pair is taken from one toolchain rather than mixed across two.
#
# This is the reproduction the appendix of docs/Design/user-memory.md was produced
# with. Build products land beside the sources and are ignored by git; the suites
# this writes under ~/Library/Preferences are removed on the way out, because a
# leaked usermem.* plist would otherwise be read as preference state by the next run.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLANG="${CLANG:-$(xcrun --find clang 2>/dev/null)}"
SDK="${SDK:-$(xcrun --sdk macosx --show-sdk-path 2>/dev/null)}"
if [ ! -x "$CLANG" ] || [ ! -d "$SDK" ]; then
  CLANG=/Library/Developer/CommandLineTools/usr/bin/clang
  SDK=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk
fi
echo "clang: $CLANG"
echo "sdk:   $SDK"
NAME="$1"
"$CLANG" -fobjc-arc -Wall -Wextra -Werror=incompatible-pointer-types \
  -isysroot "$SDK" -framework Foundation \
  -o "$HERE/$NAME.bin" "$HERE/$NAME.m" || exit 1
"$HERE/$NAME.bin"
RC=$?
rm -f "$HOME/Library/Preferences/usermem."*.plist 2>/dev/null
exit $RC
