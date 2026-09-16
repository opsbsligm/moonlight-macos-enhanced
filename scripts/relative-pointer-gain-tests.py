#!/usr/bin/env python3
"""Prove the pointer ships the motion it was asked for, not a floor of one pixel.

`HIDScaledRelativeDelta` answers every frame on its own, and its last branch
promises a whole pixel whenever the scaled move is non-zero but under one. Frames
arrive at the display-link rate and the low end of Pointer Sensitivity is 0.25 --
which the settings UI offers and the shipping clamp enforces -- so a careful move
asks for a tenth of a pixel per frame and ships a whole one. The promise is
one-directional: nothing ever subtracts the pixels it invented, so the cursor
overshoots on a slow move and drifts on a still hand, and the slider's low half
differences come from how often the promise fires rather than from what the player
set.

`HIDDrainRelativeDelta` replaces it by carrying the sub-pixel remainder to the next
frame, so what ships over a run of frames differs from what was asked by under a
pixel. Slow motion lands a frame late -- that is what scaling is -- and a reversal
pays the residue back instead of being charged for it.

Two things are checked, because a fix that only exists in the header is not a fix:

  * behaviour, from the extracted shipping functions: over a burst of frames the
    shipped total must track the asked total within one pixel at both ends of the
    real sensitivity range, zero motion must ship nothing, and a reversal must not
    be billed for the motion it undoes;
  * wiring: both relative paths in the shipping sources must drain, and the
    per-frame answer may not come back for pointer motion.

`--self-test` puts the per-frame promise back in both places and requires red.

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
POINTER_M = os.path.join(ROOT, "Limelight", "Input", "HIDSupport+Pointer.m")
HID_M = os.path.join(ROOT, "Limelight", "Input", "HIDSupport.m")


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
    end = text.find(";", start)
    return text[start:end + 1] + "\n"


def sensitivity_bounds():
    """The slider's real ends, read out of the function that enforces them."""
    text = open(HEADER, encoding="utf-8").read()
    match = re.search(r"MIN\(MAX\(sensitivity,\s*([0-9.]+)\),\s*([0-9.]+)\)", text)
    if not match:
        raise SystemExit("pointer sensitivity is no longer clamped by one expression, so "
                         "this harness would be testing numbers nobody uses")
    return float(match.group(1)), float(match.group(2))


TEST_BODY = r"""
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <math.h>
#include <limits.h>

__CONSTANTS__
__HELPERS__

static const double kSensitivityLow = __SENS_LOW__;
static const double kSensitivityHigh = __SENS_HIGH__;
static int failures = 0;

static void check(int ok, const char *message) {
    printf("%-4s %s\n", ok ? "ok" : "FAIL", message);
    if (!ok) failures++;
}

// One display-link frame of motion, drained the way the shipping callback does it.
static double ship(const double *frames, int count, double sensitivity, int per_frame) {
    CGFloat residual_x = 0.0, residual_y = 0.0;
    double shipped = 0.0;
    for (int i = 0; i < count; i++) {
        CGFloat raw = frames[i];
        CGFloat normalized = raw / HIDGCMouseRelativeSpeedDivisor;
        short move = per_frame ? HIDScaledRelativeDelta(normalized, sensitivity)
                               : HIDDrainRelativeDelta(&residual_x, normalized, sensitivity);
        shipped += move;
    }
    return shipped;
}

static double asked(const double *frames, int count, double sensitivity) {
    double total = 0.0;
    for (int i = 0; i < count; i++) {
        total += (frames[i] / HIDGCMouseRelativeSpeedDivisor) * sensitivity;
    }
    return total;
}

static void burst(const char *name, double per_frame_delta, int count, double sensitivity) {
    double frames[64];
    for (int i = 0; i < count && i < 64; i++) frames[i] = per_frame_delta;
    double want = asked(frames, count, sensitivity);
    double got = ship(frames, count, sensitivity, 0);
    // Draining leaves a sub-pixel remainder behind, so the shipped total may trail
    // the asked total by anything up to one pixel -- and may never lead it. Leading
    // is exactly what the per-frame floor did, so the two halves of this test are
    // not one tolerance band but a direction.
    check(fabs(got - want) <= 1.0 + 1e-9, name);
    check(got <= want + 1e-9, "the drained total never exceeds what was asked for");
    if (fabs(got - want) > 1.0 + 1e-9) {
        printf("     the player asked for %.2f pixels and the host was told %.0f\n", want, got);
    }
}

int main(void) {
    // The bottom of the slider, moving carefully: a tenth of a pixel a frame.
    burst("a slow move at the bottom of the slider ships what it asked for",
          1.0, 20, kSensitivityLow);
    burst("an even slower move at the bottom of the slider is not invented",
          0.5, 20, kSensitivityLow);
    burst("a slow move at the middle of the slider ships what it asked for",
          0.5, 20, 1.0);
    burst("a fast move ships what it asked for", 25.0, 20, 1.0);
    burst("a fast move at the top of the slider ships what it asked for",
          25.0, 20, kSensitivityHigh);

    // A still hand must not walk the cursor: the old floor shipped a pixel for any
    // non-zero jitter, in whichever direction it happened to point.
    CGFloat residual = 0.0;
    int drifted = 0;
    for (int i = 0; i < 40; i++) {
        double jitter = (i % 2) ? 0.3 : -0.3;
        drifted += HIDDrainRelativeDelta(&residual, jitter / HIDGCMouseRelativeSpeedDivisor,
                                        kSensitivityLow);
    }
    check(drifted == 0, "alternating jitter does not move the cursor");

    // A reversal pays the residue back rather than being charged for it.
    CGFloat debt = 0.0;
    int net = 0;
    net += HIDDrainRelativeDelta(&debt, 0.6 / HIDGCMouseRelativeSpeedDivisor, kSensitivityLow);
    net += HIDDrainRelativeDelta(&debt, -0.6 / HIDGCMouseRelativeSpeedDivisor, kSensitivityLow);
    check(net == 0, "moving back to where the cursor started ships no net motion");

    // Nothing asked, nothing shipped, and the debt is left alone.
    CGFloat kept = 0.7;
    check(HIDDrainRelativeDelta(&kept, 0.0, 1.0) == 0 && fabs(kept - 0.7) < 1e-9,
          "a frame with no motion ships nothing and keeps the debt");

    // One packet is a short, so the debt must survive an absurd frame instead of
    // wrapping into the opposite direction.
    CGFloat huge = 0.0;
    short move = HIDDrainRelativeDelta(&huge, 1e6, kSensitivityHigh);
    check(move <= SHRT_MAX && move > 0 && huge > 0.0,
          "an absurd frame clamps to one packet and keeps the rest");

    // The per-frame answer, on the same numbers: this is what shipped before, and
    // it is asserted to overshoot so the case above cannot silently become this one.
    double frames[20];
    for (int i = 0; i < 20; i++) frames[i] = 1.0;
    double want = asked(frames, 20, kSensitivityLow);
    double old = ship(frames, 20, kSensitivityLow, 1);
    check(old > want + 1.0,
          "the per-frame one-pixel floor is still the overshoot this replaces");

    printf("%d relative-pointer failures\n", failures);
    return failures ? 1 : 0;
}
"""


def assemble(constants, helpers, low, high):
    return (TEST_BODY.replace("__CONSTANTS__", constants)
            .replace("__HELPERS__", helpers)
            .replace("__SENS_LOW__", repr(low))
            .replace("__SENS_HIGH__", repr(high)))


def drain_by_per_frame(helpers):
    """Make the drain answer each frame on its own, exactly as the old code did."""
    anchor = "    CGFloat owed = *residual + (delta * sensitivity);\n"
    broken = helpers.replace(
        anchor,
        "    CGFloat owed = (delta * sensitivity);\n"
        "    if (fabs(owed) < 1.0 && owed != 0.0) { owed = owed > 0.0 ? 1.0 : -1.0; }\n", 1)
    if broken == helpers:
        raise SystemExit("HIDDrainRelativeDelta no longer accumulates its own debt")
    return broken


PAIRS = {
    # file: the residual pair that file has to drain into
    POINTER_M: ("relativeMotionResidualX", "relativeMotionResidualY"),
    HID_M: ("relativeDeltaResidualX", "relativeDeltaResidualY"),
}


def call_sites(use_per_frame):
    """Both relative paths, optionally rewired to the per-frame answer."""
    out = []
    for path, (residual_x, residual_y) in PAIRS.items():
        text = open(path, encoding="utf-8").read()
        if use_per_frame:
            text = re.sub(r"HIDDrainRelativeDelta\(&residual([XY]), (\w+), sensitivity\)",
                          r"HIDScaledRelativeDelta(\2, sensitivity)", text)
            text = text.replace("me.relativeMotionResidual", "// dropped ")
            text = text.replace("self.relativeDeltaResidual", "// dropped ")
        drained = len(re.findall(r"HIDDrainRelativeDelta\(&residual[XY],", text))
        per_frame = len(re.findall(r"HIDScaledRelativeDelta\(", text))
        stored = [name for name in (residual_x, residual_y)
                  if re.search(r"\.(%s)\s*=" % name, text)]
        out.append((os.path.basename(path), drained, per_frame, stored))
    return out


def wiring_problems(sites):
    problems = []
    for name, drained, per_frame, stored in sites:
        if drained != 2:
            problems.append("%s drains relative motion %d times, expected two axes" % (name, drained))
        if per_frame != 0:
            problems.append("%s still answers relative pointer motion per frame (%d)" % (name, per_frame))
        if len(stored) != 2:
            problems.append("%s does not write both halves of its residual back (%s)"
                            % (name, ", ".join(stored) or "neither"))
    return problems


def build_and_run(directory, constants, helpers, low, high, label):
    path = os.path.join(directory, "probe.m")
    exe = os.path.join(directory, "probe")
    open(path, "w", encoding="utf-8").write(assemble(constants, helpers, low, high))
    compile_run = subprocess.run([clang_and_sdk_cli, "-isysroot", sdk,
                                  "-Wno-deprecated-declarations", "-framework", "Foundation",
                                  "-o", exe, path], capture_output=True, text=True)
    if compile_run.returncode != 0:
        raise SystemExit("the %s probe did not compile:\n%s"
                         % (label, compile_run.stdout[-2000:] + compile_run.stderr[-2000:]))
    run = subprocess.run([exe], capture_output=True, text=True)
    return run.returncode, run.stdout


clang_and_sdk_cli = None
sdk = None


def main():
    global clang_and_sdk_cli, sdk
    clang_and_sdk_cli, sdk = clang_and_sdk("relative pointer probe")

    header = open(HEADER, encoding="utf-8").read()
    pointer = open(POINTER_M, encoding="utf-8").read()
    helpers = (block_from(header, "static inline short HIDScaledRelativeDelta",
                          "the per-frame relative scale")
               + block_from(header, "static inline short HIDDrainRelativeDelta",
                            "the draining relative scale"))
    constants = constant(pointer, "static CGFloat const HIDGCMouseRelativeSpeedDivisor",
                         "the GameController relative divisor")
    low, high = sensitivity_bounds()

    rc, out = 0, ""
    with tempfile.TemporaryDirectory() as tmp:
        rc, out = build_and_run(tmp, constants, helpers, low, high, "shipped")
        print(out.rstrip())

        problems = wiring_problems(call_sites(False))
        for problem in problems:
            print("FAIL both relative pointer paths drain their motion\n     %s" % problem)
        if problems:
            failures = len(problems)
            rc = rc or 1
            print("%d relative-pointer failures" % (failures + max(0, rc)))

        if "--self-test" in sys.argv:
            broken_rc, broken_out = build_and_run(tmp, constants,
                                                  drain_by_per_frame(helpers), low, high,
                                                  "per-frame")
            caught = [l for l in broken_out.splitlines() if l.startswith("FAIL")]
            rewired = wiring_problems(call_sites(True))
            print("%-4s rewiring the pointer to the per-frame answer is refused (%d paths named)"
                  % ("ok" if rewired else "FAIL", len(rewired)))
            print("%-4s draining replaced by the one-pixel floor is refused (%d verdicts red)"
                  % ("ok" if broken_rc != 0 and caught else "FAIL", len(caught)))
            if not rewired or broken_rc == 0 or not caught:
                print(broken_out)
                return 1

    return rc


if __name__ == "__main__":
    sys.exit(main())
