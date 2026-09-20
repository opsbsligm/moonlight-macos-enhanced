#!/usr/bin/env python3
"""Prove that holding a controller's Menu button hands over the pointer only when the player allowed it, at one boundary, on both input paths.

Issue #45 is not a request for a gesture. The gesture is old here: hold Menu past a second,
let go, mouse mode flips, the pad rumbles to say so. What the player reported is that a game
which needs a long Menu hold gets their mouse mode changed by it, and there was no way to say
no. The answer has to be one switch, one boundary, and one decision -- this fork reads a
controller through two drivers, and a switch wired into only one of them is a switch that
works on some pads.

So the decision was lifted out of both timer paths into GamepadMenuGesture, compiled whole
with a real clang, and driven with samples: the boundary is tested at exactly one second, the
switch is tested against a hold that began while it was off, and six planted defects have to
be noticed. The default lives in C and in Swift, and nothing but this file compares them.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
HEADER = "Limelight/Input/GamepadMenuGesture.h"
IMPL = "Limelight/Input/GamepadMenuGesture.m"
MFI = "Limelight/Input/ControllerSupport.m"
HID = "Limelight/Input/HIDSupport.m"
DIAG = "Limelight/macOS/ViewControllers/StreamViewController+Diagnostics.m"
SUPPORT = "Limelight/Input/ControllerSupport.h"
PBX = "Moonlight.xcodeproj/project.pbxproj"
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
          re.findall(r'#import\s*"([^"]+)"', impl_raw) == ["GamepadMenuGesture.h"],
          "the gesture needs Foundation and its own header: no GameController, no AppKit")
    return header_raw + "\n" + impl_raw.replace('#import "GamepadMenuGesture.h"\n', "")


DRIVER = r"""
@@RULES@@

typedef struct { double at; int pressed; int enabled; } Sample;

static int failures = 0;

static void expect(const char *what, double required, Sample *samples, int count, int want) {
    MLGamepadMenuGesture gesture = MLGamepadMenuGestureIdle();
    int seen = 0;
    for (int i = 0; i < count; i++) {
        if (MLGamepadMenuGestureToggles(&gesture, samples[i].pressed ? YES : NO,
                                        samples[i].at, samples[i].enabled ? YES : NO, required)) {
            seen++;
        }
    }
    if (seen != want) {
        failures++;
        printf("FAIL %s: %d toggles, wanted %d\n", what, seen, want);
    }
}

int main(void) {
    const double required = MLGamepadMenuLongPressRequiredSeconds;

    { Sample s[] = {{0,1,1},{0.5,1,1},{1.2,1,1},{1.25,0,1}};
      expect("a hold past the boundary toggles once when it is released", required, s, 4, 1); }

    { Sample s[] = {{0,1,1},{1.0,0,1}};
      expect("a release at exactly the boundary stays the game's own short press", required, s, 2, 0); }

    { Sample s[] = {{0,1,1},{0.3,0,1}};
      expect("a short tap never changes mouse mode", required, s, 2, 0); }

    { Sample s[] = {{0,1,1},{1.5,1,1},{3.0,1,1}};
      expect("a hold nobody has released has not toggled yet", required, s, 3, 0); }

    { Sample s[] = {{0,1,0},{2.0,1,0},{2.5,0,0}};
      expect("with the switch off no sample toggles, however long the hold", required, s, 3, 0); }

    { Sample s[] = {{0,1,0},{1.5,1,0},{1.6,1,1},{1.8,0,1}};
      expect("a hold begun while the switch was off does not inherit a timer when it returns",
             required, s, 4, 0); }

    { Sample s[] = {{0,1,0},{1.9,1,0},{2.0,1,1},{3.2,0,1}};
      expect("a hold begun after the switch came back is measured from its own start",
             required, s, 4, 1); }

    { Sample s[] = {{0,1,1},{1.5,0,1},{1.6,0,1}};
      expect("one release cannot toggle twice", required, s, 3, 1); }

    { Sample s[] = {{0,1,1},{0.2,1,0},{0.9,1,1},{1.05,0,1}};
      expect("a hold that straddles the switch coming back on does not bank the time it spent off",
             required, s, 4, 0); }

    { Sample s[] = {{0,1,1},{0.9,1,1},{1.05,0,1}};
      expect("the clock starts at the first sample of the press, not the last one delivered",
             required, s, 3, 1); }

    { Sample s[] = {{0,1,1},{0.6,0,1}};
      expect("the requirement is the one the caller passed, not a constant inside", 0.5, s, 2, 1); }

    printf("%s\n", failures ? "RUN FAILED" : "RUN PASSED");
    return failures ? 1 : 0;
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
        code, out, log = compiled(DRIVER.replace("@@RULES@@", rules), work, "menugesture", cc, sdk)
        if code is None:
            check(False, "%s: %s" % (label, log))
            return
        if expect_pass:
            check(code == 0 and out is not None and "RUN PASSED" in out,
                  "the shipping gesture answers every sample correctly"
                  if code == 0 else "the shipping gesture failed a case:%s" % out)
        else:
            check(code != 0, "the check still fails when %s" % label)


def mutated(rules, label, before, after):
    check(before in rules, "%s: the source it mutates is still there" % label)
    return rules.replace(before, after, 1)


def main():
    rules = shipping_rules()
    print("-- what a long Menu hold on a controller is allowed to do --")

    cc, sdk = apple_toolchain.clang_and_sdk("gamepad menu gesture")
    run_rules("the shipping gesture", rules, cc, sdk, expect_pass=True)

    # --- both drivers have to ask, and ask the same thing ---------------------
    mfi, hid = read(MFI), read(HID)
    check('#import "GamepadMenuGesture.h"' in mfi and '#import "GamepadMenuGesture.h"' in hid,
          "both controller paths import the gesture they decide with")
    for label, text in (("the MFi path", mfi), ("the CoreHID path", hid)):
        check("MLGamepadMenuGestureToggles(&gesture," in text and
              "MLGamepadMenuLongPressRequiredSeconds" in text,
              "%s asks the shared gesture with the shared requirement" % label)
        check("startButtonDownTime" not in text,
              "%s no longer keeps a date of its own" % label)
        check("timeIntervalSinceNow] < -1.0" not in text,
              "%s no longer compares a held date against a private second" % label)
    check("[self->_presenceDelegate respondsToSelector:@selector(gamepadMenuLongPressTogglesMouseModeEnabled)]" in mfi and
          "[self->_presenceDelegate gamepadMenuLongPressTogglesMouseModeEnabled]" in mfi,
          "the MFi path asks the delegate for the switch, having to ask it first")
    check("[SettingsClass gamepadMenuLongPressTogglesMouseModeFor:self.host.uuid]" in hid and
          "- (BOOL)gamepadMenuLongPressTogglesMouseModeEnabled {" in hid,
          "the CoreHID path reads the player's own stored preference for this host")
    check("- (BOOL)gamepadMenuLongPressTogglesMouseModeEnabled {" in read(DIAG) and
          "[SettingsClass gamepadMenuLongPressTogglesMouseModeFor:self.app.host.uuid]" in read(DIAG),
          "the delegate answers the MFi question from the same host preference")
    check("- (BOOL)gamepadMenuLongPressTogglesMouseModeEnabled;" in read(SUPPORT),
          "the question the MFi path asks is declared, not performed by reflection")

    # --- one default, spelled twice --------------------------------------------
    c_default = re.search(r"BOOL MLGamepadMenuLongPressDefault\(void\) \{\s*return (YES|NO);", read(IMPL))
    swift_default = re.search(r"static let defaultGamepadMenuLongPressTogglesMouseMode = (true|false)",
                              read("Limelight/macOS/ViewControllers/SettingsModel+DerivedValues.swift"))
    check(c_default is not None and swift_default is not None and
          (c_default.group(1) == "YES") == (swift_default.group(1) == "true"),
          "C and Swift agree on the shipping default, because one switch is read in one and written in the other")
    check(read(IMPL).count("1.0;") == 1,
          "the boundary is one number in one file")
    check("Input/GamepadMenuGesture.m," in read(PBX),
          "the gesture is named in the project, so it is compiled and not silently absent")

    for table, name in ((EN, "English"), (ZH, "Chinese")):
        text = read(table)
        check('"Gamepad Menu Long Press Toggles Mouse Mode" = ' in text and
              '"Gamepad Menu Long Press Toggles Mouse Mode detail" = ' in text,
              "the %s table answers the switch and its explanation" % name)

    # --- the planted defects --------------------------------------------------
    print("-- the defects this check has to notice --")
    run_rules("the boundary is one second or more instead of more than one second",
              mutated(rules, "the boundary",
                      "toggled = (now - gesture.pressedAt) > requiredSeconds;",
                      "toggled = (now - gesture.pressedAt) >= requiredSeconds;"), cc, sdk)
    run_rules("the switch is read and then ignored",
              mutated(rules, "the switch",
                      "    if (!gestureEnabled) {",
                      "    if (NO && !gestureEnabled) {"), cc, sdk)
    run_rules("turning the switch off leaves the timer it was holding",
              mutated(rules, "a frozen timer",
                      "        if (state != NULL) {\n            *state = MLGamepadMenuGestureIdle();\n        }\n        return false;",
                      "        return false;"), cc, sdk)
    run_rules("a press toggles before the player lets go",
              mutated(rules, "an early toggle",
                      "        // A hold is not yet a toggle. The player has not let go.\n        return false;",
                      "        return true;"), cc, sdk)
    run_rules("a release keeps the press it just answered",
              mutated(rules, "a repeatable release",
                      "    if (state != NULL) {\n        *state = MLGamepadMenuGestureIdle();\n    }\n    return toggled;",
                      "    if (state != NULL) {\n        *state = gesture;\n    }\n    return toggled;"), cc, sdk)
    run_rules("every sample restarts the clock it is watching",
              mutated(rules, "a restarting clock",
                      "        if (!MLGamepadMenuGestureIsHolding(gesture)) {\n            gesture.pressedAt = now;\n        }",
                      "        gesture.pressedAt = now;"), cc, sdk)

    print("%d gamepad-menu-gesture failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
