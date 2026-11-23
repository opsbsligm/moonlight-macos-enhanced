#!/usr/bin/env python3
"""Prove the one cadence answer stays one answer, and that it answers correctly.

Whether a display can carry frame interpolation at a given stream frame rate is a single
arithmetic fact -- the display refresh must be a whole multiple (within a few percent) of twice
the stream rate, so every interpolated frame lands on a whole refresh -- but two
places have to act on it: the renderer, which refuses to build an interpolating engine, and the
settings page, which has to warn a player before the stream starts and name a frame rate that
would work. The moment those two are separate copies of the formula, a player can be told to pick
a value the renderer then refuses, which is worse than no warning at all: they did what they were
asked and the feature still did nothing. InterpolationCadencePolicy.h is the single copy; this
file is what keeps it single and right.

Three things are checked:

  * the shipped C functions are compiled as-is and driven: the minimum (one-times-cadence)
    refresh per frame rate, the exact boundaries (180 Hz carrying 90 FPS and refusing 120 FPS
    -- the pairing that read as honey on a real panel --, 179 still carrying 90 within tolerance, 174 refused, unknown and negative refresh refused), the recommendation snapped to a frame rate the
    settings page actually offers, and the frame rate list itself;
  * the wiring, read out of the shipping sources: the renderer imports the header, its admission
    calls the shared function, the duplicated arithmetic is gone rather than still living beside
    it, and the recommendation cannot name a frame rate the page cannot select;
  * floors, because an audit whose driver stopped parsing would report zero failures.

--self-test plants six mistakes: loosen the rule by ten hertz; put the arithmetic back into the
renderer next to the shared call; change a frame rate in the settings list alone; replace the
snap's candidate walk with a plain rounding; let the drawable pool forget the cadence hold; and
assume one interpolated frame per source frame instead of the measured rate. All six have to
come back red.
"""
import os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = os.path.join(ROOT, "Limelight", "macOS", "InterpolationCadencePolicy.h")
RENDERER = os.path.join(ROOT, "Limelight", "Stream", "VideoDecoderRenderer.m")
DERIVED = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers",
                       "SettingsModel+DerivedValues.swift")

MIN_BEHAVIOUR = 55
PRESETS = [30, 60, 90, 120, 144]

DRIVER = r'''
#include "InterpolationCadencePolicy.h"
#include <stdio.h>
int main(void) {
    printf("min12=%.1f min20=%.1f min23=%.1f min24=%.1f\n",
           MLInterpolationMinimumRefreshForSourceFps(12),
           MLInterpolationMinimumRefreshForSourceFps(20),
           MLInterpolationMinimumRefreshForSourceFps(23),
           MLInterpolationMinimumRefreshForSourceFps(24));
    printf("min30=%.1f min60=%.1f min120=%.1f min144=%.1f\n",
           MLInterpolationMinimumRefreshForSourceFps(30),
           MLInterpolationMinimumRefreshForSourceFps(60),
           MLInterpolationMinimumRefreshForSourceFps(120),
           MLInterpolationMinimumRefreshForSourceFps(144));
    printf("edge32_20=%d edge31_20=%d edge45_30=%d edge44_30=%d\n",
           MLInterpolationHasCadenceHeadroom(32.0, 20),
           MLInterpolationHasCadenceHeadroom(31.0, 20),
           MLInterpolationHasCadenceHeadroom(45.0, 30),
           MLInterpolationHasCadenceHeadroom(44.0, 30));
    printf("edge180_120=%d edge179_120=%d edge180_144=%d edge90_60=%d edge24_36=%d\n",
           MLInterpolationHasCadenceHeadroom(180.0, 120),
           MLInterpolationHasCadenceHeadroom(179.0, 120),
           MLInterpolationHasCadenceHeadroom(180.0, 144),
           MLInterpolationHasCadenceHeadroom(90.0, 60),
           MLInterpolationHasCadenceHeadroom(36.0, 24));
    printf("edge180_90=%d edge17982_90=%d edge174_90=%d edge360_120=%d\n",
           MLInterpolationHasCadenceHeadroom(180.0, 90),
           MLInterpolationHasCadenceHeadroom(179.82, 90),
           MLInterpolationHasCadenceHeadroom(174.0, 90),
           MLInterpolationHasCadenceHeadroom(360.0, 120));
    printf("edge60_30=%d edge120_30=%d edge121_60=%d edge61_30=%d\n",
           MLInterpolationHasCadenceHeadroom(60.0, 30),
           MLInterpolationHasCadenceHeadroom(120.0, 30),
           MLInterpolationHasCadenceHeadroom(121.0, 60),
           MLInterpolationHasCadenceHeadroom(61.0, 30));
    printf("edge240_60=%d edge120_60=%d edge300_60=%d edge175_60=%d\n",
           MLInterpolationHasCadenceHeadroom(240.0, 60),
           MLInterpolationHasCadenceHeadroom(120.0, 60),
           MLInterpolationHasCadenceHeadroom(300.0, 60),
           MLInterpolationHasCadenceHeadroom(175.0, 60));
    printf("unknownrefresh=%d negrefresh=%d zerofps=%d\n",
           MLInterpolationHasCadenceHeadroom(0.0, 60),
           MLInterpolationHasCadenceHeadroom(-5.0, 60),
           MLInterpolationHasCadenceHeadroom(240.0, 0));
    printf("snap180_72=%ld snap180_52=%ld snap180_180=%ld snap60_60=%ld snap180_36=%ld snap144_108=%ld snap0_72=%ld snap180_130=%ld\n",
           MLInterpolationSnappedRefreshesPerFrame(180.0, 72.0),
           MLInterpolationSnappedRefreshesPerFrame(180.0, 52.0),
           MLInterpolationSnappedRefreshesPerFrame(180.0, 180.0),
           MLInterpolationSnappedRefreshesPerFrame(60.0, 60.0),
           MLInterpolationSnappedRefreshesPerFrame(180.0, 36.0),
           MLInterpolationSnappedRefreshesPerFrame(144.0, 108.0),
           MLInterpolationSnappedRefreshesPerFrame(0.0, 72.0),
           MLInterpolationSnappedRefreshesPerFrame(180.0, 130.0));
    const int refreshes[] = {180, 179, 165, 144, 120, 90, 60, 45, 30, 0, -8};
    for (int i = 0; i < 11; i++) {
        printf("cap%d=%d\nsug%d=%d\n", refreshes[i],
               MLInterpolationMaxSourceFpsForRefresh((double)refreshes[i]),
               refreshes[i],
               MLInterpolationSuggestedFpsForRefresh((double)refreshes[i]));
    }
    printf("count=%d\n", MLStreamFpsPresetCount());
    for (int i = 0; i < MLStreamFpsPresetCount(); i++) printf("preset%d=%d\n", i, MLStreamFpsPresetAtIndex(i));
    printf("oob=%d\n", MLStreamFpsPresetAtIndex(99));
    return 0;
}
'''

# What the answers have to be. Every one of these is a claim about the shipped rule, not about
# this file: 180 Hz refusing 120 FPS and carrying 90 is the pairing a 180 Hz player has to
# choose -- 120 on that panel was admitted by the old 1.5x headroom floor and measured as
# viscous jitter, because 240 output frames cannot land evenly on 180 scans. 179.82 carrying
# 90 is the same panel measured honestly; 174 is a different cadence and stays refused. The
# recommendation being a selectable rate is what makes the settings page's advice actionable.
EXPECTED = {
    "min12": "24.0", "min20": "40.0", "min23": "46.0", "min24": "48.0",
    "min30": "60.0", "min60": "120.0", "min120": "240.0", "min144": "288.0",
    "edge32_20": "0", "edge31_20": "0", "edge45_30": "0", "edge44_30": "0",
    "edge180_120": "0", "edge179_120": "0", "edge180_144": "0", "edge90_60": "0",
    "edge24_36": "0", "unknownrefresh": "0", "negrefresh": "0", "zerofps": "0",
    "edge180_90": "1", "edge17982_90": "1", "edge174_90": "0", "edge360_120": "0",
    "edge60_30": "1", "edge120_30": "1", "edge121_60": "1", "edge61_30": "1",
    "edge240_60": "1", "edge120_60": "1", "edge300_60": "0", "edge175_60": "0",
    "cap180": "90", "cap179": "90", "cap165": "0", "cap144": "0", "cap120": "60",
    "cap90": "0", "cap60": "30", "cap45": "0", "cap30": "0", "cap0": "0", "cap-8": "0",
    "sug180": "90", "sug179": "90", "sug165": "0", "sug144": "0", "sug120": "60",
    "sug90": "0", "sug60": "30", "sug45": "0", "sug30": "0", "sug0": "0", "sug-8": "0",
    "count": "5", "preset0": "30", "preset1": "60", "preset2": "90", "preset3": "120",
    "preset4": "144", "oob": "0",
    # The snap is the whole-refresh hold closest to the real production rate: 72 FPS of
    # output on a 180 Hz panel is 3 refreshes (60 FPS implied, the nearest divisor point to
    # 72 -- the hold never sits at 2.5). 180 against 180 is one refresh; 60 on 60 is one; a
    # 36 FPS source with no interpolation headroom snaps to 5 refreshes (36 implied). Unknown
    # refresh is the no-hold floor of one, and 130 sits closer to 90 than to 60.
    # 52 is the field session's measured production (a 35 FPS source at a ~50% interpolation
    # success rate): 180 / 52 sits between 90 and 60 implied, 45 closer to 52 than 60 is, so
    # the walk answers 4 refreshes.
    "snap180_72": "3", "snap180_52": "4", "snap180_180": "1", "snap60_60": "1",
    "snap180_36": "5",
    "snap144_108": "1", "snap0_72": "1", "snap180_130": "2",
}


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def drive(policy_text):
    """Compile the policy as given and return its answers."""
    with tempfile.TemporaryDirectory() as work:
        with open(os.path.join(work, "InterpolationCadencePolicy.h"), "w", encoding="utf-8") as handle:
            handle.write(policy_text)
        with open(os.path.join(work, "driver.c"), "w", encoding="utf-8") as handle:
            handle.write(DRIVER)
        binary = os.path.join(work, "driver")
        # -lm because the policy calls round(), and the audits runner is Linux: gcc keeps
        # libm separate, where Apple folds it into libSystem. Without this the gate compiles
        # on every laptop and fails to link on every CI image -- an ld error, not a wrong
        # reading, and the loudest thing a arithmetic gate can get wrong.
        build = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-I", work,
                                os.path.join(work, "driver.c"), "-lm", "-o", binary],
                               capture_output=True, text=True)
        if build.returncode != 0:
            return None, (build.stdout + build.stderr).strip()
        run = subprocess.run([binary], capture_output=True, text=True)
        if run.returncode != 0:
            return None, run.stderr.strip()
    answers = {}
    for token in run.stdout.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        answers[key] = value
    return answers, ""


def behaviour(answers):
    problems = []
    for key, want in EXPECTED.items():
        got = answers.get(key)
        if got != want:
            problems.append("%s answered %s, expected %s" % (key, got, want))
    return problems


def wiring(policy_text, renderer_text, swift_text):
    gaps = []
    if '#import "InterpolationCadencePolicy.h"' not in renderer_text:
        gaps.append("the renderer does not import the shared policy header")
    if "MLInterpolationMinimumRefreshForSourceFps((double)self.frameRate)" not in renderer_text:
        gaps.append("the admission does not call the shared minimum-refresh answer")
    if "if (!MLInterpolationHasCadenceHeadroom(displayRefreshRate, self.frameRate))" not in renderer_text:
        gaps.append("the admission does not use the shared integer cadence and tolerance")
    if re.search(r"frameRate\s*\*\s*1\.5", renderer_text) or \
       re.search(r"frameRate\s*\+\s*12\.0", renderer_text):
        gaps.append("the renderer still carries its own copy of the cadence arithmetic")
    # The negotiated agreement is not the content. When the measured source rate runs below
    # it, the hold must be the shared snap's answer, not the agreement's arithmetic: 36 FPS
    # over a 90 FPS agreement on 180 Hz is the field session that read as jitter.
    if "MLInterpolationSnappedRefreshesPerFrame(_lastDisplayRefreshRate, productionFps)" not in renderer_text:
        gaps.append("the hold path does not ask the shared snap for a whole-refresh answer")
    if "_measuredSourceFpsEma > 0.0 && _measuredSourceFpsEma < (double)self.frameRate * 0.9" not in renderer_text:
        gaps.append("the hold path never compares the measured source rate against the agreement")
    # The blend runs inside the C display-link callback, where self is a bridged
    # pointer, so it reaches the EMA through self->_, not the bare ivar.
    if "self->_measuredSourceFpsEma = 0.5 * self->_measuredSourceFpsEma + 0.5 * windowFps" not in renderer_text:
        gaps.append("the measured source rate is never blended from the one-second windows")
    # The production answer is measured, not assumed. The snap's production must fold in the
    # measured interpolation rate, because a ~50% interpolation success rate halves the output
    # the full-assumption formula would predict; without it the hold grid outruns the panel.
    if "MIN(_measuredInterpolatedFpsEma, _measuredSourceFpsEma)" not in renderer_text:
        gaps.append("the snap's production answer never folds in the measured interpolation rate")
    if "self->_measuredInterpolatedFpsEma = 0.75 * self->_measuredInterpolatedFpsEma + 0.25 * interpWindowFps" not in renderer_text:
        gaps.append("the measured interpolation rate is never blended from the one-second windows")
    # The grid the hold stands on must not flip on a boundary wobble: the field session
    # measured a production sitting on the 45/36 FPS boundary, and the one-second windows
    # swung the EMA across it every other window, which the panel read as a second beat.
    if "candidateError + 4.0 < currentError" not in renderer_text:
        gaps.append("the snap grid can flip on a boundary wobble (no dead zone)")
    # The drawable pool sizes itself to the hold, not to a constant that is right for a one-
    # refresh hold and wrong for a multi-refresh one: a 50 ms hold with a depth-2 pool queues
    # the next submission inside the hold and the next-drawable timeout drops it (33 ms P95).
    if "MAX(2LL, _activeCadenceRefreshesPerFrame + 1)" not in renderer_text:
        gaps.append("the drawable pool does not size itself to the cadence hold")
    if re.findall(r"presentDrawable:drawable afterMinimumDuration:(\w+)", renderer_text) != ["presentationHoldSeconds"]:
        gaps.append("Metal must receive the previous drawable's minimum display duration")
    if not re.search(r"hasInterpolatedPair\s*&&\s*\[self presentationCadenceForInterpolationHold:", renderer_text):
        gaps.append("a source without its midpoint can still incur an interpolation hold")
    if "completedStats.receivedFrames >= 4" not in renderer_text:
        gaps.append("a sub-four-frame window can seed the measured source rate")
    listed = re.search(r"static\s+var\s+fpss\s*:\s*\[Int\]\s*=\s*\[([^\]]*)\]", swift_text)
    if listed is None:
        gaps.append("the settings page's frame rate list cannot be found to compare against")
    else:
        rates = [int(number) for number in re.findall(r"\d+", listed.group(1)) if int(number) != 0]
        if rates != PRESETS:
            gaps.append("the page offers %s while the policy recommends from %s"
                        % (rates, PRESETS))
    for preset in PRESETS:
        if ("case %d: return %d;" % (PRESETS.index(preset), preset)) not in policy_text:
            gaps.append("the policy no longer names %d FPS as an offered frame rate" % preset)
    return gaps


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    return ok


def main():
    policy, renderer, swift = read(POLICY), read(RENDERER), read(DERIVED)
    answers, failure = drive(policy)
    if answers is None:
        check(False, "the shipped policy header compiles and runs: %s" % (failure or "no output"))
        return 1
    problems = behaviour(answers)
    gaps = wiring(policy, renderer, swift)
    check(len(EXPECTED) - len(problems) >= MIN_BEHAVIOUR and not problems,
          "the shipped cadence answers %d readings correctly (%d wrong)"
          % (len(EXPECTED) - len(problems), len(problems))
          if not problems else
          "cadence readings wrong: " + "; ".join(problems[:6]))
    check(not gaps, "one cadence answer serves the renderer and the settings page (%d gaps)" % len(gaps)
          if not gaps else "cadence wiring: " + "; ".join(gaps))
    return 1 if (problems or gaps) else 0


def red_proofs():
    rc = 0
    policy, renderer, swift = read(POLICY), read(RENDERER), read(DERIVED)

    countdown = renderer.replace("afterMinimumDuration:presentationHoldSeconds",
                                 "afterMinimumDuration:gridHoldSeconds", 1)
    unpaired_hold = renderer.replace("hasInterpolatedPair &&", "YES &&", 1)
    for mutation, expected in [(countdown, "previous drawable's minimum"),
                               (unpaired_hold, "without its midpoint")]:
        hit = any(expected in gap for gap in wiring(policy, mutation, swift))
        check(hit, "reject pacing regression: " + expected)
        rc |= 0 if hit else 1

    # Putting the pre-divisibility headroom rule back must go red: under it 120 FPS is
    # admitted on a 180 Hz panel (the pairing that measured as viscous jitter), which is
    # exactly the reading this file's edge180_120 names as a refusal.
    loosened = policy.replace("    return sourceFps * 2.0;",
                              "    double byRatio = sourceFps * 1.5;"
                              " double byHeadroom = sourceFps + 12.0;"
                              " return byRatio > byHeadroom ? byRatio : byHeadroom;", 1)
    answers, _ = drive(loosened)
    wrong = behaviour(answers) if answers else ["the mutated policy did not build"]
    hit = any("min60" in problem or "edge180_120" in problem or "sug180" in problem
            for problem in wrong)
    print("%-4s loosening the rule by ten hertz is refused (%d readings wrong)"
          % ("ok" if hit else "FAIL", len(wrong)))
    rc |= 0 if hit else 1

    forked = renderer.replace("    double minimumRefreshRate = MLInterpolationMinimumRefreshForSourceFps((double)self.frameRate);",
                              "    double minimumRefreshRate = MAX((double)self.frameRate * 1.5, "
                              "(double)self.frameRate + 12.0);", 1)
    gaps = wiring(policy, forked, swift)
    hit = any("own copy" in gap for gap in gaps)
    print("%-4s putting the arithmetic back beside the shared call is refused (%d gaps named)"
          % ("ok" if hit else "FAIL", len(gaps)))
    rc |= 0 if hit else 1

    retitled = swift.replace("static var fpss: [Int] = [30, 60, 90, 120, 144, .zero]",
                             "static var fpss: [Int] = [30, 60, 90, 125, 144, .zero]", 1)
    if retitled == swift:
        print("FAIL  the settings list could not be mutated (the source text moved)")
        rc = 1
    else:
        gaps = wiring(policy, renderer, retitled)
        hit = any("while the policy recommends" in gap for gap in gaps)
        print("%-4s changing a frame rate on the page alone is refused (%d gaps named)"
              % ("ok" if hit else "FAIL", len(gaps)))
        rc |= 0 if hit else 1

    # The snap is an answer about the real production rate, not a rounding of the agreement.
    # Killing the candidate walk leaves only the centre, and 130 FPS on 180 Hz rounds to 1
    # refresh (180 implied) when the walk would answer 2 (90 implied) -- the reading this
    # file names as snap180_130.
    unsnapped = policy.replace("""    for (long candidate = centre - 1; candidate <= centre + 1; candidate++) {
        if (candidate < 1) {
            continue;
        }""",
                              """    for (long candidate = centre; candidate <= centre; candidate++) {
        if (candidate < 1) {
            continue;
        }""", 1)
    if unsnapped == policy:
        print("FAIL  the snap candidate walk could not be mutated (the source text moved)")
        rc = 1
    else:
        answers, _ = drive(unsnapped)
        wrong = behaviour(answers) if answers else ["the mutated policy did not build"]
        hit = any("snap180_130" in problem for problem in wrong)
        print("%-4s rounding the hold instead of snapping to the real rate is refused (%d readings wrong)"
              % ("ok" if hit else "FAIL", len(wrong)))
        rc |= 0 if hit else 1

    # A depth-2 pool is right for a one-refresh hold and wrong for a multi-refresh one: the
    # next submission waits inside the 50 ms hold and the next-drawable timeout drops it,
    # which is the 33 ms frame P95 the field session measured. Putting the constant back
    # must go red.
    shallow = renderer.replace(
        "return (NSUInteger)MAX(2LL, _activeCadenceRefreshesPerFrame + 1);",
        "return 2;", 1)
    if shallow == renderer:
        print("FAIL  the drawable pool depth could not be mutated (the source text moved)")
        rc = 1
    else:
        gaps = wiring(policy, shallow, swift)
        hit = any("size itself to the cadence hold" in gap for gap in gaps)
        print("%-4s letting the drawable pool forget the cadence hold is refused (%d gaps named)"
              % ("ok" if hit else "FAIL", len(gaps)))
        rc |= 0 if hit else 1

    # The production answer must be measured, not assumed: dropping the interpolation EMA
    # restores the one-interpolated-frame-per-source assumption that overshot the ~50% field
    # success rate, and the 60 FPS grid outran the panel.
    assumed = renderer.replace(
        """        const double productionFps = _measuredInterpolatedFpsEma > 0.0
            ? _measuredSourceFpsEma + MIN(_measuredInterpolatedFpsEma, _measuredSourceFpsEma)
            : _measuredSourceFpsEma + MIN(_measuredSourceFpsEma, (double)self.frameRate);""",
        """        const double productionFps = _measuredSourceFpsEma + MIN(_measuredSourceFpsEma, (double)self.frameRate);""", 1)
    if assumed == renderer:
        print("FAIL  the production answer could not be mutated (the source text moved)")
        rc = 1
    else:
        gaps = wiring(policy, assumed, swift)
        hit = any("measured interpolation rate" in gap for gap in gaps)
        print("%-4s assuming one interpolated frame per source frame is refused (%d gaps named)"
              % ("ok" if hit else "FAIL", len(gaps)))
        rc |= 0 if hit else 1
    return rc


if __name__ == "__main__":
    sys.exit(1 if "--self-test" in sys.argv[1:] and red_proofs() else
             (0 if "--self-test" in sys.argv[1:] else main()))
