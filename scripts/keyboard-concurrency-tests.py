#!/usr/bin/env python3
"""Prove that two keys held at once reach the host as two independent keys.

The report that started this work was not a stack trace, it was a game: pressing
W and Space together -- walk and jump, the two most basic inputs there are --
behaved as one key interfering with the other. That symptom cannot be checked by
compiling, and it cannot be checked by asserting that a set exists somewhere in
the source: a held-key table with the right words in it can still drop one of two
concurrent keys, which is what several of the shipped regressions did.

So the keyboard state machine is extracted from HIDSupport.m verbatim, compiled,
and driven with real NSEvents through the same calls the stream window makes. The
scenarios are the shapes a real pair of hands produces: two keys down at once,
one released first, a key the settings page swallowed, a key held when input
forwarding is switched off, an auto-repeat, and a key swallowed while another one
is legitimately held.

The parts that are not the state machine are stubs, and they are stubs that say
so: the host sender records instead of sending, the modifier sync is empty, and
the dispatch block runs inline. The mapping table holds the two keys from the
report, VK 0x57 for W and VK 0x20 for Space.

Finally the harness is checked for teeth by rebuilding the same scenarios against
the pre-fix shape, a single "last forwarded key" instead of a table, which has to
fail every scenario that distinguishes it.

Exit 0 only when every scenario passes and the known-bad shape fails.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "Limelight", "Input", "HIDSupport.m")

VK_W = 0x57
VK_SPACE = 0x20
HIGH = 0x8000

SIGNATURES = [
    "- (void)noteKeyboardKeyDownSuppressedForEvent:(NSEvent *)event",
    "- (void)keyDown:(NSEvent *)event",
    "- (void)keyUp:(NSEvent *)event",
    "- (void)releaseAllHeldKeys",
    "- (short)translateKeyCodeWithEvent:(NSEvent *)event",
]


def method(text, signature):
    start = text.find(signature)
    if start < 0:
        raise SystemExit("the shipping source no longer contains %s" % signature)
    body = text.find("{", start)
    depth = 0
    for i in range(body, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit("unbalanced braces reading %s" % signature)


PROLOGUE = r"""
#import <AppKit/AppKit.h>

typedef struct MLInputStreamContext { int alive; } *PML_INPUT_STREAM_CONTEXT;
enum { KEY_ACTION_UP = 0, KEY_ACTION_DOWN = 1 };
#define LOG_I 0
#define Log(level, fmt, ...) ((void)0)

static NSMutableArray<NSString *> *gHostEvents;

static void LiSendKeyboardEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short keyCode, char action, char modifiers) {
    [gHostEvents addObject:[NSString stringWithFormat:@"%04X%c",
                            (unsigned)(keyCode & 0xFFFF), action == KEY_ACTION_DOWN ? 'D' : 'U']];
}
static PML_INPUT_STREAM_CONTEXT HIDInputContext(id support) {
    static struct MLInputStreamContext ctx = { 1 };
    return &ctx;
}
static BOOL HIDValidateInputContext(PML_INPUT_STREAM_CONTEXT ctx, const char *op) { return ctx != NULL && ctx->alive; }
static void HIDDispatchInput(id support, PML_INPUT_STREAM_CONTEXT ctx, void (^block)(void)) { block(); }
static unsigned short HIDRemappedKeyCodeForModifierKey(id support, unsigned short kc) { return 0; }
static BOOL HIDIsModifierKeyCode(unsigned short kc) { return kc == 54 || kc == 59 || kc == 60 || kc == 61 || kc == 56 || kc == 62; }

@interface MLKeyboardUnderProbe : NSObject
@property (nonatomic) BOOL shouldSendInputEvents;
@property (nonatomic) BOOL keyboardHeldKeyReleaseInProgress;
@property (nonatomic, strong) NSMutableSet<NSNumber *> *keyboardSuppressedKeyDownKeyCodes;
@property (nonatomic, strong) NSMutableDictionary<NSNumber *, NSNumber *> *keyboardForwardedKeyDownKeyCodes;
@property (nonatomic, strong) NSDictionary<NSNumber *, NSNumber *> *mappings;
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event;
- (short)translateKeyModifierWithEvent:(NSEvent *)event;
- (void)noteKeyboardKeyDownSuppressedForEvent:(NSEvent *)event;
- (void)keyDown:(NSEvent *)event;
- (void)keyUp:(NSEvent *)event;
- (void)releaseAllHeldKeys;
- (short)translateKeyCodeWithEvent:(NSEvent *)event;
@end
"""

EPILOGUE = r"""
@implementation MLKeyboardUnderProbe
- (instancetype)init {
    if ((self = [super init])) {
        _shouldSendInputEvents = YES;
        _keyboardSuppressedKeyDownKeyCodes = [NSMutableSet set];
        _keyboardForwardedKeyDownKeyCodes = [NSMutableDictionary dictionary];
        // Only the two keys from the report: W and Space, mapped as the shipping
        // table maps them.
        _mappings = @{ @13: @(0x57), @49: @(0x20) };
    }
    return self;
}
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event {}
- (short)translateKeyModifierWithEvent:(NSEvent *)event { return 0; }
"""

# The shape that shipped before the held-key table: one slot for "the key we
# forwarded last", and no record of a press the page swallowed.
LEGACY = r"""
@implementation MLKeyboardUnderProbe
- (instancetype)init {
    if ((self = [super init])) {
        _shouldSendInputEvents = YES;
        _keyboardSuppressedKeyDownKeyCodes = [NSMutableSet set];
        _keyboardForwardedKeyDownKeyCodes = [NSMutableDictionary dictionary];
        _mappings = @{ @13: @(0x57), @49: @(0x20) };
    }
    return self;
}
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event {}
- (short)translateKeyModifierWithEvent:(NSEvent *)event { return 0; }
- (void)noteKeyboardKeyDownSuppressedForEvent:(NSEvent *)event { /* the page kept no record */ }
- (void)keyDown:(NSEvent *)event {
    short translated = [self translateKeyCodeWithEvent:event];
    if (translated == 0) return;
    short keyCode = 0x8000 | translated;
    [self.keyboardForwardedKeyDownKeyCodes removeAllObjects];
    self.keyboardForwardedKeyDownKeyCodes[@(keyCode)] = @(keyCode);
    LiSendKeyboardEventCtx(HIDInputContext(self), keyCode, KEY_ACTION_DOWN, 0);
}
- (void)keyUp:(NSEvent *)event {
    if (!self.shouldSendInputEvents) return;
    short translated = [self translateKeyCodeWithEvent:event];
    if (translated == 0) return;
    [self.keyboardForwardedKeyDownKeyCodes removeAllObjects];
    LiSendKeyboardEventCtx(HIDInputContext(self), 0x8000 | translated, KEY_ACTION_UP, 0);
}
- (void)releaseAllHeldKeys {
    for (NSNumber *keyCode in self.keyboardForwardedKeyDownKeyCodes.allValues) {
        LiSendKeyboardEventCtx(HIDInputContext(self), keyCode.shortValue, KEY_ACTION_UP, 0);
    }
    [self.keyboardForwardedKeyDownKeyCodes removeAllObjects];
}
- (short)translateKeyCodeWithEvent:(NSEvent *)event {
    if (!self.mappings[@(event.keyCode)]) return 0;
    return [self.mappings[@(event.keyCode)] shortValue];
}
"""


def build(extracted):
    return PROLOGUE + EPILOGUE + extracted + "\n@end\n"


def run_source(path, source):
    open(path, "w", encoding="utf-8").write(source)


DRIVER = r"""
static NSEvent *Key(unsigned short kc) { return kc; }
"""

TEST_BODY = r"""
static NSEvent *Down(unsigned short kc, NSString *chars, BOOL repeat) {
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0
                           timestamp:0 windowNumber:0 context:nil characters:chars
            charactersIgnoringModifiers:chars isARepeat:repeat keyCode:kc];
}
static NSEvent *Up(unsigned short kc, NSString *chars) {
    return [NSEvent keyEventWithType:NSEventTypeKeyUp location:NSZeroPoint modifierFlags:0
                           timestamp:0 windowNumber:0 context:nil characters:chars
            charactersIgnoringModifiers:chars isARepeat:NO keyCode:kc];
}
static NSString *Seq(void) { return [gHostEvents componentsJoinedByString:@" "]; }
static BOOL gSettingsPageIsPresenting;

// Mirrors -keyDown: and -keyUp: in StreamViewController+MouseCapture.m: while the
// settings page owns the region the event is noted as consumed and the stream
// view is never reached at all, so the state machine under test must not be
// handed both calls for one event.
static void Deliver(MLKeyboardUnderProbe *k, NSEvent *event) {
    if (event.type == NSEventTypeKeyDown) {
        if (gSettingsPageIsPresenting) {
            [k noteKeyboardKeyDownSuppressedForEvent:event];
            return;
        }
        [k keyDown:event];
    } else {
        [k keyUp:event];
    }
}
static void Clear(void) { [gHostEvents removeAllObjects]; }
static NSString *SortedSeq(void) {
    NSMutableArray<NSString *> *sorted = [[gHostEvents copy] mutableCopy];
    [sorted sortUsingSelector:@selector(compare:)];
    return [sorted componentsJoinedByString:@" "];
}
static void Reset(MLKeyboardUnderProbe *k) {
    [gHostEvents removeAllObjects];
    [k.keyboardSuppressedKeyDownKeyCodes removeAllObjects];
    [k.keyboardForwardedKeyDownKeyCodes removeAllObjects];
    k.shouldSendInputEvents = YES;
    k.keyboardHeldKeyReleaseInProgress = NO;
    gSettingsPageIsPresenting = NO;
}
static int gFailed;
static void Expect(const char *what, NSString *got, NSString *want) {
    BOOL ok = [got isEqual:want];
    printf("%-4s %s\n", ok ? "ok" : "FAIL", what);
    if (!ok) {
        printf("     host saw [%s], expected [%s]\n", got.UTF8String, want.UTF8String);
        gFailed++;
    }
}
static void ExpectRecords(const char *what, MLKeyboardUnderProbe *k, unsigned long forwarded, unsigned long suppressed) {
    BOOL ok = k.keyboardForwardedKeyDownKeyCodes.count == forwarded
              && k.keyboardSuppressedKeyDownKeyCodes.count == suppressed;
    printf("%-4s %s\n", ok ? "ok" : "FAIL", what);
    if (!ok) {
        printf("     records: %lu forwarded, %lu suppressed\n",
               (unsigned long)k.keyboardForwardedKeyDownKeyCodes.count,
               (unsigned long)k.keyboardSuppressedKeyDownKeyCodes.count);
        gFailed++;
    }
}

int main(void) {
    @autoreleasepool {
        gHostEvents = [NSMutableArray array];
        MLKeyboardUnderProbe *k = [[MLKeyboardUnderProbe alloc] init];
        NSEvent *wDown = Down(13, @"w", NO), *wUp = Up(13, @"w");
        NSEvent *spDown = Down(49, @" ", NO), *spUp = Up(49, @" ");

        // Walk and jump, released in the order a hand produces them.
        Reset(k);
        Deliver(k, wDown); Deliver(k, spDown); Deliver(k, spUp); Deliver(k, wUp);
        Expect("W and Space down together reach the host as two presses",
               Seq(), @"8057D 8020D 8020U 8057U");
        ExpectRecords("nothing is left held afterwards", k, 0, 0);

        // The other hand order: jump first, walk last.
        Reset(k);
        Deliver(k, wDown); Deliver(k, spDown); Deliver(k, wUp);
        Expect("releasing W while Space is still held says nothing about Space",
               Seq(), @"8057D 8020D 8057U");
        ExpectRecords("Space is still known to be held", k, 1, 0);
        [k keyUp:spUp];
        Expect("the jump release follows when the finger lifts", Seq(), @"8057D 8020D 8057U 8020U");

        // The settings page swallows the key it was given, and the release that
        // belongs to that press, never the other key's.
        Reset(k);
        gSettingsPageIsPresenting = YES;
        Deliver(k, wDown);            // walk: kept by the page
        gSettingsPageIsPresenting = NO;
        Deliver(k, spDown);           // jump: a gameplay key, forwarded
        Deliver(k, wUp);              // the page closed before the finger lifted
        Deliver(k, spUp);
        Expect("a press the page kept stays local and its release is kept too",
               Seq(), @"8020D 8020U");
        ExpectRecords("the swallow is not left armed", k, 0, 0);

        // A key the host never saw go down must not be released onto it.
        Reset(k);
        gSettingsPageIsPresenting = YES;
        Deliver(k, wDown);
        [k releaseAllHeldKeys];
        Expect("flushing held keys does not invent a release for a local key", Seq(), @"");

        // Both keys held when input forwarding is switched off: the host must be
        // told to let go of each one.
        Reset(k);
        Deliver(k, wDown); Deliver(k, spDown);
        k.shouldSendInputEvents = NO;
        Clear();
        [k releaseAllHeldKeys];
        Expect("two keys held at capture-off are both released", SortedSeq(), @"8020U 8057U");
        ExpectRecords("and the table is empty so a stray release cannot double-release", k, 0, 0);
        [k releaseAllHeldKeys];
        Expect("a second flush releases nothing again", SortedSeq(), @"8020U 8057U");

        // Auto-repeat of a held key must not strand a second press.
        Reset(k);
        Deliver(k, wDown);
        Deliver(k, Down(13, @"w", YES));
        Deliver(k, wUp);
        Expect("an auto-repeat is forwarded as it arrives", Seq(), @"8057D 8057D 8057U");
        ExpectRecords("but the held table keeps one entry per key", k, 0, 0);

        printf("%d keyboard scenario failures\n", gFailed);
        return gFailed ? 1 : 0;
    }
}
"""


def toolchain():
    """The compiler and SDK, as one matched pair. See scripts/apple_toolchain.py.

    A host with neither keeps the shape this file already had: the caller prints a FAIL
    and returns a failing code, so an unusable machine reads as a red gate rather than
    a green one -- the only difference from a silent skip that would lie.
    """
    try:
        return apple_toolchain.clang_and_sdk("keyboard concurrency")
    except SystemExit as error:
        print("%s" % error)
        return None, None


def compile_and_run(source, label):
    tmp = tempfile.mkdtemp(prefix="keyboard-concurrency-")
    path = os.path.join(tmp, "probe.m")
    open(path, "w", encoding="utf-8").write(source)
    cc, sdk = toolchain()
    if cc is None or sdk is None:
        print("FAIL xcrun could not name a clang and SDK to build the %s probe" % label)
        return 1
    exe = os.path.join(tmp, "probe")
    build = subprocess.run([cc, "-fobjc-arc", "-O1",
                            "-isysroot", sdk, "-framework", "AppKit",
                            "-o", exe, path], capture_output=True, text=True)
    if build.returncode != 0:
        print("FAIL the %s probe does not compile:\n%s" % (label, build.stderr[-1500:]))
        return 1
    ran = subprocess.run([exe], capture_output=True, text=True)
    print(ran.stdout.rstrip())
    return ran.returncode


def main():
    text = open(SOURCE, encoding="utf-8").read()
    extracted = "\n\n".join(method(text, sig) for sig in SIGNATURES)
    shipping = build(extracted) + TEST_BODY
    print("extracted %d lines of the keyboard state machine from %s"
          % (extracted.count("\n") + 1, os.path.relpath(SOURCE, ROOT)))
    failures = 0

    print("\n-- the shipping state machine --")
    verdict = compile_and_run(shipping, "shipping")
    if verdict != 0:
        failures += 1

    # The harness has to be able to fail, or it is not testing anything: the
    # pre-fix shape kept the same words in the same file and still tangled two
    # concurrent keys, so it must be rejected here.
    print("\n-- the shape that shipped before the held-key table --")
    legacy = PROLOGUE + LEGACY + "\n@end\n" + TEST_BODY
    bad = compile_and_run(legacy, "known-bad")
    if bad == 0 or bad is None:
        print("FAIL the harness passed a state machine known to tangle concurrent keys")
        failures += 1
    else:
        print("ok   the harness rejects the known-bad shape (it has teeth)")

    print("\n%d keyboard-concurrency failures" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
