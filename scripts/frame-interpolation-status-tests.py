#!/usr/bin/env python3
"""Say out loud what the settings page tells a player about frame interpolation.

The renderer reports this feature twice: a summary naming the engine that ran, and a
detail line meant to explain it. Both are localization keys, and the detail key is
chosen by searching the reason for phrases. Searching a message to decide what to say
is a shape this repository has already ruled out twice over -- the pairing layer and
the retry layer read codes now, because words drift. The drift here is not
hypothetical: the reason for interpolation working says "provides cadence headroom
over", the reason for refusing it says "does not have cadence headroom over", and both
contain the phrase the dispatcher looks for, so the working case is reported with the
refusal line. The translated sentence that says interpolation is running has never been
reachable on any machine.

Nor is that the only collapse. A player who turned the feature on, on a machine that
offers it, whose per-frame interpolation then fails, is caught by the shortcut that asks
only whether the engine is none before the word "unavailable" is ever consulted. The
settings page tells that player interpolation is not enabled for the stream. They
enabled it, and the failure is the interesting one.

So every state the renderer can report is enumerated, and each pair of keys is compared
with a table written from what the player should be told rather than from what the code
currently answers. The reasons are the shipping ones: refusals come from the gate
itself, lifted and asked, and the inline texts are lifted out of the source instead of
retyped, so rewording a reason changes what this harness asks and cannot slip past. The
summary is checked beside the detail because the two render one under the other, and a
summary naming a hardware engine above a detail claiming the feature is off is exactly
what a player would read.

Coverage is counted and demanded, as it is elsewhere in this directory: a key never
returned is a sentence translated for nobody, which is how the working case hid.

Exit 0 only when every state answers correctly, the coverage is real, and every planted
shape fails.
"""
import os
import re
import subprocess
import sys
import tempfile

import apple_toolchain

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RENDERER = os.path.join(ROOT, "Limelight", "Stream", "VideoDecoderRenderer.m")

ENUMS = ("typedef NS_ENUM(NSInteger, MLActiveVideoFrameInterpolationEngine)",
         "typedef NS_ENUM(NSInteger, MLRequestedVideoFrameInterpolationMode)",
         "typedef NS_ENUM(NSInteger, MLActiveVideoRendererMode)",
         "typedef NS_ENUM(NSInteger, MLInterpolationSlotVerdict)",
         "typedef NS_ENUM(NSInteger, MLVideoFrameInterpolationReport)")
ENGINE_NAME = "static NSString *MLVideoFrameInterpolationEngineName"
DISPATCHER = "- (NSString *)runtimeDetailKeyForFrameInterpolationReport:"
# The first line of the signature only: the shipping source wraps the rest, and a
# constant spelling it out would be a claim about whitespace, not about the method.
GATE = "- (BOOL)shouldUseFrameInterpolationForDisplayRefreshRate:(double)displayRefreshRate"
SLOT_REASON = "static const char *MLInterpolationSlotReason("
REPORT_FOR_VERDICT = ("static MLVideoFrameInterpolationReport "
                      "MLVideoFrameInterpolationReportForSlotVerdict(")
STAGING = ("- (BOOL)stageInterpolatedFrameFromPreviousSource:"
           "(CVImageBufferRef)previousSourceFrame")
# Shape-based so the texts travel with the code that writes them: the two inline
# refusals sit either side of the warmup flag, the working report is the one built from
# a format string, and the transient one is the only reason handed to the logger as a
# literal rather than through a variable.
WARMUP_MARK = "_frameInterpolationWarmupInFlight"
FORMAT_MARK = "stringWithFormat:"
WAITING_SHAPE = r'reason:(@"[^"]*")\];[^@]{0,90}\[self requestEnhancedDraw\]'

HEAD = "#import <Foundation/Foundation.h>\n"

CLASS_HEAD = r"""
@interface MLVideoDecoderUnderTest : NSObject
@property (nonatomic) NSInteger requestedFrameInterpolationMode;
@property (nonatomic) NSInteger activeRendererMode;
@property (nonatomic) BOOL enableHdr;
@property (nonatomic) int frameRate;
@end

@implementation MLVideoDecoderUnderTest
"""

CLASS_TAIL = "@end\n"

DRIVER = r"""
static NSUInteger gChecked;
static NSUInteger gFailed;
static NSUInteger gKeyHits[16];
static NSString *gKeys[16];
static NSUInteger gKeyCount;

static NSString *gWantKeys[] = {
WANT_KEYS_PLACEHOLDER
};
static const NSUInteger gWantCount = sizeof(gWantKeys) / sizeof(gWantKeys[0]);

// The texts and the states are lifted from the shipping call sites, so both halves
// of every report arrive from the code rather than from this file.
static NSString *const kWarmupReason = kWarmupReason_PLACEHOLDER;
static MLVideoFrameInterpolationReport const kWarmupReport =
    kWarmupReport_PLACEHOLDER;
static NSString *const kRuntimeFailureReason = kRuntimeFailureReason_PLACEHOLDER;
static MLVideoFrameInterpolationReport const kRuntimeFailureReport =
    kRuntimeFailureReport_PLACEHOLDER;
static NSString *const kWaitingReason = kWaitingReason_PLACEHOLDER;
static MLVideoFrameInterpolationReport const kWaitingReport =
    kWaitingReport_PLACEHOLDER;
static NSString *const kWorkingFormat = kWorkingFormat_PLACEHOLDER;
static MLVideoFrameInterpolationReport const kWorkingReport =
    kWorkingReport_PLACEHOLDER;

static NSUInteger KeySlot(NSString *key) {
    for (NSUInteger index = 0; index < gKeyCount; index++) {
        if ([gKeys[index] isEqualToString:key]) {
            return index;
        }
    }
    gKeys[gKeyCount] = key;
    return gKeyCount++;
}

// One row of the settings page: the summary over the detail, both keys localized, and
// the sentence the log keeps. The prose is checked to be there because it is the only
// thing a person reading the log has, and a state that explains nothing is a state
// nobody can answer a question about.
static void Report(const char *state, MLActiveVideoFrameInterpolationEngine engine,
                   MLVideoFrameInterpolationReport report, NSString *reason,
                   NSString *wantSummary, NSString *wantDetail) {
    gChecked++;
    MLVideoDecoderUnderTest *renderer = [[MLVideoDecoderUnderTest alloc] init];
    NSString *summary = MLVideoFrameInterpolationEngineName(engine);
    NSString *detail = [renderer runtimeDetailKeyForFrameInterpolationReport:report];
    gKeyHits[KeySlot(detail)]++;
    if (reason.length == 0) {
        gFailed++;
        printf("     %-22s answers %s with nothing for the log\n", state,
               [detail UTF8String]);
        return;
    }
    if (![summary isEqualToString:wantSummary] || ![detail isEqualToString:wantDetail]) {
        gFailed++;
        printf("     %-22s the page says\n", state);
        printf("       summary %s\n         want  %s\n", [summary UTF8String],
               [wantSummary UTF8String]);
        printf("       detail  %s\n         want  %s\n", [detail UTF8String],
               [wantDetail UTF8String]);
    }
}

typedef struct { NSString *reason; MLVideoFrameInterpolationReport report; } GateAnswer;

// Ask the shipping gate rather than typing a refusal out, so both halves of what it
// answers -- the state it names and the sentence it writes -- are what gets checked.
static GateAnswer GateRefusal(NSInteger mode, NSInteger rendererMode, BOOL hdr,
                              int frameRate, double refreshRate) {
    MLVideoDecoderUnderTest *renderer = [[MLVideoDecoderUnderTest alloc] init];
    renderer.requestedFrameInterpolationMode = mode;
    renderer.activeRendererMode = rendererMode;
    renderer.enableHdr = hdr;
    renderer.frameRate = frameRate;
    NSString *reason = nil;
    MLVideoFrameInterpolationReport report = MLVideoFrameInterpolationReportActive;
    [renderer shouldUseFrameInterpolationForDisplayRefreshRate:refreshRate
                                                        report:&report
                                                        reason:&reason];
    GateAnswer answer = { reason, report };
    return answer;
}

static const char *KeyShort(NSString *key) {
    const char *tail = strstr([key UTF8String], "Runtime Detail ");
    return tail ? tail + strlen("Runtime Detail ") : [key UTF8String];
}

int main(void) {
    @autoreleasepool {
        NSString *const off = @"Video Frame Interpolation Runtime Detail Off";
        const int enhanced = MLActiveVideoRendererModeEnhanced;
        const int lowLatency = MLRequestedVideoFrameInterpolationModeVTLowLatency;
        GateAnswer answer;

        answer = GateRefusal(MLRequestedVideoFrameInterpolationModeOff, enhanced,
                             NO, 60, 144.0);
        Report("requested off", MLActiveVideoFrameInterpolationEngineNone, answer.report,
               answer.reason, @"Off", off);
        answer = GateRefusal(lowLatency, MLActiveVideoRendererModeNative, NO, 60, 144.0);
        Report("no Metal renderer", MLActiveVideoFrameInterpolationEngineNone, answer.report,
               answer.reason, @"Off",
               @"Video Frame Interpolation Runtime Detail Requires Metal Renderer");
        answer = GateRefusal(lowLatency, enhanced, YES, 60, 144.0);
        Report("HDR stream", MLActiveVideoFrameInterpolationEngineNone, answer.report,
               answer.reason, @"Off",
               @"Video Frame Interpolation Runtime Detail Disabled For Hdr");
        answer = GateRefusal(lowLatency, enhanced, NO, 60, 0.0);
        Report("refresh unknown", MLActiveVideoFrameInterpolationEngineNone, answer.report,
               answer.reason, @"Off",
               @"Video Frame Interpolation Runtime Detail Refresh Rate Unknown");
        answer = GateRefusal(lowLatency, enhanced, NO, 120, 144.0);
        Report("no cadence", MLActiveVideoFrameInterpolationEngineNone, answer.report,
               answer.reason, @"Off",
               @"Video Frame Interpolation Runtime Detail No Cadence Headroom");
        Report("runtime failure", MLActiveVideoFrameInterpolationEngineNone,
               kRuntimeFailureReport, kRuntimeFailureReason, @"Off",
               @"Video Frame Interpolation Runtime Detail Fallback");
        Report("warming up", MLActiveVideoFrameInterpolationEngineNone, kWarmupReport,
               kWarmupReason, @"Off",
               @"Video Frame Interpolation Runtime Detail Warmup");
        Report("first frame", MLActiveVideoFrameInterpolationEngineNone, kWaitingReport,
               kWaitingReason, @"Off", off);
        Report("no hardware", MLActiveVideoFrameInterpolationEngineNone,
               MLVideoFrameInterpolationReportForSlotVerdict(
                   MLInterpolationSlotVerdictNoHardware),
               @(MLInterpolationSlotReason(MLInterpolationSlotVerdictNoHardware)),
               @"Off", @"Video Frame Interpolation Runtime Detail No Interpolation Slots");
        Report("above ceiling", MLActiveVideoFrameInterpolationEngineNone,
               MLVideoFrameInterpolationReportForSlotVerdict(
                   MLInterpolationSlotVerdictStreamAboveCeiling),
               @(MLInterpolationSlotReason(MLInterpolationSlotVerdictStreamAboveCeiling)),
               @"Off", @"Video Frame Interpolation Runtime Detail Above Interpolation Ceiling");
        Report("interpolating", MLActiveVideoFrameInterpolationEngineVTLowLatency,
               kWorkingReport, [NSString stringWithFormat:kWorkingFormat, 144.0, 60],
               @"VT Low-Latency Frame Interpolation",
               @"Video Frame Interpolation Runtime Detail Active");

        printf("%s %lu states of the frame interpolation report checked, %lu failed\n",
               gFailed ? "FAIL" : "ok", (unsigned long)gChecked, (unsigned long)gFailed);
        printf("   coverage: %lu keys returned of %lu wanted",
               (unsigned long)gKeyCount, (unsigned long)gWantCount);
        NSUInteger distinctWant = 0;
        for (NSUInteger index = 0; index < gWantCount; index++) {
            if (!gKeyHits[KeySlot(gWantKeys[index])]) {
                printf("\nFAIL no state reported %s, so that wording is unreachable",
                       KeyShort(gWantKeys[index]));
                gFailed++;
            }
            BOOL seenBefore = NO;
            for (NSUInteger earlier = 0; earlier < index; earlier++) {
                if ([gWantKeys[earlier] isEqualToString:gWantKeys[index]]) {
                    seenBefore = YES;
                }
            }
            if (!seenBefore) {
                distinctWant++;
            }
        }
        printf("\n");
        // Two states a player has to tell apart must not answer alike. Counting the
        // answers is what catches a collapse, and a collapse is the failure this file
        // exists for -- twice over, in opposite directions.
        if (gKeyCount != distinctWant) {
            printf("FAIL the report answers %lu ways where the player needs %lu\n",
                   (unsigned long)gKeyCount, (unsigned long)distinctWant);
            gFailed++;
        }
        return gFailed ? 1 : 0;
    }
}
"""


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def balanced(text, start, where):
    body = text.find("{", start)
    if body < 0:
        raise SystemExit("no opening brace for %s" % where)
    depth = 0
    for index in range(body, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    raise SystemExit("unbalanced braces reading %s" % where)


def method(text, signature):
    start = text.find(signature)
    if start < 0:
        raise SystemExit("the shipping source no longer contains %s" % signature)
    return balanced(text, start, signature)


def function(text, signature):
    return method(text, signature)


def enum_block(text, marker):
    start = text.find(marker)
    if start < 0:
        raise SystemExit("the shipping source no longer contains %r" % marker)
    end = text.find("};", start)
    if end < 0:
        raise SystemExit("unterminated enum at %r" % marker)
    return text[start:end + 2]


LITERAL = re.compile(r'@"(?:[^"\\]|\\.)*"')
# The state a call site names, read from beside the text it passes: which sentence a
# player gets depends on both halves of the call, and a probe that typed the state out
# itself would be checking its own transcription.
REPORT_LABEL = re.compile(r"report:(MLVideoFrameInterpolationReport[A-Za-z]*)")
# The two runtime readings are one branch answering twice -- the sentence and the
# state, from the same flag -- so their labels sit in a ternary rather than beside a
# reason. Position is the meaning here: the question arm is the warm-up answer, the
# colon arm is the failure, exactly as in the text ternary above it.
RUNNING = r"(MLVideoFrameInterpolationReport[A-Za-z]*)"
REPORT_TERNARY = re.compile(r"MLVideoFrameInterpolationReport\s+\w*[Rr]eport\s*="
                        r"\s*\w+\s*\?\s*" + RUNNING + r"\s*:\s*" + RUNNING)


def literal_after(text, start, where):
    """The next Objective-C string literal at or after start, with where it ended.

    The end has to come back: the next literal is searched for from there, and an
    offset rebuilt from the mark plus the literal's length can land inside the literal
    it is standing on, which hands back the same text twice.
    """
    found = LITERAL.search(text, start)
    if not found:
        raise SystemExit("no string literal after %s" % where)
    return found.group(0), found.end()


def lifted_literals(source):
    """The reason texts and the states named beside them, taken from the file.

    Both halves travel together on purpose. Which sentence a player reads depends on the
    state a call site names and the text it passes to the log, and a probe that typed
    either one out itself would be checking its own transcription.
    """
    staging = method(source, STAGING)
    warmup_at = staging.find(WARMUP_MARK)
    if warmup_at < 0:
        raise SystemExit("the staging method no longer mentions %s" % WARMUP_MARK)
    warmup, warmup_end = literal_after(staging, warmup_at, WARMUP_MARK)
    runtime, _ = literal_after(staging, warmup_end, "the runtime refusal")
    working, _ = literal_after(staging, staging.find(FORMAT_MARK), "the working report")
    waiting_matches = re.findall(WAITING_SHAPE, source)
    if len(waiting_matches) != 1:
        raise SystemExit("the transient report was found %d times, expected exactly 1"
                         % len(waiting_matches))
    waiting = waiting_matches[0]
    texts = {"kWarmupReason": warmup, "kRuntimeFailureReason": runtime,
             "kWorkingFormat": working, "kWaitingReason": waiting}
    ternary = REPORT_TERNARY.findall(staging)
    if len(ternary) != 1:
        raise SystemExit("the runtime branch names %d report pairs, expected exactly 1"
                         % len(ternary))
    warmup_report, runtime_report = ternary[0]
    labels = {"kWarmupReport": warmup_report, "kRuntimeFailureReport": runtime_report,
              "kWorkingReport": label_of(staging, working, "kWorkingFormat"),
              "kWaitingReport": label_of(source, waiting, "kWaitingReason")}
    return texts, labels


def label_of(text, literal, where):
    """The state named in the call that passes this text."""
    at = text.find(literal)
    if at < 0:
        raise SystemExit("%s is not in the source it was lifted from" % where)
    window = text[max(0, at - 300):at + len(literal) + 300]
    found = REPORT_LABEL.search(window)
    if not found:
        raise SystemExit("no report named beside %s, so the state would be guessed again"
                         % where)
    return found.group(1)


WANT_KEYS = (
    "Video Frame Interpolation Runtime Detail Off",
    "Video Frame Interpolation Runtime Detail Requires Metal Renderer",
    "Video Frame Interpolation Runtime Detail Disabled For Hdr",
    "Video Frame Interpolation Runtime Detail Refresh Rate Unknown",
    "Video Frame Interpolation Runtime Detail No Cadence Headroom",
    "Video Frame Interpolation Runtime Detail Fallback",
    "Video Frame Interpolation Runtime Detail Warmup",
    "Video Frame Interpolation Runtime Detail No Interpolation Slots",
    "Video Frame Interpolation Runtime Detail Above Interpolation Ceiling",
    "Video Frame Interpolation Runtime Detail Active",
)


def build(source, known_bad=None):
    if known_bad:
        name, anchor, replacement, _why = known_bad
        if source.count(anchor) != 1:
            raise SystemExit("the anchor for %s is not there exactly once (%d times)"
                             % (name, source.count(anchor)))
        source = source.replace(anchor, replacement, 1)
    texts, labels = lifted_literals(source)
    driver = DRIVER.replace("WANT_KEYS_PLACEHOLDER",
                            "\n".join('    @"%s",' % key for key in WANT_KEYS))
    for name, value in tuple(texts.items()) + tuple(labels.items()):
        driver = driver.replace(name + "_PLACEHOLDER", value)
    leftovers = re.findall(r"([A-Za-z]+_PLACEHOLDER)", driver)
    if leftovers:
        raise SystemExit("the probe still has %s unwritten" % ", ".join(sorted(set(leftovers))))
    return (HEAD + "\n"
            + "\n".join(enum_block(source, marker) for marker in ENUMS) + "\n"
            + function(source, ENGINE_NAME) + "\n"
            + function(source, SLOT_REASON) + "\n"
            + function(source, REPORT_FOR_VERDICT) + "\n"
            + CLASS_HEAD + "\n"
            + method(source, GATE) + "\n"
            + method(source, DISPATCHER) + "\n"
            + CLASS_TAIL + "\n" + driver)


def run(command, work):
    result = subprocess.run(command, capture_output=True, text=True, cwd=work)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stdout.write(result.stderr[-4000:])
    sys.stdout.flush()
    return result.returncode


def compile_and_run(source_path, binary, clang, sdk, work):
    if run([clang, "-fobjc-arc", "-isysroot", sdk, "-framework", "Foundation",
            "-o", binary, source_path], work) != 0:
        return 2
    return run([binary], work)


KNOWN_BAD = [
    ("the-working-report-answers-the-refusal",
     '        case MLVideoFrameInterpolationReportActive:\n'
     '            return @"Video Frame Interpolation Runtime Detail Active";',
     '        case MLVideoFrameInterpolationReportActive:\n'
     '            return @"Video Frame Interpolation Runtime Detail No Cadence Headroom";',
     "interpolation that is running is described by the sentence that says it refused"),
    ("a-runtime-failure-says-nobody-asked",
     '        case MLVideoFrameInterpolationReportRuntimeUnavailable:\n'
     '            return @"Video Frame Interpolation Runtime Detail Fallback";',
     '        case MLVideoFrameInterpolationReportRuntimeUnavailable:\n'
     '            return @"Video Frame Interpolation Runtime Detail Off";',
     "a player who enabled the feature is told no stream asked for it"),
    ("the-frame-never-stops-warming-up",
     "                                     report:MLVideoFrameInterpolationReportActive",
     "                                     report:MLVideoFrameInterpolationReportWarmup",
     "the state that names the report is left behind, so a landed frame still reads as "
     "a pending one"),
    ("two-refusals-share-one-sentence",
     "            *reportOut = MLVideoFrameInterpolationReportNoCadenceHeadroom;",
     "            *reportOut = MLVideoFrameInterpolationReportRefreshRateUnknown;",
     "a display with no headroom is reported as a display with no refresh rate, which is "
     "advice pointing at the wrong knob"),
]


def main():
    source = read(RENDERER)
    print("-- what the settings page reports about frame interpolation --")
    try:
        clang, sdk = apple_toolchain.clang_and_sdk("frame interpolation status probe")
    except SystemExit as error:  # noqa: BLE001 - a host with no compiler is a skip
        print("%s" % error)
        return 0
    with tempfile.TemporaryDirectory() as work:
        failures = 0
        clean = os.path.join(work, "clean.m")
        with open(clean, "w", encoding="utf-8") as handle:
            handle.write(build(source))
        if compile_and_run(clean, os.path.join(work, "clean"), clang, sdk, work) != 0:
            return 1
        for name, _anchor, replacement, why in KNOWN_BAD:
            print("\n-- known-bad: %s --" % why)
            bad = os.path.join(work, "bad.m")
            with open(bad, "w", encoding="utf-8") as handle:
                handle.write(build(source, (name, _anchor, replacement, why)))
            code = compile_and_run(bad, os.path.join(work, "bad"), clang, sdk, work)
            if code == 2:
                print("FAIL the %s probe does not compile" % name)
                failures = 1
            elif code == 0:
                print("FAIL the sweep passed a report known to mishandle %s" % name)
                failures = 1
        print("\n%d frame-interpolation-status failures" % failures)
        return failures


if __name__ == "__main__":
    sys.exit(main())
