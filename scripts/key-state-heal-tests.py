#!/usr/bin/env python3
"""Prove the orphaned-press heal releases exactly what it should and nothing else.

A forwarded press with no matching release is a key the host repeats for the rest of the session --
that is the whole "double-click sends C over and over" symptom, whatever put the press in the stream.
The heal in -healUnpairedForwardedKeyDowns answers one question to the operating system: is anybody
holding this key? Physically held means leave it alone however long it lasts; physically released
means the release was lost between the driver and -keyUp:, so this app sends the release it never
got. It can only add a release, never suppress a press (docs/memory-ownership.md S32).

Four shapes have to hold, and each is the failure the others do not catch:

  * the orphan is healed -- a press nobody holds anymore comes back with its release, on the same
    wire code the press went out with;
  * a key that is really held is left alone -- the grace window must not turn into a watchdog that
    lifts the player's W after a quarter second, which is the "heuristics drop gameplay input"
    mistake of 2026-09-13 in a new costume;
  * inside the grace window nothing moves -- AppKit can hand over keyDown: before the HID key state
    flips, and healing there would release a press that is merely young;
  * a modifier is untouched -- chords belong to -releaseAllModifierKeys and flagsChanged:, and a
    healed Command would break shortcuts rather than fix a stuck letter.

Teeth, as every harness here has them: the three guards are deleted one at a time and each deletion
has to turn its scenario red. A gate that cannot fail is not measuring anything.
"""
import os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "Limelight", "Input", "HIDSupport.m")

SIGNATURES = [
    "- (void)keyDown:(NSEvent *)event",
    "- (void)keyUp:(NSEvent *)event",
    "- (short)translateKeyCodeWithEvent:(NSEvent *)event",
    "- (void)healUnpairedForwardedKeyDowns",
    "- (BOOL)holdKeyboardPressIfUnconfirmedForKeyCode:(unsigned short)physicalKeyCode",
    "- (void)settleHeldKeyboardPresses",
]

PROLOGUE = r"""
#import <AppKit/AppKit.h>

typedef struct MLInputStreamContext { int alive; } *PML_INPUT_STREAM_CONTEXT;
enum { KEY_ACTION_UP = 0, KEY_ACTION_DOWN = 1 };
#define LOG_I 0
#define LOG_D 0
#define Log(level, fmt, ...) ((void)0)

// The one question the heal asks the operating system, moved behind a name this harness owns, so a
// scenario can say "the keyboard says nobody holds this" without anybody holding anything.
#define CGEventSourceKeyState MLProbeKeyState
static NSMutableSet<NSNumber *> *gMLPhysicallyHeldKeys;
static bool MLProbeKeyState(CGEventSourceStateID stateID, CGKeyCode key) {
    return [gMLPhysicallyHeldKeys containsObject:@(key)];
}
// The clock the grace window is measured against, owned by the scenario.
static uint64_t gMLProbeNowMs = 0;
static uint64_t LiGetMillis(void) { return gMLProbeNowMs; }

static NSMutableArray<NSString *> *gHostEvents;
static void LiSendKeyboardEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short keyCode, char action,
                                   char modifiers) {
    [gHostEvents addObject:[NSString stringWithFormat:@"%04X%c", (unsigned)(keyCode & 0xFFFF),
                            action == KEY_ACTION_DOWN ? 'D' : 'U']];
}
static PML_INPUT_STREAM_CONTEXT HIDInputContext(id support) {
    static struct MLInputStreamContext ctx = { 1 };
    return &ctx;
}
static BOOL HIDValidateInputContext(PML_INPUT_STREAM_CONTEXT ctx, const char *op) {
    return ctx != NULL && ctx->alive;
}
static void HIDDispatchInput(id support, PML_INPUT_STREAM_CONTEXT ctx, void (^block)(void)) { block(); }
// The shipped question, without the shipped table: the heal excludes modifiers, so this has to answer
// YES for the codes the driver drives, or the exclusion is never exercised.
static BOOL HIDIsModifierKeyCode(unsigned short kc) {
    return kc == 56 || kc == 60 || kc == 57 || kc == 61 || kc == 58 || kc == 64 || kc == 59 || kc == 55;
}
static unsigned short HIDRemappedKeyCodeForModifierKey(id support, unsigned short kc) { return 0; }

@interface MLHealEvent : NSObject
@property (nonatomic) NSEventType type;
@property (nonatomic) unsigned short keyCode;
@property (nonatomic) NSEventModifierFlags modifierFlags;
@property (nonatomic) BOOL isARepeat;
@property (nonatomic) id window;
@end

@interface MLKeyboardHealProbe : NSObject
@property (nonatomic) BOOL shouldSendInputEvents;
@property (nonatomic) NSUInteger keyboardPhysicalModifierSourceMask;
@property (nonatomic) NSUInteger keyboardRemoteModifierMask;
@property (nonatomic, strong) NSMutableSet<NSNumber *> *keyboardSuppressedKeyDownKeyCodes;
@property (nonatomic, strong) NSMutableDictionary<NSNumber *, NSNumber *> *keyboardForwardedKeyDownKeyCodes;
@property (nonatomic, strong) NSMutableDictionary<NSNumber *, NSNumber *> *keyboardForwardedKeyDownAtMs;
@property (nonatomic, strong) NSMutableDictionary<NSNumber *, NSDictionary *> *keyboardHeldUnconfirmedKeyDowns;
@property (nonatomic, strong) dispatch_source_t keyboardStateHealTimer;
@property (nonatomic, strong) NSDictionary<NSNumber *, NSNumber *> *mappings;
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event;
- (void)updateKeyboardPhysicalModifierStateFromEvent:(NSEvent *)event;
- (char)translateKeyModifierWithEvent:(NSEvent *)event;
@end
"""

IMPL_HEAD = r"""
// The fake event carries only what the shipping keyDown: and keyUp: read off one; it is cast to
// NSEvent * at the call site, so anything else they reach for would raise, not silently pass.
@implementation MLHealEvent
@end

@implementation MLKeyboardHealProbe
- (instancetype)init {
    if ((self = [super init])) {
        _shouldSendInputEvents = YES;
        _keyboardSuppressedKeyDownKeyCodes = [NSMutableSet set];
        _keyboardForwardedKeyDownKeyCodes = [NSMutableDictionary dictionary];
        _keyboardForwardedKeyDownAtMs = [NSMutableDictionary dictionary];
        _keyboardHeldUnconfirmedKeyDowns = [NSMutableDictionary dictionary];
        // W is the gameplay key, Shift the chord. Codes are the Windows ones the host would see.
        _mappings = @{ @13: @(0x57), @56: @(0xA0) };
    }
    return self;
}
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event {}
- (void)updateKeyboardPhysicalModifierStateFromEvent:(NSEvent *)event {}
- (char)translateKeyModifierWithEvent:(NSEvent *)event { return 0; }
"""

TAIL = r"""
@end
"""

DRIVER = r"""
static int gFailed;

static NSString *HostSaw(void) { return [gHostEvents componentsJoinedByString:@" "]; }

static NSString *Scenario(NSString *name, unsigned short keyCode, BOOL heldAtPress,
                          BOOL heldAtHeal, uint64_t advanceMs, NSString *want) {
    [gHostEvents removeAllObjects];
    [gMLPhysicallyHeldKeys removeAllObjects];
    if (heldAtPress) {
        [gMLPhysicallyHeldKeys addObject:@(keyCode)];
    }
    gMLProbeNowMs = 1000;
    MLKeyboardHealProbe *probe = [[MLKeyboardHealProbe alloc] init];

    MLHealEvent *down = [[MLHealEvent alloc] init];
    down.type = NSEventTypeKeyDown;
    down.keyCode = keyCode;
    [probe keyDown:(NSEvent *)down];
    // The state may answer one way at the press and another way by the time the loop runs: a key
    // let go between the two is the orphan the heal exists for, and a key picked up between them
    // is the race a press must not be dropped over.
    [gMLPhysicallyHeldKeys removeAllObjects];
    if (heldAtHeal) {
        [gMLPhysicallyHeldKeys addObject:@(keyCode)];
    }
    gMLProbeNowMs += advanceMs;
    [probe healUnpairedForwardedKeyDowns];
    // No keyUp: is played on purpose: what a scenario measures is what the loop alone put on the
    // wire. A release driven here would be indistinguishable from one the loop sent.

    NSString *got = HostSaw();
    BOOL ok = [got isEqualToString:want];
    if (!ok) {
        gFailed++;
        printf("FAIL %s\n     host saw [%s], expected [%s]\n", name.UTF8String, got.UTF8String,
               want.UTF8String);
    } else {
        printf("ok   %s\n", name.UTF8String);
    }
    return got;
}

static void ScenarioDeniedOnceThenAdmitted(void) {
    [gHostEvents removeAllObjects];
    [gMLPhysicallyHeldKeys removeAllObjects];
    gMLProbeNowMs = 1000;
    MLKeyboardHealProbe *probe = [[MLKeyboardHealProbe alloc] init];

    MLHealEvent *down = [[MLHealEvent alloc] init];
    down.type = NSEventTypeKeyDown;
    down.keyCode = 13;
    [probe keyDown:(NSEvent *)down];
    // First pass: still denied, but inside the window, so the press must survive it.
    gMLProbeNowMs += 30;
    [probe healUnpairedForwardedKeyDowns];
    // Second pass: the keyboard now admits the key, and the press it holds back is owed to the host.
    [gMLPhysicallyHeldKeys addObject:@(13)];
    gMLProbeNowMs += 40;
    [probe healUnpairedForwardedKeyDowns];

    NSString *want = @"8057D";
    NSString *got = HostSaw();
    if (![got isEqualToString:want]) {
        gFailed++;
        printf("FAIL a press denied inside its window is kept, not dropped\n     host saw [%s], "
               "expected [%s]\n", got.UTF8String, want.UTF8String);
    } else {
        printf("ok   a press denied inside its window is kept, not dropped\n");
    }
}

int main(void) {
    @autoreleasepool {
        gHostEvents = [NSMutableArray array];
        gMLPhysicallyHeldKeys = [NSMutableSet set];

        // Held while the press arrives, let go before the loop runs: forwarded at once, and the
        // missing release is the one the heal puts on the wire.
        Scenario(@"a press nobody is holding anymore comes back with its release",
                 13, YES, NO, 300, @"8057D 8057U");
        Scenario(@"a key the player is really holding is left alone",
                 13, YES, YES, 300, @"8057D");
        Scenario(@"inside the race allowance nothing is released",
                 13, YES, NO, 100, @"8057D");
        Scenario(@"a modifier press is left to the modifier state machine",
                 56, NO, NO, 300, @"80A0D");
        // The ghost: the keyboard denies the key at the press and still denies it at the loop, so
        // the host must see neither edge. This is the run of keys the player complained about.
        Scenario(@"a press the keyboard denies at both ends never reaches the host",
                 13, NO, NO, 300, @"");
        // The other half of the same rule: a press the keyboard denies once and then admits is late,
        // never lost, and its release is still the heal's to send.
        Scenario(@"a press the keyboard admits at the loop still reaches the host",
                 13, NO, YES, 30, @"8057D");
        ScenarioDeniedOnceThenAdmitted();
        return gFailed == 0 ? 0 : 1;
    }
}
"""


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


GUARDS = {
    "asking the keyboard whether the key is still held":
        "        if (CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, (CGKeyCode)physical)) {\n"
        "            continue;  // physically down: this press is held, not orphaned\n"
        "        }\n",
    "the grace window that waits out the key-state race":
        "        if (ageMs < HIDKeyStateHealGraceMs) {\n            continue;\n        }\n",
    "the exclusion that leaves modifiers to their own state machine":
        "        if (HIDIsModifierKeyCode(physical)) {\n            continue;\n        }\n",
    "the question a real press answers for itself":
        "    if (CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, (CGKeyCode)physicalKeyCode)) {\n"
        "        return NO;  // physically down: forward it now, this is an ordinary press\n"
        "    }\n",
    "the exclusion that leaves a modifier press to be forwarded at once":
        "    if (HIDIsModifierKeyCode(physicalKeyCode)) {\n        return NO;\n    }\n",
    "the window a denied press waits out before it is dropped":
        "        if (ageMs < HIDKeyStateHoldConfirmMs) {\n            continue;\n        }\n",
}
# Which scenario each guard is the only thing protecting.
GUARD_VICTIMS = {
    "asking the keyboard whether the key is still held": "a key the player is really holding is left alone",
    "the grace window that waits out the key-state race": "inside the race allowance nothing is released",
    "the exclusion that leaves modifiers to their own state machine": "a modifier press is left to the modifier state machine",
    "the question a real press answers for itself": "a key the player is really holding is left alone",
    "the exclusion that leaves a modifier press to be forwarded at once": "a modifier press is left to the modifier state machine",
    "the window a denied press waits out before it is dropped": "a press denied inside its window is kept, not dropped",
}


def constants(text):
    """The two numbers the heal waits by, lifted out of the shipping file so the harness measures the
    real grace window instead of one it invented."""
    lines = [line for line in text.splitlines()
             if line.startswith("static uint64_t const HIDKeyState")]
    if len(lines) != 3:
        raise SystemExit("the heal loop's waiting numbers are no longer where they were: %r" % lines)
    hatch = [line for line in text.splitlines()
             if line.startswith("static NSString * const HIDKeyStateHoldDisabledDefault")]
    if len(hatch) != 1:
        raise SystemExit("the held-press escape hatch is no longer where it was: %r" % hatch)
    return "\n".join(lines + hatch) + "\n"


def build(support_text):
    parts = [PROLOGUE, constants(support_text), IMPL_HEAD]
    parts += [method(support_text, s) for s in SIGNATURES]
    parts.append(TAIL)
    return "\n".join(parts) + DRIVER


def compile_and_run(source, label):
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "probe.m")
        open(path, "w", encoding="utf-8").write(source)
        binary = os.path.join(work, "probe")
        cc = ["clang", "-fobjc-arc", "-framework", "AppKit", path, "-o", binary]
        result = subprocess.run(apple_toolchain.command(cc) if hasattr(apple_toolchain, "command") else cc,
                                capture_output=True, text=True)
        if result.returncode != 0:
            print("FAIL %s could not be compiled:\n%s" % (label, result.stdout + result.stderr))
            return None
        run = subprocess.run([binary], capture_output=True, text=True)
        print("\n-- %s --" % label)
        print(run.stdout, end="")
        return run.returncode


def main():
    support = open(SOURCE, encoding="utf-8", errors="replace").read()
    rc = compile_and_run(build(support), "the shipped heal loop")
    if rc in (None, 1):
        print("FAIL the heal loop does not do what it claims")
        return 1
    print("ok   the loop releases the orphan, holds nothing back from a real press, and keeps a denied press off the wire")

    failed = 0
    for guard, text in GUARDS.items():
        if support.count(text) != 1:
            print("FAIL the guard for %s cannot be found to remove (the source moved)" % guard)
            failed = 1
            continue
        broken = build(support.replace(text, "", 1))
        code = compile_and_run(broken, "known-bad: no %s" % guard)
        victim = GUARD_VICTIMS[guard]
        if code == 1:
            print("ok   removing %s turns '%s' red" % (guard, victim))
        else:
            print("FAIL removing %s did not fail the harness (it has no teeth)" % guard)
            failed = 1
    print("\n%d key-state-heal failure(s)" % failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
