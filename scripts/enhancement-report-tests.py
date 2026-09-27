#!/usr/bin/env python3
"""Say out loud what the settings page tells a player about upscaling, state by state.

The line under "Upscaling Engine" used to be picked by reading prose: `containsString:` for "warmup
in progress", then a question about whether the engine was none, then "fell back", "fallback",
"temporarily using". That is the shape this repository has ruled out twice -- the pairing layer and
the retry layer read codes now, because words drift -- and it collapsed in the direction that hurts
most: a player who asked for a hardware scaler and was quietly given bilinear scaling read the same
sentence as a player who never enabled the feature, because the engine-is-none question was asked
first. Nothing in the tree guarded this dispatcher, either: the interpolation report has its own
harness, and the enhancement one had none.

Two facts were also unsaytable, because no state existed for them. The window is not larger than the
stream -- nothing to rebuild, and no setting will change that while the sizes match -- and
VideoToolbox's scalers are macOS 26 API, so a player on an older system will never satisfy that
option however they resize the window. Both are now states, and both have a sentence.

The dispatcher is lifted and played: all eight states are asked, and each must answer a different
key that exists in both tables. The resolver is read where the answers are written: every branch that
returns an engine names a state on the way out, every reason the resolver can write is named by this
file with the state it must produce, and the refusal that means "older system" is produced by the OS
gate rather than by a guess. Both directions are proven by --self-test.
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load_sibling():
    """The resolver stand-ins from the sweep that already exists.

    That file already answers "which scaler configurations does this Mac offer" with fakes, which is
    what any probe of the resolver needs; a second copy of those fakes here would be a second thing
    to keep honest, and this repository has opinions about that. Importing it costs a coupling and
    buys one source of truth.
    """
    spec = importlib.util.spec_from_file_location(
        "enhancement_engine_resolution_tests",
        os.path.join(HERE, "enhancement-engine-resolution-tests.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RENDERER = "Limelight/Stream/VideoDecoderRenderer.m"
MODEL_RULES = "Limelight/macOS/ViewControllers/SettingsModel+VideoPageRules.swift"
PANE = "Limelight/macOS/ViewControllers/SettingsVideoPane.swift"
EN = "Limelight/macOS/en.lproj/Localizable.strings"
ZH = "Limelight/macOS/zh-Hans.lproj/Localizable.strings"
DISPATCHER = "- (NSString *)runtimeDetailKeyForEnhancementReport:(MLVideoEnhancementReport)report"

# Every state, with the key it must answer and the sentence both tables must carry.
STATES = (
    ("MLVideoEnhancementReportActive", "Video Enhancement Runtime Detail Active"),
    ("MLVideoEnhancementReportFellBack", "Video Enhancement Runtime Detail Fallback"),
    ("MLVideoEnhancementReportNeedsNewerSystem",
     "Video Enhancement Runtime Detail Needs Newer System"),
    ("MLVideoEnhancementReportNeedsStreamShape",
     "Video Enhancement Runtime Detail Needs Stream Shape"),
    ("MLVideoEnhancementReportWarmup", "Video Enhancement Runtime Detail Warmup"),
    ("MLVideoEnhancementReportNoUpScaleNeeded",
     "Video Enhancement Runtime Detail No Up Scale Needed"),
    ("MLVideoEnhancementReportDisabledForHdr",
     "Video Enhancement Runtime Detail Disabled For Hdr"),
    ("MLVideoEnhancementReportDisabled", "Video Enhancement Runtime Detail Off"),
)

# Every reason the resolver can write, with the state it has to produce. Written from what the
# player should be told, not from the code: "Auto" asked for the best available and got it, so it is
# Active where an explicit choice that failed is FellBack; the shape and the system are each their
# own answer because each names a different thing to change.
REASON_STATES = {
    "enhancement disabled": "MLVideoEnhancementReportDisabled",
    "target size does not require upscale": "MLVideoEnhancementReportNoUpScaleNeeded",
    "HDR stream uses direct Metal scaling to preserve HDR output":
        "MLVideoEnhancementReportDisabledForHdr",
    "HDR stream bypasses post-processing to preserve HDR output":
        "MLVideoEnhancementReportDisabledForHdr",
    "Auto selected VT low-latency super resolution": "MLVideoEnhancementReportActive",
    "Auto selected MetalFX": "MLVideoEnhancementReportActive",
    "Auto selected MetalFX for a window that is not the stream's shape":
        "MLVideoEnhancementReportActive",
    "Auto fell back to basic scaling": "MLVideoEnhancementReportFellBack",
    "VT low-latency super resolution requested": "MLVideoEnhancementReportActive",
    "VT low-latency super resolution unavailable; fell back to MetalFX":
        "hardwareScalerRefusedReport",
    "VT low-latency super resolution needs macOS 26; fell back to MetalFX":
        "hardwareScalerRefusedReport",
    "VT low-latency super resolution needs the stream's own shape; MetalFX scales this window":
        "hardwareScalerRefusedReport",
    "VT low-latency super resolution unavailable; fell back to basic scaling":
        "hardwareScalerRefusedReport",
    "VT low-latency super resolution needs macOS 26; fell back to basic scaling":
        "hardwareScalerRefusedReport",
    "VT quality super resolution requested": "MLVideoEnhancementReportActive",
    "VT quality super resolution unavailable; fell back to VT low-latency super resolution":
        "MLVideoEnhancementReportFellBack",
    "VT quality super resolution unavailable; fell back to MetalFX":
        "hardwareScalerRefusedReport",
    "VT quality super resolution needs macOS 26; fell back to MetalFX":
        "hardwareScalerRefusedReport",
    "VT quality super resolution needs the stream's own shape; MetalFX scales this window":
        "hardwareScalerRefusedReport",
    "VT quality super resolution unavailable; fell back to basic scaling":
        "hardwareScalerRefusedReport",
    "VT quality super resolution needs macOS 26; fell back to basic scaling":
        "hardwareScalerRefusedReport",
    "MetalFX quality requested": "MLVideoEnhancementReportActive",
    "MetalFX quality requested for a window that is not the stream's shape":
        "MLVideoEnhancementReportActive",
    "MetalFX quality unavailable; fell back to basic scaling":
        "MLVideoEnhancementReportFellBack",
    "MetalFX performance requested": "MLVideoEnhancementReportActive",
    "MetalFX performance requested for a window that is not the stream's shape":
        "MLVideoEnhancementReportActive",
    "MetalFX performance unavailable; fell back to basic scaling":
        "MLVideoEnhancementReportFellBack",
    "basic scaling requested": "MLVideoEnhancementReportActive",
}

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


DRIVER = r"""
static NSUInteger gChecked;
static NSUInteger gFailed;
static NSUInteger gDistinct;
static NSString *gAnswers[16];
static NSUInteger gAnswerCount;

static NSString *gWantKeys[] = {
WANT_KEYS_PLACEHOLDER
};
static NSString *gWantStates[] = {
WANT_STATES_PLACEHOLDER
};
static const NSUInteger gWantCount = sizeof(gWantKeys) / sizeof(gWantKeys[0]);

int main(void) {
    @autoreleasepool {
        for (NSUInteger index = 0; index < gWantCount; index++) {
            gChecked++;
            // The shipped dispatcher is an instance method of the renderer, so the
            // harness calls it the way the renderer does. A class-method call is a
            // harness bug, not a production contract.
            NSString *key = [[MLVideoDecoderUnderTest new]
                runtimeDetailKeyForEnhancementReport:(MLVideoEnhancementReport)index];
            NSUInteger seen = 0;
            BOOL fresh = YES;
            while (seen < gAnswerCount) {
                if ([gAnswers[seen] isEqualToString:key]) {
                    fresh = NO;
                    break;
                }
                seen++;
            }
            if (fresh) {
                gAnswers[gAnswerCount++] = key;
            }
            if (![key isEqualToString:gWantKeys[index]]) {
                gFailed++;
                printf("     state %lu answers %s, the page needs %s\n",
                       (unsigned long)index, [key UTF8String], [gWantKeys[index] UTF8String]);
            }
        }
        printf("%s %lu states of the enhancement report checked, %lu failed\n",
               gFailed ? "FAIL" : "ok", (unsigned long)gChecked, (unsigned long)gFailed);
        printf("   the eight states answer %lu distinct ways\n",
               (unsigned long)gAnswerCount);
        if (gAnswerCount != gWantCount) {
            gFailed++;
            printf("FAIL the page answers %lu ways where there are %lu states to tell apart\n",
                   (unsigned long)gAnswerCount, (unsigned long)gWantCount);
        }
        return gFailed ? 1 : 0;
    }
}
"""


def dispatcher_source(renderer):
    module = load_sibling()
    return (module.STUBS + "\n"
            + module.enum_block(renderer, "typedef NS_ENUM(NSInteger, MLVideoEnhancementReport)")
            + "\n@interface MLVideoDecoderUnderTest : NSObject\n@end\n@implementation "
              "MLVideoDecoderUnderTest\n"
            + module.method(renderer, DISPATCHER) + "\n@end\n"
            + DRIVER.replace("WANT_KEYS_PLACEHOLDER",
                             ",\n".join('    @"%s"' % key for _state, key in STATES))
                      .replace("WANT_STATES_PLACEHOLDER",
                               ",\n".join('    @"%s"' % state for state, _key in STATES)))


def compiled(source, work, clang, sdk):
    path = os.path.join(work, "report.m")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    binary = os.path.join(work, "report")
    command = [clang, "-fobjc-arc", "-isysroot", sdk, "-framework", "Foundation",
               "-o", binary, path]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return False, (built.stdout + built.stderr)[-2500:]
    ran = subprocess.run([binary], capture_output=True, text=True)
    sys.stdout.write(ran.stdout)
    return ran.returncode == 0, (ran.stdout.strip().splitlines() or ["no output"])[-1]


def resolver_span(source):
    start = source.index("resolveEnhancementEngineForSourceWidth:(NSUInteger)sourceWidth")
    brace = source.index("{", source.index("report:(MLVideoEnhancementReport *)reportOut", start))
    depth, index = 0, brace
    while index < len(source):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
        index += 1
    raise SystemExit("unbalanced braces reading the enhancement resolver")


def gaps(renderer, rules, pane, en, zh):
    found = []
    body = resolver_span(renderer)

    answers = re.findall(r"MLSetEnhancementAnswer\(\s*([A-Za-z_]+),\s*(.*?)\);\s*\n", body, re.S)
    if not answers:
        found.append("the resolver no longer writes its state beside its reason")
    for _state, expression in answers:
        literals = re.findall(r'@@"([^"]*)"', expression) or re.findall(r'@"([^"]*)"', expression)
        states = {REASON_STATES[literal] for literal in literals if literal in REASON_STATES}
        if literals and len(states) != 1:
            found.append("one answer names reasons that need different states: %s" % literals)

    named = {state for state, _expression in answers}
    unmapped = sorted(set(REASON_STATES)
                      - {literal for _s, expression in answers
                         for literal in re.findall(r'@@"([^"]*)"', expression)
                         + re.findall(r'@"([^"]*)"', expression)})
    if unmapped:
        found.append("reasons the resolver no longer names: %s" % ", ".join(unmapped[:3]))

    # A branch that returns an engine without naming a state is the whole failure mode: the page
    # keeps whatever the last caller left in the variable.
    returns = [m.start() for m in re.finditer(r"\n\s+return MLActiveVideoEnhancementEngine", body)]
    writes = [m.start() for m in re.finditer(r"MLSetEnhancementAnswer\(", body)]
    unreported = [position for position in returns
                  if not any(write < position for write in writes)]
    if unreported:
        found.append("%d enhancement branch(es) return an engine without naming a state"
                     % len(unreported))

    dispatcher = renderer[renderer.index(DISPATCHER):]
    dispatcher = dispatcher[:dispatcher.index("\n}\n")]
    if "containsString" in dispatcher:
        found.append("the settings line is chosen by searching the reason text again")
    for state, key in STATES:
        if "case %s:" % state not in dispatcher:
            found.append("%s has no line of its own" % state)
        if '"%s"' % key not in en or '"%s"' % key not in zh:
            found.append("%s has no wording in both languages" % key)
    # The prose collapse this file exists to refuse is two states quietly sharing one
    # sentence, so the static pass checks the dispatcher's own wording map is injective
    # -- not only that every case and every key survives somewhere.
    answered = re.findall(r'case (MLVideoEnhancementReport\w+):\s*\n\s*return @"([^"]+)"', dispatcher)
    if len(answered) >= 2:
        seen = {}
        for state, key in answered:
            if key in seen and seen[key] != state:
                found.append("two states share one sentence: %s answers both %s and %s"
                             % (key, seen[key], state))
            seen.setdefault(key, state)
    answer_writers = named | {m for m in re.findall(r"MLSetEnhancementAnswer\(\s*([A-Za-z_]+)", body)}
    # The older-system answer is written through the macOS 26 gate variable, never as a
    # second literal, so a writer counts when it names either the state or the gate that
    # produces it. The refusal below keeps the kill: a tree where every gate answer was
    # rewritten to a literal answers nothing here.
    if named and not ({"MLVideoEnhancementReportNeedsNewerSystem",
                       "hardwareScalerRefusedReport"} & answer_writers):
        found.append("nothing in the resolver can answer the older-system state")

    if not re.search(r"!videoToolboxScalerAPIAvailable \? MLVideoEnhancementReportNeedsNewerSystem",
                     body):
        found.append("the older-system state is not produced by the macOS 26 gate")
    if "MLVideoEnhancementReportWarmup" not in renderer[renderer.index("logActiveEnhancementEngine:_activeEnhancementEngine"):]:
        found.append("a warming scaler does not reach the page as a warming scaler")
    if "report:MLVideoEnhancementReportFellBack" not in renderer:
        found.append("a scaler that failed at runtime does not say so")
    if "runtimeDetailKeyForEnhancementEngine:" in renderer:
        found.append("the prose dispatcher is still there beside the state dispatcher")
    if "videoToolboxSuperResolutionIsAvailable" not in rules or \
            '"Upscaling needs newer system hint"' not in pane:
        found.append("the page does not say before a stream that the hardware path needs macOS 26")
    if '"Upscaling needs newer system hint"' not in en or \
            '"Upscaling needs newer system hint"' not in zh:
        found.append("the macOS 26 hint has no wording in both languages")
    return found


def main():
    renderer, rules, pane, en, zh = (read(RENDERER), read(MODEL_RULES), read(PANE),
                                     read(EN), read(ZH))
    try:
        clang, sdk = apple_toolchain.clang_and_sdk("enhancement report probe")
    except SystemExit as missing:
        check(False, str(missing))
        return 1
    with tempfile.TemporaryDirectory() as work:
        ok, detail = compiled(dispatcher_source(renderer), work, clang, sdk)
    check(ok, "the shipping dispatcher answers all eight states distinctly"
          if ok else "the enhancement dispatcher failed: %s" % (detail,))
    found = gaps(renderer, rules, pane, en, zh)
    check(not found, "each state reaches its own sentence on the page (%d gaps)" % len(found)
          if not found else "enhancement report wiring: " + "; ".join(found[:6]))
    return 1 if (not ok or found) else 0


def red_proofs():
    rc = 0
    renderer, rules, pane, en, zh = (read(RENDERER), read(MODEL_RULES), read(PANE),
                                     read(EN), read(ZH))
    clang, sdk = apple_toolchain.clang_and_sdk("enhancement report probe")

    def refuse(name, mutated_renderer, expected, source_mutations=None):
        nonlocal rc
        text = mutated_renderer
        for old, new in (source_mutations or []):
            assert text.count(old) >= 1, (name, old[:60])
            text = text.replace(old, new)
        hit = any(expected in gap for gap in gaps(text, rules, pane, en, zh))
        print("%-4s %s is refused" % ("ok" if hit else "FAIL", name))
        rc |= 0 if hit else 1

    refuse("the older-system refusal answering the generic fallback line",
           renderer, "produced by the macOS 26 gate",
           [("!videoToolboxScalerAPIAvailable ? MLVideoEnhancementReportNeedsNewerSystem",
             "!videoToolboxScalerAPIAvailable ? MLVideoEnhancementReportFellBack")])
    refuse("a branch returning an engine without naming a state",
           renderer, "without naming a state",
           [("        MLSetEnhancementAnswer(MLVideoEnhancementReportDisabled,\n"
             "            @\"enhancement disabled\");\n"
             "        return MLActiveVideoEnhancementEngineNone;",
             "        return MLActiveVideoEnhancementEngineNone;")])
    refuse("no writer left for the older-system state",
           renderer, "nothing in the resolver can answer the older-system state",
           [("MLSetEnhancementAnswer(hardwareScalerRefusedReport,",
             "MLSetEnhancementAnswer(MLVideoEnhancementReportActive,")])
    refuse("the collapse the prose dispatcher made: no-upscale answering the off line",
           renderer, "two states share one sentence",
           [('case MLVideoEnhancementReportNoUpScaleNeeded:\n'
             '            return @"Video Enhancement Runtime Detail No Up Scale Needed";',
             'case MLVideoEnhancementReportNoUpScaleNeeded:\n'
             '            return @"Video Enhancement Runtime Detail Off";')])
    refuse("the macOS 26 hint being dropped from the page",
           renderer, "does not say before a stream",
           [] ) if False else None

    collapsed_rules = rules.replace('''          if !settingsModel.videoToolboxSuperResolutionIsAvailable {''',
                                    '''          if NO {''')
    hit = any("does not say before a stream" in gap
              for gap in gaps(renderer, rules.replace(
                  "var videoToolboxSuperResolutionIsAvailable: Bool {",
                  "var videoToolboxSuperResolutionIsAvailableUnused: Bool {"),
                  pane.replace('textKey: "Upscaling needs newer system hint"',
                               'textKey: "Upscaling detail"'), en, zh))
    print("%-4s a page that never shows the macOS 26 hint is refused %s"
          % ("ok" if hit else "FAIL", ""))
    rc |= 0 if hit else 1
    del collapsed_rules

    with tempfile.TemporaryDirectory() as work:
        merged = dispatcher_source(renderer).replace(
            '        case MLVideoEnhancementReportNeedsStreamShape:\n'
            '            return @"Video Enhancement Runtime Detail Needs Stream Shape";',
            '        case MLVideoEnhancementReportNeedsStreamShape:\n'
            '            return @"Video Enhancement Runtime Detail Fallback";')
        assert merged != dispatcher_source(renderer), "the merge mutation was not an edit"
        ok, _ = compiled(merged, work, clang, sdk)
        print("%-4s two states answering one sentence is refused" % ("ok" if not ok else "FAIL"))
        rc |= 0 if not ok else 1
    return rc


if __name__ == "__main__":
    sys.exit(1 if "--self-test" in sys.argv[1:] and red_proofs() else
             (0 if "--self-test" in sys.argv[1:] else main()))
