#!/usr/bin/env python3
"""Prove the one cadence answer stays one answer, and that it answers correctly.

Whether a display can carry frame interpolation at a given stream frame rate is a single
arithmetic fact -- refresh at least 1.5x the stream rate and at least 12 Hz above it -- but two
places have to act on it: the renderer, which refuses to build an interpolating engine, and the
settings page, which has to warn a player before the stream starts and name a frame rate that
would work. The moment those two are separate copies of the formula, a player can be told to pick
a value the renderer then refuses, which is worse than no warning at all: they did what they were
asked and the feature still did nothing. InterpolationCadencePolicy.h is the single copy; this
file is what keeps it single and right.

Three things are checked:

  * the shipped C functions are compiled as-is and driven: the minimum refresh per frame rate,
    the exact boundary (180 Hz carrying 120 FPS, 179 not), unknown and negative refresh refused,
    the recommendation snapped to a frame rate the settings page actually offers, and the frame
    rate list itself;
  * the wiring, read out of the shipping sources: the renderer imports the header, its admission
    calls the shared function, the duplicated arithmetic is gone rather than still living beside
    it, and the recommendation cannot name a frame rate the page cannot select;
  * floors, because an audit whose driver stopped parsing would report zero failures.

--self-test plants three mistakes: loosen the rule by ten hertz; put the arithmetic back into the
renderer next to the shared call; and change a frame rate in the settings list alone. All three
have to come back red.
"""
import os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = os.path.join(ROOT, "Limelight", "macOS", "InterpolationCadencePolicy.h")
RENDERER = os.path.join(ROOT, "Limelight", "Stream", "VideoDecoderRenderer.m")
DERIVED = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers",
                       "SettingsModel+DerivedValues.swift")

MIN_BEHAVIOUR = 25
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
    printf("unknownrefresh=%d negrefresh=%d zerofps=%d\n",
           MLInterpolationHasCadenceHeadroom(0.0, 60),
           MLInterpolationHasCadenceHeadroom(-5.0, 60),
           MLInterpolationHasCadenceHeadroom(240.0, 0));
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
# this file: 180 Hz carrying exactly 120 FPS is the pairing a 180 Hz player must choose, and the
# recommendation being a selectable rate is what makes the settings page's advice actionable.
EXPECTED = {
    "min12": "24.0", "min20": "32.0", "min23": "35.0", "min24": "36.0",
    "min30": "45.0", "min60": "90.0", "min120": "180.0", "min144": "216.0",
    "edge32_20": "1", "edge31_20": "0", "edge45_30": "1", "edge44_30": "0",
    "edge180_120": "1", "edge179_120": "0", "edge180_144": "0", "edge90_60": "1",
    "edge24_36": "1", "unknownrefresh": "0", "negrefresh": "0", "zerofps": "0",
    "cap180": "120", "cap179": "119", "cap165": "110", "cap144": "96", "cap120": "80",
    "cap90": "60", "cap60": "40", "cap45": "30", "cap30": "0", "cap0": "0", "cap-8": "0",
    "sug180": "120", "sug179": "90", "sug165": "90", "sug144": "90", "sug120": "60",
    "sug90": "60", "sug60": "30", "sug45": "30", "sug30": "0", "sug0": "0", "sug-8": "0",
    "count": "5", "preset0": "30", "preset1": "60", "preset2": "90", "preset3": "120",
    "preset4": "144", "oob": "0",
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
        build = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-I", work,
                                os.path.join(work, "driver.c"), "-o", binary],
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
    if re.search(r"frameRate\s*\*\s*1\.5", renderer_text) or \
       re.search(r"frameRate\s*\+\s*12\.0", renderer_text):
        gaps.append("the renderer still carries its own copy of the cadence arithmetic")
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

    loosened = policy.replace("sourceFps + 12.0", "sourceFps + 2.0", 1)
    answers, _ = drive(loosened)
    wrong = behaviour(answers) if answers else ["the mutated policy did not build"]
    hit = any("min60" in problem or "cap180" in problem or "edge" in problem for problem in wrong)
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
    return rc


if __name__ == "__main__":
    sys.exit(1 if "--self-test" in sys.argv[1:] and red_proofs() else
             (0 if "--self-test" in sys.argv[1:] else main()))
