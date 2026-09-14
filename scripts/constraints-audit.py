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
  * releasing the mouse switched input forwarding off while a key was still held,
    and keyUp: is gated on that flag, so the host never saw the release and kept
    the movement key pressed for the rest of the session.
  * a shortcut or translation rule bound to a bare key was matched straight from
    stored configuration, so a plain W or Space could be consumed locally and
    never reach the host, even though the settings form rejects such a binding.
  * a key the mapping table has no entry for was translated to 0 and forwarded,
    so the host received a virtual key that exists on no keyboard and held it:
    the ISO section key and the contextual-menu key were both missing rows.
  * the capability matrix asked VideoToolbox whether a feature is supported and
    showed that answer, while the same configuration reported zero interpolation
    slots and no supported scale factor at the stream's size, so the settings page
    advertised enhancements the GPU could not run.
"""
import plistlib, re, subprocess, sys, os, xml.etree.ElementTree as ET

# The audit is also the CI entry point for the assertion battery, so the battery's
# own runs have to opt out or the two would call each other forever. Flags are
# separated from the positional root because the root is a path, not an option.
flags = [a for a in sys.argv[1:] if a.startswith("--")]
positional = [a for a in sys.argv[1:] if not a.startswith("--")]
root = positional[0] if positional else "."
run_battery = "--no-battery" not in flags
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

def statements(body):
    """The body as stripped lines, so a guard is checked as code and not prose."""
    return [line.strip() for line in body.split("\n")]

def guard_exits(body, condition_prefix, action, before, exit_statement="return;"):
    """Require a guard whose condition is the test and whose block exits early.

    A plain substring search is not enough: a condition neutered with "NO &&",
    moved into a comment, or left without an exit all keep the words present
    while the behaviour is gone. This asks for the shape that executes.
    """
    lines = statements(body)
    guards = [i for i, line in enumerate(lines) if line.startswith(condition_prefix)]
    if len(guards) != 1:
        return "expected exactly one line starting with %r, found %d" % (condition_prefix, len(guards))
    block = lines[guards[0] + 1:guards[0] + 8]
    joined = "\n".join(block)
    if action not in joined:
        return "%s is missing from the guard block" % action
    if exit_statement not in block:
        return "the guard block never executes %r, so the event still reaches the host" % exit_statement
    dispatch = [i for i, line in enumerate(lines) if line.startswith(before)]
    if not dispatch:
        return "no %s call to compare against" % before
    if guards[0] > dispatch[0]:
        return "the guard sits after the dispatch, which is too late"
    return None


down_body = method_body(capture_all, "- (void)keyDown:(NSEvent *)event")
problem = guard_exits(
    down_body,
    "if ([SettingsWindowObjCBridge isSettingsPresentedInWindow:",
    "noteKeyboardKeyDownSuppressedForEvent",
    "[self.hidSupport keyDown:event]")
check(problem is None, "keys the settings page owns are never forwarded to the host"
      if problem is None else "settings guard is not effective: " + problem)

hid_all = open(os.path.join(root, "Limelight/Input/HIDSupport.m"), encoding="utf-8").read()
hid_up = method_body(hid_all, "- (void)keyUp:(NSEvent *)event")
hid_down = method_body(hid_all, "- (void)keyDown:(NSEvent *)event")
problem = guard_exits(
    hid_up,
    "if ([self.keyboardSuppressedKeyDownKeyCodes containsObject:",
    "removeObject:",
    "LiSendKeyboardEventCtx")
check(problem is None, "a release whose press was consumed never reaches the host"
      if problem is None else "the release path is not effective: " + problem)
def ordered_once(body, first_prefix, second_prefix, what):
    """Require exactly one line starting with first_prefix, ahead of second_prefix."""
    lines = statements(body)
    firsts = [i for i, line in enumerate(lines) if line.startswith(first_prefix)]
    seconds = [i for i, line in enumerate(lines) if line.startswith(second_prefix)]
    if len(firsts) != 1:
        return "expected exactly one line starting with %r, found %d" % (first_prefix, len(firsts))
    if not seconds:
        return "no line starting with %r to order %s against" % (second_prefix, what)
    if firsts[0] > seconds[0]:
        return "%s is ordered after %r, which is too late" % (what, second_prefix)
    return None


problem = ordered_once(
    hid_down,
    "[self.keyboardSuppressedKeyDownKeyCodes removeObject:",
    "LiSendKeyboardEventCtx",
    "clearing the stale consumed-key record")
check(problem is None, "a forwarded press clears any stale record for that key"
      if problem is None else "the stale-record clear is not effective: " + problem)
check("keyboardSuppressedKeyDownKeyCodes removeAllObjects"
      in method_body(hid_all, "- (void)tearDownKeyboardStateForSessionEnd:(const char *)reason"),
      "session teardown drops every outstanding consumed-key record")
check("noteKeyboardKeyDownSuppressedForEvent"
      in open(os.path.join(root, "Limelight/Input/HIDSupport.h"), encoding="utf-8").read(),
      "the consumed-key contract is part of the public HID interface")

# A press the host was told about has to be recoverable when capture ends while
# the key is still held: keyUp: stops forwarding once input is off, so an
# unreleased press leaves the host holding the key for the whole session.
hid_release = method_body(hid_all, "- (void)releaseAllHeldKeys")
hid_capture_off = method_body(capture_all,
                              "- (void)uncaptureMouseWithCode:(NSString *)code reason:(NSString *)reason")
hid_init = method_body(hid_all, "- (instancetype)init:(TemporaryHost *)host")

for problem, message in [
    (ordered_once(hid_down, "[self.keyboardForwardedKeyDownKeyCodes addObject:",
                  "LiSendKeyboardEventCtx", "recording the press"),
     "a press the host is told about is recorded before it is sent"),
    (ordered_once(hid_up, "[self.keyboardForwardedKeyDownKeyCodes removeObject:",
                  "LiSendKeyboardEventCtx", "spending the held-key record"),
     "a forwarded release spends the held-key record"),
    (ordered_once(hid_release, "[self.keyboardForwardedKeyDownKeyCodes removeAllObjects]",
                  "LiSendKeyboardEventCtx", "dropping the records"),
     "the held-key release drops its records before sending the releases"),
    (ordered_once(hid_capture_off, "[self.hidSupport releaseAllHeldKeys];",
                  "self.hidSupport.shouldSendInputEvents = NO;", "releasing held keys"),
     "capture release lets go of held keys before input forwarding is off"),
]:
    check(problem is None, message if problem is None else "%s is not effective: %s" % (message, problem))

check(guard_exits(hid_release, "if (self.keyboardHeldKeyReleaseInProgress)",
                    "self.keyboardHeldKeyReleaseInProgress = YES",
                    "LiSendKeyboardEventCtx") is None,
      "the held-key release cannot re-enter itself")
check("KEY_ACTION_UP" in hid_release,
      "the held-key release actually sends releases")
check("self.keyboardForwardedKeyDownKeyCodes = [NSMutableSet set];" in hid_init,
      "the held-key record exists before the first key can reach it")
check("- (void)releaseAllHeldKeys;" in open(os.path.join(root, "Limelight/Input/HIDSupport.h"),
                                            encoding="utf-8").read(),
      "the held-key release is part of the public HID interface")
check("[self releaseAllHeldKeys];"
      in method_body(hid_all, "- (void)tearDownKeyboardStateForSessionEnd:(const char *)reason"),
      "session teardown releases the keys the host still holds")

# The mapping table is the whole keyboard contract, and translateKeyCodeWithEvent:
# answers 0 when the table has no entry. 0 is not a Windows virtual key, so every
# unmapped press used to be forwarded as VK 0: the host held a key that exists on
# no keyboard, because a release for a code it never saw go down does not clear
# anything. Two codes were missing from the table and any code a new keyboard adds
# still hits that path, so both halves have to be pinned: the table has to answer
# for the keys a game can bind, and both edges have to refuse zero rather than
# forward it. A row that maps to zero, or a duplicated physical code that the
# dictionary build in init: silently overwrites, are the same defect in disguise.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mac_keycodes


def table_rows(source):
    """The mapping table as (mac, windows) token pairs, braces scoped."""
    region = re.search(r"static struct KeyMapping keys\[\] = \{(.*?)\n\};", source, re.S)
    if region is None:
        return None
    return re.findall(r"^\s*\{\s*([^,{}]+?)\s*,\s*([^,{}]+?)\s*\},\s*$", region.group(1), re.M)


def keycode_value(token):
    """Resolve a table token to its integer code: a kVK_ name, char literal, or number."""
    token = token.strip()
    if token in mac_keycodes.KVK_CODES:
        return mac_keycodes.KVK_CODES[token]
    if re.fullmatch(r"'.{1}'", token):
        return ord(token[1:2])
    return int(token, 0)


mapping_rows = table_rows(hid_all)
check(bool(mapping_rows), "the Mac-to-Windows key mapping table can be parsed"
      if mapping_rows else "the key mapping table in HIDSupport.m is missing or unparseable")

mapped_names = {mac.strip() for mac, _ in mapping_rows or () if mac.strip().startswith("kVK_")}
unbound = sorted(set(mac_keycodes.REQUIRED_MAPPED_KEYS) - mapped_names)
check(not unbound, "the mapping table answers for every key a game can bind"
      if not unbound else "the mapping table has no entry for: %s" % ", ".join(unbound))

try:
    physical_codes = [keycode_value(mac) for mac, _ in mapping_rows or ()]
    host_codes = [keycode_value(windows) for _, windows in mapping_rows or ()]
    unresolvable = []
except ValueError as error:
    physical_codes, host_codes = [], []
    unresolvable = [str(error)]

check(not unresolvable, "every mapping token resolves to a key code"
      if not unresolvable else "a mapping entry uses a code this audit cannot resolve: %s"
      % unresolvable[0])

# The gap has to be a decision rather than an omission. Anything not in the table
# is ignored by the guard above, which is only defensible while the list of what is
# left out says why, and a row added without editing that list makes the list a lie.
undocumented = set(mac_keycodes.KVK_CODES) - mapped_names
stale = {name for name in mac_keycodes.UNMAPPED_BY_CHOICE if name not in undocumented}
check(undocumented == set(mac_keycodes.UNMAPPED_BY_CHOICE),
      "every key the table does not answer for is documented with a reason"
      if not (undocumented - set(mac_keycodes.UNMAPPED_BY_CHOICE) or stale) else
      "undocumented key gaps: %s; reasons left stale: %s"
      % (sorted(undocumented - set(mac_keycodes.UNMAPPED_BY_CHOICE)) or "none",
         sorted(stale) or "none"))

repeated = sorted({code for code in physical_codes if physical_codes.count(code) > 1})
check(not repeated, "no physical code is mapped twice"
      if not repeated else "physical codes %s appear twice, and the dictionary build keeps "
                           "only the last row for them"
      % ", ".join("0x%02X" % code for code in repeated))

zero_rows = sorted({mac.strip() for (mac, _), code in zip(mapping_rows or (), host_codes)
                    if code == 0})
check(not zero_rows, "no mapping entry forwards VK 0"
      if not zero_rows else "%s map to 0, which is the same defect as a missing row"
      % ", ".join(zero_rows))

for edge, body in (("keyDown:", hid_down), ("keyUp:", hid_up)):
    problem = guard_exits(body, "if (translated == 0) {", "return;", "LiSendKeyboardEventCtx")
    check(problem is None, "%s refuses an unmapped key instead of forwarding VK 0" % edge
          if problem is None else "%s does not refuse an unmapped key: %s" % (edge, problem))

check("{kVK_ISO_Section, 0xE2}," in hid_all and "{kVK_ContextualMenu, 0x5D}," in hid_all,
      "the two codes measured on this Mac are in the table instead of hitting the zero path")


# A shortcut bound to a bare key deletes a gameplay key from the host: the
# responder gate answers YES, a translation rule swallows the press, and a menu
# key equivalent claims the key before the stream view sees it. Settings rejects
# such a shortcut, so the streaming path has to stop relying on that being the
# only line of defence: stored shortcuts and rules are decoded from disk.
menu_all = open(os.path.join(root, "Limelight/macOS/ViewControllers/StreamViewController+MenuUI.m"),
                encoding="utf-8").read()
shortcuts_swift = open(os.path.join(root, "Limelight/macOS/ViewControllers/SettingsShortcuts.swift"),
                       encoding="utf-8").read()
menu_gate = method_body(menu_all, "- (BOOL)event:(NSEvent *)event matchesShortcut:(StreamShortcut *)shortcut")
rule_match = method_body(capture_all,
                         "- (KeyboardTranslationRule *)keyboardTranslationRuleMatchingEvent:(NSEvent *)event")
swift_gate = method_body(shortcuts_swift,
                         "static func shortcutCanMatchKeyboardEvent(_ shortcut: StreamShortcut?) -> Bool")
menu_equivalent = method_body(shortcuts_swift,
                              "static func menuKeyEquivalent(for shortcut: StreamShortcut) -> String")

for problem, message in [
    (guard_exits(menu_gate, "if (![StreamShortcutProfile shortcutCanMatchKeyboardEvent:shortcut])",
                 "return NO;", "return event.keyCode == shortcut.keyCode", "return NO;"),
     "the responder gate refuses a shortcut that needs no modifier"),
    (guard_exits(rule_match, "if (![StreamShortcutProfile shortcutCanMatchKeyboardEvent:trigger])",
                 "continue;", "if (event.keyCode == trigger.keyCode", "continue;"),
     "a translation rule on a bare key cannot swallow a gameplay press"),
]:
    check(problem is None, message if problem is None else "%s is not effective: %s" % (message, problem))

check("modifierOnly" in swift_gate and "hasKeyCode" in swift_gate
      and ">= 1" in swift_gate and "return false" in swift_gate,
      "the bare-key predicate keeps its modifier floor")
check("shortcutCanMatchKeyboardEvent" in menu_equivalent,
      "the menu key equivalent refuses a shortcut bound to a bare key")
check(sum(source.count("shortcutCanMatchKeyboardEvent")
          for source in (menu_all, capture_all, shortcuts_swift)) >= 4,
      "every keyboard consumer shares one bare-key predicate")

# Measured on an Apple M2: VTLowLatencyFrameInterpolationConfiguration.isSupported
# is true, the configuration is created, a session starts, and the configuration
# reports zero interpolation slots, so no frame can ever be inserted. The low
# latency scaler says the same while its supported scale factors are empty at
# 1080p. A capability matrix that reads those properties advertises work the GPU
# cannot do, which is the report this project keeps getting about video features
# that appear enabled and change nothing.
derived_swift = open(os.path.join(root, "Limelight/macOS/ViewControllers/SettingsModel+DerivedValues.swift"),
                     encoding="utf-8").read()
video_pane = open(os.path.join(root, "Limelight/macOS/ViewControllers/SettingsVideoPane.swift"),
                  encoding="utf-8").read()
mfx_support = method_body(derived_swift, "static var isMetalFXSupported: Bool")
fi_support = method_body(derived_swift,
                         "static func lowLatencyFrameInterpolationAvailability() -> CapabilityAvailability")
sr_support = method_body(derived_swift,
                         "static func lowLatencySuperResolutionAvailability() -> CapabilityAvailability")
fi_toggle = method_body(video_pane, "var frameInterpolationCapabilityAvailable: Bool")

check("supportsDevice(" in mfx_support and "return true" not in mfx_support,
      "MetalFX availability asks the GPU instead of the operating system version")
check("numberOfInterpolatedFrames" in fi_support and "slots >= 1" in fi_support,
      "interpolation availability counts the slots the GPU offers")
check("__supportedScaleFactors" in sr_support and "factors.isEmpty" in sr_support,
      "super resolution availability asks for the scale factors per frame size")
check('id == "enhancement.vtLowLatencyFI"' in fi_toggle and "availability == .available" in fi_toggle,
      "the interpolation control is gated by the measured capability, not a constant")




# These are findings from `xcodebuild analyze` that were real defects, kept as
# rules rather than left to be rediscovered: a CGEvent created on every gamepad
# navigation press and never released, a CGPath helper that handed out a +1
# reference under a name that did not say so (one caller released it and the
# caller in another file leaked one per shadow refresh), and the HID manager
# outliving the object that its four run loop callbacks point into.
def method_bodies(source):
    """Every method definition with its body, for rules that live per method."""
    for match in re.finditer(r"^[-+]\s*\([^\n]*?\{", source, re.M):
        brace = source.index("{", match.start())
        depth, index = 0, brace
        while index < len(source):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        yield source[match.start():index + 1]


def compiled_sources(scan_root):
    base = os.path.join(scan_root, "Limelight")
    for directory, _, names in os.walk(base):
        for name in sorted(names):
            if name.endswith(".m"):
                path = os.path.join(directory, name)
                yield path, open(path, encoding="utf-8").read()


CREATED = re.compile(r"(\w+)\s*=\s*CG\w*(?:Create|Copy)\w*\(")
unowned = []
for source_path, text in compiled_sources(root):
    for body in method_bodies(text):
        signature = body.split("\n")[0]
        for name in set(CREATED.findall(body)):
            released = re.search(r"\w*Release\(\s*%s\s*\)" % re.escape(name), body)
            returned = re.search(r"return\s+%s\s*;" % re.escape(name), body)
            if not released and not (returned and "CF_RETURNS_RETAINED" in signature):
                unowned.append("%s: %s is created and then neither released nor "
                               "declared owned" % (os.path.relpath(source_path, root), name))
check(not unowned, "every CoreFoundation reference created here is accounted for"
      if not unowned else "; ".join(unowned[:3]))

unannotated = ["%s: %s" % (os.path.relpath(source_path, root), body.split("\n")[0].strip())
               for source_path, text in compiled_sources(root)
               for body in method_bodies(text)
               if re.match(r"^[-+]\s*\(CG(?:Mutable)?PathRef\s*\*?\)", body)
               and "CF_RETURNS_RETAINED" not in body.split("\n")[0]]
check(not unannotated, "a path handed to a caller says who owns it"
      if not unannotated else "CF_RETURNS_RETAINED is missing: " + "; ".join(unannotated[:3]))

dealloc_body = method_body(hid_all, "- (void)dealloc")
check("CFRelease(_hidManager);" in dealloc_body,
      "the HID manager cannot outlive the object its run loop callbacks point into")
problem = ordered_once(dealloc_body, "IOHIDManagerUnscheduleFromRunLoop(",
                       "CFRelease(_hidManager)", "unscheduling the HID manager")
check(problem is None, "the HID manager is unscheduled before it is released"
      if problem is None else "the dealloc net is not ordered: " + problem)

# A gate nobody wired is worse than no gate: it sits in scripts/ looking like
# coverage while CI never runs it. Every audit and harness has to be reachable
# from the workflow, directly or through another reachable script, because one
# gate legitimately drives another (release-gate --self-test runs the preparation
# fixtures, and the preparation step exists only to satisfy that gate).
scripts_dir = os.path.join(root, "scripts")
gate_names = sorted(n for n in os.listdir(scripts_dir)
                    if n.endswith(("-audit.py", "-tests.py"))
                    or n in ("release-gate.py", "prepare-release.py", "assertion-battery.py"))
pipeline = open(os.path.join(root, ".github", "workflows", "build.yml"), encoding="utf-8").read()
INVOKES = re.compile(r"os\.path\.join|subprocess|sys\.executable|importlib")
reachable = {n for n in gate_names if n in pipeline}
grew = True
while grew:
    grew = False
    for name in gate_names:
        if name in reachable:
            continue
        for host in sorted(reachable):
            host_text = open(os.path.join(scripts_dir, host), encoding="utf-8").read()
            if any(name in line and INVOKES.search(line) for line in host_text.splitlines()):
                reachable.add(name)
                grew = True
                break
orphaned = sorted(set(gate_names) - reachable)
check(not orphaned, "every gate in scripts is reachable from the workflow"
      if not orphaned else "written but never run by CI: " + ", ".join(orphaned))

analyzer = subprocess.run([sys.executable,
                           os.path.join(root, "scripts", "analyzer-audit.py"), "--self-test"],
                          capture_output=True, text=True, cwd=root)
check(analyzer.returncode == 0, "the analyzer gate can tell a clean tree from a blind sweep"
      if analyzer.returncode == 0 else "the analyzer gate self test failed:\n"
      + analyzer.stdout[-700:])

# The localization scan used to be a `grep -rhoE` whose pattern contained a (?:
# group. BSD grep on macOS accepted it and reported 162 keys, while the ubuntu
# audit runner's grep produced nothing, the audit printed "0 keys referenced in
# code", both missing-key lists were empty because nothing had been scanned, and
# the step reported that coverage is complete. The pattern also allowed only a
# bare quote, so all 153 ObjC call sites that pass an @"..." literal to the same
# lookup through NSLocalizedString and MLString were invisible: the audit was
# blind twice over on the only keys it claimed to check.
l10n_script = open(os.path.join(root, "scripts", "l10n-audit.py"), encoding="utf-8").read()
check(re.search(r"^import .*\bsubprocess\b", l10n_script, re.M) is None,
      "the localization scan reads the sources itself instead of trusting a host grep")
l10n = subprocess.run([sys.executable, os.path.join(root, "scripts", "l10n-audit.py")],
                      capture_output=True, text=True, cwd=root)
check(l10n.returncode == 0, "the localization audit passes with its scan proven running"
      if l10n.returncode == 0 else "the localization audit failed:\n" + l10n.stdout[-700:])

# BUILD_NUMBER is `git rev-list --count HEAD`, which two places used to compute
# independently: the shell script that CI injects, and the release preparer. The
# preparer counted raw commits, so in a shallow clone it derived v1.3.9-build71
# for the same commit CI stamped 1407, and the changelog heading it wrote would
# have named a build no binary ever carried. One script owns the number, and that
# script has to refuse an incomplete history instead of reporting its depth.
build_script = open(os.path.join(root, "Limelight", "build-number.sh"), encoding="utf-8").read()
guards = [(cond, body) for cond, body in
          re.findall(r"(?ms)^if\b(.*?)\bthen\b(.*?)^fi\b", build_script)
          if "is-shallow-repository" in cond]
check(len(guards) == 1 and "--print" in guards[0][0]
      and re.search(r"\bexit\s+[1-9]", guards[0][1]) is not None,
      "the build number refuses a history it cannot count completely")

preparer = open(os.path.join(root, "scripts", "prepare-release.py"), encoding="utf-8").read()
check('"rev-list"' not in preparer and "build-number.sh" in preparer,
      "the release tag takes its build number from the one script that owns it")

if run_battery:
    # An assertion that stops failing on a regression is worse than no assertion,
    # because it reads as coverage. The battery plants regressions in the real
    # source and requires this file to reject every one, so it belongs to the
    # constraints and not to a step someone can drop: the CI job runs this script,
    # and running it is enough.
    battery = os.path.join(root, "scripts", "assertion-battery.py")
    proc = subprocess.run([sys.executable, battery, "--no-audit-recursion"],
                          capture_output=True, text=True, cwd=root)
    summary = [line for line in proc.stdout.splitlines() if "mutations caught" in line]
    print("%s assertion battery: %s" % ("ok" if proc.returncode == 0 else "FAIL",
                                        summary[0].strip() if summary else "no verdict reported"))
    if proc.returncode != 0:
        print(proc.stdout[-1500:])
        failures.append("the assertion battery failed to catch a planted regression")
else:
    print("skip assertion battery (invoked by the battery itself)")

print("%d constraint failures" % len(failures))
sys.exit(1 if failures else 0)
