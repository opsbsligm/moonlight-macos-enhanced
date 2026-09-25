#!/usr/bin/env python3
"""Prove the edge summon band lets go of the pointer only for a player who meant it.

The dock used to answer exactly one question: did the pointer already escape capture.
That made it unreachable in every mode that keeps the pointer parked -- the relative
mode a game is played in never lets the pointer near an edge at all -- and it made the
dock's own edge matter only where a free mouse happens to roll off the screen. The band
asks a different question instead: is the player holding the pointer against the edge
the dock lives on, or pushing at it, for long enough to be doing that on purpose.

Two ways in, either one alone of which is what a stray flick looks like:

  * dwell   -- within 2 pt of the edge, held for 150 ms;
  * push    -- 30 pt of inward intent accumulated inside the band, where one event is
               worth at most 6 pt so a single fast flick cannot spend the budget.

The gate drives the shipped C helpers themselves, extracted from the shipping source, so
what passes here is the code that ships. What it cannot drive from C -- the timer, the
capture state machine, the preference -- it reads out of the shipping sources as wiring,
and refuses a tree where a wiring claim went missing.

--self-test puts the two ways the band could misbehave back in: an uncapped single
event, which is the flick that puts the dock away every time a player looks around, and
a band that keeps evaluating after the player switched it off. Both have to go red.
"""
import os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VC = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers")

OBJC = os.path.join(VC, "StreamViewController+MouseCapture.m")
MENU_UI = os.path.join(VC, "StreamViewController+MenuUI.m")
INTERNAL = os.path.join(VC, "StreamViewController_Internal.h")
STORE = os.path.join(VC, "SettingsStore.swift")
DERIVED = os.path.join(VC, "SettingsModel+DerivedValues.swift")
BRIDGE = os.path.join(VC, "SettingsObjCBridge.swift")
PANE = os.path.join(VC, "SettingsInputPane.swift")
ZH = os.path.join(ROOT, "Limelight", "macOS", "zh-Hans.lproj", "Localizable.strings")
EN = os.path.join(ROOT, "Limelight", "macOS", "en.lproj", "Localizable.strings")

HELPERS = ["MLEdgeSensorNormalDistanceToEdge",
           "MLEdgeSensorOutwardDeltaForDeltas",
           "MLEdgeSensorPushAccumulate"]

MIN_BEHAVIOUR_CHECKS = 18

SHIM = r'''
#include <stdio.h>
#include <stddef.h>

typedef double CGFloat;
typedef int BOOL;
#define YES 1
#define NO 0
typedef struct { CGFloat x, y; } NSPoint;
typedef struct { CGFloat x, y; } NSSize;
typedef struct { NSPoint origin; NSSize size; } NSRect;
#define NSMinX(r) ((r).origin.x)
#define NSMaxX(r) ((r).origin.x + (r).size.x)
#define NSMinY(r) ((r).origin.y)
#define NSMaxY(r) ((r).origin.y + (r).size.y)
#define CGFLOAT_MAX (1.0 / 0.0)

typedef enum {
    MLFreeMouseExitEdgeNone = 0,
    MLFreeMouseExitEdgeLeft,
    MLFreeMouseExitEdgeRight,
    MLFreeMouseExitEdgeTop,
    MLFreeMouseExitEdgeBottom,
} MLFreeMouseExitEdge;

static int checks = 0;
static int failures = 0;
#define CHECK(cond, note) do { checks++; if (!(cond)) { failures++; printf("FAIL %s\n", note); } } while (0)

static NSRect Box(CGFloat w, CGFloat h) {
    NSRect r;
    r.origin.x = 0.0; r.origin.y = 0.0; r.size.x = w; r.size.y = h;
    return r;
}

static NSPoint At(CGFloat x, CGFloat y) {
    NSPoint p;
    p.x = x; p.y = y;
    return p;
}

/*-- shipped helpers, extracted verbatim from StreamViewController+MouseCapture.m --*/
%HELPER_SOURCE%
/*-- end shipped helpers --*/

static CGFloat CAP(void) { return %CAP%; }
static CGFloat BUDGET(void) { return %BUDGET%; }
static CGFloat EDGE_DISTANCE(void) { return %EDGE_DISTANCE%; }
static CGFloat BAND_WIDTH(void) { return %BAND_WIDTH%; }

/* The band's own reading of one event: inside the band, and against the edge. */
static int againstEdge(CGFloat normal) {
    return !(normal > BAND_WIDTH()) && !(normal > EDGE_DISTANCE());
}

int main(void) {
    NSRect box = Box(200.0, 100.0);

    /* the normal distance is measured to the edge the dock sits on, in that edge's
       inward direction, and a dock with no edge has nothing to be measured against */
    CHECK(MLEdgeSensorNormalDistanceToEdge(At(2.0, 50.0), box, MLFreeMouseExitEdgeLeft) == 2.0,
          "left edge distance reads the x inside");
    CHECK(MLEdgeSensorNormalDistanceToEdge(At(198.0, 50.0), box, MLFreeMouseExitEdgeRight) == 2.0,
          "right edge distance reads from the far side");
    CHECK(MLEdgeSensorNormalDistanceToEdge(At(100.0, 2.0), box, MLFreeMouseExitEdgeBottom) == 2.0,
          "bottom edge distance reads the y inside");
    CHECK(MLEdgeSensorNormalDistanceToEdge(At(100.0, 98.0), box, MLFreeMouseExitEdgeTop) == 2.0,
          "top edge distance reads from the far side");
    CHECK(MLEdgeSensorNormalDistanceToEdge(At(100.0, 50.0), box, MLFreeMouseExitEdgeNone) > 1e30,
          "no dock edge has no band");
    CHECK(MLEdgeSensorNormalDistanceToEdge(At(-40.0, 50.0), box, MLFreeMouseExitEdgeLeft) < 0.0,
          "past the edge stays negative rather than wrapping into the band");

    /* band membership is the band width, and the edge distance is what arms anything */
    CHECK(againstEdge(2.0), "two points in is against the edge");
    CHECK(!againstEdge(2.0 + 0.001), "just past the edge distance is inside the band but not against it");
    CHECK(!againstEdge(24.0 + 0.001), "outside the band arms nothing");
    CHECK(againstEdge(-40.0), "already past the edge is against it");

    /* outward intent keeps the sign convention the release path already uses */
    CHECK(MLEdgeSensorOutwardDeltaForDeltas(-5.0, 0.0, MLFreeMouseExitEdgeLeft) == 5.0,
          "leftward motion is outward on the left edge");
    CHECK(MLEdgeSensorOutwardDeltaForDeltas(5.0, 0.0, MLFreeMouseExitEdgeLeft) == 0.0,
          "rightward motion is not outward on the left edge");
    CHECK(MLEdgeSensorOutwardDeltaForDeltas(5.0, 0.0, MLFreeMouseExitEdgeRight) == 5.0,
          "rightward motion is outward on the right edge");
    CHECK(MLEdgeSensorOutwardDeltaForDeltas(0.0, 5.0, MLFreeMouseExitEdgeTop) == 5.0,
          "upward motion is outward on the top edge");
    CHECK(MLEdgeSensorOutwardDeltaForDeltas(0.0, -5.0, MLFreeMouseExitEdgeBottom) == 5.0,
          "downward motion is outward on the bottom edge");
    CHECK(MLEdgeSensorOutwardDeltaForDeltas(0.0, -5.0, MLFreeMouseExitEdgeTop) == 0.0,
          "away from the top edge is nothing on the top edge");
    CHECK(MLEdgeSensorOutwardDeltaForDeltas(50.0, 50.0, MLFreeMouseExitEdgeNone) == 0.0,
          "no dock edge accumulates nothing");

    /* one event is worth a capped amount of intent, and the budget is spent across events */
    CGFloat acc = 0.0;
    int triggered = MLEdgeSensorPushAccumulate(acc, 100.0, CAP(), BUDGET(), &acc);
    CHECK(acc == CAP(), "one flick is worth the cap and nothing more");
    CHECK(!triggered, "a single flick does not spend the budget");
    int events = 1;
    while (!triggered && events < 40) {
        triggered = MLEdgeSensorPushAccumulate(acc, 100.0, CAP(), BUDGET(), &acc);
        events++;
    }
    CHECK(triggered, "holding the push in spends the budget eventually");
    CHECK(acc == BUDGET(), "the budget is spent exactly rather than overshot");
    CHECK(events == 5, "the budget takes five events at the cap");

    acc = 0.0;
    CHECK(!MLEdgeSensorPushAccumulate(acc, -50.0, CAP(), BUDGET(), &acc) && acc == 0.0,
          "pulling back accumulates nothing");
    acc = 10.0;
    MLEdgeSensorPushAccumulate(acc, -50.0, CAP(), BUDGET(), &acc);
    CHECK(acc == 10.0, "a pull back does not refund an earlier push");

    acc = 29.4;
    CHECK(MLEdgeSensorPushAccumulate(acc, 0.6, CAP(), BUDGET(), &acc),
          "the budget is reached, not exceeded");
    acc = 29.4;
    CHECK(!MLEdgeSensorPushAccumulate(acc, 0.5, CAP(), BUDGET(), &acc),
          "under budget is not a summon");

    /* the band width and the edge distance are the numbers the settings text promises */
    CHECK(BAND_WIDTH() == 24.0 && EDGE_DISTANCE() == 2.0 && BUDGET() == 30.0 && CAP() == 6.0,
          "the shipped numbers are the documented numbers");

    printf("%d edge sensor behaviour checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
'''


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def helper_source(objc_text, cap_break=False):
    """Lift the shipped helpers out of the shipping source, brace matched."""
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
    if cap_break:
        # The pre-fix reading of intent: take the whole flick, cap nothing.
        broken = ("CGFloat clamped = outwardDelta > 0.0 ? outwardDelta : 0.0;")
        assert "CGFloat clamped = outwardDelta > perEventCap ? perEventCap : (outwardDelta > 0.0 ? outwardDelta : 0.0);" in source, \
            "the push helper no longer caps the way the gate expects"
        source = source.replace(
            "CGFloat clamped = outwardDelta > perEventCap ? perEventCap : (outwardDelta > 0.0 ? outwardDelta : 0.0);",
            broken, 1)
    return source


def constants():
    text = read(INTERNAL)
    values = {}
    for name, key in (("MLEdgeSensorBandWidth", "band"),
                      ("MLEdgeSensorEdgeDistance", "edge"),
                      ("MLEdgeSensorDwellSeconds", "dwell"),
                      ("MLEdgeSensorPushBudget", "budget"),
                      ("MLEdgeSensorPushPerEventCap", "cap")):
        match = re.search(r"static\s+(?:CGFloat|NSTimeInterval)\s+const\s+%s\s*=\s*([0-9.]+);" % name, text)
        if not match:
            raise AssertionError("%s is not a readable constant any more" % name)
        values[key] = match.group(1)
    return values


def compile_and_run(source, tmp_dir, tag):
    program = os.path.join(tmp_dir, "sensor-%s" % tag)
    c_file = os.path.join(tmp_dir, "sensor-%s.c" % tag)
    with open(c_file, "w", encoding="utf-8") as handle:
        handle.write(source)
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if not compiler:
        print("FAIL no C compiler to drive the shipped helpers")
        return 2, ""
    result = subprocess.run([compiler, "-std=c11", "-o", program, c_file],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print("FAIL the shipped helpers do not compile: %s" % result.stderr.strip()[:400])
        return 2, ""
    run = subprocess.run([program], capture_output=True, text=True)
    return run.returncode, run.stdout


def wiring_problems(objc_text, menu_text, internal_text):
    """Every way the band could quietly stop being the thing the gate just tested."""
    problems = []

    body_match = re.search(r"- \(BOOL\)handleEdgeSensorSummonForEvent:\(NSEvent \*\)event \{(.+?)\n\}\n"
                           r"\n- \(void\)logMouseClickDiagnosticsForPhase", objc_text, re.S)
    if not body_match:
        problems.append("the band's entry point is not readable in the capture source")
        return problems, ""
    body = body_match.group(1)

    if "self.edgeSensorSummonEnabled" not in body.split("isMouseCaptured")[0]:
        problems.append("the switch is not the first thing the band asks")
    if "[self freeMouseExitEdgeForEvent:event] != MLFreeMouseExitEdgeNone" not in body:
        problems.append("the free-mouse release path no longer keeps priority over the band")
    if "MLEdgeSensorPushAccumulate(self.edgeSensorPushAccumulator" not in body:
        problems.append("the band does not accumulate intent through the shipped helper")
    if "MLEdgeSensorOutwardDeltaForDeltas(" not in body:
        problems.append("the band does not read outward intent through the shipped helper")
    if "MLEdgeSensorBandWidth" not in body or "MLEdgeSensorEdgeDistance" not in body:
        problems.append("the band does not separate being inside from being against the edge")

    handlers = re.findall(r"- \(void\)(mouseMoved|mouseDragged|rightMouseDragged|otherMouseDragged):"
                          r'\(NSEvent \*\)event \{(.+?)\n\}\n', objc_text, re.S)
    armed = {name for name, body_text in handlers if "handleEdgeSensorSummonForEvent:event" in body_text}
    if len(armed) != 4:
        problems.append("only %d of the four pointer handlers arm the band: %s"
                        % (len(armed), ", ".join(sorted(armed)) or "none"))

    summon = re.search(r"- \(void\)summonEdgeMenuDockForEdge:.*?\n\}\n", objc_text, re.S)
    if not summon:
        problems.append("the summon body is unreadable")
    else:
        text = summon.group(0)
        if "uncaptureMouseWithCode:@\"MUC109\"" not in text:
            problems.append("the summon no longer hands the pointer back")
        if "activateEdgeMenuDockForExitEdge:edge" not in text:
            problems.append("the summon no longer opens the dock")
        if "resetEdgeSensorSummonState" not in text:
            problems.append("the summon does not start from nothing afterwards")

    dwell = re.search(r"- \(void\)beginEdgeSensorDwellTimerIfNeededForEdge:.*?\n\}\n", objc_text, re.S)
    reset = re.search(r"- \(void\)resetEdgeSensorSummonState \{.*?\n\}\n", objc_text, re.S)
    if not dwell or "repeats:NO" not in dwell.group(0):
        problems.append("the dwell timer is not a one-shot")
    if not dwell or "weakSelf" not in dwell.group(0):
        problems.append("the dwell timer keeps the controller alive from its block")
    if not reset or "invalidate" not in reset.group(0):
        problems.append("the dwell timer has no stop")
    if not reset or "edgeSensorPushAccumulator = 0.0" not in reset.group(0):
        problems.append("the push budget is never given back")
    if not dwell or "finishEdgeSensorSummonIfStillArmedForEdge" not in dwell.group(0):
        problems.append("the dwell timer does not re-check the hold when it expires")

    finish = re.search(r"- \(void\)finishEdgeSensorSummonIfStillArmedForEdge:.*?\n\}\n", objc_text, re.S)
    if not finish or "MLEdgeSensorNormalDistanceToEdge" not in finish.group(0):
        problems.append("an expired dwell does not require the hold to still be true")

    if "resetEdgeSensorSummonState" not in menu_text:
        problems.append("folding the dock away leaves the band's ledger standing")
    capture = re.search(r"- \(void\)captureMouse \{.*?\n\}\n", objc_text, re.S)
    if not capture or "refreshEdgeSensorSummonPreference" not in capture.group(0):
        problems.append("a fresh capture does not re-read the switch")
    pref = re.search(r"- \(void\)refreshEdgeSensorSummonPreference \{.*?\n\}\n", objc_text, re.S)
    if not pref or "resetEdgeSensorSummonState" not in pref.group(0):
        problems.append("switching the band off leaves an armed dwell running")

    if r"handleEdgeSensorSummonForEvent:(NSEvent *)event" not in internal_text:
        problems.append("the band is declared on no interface")
    declared_on = re.search(r"@interface StreamViewController \((\w+)\)[^{]*?"
                            r"- \(BOOL\)handleEdgeSensorSummonForEvent:", internal_text, re.S)
    if declared_on and declared_on.group(1) != "MouseCaptureInternal":
        problems.append("the band is declared on %s while it is implemented in the capture category"
                        % declared_on.group(1))
    return problems, body


def preference_problems():
    problems = []
    if 'let edgeSensorSummon: Bool?' not in read(STORE):
        problems.append("the preference is not a stored setting")
    if 'static let defaultEdgeSensorSummon = true' not in read(DERIVED):
        problems.append("the band is not armed for a player who never opened settings")
    bridge = read(BRIDGE)
    if '"edgeSensorSummon": settings.edgeSensorSummon ?? true' not in bridge:
        problems.append("the stream-facing dictionary does not carry the key")
    pane = read(PANE)
    if 'boolBinding: $settingsModel.edgeSensorSummon' not in pane:
        problems.append("the player has no way to switch the band off")
    if 'hintKey: "Edge Sensor Summon detail"' not in pane:
        problems.append("the thresholds are not explained where the switch lives")
    for language, path in (("zh-Hans", ZH), ("en", EN)):
        text = read(path)
        if '"Edge Sensor Summon"' not in text:
            problems.append("%s has no title for the switch" % language)
        detail = re.search(r'^"Edge Sensor Summon detail" = "(.*?)";$', text, re.M)
        if not detail:
            problems.append("%s has no thresholds beside the switch" % language)
            continue
        sentence = detail.group(1)
        for number in ("24", "2", "150", "30", "6", "0.82"):
            if number not in sentence:
                problems.append("%s hides the number %s the band ships with" % (language, number))
    return problems


def main():
    self_test = "--self-test" in sys.argv
    objc_text = read(OBJC)
    constants_values = constants()
    problems = []
    rc = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        def render(cap_break):
            return SHIM.replace("%HELPER_SOURCE%", helper_source(objc_text, cap_break)) \
                      .replace("%CAP%", constants_values["cap"]) \
                      .replace("%BUDGET%", constants_values["budget"]) \
                      .replace("%EDGE_DISTANCE%", constants_values["edge"]) \
                      .replace("%BAND_WIDTH%", constants_values["band"])

        code, out = compile_and_run(render(False), tmp_dir, "shipping")
        caught = [line for line in out.splitlines() if line.startswith("FAIL")]
        counted = re.search(r"(\d+) edge sensor behaviour checks, (\d+) failures", out)
        checks = int(counted.group(1)) if counted else 0
        print("%-4s the shipped band keeps its geometry, its signs and its budget (%d checks)"
              % ("ok" if code == 0 and checks >= MIN_BEHAVIOUR_CHECKS else "FAIL", checks))
        if code != 0 or checks < MIN_BEHAVIOUR_CHECKS:
            print(out)
            rc = 1

        wiring, _ = wiring_problems(objc_text, read(MENU_UI), read(INTERNAL))
        print("%-4s the band is armed by every pointer path and folded away by the dock (%d gaps)"
              % ("ok" if not wiring else "FAIL", len(wiring)))
        for gap in wiring:
            print("     %s" % gap)
        if wiring:
            rc = 1

        preference = preference_problems()
        print("%-4s the switch ships armed and explains its thresholds (%d gaps)"
              % ("ok" if not preference else "FAIL", len(preference)))
        for gap in preference:
            print("     %s" % gap)
        if preference:
            rc = 1

        if self_test:
            broken_code, broken_out = compile_and_run(render(True), tmp_dir, "uncapped")
            broken_checks = [l for l in broken_out.splitlines() if l.startswith("FAIL")]
            print("%-4s an uncapped flick is refused (%d verdicts red)"
                  % ("ok" if broken_code != 0 and broken_checks else "FAIL", len(broken_checks)))
            if broken_code == 0 or not broken_checks:
                print(broken_out)
                rc = 1

            switched_off = objc_text.replace(
                "    if (!self.edgeSensorSummonEnabled || event == nil) {\n        return NO;\n    }\n", "", 1)
            if switched_off == objc_text:
                print("FAIL the band's switch is not readable, so the red proof cannot be built")
                return 1
            switched_problems, _ = wiring_problems(switched_off, read(MENU_UI), read(INTERNAL))
            print("%-4s a band that ignores its switch is refused (%d gaps named)"
                  % ("ok" if switched_problems else "FAIL", len(switched_problems)))
            if not switched_problems:
                rc = 1

            folded = read(MENU_UI).replace(
                "    // The band starts from nothing every time the dock goes away: a summon that is\n"
                "    // folded up has to be paid for again with a fresh dwell or a fresh push.\n"
                "    [self resetEdgeSensorSummonState];\n\n", "", 1)
            folded_problems, _ = wiring_problems(objc_text, folded, read(INTERNAL))
            print("%-4s a fold that leaves the ledger standing is refused (%d gaps named)"
                  % ("ok" if any("ledger" in p for p in folded_problems) else "FAIL",
                     len([p for p in folded_problems if "ledger" in p])))
            if not any("ledger" in p for p in folded_problems):
                rc = 1

    return rc


if __name__ == "__main__":
    sys.exit(main())
