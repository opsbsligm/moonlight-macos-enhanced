#!/usr/bin/env python3
"""Prove the interpolation output pool really builds, with the shipping methods on real VideoToolbox.

The 4:4:4 hold-back fixed one layer of "interpolation never mounts" and exposed the next:
every output pool creation failed with -6682 (kCVReturnInternalError) on Apple M2 /
macOS 26, so even a 4:2:0 stream that the configuration accepts never reached the
interpolator. The cause is measurable, not folklore:

  VTLowLatencyFrameInterpolationConfiguration.destinationPixelBufferAttributes carries
  the frame geometry (Width/Height/ExtendedPixels...) plus its own pixel format.
  The old attribute step ran those attributes through
  CVPixelBufferCreateResolvedAttributesDictionary, which refuses geometry alongside
  extended pixels (-6660 measured), and then fell back to the renderer's preferred
  attributes ALONE -- a dictionary with a pixel format, Metal and IOSurface keys but
  no width or height. CVPixelBufferPoolCreate cannot build a pool of unknown size and
  answers -6682. Every session, every Mac, silently: the settings page said the
  engine, the runtime said warm, and no interpolated frame was ever made.

The third layer arrived once the pool existed: the merge overrode the configuration's
own destination format with the renderer's preferred BGRA, the pool built, buffers came
back, and every submit failed with VTFrameProcessorProcessingError (-19740, underlying
-50, measured on Apple M2 / macOS 26). A low-latency interpolation destination must use
the pixel format the configuration advertises -- 420v for a video-range stream -- so the
configuration is the authority on the format and the preferred value only fills a gap.

The probe lifts the two shipping methods --
resolvedFrameProcessorAttributesWithPreferredPixelFormat:baseAttributes: and
ensureFrameInterpolationOutputPoolForConfiguration:sourcePixelFormat: -- straight out
of VideoDecoderRenderer.m, hands them a real low-latency configuration, and demands a
usable pool: one that allocates a real 1920x1080 buffer in the configuration's own
format. It then submits the pool's buffer to a started session and demands the callback
report success -- a pool that builds but rejects every frame is how -19740 shipped. The
old resolver shape and a BGRA-overriding merge are replayed as planted mutations, each
must fail its own assertion, so the test is the regression and not a photo of today's
green.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RENDERER = os.path.join(ROOT, "Limelight", "Stream", "VideoDecoderRenderer.m")

RESOLVER = "- (NSDictionary *)resolvedFrameProcessorAttributesWithPreferredPixelFormat:"
POOL = "- (BOOL)ensureFrameInterpolationOutputPoolForConfiguration:"

# The attribute step as it shipped before the fix: resolver first, bare preferred on
# refusal. Written out from git history, not paraphrased, so replaying it here is
# running the old code and not an impression of it.
LEGACY_RESOLVER = r"""
- (NSDictionary *)resolvedFrameProcessorAttributesWithPreferredPixelFormat:(OSType)preferredPixelFormat
                                                             baseAttributes:(NSDictionary *)baseAttributes
{
    NSDictionary *preferredAttributes = @{
        (id)kCVPixelBufferPixelFormatTypeKey: @(preferredPixelFormat),
        (id)kCVPixelBufferMetalCompatibilityKey: @YES,
        (id)kCVPixelBufferIOSurfacePropertiesKey: @{},
    };

    CFDictionaryRef resolved = NULL;
    CVReturn status = CVPixelBufferCreateResolvedAttributesDictionary(kCFAllocatorDefault,
                                                                      (__bridge CFArrayRef)@[preferredAttributes, baseAttributes ?: @{}],
                                                                      &resolved);
    if (status != kCVReturnSuccess || resolved == NULL) {
        return preferredAttributes;
    }

    return CFBridgingRelease(resolved);
}
"""

DRIVER = r"""
#import <Foundation/Foundation.h>
#import <CoreVideo/CoreVideo.h>
#import <CoreMedia/CoreMedia.h>
#import <VideoToolbox/VideoToolbox.h>
#import <dispatch/dispatch.h>

@interface FakeRenderer : NSObject {
@public
    CVPixelBufferPoolRef _frameInterpolationOutputPool;
    OSType _frameInterpolationSourcePixelFormat;
    id _frameInterpolationProcessor;
}
@end

// The renderer logs through its own macro; the probe stays quiet but compiles.
#define Log(level, fmt, ...) ((void)0)
#define LOG_W 3

@implementation FakeRenderer
@@RESOLVER@@
@@POOL@@
// The probe's job is the pool, not the format survey; the format gate belongs to the
// sibling probe and always answers "yes, build the pool" here.
- (BOOL)frameInterpolationConfiguration:(VTLowLatencyFrameInterpolationConfiguration *)configuration
                 supportsSourcePixelFormat:(OSType)pixelFormat {
    return YES;
}
@end

int main(void) {
    @autoreleasepool {
        VTLowLatencyFrameInterpolationConfiguration *configuration =
            [[VTLowLatencyFrameInterpolationConfiguration alloc]
                initWithFrameWidth:1920 frameHeight:1080 numberOfInterpolatedFrames:1];
        if (configuration == nil) {
            printf("scenario pool skipped\n");
            return 0;
        }
        FakeRenderer *renderer = [[FakeRenderer alloc] init];
        VTFrameProcessor *session = [[VTFrameProcessor alloc] init];
        renderer->_frameInterpolationProcessor = session;
        BOOL built = [renderer ensureFrameInterpolationOutputPoolForConfiguration:configuration
                                                               sourcePixelFormat:0x34323076];
        if (!built || renderer->_frameInterpolationOutputPool == NULL) {
            printf("scenario pool ready=0\n");
            return 0;
        }
        CVPixelBufferRef buffer = NULL;
        CVReturn status = CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault,
                                                             renderer->_frameInterpolationOutputPool,
                                                             &buffer);
        if (status != kCVReturnSuccess || buffer == NULL) {
            printf("scenario pool ready=1 buffer=0\n");
            return 0;
        }
        CVPixelBufferPoolRef sourcePool = NULL;
        NSDictionary *sourceAttributes = @{
            (id)kCVPixelBufferPixelFormatTypeKey: @(0x34323076),
            (id)kCVPixelBufferWidthKey: @1920,
            (id)kCVPixelBufferHeightKey: @1080,
            (id)kCVPixelBufferIOSurfacePropertiesKey: @{},
        };
        CVPixelBufferPoolCreate(kCFAllocatorDefault, NULL,
                                (__bridge CFDictionaryRef)sourceAttributes, &sourcePool);
        printf("scenario pool ready=1 buffer=1 width=%zu height=%zu fmt=0x%X\n",
               CVPixelBufferGetWidth(buffer), CVPixelBufferGetHeight(buffer),
               (unsigned)CVPixelBufferGetPixelFormatType(buffer));

        // A pool that builds is not a pool that interpolates. Submit the shipping
        // pool's buffer to a started session and report what the callback says;
        // -19740 is the number the override bug shipped behind.
        NSError *sessionError = nil;
        if (![session startSessionWithConfiguration:configuration error:&sessionError]) {
            printf("scenario submit ok=0 err=session\n");
            CVPixelBufferRelease(buffer);
            return 0;
        }
        CVPixelBufferRef source = NULL, previous = NULL;
        CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, sourcePool, &source);
        CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, sourcePool, &previous);
        CMTime pts = CMTimeMake(33, 1000);
        VTFrameProcessorFrame *sourceFrame =
            [[VTFrameProcessorFrame alloc] initWithBuffer:source presentationTimeStamp:pts];
        VTFrameProcessorFrame *previousFrame =
            [[VTFrameProcessorFrame alloc] initWithBuffer:previous presentationTimeStamp:pts];
        VTFrameProcessorFrame *destinationFrame =
            [[VTFrameProcessorFrame alloc] initWithBuffer:buffer presentationTimeStamp:pts];
        VTLowLatencyFrameInterpolationParameters *params =
            [[VTLowLatencyFrameInterpolationParameters alloc]
                initWithSourceFrame:sourceFrame
                      previousFrame:previousFrame
                   interpolationPhase:@[@(0.5)]
                    destinationFrames:@[destinationFrame]];
        if (params == nil) {
            printf("scenario submit ok=0 err=init\n");
        } else {
            dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
            __block NSInteger code = 0;
            __block BOOL timedOut = YES;
            [session processWithParameters:params
                         completionHandler:^(id<VTFrameProcessorParameters> completed, NSError *error) {
                code = error == nil ? 0 : error.code;
                timedOut = NO;
                dispatch_semaphore_signal(semaphore);
            }];
            if (dispatch_semaphore_wait(semaphore,
                    dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC)) == 0) {
                timedOut = NO;
            } else {
                code = -1;
            }
            printf("scenario submit ok=%d err=%ld\n", code == 0 && !timedOut, (long)code);
            if (code == -19730) {
                // A started session whose pipeline cannot run at all (headless CI
                // VMs report the unknown-error code for any submit) cannot adjudicate
                // format claims; say so instead of failing them.
                printf("scenario submit capability=0\n");
            }
        }
        if (source) CVPixelBufferRelease(source);
        if (previous) CVPixelBufferRelease(previous);
        CVPixelBufferRelease(buffer);
        [session endSession];
        if (sourcePool) CVPixelBufferPoolRelease(sourcePool);
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


def definition_span(text, signature):
    for match in re.finditer(re.escape(signature), text):
        semicolon = text.find(";", match.start())
        brace = text.find("{", match.start())
        if 0 <= brace < semicolon:
            return brace_span(text, match.start())
    raise AssertionError("no definition of " + signature)


def strip_objc_comments(method):
    method = re.sub(r"/\*.*?\*/", " ", method, flags=re.S)
    return re.sub(r"//[^\n]*", " ", method)


def build(source, resolver=None, pool=None):
    return (DRIVER
            .replace("@@RESOLVER@@", definition_span(source, RESOLVER) if resolver is None else resolver)
            .replace("@@POOL@@", definition_span(source, POOL) if pool is None else pool))


def compiled(source, name, clang, sdk):
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, name + ".m")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        command = [clang, "-fobjc-arc", "-isysroot", sdk, "-mmacosx-version-min=26.0",
                   "-framework", "Foundation", "-framework", "CoreVideo",
                   "-framework", "CoreMedia", "-framework", "VideoToolbox", path, "-o", os.path.join(work, name)]
        built = subprocess.run(command, capture_output=True, text=True)
        if built.returncode != 0:
            return None, (built.stdout + built.stderr).strip()[-1800:]
        ran = subprocess.run([os.path.join(work, name)], capture_output=True, text=True)
        return ran.stdout, (ran.stdout + ran.stderr).strip()[-1800:]


failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def main():
    source = read(RENDERER)
    print("-- does the interpolation output pool really exist --")

    resolver = definition_span(source, RESOLVER)
    pool = definition_span(source, POOL)

    # --- shape of the fix, before running it ---------------------------------
    check("NSMutableDictionary" in resolver and "initWithDictionary:baseAttributes" in resolver,
          "the attribute step starts from the configuration's own attributes, so its "
          "geometry and pixel format survive instead of asking the resolver that refuses it")
    check("CVPixelBufferCreateResolvedAttributesDictionary" not in strip_objc_comments(resolver),
          "the resolver that returned -6660 on this combination is gone from the merge")
    check("preferredAttributes;" not in strip_objc_comments(resolver),
          "no path returns the bare preferred attributes -- a pool without width "
          "and height is how every interpolation silently died")
    check("kCVPixelBufferPixelFormatTypeKey] == nil" in strip_objc_comments(resolver),
          "the preferred pixel format only fills a gap -- the configuration's own "
          "destination format is the authority, which is what -19740 demanded")
    check("CVPixelBufferPoolCreate" in pool,
          "the pool step still builds a real CVPixelBufferPool")

    try:
        clang, sdk = apple_toolchain.clang_and_sdk("interpolation output pool probe")
    except SystemExit as error:  # a host with no Apple compiler is a skip
        print("%s" % error)
        return 0

    # --- the shipping methods, on real VideoToolbox --------------------------
    out, log = compiled(build(source), "clean", clang, sdk)
    check(out is not None,
          "the shipping pool methods compile" if out is not None
          else "the shipping pool methods must compile:" + log)
    if out is None:
        return finish()
    if "skipped" in out:
        print("     skipped: this host has no low-latency interpolation configuration")
        return finish()
    print("     %s" % out.strip())
    lines = [line for line in out.splitlines() if line.startswith("scenario")]
    fields = dict(pair.split("=") for line in lines for pair in line.split()[2:])
    check(fields.get("ready") == "1",
          "a real 1920x1080 configuration builds an output pool (the pre-fix "
          "code answered -6682 here and interpolation never mounted)")
    check(fields.get("buffer") == "1",
          "the pool hands out a real pixel buffer")
    check(fields.get("width") == "1920" and fields.get("height") == "1080",
          "the buffers carry the configuration's geometry, not an unspecified size")
    check(fields.get("fmt") == "0x34323076",
          "the buffers carry the configuration's own video-range 4:2:0 format, "
          "not the renderer's preferred override")
    can_process = "capability=0" not in out
    if can_process:
        check(fields.get("ok") == "1",
              "the shipping pool's buffer submits to a started session and the callback "
              "reports success (a BGRA destination reported -19740 for every frame)")
    else:
        print("     skip  submit adjudication: this host starts the session but its "
              "frame-processing pipeline reports -19730 for any submit (headless CI); "
              "the format claim below is still checked, the submit claim runs on any "
              "machine with a working pipeline")

    # --- the old code has to fail these same assertions ----------------------
    legacy, log = compiled(build(source, resolver=LEGACY_RESOLVER), "legacy", clang, sdk)
    check(legacy is not None,
          "the pre-fix resolver shape compiles" if legacy is not None
          else "the pre-fix resolver shape must compile:" + log)
    if legacy is not None:
        check("ready=0" in legacy,
              "the probe catches the old resolver+fallback attribute step "
              "(it reported %r where the fix reports a pool)" % legacy.strip())

    # --- a merge that loses the geometry has to fail too ---------------------
    stripped = resolver.replace(
        "NSMutableDictionary *merged = [[NSMutableDictionary alloc] initWithDictionary:baseAttributes ?: @{}];",
        "NSMutableDictionary *merged = [[NSMutableDictionary alloc] init];")
    check(stripped != resolver, "the mutation that drops the geometry is a real edit")
    bad, log = compiled(build(source, resolver=stripped), "stripped", clang, sdk)
    check(bad is not None,
          "the geometry-stripped mutation compiles" if bad is not None
          else "the geometry-stripped mutation must compile:" + log)
    if bad is not None:
        check("ready=0" in bad,
              "the probe notices an attribute merge that forgets the frame size "
              "(reported %r)" % bad.strip())

    # --- the shipped bug: overriding the format builds a pool that never submits
    overriding = resolver.replace(
        "if (merged[(id)kCVPixelBufferPixelFormatTypeKey] == nil) {",
        "if (YES) {")
    check(overriding != resolver, "the mutation that reinstates the format override is a real edit")
    overridden, log = compiled(build(source, resolver=overriding), "override", clang, sdk)
    check(overridden is not None,
          "the format-overriding mutation compiles" if overridden is not None
          else "the format-overriding mutation must compile:" + log)
    if overridden is not None:
        print("     %s" % overridden.strip())
        check("fmt=0x42475241" in overridden,
              "the mutation really ships BGRA destinations (reported %r)" % overridden.strip())
        if can_process:
            check("ok=0 err=-19740" in overridden,
                  "the probe catches the override bug where it actually hurt: the pool "
                  "builds, the buffers exist, and every submit fails -19740 (reported %r)"
                  % overridden.strip())
        else:
            check("ok=0" in overridden,
                  "on a host that can submit frames the override must fail the submit; "
                  "this host cannot submit, so the probe only confirms the BGRA "
                  "destination never produced a frame (reported %r)" % overridden.strip())

    return finish()


def finish():
    print("%d interpolation-output-pool failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
