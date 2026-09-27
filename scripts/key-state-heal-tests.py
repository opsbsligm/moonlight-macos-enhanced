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
// The key the leak arrives as, and the click it stands for. The harness names both because AppKit
// alone does not hand out either.
enum { kVK_ANSI_C = 8, BUTTON_LEFT = 0x01 };
// Counts what the stream UI was asked to spend a denied press on.
static int gMLStrayCalls;
static unsigned short gMLStrayLastKey;

// The shipped switch is opt-in, and the scenarios are about the behaviour behind it. Asked through
// one function precisely so this harness never writes into a real defaults domain.
#define HIDKeyboardHoldEnabled MLProbeHoldEnabled
static bool gMLProbeHoldEnabled = true;
static bool MLProbeHoldEnabled(void) { return gMLProbeHoldEnabled; }
// Two more questions the shipped code now asks before it holds a key back or spends it: does this
// machine have a pointer that publishes keyboard keys, and did the player ask for a press to become a
// click. Owned here so a scenario can answer them without defaults or a device attached.
#define HIDPointerDevicePublishesKeyboardKeys MLProbePointerPublishesKeyboard
#define HIDStrayClickConvertEnabled MLProbeConvertEnabled
static bool gMLProbePointerPublishesKeyboard = true;
static bool gMLProbeConvertEnabled = true;
static bool MLProbePointerPublishesKeyboard(void) { return gMLProbePointerPublishesKeyboard; }
static bool MLProbeConvertEnabled(void) { return gMLProbeConvertEnabled; }
// Which shipped configuration the next ScenarioStray measures: 0 keeps the switches the older
// scenarios were written against, 1 is an ordinary machine (no such pointer, hold not opted into),
// 2 is the measured machine with the conversion left off. Cleared on use, so no scenario after
// inherits it.
static int gMLStrayGate = 0;
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
@property (nonatomic) uint64_t lastTypedOtherKeyDownAtMs;
@property (nonatomic) uint64_t lastStrayClickAtMs;
@property (nonatomic, copy) BOOL (^strayKeyPressHandler)(unsigned short physicalKeyCode, uint64_t ageMs);
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
        _mappings = @{ @13: @(0x57), @56: @(0xA0), @123: @(0x25), @8: @(0x43) };
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

// One or more denied presses of the leaked key, with or without a listener, optionally right after
// another key was typed. What a scenario reports is how many times the stream UI was asked to spend
// a press, and what reached the host: a click that never left the harness must not be claimed.
static void ScenarioStray(NSString *name, BOOL installHandler, BOOL typedOtherFirst, int presses,
                          uint64_t gapMs, BOOL heldAtPress, int wantCalls, NSString *wantHost) {
    [gHostEvents removeAllObjects];
    [gMLPhysicallyHeldKeys removeAllObjects];
    gMLStrayCalls = 0;
    gMLStrayLastKey = 0xFFFF;
    gMLProbeNowMs = 1000;
    gMLProbeHoldEnabled = (gMLStrayGate == 0);
    gMLProbePointerPublishesKeyboard = (gMLStrayGate != 1);
    gMLProbeConvertEnabled = (gMLStrayGate != 2);
    gMLStrayGate = 0;
    MLKeyboardHealProbe *probe = [[MLKeyboardHealProbe alloc] init];
    if (installHandler) {
        probe.strayKeyPressHandler = ^BOOL(unsigned short key, uint64_t ageMs) {
            (void)ageMs;
            gMLStrayCalls++;
            gMLStrayLastKey = key;
            return YES;
        };
    }
    if (typedOtherFirst) {
        // A keystroke the keyboard really admits: it goes out on both edges and only leaves the
        // keystroke activity behind, which is the thing the typing test reads.
        [gMLPhysicallyHeldKeys addObject:@(13)];
        MLHealEvent *other = [[MLHealEvent alloc] init];
        other.type = NSEventTypeKeyDown;
        other.keyCode = 13;
        [probe keyDown:(NSEvent *)other];
        MLHealEvent *up = [[MLHealEvent alloc] init];
        up.type = NSEventTypeKeyUp;
        up.keyCode = 13;
        [probe keyUp:(NSEvent *)up];
    }
    for (int i = 0; i < presses; i++) {
        [gMLPhysicallyHeldKeys removeAllObjects];
        if (heldAtPress) {
            [gMLPhysicallyHeldKeys addObject:@(8)];
        }
        MLHealEvent *down = [[MLHealEvent alloc] init];
        down.type = NSEventTypeKeyDown;
        down.keyCode = 8;
        [probe keyDown:(NSEvent *)down];
        [gMLPhysicallyHeldKeys removeAllObjects];
        gMLProbeNowMs += gapMs;
        [probe healUnpairedForwardedKeyDowns];
    }

    NSString *gotHost = HostSaw();
    BOOL callsOk = (gMLStrayCalls == wantCalls) &&
                   (wantCalls == 0 || gMLStrayLastKey == kVK_ANSI_C);
    BOOL hostOk = [gotHost isEqualToString:wantHost];
    if (!callsOk || !hostOk) {
        gFailed++;
        printf("FAIL %s\n     asked for %d click(s) (wanted %d, last key %hu), host saw [%s], "
               "expected [%s]\n", name.UTF8String, gMLStrayCalls, wantCalls, gMLStrayLastKey,
               gotHost.UTF8String, wantHost.UTF8String);
    } else {
        printf("ok   %s\n", name.UTF8String);
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
        // Outside the region the key state speaks for, so the modifier is forwarded and not healed:
        // the region rule is what keeps the chord state machine's keys out of the held-back drawer.
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
        // The key state does not track the navigation cluster, so "nobody is holding it" is not
        // evidence of a phantom there: the left arrow must reach the host untouched. A real capture
        // dropped one of these while the ghost filter had no region boundary.
        Scenario(@"a navigation key the keyboard denies is forwarded anyway",
                 123, NO, NO, 100, @"8025D");
        // The other half of the ghost rule. A receiver that answers the left button as a keyboard
        // usage sends exactly this shape, so a denied C may not simply be thrown away.
        ScenarioStray(@"a denied C is spent on the click the device refused",
                      YES, NO, 1, 300, NO, 1, @"");
        // A C the keyboard admits is a keystroke: it must reach the host and must not click.
        ScenarioStray(@"a C the keyboard admits is typed and never clicked",
                      YES, NO, 1, 300, YES, 0, @"8043D 8043U");
        // Typing is the one thing that denies a key in good faith, and typists do not press only C.
        ScenarioStray(@"a denied C while the player is typing is not a click",
                      YES, YES, 1, 300, NO, 0, @"8057D 8057U");
        // With no listener the old answer is kept verbatim: neither edge of the press goes out.
        ScenarioStray(@"a denied C nobody is listening for stays dropped",
                      NO, NO, 1, 300, NO, 0, @"");
        ScenarioStray(@"two denied Cs inside the click guard spend one click",
                      YES, NO, 2, 100, NO, 1, @"");
        // The machine with no such pointer: nothing here can leak a letter out of a mouse button, so
        // the denied C is forwarded as it was before this device existed, and the heal - not the ghost
        // filter - is what sends the release for a press that never got one.
        gMLStrayGate = 1;
        ScenarioStray(@"a denied C is forwarded when no pointer publishes keyboard keys",
                      YES, NO, 1, 300, NO, 0, @"8043D 8043U");
        // The measured device is present but the player never asked for a press to become a click.
        // The measured receiver also sends the button whole, so spending this press would be a second
        // click: the phantom stops here and neither edge reaches the host.
        gMLStrayGate = 2;
        ScenarioStray(@"a denied C is dropped rather than clicked while the converter is off",
                      YES, NO, 1, 300, NO, 0, @"");
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
    "the window a denied press waits out before it is dropped":
        "        if (ageMs < HIDKeyStateHoldConfirmMs) {\n            continue;\n        }\n",
    "the region the key state is able to speak for":
        "    if (!HIDWireCodeIsKeyStateDetectable(wireCode)) {\n        return NO;\n    }\n",
    "the offer a denied press makes before it is thrown away":
        "            spent = self.strayKeyPressHandler(physical, ageMs);\n",
    "the typing test that keeps a typed C off the click path":
        "!typedRecently && ",
    "the keystroke activity the typing test measures against":
        "            self.lastTypedOtherKeyDownAtMs = (unsigned long long)LiGetMillis();\n",
    "the guard that stops one denied burst becoming a click storm":
        " && !clickedRecently",
    "the pointer that has to publish keyboard keys before a key is held back":
        "    if (strayClickWanted && !HIDPointerDevicePublishesKeyboardKeys()) {\n"
        "        strayClickWanted = NO;\n"
        "    }\n",
    "the switch that has to be thrown before a press becomes a click":
        "HIDStrayClickConvertEnabled() &&",
}
# Which scenario each guard is the only thing protecting.
GUARD_VICTIMS = {
    "asking the keyboard whether the key is still held": "a key the player is really holding is left alone",
    "the grace window that waits out the key-state race": "inside the race allowance nothing is released",
    "the exclusion that leaves modifiers to their own state machine": "a modifier press is left to the modifier state machine",
    "the question a real press answers for itself": "a key the player is really holding is left alone",
    "the window a denied press waits out before it is dropped": "a press denied inside its window is kept, not dropped",
    "the region the key state is able to speak for": "a navigation key the keyboard denies is forwarded anyway",
    "the offer a denied press makes before it is thrown away": "a denied C is spent on the click the device refused",
    "the typing test that keeps a typed C off the click path": "a denied C while the player is typing is not a click",
    "the keystroke activity the typing test measures against": "a denied C while the player is typing is not a click",
    "the guard that stops one denied burst becoming a click storm": "two denied Cs inside the click guard spend one click",
    "the pointer that has to publish keyboard keys before a key is held back": "a denied C is forwarded when no pointer publishes keyboard keys",
    "the switch that has to be thrown before a press becomes a click": "a denied C is dropped rather than clicked while the converter is off",
}


def constants(text):
    """The two numbers the heal waits by, lifted out of the shipping file so the harness measures the
    real grace window instead of one it invented."""
    lines = [line for line in text.splitlines()
             if line.startswith("static uint64_t const HIDKeyState")]
    if len(lines) != 3:
        raise SystemExit("the heal loop's waiting numbers are no longer where they were: %r" % lines)
    stray = [line for line in text.splitlines()
             if line.startswith("static uint64_t const HIDStrayClick")]
    if len(stray) != 2:
        raise SystemExit("the stray-click guard windows are no longer where they were: %r" % stray)
    hatch = [line for line in text.splitlines()
             if line.startswith("static NSString * const HIDKeyStateHoldEnabledDefault")]
    if len(hatch) != 1:
        raise SystemExit("the held-press switch is no longer where it was: %r" % hatch)
    return "\n".join(lines + stray + hatch) + "\n"


def detectable_helper(text):
    """The shipped 'can the key state speak for this key' rule, verbatim, so the harness measures the
    real region rather than a copy that could drift out of step with it."""
    signature = "static BOOL HIDWireCodeIsKeyStateDetectable(short wireCode) {"
    start = text.find(signature)
    if start < 0:
        raise SystemExit("the detectable-region rule is no longer where it was")
    end = text.find("\n}\n", start)
    if end < 0:
        raise SystemExit("the detectable-region rule has no end")
    return text[start:end + 3]


def stray_candidate_rule(text):
    """The shipped 'may a denied press stand for a click' rule, verbatim, so the harness cannot drift
    into clicking on a key the shipping code would never have spent."""
    signature = "static BOOL HIDKeyCodeIsStrayClickCandidate(unsigned short physicalKeyCode) {"
    start = text.find(signature)
    if start < 0:
        raise SystemExit("the stray-click candidate rule is no longer where it was")
    end = text.find("\n}\n", start)
    if end < 0:
        raise SystemExit("the stray-click candidate rule has no end")
    return text[start:end + 3]


def build(support_text):
    parts = [PROLOGUE, constants(support_text), detectable_helper(support_text),
             stray_candidate_rule(support_text), IMPL_HEAD]
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
