#!/usr/bin/env python3
"""Replay real HID producers, mode transitions, wire tuples and pointer consumer."""
from pathlib import Path
import subprocess
import tempfile
from apple_toolchain import clang_and_sdk

root = Path(__file__).resolve().parents[1]
hid = (root / 'Limelight/Input/HIDSupport.m').read_text()
pointer = (root / 'Limelight/Input/HIDSupport+Pointer.m').read_text()
internal = (root / 'Limelight/Input/HIDSupport_Internal.h').read_text()
def block(text, anchor):
    start = text.index(anchor)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]
methods = '\n'.join(block(hid, a) for a in (
    '- (NSString *)deviceKeyForDevice:', '- (HIDDeviceControllerEntry *)entryForDevice:',
    '- (int)allocatePlayerSlot {', '- (int)activeDeviceMask {',
    '- (void)sendControllerEventForEntry:', '- (void)sendControllerEvent {',
    '- (void)sendControllerNeutralEventForEntry:', '- (void)setControllerMouseMode:',
    '- (void)sendControllerRemovalForEntry:', '- (void)resetControllerStateForEntry:',
    '- (void)updateButtonFlags:'))
# The clock is the boundary; the shipping gesture state machine is compiled unchanged.
methods = methods.replace('[NSDate date].timeIntervalSinceReferenceDate', 'clockNow')
callbacks = '\n'.join(block(hid, a) for a in ('void myHIDCallback(', 'void myHIDDeviceRemovalCallback('))
consumer = block(pointer, 'if (me.controller.isMouseMode && me.shouldSendInputEvents)')
drain = block(internal, 'static inline short HIDDrainRelativeDelta(')
controller_header = r'''
#pragma once
#import <Foundation/Foundation.h>
#import "GamepadMenuGesture.h"
@interface Controller : NSObject
@property int playerIndex;
@property int lastButtonFlags;
@property unsigned char lastLeftTrigger;
@property unsigned char lastRightTrigger;
@property short lastLeftStickX;
@property short lastLeftStickY;
@property short lastRightStickX;
@property short lastRightStickY;
@property BOOL isMouseMode;
@property MLGamepadMenuGesture menuGesture;
@end
'''
harness = r'''
#import <Foundation/Foundation.h>
#import <IOKit/hid/IOHIDUsageTables.h>
#import "ControllerEventBaseline.h"
#import "MouseEmulation.h"
#import "Limelight.h"
#include <limits.h>
@implementation Controller
@end
typedef const void *IOHIDDeviceRef;
CFTypeRef CFRetain(CFTypeRef v) { return v; }
void CFRelease(CFTypeRef v) { (void)v; }
typedef struct { IOHIDDeviceRef device; uint32_t page, usage; CFIndex value; } FakeValue;
typedef FakeValue *IOHIDValueRef;
typedef FakeValue *IOHIDElementRef;
typedef int IOReturn;
static IOHIDElementRef IOHIDValueGetElement(IOHIDValueRef v) { return v; }
static uint32_t IOHIDElementGetUsagePage(IOHIDElementRef e) { return e->page; }
static uint32_t IOHIDElementGetUsage(IOHIDElementRef e) { return e->usage; }
static CFIndex IOHIDValueGetIntegerValue(IOHIDValueRef v) { return v->value; }
static IOHIDDeviceRef IOHIDElementGetDevice(IOHIDElementRef e) { return e->device; }
static BOOL isXbox(IOHIDDeviceRef d) { return YES; }
static BOOL isKingKong(IOHIDDeviceRef d) { return NO; }
static BOOL isPS4(IOHIDDeviceRef d) { (void)d; return NO; }
static BOOL isPS5(IOHIDDeviceRef d) { (void)d; return NO; }
static const uint16_t kHIDArrivalCapabilities = LI_CCAP_ANALOG_TRIGGERS | LI_CCAP_RUMBLE;
typedef void *PML_INPUT_STREAM_CONTEXT;
typedef struct { void *context; uint64_t generation; } HIDInputLease;
static double clockNow;
static NSMutableArray *wire, *moves;
static NSString *const HIDMouseModeToggledNotification = @"mode";
static NSString *const HIDGamepadQuitNotification = @"quit";
@interface HIDDeviceControllerEntry : NSObject
@property Controller *controller;
@property IOHIDDeviceRef hidDevice;
@property int playerIndex;
@property uint8_t protocolType;
@property uint32_t supportedButtonFlags;
@property uint16_t capabilities;
@property UInt8 previousLowFreqMotor;
@property UInt8 previousHighFreqMotor;
@property UInt8 previousLEDRed;
@property UInt8 previousLEDGreen;
@property UInt8 previousLEDBlue;
@property UInt8 previousLeftTriggerMotor;
@property UInt8 previousRightTriggerMotor;
@property uint8_t motionActiveTypes;
@property uint16_t motionAccelIntervalMs;
@property uint16_t motionGyroIntervalMs;
@property uint64_t lastMotionAccelAtMs;
@property uint64_t lastMotionGyroAtMs;
@end
@implementation HIDDeviceControllerEntry
@end
@interface HIDSupport : NSObject
@property Controller *controller;
@property HIDDeviceControllerEntry *mouseModeEntry;
@property NSMutableDictionary<NSString *, HIDDeviceControllerEntry *> *deviceControllerTable;
@property int controllerDriver;
@property BOOL shouldSendInputEvents;
@property BOOL gestureEnabled;
@property CGFloat mouseEmulationResidualX, mouseEmulationResidualY;
@property BOOL mouseDown;
@property int releases;
@property int mouseEvents;
- (NSString *)deviceKeyForDevice:(IOHIDDeviceRef)d;
- (HIDDeviceControllerEntry *)entryForDevice:(IOHIDDeviceRef)d;
- (int)allocatePlayerSlot;
- (int)activeDeviceMask;
- (void)sendControllerEventForEntry:(HIDDeviceControllerEntry *)entry;
- (void)sendControllerEvent;
- (void)sendControllerNeutralEventForEntry:(HIDDeviceControllerEntry *)entry;
- (void)setControllerMouseMode:(BOOL)enabled forEntry:(HIDDeviceControllerEntry *)entry;
- (void)sendControllerRemovalForEntry:(HIDDeviceControllerEntry *)entry;
- (void)resetControllerStateForEntry:(HIDDeviceControllerEntry *)entry;
- (void)stopMotionEventsForEntry:(HIDDeviceControllerEntry *)entry;
- (void)updateButtonFlags:(int)flag entry:(HIDDeviceControllerEntry *)entry state:(BOOL)set;
- (void)recordRelativeInputDiagnosticsFrom:(NSString *)s rawDeltaX:(CGFloat)x rawDeltaY:(CGFloat)y
    sentDeltaX:(short)sx sentDeltaY:(short)sy suppressed:(BOOL)suppressed;
@end
static HIDInputLease HIDAcquireInputContext(HIDSupport *s) { return (HIDInputLease){(void *)1,1}; }
static void HIDDispatchInput(HIDSupport *s, HIDInputLease lease, dispatch_block_t job) { job(); }
static int LiSendMultiControllerEventCtx(void *ctx, int slot, int mask, int buttons,
    int lt, int rt, int lx, int ly, int rx, int ry) {
    [wire addObject:@[@(slot),@(mask),@(buttons),@(lt),@(rt),@(lx),@(ly),@(rx),@(ry)]]; return 0;
}
static void LiSendMouseMoveEventCtx(void *ctx, short x, short y) { [moves addObject:@[@(x),@(y)]]; }
@implementation HIDSupport
- (void)stopMotionEventsForEntry:(HIDDeviceControllerEntry *)entry {}
- (uint8_t)protocolTypeForDevice:(IOHIDDeviceRef)d { return LI_CTYPE_XBOX; }
- (uint32_t)supportedButtonFlagsForDevice:(IOHIDDeviceRef)d { return 0xffff; }
- (BOOL)gamepadMenuLongPressTogglesMouseModeEnabled { return self.gestureEnabled; }
- (void)sendControllerArrivalForEntry:(HIDDeviceControllerEntry *)entry {}
- (void)publishControllerInventoryChange {}
- (void)releaseMouseButtonsForSource:(NSString *)source {
    NSCAssert([source isEqual:@"hid-controller"], @"wrong source"); self.releases++; self.mouseDown = NO;
}
- (void)sendMouseButton:(int)button pressed:(BOOL)pressed source:(NSString *)source {
    NSCAssert([source isEqual:@"hid-controller"], @"wrong source"); self.mouseDown = pressed; self.mouseEvents++;
}
- (void)rumbleLowFreqMotor:(unsigned short)lo highFreqMotor:(unsigned short)hi {}
- (void)recordRelativeInputDiagnosticsFrom:(NSString *)s rawDeltaX:(CGFloat)x rawDeltaY:(CGFloat)y
    sentDeltaX:(short)sx sentDeltaY:(short)sy suppressed:(BOOL)suppressed {}
__METHODS__
@end
__CALLBACKS__
__DRAIN__
#define kCVReturnSuccess 0
static int consume(HIDSupport *me) { @synchronized(me) { __CONSUMER__ return 0; } }
#define CHECK(...) do { if (!(__VA_ARGS__)) { NSLog(@"failed line %d", __LINE__); return 1; } } while (0)
static void input(HIDSupport *s, IOHIDDeviceRef d, uint32_t page, uint32_t usage, int v) {
    FakeValue value = {d,page,usage,v}; myHIDCallback((__bridge void *)s,0,NULL,&value);
}
int main(void) { @autoreleasepool {
    wire = [NSMutableArray new]; moves = [NSMutableArray new];
    HIDSupport *s = [HIDSupport new]; s.controller = [Controller new];
    s.shouldSendInputEvents = YES; s.gestureEnabled = YES;
    int devices[2];
    HIDDeviceControllerEntry *a = [s entryForDevice:&devices[0]];
    HIDDeviceControllerEntry *b = [s entryForDevice:&devices[1]];
    CHECK(!MLGamepadMenuGestureIsHolding(a.controller.menuGesture));
    // A release without a preceding press must not turn on mouse mode.
    clockNow = 100;
    [s updateButtonFlags:PLAY_FLAG entry:a state:NO];
    CHECK(!a.controller.isMouseMode);
    clockNow = 101; [s updateButtonFlags:PLAY_FLAG entry:a state:YES];
    clockNow = 101.1; [s updateButtonFlags:PLAY_FLAG entry:b state:NO];
    CHECK(MLGamepadMenuGestureIsHolding(a.controller.menuGesture));
    CHECK(!b.controller.isMouseMode);
    clockNow = 102.1; [s updateButtonFlags:PLAY_FLAG entry:a state:NO];
    CHECK(a.controller.isMouseMode && s.controller == a.controller && s.mouseModeEntry == a);
    CHECK([wire.lastObject isEqual:@[@0,@3,@0,@0,@0,@0,@0,@0,@0]]);
    [wire removeAllObjects];
    // Real HID XBox axis parsing feeds the exact object used by the pointer consumer.
    input(s,&devices[0],kHIDPage_GenericDesktop,kHIDUsage_GD_Z,65535);
    CHECK(a.controller.lastRightStickX == 32767);
    consume(s); CHECK([moves.lastObject isEqual:@[@15,@0]]);
    CHECK(wire.count == 1 && [wire.lastObject[0] intValue] == 1);
    [s updateButtonFlags:A_FLAG entry:a state:YES]; CHECK(s.mouseDown);
    CHECK((a.controller.lastButtonFlags & A_FLAG) != 0);
    int releases = s.releases;
    int mouseEvents = s.mouseEvents;
    [s updateButtonFlags:A_FLAG entry:b state:YES];
    CHECK(s.releases == releases && b.controller.lastButtonFlags == A_FLAG && s.mouseEvents == mouseEvents);
    input(s,&devices[1],kHIDPage_GenericDesktop,kHIDUsage_GD_Z,0);
    CHECK(b.controller.lastRightStickX == -32768);
    consume(s); CHECK([moves.lastObject isEqual:@[@15,@0]]);
    [wire removeAllObjects]; [moves removeAllObjects];
    [s setControllerMouseMode:YES forEntry:b];
    CHECK(!a.controller.isMouseMode && b.controller.isMouseMode && !s.mouseDown);
    CHECK(s.controller == b.controller && s.releases == releases + 1);
    CHECK(wire.count == 2 && [wire[0][0] intValue] == 0 && [wire[1][0] intValue] == 1);
    CHECK([wire[0][2] intValue] == A_FLAG && [wire[1][2] intValue] == 0);
    input(s,&devices[1],kHIDPage_GenericDesktop,kHIDUsage_GD_Z,0);
    consume(s); CHECK([moves.lastObject isEqual:@[@(-15),@0]]);
    [s updateButtonFlags:A_FLAG entry:b state:YES]; CHECK(s.mouseDown);
    // Exit through the real Xbox Menu callback, retaining held physical A.
    clockNow = 104; input(s,&devices[1],kHIDPage_Button,12,1);
    clockNow = 106; input(s,&devices[1],kHIDPage_Button,12,0);
    CHECK(!b.controller.isMouseMode && !s.mouseDown && s.mouseModeEntry == nil);
    CHECK([wire.lastObject[0] intValue] == 1 && [wire.lastObject[2] intValue] == A_FLAG);
    [s setControllerMouseMode:YES forEntry:b];
    [s updateButtonFlags:A_FLAG entry:b state:YES]; CHECK(s.mouseDown);
    // Removing an unrelated pad must not release the current owner's mouse button.
    releases = s.releases;
    myHIDDeviceRemovalCallback((__bridge void *)s,0,NULL,&devices[0]);
    CHECK(s.mouseDown && s.releases == releases && s.mouseModeEntry == b);
    myHIDDeviceRemovalCallback((__bridge void *)s,0,NULL,&devices[1]);
    CHECK(!s.mouseDown && !s.controller.isMouseMode && s.mouseModeEntry == nil);
    CHECK(s.deviceControllerTable.count == 0 && [wire.lastObject[1] intValue] == 0);
    [moves removeAllObjects]; consume(s); CHECK(moves.count == 0);
    a = [s entryForDevice:&devices[0]];
    s.gestureEnabled = NO;
    clockNow = 110; [s updateButtonFlags:PLAY_FLAG entry:a state:YES];
    clockNow = 112; [s updateButtonFlags:PLAY_FLAG entry:a state:NO];
    CHECK(!a.controller.isMouseMode);
    [s setControllerMouseMode:YES forEntry:a];
    a.controller.lastRightStickX = 32767;
    s.shouldSendInputEvents = NO; consume(s); CHECK(moves.count == 0);
    s.shouldSendInputEvents = YES; s.controllerDriver = 1; consume(s); CHECK(moves.count == 0);
    puts("HID producer/mouse routing replay passed"); return 0;
}}
'''
code = harness.replace('__METHODS__',methods).replace('__CALLBACKS__',callbacks).replace('__DRAIN__',drain).replace('__CONSUMER__',consumer)
cc, sdk = clang_and_sdk('controller mouse routing replay')
def run(source):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        (p/'Controller.h').write_text(controller_header)
        for name in ['ControllerEventBaseline.h','ControllerEventBaseline.m','GamepadMenuGesture.h','GamepadMenuGesture.m','MouseEmulation.h']:
            (p/name).write_text((root/'Limelight/Input'/name).read_text())
        (p/'probe.m').write_text(source)
        subprocess.run([cc,'-fobjc-arc','-fblocks','-Wall','-Werror','-isysroot',sdk,'-I',str(p),
                        '-I',str(root/'moonlight-common/moonlight-common-c/src'),'-framework','Foundation',
                        str(p/'probe.m'),str(p/'ControllerEventBaseline.m'),str(p/'GamepadMenuGesture.m'),'-o',str(p/'probe')],check=True)
        return subprocess.run([str(p/'probe')],capture_output=True,text=True)
r = run(code)
assert r.returncode == 0,r.stderr
print(r.stdout.strip())
for name, old, new in (
    ('unpressed Menu treated as an old hold', 'entry.controller.menuGesture = MLGamepadMenuGestureIdle();', ''),
    ('non-owner axis writes into pointer owner', 'Controller *devController = entry.controller;', 'Controller *devController = self.controller;'),
    ('previous owner never resumes gamepad input', 'previous.controller.isMouseMode = NO;', ''),
    ('pointer still uses orphan controller', 'self.controller = entry.controller;', ''),
    ('gesture shared between pads', 'MLGamepadMenuGesture gesture = entry.controller.menuGesture;', 'MLGamepadMenuGesture gesture = self.controller.menuGesture;'),
    ('remote held state not neutralized', '[self sendControllerNeutralEventForEntry:entry];',''),
    ('all pads become mouse buttons', 'if (entry.controller.isMouseMode) {','if (self.controller.isMouseMode) {'),
    ('mouse button state lost on mode exit', 'entry.controller.lastButtonFlags |= flag;', 'if (!entry.controller.isMouseMode) entry.controller.lastButtonFlags |= flag;'),
):
    assert code.count(old) == 1,name
    r = run(code.replace(old,new))
    assert r.returncode == 1 and 'failed line' in r.stderr,name+r.stderr
    print('caught:',name)
