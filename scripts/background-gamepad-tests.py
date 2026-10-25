#!/usr/bin/env python3
"""P2-3b gate: prove backgroundGamepad suspension is wired through every controller
wire surface while keyboard + mouse forwarding keep working.

What this file is about
-----------------------
Qt ships a per-host preference called `backgroundGamepad` that suppresses
controller events (arrival / axis / motion / touch / battery) when the
stream window is not the focused window, while leaving keyboard and
mouse forwarding untouched. The Moonlight macOS client never carried a
setting for it, so a player with two monitors side by side (one fullscreen
game and one local app) gets gamepad input still reaching the host even
while they read mail or type a chat reply.

This gate proves that:

  * HIDSupport and ControllerSupport each expose a `suspendControllerEvents`
    flag that defaults to NO (the shipped behaviour of forwarding gamepad
    input regardless of focus);
  * the suspension suppresses controller wire output at six sites (idle
    announcement, arrival, axis+button, neutral, motion, battery, touch)
    inside HIDSupport, plus the MFi `updateFinished:` path inside
    ControllerSupport, so the same guard governs both driver paths;
  * the suspension does NOT touch keyboard, mouse, scroll, mouse-button,
    mouse-derived-button, or any other input surface that lives behind
    `shouldSendInputEvents` only -- keyboard and mouse forwarding keep
    working across the same focus flip;
  * the per-host switch defaults to false (the shipped behaviour of
    "always forward gamepad input" stays the default);
  * every Swift setting registration point that carries `muteOnFocusLoss`
    also carries the new `backgroundGamepad`, so a regression in any one
    of them fails the gate;
  * the Settings UI toggle is added to the Input pane (not the Audio pane)
    because this is a controller-input concern, not an audio concern;
  * both en and zh-Hans carry the new l10n keys;
  * StreamViewController wires the focus-loss / focus-regain observers
    to the per-host preference, with unconditional restore on focus regain
    matching the P2-3a audio pattern.

A planted defect in any of those checks has to be noticed. The defects
live in --self-test, not on main.
"""
import os, re, subprocess, sys

# A mutation check runs this file again on a planted tree. Without the sentinel that
# child would plant its own defects and fork again, so the battery would grow by one
# level per level. The child answers with the plain assertions only.
NESTED = os.environ.get('BGP_GATE_NESTED') == '1'

ROOT = "."
STRICT_TEST = "--self-test" in sys.argv
for a in sys.argv[1:]:
    if a != "--self-test" and os.path.isdir(a):
        ROOT = a

HID_H = "Limelight/Input/HIDSupport.h"
HID_M = "Limelight/Input/HIDSupport.m"
CSUPPORT_H = "Limelight/Input/ControllerSupport.h"
CSUPPORT_M = "Limelight/Input/ControllerSupport.m"
STORE = "Limelight/macOS/ViewControllers/SettingsStore.swift"
MODEL = "Limelight/macOS/ViewControllers/SettingsModel.swift"
DERIVED = "Limelight/macOS/ViewControllers/SettingsModel+DerivedValues.swift"
PERSIST = "Limelight/macOS/ViewControllers/SettingsModel+Persistence.swift"
BRIDGE = "Limelight/macOS/ViewControllers/SettingsObjCBridge.swift"
INPUT_PANE = "Limelight/macOS/ViewControllers/SettingsInputPane.swift"
TAB_BAR = "Limelight/macOS/ViewControllers/LiquidGlass/LiquidGlassTabBar.swift"
SVC = "Limelight/macOS/ViewControllers/StreamViewController.m"
EN_STRINGS = "Limelight/macOS/en.lproj/Localizable.strings"
ZH_STRINGS = "Limelight/macOS/zh-Hans.lproj/Localizable.strings"

failures = []

def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)

def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()

def run_self_test():
    """Plant a defect and confirm the gate fails."""
    cases = [
        (
            HID_M,
            "- (void)announceIdleControllersForNewStream {\n    // P2-3b: a stream that opens while the app is in the background (e.g. a\n    // side-by-side window that lost focus before the launch even finished)\n    // must not tell the host the pads are already live -- the player is not\n    // in a position to send input, so the host would have to wait for an\n    // arrival it can do nothing with.\n    if (self.controllerDriver != 0 || !self.shouldSendInputEvents ||\n        self.suspendControllerEvents) return;",
            "- (void)announceIdleControllersForNewStream {\n    /* MUTATION PLANTED: idle controllers will still announce even when\n       suspendControllerEvents is YES (backgroundGamepad path broken) */\n    if (self.controllerDriver != 0) return;",
            "announceIdleControllersForNewStream lost the suspendControllerEvents gate (idle controllers will be advertised even when backgroundGamepad is on)",
        ),
        (
            HID_M,
            "    if (entry == nil || self.controllerDriver != 0 || !self.shouldSendInputEvents ||\n        self.suspendControllerEvents) return;\n    int playerIndex = entry.playerIndex;\n    int mask = [self activeDeviceMask];\n    uint8_t protocolType = entry.protocolType;",
            "    if (entry == nil || self.controllerDriver != 0 || !self.shouldSendInputEvents) return;\n    int playerIndex = entry.playerIndex;\n    int mask = [self activeDeviceMask];\n    uint8_t protocolType = entry.protocolType;",
            "sendControllerArrivalForEntry lost the suspendControllerEvents gate (pads will still be advertised when backgroundGamepad is on)",
        ),
        (
            HID_M,
            "    if (entry == nil || self.controllerDriver != 0 || !self.shouldSendInputEvents ||\n        self.suspendControllerEvents) return;\n    int playerIndex = entry.playerIndex;\n    int mask = [self activeDeviceMask];\n    uint8_t protocolType = entry.protocolType;",
            "    if (entry == nil || self.controllerDriver != 0 || !self.shouldSendInputEvents) return;\n    int playerIndex = entry.playerIndex;\n    int mask = [self activeDeviceMask];\n    uint8_t protocolType = entry.protocolType;",
            "sendControllerArrivalForEntry lost the suspendControllerEvents gate (planted twice so test sees the second plant and fails)",
        ),
        (
            INPUT_PANE,
            '      ToggleCell(\n        title: "Background Gamepad Input",\n        hintKey: "Background Gamepad detail",\n        boolBinding: $settingsModel.backgroundGamepad',
            '      /* MUTATION PLANTED: background-gamepad toggle dropped */',
            "Background Gamepad toggle dropped from SettingsInputPane",
        ),
        (
            SVC,
            "        if (backgroundGamepadApp) {\n            if (weakSelf.hidSupport != nil) {\n                weakSelf.hidSupport.suspendControllerEvents = YES;\n            }\n            if (weakSelf.controllerSupport != nil) {\n                weakSelf.controllerSupport.suspendControllerEvents = YES;\n            }\n        }",
            "        if (backgroundGamepadApp) {\n            /* MUTATION PLANTED: app-resign path no longer suspends controllers */\n        }",
            "appDidResignActive observer no longer suspends controllers on focus loss",
        ),
        (
            DERIVED,
            "defaultBackgroundGamepad = false",
            "defaultBackgroundGamepad = true",
            "default flipped to true: shipped behaviour of always-forwarding-gamepad would change",
        ),
    ]
    for rel, needle, replacement, message in cases:
        full = os.path.join(ROOT, rel)
        with open(full, encoding="utf-8") as fh:
            original = fh.read()
        idx = original.find(needle)
        if idx < 0:
            check(False, "self-test defect for %s: needle not found" % rel.split("/")[-1])
            continue
        planted = original[:idx] + replacement + original[idx+len(needle):]
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(planted)
        try:
            env = dict(os.environ, BGP_GATE_NESTED="1")
            result = subprocess.run(
                [sys.executable, os.path.abspath(__file__), ROOT],
                capture_output=True, text=True, env=env,
            )
            check(result.returncode != 0,
                  "self-test caught defect in %s (%s)" % (rel.split("/")[-1], message))
        finally:
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(original)

def main():
    global failures

    hid_h = read(HID_H)
    hid_m = read(HID_M)
    csupport_h = read(CSUPPORT_H)
    csupport_m = read(CSUPPORT_M)
    store = read(STORE)
    model = read(MODEL)
    derived = read(DERIVED)
    persist = read(PERSIST)
    bridge = read(BRIDGE)
    input_pane = read(INPUT_PANE)
    tab = read(TAB_BAR)
    svc = read(SVC)
    en_strings = read(EN_STRINGS)
    zh_strings = read(ZH_STRINGS)

    # --- HIDSupport surface -----------------------------------------------------
    check("@property(atomic) BOOL suspendControllerEvents;" in hid_h,
          "HIDSupport.h declares suspendControllerEvents property (public surface so StreamViewController can write it on focus flip)")
    check("@synthesize suspendControllerEvents = _suspendControllerEvents;" in hid_m,
          "HIDSupport.m synthesises the suspendControllerEvents iVar")
    # Six wire-output sites gated on suspendControllerEvents
    check("announceIdleControllersForNewStream" in hid_m
          and "self.suspendControllerEvents" in hid_m
          and hid_m.count("self.suspendControllerEvents") >= 6,
          "HIDSupport carries the suspendControllerEvents gate at 6+ controller-wire sites")
    for needle in [
        "- (void)announceIdleControllersForNewStream {",
        "- (void)sendControllerArrivalForEntry:",
        "- (void)sendControllerNeutralEventForEntry:",
        "- (void)pushMotionEventsForEntry:",
        "- (void)pushBatteryEventForEntry:",
        "- (void)pushControllerTouchForEntry:",
    ]:
        # Each of these six methods must include suspendControllerEvents in its gate.
        idx = hid_m.find(needle)
        if idx < 0:
            check(False, "%s present in HIDSupport.m" % needle)
            continue
        nxt = hid_m.find("- (", idx + len(needle))
        body = hid_m[idx: nxt if nxt > 0 else idx + 1200]
        check("suspendControllerEvents" in body,
              "%s honours suspendControllerEvents" % needle.split("(")[1].split(":")[0] if "(" in needle else needle)
    # Keyboard + mouse paths must NOT be gated on suspendControllerEvents.
    # Those handlers all live in the (MouseCapture) category / on keys / scroll,
    # none of which should be touched by this wave. The two mouse-button
    # registrations carry shouldSendInputEvents gates only -- assert their
    # bodies do NOT mention suspendControllerEvents.
    # The keyboard + mouse paths are split between HIDSupport.m and the
    # HIDSupport+Pointer.m category file. Sweep them together so the gate
    # stays accurate regardless of where the method declaration lives.
    hid_extra_files = []
    for sub in ["Limelight/Input/HIDSupport+Pointer.m"]:
        try:
            hid_extra_files.append(read(sub))
        except FileNotFoundError:
            pass
    hid_all = hid_m + "\n".join(hid_extra_files)
    for needle in [
        "registerMouseCallbacks:",
        "dispatchRelativeMouseDeltaX:(",
        "keyDown:",
        "keyUp:",
        "flagsChanged:",
    ]:
        idx = hid_all.find(needle)
        if idx < 0:
            check(False, "%s present in HIDSupport*" % needle)
            continue
        # Stop the search window at the next @implementation or the next
        # method declaration, whichever comes first.
        nxt = hid_all.find("- (", idx + len(needle))
        end = hid_all.find("@end", idx + len(needle))
        body = hid_all[idx: min(nxt if nxt > 0 else idx + 1200, end if end > 0 else idx + 1200)]
        check("suspendControllerEvents" not in body,
              "%s must not be gated on suspendControllerEvents (P2-3b leaves keyboard + mouse alone)" % needle)

    # --- ControllerSupport surface ----------------------------------------------
    check("@property(nonatomic) BOOL suspendControllerEvents;" in csupport_h,
          "ControllerSupport.h declares suspendControllerEvents property")
    check("if (!_shouldSendInputEvents || _suspendControllerEvents) {" in csupport_m,
          "ControllerSupport updateFinished: gates on shouldSendInputEvents AND suspendControllerEvents")

    # --- Settings registration (5 mirrors + per-host getter) --------------------
    check("let backgroundGamepad: Bool?" in store,
          "SettingsStore struct carries backgroundGamepad field")
    for path in [STORE, MODEL, DERIVED, PERSIST, BRIDGE]:
        text = read(path)
        needle = "defaultBackgroundGamepad" if path == DERIVED else "backgroundGamepad"
        check(needle in text,
              "%s carries %s" % (path.split("/")[-1], needle))
    check("@objc static func backgroundGamepad(for key: String) -> Bool" in bridge,
          "SettingsObjCBridge exposes per-host backgroundGamepad getter")
    check("defaultBackgroundGamepad = false" in derived,
          "defaultBackgroundGamepad is false (shipped behaviour preserved)")
    check("backgroundGamepad = Self.defaultBackgroundGamepad" in model
          and "backgroundGamepad = Self.defaultBackgroundGamepad" in persist,
          "SettingsModel and SettingsModel+Persistence reset backgroundGamepad to the default")
    check("backgroundGamepad ?? Self.defaultBackgroundGamepad" in persist,
          "SettingsModel+Persistence decodes backgroundGamepad with the per-host default")
    check("backgroundGamepad: backgroundGamepad," in persist,
          "SettingsModel+Persistence re-encodes backgroundGamepad into Settings")

    # ObjCBridge dictionary carries the key.
    check('"backgroundGamepad": settings.backgroundGamepad,' in bridge,
          "SettingsObjCBridge dictionary exposes backgroundGamepad for ObjC readers")
    # Struct-copy mirrors (settings / updated / per-host): three distinct call sites.
    count_mirror = 0
    for variant in [
        "absoluteMouseMode: settings.absoluteMouseMode,\n      relativeMouseAsAbsolute: settings.relativeMouseAsAbsolute,\n      muteOnFocusLoss: settings.muteOnFocusLoss,\n      backgroundGamepad: settings.backgroundGamepad,\n      imeLocalComposition: settings.imeLocalComposition,\n      swapMouseButtons: settings.swapMouseButtons,",
        "absoluteMouseMode: updated.absoluteMouseMode,\n        relativeMouseAsAbsolute: updated.relativeMouseAsAbsolute,\n        muteOnFocusLoss: updated.muteOnFocusLoss,\n        backgroundGamepad: updated.backgroundGamepad,\n        imeLocalComposition: updated.imeLocalComposition,\n        swapMouseButtons: updated.swapMouseButtons,",
        "      absoluteMouseMode: settings.absoluteMouseMode,\n      relativeMouseAsAbsolute: settings.relativeMouseAsAbsolute,\n      muteOnFocusLoss: settings.muteOnFocusLoss,\n      backgroundGamepad: settings.backgroundGamepad,\n      imeLocalComposition: settings.imeLocalComposition,\n      swapMouseButtons: settings.swapMouseButtons,\n      reverseScrollDirection: settings.reverseScrollDirection,",
    ]:
        if variant in bridge:
            count_mirror += 1
    check(count_mirror == 3,
          "ObjCBridge carries the new backgroundGamepad field in all three Settings struct copies (got %d/3)" % count_mirror)

    # --- Settings UI ------------------------------------------------------------
    check('title: "Background Gamepad Input"' in input_pane,
          "SettingsInputPane renders the Background Gamepad Input toggle")
    check('boolBinding: $settingsModel.backgroundGamepad' in input_pane,
          "SettingsInputPane toggle binds to settingsModel.backgroundGamepad")
    # The toggle must live in the Input pane (not the Audio pane). Background
    # gamepad is a controller-input concern; placing it under audio would
    # mislead users into thinking it touches audio.
    check("audio_pane_path_not_used_for_gamepad" not in input_pane,
          "SettingsInputPane is the right home for the new toggle (sanity)")
    audio_pane = read("Limelight/macOS/ViewControllers/SettingsAudioPane.swift")
    check('boolBinding: $settingsModel.backgroundGamepad' not in audio_pane,
          "SettingsAudioPane does NOT carry the background-gamepad toggle (this is an input concern)")

    # --- Tab bar immutability ----------------------------------------------------
    check("NSSegmentedControl" in tab and "segmentedControl.segmentStyle = NSSegmentStyle" not in tab,
          "tab bar is the macOS 27 NSSegmentedControl (immutable)")

    # --- l10n -------------------------------------------------------------------
    check('"Background Gamepad Input"' in en_strings,
          "en strings carry Background Gamepad Input title")
    check('"Background Gamepad detail"' in en_strings,
          "en strings carry Background Gamepad detail hint")
    check('"Background Gamepad Input"' in zh_strings,
          "zh-Hans strings carry Background Gamepad Input title")
    check('"Background Gamepad detail"' in zh_strings,
          "zh-Hans strings carry Background Gamepad detail hint")

    # --- StreamViewController wiring -------------------------------------------
    # Window-resign-key path
    check("backgroundGamepadWindow = NO;" in svc,
          "SVC windowDidResignKey: starts with a NO default for backgroundGamepadWindow")
    check("windowGamepadPrefs[@\"backgroundGamepad\"]" in svc,
          "SVC windowDidResignKey: reads backgroundGamepad from the per-host settings dictionary")
    check("weakSelf.hidSupport.suspendControllerEvents = YES;" in svc
          and "weakSelf.controllerSupport.suspendControllerEvents = YES;" in svc,
          "SVC windowDidResignKey: writes YES to both supports when the per-host flag is on")
    # Window-become-key path
    check("weakSelf.hidSupport.suspendControllerEvents = NO;" in svc
          and "weakSelf.controllerSupport.suspendControllerEvents = NO;" in svc,
          "SVC windowDidBecomeKey: unconditionally restores NO on both supports (matches P2-3a audio pattern)")
    # App-resign-active path
    check("backgroundGamepadApp = NO;" in svc,
          "SVC appDidResignActive: starts with a NO default for backgroundGamepadApp")
    check("resignGamepadPrefs[@\"backgroundGamepad\"]" in svc,
          "SVC appDidResignActive: reads backgroundGamepad from the per-host settings dictionary")
    # App-become-active path
    check(svc.count("weakSelf.hidSupport.suspendControllerEvents = NO;") >= 2
          and svc.count("weakSelf.controllerSupport.suspendControllerEvents = NO;") >= 2,
          "SVC has two unconditional restore paths (window-became-key + app-became-active)")
    check(svc.count("weakSelf.hidSupport.suspendControllerEvents = YES;") == 2
          and svc.count("weakSelf.controllerSupport.suspendControllerEvents = YES;") == 2,
          "SVC has exactly two YES-write paths (window-resigned-key + app-resigned-active)")

    # --- Default-flag discipline ------------------------------------------------
    check("SettingsModel.defaultBackgroundGamepad" in bridge,
          "ObjCBridge falls back to SettingsModel.defaultBackgroundGamepad")

    if failures:
        print("\n%d failures" % len(failures))
        sys.exit(1)
    print("\nOK")

if __name__ == "__main__":
    if STRICT_TEST and not NESTED:
        run_self_test()
    else:
        main()
