#!/usr/bin/env python3
"""Prove that a translation rule which takes a key also takes that key's release.

The report is W and Space colliding, and the shipping source names the mechanism
twice: a shortcut or rule bound to a bare key "deletes a movement or action key
from the host", and a rule that consumes a press without recording the debt leaves
"one orphan release ... the jump letting go early". Both are promises that span two
events. Neither is visible in any one line of code, and the rules already written
over this file count how often a method is called -- which stays green while the
state that has to outlive the call is wrong.

So this harness plays events. The matching method ships verbatim, together with the
suppression record in HIDSupport and the release path that reads it, and each case is
played three ways: a single press and release, two presses of the same key where the
first was taken by a rule and the second was not, and a press taken by a rule whose
release never arrives because the window went away while it was held. The last two are
where a stale record bites. The record a rule leaves has to be spent either by the
release that comes or by the next press of that key, and if neither spends it, the
release of a later press is swallowed as well and the key stays held down on the host.
One thousand five hundred and forty-four cases survive to be judged, because the third
shape needs a press a rule actually took and says so rather than expecting the
impossible.

The two keys played are the two from the report -- W and Space -- because those are
the codes the shipping mapping table knows, so a press of either reaches the host
recorder instead of being dropped as unmapped hardware, which would hide exactly the
release being looked for. Thirty-two modifier snapshots cover every combination of
the five flags the shortcut layer treats as relevant. Eight rule sets cover what a
stored rule can look like: the same key bare, the same key under one modifier and
under two, a different key under the event's own modifiers, a modifier-only trigger,
a trigger carrying no key code at all, and a set holding two rules so the walk past
a rejected shortcut is exercised. Every rule runs both ways through the guard,
because the promise checked here is that the matcher obeys the guard rather than
what the guard answers -- that answer belongs to Swift, which has its own type gate,
and an audit rule keeps this call site calling it.

Expected outcomes are derived separately, from a statement of what a rule means --
match the key code and the whole relevant modifier set, never a subset, never a
shortcut the guard turned down -- so the harness fails when the shipping matcher and
the rule part company rather than when either one merely changes. Only the pairing
and the count are asserted. What modifier byte a key carries is the promise another
harness owns, and re-deriving it here would put a second reader over that table.

A sweep that never reaches the branch it was written for still reports ok, and this
file did exactly that once: one stand-in forgot to carry the guard's answer, every
shortcut was therefore refused, no press was ever taken, no debt was ever recorded,
and the sweep came back green over every case while two of its planted shapes walked
free. Coverage is a claim, so the count of presses taken, presses released, releases
after a taken press, and taken presses whose release never came is printed and has to
be non-zero.

Exit 0 only when the sweep passes on the shipping source, its coverage is real, and
every planted shape fails.
"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAPTURE = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers",
                       "StreamViewController+MouseCapture.m")
INTERNAL = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers",
                        "StreamViewController_Internal.h")
SUPPRESS_SIGNATURE = "- (void)noteKeyboardKeyDownSuppressedForEvent:(NSEvent *)event"
MATCHER_SIGNATURE = ("- (KeyboardTranslationRule *)keyboardTranslationRuleMatchingEvent:"
                    "(NSEvent *)event")
RELEVANT_SIGNATURE = "static inline NSEventModifierFlags MLRelevantShortcutModifiers("
KEY_EVENT_SIGNATURE = "static inline BOOL MLIsKeyboardKeyEvent(NSEvent *event)"
GUARD_SIGNATURE = ("static inline BOOL MLShortcutUsesGameplayOnlyModifiers(")


def load_pair_harness():
    """The harness that already lifts this keyboard chain -- for the lift, not a copy.

    The recorder, the event stand-in, the resolver tables and the HIDSupport methods
    are facts owned by the shipping source and read there in one place. A second
    reader of them would drift, and the day it drifted this file would be checking a
    machine the app does not run.
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


STUBS = r"""
// The classes the matcher talks to are Swift, and what is under test is how the
// Objective-C matcher behaves towards them, not what they answer. Each stand-in
// carries the name the shipping source uses, so the matcher text compiled below is
// the shipping text with nothing adapted to fit it.
// A category would need the probe class already defined, and it is defined further
// down in the lifted recorder. The promise HIDSupport makes to a consumer is stated
// here instead, which is also the promise the shipping code is making.
@protocol MLKeyboardSuppression <NSObject>
- (void)noteKeyboardKeyDownSuppressedForEvent:(NSEvent *)event;
@end

@interface StreamShortcut : NSObject
@property (nonatomic) NSInteger keyCode;
@property (nonatomic) NSEventModifierFlags modifierFlags;
// What the profile answers for this shortcut. Both answers are swept: the matcher has
// to obey the guard whether it allows the shortcut or turns it down.
@property (nonatomic) BOOL guardAllowsMatch;
// The two things the gameplay guard reads. They are modelled the way the shipping
// StreamShortcut derives them, so a shape the guard has to refuse cannot be
// smuggled into the sweep as a shortcut that has no key code: -1 means no key,
// and a modifier-only binding never names one.
@property (nonatomic) BOOL modifierOnly;
- (BOOL)hasKeyCode;
@end
@implementation StreamShortcut
- (BOOL)hasKeyCode {
    return self.keyCode != -1;
}
@end

@interface KeyboardTranslationRule : NSObject
@property (nonatomic, strong) StreamShortcut *trigger;
@end
@implementation KeyboardTranslationRule
@end

static NSString *MLDisconnectEventSummary(NSEvent *event) {
    return [NSString stringWithFormat:@"keyCode=%lu mods=0x%lx",
            (unsigned long)event.keyCode,
            (unsigned long)(unsigned long)event.modifierFlags];
}

// The guard is not reimplemented here. Its answer is carried by the shortcut, and
// both answers get played, so nothing in this file can pass by agreeing with its own
// copy of a rule that really lives in Swift.
@interface StreamShortcutProfile : NSObject
+ (BOOL)shortcutCanMatchKeyboardEvent:(StreamShortcut *)shortcut;
@end
@implementation StreamShortcutProfile
+ (BOOL)shortcutCanMatchKeyboardEvent:(StreamShortcut *)shortcut {
    return shortcut != nil && shortcut.guardAllowsMatch;
}
@end

@interface MLHostUnderTest : NSObject
@property (nonatomic, copy) NSString *uuid;
@end
@implementation MLHostUnderTest
@end

@interface MLAppUnderTest : NSObject
@property (nonatomic, strong) MLHostUnderTest *host;
@end
@implementation MLAppUnderTest
@end

static NSArray *gRulesForHost;

@interface SettingsClass : NSObject
+ (NSArray *)keyboardTranslationRulesFor:(NSString *)key;
@end
@implementation SettingsClass
+ (NSArray *)keyboardTranslationRulesFor:(NSString *)key {
    return gRulesForHost != nil ? gRulesForHost : @[];
}
@end

@interface MLRuleProbe : NSObject
@property (nonatomic, strong) MLAppUnderTest *app;
// The view controller reaches HIDSupport the same way; the sweep hands it the probe.
@property (nonatomic, strong) id<MLKeyboardSuppression> hidSupport;
- (KeyboardTranslationRule *)keyboardTranslationRuleMatchingEvent:(NSEvent *)event;
- (BOOL)consumeKeyDownEvent:(NSEvent *)event;
@end
@implementation MLRuleProbe
- (instancetype)init {
    if ((self = [super init])) {
        _app = [[MLAppUnderTest alloc] init];
        _app.host = [[MLHostUnderTest alloc] init];
        _app.host.uuid = @"under-test-host";
    }
    return self;
}
"""

TAIL_RULE_PROBE = r"""
@end
"""

DRIVER = r"""
// The two keys from the report, and the only two played.
static const int kKeyCount = 2;
static const unsigned short kKeyCode[kKeyCount] = {13, 49};

static const int kModifierBitCount = 5;
static const NSEventModifierFlags kModifierBit[kModifierBitCount] = {
    NSEventModifierFlagShift, NSEventModifierFlagControl, NSEventModifierFlagOption,
    NSEventModifierFlagCommand, NSEventModifierFlagFunction,
};

static NSUInteger gChecked;
static NSUInteger gFailed;
static NSUInteger gShown;
// What the sweep actually reached. Without these, a sweep that never fires a rule
// still reports ok, and the planted shapes it cannot see pass beside it: this file
// did exactly that, green over all fifteen hundred and thirty-six cases, with every
// shortcut refused by its own guard so that no press was ever taken and no debt was
// ever recorded. Coverage is a claim, so it is counted and checked like one.
static NSUInteger gPressesTaken;
static NSUInteger gPressesReleased;
static NSUInteger gReleasesAfterATakenPress;
static NSUInteger gPressesTakenWhoseReleaseNeverCame;

// The rule as stated, not as coded: match the key code, match the whole relevant
// modifier set, and never match a shortcut the guard turned down. Written against the
// sweep's own inputs so it cannot reach the answer by reading the shipping method.
static BOOL RuleShouldMatch(StreamShortcut *trigger, unsigned short keyCode,
                            NSEventModifierFlags flags) {
    if (!trigger.guardAllowsMatch) {
        return NO;
    }
    // The matcher asks a second gate before a rule may take a key, and what is
    // promised here is that the matcher obeys every gate it asks. The answer is
    // taken from the shipping function rather than restated, so this file keeps
    // checking that the call site is obeyed instead of offering a second opinion
    // on what the answer should be. Gameplay answers belong to
    // scripts/gameplay-modifier-tests.py.
    if (MLShortcutUsesGameplayOnlyModifiers(MLRelevantShortcutModifiers(trigger.modifierFlags),
                                            trigger.hasKeyCode,
                                            trigger.modifierOnly)) {
        return NO;
    }
    if (trigger.keyCode != (NSInteger)keyCode) {
        return NO;
    }
    return MLRelevantShortcutModifiers(flags) == trigger.modifierFlags;
}

// Which rule the sweep expects to win, given that the shipping matcher answers with
// the first usable one it walks past.
static BOOL SweepExpectsMatch(NSArray *rules, unsigned short keyCode,
                              NSEventModifierFlags flags) {
    for (KeyboardTranslationRule *rule in rules) {
        if (RuleShouldMatch(rule.trigger, keyCode, flags)) {
            return YES;
        }
    }
    return NO;
}

static StreamShortcut *Shortcut(NSInteger keyCode, NSEventModifierFlags flags,
                                BOOL guardAllowsMatch) {
    StreamShortcut *shortcut = [[StreamShortcut alloc] init];
    shortcut.keyCode = keyCode;
    shortcut.modifierFlags = flags;
    shortcut.guardAllowsMatch = guardAllowsMatch;
    return shortcut;
}

static KeyboardTranslationRule *Rule(StreamShortcut *trigger) {
    KeyboardTranslationRule *rule = [[KeyboardTranslationRule alloc] init];
    rule.trigger = trigger;
    return rule;
}

static const int kRuleSetCount = 6;

static NSArray *RuleSet(int index, unsigned short eventKeyCode, NSEventModifierFlags flags,
                        BOOL guardAllowsMatch) {
    const unsigned short otherKeyCode = eventKeyCode == 13
                                        ? (unsigned short)49 : (unsigned short)13;
    const NSEventModifierFlags asEvent = MLRelevantShortcutModifiers(flags);
    switch (index) {
        case 0:
            return @[];
        case 1:
            // The bare key: the shape the settings form refuses, and the one stored
            // data cannot be trusted to have avoided.
            return @[ Rule(Shortcut(eventKeyCode, 0, guardAllowsMatch)) ];
        case 2:
            return @[ Rule(Shortcut(eventKeyCode, NSEventModifierFlagShift,
                                    guardAllowsMatch)) ];
        case 3:
            return @[ Rule(Shortcut(eventKeyCode, NSEventModifierFlagCommand,
                                    guardAllowsMatch)) ];
        case 4:
            // A different key under the very modifiers the event carries, so a matcher
            // that looked at modifiers alone would match here.
            return @[ Rule(Shortcut(otherKeyCode, asEvent, guardAllowsMatch)) ];
        default: {
            // Two rules, the unusable one first, so the walk past a rejected shortcut
            // has to reach the usable one sitting behind it.
            return @[ Rule(Shortcut(eventKeyCode, 0, NO)),
                      Rule(Shortcut(eventKeyCode, NSEventModifierFlagCommand,
                                     guardAllowsMatch)) ];
        }
    }
}

static NSEvent *Event(NSEventType type, unsigned short keyCode, NSEventModifierFlags flags) {
    return [MLKeyboardEventUnderTest eventWithType:type keyCode:keyCode flags:flags];
}

static BOOL PairTakenByRule(MLRuleProbe *ruleProbe, MLModifierPairProbe *probe,
                            unsigned short keyCode, NSEventModifierFlags flags,
                            BOOL dispatchRelease) {
    NSEvent *press = Event(NSEventTypeKeyDown, keyCode, flags);
    // The shipping decision drives the branch the app would take: a rule that takes the
    // key means AppKit never delivers -keyDown: for it, and the press is consumed the
    // way the shipping code consumes it -- through consumeKeyDownEvent:, because
    // "consumed but never recorded" is a defect worth being able to plant.
    const BOOL taken = [ruleProbe keyboardTranslationRuleMatchingEvent:press] != nil;
    if (taken) {
        [ruleProbe consumeKeyDownEvent:press];
    } else {
        [probe keyDown:press];
    }
    // The release is dispatched either way. Key equivalents are decided on the press
    // only, so a rule that took the key stops -keyDown: and nothing else: whether the
    // host hears this release is decided entirely by the record the consumer left.
    // A release that never arrives at all is the third case: the window went away, or
    // input was switched off, while the key was held.
    if (dispatchRelease) {
        [probe keyUp:Event(NSEventTypeKeyUp, keyCode, flags)];
    }
    return taken;
}

static NSString *CodeOf(NSString *hostEvent) {
    return [hostEvent substringToIndex:5];
}

static void Fail(NSString *caseName, NSArray<NSString *> *host, NSString *why) {
    gFailed++;
    if (gShown < 8) {
        gShown++;
        printf("     case      %s\n", [caseName UTF8String]);
        printf("     host saw  [%s]\n", [[host componentsJoinedByString:@" "] UTF8String]);
        printf("     %s\n", [why UTF8String]);
    }
}

enum { kScenarioOnce, kScenarioTwice, kScenarioReleaseNeverCame, kScenarioCount };

static void Check(NSArray *rules, unsigned short keyCode, NSEventModifierFlags flags,
                  int scenario, NSString *caseName) {
    const BOOL twoPresses = scenario != kScenarioOnce;
    if (scenario == kScenarioReleaseNeverCame && !SweepExpectsMatch(rules, keyCode, flags)) {
        // This shape needs a press the rule took. Play it without one and the release
        // that never arrives leaves an open edge here for a reason the app never has:
        // skipping is honest, and the coverage counter below refuses to let the whole
        // sweep lean on that skip.
        return;
    }
    gChecked++;
    gRulesForHost = rules;
    MLRuleProbe *ruleProbe = [[MLRuleProbe alloc] init];
    MLModifierPairProbe *probe = [[MLModifierPairProbe alloc] init];
    ruleProbe.hidSupport = (id<MLKeyboardSuppression>)probe;
    [gHostEvents removeAllObjects];

    // The promise being checked: the matcher's own answer, and the answer the rule as
    // stated requires. Reported apart from the pairing below, so a matcher that
    // disagrees with the rule shows up as that, not as a lost key.
    const BOOL firstTaken = PairTakenByRule(ruleProbe, probe, keyCode, flags,
                                            scenario != kScenarioReleaseNeverCame);
    BOOL firstExpected = SweepExpectsMatch(rules, keyCode, flags);
    if (firstTaken != firstExpected) {
        Fail(caseName, [gHostEvents copy], [NSString stringWithFormat:@"the matcher %@ the "
              "rule while the rule requires it to %@", firstTaken ? @"took" : @"released",
              firstExpected ? @"take" : @"release"]);
        return;
    }
    BOOL secondTaken = firstExpected;
    if (twoPresses) {
        // The same key again with nothing held, which is what a player does after a
        // rule fired once: press it, let it go. Whatever the first press did, this one
        // has to reach the host and come back up again.
        secondTaken = PairTakenByRule(ruleProbe, probe, keyCode, 0, YES);
        const BOOL secondExpected = SweepExpectsMatch(rules, keyCode, 0);
        if (secondTaken != secondExpected) {
            Fail(caseName, [gHostEvents copy], [NSString stringWithFormat:@"on the plain "
                  "second press the matcher %@ the rule while the rule requires it to %@",
                  secondTaken ? @"took" : @"released",
                  secondExpected ? @"take" : @"release"]);
            return;
        }
    }
    NSArray<NSString *> *host = [gHostEvents copy];

    if (firstTaken) {
        gPressesTaken++;
    } else {
        gPressesReleased++;
    }
    if (twoPresses && firstTaken && !secondTaken) {
        gReleasesAfterATakenPress++;
    }
    if (scenario == kScenarioReleaseNeverCame && firstTaken && !secondTaken) {
        gPressesTakenWhoseReleaseNeverCame++;
    }

    NSUInteger expectedEdges = firstTaken ? 0 : 2;
    if (twoPresses) {
        expectedEdges += secondTaken ? 0 : 2;
    }
    if (host.count != expectedEdges) {
        Fail(caseName, host, [NSString stringWithFormat:@"%@ the host should have seen %lu "
                              "edge(s) but saw %lu", caseName, (unsigned long)expectedEdges,
                              (unsigned long)host.count]);
        return;
    }
    // The codes the shipping mapping table turns W and Space into, and nothing else
    // may appear: an orphan release of a third key is its own report here.
    for (NSString *event in host) {
        unichar action = [event characterAtIndex:4];
        unsigned int code = (unsigned int)strtol([[event substringToIndex:4] UTF8String],
                                                 NULL, 16);
        unsigned short vk = (unsigned short)(code & 0x7FFF);
        if (vk != 0x57 && vk != 0x20) {
            Fail(caseName, host, [NSString stringWithFormat:@"the host was sent VK %02X, which "
                                  "nobody pressed", vk]);
            return;
        }
    }
    // Whatever reached the host has to come back up. Two presses and two releases of
    // the same key pair off; a swallowed release leaves one D with no U behind it.
    NSMutableArray<NSString *> *pending = [NSMutableArray array];
    for (NSString *event in host) {
        NSString *code = CodeOf(event);
        unichar action = [event characterAtIndex:4];
        if (action == 'D') {
            [pending addObject:code];
        } else {
            if (pending.count == 0) {
                Fail(caseName, host, [NSString stringWithFormat:@"%@ came up on the host "
                                      "without going down", [code substringFromIndex:4]]);
                return;
            }
            [pending removeObjectAtIndex:0];
        }
    }
    if (pending.count) {
        Fail(caseName, host, @"a key the host was told about never came back up");
    }
}

int main(void) {
    @autoreleasepool {
        gHostEvents = [NSMutableArray array];
        for (int key = 0; key < kKeyCount; key++) {
            for (int snapshot = 0; snapshot < (1 << kModifierBitCount); snapshot++) {
                NSEventModifierFlags flags = 0;
                for (int bit = 0; bit < kModifierBitCount; bit++) {
                    if (snapshot & (1 << bit)) {
                        flags |= kModifierBit[bit];
                    }
                }
                for (int setIndex = 0; setIndex < kRuleSetCount; setIndex++) {
                    for (int guard = 0; guard < 2; guard++) {
                        const BOOL guardAllowsMatch = guard == 1;
                        NSArray *rules = RuleSet(setIndex, kKeyCode[key], flags,
                                                 guardAllowsMatch);
                        NSString *stem = [NSString stringWithFormat:@"%@, modifiers 0x%lx, "
                                          @"rule set %d, guard %@",
                                          (kKeyCode[key] == 13 ? @"W" : @"Space"),
                                          (unsigned long)flags, setIndex + 1,
                                          guardAllowsMatch ? @"allows" : @"refuses"];
                        for (int scenario = 0; scenario < kScenarioCount; scenario++) {
                            NSString *prefix = @"one press of";
                            if (scenario == kScenarioTwice) {
                                prefix = @"twice, then plain, on";
                            } else if (scenario == kScenarioReleaseNeverCame) {
                                prefix = @"held while the window went, then plain, on";
                            }
                            Check(rules, kKeyCode[key], flags, scenario,
                                  [NSString stringWithFormat:@"%@ %@", prefix, stem]);
                        }
                    }
                }
            }
        }
        if (!gPressesTaken || !gPressesReleased || !gReleasesAfterATakenPress
            || !gPressesTakenWhoseReleaseNeverCame) {
            gFailed++;
            printf("     the sweep never reached a shape it needed: %lu taken, %lu "
                   "released, %lu released after a taken press, %lu taken with no "
                   "release\n", (unsigned long)gPressesTaken,
                   (unsigned long)gPressesReleased,
                   (unsigned long)gReleasesAfterATakenPress,
                   (unsigned long)gPressesTakenWhoseReleaseNeverCame);
        }
        printf("%s %lu cases of rule consumption checked, %lu failed\n",
               gFailed ? "FAIL" : "ok", (unsigned long)gChecked, (unsigned long)gFailed);
        printf("   coverage: %lu taken, %lu released, %lu released after a taken press, "
               "%lu taken with the release never arriving\n", (unsigned long)gPressesTaken,
               (unsigned long)gPressesReleased, (unsigned long)gReleasesAfterATakenPress,
               (unsigned long)gPressesTakenWhoseReleaseNeverCame);
        return gFailed ? 1 : 0;
    }
}
"""


CONSUME_SIGNATURE = "- (BOOL)consumeKeyDownEvent:(NSEvent *)event"

# Each shape is a way this chain could plausibly be written, that leaves the file
# compiling and the ordinary unbound key behaving, and breaks only across the two
# events. Anchors name the file they belong to so a move inside that file fails loudly.
KNOWNS_BAD = [
    ("subset-match", "capture",
     "if (event.keyCode == trigger.keyCode && relevantModifiers == trigger.modifierFlags) {",
     "if (event.keyCode == trigger.keyCode\n"
     "                && (relevantModifiers & trigger.modifierFlags) "
     "                       == trigger.modifierFlags) {",
     "a rule fires because some of its modifiers are held, so extra keys the player "
     "never bound it to take the key as well"),
    ("guard-ignored", "capture",
     "if (![StreamShortcutProfile shortcutCanMatchKeyboardEvent:trigger]) {",
     "if (NO) {",
     "a shortcut the guard turned down still takes the key, which is the bare binding "
     "that deletes a movement key from the host"),
    ("consume-without-debt", "consume",
     "[self.hidSupport noteKeyboardKeyDownSuppressedForEvent:event];",
     "/* the client took the key, and nothing records that it did */",
     "a consumed press records no debt, so its release is forwarded as an orphan"),
    ("stale-record", "hid",
     "[self.keyboardSuppressedKeyDownKeyCodes removeObject:@(event.keyCode)];",
     "/* the record from an earlier press of this key is kept */",
     "a press that reaches the host leaves an old suppression record behind, and the "
     "release of that press is swallowed with it"),
]

def plant(text, name, label):
    """Dirty one specific piece of lifted source, and refuse if it has moved.

    The anchor is checked against the exact piece the shape targets -- one method, or
    one whole file -- so a call site added elsewhere cannot quietly move a plant onto
    the wrong line, and a plant whose anchor is gone says so instead of passing.
    """
    _name, where, anchor, replacement, _why = shape(name)
    if where != label:
        raise SystemExit("shape %r is planted in %r, not %r" % (name, where, label))
    if text.count(anchor) != 1:
        raise SystemExit("the anchor for %s is not there exactly once in %s (%d times): %s"
                         % (name, label, text.count(anchor), anchor))
    return text.replace(anchor, replacement, 1)


def shape(name):
    for entry in KNOWNS_BAD:
        if entry[0] == name:
            return entry
    raise SystemExit("unknown known-bad shape %r" % name)


def build(module, known_bad=None):
    """The whole probe: lifted shipping source, the stand-ins it needs, this driver."""
    capture = module.read(CAPTURE)
    internal = module.read(INTERNAL)
    hid_source = module.read(module.SOURCE)
    name, where, _anchor, _replacement, _why = shape(known_bad) if known_bad else (None,)*5
    if where == "capture":
        capture = plant(capture, name, "capture")
    elif where == "hid":
        hid_source = plant(hid_source, name, "hid")

    helpers = "\n".join([
        module.static_function(internal, RELEVANT_SIGNATURE),
        module.static_function(internal, KEY_EVENT_SIGNATURE),
        # The matcher asks the gameplay guard before it lets a rule take a key, so
        # the model has to carry the same answer rather than a copy of it.
        module.static_function(internal, GUARD_SIGNATURE),
    ]) + "\n"

    matcher = module.method(capture, MATCHER_SIGNATURE)
    consume = module.method(capture, CONSUME_SIGNATURE)
    if where == "consume":
        consume = plant(consume, name, "consume")
    suppress = module.method(hid_source, SUPPRESS_SIGNATURE)

    rule_probe = (STUBS + "\n" + matcher + "\n" + consume + "\n" + TAIL_RULE_PROBE)
    hid_probe = (module.RECORDER + "\n" + suppress + "\n"
                 + module.method(hid_source, "- (void)keyDown:(NSEvent *)event")
                 + "\n" + "\n".join(
                     module.method(hid_source, signature)
                     for signature in module.METHODS
                     if signature != "- (void)keyDown:(NSEvent *)event")
                 + "\n" + module.TAIL)
    return (module.HEAD + module.modifier_defines() + "\n" + module.declarations()
            + "\n" + helpers + "\n" + rule_probe + "\n" + hid_probe + "\n" + DRIVER)


def main():
    module = load_pair_harness()
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "probe.m")
        print("-- which key does the host get, and does it come back --")
        failures = 0
        if module.compile_and_run(os.path.join(path), build(module), "rule consumption") != 0:
            failures = 1
        for name, _where, _anchor, _replacement, why in KNOWNS_BAD:
            print("\n-- known-bad: %s --" % why)
            if module.compile_and_run(os.path.join(work, "bad.m"),
                                       build(module, name), name) == 0:
                print("FAIL the sweep passed a state machine known to mishandle a consumed key")
                failures = 1
        print("\n%d rule-consumption failures" % failures)
        return failures


if __name__ == "__main__":
    sys.exit(main())
