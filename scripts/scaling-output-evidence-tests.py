#!/usr/bin/env python3
"""Prove the scalers' output is counted where it is drawn, and read back off the overlay.

The player's question was "is MetalFX scaling, or the Video Toolbox one, actually
doing anything", and the renderer could answer it only to itself: it stored an engine
and a reason, and nothing anywhere counted a frame a scaler had enlarged. The overlay
quotes the resolution of the *stream*, so a 1280x720 picture stretched by a bilinear
blit and a 1280x720 picture resampled to 2560x2160 by hardware print the same line,
and the one thing that would tell them apart -- how many pixels arrived -- was dropped
on the way to the screen.

Counting it is not a matter of adding one to a field in the draw pass, because there
are two scalers and neither of them is the blit that shows the result. MetalFX reports
whether it encoded; VideoToolbox super resolution reports nothing at that point and
announces itself only by having handed back an enlarged buffer. So the charge goes
through one file-scope decision that is asked what the encode actually did, and that
decision refuses a present whose sizes came out the same as they went in -- a scaler
that invented no pixels has nothing to report, and "0 fps scaled" has to stay a claim
rather than a description of 1:1 blitting.

What runs here is the product's own text: the enum, the struct, the decision, and the
block in the draw pass that asks it and applies the answer, all lifted verbatim out of
VideoDecoderRenderer.m and played across 330 presents, including the ones where a
scaler was wanted and did not run. The sizes are realistic on every scenario, because
the thing being tested is "a scaler ran", not "the sizes differ": a bilinear stretch to
a bigger drawable looks exactly like a scaled present to anybody who asks only about
sizes, and it is exactly the case that must not be charged.

Reading the number is the other half. The window that closes has to publish it as a
rate, the overlay has to show the size the scaler wrote as well as the rate -- a count
without the size is the half that does not answer the question -- and both languages
have to name it.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
RENDERER = "Limelight/Stream/VideoDecoderRenderer.m"
STATS_HEADER = "Limelight/Stream/VideoDecoderRenderer.h"
OVERLAY = "Limelight/macOS/ViewControllers/StreamViewController+Diagnostics.m"
KIND = "MLScalerKind"
EVIDENCE = "MLScaledFrameEvidence"
DECIDER = "MLHardwareScaledEvidenceForPresentedFrame"
FIT = "static MLContentRect MLContentRectForSource("
FIT_NOTE = "// The rectangle a picture of one shape occupies"
CONTENT_TYPE = "} MLContentRect;"
LABEL = "Scaled"

# The answer the Video Toolbox processor gives for every engine but its own.
# The guard assertion and the mutation that removes it are both built from this one
# string, so the assertion cannot outlive the mutation it is meant to notice.
PROCESSOR_GUARD = (
    "engine != MLActiveVideoEnhancementEngineVTLowLatencySuperResolution &&" + chr(10)
    + "        engine != MLActiveVideoEnhancementEngineVTQualitySuperResolution) {" + chr(10)
    + "        return NULL;")

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def brace_span(text, start):
    """The text from start through the brace that closes the first brace after it."""
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
    raise AssertionError("unbalanced braces after " + text[start:start + 60])


def enum_block(text, name):
    """The shipping NS_ENUM declaration, enumerators included."""
    match = re.search("^typedef NS_ENUM[(]NSInteger, " + name + "[)]", text, re.M)
    assert match, "no NS_ENUM declaration for " + name
    end = text.index("};", match.start())
    return text[match.start():end + 2]


def struct_block(text, name):
    """The shipping typedef struct declaration for name."""
    for match in re.finditer("^typedef struct [{]", text, re.M):
        # The terminator is the semicolon after the closing brace: every field inside
        # ends with one, so searching from the start would stop at the first field.
        closing_brace = text.index("}", match.start())
        end = text.index(";", closing_brace)
        span = text[match.start():end + 1]
        if name + ";" in span:
            return span
    raise AssertionError("no typedef struct for " + name)


def inline_function(text, name):
    """The shipping text of a static inline function, signature included."""
    match = re.search("^static inline [^(]*" + name, text, re.M)
    assert match, "no inline definition of " + name
    return brace_span(text, match.start())


def charge_block(text):
    """The product's own scaling bookkeeping for one present, verbatim.

    It starts where the present decides which scaler, if any, has to answer for these
    pixels, and ends after the counters have been moved, because what follows belongs
    to the source-frame tally.
    """
    start = text.index(KIND + " scalerKindForPresent = " + KIND + "None;")
    gate = text.index("if (scalingEvidence.reachedDisplay) {", start)
    return text[start:gate] + brace_span(text, gate)


def method_definition(text, signature):
    """The body of a method, found by its first signature line."""
    start = text.index(signature)
    return brace_span(text, start)


DRIVER = r"""
#import <Foundation/Foundation.h>

// The three fields the shipping struct gained, and only those. Every other member of
// VideoStats describes a timing a fake cannot reproduce, and none of it decides a
// count.
typedef struct {
    uint32_t scaledFrames;
    uint32_t scaledOutputWidth;
    uint32_t scaledOutputHeight;
} FakeVideoStats;

@@HELPER@@

// The draw pass settles the content rectangle before the bookkeeping below runs, so
// the fake settles it the same way and from the same two inputs. Without this the
// lifted block would be measured against a size a fake invented.
static MLContentRect MLContentRectForFakePresent(NSUInteger sourceWidth,
                                                 NSUInteger sourceHeight,
                                                 NSUInteger drawableWidth,
                                                 NSUInteger drawableHeight) {
    return MLContentRectForSource(sourceWidth, sourceHeight, drawableWidth, drawableHeight);
}

static FakeVideoStats _activeWndVideoStats;
static int g_checked;
static int g_metalfxPresents;
static int g_videoToolboxPresents;
static int g_plainPresents;
static int g_sizedScalerPresents;   // a scaler ran and the sizes really differed

// The lifted block reaches for a drawable's texture size, so the fake answers that
// shape and nothing else.
@interface FakeTexture : NSObject
@property (nonatomic) NSUInteger width;
@property (nonatomic) NSUInteger height;
@end
@implementation FakeTexture
@end

@interface FakeDrawable : NSObject
@property (nonatomic, strong) FakeTexture *texture;
@end
@implementation FakeDrawable
@end

static char g_processorOutputToken;

@@KIND@@

@@EVIDENCE@@

@@DECIDER@@

// One present through the draw pass, booked the way the renderer books it.
//
// The sizes are the ones the product would hold at that point in the pass: the stream
// as decoded, the buffer that is about to be drawn, and the drawable that will show it.
// A scaler that ran wrote the drawable (MetalFX) or wrote the buffer (VideoToolbox),
// and a plain blit leaves both of those alone -- which is why every scenario, including
// the plain one, carries a bigger drawable.
static void present(FakeDrawable *drawable,
                    BOOL usedMetalFX,
                    void *processedFrame,
                    NSUInteger sourceWidth,
                    NSUInteger sourceHeight,
                    size_t workingWidth,
                    size_t workingHeight) {
    const MLContentRect contentRect = MLContentRectForFakePresent(sourceWidth, sourceHeight,
                                                                  drawable.texture.width,
                                                                  drawable.texture.height);
    @@BLOCK@@
}

static FakeDrawable *drawable_sized(NSUInteger width, NSUInteger height) {
    FakeDrawable *drawable = [[FakeDrawable alloc] init];
    drawable.texture = [[FakeTexture alloc] init];
    drawable.texture.width = width;
    drawable.texture.height = height;
    return drawable;
}

static int g_metalfxRuns, g_videoToolboxRuns;

// Scaled by MetalFX from the stream straight to the panel.
static void metalfx(int presents, NSUInteger inW, NSUInteger inH, NSUInteger outW, NSUInteger outH) {
    for (int index = 0; index < presents; index++) {
        present(drawable_sized(outW, outH), YES, NULL, inW, inH, inW, inH);
        g_checked++;
        g_metalfxPresents++;
        if (outW > inW && outH > inH) {
            g_sizedScalerPresents++;
        }
    }
    g_metalfxRuns++;
}

// Scaled by the Video Toolbox processor, which writes an enlarged buffer that the
// render pass then shows.
static void video_toolbox(int presents, NSUInteger inW, NSUInteger inH, NSUInteger outW, NSUInteger outH) {
    for (int index = 0; index < presents; index++) {
        present(drawable_sized(outW, outH), NO, &g_processorOutputToken, inW, inH, outW, outH);
        g_checked++;
        g_videoToolboxPresents++;
        if (outW > inW && outH > inH) {
            g_sizedScalerPresents++;
        }
    }
    g_videoToolboxRuns++;
}

// No scaler: the blit that stretches the decode to fill the window. The drawable is
// bigger than the stream here too, because that is what a windowed stream looks like,
// and it is the case a size question alone cannot tell from a scaled one.
static void plain(int presents, NSUInteger inW, NSUInteger inH, NSUInteger outW, NSUInteger outH) {
    for (int index = 0; index < presents; index++) {
        present(drawable_sized(outW, outH), NO, NULL, inW, inH, inW, inH);
        g_checked++;
        g_plainPresents++;
    }
}

static void report(const char *name) {
    printf("scenario %s %u %u %u", name,
           _activeWndVideoStats.scaledFrames,
           _activeWndVideoStats.scaledOutputWidth,
           _activeWndVideoStats.scaledOutputHeight);
    puts("");
    _activeWndVideoStats = (FakeVideoStats){0};
}

int main(void) {
    metalfx(60, 1280, 720, 3840, 2160);
    report("metalfx");

    video_toolbox(60, 1280, 720, 2560, 1440);
    report("video-toolbox");

    plain(60, 1280, 720, 3840, 2160);
    report("bilinear");

    // A panel that is exactly the size the scaler was handed. Nothing was invented, so
    // the tally has to stay quiet even though a scaler did run.
    metalfx(60, 1920, 1080, 1920, 1080);
    report("exact-fit");

    // Wider but no taller: resampling, not inventing picture.
    metalfx(60, 1280, 720, 3840, 720);
    report("one-axis");

    for (int index = 0; index < 30; index++) {
        metalfx(1, 1280, 720, 2560, 2160);
    }
    video_toolbox(10, 1280, 720, 2560, 1440);
    plain(20, 1280, 720, 2560, 2160);
    report("mixed");

    printf("checked %d\n", g_checked);
    printf("kinds metalfx=%d video-toolbox=%d plain=%d sized=%d runs=%d/%d\n",
           g_metalfxPresents, g_videoToolboxPresents, g_plainPresents,
           g_sizedScalerPresents, g_metalfxRuns, g_videoToolboxRuns);
    return 0;
}
"""


def compiled(source, work, name, cc, sdk):
    path = os.path.join(work, name + ".m")
    open(path, "w", encoding="utf-8").write(source)
    command = [cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
               "-framework", "Foundation", path, "-o", os.path.join(work, name)]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr).strip()[-1800:]
    ran = subprocess.run([os.path.join(work, name)], capture_output=True, text=True)
    return ran.stdout, (ran.stdout + ran.stderr).strip()[-1800:]


def content_helper(text):
    """The one answer about shapes, with the type it returns, verbatim.

    The lifted present bookkeeping asks for the rectangle the picture occupies, so the
    harness has to run the real answer rather than a copy of it. A drift between the
    shape rule and the size the overlay prints is exactly what no player would ever
    describe as "the numbers look wrong".
    """
    start = text.index(FIT_NOTE)
    typedef_end = text.index(CONTENT_TYPE) + len(CONTENT_TYPE)
    return (text[start:typedef_end] + chr(10) + chr(10)
            + brace_span(text, text.index(FIT, typedef_end)))


def build(kinds, evidence, decider, block, helper):
    return (DRIVER.replace("@@KIND@@", kinds)
                  .replace("@@EVIDENCE@@", evidence)
                  .replace("@@DECIDER@@", decider)
                  .replace("@@HELPER@@", helper)
                  .replace("@@BLOCK@@", block))


def reading(stdout):
    """{scenario: (frames, width, height)}, plus the coverage the run reported."""
    rows, checked, kinds = {}, None, None
    for line in stdout.splitlines():
        fields = line.split()
        if fields[:1] == ["checked"]:
            checked = int(fields[1])
        elif fields[:1] == ["kinds"]:
            kinds = dict(pair.split("=") for pair in fields[1:])
        elif fields[:1] == ["scenario"]:
            rows[fields[1]] = tuple(int(value) for value in fields[2:5])
    return rows, checked, kinds


def run_compiled(label, kinds, evidence, decider, block, helper, cc, sdk, expect):
    """Plant one wrong answer in the lifted text and require the run to show it."""
    with tempfile.TemporaryDirectory() as work:
        rows, log = compiled(build(kinds, evidence, decider, block, helper), work, "bad", cc, sdk)
        check(rows is not None,
              "the mutation that %s compiles" % label if rows is not None
              else "the mutation that %s must compile:%s" % (label, log))
        if rows is None:
            return
        seen, _checked, _kinds = reading(rows)
        for scenario, wanted in expect.items():
            check(seen.get(scenario) == wanted,
                  "the sweep sees a run that %s (%s %s, expected %s)"
                  % (label, scenario, seen.get(scenario), wanted))


def main():
    renderer = read(RENDERER)
    header = read(STATS_HEADER)
    overlay = read(OVERLAY)

    kinds = enum_block(renderer, KIND)
    evidence = struct_block(renderer, EVIDENCE)
    decider = inline_function(renderer, DECIDER)
    block = charge_block(renderer)
    helper = content_helper(renderer)

    print("-- what the scalers produced, and who is told --")

    # --- the struct can hold the answer --------------------------------------
    check("uint32_t scaledFrames;" in header and "float scaledFps;" in header,
          "the video stats struct has a place for scaled frames and their rate")
    check("uint32_t scaledOutputWidth;" in header and "uint32_t scaledOutputHeight;" in header,
          "the video stats struct can also say what size the scaler wrote")
    check(header.count("uint32_t scaledFrames;") == 1
          and header.count("float scaledFps;") == 1,
          "the scaled tally is declared once, not aliased over an existing counter")

    # --- the decision is one file-scope function -----------------------------
    check(decider.count("return") == 4,
          "%s answers for every shape of present (%d returns)" % (DECIDER, decider.count("return")))
    check(renderer.index("@interface VideoDecoderRenderer") > renderer.index(DECIDER),
          "%s is file scope, so the two scalers cannot drift apart" % DECIDER)
    check(KIND + "None" in kinds and KIND + "MetalFX" in kinds and KIND + "VideoToolbox" in kinds,
          "the decision names both scalers and the case of neither")
    check("scalerOutputWidth <= scalerInputWidth" in decider
          and "scalerOutputHeight <= scalerInputHeight" in decider,
          "a present whose sizes did not grow is refused, so the tally means invented pixels")
    check(block.count("MLHardwareScaledEvidenceForPresentedFrame(") == 1,
          "one reading of the decision moves the counters")
    check("_activeWndVideoStats.scaledFrames += 1;" in block
          and "scalingEvidence.outputWidth;" in block,
          "the charge records the size beside the count")
    check(block.count(used_metalfx_marker()) == 1,
          "MetalFX answers for its own encode (%d)" % block.count(used_metalfx_marker()))
    check("processedFrame != NULL" in block,
          "the Video Toolbox scaler is recognised by the enlarged buffer it handed back")

    # --- and only a Video Toolbox run can hand back that buffer --------------
    processor = method_definition(
        renderer, "- (CVImageBufferRef)copyFrameUsingFrameProcessorIfNeeded:")
    check("engine != MLActiveVideoEnhancementEngineVTLowLatencySuperResolution" in processor
          and PROCESSOR_GUARD in processor,
          "the frame processor returns nothing for every engine but the Video Toolbox ones, "
          "so a non-NULL buffer is the scaler's own output")

    # --- the window that closes publishes the rate ---------------------------
    closed = re.search(
        "if [(]now - self->_activeWndVideoStats.measurementStartTimestamp >= 1000[)] [{](.*?)^        [}]",
        renderer, re.S | re.M)
    check(closed is not None, "the measurement window still closes and reports")
    window = closed.group(1) if closed else ""
    check("scaledFps = (float)self->_activeWndVideoStats.scaledFrames;" in window,
          "the closed window reports the scaled tally as a rate")
    check("scaledFps = (float)self->_activeWndVideoStats.renderedFrames" not in window
          and "scaledFps = (float)self->_activeWndVideoStats.interpolatedFrames" not in window,
          "the scaled rate is not another counter wearing its name")
    check("memset(&self->_activeWndVideoStats, 0, sizeof(VideoStats));" in window,
          "the whole struct is zeroed, so the tally resets with the window it reports")

    # --- and somebody reads it ----------------------------------------------
    check("stats.scaledFps" in overlay and "stats.scaledFrames" in overlay,
          "the overlay reads the scaled tally rather than restating a setting")
    gate = re.search("if [(]scaledFps > ([^" + chr(10) + "{]*)[{](.*?)^    [}]", overlay, re.S | re.M)
    check(gate is not None, "the overlay only speaks about scaling when there is a number to speak about")
    check(gate is not None and 'MLString(@"' + LABEL + '"' in gate.group(2)
          and "+%.1f" in gate.group(2),
          "the line names the tally and shows the rate")
    check(gate is not None and "stats.scaledOutputWidth" in gate.group(2)
          and "stats.scaledOutputHeight" in gate.group(2),
          "the line also shows the size the scaler wrote, which is the half a count cannot give")
    condition = "scaledFps > " + gate.group(1) if gate else ""
    check("scaledOutputWidth > 0" in condition and "scaledOutputHeight > 0" in condition,
          "the size is only asked for when there is a size, so no window can read 0x0")
    check(overlay.count('MLString(@"' + LABEL + '"') == 1,
          "the tally is named once on the overlay (%d)" % overlay.count('MLString(@"' + LABEL + '"'))

    l10n_en = read("Limelight/macOS/en.lproj/Localizable.strings")
    l10n_zh = read("Limelight/macOS/zh-Hans.lproj/Localizable.strings")
    check('"' + LABEL + '" = "' + LABEL + '";' in l10n_en and '"' + LABEL + '" = "' in l10n_zh,
          "the tally has wording in both languages")

    # --- play the shipping bookkeeping ---------------------------------------
    cc, sdk = apple_toolchain.clang_and_sdk("scaling output evidence")
    source = build(kinds, evidence, decider, block, helper)
    with tempfile.TemporaryDirectory() as work:
        rows, log = compiled(source, work, "evidence", cc, sdk)
        check(rows is not None,
              "the shipping present bookkeeping compiles" if rows is not None
              else "the shipping present bookkeeping must compile:%s" % log)
    if rows is None:
        return finish()

    seen, checked, cover = reading(rows)
    check(checked == 360 and len(seen) == 6,
          "%d presents of the shipping text across %d scenarios" % (checked or -1, len(seen)))
    check(seen.get("metalfx") == (60, 3840, 2160),
          "60 frames MetalFX resampled to the panel count 60 and report 3840x2160 (%s)"
          % (seen.get("metalfx"),))
    check(seen.get("video-toolbox") == (60, 2560, 1440),
          "60 frames the Video Toolbox processor enlarged count 60 and report its own output (%s)"
          % (seen.get("video-toolbox"),))
    check(seen.get("bilinear") == (0, 0, 0),
          "60 presents stretched by the blit into a bigger drawable count nothing (%s)"
          % (seen.get("bilinear"),))
    check(seen.get("exact-fit") == (0, 0, 0),
          "a scaler that was handed exactly the size it was given reports nothing (%s)"
          % (seen.get("exact-fit"),))
    check(seen.get("one-axis") == (0, 0, 0),
          "a scaler that widened a frame without heightening it reports nothing (%s)"
          % (seen.get("one-axis"),))
    check(seen.get("mixed") == (40, 2560, 1440),
          "30 MetalFX plus 10 Video Toolbox plus 20 plain presents count 40, not 90 (%s)"
          % (seen.get("mixed"),))
    check(cover is not None and int(cover.get("metalfx", 0)) > 0
          and int(cover.get("video-toolbox", 0)) > 0 and int(cover.get("plain", 0)) > 0
          and int(cover.get("sized", 0)) > 0,
          "both scalers and the case of neither were actually run (%s)" % (cover,))

    # --- the assertions have to be the thing that fails ----------------------
    # The caller is what separates a frame a scaler wrote from a frame the blit
    # stretched. Ask the draw pass to believe every present was MetalFX and a plain
    # stretch is charged as scaling, while the Video Toolbox frames -- already
    # enlarged before the pass -- stop being charged at all.
    blind = block.replace("        if (usedMetalFX) {", "        if (YES) {")
    check(blind != block,
          "the mutation that charges a stretch no scaler made has to be a real edit")
    run_compiled("charges a stretch no scaler made", kinds, evidence, decider, blind, helper, cc, sdk,
                 {"bilinear": (60, 3840, 2160), "video-toolbox": (0, 0, 0),
                  # 30 plus 20, the 10 enlarge-and-show frames not. The size is the
                  # rectangle the scaler wrote, which for a 16:9 stream in a 2560x2160
                  # drawable is 2560x1440: the scaler is no longer handed the drawable,
                  # because drawable-sized output is a picture already stretched out of
                  # its shape. bilinear keeps 3840x2160 -- that drawable is 16:9 too.
                  "mixed": (50, 2560, 1440)})

    # And the counters have to follow the decision rather than the draw call.
    mute = block.replace("        if (scalingEvidence.reachedDisplay) {", "        if (YES) {")
    check(mute != block,
          "the mutation that counts presents where the scaler wrote nothing has to be a real edit")
    run_compiled("counts presents where the scaler wrote nothing", kinds, evidence, decider, mute, helper, cc, sdk,
                 {"bilinear": (60, 0, 0), "exact-fit": (60, 0, 0), "one-axis": (60, 0, 0)})

    greedy = decider.replace(
        "    if (scalerOutputWidth <= scalerInputWidth || scalerOutputHeight <= scalerInputHeight) {\n"
        "        return evidence;\n    }\n", "")
    check(greedy != decider,
          "the mutation that counts a scaler that invented no pixels has to be a real edit")
    run_compiled("counts a scaler that invented no pixels", kinds, evidence, greedy, block, helper, cc, sdk,
                 # A 1280x720 stream in a 3840x720 drawable fits to 1280x720: the
                 # drawable was only wider, never taller, so there is nothing to
                 # invent. The mutation has to show that as scaling to be caught.
                 {"exact-fit": (60, 1920, 1080), "one-axis": (60, 1280, 720)})

    sizeless = evidence.replace("    uint32_t outputWidth;", "    uint32_t outputWidthUnused;")
    check(sizeless != evidence,
          "the mutation that drops the scaler's output size has to be a real edit")

    forgotten = block.replace("            _activeWndVideoStats.scaledOutputWidth = scalingEvidence.outputWidth;"
                              + chr(10), "")
    forgotten = forgotten.replace("            _activeWndVideoStats.scaledOutputHeight = scalingEvidence.outputHeight;"
                                  + chr(10), "")
    check(forgotten != block,
          "the mutation that counts without recording the size has to be a real edit")
    run_compiled("counts without recording the size", kinds, evidence, decider, forgotten, helper, cc, sdk,
                 {"metalfx": (60, 0, 0), "video-toolbox": (60, 0, 0)})

    lying = window.replace("scaledFps = (float)self->_activeWndVideoStats.scaledFrames;",
                           "scaledFps = (float)self->_activeWndVideoStats.renderedFrames;")
    check(lying != window,
          "the mutation that reports the source rate as scaling has to be a real edit")
    check("scaledFps = (float)self->_activeWndVideoStats.scaledFrames;" not in lying,
          "the window assertion fails when the rate is copied from another counter")

    mute = overlay.replace("if (scaledFps > 0.05f && stats.scaledOutputWidth > 0", "if (YES")
    check(mute != overlay,
          "the mutation that always shows the tally has to be a real edit")
    check(re.search("if [(]scaledFps > ([^" + chr(10) + "{]*)[{]", mute) is None,
          "the wiring assertion fails when the line loses its condition")

    trusting = processor.replace("    if (" + PROCESSOR_GUARD + chr(10) + "    }" + chr(10), "")
    check(trusting != processor,
          "the mutation that lets the frame processor answer for a non-Video-Toolbox engine "
          "has to be a real edit")
    check("engine != MLActiveVideoEnhancementEngineVTLowLatencySuperResolution" not in trusting,
          "the guard assertion fails when a buffer stops meaning the scaler ran")

    return finish()


def used_metalfx_marker():
    return "if (usedMetalFX) {"


# The path is spelled at the call rather than parked in a constant: the audit that
# lets this gate ride this step looks for the name and the invocation on the same
# line, because a name in a constant proves nothing about whether anything runs it.


def run_aspect_fit():
    """The shape of the picture inside the window, which is the other half of these sizes.

    This file asks what a scaler wrote; that one asks where the result is drawn. They
    are the one decision seen from two ends -- a scaler handed the drawable, or a blit
    told to cover it, produces sizes that are both true and a picture that is stretched
    -- so the two run together. It also matters practically: a gate that needs a real
    clang and a macOS SDK cannot run in the Ubuntu audits job, so it needs a step on a
    macOS runner, and adding a step means a token with the `workflow` scope, which the
    pushing credential here does not have. Riding the neighbouring step is the honest
    way to be executed by CI in the meantime, and it is what
    constraints-audit.py's DRIVEN_BY records rather than letting the gate look covered
    while nothing on a runner ever invokes it.
    """
    ran = subprocess.run([sys.executable, "scripts/aspect-fit-presentation-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "the picture keeps its shape in a window of another shape"
          if ran.returncode == 0 else
          "the aspect-fit gate failed:\n" + chr(10).join(tail))


def run_device_redirection_policy():
    """The refusal that decides whether a USB device may be offered to a host at all.

    Nothing here scales a frame, so the question is why it runs here: the policy is
    Objective-C, so its gate needs a real clang and a macOS SDK, which the Ubuntu audits
    job does not have, and giving it its own step needs a push credential with the
    `workflow` scope, which this one does not. Riding a step every macOS build already
    runs is the way to be executed by CI in the meantime, and constraints-audit.py's
    DRIVEN_BY writes that down rather than letting the gate look covered while nothing on
    a runner invokes it. The same reason holds for the aspect-fit gate above; both are
    listed there, and both are checked against the step that actually runs them.
    """
    ran = subprocess.run([sys.executable, "scripts/device-redirection-policy-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "a device is refused unless a rule earns the yes"
          if ran.returncode == 0 else
          "the device redirection policy gate failed:\n" + chr(10).join(tail))


def run_pointer_entry_policy():
    """Whether a pointer sliding into the stream window is allowed to take it.

    Not a scaling question either, and it rides here for the same two reasons as the
    aspect-fit gate above: the decision is C called from Objective-C, so the harness needs
    the macOS job's clang and SDK, and its own step needs the `workflow` scope this pushing
    credential does not have. constraints-audit.py's DRIVEN_BY records the arrangement, and
    the audit refuses the entry if the step stops invoking it.
    """
    ran = subprocess.run([sys.executable, "scripts/pointer-entry-takeover-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "a hover only takes the window when the player allowed it"
          if ran.returncode == 0 else
          "the pointer entry policy gate failed:\n" + chr(10).join(tail))


def run_usb_device_enumeration():
    """What the bus can honestly be read as before any device reaches a host.

    The first stage of the same work as the policy gate above, so it rides here for the same
    two reasons: reading a device identity is Objective-C, so the harness needs the macOS
    job's clang and SDK, and a step of its own needs the `workflow` scope this pushing
    credential does not carry. constraints-audit.py's DRIVEN_BY records the arrangement
    rather than letting the gate look covered while no runner invokes it.
    """
    ran = subprocess.run([sys.executable, "scripts/usb-device-enumeration-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "a device on the bus is named by digest and never by serial"
          if ran.returncode == 0 else
          "the usb device enumeration gate failed:\n" + chr(10).join(tail))


def run_device_redirection_session():
    """The order a device may be handed over in, checked against a host that does not exist.

    Stage 2's client half. No host implements the three exchanges, so the question is why CI runs
    it at all: sequencing is the part this repository can get right today, and a gate that only a
    real host could settle would be a gate nobody can add. It rides here for the same two reasons
    as the enumeration gate above -- Objective-C against the macOS SDK, and no `workflow` scope on
    this credential for a step of its own -- and constraints-audit.py's DRIVEN_BY writes it down.
    """
    ran = subprocess.run([sys.executable, "scripts/device-redirection-session-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "a device never reaches a host that has not been asked for room"
          if ran.returncode == 0 else
          "the device redirection session gate failed:\n" + chr(10).join(tail))


def run_driver_lifecycle():
    """What a driver extension that has not shipped may be trusted to have done.

    Stage 3's logic, and stage 3 itself is blocked on a signing identity, so nothing here loads
    anything: the gate covers installs that time out, crashes that keep what they held, and a
    replugged device that must not inherit the last session's answer. Objective-C against the
    macOS SDK, and no `workflow` scope for a step of its own -- the same two reasons as above.
    """
    ran = subprocess.run([sys.executable, "scripts/driver-lifecycle-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "an unloadable extension is never counted as one that works"
          if ran.returncode == 0 else
          "the driver lifecycle gate failed:\n" + chr(10).join(tail))


def run_usb_bus_snapshot():
    """Which registry nodes belong to one device, checked against the bus the runner has.

    The step the enumeration gate leaves to its caller, and the step a measurement says the
    obvious way of doing is wrong: the interface iterator returned 11 of the 16 interfaces the
    devices named under themselves. Objective-C against the macOS SDK, and no `workflow` scope on
    this credential for a step of its own -- the same two reasons as the gates above, written into
    constraints-audit.py's DRIVEN_BY.
    """
    ran = subprocess.run([sys.executable, "scripts/usb-bus-snapshot-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "an interface lands on the device it names, and the bus is read without being touched"
          " (%s)" % " | ".join(tail))


def run_code_signature_profile():
    """What this build may claim about its own signature, which is what the panel may show.

    Stage 3 waits on a signing identity, so the only honest line the devices panel can put above a
    list of refusals is one read from the running binary. It rides here for the same two reasons
    as the gates above, and the gate runs its classifier against three generated certificates plus
    the harness's own signature.
    """
    ran = subprocess.run([sys.executable, "scripts/code-signature-profile-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "an ad-hoc build cannot talk itself into a driver extension"
          " (%s)" % " | ".join(tail))


def run_device_redirection_panel_model():
    """What the devices panel may claim, and about which device.

    The panel is where stage 2 and stage 3 meet a player: four preconditions have to be true at the
    same moment, and the panel has to say which one is still missing instead of listing refusals as
    though the devices were broken. Objective-C against the macOS SDK, so it rides here for the same
    two reasons as the gates above -- and it is also the first consumer of the two layers before it,
    which is what turns their audit lines from dead code into the thing a screen shows.
    """
    ran = subprocess.run([sys.executable, "scripts/device-redirection-panel-model-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "the devices panel refuses the same way the policy does, and names what is missing"
          if ran.returncode == 0 else
          "the devices panel gate failed:\n" + chr(10).join(tail))


def run_driver_extension_signing():
    """Whether anything in the tree could be loaded by a player at all.

    Not a scaling question, and it needs no toolchain: it reads the committed file list and the
    workflow text. It rides here for one reason only -- a gate needs a CI step, and a step needs the
    `workflow` scope this credential does not carry. constraints-audit.py's DRIVEN_BY records the
    arrangement, and the audit refuses its own entry if the step stops invoking it.
    """
    ran = subprocess.run([sys.executable, "scripts/driver-extension-signing-audit.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "no driver extension ships that a player could not load"
          if ran.returncode == 0 else
          "the driver extension signing audit failed:\n" + chr(10).join(tail))


def run_hdr_sdr_exposure():
    """The exposure each HDR-to-SDR policy applies, and where that number is allowed to live.

    Not a scaling question either. It rides here for the same two reasons as the gates below
    it: the answer is C inside the renderer, so its harness wants the macOS job's clang and
    SDK, and a step of its own wants the `workflow` scope this pushing credential does not
    carry. constraints-audit.py's DRIVEN_BY records it, and now also refuses an entry whose
    call sits in a function the driver never reaches.
    """
    ran = subprocess.run([sys.executable, "scripts/hdr-sdr-exposure-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "every tone mapping policy states the exposure it applies"
          if ran.returncode == 0 else
          "the hdr sdr exposure gate failed:\n" + chr(10).join(tail))


def run_settings_rebuild_passthrough():
    """Whether each hand-copied settings rebuild carries the field its name asks for.

    Not a scaling question, and not here for the clang reason the gates above it are: this one
    reads Swift text and needs no toolchain at all. It rides this driver for the other half of
    the reason -- a step of its own needs the `workflow` scope the pushing credential does not
    carry -- and this driver is a step on every macOS build. constraints-audit.py's DRIVEN_BY
    says so, and refuses an entry whose call sits in a function the driver never reaches.
    """
    ran = subprocess.run([sys.executable, "scripts/settings-rebuild-passthrough-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "every settings rebuild carries the field its own name asks for"
          if ran.returncode == 0 else
          "the settings rebuild passthrough gate failed:\n" + chr(10).join(tail))


def run_gamepad_menu_gesture():
    """Ride the controller gesture gate on a macOS job, the way its siblings do.

    The gate needs a real clang and a macOS SDK to compile the shipping decision, so it
    cannot run in the Ubuntu audits job, and a step of its own would need the `workflow`
    scope this pushing credential does not carry. constraints-audit.py's DRIVEN_BY records
    the arrangement rather than letting a gate look covered while nothing invokes it.
    """
    ran = subprocess.run([sys.executable, "scripts/gamepad-menu-gesture-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "a long Menu hold changes mouse mode only when the player allowed it"
          if ran.returncode == 0 else "the gamepad menu gesture gate failed:\n" + chr(10).join(tail))


def run_settings_callback_ownership():
    """Ride the settings callback ownership gate on a macOS job, like its siblings.

    The gate compiles the two closures the settings page hands its model and counts
    whether the model is released, so it needs a swiftc and an SDK, and a step of its own
    would need the `workflow` scope this pushing credential does not carry.
    constraints-audit.py's DRIVEN_BY records the arrangement.
    """
    ran = subprocess.run([sys.executable, "scripts/settings-callback-ownership-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "a settings page that closes takes its model with it"
          if ran.returncode == 0 else
          "the settings callback ownership gate failed:\n" + chr(10).join(tail))



def run_timer_registration():
    """Ride the run loop timer measurement on a macOS job, like the gates above it.

    The gate compiles and runs four repeating timers against a real AppKit, so it needs a
    clang, an SDK and a run loop, and a step of its own would need the `workflow` scope this
    pushing credential does not carry. constraints-audit.py's DRIVEN_BY records that, and
    refuses the entry if the call below ever stops being reachable from this driver's finish.
    """
    ran = subprocess.run([sys.executable, "scripts/timer-registration-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "a repeating timer fires in every mode the app runs its loop in during a stream"
          if ran.returncode == 0 else
          "the timer registration gate failed:\n" + chr(10).join(tail))


def run_command_to_control():
    """Ride the Command mapping gate on a macOS job, the way its siblings do.

    The gate compiles the shipping mapping with a real clang and a macOS SDK, so it cannot
    run in the Ubuntu audits job, and a step of its own would need the `workflow` scope this
    pushing credential does not carry. constraints-audit.py's DRIVEN_BY records the
    arrangement rather than letting a gate look covered while nothing invokes it.
    """
    ran = subprocess.run([sys.executable, "scripts/command-to-control-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "one switch says what a Command key means on the host, on every keyboard path"
          if ran.returncode == 0 else "the command-to-control gate failed:\n" + chr(10).join(tail))


def run_sdr_10bit_codec():
    """Ride the 10-bit SDR negotiation gate on a macOS job, beside its HDR sibling.

    The gate compiles the shipping negotiation with a real clang against the core
    headers, so it cannot run in the Ubuntu audits job, and a step of its own would
    need the `workflow` scope this pushing credential does not carry.
    constraints-audit.py's DRIVEN_BY records the arrangement.
    """
    ran = subprocess.run([sys.executable, "scripts/sdr-10bit-codec-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "10-bit samples can carry an SDR picture without the picture changing"
          if ran.returncode == 0 else "the sdr-10bit-codec gate failed:\n" + chr(10).join(tail))


def run_sas_preset():
    """Ride the secure-attention-sequence preset gate on the same step.

    It reads Swift and Objective-C text and wants no toolchain, but a gate nobody invokes is
    a gate that reads as covered. constraints-audit.py's DRIVEN_BY says who runs it.
    """
    ran = subprocess.run([sys.executable, "scripts/sas-preset-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "the button that offers Ctrl+Alt+Del offers the chord the host reads"
          if ran.returncode == 0 else "the sas-preset gate failed:\n" + chr(10).join(tail))


def run_diagnostics_report():
    """Ride the diagnostics report gate on the same step.

    The report is compiled Objective-C with a harness of its own, so its harness wants the
    macOS clang and SDK this job has and the audit runner does not, and a step of its own
    would want the `workflow` scope the pushing credential does not carry. It is the gate
    that decides whether a PIN or a certificate can leave the machine inside a bug report,
    so it runs on every build rather than on somebody's memory.
    """
    ran = subprocess.run([sys.executable, "scripts/diagnostics-report-tests.py"],
                         cwd=ROOT, capture_output=True, text=True)
    tail = (ran.stdout + ran.stderr).strip().splitlines()[-3:]
    check(ran.returncode == 0,
          "the diagnostics report helps a maintainer without carrying the player's secrets"
          if ran.returncode == 0 else "the diagnostics-report gate failed:\n" + chr(10).join(tail))



def finish():
    run_aspect_fit()
    run_device_redirection_policy()
    run_pointer_entry_policy()
    run_usb_device_enumeration()
    run_device_redirection_session()
    run_driver_lifecycle()
    run_usb_bus_snapshot()
    run_code_signature_profile()
    run_device_redirection_panel_model()
    run_driver_extension_signing()
    run_hdr_sdr_exposure()
    run_settings_rebuild_passthrough()
    run_gamepad_menu_gesture()
    run_timer_registration()
    run_command_to_control()
    run_settings_callback_ownership()
    run_sas_preset()
    run_sdr_10bit_codec()
    run_diagnostics_report()

    print("%d scaling-output-evidence failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
