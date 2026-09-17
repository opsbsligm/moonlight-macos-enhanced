#!/usr/bin/env python3
"""Prove the enhancement the player asked for is the enhancement that runs.

The question asked of this feature was "is it actually doing anything", and the code
already keeps the answer: the renderer stores an active engine beside the requested
mode, and a reason string beside that. What nothing did was look at them. The rules
over this file check that the capability probe asks the GPU and counts the slots it
offers -- worth having, and one step removed from the frame. A mode could resolve to
nothing on every machine, the log could stay silent about why, and every existing
assertion would still pass, because none of them reads the resolver.

So the resolver is lifted verbatim and swept. Seven requested modes, HDR on and off,
five source-and-window pairs, and the three capabilities switched every which way:
five hundred and sixty cases, plus four asked without the out-parameters they are
allowed to decline. Each is judged against a statement of the policy written
from the policy rather than from the code, so the harness fails when the two part
company and not merely when one of them changes. Two things are demanded on every
case: the engine, and a non-empty reason -- because "why did my hardware scaler not
engage" is asked in the log, and a silent resolver cannot answer it.

The scale each pair means is written out as a table rather than recomputed, and so is
whether the menu a stand-in publishes offers it. Recomputing either would make the
expectation a copy of the thing under test instead of a claim about it.

The shape that matters most is the explicit one. A player who picks VT low-latency
super resolution and has it should get that engine and not a quieter substitute; the
same reasoning says Auto has to reach for the hardware path when the hardware offers
it, rather than settling for the scaling it can always do.

The two VT menus deliberately disagree, because the real per-size and any-size APIs do
not: the fallback from quality to low-latency only shows up when they differ. The
low-latency menu is keyed on the frame it is asked about, which is the shape that API
has, so a resolver that asked about the window rather than the stream is handed an
empty menu and turns up in the sweep.

Coverage is counted and demanded, as it is elsewhere in this directory. The Video
Toolbox branches sit behind an availability check, so a host that compiled them away
would sweep every case without reaching one -- green, and knowing nothing. Every
engine the policy can name has to have been returned at least once.

Exit 0 only when the sweep passes, its coverage is real, and every planted shape fails.
"""
import os
import subprocess
import sys
import tempfile

import apple_toolchain

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RENDERER = os.path.join(ROOT, "Limelight", "Stream", "VideoDecoderRenderer.m")

REQUEST_ENUM = "typedef NS_ENUM(NSInteger, MLRequestedVideoEnhancementMode)"
ACTIVE_ENUM = "typedef NS_ENUM(NSInteger, MLActiveVideoEnhancementEngine)"
# The first line of each signature is all that is searched for. The shipping source
# wraps the rest of those parameter lists onto their own lines, and a constant that
# spelled them out would be a claim about whitespace rather than about the method.
SCALE_FACTOR = "- (float)requestedScaleFactorForSourceWidth:(NSUInteger)sourceWidth"
FLOAT_SUPPORTED = "- (BOOL)floatScaleFactor:(float)scaleFactor isSupportedByValues:"
RESOLVER = ("- (MLActiveVideoEnhancementEngine)resolveEnhancementEngineForSourceWidth:"
            "(NSUInteger)sourceWidth")

STUBS = r"""
#import <Foundation/Foundation.h>

// The scaler configurations are macOS 26 API. The stand-ins below answer whatever a
// case asks of them, which is the point: what is under test is the resolver's use of
// them, not what a machine of this generation happens to offer. The lifted text keeps
// the shipping spellings of both class names untouched; the defines above bind those
// names to the stand-ins below, so the probe cannot be answered by the real Video
// Toolbox while the machine it runs on happens to have it loaded. Without them the
// runtime reports a duplicate implementation and either class may answer.
#define VTLowLatencySuperResolutionScalerConfiguration MLProbeLowLatencyScalerConfiguration
#define VTSuperResolutionScalerConfiguration MLProbeQualityScalerConfiguration

static BOOL gLowLatencyConfigurationSupported;
static BOOL gQualityConfigurationSupported;
static NSArray<NSNumber *> *gLowLatencyMenu;
static NSArray<NSNumber *> *gQualityMenu;
static NSUInteger gStreamWidth;
static NSUInteger gStreamHeight;

@interface MLProbeLowLatencyScalerConfiguration : NSObject
+ (BOOL)isSupported;
+ (NSArray<NSNumber *> *)supportedScaleFactorsForFrameWidth:(NSInteger)width
                                                 frameHeight:(NSInteger)height;
@end

@implementation MLProbeLowLatencyScalerConfiguration
+ (BOOL)isSupported { return gLowLatencyConfigurationSupported; }
+ (NSArray<NSNumber *> *)supportedScaleFactorsForFrameWidth:(NSInteger)width
                                                frameHeight:(NSInteger)height {
    // Answer only for the frame the case says the stream is. Asking about anything
    // else -- the window, for instance -- gets an empty menu.
    if ((NSUInteger)width != gStreamWidth || (NSUInteger)height != gStreamHeight) {
        return @[];
    }
    return gLowLatencyMenu != nil ? gLowLatencyMenu : @[];
}
@end

@interface MLProbeQualityScalerConfiguration : NSObject
+ (BOOL)isSupported;
+ (NSArray<NSNumber *> *)supportedScaleFactors;
@end

@implementation MLProbeQualityScalerConfiguration
+ (BOOL)isSupported { return gQualityConfigurationSupported; }
+ (NSArray<NSNumber *> *)supportedScaleFactors {
    return gQualityMenu != nil ? gQualityMenu : @[];
}
@end

static BOOL gMetalFXSupported;
static BOOL MLMetalFXIsSupported(id device) {
    (void)device;
    return gMetalFXSupported;
}
"""

CLASS_HEAD = r"""
// The lifted methods reach for three instance variables by name. Properties of exactly
// those names synthesise ivars of exactly those names, so the text compiles as written
// and the case can set the mode it wants from the outside.
@interface MLVideoDecoderUnderTest : NSObject
@property (nonatomic) NSInteger requestedEnhancementMode;
@property (nonatomic) BOOL enableHdr;
@property (nonatomic, strong) id device;
@end

@implementation MLVideoDecoderUnderTest
"""

CLASS_TAIL = "@end\n"

DRIVER = r"""
static const int kModeCount = 7;
static NSInteger Mode(int index) {
    const NSInteger modes[kModeCount] = {
        MLRequestedVideoEnhancementModeOff,
        MLRequestedVideoEnhancementModeAuto,
        MLRequestedVideoEnhancementModeVTLowLatencySuperResolution,
        MLRequestedVideoEnhancementModeVTQualitySuperResolution,
        MLRequestedVideoEnhancementModeMetalFXQuality,
        MLRequestedVideoEnhancementModeMetalFXPerformance,
        MLRequestedVideoEnhancementModeBasicScaling,
    };
    return modes[index];
}

static NSString *ModeName(NSInteger mode) {
    switch (mode) {
        case MLRequestedVideoEnhancementModeOff: return @"off";
        case MLRequestedVideoEnhancementModeAuto: return @"auto";
        case MLRequestedVideoEnhancementModeVTLowLatencySuperResolution:
            return @"vt-low-latency";
        case MLRequestedVideoEnhancementModeVTQualitySuperResolution:
            return @"vt-quality";
        case MLRequestedVideoEnhancementModeMetalFXQuality: return @"metalfx-quality";
        case MLRequestedVideoEnhancementModeMetalFXPerformance:
            return @"metalfx-performance";
        default: return @"basic";
    }
}

static const int kEngineCount = 6;
static NSString *EngineName(MLActiveVideoEnhancementEngine engine) {
    switch (engine) {
        case MLActiveVideoEnhancementEngineNone: return @"none";
        case MLActiveVideoEnhancementEngineBasicScaling: return @"basic-scaling";
        case MLActiveVideoEnhancementEngineMetalFXQuality: return @"metalfx-quality";
        case MLActiveVideoEnhancementEngineMetalFXPerformance:
            return @"metalfx-performance";
        case MLActiveVideoEnhancementEngineVTLowLatencySuperResolution:
            return @"vt-low-latency";
        default: return @"vt-quality";
    }
}

// Five source and window pairs chosen to straddle the branches: an even frame, a
// fractional upscale, a doubling, a downscale, and a window whose aspect ratio does
// not match the stream, so there is no uniform scale for a scaler to be offered.
static const int kSizePairCount = 5;
static const NSUInteger kSourceWidth[kSizePairCount] = {1920, 1280, 1920, 1280, 1280};
static const NSUInteger kSourceHeight[kSizePairCount] = {1080, 720, 1080, 720, 720};
static const NSUInteger kTargetWidth[kSizePairCount] = {1920, 1920, 3840, 640, 2560};
static const NSUInteger kTargetHeight[kSizePairCount] = {1080, 1080, 2160, 360, 2160};

// The scale each pair means, written rather than recomputed, so the expectation is not
// the arithmetic of the code under test wearing a different name.
static const float kExpectedScale[kSizePairCount] = {1.0f, 1.5f, 2.0f, 0.5f, 0.0f};

// Whether the menu each stand-in publishes offers that scale. The two differ on
// purpose: the per-size API and the any-size API do not agree in the field, and the
// fallback from quality to low-latency only appears where they do not.
static const BOOL kLowLatencyMenuOffers[kSizePairCount] = {NO, YES, YES, NO, NO};
static const BOOL kQualityMenuOffers[kSizePairCount] = {NO, NO, YES, NO, NO};

// The policy, stated rather than copied: off stays off; HDR never goes through a
// post-processing scaler; a target that needs no upscale needs no scaler; and
// otherwise the engine asked for is the engine that runs when the machine offers it,
// falling back along a named path only when it does not.
static MLActiveVideoEnhancementEngine PolicyEngine(NSInteger mode, BOOL hdr, float scale,
                                                   BOOL vtLowLatency, BOOL vtQuality,
                                                   BOOL metalFX) {
    if (mode == MLRequestedVideoEnhancementModeOff) {
        return MLActiveVideoEnhancementEngineNone;
    }
    if (hdr) {
        return scale > 1.0f ? MLActiveVideoEnhancementEngineBasicScaling
                            : MLActiveVideoEnhancementEngineNone;
    }
    if (scale <= 1.0f && mode != MLRequestedVideoEnhancementModeBasicScaling) {
        return MLActiveVideoEnhancementEngineNone;
    }
    switch (mode) {
        case MLRequestedVideoEnhancementModeAuto:
            if (vtLowLatency) return MLActiveVideoEnhancementEngineVTLowLatencySuperResolution;
            if (metalFX) return MLActiveVideoEnhancementEngineMetalFXQuality;
            return MLActiveVideoEnhancementEngineBasicScaling;
        case MLRequestedVideoEnhancementModeVTLowLatencySuperResolution:
            if (vtLowLatency) return MLActiveVideoEnhancementEngineVTLowLatencySuperResolution;
            if (metalFX) return MLActiveVideoEnhancementEngineMetalFXQuality;
            return MLActiveVideoEnhancementEngineBasicScaling;
        case MLRequestedVideoEnhancementModeVTQualitySuperResolution:
            if (vtQuality) return MLActiveVideoEnhancementEngineVTQualitySuperResolution;
            if (vtLowLatency) return MLActiveVideoEnhancementEngineVTLowLatencySuperResolution;
            if (metalFX) return MLActiveVideoEnhancementEngineMetalFXQuality;
            return MLActiveVideoEnhancementEngineBasicScaling;
        case MLRequestedVideoEnhancementModeMetalFXQuality:
            return metalFX ? MLActiveVideoEnhancementEngineMetalFXQuality
                           : MLActiveVideoEnhancementEngineBasicScaling;
        case MLRequestedVideoEnhancementModeMetalFXPerformance:
            return metalFX ? MLActiveVideoEnhancementEngineMetalFXPerformance
                           : MLActiveVideoEnhancementEngineBasicScaling;
        case MLRequestedVideoEnhancementModeBasicScaling:
            return MLActiveVideoEnhancementEngineBasicScaling;
        default:
            return MLActiveVideoEnhancementEngineNone;
    }
}

static NSUInteger gChecked;
static NSUInteger gFailed;
static NSUInteger gShown;
static NSUInteger gEngineSeen[kEngineCount];

static void Check(NSInteger mode, BOOL hdr, int sizeIndex, BOOL lowLatencyCapable,
                  BOOL qualityCapable, BOOL metalFX, BOOL omitScale, BOOL omitReason,
                  NSString *caseName) {
    gChecked++;
    // The menus the two configurations will report, and the frame they are being asked
    // about. Quality offers a doubling and nothing else; low latency also offers one
    // and a half.
    gStreamWidth = kSourceWidth[sizeIndex];
    gStreamHeight = kSourceHeight[sizeIndex];
    gLowLatencyConfigurationSupported = lowLatencyCapable;
    gQualityConfigurationSupported = qualityCapable;
    gLowLatencyMenu = @[ @1.5f, @2.0f ];
    gQualityMenu = @[ @2.0f ];
    gMetalFXSupported = metalFX;

    MLVideoDecoderUnderTest *renderer = [[MLVideoDecoderUnderTest alloc] init];
    renderer.requestedEnhancementMode = mode;
    renderer.enableHdr = hdr;
    renderer.device = (id)@"under-test-device";

    float scale = -1.0f;
    NSString *reason = nil;
    const MLActiveVideoEnhancementEngine got =
        [renderer resolveEnhancementEngineForSourceWidth:kSourceWidth[sizeIndex]
                                            sourceHeight:kSourceHeight[sizeIndex]
                                             targetWidth:kTargetWidth[sizeIndex]
                                            targetHeight:kTargetHeight[sizeIndex]
                                            scaleFactor:(omitScale ? NULL : &scale)
                                                 reason:(omitReason ? NULL : &reason)];
    const float wantScale = kExpectedScale[sizeIndex];
    const BOOL vtLowLatency = lowLatencyCapable && kLowLatencyMenuOffers[sizeIndex];
    const BOOL vtQuality = qualityCapable && kQualityMenuOffers[sizeIndex];
    const MLActiveVideoEnhancementEngine want =
        PolicyEngine(mode, hdr, wantScale, vtLowLatency, vtQuality, metalFX);

    if (got >= 0 && got < kEngineCount) {
        gEngineSeen[got]++;
    }
    if (got != want) {
        gFailed++;
        if (gShown++ < 6) {
            printf("     case   %s\n", [caseName UTF8String]);
            printf("     policy runs %s, the renderer resolved %s\n",
                   [EngineName(want) UTF8String], [EngineName(got) UTF8String]);
        }
        return;
    }
    // The scale is what the decision was made from, and what a player reads back off
    // the window size. A resolver that answers with the right engine for a scale it
    // never measured has not answered anything.
    if (!omitScale && fabsf(scale - wantScale) > 0.001f) {
        gFailed++;
        if (gShown++ < 6) {
            printf("     case   %s\n", [caseName UTF8String]);
            printf("     measured %.3f where the pair means %.3f\n", scale, wantScale);
        }
        return;
    }
    // The reason is half of what the player needs when a scaler did not engage, and
    // it is the only half that survives into the log.
    if (!omitReason && reason.length == 0) {
        gFailed++;
        if (gShown++ < 6) {
            printf("     case   %s\n", [caseName UTF8String]);
            printf("     resolved %s and said nothing about why\n",
                   [EngineName(got) UTF8String]);
        }
    }
}

int main(void) {
    @autoreleasepool {
        for (int mode = 0; mode < kModeCount; mode++) {
            for (int hdr = 0; hdr < 2; hdr++) {
                for (int sizeIndex = 0; sizeIndex < kSizePairCount; sizeIndex++) {
                    for (int capabilities = 0; capabilities < 8; capabilities++) {
                        const BOOL lowLatency = (capabilities & 1) != 0;
                        const BOOL quality = (capabilities & 2) != 0;
                        const BOOL metalFX = (capabilities & 4) != 0;
                        NSString *name = [NSString stringWithFormat:
                            @"%@, HDR %@, %lux%lu into %lux%lu, VT-LL %@, VT-Q %@, MetalFX %@",
                            ModeName(Mode(mode)), hdr ? @"on" : @"off",
                            (unsigned long)kSourceWidth[sizeIndex],
                            (unsigned long)kSourceHeight[sizeIndex],
                            (unsigned long)kTargetWidth[sizeIndex],
                            (unsigned long)kTargetHeight[sizeIndex],
                            lowLatency ? @"yes" : @"no",
                            quality ? @"yes" : @"no",
                            metalFX ? @"yes" : @"no"];
                        Check(Mode(mode), hdr != 0, sizeIndex, lowLatency, quality, metalFX,
                              NO, NO, name);
                    }
                }
            }
        }
        // Callers are allowed to ask for less than the whole answer, and a resolution
        // that crashed on being asked would take the stream down with it. The engine
        // still has to be the one the policy names.
        for (int omission = 0; omission < 4; omission++) {
            const BOOL omitScale = (omission & 1) != 0;
            const BOOL omitReason = (omission & 2) != 0;
            NSString *name = [NSString stringWithFormat:
                @"%@ asked without the %@ and without the %@",
                @"auto, HDR off, 1920x1080 into 3840x2160",
                omitScale ? @"scale" : @"reason",
                omitReason ? @"scale" : @"reason"];
            Check(MLRequestedVideoEnhancementModeAuto, NO, 2, YES, YES, YES,
                  omitScale, omitReason, name);
        }
        printf("%s %lu resolutions of the requested enhancement checked, %lu failed\n",
               gFailed ? "FAIL" : "ok", (unsigned long)gChecked, (unsigned long)gFailed);
        printf("   coverage:");
        for (int engine = 0; engine < kEngineCount; engine++) {
            printf(" %s=%lu", [EngineName((MLActiveVideoEnhancementEngine)engine) UTF8String],
                   (unsigned long)gEngineSeen[engine]);
        }
        printf("\n");
        // Every engine the policy can name has to have been reached. The Video Toolbox
        // branches sit behind an availability check, and a host that compiled them away
        // would sweep every case and prove nothing at all.
        for (int engine = 0; engine < kEngineCount; engine++) {
            if (!gEngineSeen[engine]) {
                printf("FAIL the sweep never resolved %s, so it did not test what it claims\n",
                       [EngineName((MLActiveVideoEnhancementEngine)engine) UTF8String]);
                gFailed++;
            }
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


def enum_block(text, marker):
    start = text.find(marker)
    if start < 0:
        raise SystemExit("the shipping source no longer contains %r" % marker)
    # The enum ends at its closing brace and semicolon. Searching for a bare semicolon
    # would stop at the first one the macro's own argument list contains.
    end = text.find("};", start)
    if end < 0:
        raise SystemExit("unterminated enum at %r" % marker)
    return text[start:end + 2]


KNOWN_BAD = [
    ("auto-never-reaches-the-hardware-path",
     "case MLRequestedVideoEnhancementModeAuto:\n            if (vtLowLatencySupported) {",
     "case MLRequestedVideoEnhancementModeAuto:\n            if (NO) {",
     "Auto settles for what it can always do and never reaches the hardware scaler "
     "the machine is offering"),
    ("an-explicit-choice-is-quietly-replaced",
     "case MLRequestedVideoEnhancementModeVTLowLatencySuperResolution:\n"
     "            if (vtLowLatencySupported) {",
     "case MLRequestedVideoEnhancementModeVTLowLatencySuperResolution:\n            if (NO) {",
     "the engine the player picked is replaced by a quieter one on a machine that has it"),
    ("the-machine-was-asked-about-the-window-not-the-stream",
     "supportedScaleFactorsForFrameWidth:(NSInteger)sourceWidth",
     "supportedScaleFactorsForFrameWidth:(NSInteger)targetWidth",
     "the scaler menu is read for the window being drawn instead of the stream being "
         "scaled, so a machine that offers one is told it offers nothing"),
    ("the-resolver-answers-without-saying-why",
     '            *reasonOut = @"enhancement disabled";\n        }\n'
     '        return MLActiveVideoEnhancementEngineNone;\n    }\n\n    if (_enableHdr) {',
     '            *reasonOut = nil;\n        }\n'
     '        return MLActiveVideoEnhancementEngineNone;\n    }\n\n    if (_enableHdr) {',
     "a resolution leaves no reason, so the log cannot answer why the scaler did not engage"),
    ("every-case-resolves-to-nothing",
     "    if (_requestedEnhancementMode == MLRequestedVideoEnhancementModeOff) {",
     "    if (YES) {",
     "the renderer records an active engine that is never anything but none"),
]


def build(source, known_bad=None):
    if known_bad:
        name, anchor, replacement, _why = known_bad
        if source.count(anchor) != 1:
            raise SystemExit("the anchor for %s is not there exactly once (%d times)"
                             % (name, source.count(anchor)))
        source = source.replace(anchor, replacement, 1)
    # The enums have to precede the class that names them as a return type.
    return (STUBS + "\n"
            + enum_block(source, REQUEST_ENUM) + "\n"
            + enum_block(source, ACTIVE_ENUM) + "\n"
            + CLASS_HEAD + "\n"
            + method(source, SCALE_FACTOR) + "\n"
            + method(source, FLOAT_SUPPORTED) + "\n"
            + method(source, RESOLVER) + "\n"
            + CLASS_TAIL + "\n" + DRIVER)


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


def main():
    source = read(RENDERER)
    print("-- which engine actually runs the enhancement --")
    try:
        clang, sdk = apple_toolchain.clang_and_sdk("enhancement resolution probe")
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
                print("FAIL the sweep passed a resolver known to mishandle %s" % name)
                failures = 1
        print("\n%d enhancement-resolution failures" % failures)
        return failures


if __name__ == "__main__":
    sys.exit(main())
