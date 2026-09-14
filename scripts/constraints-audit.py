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
  * both macOS jobs asked for macos-26-arm64, which is an image name and not a
    label, so both sat queued with no failure to read. The earlier check accepted
    it because it only looked for the -intel suffix.
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
  * the dependency script began with a zsh shebang, so the ubuntu audit runner
    could not start it and reported the script itself as missing.
  * settings was a second NSWindow, which is how the app acquired two competing
    window layers, and the only thing keeping the embedded page embedded was a
    reviewer remembering that it used to be a window.
  * a branch that consumed a key still let its release through, because AppKit
    only asks the key-equivalent question on keyDown, so the host saw a key come
    up that it never saw go down.
  * keys the settings page did not use walked the responder chain back to the
    stream view and were forwarded, so typing in settings moved the character on
    the host.
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

# GitHub names a hosted image and its label differently, and only the label works
# in runs-on. For macOS 26 the arm64 label is macos-26 while macos-26-arm64 is the
# image name in the docs; naming the image matches no runner, and the job then sits
# queued with no failure and no log. The allowlist is the published label set, so
# an invented spelling fails here instead of stalling a pipeline.
MACOS_ARM64_LABELS = {"macos-latest", "macos-26", "macos-26-xlarge",
                      "macos-15", "macos-15-xlarge"}
MACOS_INTEL_LABELS = {"macos-latest-large", "macos-26-large", "macos-26-intel",
                      "macos-15-large", "macos-15-intel"}
UBUNTU_LABELS = {"ubuntu-latest", "ubuntu-24.04", "ubuntu-22.04"}

macos_labels = sorted(set(re.findall(
    r"^\s*(?:runner|runs-on):\s*(macos-[A-Za-z0-9.-]+)\s*$", workflow, re.M)))
ubuntu_labels = sorted(set(re.findall(
    r"^\s*runs-on:\s*(ubuntu-[A-Za-z0-9.-]+)\s*$", workflow, re.M)))
unknown = [label for label in macos_labels + ubuntu_labels
           if label not in MACOS_ARM64_LABELS | MACOS_INTEL_LABELS | UBUNTU_LABELS]
check(not unknown,
      "every runner label is one GitHub publishes"
      if not unknown else
      "runner labels GitHub does not publish: %s" % unknown)
off_arm64 = [label for label in macos_labels if label not in MACOS_ARM64_LABELS]
check(not off_arm64,
      "every macOS job builds on the arm64 image, which cross-links both slices"
      if not off_arm64 else
      "macOS jobs that depend on an Intel image: %s" % off_arm64)


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

check("scripts/liquid-glass-audit.py" in workflow,
      "CI checks the glass surface instead of relying on review memory")

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


# Settings used to be its own NSWindow, rebuilt on every invocation. It is now a
# child view controller inside the main window, and nothing in the code says so:
# the only protection was a reviewer remembering the old design. The checks below
# pin what "inside the same window" means in code, scoped to the settings path.
# The permissions dialog in the same file is a real window on purpose, so the
# window-construction ban is scoped to the presenter and the bridge, never the
# file, or the audit would either miss the settings page or fail on the dialog.
WINDOW_CONSTRUCTION = ("NSWindow(", "NSPanel(", "NSWindowController(", "initWithContentRect")

def swift_block(text, declaration):
    """Return the body of a Swift declaration, braces counted."""
    start = text.find(declaration)
    if start < 0:
        raise AssertionError("no Swift declaration containing " + repr(declaration))
    opening = text.index("{", start)
    depth, index = 0, opening
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening:index + 1]
        index += 1
    raise AssertionError("unbalanced braces after " + declaration)


presenter_path = "Limelight/macOS/ViewControllers/LiquidGlass/SettingsOverlayPresenter.swift"
settings_view_path = "Limelight/macOS/ViewControllers/LiquidGlass/LiquidGlassSettingsView.swift"
bridge_path = "Limelight/macOS/ViewControllers/SettingsHostingController.swift"
presenter_src = open(os.path.join(root, presenter_path), encoding="utf-8").read()
settings_view_src = open(os.path.join(root, settings_view_path), encoding="utf-8").read()
bridge_src = open(os.path.join(root, bridge_path), encoding="utf-8").read()
bridge_body = swift_block(bridge_src, "@objc class SettingsWindowObjCBridge")

for rel, source in ((presenter_path, presenter_src), (settings_view_path, settings_view_src),
                    ("SettingsWindowObjCBridge", bridge_body)):
    found = [token for token in WINDOW_CONSTRUCTION if token in source]
    check(not found, "the settings page never builds a window of its own (%s)" % rel
          if not found else "the settings page builds a window in %s: %s" % (rel, found))

# Attaching is what makes it embedded; restoring is what makes leaving invisible.
check("parent.addChild(hosting)" in presenter_src
      and "content.addSubview(hosting.view)" in presenter_src,
      "the settings page is attached to the window it was asked to present in")
check("window.toolbar?.isVisible = savedToolbarVisible" in presenter_src
      and "window.title = savedTitle" in presenter_src,
      "leaving the settings page restores the toolbar and the title it replaced")
check("TabBarConfig.animationDuration" in presenter_src
      and not re.search(r"(?i)duration\s*=\s*0?\.\d", presenter_src),
      "the settings transition takes its duration from TabBarConfig instead of a literal")

# The page swallows Command+W so the window menu cannot close the window under
# it. A local monitor that outlives the page would swallow it everywhere.
show_body = swift_block(presenter_src, "private func show(in content: NSView)")
dismiss_body = swift_block(presenter_src, "private func dismiss()")
check("installCommandWFilter()" in show_body and "installCloseObserver()" in show_body,
      "presenting the settings page installs both of its exit paths")
check("NSEvent.removeMonitor(commandWMonitor)" in dismiss_body
      and "NotificationCenter.default.removeObserver(closeObserver)" in dismiss_body
      and "hosting.view.removeFromSuperview()" in dismiss_body
      and "hosting.removeFromParent()" in dismiss_body,
      "leaving the settings page removes its key monitor, observer and view")

# Two entry points would mean two lifetimes. The Objective-C side may only reach
# the page through the bridge, and the bridge may only forward to the presenter.
sends = subprocess.run(
    ["grep", "-rn", "--include=*.m", "--include=*.h", "-e", "presentSettingsInWindow", "."],
    capture_output=True, text=True, cwd=root).stdout.splitlines()
send_sites = sorted(set(l.split(":", 1)[0].lstrip("./") for l in sends
                        if re.search(r"\[[^\]]*presentSettingsInWindow:", l)))
check(send_sites == ["Limelight/macOS/AppDelegateForAppKit.m"],
      "settings is presented from one Objective-C site only"
      if send_sites == ["Limelight/macOS/AppDelegateForAppKit.m"] else
      "unexpected settings presentation sites: %s" % send_sites)
check(bridge_body.count("SettingsOverlayPresenter.") == 3
      and "func presentSettings(inWindow" in bridge_body
      and "SettingsOverlayPresenter.present(in: window, hostId: hostId)" in bridge_body,
      "the settings bridge forwards all three calls to the presenter and adds nothing")


# AppKit asks the key-equivalent question on keyDown only. A branch that consumes
# a key therefore has to say so, or the matching keyUp still reaches -keyUp: and
# the host is told a key was released that it never saw pressed. The pairing is
# invisible in review because the two halves live in different methods.
capture_all = open(os.path.join(root, "Limelight/macOS/ViewControllers/StreamViewController+MouseCapture.m"),
                   encoding="utf-8").read()
gate_source = capture_all[capture_all.index("- (BOOL)onKeyboardEquivalent:"):]
gate_source = gate_source[:gate_source.index("\n@end")]
gate_lines = gate_source.split("\n")
bare = [i for i, line in enumerate(gate_lines) if line.strip() == "return YES;"]
reasons = [any("MLIsKeyboardKeyEvent(event)" in l or "swallowed key kVK=" in l
               for l in gate_lines[max(0, i - 12):i][::-1][:8]) for i in bare]
check(len(bare) == 2 and all(reasons),
      "the only unpaired swallows left are the two documented paths"
      if len(bare) == 2 and all(reasons) else
      "unpaired keyDown paths in the gate: %d, reasons matched: %s" % (len(bare), reasons))
paired = gate_source.count("return [self consumeKeyDownEvent:event];")
check(paired >= 8,
      "every shortcut branch that consumes a key records the debt"
      if paired >= 8 else "only %d consuming branches record the debt" % paired)

monitor_start = capture_all.index("self.localKeyDownMonitor = [NSEvent addLocalMonitorForEventsMatchingMask")
monitor_body = capture_all[monitor_start:capture_all.index("    }];", monitor_start)]
check("return nil;" not in monitor_body
      and monitor_body.count("consumeMonitoredKeyDownEvent:") == 3,
      "the key monitor suppresses only by recording the debt"
      if "return nil;" not in monitor_body and monitor_body.count("consumeMonitoredKeyDownEvent:") == 3 else
      "bare suppressions in the monitor: %d, recorded: %d"
      % (monitor_body.count("return nil;"), monitor_body.count("consumeMonitoredKeyDownEvent:")))

down_body = method_body(capture_all, "- (void)keyDown:(NSEvent *)event")
check("isSettingsPresentedInWindow" in down_body
      and "noteKeyboardKeyDownSuppressedForEvent" in down_body,
      "keys the settings page owns are never forwarded to the host")

hid_all = open(os.path.join(root, "Limelight/Input/HIDSupport.m"), encoding="utf-8").read()
hid_up = method_body(hid_all, "- (void)keyUp:(NSEvent *)event")
hid_down = method_body(hid_all, "- (void)keyDown:(NSEvent *)event")
check("keyboardSuppressedKeyDownKeyCodes containsObject:" in hid_up
      and hid_up.index("keyboardSuppressedKeyDownKeyCodes containsObject:")
          < hid_up.index("LiSendKeyboardEventCtx"),
      "a release whose press was consumed never reaches the host")
check("keyboardSuppressedKeyDownKeyCodes removeObject:" in hid_down,
      "a forwarded press clears any stale record for that key")
check("keyboardSuppressedKeyDownKeyCodes removeAllObjects"
      in method_body(hid_all, "- (void)tearDownKeyboardStateForSessionEnd:(const char *)reason"),
      "session teardown drops every outstanding consumed-key record")
check("noteKeyboardKeyDownSuppressedForEvent"
      in open(os.path.join(root, "Limelight/Input/HIDSupport.h"), encoding="utf-8").read(),
      "the consumed-key contract is part of the public HID interface")


print("%d constraint failures" % len(failures))
sys.exit(1 if failures else 0)
