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
  * a locked pointer was reported immovable (issue 24), and the tree answered with two
    claims: an unrecognised stored mouse strategy fell through to the mode that switches
    CoreHID off, and the status line credited motion to a sender nobody had observed --
    the AppKit line was written where the event arrived and a failed CoreHID named a
    replacement nothing had measured.
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

# The bundle name is what two clients collide over. Issue 41 is a report about an app that
# vanished from /Applications after this one was installed, and the identifier was never the
# problem -- both installed themselves as Moonlight.app. `project_identity` refuses that name
# on read, so the check below is about the constraint surviving an edit: a project file that
# names the Qt product has to be refused here, where a green build would otherwise ship it.
sys.path.insert(0, os.path.join(root, "scripts"))
import project_identity
product_names = set(re.findall(r"PRODUCT_NAME = ([^;]+);", project))
check(len(product_names) == 1
      and product_names == {project_identity.product_name(
          os.path.join(root, "Moonlight.xcodeproj", "project.pbxproj"))},
      "the product installs as %s, not the Qt client's Moonlight.app"
      % (", ".join(product_names) or "unset"))
check("CFBundleDisplayName" in info,
      "Info.plist carries a display name, so the disk name can stay ASCII")

# Renaming the product renames the header the Swift compiler emits, because its default
# name is `$(PRODUCT_NAME)-Swift.h`. Seventeen Objective-C files import that header under
# the name it carried before the rename, and every build starting from a clean derived
# data path -- the analyzer job and the render probe, both -- died in twenty-four seconds
# on the mismatch, while a stale derived data path let a local build report success. The
# name the compiler hands back is a compile-time contract, not a name a user reads, so the
# product name moves and this one is pinned, and a pin nobody checks is a comment.
GENERATED_SWIFT_HEADER = "Moonlight-Swift.h"
pinned_headers = set(re.findall(r'SWIFT_OBJC_INTERFACE_HEADER_NAME\s*=\s*"?([^";]+)"?;', project))
check(pinned_headers == {GENERATED_SWIFT_HEADER},
      "the generated Swift header keeps the name the sources import, whatever the product is called"
      if pinned_headers == {GENERATED_SWIFT_HEADER}
      else "the project pins the generated header to %s" % sorted(pinned_headers))
imported_headers = set(re.findall(
    r'#import "([^"]+)"',
    subprocess.run(["grep", "-rho", "--include=*.m", "--include=*.h",
                    "-e", '#import "[^"]*-Swift\\.h"', "Limelight"],
                   capture_output=True, text=True, cwd=root).stdout))
check(imported_headers == {GENERATED_SWIFT_HEADER},
      "no Objective-C file imports a generated Swift header the project does not emit"
      if imported_headers == {GENERATED_SWIFT_HEADER}
      else "sources import %s" % sorted(imported_headers))

# The same rename missed the second half of itself: a bundle's binary is named after the
# product too, and three consumers had `Contents/MacOS/Moonlight` written into them, so the
# render probe failed on the runner looking for a file the build no longer produces. Every
# one of them now asks the bundle, because the bundle is the thing that launches the binary.
BINARY_SPELLINGS = subprocess.run(
    ["grep", "-rn", "--include=*.py", "--include=*.sh", "--include=*.yml",
     "-e", 'Contents", "MacOS", "Moonlight"', "-e", 'Contents/MacOS/Moonlight"',
     "--", "scripts", ".github"],
    capture_output=True, text=True, cwd=root).stdout.splitlines()
# Two files may hold these spellings: this one, because a gate that cannot name what it
# refuses cannot refuse it, and the battery, because a mutation has to be able to write the
# mistake back. Everything else is a consumer, and a consumer is what broke.
REFEREES = ("scripts/constraints-audit.py:", "scripts/assertion-battery.py:")
BINARY_SPELLINGS = [line for line in BINARY_SPELLINGS
                    if not line.startswith(REFEREES)]
check(not BINARY_SPELLINGS,
      "no consumer spells a bundle's binary name, because the product name moves without it"
      if not BINARY_SPELLINGS else "the binary name is written out in: %s"
      % "; ".join(line.split(":")[0] for line in BINARY_SPELLINGS))

for reader, needle in (("scripts/render-probe.py", "bundle_executable"),
                       ("scripts/dmg-audit.py", "bundle_executable"),
                       ("scripts/integration-test.sh", "CFBundleExecutable")):
    check(needle in open(os.path.join(root, reader), encoding="utf-8").read(),
          "%s asks the bundle which binary it points at" % reader)

# The reader itself is a gate: its refusal is the half that protects issue 41, and a
# refusal that no local command runs is discovered on a runner eight minutes later.
identity = subprocess.run([sys.executable,
                           os.path.join(root, "scripts", "project_identity.py"), "--self-test"],
                          capture_output=True, text=True)
check(identity.returncode == 0,
      "project_identity.py self-test passes"
      if identity.returncode == 0 else
      "project_identity.py self-test failed: %s" % (identity.stdout + identity.stderr).strip()[-400:])
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
def job_body(workflow_text, job_name):
    """One job's own YAML body, from its key up to the next job key.

    Splitting the file on the release key and taking the last piece looked like the
    same thing and was not: it keeps every byte written after the release job. The
    day a second job runs the gate for its own reasons -- a rehearsal, a dry run, a
    rollback -- the check below is satisfied by that job while the release job itself
    publishes ungated. The jobs in this file are two-space keys, so one body ends at
    the next of those.
    """
    start = re.search(r"^  %s:[ \t]*$" % re.escape(job_name), workflow_text, re.M)
    if start is None:
        return ""
    rest = workflow_text[start.end():]
    following = re.search(r"^  [A-Za-z_][A-Za-z0-9_.-]*:[ \t]*$", rest, re.M)
    return rest[:following.start()] if following else rest


release_job = job_body(workflow, "release")
check("scripts/release-gate.py" in release_job,
      "the release job gates the tag before publishing")
# A boundary that only holds for today's file layout is a comment about tomorrow, so
# the boundary is exercised: a gate call written into the job that follows release has
# to stay invisible to the release job, and still be present in the file.
decoy_workflow = ("  release:\n"
                  "    steps:\n"
                  "    - run: echo publishing without a gate\n"
                  "  rehearsal:\n"
                  "    steps:\n"
                  "    - run: python3 scripts/release-gate.py\n")
check("scripts/release-gate.py" not in job_body(decoy_workflow, "release")
      and "scripts/release-gate.py" in decoy_workflow
      and "echo publishing" in job_body(decoy_workflow, "release"),
      "a gate call in a later job cannot answer for the release job")
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

# A runner that could not open a connection to github.com for nine seconds turned
# both macOS builds red, and the download had no retry and no check that what arrived
# was whole. The retry is worth less than the rule: a third dependency added next
# month will not remember to copy it unless the file is checked for it.
fetch_start = fetch.find("fetch_archive() {")
check(fetch_start >= 0,
      "dependency downloads share one fetch helper instead of one curl per dependency")
fetch_body = fetch[fetch_start:fetch.index("\n}", fetch_start)] if fetch_start >= 0 else ""
unheld = [flag for flag in ("--retry", "--connect-timeout", "--speed-limit", "verify_archive")
          if flag not in fetch_body]
check(not unheld,
      "the fetch helper retries a stalled connection and verifies the archive before unzipping"
      if not unheld else
      "the fetch helper no longer does these: " + ", ".join(unheld))
bypassed = [name for name in ("XCFRAMEWORKS_URL", "OPENSSL_URL")
            if 'fetch_archive "$%s"' % name not in fetch]
check(not bypassed,
      "every dependency download goes through the fetch helper"
      if not bypassed else
      "these downloads bypass the fetch helper: " + ", ".join(bypassed))

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


# Issue 24 is a locked pointer that cannot be moved at all, and two things in this tree
# made that report harder to act on than the missing feature itself. A stored mouse
# strategy this client does not recognise used to fall through to the strategy whose label
# read "HID" -- the strategy whose only effect was to switch CoreHID off, and whose single
# ObjC reader had no caller anywhere in `Limelight/`. And the runtime status line credited
# motion to a sender nobody had observed: the AppKit line was written where the pointer
# event arrived, which is upstream of every reason that event is still dropped, and a
# failed CoreHID named a replacement path that nothing had seen deliver anything. Both were
# claims with no measurement behind them, and the earlier version of this file repeated the
# second claim while trying to document it -- an assertion written from a reading of the
# strings table instead of the sender is how a wrong fact gets protected by a gate.
derived_text = open(os.path.join(root, "Limelight/macOS/ViewControllers/"
                                 "SettingsModel+DerivedValues.swift"),
                    encoding="utf-8").read()
strategy_block = swift_block(derived_text, "MouseInputDriverStrategy")
strategy_init = strategy_block.split("init(persistedRawValue", 1)[-1].split("init(selection", 1)[0]
check("self = Self.defaultStrategy" in strategy_init
      and ".compatibility" not in strategy_init,
      "an unusable stored mouse strategy falls back to the default, not to the retired mode")
check("case compatibility" not in strategy_block,
      "the strategy that only switched CoreHID off is retired, so it cannot be re-added as a case")
check(".compatibility" not in strategy_block.split("displayOrder")[-1],
      "the retired strategy is not offered by the settings picker")

bridge_text = open(os.path.join(root, "Limelight/macOS/ViewControllers/"
                                "SettingsObjCBridge.swift"), encoding="utf-8").read()
check("shouldUseCompatibilityMouse" not in bridge_text,
      "the reader that had no caller is not drafted back into the bridge")

# A string the runtime never asks for is not documentation, it is a claim waiting to be
# quoted. These rows stated which path would move the pointer, and no sender wrote them.
RETIRED_MOUSE_ROWS = ('"Mouse Input Strategy Compatibility detail"',
                      '"Mouse Runtime Path AppKit Fallback"',
                      '"Mouse Runtime Detail AppKit Fallback')
MOUSE_ROW_LIES = ("HID-compatible AppKit path", "使用 HID 兼容的 AppKit 路径",
                  "fell back to the AppKit compatibility path", "已回退到 AppKit 兼容路径")
OBSERVED_MOUSE_ROWS = ('"Mouse Runtime Path CoreHID Stopped"',
                       '"Mouse Runtime Detail CoreHID Stopped Permission"',
                       '"Mouse Runtime Detail CoreHID Stopped UnsupportedOS"',
                       '"Mouse Runtime Detail CoreHID Stopped Runtime"')
for table_name, table_path in (("en", "Limelight/macOS/en.lproj/Localizable.strings"),
                               ("zh-Hans", "Limelight/macOS/zh-Hans.lproj/Localizable.strings")):
    table = open(os.path.join(root, table_path), encoding="utf-8").read()
    check(not any(row in table for row in RETIRED_MOUSE_ROWS),
          "%s carries no mouse row that names a sender nobody credits" % table_name)
    check(not any(lie in table for lie in MOUSE_ROW_LIES),
          "%s does not keep a sentence that promised a path it never measured" % table_name)
    check(all(row in table for row in OBSERVED_MOUSE_ROWS),
          "%s states CoreHID stopping without naming a replacement" % table_name)

hid_text = open(os.path.join(root, "Limelight/Input/HIDSupport.m"), encoding="utf-8").read()
failure_body = method_body(hid_text, "- (void)coreHIDMouseDriver:(CoreHIDMouseDriver *)driver\n         didFailWithReason:")
check("AppKit" not in failure_body and "CoreHID Stopped" in failure_body,
      "a CoreHID failure reports what it observed and leaves the sender line uncredited")
dispatcher_body = method_body(hid_text, "- (void)dispatchRelativeMouseDeltaX:(CGFloat)deltaX")
check("noteMotionSource" in dispatcher_body and "LiSendMouseMoveEventCtx" in dispatcher_body
      and dispatcher_body.index("LiSendMouseMoveEventCtx") < dispatcher_body.rindex("noteMotionSource"),
      "the relative sender credits the status line after the packet, not before it")
pointer_text = open(os.path.join(root, "Limelight/Input/HIDSupport+Pointer.m"),
                    encoding="utf-8").read()
moved_body = method_body(pointer_text, "- (void)mouseMoved:(NSEvent *)event")
check("updateMouseInputRuntimeStatusFor" not in moved_body,
      "the pointer path no longer credits a sender on the way in, before the motion survives")


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

# A shortcut capture has to read every key the app gets, because the chord it records is
# one no control will accept, and a monitor that outlives the sheet keeps answering keys:
# `ShortcutCaptureSheet` answers a keyDown by writing a shortcut into the player's
# settings and swallowing the key, app-wide, while a game streams in another window.
# The page is taken out of the view tree by hand, so whether SwiftUI runs the sheet's
# `onDisappear` afterwards is a question about the SwiftUI version doing the presenting.
# Two things make the keyboard come back whichever answer that is, and both are
# load-bearing: the page's teardown ends the capture, and the monitor asks this type what
# to do with each key instead of closing over one sheet's handler, so what is left behind
# after an end is a monitor with nothing to say.
controls_path = "Limelight/macOS/ViewControllers/SettingsSharedControls.swift"
controls_src = open(os.path.join(root, controls_path), encoding="utf-8").read()
monitor_body = swift_block(controls_src, "enum SettingsKeyCaptureMonitor")
check(controls_src.count("NSEvent.addLocalMonitorForEvents") == 1
      and "NSEvent.addLocalMonitorForEvents" in monitor_body,
      "the settings page registers one app-level key monitor, in the type that owns it"
      if controls_src.count("NSEvent.addLocalMonitorForEvents") == 1 else
      "the settings page registers %d app-level key monitors: each one needs its own "
      "removal, which is the arrangement that leaked"
      % controls_src.count("NSEvent.addLocalMonitorForEvents"))
check("SettingsKeyCaptureMonitor.handler?(event) ?? event" in monitor_body,
      "the key monitor asks the capture type what to do with each key, so an ended "
      "capture answers nothing even if the monitor is still registered")
begin_body = swift_block(monitor_body, "static func begin(matching mask")
check(begin_body.lstrip("{").lstrip().startswith("end()"),
      "beginning a capture takes the slot from whoever holds it, so two sheets never read "
      "the same key")
check("NSEvent.removeMonitor" in monitor_body and "token = nil" in monitor_body,
      "ending a capture removes the monitor and forgets its token, so it is not removed "
      "twice")
check(not re.search(r"@SwiftUI\.State[^\n]*[Mm]onitor", controls_src),
      "no view holds a key monitor token in its own storage -- a view that goes away "
      "without being told takes the removal with it")
check(controls_src.count("SettingsKeyCaptureMonitor.begin(") == 2
      and controls_src.count("SettingsKeyCaptureMonitor.end(captureGeneration)") == 2,
      "both capture sheets begin a capture and end the one they began")
check("SettingsKeyCaptureMonitor.end()" in dismiss_body,
      "leaving the settings page ends a capture that is still open"
      if "SettingsKeyCaptureMonitor.end()" in dismiss_body else
      "the page can close over an open capture -- Command+W and the host window closing "
      "both reach this line -- and leave the app-level monitor reading every key")
left_an_open_capture = dismiss_body.replace("SettingsKeyCaptureMonitor.end()", "// x", 1)
check("SettingsKeyCaptureMonitor.end()" not in left_an_open_capture,
      "a teardown that leaves a capture open trips the assertion above")
neutral_monitor = monitor_body.replace(
    "SettingsKeyCaptureMonitor.handler?(event) ?? event", "handler(event)", 1)
check("SettingsKeyCaptureMonitor.handler?(event) ?? event" not in neutral_monitor,
      "a monitor that closes over one handler keeps recording after the capture ends, "
      "and trips the assertion above")

# The settings page also hands its model two closures to call when a value the page
# shows changes, and the model holds them for as long as it lives. A closure written the
# obvious way reaches the pane for both its state and its model, so the model keeps the
# pane, the pane keeps the model, and the presenter builds a fresh model for every
# settings window -- each one opened would leak one. This is the same cycle the block
# below refuses in Objective-C, arriving from the Swift side, and it is invisible in the
# one way a leak usually announces itself: nothing about the settings page behaves
# differently while it leaks. What makes it a claim rather than a hunch is that the
# ownership shape was compiled and run: capturing the pane left the model's deinit
# unprinted, capturing the model weakly and writing through a state binding printed it.
# The rule below keeps a later tidy-up from tidying that back.
pane_path = "Limelight/macOS/ViewControllers/SettingsStreamPane.swift"
pane_src = open(os.path.join(root, pane_path), encoding="utf-8").read()


def callbacks_held_tightly(src):
    """The view callbacks a model would keep its own pane alive through."""
    tight = []
    for name in re.findall(r"settingsModel\.(\w+Callback) = \{", src):
        if "[weak" not in swift_block(src, "settingsModel.%s = {" % name):
            tight.append(name)
    return tight


check(sorted(callbacks_held_tightly(pane_src)) == []
      and pane_src.count("Callback = {") == 2,
      "the settings page's model callbacks hold the model weakly and write through bindings"
      if not callbacks_held_tightly(pane_src) else
      "%s capture the model through the pane, and the model holds the closure that "
      "captures it" % ", ".join(callbacks_held_tightly(pane_src)))
held_tight = pane_src.replace("[weak model = settingsModel]", "[model = settingsModel]")
check(sorted(callbacks_held_tightly(held_tight)) ==
      ["fpsChangedCallback", "resolutionChangedCallback"],
      "a settings callback that keeps the model it belongs to trips the assertion above"
      if sorted(callbacks_held_tightly(held_tight)) else
      "the weak-capture rule does not see the cycle it was written for")

# Every back-reference in this tree points at the object that owns the thing holding it: a
# host cell points at the hosts page, a box-art retriever at the page that asked for the
# artwork, a service browser at the discovery stack that started it. Held strongly each one
# is a cycle, and a cycle is a leak with a face. Two of them were shipping: MDNSManager was
# told to report hosts to the DiscoveryManager that owns it and held that promise strongly,
# and AppAssetManager did the same to the apps page, so every refresh of the hosts page and
# every host whose artwork was fetched left a whole stack alive forever. Nothing could
# release it either, because a bare `id` ivar is strong under ARC and so is
# `@property id<X> name;`, which is why neither of them read as anything special.
#
# So a back-reference is weak, or the reason it is not a cycle is written down with a line
# that has to still be true -- and an excuse whose proof has gone away fails the same way.
# An exemption nobody can re-check is a hole with a note beside it. A needle beginning with
# "!" has to be absent.
STRONG_BACK_REFERENCES = {
    # "file::member" -> (why this is not a cycle, where to look, the line to find)
    "Limelight/Network/PairManager.m::_callback": (
        "the hosts page builds a pairing manager as a local and never stores it, so the "
        "manager is not owned by the page it reports to and cannot own it back",
        "Limelight/macOS/ViewControllers/HostsViewController.m",
        "PairManager* pMan = [[PairManager alloc]"),
    "Limelight/Stream/StreamManager.m::_callbacks": (
        "this is the scoped forwarder rather than the page, and the forwarder holds the page "
        "weakly and drops a callback whose stream generation is gone",
        "Limelight/macOS/ViewControllers/StreamViewController.m",
        "__weak id<MLStreamScopedCallbackOwner> _owner;"),
    "Limelight/Stream/Connection.m::_callbacks": (
        "the same scoped forwarder, carried to the connection thread that has to answer "
        "callbacks without the page",
        "Limelight/macOS/ViewControllers/StreamViewController.m",
        "__weak id<MLStreamScopedCallbackOwner> _owner;"),
    "Limelight/Input/ControllerSupport.m::_presenceDelegate": (
        "the stream page owns its controller support and nils it on the way out, which is "
        "what breaks the cycle a strong delegate would otherwise be",
        "Limelight/macOS/ViewControllers/StreamViewController.m",
        "self.controllerSupport = nil;"),
    "Limelight/Input/OnScreenControls.m::_edgeDelegate": (
        "the macOS target does not compile this file, so the delegate is a name in a source "
        "nobody builds -- which is only safe to say while the project really does not name it",
        "Moonlight.xcodeproj/project.pbxproj", "!OnScreenControls"),
}
BACK_REFERENCE_PROTOCOL = re.compile(r"(Delegates?|Callbacks?|DataSource|Listener|Owner)$")
PROPERTY_REFERENCE = re.compile(
    r"@property\s*(?:\((?P<attrs>[^)]*)\))?\s*(?P<weak>__weak\s+)?id\s*<(?P<proto>[^>]+)>\s*"
    r"(?P<name>\w+)\s*;")
IVAR_REFERENCE = re.compile(
    r"^\s*(?P<weak>__weak\s+)?id\s*<(?P<proto>[^>]+)>\s*(?P<name>_\w+)\s*;\s*$", re.M)
back_references = {}
for directory, _, names in os.walk(os.path.join(root, "Limelight")):
    for name in sorted(names):
        if not name.endswith((".h", ".m")):
            continue
        relative = os.path.relpath(os.path.join(directory, name), root)
        source = open(os.path.join(root, relative), encoding="utf-8", errors="replace").read()
        for found in (list(PROPERTY_REFERENCE.finditer(source))
                      + list(IVAR_REFERENCE.finditer(source))):
            if not BACK_REFERENCE_PROTOCOL.search(found.group("proto")):
                continue
            attributes = (found.groupdict().get("attrs") or "").lower()
            back_references["%s::%s" % (relative, found.group("name"))] = (
                found.group("weak") is not None
                or "weak" in attributes or "assign" in attributes)
unowned = sorted(site for site, weak in sorted(back_references.items())
                 if not weak and site not in STRONG_BACK_REFERENCES)
check(not unowned,
      "every back-reference to an owner is weak, or its reason is written down"
      if not unowned else
      "strong reference back to whatever owns it, which is a cycle and a leak: "
      + ", ".join(unowned))
stale_back_reference_excuses = []
for site, (reason, proof_file, needle) in sorted(STRONG_BACK_REFERENCES.items()):
    if site not in back_references:
        stale_back_reference_excuses.append("%s is not declared any more" % site)
        continue
    if back_references[site]:
        stale_back_reference_excuses.append("%s is weak now, so the excuse is dead weight" % site)
        continue
    proof = open(os.path.join(root, proof_file), encoding="utf-8", errors="replace").read()
    wanted = needle[1:] if needle.startswith("!") else needle
    present = wanted in proof
    if present == needle.startswith("!"):
        stale_back_reference_excuses.append("%s's excuse cites %s, which is not the case "
                                            "any more" % (site, needle))
check(not stale_back_reference_excuses,
      "each written excuse for a strong back-reference is still needed and still true"
      if not stale_back_reference_excuses else "; ".join(stale_back_reference_excuses))
check(len(back_references) >= 12,
      "the scan really reads the back-references it counts (%d found)" % len(back_references))
for site in ("Limelight/Network/MDNSManager.h::callback",
             "Limelight/Network/DiscoveryManager.m::_callback",
             "Limelight/Network/AppAssetManager.m::_callback",
             "Limelight/Network/AppAssetRetriever.h::callback"):
    check(back_references.get(site) is True,
          "%s is weak, which is what keeps the owner behind it releasable" % site)
unqualified = PROPERTY_REFERENCE.search("@property (nonatomic) id<MDNSCallback> callback;")
check(unqualified is not None and "weak" not in (unqualified.group("attrs") or "").lower(),
      "a callback property written without a qualifier is read as strong, which is what "
      "lets the rule above refuse one")

# A trap in shipping code is a decision that whichever input arrives first gets to make.
# The two storyboard stubs below are traps by construction -- nobody builds those views from
# a storyboard, and the compiler cannot say so -- and every other one has to be argued for
# the way a strong back-reference has to be, with a line that has to still be true.
#
# `try!` was the only one standing when this rule was written. It sat on the way to
# installing a privileged helper, and the sentence that justified it -- the property list is a
# literal of plist-safe types, so it cannot throw -- is a claim about that day's source and
# not a property of the type: one field added beside it that is not plist-safe (a URL, a date,
# a value read from disk) turns the promise into an app that stops. The caller already had a
# failure it could show, so the throwing answer costs nothing and removes the class.
UNREACHABLE_TRAPS = {
    # file -> (why this trap cannot be reached, the line that says so)
    "Limelight/macOS/ViewControllers/ConnectionDetailsViewController.swift": (
        "two rows AppKit builds programmatically, whose storyboard initialiser has no answer "
        "that is not a bug -- refusing it in words is the honest answer",
        'fatalError("init(coder:) has not been implemented")'),
}
TRAP = re.compile(r"\btry\s*!|\bas\s*!|\bfatalError\(|\bpreconditionFailure\(")
trap_problems, swift_files = [], 0
for directory, _, names in os.walk(os.path.join(root, "Limelight")):
    if not any(part in ("macOS", "Input") for part in directory.split(os.sep)):
        continue
    for name in sorted(names):
        if not name.endswith(".swift"):
            continue
        relative = os.path.relpath(os.path.join(directory, name), root)
        source = open(os.path.join(root, relative), encoding="utf-8", errors="replace").read()
        # A comment that names `try!` is not a trap, and the rule that refuses traps must not
        # be refusible by the sentence that describes one.
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith(("//", "///", "*")))
        swift_files += 1
        found = len(TRAP.findall(code))
        reason, needle = UNREACHABLE_TRAPS.get(relative, ("", ""))
        argued_for = code.count(needle) if needle else 0
        if found != argued_for:
            trap_problems.append(
                "%s traps %d time(s) and argued for %d" % (relative, found, argued_for))
check(not trap_problems,
      "no shipping Swift source traps unless it has argued for the trap"
      if not trap_problems else "; ".join(trap_problems))
check(swift_files >= 25,
      "the trap scan really read the Swift sources it counts (%d)" % swift_files)
trap_probe = "        return try! PropertyListSerialization.data(fromPropertyList: plist)\n"
check(len(TRAP.findall(trap_probe)) == 1,
      "a `try!` written the way this tree writes one is read by the scan above")

# The page takes the key focus on the way in. Two things follow, and both are
# about order rather than presence: the record has to be read before the focus
# is taken, because reading the first responder afterwards records the page
# itself, and the hand-back has to happen while the page is still in the view
# tree, because AppKit chooses the successor of a first responder that simply
# disappears. The successor is where every key the page's gate declines to
# consume then lands -- on the window, where Space and Return activate the
# default button and the arrows move the key view loop.
check("savedFirstResponder = window.firstResponder" in show_body
      and show_body.index("savedFirstResponder = window.firstResponder")
          < show_body.index("window.makeFirstResponder(hosting.view)"),
      "the page records who held the key focus before it takes the focus")
check("window.makeFirstResponder(savedFirstResponder)" in dismiss_body
      and "window.makeFirstResponder(window.contentView)" in dismiss_body,
      "leaving the settings page hands the key focus back instead of leaving AppKit to choose")

took_without_asking = show_body.replace(
    "    savedFirstResponder = window.firstResponder" + chr(10), "", 1)
check("window.makeFirstResponder(hosting.view)" in took_without_asking
      and "savedFirstResponder = window.firstResponder" not in took_without_asking,
      "a page that takes the focus without recording it trips the order assertion")
kept_the_keys = dismiss_body.replace(
    "window.makeFirstResponder(savedFirstResponder)", "// inverted", 1)
check("window.makeFirstResponder(savedFirstResponder)" not in kept_the_keys,
      "a page that closes and keeps the keys trips the hand-back assertion")

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

# Building a window is not the only way the page can leave the subject. A sheet,
# a popover and a modal present each put the page in a window AppKit builds for
# it, none of which spells NSWindow(, and every one of them is the thing the
# request was about: the page has to share the interface it was opened from.
# Raising the window that already holds the page is legal and already happens,
# so this names the mechanisms that move the page somewhere else rather than the
# ones that bring an existing window forward.
DETACHED_PRESENTATION = ("NSPopover", "beginSheet", "beginAnimatedSheet", "endSheet",
                         "presentViewController", "presentAsPopover",
                         "presentAsModalWindow", "runModal", "openWindow(",
                         ".sheet(", ".popover(", "fullScreenCover")

for rel, source in ((presenter_path, presenter_src), (settings_view_path, settings_view_src),
                    ("SettingsWindowObjCBridge", bridge_body)):
    found = [token for token in DETACHED_PRESENTATION if token in source]
    check(not found, "the settings page never moves itself into another window (%s)" % rel
          if not found else "the settings page detaches from its window in %s: %s" % (rel, found))

# Where the page is attached is the same claim from the other side: it goes into
# the content view of the window it was asked to present in, not into a view of
# something presented on top of that window.
present_body = swift_block(presenter_src, "static func present(in window: NSWindow?")
check("let content = window.contentView" in present_body,
      "the page attaches to the content view of the window it was opened from")

# Both directions. The mutation is what the ban is for, and the older ban has to
# stay demonstrably blind to it, or this second rule is only decoration.
detached_probe = presenter_src.replace(
    "    content.addSubview(hosting.view)",
    "    let relocated = NSPopover()" + chr(10) + "    content.addSubview(hosting.view)", 1)
check(detached_probe != presenter_src
      and any(token in detached_probe for token in DETACHED_PRESENTATION),
      "a settings page handed to a popover is refused by the presentation ban")
check(not any(token in detached_probe for token in WINDOW_CONSTRUCTION),
      "the window-construction ban alone would miss a popover-based page, which is "
      "what the presentation ban above is for")


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

# The gate is not the only place a key gets consumed. The translation-rule helper
# runs from inside it and hands its answer straight back through it, so a bare
# `return YES;` in there consumes a key exactly the way the gate does -- and the
# rule above cannot see it, because the helper sits above the gate in the file.
# Both of its consuming exits were exactly that, which is how a rule that sends a
# synthetic shortcut also handed the host a release for the player's own key: a
# key the host never saw go down, coming up on its own, mid-action.
helper_start = capture_all.index("- (BOOL)handleKeyboardTranslationRuleForEvent:")
helper_body = capture_all[helper_start:
                          capture_all.index("\n#pragma mark - KeyboardNotifiable", helper_start)]
check("return YES;" not in helper_body,
      "the rule helper records the debt for every key it consumes"
      if "return YES;" not in helper_body else
      "the translation-rule helper consumes a key without recording the debt")
check(helper_body.count("return [self consumeKeyDownEvent:event];") >= 2,
      "both consuming exits of the rule helper pair the release"
      if helper_body.count("return [self consumeKeyDownEvent:event];") >= 2 else
      "only %d of the rule helper's consuming exits record the debt"
      % helper_body.count("return [self consumeKeyDownEvent:event];"))
# A local action returns whether it ran, which is not a claim about the key. The
# one place that calls it has to turn that answer into a recorded consumption.
check(capture_all.count("if ([self performKeyboardTranslationLocalAction:rule.localAction]) {") == 1,
      "the local-action answer is turned into a recorded consumption at its one call site"
      if capture_all.count("if ([self performKeyboardTranslationLocalAction:rule.localAction]) {") == 1 else
      "the local-action answer reaches the gate with %d wrapped call sites"
      % capture_all.count("if ([self performKeyboardTranslationLocalAction:rule.localAction]) {"))

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
    (ordered_once(hid_down, "self.keyboardForwardedKeyDownKeyCodes[@(event.keyCode)] = @(keyCode)",
                  "LiSendKeyboardEventCtx", "recording the press"),
     "a press the host is told about is recorded before it is sent"),
    (ordered_once(hid_up, "[self.keyboardForwardedKeyDownKeyCodes removeObjectForKey:@(event.keyCode)]",
                  "LiSendKeyboardEventCtx", "spending the held-key record"),
     "a forwarded release spends the held-key record for that physical key"),
    (ordered_once(hid_release, "[self.keyboardForwardedKeyDownKeyCodes removeAllObjects]",
                  "LiSendKeyboardEventCtx", "dropping the records"),
     "the held-key release drops its records before sending the releases"),
    (ordered_once(hid_capture_off, "[self.hidSupport releaseAllHeldKeys];",
                  "self.hidSupport.shouldSendInputEvents = NO;", "releasing held keys"),
     "capture release lets go of held keys before input forwarding is off"),
    # The same argument covers the modifier tracker. flagsChanged: stops reaching
    # the sync once input is off, so a modifier the host was told about and the
    # player later lets go of stays down on the host until the next keyboard
    # event -- every pointer click in between carries a modifier nobody holds.
    (ordered_once(hid_capture_off,
                  "[self.hidSupport releaseRemoteModifierKeysForUncapture];",
                  "self.hidSupport.shouldSendInputEvents = NO;", "returning modifiers"),
     "capture release returns the modifiers the host was told about before "
     "input forwarding is off"),
]:
    check(problem is None, message if problem is None else "%s is not effective: %s" % (message, problem))

check(guard_exits(hid_release, "if (self.keyboardHeldKeyReleaseInProgress)",
                    "self.keyboardHeldKeyReleaseInProgress = YES",
                    "LiSendKeyboardEventCtx") is None,
      "the held-key release cannot re-enter itself")
check("KEY_ACTION_UP" in hid_release,
      "the held-key release actually sends releases")
check("self.keyboardForwardedKeyDownKeyCodes = [NSMutableDictionary dictionary];" in hid_init,
      "the held-key record exists before the first key can reach it")
check("self.keyboardForwardedKeyDownKeyCodes.allValues" in hid_release,
      "the held-key release reads the dispatched code back out of the record, "
      "not the physical key it was filed under")
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
video_rules_path = os.path.join(root, "Limelight/macOS/ViewControllers/SettingsModel+VideoPageRules.swift")
video_rules = open(video_rules_path, encoding="utf-8").read()
fi_rule = swift_block(video_rules, "var frameInterpolationIsCapable: Bool")

check("supportsDevice(" in mfx_support and "return true" not in mfx_support,
      "MetalFX availability asks the GPU instead of the operating system version")
check("numberOfInterpolatedFrames" in fi_support and "slots >= 1" in fi_support,
      "interpolation availability counts the slots the GPU offers")
check("__supportedScaleFactors" in sr_support and "factors.isEmpty" in sr_support,
      "super resolution availability asks for the scale factors per frame size")
check('id == "enhancement.vtLowLatencyFI"' in fi_rule and "availability == .available" in fi_rule,
      "the interpolation control is gated by the measured capability, not a constant")
fi_enabled = swift_block(video_rules, "var frameInterpolationControlIsEnabled: Bool")
check("frameInterpolationIsCapable" in fi_enabled and "videoRendererModeIsMetal" in fi_enabled,
      "the interpolation control's live state is one expression, so the control and the "
      "sentence beside it cannot disagree")
check(".disabled(!settingsModel.frameInterpolationControlIsEnabled)" in video_pane,
      "the video page disables the interpolation control through that one expression")




# These are findings from `xcodebuild analyze` that were real defects, kept as
# rules rather than left to be rediscovered: a CGEvent created on every gamepad
# navigation press and never released, a CGPath helper that handed out a +1
# reference under a name that did not say so (one caller released it and the
# caller in another file leaked one per shadow refresh), and the HID manager
# outliving the object that its four run loop callbacks point into.
def method_bodies(source):
    """Every method definition with its body, for rules that live per method.

    This tree writes the opening brace two ways. Counted on the sources as they stand:
    1315 definitions put it on the signature's own line and 244 put it on the next one, so a
    reader that asked for the first style reported on three quarters of the file it believed
    it had read -- and said nothing about the rest. That is the failure mode this repository
    keeps finding rather than the one it sets out to find: a rule that is quietly blind reads
    exactly like a rule that is quietly satisfied. So both styles are read here. A signature
    that runs on into a `;` is a declaration rather than a definition, which is what the
    class extensions in these files carry, and it is skipped rather than answered.
    """
    for match in re.finditer(r"^[-+]\s*\(", source, re.M):
        start, index = match.start(), match.start()
        while index < len(source) and source[index] not in "{;":
            index += 1
        if index >= len(source) or source[index] == ";":
            continue
        depth, brace = 0, index
        while brace < len(source):
            if source[brace] == "{":
                depth += 1
            elif source[brace] == "}":
                depth -= 1
                if depth == 0:
                    break
            brace += 1
        yield source[start:brace + 1]


# A Debug-only Swift file is only Debug-only if the Swift compiler is told the
# condition exists. This project carried no SWIFT_ACTIVE_COMPILATION_CONDITIONS at
# all, so `#if DEBUG` in a .swift file compiled to nothing while the Objective-C
# half of the same feature compiled and reached for a class that had never been
# emitted. Nothing about that is visible in a Release build, which is the worst
# kind of silent: the shipped binary looks clean because the code was never there.
PBXPROJ = os.path.join(root, "Moonlight.xcodeproj", "project.pbxproj")
project_text = open(PBXPROJ, encoding="utf-8").read()


def configuration_blocks(source):
    """Every XCBuildConfiguration block, so a rule can ask one language at a time."""
    blocks = {}
    for match in re.finditer(r"^\t\t(\w{24}) /\* (\w+) \*/ = \{$", source, re.M):
        depth, index = 1, match.end()
        while index < len(source):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        blocks[match.group(1)] = (match.group(2), source[match.end():index])
    return blocks


def defines_condition(block, key):
    """True when a build setting lists a bare flag, ignoring a substring match.

    NDEBUG has to count as absent here: matching "DEBUG" inside "NDEBUG" would
    call a Release-only macro the Debug one.
    """
    match = re.search(key + r"\s*=\s*((?:[^;\"']|\"[^\"']*\")*)\s*;", block, re.S)
    if not match:
        return False
    return any(token == "DEBUG" or token.startswith("DEBUG=")
               for token in re.split(r"[^0-9A-Za-z_=]+", match.group(1)))


configs = configuration_blocks(project_text)
check(len(configs) >= 2, "the project file exposes %d build configurations to read" % len(configs)
      if len(configs) >= 2 else "the project file parsed to %d build configurations, which is "
                                "too few to tell Debug from Release" % len(configs))
debug_blocks = [body for name, body in configs.values() if name == "Debug"]
objc_defines_debug = any(defines_condition(body, "GCC_PREPROCESSOR_DEFINITIONS")
                         for body in debug_blocks)
swift_defines_debug = any(defines_condition(body, "SWIFT_ACTIVE_COMPILATION_CONDITIONS")
                          for body in debug_blocks)
# The asymmetry, not the missing line, is the defect: a project with no DEBUG
# anywhere is consistent, and a project that names it for one language and not the
# other is how a Debug-only feature ends up half-compiled. This happened here -- the
# Debug configuration defined DEBUG=1 for C-family sources and nothing for Swift, so
# `#if DEBUG` in a .swift file compiled to nothing while the Objective-C caller of
# the class inside it was still compiled and linked against a header that had no
# such class. A Release build shows nothing wrong, because in Release the code is
# absent on both sides.
check(not objc_defines_debug or swift_defines_debug,
      "the Debug configuration names DEBUG for Swift as well as for C-family sources"
      if not objc_defines_debug or swift_defines_debug
      else "the Debug configuration defines DEBUG for Objective-C but not for Swift, so every "
           "`#if DEBUG` in a .swift file compiles to nothing while its caller stays compiled")

swift_debug_files = [os.path.relpath(os.path.join(directory, name), root)
                     for directory, _, names in os.walk(os.path.join(root, "Limelight"))
                     for name in sorted(names)
                     if name.endswith(".swift")
                     and "#if DEBUG" in open(os.path.join(directory, name), encoding="utf-8").read()]
if swift_debug_files:
    check(swift_defines_debug,
          "Debug builds define the condition %d Debug-only Swift file(s) are written against"
          % len(swift_debug_files))
for relative in swift_debug_files:
    check(relative.split("/")[-1] in project_text,
          "a Debug-only Swift file is listed for the target, so it is really compiled"
          if relative.split("/")[-1] in project_text
          else "%s is not in the project file and would ship nothing" % relative)

# The capability matrix sits in a collapsed DisclosureGroup, so the only reading that
# proves anything is taken after the probe presses the section open. That claim lives
# in two files: the probe has to press, the checker has to read the pressed pass. Bind
# them together, and bind the defaults key the probe forces shut to the string the page
# actually stores the state under, so a rename cannot leave the probe forcing a
# preference nothing reads.
APP_PANE = os.path.join(root, "Limelight", "macOS", "ViewControllers", "SettingsAppPane.swift")
app_pane = open(APP_PANE, encoding="utf-8").read()
PROBE_APP = os.path.join(root, "Limelight", "macOS", "AppDelegateForAppKit.m")
probe_app = open(PROBE_APP, encoding="utf-8").read()
RENDER_PROBE = os.path.join(root, "scripts", "render-probe.py")
render_probe = open(RENDER_PROBE, encoding="utf-8").read()
probe_key = re.search(r'MLProbeAdvancedSectionCollapsedKey\s*\n?\s*= @"([^"]+)"', probe_app)
check(bool(probe_key) and probe_key.group(1) in app_pane,
      "the probe forces the same preference the app page stores the section state under"
      if probe_key and probe_key.group(1) in app_pane
      else "the probe forces %r, which the app page never reads, so the section state it "
           "checks is not the one the page uses" % (probe_key.group(1) if probe_key else None,))
check("accessibilityPerformPress" in probe_app and "readableContentExpanded" in probe_app
      and 'texts_of(pane, "readableContentExpanded")' in render_probe,
      "the capability claims are checked only against the pass that pressed the section open"
      if "accessibilityPerformPress" in probe_app and "readableContentExpanded" in probe_app
      and 'texts_of(pane, "readableContentExpanded")' in render_probe
      else "the probe or the checker stopped pairing the capability claims with the pass "
           "taken after the collapsed section was opened, so a collapsed page reads as clean")

# The video page and the Debug render probe read one rule about which enhancement
# controls are live and which sentence explains them. The rule used to live inside
# the page, where nothing could compare it against what the page then displayed;
# copying it back into the page would put the claim out of reach again, so the
# page is only allowed to ask the model.
VIDEO_PAGE = os.path.join(root, "Limelight", "macOS", "ViewControllers", "SettingsVideoPane.swift")
video_page = open(VIDEO_PAGE, encoding="utf-8").read()
check("settingsModel.frameInterpolationControlIsEnabled" in video_page
      and "settingsModel.upscalingControlIsEnabled" in video_page,
      "the video page asks the model whether an enhancement control is live")
check("videoCapabilityMatrix.items.first" not in video_page
      and 'normalizedVideoRendererMode(' not in video_page,
      "the video page does not keep its own copy of the enhancement rule"
      if "videoCapabilityMatrix.items.first" not in video_page
      and 'normalizedVideoRendererMode(' not in video_page
      else "the video page recomputes a rule the model already answers, so the page and "
           "the check on it can drift apart")
check("settingsModel.frameInterpolationExplanationKey" in video_page
      and "settingsModel.upscalingExplanationKey" in video_page,
      "the video page shows the explanation its own rules chose")

# What the settings page says about frame interpolation used to be chosen by searching
# the reason for a phrase, and the phrasing was the bug twice over: "provides cadence
# headroom over" and "does not have cadence headroom over" share the phrase, so the
# working case answered the refusal sentence, and a per-frame failure was caught by the
# engine-is-none shortcut before the word "unavailable" was read. The pairing layer had
# this ruled out years ago for the same reason, so the rule is repeated here rather than
# re-argued: the sentence comes from a named state, every state has a sentence, and every
# sentence exists in both languages.
RENDERER = os.path.join(root, "Limelight", "Stream", "VideoDecoderRenderer.m")
renderer = open(RENDERER, encoding="utf-8").read()
interpolation_report = method_body(
    renderer, "- (NSString *)runtimeDetailKeyForFrameInterpolationReport:"
              "(MLVideoFrameInterpolationReport)report")
check("switch (report)" in interpolation_report
      and "containsString:" not in interpolation_report,
      "the frame interpolation sentence is chosen by state and not by reading the reason")

named_states = sorted({m.group(1) for m in re.finditer(
    r"MLVideoFrameInterpolationReport([A-Z][A-Za-z]+)\s*(?:,|=)", renderer)})
answered_states = sorted({m.group(1) for m in re.finditer(
    r"case\s+MLVideoFrameInterpolationReport([A-Z][A-Za-z]+)\s*:", interpolation_report)})
check(bool(named_states) and answered_states == named_states,
      "every frame interpolation state has a sentence behind it"
      if answered_states == named_states else
      "frame interpolation states with no wording: %s"
      % ", ".join(sorted(set(named_states) - set(answered_states)) or
                  "none; extra: " + ", ".join(sorted(set(answered_states) - set(named_states)))))

# Every string the switch hands back, not every string matching a pattern: a filter that
# quietly missed the keys with spaces in them would leave six of ten sentences unchecked
# while the rule reported green, which is the failure this round keeps tripping over.
REPORT_LKEYS = sorted(set(re.findall(r'return @"([^"]+)"', interpolation_report)))
check(len(REPORT_LKEYS) >= 2,
      "the frame interpolation report answers with localization keys"
      if len(REPORT_LKEYS) >= 2 else
      "the frame interpolation report returns %d keys, so the wording check below is "
      "reading an answer that is not there" % len(REPORT_LKEYS))
for language in ("en", "zh-Hans"):
    table = open(os.path.join(root, "Limelight", "macOS", "%s.lproj" % language,
                              "Localizable.strings"), encoding="utf-8").read()
    untranslated = [key for key in REPORT_LKEYS if '"%s" =' % key not in table]
    check(bool(REPORT_LKEYS) and not untranslated,
          "the frame interpolation sentences all exist in %s" % language
          if not untranslated else
          "frame interpolation sentences missing from %s: %s"
          % (language, ", ".join(untranslated)))


def compiled_sources(scan_root):
    base = os.path.join(scan_root, "Limelight")
    for directory, _, names in os.walk(base):
        for name in sorted(names):
            if name.endswith(".m"):
                path = os.path.join(directory, name)
                yield path, open(path, encoding="utf-8").read()


CREATED = re.compile(r"(\w+)\s*=\s*CG\w*(?:Create|Copy)\w*\(")


def unowned_creations(source_path, text):
    """CoreFoundation references this file takes without saying who owes them back.

    A Create or Copy has three honest endings. It is released before the method that took it
    ends; it is returned by a method that says it hands over a +1; or it is stored where the
    object keeps it -- an ivar -- with a release somewhere else in the same file. The third is
    what the renderer's colour spaces do, one teardown per prepare, and no rule here had ever
    seen that ending, because those methods open their brace on the line after the signature
    and the reader used to stop at the signature. They appeared as three unaccounted
    references the moment the other style became readable, which is the same blind spot seen
    from the side it hurts.
    """
    problems = []
    for body in method_bodies(text):
        signature = body.split("\n")[0]
        for name in set(CREATED.findall(body)):
            released = re.search(r"\w*Release\(\s*%s\s*\)" % re.escape(name), body)
            returned = re.search(r"return\s+%s\s*;" % re.escape(name), body)
            kept = (name.startswith("_")
                    and re.search(r"\w*Release\(\s*%s\s*\)" % re.escape(name), text))
            if not released and not kept and not (returned and "CF_RETURNS_RETAINED" in signature):
                problems.append("%s: %s is created and then neither released nor "
                                "declared owned" % (os.path.relpath(source_path, root), name))
    return problems


unowned = [problem
           for source_path, text in compiled_sources(root)
           for problem in unowned_creations(source_path, text)]
check(not unowned, "every CoreFoundation reference created here is accounted for"
      if not unowned else "; ".join(unowned[:3]))

planted_stored_space = ("- (void)keepThePlantedColorSpace\n"
                        "{\n"
                        "    _plantedColorSpace = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);\n"
                        "}\n"
                        "- (void)releaseThePlantedColorSpace\n"
                        "{\n"
                        "    CGColorSpaceRelease(_plantedColorSpace);\n"
                        "    _plantedColorSpace = NULL;\n"
                        "}\n")
planted_dropped_space = ("- (void)keepThePlantedColorSpace\n"
                         "{\n"
                         "    _plantedColorSpace = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);\n"
                         "}\n")
kept_space = unowned_creations("planted.m", planted_stored_space)
dropped_space = unowned_creations("planted.m", planted_dropped_space)
check(not kept_space and len(dropped_space) == 1,
      "a reference an object stores and releases elsewhere in the file is accounted for,"
      " and one it stores and never releases is not"
      if not kept_space and len(dropped_space) == 1 else
      "the stored-reference pair answers wrong: kept=%s dropped=%s"
      % (kept_space, dropped_space))

unannotated = ["%s: %s" % (os.path.relpath(source_path, root), body.split("\n")[0].strip())
               for source_path, text in compiled_sources(root)
               for body in method_bodies(text)
               if re.match(r"^[-+]\s*\(CG(?:Mutable)?PathRef\s*\*?\)", body)
               and "CF_RETURNS_RETAINED" not in body.split("\n")[0]]
check(not unannotated, "a path handed to a caller says who owns it"
      if not unannotated else "CF_RETURNS_RETAINED is missing: " + "; ".join(unannotated[:3]))

# Two more handle families are as unmanaged as the ones above and equally silent when
# wrong, and neither was read by any rule until now: an IOKit registry walk, and a
# CoreFoundation-typed property. Both were read by hand this round -- six IOKit locals in
# the one file that touches the registry, every one released; three CF-typed properties,
# every one released -- and "read by hand" is a statement about today. The registry
# iterator is the nastier of the two: what a leaked io_iterator_t pins is a walk over the
# live registry rather than one block of memory, so it accumulates against the kernel's
# own map rather than against the heap.

IOKIT_LOCAL = re.compile(
    r"\b(?:io_iterator_t|io_service_t|io_registry_entry_t|io_object_t)\s+(\w+)\s*(?:=|;)")


def unheld_iookit_locals(body):
    """IOKit registry handles a method takes from the kernel and never gives back."""
    return sorted({name for name in IOKIT_LOCAL.findall(body)
                   if not re.search(r"IOObjectRelease\(\s*%s\s*\)" % re.escape(name), body)})


unreleased_iookit = ["%s: %s" % (os.path.relpath(source_path, root), name)
                     for source_path, text in compiled_sources(root)
                     for body in method_bodies(text)
                     for name in unheld_iookit_locals(body)]
check(not unreleased_iookit,
      "every IOKit registry handle a method takes is released in that method"
      if not unreleased_iookit else
      "no IOObjectRelease for: " + ", ".join(unreleased_iookit[:4]))
planted_walk = ("- (void)walkTheRegistry\n"
                "{\n"
                "    io_iterator_t plantedIterator = IO_OBJECT_NULL;\n"
                "    IOServiceGetMatchingServices(kIOMainPortDefault, match, &plantedIterator);\n"
                "}\n")
check(unheld_iookit_locals(planted_walk) == ["plantedIterator"],
      "a registry walk that never releases its iterator trips the rule above"
      if unheld_iookit_locals(planted_walk) == ["plantedIterator"] else
      "the IOKit rule does not see the leak it was written for")

CF_PROPERTY = re.compile(r"@property[^(]*\([^)]*\)\s+(\w+Ref)\s+(\w+)\s*;")


def unreleased_cf_properties(texts):
    """CF-typed properties nobody releases.

    clang gives a property of a CoreFoundation type no reference at all -- the AST calls
    `@property (nonatomic) IOHIDManagerRef` an assign -- so nobody releasing it is not a
    leak the analyzer will always catch: it catches the store it cannot follow, not the
    owner that never hands it back.
    """
    every = "\n".join(texts)
    return sorted({"%s %s" % (type_name, name)
                   for type_name, name in CF_PROPERTY.findall(every)
                   if not re.search(r"\w*Release\(\s*(?:self\.|_)?%s\s*\)" % re.escape(name),
                                    every)})


objc_texts = [text for _path, text in compiled_sources(root)] + \
             [open(os.path.join(directory, name), encoding="utf-8").read()
              for directory, _, names in os.walk(os.path.join(root, "Limelight"))
              for name in sorted(names) if name.endswith(".h")]
unowned_properties = unreleased_cf_properties(objc_texts)
check(not unowned_properties,
      "a CoreFoundation-typed property is released by whoever owns the object"
      if not unowned_properties else
      "nobody releases: " + ", ".join(unowned_properties[:4]))
check(unreleased_cf_properties(["@property (nonatomic) CFReadStreamRef plantedStream;"])
      == ["CFReadStreamRef plantedStream"],
      "a CF property nobody releases trips the rule above")

# Repeating timers are a third handle family that fails silently, and silently in a
# way the two above do not: nothing leaks, the poll just stops answering.
#
# A repeating timer fires only while its run loop runs in a mode it was added to.
# +scheduledTimerWithTimeInterval: adds to the current run loop in NSDefaultRunLoopMode,
# and this app leaves that mode mid-session by name: a modal session runs in
# NSModalPanelRunLoopMode and a menu or a window drag in NSEventTrackingRunLoopMode.
# The counts are scripts/timer-registration-tests.py -- 15 ticks in 300ms for a poll
# added to the main run loop in the common modes, 0 for one left in the default mode,
# both measured against the same 15 while the loop runs in the default mode.

REPEATING = re.compile(r"repeats:YES")
NAMED_TIMER = re.compile(r"([*]?[A-Za-z_][\w.]*)\s*=\s*$")


def unregistered_repeating_timers(source_path, text):
    """Repeating timers that cannot fire in every mode the app runs its loop in."""
    problems = []
    for match in REPEATING.finditer(text):
        head = text.rfind("[NSTimer", 0, match.start())
        line = "%s:%d" % (os.path.basename(source_path), text.count("\n", 0, head) + 1)
        if head == -1:
            problems.append("%s repeats:YES with no [NSTimer creation in front of it" % line)
            continue
        if "scheduledTimerWithTimeInterval" in text[head:match.end()]:
            problems.append("%s schedules a repeating timer, which registers it in one"
                            " run loop mode" % line)
            continue
        named = NAMED_TIMER.search(text[max(0, head - 120):head])
        following = text[match.end():match.end() + 500]
        if named is None:
            problems.append("%s builds a repeating timer that nothing names" % line)
        elif not (re.search(r"addTimer:\s*%s\b" % re.escape(named.group(1).lstrip("*")),
                            following)
                  and "NSRunLoopCommonModes" in following):
            problems.append("%s adds a repeating timer outside the common modes" % line)
    return problems


mode_limited = [problem
                for source_path, text in compiled_sources(root)
                for problem in unregistered_repeating_timers(source_path, text)]
check(not mode_limited,
      "every repeating timer is added to a run loop in the modes this app leaves the"
      " default one for" if not mode_limited else
      "a repeating timer cannot fire in a mode it was not added to: "
      + "; ".join(mode_limited[:4]))

planted_scheduled_poll = ("- (void)startThePlantedPoll\n"
                         "{\n"
                         "    _plantedPollTimer = [NSTimer scheduledTimerWithTimeInterval:1.0\n"
                         "                                                          target:self\n"
                         "                                                        selector:@selector(tick:)\n"
                         "                                                        userInfo:nil\n"
                         "                                                         repeats:YES];\n"
                         "}\n")
planted_common_poll = ("- (void)startThePlantedPoll\n"
                       "{\n"
                       "    NSTimer *plantedPollTimer = [NSTimer timerWithTimeInterval:1.0\n"
                       "      repeats:YES block:^(NSTimer *timer) { }];\n"
                       "    [[NSRunLoop mainRunLoop] addTimer:plantedPollTimer\n"
                       "                              forMode:NSRunLoopCommonModes];\n"
                       "}\n")
scheduled_tripped = unregistered_repeating_timers("planted.m", planted_scheduled_poll)
common_cleaned = unregistered_repeating_timers("planted.m", planted_common_poll)
check(len(scheduled_tripped) == 1 and not common_cleaned,
      "a repeating timer left in one run loop mode trips the rule above"
      if len(scheduled_tripped) == 1 and not common_cleaned else
      "the run loop mode rule does not see the poll it was written for")

# The other half of the same family is who a repeating timer outlives. The run loop
# retains a timer that repeats, and that timer retains the object it names as its
# target, so an object polled by its own repeating timer cannot reach dealloc to stop
# it -- scripts/timer-registration-tests.py measured the target of one alive and still
# ticking after the last reference outside the timer went away. A stop that lives only
# in dealloc is therefore not a stop; it is a claim about a path that does not run.

CREATED_TIMER = re.compile(r"(?<![\w*.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w+)?)\s*=\s*\[NSTimer")
STOPPED_TIMER = re.compile(r"\[(?:self\.|_)?(\w*[Tt]imer\w*)\s+invalidate\]")


def held_timer_names(text):
    """Names an object keeps a *repeating* timer under.

    Two readings this went through. The first collected every `[NSTimer ...]` an object
    stored, which reached eleven names, and asked for a reachable stop on each -- more than
    the premise of the rule can pay for. A one-shot timer releases its target when it fires,
    so demanding a stop for one is a refusal the measurement does not support, and a rule
    that refuses things it never claimed to be about is how a gate gets walked past. So the
    question asked of each creation is whether it repeats.

    The second reading is why creation-site reading alone is not enough: the shape the
    pointer fix uses builds the timer as a local so its block can name it, hands it to the
    run loop, then stores it -- `_mouseTimer = pointerPoll;`. Reading only the assignment
    would call that invisible, and the object would hold a repeating timer no rule could
    trace to a stop.
    """
    held = set()
    for match in CREATED_TIMER.finditer(text):
        if not REPEATING.search(text[match.end():match.end() + 400]):
            continue
        name = match.group(1)
        held.add(name[5:] if name.startswith("self.") else name.lstrip("_"))
    for match in REPEATING.finditer(text):
        head = text.rfind("[NSTimer", 0, match.start())
        named = NAMED_TIMER.search(text[max(0, head - 120):head]) if head != -1 else None
        if named is None or "*" not in named.group(1) and not named.group(1).startswith("*"):
            continue          # only a local, `NSTimer *name = `, hands a timer to a store
        local = named.group(1).lstrip("*")
        stored = re.search(r"(?<![\w*.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w+)?)\s*=\s*%s\s*;"
                           % re.escape(local), text[match.end():match.end() + 800])
        if stored is not None:
            name = stored.group(1)
            held.add(name[5:] if name.startswith("self.") else name.lstrip("_"))
    return held


def timers_without_a_reachable_stop(pairs):
    """Timers an owner holds, stopped nowhere but in its own dealloc."""
    held, stopped_early, stopped_late = set(), set(), set()
    for source_path, text in pairs:
        held.update(held_timer_names(text))
        for body in method_bodies(text):
            stopped = STOPPED_TIMER.findall(body)
            if not stopped:
                continue
            if body.split("\n")[0].startswith("- (void)dealloc"):
                stopped_late.update(stopped)
            else:
                stopped_early.update(stopped)
    return sorted(name for name in held if name not in stopped_early)


never_stopped = timers_without_a_reachable_stop(list(compiled_sources(root)))
check(not never_stopped,
      "an object holding a repeating timer stops it on a path that can run"
      if not never_stopped else
      "only a dealloc that cannot run stops: " + ", ".join(never_stopped[:4]))

planted_late_stop = ("- (void)startThePlantedPoll\n"
                     "{\n"
                     "    _plantedPollTimer = [NSTimer timerWithTimeInterval:1.0 repeats:YES\n"
                     "                              block:^(NSTimer *timer) { }];\n"
                     "    [[NSRunLoop mainRunLoop] addTimer:_plantedPollTimer\n"
                     "                              forMode:NSRunLoopCommonModes];\n"
                     "}\n"
                     "- (void)dealloc\n"
                     "{\n"
                     "    [_plantedPollTimer invalidate];\n"
                     "}\n")
planted_early_stop = ("- (void)stopThePlantedPoll\n"
                      "{\n"
                      "    [_plantedPollTimer invalidate];\n"
                      "    _plantedPollTimer = nil;\n"
                      "}\n"
                      "- (void)dealloc\n"
                      "{\n"
                      "    [_plantedPollTimer invalidate];\n"
                      "}\n")
planted_single_shot = ("- (void)queueThePlantedThing\n"
                       "{\n"
                       "    _plantedOneShotTimer = [NSTimer scheduledTimerWithTimeInterval:1.0\n"
                       "                                                             repeats:NO\n"
                       "                                                               block:^(NSTimer *timer) { }];\n"
                       "}\n")
late_only = timers_without_a_reachable_stop([("planted.m", planted_late_stop)])
early_too = timers_without_a_reachable_stop([("planted.m", planted_early_stop)])
single_shot = timers_without_a_reachable_stop([("planted.m", planted_single_shot)])
check(late_only == ["plantedPollTimer"] and not early_too and not single_shot,
      "a repeating timer stopped only by a dealloc that cannot run trips the rule above,"
      " and a one-shot, which releases its target by firing, does not"
      if late_only == ["plantedPollTimer"] and not early_too and not single_shot else
      "the reachable stop rule answers wrong: late=%s early=%s one-shot=%s"
      % (late_only, early_too, single_shot))

# Block observers are the fourth handle family, and the one whose owner is wrong: the
# notification centre holds the block, so the object that registered it is not the thing
# deciding whether it keeps answering. scripts/notification-observer-tests.py measured
# what that costs. One post reaches every block registered for a name, so two registrations
# answer one event twice. Writing a fresh token over an old one leaves the old block
# registered and unreachable, because the owner has nothing left to name it with. And
# -removeObserver:name:object: withdraws a selector observer while leaving a tokenless
# block in place, so a token that was never stored can never be withdrawn.
#
# The premise that turns those facts into a defect is that a registration can run twice.
# It measured that too: the same view controller heard -viewDidAppear once per show across
# three parent changes, and heard it again after its window was hidden and shown again. Two
# shipped controllers registered block observers on exactly that path, which is what this
# rule now refuses. -viewDidLoad is not on the list because nothing measured it, and a rule
# that refuses a path nobody watched is a rule somebody has to work around later.

REPEATING_LIFECYCLE = re.compile(r"^[-+]\s*\(\s*void\s*\)\s*(viewDidAppear|viewWillAppear)\b")
BLOCK_REGISTRATION = re.compile(r"addObserverForName:(?:.|\n)*?usingBlock:")
TOKEN_WITHDRAWAL = re.compile(r"removeObserver:|\[\s*(?:self|weakSelf)\s+\w*[Rr]emove\w*\b")


def statement_span(text, index):
    """The whole message send an observer registration is part of.

    A registration spans lines in this tree -- the receiver sits on the line above the
    name -- so reading one line either way would call a stored token a discarded one. The
    span runs back to the last statement boundary and forward to the first semicolon, which
    is short of a parser but enough to answer the only question asked here: does anything on
    this statement keep the return value.
    """
    end = text.find(";", index)
    if end < 0:
        end = len(text)
    start = index
    while start > 0 and text[start - 1] not in ";{}\n":
        start -= 1
    if not text[start:index].strip():
        head = index
        while head > 0 and text[head - 1] not in ";{}":
            head -= 1
        start = head
    return text[start:end]


def registration_is_stored(text, index):
    """Whether the token a registration returns is kept by something."""
    span = statement_span(text, index)
    before = span[:span.find("addObserverForName:")]
    return re.search(r"(?<![=!<>])=(?!=)|\breturn\b", before) is not None


def observers_registered_twice(source_path, text):
    """Block observers registered on a lifecycle path AppKit runs again."""
    problems = []
    for body in method_bodies(text):
        lifecycle = REPEATING_LIFECYCLE.match(body.split("\n")[0])
        if lifecycle is None:
            continue
        offset = text.find(body)
        for match in BLOCK_REGISTRATION.finditer(body):
            if TOKEN_WITHDRAWAL.search(body[:match.start()]):
                continue
            line = "%s:%d" % (os.path.basename(source_path),
                              text.count("\n", 0, max(0, offset) + match.start()) + 1)
            problems.append("%s registers a block observer in -%s without withdrawing the"
                            " token it already holds" % (line, lifecycle.group(1)))
    return problems


def observers_nobody_can_withdraw(source_path, text):
    """Block observers whose token was thrown away on the spot."""
    problems = []
    for match in re.finditer(r"addObserverForName:", text):
        if registration_is_stored(text, match.start()):
            continue
        problems.append("%s:%d keeps no token for a block observer"
                        % (os.path.basename(source_path), text.count("\n", 0, match.start()) + 1))
    return problems


twice_registered = [problem
                    for source_path, text in compiled_sources(root)
                    for problem in observers_registered_twice(source_path, text)]
check(not twice_registered,
      "no block observer is registered on a path AppKit runs a second time without removing"
      " the one already held" if not twice_registered else
      "a repeated pass registered a second observer for the same event: "
      + "; ".join(twice_registered[:4]))

never_withdrawn = [problem
                   for source_path, text in compiled_sources(root)
                   for problem in observers_nobody_can_withdraw(source_path, text)]
check(not never_withdrawn,
      "every block observer keeps the token it has to be removed with"
      if not never_withdrawn else
      "nothing can unregister these, because -removeObserver: does not reach a block: "
      + "; ".join(never_withdrawn[:4]))

planted_repeat_registration = (
    "- (void)viewDidAppear\n"
    "{\n"
    "    __weak typeof(self) weakSelf = self;\n"
    "    _plantedObserver = [[NSNotificationCenter defaultCenter]"
    " addObserverForName:@\"PlantedNotification\"\n"
    "        object:nil queue:nil usingBlock:^(NSNotification *note) { [weakSelf tick]; }];\n"
    "}\n")
planted_withdrawn_registration = (
    "- (void)viewDidAppear\n"
    "{\n"
    "    __weak typeof(self) weakSelf = self;\n"
    "    if (_plantedObserver != nil) {\n"
    "        [[NSNotificationCenter defaultCenter] removeObserver:_plantedObserver];\n"
    "        _plantedObserver = nil;\n"
    "    }\n"
    "    _plantedObserver = [[NSNotificationCenter defaultCenter]"
    " addObserverForName:@\"PlantedNotification\"\n"
    "        object:nil queue:nil usingBlock:^(NSNotification *note) { [weakSelf tick]; }];\n"
    "}\n")
planted_removal_through_a_helper = (
    "- (void)viewDidAppear\n"
    "{\n"
    "    __weak typeof(self) weakSelf = self;\n"
    "    [self removePlantedObservers];\n"
    "    _plantedObserver = [[NSNotificationCenter defaultCenter]"
    " addObserverForName:@\"PlantedNotification\"\n"
    "        object:nil queue:nil usingBlock:^(NSNotification *note) { [weakSelf tick]; }];\n"
    "}\n")
planted_view_did_load = planted_repeat_registration.replace("viewDidAppear", "viewDidLoad")
planted_discarded_token = (
    "- (void)startListening\n"
    "{\n"
    "    [[NSNotificationCenter defaultCenter] addObserverForName:@\"PlantedNotification\"\n"
    "        object:nil queue:nil usingBlock:^(NSNotification *note) { [self tick]; }];\n"
    "}\n")
planted_stored_token = (
    "- (void)startListening\n"
    "{\n"
    "    _plantedObserver = [[NSNotificationCenter defaultCenter]"
    " addObserverForName:@\"PlantedNotification\"\n"
    "        object:nil queue:nil usingBlock:^(NSNotification *note) { [self tick]; }];\n"
    "}\n")
planted_stored_on_the_line_above = (
    "- (void)startListening\n"
    "{\n"
    "    _plantedObserver = [[NSNotificationCenter defaultCenter]\n"
    "        addObserverForName:@\"PlantedNotification\"\n"
    "        object:nil queue:nil usingBlock:^(NSNotification *note) { [self tick]; }];\n"
    "}\n")

repeat_tripped = observers_registered_twice("planted.m", planted_repeat_registration)
repeat_cleaned = observers_registered_twice("planted.m", planted_withdrawn_registration)
helper_cleaned = observers_registered_twice("planted.m", planted_removal_through_a_helper)
load_view = observers_registered_twice("planted.m", planted_view_did_load)
check(len(repeat_tripped) == 1 and not repeat_cleaned and not helper_cleaned
      and not load_view,
      "a block observer registered on a second pass without a withdrawal trips the rule"
      " above, and a withdrawal either way clears it"
      if len(repeat_tripped) == 1 and not repeat_cleaned and not helper_cleaned
      and not load_view else
      "the repeated registration rule answers wrong: raw=%s withdrawn=%s helper=%s"
      " did-load=%s" % (len(repeat_tripped), repeat_cleaned, helper_cleaned, load_view))

discarded_tripped = observers_nobody_can_withdraw("planted.m", planted_discarded_token)
stored_cleaned = observers_nobody_can_withdraw("planted.m", planted_stored_token)
split_cleaned = observers_nobody_can_withdraw("planted.m", planted_stored_on_the_line_above)
check(len(discarded_tripped) == 1 and not stored_cleaned and not split_cleaned,
      "a block observer whose token is thrown away trips the rule above, whether the"
      " assignment sat on the same line or the one before"
      if len(discarded_tripped) == 1 and not stored_cleaned and not split_cleaned else
      "the discarded token rule answers wrong: discarded=%s stored=%s split=%s"
      % (discarded_tripped, stored_cleaned, split_cleaned))

dealloc_body = method_body(hid_all, "- (void)dealloc")
check("CFRelease(_hidManager);" in dealloc_body,
      "the HID manager cannot outlive the object its run loop callbacks point into")
problem = ordered_once(dealloc_body, "IOHIDManagerUnscheduleFromRunLoop(",
                       "CFRelease(_hidManager)", "unscheduling the HID manager")
check(problem is None, "the HID manager is unscheduled before it is released"
      if problem is None else "the dealloc net is not ordered: " + problem)

# The display link is the same shape of object one property later: an assign CFReference
# plus a C callback whose context is this object. Its callback runs on the display link's
# own thread and converts that context back into a strong reference without asking, so a
# link still running after the object is gone is a crash waiting for a frame rather than
# a leak. Every path that drops an HIDSupport stops it through tearDownHidManager today,
# which is why this is a net and not a repair -- and a net is only worth having because
# "every path" is a claim about code that has not been written yet.
check("CVDisplayLinkRelease(_displayLink);" in dealloc_body,
      "the display link cannot outlive the object its callback thread points into")
stopped_first = ordered_once(dealloc_body, "CVDisplayLinkStop(_displayLink);",
                             "CVDisplayLinkRelease(_displayLink);",
                             "stopping the display link")
check(stopped_first is None, "the display link is stopped before it is released"
      if stopped_first is None else "the display link net is not ordered: " + stopped_first)

# Every path that stops a stream relies on tearing the keyboard state down
# first, because -releaseAllHeldKeys needs a live input context to tell the host
# to let go. All four call sites do that today, and -beginStopStreamIfNeededWith
# Reason itself switches forwarding off and NULLs the context, so a call site
# added without the teardown would leave the host believing a key is pressed
# forever, with no log and no visible failure in the app that stopped.
stop_calls = re.compile(r"\[(?:self|weakSelf)\s+beginStopStreamIfNeededWithReason")
stopping_without_release = []
for relative in ("macOS/ViewControllers/StreamViewController.m",
                 "macOS/ViewControllers/StreamViewController+WindowModes.m"):
    text = open(os.path.join(root, "Limelight", relative), encoding="utf-8").read()
    for body in method_bodies(text):
        if "beginStopStreamIfNeededWithReason" in body.split("\n")[0]:
            continue  # the forwarder is not a decision point
        call = stop_calls.search(body)
        if not call:
            continue
        released = body.find("tearDownKeyboardStateForSessionEnd")
        if released < 0 or released > call.start():
            stopping_without_release.append("%s: %s" % (relative.split("/")[-1],
                                                        body.split("\n")[0].strip()[:60]))
check(not stopping_without_release,
      "a stream that stops never leaves a key down on the host"
      if not stopping_without_release else
      "stops the stream without releasing held keys first: " + "; ".join(stopping_without_release))

# A gate nobody wired is worse than no gate: it sits in scripts/ looking like
# coverage while CI never runs it. Every audit and harness has to be reachable
# from the workflow, directly or through another reachable script, because one
# gate legitimately drives another (release-gate --self-test runs the preparation
# fixtures, and the preparation step exists only to satisfy that gate).
scripts_dir = os.path.join(root, "scripts")
gate_names = sorted(n for n in os.listdir(scripts_dir)
                    if n.endswith(("-audit.py", "-tests.py", "-probe.py"))
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

# A local verdict that means less than CI's is not a verdict. The audits job runs
# five audit scripts and the local habit exercised two of them, so a source file
# that belonged to no target read as green here, reached a runner, and failed eight
# minutes before a release; the same shape then cost a second round, because the
# build jobs ran a probe harness that no local command ran either. The workflow is
# now the specification: every gate script it names has to be run here, or be named
# below with the thing that makes it impossible to run here. A reason that stops
# being true fails the same way an expired library card does.
CI_ONLY = {
    # script: a marker that has to stay true in that script for the excuse to hold
    "compiled-source-audit.py": "Mach-O",
    "render-probe.py": "xcodebuild",
    # The notch consumer is compiled and run, so it needs Apple's toolchain, which
    # this job's runner does not have. The two macOS build jobs run it for real.
    "scroll-notch-consumption-tests.py": "macOS SDK",
    "relative-pointer-gain-tests.py": "macOS SDK",
    "discrete-scroll-click-tests.py": "macOS SDK",
    "controller-mouse-emulation-tests.py": "macOS SDK",
    # The excuse is thinner here than the others and worth reading exactly: the script runs
    # anywhere, and what it cannot do is invent its own input. It reads the transcript a build
    # left behind, and local-gates.sh has no build to hand it, so the step skips on a laptop and
    # the human has to point it at a log after building -- which is precisely what did not
    # happen once: a warning sat in a first-party Swift file, every local gate was green, the
    # local build log contained the line, and the check that reads such logs was inline shell in
    # the build job and therefore invisible to the local list. Run it against your own log.
    "build-warning-audit.py": "xcodebuild log",
}
gates_in_workflow = sorted(set(re.findall(r"python3 scripts/([\w.\-]+\.py)", pipeline))
                           - {"constraints-audit.py"})
here = open(os.path.join(root, "scripts", "constraints-audit.py"),
            encoding="utf-8").read().splitlines()
not_run_here = [name for name in gates_in_workflow
                if name not in CI_ONLY
                and not any(name in line and INVOKES.search(line) for line in here)]
stale_excuses = [name for name, marker in sorted(CI_ONLY.items())
                 if name in gates_in_workflow
                 and marker not in open(os.path.join(scripts_dir, name),
                                        encoding="utf-8").read()]
# A changelog round that says a script "is now a step in both macOS build jobs" is a
# claim about the pipeline, and one made exactly that claim while the step existed in
# neither the commit nor the file: the reachability rule above accepts the assertion
# battery naming a gate as a mutation judge, which is honest wiring for a gate but is
# not a build step. Where the prose names a script and a job, the workflow has to name
# the script too, or the sentence is a claim nobody checked.
changelog_text = open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8").read()
# The file is hard-wrapped at eighty columns, so a sentence is not a line and a
# phrase is not contiguous: matching against the raw text would miss exactly the
# claims this is looking for, because the wrap lands in the middle of them. Fold each
# paragraph back into one line first.
claimed_steps = set()
for paragraph in changelog_text.split("\n\n"):
    folded = " ".join(line.strip() for line in paragraph.splitlines() if line.strip())
    for sentence in re.split(r"(?<=[.!?])\s+", folded):
        if "step in both macOS build jobs" in sentence or "step in the workflow" in sentence:
            claimed_steps.update(re.findall(r"scripts/([\w.\-]+\.py)", sentence))
not_a_step = sorted(name for name in claimed_steps
                    if ("python3 scripts/%s" % name) not in pipeline
                    and os.path.exists(os.path.join(scripts_dir, name)))
check(not not_a_step,
      "every changelog claim about a build step names a step the workflow runs"
      if not not_a_step else
      "the changelog says these run in the build jobs but the workflow never runs them: "
      + ", ".join(not_a_step))

# The shape of the changelog is a fact a rewrite can destroy. One rewrite this round
# swallowed the tail of the file: seven rounds and every released-version section went
# away, and the rule above stayed green because it reads sentences rather than
# structure. Rounds are numbered, so the numbering is the part a truncation cannot
# survive, and a release section without its date is the next thing a truncation drops.
round_numbers = [int(n) for n in re.findall(r"^### Round (\d+):", changelog_text, re.M)]
shape_problems = []
if round_numbers:
    gaps = sorted(set(range(min(round_numbers), max(round_numbers) + 1)) - set(round_numbers))
    repeats = sorted({n for n in round_numbers if round_numbers.count(n) > 1})
    if gaps:
        label = "round" if len(gaps) == 1 else "rounds"
        verb = "is" if len(gaps) == 1 else "are"
        shape_problems.append("%s %s %s gone from the changelog"
                              % (label, ", ".join(str(g) for g in gaps), verb))
    if repeats:
        shape_problems.append("rounds %s are written twice" % ", ".join(str(r) for r in repeats))
sections = [line for line in changelog_text.splitlines() if line.startswith("## [")]
if not sections or sections[0] != "## [Unreleased]":
    shape_problems.append("the changelog no longer opens with the Unreleased section")
released = sections[1:]
undated = [line for line in released
           if not re.match(r"^## \[[\w.\-]+\] - \d{4}-\d{2}-\d{2}$", line)]
if undated:
    shape_problems.append("a released section lost its date: " + ", ".join(undated))
# A doubled bullet is the same class of rewrite accident, in a shape none of the
# rules above can see: a hand-written "- " in front of a generator that already adds
# one leaves a line no markdown renderer reads as a list item, and three of them
# survived here while every rule stayed green, because those rules read sentences and
# section headings and never the bullet itself.
def doubled_bullets(text):
    return [n for n, line in enumerate(text.splitlines(), 1) if line.startswith("- - ")]


def entry_shape_problems(text):
    doubled = doubled_bullets(text)
    if doubled:
        return ["a changelog entry has a doubled bullet on line%s %s"
                % ("s" if len(doubled) > 1 else "", ", ".join(str(n) for n in doubled))]
    return []


shape_problems += entry_shape_problems(changelog_text)
dates = [line[-10:] for line in released]
if dates != sorted(dates, reverse=True):
    shape_problems.append("the released sections are no longer in date order")
check(not shape_problems,
      "the changelog has every round once and every release section dated"
      if not shape_problems else "; ".join(shape_problems))

# The changelog is clean today, so a rule that passes on it has proved nothing. The
# defect gets planted, and the rule has to see exactly it.
planted = "- - **planted for the rule that looks for this**\n\n" + changelog_text
check(entry_shape_problems(changelog_text) == [] and
      len(entry_shape_problems(planted)) == 1 and
      "line 1" in entry_shape_problems(planted)[0],
      "a doubled changelog bullet is refused"
      if entry_shape_problems(planted) and entry_shape_problems(changelog_text) == []
      else "the doubled-bullet rule does not see the one it was written for")

parity_problems = []
if not gates_in_workflow:
    parity_problems.append("the workflow names no gate script at all")
if not_run_here:
    parity_problems.append("CI runs a gate no local command runs: " + ", ".join(not_run_here))
if stale_excuses:
    parity_problems.append("the reason for running it only on CI has stopped being true: "
                           + ", ".join(stale_excuses))
check(not parity_problems,
      "every gate the workflow runs is wired into the local aggregate"
      if not parity_problems else "; ".join(parity_problems))

# The parity above points one way only. Its mirror is the failure this repository
# has not yet been able to see: a gate sits in scripts/, the aggregate still
# invokes it, and the reachability rule is satisfied by that invocation -- so the
# day somebody deletes the workflow step that ran it, every check stays green
# while CI has stopped running a guard on exactly the commits it exists to
# protect. Reachability that bottoms out at the aggregate is only honest while the
# driver is itself named by a step, so the gates that lean on that are written out
# with their driver instead of absorbed into a rule that would prove nothing.
DRIVEN_BY = {
    "assertion-battery.py": "constraints-audit.py",
    "prepare-release.py": "release-gate.py",
    "shortcut-menu-key-tests.py": "constraints-audit.py",
    # A gate that needs a real clang and a macOS SDK cannot run in the Ubuntu audits
    # job, so it has to be invoked from a macOS step. Its own step would need a push
    # credential carrying the `workflow` scope, which this one does not, so the aspect
    # fit gate rides the neighbouring renderer harness -- which is a step on every
    # macOS build -- and that is what is written down here. The rule this satisfies is
    # the one that refuses a gate reachable only through an aggregate whose own step
    # has quietly disappeared: follow this entry and you land on a step CI runs twice.
    "aspect-fit-presentation-tests.py": "scaling-output-evidence-tests.py",
    # The same argument, one gate later: the device redirection policy is Objective-C, so
    # its harness needs the macOS job's clang and SDK, and its own step would need the
    # `workflow` scope the pushing credential does not carry. The driver below is a step on
    # every macOS build, and it invokes this one.
    "device-redirection-policy-tests.py": "scaling-output-evidence-tests.py",
    # Third gate with the same shape of reason: the pointer entry decision is C called from
    # Objective-C, so its harness needs a macOS clang and SDK, and a step of its own needs
    # the `workflow` scope the pushing credential does not carry.
    "pointer-entry-takeover-tests.py": "scaling-output-evidence-tests.py",
    # Fourth gate of the same shape, and the same two reasons: the enumeration reads a
    # registry identity in Objective-C, so its harness needs the macOS clang and SDK, and a
    # step of its own needs the `workflow` scope the pushing credential does not carry.
    "usb-device-enumeration-tests.py": "scaling-output-evidence-tests.py",
    # Same shape again: the exposure answer is C inside the renderer, so its harness wants the
    # macOS clang and SDK, and its own step wants the `workflow` scope this credential lacks.
    "hdr-sdr-exposure-tests.py": "scaling-output-evidence-tests.py",
    # Not the clang reason again: this gate reads Swift text and needs no toolchain. It needs
    # a CI step, and a step needs the `workflow` scope the pushing credential does not carry,
    # so it rides the driver below it -- which is a step on every macOS build, and invokes it.
    "settings-rebuild-passthrough-tests.py": "scaling-output-evidence-tests.py",
    # Fourth gate of the same shape: the gamepad Menu gesture is C compiled by a harness,
    # so it needs the macOS job's clang and SDK, and a step of its own needs the `workflow`
    # scope the pushing credential does not carry. The driver below is a step on every
    # macOS build, and it invokes this one.
    "gamepad-menu-gesture-tests.py": "scaling-output-evidence-tests.py",
    # Same shape a fifth time: the Command mapping is Objective-C that only the macOS SDK
    # can compile, so its harness runs where the toolchain is, and its own CI step would
    # need the `workflow` scope the pushing credential does not carry.
    "command-to-control-tests.py": "scaling-output-evidence-tests.py",
    # Reads Swift and Objective-C text and needs no toolchain, but a gate still needs a CI
    # step to run it, and a step needs the `workflow` scope this credential does not carry.
    "sas-preset-tests.py": "scaling-output-evidence-tests.py",
    # Same shape again: Objective-C compiled against the macOS SDK, so the harness runs
    # where the toolchain is, and a step of its own would need the `workflow` scope the
    # pushing credential does not carry.
    "sdr-10bit-codec-tests.py": "scaling-output-evidence-tests.py",
    # Stage 2's client half, same shape and same two reasons: Objective-C against the macOS SDK,
    # and no `workflow` scope on this credential for a step of its own. Worth noting what it is
    # a gate over -- no host implements the three exchanges, so this one pins the sequencing
    # rather than the wire, which is exactly the part that can be wrong today and right later.
    "device-redirection-session-tests.py": "scaling-output-evidence-tests.py",
    # Stage 3's logic, same shape and the same two reasons: Objective-C against the macOS SDK, and
    # no `workflow` scope on this credential for a step of its own. It is the counterpart of the
    # entry below it -- that one refuses an unsigned artefact, this one refuses a lifecycle that
    # would pretend an artefact nobody can load is working.
    "driver-lifecycle-tests.py": "scaling-output-evidence-tests.py",
    # The measurement that says the obvious implementation is wrong -- the interface iterator
    # returned 11 of the 16 interfaces the devices named under themselves -- is Objective-C
    # against a live bus, so it needs the macOS clang, SDK, and hardware, and a step of its own
    # would need the `workflow` scope this credential does not carry.
    "usb-bus-snapshot-tests.py": "scaling-output-evidence-tests.py",
    # What a build may claim about its own signature. The classifier is built against three
    # generated certificates plus the harness's own ad-hoc signature, so it needs Security.framework
    # and a codesign-capable runner; a step of its own needs the scope that is missing here.
    "code-signature-profile-tests.py": "scaling-output-evidence-tests.py",
    # The devices panel: the same two reasons, and one more worth writing down. The panel is the
    # first part of this feature a player touches, so it is the first place where four independent
    # preconditions have to be checked together rather than one at a time -- and the gate rides a
    # driver that runs on every macOS build rather than waiting for a step nobody can add.
    "device-redirection-panel-model-tests.py": "scaling-output-evidence-tests.py",
    # Reads the committed file list and the workflow text, so no toolchain is missing here; the
    # missing thing is a CI step, and a step needs the `workflow` scope this credential lacks.
    "driver-extension-signing-audit.py": "scaling-output-evidence-tests.py",
    # The report is Objective-C plus a compiled harness, so it needs the macOS clang and SDK,
    # and a step of its own would need the `workflow` scope this credential does not carry.
    # It is also the gate that decides whether a pairing PIN can reach an issue, so it rides
    # a driver that runs on every macOS build instead of waiting for a step nobody can add.
    "diagnostics-report-tests.py": "scaling-output-evidence-tests.py",
    # The two closures the settings page hands its model, compiled as they stand to count
    # whether the model is released, so it needs a swiftc and an SDK and a step of its own
    # needs the `workflow` scope this credential does not carry. It rides the driver for
    # that reason and stays for a better one: this is the gate that says the weak capture
    # above it is holding up a real cycle rather than satisfying a spelling rule.
    "settings-callback-ownership-tests.py": "scaling-output-evidence-tests.py",
    # Same arrangement again, one gate later: this one compiles four repeating timers and runs
    # them against a real AppKit, so it needs the macOS job's clang, SDK and run loop, and a
    # step of its own needs the `workflow` scope the pushing credential does not carry.
    "timer-registration-tests.py": "scaling-output-evidence-tests.py",
    # One gate later and the shape repeats: block observers are counted against a real
    # AppKit run loop and a real window, so this harness needs the macOS job's clang, SDK
    # and NSApplication, and a step of its own needs the `workflow` scope this pushing
    # credential does not carry.
    "notification-observer-tests.py": "scaling-output-evidence-tests.py",
}
named_by_a_step = {name for name in gate_names
                   if re.search(r"scripts/" + re.escape(name), pipeline) is not None}
unrun_gates = sorted(set(gate_names) - named_by_a_step - set(CI_ONLY) - set(DRIVEN_BY))
check(not unrun_gates,
      "a CI step runs every gate in scripts"
      if not unrun_gates else "no CI step runs these gates any more: "
      + ", ".join(unrun_gates))

for driven, driver in sorted(DRIVEN_BY.items()):
    driver_lines = open(os.path.join(scripts_dir, driver),
                        encoding="utf-8").read().splitlines()
    driver_is_a_step = re.search(r"scripts/" + re.escape(driver),
                                 pipeline) is not None
    # An invoked line is not the same thing as an invoked gate. Wiring the usb enumeration
    # gate here produced exactly that: the subprocess.run sat inside a function the driver's
    # finish() never called, every text check passed, and the only thing that caught it was
    # reading the driver's own output for a line that never appeared. So the call is now
    # followed up to the def that owns it, and that def has to be called somewhere too.
    call_line = next((i for i, line in enumerate(driver_lines)
                      if driven in line and INVOKES.search(line)), None)
    owner = next((line[4:].split("(")[0].strip()
                  for line in reversed(driver_lines[:call_line]) if line.startswith("def "))
                 if call_line is not None else None)
    owner_is_called = owner is not None and sum(
        1 for line in driver_lines
        if re.search(r"\b" + re.escape(owner) + r"\(", line)) >= 2
    driver_invokes_it = call_line is not None and owner_is_called
    check(driver_is_a_step and driver_invokes_it,
          "%s is driven by %s, and that driver is a CI step" % (driven, driver)
          if driver_is_a_step and driver_invokes_it else
          "%s claims %s as its driver, but that gate is not a CI step, or the call "
          "sits in a function nothing reaches" % (driven, driver))

# --- a header has to be able to name the type it declares -----------------
# GlassOverlayContainer.m compiled in its own harness while the app that owns it
# did not build at all: StreamViewController_Internal.h declared
# `GlassOverlayContainer *logOverlayContainer` without importing or
# forward-declaring the class, so every translation unit that reached that header
# failed to compile it. Nothing local could see that -- the harness builds the
# container, not the app's internal header, and a grep finds every word of that
# line present. It took a runner to notice, and the runner found it in a probe step
# rather than in a build that had already been reported green twice. A first-party
# class used as a property type now has to be reachable from that header's own
# imports, or forward-declared in it.
header_texts = {}
for base, _, files in os.walk(os.path.join(root, "Limelight")):
    for name in files:
        if name.endswith(".h"):
            path = os.path.join(base, name)
            header_texts[path] = open(path, encoding="utf-8", errors="replace").read()
headers_by_basename = {}
for path in header_texts:
    headers_by_basename.setdefault(os.path.basename(path), []).append(path)

declared_in = {}
for path, text in header_texts.items():
    for line in text.splitlines():
        # A category (`@interface NSNumber (F)`) reopens a class owned by somebody
        # else, so counting it as a declaration made 27 system types look
        # first-party and reported a header full of defects that compile fine.
        found = re.match(r"\s*@interface\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?::|\{|$)", line)
        if found:
            declared_in.setdefault(found.group(1), set()).add(path)


def first_party_imports(text):
    seen = []
    for match in re.finditer(r'#\s*(?:import|include)\s+"([^"]+)"', text):
        written = match.group(1)
        if written in header_texts:
            seen.append(written)
        else:
            unique = headers_by_basename.get(os.path.basename(written), [])
            if len(unique) == 1:
                seen.append(unique[0])
    return seen


def imports_reachable(path, seen=None):
    seen = set() if seen is None else seen
    reachable = set()
    for imported in first_party_imports(header_texts[path]):
        if imported in seen:
            continue
        seen.add(imported)
        reachable.add(imported)
        reachable |= imports_reachable(imported, seen)
    return reachable


# Every source file gets the prefix header, so its imports are visible everywhere.
prefix_header = re.search(r'GCC_PREFIX_HEADER = "?([^;"\n]+)"?;', project_text or "")
prefix_first_party = set()
if prefix_header and os.path.exists(os.path.join(root, prefix_header.group(1))):
    prefix_text = open(os.path.join(root, prefix_header.group(1)),
                       encoding="utf-8", errors="replace").read()
    prefix_first_party = {path for path in first_party_imports(prefix_text)
                          if path in header_texts}

blind_properties = []
for path, text in header_texts.items():
    visible = imports_reachable(path) | prefix_first_party
    forward = {entry.strip()
               for group in re.findall(r"@class\s+([^;]+);", text)
               for entry in group.split(",") if entry.strip()}
    own = set(re.findall(r"@interface\s+([A-Za-z_$][A-Za-z0-9_$]*)", text))
    for match in re.finditer(r"@property\s*(?:\([^)]*\)\s*)?([A-Z][A-Za-z0-9_$]*)\s*\*", text):
        declared = match.group(1)
        if (declared in declared_in and declared not in own and declared not in forward
                and not declared_in[declared] & visible):
            blind_properties.append("%s declares a %s property that its imports cannot see "
                                    "(%s owns that class)"
                                    % (os.path.relpath(path, root), declared,
                                       ", ".join(sorted(os.path.basename(owner)
                                                        for owner in declared_in[declared]))))
check(not blind_properties,
      "a header can only name a type it can actually see"
      if not blind_properties else "; ".join(sorted(set(blind_properties))))

# --- addressing and localization reach -------------------------------------
# The connection-timeout overlay has three buttons that pop up the stream menu's
# Window, Monitor and Quality submenus. The lookup used the words printed on the
# items: `if ([item.title isEqualToString:@"屏幕"])`. The titles come from the
# language table, so that comparison was true only in the Chinese interface, and in
# English the loop fell through, popUpMenuPositioningItem: was never called, and
# Resolution, Bitrate and Display Mode did nothing at all. No crash, no log line, no
# build failure: a check that looked for the word 屏幕 in the source would have been
# satisfied for the entire time the feature was broken for half the users. The
# contract is now an integer both sides honour, so both halves are required here --
# a lookup that matches nothing is indistinguishable from a menu nobody built.
menu_ui = open(os.path.join(root, "Limelight/macOS/ViewControllers/"
                            "StreamViewController+MenuUI.m"), encoding="utf-8").read()
diagnostics = open(os.path.join(root, "Limelight/macOS/ViewControllers/"
                                "StreamViewController+Diagnostics.m"), encoding="utf-8").read()

TAGGED_ITEMS = (("windowItem", "StreamMenuSectionWindow"),
                ("monitorItem", "StreamMenuSectionMonitor"),
                ("qualityItem", "StreamMenuSectionQuality"))
untagged = ["%s.tag = %s" % pair for pair in TAGGED_ITEMS
            if re.search(r"\b%s\.tag\s*=\s*%s\s*;" % pair, menu_ui) is None]
check(not untagged, "every stream submenu advertises the section it is addressed by"
      if not untagged else "menu items that advertise no section: " + ", ".join(untagged))

popup_body = method_body(diagnostics, "- (void)popUpStreamSubmenuForSection:(StreamMenuSection)"
                                      "section fromButton:(id)sender")
check("streamSubmenuForSection:" in popup_body and "popUpMenuPositioningItem" in popup_body,
      "the overlay resolves its submenu by section and still pops it up")

lookup_body = method_body(diagnostics, "- (NSMenu *)streamSubmenuForSection:"
                                       "(StreamMenuSection)section")
check("tag" in lookup_body and "isEqualToString" not in lookup_body,
      "the section lookup reads the tag and never the words on the item"
      if "tag" in lookup_body and "isEqualToString" not in lookup_body else
      "streamSubmenuForSection: is deciding by title again")

for section, _, _ in (("StreamMenuSectionWindow", 0, 0),
                      ("StreamMenuSectionMonitor", 0, 0),
                      ("StreamMenuSectionQuality", 0, 0)):
    check("[self popUpStreamSubmenuForSection:%s fromButton:sender]" % section in diagnostics,
          "the %s button asks for its section by name" % section)

# --- one compiler answer --------------------------------------------------
# Every behavioural harness needs a clang and an SDK. Four of them wrote the answer
# themselves and all four asked xcrun, so on a host whose Xcode license has not been
# accepted from a Terminal they refused to run -- not failed, refused -- and the tree
# looked untestable rather than testable by another route, because the Command Line
# Tools ship a clang and an SDK that need no such consent. The pairs matter: a compiler
# from one vendor and an SDK from the other produces "unknown architecture arm64e.x1"
# out of the linker, which reads as broken code and gets a gate silenced. One module
# answers now, and a harness that asks xcrun again has to be noticed here.
harnesses = sorted(name for name in os.listdir(os.path.join(root, "scripts"))
                   if name.endswith("-tests.py"))
asking_again = sorted(name for name in harnesses
                      if re.search(r"\bxcrun\b", open(os.path.join(root, "scripts", name),
                                                        encoding="utf-8").read())
                      and "apple_toolchain.clang_and_sdk" not in
                      open(os.path.join(root, "scripts", name), encoding="utf-8").read())
check(bool(harnesses) and not asking_again,
      "every behavioural harness takes its compiler from the one module"
      if harnesses and not asking_again else
      "harnesses that ask xcrun for themselves: " + (", ".join(asking_again)
                                                     or "none; no harness found at all"))

# --- every modifier edge answers to the tracker ---------------------------
# Two shipped defects shared one shape: a hand-written packet sequence pressed or
# released a modifier while the physical modifier tracker said something else.
# -syncKeyboardModifierStateForEvent: decides what to send by diffing the desired
# mask against that tracker, so an untracked edge is not a cosmetic surplus -- the
# diff comes out zero and the corrective press is never sent. The first of these made
# a double-click send a Win key; the second let a mouse-driven translation rule drop a
# held Shift mid-game, because the rule released a modifier the player never released
# (scripts/keyboard-shortcut-modifier-tests.py measures that one as packets).
# So any body that emits a modifier edge -- by literal virtual key or through
# HIDRemoteModifierKeyCode -- has to answer to the tracker: consult it, ask the
# ownership helper that consults it, or clear it before releasing everything.
def static_function_bodies(source, name):
    match = re.search(r"^static\s+[^\n;]*\b%s\s*\(" % re.escape(name), source, re.M)
    if match is None:
        return
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


MODIFIER_EDGE = re.compile(r"LiSendKeyboardEventCtx\s*\([^,]+,\s*"
                           r"(?:modifierKeyCode|HIDRemoteModifierKeyCode\(|0x(?:5B|5C|A[0-5]))")
ANSWERS_TO_TRACKER = ("keyboardRemoteModifierMask", "HIDSyntheticOwnedModifierMask",
                      "syncKeyboardModifierStateForEvent")
hid_source = open(os.path.join(root, "Limelight", "Input", "HIDSupport.m"),
                  encoding="utf-8").read()
bodies = list(method_bodies(hid_source)) + list(static_function_bodies(
    hid_source, "HIDDispatchSyntheticRemoteModifierTap"))
senders = [body for body in bodies if MODIFIER_EDGE.search(body)]
untracked = sorted({body.split("{", 1)[0].strip()
                    for body in senders if not any(marker in body for marker in ANSWERS_TO_TRACKER)})
check(bool(senders) and not untracked,
      "every body that sends a modifier edge answers to the modifier tracker (%d of them)"
      % len(senders) if senders and not untracked else
      "modifier edges the tracker cannot see: " + (", ".join(untracked)
                                                   or "no modifier edge found at all"))

# --- the modifier mapping, from both ends ----------------------------------
# KeyboardMapResolver is described in its own header as the only place modifier
# mapping is defined, and the mapping it defines is the thing people buy this
# branch for: Command to Win, Control to Ctrl, Option to Alt, Shift to Shift, each
# side to its own side. Nothing read it -- not a test, not a constraint, not one
# scenario naming KMR_. A table row pointing at the wrong side, two rows pointing at
# the same one, or a virtual key one digit off would all have shipped and come back
# as a report that the keyboard feels wrong in a game, which is the report that
# started this whole pass. The behavioural harness compiles the file and walks all
# eight keys; these are the shape checks that hold even where no compiler answers.
resolver_header = open(os.path.join(root, "Limelight/Input/KeyboardMapResolver.h"),
                       encoding="utf-8").read()
resolver_body = open(os.path.join(root, "Limelight/Input/KeyboardMapResolver.m"),
                     encoding="utf-8").read()

# Windows virtual keys for the eight modifier keys. Written here rather than read from
# the header, because comparing a table to itself proves nothing.
WINDOWS_VK = {"LSHIFT": 0xA0, "RSHIFT": 0xA1, "LCONTROL": 0xA2, "RCONTROL": 0xA3,
              "LALT": 0xA4, "RALT": 0xA5, "LWIN": 0x5B, "RWIN": 0x5C}
declared_vk = {name: int(value, 16) for name, value in
               re.findall(r"\bKMR_VK_(\w+)\s*=\s*(0x[0-9A-Fa-f]+)", resolver_header)}
wrong_vk = {name: hex(declared_vk.get(name, -1)) for name, want in WINDOWS_VK.items()
            if declared_vk.get(name) != want}
check(not wrong_vk, "the modifier virtual keys are the Windows ones"
      if not wrong_vk else "modifier virtual keys that are not the standard code: "
      + ", ".join("%s=%s" % item for item in sorted(wrong_vk.items())))

shifts = re.findall(r"\bKMR_Remote_(Left|Right)(Shift|Control|Alt|Meta)\s*=\s*1\s*<<\s*(\d+)",
                    resolver_header)
shift_numbers = [int(n) for _, _, n in shifts]
check(len(shift_numbers) == 8 and len(set(shift_numbers)) == 8,
      "each remote modifier bit occupies one distinct position"
      if len(shift_numbers) == 8 and len(set(shift_numbers)) == 8 else
      "remote modifier bits declared: %d, distinct: %d"
      % (len(shift_numbers), len(set(shift_numbers))))

table_rows = re.findall(r"(KMR_Remote_\w+)\s*,\s*//\s*(KMR_Phys_\w+)", resolver_body)
# (remote key, physical slot) in the order the table declares them, which is the
# order the enum gives the physical slots: a row that keeps its remote key but moves
# is a different key per slot, so the order is part of the assertion.
wanted_order = [("KMR_Remote_LeftShift", "KMR_Phys_LeftShift"),
                ("KMR_Remote_RightShift", "KMR_Phys_RightShift"),
                ("KMR_Remote_LeftControl", "KMR_Phys_LeftControl"),
                ("KMR_Remote_RightControl", "KMR_Phys_RightControl"),
                ("KMR_Remote_LeftAlt", "KMR_Phys_LeftOption"),
                ("KMR_Remote_RightAlt", "KMR_Phys_RightOption"),
                ("KMR_Remote_LeftMeta", "KMR_Phys_LeftCommand"),
                ("KMR_Remote_RightMeta", "KMR_Phys_RightCommand")]
check(table_rows == wanted_order,
      "the mapping table answers each physical modifier with its own remote key"
      if table_rows == wanted_order else
      "the mapping table reads %s, expected %s"
      % (table_rows or "nothing", wanted_order))
declared_remotes = [remote for remote, _ in table_rows]
duplicated_remote = sorted({r for r in declared_remotes
                            if declared_remotes.count(r) > 1})
check(len(table_rows) == len(set(declared_remotes)) == 8 and not duplicated_remote,
      "no two physical modifiers share a remote key and none is left out"
      if not duplicated_remote and len(table_rows) == 8 else
      "remote keys used more than once: " + (", ".join(duplicated_remote) or "none"))

# The header promises the flags path can only answer with the left key of each pair,
# because NSEvent modifier flags do not say which side went down. If it ever names a
# right-hand physical slot, that promise and the harness expectation both break.
flags_body = resolver_body[resolver_body.index("KMR_RemoteMaskForAppKitFlags"):]
flags_body = flags_body[:flags_body.index("\n}\n") + 3]
right_in_flags = sorted({m.group(0) for m in re.finditer(r"KMR_Phys_Right\w+", flags_body)})
check(len(right_in_flags) == 0 and flags_body.count("KMR_Phys_Left") == 4,
      "the flags path asks for the left key of each pair, never the right"
      if not right_in_flags and flags_body.count("KMR_Phys_Left") == 4 else
      "the flags path names %d left and %d right physical slots"
      % (flags_body.count("KMR_Phys_Left"), len(right_in_flags)))

# Logger.m writes a one-line summary when it suppresses a repeated warning, and the
# log browser folds those summaries into one row. The producer and the reader are in
# different files and used to be joined by a Chinese sentence: the reader asked whether
# the line contained 内重复, so rewording the summary in Logger.m switched the folding
# off with nothing printed anywhere to say so, and the comparison was made against
# prose in a language the reader had no reason to speak. Both halves now name the same
# ASCII marker, so the pair is checked as a pair: a marker changed on one side has to
# fail here rather than quietly cost a feature.
logger = open(os.path.join(root, "Limelight/Utility/Logger.m"), encoding="utf-8").read()
repeat_marker = "[curated] repeated "
written = re.search(r'@"(\[curated\][^"]*)"', logger)
check(written is not None and written.group(1).startswith(repeat_marker)
      and all(ord(ch) < 128 for ch in written.group(1)),
      "the summary Logger.m writes carries an ASCII marker"
      if written is not None and written.group(1).startswith(repeat_marker) else
      "the summary line no longer starts with %r as an ASCII marker: %s"
      % (repeat_marker, written.group(1) if written else "no [curated] literal in Logger.m"))
check('[line containsString:@"' + repeat_marker + '"]' in diagnostics,
"the log browser folds on that marker and not on the prose around it")
# Pairing tells the screen why it failed. It used to hand over a sentence and let
# the screen guess: HostsViewController searched the failure text for "timeout",
# "network", "disconnected" and three Chinese phrases to decide whether to retry at a
# second address, so the decision moved whenever either side reworded anything, and a
# host that refused in words the list happened to contain was retried while one that
# refused in other words was not. The enum is the contract now, so every case has to
# arrive and every case has to be answered.
pair_header = open(os.path.join(root, "Limelight/Network/PairManager.h"), encoding="utf-8").read()
pair_source = open(os.path.join(root, "Limelight/Network/PairManager.m"), encoding="utf-8").read()
hosts_vc = open(os.path.join(root, "Limelight/macOS/ViewControllers/HostsViewController.m"),
                encoding="utf-8").read()
check("- (void) pairFailedWithReason:(PairFailureReason)reason detail:(NSString*)detail;"
      in pair_header and "- (void) pairFailed:(NSString*)message;" not in pair_header,
      "pairing reports a reason instead of a sentence to be read")

reasons = re.findall(r"\bPairFailureReason([A-Z][A-Za-z]+)\b", pair_header)
reason_cases = sorted(set(reasons))
answered = sorted({m.group(1) for m in
                   re.finditer(r"case\s+PairFailureReason([A-Z][A-Za-z]+)\s*:", hosts_vc)})
check(bool(reason_cases) and answered == reason_cases,
      "every pairing reason the network layer can report has wording behind it"
      if answered == reason_cases else
      "pairing reasons with no wording in HostsViewController: %s"
      % ", ".join(sorted(set(reason_cases) - set(answered)) or "none; extra: "
                  + ", ".join(sorted(set(answered) - set(reason_cases)))))

retry_shape = method_body(hosts_vc, "- (void)pairFailedWithReason:(PairFailureReason)reason "
                                    "detail:(NSString*)detail")
check("PairFailureReasonNetwork" in retry_shape and "PairFailureReasonTimeout" in retry_shape,
      "the retry decision reads the reason and not the words around it")
guessed = sorted({token for token in ("timeout", "network", "disconnected", "\u8bf7\u6c42\u8d85\u65f6")
                  if re.search(r'containsString:@"[^"]*%s' % token, hosts_vc, re.I)})
check(not guessed and "isTransientNetworkPairFailureMessage" not in hosts_vc,
      "no pairing decision is made by searching a failure message for words"
      if not guessed and "isTransientNetworkPairFailureMessage" not in hosts_vc else
      "pairing still guesses from message text: " + (", ".join(guessed) or "the old helper"))

# MLString is one macro over one lookup. It used to be a #define inside
# StreamViewController_Internal.h, which left AppDelegate and ConnectionEditor with
# no macro at all, HostsViewController undefining NSLocalizedString to write its own,
# and ContainerViewController calling the manager directly and then localizing the
# already localized result: localize:MLString(@"...") looked the translation up twice
# and returned the second answer. One header owns the macro now, so the macro may be
# defined in that header and nowhere else, and nothing may wrap a call in another.
objc_sources = []
for directory, _, names in os.walk(os.path.join(root, "Limelight")):
    for name in sorted(names):
        if name.endswith((".m", ".h", ".swift")):
            objc_sources.append(os.path.join(directory, name))
definers = sorted(os.path.relpath(path, root) for path in objc_sources
                  if re.search(r"^\s*#\s*define\s+MLString\b",
                               open(path, encoding="utf-8", errors="replace").read(), re.M))
check(definers == ["Limelight/macOS/Localization.h"],
      "one header owns the localization macro"
      if definers == ["Limelight/macOS/Localization.h"] else
      "MLString is defined by: " + (", ".join(definers) or "nothing at all"))

double_localized = sorted(os.path.relpath(path, root) for path in objc_sources
                          if re.search(r"localize:\s*\(?\s*MLString\s*\(",
                                       open(path, encoding="utf-8", errors="replace").read()))
check(not double_localized, "no translation is looked up twice on its way to the screen"
      if not double_localized else "a localized string is localized again in: "
      + ", ".join(double_localized))

analyzer = subprocess.run([sys.executable,
                           os.path.join(root, "scripts", "analyzer-audit.py"), "--self-test"],
                          capture_output=True, text=True, cwd=root)
check(analyzer.returncode == 0, "the analyzer gate can tell a clean tree from a blind sweep"
      if analyzer.returncode == 0 else "the analyzer gate self test failed:\n"
      + analyzer.stdout[-700:])

# Every audit above asks what the source does. None of them asks what the source
# happens to contain, so a personal access token pasted into a helper, a debug
# script, or a workflow step would have been built, tested, artefacted, and
# pushed without a single word of comment -- and a pushed secret is in the object
# database, in every fork made afterwards, and in any log that echoes the file.
# The one cheap moment to refuse is the commit that adds it.
#
# The whole history is walked once per full pass, not once per gate: the battery
# runs this file ninety-seven times, and twenty-four seconds times ninety-seven
# is a battery nobody waits for. Under --no-battery the tree scan still runs, so
# the mutation battery still sees a secret-shaped file in the tree.
credential = subprocess.run(
    [sys.executable, os.path.join(root, "scripts", "credential-scan-audit.py")]
    + (["--history"] if run_battery else []),
    capture_output=True, text=True, cwd=root)
check(credential.returncode == 0,
      "no credential shape is in the tree"
      + (" or anywhere in the history" if run_battery else "")
      if credential.returncode == 0 else
      "the credential scan refused the tree:\n" + credential.stdout[-700:])

# Rules that never fire and a tree that never had a secret look identical from
# green, so the shapes are planted and hunted on every pass.
credential_self = subprocess.run(
    [sys.executable, os.path.join(root, "scripts", "credential-scan-audit.py"),
     "--self-test"],
    capture_output=True, text=True, cwd=root)
check(credential_self.returncode == 0,
      "every credential rule catches its own shape, the prescreen stays a "
      "superset, and the report never prints a whole value"
      if credential_self.returncode == 0 else
      "the credential scan cannot prove its own rules:\n"
      + credential_self.stdout[-700:])

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

# The three greps below are the audits job's other steps, and they run here for
# the same reason the parity rule above exists. Membership is the cheap one that
# answers "will this file ever be compiled", the glass rules are a source rule
# with fixtures that break each one, and the workflow rules cover what a yaml
# parse cannot see. Each is under a tenth of a second, so none of them has an
# excuse for living only on a runner.
membership = subprocess.run([sys.executable,
                             os.path.join(root, "scripts", "source-membership-audit.py")],
                            capture_output=True, text=True, cwd=root)
check(membership.returncode == 0,
      "no implementation file is excluded from its target without a reason"
      if membership.returncode == 0 else
      "the source membership audit failed:\n" + membership.stdout[-900:])

glass_rules = subprocess.run([sys.executable,
                              os.path.join(root, "scripts", "liquid-glass-audit.py"),
                              "--self-test"], capture_output=True, text=True, cwd=root)
check(glass_rules.returncode == 0,
      "the glass fixtures break every glass rule they claim to break"
      if glass_rules.returncode == 0 else
      "the liquid glass self-test failed:\n"
      + (glass_rules.stdout + glass_rules.stderr)[-900:])

glass = subprocess.run([sys.executable,
                        os.path.join(root, "scripts", "liquid-glass-audit.py")],
                       capture_output=True, text=True, cwd=root)
check(glass.returncode == 0,
      "the shipped glass surfaces satisfy the glass rules"
      if glass.returncode == 0 else
      "the liquid glass audit failed:\n" + glass.stdout[-900:])

workflow_rules = subprocess.run([sys.executable,
                                 os.path.join(root, "scripts", "workflow-audit.py"),
                                 "--self-test"], capture_output=True, text=True, cwd=root)
check(workflow_rules.returncode == 0,
      "the workflow fixtures break every workflow rule they claim to break"
      if workflow_rules.returncode == 0 else
      "the workflow self-test failed:\n"
      + (workflow_rules.stdout + workflow_rules.stderr)[-900:])

pipeline_rules = subprocess.run([sys.executable,
                                 os.path.join(root, "scripts", "workflow-audit.py")],
                                capture_output=True, text=True, cwd=root)
check(pipeline_rules.returncode == 0,
      "the workflow can actually run"
      if pipeline_rules.returncode == 0 else
      "the workflow audit failed:\n" + pipeline_rules.stdout[-900:])

tag_rules = subprocess.run([sys.executable, os.path.join(root, "scripts", "release-gate.py"),
                            "--self-test"], capture_output=True, text=True, cwd=root)
check(tag_rules.returncode == 0,
      "the release tag rules reject every tag they claim to reject"
      if tag_rules.returncode == 0 else
      "the release gate self-test failed:\n"
      + (tag_rules.stdout + tag_rules.stderr)[-900:])

analyzer_rules = subprocess.run([sys.executable, os.path.join(root, "scripts", "analyzer-audit.py"),
                                 "--self-test"], capture_output=True, text=True, cwd=root)
check(analyzer_rules.returncode == 0,
      "the analyzer gate notices a scan that did not run"
      if analyzer_rules.returncode == 0 else
      "the analyzer self-test failed:\n"
      + (analyzer_rules.stdout + analyzer_rules.stderr)[-900:])

# What a DMG has to be is a three-part rule, and until now the repository had none
# of it: the packaging step fell back from create-dmg to a bare `hdiutil create`
# with `||`, which succeeds and produces an image with no Applications drop target,
# and nothing in the pipeline opened an image at all. The checksum half needs no
# toolchain, so it is checked on every host, including the ubuntu audits runner
# that publishes the release. The mount half needs a host that can mount HFS+, so
# it is asked rather than assumed, and a host that cannot says so out loud.
checksum_rules = subprocess.run([sys.executable, os.path.join(root, "scripts", "dmg-audit.py"),
                                 "--self-test-checksums"],
                                capture_output=True, text=True, cwd=root)
check(checksum_rules.returncode == 0,
      "the checksum rule binds the bytes a release publishes"
      if checksum_rules.returncode == 0 else
      "the published-image checksum self-test failed:\n"
      + (checksum_rules.stdout + checksum_rules.stderr)[-900:])

# A machine that has never seen Xcode has no `xcrun` at all, and a missing binary
# arrives as FileNotFoundError rather than an empty answer. Two CI runs found that
# out by crashing: the module that hands out compilers answered a question it could
# not answer with a traceback, so every harness on such a host looked like broken
# code. The probe takes the compiler-finder's own word for it -- an empty pair, not
# an exception -- with PATH emptied, which a Mac can test as well as a Linux runner.
probe = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0, %r); import apple_toolchain; "
     "clang, sdk = apple_toolchain._xcrun_pair(); "
     "sys.exit(0 if not clang and not sdk else 1)" % os.path.join(root, "scripts")],
    env={"PATH": "/nonexistent"}, capture_output=True, text=True, cwd=root)
check(probe.returncode == 0,
      "a host with no xcrun is answered, not crashed"
      if probe.returncode == 0 else
      "the compiler finder raised instead of answering: "
      + (probe.stderr or probe.stdout)[-400:])

toolchain_missing = None
try:
    sys.path.insert(0, os.path.join(root, "scripts"))
    import apple_toolchain
    apple_toolchain.clang_and_sdk("the behavioural harnesses")
except (SystemExit, OSError) as absent:
    toolchain_missing = "%s: %s" % (type(absent).__name__, absent)

if run_battery:
    # The build jobs run these ten on every change, and until now nothing ran
    # them here, which is the same gap that hid an uncompilable header for a whole
    # round. Each one compiles the shipping source with the compiler from
    # apple_toolchain and finishes in under two seconds, so the only reason they
    # lived on a runner was habit. They need an Apple toolchain, and the audits job
    # runs on ubuntu, where there is none: that is what broke a run twenty minutes
    # ago, and it was this file's fault, not the tree's. So the host is asked, and a
    # host that cannot run them says so in one line rather than passing quietly or
    # failing for a reason no source caused. The battery's nested runs skip them
    # either way: a mutation is judged by the harness that owns it, and sixty-two
    # nested runs of all seven would only teach everyone to stop running this file.
    # Making and mounting two throwaway disk images costs about as much as all
    # ten harnesses together, so it belongs to the full run and not to the
    # battery's sixty-odd nested ones. The cheap checksum half above is what a
    # nested run judges a mutation against.
    has_hdiutil = any(os.path.exists(os.path.join(folder, "hdiutil"))
                      for folder in os.environ.get("PATH", "").split(os.pathsep) + ["/usr/bin"])
    if not has_hdiutil:
        print("skip the disk image self-test: this host has no hdiutil to mount an image")
    elif toolchain_missing:
        print("skip behavioural harnesses: %s" % toolchain_missing)
    else:
        behaviours = (os.path.join("scripts", "input-concurrency-tests.py"),
                          os.path.join("scripts", "keyboard-concurrency-tests.py"),
                          os.path.join("scripts", "held-key-identity-tests.py"),
                          os.path.join("scripts", "held-modifier-keyboard-pair-tests.py"),
                          os.path.join("scripts", "modifier-only-release-collision-tests.py"),
                          os.path.join("scripts", "key-order-exhaustive-tests.py"),
                          os.path.join("scripts", "translation-rule-consumption-tests.py"),
                          os.path.join("scripts", "gameplay-modifier-tests.py"),
                          os.path.join("scripts", "controller-key-navigation-tests.py"),
                          os.path.join("scripts", "space-transition-held-key-tests.py"),
                          os.path.join("scripts", "keyboard-modifier-mapping-tests.py"),
                          os.path.join("scripts", "keyboard-shortcut-modifier-tests.py"),
                          os.path.join("scripts", "stream-menu-addressing-tests.py"),
                          os.path.join("scripts", "video-enhancement-tests.py"),
                          os.path.join("scripts", "enhancement-engine-resolution-tests.py"),
                          os.path.join("scripts", "frame-interpolation-status-tests.py"),
                          os.path.join("scripts", "interpolated-frame-count-tests.py"),
                          os.path.join("scripts", "interpolation-source-format-tests.py"),
                          os.path.join("scripts", "scaling-output-evidence-tests.py"),
                          os.path.join("scripts", "liquid-glass-overlay-tests.py"),
                          os.path.join("scripts", "shortcut-menu-key-tests.py"))
        for behaviour in behaviours:
            harness = subprocess.run([sys.executable, os.path.join(root, behaviour)],
                                     capture_output=True, text=True, cwd=root)
            label = os.path.basename(behaviour)
            check(harness.returncode == 0,
                  "%s passes" % label
                  if harness.returncode == 0 else
                  "%s failed:\n" % label
                  + (harness.stdout + harness.stderr)[-1200:])

        # A build once reached a runner with a mistake every local gate had called
        # clean, because the mistake was only visible inside a translation unit and the
        # SDK on the machine doing the checking decided which answer was right. So the
        # aggregate compiles the macOS sources too, against every SDK the host offers:
        # a host with no toolchain says so in one line above, and a host with no build
        # yet says so here, rather than passing quietly.
        for flags, label in ((["--self-test"],
                              "the compile gate refuses a selector that does not exist "
                              "and accepts one that does"),
                             ([],
                              "every macOS source file type-checks against every installable SDK")):
            compiled = subprocess.run([sys.executable,
                                       os.path.join(root, "scripts", "compile-audit.py")] + flags,
                                      capture_output=True, text=True, cwd=root)
            outcome = (compiled.stdout + compiled.stderr).strip()
            if compiled.returncode == 0 and "skipped" in outcome:
                print("skip %s: %s" % (label, outcome.splitlines()[0]))
                continue
            check(compiled.returncode == 0, label
                  if compiled.returncode == 0 else
                  "%s:" % label + "\n" + outcome[-1500:])

        # The same two halves for the Swift half of the app. A mistake that only a
        # type-checker can see -- asking an NSResponder which window it belongs to --
        # passed the syntax parse and every source rule here, and arrived as three
        # failing jobs, because the only thing in the tree that read Swift types was
        # a build step twelve minutes away. Self-test first so a gate that has stopped
        # being able to fail is reported before a gate that reports a clean tree.
        for swift_flags, swift_label in (
                (["--self-test"],
                 "the Swift gate refuses the shape that reached CI and accepts the "
                 "shape that fixed it"),
                ([], "the Swift sources type-check against every installable SDK")):
            swift_run = subprocess.run(
                [sys.executable, os.path.join(root, "scripts", "swift-typecheck.py")]
                + swift_flags, capture_output=True, text=True, cwd=root)
            swift_outcome = (swift_run.stdout + swift_run.stderr).strip()
            # The gate says "swift type-check skipped" only when it read nothing --
            # no compiler, or no SDK whose macros it can see. A run that checked one
            # SDK and could not read another is a verdict, and the local answer has
            # to mean what the CI answer means, so that one is judged, not excused.
            if swift_run.returncode == 0 and "swift type-check skipped" in swift_outcome:
                print("skip %s: %s" % (swift_label, swift_outcome.splitlines()[0]))
                continue
            check(swift_run.returncode == 0, swift_label
                  if swift_run.returncode == 0 else
                  "%s:" % swift_label + "\n" + swift_outcome[-1500:])

        image_rules = subprocess.run([sys.executable,
                                      os.path.join(root, "scripts", "dmg-audit.py"),
                                      "--self-test"],
                                     capture_output=True, text=True, cwd=root)
        check(image_rules.returncode == 0,
              "the disk image gate rejects an image with no drop target and a wrong build"
              if image_rules.returncode == 0 else
              "the disk image self-test failed:\n"
              + (image_rules.stdout + image_rules.stderr)[-900:])

        # Same reasoning as the image self-test beside it: this one compiles two
        # throwaway bundles to test the signature gate, so it belongs to the full pass
        # and to the macOS build jobs, not to the battery's nested runs.
        signature_rules = subprocess.run([sys.executable,
                                          os.path.join(root, "scripts", "launch-code-audit.py"),
                                          "--self-test"],
                                         capture_output=True, text=True, cwd=root)
        check(signature_rules.returncode == 0,
              "the signature gate accepts a sealed bundle and refuses an unsigned one"
              if signature_rules.returncode == 0 else
              "the launch code self-test failed:\n"
              + (signature_rules.stdout + signature_rules.stderr)[-900:])

# --- an API newer than the build's SDK may only be reached by name ----------
# `effectIsInteractive` is declared in the macOS 27 SDK. The CI image compiles with
# the 26.5 one, where the name is not a deprecation warning but a compile error, and
# the machine whose SDK has it cannot see that at all: three jobs went red while every
# local gate said clean. A source scan cannot derive "newer than the build SDK", so it
# is a list, and the rule is that a listed name may only exist inside a string --
# looked up on the object, which compiles against any SDK and does nothing where the
# answer is absent. scripts/compile-audit.py is the second half: it compiles the
# sources against every SDK the host actually has.
RUNTIME_ONLY_APIS = {
    "effectIsInteractive": "declared in a newer SDK than the CI image builds with",
}


def without_literals_and_comments(text):
    """The source with string literals collapsed and comments removed.

    A name written in a comment, or inside the string a runtime lookup is made with,
    is not the identifier the compiler has to resolve -- and the comment beside this
    very rule explains why the API is on the list, so a rule that read it as a use
    would fail the file for documenting the rule.
    """
    stripped = re.sub(r'@?"(?:[^"\\]|\\.)*"', '""', text)
    stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
    return re.sub(r"//[^\n]*", "", stripped)


offenders = []
for base, _, files in os.walk(os.path.join(root, "Limelight")):
    for name in sorted(files):
        if not name.endswith(".m"):
            continue
        path = os.path.join(base, name)
        bare = without_literals_and_comments(open(path, encoding="utf-8",
                                           errors="replace").read())
        for api, why in RUNTIME_ONLY_APIS.items():
            if re.search(r"\b%s\b" % re.escape(api), bare) is not None:
                offenders.append("%s names %s directly (%s)"
                                 % (os.path.relpath(path, root), api, why))
check(not offenders,
      "an API newer than the build\'s SDK is reached by lookup, never by name"
      if not offenders else "; ".join(offenders))

# --- the Swift half has to be checked by something the workflow runs ----------
# The rule above refuses a newer-SDK name written in source, and compile-audit
# compiles the Objective-C half against every SDK the host has. Neither reads a Swift
# type, and the tree paid twelve minutes and three jobs for that gap. A gate that
# exists but is only ever run in self-test mode is the same hole wearing a hat -- it
# proves the gate can fail and never asks whether this tree would fail -- so the
# aggregate requires the pipeline to name the Swift check twice: once to prove the
# gate can still fail, once to run it over the sources.
swift_invocations = re.findall(r"python3 scripts/swift-typecheck\.py[ \t]*(.*)", pipeline)
swift_reads_tree = [tail for tail in swift_invocations if "--self-test" not in tail]
# The second invocation has to name the derived data as well. The generated headers
# the Swift sources import are xcodebuild's, and on a runner they live outside the
# checkout, so an invocation without --derived reads nothing and says so -- a skip
# that is honest in the log and empty in the pipeline.
swift_wired = (len(swift_invocations) == 2 and len(swift_reads_tree) == 1
               and any("--self-test" in tail for tail in swift_invocations)
               and "--derived" in swift_reads_tree[0])
check(swift_wired,
      "the Swift half is type-checked over the tree, and its gate proves it can fail"
      if swift_wired else
      "the workflow runs the Swift check %d time(s) [%s]; it needs one self-test "
      "invocation and one that reads the tree with --derived"
      % (len(swift_invocations),
         ", ".join(repr(t.strip()) for t in swift_invocations)))

# --- a menu hint has to be something AppKit can compare to a key ------------
# The settings page names keys for people (`Space`, `Return`, an arrow), and those
# names went straight into NSMenuItem.keyEquivalent, where a word matches no key at
# all: measured against a live NSMenu the item took neither the key the word names nor
# the key its first letter names. The compiled answer is what scripts/
# shortcut-menu-key-tests.py checks; here the guard that produces it is what has to
# stay, because a hint nobody can press is invisible to every test that only asks the
# stream view.
menu_profile = open(os.path.join(root, "Limelight", "macOS", "ViewControllers",
                                 "SettingsShortcuts.swift"), encoding="utf-8").read()
menu_guard = re.search(r"guard\s+key\.utf16\.count\s*==\s*1[\s\S]{0,240}?"
                       r"scalar\.value\s*>=\s*0x20", menu_profile)
check(menu_guard is not None,
      "a menu key equivalent is limited to one printable scalar, so a key name is never "
      "handed to AppKit as if it were a key"
      if menu_guard else "menuKeyEquivalent no longer limits its answer to one printable "
      "scalar, so Space and Return are handed to AppKit as words")

# --- a release has to answer the press it was given ----------------------------
# Everything a player calls a key conflict lives on the release edge: the press went
# out as "W with Shift" and a release that carries zero tells the host to lift a key
# it was never told about, so the sprint keeps running after the finger comes up; and
# a press the client consumed for a local binding never reached the host at all, so
# forwarding its release is a gameplay key coming up by itself. scripts/
# keyboard-shortcut-modifier-tests.py proves both by reading packets off the shipped
# -keyUp:, but it needs a compiler and the audit runner has none, so the two lines
# that carry these properties are what the aggregate requires.
hid_support = open(os.path.join(root, "Limelight", "Input",
                                "HIDSupport.m"), encoding="utf-8").read()
key_up_start = hid_support.index("- (void)keyUp:(NSEvent *)event {")
key_up_body = hid_support[key_up_start:hid_support.index("\n}\n", key_up_start) + 3]
release_problems = []
if "translateKeyModifierWithEvent" not in key_up_body:
    release_problems.append("-keyUp: no longer answers with the modifier byte its press "
                            "used, so a release is sent for a key the host never saw")
if "keyboardSuppressedKeyDownKeyCodes containsObject" not in key_up_body:
    release_problems.append("-keyUp: no longer consults the record of presses consumed "
                            "locally, so a client shortcut releases a gameplay key")
check(not release_problems,
      "a released key carries the modifier its press carried, and never answers a press "
      "the client kept to itself"
      if not release_problems else "; ".join(release_problems))

# --- a key held down must fire its hotkey once, not at autorepeat rate ---------
# AppKit keeps sending keyDown while a key is held, and measured against a live
# NSWindow the key-equivalent chain delivers those isARepeat events exactly like the
# first one. A shortcut that flips a panel therefore flips it once per repeat, and a
# rule bound to a window rebuild lifts the player's held modifiers once per repeat.
# Ignoring the repeat is not a fix either: the first press was never forwarded, so a
# repeat allowed to fall through hands the host a key the player only bound to the
# client. Every state-changing binding has to consume its own repeats, and consume
# them by asking AppKit which delivery it is.
capture_src = open(os.path.join(root, "Limelight", "macOS", "ViewControllers",
                                "StreamViewController+MouseCapture.m"),
                   encoding="utf-8").read()


def ml_branch(text, marker, limit=900):
    """The lines from a known expression to the end of the block that holds it."""
    at = text.index(marker)
    window = text[at:at + limit]
    closer = window.index("\n    }\n") if "\n    }\n" in window else len(window)
    return window[:closer]


def ml_method(text, signature):
    at = text.index(signature)
    return text[at:text.index("\n}\n", at) + 3]


repeat_problems = []
rule_body = ml_method(capture_src,
                      "- (BOOL)handleKeyboardTranslationRuleForEvent:(NSEvent *)event {")
if "event.isARepeat" not in rule_body:
    repeat_problems.append("a translation rule runs its action again for every repeat "
                           "of the key that triggered it")
for hotkey in ("MLShortcutActionTogglePerformanceOverlay",
               "MLShortcutActionToggleMouseMode",
               "MLShortcutActionToggleFullscreenControlBall",
               "MLShortcutActionOpenControlCenter"):
    branch = ml_branch(capture_src,
                       "matchesShortcut:[self streamShortcutForAction:%s]" % hotkey)
    if "event.isARepeat" not in branch:
        repeat_problems.append("%s runs its action again for every repeat of its key"
                               % hotkey)
check(not repeat_problems,
      "a held hotkey fires once, and every repeated delivery is consumed rather than run"
      if not repeat_problems else "; ".join(repeat_problems))

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
