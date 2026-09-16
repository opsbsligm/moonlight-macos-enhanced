#!/usr/bin/env python3
"""Prove the shipping keyboard state machine survives every order the fingers can make.

The report is W and Space, walk and jump, colliding. Two harnesses already drive
that pair: one asks whether two ordinary keys stay two keys, another runs the
modifier chain for sprinting, and both pass. What neither does is ask about
*order*. Each of them plays one timeline that somebody wrote down, so the shapes
they cover are the shapes a person thought of -- and a stranded key is exactly the
kind of defect that lives in an order nobody pictured, like letting go of Shift
between the jump's press and its release.

So this harness enumerates instead of imagining. Four keys are given, each with
its own press-then-release pair -- left Shift and right Shift, W and Space -- and
every interleaving that keeps each key's own order is played: 2520 of them. Each
one gets a fresh controller, the real state machine, and a host recorder that
keeps the modifier byte beside the key code. AppKit's own conventions are
supplied rather than invented: a `flagsChanged:` carries the family bit plus the
bit for the key that just moved, and an ordinary key carries the flags of the
moment it was pressed.

Four things have to hold on every one of those orders. Every key the host was
told about goes down once and comes back up once, so nothing stays down and
nothing is invented -- and that includes the two shift keys, because a stranded
shift is the report this started from. Both modifier masks are empty when the
hands leave, so the host is not sprinting on its own. Every byte beside a key code
agrees with the shift keys the host was itself told about, because a byte that
disagrees is the moment a walk stops being a walk: the release that lifts a sprint
the other finger still holds, and the press that carries a spare bit, both hand the
host a different key than the one it was just told the name of. And nothing arrives
that is not one of the four keys, so a shift that goes out as control is its own
report rather than passing a looser modifier-range check.

One thing deliberately does not hold, and is not a defect: a release does not have
to repeat the byte its press carried. Letting go of Shift between the jump's press
and its release is ordinary play, and then the jump comes up without the sprint bit
because the host was already told about that shift coming up. Asserting equality
instead would fail most of the sweep for the rightest reason, so the rule is
agreement with the shifts the host holds, not equality with the byte from earlier.

Auto-repeat is deliberately absent: the shipped `keyDown:` forwards repeats as
fresh presses, which is upstream behaviour, audited and left alone, and a repeat
would break the pairing rule for a reason that is not a defect.

Exit 0 only when all 2520 orders pass and every planted shape fails.
"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def load_sibling():
    """The harness that already lifts this state machine -- for the lift, not a copy.

    Which methods and which statics make the keyboard chain, which bit is left
    shift, and which byte the host calls the shift modifier are facts owned by the
    shipping source and read from it in one place. A second reader of those facts
    would drift, and the day it drifted this harness would be checking a machine
    the app does not run.
    """
    spec = importlib.util.spec_from_file_location(
        "pair_harness", os.path.join(HERE, "held-modifier-keyboard-pair-tests.py"))
    module = importlib.util.module_from_spec(spec)
    argv = sys.argv
    sys.argv = [spec.origin]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.argv = argv
    return module

# The line that decides the byte beside a key code. It appears in -keyDown: and
# -keyUp:, and nothing else in the shipping source.
ANCHOR = "char modifiers = [self translateKeyModifierWithEvent:event];"

DRIVER = r"""
// The four keys, in the order the fingers usually reach them. 56 and 60 are the
// Mac's left and right shift; 13 and 49 are W and Space from the report.
static const int kKeyCount = 4;
static const unsigned short kKeyCode[kKeyCount] = {56, 13, 49, 60};
static NSUInteger gChecked;
static NSUInteger gFailed;
static NSUInteger gShown;
static NSMutableArray<NSArray *> *gScript;
static NSEventModifierFlags gLiveFlags;

static NSString *KeyName(unsigned short keyCode) {
    if (keyCode == 56) return @"LShift";
    if (keyCode == 60) return @"RShift";
    if (keyCode == 13) return @"W";
    return @"Space";
}

// Which edge a flagsChanged carries: the per-key bit for the key the event
// names is set while that key is down, so it says the direction the type cannot.
static BOOL ShiftIsDown(unsigned short keyCode, NSEventModifierFlags flags) {
    if (keyCode == 56) return (flags & NX_DEVICELSHIFTKEYMASK) != 0;
    if (keyCode == 60) return (flags & NX_DEVICERSHIFTKEYMASK) != 0;
    return YES;
}

// AppKit reports the family bit and the per-key bit together, and the family bit
// has to survive the first of two shifts coming up. Getting this wrong would make
// the probe disagree with a real keyboard in exactly the case this enumerates.
static NSEventModifierFlags FlagsAfter(NSEventModifierFlags flags, int index, BOOL down) {
    const NSEventModifierFlags shift = NSEventModifierFlagShift;
    if (kKeyCode[index] == 56) {
        if (down) return flags | shift | NX_DEVICELSHIFTKEYMASK;
        flags &= ~NX_DEVICELSHIFTKEYMASK;
        if (!(flags & NX_DEVICERSHIFTKEYMASK)) flags &= ~shift;
        return flags;
    }
    if (kKeyCode[index] == 60) {
        if (down) return flags | shift | NX_DEVICERSHIFTKEYMASK;
        flags &= ~NX_DEVICERSHIFTKEYMASK;
        if (!(flags & NX_DEVICELSHIFTKEYMASK)) flags &= ~shift;
        return flags;
    }
    return flags;
}

static void Drive(NSArray<NSArray *> *script, MLModifierPairProbe *probe) {
    for (NSArray *step in script) {
        NSEventType type = (NSEventType)[step[0] unsignedIntegerValue];
        NSEvent *event = (NSEvent *)[MLKeyboardEventUnderTest
                                     eventWithType:type
                                     keyCode:(unsigned short)[step[1] unsignedShortValue]
                                     flags:(NSEventModifierFlags)[step[2]
                                                                  unsignedLongLongValue]];
        if (type == NSEventTypeFlagsChanged) {
            [probe flagsChanged:event];
        } else if (type == NSEventTypeKeyDown) {
            [probe keyDown:event];
        } else {
            [probe keyUp:event];
        }
    }
}

// The host was told about these four keys and nothing else. A modifier byte for
// control, option or command is its own report, so the right shift going out as
// control fails here rather than passing a looser range check.
static BOOL IsHostedKey(unsigned short vk) {
    return vk == 0x57 || vk == 0x20 || vk == 0xA0 || vk == 0xA1;
}

// The host side name. KeyName is keyed on the Mac key code, and the two differ by
// domain, so looking a VK up there would call both W and Space "Space".
static NSString *HostName(unsigned short vk) {
    if (vk == 0x57) return @"W";
    if (vk == 0x20) return @"Space";
    if (vk == 0xA0) return @"LShift";
    return @"RShift";
}

static NSString *Describe(NSArray<NSArray *> *script) {
    NSMutableArray *parts = [NSMutableArray array];
    for (NSArray *step in script) {
        unsigned short keyCode = (unsigned short)[step[1] unsignedShortValue];
        NSEventType type = (NSEventType)[step[0] unsignedIntegerValue];
        NSEventModifierFlags flags =
            (NSEventModifierFlags)[step[2] unsignedLongLongValue];
        const char *edge = "u";
        if (type == NSEventTypeKeyDown) edge = "d";
        else if (type == NSEventTypeFlagsChanged
                 && ShiftIsDown(keyCode, flags)) edge = "d";
        [parts addObject:[NSString stringWithFormat:@"%s%s",
                          [KeyName(keyCode) UTF8String], edge]];
    }
    return [parts componentsJoinedByString:@" "];
}

static void Fail(NSArray<NSArray *> *script, NSArray<NSString *> *host, NSString *why) {
    gFailed++;
    if (gShown < 6) {
        gShown++;
        printf("     order     [%s]\n", [Describe(script) UTF8String]);
        printf("     host saw  [%s]\n", [[host componentsJoinedByString:@" "] UTF8String]);
        printf("     %s\n", [why UTF8String]);
    }
}

static void Check(NSArray<NSArray *> *script) {
    gChecked++;
    MLModifierPairProbe *probe = [[MLModifierPairProbe alloc] init];
    [gHostEvents removeAllObjects];
    Drive(script, probe);
    NSArray<NSString *> *host = [gHostEvents copy];

    // What the host has been told so far. A shift it was told about and never told
    // out of is a shift it still holds, and MODIFIER_SHIFT is the only bit this
    // four-key sweep can ever put in the byte beside a key code. The rule is then
    // one rule, not a case list: every byte the host is handed has to agree with
    // the shift keys the host itself was told about. That is what a player means by
    // a jump colliding with a walk -- a jump the host reads as some other key
    // because the byte beside it disagreed with the sprint it still had.
    NSUInteger shiftsDown = 0;
    NSMutableSet<NSNumber *> *held = [NSMutableSet set];
    for (NSString *event in host) {
        unsigned int code = (unsigned int)strtol([[event substringToIndex:4] UTF8String],
                                                 NULL, 16);
        unichar action = [event characterAtIndex:4];
        unsigned int modifiers = (unsigned int)strtol([[event substringFromIndex:6] UTF8String],
                                                      NULL, 16);
        unsigned short vk = (unsigned short)(code & 0x7FFF);
        if (!IsHostedKey(vk)) {
            Fail(script, host, [NSString stringWithFormat:@"the host was sent VK %02X, "
                                 "which nobody pressed", vk]);
            return;
        }
        const BOOL isShift = vk == 0xA0 || vk == 0xA1;
        const BOOL down = action == 'D';
        if (down && [held containsObject:@(vk)]) {
            Fail(script, host, [NSString stringWithFormat:@"%@ went down on the host "
                                 "while it was already down", HostName(vk)]);
            return;
        }
        if (!down && ![held containsObject:@(vk)]) {
            Fail(script, host, [NSString stringWithFormat:@"%@ came up on the host "
                                 "without going down", HostName(vk)]);
            return;
        }
        if (down) {
            [held addObject:@(vk)];
        } else {
            [held removeObject:@(vk)];
        }
        if (isShift) {
            shiftsDown += down ? 1 : (shiftsDown ? -1 : 0);
        }
        const unsigned int expected = shiftsDown ? MODIFIER_SHIFT : 0;
        if (modifiers != expected) {
            Fail(script, host, [NSString stringWithFormat:@"%@%c carries byte %02X while "
                                 "the host holds %lu shift(s), so the byte must be %02X",
                                 HostName(vk), down ? 'D' : 'U', modifiers,
                                 (unsigned long)shiftsDown, expected]);
            return;
        }
    }
    if (held.count) {
        Fail(script, host, @"a key the host was told about never came back up");
        return;
    }
    const BOOL masksClear = probe.keyboardRemoteModifierMask == 0
                            && probe.keyboardPhysicalModifierSourceMask == 0;
    if (!masksClear) {
        Fail(script, host, [NSString stringWithFormat:@"the hands left but the host still "
                             "holds modifiers (remote 0x%lX, physical 0x%lX)",
                             (unsigned long)probe.keyboardRemoteModifierMask,
                             (unsigned long)probe.keyboardPhysicalModifierSourceMask]);
    }
}
static void Recurse(int *position, int placed) {
    if (placed == kKeyCount * 2) {
        Check(gScript);
        return;
    }
    for (int index = 0; index < kKeyCount; index++) {
        if (position[index] >= 2) continue;
        BOOL down = position[index] == 0;
        NSEventModifierFlags next = FlagsAfter(gLiveFlags, index, down);
        NSEventType type = (kKeyCode[index] == 56 || kKeyCode[index] == 60)
                           ? NSEventTypeFlagsChanged
                           : (down ? NSEventTypeKeyDown : NSEventTypeKeyUp);
        [gScript addObject:@[@(type), @(kKeyCode[index]), @(next)]];
        NSEventModifierFlags held = gLiveFlags;
        gLiveFlags = next;
        position[index]++;
        Recurse(position, placed + 1);
        position[index]--;
        gLiveFlags = held;
        [gScript removeLastObject];
    }
}

int main(void) {
    @autoreleasepool {
        gHostEvents = [NSMutableArray array];
        gScript = [NSMutableArray array];
        int position[kKeyCount] = {0, 0, 0, 0};
        Recurse(position, 0);
        printf("%s %lu orders of four keys checked, %lu failed\n",
               gFailed ? "FAIL" : "ok", (unsigned long)gChecked, (unsigned long)gFailed);
        return gFailed ? 1 : 0;
    }
}
"""

# Only an order where Shift moves between a key's press and its release can show
# this one, which is the case a hand-written timeline tends to leave out.
# Each shape is a plausible way to write this code wrong, and each names the edge it
# breaks on: the anchor occurs once in -keyDown: and once in -keyUp:, so the ordinal
# says which one. They all leave the key codes right, which is why a hand-written
# timeline that never interleaves a shift with a key edge does not see them.
KNOWNS_BAD = [
    ("press-drops-the-sprint-still-held", 1,
     ANCHOR,
     "char modifiers = (char)([self translateKeyModifierWithEvent:event] "
     "& ~MODIFIER_SHIFT);",
     "a press is sent without the sprint the other finger is holding"),
    ("release-drops-the-sprint-still-held", 2,
     ANCHOR,
     "char modifiers = (char)([self translateKeyModifierWithEvent:event] "
     "& ~MODIFIER_SHIFT);",
     "a release lifts the sprint the other finger is still holding"),
    ("release-answers-with-the-raw-flag-bits", 2,
     ANCHOR,
     "char modifiers = (char)((unsigned long long)[event modifierFlags] & 0xFFULL);",
     "a release carries the raw NSEvent flag bits instead of the host modifier byte"),
]


def replace_nth(body, anchor, replacement, ordinal):
    """Swap one specific occurrence of an anchor, and refuse if the anchor moved.

    The ordinal is only meaningful while the anchor appears twice, so a third call
    site added to the shipping source makes every known-bad fail loudly rather than
    quietly dirtying the wrong method.
    """
    found = body.count(anchor)
    if found != 2:
        raise SystemExit("the known-bad anchor is no longer in keyDown: and keyUp: "
                         "exactly once (found %d): %s" % (found, anchor))
    if ordinal not in (1, 2):
        raise SystemExit("known-bad ordinal %r is not one of the two key edges" % ordinal)
    pos = -1
    for _ in range(ordinal):
        pos = body.index(anchor, pos + 1)
    return body[:pos] + replacement + body[pos + len(anchor):]


def build(module, known_bad=None):
    """The whole probe: the lifted app source, plus this harness's own driver.

    `known_bad` is the shape to plant, or None for the code as it ships. The plant
    goes into the lifted methods, never into the driver, so a known-bad run checks
    the same state machine with one wrong line in it.
    """
    if known_bad:
        ordinal, anchor, replacement, _why = known_bad
        body = replace_nth(module.shipping_methods(), anchor, replacement, ordinal)
        implementation = module.RECORDER + body + module.TAIL
    else:
        implementation = module.implementation()
    return (module.HEAD + module.modifier_defines() + "\n" + module.declarations()
            + "\n" + implementation + "\n" + DRIVER)


def main():
    module = load_sibling()
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "probe.m")
        print("-- every order of LShift, RShift, W and Space --")
        failures = 0
        if module.compile_and_run(os.path.join(work, "probe.m"), build(module),
                                  "key order") != 0:
            failures = 1
        for name, ordinal, anchor, replacement, why in KNOWNS_BAD:
            print("\n-- known-bad: %s --" % why)
            shape = (ordinal, anchor, replacement, why)
            if module.compile_and_run(os.path.join(work, "bad.m"),
                                      build(module, shape), name) == 0:
                print("FAIL the exhaustive sweep passed a state machine known to release "
                      "with the wrong modifier")
                failures = 1
        print("\n%d key-order failures" % failures)
        return failures


if __name__ == "__main__":
    sys.exit(main())
