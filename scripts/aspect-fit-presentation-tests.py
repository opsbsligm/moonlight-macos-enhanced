#!/usr/bin/env python3
"""Prove the picture keeps its shape in a window that does not, and that the check notices.

The report this answers is the one nobody files as a bug: a 2560x1440 stream in a 16:10
window looked stretched, and every counter on screen was telling the truth about it. The
metal view resizes with its window in both axes, so the drawable is whatever shape the
player dragged the window into, and the blit drew the texture across all of it. Upstream
carries the same defect and describes it the same way in PR #46.

Three things had to stop deciding independently, because any one of them alone still
leaves a stretched picture:

  * the blit's viewport, which is where the stretch happened;
  * MetalFX's output size, because a scaler handed the whole drawable writes pixels that
    are already out of shape, and a viewport cannot restore a shape it never had;
  * the Video Toolbox super resolution target, which has the same problem one step
    earlier, plus the enhancement decision that asks whether there is anything worth
    enlarging -- measured against the drawable it can promise a scaler the letterbox then
    makes pointless.

So the shape is decided once, by MLContentRectForSource, and every consumer above asks
it. This harness runs the shipping answer: the type, the rule and the viewport
construction are lifted verbatim out of VideoDecoderRenderer.m and played across the
shapes a window actually takes, including the proportional ones, which are the promise
that nothing changed for a stream that already fits. A viewport is what a GPU is handed,
so the assertions are made against the viewport rather than against a resemblance in the
method body.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
RENDERER = "Limelight/Stream/VideoDecoderRenderer.m"
SHAPE_NOTE = "// The rectangle a picture of one shape occupies"
SHAPE_TYPE = "} MLContentRect;"
SHAPE_RULE = "static MLContentRect MLContentRectForSource("
VIEWPORT_RULE = "static MTLViewport MLViewportForContent(MLContentRect content)"
PRESENT = "- (BOOL)encodePresentFromTexture:(id<MTLTexture>)sourceTexture"
METALFX = "- (BOOL)encodeMetalFXScalingFromTexture:(id<MTLTexture>)sourceTexture"

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


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


def method_body(text, signature):
    return brace_span(text, text.index(signature))


def shape_rules(text):
    """The type, the rule, and the viewport it becomes -- verbatim, in dependency order."""
    start = text.index(SHAPE_NOTE)
    type_end = text.index(SHAPE_TYPE) + len(SHAPE_TYPE)
    rule = brace_span(text, text.index(SHAPE_RULE, type_end))
    viewport = brace_span(text, text.index(VIEWPORT_RULE))
    return text[start:type_end] + "\n\n" + rule + "\n\n" + viewport


DRIVER = r"""
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>

@@RULES@@

static int failures = 0;

static void expect(const char *what, MLContentRect got, NSUInteger w, NSUInteger h,
                   NSUInteger x, NSUInteger y) {
    BOOL ok = got.width == w && got.height == h && got.originX == x && got.originY == y;
    if (!ok) failures++;
    printf("%-4s %-34s -> %zux%zu @ %zu,%zu (want %zux%zu @ %zu,%zu)\n",
           ok ? "ok" : "FAIL", what, got.width, got.height, got.originX, got.originY, w, h, x, y);
}

static void expect_viewport(const char *what, NSUInteger sw, NSUInteger sh,
                            NSUInteger dw, NSUInteger dh,
                            double x, double y, double w, double h) {
    const MTLViewport vp = MLViewportForContent(MLContentRectForSource(sw, sh, dw, dh));
    BOOL ok = vp.originX == x && vp.originY == y && vp.width == w && vp.height == h
              && vp.znear == 0.0 && vp.zfar == 1.0;
    if (!ok) failures++;
    printf("%-4s %-34s -> viewport (%g,%g %gx%g) want (%g,%g %gx%g)\n",
           ok ? "ok" : "FAIL", what, vp.originX, vp.originY, vp.width, vp.height, x, y, w, h);
}

int main(void) {
    @autoreleasepool {
        // A 16:9 stream in a 16:10 window: full width, fifty pixels of bar each side.
        expect_viewport("2560x1440 into 1600x1000", 2560, 1440, 1600, 1000, 0, 50, 1600, 900);
        expect_viewport("1280x720 into 1600x1000", 1280, 720, 1600, 1000, 0, 50, 1600, 900);
        // A 4:3 stream in the same window gets bars left and right instead.
        expect_viewport("1024x768 into 1600x1000", 1024, 768, 1600, 1000, 133, 0, 1333, 1000);
        // An ultrawide stream into the same window.
        expect_viewport("4320x2160 into 1600x1000", 4320, 2160, 1600, 1000, 0, 100, 1600, 800);
        // A window a player dragged into a sliver still gets a picture, not a zero.
        expect_viewport("2560x1440 into 100x1000", 2560, 1440, 100, 1000, 0, 472, 100, 56);
        expect_viewport("2560x1440 into 1x1", 2560, 1440, 1, 1, 0, 0, 1, 1);
        // Nothing to draw, or nowhere to draw it: the surface wins, and nothing crashes.
        expect("no stream falls back to the surface",
               MLContentRectForSource(0, 0, 800, 600), 800, 600, 0, 0);
        expect("no surface stays empty",
               MLContentRectForSource(1920, 1080, 0, 0), 0, 0, 0, 0);

        const NSUInteger shapes[][2] = {{1280, 720}, {1920, 1080}, {2560, 1440},
                                        {3840, 2160}, {720, 1280}, {1080, 1080}};
        int proportional = 0;
        for (int i = 0; i < 6; i++) {
            for (NSUInteger k = 1; k <= 5; k++) {
                const NSUInteger w = shapes[i][0] * k, h = shapes[i][1] * k;
                const MLContentRect fit = MLContentRectForSource(shapes[i][0], shapes[i][1], w, h);
                if (fit.width != w || fit.height != h || fit.originX || fit.originY) {
                    failures++;
                    printf("FAIL shape %zux%zu into %zux%zu became %zux%zu @ %zu,%zu\n",
                           shapes[i][0], shapes[i][1], w, h, fit.width, fit.height,
                           fit.originX, fit.originY);
                }
                proportional++;
            }
        }
        printf("%-4s %d proportional surfaces keep the whole surface (%d checked)\n",
               failures ? "FAIL" : "ok", 6, proportional);

        printf("%s\n", failures ? "RUN FAILED" : "RUN PASSED");
        return failures ? 1 : 0;
    }
}
"""


def compiled(source, work, name, cc, sdk):
    path = os.path.join(work, name + ".m")
    open(path, "w", encoding="utf-8").write(source)
    command = [cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
               "-framework", "Foundation", "-framework", "Metal",
               path, "-o", os.path.join(work, name)]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return None, None, (built.stdout + built.stderr).strip()[-1800:]
    ran = subprocess.run([os.path.join(work, name)], capture_output=True, text=True)
    return ran.returncode, ran.stdout, (ran.stdout + ran.stderr).strip()[-1800:]


def run_rules(label, rules, cc, sdk):
    with tempfile.TemporaryDirectory() as work:
        code, out, log = compiled(DRIVER.replace("@@RULES@@", rules), work, "aspectfit", cc, sdk)
        if code is None:
            check(False, "%s compiles: %s" % (label, log))
            return
        if label == "the shipping shape rule":
            check(code == 0 and out is not None and "RUN PASSED" in out,
                  "the shipping shape rule keeps its shape across the shapes a window takes"
                  if code == 0 else "the shipping shape rule failed a case:%s" % out)
        else:
            check(code != 0, "the check still fails when %s" % label)


def main():
    renderer = read(RENDERER)
    rules = shape_rules(renderer)
    present = method_body(renderer, PRESENT)
    metalfx = method_body(renderer, METALFX)

    print("-- what the picture does with a window of a different shape --")

    cc, sdk = apple_toolchain.clang_and_sdk("aspect fit")
    run_rules("the shipping shape rule", rules, cc, sdk)

    # --- the three decisions have to be one decision -------------------------
    check(present.count("MTLLoadActionClear") == 1 and
          "MTLClearColorMake(0.0, 0.0, 0.0, 1.0)" in present,
          "the present clears the bars to black instead of leaving the last frame in them")
    check("[renderEncoder setViewport:MLViewportForContent(content)]" in present,
          "the blit draws into the content rectangle through the one viewport construction")
    check(present.index("MLContentRectForSource(") < present.index("setViewport:"),
          "the viewport comes from the shape rule and not from somewhere else in the method")

    check(re.search(r"scalerDesc\.outputWidth = content\.width;", metalfx) is not None
          and re.search(r"scalerDesc\.outputHeight = content\.height;", metalfx) is not None,
          "MetalFX is asked for the content rectangle, so its output keeps the stream's shape")
    check("scalerDesc.outputWidth = drawable.texture.width;" not in metalfx
          and "scalerDesc.outputHeight = drawable.texture.height;" not in metalfx,
          "no scaler is handed the drawable behind the shape rule's back")
    check("[_spatialScaler outputWidth] != content.width" in metalfx
          and "[_spatialScaler outputHeight] != content.height" in metalfx,
          "a scaler left at the drawable's size is torn down rather than reused")
    check("needsIntermediateTexture" in metalfx
          and "width:content.width" in metalfx and "height:content.height" in metalfx,
          "a content rectangle smaller than the drawable is written through an intermediate")

    check("MLContentRectForSource(sourceWidth, sourceHeight," in renderer
          and "const NSUInteger targetWidth = contentRect.width;" in renderer
          and "const NSUInteger targetHeight = contentRect.height;" in renderer,
          "the enhancement decision and the super resolution target are sized to the picture")
    check("targetWidth:(NSUInteger)llround(self->_metalView.drawableSize.width)" not in renderer,
          "the warm-up does not prepare a session the first frame will not use")
    check("scaledOutputWidth = (uint32_t)contentRect.width;" in renderer
          and "scaledOutputHeight = (uint32_t)contentRect.height;" in renderer,
          "the overlay quotes the rectangle a scaler wrote, not the size of the window")

    # --- and the assertions above have to be the thing that fails ------------
    run_rules("the bars stop being centred",
              rules.replace("fit.originY = (targetHeight - fit.height) / 2;", "fit.originY = 0;"),
              cc, sdk)
    run_rules("the two shape branches trade places",
              rules.replace("if (sourceIsWider > targetIsWider) {", "if (sourceIsWider < targetIsWider) {"),
              cc, sdk)
    run_rules("a sliver of a window is allowed to collapse to nothing",
              rules.replace("if (fit.height == 0) {\n            fit.height = 1;\n        }", ""),
              cc, sdk)

    check("[renderEncoder setViewport:MLViewportForContent(content)];" in present
          and "[renderEncoder setViewport:MLViewportForContent(content)];"
              not in present.replace("[renderEncoder setViewport:MLViewportForContent(content)];", ""),
          "the viewport is set exactly once, so no later pass can undo it")
    check(present.count("setViewport:") == 1,
          "the present sets one viewport (%d)" % present.count("setViewport:"))
    mutated = present.replace("[renderEncoder setViewport:MLViewportForContent(content)];", "")
    check(mutated != present and "setViewport:" not in mutated,
          "removing the viewport really does leave the blit drawing across the drawable")

    print("%d aspect-fit-presentation failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
