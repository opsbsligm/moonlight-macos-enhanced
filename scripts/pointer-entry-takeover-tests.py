#!/usr/bin/env python3
"""Prove a pointer entering the stream window only takes it when the player allowed that.

Two upstream issues, one mechanism. #21: the pointer leaves the window, the player goes to
another application, and moving back over the window raises Moonlight without a click. #40:
⌘-Tab away and the stream window comes back on its own. The tracking area is installed with
NSTrackingActiveAlways, so mouseEntered: arrives while this application is in the
background, and the entry path made the stream window key -- which activates the app.

The answer is not "hover never activates": a player who clicked into the stream and stepped
the pointer out to reach a second display should not have to click back in. It is a switch
that exists, a default that is the shipping behaviour, and a decision made in one function
instead of five early returns inside an AppKit callback. This harness compiles that function
whole -- header and implementation, verbatim -- with a real clang, drives every field of its
input on its own, and checks against the source that the callback actually consults it.

The default lives in two languages, C and Swift, because the switch is read in Objective-C
and written in SwiftUI. Nothing but this file compares them, so it does.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
HEADER = "Limelight/macOS/PointerEntryPolicy.h"
IMPL = "Limelight/macOS/PointerEntryPolicy.m"
MOUSE = "Limelight/macOS/ViewControllers/StreamViewController+MouseCapture.m"
INTERNAL = "Limelight/macOS/ViewControllers/StreamViewController_Internal.h"
DERIVED = "Limelight/macOS/ViewControllers/SettingsModel+DerivedValues.swift"
PANE = "Limelight/macOS/ViewControllers/SettingsInputPane.swift"
EN = "Limelight/macOS/en.lproj/Localizable.strings"
ZH = "Limelight/macOS/zh-Hans.lproj/Localizable.strings"

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def shipping_rules():
    header_raw, impl_raw = read(HEADER), read(IMPL)
    check(re.findall(r"#import\s*<([^>]+)>", header_raw) == ["Foundation/Foundation.h"] and
          re.findall(r"#import\s*<([^>]+)>", impl_raw) == [] and
          re.findall(r'#import\s*"([^"]+)"', impl_raw) == ["PointerEntryPolicy.h"],
          "the policy needs Foundation and its own header: no AppKit, no window server")
    return header_raw + "\n" + impl_raw.replace('#import "PointerEntryPolicy.h"\n', "")


def mouse_entry_body(text):
    start = text.index("- (void)mouseEntered:(NSEvent *)event {")
    brace, index = text.index("{", start), text.index("{", start)
    depth = 0
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
        index += 1


def wiring_ok(text):
    """The callback has to ask, and act on the answer it got -- nothing else."""
    body = mouse_entry_body(text)
    return ("MLPointerEntryState state;" in body and
            "MLPointerEntryActionsForState(state)" in body and
            "if (actions & MLPointerEntryActionMakeWindowKey) {" in body and
            "if (actions & MLPointerEntryActionSyncRemoteCursor) {" in body and
            "if (actions & MLPointerEntryActionRearmCapture) {" in body and
            body.index("if (actions & MLPointerEntryActionMakeWindowKey) {")
            < body.index("[self ensureStreamWindowKeyIfPossible];") and
            body.count("[self ensureStreamWindowKeyIfPossible];") == 1)


DRIVER = r"""
#import <Foundation/Foundation.h>

@@RULES@@

static int failures = 0;

static void check(BOOL ok, const char *what) {
    if (!ok) failures++;
    printf("%-4s %s\n", ok ? "ok" : "FAIL", what);
}

static MLPointerEntryState state(BOOL hoverOn, BOOL remote, BOOL captured,
                                 BOOL edgeMenu, BOOL pendingEdge) {
    MLPointerEntryState s;
    s.hoverActivatesWindow = hoverOn;
    s.remoteDesktopMode = remote;
    s.mouseCaptured = captured;
    s.edgeMenuTemporaryReleaseActive = edgeMenu;
    s.pendingReentryEdge = pendingEdge;
    return s;
}

static void expect(const char *what, MLPointerEntryState s, MLPointerEntryAction want) {
    MLPointerEntryAction got = MLPointerEntryActionsForState(s);
    if (got != want) failures++;
    printf("%-4s %-48s -> 0x%lx want 0x%lx\n", got == want ? "ok" : "FAIL", what,
           (unsigned long)got, (unsigned long)want);
}

int main(void) {
    @autoreleasepool {
        const MLPointerEntryAction takeover =
            MLPointerEntryActionMakeWindowKey | MLPointerEntryActionSyncRemoteCursor |
            MLPointerEntryActionRearmCapture;

        check(MLPointerEntryHoverActivatesWindowDefault() == YES,
              "a fresh install behaves the way every build of this app has behaved");

        // The switch on: the shipping behaviour, action for action.
        expect("hover takes the window in free mode", state(YES, YES, NO, NO, NO), takeover);
        // Each reason a hover is not a claim, driven on its own with the switch open.
        expect("an already captured mouse is the host's already", state(YES, YES, YES, NO, NO),
               MLPointerEntryActionNone);
        expect("absolute pointer mode holds nothing", state(YES, NO, NO, NO, NO),
               MLPointerEntryActionNone);
        expect("reaching for the overlay menu is not a decision to play",
               state(YES, YES, NO, YES, NO), MLPointerEntryActionNone);
        expect("a pointer coming back through the edge it left by is already owned",
               state(YES, YES, NO, NO, YES), MLPointerEntryActionNone);
        // The switch off: what #21 and #40 asked for.
        expect("with the switch off a hover waits for a click", state(NO, YES, NO, NO, NO),
               MLPointerEntryActionNone);
        expect("the switch off is not undone by a captured mouse", state(NO, YES, YES, NO, NO),
               MLPointerEntryActionNone);
        // Taking the window means taking all of it: a window made key without the host's
        // cursor lined up is a window the player then has to correct by hand.
        MLPointerEntryAction half = MLPointerEntryActionsForState(state(YES, YES, NO, NO, NO));
        check((half & MLPointerEntryActionSyncRemoteCursor) != 0 &&
              (half & MLPointerEntryActionRearmCapture) != 0,
              "a hover that takes the window also lines up the host cursor and the pointer");
        printf("%s\n", failures ? "RUN FAILED" : "RUN PASSED");
        return failures ? 1 : 0;
    }
}
"""


def compiled(source, work, name, cc, sdk):
    path = os.path.join(work, name + ".m")
    open(path, "w", encoding="utf-8").write(source)
    command = [cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
               "-framework", "Foundation", path, "-o", os.path.join(work, name)]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return None, None, (built.stdout + built.stderr).strip()[-2200:]
    ran = subprocess.run([os.path.join(work, name)], capture_output=True, text=True)
    return ran.returncode, ran.stdout, (ran.stdout + ran.stderr).strip()[-2200:]


def run_rules(label, rules, cc, sdk, expect_pass=False):
    with tempfile.TemporaryDirectory() as work:
        code, out, log = compiled(DRIVER.replace("@@RULES@@", rules), work, "pointerentry", cc, sdk)
        if code is None:
            check(False, "%s: %s" % (label, log))
            return
        if expect_pass:
            check(code == 0 and out is not None and "RUN PASSED" in out,
                  "the shipping decision answers every state correctly"
                  if code == 0 else "the shipping decision failed a case:%s" % out)
        else:
            check(code != 0, "the check still fails when %s" % label)


def mutated(rules, label, before, after):
    check(before in rules, "%s: the source it mutates is still there" % label)
    return rules.replace(before, after, 1)


def main():
    rules = shipping_rules()
    mouse = read(MOUSE)
    print("-- what a pointer entering the window is allowed to do --")

    cc, sdk = apple_toolchain.clang_and_sdk("pointer entry policy")
    run_rules("the shipping decision", rules, cc, sdk, expect_pass=True)

    # --- the callback has to consult the decision -----------------------------
    check('#import "PointerEntryPolicy.h"' in mouse,
          "the mouse capture category imports the policy it decides with")
    check(wiring_ok(mouse),
          "mouseEntered: asks the policy and acts on the answer, once per action")
    internal = read(INTERNAL)
    check("- (BOOL)hoverActivatesStreamWindowOnPointerEntry;" in internal,
          "the switch is read through one declared helper, not inline at the call site")
    check("[SettingsClass hoverActivatesStreamWindowFor:self.app.host.uuid]" in mouse,
          "the helper reads the player's own stored preference for this host")

    # --- the switch is reachable, and the two defaults agree ------------------
    pane = read(PANE)
    check("boolBinding: $settingsModel.hoverActivatesStreamWindow" in pane and
          'title: "Pointer Enter Activates Stream"' in pane,
          "the switch is on the mouse panel, where a player looking for it would find it")
    check('"Pointer Enter Activates Stream" = "Pointer Enter Activates Stream";' in read(EN),
          "english names the switch")
    check('"Pointer Enter Activates Stream"' in read(ZH),
          "chinese names the switch")
    derived = read(DERIVED)
    swift_default = re.search(r"static let defaultHoverActivatesStreamWindow\s*=\s*(\w+)", derived)
    c_default = re.search(r"MLHoverActivatesWindowDefault\s*=\s*(YES|NO)", read(IMPL))
    check(swift_default is not None and c_default is not None and
          swift_default.group(1) == "true" and c_default.group(1) == "YES",
          "the C default and the Swift default are both yes, which is the one thing no "
          "other file compares")

    # --- and the assertions above have to be the thing that fails -------------
    run_rules("the player's switch is ignored",
              mutated(rules, "the switch",
                      "if (!state.hoverActivatesWindow) {", "if (NO) {"),
              cc, sdk)
    run_rules("a captured mouse is claimed back by a hover",
              mutated(rules, "the captured mouse",
                      "if (!state.remoteDesktopMode || state.mouseCaptured) {",
                      "if (!state.remoteDesktopMode) {"),
              cc, sdk)
    run_rules("the overlay menu reach is treated as a hover",
              mutated(rules, "the overlay menu reach",
                      "if (state.edgeMenuTemporaryReleaseActive) {", "if (NO) {"),
              cc, sdk)
    run_rules("an edge handoff is decided a second time",
              mutated(rules, "the edge handoff",
                      "if (state.pendingReentryEdge) {", "if (NO) {"),
              cc, sdk)
    run_rules("a hover takes the window but leaves the host cursor behind",
              mutated(rules, "a half takeover",
                      "return MLPointerEntryActionMakeWindowKey | MLPointerEntryActionSyncRemoteCursor |\n"
                      "           MLPointerEntryActionRearmCapture;",
                      "return MLPointerEntryActionMakeWindowKey;"),
              cc, sdk)
    run_rules("the default becomes the new behaviour instead of the old one",
              mutated(rules, "the default",
                      "static const BOOL MLHoverActivatesWindowDefault = YES;",
                      "static const BOOL MLHoverActivatesWindowDefault = NO;"),
              cc, sdk)

    check(wiring_ok(mouse), "the wiring check has something to fail on")
    unwired = mouse.replace("if (actions & MLPointerEntryActionMakeWindowKey) {\n        [self ensureStreamWindowKeyIfPossible];",
                            "[self ensureStreamWindowKeyIfPossible];", 1)
    check(unwired != mouse and not wiring_ok(unwired),
          "removing the guard really does put an unconditional activation back in the hover path")

    print("%d pointer-entry-takeover failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
