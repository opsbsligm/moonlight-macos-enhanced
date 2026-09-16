#!/usr/bin/env python3
"""Prove one wheel event carrying several notches is worth several notches.

`HIDScrollEventDiscreteDeltaForAxis` reads the notch count out of the event's own
wheel fields -- raw first, then line, then the AppKit delta -- and those fields carry
more than one notch whenever AppKit coalesces a fast scroll into a single event, when
a free-spinning wheel is moving fast enough to report several detents at once, or when
the driver reports a jump. `HIDNormalizedDiscreteScrollClick` then rounds that count
and clamps it to one notch.

Nothing downstream recovers the difference. This is the accumulated path's cousin with
no accumulator: the quantized branch and the fallback branch each answer once per
event, so a three-notch event ships one notch and the other two never existed. The
round-to-one that clamping was protecting against is a separate thing -- a real detent
that rounds to zero still has to send one notch, or the wheel silently stops -- so the
floor belongs there and nowhere else.

Extracted from the shipping sources and run:

  * a frame of three notches is worth three;
  * a run of frames adds up to what the wheel went through;
  * a detent too small to round to one still sends one, in its own direction;
  * the units a frame may carry are bounded by one packet, so an absurd event clamps
    instead of wrapping through SHRT_MIN and scrolling the host the other way.

`--self-test` restores the one-notch clamp and requires the red.

Needs a clang and macOS SDK pair, which the ubuntu audits job does not have. That is
the only reason this sits in constraints-audit.py's CI_ONLY list rather than being run
by that script itself: the macOS build jobs run it for real, twice, and the excuse is
re-checked there, so if this ever learns to run without a toolchain the exemption
expires and goes red.
"""
import os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apple_toolchain import clang_and_sdk

HEADER = os.path.join(ROOT, "Limelight", "Input", "HIDSupport_Internal.h")

ANCHORS = [
    "static short const HIDScrollWheelDelta",
    "static inline short HIDNormalizedDiscreteScrollClick",
    "static inline short HIDDiscreteScrollPacketUnits",
]


def block_from(text, anchor, what):
    start = text.find(anchor)
    if start < 0:
        raise SystemExit("the shipping source no longer contains %s" % what)
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit("no body found for %s" % what)
    depth, index = 0, brace
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1
    else:
        raise SystemExit("unbalanced braces in %s" % what)
    return text[start:index + 1] + "\n"


def constant(text, anchor, what):
    start = text.find(anchor)
    if start < 0:
        raise SystemExit("the shipping source no longer declares %s" % what)
    return text[start:text.find(";", start) + 1] + "\n"


TEST_BODY = r"""
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <math.h>
#include <limits.h>

__CONSTANT__
__HELPERS__

static int failures = 0;

static void check(int ok, const char *message) {
    printf("%-4s %s\n", ok ? "ok" : "FAIL", message);
    if (!ok) failures++;
}

int main(void) {
    check(HIDNormalizedDiscreteScrollClick(3.0) == 3,
          "a three-notch wheel event is worth three notches");
    check(HIDNormalizedDiscreteScrollClick(-2.0) == -2,
          "a two-notch reverse event is worth two reverse notches");

    int total = 0;
    double frames[] = {2.0, 3.0, 1.0, -4.0};
    for (int i = 0; i < 4; i++) total += HIDNormalizedDiscreteScrollClick(frames[i]);
    check(total == 2, "a run of wheel frames adds up to what the wheel went through");

    // The floor that belongs: a detent that rounds below one still has to move,
    // because a wheel that answers zero is a wheel that appears to stop working.
    check(HIDNormalizedDiscreteScrollClick(0.4) == 1 &&
          HIDNormalizedDiscreteScrollClick(-0.4) == -1,
          "a detent too small to round still sends one notch, in its own direction");
    check(HIDNormalizedDiscreteScrollClick(0.0) == 0, "no detent sends nothing");

    // The clamp that belongs: units have to fit in the short the packet carries, and
    // an absurd frame must saturate rather than wrap through the other sign.
    short units = HIDDiscreteScrollPacketUnits(HIDNormalizedDiscreteScrollClick(1e9), 4.0);
    check(units > 0 && units <= SHRT_MAX,
          "an absurd frame saturates at one packet instead of reversing the host");
    units = HIDDiscreteScrollPacketUnits(HIDNormalizedDiscreteScrollClick(-1e9), 4.0);
    check(units < 0 && units >= SHRT_MIN,
          "and the same is true going the other way");

    // At the speed the feature ships with, the units are exactly the notches scaled.
    check(HIDDiscreteScrollPacketUnits(3, 1.0) == 3 * HIDScrollWheelDelta,
          "at the default wheel speed three notches are three ticks of the wheel");
    check(HIDDiscreteScrollPacketUnits(1, 0.1) > 0,
          "the smallest legal speed still sends a notch somebody asked for");

    printf("%d discrete-scroll failures\n", failures);
    return failures ? 1 : 0;
}
"""


def assemble(constant_text, helpers):
    return TEST_BODY.replace("__CONSTANT__", constant_text).replace("__HELPERS__", helpers)


def restore_the_clamp(helpers):
    """Clamp the notch count to one again, which is the shipped shape."""
    anchor = "    NSInteger limit = SHRT_MAX / HIDScrollWheelDelta;\n"
    broken = helpers.replace(
        anchor,
        "    if (clicks > 1) { clicks = 1; } else if (clicks < -1) { clicks = -1; }\n" + anchor,
        1)
    if broken == helpers:
        raise SystemExit("HIDNormalizedDiscreteScrollClick no longer bounds its notch count, "
                         "so this fixture has nothing left to restore")
    return broken


def main():
    clang, sdk = clang_and_sdk("discrete scroll probe")
    header = open(HEADER, encoding="utf-8").read()
    helpers = "".join(block_from(header, a, a) for a in ANCHORS[1:])
    constant_text = constant(header, ANCHORS[0], "the wheel delta the wire calls one notch")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "probe.m")
        exe = os.path.join(tmp, "probe")
        open(path, "w", encoding="utf-8").write(assemble(constant_text, helpers))
        compile_run = subprocess.run([clang, "-isysroot", sdk, "-Wno-deprecated-declarations",
                                      "-framework", "Foundation", "-o", exe, path],
                                     capture_output=True, text=True)
        if compile_run.returncode != 0:
            raise SystemExit("the probe did not compile:\n%s"
                             % (compile_run.stdout[-2000:] + compile_run.stderr[-2000:]))
        run = subprocess.run([exe], capture_output=True, text=True)
        print(run.stdout.rstrip())
        rc = run.returncode

        if "--self-test" in sys.argv:
            open(path, "w", encoding="utf-8").write(assemble(constant_text,
                                                             restore_the_clamp(helpers)))
            subprocess.run([clang, "-isysroot", sdk, "-Wno-deprecated-declarations",
                            "-framework", "Foundation", "-o", exe, path],
                           capture_output=True, text=True, check=True)
            broken = subprocess.run([exe], capture_output=True, text=True)
            caught = [l for l in broken.stdout.splitlines() if l.startswith("FAIL")]
            print("%-4s restoring the one-notch clamp is refused (%d verdicts red)"
                  % ("ok" if broken.returncode != 0 and caught else "FAIL", len(caught)))
            if broken.returncode == 0 or not caught:
                print(broken.stdout)
                return 1
        return rc


if __name__ == "__main__":
    sys.exit(main())
