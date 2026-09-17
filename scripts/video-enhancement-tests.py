#!/usr/bin/env python3
"""Verify the two video enhancement paths do what the interface claims they do.

Both features are object-creation APIs, so a build can compile, link and ship
while the feature never runs. Two failures were found this way on real hardware:

  * the renderer asked whether a MetalFX class merely exists. Class presence only
    proves the symbol linked; the descriptor's own supportsDevice: call is what
    reports whether this GPU can run a scaler.
  * VTLowLatencyFrameInterpolationConfiguration is created even on a GPU with no
    interpolation hardware, which then reports zero slots, while
    startSessionWithConfiguration:error: still returns success. Treating the
    session as the proof made the interface claim interpolation that produced no
    extra frame. On Apple M2 every size from 720p to 4K and both initialisers
    reported zero slots.

The probe below therefore measures the real thing: it scales a checkerboard and
counts interpolated edge pixels on the output, and it reads the slot count back
from the configuration instead of trusting the session. Source checks pin the
renderer to the same evidence, and the inverted copy of those checks proves the
assertions fire on the defect they describe.

Zero slots is also not one answer but two, and the same machine gives both.
`VTLowLatencyFrameInterpolationConfiguration` refuses an oversized request the
same way it refuses a GPU with no interpolation engine -- by reporting zero --
while publishing a ceiling of 1920 per side and 2073600 pixels for temporal
interpolation, measured on Apple M2. Reported as one sentence, a 1440p or 4K
stream on a Mac that *can* interpolate reads as a Mac that cannot, which is the
opposite of what the capability matrix on the settings page says about the same
machine. The classifier below is extracted from the renderer and compiled, so the
two answers are separated by a test and not by a guess.
"""
import os, re, subprocess, sys, tempfile, textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
SRC = "Limelight/Stream/VideoDecoderRenderer.m"
failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def method_body_at(src, brace):
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[brace:i + 1]
    raise AssertionError("unbalanced braces at offset %d" % brace)


def method_body(src, signature):
    """Body of a definition, never a forward declaration of the same selector."""
    brace = definition_brace(src, signature)
    return method_body_at(src, brace)


def definition_brace(src, signature):
    # A declaration ends in ';'; only a definition reaches '{' without a ';' first.
    for match in re.finditer(re.escape(signature), src):
        tail = src[match.end():]
        stop = re.search(r"[{;]", tail)
        if stop and stop.group(0) == "{":
            return match.end() + stop.start()
    raise AssertionError("no definition found for " + signature)


def warmup_body(text):
    return method_body(text, "- (void)requestFrameInterpolationWarmupForStreamWidth:")


def refusal_turn(text):
    """The refusal branch: from reading the slot count to building a processor."""
    body = warmup_body(text)
    start = body.index("if (configuration.numberOfInterpolatedFrames < 1)")
    end = body.index("VTFrameProcessor *processor", start)
    return body[start:end]


def report_enum_block(text):
    """The whole report enum typedef, so the model compiles the shipping states."""
    start = text.index(REPORT_ENUM)
    end = text.index("};", start)
    return text[start:end + 2]


def case_literal(body, case):
    """The @"..." a switch case returns, or None when the case is gone."""
    tail = case_tail(body, case)
    if tail is None:
        return None
    literal = re.search(r'@"([^"]*)"', tail)
    return literal.group(1) if literal else None


def case_return(body, case):
    """The value a switch case returns, as written, or None when the case is gone."""
    tail = case_tail(body, case)
    if tail is None:
        return None
    returned = re.search(r"return\s+([A-Za-z_][\w:]*)", tail)
    return returned.group(1) if returned else None


def case_tail(body, case):
    start = re.search(r"\bcase\s+" + re.escape(case) + r"\s*:", body)
    if not start:
        return None
    tail = body[start.end():]
    stop = re.search(r"\bcase\b|\bdefault\b", tail)
    return tail[:stop.start()] if stop else tail


INTERPOLATION_REGION_START = "typedef NS_ENUM(NSInteger, MLInterpolationSlotVerdict)"
INTERPOLATION_REGION_END = "static MLHDRTransferMode MLResolveHDRTransferMode"
REPORT_ENUM = "typedef NS_ENUM(NSInteger, MLVideoFrameInterpolationReport)"
DETAIL_MAPPER = ("- (NSString *)runtimeDetailKeyForFrameInterpolationReport:"
                 "(MLVideoFrameInterpolationReport)report")
REPORT_FOR_VERDICT = ("static MLVideoFrameInterpolationReport "
                      "MLVideoFrameInterpolationReportForSlotVerdict(")
DERIVED = "Limelight/macOS/ViewControllers/SettingsModel+DerivedValues.swift"


def interpolation_region(text):
    start = text.index(INTERPOLATION_REGION_START)
    end = text.index(INTERPOLATION_REGION_END, start)
    return text[start:end]


def probe_size(text):
    """The size the renderer re-asks the engine about, read from its own defines."""
    width = int(re.search(r"#define\s+ML_INTERPOLATION_PROBE_WIDTH\s+(\d+)", text).group(1))
    height = int(re.search(r"#define\s+ML_INTERPOLATION_PROBE_HEIGHT\s+(\d+)", text).group(1))
    return width, height


def matrix_sizes(text):
    """The sizes the settings matrix asks, straight out of the Swift source."""
    block = text[text.index("capabilityProbeSizes"):][:600]
    return [(int(w), int(h)) for w, h in re.findall(r"\(width:\s*(\d+),\s*height:\s*(\d+)\)", block)]


def defines(size):
    width, height = size
    return ("#define ML_INTERPOLATION_PROBE_WIDTH %d\n"
            "#define ML_INTERPOLATION_PROBE_HEIGHT %d\n" % (width, height))


def toolchain():
    """The compiler and SDK, as one matched pair. See scripts/apple_toolchain.py."""
    return apple_toolchain.clang_and_sdk("video enhancement probe")


PROBE = r"""
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#if __has_include(<MetalFX/MetalFX.h>)
#import <MetalFX/MetalFX.h>
#define HAVE_METALFX 1
#else
#define HAVE_METALFX 0
#endif
#import <objc/message.h>

static BOOL scaleRuns(BOOL *supportedOut) {
#if HAVE_METALFX
    if (@available(macOS 13.0, *)) {
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        if (device == nil) return NO;
        *supportedOut = [MTLFXSpatialScalerDescriptor supportsDevice:device];
        if (!*supportedOut) return NO;
        MTLFXSpatialScalerDescriptor *d = [[MTLFXSpatialScalerDescriptor alloc] init];
        d.inputWidth = 64; d.inputHeight = 64; d.outputWidth = 128; d.outputHeight = 128;
        d.colorTextureFormat = MTLPixelFormatBGRA8Unorm;
        d.outputTextureFormat = MTLPixelFormatBGRA8Unorm;
        id<MTLFXSpatialScaler> scaler = [d newSpatialScalerWithDevice:device];
        if (scaler == nil) return NO;
        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:
            MTLPixelFormatBGRA8Unorm width:64 height:64 mipmapped:NO];
        td.storageMode = MTLStorageModeShared; td.usage = scaler.colorTextureUsage;
        id<MTLTexture> src = [device newTextureWithDescriptor:td];
        NSUInteger bpr = 64 * 4;
        uint8_t *in = calloc(1, bpr * 64);
        for (NSUInteger y = 0; y < 64; y++)
            for (NSUInteger x = 0; x < 64; x++) {
                uint8_t v = (((x / 8) + (y / 8)) % 2) ? 255 : 0;
                uint8_t *p = in + y * bpr + x * 4; p[0] = p[1] = p[2] = v; p[3] = 255;
            }
        [src replaceRegion:MTLRegionMake2D(0, 0, 64, 64) mipmapLevel:0 withBytes:in bytesPerRow:bpr];
        MTLTextureDescriptor *od = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:
            MTLPixelFormatBGRA8Unorm width:128 height:128 mipmapped:NO];
        od.storageMode = MTLStorageModeShared; od.usage = scaler.outputTextureUsage;
        id<MTLTexture> dst = [device newTextureWithDescriptor:od];
        scaler.colorTexture = src; scaler.outputTexture = dst;
        scaler.inputContentWidth = 64; scaler.inputContentHeight = 64;
        id<MTLCommandBuffer> cb = [[device newCommandQueue] commandBuffer];
        [scaler encodeToCommandBuffer:cb]; [cb commit]; [cb waitUntilCompleted];
        if (cb.error != nil) { free(in); return NO; }
        uint8_t *out = calloc(1, 128 * 4 * 128);
        [dst getBytes:out bytesPerRow:128 * 4 fromRegion:MTLRegionMake2D(0, 0, 128, 128) mipmapLevel:0];
        NSUInteger blended = 0;
        for (NSUInteger i = 0; i < 128 * 128; i++) {
            uint8_t v = out[i * 4];
            if (v > 16 && v < 239) blended++;
        }
        free(in); free(out);
        printf("[metalfx] interpolated edge pixels=%lu\n", (unsigned long)blended);
        return blended > 0;
    }
#endif
    return NO;
}

// Does the scaler fill a window that is not the stream's shape?
//
// The renderer used to answer that window by asking for a uniform scale factor, not
// finding one, and reporting that no upscale was required -- while drawing the stream
// at twice its width and three times its height. The rule that replaced it rests on a
// claim about the hardware: that MetalFX is given an input size and an output size
// rather than a factor, so an anisotropic window is a window it can write. A claim
// about hardware belongs in front of the hardware, so the scaler is asked to resample
// a 64x64 ramp into 96x176 the same way the product asks -- with the colour-processing
// mode and content size left alone -- and the pixels that come back are measured.
//
// Both ramps have to reach the far edge. A scaler that kept the source's shape would
// stop short of it, and a scaler that cropped rather than stretched would not start at
// the near edge; either answer means the window cannot be handed to it as it is.
static BOOL nonUniformFills(void) {
#if HAVE_METALFX
    if (@available(macOS 13.0, *)) {
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        if (device == nil) return NO;
        if (![MTLFXSpatialScalerDescriptor supportsDevice:device]) return NO;
        MTLFXSpatialScalerDescriptor *d = [[MTLFXSpatialScalerDescriptor alloc] init];
        d.inputWidth = 64; d.inputHeight = 64; d.outputWidth = 96; d.outputHeight = 176;
        d.colorTextureFormat = MTLPixelFormatBGRA8Unorm;
        d.outputTextureFormat = MTLPixelFormatBGRA8Unorm;
        d.colorProcessingMode = MTLFXSpatialScalerColorProcessingModePerceptual;
        id<MTLFXSpatialScaler> scaler = [d newSpatialScalerWithDevice:device];
        if (scaler == nil) return NO;

        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:
            MTLPixelFormatBGRA8Unorm width:64 height:64 mipmapped:NO];
        td.storageMode = MTLStorageModeShared; td.usage = scaler.colorTextureUsage;
        id<MTLTexture> src = [device newTextureWithDescriptor:td];
        NSUInteger bpr = 64 * 4;
        uint8_t *in = calloc(1, bpr * 64);
        for (NSUInteger y = 0; y < 64; y++)
            for (NSUInteger x = 0; x < 64; x++) {
                uint8_t *p = in + y * bpr + x * 4;
                p[0] = (uint8_t)(x * 255 / 63);   // the ramp across the window
                p[2] = (uint8_t)(y * 255 / 63);   // and down it
                p[1] = 0; p[3] = 255;
            }
        [src replaceRegion:MTLRegionMake2D(0, 0, 64, 64) mipmapLevel:0 withBytes:in bytesPerRow:bpr];

        MTLTextureDescriptor *od = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:
            MTLPixelFormatBGRA8Unorm width:96 height:176 mipmapped:NO];
        od.storageMode = MTLStorageModeShared; od.usage = scaler.outputTextureUsage;
        id<MTLTexture> dst = [device newTextureWithDescriptor:od];
        scaler.colorTexture = src; scaler.outputTexture = dst;
        id<MTLCommandBuffer> cb = [[device newCommandQueue] commandBuffer];
        [scaler encodeToCommandBuffer:cb]; [cb commit]; [cb waitUntilCompleted];
        if (cb.error != nil) { free(in); return NO; }

        NSUInteger obpr = 96 * 4;
        uint8_t *out = calloc(1, obpr * 176);
        [dst getBytes:out bytesPerRow:obpr fromRegion:MTLRegionMake2D(0, 0, 96, 176) mipmapLevel:0];
        uint8_t nearX = out[(88 * obpr) + (0 * 4) + 0];               // first column, mid row
        uint8_t farX = out[(88 * obpr) + (95 * 4) + 0];           // last column, mid row
        uint8_t nearY = out[(0 * obpr) + (48 * 4) + 2];               // first row, mid column
        uint8_t farY = out[(175 * obpr) + (48 * 4) + 2];          // last row, mid column
        free(in); free(out);
        printf("[metalfx] nonuniform 64x64 into 96x176 nearX=%u farX=%u nearY=%u farY=%u\n",
               nearX, farX, nearY, farY);
        return farX >= 200 && farY >= 200 && nearX <= 40 && nearY <= 40;
    }
#endif
    return NO;
}

static void reportSupportAndFacts(Class cls, const char *label, NSInteger width, NSInteger height) {
    // The class answers two different questions, and only the second one is about
    // this GPU. Printing both keeps a runner from reading isSupported as proof:
    // measured on an Apple M2 the property is true while the slot count is zero
    // and the low latency scaler has no supported scale factor at 1080p.
    BOOL supported = ((BOOL (*)(id, SEL))objc_msgSend)(cls, @selector(isSupported));
    printf("[vt] %s isSupported=%d\n", label, supported);

    SEL sized = @selector(supportedScaleFactorsForFrameWidth:frameHeight:);
    if (sized != nil && [cls respondsToSelector:sized]) {
        id factors = ((id (*)(id, SEL, NSInteger, NSInteger))objc_msgSend)(cls, sized, width, height);
        printf("[vt] %s supportedScaleFactors %ldx%ld=%s\n", label,
               (long)width, (long)height,
               factors == nil ? "none" : [[factors description] UTF8String]);
    }

    SEL make = @selector(initWithFrameWidth:frameHeight:scaleFactor:);
    if (make != nil && [cls instancesRespondToSelector:make]) {
        id config = ((id (*)(id, SEL, NSInteger, NSInteger, float))objc_msgSend)(
            [cls alloc], make, width, height, (float)2.0);
        printf("[vt] %s 2x configuration created=%d\n", label, config != nil);
    }
}

static void probeInterpolation(void) {
    Class cfg = NSClassFromString(@"VTLowLatencyFrameInterpolationConfiguration");
    if (cfg == nil) { printf("[vt] configuration class unavailable\n"); return; }
    reportSupportAndFacts(NSClassFromString(@"VTLowLatencySuperResolutionScalerConfiguration"),
                          "lowLatencySuperResolution", 1280, 720);
    reportSupportAndFacts(NSClassFromString(@"VTLowLatencySuperResolutionScalerConfiguration"),
                          "lowLatencySuperResolution", 1920, 1080);
    SEL initSel = @selector(initWithFrameWidth:frameHeight:numberOfInterpolatedFrames:);
    if (![cfg instancesRespondToSelector:initSel]) { printf("[vt] initialiser unavailable\n"); return; }
    id obj = ((id (*)(id, SEL, NSInteger, NSInteger, NSInteger))objc_msgSend)(
        [cfg alloc], initSel, (NSInteger)1920, (NSInteger)1080, (NSInteger)1);
    if (obj == nil) { printf("[vt] configuration rejected\n"); return; }
    BOOL fiSupported = ((BOOL (*)(id, SEL))objc_msgSend)(cfg, @selector(isSupported));
    NSInteger slots = ((NSInteger (*)(id, SEL))objc_msgSend)(obj, @selector(numberOfInterpolatedFrames));
    printf("[vt] frameInterpolation isSupported=%d slots offered=%ld\n", fiSupported, (long)slots);
    printf("[vt] trust-isSupported would claim %s\n",
           (fiSupported && slots < 1) ? "interpolation the hardware cannot do" : "the truth");
    if (slots < 1) return;
    Class proc = NSClassFromString(@"VTFrameProcessor");
    if (proc == nil) { printf("[vt] processor class unavailable\n"); return; }
    id processor = ((id (*)(id, SEL))objc_msgSend)([proc alloc], @selector(init));
    typedef BOOL (*StartSessionFn)(id, SEL, id, __autoreleasing NSError **);
    __autoreleasing NSError *err = nil;
    StartSessionFn startSession = (StartSessionFn)objc_msgSend;
    BOOL started = startSession(processor, @selector(startSessionWithConfiguration:error:), obj, &err);
    printf("[vt] slots available and session started=%d%s\n", started,
           started ? "" : [[NSString stringWithFormat:@" error=%@", err.localizedDescription] UTF8String]);
    if (started) ((void (*)(id, SEL))objc_msgSend)(processor, @selector(endSession));
}

int main(void) {
    @autoreleasepool {
        BOOL supported = NO;
        BOOL scaled = scaleRuns(&supported);
        printf("METALFX_SUPPORT=%s\n", supported ? "yes" : "no");
        printf("METALFX_SCALING=%s\n", scaled ? "yes" : "no");
        BOOL anisotropic = NO;
        BOOL metalFXHere = NO;
#if HAVE_METALFX
        if (@available(macOS 13.0, *)) {
            id<MTLDevice> probeDevice = MTLCreateSystemDefaultDevice();
            metalFXHere = probeDevice != nil
                && [MTLFXSpatialScalerDescriptor supportsDevice:probeDevice];
        }
#endif
        if (metalFXHere) {
            anisotropic = nonUniformFills();
            printf("METALFX_NONUNIFORM=%s\n", anisotropic ? "yes" : "no");
        } else {
            printf("METALFX_NONUNIFORM=unavailable\n");
        }
        probeInterpolation();
        return 0;
    }
}
"""


# extracted from Limelight/Stream/VideoDecoderRenderer.m by this harness, compiled
# against the scenarios the renderer actually meets. @@REPORT_ENUM@@ is the
# report enum, @@DEFINES@@ is the two probe
# defines and @@REGION@@ the verdict region, both taken from the shipping file.
VERDICT_MODEL = r"""
#import <Foundation/Foundation.h>

@@REPORT_ENUM@@
@@DEFINES@@
@@REGION@@

static int gFailed = 0;

static void expect(const char *what, MLInterpolationSlotVerdict got,
                   MLInterpolationSlotVerdict want) {
    if (got != want) {
        gFailed += 1;
        printf("FAIL %s: got \"%s\", want \"%s\"\n", what,
               MLInterpolationSlotReason(got), MLInterpolationSlotReason(want));
    } else {
        printf("ok   %s -> %s\n", what, MLInterpolationSlotReason(got));
    }
}

int main(void) {
    /* Apple M2, measured: 1080p is inside the ceiling and still gets zero. */
    expect("1920x1080 stream, no slots at that size and none at the probe size",
           MLClassifyInterpolationSlots(1920, 1080, 0, 0),
           MLInterpolationSlotVerdictNoHardware);
    /* The same M2 at 4K: oversized, but the engine has no slots either way. */
    expect("3840x2160 stream, no slots at any size",
           MLClassifyInterpolationSlots(3840, 2160, 0, 0),
           MLInterpolationSlotVerdictNoHardware);
    /* A GPU with the engine, asked above its ceiling: the resolution is the story. */
    expect("3840x2160 stream, no slots there but slots at the probe size",
           MLClassifyInterpolationSlots(3840, 2160, 0, 1),
           MLInterpolationSlotVerdictStreamAboveCeiling);
    expect("2560x1440 stream, no slots there but slots at the probe size",
           MLClassifyInterpolationSlots(2560, 1440, 0, 1),
           MLInterpolationSlotVerdictStreamAboveCeiling);
    /* Slots at the stream size is the only answer that runs. */
    expect("1920x1080 stream with one slot",
           MLClassifyInterpolationSlots(1920, 1080, 1, 1),
           MLInterpolationSlotVerdictRuns);
    /* A stream at the probe size was never refused for size: re-asking proves nothing. */
    expect("probe-sized stream with no slots",
           MLClassifyInterpolationSlots(ML_INTERPOLATION_PROBE_WIDTH,
                                        ML_INTERPOLATION_PROBE_HEIGHT, 0, 0),
           MLInterpolationSlotVerdictNoHardware);
    expect("smaller-than-probe stream with no slots",
           MLClassifyInterpolationSlots(1024, 640, 0, 1),
           MLInterpolationSlotVerdictNoHardware);

    /* The two reasons have to stay tellable apart by the settings page. */
    NSString *hardware = @(MLInterpolationSlotReason(MLInterpolationSlotVerdictNoHardware));
    NSString *ceiling = @(MLInterpolationSlotReason(MLInterpolationSlotVerdictStreamAboveCeiling));
    if ([hardware containsString:@"above the interpolation ceiling"]) {
        gFailed += 1;
        printf("FAIL the hardware reason reads as a resolution problem\n");
    }
    if (![ceiling containsString:@"resolution"] || ![hardware containsString:@"no interpolation slots"]) {
        gFailed += 1;
        printf("FAIL a reason string lost the words the settings page routes on\n");
    }

    /* The settings page routes on the report enum now, so the compiled model has
     * to prove the two zero-slot verdicts still reach two different states. */
    MLVideoFrameInterpolationReport hardwareReport =
        MLVideoFrameInterpolationReportForSlotVerdict(MLInterpolationSlotVerdictNoHardware);
    MLVideoFrameInterpolationReport ceilingReport =
        MLVideoFrameInterpolationReportForSlotVerdict(MLInterpolationSlotVerdictStreamAboveCeiling);
    if (hardwareReport != MLVideoFrameInterpolationReportNoInterpolationSlots ||
        ceilingReport != MLVideoFrameInterpolationReportAboveInterpolationCeiling) {
        gFailed += 1;
        printf("FAIL the zero-slot verdicts report as %ld and %ld\n",
               (long)hardwareReport, (long)ceilingReport);
    } else {
        printf("ok   the two zero-slot verdicts report as two states\n");
    }

    printf("%s\n", gFailed ? "verdict scenarios failed" : "all verdict scenarios passed");
    return gFailed;
}
"""


def main():
    cc, sdk = toolchain()

    src = open(os.path.join(ROOT, SRC), encoding="utf-8").read()
    report_enum = report_enum_block(src)

    gate = method_body(src, "static BOOL MLMetalFXIsSupported(id<MTLDevice> device)")
    check("supportsDevice:" in gate,
          "the MetalFX decision asks the descriptor about this GPU, not just for the class")
    check("NSClassFromString" in gate,
          "the MetalFX decision still guards the weak-linked class")

    warmup = warmup_body(src)
    check("configuration.numberOfInterpolatedFrames < 1" in warmup,
          "interpolation is only adopted when the configuration offers slots")
    check("MLInterpolationSlotReason" in warmup,
          "a slot-less machine reports its own reason instead of appearing active")

    # The inverted renderer text must trip the two assertions above, otherwise
    # they would be reading whatever the file happens to say.
    inverted = src.replace("[MTLFXSpatialScalerDescriptor supportsDevice:device]", "YES /* inverted */")
    inverted = inverted.replace("configuration.numberOfInterpolatedFrames < 1", "NO /* inverted */")
    inverted_gate = method_body(inverted, "static BOOL MLMetalFXIsSupported(id<MTLDevice> device)")
    check("supportsDevice:" not in inverted_gate,
          "the MetalFX assertion fails on a class-presence-only decision")
    inverted_warmup = warmup_body(inverted)
    check("configuration.numberOfInterpolatedFrames < 1" not in inverted_warmup,
          "the slot assertion fails on a renderer that never reads the slot count")

    # --- a refusal must outlive the frame that received it ------------------
    # prepareFrameInterpolation asks for a processor on every decoded frame, so
    # a refusal that is not remembered turns into a new capability probe every
    # frame: two configurations and a queue hop per 16ms, plus a runtime reason
    # that alternates as the in-flight flag flips, which slips past the settings
    # page de-duplication and posts at display rate. Measured as reachable on
    # every Mac without the interpolation engine - Apple M2 included, where the
    # slot count is zero at all sizes.
    check("_frameInterpolationNoSlotWidth" in warmup and
          "streamWidth == _frameInterpolationNoSlotWidth" in warmup,
          "a size the engine refused is refused without asking the hardware again")
    refusal = refusal_turn(src)
    check("_frameInterpolationNoSlotWidth = streamWidth" in refusal,
          "the refusal is recorded where the slot count was read")
    check(refusal.index("_frameInterpolationWarmupInFlight = NO") <
          refusal.index("_frameInterpolationNoSlotWidth = streamWidth"),
          "the refusal is stored in the same turn that retires the request, so no "
          "reader can see a finished request it has not yet learned to refuse")

    # setupWithVideoFormat is where a new stream, size or setting arrives.
    setup = method_body(src, "- (void)setupWithVideoFormat:")
    check("_frameInterpolationNoSlotWidth = 0" in setup,
          "a new stream config re-opens the interpolation question")

    # The runtime failure path tears the processor down every frame it fails.
    # Forgetting the refusal there would put the per-frame probe back.
    teardown = method_body(src, "- (void)teardownFrameInterpolationProcessor")
    check("_frameInterpolationNoSlotWidth" not in teardown,
          "tearing down the processor keeps the refusal, because the runtime "
          "failure path tears down on every failing frame")

    forgotten = src.replace(
        "        if (streamWidth == _frameInterpolationNoSlotWidth &&\n"
        "            streamHeight == _frameInterpolationNoSlotHeight) {\n"
        "            return;\n"
        "        }", "        /* inverted: the refusal is forgotten */")
    inverted_refusal = warmup_body(forgotten)
    check("streamWidth == _frameInterpolationNoSlotWidth"
          not in inverted_refusal,
          "the remembering assertion fails on a renderer that re-asks every frame")

    # --- zero slots is two answers, and they must not be merged -------------
    verdict = interpolation_region(src)
    check("slotsAtProbeSize >= 1" in verdict,
          "the classifier distinguishes a GPU with no engine from a stream above its ceiling")
    check("no interpolation slots" in verdict and "above the interpolation ceiling" in verdict,
          "each verdict carries its own reason string")
    check("ML_INTERPOLATION_PROBE_WIDTH" in warmup and
          "initWithFrameWidth:ML_INTERPOLATION_PROBE_WIDTH" in warmup,
          "a refusal at the stream size is asked again at a size the engine can answer")
    check("MLClassifyInterpolationSlots" in warmup and "reason:slotReason" in warmup,
          "the warmup reports the verdict it classified rather than one fixed sentence")

    # The settings page line used to be picked by searching the reason text, and
    # the two zero-slot answers were ordered so the narrower one was asked first.
    # A report enum replaces that ordering with two states, so the guard is now
    # that each verdict still reaches its own line through the enum -- and that
    # nothing picks either answer by reading prose again.
    verdict_report = method_body(src, REPORT_FOR_VERDICT)
    ceiling_report = case_return(verdict_report, "MLInterpolationSlotVerdictStreamAboveCeiling")
    hardware_report = case_return(verdict_report, "MLInterpolationSlotVerdictNoHardware")
    mapper = method_body(src, DETAIL_MAPPER)
    ceiling_key = case_literal(mapper, "MLVideoFrameInterpolationReportAboveInterpolationCeiling")
    hardware_key = case_literal(mapper, "MLVideoFrameInterpolationReportNoInterpolationSlots")
    check(ceiling_key == "Video Frame Interpolation Runtime Detail Above Interpolation Ceiling"
          and hardware_key == "Video Frame Interpolation Runtime Detail No Interpolation Slots",
          "the resolution verdict has its own line on the settings page")
    check(ceiling_key is not None and hardware_key is not None
          and ceiling_key != hardware_key,
          "a stream above the ceiling does not read as a GPU with no engine")
    check("containsString:" not in mapper and "containsString:" not in verdict_report,
          "neither the settings line nor the verdict mapping is chosen by searching "
          "the reason text for a phrase")
    check(ceiling_report == "MLVideoFrameInterpolationReportAboveInterpolationCeiling"
          and hardware_report == "MLVideoFrameInterpolationReportNoInterpolationSlots",
          "the verdict that says the resolution is too high is the one the page "
          "calls the interpolation ceiling")
    check(ceiling_report is not None and hardware_report is not None
          and ceiling_report != hardware_report,
          "the two zero-slot verdicts map to two reports, so a merge cannot be "
          "hidden by an enum that still has two names")

    merged_answers = mapper.replace(
        'case MLVideoFrameInterpolationReportAboveInterpolationCeiling:\n'
        '            return @"Video Frame Interpolation Runtime Detail Above Interpolation Ceiling";',
        'case MLVideoFrameInterpolationReportAboveInterpolationCeiling:\n'
        '            return @"Video Frame Interpolation Runtime Detail No Interpolation Slots";')
    check(merged_answers != mapper,
          "the merged-answer mutation has to be a real edit, or the test below proves nothing")
    check(case_literal(merged_answers, "MLVideoFrameInterpolationReportAboveInterpolationCeiling")
          == hardware_key,
          "the ceiling-line assertion fails on a renderer that answers a resolution "
          "refusal with the no-engine sentence")

    collapsed_verdicts = verdict_report.replace(
        "        case MLInterpolationSlotVerdictStreamAboveCeiling:\n"
        "            return MLVideoFrameInterpolationReportAboveInterpolationCeiling;",
        "        case MLInterpolationSlotVerdictStreamAboveCeiling:\n"
        "            return MLVideoFrameInterpolationReportNoInterpolationSlots;")
    check(collapsed_verdicts != verdict_report,
          "the collapsed-verdict mutation has to be a real edit, or the test below proves nothing")
    check(case_return(collapsed_verdicts, "MLInterpolationSlotVerdictStreamAboveCeiling")
          == hardware_report,
          "the verdict-mapping assertion fails on a renderer that folds the two "
          "zero-slot answers into one report")

    asked = probe_size(src)
    matrix = matrix_sizes(open(os.path.join(ROOT, DERIVED), encoding="utf-8").read())
    check(matrix and asked == min(matrix, key=lambda size: size[0] * size[1]),
          "the renderer asks the engine the same size the settings matrix asks (%s vs %s)"
          % (asked, min(matrix, key=lambda size: size[0] * size[1]) if matrix else "none"))

    old_shape = verdict.replace(
        "    return slotsAtProbeSize >= 1 ? MLInterpolationSlotVerdictStreamAboveCeiling\n"
        "                                 : MLInterpolationSlotVerdictNoHardware;",
        "    return MLInterpolationSlotVerdictNoHardware; /* inverted: one answer for two */")
    check(old_shape != verdict,
          "the inverted classifier has to be a real edit, or the test below proves nothing")

    with tempfile.TemporaryDirectory() as tmp:
        model = os.path.join(tmp, "verdicts.m")
        open(model, "w", encoding="utf-8").write(
            VERDICT_MODEL.replace("@@REPORT_ENUM@@", report_enum)
                .replace("@@DEFINES@@", defines(asked)).replace("@@REGION@@", verdict))
        built = subprocess.run([cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
                                "-framework", "Foundation",
                                model, "-o", os.path.join(tmp, "verdicts")],
                               capture_output=True, text=True)
        if built.returncode != 0:
            check(False, "the slot verdict model must compile:\n" + built.stderr.strip()[-700:])
        else:
            ran = subprocess.run([os.path.join(tmp, "verdicts")], capture_output=True, text=True)
            print(textwrap.indent(ran.stdout.strip() or "(no output)", "     "))
            check(ran.returncode == 0,
                  "the shipping classifier separates the two zero-slot answers:\n"
                  + ran.stdout.strip())

        inverted_model = os.path.join(tmp, "inverted.m")
        open(inverted_model, "w", encoding="utf-8").write(
            VERDICT_MODEL.replace("@@REPORT_ENUM@@", report_enum)
                .replace("@@DEFINES@@", defines(asked)).replace("@@REGION@@", old_shape))
        built = subprocess.run([cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
                                "-framework", "Foundation",
                                inverted_model, "-o", os.path.join(tmp, "inverted")],
                               capture_output=True, text=True)
        if built.returncode != 0:
            check(False, "the inverted verdict model must still compile:\n" + built.stderr.strip()[-700:])
        else:
            ran = subprocess.run([os.path.join(tmp, "inverted")], capture_output=True, text=True)
            check(ran.returncode != 0,
                  "one answer for two zero-slot cases must fail the model:\n" + ran.stdout.strip())
            print("     merged verdict refused as expected: %s"
                  % (ran.stdout.strip().splitlines()[-1] if ran.stdout.strip() else "no output"))

    with tempfile.TemporaryDirectory() as tmp:
        probe_path = os.path.join(tmp, "probe.m")
        open(probe_path, "w", encoding="utf-8").write(PROBE)
        binary = os.path.join(tmp, "probe")
        cmd = [cc, "-fobjc-arc", "-fmodules", "-mmacosx-version-min=13.0",
               "-isysroot", sdk, "-framework", "Foundation", "-framework", "Metal",
               "-framework", "MetalFX", probe_path, "-o", binary]
        built = subprocess.run(cmd, capture_output=True, text=True)
        if built.returncode != 0:
            check(False, "the enhancement probe must compile:\n" + built.stderr.strip()[-700:])
            return 1
        run = subprocess.run([binary], capture_output=True, text=True)
        out = run.stdout.strip()
        print(textwrap.indent(out or "(no output)", "     "))

    scaling = re.search(r"METALFX_SCALING=(\w+)", out)
    support = re.search(r"METALFX_SUPPORT=(\w+)", out)
    if scaling is None or support is None:
        check(False, "the probe must report both a support verdict and a scaling verdict")
    elif support.group(1) == "yes":
        check(scaling.group(1) == "yes",
              "MetalFX really rescaled the test pattern on this GPU")
    else:
        print("     MetalFX is not available on this GPU; checking the fallback instead")
        check(re.search(r"MLMetalFXIsSupported\(_device\)\s*\?\s*"
                        r"MLActiveVideoEnhancementEngineMetalFXQuality\s*:\s*"
                        r"MLActiveVideoEnhancementEngineBasicScaling", src) is not None,
              "an unsupported GPU falls back to basic scaling, never to a scaler it cannot run")
    # The resolver now asks whether the panel has more pixels than the stream rather
    # than whether the panel has the stream's shape, because MetalFX takes sizes and not
    # a factor. That premise is the whole change, and it is a claim about a GPU, so it is
    # checked against one rather than asserted in a comment. A machine without MetalFX
    # cannot answer it, and says so instead of passing quietly.
    anisotropic = re.search(r"METALFX_NONUNIFORM=(\w+)", out)
    if support is not None and support.group(1) == "yes":
        check(anisotropic is not None and anisotropic.group(1) == "yes",
              "the scaler fills a window that is not the stream's shape on this GPU, so "
              "an anisotropic window is one the resolver may hand it")
    else:
        print("     no MetalFX on this GPU; the anisotropic premise is not testable here")

    slots = re.search(r"\[vt\] slots offered=(\d+)", out)
    if slots is None:
        print('     (no interpolation verdict reported; skipped)')
    else:
        offered = int(slots.group(1))
        print("     interpolation slots on this machine: %d" % offered)
        if offered >= 1:
            started = re.search(r"session started=(\d)", out)
            check(started is not None and started.group(1) == "1",
                  "a machine that offers slots also starts the session")
        else:
            check("[vt] slots offered=0" in out,
                  "a machine with no slots is reported as such rather than as active")

    print("%d video enhancement failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
