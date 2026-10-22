#!/usr/bin/env python3
"""Record and replay the single-controller wire tuple, byte for byte.

Campaign 0.2 is the one big refactor of the campaign plan: the HID path keeps a
single `Controller` and a hard-coded mask of 1, and the per-device state table
will change how the send path is called. The refactor is only safe once
"what one connected controller sends" is something a machine compares, not
something a reviewer remembers. This gate is the recorded baseline: the
shipping tuple computation is compiled with a real clang and replayed against
the tuples the inline code sent before it was factored into
`ControllerEventBaseline.m`.

The tuples are the exact arguments of `LiSendMultiControllerEventCtx`:
playerIndex, mask, buttons, both triggers, both sticks. The three rules the
tuple must keep are asserted, not assumed -- Guide emulation (Start+Select
becomes Guide, never alongside it), the mask fixed at 1 until M1 owns
advertisement, and the two "sends nothing" gates (input off, mouse mode).

The driver itself is a gate: it prints how many checks it ran, and a count
that shrank in silence fails, because a harness with deleted cases still
reports success. The wiring is checked from the text of the tree as well,
because a baseline nobody calls is a baseline nothing protects.

Self-test mode (`--self-test`) plants the mutations below into a temporary
copy of the shipping source and requires each one to be caught; a gate that
only passes tells you nothing about whether it would notice.

Usage: controller-event-baseline.py [root] | --self-test [root]
Exit 0 when the shipping baseline replays, every mutation is caught, and the
wiring holds.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = "."
args = [a for a in sys.argv[1:] if a != "--self-test"]
SELF_TEST = "--self-test" in sys.argv
if args:
    ROOT = args[0]

BASELINE_HEADER = "Limelight/Input/ControllerEventBaseline.h"
BASELINE_SOURCE = "Limelight/Input/ControllerEventBaseline.m"
HID = "Limelight/Input/HIDSupport.m"
PBX = "Moonlight.xcodeproj/project.pbxproj"
# The real protocol header, copied next to the harness sources: the baseline
# must compute against the flag values the shipping tree uses, not a shadow
# of them, or a constant that drifts on one side and not the other passes.
LIMITED_INCLUDE = "moonlight-common/moonlight-common-c/src/Limelight.h"

# The floor, not a claim about the exact number: the shipped driver prints how
# many checks it ran, and this refuses a run that quietly lost cases.
MIN_DRIVER_CHECKS = 21

failures = []


def check(cond, label):
    if cond:
        print("ok   " + label)
    else:
        print("FAIL " + label)
        failures.append(label)


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
        return handle.read()


# The recorded tuples: what the inline code in sendControllerEvent sent before
# it was factored, for one connected single controller.
CASES = [
    # (player, buttons_in, mouse, send_on, expected_sent, expected_out, sticks)
    # sticks = (lt, rt, lx, ly, rx, ry)
    (0, 0, False, True, True, (0, 1, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0)),
    (0, 0x0010, False, True, True, (0, 1, 0x0010, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0)),
    (0, 0x0020, False, True, True, (0, 1, 0x0020, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0)),
    # Start + Select -> Guide, with both source bits cleared.
    (0, 0x0010 | 0x0020, False, True, True, (0, 1, 0x0400, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0)),
    # Guide alone is not a chord: it stays exactly what it is.
    (0, 0x0400, False, True, True, (0, 1, 0x0400, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0)),
    # Every flag set: the Guide chord still fires on the PLAY|BACK bits (cleared) and
    # re-added as Guide; the rest of the word passes through untouched.
    (0, 0xFFFF, False, True, True, (0, 1, 0xFFCF, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0)),
    # A flag from a different device family must not be touched by emulation.
    (0, 0x3000 | 0x0010 | 0x0020, False, True, True, (0, 1, 0x3400, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0)),
    (0, 0x1000, False, True, True, (0, 1, 0x1000, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0)),
    (0, 0x2000, False, True, True, (0, 1, 0x2000, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0)),
    (1, 0x0010, False, True, True, (1, 1, 0x0010, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0)),
    (3, 0, False, True, True, (3, 1, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0)),
    # Mouse mode: the tuple is computed but nothing goes out.
    (0, 0x0010, True, True, False, None, (0, 0, 0, 0, 0, 0)),
    (0, 0x0010 | 0x0020, True, True, False, None, (0, 0, 0, 0, 0, 0)),
    # Input gated off: same, for the gate.
    (0, 0x0010, False, False, False, None, (0, 0, 0, 0, 0, 0)),
    (0, 0x0010 | 0x0020, False, False, False, None, (0, 0, 0, 0, 0, 0)),
    # Triggers saturate; sticks span the full 16-bit range.
    (0, 0, False, True, True, (0, 1, 0, 255, 0, 0, 0, 0, 0), (255, 0, 0, 0, 0, 0)),
    (0, 0, False, True, True, (0, 1, 0, 0, 255, 0, 0, 0, 0), (0, 255, 0, 0, 0, 0)),
    (0, 0, False, True, True, (0, 1, 0, 255, 255, 32767, -32768, 32767, -32768),
     (255, 255, 32767, -32768, 32767, -32768)),
    (0, 0, False, True, True, (0, 1, 0, 128, 127, -1, 1, -2, 2), (128, 127, -1, 1, -2, 2)),
    (0, 0, False, True, True, (0, 1, 0, 1, 2, 100, 200, 300, 400), (1, 2, 100, 200, 300, 400)),
    (0, 0, False, True, True, (0, 1, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0)),
]


DRIVER_TEMPLATE = """
#import <Foundation/Foundation.h>
#import <string.h>
#import "Controller.h"
#import "ControllerEventBaseline.h"

typedef struct {
    int player;
    int buttons;
    BOOL mouse;
    BOOL sendOn;
    BOOL expectSent;
    ControllerWireEvent expected;
} Case;
typedef struct {
    unsigned char lt;
    unsigned char rt;
    short lx;
    short ly;
    short rx;
    short ry;
} StickState;

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        Case cases[] = {
            __CASES__
        };
        StickState sticks[] = {
            __STICKS__
        };
        int n = (int)(sizeof(cases) / sizeof(cases[0]));
        int failed = 0;
        for (int i = 0; i < n; i++) {
            Controller *c = [Controller new];
            c.playerIndex = cases[i].player;
            c.lastButtonFlags = cases[i].buttons;
            c.isMouseMode = cases[i].mouse;
            c.lastLeftTrigger = sticks[i].lt;
            c.lastRightTrigger = sticks[i].rt;
            c.lastLeftStickX = sticks[i].lx;
            c.lastLeftStickY = sticks[i].ly;
            c.lastRightStickX = sticks[i].rx;
            c.lastRightStickY = sticks[i].ry;
            ControllerWireEvent got;
            memset(&got, 0xEE, sizeof(got));
            BOOL sent = ControllerEventBaselineFromController(c, cases[i].sendOn, &got);
            if (sent != cases[i].expectSent) {
                printf("case %d: sent=%d expected=%d\\n", i, sent, cases[i].expectSent);
                failed++;
                continue;
            }
            if (sent) {
                // Field by field: a memcmp over the struct would compare padding
                // the sender never writes, and fail on bytes nobody owns.
                if (got.playerIndex != cases[i].expected.playerIndex ||
                    got.mask != cases[i].expected.mask ||
                    got.buttons != cases[i].expected.buttons ||
                    got.leftTrigger != cases[i].expected.leftTrigger ||
                    got.rightTrigger != cases[i].expected.rightTrigger ||
                    got.leftStickX != cases[i].expected.leftStickX ||
                    got.leftStickY != cases[i].expected.leftStickY ||
                    got.rightStickX != cases[i].expected.rightStickX ||
                    got.rightStickY != cases[i].expected.rightStickY) {
                    printf("case %d: got { pi=%d mask=%d buttons=0x%04x lt=%u rt=%u lX=%d lY=%d rX=%d rY=%d } "
                           "expected { pi=%d mask=%d buttons=0x%04x lt=%u rt=%u lX=%d lY=%d rX=%d rY=%d }\\n",
                           i, got.playerIndex, got.mask, got.buttons, got.leftTrigger, got.rightTrigger,
                           got.leftStickX, got.leftStickY, got.rightStickX, got.rightStickY,
                           cases[i].expected.playerIndex, cases[i].expected.mask, cases[i].expected.buttons,
                           cases[i].expected.leftTrigger, cases[i].expected.rightTrigger,
                           cases[i].expected.leftStickX, cases[i].expected.leftStickY,
                           cases[i].expected.rightStickX, cases[i].expected.rightStickY);
                    failed++;
                }
            }
        }
        if (failed) {
            printf("RUN FAILED (%d of %d cases)\\n", failed, n);
            return 1;
        }
        printf("RUN PASSED (%d checks)\\n", n);
        return 0;
    }
}
"""


def driver_source():
    def expected_literal(expected_out):
        if expected_out is None:
            return "{ 0, 0, 0, 0, 0, 0, 0, 0, 0 }"
        pi, mask, buttons, lt, rt, lx, ly, rx, ry = expected_out
        return ("{ %d, %d, 0x%04X, %d, %d, %d, %d, %d, %d }"
                % (pi, mask, buttons, lt, rt, lx, ly, rx, ry))
    cases_objc = ",\n".join(
        "{ %d, 0x%04X, %s, %s, %s, %s }" % (
            player, buttons_in,
            "YES" if mouse else "NO",
            "YES" if send_on else "NO",
            "YES" if expected_sent else "NO",
            expected_literal(expected_out))
        for (player, buttons_in, mouse, send_on, expected_sent, expected_out, _sticks) in CASES
    )
    sticks_objc = ",\n".join(
        "{ %d, %d, %d, %d, %d, %d }" % sticks
        for (_p, _b, _m, _s, _e, _o, sticks) in CASES
    )
    return (DRIVER_TEMPLATE
            .replace("__CASES__", cases_objc)
            .replace("__STICKS__", sticks_objc))


def compile_and_run(source, work, cc, sdk):
    for name, text in (
            ("Controller.h", read("Limelight/Input/Controller.h")),
            ("Controller.m", read("Limelight/Input/Controller.m")),
            ("GamepadMenuGesture.h", read("Limelight/Input/GamepadMenuGesture.h")),
            ("HapticContext.h", read("Limelight/Input/HapticContext.h")),
            ("ControllerEventBaseline.h", read(BASELINE_HEADER)),
            ("ControllerEventBaseline.m", source),
            ("Limelight.h", read(LIMITED_INCLUDE)),
            ("driver.m", driver_source())):
        with open(os.path.join(work, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    binary = os.path.join(work, "baseline")
    built = subprocess.run(
        [cc, "-x", "objective-c", "-fobjc-arc", "-fmodules", "-isysroot", sdk,
         "-Wall", "-Werror",
         "-framework", "Foundation", "-framework", "GameController",
         "-framework", "CoreHaptics",
         os.path.join(work, "Controller.m"),
         os.path.join(work, "driver.m"),
         os.path.join(work, "ControllerEventBaseline.m"),
         "-o", binary],
        capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr).strip()[-2000:]
    ran = subprocess.run([binary], capture_output=True, text=True)
    return ran.returncode, (ran.stdout + ran.stderr).strip()


def mutations_in_source():
    """Label, old, new triples planted into the shipping source by --self-test."""
    return [
        ("the Guide flag is not what it is",
         "lastButtonFlags |= SPECIAL_FLAG;",
         "lastButtonFlags |= 0x0800;"),
        ("the Guide chord is recognized on the wrong pair",
         "if ((lastButtonFlags & (PLAY_FLAG | BACK_FLAG)) == (PLAY_FLAG | BACK_FLAG)) {",
         "if ((lastButtonFlags & (PLAY_FLAG | 0x0100)) == (PLAY_FLAG | 0x0100)) {"),
        ("the mask drifts from the recorded 1",
         "outEvent->mask = 1;",
         "outEvent->mask = 2;"),
        ("the trigger swap",
         "outEvent->leftTrigger = lastLeftTrigger;\n        outEvent->rightTrigger = lastRightTrigger;",
         "outEvent->leftTrigger = lastRightTrigger;\n        outEvent->rightTrigger = lastLeftTrigger;"),
        ("the stick x/y swap",
         "outEvent->leftStickX = lastLeftStickX;\n        outEvent->leftStickY = lastLeftStickY;",
         "outEvent->leftStickX = lastLeftStickY;\n        outEvent->leftStickY = lastLeftStickX;"),
        ("the input gate is deleted",
         "if (!shouldSendInputEvents) {\n        return NO;\n    }",
         "if (NO) {\n        return NO;\n    }"),
        ("the mouse-mode gate is deleted",
         "if (controller.isMouseMode) {\n        return NO;\n    }",
         "if (NO) {\n        return NO;\n    }"),
        ("playerIndex is not passed through",
         "int playerIndex = controller.playerIndex;",
         "int playerIndex = 0;"),
    ]


def run(root):
    global ROOT
    ROOT = root
    cc, sdk = apple_toolchain.clang_and_sdk("the controller baseline harness")
    shipping = read(BASELINE_SOURCE)

    with tempfile.TemporaryDirectory() as work:
        code, log = compile_and_run(shipping, work, cc, sdk)
        if code is None:
            check(False, "the shipping baseline compiles: " + log)
            return
        check(code == 0 and "RUN PASSED" in log,
              "the shipping baseline replays the recorded tuples"
              if code == 0 else "the shipping baseline replay failed: " + log)
        if code != 0 or "RUN PASSED" not in log:
            return
        run_line = next((line for line in log.splitlines() if line.startswith("RUN PASSED")), "")
        checks = int(run_line.split("(")[1].split(" ")[0]) if "(" in run_line else 0
        check(checks >= MIN_DRIVER_CHECKS,
              "the harness runs its whole case list (%d cases in the shipped binary)" % checks
              if checks >= MIN_DRIVER_CHECKS else
              "the harness runs only %d of at least %d cases; a case list that shrank in "
              "silence reports success on less than it used to test" % (checks, MIN_DRIVER_CHECKS))

    hid = read(HID)
    check("ControllerEventBaselineFromController" in hid,
          "the HID send path asks the shared owner for the tuple, rather than "
          "computing it inline where a baseline cannot reach it")
    check("LiSendMultiControllerEventCtx" in hid and "wireEvent.mask" in hid,
          "the HID send path sends the tuple the owner returned, so a mask drift "
          "cannot land in the call without touching the owner")
    check("Input/ControllerEventBaseline.m" in read(PBX),
          "the baseline source is in the project file, where a file nobody compiles "
          "would otherwise rot in silence")


def main():
    run(ROOT)
    if SELF_TEST:
        cc, sdk = apple_toolchain.clang_and_sdk("the controller baseline self-test")
        shipping = read(BASELINE_SOURCE)
        for label, old, new in mutations_in_source():
            if shipping.count(old) != 1:
                check(False, "the self-test mutation '%s' must match exactly once" % label)
                continue
            with tempfile.TemporaryDirectory() as work:
                code, log = compile_and_run(shipping.replace(old, new, 1), work, cc, sdk)
                caught = code == 1 and "RUN FAILED" in log
                check(caught,
                      "the run fails when %s" % label
                      if caught else "NOT CAUGHT (%s): %s" % (label, log))
    total = len(failures)
    print("%s: %d failures" % ("controller-event-baseline", total))
    if failures:
        for label in failures:
            print("  - " + label)
        sys.exit(1)
    print("controller-event-baseline: all checks passed" +
          (" (self-test included)" if SELF_TEST else ""))


if __name__ == "__main__":
    main()
