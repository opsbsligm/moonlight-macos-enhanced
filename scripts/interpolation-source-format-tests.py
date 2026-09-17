#!/usr/bin/env python3
"""Prove a stream the interpolator cannot take is refused once, not once per frame.

A low-latency interpolation configuration accepts one source pixel format, and measured
on Apple silicon that format is 420v. The decoder here is asked for something else
whenever the stream is 10-bit or 4:4:4 -- ordinary settings, HEVC 10-bit being the
common default -- so the mismatch arrives on every decoded frame rather than never.

Refusing it per frame is not free. The shape this replaces fell through to a warmup
request, the warmup answered "a session for this size already exists" and did nothing,
the caller read that as a runtime failure, and tore the session down. The next frame
built another configuration, asked the hardware for its slots, allocated another frame
processor and started another session, and was refused at the same line: one hardware
video session destroyed and rebuilt per frame, a warning per frame, and a settings
status that alternated between two sentences so it never de-duplicated.

The method under test is the shipping one. Its body is lifted out of
VideoDecoderRenderer.m and run against a renderer whose output-pool step answers the
way the machine does, because what decides the outcome is a hardware fact: the probe
asks VideoToolbox which source formats the configuration actually takes and hands each
of the formats the decoder is asked to produce through the shipping method. A stream in
an unacceptable format has to be refused once and remembered; a stream in an acceptable
format must not be affected by that memory.
"""
import os, re, subprocess, sys, tempfile

NL = chr(10)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RENDERER = os.path.join(ROOT, "Limelight", "Stream", "VideoDecoderRenderer.m")
DECIDER = "MLFrameInterpolationPrepareActionForSource"
PREPARE = "- (BOOL)prepareFrameInterpolationProcessorForSourceFrame:"
KEY = "Video Frame Interpolation Runtime Detail Source Format Unsupported"

DRIVER = r"""
#import <Foundation/Foundation.h>
#import <CoreVideo/CoreVideo.h>
#import <VideoToolbox/VideoToolbox.h>

@@REPORT_ENUM@@
@@ACTION_ENUM@@
@@DECIDER@@

// Which source formats a running configuration takes, asked of VideoToolbox once,
// at startup, rather than written down here.
static NSArray<NSNumber *> *gSupportedFormats;

@interface FakeRenderer : NSObject {
@public
    id _frameInterpolationProcessor;
    id _frameInterpolationConfiguration;
    NSInteger _frameInterpolationInputWidth;
    NSInteger _frameInterpolationInputHeight;
    OSType _frameInterpolationSourcePixelFormat;
    OSType _frameInterpolationRefusedSourcePixelFormat;
}
@property(nonatomic) unsigned long ensureCalls;
@property(nonatomic) unsigned long warmupCalls;
@end

@implementation FakeRenderer
// The shipping output-pool step refuses a format the running configuration does not
// take and accepts one it does. Those are the two answers below, and the list comes
// from the hardware rather than from this file.
- (BOOL)ensureFrameInterpolationOutputPoolForConfiguration:(VTLowLatencyFrameInterpolationConfiguration *)configuration
                                         sourcePixelFormat:(OSType)pixelFormat {
    self.ensureCalls++;
    BOOL supported = (gSupportedFormats == NULL);
    for (NSNumber *value in gSupportedFormats) {
        if ((OSType)value.unsignedIntValue == pixelFormat) {
            supported = YES;
        }
    }
    if (supported) {
        _frameInterpolationSourcePixelFormat = pixelFormat;
    }
    return supported;
}

- (void)requestFrameInterpolationWarmupForStreamWidth:(NSInteger)streamWidth
                                         streamHeight:(NSInteger)streamHeight {
    self.warmupCalls++;
}

@@PREPARE@@
@end

static void reset(FakeRenderer *renderer) {
    renderer.ensureCalls = 0;
    renderer.warmupCalls = 0;
}

static void run(const char *name, OSType format, int frames, int expectReady) {
    FakeRenderer *renderer = [[FakeRenderer alloc] init];
    // A session for this size already exists and no format has been agreed for it yet,
    // which is the state every decoded frame arrives in.
    renderer->_frameInterpolationProcessor = [NSObject new];
    renderer->_frameInterpolationInputWidth = 1920;
    renderer->_frameInterpolationInputHeight = 1080;
    renderer->_frameInterpolationSourcePixelFormat = 0;
    renderer->_frameInterpolationRefusedSourcePixelFormat = 0;

    CVPixelBufferRef buffer = NULL;
    NSDictionary *attributes = @{ (__bridge NSString *)kCVPixelBufferWidthKey: @1920,
                                  (__bridge NSString *)kCVPixelBufferHeightKey: @1080 };
    CVReturn created = CVPixelBufferCreate(kCFAllocatorDefault, 1920, 1080, format,
                                           (__bridge CFDictionaryRef)attributes, &buffer);
    if (created != kCVReturnSuccess || buffer == NULL) {
        printf("scenario %s skipped\n", name);
        return;
    }
    int ready = 0;
    long report = -1;
    for (int frame = 0; frame < frames; frame++) {
        MLVideoFrameInterpolationReport value = MLVideoFrameInterpolationReportDisabled;
        if ([renderer prepareFrameInterpolationProcessorForSourceFrame:buffer report:&value]) {
            ready++;
        }
        report = (long)value;
    }
    printf("scenario %s ready=%d ensure=%lu warmups=%lu report=%ld want=%d\n",
           name, ready, renderer.ensureCalls, renderer.warmupCalls, report, expectReady);
    CVBufferRelease(buffer);
}

static void run_after_refusal(OSType refused, OSType accepted, int frames) {
    FakeRenderer *renderer = [[FakeRenderer alloc] init];
    renderer->_frameInterpolationProcessor = [NSObject new];
    renderer->_frameInterpolationInputWidth = 1920;
    renderer->_frameInterpolationInputHeight = 1080;
    CVPixelBufferRef bad = NULL;
    CVPixelBufferRef good = NULL;
    NSDictionary *attributes = @{ (__bridge NSString *)kCVPixelBufferWidthKey: @1920,
                                  (__bridge NSString *)kCVPixelBufferHeightKey: @1080 };
    if (CVPixelBufferCreate(kCFAllocatorDefault, 1920, 1080, refused,
                            (__bridge CFDictionaryRef)attributes, &bad) != kCVReturnSuccess ||
        CVPixelBufferCreate(kCFAllocatorDefault, 1920, 1080, accepted,
                            (__bridge CFDictionaryRef)attributes, &good) != kCVReturnSuccess) {
        printf("scenario after-refusal skipped\n");
        return;
    }
    int refusedFrames = 0;
    int acceptedFrames = 0;
    for (int frame = 0; frame < frames; frame++) {
        MLVideoFrameInterpolationReport value = MLVideoFrameInterpolationReportDisabled;
        if (![renderer prepareFrameInterpolationProcessorForSourceFrame:bad report:&value]) {
            refusedFrames++;
        }
    }
    reset(renderer);
    for (int frame = 0; frame < frames; frame++) {
        MLVideoFrameInterpolationReport value = MLVideoFrameInterpolationReportDisabled;
        if ([renderer prepareFrameInterpolationProcessorForSourceFrame:good report:&value]) {
            acceptedFrames++;
        }
    }
    printf("scenario after-refusal refused=%d accepted=%d ensure=%lu warmups=%lu\n",
           refusedFrames, acceptedFrames, renderer.ensureCalls, renderer.warmupCalls);
    CVBufferRelease(bad);
    CVBufferRelease(good);
}

int main(void) {
    @autoreleasepool {
        if (@available(macOS 26.0, *)) {
            VTLowLatencyFrameInterpolationConfiguration *configuration =
                [[VTLowLatencyFrameInterpolationConfiguration alloc]
                    initWithFrameWidth:1920 frameHeight:1080 numberOfInterpolatedFrames:1];
            gSupportedFormats = configuration.frameSupportedPixelFormats;
            printf("hardware supported formats=%lu", (unsigned long)gSupportedFormats.count);
            char fourcc[5] = {0};
            for (NSNumber *value in gSupportedFormats) {
                OSType format = (OSType)value.unsignedIntValue;
                fourcc[0] = (char)((format >> 24) & 0xFF);
                fourcc[1] = (char)((format >> 16) & 0xFF);
                fourcc[2] = (char)((format >> 8) & 0xFF);
                fourcc[3] = (char)(format & 0xFF);
                printf(" %s", fourcc);
            }
            printf("\n");
        } else {
            printf("hardware unavailable before macOS 26\n");
        }

        run("eight-bit-420", '420v', 60, 60);
        run("ten-bit-420", 'p010', 60, 0);
        run("eight-bit-444", '444v', 60, 0);
        run("ten-bit-444", 'p210', 60, 0);
        run_after_refusal('444v', '420v', 30);
    }
    return 0;
}
"""


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def brace_span(text, start):
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
    raise AssertionError("unbalanced braces in " + text[start:start + 60])


def enum_block(source, marker):
    at = source.index(marker)
    return brace_span(source, at) + ";"


def inline_function(source, name):
    match = re.search("^static inline [^(]*" + name, source, re.M)
    assert match, "no inline definition of " + name
    return brace_span(source, match.start())


def definition_span(text, signature):
    """The body of the first definition, skipping the declaration written beside it.

    A method header appears twice in this file: once the compiler is told about, once
    as the thing that runs. Whichever terminator arrives first tells them apart, and
    reading the declaration instead would let a change to the code hide behind a line
    that only announces it.
    """
    for match in re.finditer(re.escape(signature), text):
        semicolon = text.find(";", match.start())
        brace = text.find("{", match.start())
        if 0 <= brace < semicolon:
            return brace_span(text, match.start())
    raise AssertionError("no definition of " + signature)


def method(source, marker):
    return definition_span(source, marker)


def build(source, decider=None, prepare=None):
    return (DRIVER.replace("@@REPORT_ENUM@@",
                           enum_block(source, "typedef NS_ENUM(NSInteger, MLVideoFrameInterpolationReport)"))
                  .replace("@@ACTION_ENUM@@",
                           enum_block(source, "typedef NS_ENUM(NSInteger, MLFrameInterpolationPrepareAction)"))
                  .replace("@@DECIDER@@", inline_function(source, DECIDER) if decider is None else decider)
                  .replace("@@PREPARE@@", method(source, PREPARE) if prepare is None else prepare))


def compiled(source, work, name, clang, sdk):
    path = os.path.join(work, name + ".m")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    command = [clang, "-fobjc-arc", "-isysroot", sdk, "-mmacosx-version-min=26.0",
               "-framework", "Foundation", "-framework", "CoreVideo",
               "-framework", "VideoToolbox", path, "-o", os.path.join(work, name)]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr).strip()[-1800:]
    ran = subprocess.run([os.path.join(work, name)], capture_output=True, text=True)
    return ran.stdout, (ran.stdout + ran.stderr).strip()[-1800:]


def reading(stdout):
    rows = {}
    for line in stdout.splitlines():
        fields = line.split()
        if fields[:1] == ["scenario"] and "skipped" not in fields:
            rows[fields[1]] = dict(pair.split("=") for pair in fields[2:])
    return rows


failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def main():
    source = read(RENDERER)
    print("-- what a stream the interpolator cannot take costs --")

    # --- the shipped facts the decision is about ------------------------------
    asked = re.findall(r"@[\(]kCVPixelFormatType_[A-Za-z0-9]+[\)]", source)
    check(len(set(asked)) >= 4,
          "the decoder is asked for %d distinct pixel formats, so more than one reaches "
          "the interpolator" % len(set(asked)))

    teardown = definition_span(source, "- (void)teardownFrameInterpolationProcessor")
    check("_frameInterpolationRefusedSourcePixelFormat = 0;" in teardown,
          "a torn-down session forgets the refusal, so the next stream is asked again")

    en = read(os.path.join(ROOT, "Limelight", "macOS", "en.lproj", "Localizable.strings"))
    zh = read(os.path.join(ROOT, "Limelight", "macOS", "zh-Hans.lproj", "Localizable.strings"))
    check('"' + KEY + '"' in en and '"' + KEY + '"' in zh,
          "the refusal has wording in both languages")

    # --- run the shipping prepare method -------------------------------------
    try:
        clang, sdk = apple_toolchain.clang_and_sdk("interpolation source format probe")
    except SystemExit as error:  # noqa: BLE001 - a host with no compiler is a skip
        print("%s" % error)
        return 0

    with tempfile.TemporaryDirectory() as work:
        out, log = compiled(build(source), work, "clean", clang, sdk)
        check(out is not None,
              "the shipping prepare method compiles" if out is not None
              else "the shipping prepare method must compile:" + log)
        if out is None:
            return finish()
    print(NL.join(out.splitlines()))

    seen = reading(out)
    # What the host can build decides how much is covered, and the probe says so out
    # loud rather than letting a thin host read as a clean one: a format CoreVideo
    # will not hand out here is reported as skipped, and the sweep still has to see a
    # format accepted and a format refused to count as having run at all.
    required = (("eight-bit-420", 60), ("eight-bit-444", 0))
    optional = (("ten-bit-420", 0), ("ten-bit-444", 0))
    ran = 0
    refused = 0
    for name, want_ready in required + optional:
        row = seen.get(name)
        if row is None:
            if name in dict(optional):
                print("     %s skipped: this host will not hand out that buffer" % name)
                continue
            check(False, "scenario %s produced nothing" % name)
            continue
        ran += 1
        if want_ready == 0:
            refused += 1
        check(int(row["ready"]) == want_ready,
              "60 frames decoded as %s prepare %d of them" % (name, want_ready))
        check(int(row["ensure"]) <= 1 and int(row["warmups"]) == 0,
              "%s is settled once (pool steps %s, warmups %s over 60 frames)"
              % (name, row["ensure"], row["warmups"]))
    check(ran >= 2 and refused >= 1,
          "the probe saw %d formats, %d of them refused" % (ran, refused))

    after = seen.get("after-refusal")
    if after is None:
        print("     after-refusal skipped: this host will not hand out those buffers")
    else:
        check(int(after["refused"]) == 30 and int(after["accepted"]) == 30
              and int(after["ensure"]) <= 1,
              "a refused format is remembered and the next format still runs unchanged "
              "(refused %s, accepted %s, pool steps %s)"
              % (after["refused"], after["accepted"], after["ensure"]))

    # --- the assertions have to be the thing that fails ----------------------
    decider = inline_function(source, DECIDER)
    prepare = method(source, PREPARE)

    forgetful = decider.replace(
        "    if (refusedSourceFormat != 0 && incomingSourceFormat == refusedSourceFormat) {",
        "    if (refusedSourceFormat != 0 && incomingSourceFormat == refusedSourceFormat"
        " && rememberedSourceFormat == refusedSourceFormat) {")
    check(forgetful != decider,
          "the mutation that forgets the refusal has to be a real edit")
    blind = decider.replace("if (refusedSourceFormat != 0 && incomingSourceFormat == refusedSourceFormat) {",
                            "if (refusedSourceFormat != 0) {")
    check(blind != decider,
          "the mutation that refuses every format once one is refused has to be a real edit")
    silent = prepare.replace(
        "                _frameInterpolationRefusedSourcePixelFormat = sourcePixelFormat;", "")
    check(silent != prepare,
          "the mutation that never records the refusal has to be a real edit")

    for label, mutated_decider, mutated_prepare in (
            ("refuses the format once and then forgets", forgetful, None),
            ("refuses every format the moment one was refused", blind, None),
            ("refuses without remembering", None, silent)):
        with tempfile.TemporaryDirectory() as work:
            planted = build(source, decider=mutated_decider, prepare=mutated_prepare)
            rows, log = compiled(planted, work, "bad", clang, sdk)
            check(rows is not None,
                  "the mutation that %s compiles" % label if rows is not None
                  else "the mutation that %s must compile:%s" % (label, log))
            if rows is None:
                continue
            bad = reading(rows)
            refused = bad.get("eight-bit-444", {})
            after = bad.get("after-refusal", {})
            if label == "refuses every format the moment one was refused":
                check(after.get("accepted") is not None
                      and int(after["accepted"]) < 30,
                      "the probe notices a 420v stream refused because 4:4:4 was "
                      "(accepted %s of 30)" % after.get("accepted"))
            else:
                check(int(refused.get("ensure", 1)) > 1 or int(refused.get("warmups", 0)) > 0,
                      "the probe notices %s: pool steps %s, warmups %s over 60 frames"
                      % (label, refused.get("ensure"), refused.get("warmups")))

    return finish()


def finish():
    print("%d interpolation-source-format failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
