#!/usr/bin/env python3
"""Prove that a modifier held for sprinting survives the key pressed beside it.

The report is a game again: W and Space, walk and jump. The keyboard-concurrency
harness already drives that pair, and it passes -- but it empties the modifier
sync on purpose, because it was built to ask whether two ordinary keys stay two
keys. Nobody has ever run the modifier state machine at all.

That omission matters, because a player does not press W and Space in isolation.
In the games where this was reported, the pair arrives while Shift is held to
sprint, and Shift is the one thing that must not lie: if its release is dropped,
the host goes on sprinting; if a press beside it carries a stale modifier byte,
the jump becomes Ctrl+Space; if the sync answers a change with only one of two
changed bits, one sprint key is stranded with no key left to release it.

So the modifier chain is lifted verbatim out of HIDSupport.m -- the physical
mask, the desired remote mask, the sync that diffs them, the flags-changed entry
that feeds them, and the ordinary keyDown:/keyUp: that a game key travels
through -- together with the shipping lookup table in KeyboardMapResolver.m that
decides which Windows modifier a Mac key becomes. Stubs are the host sender, the
stream context, and the dispatch block, and the sender records the modifier byte
it was handed, because half of the failures this harness looks for are in that
byte rather than in the key code.

Scenarios are hand shapes: sprint then walk then jump and let go in order; let go
of sprint while a movement key is still down; left and right shift as the two
distinct keys the host must see them as; a jump the client kept locally while
sprint and walk stayed with the host. Every scenario is replayed against the
shape that drops the release half of a modifier change, which has to fail.

Exit 0 only when every scenario passes and both known-bad shapes fail.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "Limelight", "Input", "HIDSupport.m")
RESOLVER = os.path.join(ROOT, "Limelight", "Input", "KeyboardMapResolver.m")
RESOLVER_H = os.path.join(ROOT, "Limelight", "Input", "KeyboardMapResolver.h")

METHODS = [
    "- (void)updateKeyboardPhysicalModifierStateFromEvent:(NSEvent *)event",
    "- (NSUInteger)desiredRemoteKeyboardModifierMaskForEvent:(NSEvent *)event",
    "- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event",
    "- (void)flagsChanged:(NSEvent *)event",
    "- (void)keyDown:(NSEvent *)event",
    "- (void)keyUp:(NSEvent *)event",
    "- (short)translateKeyCodeWithEvent:(NSEvent *)event",
    "- (char)translatedModifierFlagsForEvent:(NSEvent *)event",
    "- (char)translateKeyModifierWithEvent:(NSEvent *)event",
]

STATICS = [
    "static HIDKeyboardPhysicalModifierMask HIDPhysicalModifierMaskForKeyCode(",
    "static NSEventModifierFlags HIDModifierFlagForKeyCode(",
    "static HIDKeyboardPhysicalModifierMask HIDEffectivePhysicalModifierMaskForEvent(",
    "static unsigned short HIDRemoteModifierKeyCode(",
    "static char HIDRemoteModifierFlagsToGenericFlags(",
]

# The two masks and the resolver's enums, lifted so the probe cannot disagree
# with the shipping build about which bit means "left shift".
ENUMS = [
    (SOURCE, "typedef NS_OPTIONS(NSUInteger, HIDKeyboardPhysicalModifierMask) {"),
    (SOURCE, "typedef NS_OPTIONS(NSUInteger, HIDKeyboardRemoteModifierMask) {"),
    (RESOLVER_H, "typedef NS_ENUM(uint8_t, KMR_PhysicalModifier) {"),
    (RESOLVER_H, "enum {\n    KMR_Remote_LeftShift   = 1 << 0,"),
]

RESOLVER_TABLE = "static const uint8_t s_mapTable[KMR_Phys_Count] = {"
RESOLVER_FUNC = "KMR_RemoteModifierMask KMR_RemoteMaskForPhysical("


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


def static_function(text, signature):
    return method(text, signature)


def enum_block(text, marker):
    start = text.find(marker)
    if start < 0:
        raise SystemExit("the shipping source no longer contains %r" % marker)
    end = text.find("};", start)
    if end < 0:
        raise SystemExit("unterminated enum at %r" % marker)
    return text[start:end + 2]


def typedef_line(text, name):
    match = re.search(r"^typedef [^\n]*\b%s;" % re.escape(name), text, re.M)
    if not match:
        raise SystemExit("no typedef for %s" % name)
    return match.group(0)




STATICS.append("static BOOL HIDIsModifierKeyCode(")
STATICS.append(
    "static NSEventModifierFlags HIDDeviceModifierMaskForKeyCode(")
STATICS.append(
    "static BOOL HIDEventCarriesDeviceModifierState(")

HEAD = r"""
#import <AppKit/AppKit.h>
#import <Carbon/Carbon.h>
// The per-key halves of the modifier snapshot. These are the bits that tell left
// shift from right shift; the family bit (NSEventModifierFlagShift) cannot.
#import <IOKit/hidsystem/IOLLEvent.h>

typedef struct MLInputStreamContext { int alive; } *PML_INPUT_STREAM_CONTEXT;
enum { KEY_ACTION_UP = 0, KEY_ACTION_DOWN = 1 };
#define LOG_D 0
#define LOG_I 0
#define Log(level, fmt, ...) ((void)0)

"""

RECORDER = r"""
static NSMutableArray<NSString *> *gHostEvents;

int LiSendKeyboardEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short keyCode,
                           char action, char modifiers) {
    // The modifier byte is recorded next to the key code on purpose. Half of
    // the failures this harness looks for leave the key code correct and the
    // byte beside it stale, and a recorder that drops it cannot see them.
    [gHostEvents addObject:[NSString stringWithFormat:@"%04X%c/%02X",
                            (unsigned)(keyCode & 0xFFFF),
                            action == KEY_ACTION_DOWN ? 'D' : 'U',
                            (unsigned)(unsigned char)modifiers]];
    return 0;
}
static PML_INPUT_STREAM_CONTEXT HIDInputContext(id support) {
    static struct MLInputStreamContext ctx = { 1 };
    return &ctx;
}
static BOOL HIDValidateInputContext(PML_INPUT_STREAM_CONTEXT ctx, const char *op) {
    return ctx != NULL && ctx->alive;
}
static void HIDDispatchInput(id support, PML_INPUT_STREAM_CONTEXT ctx,
                             void (^block)(void)) { block(); }
static unsigned short HIDRemappedKeyCodeForModifierKey(id support,
                                                       unsigned short kc) { return 0; }

// The state machine reads three things off an event: its type, its key code,
// and the modifier snapshot AppKit attached to it. NSEvent cannot be built here
// -- its class constructor is not in the headers this probe sees -- so the
// probe supplies those three and nothing else. An event carrying more than that
// would let a fix that reads a fourth field pass here and fail on a real keyboard.
@interface MLKeyboardEventUnderTest : NSObject
@property (nonatomic) NSEventType type;
@property (nonatomic) unsigned short keyCode;
@property (nonatomic) NSEventModifierFlags modifierFlags;
+ (instancetype)eventWithType:(NSEventType)type
                      keyCode:(unsigned short)keyCode
                        flags:(NSEventModifierFlags)flags;
@end

@implementation MLKeyboardEventUnderTest
+ (instancetype)eventWithType:(NSEventType)type
                      keyCode:(unsigned short)keyCode
                        flags:(NSEventModifierFlags)flags {
    MLKeyboardEventUnderTest *event = [[MLKeyboardEventUnderTest alloc] init];
    event.type = type;
    event.keyCode = keyCode;
    event.modifierFlags = flags;
    return event;
}
@end

@interface MLModifierPairProbe : NSObject
@property (nonatomic) BOOL shouldSendInputEvents;
@property (nonatomic) BOOL keyboardModifierReleaseInProgress;
@property (nonatomic) NSUInteger keyboardPhysicalModifierSourceMask;
@property (nonatomic) NSUInteger keyboardRemoteModifierMask;
@property (nonatomic, strong) NSMutableSet<NSNumber *> *keyboardSuppressedKeyDownKeyCodes;
@property (nonatomic, strong) NSMutableDictionary<NSNumber *, NSNumber *> *keyboardForwardedKeyDownKeyCodes;
@property (nonatomic, strong) NSDictionary<NSNumber *, NSNumber *> *mappings;
- (void)updateKeyboardPhysicalModifierStateFromEvent:(NSEvent *)event;
- (NSUInteger)desiredRemoteKeyboardModifierMaskForEvent:(NSEvent *)event;
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event;
- (void)flagsChanged:(NSEvent *)event;
- (void)keyDown:(NSEvent *)event;
- (void)keyUp:(NSEvent *)event;
- (short)translateKeyCodeWithEvent:(NSEvent *)event;
- (char)translatedModifierFlagsForEvent:(NSEvent *)event;
- (char)translateKeyModifierWithEvent:(NSEvent *)event;
@end

@implementation MLModifierPairProbe
- (instancetype)init {
    if ((self = [super init])) {
        _shouldSendInputEvents = YES;
        _keyboardSuppressedKeyDownKeyCodes = [NSMutableSet set];
        _keyboardForwardedKeyDownKeyCodes = [NSMutableDictionary dictionary];
        // W and Space are the keys from the report; the shifts are the sprint.
        _mappings = @{ @13: @(0x57), @49: @(0x20),
                       @56: @(0xA0), @60: @(0xA1) };
    }
    return self;
}
"""

TAIL = r"""
@end
"""

DRIVER = r"""
static int gFailed;

static NSString *Ev(unsigned vk, char action, char modifiers) {
    return [NSString stringWithFormat:@"%04X%c/%02X", vk, action, (unsigned)modifiers];
}

static NSEvent *KeyEvent(NSEventType type, unsigned short keyCode,
                         NSEventModifierFlags flags) {
    return (NSEvent *)[MLKeyboardEventUnderTest eventWithType:type
                                                      keyCode:keyCode
                                                        flags:flags];
}

// Every hand shape gets a fresh controller. A stranded modifier really does
// poison the keys that follow it -- that is what makes it feel sticky to a
// player -- but a harness that replays one shape on the wreckage of the last
// cannot say which of the two it is looking at.
static NSArray<NSString *> *Play(NSArray<NSArray *> *script) {
    MLModifierPairProbe *probe = [[MLModifierPairProbe alloc] init];
    [gHostEvents removeAllObjects];
    for (NSArray *step in script) {
        NSEventType type = (NSEventType)[step[0] unsignedIntegerValue];
        NSEvent *event = KeyEvent(type, (unsigned short)[step[1] unsignedShortValue],
                                  (NSEventModifierFlags)[step[2] unsignedLongLongValue]);
        if (type == NSEventTypeFlagsChanged) {
            [probe flagsChanged:event];
        } else if (type == NSEventTypeKeyDown) {
            [probe keyDown:event];
        } else {
            [probe keyUp:event];
        }
    }
    return [gHostEvents copy];
}

static void Expect(const char *what, NSArray<NSString *> *got,
                   NSArray<NSString *> *want) {
    BOOL ok = [got isEqualToArray:want];
    printf("%-4s %s\n", ok ? "ok" : "FAIL", what);
    if (!ok) {
        gFailed++;
        printf("     host saw  [%s]\n", [[got componentsJoinedByString:@" "] UTF8String]);
        printf("     expected  [%s]\n", [[want componentsJoinedByString:@" "] UTF8String]);
    }
}

int main(void) {
    @autoreleasepool {
        gHostEvents = [NSMutableArray array];

        // A real keyDown under Shift carries the family bit; a flagsChanged
        // carries the family bit plus the bit for the key that just moved. That
        // pair is what the state machine has to read, so the script supplies it.
        const NSEventModifierFlags shift = NSEventModifierFlagShift;
        const NSEventModifierFlags leftShift = shift | NX_DEVICELSHIFTKEYMASK;
        const NSEventModifierFlags bothShifts = shift | NX_DEVICELSHIFTKEYMASK
                                              | NX_DEVICERSHIFTKEYMASK;
        const NSEventModifierFlags rightShift = shift | NX_DEVICERSHIFTKEYMASK;
        // Sprint, walk, jump, and let go in the order the fingers lifted them.
        NSArray *sprint_walk_jump = @[
            @[@(NSEventTypeFlagsChanged), @(56), @(leftShift)],
            @[@(NSEventTypeKeyDown), @(13), @(leftShift)],
            @[@(NSEventTypeKeyDown), @(49), @(leftShift)],
            @[@(NSEventTypeKeyUp), @(49), @(leftShift)],
            @[@(NSEventTypeKeyUp), @(13), @(leftShift)],
            @[@(NSEventTypeFlagsChanged), @(56), @(0ULL)],
        ];
        Expect("sprint, walk and jump reach the host as three keys that release in order",
               Play(sprint_walk_jump),
               @[Ev(0x00A0, 'D', MODIFIER_SHIFT), Ev(0x8057, 'D', MODIFIER_SHIFT),
                 Ev(0x8020, 'D', MODIFIER_SHIFT), Ev(0x8020, 'U', MODIFIER_SHIFT),
                 Ev(0x8057, 'U', MODIFIER_SHIFT), Ev(0x00A0, 'U', 0)]);

        // Letting go of sprint while the movement key is still down must not
        // touch the movement key, and the next jump must no longer be a sprint.
        NSArray *sprint_released_midstride = @[
            @[@(NSEventTypeFlagsChanged), @(56), @(leftShift)],
            @[@(NSEventTypeKeyDown), @(13), @(leftShift)],
            @[@(NSEventTypeFlagsChanged), @(56), @(0ULL)],
            @[@(NSEventTypeKeyDown), @(49), @(0ULL)],
            @[@(NSEventTypeKeyUp), @(49), @(0ULL)],
            @[@(NSEventTypeKeyUp), @(13), @(0ULL)],
        ];
        Expect("a sprint let go mid-stride ends, and the jump after it is not a sprint",
               Play(sprint_released_midstride),
               @[Ev(0x00A0, 'D', MODIFIER_SHIFT), Ev(0x8057, 'D', MODIFIER_SHIFT),
                 Ev(0x00A0, 'U', 0), Ev(0x8020, 'D', 0),
                 Ev(0x8020, 'U', 0), Ev(0x8057, 'U', 0)]);

        // Left and right shift are two keys on the host, not one "Shift" state.
        NSArray *both_shifts = @[
            @[@(NSEventTypeFlagsChanged), @(56), @(leftShift)],
            @[@(NSEventTypeFlagsChanged), @(60), @(bothShifts)],
            @[@(NSEventTypeFlagsChanged), @(56), @(rightShift)],
            @[@(NSEventTypeFlagsChanged), @(60), @(0ULL)],
        ];
        Expect("left shift released while right shift is held leaves the host still shifted",
               Play(both_shifts),
               @[Ev(0x00A0, 'D', MODIFIER_SHIFT), Ev(0x00A1, 'D', MODIFIER_SHIFT),
                 Ev(0x00A0, 'U', MODIFIER_SHIFT), Ev(0x00A1, 'U', 0)]);

        // Both shifts down, both up, and the key pressed between them belongs to
        // whichever the player is actually holding -- here the right one.
        NSArray *right_shift_only = @[
            @[@(NSEventTypeFlagsChanged), @(60), @(rightShift)],
            @[@(NSEventTypeKeyDown), @(13), @(rightShift)],
            @[@(NSEventTypeKeyUp), @(13), @(rightShift)],
            @[@(NSEventTypeFlagsChanged), @(60), @(0ULL)],
        ];
        Expect("a walk key under the right shift reaches the host as the right shift only",
               Play(right_shift_only),
               @[Ev(0x00A1, 'D', MODIFIER_SHIFT), Ev(0x8057, 'D', MODIFIER_SHIFT),
                 Ev(0x8057, 'U', MODIFIER_SHIFT), Ev(0x00A1, 'U', 0)]);

        printf("%d held-modifier pair failures\n", gFailed);
        return gFailed == 0 ? 0 : 1;
    }
}
"""


def modifier_defines():
    """The modifier byte values, lifted from the header that defines them."""
    text = read(os.path.join(ROOT, "moonlight-common", "moonlight-common-c",
                             "src", "Limelight.h"))
    block = re.findall(r"^#define MODIFIER_[A-Z_]+ +0x[0-9A-Fa-f]+$", text, re.M)
    if not block:
        raise SystemExit("Limelight.h no longer defines the modifier byte values")
    return "\n".join(block) + "\n"


def resolver_table(resolver):
    start = resolver.index(RESOLVER_TABLE)
    return resolver[start:resolver.index("};", start) + 2]


def declarations():
    """The types and pure helpers the probe must agree with the app about.

    These are lifted rather than rewritten so the probe cannot pass on a bit
    layout the shipping build does not use: which bit is left shift, which byte
    is the shift modifier, and which Windows key a Mac key becomes are all facts
    owned by the shipping source.
    """
    parts = [enum_block(read(path), marker) for path, marker in ENUMS]
    parts.append(typedef_line(read(RESOLVER_H), "KMR_RemoteModifierMask"))
    resolver = read(RESOLVER)
    parts.append(resolver_table(resolver))
    parts.append(static_function(resolver, RESOLVER_FUNC))
    source = read(SOURCE)
    parts.extend(static_function(source, signature) for signature in STATICS)
    return "\n\n".join(parts) + "\n"


def shipping_methods():
    """The state machine under test, verbatim from the shipping file."""
    source = read(SOURCE)
    return "\n\n".join(method(source, signature) for signature in METHODS) + "\n"


# Each known-bad shape is a plausible way to write this code wrong, not a random
# edit: it has to leave the file compiling and the ordinary single-key case
# behaving, and fail only on the pair a player actually produces.
KNOWN_BAD = {
    # A modifier change answered only for the bits that went down. Pressing
    # Shift works, so the single-key case looks fine; letting go never tells the
    # host, so the player sprints until something else lifts the key.
    "release-half-dropped": (
        "NSUInteger changed = previous ^ desired;",
        "NSUInteger changed = desired & ~previous;",
        "letting go of a modifier is never sent"),
    # The key code is right and the byte beside it is the previous event's, which
    # is a jump that arrives as Ctrl+Space.
    "stale-modifier-byte": (
        "char modifiers = [self translateKeyModifierWithEvent:event];",
        "static char gStale = 0;\n"
        "        char modifiers = gStale;\n"
        "        gStale = [self translateKeyModifierWithEvent:event];",
        "a key carries the modifier byte of the event before it"),
}


def implementation(known_bad=None):
    body = shipping_methods()
    if known_bad:
        anchor, replacement, _why = KNOWN_BAD[known_bad]
        if body.count(anchor) < 1:
            raise SystemExit("the known-bad anchor is gone from the source: %s" % anchor)
        body = body.replace(anchor, replacement, 1)
    return RECORDER + body + TAIL


def build(known_bad=None):
    return (HEAD + modifier_defines() + "\n" + declarations()
            + "\n" + implementation(known_bad) + "\n" + DRIVER)


def compile_and_run(path, source, label):
    open(path, "w", encoding="utf-8").write(source)
    try:
        clang, sdk = apple_toolchain.clang_and_sdk(label)
    except Exception as error:  # noqa: BLE001 - the answer is the point
        print("%s" % error)
        return None
    probe = path + ".probe"
    build = subprocess.run([clang, "-fobjc-arc", "-fmodules", "-w",
                            "-isysroot", sdk, "-framework", "AppKit",
                            "-o", probe, path],
                           capture_output=True, text=True)
    if build.returncode != 0:
        print("FAIL the %s probe does not compile:\n%s"
              % (label, build.stderr[-2000:]))
        return None
    run = subprocess.run([probe], capture_output=True, text=True)
    print(run.stdout, end="")
    if run.stderr.strip():
        print(run.stderr[-800:])
    return run.returncode


def main():
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "probe.m")
        print("-- the shipping modifier and key state machine --")
        code = compile_and_run(path, build(), "held-modifier pair")
        if code is None:
            return 1
        failures = 0 if code == 0 else 1
        if failures:
            print("FAIL the harness failed the shipping state machine")

        for known_bad in sorted(KNOWN_BAD):
            print("\n-- known-bad: %s --" % KNOWN_BAD[known_bad][2])
            code = compile_and_run(os.path.join(work, "bad.m"),
                                 build(known_bad), known_bad)
            if code is None:
                return 1
            if code == 0:
                print("FAIL the harness passed a state machine known to strand a held modifier")
                failures = 1

        print("\n%d held-modifier-pair failures" % failures)
        return failures


if __name__ == "__main__":
    sys.exit(main())
