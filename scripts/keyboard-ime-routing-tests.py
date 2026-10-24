#!/usr/bin/env python3
"""K1.2 local IME composition.

Extracts the shipping keyboard state machine plus the IME session/commit
methods from Limelight/Input/HIDSupport.m verbatim, compiles them with
stubs for the host sender and the input-context dispatch, and drives the
result with real NSEvents through a fake text input context whose answer
to -handleEvent: the probe controls.

The contract under test:
  * a key the IME consumed never reaches the host as a key code,
  * a key the IME did not consume keeps its normal route,
  * a pending commit the IME produced reaches the host as one UTF-8 event,
  * the setting being off leaves the normal route untouched.

Exit 0 only when every scenario passes and the known-bad shape fails.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain
import ml_probe_fixture

ROOT = Path(__file__).resolve().parents[1]
SHIP = ROOT / "Limelight/Input/HIDSupport.m"
KEYMAP_HEADER = ROOT / "Limelight/Input/KeyboardMapResolver.h"


def _block(text, signature):
    start = text.find(signature)
    if start < 0:
        raise SystemExit("shipping source no longer contains %s" % signature)
    body = text.find("{", start)
    depth = 0
    for i in range(body, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                # typedefs close with "};" and the semicolon is part of the
                # declaration, not a statement following the block.
                if text[end:end + 1] == ";":
                    end += 1
                return text[start:end]
    raise SystemExit("unbalanced braces reading %s" % signature)


SIGNATURES = [
    # IME methods (the ones this probe exists for)
    "- (void)beginIMECompositionIfEnabled",
    "- (void)flushIMECommit",
    "- (void)endIMEComposition",
    # the keyboard state machine
    "- (void)noteKeyboardKeyDownSuppressedForEvent:(NSEvent *)event",
    "- (void)keyDown:(NSEvent *)event",
    "- (void)keyUp:(NSEvent *)event",
    "- (void)releaseAllHeldKeys",
    # helper methods the above reference
    "- (char)translateKeyModifierWithEvent:(NSEvent *)event",
    "- (char)translatedModifierFlagsForEvent:(NSEvent *)event",
    "- (NSUInteger)desiredRemoteKeyboardModifierMaskForEvent:(NSEvent *)event",
    "- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event",
    "- (void)updateKeyboardPhysicalModifierStateFromEvent:(NSEvent *)event",
    "- (short)translateKeyCodeWithEvent:(NSEvent *)event",
    "- (BOOL)holdKeyboardPressIfUnconfirmedForKeyCode:(unsigned short)physicalKeyCode",
    "- (void)refreshKeyboardModifiersForCapture",
]
STATIC_HELPER = "static BOOL HIDIMECurrentInputSourceComposes(void) {"
# commandKeyPreferenceForCurrentHost stays stubbed in the probe: it only reads
# the per-host setting, and the probe answers with the shipping default.

# Modifier bookkeeping the extracted modifier helpers lean on, verbatim.
STATIC_TYPEDefs = [
    "typedef NS_OPTIONS(NSUInteger, HIDKeyboardPhysicalModifierMask) {",
    "typedef NS_OPTIONS(NSUInteger, HIDKeyboardRemoteModifierMask) {",
    "static HIDKeyboardPhysicalModifierMask HIDPhysicalModifierMaskForKeyCode",
    "static NSEventModifierFlags HIDModifierFlagForKeyCode",
    "static NSEventModifierFlags HIDDeviceModifierMaskForKeyCode",
    "static BOOL HIDEventCarriesDeviceModifierState",
    "static HIDKeyboardPhysicalModifierMask HIDEffectivePhysicalModifierMaskForEvent",
    "static unsigned short HIDRemoteModifierKeyCode",
    "static char HIDRemoteModifierFlagsToGenericFlags",
    "static BOOL HIDIsModifierKeyCode",
]
STATIC_MISC = [
    "static BOOL HIDKeyboardHoldEnabled(void) {",
    "static BOOL HIDWireCodeIsKeyStateDetectable(short wireCode) {",
    "static unsigned short HIDRemappedKeyCodeForModifierKey",
]

PROLOGUE = r"""
#import <AppKit/AppKit.h>
#import <Carbon/Carbon.h>
#import <ApplicationServices/ApplicationServices.h>
#define CGEventSourceKeyState(stateID, key) true

@class HIDSupport;
typedef struct MLInputStreamContext { int alive; } *PML_INPUT_STREAM_CONTEXT;
enum { KEY_ACTION_UP = 0, KEY_ACTION_DOWN = 1 };
#define MODIFIER_SHIFT 0x01
#define MODIFIER_CTRL 0x02
#define MODIFIER_ALT 0x04
#define MODIFIER_META 0x08
#define LOG_D 0
#define LOG_I 0
#define Log(level, fmt, ...) ((void)0)

static uint64_t const HIDKeyStateHoldConfirmMs = 60;
static NSString * const HIDKeyStateHoldEnabledDefault = @"input.enableKeyStateHold";

static NSMutableArray<NSString *> *gHostKeys;
static NSMutableArray<NSString *> *gHostText;

static void LiSendKeyboardEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short keyCode,
                                   char action, char modifiers) {
    [gHostKeys addObject:[NSString stringWithFormat:@"%04X%c",
                          (unsigned)(keyCode & 0xFFFF),
                          action == KEY_ACTION_DOWN ? 'D' : 'U']];
}
static uint64_t gMLProbeNowMs = 0;
static uint64_t LiGetMillis(void) { return gMLProbeNowMs; }
static PML_INPUT_STREAM_CONTEXT HIDInputContext(id support) {
    static struct MLInputStreamContext ctx = { 1 };
    return &ctx;
}
static BOOL HIDValidateInputContext(PML_INPUT_STREAM_CONTEXT ctx, const char *op) {
    return ctx != NULL && ctx->alive;
}
static void HIDDispatchInput(id support, HIDInputLease lease, void (^block)(void)) {
    block();
}
"""


KMR_STUBS = r"""
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
@interface HIDKeyboardQuirkFilter : NSObject
- (BOOL)isKnownPointerKeyCode:(unsigned short)code timestamp:(NSTimeInterval)timestamp;
- (BOOL)shouldDeferKeyCode:(unsigned short)code timestamp:(NSTimeInterval)timestamp;
@end
@implementation HIDKeyboardQuirkFilter
- (BOOL)isKnownPointerKeyCode:(unsigned short)code timestamp:(NSTimeInterval)timestamp { (void)code; (void)timestamp; return NO; }
- (BOOL)shouldDeferKeyCode:(unsigned short)code timestamp:(NSTimeInterval)timestamp { (void)code; (void)timestamp; return NO; }
@end

// The mapping table links from KeyboardMapResolver.m in the app target; these
// scenarios only need the answers for the probe's keys and modifiers, so the
// stubs reproduce the shipped table for exactly those.
KMR_RemoteModifierMask KMR_RemoteMaskForPhysicalWithCommandPreference(
        KMR_PhysicalModifier phys, KMR_CommandPreference pref) {
    // Raw bit values of the remote modifier masks, so this stub needs no
    // dependency on the typedefs that arrive later in the probe.
    switch (phys) {
        case KMR_Phys_LeftShift:    return 0x01;
        case KMR_Phys_RightShift:   return 0x02;
        case KMR_Phys_LeftControl:  return 0x04;
        case KMR_Phys_RightControl: return 0x08;
        case KMR_Phys_LeftOption:   return 0x10;
        case KMR_Phys_RightOption:  return 0x20;
        case KMR_Phys_LeftCommand:
            if (pref == KMR_CommandPreferenceControl) return 0x04;
            return 0x40;
        case KMR_Phys_RightCommand:
            if (pref == KMR_CommandPreferenceControl) return 0x08;
            return 0x80;
        default: return 0;
    }
}
unsigned short KMR_RemoteVKForPhysicalKeyCodeWithCommandPreference(
        unsigned short keyCode, KMR_CommandPreference pref) {
    switch (keyCode) {
        case kVK_Shift:        return 0xA0;
        case kVK_RightShift:   return 0xA1;
        case kVK_Control:      return 0xA2;
        case kVK_RightControl: return 0xA3;
        case kVK_Option:       return 0xA4;
        case kVK_RightOption:  return 0xA5;
        case kVK_Command:      return pref == KMR_CommandPreferenceControl ? 0xA2 : 0x5B;
        case kVK_RightCommand: return pref == KMR_CommandPreferenceControl ? 0xA3 : 0x5C;
        default:               return 0;
    }
}
"""

# A fake text input context whose answer to -handleEvent: is controlled by a
# flag, so the probe can say "the IME consumed this key" or "it did not".
FAKE_CONTEXT = r"""
@interface MLFakeIMEContext : NSObject
@property (atomic) BOOL consume;
@property (atomic) NSUInteger handled;
- (instancetype)init;
- (BOOL)handleEvent:(NSEvent *)event;
@end
@implementation MLFakeIMEContext
- (instancetype)init {
    if ((self = [super init])) { _handled = 0; }
    return self;
}
- (BOOL)handleEvent:(NSEvent *)event {
    if (!self.consume) return NO;
    self.handled += 1;
    return YES;
}
@end
"""

# The shipping session/client pair, reduced to exactly what the extracted
# HIDSupport methods touch: the client records a commit, the session drains it.
FAKE_SESSION = r"""
@interface MLLocalIMETextClient : NSObject
@property (nonatomic) NSRect anchorRect;
@property (nonatomic, readonly) NSUInteger commits;
@property (nonatomic, readonly, nullable) NSString *pendingCommit;
- (void)insertText:(id)string replacementRange:(NSRange)replacementRange;
- (void)consumePendingCommit;
@end
@implementation MLLocalIMETextClient {
    NSMutableString *_pendingCommit;
    NSUInteger _commits;
}
- (instancetype)init {
    if ((self = [super init])) { _pendingCommit = [NSMutableString new]; }
    return self;
}
- (NSString *)pendingCommit {
    return _pendingCommit.length > 0 ? [_pendingCommit copy] : nil;
}
- (void)insertText:(id)string replacementRange:(NSRange)replacementRange {
    if ([string isKindOfClass:[NSString class]] && [string length] > 0) {
        [_pendingCommit appendString:(NSString *)string];
        _commits += 1;
    }
}
- (void)consumePendingCommit { [_pendingCommit setString:@""]; }
- (NSUInteger)commits { return _commits; }
@end

@interface MLLocalIMESession : NSObject
@property (nonatomic, strong, readonly) MLLocalIMETextClient *client;
@property (nonatomic, strong) NSTextInputContext *context;
@property (nonatomic, readonly) NSUInteger compositions;
@property (nonatomic, readonly) NSUInteger commits;
- (instancetype)initWithClient:(MLLocalIMETextClient *)client;
- (void)begin;
- (void)end;
- (NSString *)drainCommit;
@end
@implementation MLLocalIMESession {
    MLLocalIMETextClient *_client;
    NSTextInputContext *_context;
}
- (instancetype)initWithClient:(MLLocalIMETextClient *)client {
    if ((self = [super init])) { _client = client; }
    return self;
}
- (MLLocalIMETextClient *)client { return _client; }
- (void)begin { (void)0; }
- (void)end { (void)0; }
- (NSString *)drainCommit {
    NSString *t = [_client pendingCommit];
    if (t != nil) { [_client consumePendingCommit]; }
    return t;
}
- (NSUInteger)compositions { return 0; }
- (NSUInteger)commits { return _client.commits; }
@end
"""

PROBE_INTERFACE = r"""
@interface MLProbeIME : NSObject
@property (nonatomic) BOOL shouldSendInputEvents;
@property (nonatomic) BOOL imeLocalCompositionEnabled;
@property (nonatomic) NSRect imeCandidateAnchorRect;
@property (nonatomic, strong) MLLocalIMESession *imeSession;
@property (nonatomic) NSUInteger imeWatermarkCompositions;
@property (nonatomic) NSUInteger imeWatermarkCommits;
@property (nonatomic) BOOL keyboardHeldKeyReleaseInProgress;
@property (nonatomic) BOOL keyboardModifierReleaseInProgress;
@property (nonatomic, strong) NSMutableSet<NSNumber *> *keyboardSuppressedKeyDownKeyCodes;
@property (nonatomic, strong) NSMutableDictionary<NSNumber *, NSNumber *> *keyboardForwardedKeyDownKeyCodes;
@property (nonatomic, strong) NSMutableDictionary<NSNumber *, NSNumber *> *keyboardForwardedKeyDownAtMs;
@property (nonatomic, strong) NSMutableDictionary<NSNumber *, NSDictionary *> *keyboardHeldUnconfirmedKeyDowns;
@property (nonatomic, strong) HIDKeyboardQuirkFilter *keyboardQuirkFilter;
@property (nonatomic) NSNumber *keyboardCapsLockState;
@property (nonatomic) NSUInteger keyboardPhysicalModifierSourceMask;
@property (nonatomic) NSUInteger keyboardRemoteModifierMask;
@property (nonatomic, strong) NSDictionary<NSNumber *, NSNumber *> *mappings;
@end
"""

PROBE_IMPL = r"""
@implementation MLProbeIME
- (instancetype)init {
    if ((self = [super init])) {
        _shouldSendInputEvents = YES;
        _keyboardSuppressedKeyDownKeyCodes = [NSMutableSet set];
        _keyboardForwardedKeyDownKeyCodes = [NSMutableDictionary dictionary];
        _keyboardForwardedKeyDownAtMs = [NSMutableDictionary dictionary];
        _keyboardHeldUnconfirmedKeyDowns = [NSMutableDictionary dictionary];
        _keyboardQuirkFilter = [HIDKeyboardQuirkFilter new];
        _mappings = @{ @13: @(0x57), @49: @(0x20) };
    }
    return self;
}
// The shipping implementation reads the per-host setting; the probe has no
// hosts, so it answers the default the setting exists to override.
- (KMR_CommandPreference)commandKeyPreferenceForCurrentHost {
    return KMR_CommandPreferenceWin;
}
@end
"""

SCENARIOS = r"""
static NSEvent *Down(unsigned short kc) {
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint
                     modifierFlags:0 timestamp:0 windowNumber:0 context:nil
                     characters:@"" charactersIgnoringModifiers:@""
                     isARepeat:NO keyCode:kc];
}
static NSEvent *Up(unsigned short kc) {
    return [NSEvent keyEventWithType:NSEventTypeKeyUp location:NSZeroPoint
                     modifierFlags:0 timestamp:0 windowNumber:0 context:nil
                     characters:@"" charactersIgnoringModifiers:@""
                     isARepeat:NO keyCode:kc];
}
static void Clear(void) {
    [gHostKeys removeAllObjects];
    [gHostText removeAllObjects];
}
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL line %d\n", __LINE__); return 1; } } while (0)

// A probe whose IME context the fake controls, so scenarios can flip between
// "the IME took the key" and "it did not" mid-run.
static MLProbeIME *ProbeWithIME(MLFakeIMEContext **outFake) {
    MLProbeIME *probe = [MLProbeIME new];
    MLLocalIMETextClient *client = [MLLocalIMETextClient new];
    MLLocalIMESession *session = [[MLLocalIMESession alloc] initWithClient:client];
    MLFakeIMEContext *fake = [MLFakeIMEContext new];
    session.context = (NSTextInputContext *)fake;
    probe.imeSession = session;
    probe.imeLocalCompositionEnabled = YES;
    if (outFake) *outFake = fake;
    return probe;
}

int main(void) {
@autoreleasepool {
    gHostKeys = [NSMutableArray new];
    gHostText = [NSMutableArray new];

    // --- 1. Setting OFF: no session, normal route untouched ---
    MLProbeIME *off = [MLProbeIME new];
    off.imeLocalCompositionEnabled = NO;
    [off beginIMECompositionIfEnabled];
    CHECK(off.imeSession == nil);
    Clear();
    [off keyDown:Down(13)];
    CHECK(gHostKeys.count == 1 && [gHostKeys[0] isEqualToString:@"8057D"]);
    [off keyUp:Up(13)];
    CHECK(gHostKeys.count == 2 && [gHostKeys[1] isEqualToString:@"8057U"]);

    // --- 2. IME active and consuming: the key never reaches the host ---
    MLFakeIMEContext *fake;
    MLProbeIME *on = ProbeWithIME(&fake);
    fake.consume = YES;
    Clear();
    [on keyDown:Down(13)];
    CHECK(gHostKeys.count == 0 && gHostText.count == 0 && fake.handled == 1);
    [on keyUp:Up(13)];
    CHECK(gHostKeys.count == 0 && gHostText.count == 0 && fake.handled == 2);

    // --- 3. IME active but not consuming: normal route still works ---
    fake.consume = NO;
    Clear();
    [on keyDown:Down(13)];
    CHECK(gHostKeys.count == 1 && [gHostKeys[0] isEqualToString:@"8057D"]);
    [on keyUp:Up(13)];
    CHECK(gHostKeys.count == 2 && [gHostKeys[1] isEqualToString:@"8057U"]);

    // --- 4. A pending commit reaches the host as one UTF-8 event ---
    fake.consume = YES;
    MLLocalIMETextClient *client = on.imeSession.client;
    [client insertText:@"\u4e2d\u6587" replacementRange:NSMakeRange(0, 0)];
    Clear();
    [on keyDown:Down(13)];
    CHECK(gHostText.count == 1 && [gHostText[0] isEqualToString:@"\u4e2d\u6587"]);
    CHECK(gHostKeys.count == 0);

    // --- 5. shouldSendInputEvents NO: gated before the IME check ---
    on.shouldSendInputEvents = NO;
    Clear();
    [on keyDown:Down(13)];
    CHECK(gHostKeys.count == 0 && gHostText.count == 0);
    on.shouldSendInputEvents = YES;

    // --- 6. releaseAllHeldKeys flushes a pending commit ---
    [client insertText:@"\u6d4b\u8bd5" replacementRange:NSMakeRange(0, 0)];
    Clear();
    [on releaseAllHeldKeys];
    CHECK(gHostText.count == 1 && [gHostText[0] isEqualToString:@"\u6d4b\u8bd5"]);
    CHECK(gHostKeys.count == 0);

    puts("K1.2 IME routing replay passed");
    return 0;
}}
"""


def run(code):
    cc, sdk = apple_toolchain.clang_and_sdk("K1.2 IME routing replay")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        (p / "probe.m").write_text(code, encoding="utf-8")
        built = subprocess.run(
            [cc, "-fobjc-arc", "-fblocks", "-O1", "-isysroot", sdk,
             "-framework", "AppKit", "-framework", "Carbon",
             str(p / "probe.m"), "-o", str(p / "probe")],
            capture_output=True, text=True)
        if built.returncode:
            raise RuntimeError(built.stderr)
        return subprocess.run([str(p / "probe")], capture_output=True, text=True)


def main():
    shipping = SHIP.read_text()
    methods = "\n".join(_block(shipping, s) for s in SIGNATURES)
    ime_helper = _block(shipping, STATIC_HELPER)
    statics = "\n".join(_block(shipping, s) for s in STATIC_TYPEDefs + STATIC_MISC)

    # The real mapping table, so the probe answers for Command the same way the
    # shipped one does. Only its declarations are needed here; the table itself
    # links in from the app target and is not executed by these scenarios.
    keymap = KEYMAP_HEADER.read_text()
    keymap = keymap.replace('#import <Foundation/Foundation.h>', "").replace(
        '#import <Carbon/Carbon.h>', "").replace("#pragma once", "")

    # Statics precede the category implementation: C needs the file-scope
    # helpers in place before the extracted method bodies name them.
    out = PROLOGUE + "\n" + keymap + "\n" + KMR_STUBS + "\n" + FAKE_CONTEXT + "\n"
    out += FAKE_SESSION + "\n" + PROBE_INTERFACE + "\n"
    out += PROBE_IMPL + "\n"
    # The remap helper names the shipping class in its signature; the probe
    # is what passes itself, so the parameter takes the wider type.
    statics = statics.replace("HIDSupport *support", "id support")
    out += statics + "\n"
    out += "@implementation MLProbeIME (IMEProbe)\n"
    out += methods + "\n" + ime_helper + "\n"
    out += "@end\n"
    out = ml_probe_fixture.apply(out)

    # The fixture's abort stand-in for the text send would make every commit a
    # crash; this probe wants the commit recorded instead.
    out = out.replace(
        "static int LiSendUtf8TextEventCtx(void *ctx, const char *text, unsigned int length) {\n"
        "    (void)ctx; (void)text; (void)length; abort();\n}",
        "static int LiSendUtf8TextEventCtx(void *ctx, const char *text, unsigned int length) {\n"
        "    [gHostText addObject:[[NSString alloc] initWithBytes:text length:length\n"
        "                                                 encoding:NSUTF8StringEncoding]];\n"
        "    return 0;\n}")

    source = out + SCENARIOS
    result = run(source)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout.strip())

    # --- Mutation: keyDown no longer consults the IME session ---
    old = ("    if (self.imeSession != nil) {\n"
           "        BOOL imeConsumed = [self.imeSession.context handleEvent:event];\n"
           "        [self flushIMECommit];\n"
           "        if (imeConsumed) {\n"
           "            [self noteKeyboardKeyDownSuppressedForEvent:event];\n"
           "            return;\n"
           "        }\n"
           "    }")
    new = ("    if (NO) {\n"
           "        [self noteKeyboardKeyDownSuppressedForEvent:event];\n"
           "        return;\n"
           "    }")
    assert source.count(old) == 1, "keyDown IME block not found"
    result = run(source.replace(old, new, 1))
    assert result.returncode == 1 and "FAIL line" in result.stderr, "mutation not caught"
    print("caught: keyDown does not consult IME session")

    # --- Mutation: keyUp no longer consults the IME session (orphan UP) ---
    old = ("    if (self.imeSession != nil && self.shouldSendInputEvents) {\n"
           "        BOOL imeConsumed = [self.imeSession.context handleEvent:event];\n"
           "        [self flushIMECommit];\n"
           "        if (imeConsumed) {\n"
           "            return;\n"
           "        }\n"
           "    }")
    new = ("    if (NO) {\n"
           "        [self flushIMECommit];\n"
           "    }")
    assert source.count(old) == 1, "keyUp IME block not found"
    result = run(source.replace(old, new, 1))
    assert result.returncode == 1 and "FAIL line" in result.stderr, "mutation not caught"
    print("caught: keyUp does not consume the IME release (orphan UP)")

    # --- Mutation: flushIMECommit no longer sends the text ---
    old = "            LiSendUtf8TextEventCtx(ctx, captured.bytes, (unsigned int)captured.length);"
    new = "            (void)ctx; (void)captured;"
    assert source.count(old) == 1, "flush send site not found"
    result = run(source.replace(old, new, 1))
    assert result.returncode == 1 and "FAIL line" in result.stderr, "mutation not caught"
    print("caught: flushIMECommit drops the commit")

    return 0


if __name__ == "__main__":
    sys.exit(main())
