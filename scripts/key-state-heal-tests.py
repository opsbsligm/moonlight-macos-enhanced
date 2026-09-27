#!/usr/bin/env python3
"""Compile shipped keyboard transitions and check device quarantine, ownership and release.

The monitor and physical-state query are controlled dependencies. Every state transition
comes from HIDSupport.m. Mutations verify that pairing and capture gates are exercised.
"""
import os, re, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain
import ml_probe_fixture
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "Limelight", "Input", "HIDSupport.m")
SIGNATURES = ['- (void)keyDown:(NSEvent *)event', '- (void)keyUp:(NSEvent *)event', '- (short)translateKeyCodeWithEvent:(NSEvent *)event', '- (void)healUnpairedForwardedKeyDowns', '- (BOOL)holdKeyboardPressIfUnconfirmedForKeyCode:(unsigned short)physicalKeyCode', '- (void)settleHeldKeyboardPresses', '- (void)releaseAllHeldKeys', '- (void)noteKeyboardKeyDownSuppressedForEvent:']
PROLOGUE = r"""
#import <AppKit/AppKit.h>
#import <Carbon/Carbon.h>

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
// The shipped switch is opt-in, and the scenarios are about the behaviour behind it. Asked through
// one function precisely so this harness never writes into a real defaults domain.
#define HIDKeyboardHoldEnabled MLProbeHoldEnabled
static bool gMLProbeHoldEnabled = true;
static bool MLProbeHoldEnabled(void) { return gMLProbeHoldEnabled; }
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

static BOOL gHealEnabled = YES;
#define HIDKeyboardHealEnabled() gHealEnabled
@interface HIDKeyboardQuirkFilter : NSObject
@property BOOL defer;
@property BOOL known;
- (BOOL)isKnownPointerKeyCode:(unsigned short)code timestamp:(NSTimeInterval)timestamp;
- (BOOL)shouldDeferKeyCode:(unsigned short)code timestamp:(NSTimeInterval)timestamp;
@end
@implementation HIDKeyboardQuirkFilter
- (BOOL)isKnownPointerKeyCode:(unsigned short)code timestamp:(NSTimeInterval)timestamp { return self.known && code == 8; }
- (BOOL)shouldDeferKeyCode:(unsigned short)code timestamp:(NSTimeInterval)timestamp { return self.defer && code == 8; }
@end
@interface MLHealEvent : NSObject
@property (nonatomic) NSEventType type;
@property (nonatomic) unsigned short keyCode;
@property (nonatomic) NSEventModifierFlags modifierFlags;
@property (nonatomic) BOOL isARepeat;
@property (nonatomic) NSTimeInterval timestamp;
@property (nonatomic) id window;
@end

@interface MLKeyboardHealProbe : NSObject
@property (nonatomic) BOOL shouldSendInputEvents;
@property (nonatomic) BOOL keyboardHeldKeyReleaseInProgress;
@property (nonatomic, strong) HIDKeyboardQuirkFilter *keyboardQuirkFilter;
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
        _keyboardQuirkFilter = [HIDKeyboardQuirkFilter new];
        _keyboardSuppressedKeyDownKeyCodes = [NSMutableSet set];
        _keyboardForwardedKeyDownKeyCodes = [NSMutableDictionary dictionary];
        _keyboardForwardedKeyDownAtMs = [NSMutableDictionary dictionary];
        _keyboardHeldUnconfirmedKeyDowns = [NSMutableDictionary dictionary];
        // W is the gameplay key, Shift the chord. Codes are the Windows ones the host would see.
        _mappings = @{ @13: @(0x57), @56: @(0xA0), @123: @(0x25), @8: @(0x43), @36: @13, @76: @13 };
    }
    return self;
}
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event {}
- (void)updateKeyboardPhysicalModifierStateFromEvent:(NSEvent *)event {}
- (char)translateKeyModifierWithEvent:(NSEvent *)event { return 0; }
"""

DRIVER = r"""
@end
static int failed;
static MLKeyboardHealProbe *probe;
static MLHealEvent *Edge(NSEventType type, unsigned short code, BOOL repeat) {
    MLHealEvent *e = [MLHealEvent new]; e.type=type; e.keyCode=code; e.isARepeat=repeat;
    e.timestamp=(double)gMLProbeNowMs/1000.0; return e;
}
static void Reset(BOOL hold) {
    [gHostEvents removeAllObjects]; [gMLPhysicallyHeldKeys removeAllObjects];
    gMLProbeNowMs=1000; gMLProbeHoldEnabled=hold; gHealEnabled=YES;
    probe=[MLKeyboardHealProbe new];
}
static void Down(unsigned short k) { [probe keyDown:(NSEvent *)Edge(NSEventTypeKeyDown,k,NO)]; }
static void Up(unsigned short k) { [gMLPhysicallyHeldKeys removeObject:@(k)]; [probe keyUp:(NSEvent *)Edge(NSEventTypeKeyUp,k,NO)]; }
static void Tick(unsigned long long delta) { gMLProbeNowMs+=delta; [probe healUnpairedForwardedKeyDowns]; }
static void Want(NSString *name, NSString *want) {
    NSString *got=[gHostEvents componentsJoinedByString:@" "];
    if (![got isEqualToString:want]) { failed++; printf("FAIL %s: [%s], expected [%s]\n",name.UTF8String,got.UTF8String,want.UTF8String); }
    else { printf("ok   %s\n",name.UTF8String); }
}
static void Check(BOOL condition, NSString *name) { if (!condition) { failed++; printf("FAIL %s\n",name.UTF8String); } }
int main(void) { @autoreleasepool {
    gHostEvents=[NSMutableArray new]; gMLPhysicallyHeldKeys=[NSMutableSet new];
    Reset(NO); Down(8); Tick(130); Want(@"default unpaired C is never sent without a device listener",@"");
    Reset(NO); for (int i=0;i<20;i++) { Down(8); Tick(140); }
    Want(@"incident replay: twenty unpaired C presses cannot leak during repeated clicks",@"");
    Reset(NO); Down(8); gMLProbeNowMs+=20; Up(8);
    Want(@"default guard preserves rapid real C as one complete pair",@"8043D 8043U");
    Reset(NO); [gMLPhysicallyHeldKeys addObject:@8]; Down(8); Tick(1000);
    Want(@"default guard forwards a physically held C immediately",@"8043D");
    Up(8); Want(@"held real C releases once",@"8043D 8043U");
    Reset(NO); Down(8); Tick(140); [gMLPhysicallyHeldKeys addObject:@8]; Down(8); Up(8);
    Want(@"real C works after an unpaired C was rejected",@"8043D 8043U");
    Reset(NO); [gMLPhysicallyHeldKeys addObject:@13]; Down(13); Tick(2000); Want(@"real W held without time limit",@"8057D");
    Reset(NO); Down(13); Tick(40); Want(@"state race grace preserves down",@"8057D");
    Reset(YES); Down(123); Tick(1000); Want(@"untracked arrow is never healed",@"8025D");
    Reset(NO); Down(56); Tick(1000); Want(@"modifier belongs to flags state",@"80A0D");

    Reset(YES); Down(8); gMLProbeNowMs+=20; Up(8); Tick(100); Want(@"rapid quarantined tap has both edges",@"8043D 8043U");
    Check(probe.keyboardHeldUnconfirmedKeyDowns.count==0,@"rapid tap clears pending ownership");
    Reset(YES); Down(8); [gMLPhysicallyHeldKeys addObject:@8]; Tick(20); Up(8); Want(@"late physical confirmation is paired",@"8043D 8043U");
    Reset(YES); Down(8); Tick(70); Up(8); Want(@"opt-in unknown press expires locally",@"");
    Reset(YES); Down(8); gMLProbeNowMs+=40; [probe keyDown:(NSEvent*)Edge(NSEventTypeKeyDown,8,YES)]; Tick(30);
    Want(@"repeat cannot extend quarantine",@""); Check(probe.keyboardHeldUnconfirmedKeyDowns.count==0,@"repeat keeps original deadline");

    Reset(NO); probe.keyboardQuirkFilter.defer=YES; probe.keyboardQuirkFilter.known=YES; [gMLPhysicallyHeldKeys addObject:@8]; Down(8); Tick(70); Want(@"proven pointer C is ignored even if globally held",@"");
    Reset(NO); probe.keyboardQuirkFilter.defer=YES; Down(8); probe.keyboardQuirkFilter.known=YES; Tick(20); Want(@"pointer source stays pending until full attribution window",@""); Tick(50); Up(8); Want(@"delayed pointer source evidence discards C",@"");
    Reset(NO); probe.keyboardQuirkFilter.defer=YES; probe.keyboardQuirkFilter.known=YES; Down(8); Tick(20); probe.keyboardQuirkFilter.known=NO; Tick(50); Up(8); Want(@"late real keyboard evidence wins the attribution window",@"8043D 8043U");
    Reset(NO); probe.keyboardQuirkFilter.defer=YES; probe.keyboardQuirkFilter.known=YES; Down(8); Up(8); Want(@"real keyUp preserves a tap despite incomplete source callbacks",@"8043D 8043U");
    Reset(NO); probe.keyboardQuirkFilter.defer=YES; Down(8); Tick(70); Up(8); Want(@"missing device evidence fails open",@"8043D 8043U");
    Reset(NO); probe.keyboardQuirkFilter.defer=YES; Down(8); gMLProbeNowMs+=10; Up(8); Want(@"fast real C remains a full tap",@"8043D 8043U");
    Reset(NO); gHealEnabled=NO; probe.keyboardQuirkFilter.defer=YES; Down(8); Tick(70); Tick(500); Want(@"heal disabled still settles provenance",@"8043D");

    Reset(YES); Down(8); [probe releaseAllHeldKeys]; probe.shouldSendInputEvents=NO; [gMLPhysicallyHeldKeys addObject:@8]; Tick(20);
    Want(@"uncapture cancels quarantined press",@""); Check(probe.keyboardHeldUnconfirmedKeyDowns.count==0,@"uncapture clears pending");
    Reset(YES); Down(8); probe.shouldSendInputEvents=NO; [gMLPhysicallyHeldKeys addObject:@8]; Tick(20); Want(@"closed input gate cannot emit deferred down",@"");
    Reset(NO); Down(13); Down(13); Up(13); Up(13); Want(@"duplicate edges are idempotent",@"8057D 8057U");
    Reset(NO); Down(13); [probe releaseAllHeldKeys]; [probe keyDown:(NSEvent*)Edge(NSEventTypeKeyDown,13,YES)]; Up(13);
    Want(@"stale repeat cannot resurrect released ownership",@"8057D 8057U");
    Reset(NO); Up(13); Want(@"orphan up is ignored",@"");
    Reset(NO); Down(13); [probe noteKeyboardKeyDownSuppressedForEvent:(NSEvent*)Edge(NSEventTypeKeyDown,13,YES)]; Up(13);
    Want(@"local repeat consumer cannot steal physical release",@"8057D 8057U");

    Reset(NO); Down(36); Down(76); Up(36); Want(@"shared VK remains pressed for its final owner",@"800DD"); Up(76); Want(@"shared VK has one matching up",@"800DD 800DU");
    Reset(NO); Down(36); Down(76); [probe releaseAllHeldKeys]; Want(@"capture releases shared VK once",@"800DD 800DU");
    Reset(NO); [gMLPhysicallyHeldKeys addObject:@76]; Down(36); Down(76); Tick(130); Want(@"healing one alias preserves the other",@"800DD"); Up(76); Want(@"final healed alias remains paired",@"800DD 800DU");
    Reset(NO); Down(8); probe.mappings=@{@8:@0x44}; Up(8); Want(@"keyUp uses the original wire code",@"8043D 8043U");
    printf("%d keyboard lifecycle failures\n",failed); return failed ? 1:0;
} }
"""

def method(text, signature):
    start=text.index(signature); body=text.index("{",start); depth=0
    for i in range(body,len(text)):
        if text[i]=="{": depth+=1
        elif text[i]=="}":
            depth-=1
            if depth==0: return text[start:i+1]
    raise RuntimeError("unbalanced method: "+signature)

def build(text):
    constants="\n".join(line for line in text.splitlines() if line.startswith("static uint64_t const HIDKeyState"))
    return (PROLOGUE+constants+method(text,"static BOOL HIDWireCodeIsKeyStateDetectable(short wireCode)")+
            IMPL_HEAD+"\n".join(method(text,s) for s in SIGNATURES)+DRIVER)

def compile_and_run(code,label):
    cc,sdk=apple_toolchain.clang_and_sdk("keyboard lifecycle probe")
    with tempfile.TemporaryDirectory(prefix="key-state-heal-") as tmp:
        src=os.path.join(tmp,"probe.m"); exe=os.path.join(tmp,"probe")
        with open(src,"w") as f: f.write(ml_probe_fixture.apply(code))
        built=subprocess.run([cc,"-isysroot",sdk,"-fobjc-arc","-framework","AppKit",src,"-o",exe],capture_output=True,text=True)
        if built.returncode: print("FAIL",label,"compile:\n",built.stderr[-2500:]); return None
        ran=subprocess.run([exe],capture_output=True,text=True)
        print(label+"\n"+ran.stdout.strip()); return ran.returncode

def main():
    text=open(SOURCE).read()
    if compile_and_run(build(text),"shipping") != 0: return 1
    mutants={
        "permission-independent C guard": ("BOOL unpairedC = physicalKeyCode == kVK_ANSI_C && !quirk;", "BOOL unpairedC = NO;"),
        "rapid tap pairing": ("if (pending != nil && savedCode == nil) {", "if (NO) {"),
        "shared VK release ownership": ("if ([self.keyboardForwardedKeyDownKeyCodes.allValues containsObject:@(keyCode)]) {", "if (NO) {"),
        "saved wire identity": ("short keyCode = savedCode != nil ? savedCode.shortValue : [pending[@\"wire\"] shortValue];", "short keyCode = (short)(0x8000 | [self translateKeyCodeWithEvent:event]);"),
    }
    for label,(before,after) in mutants.items():
        if text.count(before)!=1: print("FAIL mutation cannot find",label); return 1
        if compile_and_run(build(text.replace(before,after,1)),"known-bad "+label) != 1:
            print("FAIL mutation did not fail:",label); return 1
    return 0
if __name__=="__main__": sys.exit(main())
