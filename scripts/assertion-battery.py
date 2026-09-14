#!/usr/bin/env python3
"""Prove that the keyboard-constraint assertions fail when the code regresses.

An assertion that only looks for words passes on code that no longer behaves,
so every guard we rely on has to be broken on purpose at least once and shown
to be caught. Each mutation below is a realistic regression: the words stay in
place while the behaviour is gone.

Usage: assertion-battery.py [--keep-broken <name>]
Exit 0 only when every mutation is caught by constraints-audit.py.
"""
import os
import re
import subprocess
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HID = os.path.join(root, "Limelight", "Input", "HIDSupport.m")
CAPTURE = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                       "StreamViewController+MouseCapture.m")
MENU = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                    "StreamViewController+MenuUI.m")
SHORTCUTS = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                         "SettingsShortcuts.swift")
DERIVED = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                       "SettingsModel+DerivedValues.swift")
VIDEO_PANE = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                          "SettingsVideoPane.swift")

UP_GUARD = """        if ([self.keyboardSuppressedKeyDownKeyCodes containsObject:physicalKeyCode]) {
            // The host never saw this key go down, so it must not see it come up
            // either: an unmatched release reads as the key being let go by
            // itself, which is what made local shortcuts look like gameplay keys
            // releasing mid-action.
            [self.keyboardSuppressedKeyDownKeyCodes removeObject:physicalKeyCode];
            return;
        }
"""
UP_DISPATCH = """        HIDDispatchInput(self, inputCtx, ^{
            LiSendKeyboardEventCtx(inputCtx, keyCode, KEY_ACTION_UP, modifiers);
        });
"""
DOWN_CLEAR = """        [self.keyboardSuppressedKeyDownKeyCodes removeObject:@(event.keyCode)];
"""
DOWN_DISPATCH = """        HIDDispatchInput(self, inputCtx, ^{
            LiSendKeyboardEventCtx(inputCtx, keyCode, KEY_ACTION_DOWN, modifiers);
        });
"""


def once(text, needle, where):
    if text.count(needle) != 1:
        raise SystemExit("anchor found %d times, expected 1: %s in %s"
                         % (text.count(needle), where, os.path.basename(needle[:40])))
    return text


def neuter_if(text):
    return once(text, UP_GUARD, "keyUp guard").replace(
        "if ([self.keyboardSuppressedKeyDownKeyCodes containsObject:physicalKeyCode]) {",
        "if (NO && [self.keyboardSuppressedKeyDownKeyCodes containsObject:physicalKeyCode]) {", 1)


def no_return(text):
    once(text, UP_GUARD, "keyUp guard")
    return text.replace(
        "[self.keyboardSuppressedKeyDownKeyCodes removeObject:physicalKeyCode];\n            return;",
        "[self.keyboardSuppressedKeyDownKeyCodes removeObject:physicalKeyCode];", 1)


def drop_release(text):
    once(text, UP_GUARD, "keyUp guard")
    return text.replace(
        "            [self.keyboardSuppressedKeyDownKeyCodes removeObject:physicalKeyCode];\n            return;\n",
        "            return;\n", 1)


def late_guard(text):
    once(text, UP_GUARD, "keyUp guard")
    once(text, UP_DISPATCH, "keyUp dispatch")
    rest = text.replace(UP_GUARD, "", 1)
    return rest.replace(UP_DISPATCH, UP_DISPATCH + "\n" + UP_GUARD.rstrip("\n") + "\n", 1)


def commented_guard(text):
    once(text, UP_GUARD, "keyUp guard")
    return text.replace(UP_GUARD, "".join("//" + line + "\n" for line in
                                          UP_GUARD.rstrip("\n").split("\n")), 1)


def neuter_settings(text):
    return once(text, "if ([SettingsWindowObjCBridge isSettingsPresentedInWindow:self.view.window]) {",
                "settings guard").replace(
        "if ([SettingsWindowObjCBridge isSettingsPresentedInWindow:self.view.window]) {",
        "if (NO && [SettingsWindowObjCBridge isSettingsPresentedInWindow:self.view.window]) {", 1)


def late_clear(text):
    once(text, DOWN_CLEAR, "keyDown clear")
    once(text, DOWN_DISPATCH, "keyDown dispatch")
    rest = text.replace(DOWN_CLEAR, "", 1)
    return rest.replace(DOWN_DISPATCH, DOWN_DISPATCH + DOWN_CLEAR, 1)


DOWN_DISPATCH = """        HIDDispatchInput(self, inputCtx, ^{
            LiSendKeyboardEventCtx(inputCtx, keyCode, KEY_ACTION_DOWN, modifiers);
        });
"""
REC = """        [self.keyboardForwardedKeyDownKeyCodes addObject:@(keyCode)];
"""
INIT = """        self.keyboardForwardedKeyDownKeyCodes = [NSMutableSet set];
"""
CLEAR = """    [self.keyboardForwardedKeyDownKeyCodes removeAllObjects];
"""
TEARDOWN = """    // 0) Release keys the host still believes are pressed, before input is
    //    switched off, so an action key held at disconnect cannot stay stuck.
    [self releaseAllHeldKeys];
"""
UNCAPTURE_CALL = """    [self.hidSupport releaseAllHeldKeys];
"""
UNCAPTURE_OFF = """    self.hidSupport.shouldSendInputEvents = NO;
"""


def no_record(text):
    once(text, REC, "held-key record")
    return text.replace(REC, "", 1)


def late_record(text):
    once(text, REC, "held-key record")
    once(text, DOWN_DISPATCH, "keyDown dispatch")
    rest = text.replace(REC, "", 1)
    return rest.replace(DOWN_DISPATCH, DOWN_DISPATCH + REC, 1)


def no_init(text):
    once(text, INIT, "held-key record init")
    return text.replace(INIT, "", 1)


def leak_records(text):
    once(text, CLEAR, "held-key release")
    return text.replace(CLEAR, "", 1)


def drop_teardown_release(text):
    once(text, TEARDOWN, "session teardown")
    return text.replace(TEARDOWN, "", 1)


def drop_uncapture_release(text):
    once(text, UNCAPTURE_CALL, "capture release")
    return text.replace(UNCAPTURE_CALL, "", 1)


def late_uncapture_release(text):
    once(text, UNCAPTURE_CALL, "capture release")
    once(text, UNCAPTURE_OFF, "input switch off")
    rest = text.replace(UNCAPTURE_CALL, "", 1)
    return rest.replace(UNCAPTURE_OFF, UNCAPTURE_OFF + UNCAPTURE_CALL, 1)



FLOOR = "    return modifierCount(relevantModifierFlags(shortcut.modifierFlags)) >= 1\n"
MENU_GATE = "    if (![StreamShortcutProfile shortcutCanMatchKeyboardEvent:shortcut]) {\n"
RULE_GATE = "        if (![StreamShortcutProfile shortcutCanMatchKeyboardEvent:trigger]) {\n"
MENU_EQUIV = "    guard StreamShortcutProfile.shortcutCanMatchKeyboardEvent(shortcut),\n"


def bare_predicate(text):
    once(text, FLOOR, "modifier floor")
    return text.replace(FLOOR, FLOOR.replace(">= 1", ">= 0"), 1)


def bare_menu_gate(text):
    once(text, MENU_GATE, "responder gate")
    return text.replace(MENU_GATE,
                        MENU_GATE.replace("if (![", "if (NO && !["), 1)


def bare_rule_gate(text):
    once(text, RULE_GATE, "translation matcher")
    return text.replace(RULE_GATE,
                        RULE_GATE.replace("if (![", "if (NO && !["), 1)


def bare_menu_equivalent(text):
    once(text, MENU_EQUIV, "menu key equivalent")
    return text.replace(MENU_EQUIV, "    guard true,\n", 1)



MFX_QUERY = "      return MTLFXSpatialScalerDescriptor.supportsDevice(device)\n"
FI_DECISION = "      return slots >= 1 ? .available : .unavailable\n"
SR_GUARD = "      guard !factors.isEmpty else { return .unavailable }\n"
FI_TOGGLE = """  private var frameInterpolationCapabilityAvailable: Bool {
    settingsModel.videoCapabilityMatrix.items.first(where: { $0.id == "enhancement.vtLowLatencyFI" })?
      .availability == .available
  }"""


def unmeasured_mfx(text):
    once(text, MFX_QUERY, "MetalFX query")
    return text.replace(MFX_QUERY, "      return true\n", 1)


def unmeasured_interpolation(text):
    once(text, FI_DECISION, "interpolation decision")
    return text.replace(FI_DECISION, "      return .available\n", 1)


def unmeasured_scaler(text):
    once(text, SR_GUARD, "scaler guard")
    return text.replace(SR_GUARD, "      _ = factors\n", 1)


def constant_toggle(text):
    once(text, FI_TOGGLE, "interpolation toggle gate")
    return text.replace(FI_TOGGLE, """  private var frameInterpolationCapabilityAvailable: Bool {
    return true
  }""", 1)


MUTATIONS = [
    ("neuter-if", HID, neuter_if, "keyUp release guard is disabled but still worded"),
    ("no-return", HID, no_return, "keyUp guard records without returning"),
    ("drop-release", HID, drop_release, "keyUp guard no longer clears the record"),
    ("late-guard", HID, late_guard, "keyUp guard runs after the release is sent"),
    ("commented-guard", HID, commented_guard, "keyUp guard moved into a comment"),
    ("neuter-settings", CAPTURE, neuter_settings, "settings guard is disabled but still worded"),
    ("late-clear", HID, late_clear, "stale record cleared after the press is sent"),
    ("no-record", HID, no_record, "forwarded presses are never recorded"),
    ("late-record", HID, late_record, "the press is recorded after it is sent"),
    ("no-init", HID, no_init, "the held-key set is left nil so records vanish"),
    ("leak-records", HID, leak_records, "the held-key release keeps its records"),
    ("drop-teardown", HID, drop_teardown_release, "session teardown no longer releases held keys"),
    ("drop-uncapture", CAPTURE, drop_uncapture_release, "capture release forgets held keys entirely"),
    ("late-uncapture", CAPTURE, late_uncapture_release, "held keys released after input is switched off"),
    ("bare-predicate", SHORTCUTS, bare_predicate, "the modifier floor is dropped to zero"),
    ("bare-menu-gate", MENU, bare_menu_gate, "the responder gate ignores the floor"),
    ("bare-rule-gate", CAPTURE, bare_rule_gate, "a bare translation rule eats a gameplay key"),
    ("bare-menu-equiv", SHORTCUTS, bare_menu_equivalent, "a bare key becomes a menu key equivalent"),
    ("unmeasured-mfx", DERIVED, unmeasured_mfx, "MetalFX availability falls back to trusting the OS version"),
    ("unmeasured-fi", DERIVED, unmeasured_interpolation, "interpolation claims available without slots"),
    ("unmeasured-sr", DERIVED, unmeasured_scaler, "the scaler ignores an empty scale factor list"),
    ("constant-fi-toggle", VIDEO_PANE, constant_toggle, "the interpolation control ignores the measured capability"),
]


def audit_failed():
    proc = subprocess.run([sys.executable, os.path.join(root, "scripts", "constraints-audit.py")],
                          capture_output=True, text=True, cwd=root)
    detail = [line for line in (proc.stdout + proc.stderr).splitlines() if "FAIL" in line]
    return proc.returncode != 0, detail


def main():
    keep = None
    if "--keep-broken" in sys.argv:
        keep = sys.argv[sys.argv.index("--keep-broken") + 1]

    original = {path: open(path, encoding="utf-8").read()
                for path in {p for _, p, _, _ in MUTATIONS}}
    missed = []
    for name, path, mutate, note in MUTATIONS:
        open(path, "w", encoding="utf-8").write(mutate(original[path]))
        failed, detail = audit_failed()
        open(path, "w", encoding="utf-8").write(original[path])
        caught = "CAUGHT " if failed else "MISSED "
        print("%s %-16s %s" % (caught, name, note))
        if failed and detail:
            print("        %s" % detail[0].strip()[:160])
        if not failed:
            missed.append(name)

    print("\n%d/%d mutations caught" % (len(MUTATIONS) - len(missed), len(MUTATIONS)))
    if missed:
        print("assertions that a real regression would slip past: %s" % ", ".join(missed))
    if keep:
        for name, path, mutate, _ in MUTATIONS:
            if name == keep:
                open(path, "w", encoding="utf-8").write(mutate(original[path]))
                print("left %s applied for manual inspection" % name)
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
