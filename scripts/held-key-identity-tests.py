#!/usr/bin/env python3
"""Prove the held-key record identifies a press by the physical key, not by the
code that was dispatched.

The record exists so that capture can end while a key is still physically held:
keyUp: stops forwarding once input is off, so a press with no record leaves the
host holding that key for the rest of the session. Recording it under the code
that was dispatched looks equivalent and is not, because the shipping table maps
two different Mac keys onto the same Windows code -- Return and Keypad Enter both
go out as VK_RETURN, Equals and Keypad Equals both as VK_OEM_PLUS. A set keyed by
the dispatched code therefore holds ONE entry for TWO physical keys, and letting
go of either one spends the record that belonged to the other. The press the
player is still holding is then invisible, and capture ending behind it releases
nothing.

The scenarios come from the table itself: the colliding pairs are read out of
keys[] in HIDSupport.m, so the harness cannot drift away from the table that made
the collision real. Like every harness here it is checked for teeth, by running
the same scenarios against the shape that shipped before -- a set keyed by the
dispatched code -- which has to fail the collision scenarios while agreeing with
the shipping shape on every non-colliding key.

Exit 0 only when the shipping shape passes, the known-bad shape fails, and the
table still contains exactly the collisions this harness knows about.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "Limelight", "Input", "HIDSupport.m")
HIGH = 0x8000

# Virtual key codes for the keys this harness drives, taken from <Carbon/Carbon.h>.
MAC_KEY_CODES = {
    "kVK_Return": 0x24,
    "kVK_ANSI_KeypadEnter": 0x4C,
    "kVK_ANSI_Equal": 0x18,
    "kVK_ANSI_KeypadEquals": 0x51,
    "kVK_ANSI_W": 0x0D,
    "kVK_Space": 0x31,
}

SIGNATURES = [
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


def windows_code(literal):
    """The numeric value the C initializer for `short windows` denotes."""
    literal = literal.strip()
    if literal.startswith("'") and literal.endswith("'"):
        inner = literal[1:-1]
        escapes = {"\\r": 13, "\\n": 10, "\\t": 9, "\\b": 8, "\\\\": 92, "\\'": 39}
        if inner in escapes:
            return escapes[inner]
        if len(inner) == 1:
            return ord(inner)
        raise SystemExit("cannot read the Windows code %s" % literal)
    return int(literal, 0)


def table_pairs(text):
    """[(mac symbol, mac code, Windows code)] straight out of keys[]."""
    body = text.split("static struct KeyMapping keys[] = {", 1)[1].split("\n};", 1)[0]
    rows = []
    for line in body.splitlines():
        match = re.match(r"\s*\{\s*(kVK_\w+)\s*,\s*(.+?)\s*\},?\s*$", line)
        if not match:
            continue
        symbol, literal = match.group(1), match.group(2)
        if symbol not in MAC_KEY_CODES:
            continue
        rows.append((symbol, MAC_KEY_CODES[symbol], windows_code(literal)))
    return rows


def collisions(rows):
    by_code = {}
    for symbol, mac, win in rows:
        by_code.setdefault(win, []).append(symbol)
    return {code: sorted(names) for code, names in sorted(by_code.items()) if len(names) > 1}


PROLOGUE = r"""
#import <AppKit/AppKit.h>

typedef struct MLInputStreamContext { int alive; } *PML_INPUT_STREAM_CONTEXT;
enum { KEY_ACTION_UP = 0, KEY_ACTION_DOWN = 1 };
#define LOG_I 0
#define LOG_D 0
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
static BOOL HIDIsModifierKeyCode(unsigned short kc) { return NO; }
"""


# Every probe declares its own record type, because the difference under test is
# precisely which container the record uses.
DECLARATIONS = r"""
@interface MLKeyboardUnderProbe : NSObject
@property (nonatomic) BOOL shouldSendInputEvents;
@property (nonatomic) BOOL keyboardHeldKeyReleaseInProgress;
@property (nonatomic, strong) NSMutableSet<NSNumber *> *keyboardSuppressedKeyDownKeyCodes;
RECORD_PROPERTY
@property (nonatomic, strong) NSDictionary<NSNumber *, NSNumber *> *mappings;
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event;
- (short)translateKeyModifierWithEvent:(NSEvent *)event;
- (void)keyDown:(NSEvent *)event;
- (void)keyUp:(NSEvent *)event;
- (void)releaseAllHeldKeys;
- (short)translateKeyCodeWithEvent:(NSEvent *)event;
@end
"""

RECORD_AS_TABLE = "@property (nonatomic, strong) NSMutableDictionary<NSNumber *, NSNumber *> *keyboardForwardedKeyDownKeyCodes;"
RECORD_AS_SET = "@property (nonatomic, strong) NSMutableSet<NSNumber *> *keyboardForwardedKeyDownKeyCodes;"


def declarations(record):
    return DECLARATIONS.replace("RECORD_PROPERTY", record)


def epilogue(mapping_literal):
    return r"""
@implementation MLKeyboardUnderProbe
- (instancetype)init {
    if ((self = [super init])) {
        _shouldSendInputEvents = YES;
        _keyboardSuppressedKeyDownKeyCodes = [NSMutableSet set];
        _keyboardForwardedKeyDownKeyCodes = [NSMutableDictionary dictionary];
        _mappings = @{ """ + mapping_literal + r""" };
    }
    return self;
}
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event {}
- (short)translateKeyModifierWithEvent:(NSEvent *)event { return 0; }
"""


# The record exactly as it shipped before this round: the identity of a press is
# the code that went out, so two Mac keys that share a code share one record.
KNOWN_BAD = r"""
@implementation MLKeyboardUnderProbe
- (instancetype)init {
    if ((self = [super init])) {
        _shouldSendInputEvents = YES;
        _keyboardSuppressedKeyDownKeyCodes = [NSMutableSet set];
        _keyboardForwardedKeyDownKeyCodes = [NSMutableSet set];
        _mappings = @{ DICT };
    }
    return self;
}
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event {}
- (short)translateKeyModifierWithEvent:(NSEvent *)event { return 0; }
- (void)keyDown:(NSEvent *)event {
    if (event == nil || event.type != NSEventTypeKeyDown) return;
    if (self.shouldSendInputEvents) {
        [self syncKeyboardModifierStateForEvent:event];
        short translated = [self translateKeyCodeWithEvent:event];
        if (translated == 0) return;
        short keyCode = 0x8000 | translated;
        [self.keyboardForwardedKeyDownKeyCodes addObject:@(keyCode)];
        HIDDispatchInput(self, HIDInputContext(self), ^{
            LiSendKeyboardEventCtx(HIDInputContext(self), keyCode, KEY_ACTION_DOWN, 0);
        });
    }
}
- (void)keyUp:(NSEvent *)event {
    if (event == nil || event.type != NSEventTypeKeyUp) return;
    if (self.shouldSendInputEvents) {
        [self syncKeyboardModifierStateForEvent:event];
        short translated = [self translateKeyCodeWithEvent:event];
        if (translated == 0) return;
        short keyCode = 0x8000 | translated;
        [self.keyboardForwardedKeyDownKeyCodes removeObject:@(keyCode)];
        HIDDispatchInput(self, HIDInputContext(self), ^{
            LiSendKeyboardEventCtx(HIDInputContext(self), keyCode, KEY_ACTION_UP, 0);
        });
    }
}
- (void)releaseAllHeldKeys {
    if (self.keyboardHeldKeyReleaseInProgress) return;
    self.keyboardHeldKeyReleaseInProgress = YES;
    NSArray *held = self.keyboardForwardedKeyDownKeyCodes.allObjects;
    [self.keyboardForwardedKeyDownKeyCodes removeAllObjects];
    if (held.count == 0) { self.keyboardHeldKeyReleaseInProgress = NO; return; }
    HIDDispatchInput(self, HIDInputContext(self), ^{
        for (NSNumber *keyCode in held) {
            LiSendKeyboardEventCtx(HIDInputContext(self), keyCode.shortValue, KEY_ACTION_UP, 0);
        }
    });
    self.keyboardHeldKeyReleaseInProgress = NO;
}
- (short)translateKeyCodeWithEvent:(NSEvent *)event {
    if (!self.mappings[@(event.keyCode)]) return 0;
    return [self.mappings[@(event.keyCode)] shortValue];
}
@end
"""


def test_body(cases):
    """cases: [(name, firstMac, secondMac, wantNetZeroForShipping)]"""
    lines = []
    lines.append(r"""
static NSEvent *Key(unsigned short code, NSEventType type) {
    return [NSEvent keyEventWithType:type location:NSMakePoint(0, 0) modifierFlags:0
                        timestamp:0 windowNumber:0 context:nil
                        characters:@"x" charactersIgnoringModifiers:@"x" isARepeat:NO keyCode:code];
}
static NSString *Seq(void) {
    return [[gHostEvents copy] componentsJoinedByString:@" "];
}
static int gFailed;
static int gPresented;
static void Expect(const char *what, NSString *got, NSString *want) {
    gPresented++;
    BOOL ok = [got isEqual:want];
    printf("%-4s %s\n", ok ? "ok" : "FAIL", what);
    if (!ok) {
        printf("     host saw [%s], expected [%s]\n", got.UTF8String, want.UTF8String);
        gFailed++;
    }
}
static NSString *Scenario(unsigned short first, unsigned short second, NSString *label) {
    [gHostEvents removeAllObjects];
    MLKeyboardUnderProbe *k = [[MLKeyboardUnderProbe alloc] init];
    // Both hands confirm at once: the two keys that the table sends as one code.
    [k keyDown:Key(first, NSEventTypeKeyDown)];
    [k keyDown:Key(second, NSEventTypeKeyDown)];
    // The second finger lifts first.
    [k keyUp:Key(second, NSEventTypeKeyUp)];
    // Capture ends behind the finger that is still down -- mouse uncapture, the
    // window losing focus, the Space changing. Input stops being forwarded, then
    // the session asks for every held key to be let go.
    k.shouldSendInputEvents = NO;
    [k releaseAllHeldKeys];
    // The remaining finger comes off the key while input is still off, which is
    // the release that gets dropped and the reason the record has to cover it.
    [k keyUp:Key(first, NSEventTypeKeyUp)];
    k.shouldSendInputEvents = NO;
    [k releaseAllHeldKeys];
    NSString *seq = Seq();
    printf("     [%s] host saw %s\n", label.UTF8String, seq.UTF8String);
    return seq;
}
static int NetDown(NSString *seq, unsigned short code) {
    NSString *prefix = [NSString stringWithFormat:@"%04X", (unsigned)code];
    int net = 0;
    for (NSString *item in [seq componentsSeparatedByString:@" "]) {
        if (item.length != 5) continue;
        if ([[item substringToIndex:4] isEqualToString:prefix]) {
            net += ([item characterAtIndex:4] == 'D') ? 1 : -1;
        }
    }
    return net;
}
int main(void) {
    @autoreleasepool {
        gHostEvents = [NSMutableArray array];
""")
    for name, first, second, code in cases:
        lines.append('        {' + chr(10))
        lines.append('            NSString *seq = Scenario(%d, %d, @"%s");' % (first, second, name) + chr(10))
        lines.append('            Expect("no key is left pressed on the host after capture ends: %s",' % name)
        lines.append('                   [NSString stringWithFormat:@"%%d", NetDown(seq, 0x%04X)], @"0");' % (HIGH | code) + chr(10))
        lines.append('        }' + chr(10))
    lines.append(r"""        printf("scenarios presented: %d\n", gPresented);
        return gFailed ? 1 : 0;
    }
}
""")
    return "".join(lines)


def build_run(source, label):
    cc, sdk = apple_toolchain.clang_and_sdk()
    if not cc or not sdk:
        print("FAIL xcrun could not name a clang and SDK to build the %s probe" % label)
        return None
    with tempfile.TemporaryDirectory(prefix="held-key-identity-") as tmp:
        path = os.path.join(tmp, "probe.m")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        exe = os.path.join(tmp, "probe")
        build = subprocess.run([cc, "-fobjc-arc", "-O1", "-isysroot", sdk,
                                "-framework", "AppKit", "-o", exe, path],
                               capture_output=True, text=True)
        if build.returncode != 0:
            print("FAIL the %s probe does not compile:\n%s" % (label, build.stderr[-1500:]))
            return None
        ran = subprocess.run([exe], capture_output=True, text=True)
        print(ran.stdout.rstrip())
        return ran.returncode


def main():
    text = open(SOURCE, encoding="utf-8").read()
    rows = table_pairs(text)
    found = collisions(rows)

    print("table rows read for the driven keys: %d" % len(rows))
    if not found:
        print("FAIL the keyboard table no longer maps any two Mac keys to one Windows code")
        print("     -- the collision this harness guards has no subject left")
        return 1
    for code, names in found.items():
        print("collision: %-28s both reach the host as Windows code %d" % (" + ".join(names), code))

    # Drive every colliding pair, plus one non-colliding pair that the shipping
    # shape and the known-bad shape must agree on, so the difference the harness
    # reports is the collision and nothing else.
    cases = [(names[0] + "+" + names[1], mac_a, mac_b, code)
             for code, names in found.items()
             for mac_a, mac_b in [(MAC_KEY_CODES[names[0]], MAC_KEY_CODES[names[1]])]]
    cases.append(("W+Space (no shared code)", MAC_KEY_CODES["kVK_ANSI_W"],
                  MAC_KEY_CODES["kVK_Space"], 0x57))

    driven = {}
    for _, first, second, _ in cases:
        for mac in (first, second):
            for symbol, code_mac, code_win in rows:
                if code_mac == mac:
                    driven[mac] = code_win
    driven[MAC_KEY_CODES["kVK_Space"]] = 0x20
    mapping = ", ".join("@%d: @%d" % (mac, win) for mac, win in sorted(driven.items()))
    print("stand-in table: %s" % mapping)

    extracted = "\n\n".join(method(text, sig) for sig in SIGNATURES)
    shipping = (PROLOGUE + declarations(RECORD_AS_TABLE) + epilogue(mapping) +
                extracted + "\n@end\n" + test_body(cases))
    bad = (PROLOGUE + declarations(RECORD_AS_SET).replace("@end", "@end\n") +
           KNOWN_BAD.replace("DICT", mapping) + test_body(cases))

    print(chr(10) + "-- the shipping record --")
    verdict = build_run(shipping, "shipping")
    print(chr(10) + "-- the shape that shipped before: the record keyed by the dispatched code --")
    bad_verdict = build_run(bad, "known-bad")

    failures = 0
    if verdict != 0:
        print("FAIL the shipping record does not release every physical press")
        failures += 1
    else:
        print("ok   every physical press the host was told about comes back up")
    if bad_verdict == 0 or bad_verdict is None:
        print("FAIL the harness passed a record known to spend one key's record on another")
        failures += 1
    else:
        print("ok   the harness rejects the known-bad record (it has teeth)")

    print(chr(10) + "%d held-key-identity failures" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
