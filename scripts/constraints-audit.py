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
  * the x86_64 job asked for a macos-26-intel runner that GitHub does not
    publish, so it could never start.
  * the workflow declared no permissions and no concurrency group, so every job
    inherited whatever default write scope the repository settings allow and
    each push queued a second full macOS matrix.
  * CI unzipped the framework archive with its own inline curl step, so the shared
    preparation script never ran on a runner and both Packages/OpenSSL.xcframework
    and the libs/openssl header symlink were absent: every job failed before the
    compiler could report anything.
  * the vendored OpenSSL bundle sat one directory too deep while Package.swift
    named the outer shell, which Xcode only tolerated by finding the framework
    inside it.
  * the local network probe and its defaults keys were defined after their only
    call sites, which the local toolchain happened to accept and a stricter one
    does not.
  * the key-equivalent gate sent DOWN and UP back to back for every key it did
    not consume and then swallowed the event, so no key could be held and two
    keys could never overlap. That is the reported "W and Space collide" defect.
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

# Workflow policies that have to be visible before the first job, checked on the
# text so this audit keeps running on a runner without PyYAML installed.
head = workflow.split("\njobs:")[0]
check(re.search(r"^permissions:\n  contents: read$", head, re.M) is not None,
      "CI defaults every job to read-only repository contents")
check(re.search(r"^concurrency:$", head, re.M) is not None,
      "CI limits each ref to one live run through a concurrency group")

intel_labels = sorted(set(re.findall(
    r"^\s*(?:runner|runs-on):\s*(macos-[0-9]+(?:-intel)?)\s*$", workflow, re.M)))
check(not intel_labels,
      "every macOS runner label names an arm64 image"
      if not intel_labels else
      "macOS runner labels that do not name an arm64 image: %s" % intel_labels)


# Dependency preparation has to go through one entry point. The build job used to
# unzip the archive itself, which silently skipped the rest of the script: a
# runner then had no Packages/OpenSSL.xcframework for the Swift package and no
# libs/openssl symlink for moonlight-common, so both architecture jobs died with
# errors that named neither missing input.
check("./scripts/download-frameworks.sh" in workflow,
      "CI prepares vendored dependencies through the shared script")
# The publish step has to stay behind the gate. Without it a mistyped tag is
# published, withdrawn and re-tagged, and every install in between keeps a wrong
# version string.
release_job = workflow.split("\n  release:")[-1] if "\n  release:" in workflow else ""
check("scripts/release-gate.py" in release_job,
      "the release job gates the tag before publishing")
check("scripts/release-gate.py --self-test" in workflow,
      "the release tag rules are exercised on every change")

check("scripts/video-enhancement-tests.py" in workflow,
      "CI measures the video enhancement paths instead of trusting object creation")

check("xcframeworks.zip" not in workflow,
      "CI does not duplicate the dependency download inline")

manifest = open(os.path.join(root, "Packages/OpenSSL-Package", "Package.swift"),
                encoding="utf-8").read()
check(re.search(r'path:\s*"\.\./OpenSSL\.xcframework"', manifest) is not None,
      "the OpenSSL binary target resolves to Packages/OpenSSL.xcframework")

fetch = open(os.path.join(root, "scripts/download-frameworks.sh"),
             encoding="utf-8").read()
# Two separate risks: the rule can exist and never be applied, or be applied and
# be wrong. Each half gets its own assertion so each half can fail on its own.
check('flatten_if_nested "$OPENSSL_DIR"' in fetch
      and re.search(r'\[\[ -f "\$\{OPENSSL_DIR\}/Info\.plist" \]\]', fetch) is not None,
      "the dependency script flattens and then verifies the bundle the manifest names")
layout = subprocess.run(
    [os.path.join(root, "scripts/download-frameworks.sh"), "--self-test"],
    capture_output=True, text=True, cwd=root)
check(layout.returncode == 0,
      "the layout rule accepts a valid bundle, flattens a nested one and rejects a shell"
      if layout.returncode == 0 else
      "dependency layout self-test failed:\n%s"
      % ((layout.stdout + layout.stderr).strip()[-700:])
      )

delegate = open(os.path.join(root, "Limelight/macOS/AppDelegateForAppKit.m"),
                encoding="utf-8").read()

def first_line_of(needle):
    return delegate.index(needle) if needle in delegate else -1

check(0 <= first_line_of(
          "static void TriggerLocalNetworkPermissionPromptWithDiscoveryProbe(void)")
      < first_line_of("@implementation AppDelegateForAppKit"),
      "the local network probe is defined ahead of the code that calls it")


# Gameplay input contract. A held key needs two separate deliveries: the DOWN
# edge from -keyDown: and the UP edge from -keyUp:. The key-equivalent gate used
# to emit both edges itself and return YES, which made every key a tap and made
# any overlap impossible. The gate now hands unconsumed keys back to AppKit, and
# HIDSupport must keep forwarding each edge without a seen-keys or timing filter,
# because every such filter ever added here dropped real gameplay input.
capture = open(os.path.join(root, "Limelight/macOS/ViewControllers",
                            "StreamViewController+MouseCapture.m"),
               encoding="utf-8").read()

def method_body(src, signature):
    start = src.index(signature)
    brace = src.index("{", start)
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[brace:i + 1]
    raise AssertionError("unbalanced braces after " + signature)

gate = method_body(capture, "- (BOOL)onKeyboardEquivalent:(NSEvent *)event")
check(not ("[self.hidSupport keyDown:event]" in gate
           and "[self.hidSupport keyUp:event]" in gate),
      "the key-equivalent gate never emits both edges for one key")
returns = re.findall(r"return\s+(YES|NO)\s*;", gate)
check(bool(returns) and returns[-1] == "NO",
      "the key-equivalent gate hands unconsumed keys back to AppKit")

check("[self.hidSupport keyDown:event]"
          in method_body(capture, "- (void)keyDown:(NSEvent *)event")
      and "[self.hidSupport keyUp:event]"
          in method_body(capture, "- (void)keyUp:(NSEvent *)event"),
      "the responder forwards the DOWN and the UP edge separately")

hid = open(os.path.join(root, "Limelight/Input/HIDSupport.m"),
           encoding="utf-8").read()
hid_down = method_body(hid, "- (void)keyDown:(NSEvent *)event")
forbidden_filters = ("NSMutableSet", "NSDate", "dispatch_after", "lastKeyCode")
check(not [f for f in forbidden_filters if f in hid_down],
      "HID keyDown forwards every edge without a seen-keys or timing filter"
      if not [f for f in forbidden_filters if f in hid_down] else
      "HID keyDown filters edges through: %s"
      % [f for f in forbidden_filters if f in hid_down])


# The gate only has power because AppKit calls it from -performKeyEquivalent:
# before normal key delivery. If it ever gets wired somewhere else, or the view
# stops forwarding to it, the gate becomes dead code and the real path is
# -keyDown: alone, which would leave this audit asserting a contract nobody
# enforces. The call sites are therefore pinned.
callers = subprocess.run(
    ["grep", "-rn", "--include=*.m", "--include=*.h", "-e", "onKeyboardEquivalent", "."],
    capture_output=True, text=True, cwd=root).stdout.splitlines()
# A message send only: declarations and log strings mention the selector too.
sites = sorted(set(l.split(":", 1)[0].lstrip("./") for l in callers
                   if re.search(r"\[[^\]]*onKeyboardEquivalent:", l)))
check(sites == ["Limelight/macOS/Views/StreamViewMac.m"],
      "the keyboard gate is reached only from the stream view's key-equivalent hook"
      if sites == ["Limelight/macOS/Views/StreamViewMac.m"] else
      "unexpected keyboard gate call sites: %s" % sites)

print("%d constraint failures" % len(failures))
sys.exit(1 if failures else 0)
