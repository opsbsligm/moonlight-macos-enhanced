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

The probe lifts the two shipping methods --
resolvedFrameProcessorAttributesWithPreferredPixelFormat:baseAttributes: and
ensureFrameInterpolationOutputPoolForConfiguration:sourcePixelFormat: -- straight out
of VideoDecoderRenderer.m, hands them a real low-latency configuration, and demands a
usable pool: one that allocates a real 1920x1080 BGRA buffer. The old resolver shape is
replayed as a planted mutation and must fail the same assertions, so the test is the
regression and not a photo of today's green.
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
#import <VideoToolbox/VideoToolbox.h>

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
        renderer->_frameInterpolationProcessor = [NSObject new];
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
        printf("scenario pool ready=1 buffer=1 width=%zu height=%zu fmt=0x%X\n",
               CVPixelBufferGetWidth(buffer), CVPixelBufferGetHeight(buffer),
               (unsigned)CVPixelBufferGetPixelFormatType(buffer));
        CVPixelBufferRelease(buffer);
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
                   "-framework", "VideoToolbox", path, "-o", os.path.join(work, name)]
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
    check("NSMutableDictionary" in resolver and "addEntriesFromDictionary" in resolver,
          "the attribute step merges the configuration geometry with the renderer "
          "preference instead of asking the resolver that refuses it")
    check("CVPixelBufferCreateResolvedAttributesDictionary" not in strip_objc_comments(resolver),
          "the resolver that returned -6660 on this combination is gone from the merge")
    check("preferredAttributes;" not in strip_objc_comments(resolver),
          "no path returns the bare preferred attributes -- a pool without width "
          "and height is how every interpolation silently died")
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
    fields = dict(pair.split("=") for pair in out.split()[2:])
    check(fields.get("ready") == "1",
          "a real 1920x1080 configuration builds an output pool (the pre-fix "
          "code answered -6682 here and interpolation never mounted)")
    check(fields.get("buffer") == "1",
          "the pool hands out a real pixel buffer")
    check(fields.get("width") == "1920" and fields.get("height") == "1080",
          "the buffers carry the configuration's geometry, not an unspecified size")

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

    return finish()


def finish():
    print("%d interpolation-output-pool failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
