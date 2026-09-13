#!/usr/bin/env python3
"""Assert the project constraints that regressions have actually violated.

Each check below corresponds to a defect that shipped at some point:
  * /usr/sbin/tccutil was used for the local network repair, so the reset never
    ran because the binary lives in /usr/bin.
  * tccutil "dump" and "list" were treated as query commands; tccutil only
    implements "reset SERVICE [BUNDLE_ID]".
  * spctl --assess was reported as a Gatekeeper block, which is always false for
    an Apple Development signature and produced a misleading dialog.
  * the AWDL helper assertion in CI pinned the pre-rename bundle identifier and
    broke both architecture jobs.
"""
import plistlib, re, subprocess, sys, os, xml.etree.ElementTree as ET

root = sys.argv[1] if len(sys.argv) > 1 else "."
failures = []

def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)

info_path = os.path.join(root, "Limelight/macOS/Supporting Files/Info.plist")
with open(info_path, "rb") as handle:
    info = plistlib.load(handle)

# Info.plist carries the build setting variable, so the truth lives in the
# project file.
project = open(os.path.join(root, "Moonlight.xcodeproj", "project.pbxproj"),
               encoding="utf-8").read()
bundle_ids = set(re.findall(r"PRODUCT_BUNDLE_IDENTIFIER = ([^;]+);", project))
check(bundle_ids == {"std.skyhua.MoonlightMac2"},
      "product bundle identifier is %s" % (sorted(bundle_ids) or "unset"))
check("NSLocalNetworkUsageDescription" in info,
      "Info.plist declares NSLocalNetworkUsageDescription")
bonjour = info.get("NSBonjourServices") or []
check("_nvstream._tcp." in bonjour or "_nvstream._tcp" in bonjour,
      "Info.plist advertises the _nvstream._tcp Bonjour service")

with open(os.path.join(root, "Moonlight.entitlements"), "rb") as handle:
    entitlements = plistlib.load(handle)

check(entitlements.get("com.apple.security.network.client") is True,
      "entitlements grant outbound network client access")
check(entitlements.get("com.apple.security.network.server") is True,
      "entitlements grant listening server access")
check(entitlements.get("com.apple.security.app-sandbox") is not True,
      "App Sandbox stays off (helper launchd job and plain BSD sockets)")

FORBIDDEN = ("/usr/sbin/tccutil", "spctl --assess", "tccutil dump", "tccutil list")
hits = []
listing = subprocess.run(
    ["grep", "-rn", "--include=*.m", "--include=*.h", "--include=*.swift",
     "--include=*.sh", "--include=*.yml", "."]
    + sum([["-e", needle] for needle in FORBIDDEN], []),
    capture_output=True, text=True).stdout
for line in listing.splitlines():
    text = line.split(":", 2)[-1].strip()
    # Prose that explains why a command must not be used is encouraged; only an
    # actual invocation is a violation.
    if text.startswith(("//", "#", "*", "--")):
        continue
    hits.append(line)
check(not hits,
      "no forbidden tool paths or subcommands"
      if not hits else "forbidden invocations remain:\n%s" % "\n".join(hits))

waits = subprocess.run(
    ["grep", "-rn", "--include=*.m", "--include=*.swift",
     "-e", "waitsForConnectivity = YES", "-e", "waitsForConnectivity = true", "."],
    capture_output=True, text=True).stdout.strip()
check(not waits,
      "waitsForConnectivity is never enabled (would stall LAN discovery)"
      if not waits else "waitsForConnectivity enabled:\n%s" % waits)

workflow = open(os.path.join(root, ".github/workflows/build.yml"),
                encoding="utf-8").read()
check("std.skyhua.MoonlightMac.AwdlPrivilegedHelper" not in workflow,
      "CI derives the helper path instead of pinning the old bundle identifier")

print("%d constraint failures" % len(failures))
sys.exit(1 if failures else 0)
