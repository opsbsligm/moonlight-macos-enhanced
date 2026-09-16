#!/usr/bin/env python3
"""Prove the emulated pointer travels the distance the stick asked for.

Two files move the cursor with the right stick: the HID consumer in
HIDSupport+Pointer.m and the display-link consumer in ControllerSupport.m. The HID one
normalised the stick to a fraction, multiplied by 15.0, and truncated the product to a
short every frame with nothing kept -- so a stick held a little off centre asked for one
and eight tenths pixels a frame and shipped one, losing 45 per cent of the movement
that was asked for, and only a full deflection shipped what it promised. The other path
accumulated and was already exact, which is the same feature answering two different
speeds depending on which device produced the frame. The thresholds disagreed too:
4000 counts out of 32767 on one side, 0.1 of full scale on the other.

Extracted from the shipping sources and run:

  * a stick held just past the deadzone ships the travel it asked for;
  * a full deflection ships the rate the settings promise;
  * rest and below-deadzone send nothing, and keep no debt;
  * the shipped total may trail what was asked but never leads it;
  * a reversal pays back the residue rather than being charged for it;
  * an absurd frame saturates instead of wrapping through SHRT_MIN;
  * the same input under the old per-frame truncation loses travel, which is what
    makes the first verdict mean something.

`--self-test` throws the residue away -- the old behaviour -- and requires the red.

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

EMULATION_HEADER = os.path.join(ROOT, "Limelight", "Input", "MouseEmulation.h")
INTERNAL_HEADER = os.path.join(ROOT, "Limelight", "Input", "HIDSupport_Internal.h")
POINTER_SOURCE = os.path.join(ROOT, "Limelight", "Input", "HIDSupport+Pointer.m")
CONTROLLER_SOURCE = os.path.join(ROOT, "Limelight", "Input", "ControllerSupport.m")
DRAIN_ANCHOR = "static inline short HIDDrainRelativeDelta"

TEST_BODY = r"""
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <math.h>
#include <limits.h>
#include "MouseEmulation.h"

__DRAIN__

static int failures = 0;

static void check(int ok, const char *message) {
    printf("%-4s %s\n", ok ? "ok" : "FAIL", message);
    if (!ok) failures++;
}

/* The shipping call sequence: normalise, then drain at the shared rate. */
static short emulate_frame(double *residual, short stick, double sign) {
    return HIDDrainRelativeDelta(residual,
                                 sign * HIDControllerMouseDeltaForAxis(stick),
                                 HIDMouseEmulationSpeed);
}

/* What shipped before this fix, kept so the first verdict has something to be
 * measured against: the same normalisation, truncated per frame, residue discarded. */
static short truncated_frame(double *ignored_residual, short stick, double sign) {
    (void) ignored_residual;
    double delta = sign * HIDControllerMouseDeltaForAxis(stick);
    return (short)(delta * HIDMouseEmulationSpeed);
}

static double run(short stick, int frames, short (*frame)(double *, short, double)) {
    double residual = 0.0, shipped = 0.0;
    for (int i = 0; i < frames; i++) {
        short move = frame(&residual, stick, 1.0);
        if (move > SHRT_MAX || move < SHRT_MIN) return -1.0;
        shipped += (double)move;
    }
    return shipped;
}

static double asked_for(short stick, int frames) {
    return HIDControllerMouseDeltaForAxis(stick) * HIDMouseEmulationSpeed * (double)frames;
}

int main(void) {
    short held = 4000;                       /* just past the deadzone */
    int frames = 60;                         /* one second at 60Hz */
    double asked = asked_for(held, frames);
    double shipped = run(held, frames, emulate_frame);
    check(shipped >= asked - 1.0 && shipped <= asked,
          "a stick held just past the deadzone ships the travel it asked for");

    double old = run(held, frames, truncated_frame);
    check(old < asked * 0.85,
          "and the old per-frame truncation loses travel on the same input");

    double midway = run(8192, 600, emulate_frame);
    check(midway >= asked_for(8192, 600) - 1.0 && midway <= asked_for(8192, 600),
          "a mid-range deflection adds up over ten times as many frames");
    double full = run(32767, frames, emulate_frame);
    check(full == asked_for(32767, frames),
          "a full deflection ships the rate the settings promise");

    double residual = 0.0;
    check(emulate_frame(&residual, 0, 1.0) == 0 && residual == 0.0,
          "a stick at rest sends nothing and keeps no debt");
    check(emulate_frame(&residual, 3000, 1.0) == 0 && residual == 0.0,
          "a stick inside the deadzone sends nothing and keeps no debt");

    int leading = 0;
    short sticks[] = {3400, 4000, 8192, 16384, 24000, 32767};
    for (int i = 0; i < 6; i++) {
        double rest = 0.0, total = 0.0;
        for (int f = 0; f < 25; f++) {
            short move = emulate_frame(&rest, sticks[i], 1.0);
            if (move > SHRT_MAX || move < SHRT_MIN) leading = 1;
            total += (double)move;
        }
        if (total > asked_for(sticks[i], 25) + 1e-9) leading = 1;
    }
    check(!leading, "the shipped total may trail what was asked but never leads it");

    double debt = 0.0;
    double out = 0.0;
    for (int f = 0; f < 10; f++) out += emulate_frame(&debt, 20000, 1.0);
    for (int f = 0; f < 10; f++) out += emulate_frame(&debt, 20000, -1.0);
    check(fabs(out) <= 1.0, "a reversal pays back the residue instead of charging for it");

    double absurd = 0.0;
    short move = HIDDrainRelativeDelta(&absurd, 1e9, HIDMouseEmulationSpeed);
    check(move == SHRT_MAX, "an absurd frame saturates at one packet instead of wrapping");
    move = HIDDrainRelativeDelta(&absurd, -1e9, HIDMouseEmulationSpeed);
    check(move == SHRT_MIN || move <= -SHRT_MAX,
          "and the same is true going the other way");

    printf("%d mouse-emulation failures\n", failures);
    return failures ? 1 : 0;
}
"""


def drain_block(text):
    start = text.find(DRAIN_ANCHOR)
    if start < 0:
        raise SystemExit("the shipping source no longer defines the draining delta helper")
    brace = text.find("{", start)
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
        raise SystemExit("unbalanced braces in the draining delta helper")
    return text[start:index + 1] + "\n"


def throw_the_residue_away(drainer):
    """Discard the sub-pixel remainder, which is exactly what shipped before."""
    anchor = "    *residual = owed - (CGFloat)move;\n"
    broken = drainer.replace(anchor, "    *residual = 0.0;\n", 1)
    if broken == drainer:
        raise SystemExit("HIDDrainRelativeDelta no longer keeps a residue, so this fixture "
                         "has nothing left to throw away")
    return broken


def source_checks():
    """The two paths have to read the numbers from the one header, not recall them."""
    problems = []
    pointer = open(POINTER_SOURCE, encoding="utf-8").read()
    controller = open(CONTROLLER_SOURCE, encoding="utf-8").read()
    for name, text in (("HIDSupport+Pointer.m", pointer), ("ControllerSupport.m", controller)):
        if "HIDMouseEmulationSpeed" not in text:
            problems.append("%s sets the emulated pointer rate without the shared constant"
                            % name)
    # The HID path takes its deadzone from the shared normaliser; the display-link
    # path reads the same number straight off the stick, so it names the constant.
    if "HIDControllerMouseDeltaForAxis" not in pointer:
        problems.append("HIDSupport+Pointer.m normalises the stick without the shared helper")
    if "HIDMouseEmulationDeadzone" not in controller:
        problems.append("ControllerSupport.m compares the stick without the shared constant")
    if re.search(r"\bfloat\s+sensitivity\s*=\s*15\.0", controller):
        problems.append("ControllerSupport.m keeps its own copy of the rate")
    if re.search(r">\s*0\.1\s*\|\|", controller):
        problems.append("ControllerSupport.m compares the stick against its own deadzone")
    # The block that moves the cursor with the stick is the one that has to drain,
    # and it is worth naming: the same file drains the mouse deltas correctly, so a
    # file-wide search would pass while the stick path truncated again.
    marker = "// Mouse Emulation Movement"
    if marker in pointer:
        block = pointer[pointer.index(marker):]
        # The block ends where the function does. The early return inside it is
        # indented deeper, so matching the function-level one is what keeps the
        # window from closing before the code under check begins.
        end = block.find("\n    return kCVReturnSuccess;")
        block = block if end < 0 else block[:end]
        if "HIDDrainRelativeDelta" not in block:
            problems.append("the stick path answers each frame on its own instead of "
                            "draining the travel it cannot ship")
        if re.search(r"\(short\)", block):
            problems.append("the stick path truncates a frame again, which is the "
                            "shape that lost 45 per cent of a held deflection")
        if re.search(r"3\d{4}|4\d{3}", block) or "32767" in block:
            problems.append("the stick path counts the stick in raw units again, which is "
                            "how two paths came to disagree about where movement begins")
        # Both axes have to take the rate from the shared constant. One of them
        # drifting to a literal is invisible to a search that only asks whether the
        # name appears somewhere in the block.
        axes = block.count("HIDMouseEmulationSpeed")
        if axes != 2:
            problems.append("the stick path takes the shared rate %d times, expected "
                            "once per axis" % axes)
    else:
        problems.append("HIDSupport+Pointer.m no longer has the stick pointer block")
    if not os.path.exists(EMULATION_HEADER):
        problems.append("the shared mouse-emulation header is gone")
    return problems


def main():
    problems = source_checks()
    for line in problems:
        print("FAIL %s" % line)
    clang, sdk = clang_and_sdk("controller mouse emulation probe")
    drainer = drain_block(open(INTERNAL_HEADER, encoding="utf-8").read())

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "probe.m")
        exe = os.path.join(tmp, "probe")
        open(path, "w", encoding="utf-8").write(TEST_BODY.replace("__DRAIN__", drainer))
        compile_run = subprocess.run(
            [clang, "-isysroot", sdk, "-Wno-deprecated-declarations",
             "-framework", "Foundation", "-I", os.path.dirname(EMULATION_HEADER),
             "-o", exe, path], capture_output=True, text=True)
        if compile_run.returncode != 0:
            raise SystemExit("the probe did not compile:\n%s"
                             % (compile_run.stdout[-2000:] + compile_run.stderr[-2000:]))
        run = subprocess.run([exe], capture_output=True, text=True)
        print(run.stdout.rstrip())
        rc = run.returncode or (1 if problems else 0)

        if "--self-test" in sys.argv:
            open(path, "w", encoding="utf-8").write(
                TEST_BODY.replace("__DRAIN__", throw_the_residue_away(drainer)))
            subprocess.run([clang, "-isysroot", sdk, "-Wno-deprecated-declarations",
                            "-framework", "Foundation",
                            "-I", os.path.dirname(EMULATION_HEADER), "-o", exe, path],
                           capture_output=True, text=True, check=True)
            broken = subprocess.run([exe], capture_output=True, text=True)
            caught = [l for l in broken.stdout.splitlines() if l.startswith("FAIL")]
            print("%-4s throwing the residue away is refused (%d verdicts red)"
                  % ("ok" if broken.returncode != 0 and caught else "FAIL", len(caught)))
            if broken.returncode == 0 or not caught:
                print(broken.stdout)
                return 1
        return rc


if __name__ == "__main__":
    sys.exit(main())
