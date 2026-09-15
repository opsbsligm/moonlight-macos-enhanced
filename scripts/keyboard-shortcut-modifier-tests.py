#!/usr/bin/env python3
"""Prove that a synthetic shortcut cannot take a modifier away from a held key.

The reports in this area all read the same way: two things pressed at once and one
of them stops working. The held-key table, the suppressed-press record and the
unmapped-key gate already cover the keyboard's own paths. What was left uncovered is
the path the mouse takes: a translation rule fires a shortcut on the host by hand
(`StreamViewController+MouseCapture.m` calls `-sendSyntheticRemoteShortcut:`), and
that hand-written packet sequence presses its modifiers, fires its key, then lets
its modifiers go -- including a modifier the player is still holding with a real
finger, such as Shift while sprinting and a Shift+Tab rule.

The physical state is tracked separately (`keyboardRemoteModifierMask`) and the next
`-syncKeyboardModifierStateForEvent:` compares desired against that tracker. A
synthetic release does not move the tracker, so after one rule fires the tracker says
LeftShift is down, the host thinks it is up, `changed` is zero, and no corrective
press is ever sent. The player keeps holding Shift, the game has stopped sprinting,
and nothing is logged.

So the harness extracts the shipping state machine -- the physical mask, the desired
mask, the sync that diffs it, and both synthetic paths -- compiles it against the real
`KeyboardMapResolver`, and reads the packets the host would receive. Two things are
asserted for every scenario: the exact packet list, and the invariant the defect
breaks, that the host's held-modifier set derived from those packets equals the
tracker the app will diff against next.

Exit 0 only when every scenario passes, the ownership rule is in the shipped source,
and the unconditional-release shape is refused.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "Limelight", "Input", "HIDSupport.m")
# The caller. A rule's handler is where the release used to happen, so the rule that
# keeps it out has to be checked against that file and nowhere else.
STREAM_VIEW = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers",
                           "StreamViewController+MouseCapture.m")
RESOLVER_M = os.path.join(ROOT, "Limelight", "Input", "KeyboardMapResolver.m")
RESOLVER_H = os.path.join(ROOT, "Limelight", "Input", "KeyboardMapResolver.h")
LIMELIGHT_H = os.path.join(ROOT, "moonlight-common", "moonlight-common-c", "src", "Limelight.h")

STATICS = [
    "typedef NS_OPTIONS(NSUInteger, HIDKeyboardPhysicalModifierMask)",
    "typedef NS_OPTIONS(NSUInteger, HIDKeyboardRemoteModifierMask)",
    "static HIDKeyboardPhysicalModifierMask HIDPhysicalModifierMaskForKeyCode",
    "static NSEventModifierFlags HIDModifierFlagForKeyCode",
    "static HIDKeyboardPhysicalModifierMask HIDEffectivePhysicalModifierMaskForEvent",
    "static unsigned short HIDRemoteModifierKeyCode",
    "static char HIDRemoteModifierFlagsToGenericFlags",
    "static NSUInteger HIDSyntheticOwnedModifierMask",
    "static void HIDDispatchSyntheticRemoteModifierTap",
    "static BOOL HIDIsModifierKeyCode",
    "static unsigned short HIDRemappedKeyCodeForModifierKey",
]

METHODS = [
    "- (void)updateKeyboardPhysicalModifierStateFromEvent:(NSEvent *)event",
    "- (NSUInteger)desiredRemoteKeyboardModifierMaskForEvent:(NSEvent *)event",
    "- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event",
    "- (void)sendSyntheticRemoteModifierTapForFlags:(NSEventModifierFlags)modifierFlags",
    "- (void)sendSyntheticRemoteShortcut:(StreamShortcut *)shortcut",
    "- (short)translateKeyCodeWithEvent:(NSEvent *)event",
    "- (char)translatedModifierFlagsForEvent:(NSEvent *)event",
    "- (char)translateKeyModifierWithEvent:(NSEvent *)event",
    "- (void)keyDown:(NSEvent *)event",
    "- (void)releaseAllModifierKeys",
]


def block_from(text, anchor, what):
    """The declaration or definition starting at `anchor`, braces and ';' included."""
    start = text.find(anchor)
    if start < 0:
        raise SystemExit("the shipping source no longer contains %s" % what)
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit("no body found for %s" % what)
    depth, index = 0, brace
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1
    else:
        raise SystemExit("unbalanced braces in %s" % what)
    end = index + 2 if text[index + 1:index + 2] == ";" else index + 1
    return text[start:end]


def extract(text):
    return "\n\n".join(block_from(text, anchor, anchor) for anchor in STATICS + METHODS)


def resolver_body():
    """The shipped resolver with its project imports dropped and nothing else touched."""
    body = open(RESOLVER_M, encoding="utf-8").read()
    stripped = re.sub(r'^#import\s+"[^"]*"\n', "", body, flags=re.M)
    if stripped == body:
        raise SystemExit("KeyboardMapResolver.m no longer imports its project headers, so "
                         "this harness would be compiling something other than the shipped file")
    return stripped


def modifier_defines():
    """MODIFIER_* read out of the header the shipping build uses, never restated."""
    text = open(LIMELIGHT_H, encoding="utf-8", errors="replace").read()
    out = []
    for name in ("MODIFIER_SHIFT", "MODIFIER_CTRL", "MODIFIER_ALT", "MODIFIER_META"):
        match = re.search(r"^#define\s+%s\s+(\S+)" % name, text, re.M)
        if not match:
            raise SystemExit("%s is not defined in %s" % (name, LIMELIGHT_H))
        out.append("#define %s %s" % (name, match.group(1)))
    return "\n".join(out)


PROLOGUE = r"""
#import <AppKit/AppKit.h>
#import <Carbon/Carbon.h>
#include <stdlib.h>

#define HIDSupport MLModifiersUnderProbe

typedef struct MLInputStreamContext { int alive; } *PML_INPUT_STREAM_CONTEXT;
enum { KEY_ACTION_UP = 0, KEY_ACTION_DOWN = 1 };
#define LOG_I 0
#define LOG_D 0
#define Log(level, fmt, ...) ((void)0)

__MODIFIER_DEFINES__

#include "__RESOLVER_HEADER__"

static NSMutableArray<NSString *> *gHostEvents;

// The host is a recorder. Each packet is the virtual key, the edge, and the legacy
// modifier byte, so a scenario's expectation is a packet list rather than a peek at
// internal state.
static NSString *Ev(unsigned short vk, BOOL down, unsigned char modifiers) {
    return [NSString stringWithFormat:@"%04X%c%02X", vk, down ? 'D' : 'U', modifiers];
}

static void LiSendKeyboardEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short keyCode, char action, char modifiers) {
    [gHostEvents addObject:Ev((unsigned short)keyCode, action == KEY_ACTION_DOWN, (unsigned char)modifiers)];
}
static PML_INPUT_STREAM_CONTEXT HIDInputContext(id support) {
    static struct MLInputStreamContext ctx = { 1 };
    return &ctx;
}
static BOOL HIDValidateInputContext(PML_INPUT_STREAM_CONTEXT ctx, const char *op) { return ctx != NULL && ctx->alive; }
static void HIDDispatchInput(id support, PML_INPUT_STREAM_CONTEXT ctx, void (^block)(void)) { block(); }

// Stands in for the Swift pair. The intersection below is the shipping one, copied
// from SettingsShortcuts.swift: `flags.intersection([.control, .option, .shift,
// .command, .function])`.
@interface StreamShortcut : NSObject
@property (nonatomic) NSInteger keyCode;
@property (nonatomic) NSEventModifierFlags modifierFlags;
@property (nonatomic) BOOL modifierOnly;
+ (NSInteger)noKeyCode;
@end
@implementation StreamShortcut
+ (NSInteger)noKeyCode { return -1; }
@end

@interface StreamShortcutProfile : NSObject
+ (NSEventModifierFlags)relevantModifierFlags:(NSEventModifierFlags)flags;
@end
@implementation StreamShortcutProfile
+ (NSEventModifierFlags)relevantModifierFlags:(NSEventModifierFlags)flags {
    return flags & (NSEventModifierFlagControl | NSEventModifierFlagOption
                    | NSEventModifierFlagShift | NSEventModifierFlagCommand
                    | NSEventModifierFlagFunction);
}
@end

@interface MLModifiersUnderProbe : NSObject
@property (nonatomic) BOOL shouldSendInputEvents;
@property (nonatomic) NSUInteger keyboardPhysicalModifierSourceMask;
@property (nonatomic) NSUInteger keyboardRemoteModifierMask;
@property (nonatomic) BOOL keyboardModifierReleaseInProgress;
@property (nonatomic, strong) NSDictionary<NSNumber *, NSNumber *> *mappings;
@property (nonatomic, strong) NSMutableSet<NSNumber *> *keyboardSuppressedKeyDownKeyCodes;
@property (nonatomic, strong) NSMutableSet<NSNumber *> *keyboardForwardedKeyDownKeyCodes;
- (void)updateKeyboardPhysicalModifierStateFromEvent:(NSEvent *)event;
- (NSUInteger)desiredRemoteKeyboardModifierMaskForEvent:(NSEvent *)event;
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event;
- (void)sendSyntheticRemoteModifierTapForFlags:(NSEventModifierFlags)modifierFlags;
- (void)sendSyntheticRemoteShortcut:(StreamShortcut *)shortcut;
- (short)translateKeyCodeWithEvent:(NSEvent *)event;
- (char)translateKeyModifierWithEvent:(NSEvent *)event;
- (void)keyDown:(NSEvent *)event;
- (void)releaseAllModifierKeys;
@end

@implementation MLModifiersUnderProbe
- (instancetype)init {
    if ((self = [super init])) {
        _shouldSendInputEvents = YES;
        // Tab, W and Space, as the shipping table maps them (HIDSupport.m's own
        // KeyMapping table: 13 -> 'W', 48 -> 0x0F, 49 -> 0x20).
        _mappings = @{ @48: @(0x0F), @13: @(0x57), @49: @(0x20) };
        _keyboardSuppressedKeyDownKeyCodes = [NSMutableSet set];
        _keyboardForwardedKeyDownKeyCodes = [NSMutableSet set];
    }
    return self;
}
"""

TEST_BODY = r"""
__RESOLVER_BODY__
@end

static int gFailures = 0;

// Each scenario starts from a clean machine: no packets recorded, no modifier held,
// and nothing in the tracker. Reusing state between scenarios would compare one
// scenario's host against another scenario's tracker and prove nothing.
static void Reset(MLModifiersUnderProbe *k) {
    [gHostEvents removeAllObjects];
    k.keyboardPhysicalModifierSourceMask = 0;
    k.keyboardRemoteModifierMask = 0;
}
static NSString *Seq(void) { return [gHostEvents componentsJoinedByString:@" "]; }

static NSMutableString *Exp(void) { return [NSMutableString string]; }
static void Add(NSMutableString *expectation, NSString *packet) {
    if (expectation.length) [expectation appendString:@" "];
    [expectation appendString:packet];
}

static NSEvent *FlagsEvent(unsigned short keyCode, NSEventModifierFlags held) {
    return [NSEvent keyEventWithType:NSEventTypeFlagsChanged location:NSZeroPoint
                        modifierFlags:held timestamp:0 windowNumber:0 context:nil
                         characters:@"" charactersIgnoringModifiers:@""
                           isARepeat:NO keyCode:keyCode];
}

// Mirrors -flagsChanged: in HIDSupport.m: physical state first, then the sync.
static void FlagsChanged(MLModifiersUnderProbe *k, unsigned short keyCode, NSEventModifierFlags held) {
    [k updateKeyboardPhysicalModifierStateFromEvent:FlagsEvent(keyCode, held)];
    [k syncKeyboardModifierStateForEvent:FlagsEvent(keyCode, held)];
}

static NSEvent *KeyDownEvent(unsigned short keyCode, NSEventModifierFlags held) {
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint
                        modifierFlags:held timestamp:0 windowNumber:0 context:nil
                         characters:@"" charactersIgnoringModifiers:@""
                           isARepeat:NO keyCode:keyCode];
}

// Mirrors -keyDown: in HIDSupport.m, which syncs the modifier state and then sends the
// key with the modifier byte that same tracker produced. It does not re-read the
// physical state: only -flagsChanged: does, and an edge that has already happened does
// not happen again. That is the whole reason a release issued mid-hold survives.
static void PressKey(MLModifiersUnderProbe *k, unsigned short keyCode, NSEventModifierFlags held) {
    [k keyDown:KeyDownEvent(keyCode, held)];
}

static StreamShortcut *Rule(NSInteger keyCode, NSEventModifierFlags modifiers) {
    StreamShortcut *shortcut = [[StreamShortcut alloc] init];
    shortcut.keyCode = keyCode;
    shortcut.modifierFlags = modifiers;
    shortcut.modifierOnly = NO;
    return shortcut;
}

// What the host believes is held, derived only from the packets it received. This is
// the half the app cannot see, and the whole point of the invariant below.
static NSUInteger HostHeldMask(void) {
    NSUInteger mask = 0;
    struct { unsigned short vk; NSUInteger bit; } table[] = {
        { 0xA0, KMR_Remote_LeftShift }, { 0xA1, KMR_Remote_RightShift },
        { 0xA2, KMR_Remote_LeftControl }, { 0xA3, KMR_Remote_RightControl },
        { 0xA4, KMR_Remote_LeftAlt }, { 0xA5, KMR_Remote_RightAlt },
        { 0x5B, KMR_Remote_LeftMeta }, { 0x5C, KMR_Remote_RightMeta },
    };
    for (NSString *packet in gHostEvents) {
        unsigned short vk = (unsigned short)strtoul([packet substringToIndex:4].UTF8String, NULL, 16);
        BOOL down = [packet characterAtIndex:4] == 'D';
        for (size_t i = 0; i < sizeof(table) / sizeof(table[0]); i++) {
            if (table[i].vk != vk) continue;
            if (down) mask |= table[i].bit; else mask &= ~table[i].bit;
        }
    }
    return mask;
}

static void Expect(const char *name, NSString *expected, NSString *got) {
    BOOL ok = [expected isEqualToString:got];
    if (!ok) gFailures++;
    printf("%-4s %s\n", ok ? "ok" : "FAIL", name);
    if (!ok) {
        printf("        expected: %s\n        got:      %s\n",
               expected.UTF8String, got.UTF8String);
    }
}

// The invariant the defect breaks: whatever the app will diff against on the next
// event has to be what the host actually holds.
static void ExpectAgreement(const char *name, MLModifiersUnderProbe *k) {
    NSUInteger host = HostHeldMask(), app = k.keyboardRemoteModifierMask;
    BOOL ok = host == app;
    if (!ok) gFailures++;
    printf("%-4s %s and the host agree on the held modifiers (%s)\n", ok ? "ok" : "FAIL", name,
           ok ? "they do"
              : ([NSString stringWithFormat:@"app says 0x%02lX, the host holds 0x%02lX",
                 (unsigned long)app, (unsigned long)host].UTF8String));
}

int main(void) {
    @autoreleasepool {
        gHostEvents = [NSMutableArray array];
        MLModifiersUnderProbe *k = [[MLModifiersUnderProbe alloc] init];

        // 1. A rule on its own still presses, fires and releases. Everything below
        //    has to leave this behaviour alone.
        Reset(k);
        [k sendSyntheticRemoteShortcut:Rule(kVK_Tab, NSEventModifierFlagShift)];
        NSMutableString *want = Exp();
        Add(want, Ev(0xA0, YES, MODIFIER_SHIFT));
        Add(want, Ev(0x8000 | 0x0F, YES, MODIFIER_SHIFT));
        Add(want, Ev(0x8000 | 0x0F, NO, MODIFIER_SHIFT));
        Add(want, Ev(0xA0, NO, 0));
        Expect("a Shift+Tab rule with nothing held presses, fires and releases Shift", want, Seq());
        ExpectAgreement("a rule that started clean", k);

        // 2. The defect. Shift is held for real -- sprinting -- and a Shift+Tab rule
        //    fires. The rule owns nothing here: the player's finger is still down, and
        //    the tracker will never send Shift down again.
        Reset(k);
        FlagsChanged(k, kVK_Shift, NSEventModifierFlagShift);
        [k sendSyntheticRemoteShortcut:Rule(kVK_Tab, NSEventModifierFlagShift)];
        want = Exp();
        Add(want, Ev(0xA0, YES, MODIFIER_SHIFT));
        Add(want, Ev(0x8000 | 0x0F, YES, MODIFIER_SHIFT));
        Add(want, Ev(0x8000 | 0x0F, NO, MODIFIER_SHIFT));
        Expect("holding Shift, a Shift+Tab rule leaves the held Shift down", want, Seq());
        ExpectAgreement("the held-Shift scenario", k);

        // 3. Command, the neighbour of the old double-click-sends-Win bug.
        Reset(k);
        FlagsChanged(k, kVK_Command, NSEventModifierFlagCommand);
        [k sendSyntheticRemoteShortcut:Rule(kVK_Tab, NSEventModifierFlagCommand)];
        want = Exp();
        Add(want, Ev(0x5B, YES, MODIFIER_META));
        Add(want, Ev(0x8000 | 0x0F, YES, MODIFIER_META));
        Add(want, Ev(0x8000 | 0x0F, NO, MODIFIER_META));
        Expect("holding Command, a Command+Tab rule leaves the held Command down", want, Seq());
        ExpectAgreement("the held-Command scenario", k);

        // 4. The other synthetic entry point: tapping a modifier that is already held
        //    must send nothing at all, because a tap ends in a release.
        Reset(k);
        FlagsChanged(k, kVK_Control, NSEventModifierFlagControl);
        NSString *held_only = [Seq() copy];
        [k sendSyntheticRemoteModifierTapForFlags:NSEventModifierFlagControl];
        Expect("tapping Control while Control is held sends nothing new", held_only, Seq());
        ExpectAgreement("the held-Control tap", k);

        // 5. Releasing the held key has to produce exactly one release, however many
        //    rules fired in the middle.
        Reset(k);
        FlagsChanged(k, kVK_Shift, NSEventModifierFlagShift);
        [k sendSyntheticRemoteShortcut:Rule(kVK_Tab, NSEventModifierFlagShift)];
        [k sendSyntheticRemoteShortcut:Rule(kVK_Tab, NSEventModifierFlagShift)];
        NSString *before = Seq();
        FlagsChanged(k, kVK_Shift, 0);
        want = Exp();
        Add(want, Ev(0xA0, YES, MODIFIER_SHIFT));
        Add(want, Ev(0x8000 | 0x0F, YES, MODIFIER_SHIFT));
        Add(want, Ev(0x8000 | 0x0F, NO, MODIFIER_SHIFT));
        Add(want, Ev(0x8000 | 0x0F, YES, MODIFIER_SHIFT));
        Add(want, Ev(0x8000 | 0x0F, NO, MODIFIER_SHIFT));
        Add(want, Ev(0xA0, NO, 0));
        Expect("two rules while Shift is held still end in one Shift release", want, Seq());
        ExpectAgreement("the release after two rules", k);
        (void)before;

        // 6. A right-hand hold with a left-hand rule: the rule may press its own left
        //    key, but it must never lift the right one.
        Reset(k);
        FlagsChanged(k, kVK_RightShift, NSEventModifierFlagShift);
        [k sendSyntheticRemoteShortcut:Rule(kVK_Tab, NSEventModifierFlagShift)];
        BOOL liftedRight = [[Seq() componentsSeparatedByString:@" "]
                            containsObject:Ev(0xA1, NO, 0)];
        Expect("a Shift rule never lifts a held right Shift", @"kept",
               liftedRight ? @"lifted" : @"kept");
        ExpectAgreement("the right-hand hold", k);

        // 7. Nothing held: a lone tap is one press and one release.
        Reset(k);
        [k sendSyntheticRemoteModifierTapForFlags:NSEventModifierFlagShift];
        want = Exp();
        Add(want, Ev(0xA0, YES, MODIFIER_SHIFT));
        Add(want, Ev(0xA0, NO, 0));
        Expect("a lone Shift tap is one press and one release", want, Seq());
        ExpectAgreement("a lone tap", k);

        // 8. A rule that mixes a held modifier with an unheld one: it presses and
        //    releases only what it owns, and the held one survives intact.
        Reset(k);
        FlagsChanged(k, kVK_Shift, NSEventModifierFlagShift);
        [k sendSyntheticRemoteShortcut:Rule(kVK_Tab, NSEventModifierFlagShift | NSEventModifierFlagControl)];
        want = Exp();
        Add(want, Ev(0xA0, YES, MODIFIER_SHIFT));
        Add(want, Ev(0xA2, YES, MODIFIER_SHIFT | MODIFIER_CTRL));
        Add(want, Ev(0x8000 | 0x0F, YES, MODIFIER_SHIFT | MODIFIER_CTRL));
        Add(want, Ev(0x8000 | 0x0F, NO, MODIFIER_SHIFT | MODIFIER_CTRL));
        Add(want, Ev(0xA2, NO, 0));
        Expect("a rule keeps the held Shift and releases only its own Control", want, Seq());
        ExpectAgreement("the mixed hold", k);

        // 9. Two gameplay keys while a modifier is held, and a translation rule that
        //    no longer clears the keyboard between them. The player holds Option, runs
        //    on W, and jumps on Space: both presses have to carry Option, because the
        //    finger never left it.
        Reset(k);
        FlagsChanged(k, kVK_Option, NSEventModifierFlagOption);
        PressKey(k, kVK_ANSI_W, NSEventModifierFlagOption);
        PressKey(k, kVK_Space, NSEventModifierFlagOption);
        want = Exp();
        Add(want, Ev(0xA4, YES, MODIFIER_ALT));
        Add(want, Ev(0x8000 | 0x57, YES, MODIFIER_ALT));
        Add(want, Ev(0x8000 | 0x20, YES, MODIFIER_ALT));
        Expect("W then Space while Option is held both carry Option", want, Seq());
        ExpectAgreement("two gameplay keys under a held Option", k);

        // 10. The shape this repository used to have: a translation rule released all
        //     eight modifiers on the way through. The player is still holding Option,
        //     so nothing re-presses it -- -keyDown: only syncs against the tracker, and
        //     only -flagsChanged: re-reads the physical state, which an edge that has
        //     already happened will not do again. The next gameplay key therefore goes
        //     out with a modifier byte of zero: the sprint stops, the crouch stands up,
        //     and no log calls it a bug. This scenario asserts the damage, so the fix
        //     cannot be undone without one turning red.
        Reset(k);
        FlagsChanged(k, kVK_Option, NSEventModifierFlagOption);
        PressKey(k, kVK_ANSI_W, NSEventModifierFlagOption);
        [k releaseAllModifierKeys];
        PressKey(k, kVK_Space, NSEventModifierFlagOption);
        want = Exp();
        Add(want, Ev(0xA4, YES, MODIFIER_ALT));
        Add(want, Ev(0x8000 | 0x57, YES, MODIFIER_ALT));
        {
            unsigned short up[] = {0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5};
            for (size_t i = 0; i < sizeof(up) / sizeof(up[0]); i++) {
                Add(want, Ev(up[i], NO, 0));
            }
        }
        Add(want, Ev(0x8000 | 0x20, YES, 0));
        Expect("releasing every modifier mid-hold strips Option off the next key", want, Seq());
        BOOL optionStillDown = (HostHeldMask() & KMR_Remote_LeftAlt) != 0;
        Expect("the host stopped believing in an Option the player still holds", @"stopped",
               optionStillDown ? @"held" : @"stopped");

        printf("%d scenario failure(s)\n", gFailures);
    }
    return gFailures ? 1 : 0;
}
"""


def assemble(extracted):
    source = (PROLOGUE
              .replace("__MODIFIER_DEFINES__", modifier_defines())
              .replace("__RESOLVER_HEADER__", RESOLVER_H))
    return source + extracted + TEST_BODY.replace("__RESOLVER_BODY__", resolver_body())


# The shipped shape, rebuilt from the same source: every modifier the rule names is
# released when it finishes, held finger or not.
def unconditional_release(extracted):
    broken = extracted \
        .replace("HIDSyntheticOwnedModifierMask(support, remoteModifierMask)", "remoteModifierMask") \
        .replace("HIDSyntheticOwnedModifierMask(self, remoteModifierMask)", "remoteModifierMask")
    return broken


# The player-facing half of the rule: what a translation rule may do to the modifiers
# the player is holding. Expressed as a function over the shipping source so the same
# function can be run against the file and against a mutated copy of it.
KEYBOARD_LEAVING_ACTIONS = (
    "localActionDisconnectStream",
    "localActionShowDisconnectOptions",
    "localActionCloseAndQuitApp",
    "localActionReconnectStream",
    "localActionOpenControlCenter",
    "localActionReleaseMouseCapture",
    "localActionToggleBorderlessWindowed",
)
STREAM_KEeps_ACTIONS = (
    "localActionTogglePerformanceOverlay",
    "localActionToggleMouseMode",
    "localActionToggleFullscreenControlBall",
)


def translation_rule_release_problems(text):
    """Why a translation rule must not clear the keyboard it stays inside of."""
    problems = []
    handler = block_from(text, "- (BOOL)handleKeyboardTranslationRuleForEvent:(NSEvent *)event",
                         "the translation-rule handler")
    if "releaseAllModifierKeys" in handler:
        problems.append("a translation rule releases every modifier again, which takes "
                        "away a modifier the player is still holding")

    predicate = "+ (BOOL)keyboardTranslationLocalActionReleasesHeldModifiers:(NSString *)action"
    if predicate not in text:
        problems.append("nothing names which local actions may release held modifiers")
    else:
        body = block_from(text, predicate, "the release predicate")
        named = set(re.findall(r"KeyboardTranslationProfile\.(localAction\w+)", body))
        missing = [name for name in KEYBOARD_LEAVING_ACTIONS if name not in named]
        if missing:
            problems.append("the predicate no longer releases for: %s" % ", ".join(missing))
        inside = [name for name in STREAM_KEeps_ACTIONS if name in named]
        if inside:
            problems.append("the predicate releases for actions that keep the stream in "
                            "the foreground: %s" % ", ".join(inside))

    performer = block_from(text, "- (BOOL)performKeyboardTranslationLocalAction:(NSString *)action",
                          "the local-action runner")
    if "releaseAllModifierKeys" in performer:
        guarded = re.search(r"if\s*\(\s*\[\[self class\]\s+"
                            r"keyboardTranslationLocalActionReleasesHeldModifiers:", performer)
        if guarded is None:
            problems.append("the local-action runner releases modifiers without asking "
                            "whether the action takes the keyboard away")
    return problems


def blanket_release_returned(text):
    """The known-bad shape: the release, back at the entry point, unguarded."""
    anchor = """    KeyboardTranslationRule *rule = [self keyboardTranslationRuleMatchingEvent:event];
    if (rule == nil) {
        return NO;
    }
"""
    if text.count(anchor) != 1:
        raise SystemExit("the translation-rule handler no longer has the shape this "
                         "mutation expects, so it would prove nothing")
    return text.replace(anchor, anchor + "\n    [self.hidSupport releaseAllModifierKeys];\n", 1)


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        check.failures.append(message)
check.failures = []


def run_variant(directory, extracted, label):
    source_path = os.path.join(directory, "probe_%s.m" % label)
    open(source_path, "w", encoding="utf-8").write(assemble(extracted))
    binary = os.path.join(directory, "probe_%s" % label)
    cc, sdk = apple_toolchain.clang_and_sdk("keyboard shortcut modifier probe")
    cmd = [cc, "-fobjc-arc", "-fmodules", "-mmacosx-version-min=13.0", "-isysroot", sdk,
           "-framework", "AppKit", "-framework", "Foundation", source_path, "-o", binary]
    built = subprocess.run(cmd, capture_output=True, text=True)
    if built.returncode != 0:
        print("FAIL %s could not be compiled:\n%s" % (label, built.stderr.strip()[-1800:]))
        return None
    return subprocess.run([binary], capture_output=True, text=True)


def main():
    source = open(SOURCE, encoding="utf-8").read()
    extracted = extract(source)

    with tempfile.TemporaryDirectory() as tmp:
        shipped = run_variant(tmp, extracted, "shipped")
        if shipped is None:
            return 1
        print(shipped.stdout.rstrip())
        check(shipped.returncode == 0,
              "the shipped state machine passes every scenario"
              if shipped.returncode == 0 else
              "the shipped state machine fails %d scenario(s)" % shipped.returncode)

        check("HIDSyntheticOwnedModifierMask" in source,
              "the shipped source owns the rule that a synthetic sequence may only "
              "press and release modifiers it actually put down"
              if "HIDSyntheticOwnedModifierMask" in source else
              "no modifier-ownership rule in the shipped source: a synthetic shortcut "
              "releases modifiers the player is holding")

        stream_source = open(STREAM_VIEW, encoding="utf-8").read()
        found = translation_rule_release_problems(stream_source)
        check(not found,
              "a translation rule leaves a held modifier alone, and only the actions that "
              "take the keyboard away release one"
              if not found else
              "; ".join(found))

        restored = blanket_release_returned(stream_source)
        if restored == stream_source:
            print("FAIL the blanket-release shape is identical to the shipped file (no teeth)")
            return 1
        found = translation_rule_release_problems(restored)
        check(found,
              "the shape where a translation rule releases every modifier is refused (%s)"
              % found[0] if found else
              "putting the release back at the entry point changes nothing the harness sees")

        broken = unconditional_release(extracted)
        if broken == extracted:
            print("FAIL the known-bad shape is identical to the shipped shape (no teeth)")
            return 1
        bad = run_variant(tmp, broken, "unconditional")
        if bad is None:
            return 1
        print(bad.stdout.rstrip())
        check(bad.returncode != 0,
              "the unconditional-release shape is refused (%d scenario failure(s))"
              % bad.returncode if bad.returncode != 0 else
              "the known-bad shape passes: the scenarios have no teeth")

    print("%d harness failure(s)" % len(check.failures))
    return 1 if check.failures else 0


sys.exit(main())
