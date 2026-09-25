#!/usr/bin/env python3
"""Prove the app gives the system's hotkeys back in every direction it took them.

Taking F1-F12 and the system's own shortcuts is a WindowServer call Apple does not
document. It is process-wide, it is not reference counted, and the app has exactly one
copy of it: a stream that ends without handing the keys back leaves the player without
Mission Control, Spotlight or an input-source switch until the app quits, and nothing
inside the app can undo it afterwards. So the shape that matters is not whether the call
works -- it is whether every path that could have taken them is seen giving them back.

Three things are checked:

  * the state ledger, driven from the shipped C helper: the remembered state changes only
    when the call agreed, because remembering a suppression that never happened is how a
    refused call turns into hotkeys that stay gone;
  * the bridge, driven for real: an entry point the OS does not hand back is reported as
    unavailable rather than as a success, and the call is never linked -- a binary that
    links a private symbol refuses to launch where it is gone;
  * the wiring, read out of the shipping sources: the three capture modes, the six moments
    that decide the state, and the fact that the session's teardown -- not the observer
    refresh that -viewDidAppear does before re-registering -- is the one that hands the
    keys back.

--self-test plants four mistakes: remember the request whether or not the call agreed;
drop the teardown restore; let "never capture" stop being the first question; and move the
restore onto the per-view observer refresh, which -viewDidAppear runs on its way back in.
"""
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VC = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers")

OBJC = os.path.join(VC, "StreamViewController+MouseCapture.m")
CONTROLLER = os.path.join(VC, "StreamViewController.m")
INTERNAL = os.path.join(VC, "StreamViewController_Internal.h")
STORE = os.path.join(VC, "SettingsStore.swift")
DERIVED = os.path.join(VC, "SettingsModel+DerivedValues.swift")
MODEL = os.path.join(VC, "SettingsModel.swift")
BRIDGE = os.path.join(VC, "SettingsObjCBridge.swift")
PANE = os.path.join(VC, "SettingsInputPane.swift")
ZH = os.path.join(ROOT, "Limelight", "macOS", "zh-Hans.lproj", "Localizable.strings")
EN = os.path.join(ROOT, "Limelight", "macOS", "en.lproj", "Localizable.strings")

MIN_BEHAVIOUR_CHECKS = 9

SHIM = r'''
#include <dlfcn.h>
#include <stdio.h>
#include <unistd.h>

typedef int BOOL;
#define YES 1
#define NO 0
typedef double CGFloat;

#define MLkCGErrorSuccess 0
#define MLkCGErrorUnavailable (-1)

typedef int (*MLSetGlobalHotKeyOperatingModeFunction)(unsigned connectionID, unsigned mode);
typedef unsigned (*MLMainConnectionIDFunction)(void);

typedef struct {
    MLMainConnectionIDFunction connectionID;
    MLSetGlobalHotKeyOperatingModeFunction setMode;
} MLSystemHotkeyBridge;

/*-- shipped helpers, extracted verbatim from StreamViewController+MouseCapture.m --*/
%HELPER_SOURCE%
/*-- end shipped helpers --*/

static int checks = 0;
static int failures = 0;
#define CHECK(cond, note) do { checks++; if (!(cond)) { failures++; printf("FAIL %s\n", note); } } while (0)

int main(void) {
    /* the ledger: the request is remembered only when the call agreed */
    CHECK(MLSystemHotkeyStateAfter(MLkCGErrorSuccess, YES, NO) == YES,
          "an agreed disable is remembered as suppressing");
    CHECK(MLSystemHotkeyStateAfter(MLkCGErrorSuccess, NO, YES) == NO,
          "an agreed enable is remembered as released");
    CHECK(MLSystemHotkeyStateAfter(1002, YES, NO) == NO,
          "an invalid connection does not become a suppression the app believes in");
    CHECK(MLSystemHotkeyStateAfter(MLkCGErrorUnavailable, YES, NO) == NO,
          "a missing private entry point does not become a suppression either");
    CHECK(MLSystemHotkeyStateAfter(MLkCGErrorUnavailable, NO, YES) == YES,
          "a failed restore does not claim the keys came back");

    /* refusing repeatedly has to leave the ledger where it started, in both directions */
    BOOL state = NO;
    for (int i = 0; i < 5; i++) {
        state = MLSystemHotkeyStateAfter(1002, YES, state);
    }
    CHECK(state == NO, "five refused disables still say nothing was taken");
    state = YES;
    for (int i = 0; i < 5; i++) {
        state = MLSystemHotkeyStateAfter(MLkCGErrorUnavailable, NO, state);
    }
    CHECK(state == YES, "five refused restores still say the keys are taken");

    /* zero is the only agreed value */
    CHECK(MLSystemHotkeyStateAfter(1, YES, NO) == NO, "a nonzero CGError is never agreement");
    CHECK(MLSystemHotkeyStateAfter(-50, NO, YES) == YES, "paramErr is never agreement either");

    /* the bridge is driven for real: it answers, and it never crashes or claims success
       when the operating system would not hand the symbol over */
    int enabled = MLSystemGlobalHotkeysSetEnabled(YES);
    int disabled = MLSystemGlobalHotkeysSetEnabled(NO);
    CHECK(enabled == MLkCGErrorUnavailable || enabled == MLkCGErrorSuccess,
          "enabling the system hotkeys answers unavailable or success");
    CHECK(disabled == MLkCGErrorUnavailable || disabled == MLkCGErrorSuccess,
          "disabling them answers unavailable or success on a host with a session");
    /* both directions went through the same resolved bridge, so the pair is reachable */
    CHECK((enabled == MLkCGErrorUnavailable) == (disabled == MLkCGErrorUnavailable),
          "the two directions agree about whether the entry point exists at all");

    /* Never leave the harness having taken the keys: the process exiting is the backstop,
       not the plan. */
    int final = MLSystemGlobalHotkeysSetEnabled(YES);
    CHECK(final == MLkCGErrorUnavailable || final == MLkCGErrorSuccess,
          "handing the keys back on the way out answers too");

    printf("%d system hotkey checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
'''

HELPERS = ["MLSystemHotkeyStateAfter", "MLSystemHotkeyBridgeResolve", "MLSystemGlobalHotkeysSetEnabled"]


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def helper_source(objc_text, break_ledger=False):
    out = []
    for name in HELPERS:
        match = re.search(r"^static\s+\w+\s+%s\(" % re.escape(name), objc_text, re.M)
        if not match:
            raise AssertionError("shipped helper %s is gone from the source" % name)
        start = objc_text.index("{", match.start())
        depth, index = 0, start
        while index < len(objc_text):
            if objc_text[index] == "{":
                depth += 1
            elif objc_text[index] == "}":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        out.append(objc_text[match.start():index + 1])
    source = "\n\n".join(out)
    if break_ledger:
        old = "return error == MLkCGErrorSuccess ? wantSuppressed : wasSuppressed;"
        assert old in source, "the ledger helper no longer reads the way the gate expects"
        source = source.replace(old, "(void)error; (void)wasSuppressed; return wantSuppressed;", 1)
    return source


def compile_and_run(source, tmp_dir, tag):
    program = os.path.join(tmp_dir, "hotkey-%s" % tag)
    c_file = os.path.join(tmp_dir, "hotkey-%s.c" % tag)
    with open(c_file, "w", encoding="utf-8") as handle:
        handle.write(source)
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if not compiler:
        print("FAIL no C compiler to drive the shipped bridge")
        return 2, ""
    built = subprocess.run([compiler, "-std=c11", "-o", program, c_file],
                           capture_output=True, text=True)
    if built.returncode != 0:
        print("FAIL the shipped bridge does not compile: %s" % built.stderr.strip()[:400])
        return 2, ""
    run = subprocess.run([program], capture_output=True, text=True, timeout=60)
    return run.returncode, run.stdout


def method_body(text, signature):
    start = text.find(signature)
    if start < 0:
        return None
    index = text.index("{", start)
    depth, cursor = 0, index
    while cursor < len(text):
        if text[cursor] == "{":
            depth += 1
        elif text[cursor] == "}":
            depth -= 1
            if depth == 0:
                break
        cursor += 1
    return text[start:cursor + 1]


def wiring_problems(objc_text, controller_text):
    problems = []

    should = method_body(objc_text, "- (BOOL)shouldSuppressSystemHotkeys")
    if should is None:
        problems.append("the capture decision is unreadable")
    else:
        first_if = should.find("if (")
        if "MLSystemKeyboardShortcutCaptureNever" not in should[:should.find("return NO", first_if)]:
            problems.append('"never capture" is not the first thing the decision asks')
        if "!NSApp.isActive" not in should:
            problems.append("another app in front does not get its keys back")
        if "isWindowFullscreen" not in should or "isWindowBorderlessMode" not in should:
            problems.append('"follow fullscreen" no longer means fullscreen or borderless')
        if "self.view.window == nil" not in should:
            problems.append("a stream with no window is asked to take the system hotkeys")

    update = method_body(objc_text, "- (void)updateSystemHotkeySuppression")
    if update is None:
        problems.append("the state machine is unreadable")
    else:
        if "if (wants == self.systemHotkeysSuppressed)" not in update:
            problems.append("the state machine re-asks WindowServer on every window notification")
        if "MLSystemHotkeyStateAfter(" not in update:
            problems.append("the state machine writes its ledger without asking whether the call agreed")
        if re.search(r"self\.systemHotkeysSuppressed\s*=\s*(wants|YES|NO)", update):
            problems.append("the state machine writes its ledger straight from the request")

    restore = method_body(objc_text, "- (void)restoreSystemHotkeySuppressionForReason:(NSString *)reason")
    if restore is None:
        problems.append("the restore path is unreadable")
    else:
        if "MLSystemHotkeyStateAfter(" not in restore:
            problems.append("the restore path claims the keys came back whatever the call said")
        if "if (!self.systemHotkeysSuppressed)" not in restore:
            problems.append("the restore path takes the call on every teardown whether or not anything was taken")

    refresh = method_body(objc_text, "- (void)refreshSystemKeyboardShortcutCapturePreference")
    if refresh is None or "MLSystemKeyboardShortcutCaptureAlways" not in refresh:
        problems.append("a stored mode outside the three cases is not read back to the default")

    capture = method_body(objc_text, "- (void)captureMouse")
    if capture is None or "updateSystemHotkeySuppression" not in capture:
        problems.append("a fresh capture does not bring the system hotkeys to the wanted state")
    if capture is None or "refreshSystemKeyboardShortcutCapturePreference" not in capture:
        problems.append("a fresh capture does not re-read the capture mode")

    bridge = method_body(objc_text, "static int MLSystemGlobalHotkeysSetEnabled(BOOL enabled)")
    whole_bridge = objc_text
    if "dlsym" not in whole_bridge or "CGSSetGlobalHotKeyOperatingMode" not in whole_bridge:
        problems.append("the private entry point is not resolved at run time")
    if re.search(r"(?<!\")CGSSetGlobalHotKeyOperatingMode\s*\(",
                 re.sub(r"dlsym\([^)]*\)", "", whole_bridge)):
        problems.append("the private entry point is called as a linked symbol, which refuses to launch without it")
    if "dlclose" in whole_bridge:
        problems.append("the framework handle is closed while its function pointers are still kept")
    if bridge is None or "MLkCGErrorUnavailable" not in bridge:
        problems.append("a missing private entry point is not reported as unavailable")

    moments = {
        "leaving fullscreen": ("window-did-exit-fullscreen", "updateSystemHotkeySuppression"),
        "entering fullscreen": ("window-did-enter-fullscreen", "updateSystemHotkeySuppression"),
        "the app becoming active": ("app-became-active", "updateSystemHotkeySuppression"),
    }
    for label, (needle, call) in moments.items():
        at = controller_text.find(needle)
        window = controller_text[max(0, at - 1200):at + 1200] if at >= 0 else ""
        if at < 0 or call not in window:
            problems.append("%s does not bring the system hotkeys to the wanted state" % label)

    for label, needle in (("the app resigning active", "app-resigned-active"),
                          ("the stream window closing", "window-will-close")):
        at = controller_text.find(needle)
        window = controller_text[max(0, at - 1200):at + 1200] if at >= 0 else ""
        if at < 0 or "restoreSystemHotkeySuppressionForReason" not in window:
            problems.append("%s does not hand the system hotkeys back" % label)

    teardown = method_body(controller_text, "- (void)tearDownStreamLifecycleObserversAndTimers")
    if teardown is None or "restoreSystemHotkeySuppressionForReason" not in teardown:
        problems.append("the stream teardown does not hand the system hotkeys back")

    settings_refresh = method_body(controller_text, "- (void)removeStreamSettingsObservers")
    if settings_refresh and "restoreSystemHotkeySuppressionForReason" in settings_refresh:
        problems.append("-viewDidAppear re-registers through a path that hands the keys back mid-stream")

    if "- (BOOL)shouldSuppressSystemHotkeys" not in internal_declared():
        problems.append("the decision is declared on no interface")
    return problems


def internal_declared():
    return read(INTERNAL)


def preference_problems():
    problems = []
    if "let systemKeyboardShortcutCapture: Int?" not in read(STORE):
        problems.append("the capture mode is not a stored setting")
    derived = read(DERIVED)
    if "static let defaultSystemKeyboardShortcutCapture = systemKeyboardShortcutCaptureFollowFullscreen" not in derived:
        problems.append("the mode is not stored where the modes live")
    if "systemKeyboardShortcutCaptureFollowFullscreen = 0" not in derived:
        problems.append("the raw values are not the ones the stream reads")
    if "@Published var systemKeyboardShortcutCapture: Int" not in read(MODEL):
        problems.append("the mode is not a modelled setting")
    if '"systemKeyboardShortcutCapture": settings.systemKeyboardShortcutCapture ?? 0' not in read(BRIDGE):
        problems.append("the stream-facing dictionary does not carry the mode")
    pane = read(PANE)
    if 'title: "Capture System Keyboard Shortcuts"' not in pane:
        problems.append("the player has no way to choose a capture mode")
    if 'hintKey: "Capture System Keyboard Shortcuts detail"' not in pane:
        problems.append("the capture modes are not explained where the choice lives")
    for language, path in (("zh-Hans", ZH), ("en", EN)):
        text = read(path)
        for key in ("Capture System Keyboard Shortcuts",
                    "Capture System Keyboard Shortcuts detail",
                    "Follow Fullscreen", "Always Capture", "Never Capture"):
            if '"%s"' % key not in text:
                problems.append("%s has no wording for %r" % (language, key))
        detail = re.search(r'^"Capture System Keyboard Shortcuts detail" = "(.*?)";$', text, re.M)
        if detail and not re.search(r"F1\s*-\s*F12|F1-F12", detail.group(1)):
            problems.append("%s explains the mode without naming the keys it covers" % language)
    return problems


def main():
    self_test = "--self-test" in sys.argv
    objc_text = read(OBJC)
    controller_text = read(CONTROLLER)
    rc = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        code, out = compile_and_run(SHIM.replace("%HELPER_SOURCE%", helper_source(objc_text)),
                                    tmp_dir, "shipping")
        counted = re.search(r"(\d+) system hotkey checks, (\d+) failures", out)
        checks = int(counted.group(1)) if counted else 0
        print("%-4s the hotkey ledger and the run-time bridge behave (%d checks)"
              % ("ok" if code == 0 and checks >= MIN_BEHAVIOUR_CHECKS else "FAIL", checks))
        if code != 0 or checks < MIN_BEHAVIOUR_CHECKS:
            print(out)
            rc = 1

        wiring = wiring_problems(objc_text, controller_text)
        print("%-4s every moment that takes the hotkeys is matched by one that returns them (%d gaps)"
              % ("ok" if not wiring else "FAIL", len(wiring)))
        for gap in wiring:
            print("     %s" % gap)
        if wiring:
            rc = 1

        preference = preference_problems()
        print("%-4s the three capture modes ship and are named in both languages (%d gaps)"
              % ("ok" if not preference else "FAIL", len(preference)))
        for gap in preference:
            print("     %s" % gap)
        if preference:
            rc = 1

        if self_test:
            broken_out_code, broken_out = compile_and_run(
                SHIM.replace("%HELPER_SOURCE%", helper_source(objc_text, break_ledger=True)),
                tmp_dir, "unconditional")
            caught = [line for line in broken_out.splitlines() if line.startswith("FAIL")]
            print("%-4s a ledger that believes a refused call is refused (%d verdicts red)"
                  % ("ok" if broken_out_code != 0 and caught else "FAIL", len(caught)))
            if broken_out_code == 0 or not caught:
                print(broken_out)
                rc = 1

            no_teardown = controller_text.replace(
                "    [self restoreSystemHotkeySuppressionForReason:@\"stream-teardown\"];", "", 1)
            if no_teardown == controller_text:
                print("FAIL the teardown restore is not readable, so its red proof cannot be built")
                return 1
            teardown_problems = wiring_problems(objc_text, no_teardown)
            print("%-4s a stream teardown that keeps the hotkeys is refused (%d gaps named)"
                  % ("ok" if any("stream teardown" in p for p in teardown_problems) else "FAIL",
                     len([p for p in teardown_problems if "stream teardown" in p])))
            if not any("stream teardown" in p for p in teardown_problems):
                rc = 1

            no_never = objc_text.replace(
                "    if (self.systemKeyboardShortcutCapture == MLSystemKeyboardShortcutCaptureNever) {\n"
                "        return NO;\n"
                "    }\n", "", 1)
            if no_never == objc_text:
                print("FAIL the never case is not readable, so its red proof cannot be built")
                return 1
            never_problems = wiring_problems(no_never, controller_text)
            print("%-4s a capture mode that ignores \"never\" is refused (%d gaps named)"
                  % ("ok" if any("never capture" in p for p in never_problems) else "FAIL",
                     len([p for p in never_problems if "never capture" in p])))
            if not any("never capture" in p for p in never_problems):
                rc = 1

            misplaced = controller_text.replace(
                "- (void)removeStreamSettingsObservers\n{",
                "- (void)removeStreamSettingsObservers\n{\n"
                "    [self restoreSystemHotkeySuppressionForReason:@\"observer-refresh\"];\n", 1)
            misplaced_problems = wiring_problems(objc_text, misplaced)
            print("%-4s handing the keys back from -viewDidAppear's refresh is refused (%d gaps named)"
                  % ("ok" if any("mid-stream" in p for p in misplaced_problems) else "FAIL",
                     len([p for p in misplaced_problems if "mid-stream" in p])))
            if not any("mid-stream" in p for p in misplaced_problems):
                rc = 1

    return rc


if __name__ == "__main__":
    sys.exit(main())
