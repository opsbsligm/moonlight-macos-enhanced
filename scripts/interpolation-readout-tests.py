#!/usr/bin/env python3
"""Prove the interpolation readout carries measurements, and reaches a person who can act on them.

A sentence naming an engine is not a measurement. The settings page could already say "VT
Low-Latency Frame Interpolation", and that came from the admission -- the code deciding whether to
build an engine -- so it reported the decision, not the frames. Whether extra frames actually reach
the display, and against what refresh rate, was only on the performance overlay, and the overlay
exists only when the player turned it on. The player who most needs to know whether interpolation is
doing anything is the one looking at a settings page that cannot tell them.

So the three numbers, and the frame rate this display can carry, have to travel from the counters to
that page. Three ways for that to be untrue are worth refusing:

  * The readings are wired to the wrong counters. A row that says 60 arriving and 60 on screen while
    the interpolator is doubling is worse than no row, because it looks like evidence.
  * The publisher lives on the overlay's timer. `setupOverlay` -- and with it the only timer that
    calls `updateStats` -- is created when the host's "show performance overlay" setting is on, so a
    readout fed from there stops updating exactly for the players who never enable it, and the page
    keeps the last numbers it was given.
  * The advice recomputes the cadence rule. The renderer refuses a stream on `refresh >= max(1.5 fps,
    fps + 12)`; a page with its own copy of that is one edit away from recommending a rate the stream
    then refuses, which is the failure this repository has already been bitten by twice.

The publisher is therefore lifted out of VideoDecoderRenderer.m and played, with a fake settings
class recording what the shipping code asks the page to show, and the suggestion it hands over has
to be the shared policy's answer for the refresh it was given -- 180 Hz yields 120, 179 yields 90,
44 yields nothing. The rest is read where it is written: which counters feed the row, that stopping
a stream zeroes it, that the advice calls the shared policy rather than repeating it, and that the
page shows a line before there are any numbers to show.
"""
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDERER = "Limelight/Stream/VideoDecoderRenderer.m"
OVERLAY = "Limelight/macOS/ViewControllers/StreamViewController+Diagnostics.m"
BRIDGE = "Limelight/macOS/ViewControllers/SettingsObjCBridge.swift"
MODEL = "Limelight/macOS/ViewControllers/SettingsModel.swift"
RULES = "Limelight/macOS/ViewControllers/SettingsModel+VideoPageRules.swift"
PANE = "Limelight/macOS/ViewControllers/SettingsVideoPane.swift"
PROBE = "Limelight/macOS/ViewControllers/DebugVideoProbeExpectations.swift"
EN = "Limelight/macOS/en.lproj/Localizable.strings"
ZH = "Limelight/macOS/zh-Hans.lproj/Localizable.strings"

PUBLISHER = "- (void)publishVideoCadenceRuntimeReadoutWithSourceFps:(double)sourceFps"
STOP_PUBLISHER = "- (void)publishVideoCadenceRuntimeReadoutStopped"
READOUT_ROW = "SettingMeasuredRow(text: settingsModel.videoCadenceReadoutDisplayText)"
READOUT_KEYS = ("Frame Interpolation Cadence Idle",
                "Frame Interpolation Cadence Readout",
                "Frame Interpolation Cadence Readout Interpolating",
                "Frame Interpolation Cadence Advice",
                "Frame Interpolation Cadence No Headroom")

# refresh Hz -> the frame rate the policy will recommend, 0 meaning "not on this panel"
# 45 Hz answers 30 rather than nothing: 45 is exactly 1.5x 30, and the shipped comparison refuses
# only a refresh strictly below the minimum, so the boundary carries the slowest rate on offer.
# 44 is the first refresh that cannot carry any of them.
EXPECTED_SUGGESTIONS = ((180.0, 120), (179.0, 90), (140.0, 90), (100.0, 60),
                        (59.94, 30), (44.0, 0), (0.0, 0))

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def method(text, signature):
    start = text.find(signature)
    if start < 0:
        raise SystemExit("the shipping source no longer contains %s" % signature)
    brace = text.index("{", start)
    depth, index = 0, brace
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
        index += 1
    raise SystemExit("unbalanced braces reading %s" % signature)


HEAD = """#import <Foundation/Foundation.h>
#import "InterpolationCadencePolicy.h"

@interface SettingsClass : NSObject
+ (void)updateVideoCadenceReadoutFor:(NSString *)hostKey
                           sourceFps:(double)sourceFps
                           outputFps:(double)outputFps
                      interpolatedFps:(double)interpolatedFps
                            refreshHz:(double)refreshHz
                         suggestedFps:(int)suggestedFps;
@end

static double gSource, gOutput, gInterpolated, gRefresh;
static int gSuggested;
static NSString *gHostKey;

@implementation SettingsClass
+ (void)updateVideoCadenceReadoutFor:(NSString *)hostKey
                           sourceFps:(double)sourceFps
                           outputFps:(double)outputFps
                      interpolatedFps:(double)interpolatedFps
                            refreshHz:(double)refreshHz
                         suggestedFps:(int)suggestedFps
{
    gSource = sourceFps;
    gOutput = outputFps;
    gInterpolated = interpolatedFps;
    gRefresh = refreshHz;
    gSuggested = suggestedFps;
    gHostKey = hostKey;
}
@end
"""

CLASS = """
@interface MLProbeRenderer : NSObject {
    NSString *_runtimeHostKey;
}
@property (nonatomic, copy) NSString *runtimeHostKey;
@end

@implementation MLProbeRenderer
"""

DRIVER = """
static void Ask(NSString *hostKey, double source, double output, double interpolated,
                double refresh) {
    MLProbeRenderer *renderer = [[MLProbeRenderer alloc] init];
    renderer.runtimeHostKey = hostKey;
    gSource = gOutput = gInterpolated = gRefresh = -1;
    gSuggested = -1;
    gHostKey = nil;
    [renderer publishVideoCadenceRuntimeReadoutWithSourceFps:source outputFps:output
                                             interpolatedFps:interpolated refreshHz:refresh];
}

int main(void) {
    @autoreleasepool {
        int failed = 0;
        int checks = 0;
        double refreshes[] = {@@REFRESH@@};
        int wants[] = {@@WANT@@};
        for (int i = 0; i < @@COUNT@@; i++) {
            checks++;
            Ask(@"host-a", 60.0, 120.0, 60.0, refreshes[i]);
            if (gSuggested != wants[i]) {
                printf("     %.2fHz recommends %d, the policy says %d\\n",
                       refreshes[i], gSuggested, wants[i]);
                failed++;
            }
        }

        // The four readings travel untouched: a row that quietly swaps arriving for on screen
        // reads as a stream that is not being interpolated at all.
        checks++;
        Ask(@"host-a", 59.5, 118.25, 58.75, 179.94);
        if (gSource != 59.5 || gOutput != 118.25 || gInterpolated != 58.75 || gRefresh != 179.94) {
            printf("     the readings arrive as %.2f %.2f %.2f %.2f\\n",
                   gSource, gOutput, gInterpolated, gRefresh);
            failed++;
        }

        // A host without a key still has to reach the page, which reads the global row.
        checks++;
        Ask(nil, 60.0, 60.0, 0.0, 144.0);
        if (![gHostKey isEqualToString:@"__global__"]) {
            printf("     a keyless stream publishes under %s\\n",
                   gHostKey ? [gHostKey UTF8String] : "(nil)");
            failed++;
        }

        // Stopping a stream ends the measurement rather than leaving last second's numbers on
        // the page, where they are indistinguishable from a live reading.
        checks++;
        Ask(@"host-a", 60.0, 120.0, 60.0, 180.0);
        MLProbeRenderer *stopped = [[MLProbeRenderer alloc] init];
        stopped.runtimeHostKey = @"host-a";
        [stopped publishVideoCadenceRuntimeReadoutStopped];
        if (gSource != 0 || gOutput != 0 || gInterpolated != 0 || gRefresh != 0 || gSuggested != 0) {
            printf("     stopping leaves %.2f %.2f %.2f %.2f (%d) on screen\\n",
                   gSource, gOutput, gInterpolated, gRefresh, gSuggested);
            failed++;
        }

        printf("%s %d readings of the cadence readout published, %d wrong\\n",
               failed ? "FAIL" : "ok", checks, failed);
        return failed ? 1 : 0;
    }
}
"""


def probe_source(renderer):
    driver = (DRIVER
              .replace("@@REFRESH@@", ", ".join("%r" % refresh for refresh, _ in EXPECTED_SUGGESTIONS))
              .replace("@@WANT@@", ", ".join(str(want) for _, want in EXPECTED_SUGGESTIONS))
              .replace("@@COUNT@@", str(len(EXPECTED_SUGGESTIONS))))
    return (HEAD + CLASS + "\n" + method(renderer, PUBLISHER) + "\n"
            + method(renderer, STOP_PUBLISHER) + "\n@end\n" + driver)


def compiled(source, work, cc, sdk):
    path = os.path.join(work, "readout.m")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    binary = os.path.join(work, "readout")
    command = [cc, "-fobjc-arc", "-isysroot", sdk, "-framework", "Foundation",
               "-I", os.path.join(ROOT, "Limelight", "macOS"),
               "-o", binary, path]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr)[-3000:]
    ran = subprocess.run([binary], capture_output=True, text=True)
    sys.stdout.write(ran.stdout)
    return ran.returncode == 0, ran.stdout.strip().splitlines()[-1:] or ["no output"]


def advice_body(rules):
    start = rules.find("var frameInterpolationCadenceAdviceText")
    if start < 0:
        raise SystemExit("the settings page no longer has a cadence advice property")
    return rules[start:rules.find("\n  }\n", start)]


def gaps(renderer, overlay, bridge, model, rules, pane, probe, en, zh):
    found = []
    publish_call = re.search(
        r"\[self publishVideoCadenceRuntimeReadoutWithSourceFps:completedStats\.receivedFps\s+"
        r"outputFps:completedStats\.renderedFps\s+interpolatedFps:completedStats\.interpolatedFps\s+"
        r"refreshHz:self->_lastDisplayRefreshRate\];", renderer)
    if not publish_call:
        found.append("the row is not fed by the counters it names and the refresh the display link measured")

    roll_up = renderer.find("self->_videoStats = completedStats;")
    stop_zeroing = renderer.find("[self publishVideoCadenceRuntimeReadoutStopped];")
    if not (0 <= roll_up < (publish_call.start() if publish_call else -1)):
        found.append("the publish does not sit beside the per-second roll-up")
    teardown = renderer.find("[self publishVideoFrameInterpolationRuntimeStatusSummary:MLVideoFrameInterpolationEngineName(MLActiveVideoFrameInterpolationEngineNone)")
    if not (0 <= teardown < stop_zeroing):
        found.append("ending the interpolation session does not zero the readings")

    if "CadenceReadout" in overlay or "publishVideoCadenceReadout" in overlay:
        found.append("the readout is fed from the stats overlay, which only runs when the overlay is on")
    if "videoCadenceReadoutText" not in bridge or "== snapshot" not in bridge:
        found.append("the bridge does not store the readings and skip a repeat of them")
    if not re.search(r"name: \.moonlightVideoRuntimeStatusDidChange,\s*object: nil,\s*userInfo: \[\"hostKey\": key\]", bridge):
        found.append("a new reading does not wake the page that shows it")
    if "videoCadenceReadoutText = SettingsClass.videoCadenceReadoutText(for: hostId)" not in model:
        found.append("the page model never picks up the readings")
    if 'LanguageManager.shared.localize("Frame Interpolation Cadence Idle")' not in model:
        found.append("the row has nothing to say before a stream has measured anything")

    advice = advice_body(rules)
    if "MLInterpolationHasCadenceHeadroom" not in advice or "MLInterpolationSuggestedFpsForRefresh" not in advice:
        found.append("the advice does not ask the shared cadence policy")
    if re.search(r"1\.5|\*\s*1\.5|/ 1\.5", advice):
        found.append("the advice keeps its own copy of the cadence arithmetic")
    if READOUT_ROW not in pane:
        found.append("the page does not show the readout row")
    if "settingsModel.frameInterpolationCadenceAdviceText" not in pane:
        found.append("the page does not show the advice")
    if "model.videoCadenceReadoutDisplayText" not in probe:
        found.append("the artefact probe does not expect the readout row, so removing it stays invisible")
    for key in READOUT_KEYS:
        if '"%s"' % key not in en or '"%s"' % key not in zh:
            found.append("%s has no wording in both languages" % key)
    return found


def main():
    sources = dict(renderer=read(RENDERER), overlay=read(OVERLAY), bridge=read(BRIDGE),
                   model=read(MODEL), rules=read(RULES), pane=read(PANE), probe=read(PROBE),
                   en=read(EN), zh=read(ZH))
    try:
        cc, sdk = apple_toolchain.clang_and_sdk("cadence readout probe")
    except SystemExit as missing:
        check(False, str(missing))
        return 1
    with tempfile.TemporaryDirectory() as work:
        ok, detail = compiled(probe_source(sources["renderer"]), work, cc, sdk)
    check(ok, "the shipping publisher answers every reading it is given"
          if ok else "the shipping publisher failed: %s" % (detail or ""))
    found = gaps(**sources)
    check(not found, "the readings reach the page that shows them (%d gaps)" % len(found)
          if not found else "cadence readout wiring: " + "; ".join(found))
    return 1 if (not ok or found) else 0


def red_proofs():
    rc = 0
    sources = dict(renderer=read(RENDERER), overlay=read(OVERLAY), bridge=read(BRIDGE),
                   model=read(MODEL), rules=read(RULES), pane=read(PANE), probe=read(PROBE),
                   en=read(EN), zh=read(ZH))
    cc, sdk = apple_toolchain.clang_and_sdk("cadence readout probe")

    def refuse(name, mutate, expected):
        nonlocal rc
        mutated = dict(sources)
        mutated.update(mutate(dict(sources)))
        hit = any(expected in gap for gap in gaps(**mutated))
        print("%-4s %s is refused" % ("ok" if hit else "FAIL", name))
        rc |= 0 if hit else 1

    refuse("the arriving rate taken from the on-screen rate",
           lambda s: dict(renderer=s["renderer"].replace(
               "[self publishVideoCadenceRuntimeReadoutWithSourceFps:completedStats.receivedFps",
               "[self publishVideoCadenceRuntimeReadoutWithSourceFps:completedStats.renderedFps", 1)),
           "fed by the counters it names")
    refuse("a stopped stream leaving its last numbers on screen",
           lambda s: dict(renderer=s["renderer"].replace(
               "    [self publishVideoCadenceRuntimeReadoutStopped];\n", "", 1)),
           "does not zero the readings")
    refuse("the readout being fed from the performance overlay's timer",
           lambda s: dict(overlay=s["overlay"].replace(
               "    VideoStats stats = self.streamMan.connection.renderer.videoStats;",
               "    VideoStats stats = self.streamMan.connection.renderer.videoStats;\n"
               "    [SettingsClass updateVideoCadenceReadoutFor:0 sourceFps:0 outputFps:0"
               " interpolatedFps:0 refreshHz:0 suggestedFps:0];", 1)),
           "only runs when the overlay is on")
    refuse("a reading that never wakes the page",
           lambda s: dict(bridge=s["bridge"].replace(
               "name: .moonlightVideoRuntimeStatusDidChange,\n        object: nil,\n"
               "        userInfo: [\"hostKey\": key]", "name: .moonlightVideoRuntimeStatusDidChange", 1)),
           "does not wake the page")
    refuse("advice with its own copy of the rule",
           lambda s: dict(rules=s["rules"].replace(
               "!MLInterpolationHasCadenceHeadroom(refreshHz, Int32(targetFps))",
               "refreshHz < Double(targetFps) * 1.5", 1)),
           "own copy of the cadence arithmetic")
    refuse("the readout row being dropped from the page",
           lambda s: dict(probe=s["probe"].replace("model.videoCadenceReadoutDisplayText,", "", 1)),
           "does not expect the readout row")

    with tempfile.TemporaryDirectory() as work:
        lying = sources["renderer"].replace(
            "int suggestedFps = MLInterpolationSuggestedFpsForRefresh(refreshHz);",
            "int suggestedFps = refreshHz >= 180.0 ? 120 : 0;", 1)
        ok, _ = compiled(probe_source(lying), work, cc, sdk)
        print("%-4s a suggestion that is a constant rather than the policy's answer is refused"
              % ("ok" if not ok else "FAIL"))
        rc |= 0 if not ok else 1
    return rc


if __name__ == "__main__":
    sys.exit(1 if "--self-test" in sys.argv[1:] and red_proofs() else
             (0 if "--self-test" in sys.argv[1:] else main()))
