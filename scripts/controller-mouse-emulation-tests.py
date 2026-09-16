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
UNCAPTURE_SOURCE = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers",
                                  "StreamViewController+MouseCapture.m")
DRAIN_ANCHOR = "static inline short HIDDrainRelativeDelta"

TEST_BODY = r"""
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <math.h>
#include <limits.h>
#include "MouseEmulation.h"

__DRAIN__

__FACTS__

// One tick of the stick cursor in ControllerSupport.m, in the order the shipping
// source runs it: ask whether motion may reach the host, apply the deadzone,
// accumulate, ship whole pixels, keep the remainder. Where that ask sits is part
// of the shape, so it is baked in too. Every define comes from the shipping
// source rather than from wishful thinking, so this model says what the timer
// does and not what this file would like it to do.
#ifndef STICK_TIMER_IS_GATED
#define STICK_TIMER_IS_GATED 0
#endif
#ifndef STICK_GATE_REFUSES_BEFORE_ACCUMULATING
#define STICK_GATE_REFUSES_BEFORE_ACCUMULATING 0
#endif
#ifndef STICK_TIMER_DROPS_MOTION
#define STICK_TIMER_DROPS_MOTION 0
#endif

static short stick_tick(double *accumulated, double delta, int forwarding,
                        int *sent) {
    int refused = STICK_TIMER_IS_GATED && !forwarding;
    if (refused && STICK_GATE_REFUSES_BEFORE_ACCUMULATING) {
        if (STICK_TIMER_DROPS_MOTION) *accumulated = 0.0;
        return 0;
    }
    if (fabs(delta) > HIDMouseEmulationDeadzone) {
        *accumulated += delta * HIDMouseEmulationSpeed;
    }
    if (refused) {
        if (STICK_TIMER_DROPS_MOTION) *accumulated = 0.0;
        return 0;
    }
    short whole = (short)*accumulated;
    if (whole != 0) {
        *sent += whole;
        *accumulated -= whole;
    }
    return whole;
}

// The mouse-mode click path in ControllerSupport.m: the forwarding gate, the
// edge it refuses, the button the host was told about, and what the uncapture
// commit point does with all three. As above, the defines come from the source.
#ifndef CLICKS_ARE_GATED
#define CLICKS_ARE_GATED 0
#endif
#ifndef CLICK_GATE_COVERS_THE_EDGE
#define CLICK_GATE_COVERS_THE_EDGE 0
#endif
#ifndef HANDBACK_RETURNS_PRESSED_BUTTONS
#define HANDBACK_RETURNS_PRESSED_BUTTONS 0
#endif

#define CLICK_A 1
#define CLICK_B 2

typedef struct {
    int tracker;   /* the last state this handler reported */
    int hostDown;  /* the buttons the host believes are pressed */
    int packets;   /* button packets that reached the host */
} clickPath;

static void click_edge(clickPath *path, int bit, int pressed, int forwarding) {
    int last = (path->tracker & bit) != 0;
    if (last == pressed) return;
    if (CLICKS_ARE_GATED && CLICK_GATE_COVERS_THE_EDGE && !forwarding) return;
    if (pressed) path->tracker |= bit;
    else path->tracker &= ~bit;
    if (CLICKS_ARE_GATED && !forwarding) return;
    path->packets++;
    if (pressed) path->hostDown |= bit;
    else path->hostDown &= ~bit;
}

/* The uncapture commit point: return what the host was told about, then forget
   it, so the host and the tracker both land on nothing down. */
static void click_uncapture(clickPath *path) {
    if (!HANDBACK_RETURNS_PRESSED_BUTTONS) return;
    if (path->hostDown & CLICK_A) path->packets++;
    if (path->hostDown & CLICK_B) path->packets++;
    path->hostDown = 0;
    path->tracker = 0;
}

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

    // Handing the pointer back to the Mac turns forwarding off without stopping
    // the stick timer, so a stick parked past its deadzone has to send nothing
    // for as long as the player owns the cursor -- and it must not save the
    // motion up, because recapture would spend a whole uncapture in one packet.
    {
        double accumulator = 0.0;
        int sent = 0;
        for (int tick = 0; tick < 60; tick++) stick_tick(&accumulator, 0.5, 0, &sent);
        check(sent == 0, "a right stick past the deadzone moves nothing while the "
                         "pointer belongs to the Mac");
        short resumed = stick_tick(&accumulator, 0.5, 1, &sent);
        check(resumed <= (short)(0.5 * HIDMouseEmulationSpeed) + 1,
              "and recapture answers the current frame, not the whole uncapture");
    }

    // A gamepad in mouse mode clicks on the host with A and B. Handing the
    // pointer back to the Mac does not unregister that handler, so a button the
    // player was holding when the pointer went back has to be lifted on the host,
    // and a click made afterwards -- while their own cursor is what they are
    // moving -- has to leave no trace on either side of it.
    {
        clickPath path;
        path.tracker = 0; path.hostDown = 0; path.packets = 0;
        click_edge(&path, CLICK_A, 1, 1);
        check(path.packets == 1 && (path.hostDown & CLICK_A) != 0,
              "a mouse-mode gamepad press reaches the host exactly once");
        click_uncapture(&path);
        check(path.hostDown == 0,
              "handing the pointer back lifts the button the host was told about");
        int handedBack = path.packets;
        click_edge(&path, CLICK_A, 0, 0);
        click_edge(&path, CLICK_B, 1, 0);
        check(path.packets == handedBack,
              "a click made while the Mac owns the pointer never reaches the host");
        click_edge(&path, CLICK_B, 0, 1);
        check(path.hostDown == 0 && path.packets == handedBack,
              "and recapture opens with a clean button table on both sides");
    }

    printf("%d mouse-emulation failures\n", failures);
    return failures ? 1 : 0;
}
"""


def method_body(text, signature):
    """The method body that starts at `signature`, braces included."""
    start = text.find(signature)
    if start < 0:
        raise SystemExit("the shipping source no longer contains %s" % signature)
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
        raise SystemExit("unbalanced braces in %s" % signature)
    return text[start:index + 1]


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


def stick_timer_facts(text):
    """What the shipping stick timer does about a pointer it no longer owns.

    Read from the method body so a planted defect changes the answer here, and
    the probe below is built from that answer rather than from a separate guess.
    """
    timer = method_body(text, "-(void) mouseTimerCallback:(NSTimer*)timer {")
    send = timer.find("LiSendMouseMoveEventCtx")
    accumulate = timer.find("_accumulatedMouseX +=")
    gate = re.search(r"_shouldSendInputEvents", timer)
    return {
        "has_send": send >= 0,
        "asked": gate is not None,
        "gated": send >= 0 and gate is not None and gate.start() < send,
        "refuses_before_accumulating": (gate is not None and accumulate >= 0
                                       and gate.start() < accumulate),
        "drops": bool(re.search(r"_accumulatedMouseX\s*=\s*0", timer))
                 and bool(re.search(r"_accumulatedMouseY\s*=\s*0", timer)),
    }


def click_path_facts(controller, uncapture):
    """What the shipping mouse-mode click path does about a pointer it lost.

    Three things have to hold at once, and each is read from the source rather
    than assumed: a click edge asks whether input is forwarded at all, the gate
    covers the recorded edge and not only the packet, and the uncapture commit
    point returns a button the host was told about while it still can.
    """
    gate = re.search(r"BOOL pointerForwarded = self->_shouldSendInputEvents;", controller)
    sends = [m.start() for m in re.finditer(r"LiSendMouseButtonEventCtx\(inputCtx, current", controller)]
    edges = len(re.findall(r"if \(current[AB] != last[AB] && pointerForwarded\) \{", controller))
    release = uncapture.find("releaseRemoteMouseButtonsForUncapture")
    switch = uncapture.find("self.controllerSupport.shouldSendInputEvents = NO;")
    return {
        "CLICKS_ARE_GATED": bool(gate) and len(sends) == 2 and
                            all(gate.start() < p for p in sends),
        "CLICK_GATE_COVERS_THE_EDGE": edges == 2,
        # Finding the call is not enough: after the flag goes down, the release
        # it performs can no longer reach the host it is trying to please.
        "HANDBACK_RETURNS_PRESSED_BUTTONS": release >= 0 and switch >= 0 and
                                            release < switch,
    }


def bake_in_facts(stick, clicks):
    """The one place that maps what the sources do to what the probe assumes."""
    return {
        "STICK_TIMER_IS_GATED": stick["gated"],
        "STICK_GATE_REFUSES_BEFORE_ACCUMULATING": stick["refuses_before_accumulating"],
        "STICK_TIMER_DROPS_MOTION": stick["drops"],
        "CLICKS_ARE_GATED": clicks["CLICKS_ARE_GATED"],
        "CLICK_GATE_COVERS_THE_EDGE": clicks["CLICK_GATE_COVERS_THE_EDGE"],
        "HANDBACK_RETURNS_PRESSED_BUTTONS": clicks["HANDBACK_RETURNS_PRESSED_BUTTONS"],
    }


def probe_source(drainer, facts):
    """The probe source with the drainer and the shipping shapes baked in."""
    defines = "".join("#define %s %d\n" % (name, 1 if facts[name] else 0)
                      for name in sorted(facts))
    return TEST_BODY.replace("__FACTS__", defines).replace("__DRAIN__", drainer)


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

    # The third consumer of one decision. Whether motion may reach the host right
    # now is asked by the button path in ControllerSupport.m and by the display-link
    # consumer in HIDSupport+Pointer.m. The stick cursor runs on its own NSTimer,
    # which is never stopped when the pointer is handed back to the Mac -- only when
    # the session is torn down -- so a timer that never asks keeps dragging the
    # remote cursor with the right stick while the player is using their own mouse.
    facts = stick_timer_facts(controller)
    if not facts["has_send"]:
        problems.append("the stick timer no longer has the send this check can guard")
    elif not facts["asked"]:
        problems.append("the stick timer moves the remote cursor without asking "
                        "whether input is being forwarded")
    elif not facts["gated"]:
        problems.append("the stick timer asks whether input is forwarded only after "
                        "it has already moved the remote cursor")
    elif not facts["refuses_before_accumulating"] and not facts["drops"]:
        # Asking before the send is not enough on its own. Refusing after the
        # accumulation leaves the owed pixels standing through the whole uncapture,
        # and they land on the host as one throw the moment capture returns -- the
        # same ghost motion the display-link consumer takes care not to keep.
        # Refusing before the deadzone satisfies it; emptying the accumulator does
        # too, which is why only their combination is a defect.
        problems.append("the stick timer accumulates the motion it will not send, so "
                        "the host takes one throw at recapture")

    # A gamepad in mouse mode clicks on the host with A and B, through a handler
    # that stays registered when the pointer is handed back to the Mac and is
    # only torn down with the session. Handing the pointer back also stops the
    # one thing that could still lift a button on the host, so the uncapture has
    # to do that itself, and do it before the flag goes down.
    clicks = click_path_facts(controller, open(UNCAPTURE_SOURCE, encoding="utf-8").read())
    if not clicks["CLICKS_ARE_GATED"]:
        problems.append("the mouse-mode click path moves the host cursor without "
                        "asking whether input is being forwarded")
    elif not clicks["CLICK_GATE_COVERS_THE_EDGE"]:
        problems.append("the mouse-mode click path records the edge it refuses, so "
                        "the host is owed a release for a button it never took on")
    elif not clicks["HANDBACK_RETURNS_PRESSED_BUTTONS"]:
        problems.append("nothing returns a gamepad mouse button at the uncapture "
                        "while the packet can still reach the host")
    return problems


def compile_args(clang, sdk, path, exe):
    """One place that decides what a probe needs to build."""
    return [clang, "-isysroot", sdk, "-Wno-deprecated-declarations",
            "-framework", "Foundation", "-I", os.path.dirname(EMULATION_HEADER),
            "-o", exe, path]


def expect_red(clang, sdk, tmp, source, label):
    """Build and run a broken probe, and require it to report the breakage."""
    path = os.path.join(tmp, "broken.m")
    exe = os.path.join(tmp, "broken")
    open(path, "w", encoding="utf-8").write(source)
    build = subprocess.run(compile_args(clang, sdk, path, exe),
                           capture_output=True, text=True)
    if build.returncode != 0:
        print("FAIL %s would not build, which is not a caught defect" % label)
        print((build.stdout + build.stderr)[-2000:])
        return 1
    broken = subprocess.run([exe], capture_output=True, text=True)
    caught = [l for l in broken.stdout.splitlines() if l.startswith("FAIL")]
    ok = broken.returncode != 0 and caught
    print("%-4s %s (%d verdicts red)" % ("ok" if ok else "FAIL", label, len(caught)))
    if not ok:
        print(broken.stdout)
    return 0 if ok else 1


def main():
    problems = source_checks()
    for line in problems:
        print("FAIL %s" % line)
    clang, sdk = clang_and_sdk("controller mouse emulation probe")
    drainer = drain_block(open(INTERNAL_HEADER, encoding="utf-8").read())
    base = bake_in_facts(
        stick_timer_facts(open(CONTROLLER_SOURCE, encoding="utf-8").read()),
        click_path_facts(open(CONTROLLER_SOURCE, encoding="utf-8").read(),
                         open(UNCAPTURE_SOURCE, encoding="utf-8").read()))

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "probe.m")
        exe = os.path.join(tmp, "probe")
        open(path, "w", encoding="utf-8").write(probe_source(drainer, base))
        compile_run = subprocess.run(compile_args(clang, sdk, path, exe),
                                     capture_output=True, text=True)
        if compile_run.returncode != 0:
            raise SystemExit("the probe did not compile:\n%s"
                             % (compile_run.stdout[-2000:] + compile_run.stderr[-2000:]))
        run = subprocess.run([exe], capture_output=True, text=True)
        print(run.stdout.rstrip())
        rc = run.returncode or (1 if problems else 0)

        if "--self-test" in sys.argv:
            variants = [
                ("throwing the residue away is refused",
                 throw_the_residue_away(drainer), {}),
                ("a stick timer with no forwarding gate is refused", drainer,
                 {"STICK_TIMER_IS_GATED": False}),
                ("a stick timer that refuses after it has banked the motion is "
                 "refused", drainer, {"STICK_GATE_REFUSES_BEFORE_ACCUMULATING": False}),
                ("a mouse-mode gamepad click with no forwarding gate is refused",
                 drainer, {"CLICKS_ARE_GATED": False}),
                ("a click gate that still records the refused edge is refused",
                 drainer, {"CLICK_GATE_COVERS_THE_EDGE": False}),
                ("an uncapture that leaves the gamepad button down is refused",
                 drainer, {"HANDBACK_RETURNS_PRESSED_BUTTONS": False}),
            ]
            for label, broken_drainer, override in variants:
                rc |= expect_red(clang, sdk, tmp,
                                 probe_source(broken_drainer,
                                              dict(base, **override)),
                                 label)
        return rc


if __name__ == "__main__":
    sys.exit(main())
