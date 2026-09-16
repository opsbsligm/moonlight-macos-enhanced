#!/usr/bin/env python3
"""Prove that one scroll event consumes the displacement it was given.

`HIDSupport+Scroll.m` quantizes a rewritten or synthetic scroll into notches: it
accumulates `deltaY * rewrittenScrollSpeed` across events, then calls
`HIDConsumeAccumulatedDiscreteScrollClick` and dispatches
`clicks * HIDScrollWheelDelta`. The accumulation is the point of the exercise -- a
trackpad delivers dozens of sub-notch frames, and a fast one delivers several
notches in a frame -- so the consumer owns the question "how much of what arrived
may leave now".

That function clamps its answer to one notch and then subtracts that one notch.
Nothing else in the file ever empties the accumulator: the caller zeroes it only
when a *different* classification path runs, and a scroll gesture that ends simply
stops calling. So a two-finger flick of four notches dispatches one, freezes three,
and loses them the moment the player lifts their fingers. The faster the flick, the
larger the fraction that disappears, which reads on the host as scrolling that
refuses to keep up and then jerks a beat late.

The shipping neighbour, `HIDDispatchAccumulatedHighResScrollDelta`, does the same
job correctly: it clamps to what one packet can carry and subtracts exactly what it
returned, so what is left is always under one unit. It is the control here.

Two properties are checked against the extracted shipping functions:

  * after a consume, what remains must be less than one notch, or the consumer must
    have already emitted the largest single packet the wire can carry -- otherwise
    an amount it was allowed to send is being held back;
  * a gesture -- a burst of frames followed by the player lifting off -- must
    dispatch as many notches as it received, because after lift-off no further
    event exists to empty the accumulator.

`--self-test` re-clamps the consumer to one notch and requires both properties to
go red, because a property that cannot fail is a comment.

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
    "static inline short HIDDispatchAccumulatedHighResScrollDelta",
    "static inline short HIDConsumeAccumulatedDiscreteScrollClick",
]


def block_from(text, anchor):
    """The declaration or definition starting at `anchor`, braces and ';' included."""
    start = text.find(anchor)
    if start < 0:
        raise SystemExit("the shipping header no longer contains %s" % anchor)
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit("no body found for %s" % anchor)
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
        raise SystemExit("unbalanced braces in %s" % anchor)
    return text[start:index + 1] + "\n"


def extract(text):
    out = []
    for anchor in ANCHORS:
        start = text.find(anchor)
        if "const HIDScrollWheelDelta" in anchor:
            end = text.find(";", start)
            if end < 0:
                raise SystemExit("HIDScrollWheelDelta is not a plain constant any more")
            out.append(text[start:end + 1] + "\n")
            continue
        out.append(block_from(text, anchor))
    return "\n".join(out)


TEST_BODY = r"""
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <math.h>
#include <limits.h>

__HELPERS__

static int failures = 0;

static void check(int ok, const char *message) {
    printf("%-4s %s\n", ok ? "ok" : "FAIL", message);
    if (!ok) failures++;
}

// The largest notch count one scroll packet can carry, derived from the shipped
// constant rather than restated: the call site multiplies by HIDScrollWheelDelta
// and stores the result into a short.
static const int kMaxNotchesPerPacket = SHRT_MAX / HIDScrollWheelDelta;

static void consume_case(const char *name, double incoming, double emitted_want) {
    CGFloat accumulated = incoming;
    short emitted = HIDConsumeAccumulatedDiscreteScrollClick(&accumulated);

    // Property 1: nothing the consumer was allowed to send may be held back.
    int held = fabs(accumulated) >= 1.0 && abs((int)emitted) < kMaxNotchesPerPacket;
    check(!held, name);
    if (held) {
        printf("     incoming %.2f notches emitted %d, so %.2f notches are still parked\n",
               incoming, (int)emitted, accumulated);
    }
    if (emitted_want != 0.0) {
        check(fabs((double)emitted - emitted_want) < 0.0001,
              "the same case emits the notches the displacement contains");
    }
}

static void gesture_case(const char *name, double *frames, int count, double want) {
    CGFloat accumulated = 0.0;
    double emitted = 0.0;
    for (int i = 0; i < count; i++) {
        accumulated += frames[i];
        emitted += HIDConsumeAccumulatedDiscreteScrollClick(&accumulated);
    }
    // The player lifted off: no further event arrives, so what is left never ships.
    check(fabs(emitted - want) < 1.0, name);
    if (fabs(emitted - want) >= 1.0) {
        printf("     the gesture asks for %.2f notches and the host is told %.0f\n",
               want, emitted);
    }
}

int main(void) {
    // One sub-notch frame keeps its fraction and sends nothing: correct, and the
    // case the clamp was written for.
    CGFloat half = 0.6;
    check(HIDConsumeAccumulatedDiscreteScrollClick(&half) == 0 && fabs(half - 0.6) < 1e-9,
          "a sub-notch frame sends nothing and keeps its fraction");

    consume_case("a four-notch frame sends four notches", 4.0, 4.0);
    consume_case("a reverse frame of seven notches sends seven", -7.2, 0.0);

    // A flick: several frames, each several notches, then lift-off. This is the
    // shape a two-finger swipe actually has at rewrittenScrollSpeed 1.0.
    double flick[] = {4.0, 6.5, 3.2, 1.8};
    gesture_case("a four-frame flick delivers the notches it contains",
                 flick, 4, 15.5);
    double gentle[] = {0.7, 0.7, 0.7};
    gesture_case("a slow drag over three frames delivers two notches", gentle, 3, 2.0);
    double both_ways[] = {1.5, -1.5};
    gesture_case("a reversal inside one gesture does not bank a notch", both_ways, 2, 0.0);

    // The neighbour that already gets this right: it clamps to the packet and
    // subtracts what it returned, so the residue is always below one unit.
    CGFloat big = 1000.5;
    short sent = HIDDispatchAccumulatedHighResScrollDelta(&big);
    check(sent == 1000 && fabs(big - 0.5) < 1e-9,
          "the high-resolution neighbour sends the whole amount and keeps the fraction");
    CGFloat overflow = 100000.0;
    sent = HIDDispatchAccumulatedHighResScrollDelta(&overflow);
    check(sent == SHRT_MAX && overflow > 0.0,
          "the high-resolution neighbour clamps to one packet instead of wrapping");

    // And the consumer must not wrap either: the call site multiplies by
    // HIDScrollWheelDelta into a short.
    CGFloat huge = 100000.0;
    short notches = HIDConsumeAccumulatedDiscreteScrollClick(&huge);
    check(abs((int)notches) <= kMaxNotchesPerPacket,
          "a single event cannot ask for more notches than one packet can carry");

    printf("%d scroll-notch failures\n", failures);
    return failures ? 1 : 0;
}
"""


def assemble(source):
    return TEST_BODY.replace("__HELPERS__", source)


def reclamp(source):
    """Clamp the answer to one notch again, and keep subtracting that one notch.

    That is the shipped shape this harness was written against: the arrival could
    be several notches, the answer and the subtraction were both one, and the rest
    sat in the accumulator until the gesture stopped.
    """
    anchor = "    CGFloat limit = (CGFloat)(SHRT_MAX / HIDScrollWheelDelta);\n"
    broken = source.replace(
        anchor,
        "    if (whole > 1.0) { whole = 1.0; } else if (whole < -1.0) { whole = -1.0; }\n" + anchor,
        1)
    if broken == source:
        raise SystemExit("the notch consumer no longer clamps the way this fixture rewrites")
    return broken


def build_and_run(directory, source, clang, sdk, label):
    path = os.path.join(directory, "probe.m")
    exe = os.path.join(directory, "probe")
    open(path, "w", encoding="utf-8").write(assemble(source))
    compile_run = subprocess.run(
        [clang, "-isysroot", sdk, "-Wno-deprecated-declarations", "-framework", "Foundation",
         "-o", exe, path], capture_output=True, text=True)
    if compile_run.returncode != 0:
        raise SystemExit("the %s probe did not compile:\n%s" % (label, compile_run.stdout[-2000:]
                                                                + compile_run.stderr[-2000:]))
    run = subprocess.run([exe], capture_output=True, text=True)
    return run.returncode, run.stdout


def main():
    self_test = "--self-test" in sys.argv
    source = extract(open(HEADER, encoding="utf-8").read())
    clang, sdk = clang_and_sdk("scroll notch probe")
    with tempfile.TemporaryDirectory() as tmp:
        rc, out = build_and_run(tmp, source, clang, sdk, "shipped")
        print(out.rstrip())
        if self_test:
            broken_rc, broken_out = build_and_run(tmp, reclamp(source), clang, sdk, "re-clamped")
            caught = [l for l in broken_out.splitlines() if l.startswith("FAIL")]
            print("%-4s re-clamping the consumer to one notch is refused (%d verdicts red)"
                  % ("ok" if broken_rc != 0 and caught else "FAIL", len(caught)))
            if broken_rc == 0 or not caught:
                print(broken_out)
                return 1
            return rc
        return rc


if __name__ == "__main__":
    sys.exit(main())
