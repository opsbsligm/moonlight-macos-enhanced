#!/usr/bin/env python3
"""Exercise shipping Caps Lock, capture gate, numeric and HID report boundaries.

Compiles extracted production methods with UBSan. Source checks cover the UI
executor/cleanup wiring that requires an AppKit window; those are not hardware tests.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
from apple_toolchain import clang_and_sdk

ROOT = Path(__file__).resolve().parents[1]

def block(source, anchor):
    start = source.index(anchor)
    end = source.index('{', start)
    depth = 1
    end += 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

HARNESS = r'''
#import <AppKit/AppKit.h>
#import <Carbon/Carbon.h>
#include <limits.h>
#include <float.h>
#include <stdint.h>
#include <string.h>
#include <stdatomic.h>
@interface HIDMouseDeltaAccumulator : NSObject
- (void)accumulateMotionX:(CGFloat)deltaX deltaY:(CGFloat)deltaY;
- (void)takeAccumulatedMotionX:(CGFloat *)deltaXOut deltaY:(CGFloat *)deltaYOut;
@end
__ACCUMULATOR__
#define KEY_ACTION_DOWN 1
#define KEY_ACTION_UP 0
#define Log(...) ((void)0)
typedef void *PML_INPUT_STREAM_CONTEXT;
typedef struct { PML_INPUT_STREAM_CONTEXT context; uint64_t generation; } HIDInputLease;
static BOOL physicalKeys[128];
static NSEventModifierFlags localModifierFlags;
#define CGEventSourceKeyState(source, key) (physicalKeys[(key)])
static NSUInteger HIDPhysicalModifierMaskForKeyCode(unsigned short key) { return (NSUInteger)1 << (key % 16); }
static NSMutableArray *packets;
static NSMutableArray *positions;
static uint64_t nowMs=1000;
static int traces, wheelPackets;
static uint64_t LiGetMillis(void) { return nowMs; }
static void LiStartScrollTraceCtx(void *context, uint64_t trace, uint64_t now) { traces++; }
static void LiNoteScrollTraceLocalDispatchCtx(void *context, uint64_t trace, uint64_t now, short amount, BOOL horizontal, BOOL continuous) {}
static void LiSendHighResScrollEventCtx(void *context, short amount) { wheelPackets++; }
static BOOL HIDValidateInputContext(void *context, const char *operation) { return context != NULL; }
static const uint64_t HIDGCMouseAppKitSuppressMs=80;
static CGFloat HIDWheelScrollSpeedForHost(id host) { return 1; }
static short HIDDiscreteScrollPacketUnits(short clicks, CGFloat speed);
static BOOL HIDAbsoluteMousePositionForViewPoint(NSPoint point, NSSize size, BOOL clamp,
                                                short *x, short *y, short *width, short *height);
@interface TestHost : NSObject
@property NSString *uuid;
@end
@implementation TestHost
@end
@interface SettingsClass : NSObject
+ (BOOL)reverseScrollDirectionFor:(NSString *)uuid;
+ (void)updateScrollInputRuntimeStatusFor:(NSString *)uuid summaryKey:(NSString *)summary detailKey:(NSString *)detail;
@end
@implementation SettingsClass
+ (BOOL)reverseScrollDirectionFor:(NSString *)uuid { return NO; }
+ (void)updateScrollInputRuntimeStatusFor:(NSString *)uuid summaryKey:(NSString *)summary detailKey:(NSString *)detail {}
@end
static void LiSendKeyboardEventCtx(void *ctx, short code, char action, char modifiers) {
    [packets addObject:@[@((unsigned short)code), @(action), @(modifiers)]];
}
static HIDInputLease HIDAcquireInputContext(id support) { return (HIDInputLease){(void *)1, 1}; }
static void HIDDispatchInput(id support, HIDInputLease lease, dispatch_block_t block) { block(); }
static void HIDExecuteInputLeaseOnQueue(id support, HIDInputLease lease, dispatch_block_t block) { block(); }
static void LiSendMousePositionEventCtx(void *context, short x, short y, short width, short height) {
    [positions addObject:@[@(x), @(y), @(width), @(height)]];
}
@interface HIDSupport : NSObject
@property BOOL shouldSendInputEvents;
@property BOOL keyboardTeardownAlreadyCalled;
@property uint64_t inputCaptureGeneration;
@property NSNumber *keyboardCapsLockState;
@property HIDMouseDeltaAccumulator *mouseDeltaAccumulator;
@property CGFloat relativeMotionResidualX;
@property CGFloat relativeMotionResidualY;
@property CGFloat relativeDeltaResidualX;
@property CGFloat relativeDeltaResidualY;
@property CGFloat mouseEmulationResidualX;
@property CGFloat mouseEmulationResidualY;
@property dispatch_queue_t inputQueue;
@property BOOL pendingCoalescedAbsolutePointerValid;
@property BOOL pendingCoalescedAbsolutePointerDispatch;
@property short pendingCoalescedAbsolutePointerHostX;
@property short pendingCoalescedAbsolutePointerHostY;
@property short pendingCoalescedAbsolutePointerReferenceWidth;
@property short pendingCoalescedAbsolutePointerReferenceHeight;
@property NSString *pendingCoalescedAbsolutePointerSource;
@property void *pendingCoalescedAbsolutePointerContext;
@property uint64_t pendingCoalescedAbsolutePointerGeneration;
@property uint64_t pendingCoalescedAbsolutePointerCaptureGeneration;
@property short lastAbsolutePointerHostX;
@property short lastAbsolutePointerHostY;
@property short lastAbsolutePointerReferenceWidth;
@property short lastAbsolutePointerReferenceHeight;
@property uint64_t lastAbsolutePointerAtMs;
@property NSString *lastAbsolutePointerSource;
@property NSUInteger inputDiagnosticsAbsoluteDuplicateSkips;
@property NSUInteger keyboardPhysicalModifierSourceMask;
@property NSObject *inputDiagnosticsLock;
@property BOOL inputDiagnosticsEnabled;
@property uint64_t activeScrollTraceLastEventMs;
@property uint64_t activeScrollTraceStartedMs;
@property uint64_t activeScrollTraceId;
@property uint64_t scrollTraceSequence;
@property BOOL activeScrollTraceLockedToPrecise;
@property NSString *activeScrollTraceSource;
@property BOOL useGCMouse;
@property TestHost *host;
@property uint64_t suppressAppKitScrollUntilMsY;
@property CGFloat accumulatedHighResScrollDeltaY;
@end
@implementation HIDSupport
@synthesize shouldSendInputEvents = _shouldSendInputEvents;
- (void)syncScrollTraceDiagnosticsPreferenceToInputContext {}
- (void)syncKeyboardModifierStateForEvent:(NSEvent *)event {}
- (void)updateKeyboardPhysicalModifierStateFromEvent:(NSEvent *)event {}
- (char)translateKeyModifierWithEvent:(NSEvent *)event { return 1; }
- (void)recordAbsoluteInputDiagnosticsFrom:(NSString *)source x:(short)x y:(short)y width:(short)width height:(short)height {}
__METHODS__
@end
static short const HIDScrollWheelDelta = 120;
__HELPERS__
static int failures;
static void check(BOOL ok, const char *label) { printf("%s %s\n", ok ? "PASS" : "FAIL", label); failures += !ok; }
static NSEvent *caps(BOOL enabled) {
    return [NSEvent keyEventWithType:NSEventTypeFlagsChanged location:NSZeroPoint
                      modifierFlags:enabled ? NSEventModifierFlagCapsLock : 0
                          timestamp:1 windowNumber:0 context:nil characters:@"" charactersIgnoringModifiers:@""
                          isARepeat:NO keyCode:kVK_CapsLock];
}
int main(void) { @autoreleasepool {
    packets = [NSMutableArray new];
    positions = [NSMutableArray new];
    HIDSupport *support = [HIDSupport new];
    support.inputDiagnosticsLock = [NSObject new];
    support.inputQueue = dispatch_queue_create("test.capture.positions", DISPATCH_QUEUE_SERIAL);
    support.keyboardPhysicalModifierSourceMask = NSUIntegerMax;
    support.shouldSendInputEvents = YES;
    [support refreshKeyboardModifiersForCapture];
    check(support.keyboardPhysicalModifierSourceMask == 0, "recapture removes modifiers released in another application");
    physicalKeys[kVK_RightShift] = YES;
    [support refreshKeyboardModifiersForCapture];
    check(support.keyboardPhysicalModifierSourceMask == HIDPhysicalModifierMaskForKeyCode(kVK_RightShift),
          "recapture restores the actual held side without synthesizing the left key");
    physicalKeys[kVK_RightShift] = NO;
    packets = [NSMutableArray new];
    support.keyboardCapsLockState = @NO;
    localModifierFlags = NSEventModifierFlagCapsLock;
    [support refreshKeyboardModifiersForCapture];
    check(support.keyboardCapsLockState.boolValue && packets.count == 0,
          "recapture refreshes an unseen local Caps Lock change without toggling the host");
    [support flagsChanged:caps(NO)];
    check(packets.count == 2, "first Caps Lock toggle after recapture is not swallowed");
    [packets removeAllObjects];
    support.keyboardCapsLockState = @NO;
    support.shouldSendInputEvents = YES;
    [support flagsChanged:caps(YES)];
    check([packets isEqual:@[@[@0x8014,@1,@1], @[@0x8014,@0,@1]]], "Caps Lock flags change emits a complete toggle pair");
    [support flagsChanged:caps(YES)];
    check(packets.count == 2, "duplicate lock-state report does not toggle twice");
    [support flagsChanged:caps(NO)];
    check(packets.count == 4, "unlock emits the second toggle pair");
    support.shouldSendInputEvents = NO;
    [support flagsChanged:caps(YES)];
    support.shouldSendInputEvents = YES;
    [support flagsChanged:caps(YES)];
    check(packets.count == 4, "uncaptured lock changes update local state without deferred host input");
    support.keyboardTeardownAlreadyCalled = YES;
    support.shouldSendInputEvents = YES;
    check(!support.shouldSendInputEvents, "a terminated session cannot reopen its forwarding gate");

    support.keyboardTeardownAlreadyCalled = NO;
    support.mouseDeltaAccumulator = [HIDMouseDeltaAccumulator new];
    support.useGCMouse = YES;
    support.shouldSendInputEvents = YES;
    [support accumulateCapturedMouseMotionX:12 deltaY:-9];
    support.relativeMotionResidualX = 0.75;
    support.relativeMotionResidualY = -0.75;
    support.relativeDeltaResidualX = 0.75;
    support.relativeDeltaResidualY = -0.75;
    support.mouseEmulationResidualX = 0.75;
    support.mouseEmulationResidualY = -0.75;
    support.shouldSendInputEvents = NO;
    [support accumulateCapturedMouseMotionX:100 deltaY:100];
    support.shouldSendInputEvents = YES;
    CGFloat capturedX=0, capturedY=0;
    [support.mouseDeltaAccumulator takeAccumulatedMotionX:&capturedX deltaY:&capturedY];
    check(capturedX == 0 && capturedY == 0 &&
          support.relativeMotionResidualX == 0 && support.relativeMotionResidualY == 0 &&
          support.relativeDeltaResidualX == 0 && support.relativeDeltaResidualY == 0 &&
          support.mouseEmulationResidualX == 0 && support.mouseEmulationResidualY == 0,
          "capture boundary drops buffered motion and every source's fractional debt without a display tick");
    [support accumulateCapturedMouseMotionX:3 deltaY:-4];
    support.shouldSendInputEvents = YES;
    [support.mouseDeltaAccumulator takeAccumulatedMotionX:&capturedX deltaY:&capturedY];
    check(capturedX == 3 && capturedY == -4, "repeating an unchanged capture state preserves fresh motion");
    support.useGCMouse = NO;
    [support accumulateCapturedMouseMotionX:99 deltaY:99];
    [support.mouseDeltaAccumulator takeAccumulatedMotionX:&capturedX deltaY:&capturedY];
    check(capturedX == 0 && capturedY == 0, "a late GameController callback cannot accumulate after driver switch");

    dispatch_suspend(support.inputQueue);
    [support sendCoalescedAbsoluteMousePositionForViewPoint:NSMakePoint(20,30)
        referenceSize:NSMakeSize(100,100) clampToBounds:YES sourceTag:@"test"];
    support.shouldSendInputEvents = NO;
    support.shouldSendInputEvents = YES;
    dispatch_resume(support.inputQueue);
    dispatch_sync(support.inputQueue, ^{});
    check(positions.count == 0, "queued absolute position from a previous capture is discarded");
    [support sendCoalescedAbsoluteMousePositionForViewPoint:NSMakePoint(20,30)
        referenceSize:NSMakeSize(100,100) clampToBounds:YES sourceTag:@"test"];
    dispatch_sync(support.inputQueue, ^{});
    check(positions.count == 1, "same position in a new capture is sent instead of falsely deduplicated");
    [positions removeAllObjects];
    dispatch_suspend(support.inputQueue);
    [support sendCoalescedAbsoluteMousePositionForViewPoint:NSMakePoint(40,50)
        referenceSize:NSMakeSize(100,100) clampToBounds:YES sourceTag:@"test"];
    // Simulate a slot copied across a capture boundary independently of reset.
    support.inputCaptureGeneration++;
    dispatch_resume(support.inputQueue);
    dispatch_sync(support.inputQueue, ^{});
    check(positions.count == 0, "capture generation rejects an old absolute payload even if its slot survives");

    short x=0,y=0,w=0,h=0;
    check(HIDAbsoluteMousePositionForViewPoint(NSMakePoint(960,540), NSMakeSize(1920,1080), YES, &x,&y,&w,&h)
          && w==15360 && h==8640 && x==7680 && y==4320, "ordinary absolute coordinates preserve existing precision");
    check(HIDAbsoluteMousePositionForViewPoint(NSMakePoint(40000,100), NSMakeSize(80000,50000), YES, &x,&y,&w,&h)
          && w>1 && h>1 && x>=0 && x<w && y>=0 && y<=h, "large virtual desktop fits positive signed protocol fields");
    check(HIDAbsoluteMousePositionForViewPoint(NSZeroPoint, NSMakeSize(DBL_MAX,1), YES, &x,&y,&w,&h)
          && w>1 && h>1, "extreme aspect ratio cannot create a zero divisor");
    check(!HIDAbsoluteMousePositionForViewPoint(NSZeroPoint, NSMakeSize(NAN,1), YES, &x,&y,&w,&h)
          && !HIDAbsoluteMousePositionForViewPoint(NSMakePoint(INFINITY,0), NSMakeSize(10,10), YES, &x,&y,&w,&h)
          && !HIDAbsoluteMousePositionForViewPoint(NSZeroPoint, NSMakeSize(0,10), YES, &x,&y,&w,&h), "invalid coordinate geometry is rejected before conversion");
    check(HIDNormalizedDiscreteScrollClick(DBL_MAX)==SHRT_MAX/120 &&
          HIDNormalizedDiscreteScrollClick(-DBL_MAX)==-(SHRT_MAX/120), "huge finite wheel values saturate before integer rounding");
    check(HIDDiscreteScrollPacketUnits(1, DBL_MAX)==SHRT_MAX &&
          HIDDiscreteScrollPacketUnits(-1, DBL_MAX)==SHRT_MIN, "wheel speed overflow preserves direction");
    check(HIDDiscreteScrollPacketUnits(3,4)==1440 && HIDDiscreteScrollPacketUnits(-3,4)==-1440,
          "ordinary multi-notch speed remains unchanged");
    support.keyboardTeardownAlreadyCalled = NO;
    support.shouldSendInputEvents = YES;
    support.useGCMouse = YES;
    support.host = [TestHost new];
    support.inputDiagnosticsLock = [NSObject new];
    for (int enabled=0; enabled<=1; enabled++) {
        support.inputDiagnosticsEnabled = enabled;
        uint64_t trace=[support prepareScrollTraceFromSource:@"appkit" rawDeltaX:0 rawDeltaY:1
                phase:NSEventPhaseBegan momentumPhase:NSEventPhaseNone hasPreciseDeltas:YES];
        support.activeScrollTraceLockedToPrecise=YES;
        nowMs++;
        uint64_t continued=[support prepareScrollTraceFromSource:@"appkit" rawDeltaX:0 rawDeltaY:1
                phase:NSEventPhaseChanged momentumPhase:NSEventPhaseNone hasPreciseDeltas:YES];
        check(trace!=0 && trace==continued && support.activeScrollTraceLockedToPrecise,
              "scroll gesture classification survives with diagnostics off and on");
    }
    check(traces==1, "disabled diagnostics send no trace instrumentation");
    for (int tick=0;tick<10;tick++) { nowMs++; [support handleGCMouseScrollValueY:1]; }
    check(wheelPackets==10, "ten fast same-direction wheel callbacks produce ten scroll packets");
    unsigned char report[8]={9,1,2,3,4,5,6,7}, target[12];
    check(HIDCopyReportPayload(target,sizeof(target),3,report,4,1) &&
          target[0]==1 && target[2]==3 && target[3]==0 && target[11]==0,
          "short valid report copies controls and zeroes missing sensor bytes");
    check(!HIDCopyReportPayload(target,sizeof(target),3,report,2,1) &&
          !HIDCopyReportPayload(target,sizeof(target),3,NULL,8,1) &&
          !HIDCopyReportPayload(target,sizeof(target),3,report,-1,1) &&
          !HIDCopyReportPayload(target,sizeof(target),3,report,8,SIZE_MAX),
          "truncated, null and invalid-offset reports cannot be read");
    BOOL reportMatrixValid=YES;
    for (int length=0;length<=8;length++) {
        for (int offset=0;offset<=10;offset++) {
            BOOL expected=offset<=length && length-offset>=3;
            if (HIDCopyReportPayload(target,sizeof(target),3,report,length,offset)!=expected) reportMatrixValid=NO;
        }
    }
    check(reportMatrixValid, "report length/offset matrix has no out-of-bounds access");
    return failures != 0;
}}
'''

def run(negative=False):
    hid=(ROOT/'Limelight/Input/HIDSupport.m').read_text()
    header=(ROOT/'Limelight/Input/HIDSupport_Internal.h').read_text()
    capture=(ROOT/'Limelight/macOS/ViewControllers/StreamViewController+MouseCapture.m').read_text()
    scroll=(ROOT/'Limelight/Input/HIDSupport+Scroll.m').read_text()
    pointer=(ROOT/'Limelight/Input/HIDSupport+Pointer.m').read_text()
    methods='\n'.join(block(hid,a) for a in ('- (BOOL)shouldSendInputEvents {','- (void)setShouldSendInputEvents:', '- (void)flagsChanged:', '- (void)refreshKeyboardModifiersForCapture', '- (uint64_t)prepareScrollTraceFromSource:'))
    diagnostic=block(hid, '- (void)recordScrollInputDiagnosticsMode:')
    methods += '\n' + block(pointer, '- (void)resetPointerMotionForCaptureTransition')
    methods += '\n' + block(pointer, '- (void)accumulateCapturedMouseMotionX:')
    methods += '\n' + block(pointer, '- (void)dispatchPendingCoalescedAbsolutePointerPosition')
    methods += '\n' + block(pointer, '- (void)sendCoalescedAbsoluteMousePositionForViewPoint:')
    # Replace only the operating system snapshot; run the shipping state logic.
    methods = methods.replace('[NSEvent modifierFlags]', 'localModifierFlags')
    methods=diagnostic[:diagnostic.index('{')]+'{}\n'+methods+'\n'+block(scroll, '- (void)handleGCMouseScrollValueY:')
    helpers='\n'.join(block(header,a) for a in ('static inline BOOL HIDCopyReportPayload(',
        'static inline CGFloat HIDAbsoluteMouseReferencePrecisionScale(', 'static inline BOOL HIDAbsoluteMousePositionForViewPoint(',
        'static inline short HIDNormalizedDiscreteScrollClick(', 'static inline short HIDDiscreteScrollPacketUnits('))
    if negative == 'legacy-boundaries':
        methods=methods.replace('if (event.keyCode == kVK_CapsLock)', 'if (NO)')
        helpers=helpers.replace('return (((CGFloat)SHRT_MAX) - 1.0) / maxDimension;', 'return 1.0;')
    elif negative == 'stale-caps-baseline':
        original = methods
        methods=methods.replace('self.keyboardCapsLockState = @((localModifierFlags & NSEventModifierFlagCapsLock) != 0);', '')
        assert methods != original
    elif negative == 'stale-pointer-motion':
        original = methods
        methods=methods.replace('[self resetPointerMotionForCaptureTransition];', '')
        assert methods != original
    elif negative == 'stale-absolute-generation':
        original = methods
        methods=methods.replace(' || captureGeneration != self.inputCaptureGeneration', '')
        assert methods != original
    accumulator=pointer[pointer.index('@implementation HIDMouseDeltaAccumulator'):pointer.index('@implementation HIDSupport (Pointer)')]
    code=HARNESS.replace('__METHODS__',methods).replace('__HELPERS__',helpers).replace('__ACCUMULATOR__', accumulator)
    clang,sdk=clang_and_sdk('input boundary tests')
    with tempfile.TemporaryDirectory(prefix='moonlight-input-boundary-') as directory:
        source=Path(directory)/'probe.m';binary=Path(directory)/'probe'
        source.write_text(code)
        subprocess.run([clang,'-isysroot',sdk,'-fobjc-arc','-fblocks','-fsanitize=undefined,float-cast-overflow',
                        '-framework','AppKit',str(source),'-o',str(binary)],check=True)
        result=subprocess.run([str(binary)],capture_output=True,text=True)
        print(result.stdout,end='')
        if not negative and (result.returncode or result.stderr):
            raise SystemExit(result.stderr or 'behavioral boundary checks failed')
        if negative:
            if result.returncode == 0:
                raise SystemExit('known bad implementation was not detected: '+negative)
            print('PASS negative control detected: '+negative)
    if negative: return
    uncapture=block(capture,'- (void)uncaptureMouseWithCode:')
    teardown=block(hid,'- (void)tearDownKeyboardStateForSessionEnd:')
    for label,body in [('uncapture',uncapture),('teardown',teardown)]:
        assert body.index('self.shouldSendInputEvents = NO;' if label=='teardown' else 'self.hidSupport.shouldSendInputEvents = NO;') < body.index('releaseAllHeldKeys'), label
    focus=block(capture, '- (void)requestMouseUncaptureWhenSafeWithReason:(NSString *)reason code:')
    assert focus.index('!NSApp.isActive') < focus.index('hasPressedMouseButtonsForCaptureTransition')
    assert 'refreshKeyboardModifiersForCapture' in block(capture, '- (void)captureMouse {')
    assert 'skip-window-nil' not in uncapture and 'if (!showLocalCursor)' not in uncapture
    for signature in ['- (void)coreHIDMouseDriver:(CoreHIDMouseDriver *)driver\n             didReceiveDeltaX:',
                      '- (void)coreHIDMouseDriver:(CoreHIDMouseDriver *)driver\n         didFailWithReason:']:
        method=block(hid,signature)
        assert 'if (![NSThread isMainThread])' in method and 'dispatch_get_main_queue()' in method
        assert 'if (driver != self.coreHIDMouseDriver) return;' in method
    assert 'self.mouseConnectObserver' in hid and '[weakSelf registerMouseCallbacks:note.object]' in hid
    display=block(pointer, 'static CVReturn displayLinkOutputCallback(')
    assert display.index('@synchronized (me)') < display.index('takeAccumulatedMotionX:')
    assert 'accumulateCapturedMouseMotionX:' in block(pointer, '-(void)registerMouseCallbacks:')
    controller=(ROOT/'Limelight/Input/ControllerSupport.m').read_text()
    cleanup=block(controller, '-(void) releaseRemoteMouseButtonsForUncapture')
    assert '_accumulatedMouseX = 0;' in cleanup and '_accumulatedMouseY = 0;' in cleanup
    print('PASS capture closes before cleanup; window/cursor cleanup and CoreHID executor guards are wired')

if __name__=='__main__':
    if '--self-test' in sys.argv:
        for mutation in ('legacy-boundaries', 'stale-caps-baseline', 'stale-pointer-motion', 'stale-absolute-generation'):
            run(mutation)
    else:
        run()
