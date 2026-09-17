#!/usr/bin/env python3
"""Prove the interpolator's output is counted, and counted where it can be seen.

Frame interpolation either makes frames or it does not, and until now the app could
not say which. Nothing anywhere counted a produced frame, and the one counter a
player can read -- Rd on the performance overlay -- is fed only when the frame being
drawn is a source frame, so a stream being doubled to 120 FPS reported 60 Rd, which
is the same line a stream that is not being doubled reports. "Is it working?" had no
answer on the machine where it is running.

The answer is one decision, because both kinds of frame leave through the same
drawable and a present has to pick a counter. The pick matters in both directions:
charge an interpolated frame to the rendered counter and it is timed from its
neighbour's enqueue stamp, gains an 8ms cadence nobody streamed, and doubles the
frame count the host never sent; count nothing instead and the work stays invisible.

So the decision is compiled here out of the shipping source and played, and the text
that runs is the product's own: the block that picks and applies the counters is
lifted out of VideoDecoderRenderer.m and executed against a fake renderer, with the
stub incrementing the rendered count exactly as the real recorder does. A driver
written beside the product would have proved only that the driver works.

Reading the number is the other half, so the wiring is checked as well: the window
that closes has to publish the tally as a rate, the overlay has to read it and say it
only when there is something to say, and Rd has to stay the source-frame figure.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
RENDERER = "Limelight/Stream/VideoDecoderRenderer.m"
STATS_HEADER = "Limelight/Stream/VideoDecoderRenderer.h"
OVERLAY = "Limelight/macOS/ViewControllers/StreamViewController+Diagnostics.m"
ENUM = "MLPresentedFrameAccounting"
DECIDER = "MLAccountingForPresentedFrame"
LABEL = "Interpolated"

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


def options_block(text, name):
    """The shipping NS_OPTIONS declaration, enumerators included."""
    match = re.search("^typedef NS_OPTIONS[(][^)]*" + name , text, re.M)
    assert match, "no NS_OPTIONS declaration for " + name
    return brace_span(text, match.start()) + ";"


def inline_function(text, name):
    """The shipping text of a static inline function, signature included."""
    match = re.search("^static inline [^(]*" + name, text, re.M)
    assert match, "no inline definition of " + name
    return brace_span(text, match.start())


def accounting_block(text):
    """The product's own counter bookkeeping for one present, verbatim.

    It stops after the recorder is asked, because what follows is the once-per-stream
    first-present log, which has nothing to say about counting. The brace the cut
    removes is closed again by the text that is added back.
    """
    start = text.index(ENUM + " accounting =")
    end = text.index("[self recordRenderedFrameSampleAtTimeMs:presentMs", start)
    end = text.index(";", end) + 1
    return text[start:end] + chr(10) + "        }"


def recorder_body(text, name):
    """The body of the first definition of name, skipping the forward declaration.

    The header of the method appears twice in the file, once as a declaration the
    compiler is told about and once as the thing that runs. Only the second one can
    show where the count is taken, so the two are told apart by whichever terminator
    comes first: a semicolon means the declaration, a brace means the definition.
    """
    pattern = "- [(]void[)]" + name
    for match in re.finditer(pattern, text):
        semicolon = text.find(";", match.start())
        brace = text.find("{", match.start())
        if 0 <= brace < semicolon:
            return brace_span(text, match.start())
    raise AssertionError("no definition of " + name)


def compiled(source, work, name, cc, sdk):
    path = os.path.join(work, name + ".m")
    open(path, "w", encoding="utf-8").write(source)
    command = [cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
               "-framework", "Foundation", path, "-o", os.path.join(work, name)]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr).strip()[-1600:]
    ran = subprocess.run([os.path.join(work, name)], capture_output=True, text=True)
    return ran.stdout, (ran.stdout + ran.stderr).strip()[-1600:]


def reading(stdout):
    """{scenario: (rendered, interpolated)} plus the coverage the run reported."""
    rows, checked = {}, None
    for line in stdout.splitlines():
        fields = line.split()
        if fields[:1] == ["checked"]:
            checked = int(fields[1])
        elif fields[:1] == ["scenario"]:
            rows[fields[1]] = (int(fields[2]), int(fields[3]))
    return rows, checked


DRIVER = r"""
#import <Foundation/Foundation.h>

// The two counters the shipping struct gained, and only those. The rest of VideoStats
// describes timings a fake cannot reproduce, and none of it is what is being asked.
typedef struct {
    uint32_t renderedFrames;
    uint32_t interpolatedFrames;
} FakeVideoStats;

static FakeVideoStats _activeWndVideoStats;
static int g_checked;

static uint64_t LiGetMillis(void) {
    static uint64_t now = 0;
    now += 8;
    return now;
}

@interface FakeRenderer : NSObject
- (void)recordRenderedFrameSampleAtTimeMs:(uint64_t)renderSampleNowMs
                            enqueueTimeMs:(uint64_t)enqueueTimeMs;
@end

@implementation FakeRenderer
// The shipping recorder does three things. The one a count depends on is this one, and
// the sweep next door asserts the real recorder still does it.
- (void)recordRenderedFrameSampleAtTimeMs:(uint64_t)renderSampleNowMs
                            enqueueTimeMs:(uint64_t)enqueueTimeMs {
    (void)renderSampleNowMs;
    (void)enqueueTimeMs;
    _activeWndVideoStats.renderedFrames++;
}
@end

@@ENUM@@

@@DECIDER@@

// One present, booked the way the renderer books it.
static void present(FakeRenderer *self,
                    BOOL presentingInterpolatedFrame,
                    NSUInteger presentedCount,
                    uint64_t frameEnqueueTimeMs) {
    @@BLOCK@@
}

static void scenario(const char *name,
                     int sourcePresents,
                     int interpolatedPresents,
                     int redraws) {
    FakeRenderer *renderer = [[FakeRenderer alloc] init];
    _activeWndVideoStats = (FakeVideoStats){0};
    for (int index = 0; index < sourcePresents; index++) {
        // A source frame the display has not seen, then the frame made from it, the
        // way the enhanced draw pass alternates the two.
        present(renderer, NO, 1, 1000 + (uint64_t)index * 16);
        g_checked++;
        if (index < interpolatedPresents) {
            present(renderer, YES, 0, 1000 + (uint64_t)index * 16);
            g_checked++;
        }
    }
    for (int index = 0; index < redraws; index++) {
        // The same frame drawn again while nothing new arrives. The overlay refreshes
        // far more often than the stream produces, so this is the common case, and a
        // tally that grew here would report frames nobody made.
        present(renderer, NO, 0, 1000 + (uint64_t)index * 16);
        g_checked++;
    }
    printf("scenario %s %u %u", name,
           _activeWndVideoStats.renderedFrames,
           _activeWndVideoStats.interpolatedFrames);
    puts("");
}

int main(void) {
    scenario("doubled", 60, 60, 0);
    scenario("off", 60, 0, 0);
    scenario("redrawn", 4, 4, 25);
    printf("checked %d", g_checked);
    puts("");
    return 0;
}
"""


def run_mutation(label, options, decider, block, cc, sdk, expect):
    """Plant one wrong answer and require the sweep to see exactly that."""
    source = (DRIVER.replace("@@ENUM@@", options)
                   .replace("@@DECIDER@@", decider)
                   .replace("@@BLOCK@@", block))
    with tempfile.TemporaryDirectory() as work:
        rows, log = compiled(source, work, "bad", cc, sdk)
        check(rows is not None,
              "the mutation that %s compiles" % label if rows is not None
              else "the mutation that %s must compile:%s" % (label, log))
        if rows is None:
            return
        seen, _count = reading(rows)
        check(seen.get("doubled") == expect,
              "the sweep sees a run that %s (%s, expected %s)"
              % (label, seen.get("doubled"), expect))
        check(seen.get("doubled") != (60, 60),
              "the count assertion fails when a run %s" % label)


def main():
    renderer = read(RENDERER)
    header = read(STATS_HEADER)
    overlay = read(OVERLAY)

    decider = inline_function(renderer, DECIDER)
    options = options_block(renderer, ENUM)
    block = accounting_block(renderer)

    print("-- what the interpolator produced, and who is told --")

    # --- the struct has to be able to hold the answer -------------------------
    check("uint32_t interpolatedFrames;" in header and "float interpolatedFps;" in header,
          "the video stats struct has a place for produced frames and their rate")
    check("uint32_t renderedFrames;" in header,
          "the source-frame counter is still there, untouched")
    check(ENUM in block and ENUM + "Interpolated" in options,
          "the tally has a named decision behind it, not an inline guess")

    # --- the decision is one function, asked once -----------------------------
    check(decider.count("return") == 3,
          "%s answers for every shape of present (%d returns)" % (DECIDER, decider.count("return")))
    check(renderer.index("@interface VideoDecoderRenderer") > renderer.index(DECIDER),
          "%s is file scope, so the two counters cannot drift apart" % DECIDER)
    check(block.count("accounting &") == 2,
          "one reading of the decision drives both counters (%d applied)" % block.count("accounting &"))
    check(ENUM + "Interpolated) {" in block
          and "_activeWndVideoStats.interpolatedFrames++;" in block,
          "the interpolated counter is the thing the interpolated bit moves")
    check(ENUM + "Rendered) {" in block
          and "[self recordRenderedFrameSampleAtTimeMs:presentMs" in block,
          "the pipeline metrics still follow the rendered bit, and only it")

    # --- an interpolated frame must not look like a first source frame --------
    first_present = re.search("NSUInteger presentedCount = 0;.{0,400}_enhancedStartupPresentedFrameCount",
                              renderer, re.S)
    check(first_present is not None and "presentingInterpolatedFrame" in first_present.group(0),
          "a present of interpolated pixels never advances the source-frame counter")
    recorder = recorder_body(renderer, "recordRenderedFrameSampleAtTimeMs")
    check("_activeWndVideoStats.renderedFrames++" in recorder,
          "the recorder still owns the rendered count, so moving the pick cannot lose it")

    # --- the window that closes publishes the tally ---------------------------
    closed = re.search("if [(]now - self->_activeWndVideoStats.measurementStartTimestamp >= 1000[)] [{](.*?)^        [}]",
                       renderer, re.S | re.M)
    check(closed is not None, "the measurement window still closes and reports")
    window = closed.group(1) if closed else ""
    check("interpolatedFps = (float)self->_activeWndVideoStats.interpolatedFrames;" in window,
          "the closed window reports the tally as a rate")
    check("interpolatedFps = (float)self->_activeWndVideoStats.renderedFrames" not in window,
          "the tally is not the source-frame rate wearing its name")
    check("memset(&self->_activeWndVideoStats, 0, sizeof(VideoStats));" in window,
          "the whole struct is zeroed, so the tally resets with the window it reports")

    # --- and somebody reads it ------------------------------------------------
    check("stats.interpolatedFps" in overlay and "stats.interpolatedFrames" in overlay,
          "the overlay reads the tally rather than restating a setting")
    gate = re.search("if [(]interpolatedFps > [0-9.]+f[)] [{](.*?)^    [}]", overlay, re.S | re.M)
    check(gate is not None, "the overlay only speaks when there is a number to speak about")
    check(gate is not None and 'MLString(@"' + LABEL + '"' in gate.group(1)
          and "+%.1f" in gate.group(1),
          "the line names the tally and shows the rate, signed so it cannot read as a total")
    rd = overlay.index('append(@" Rd"')
    check("interpolatedFps" not in overlay[max(0, rd - 400):rd],
          "Rd is still built from the source-frame figure, so a doubled stream is not mislabelled")
    check(overlay.count('MLString(@"' + LABEL + '"') == 1,
          "the tally is named once on the overlay (%d)" % overlay.count('MLString(@"' + LABEL + '"'))

    l10n_en = read("Limelight/macOS/en.lproj/Localizable.strings")
    l10n_zh = read("Limelight/macOS/zh-Hans.lproj/Localizable.strings")
    check('"' + LABEL + '" = "' + LABEL + '";' in l10n_en and '"' + LABEL + '" = "' in l10n_zh,
          "the tally has wording in both languages")

    # --- play the shipping bookkeeping ---------------------------------------
    cc, sdk = apple_toolchain.clang_and_sdk("interpolated frame counting")
    source = (DRIVER.replace("@@ENUM@@", options)
                   .replace("@@DECIDER@@", decider)
                   .replace("@@BLOCK@@", block))
    with tempfile.TemporaryDirectory() as work:
        rows, log = compiled(source, work, "counting", cc, sdk)
        check(rows is not None,
              "the shipping present bookkeeping compiles" if rows is not None
              else "the shipping present bookkeeping must compile:%s" % log)
    if rows is None:
        return finish()

    seen, checked = reading(rows)
    check(checked == 213 and len(seen) == 3,
          "%d presents of the shipping text across %d scenarios" % (checked or -1, len(seen)))
    check(seen.get("doubled") == (60, 60),
          "60 source frames plus 60 interpolated frames count as 60 and 60, not 120 (%s)"
          % (seen.get("doubled"),))
    check(seen.get("off") == (60, 0),
          "a stream nobody interpolates counts 0 interpolated frames (%s)" % (seen.get("off"),))
    check(seen.get("redrawn") == (4, 4),
          "25 refreshes over the same frame invent nothing (%s)" % (seen.get("redrawn"),))

    # --- the assertions have to be the thing that fails ----------------------
    charged = decider.replace("return " + ENUM + "Interpolated;",
                              "return " + ENUM + "Rendered;")
    check(charged != decider,
          "the mutation that charges interpolated pixels at Rd has to be a real edit")
    run_mutation("charges interpolated pixels at Rd", options, charged, block, cc, sdk, (120, 0))

    silent = block.replace("            _activeWndVideoStats.interpolatedFrames++;" + chr(10), "")
    check(silent != block,
          "the mutation that never increments the tally has to be a real edit")
    run_mutation("never increments the tally", options, decider, silent, cc, sdk, (60, 0))

    lying = window.replace("interpolatedFps = (float)self->_activeWndVideoStats.interpolatedFrames;",
                           "interpolatedFps = (float)self->_activeWndVideoStats.renderedFrames;")
    check(lying != window,
          "the mutation that reports the source rate as interpolation has to be a real edit")
    check("interpolatedFps = (float)self->_activeWndVideoStats.interpolatedFrames;" not in lying,
          "the window assertion fails when the rate is copied from the source counter")

    mute = overlay.replace("if (interpolatedFps > 0.05f) {", "if (YES) {")
    check(mute != overlay,
          "the mutation that always shows the tally has to be a real edit")
    check(re.search("if [(]interpolatedFps > [0-9.]+f[)] [{]", mute) is None,
          "the wiring assertion fails when the line loses its condition")

    return finish()


def finish():
    print("%d interpolated-frame-count failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
