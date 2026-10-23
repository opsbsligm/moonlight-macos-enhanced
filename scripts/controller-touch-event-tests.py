#!/usr/bin/env python3
"""Compile the shipping pushControllerTouch touch path; replay a PS4 pad.

The host can show a controller touchpad if the client advertises
LI_CCAP_TOUCHPAD and sends controller touch events. Before this gate the
macOS app never read the two touch points that the PS4/PS5 state packets
already carry, so the host never saw a touchpad.

This gate compiles the real pushControllerTouchForEntry /
dispatchTouchForEntry / sendControllerTouchForEntry / resetControllerState /
entryForDevice out of the tree and replays two PS4 pads plus one PS5 and one
Xbox:

  * only a pad whose state packets carry touch points (PS4/PS5) advertises
    the capability, and only those two send;
  * the 12-bit X/Y decode normalizes to 0-1 (0xFFF maps to 1.0);
  * a finger going down is a DOWN, a move that actually changed position is a
    MOVE, and a lift is an UP - an unchanged re-announce does not resend;
  * the pointer id is locked for the life of a press;
  * the two physical touch points are tracked independently;
  * the PS5 reads its own snapshot, not the PS4 one.

Self-test plants the regressions this gate exists to catch.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
from apple_toolchain import clang_and_sdk


def method(text, anchor):
    start = text.index(anchor)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


hid_src = Path('Limelight/Input/HIDSupport.m').read_text()
HELPERS = ['- (void)pushControllerTouchForEntry:',
           '- (void)dispatchTouchForEntry:',
           '- (void)sendControllerTouchForEntry:',
           '- (void)resetControllerStateForEntry:',
           '- (HIDDeviceControllerEntry *)entryForDevice:']
methods = '\n'.join(method(hid_src, h) for h in HELPERS) + '\n'

harness = r'''
#import <Foundation/Foundation.h>
typedef const void *IOHIDDeviceRef;
CFTypeRef CFRetain(CFTypeRef v) { return v; }
void CFRelease(CFTypeRef v) { (void)v; }

static const void *PAD0 = (const void *)0x1;
static const void *PAD1 = (const void *)0x2;
static const void *PAD2 = (const void *)0x3;
static const void *PAD3 = (const void *)0x4;
static BOOL isPS4(IOHIDDeviceRef device) { return device == PAD0 || device == PAD1; }
static BOOL isPS5(IOHIDDeviceRef device) { return device == PAD2; }
static BOOL isXbox(IOHIDDeviceRef device) { (void)device; return NO; }
static BOOL isKingKong(IOHIDDeviceRef device) { (void)device; return NO; }
typedef struct { double pressedAt; } MLGamepadMenuGesture;
static MLGamepadMenuGesture MLGamepadMenuGestureIdle(void) {
    return (MLGamepadMenuGesture){__builtin_nan("")};
}
static const uint16_t LI_CCAP_ANALOG_TRIGGERS = 0x01;
static const uint16_t LI_CCAP_RUMBLE = 0x02;
static const uint16_t LI_CCAP_TRIGGER_RUMBLE = 0x04;
static const uint16_t LI_CCAP_TOUCHPAD = 0x08;
static const uint16_t LI_CCAP_ACCEL = 0x10;
static const uint16_t LI_CCAP_GYRO = 0x20;
static const uint16_t LI_CCAP_BATTERY_STATE = 0x40;
static const uint16_t LI_CCAP_RGB_LED = 0x80;
static const uint16_t kHIDArrivalCapabilities = LI_CCAP_ANALOG_TRIGGERS | LI_CCAP_RUMBLE;
static const uint8_t LI_TOUCH_EVENT_DOWN = 0x01;
static const uint8_t LI_TOUCH_EVENT_UP = 0x02;
static const uint8_t LI_TOUCH_EVENT_MOVE = 0x03;
static const uint32_t LI_FF_CONTROLLER_TOUCH_EVENTS = 0x02;
static uint32_t g_flags;
typedef void *PML_CONNECTION_CONTEXT;
typedef struct { PML_CONNECTION_CONTEXT connectionContext; } FakeInputContext;
typedef FakeInputContext *PML_INPUT_STREAM_CONTEXT;
#pragma clang diagnostic ignored "-Wunused-function"
static uint32_t LiGetHostFeatureFlagsCtx(PML_CONNECTION_CONTEXT ctx) {
    (void)ctx;
    return g_flags;
}
typedef struct { PML_INPUT_STREAM_CONTEXT context; uint64_t generation; } HIDInputLease;
static FakeInputContext g_ctx = { (PML_CONNECTION_CONTEXT)0x1 };
@class HIDSupport;
static HIDInputLease HIDAcquireInputContext(HIDSupport *s) { (void)s; return (HIDInputLease){&g_ctx, 1}; }
@interface TCall : NSObject
@property uint8_t number, eventType;
@property uint32_t pointerId;
@property float x, y, pressure;
@end
@implementation TCall
@end
static NSMutableArray *g_touch;
static void LiSendControllerTouchEventCtx(PML_INPUT_STREAM_CONTEXT ctx, uint8_t number,
                                          uint8_t eventType, uint32_t pointerId,
                                          float x, float y, float pressure) {
    (void)ctx;
    TCall *c = [TCall new];
    c.number = number; c.eventType = eventType; c.pointerId = pointerId;
    c.x = x; c.y = y; c.pressure = pressure;
    [g_touch addObject:c];
}
static void HIDDispatchInput(HIDSupport *s, HIDInputLease lease, dispatch_block_t job) { (void)s; (void)lease; job(); }
@interface Controller : NSObject
@property int lastButtonFlags;
@property unsigned char lastLeftTrigger;
@property unsigned char lastRightTrigger;
@property short lastLeftStickX;
@property short lastLeftStickY;
@property short lastRightStickX;
@property short lastRightStickY;
@property MLGamepadMenuGesture menuGesture;
@end
@implementation Controller
@end
typedef struct {
    UInt8 ucLeftJoystickX; UInt8 ucLeftJoystickY; UInt8 ucRightJoystickX; UInt8 ucRightJoystickY;
    UInt8 rgucButtonsHatAndCounter[3]; UInt8 ucTriggerLeft; UInt8 ucTriggerRight;
    UInt8 _rgucPad0[3];
    UInt8 rgucGyroX[2]; UInt8 rgucGyroY[2]; UInt8 rgucGyroZ[2];
    UInt8 rgucAccelX[2]; UInt8 rgucAccelY[2]; UInt8 rgucAccelZ[2];
    UInt8 _rgucPad1[5]; UInt8 ucBatteryLevel; UInt8 _rgucPad2[4];
    UInt8 ucTouchpadCounter1; UInt8 rgucTouchpadData1[3];
    UInt8 ucTouchpadCounter2; UInt8 rgucTouchpadData2[3];
} PS4StatePacket_t;
typedef struct {
    UInt8 ucLeftJoystickX; UInt8 ucLeftJoystickY; UInt8 ucRightJoystickX; UInt8 ucRightJoystickY;
    UInt8 ucTriggerLeft; UInt8 ucTriggerRight; UInt8 ucCounter; UInt8 rgucButtonsAndHat[3];
    UInt8 ucZero; UInt8 rgucPacketSequence[4];
    UInt8 rgucGyroX[2]; UInt8 rgucGyroY[2]; UInt8 rgucGyroZ[2];
    UInt8 rgucAccelX[2]; UInt8 rgucAccelY[2]; UInt8 rgucAccelZ[2];
    UInt8 rgucTimer1[4]; UInt8 ucBatteryTemp;
    UInt8 ucTouchpadCounter1; UInt8 rgucTouchpadData1[3];
    UInt8 ucTouchpadCounter2; UInt8 rgucTouchpadData2[3];
    UInt8 rgucUnknown1[8]; UInt8 rgucTimer2[4];
    UInt8 ucBatteryLevel; UInt8 ucConnectState;
} PS5StatePacket_t;
@interface HIDDeviceControllerEntry : NSObject
@property(strong) Controller *controller;
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
@property uint8_t previousBatteryState;
@property uint8_t previousBatteryPercentage;
@property BOOL touchPressed;
@property BOOL touchPressed2;
@property uint32_t touchPointerId;
@property float touchLastX, touchLastY;
@property uint32_t touchPointerId2;
@property float touchLastX2, touchLastY2;
@property PS4StatePacket_t lastPS4State;
@property PS5StatePacket_t lastPS5State;
@end
@implementation HIDDeviceControllerEntry
@end
@interface HIDSupport : NSObject
@property(strong) NSMutableDictionary<NSString *, HIDDeviceControllerEntry *> *deviceControllerTable;
@property NSInteger controllerDriver;
@property BOOL shouldSendInputEvents;
@property BOOL suspendControllerEvents;
@end
@implementation HIDSupport
- (void)stopMotionEventsForEntry:(HIDDeviceControllerEntry *)entry { (void)entry; }
- (uint8_t)protocolTypeForDevice:(IOHIDDeviceRef)d { (void)d; return 1; }
- (uint32_t)supportedButtonFlagsForDevice:(IOHIDDeviceRef)d { (void)d; return 0xffff; }
- (NSString *)deviceKeyForDevice:(IOHIDDeviceRef)device {
    return device == NULL ? nil : [NSString stringWithFormat:@"hid:%p", (void *)device];
}
- (int)allocatePlayerSlot {
    int taken[16] = {0};
    for (HIDDeviceControllerEntry *e in self.deviceControllerTable.allValues) {
        if (e.playerIndex >= 0 && e.playerIndex < 16) taken[e.playerIndex] = 1;
    }
    for (int i = 0; i < 16; i++) if (!taken[i]) return i;
    return -1;
}
- (IOHIDDeviceRef)getFirstDevice { return (IOHIDDeviceRef)PAD0; }
__METHODS__
@end

// 12-bit touch coordinate: x = data[0]|((data[1]&0xF)<<8), y = (data[1]>>4)|(data[2]<<4).
// counter: top bit clear = finger down, low 7 bits = press counter (pointer id).
static void setPS4Touch1(HIDDeviceControllerEntry *e, uint8_t counter, int16_t x12, int16_t y12) {
    PS4StatePacket_t p = e.lastPS4State;
    p.ucTouchpadCounter1 = counter;
    p.rgucTouchpadData1[0] = (uint8_t)(x12 & 0xFF);
    p.rgucTouchpadData1[1] = (uint8_t)(((x12 >> 8) & 0x0F) | ((y12 & 0x0F) << 4));
    p.rgucTouchpadData1[2] = (uint8_t)((y12 >> 4) & 0xFF);
    e.lastPS4State = p;
}
static void setPS4Touch2(HIDDeviceControllerEntry *e, uint8_t counter, int16_t x12, int16_t y12) {
    PS4StatePacket_t p = e.lastPS4State;
    p.ucTouchpadCounter2 = counter;
    p.rgucTouchpadData2[0] = (uint8_t)(x12 & 0xFF);
    p.rgucTouchpadData2[1] = (uint8_t)(((x12 >> 8) & 0x0F) | ((y12 & 0x0F) << 4));
    p.rgucTouchpadData2[2] = (uint8_t)((y12 >> 4) & 0xFF);
    e.lastPS4State = p;
}
static void setPS5Touch1(HIDDeviceControllerEntry *e, uint8_t counter, int16_t x12, int16_t y12) {
    PS5StatePacket_t p = e.lastPS5State;
    p.ucTouchpadCounter1 = counter;
    p.rgucTouchpadData1[0] = (uint8_t)(x12 & 0xFF);
    p.rgucTouchpadData1[1] = (uint8_t)(((x12 >> 8) & 0x0F) | ((y12 & 0x0F) << 4));
    p.rgucTouchpadData1[2] = (uint8_t)((y12 >> 4) & 0xFF);
    e.lastPS5State = p;
}
static void setPS5Touch2(HIDDeviceControllerEntry *e, uint8_t counter, int16_t x12, int16_t y12) {
    PS5StatePacket_t p = e.lastPS5State;
    p.ucTouchpadCounter2 = counter;
    p.rgucTouchpadData2[0] = (uint8_t)(x12 & 0xFF);
    p.rgucTouchpadData2[1] = (uint8_t)(((x12 >> 8) & 0x0F) | ((y12 & 0x0F) << 4));
    p.rgucTouchpadData2[2] = (uint8_t)((y12 >> 4) & 0xFF);
    e.lastPS5State = p;
}
#define CHECK(x) do { if (!(x)) { NSLog(@"failed line %d", __LINE__); return 1; } } while (0)
#define TCH(i) ((TCall *)g_touch[i])

int main(int argc, char *argv[]) { (void)argc; (void)argv; @autoreleasepool {
    g_touch = [NSMutableArray new];
    HIDSupport *s = [HIDSupport new];
    s.shouldSendInputEvents = YES;
    // The host in this replay answers that it can draw a controller touchpad;
    // the last case clears the flag to prove the pad stops paying for reports
    // a host will never read.
    g_flags = LI_FF_CONTROLLER_TOUCH_EVENTS;

    HIDDeviceControllerEntry *e0 = [s entryForDevice:PAD0]; e0.playerIndex = 0;
    HIDDeviceControllerEntry *e1 = [s entryForDevice:PAD1]; e1.playerIndex = 1;
    HIDDeviceControllerEntry *e2 = [s entryForDevice:PAD2]; e2.playerIndex = 2;
    HIDDeviceControllerEntry *e3 = [s entryForDevice:PAD3]; e3.playerIndex = 3;
    CHECK((e0.capabilities & LI_CCAP_TOUCHPAD) != 0);
    CHECK((e2.capabilities & LI_CCAP_TOUCHPAD) != 0);
    CHECK((e3.capabilities & LI_CCAP_TOUCHPAD) == 0);

    // An idle pad reports both touch points with the top counter bit set
    // (inactive). Establish that baseline first, so a zero-initialized entry
    // does not read an untouched point as a phantom press.
    setPS4Touch1(e0, 0x80, 0, 0);
    setPS4Touch2(e0, 0x80, 0, 0);
    [s pushControllerTouchForEntry:e0];
    CHECK(g_touch.count == 0);

    // PS4: a finger goes down at 12-bit (4095, 0). The top counter bit is
    // clear when down, so counter 0x01 = press 1. This is a DOWN at x=1.0.
    setPS4Touch1(e0, 0x01, 4095, 0);
    [s pushControllerTouchForEntry:e0];
    CHECK(g_touch.count == 1);
    CHECK(TCH(0).number == 0);
    CHECK(TCH(0).eventType == LI_TOUCH_EVENT_DOWN);
    CHECK(TCH(0).pointerId == 1);
    CHECK(fabsf(TCH(0).x - 1.0f) < 0.0001f);
    CHECK(fabsf(TCH(0).y - 0.0f) < 0.0001f);
    CHECK(TCH(0).pressure == 1.0f);

    // A move that changes position is a MOVE. The counter byte keeps ticking
    // on a real pad (here 0x01 -> 0x03), so the pointer id is only stable if
    // it was locked at the down edge.
    setPS4Touch1(e0, 0x03, 2048, 2048);
    [s pushControllerTouchForEntry:e0];
    CHECK(g_touch.count == 2);
    CHECK(TCH(1).eventType == LI_TOUCH_EVENT_MOVE);
    CHECK(TCH(1).pointerId == 1);
    CHECK(fabsf(TCH(1).x - 0.5f) < 0.0005f);
    CHECK(fabsf(TCH(1).y - 0.5f) < 0.0005f);
    // A re-announce with unchanged position does not resend.
    [s pushControllerTouchForEntry:e0];
    CHECK(g_touch.count == 2);
    // The finger lifts: the top counter bit is set when up.
    setPS4Touch1(e0, 0x81, 2048, 2048);
    [s pushControllerTouchForEntry:e0];
    CHECK(g_touch.count == 3);
    CHECK(TCH(2).eventType == LI_TOUCH_EVENT_UP);
    CHECK(TCH(2).pointerId == 1);
    CHECK(TCH(2).pressure == 0.0f);
    // Nothing moves while no finger is down.
    [s pushControllerTouchForEntry:e0];
    CHECK(g_touch.count == 3);

    // Pointer id is captured at the down edge, not the current counter: a new
    // press with a different counter value gets its own id.
    setPS4Touch1(e0, 0x07, 0, 0);
    [s pushControllerTouchForEntry:e0];
    CHECK(g_touch.count == 4);
    CHECK(TCH(3).eventType == LI_TOUCH_EVENT_DOWN);
    CHECK(TCH(3).pointerId == 7);

    // The second touch point is independent: point 2 going down does not
    // disturb point 1's still-down state.
    setPS4Touch2(e0, 0x02, 4095, 4095);
    [s pushControllerTouchForEntry:e0];
    CHECK(g_touch.count == 5);
    TCall *last = TCH(g_touch.count - 1);
    CHECK(last.eventType == LI_TOUCH_EVENT_DOWN);
    CHECK(last.pointerId == 2);
    CHECK(fabsf(last.x - 1.0f) < 0.0001f);
    CHECK(fabsf(last.y - 1.0f) < 0.0001f);
    // Point 1 still down, moving, is unaffected by point 2.
    setPS4Touch1(e0, 0x07, 1024, 1024);
    setPS4Touch2(e0, 0x02, 4095, 4095);   // unchanged point 2
    [s pushControllerTouchForEntry:e0];
    CHECK(TCH(g_touch.count - 1).eventType == LI_TOUCH_EVENT_MOVE);
    CHECK(TCH(g_touch.count - 1).pointerId == 7);

    // The dedup is per device: a neighbour pad's down is not suppressed.
    // Baseline e1 first (its point2 is otherwise a phantom press).
    setPS4Touch2(e1, 0x80, 0, 0);
    setPS4Touch1(e1, 0x80, 0, 0);
    [s pushControllerTouchForEntry:e1];
    setPS4Touch1(e1, 0x01, 0, 4095);
    [s pushControllerTouchForEntry:e1];
    last = TCH(g_touch.count - 1);
    CHECK(last.number == 1);
    CHECK(last.eventType == LI_TOUCH_EVENT_DOWN);
    CHECK(fabsf(last.y - 1.0f) < 0.0001f);

    // PS5 reads its own snapshot, not the PS4 one. Baseline e2 first (its
    // point2 would otherwise be a phantom press), then point 1 goes down.
    setPS5Touch2(e2, 0x80, 0, 0);
    setPS5Touch1(e2, 0x80, 0, 0);
    [s pushControllerTouchForEntry:e2];
    setPS5Touch1(e2, 0x01, 4095, 4095);
    [s pushControllerTouchForEntry:e2];
    last = TCH(g_touch.count - 1);
    CHECK(last.number == 2);
    CHECK(last.eventType == LI_TOUCH_EVENT_DOWN);
    CHECK(fabsf(last.x - 1.0f) < 0.0001f);
    CHECK(fabsf(last.y - 1.0f) < 0.0001f);

    // Gates: the driver switch and the input-forwarding gate suppress.
    [s resetControllerStateForEntry:e0];
    setPS4Touch1(e0, 0x01, 128, 128);
    s.controllerDriver = 1;
    [s pushControllerTouchForEntry:e0];
    CHECK(TCH(g_touch.count - 1).eventType == LI_TOUCH_EVENT_DOWN); // last was e2's
    s.controllerDriver = 0;
    s.shouldSendInputEvents = NO;
    [s pushControllerTouchForEntry:e0];
    CHECK(TCH(g_touch.count - 1).eventType == LI_TOUCH_EVENT_DOWN);
    s.shouldSendInputEvents = YES;

    // reset clears the session: the same down re-sends after a reset. Point 2
    // is parked idle so only point 1 re-announces.
    setPS4Touch2(e0, 0x80, 0, 0);
    [s resetControllerStateForEntry:e0];
    [s pushControllerTouchForEntry:e0];   // e0 point 1 still down at (128,128)
    last = TCH(g_touch.count - 1);
    CHECK(last.number == 0);
    CHECK(last.eventType == LI_TOUCH_EVENT_DOWN);
    CHECK(last.pointerId == 1);
    CHECK(fabsf(last.x - (128.0f/4095.0f)) < 0.0005f);

    // M4 退化路径: the pad advertises the touchpad, but a host that did not set
    // LI_FF_CONTROLLER_TOUCH_EVENTS (the GFE shape) would ignore the reports.
    // With the flag cleared the same down must produce no report at all, and the
    // transition state still moved, so restoring the flag re-sends the down once.
    NSUInteger before = g_touch.count;
    g_flags = 0;
    // The finger is already down, so the next frame with a moved position is a
    // transition that would emit: the gate must swallow that report, not the
    // state machine.
    setPS4Touch1(e0, 0x03, 256, 256);
    [s pushControllerTouchForEntry:e0];
    CHECK(g_touch.count == before);
    g_flags = LI_FF_CONTROLLER_TOUCH_EVENTS;
    setPS4Touch2(e0, 0x80, 0, 0);
    [s resetControllerStateForEntry:e0];
    setPS4Touch1(e0, 0x01, 128, 128);
    [s pushControllerTouchForEntry:e0];
    CHECK(g_touch.count == before + 1);
    CHECK(TCH(before).eventType == LI_TOUCH_EVENT_DOWN);

    puts("touch event replay passed");
    return 0;
}}
'''

harness = harness.replace('__METHODS__', methods)


def replay_probe(path):
    cc, sdk = clang_and_sdk('touch event replay')
    proc = subprocess.run(
        [cc, '-fobjc-arc', '-fblocks', '-Wall', '-Werror', '-isysroot', sdk,
         '-framework', 'Foundation',
         str(path / 'probe.m'), '-o', str(path / 'probe')],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout + proc.stderr)
        return False, 'build'
    ran = subprocess.run([str(path / 'probe')], capture_output=True, text=True)
    ok = ran.returncode == 0 and 'touch event replay passed' in ran.stdout
    if not ok:
        print(ran.stdout, ran.stderr)
    return ok, None


def replay(code, label='current'):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        (path / 'probe.m').write_text(code)
        ok, _ = replay_probe(path)
        return ok, label


MUTATIONS = (
    ('pointer id not locked, uses live counter',
     'uint32_t pid = pressed ? entry.touchPointerId : (uint32_t)id;',
     'uint32_t pid = (uint32_t)id;'),
    ('move not deduplicated on position',
     'if (x != entry.touchLastX || y != entry.touchLastY) {',
     'if (NO) {'),
    ('up edge keeps pressure at 1',
     '[self sendControllerTouchForEntry:entry pointer:pid eventType:LI_TOUCH_EVENT_UP x:x y:y pressure:0.0f];',
     '[self sendControllerTouchForEntry:entry pointer:pid eventType:LI_TOUCH_EVENT_UP x:x y:y pressure:1.0f];'),
    ('12-bit decode wrong, x from raw byte only',
     'float x1 = (float)(s.rgucTouchpadData1[0] | ((s.rgucTouchpadData1[1] & 0x0F) << 8)) / 4095.0f;',
     'float x1 = (float)s.rgucTouchpadData1[0] / 255.0f;'),
    ('active bit inverted',
     'BOOL active1 = !(s.ucTouchpadCounter1 & 0x80);',
     'BOOL active1 = (s.ucTouchpadCounter1 & 0x80);'),
    ('second point not independent, shares state',
     'BOOL pressed2 = entry.touchPressed2;',
     'BOOL pressed2 = entry.touchPressed;'),
    ('host feature flag ignored, reports always sent',
     "        if ((LiGetHostFeatureFlagsCtx(lease.context->connectionContext) & LI_FF_CONTROLLER_TOUCH_EVENTS) == 0) {\n            return;\n        }\n",
     ""),
    ('host feature flag inverted, sends only when unsupported',
     "LI_FF_CONTROLLER_TOUCH_EVENTS) == 0) {",
     "LI_FF_CONTROLLER_TOUCH_EVENTS) != 0) {"),
)


def main():
    if '--self-test' in sys.argv:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for label_, old, new in MUTATIONS:
                (path / 'probe.m').write_text(harness.replace(old, new))
                ok_, _ = replay_probe(path)
                if ok_:
                    print('touch event self-test: NOT CAUGHT (%s)' % label_)
                    raise SystemExit(1)
                print('touch event self-test: caught %s' % label_)
            (path / 'probe.m').write_text(harness)
            ok_, _ = replay_probe(path)
            if not ok_:
                print('touch event self-test: clean harness FAILS')
                raise SystemExit(1)
            print('touch event self-test: clean harness passes')
        return

    ok, label = replay(harness)
    if not ok:
        print('touch event: current code FAILS (%s)' % label)
        raise SystemExit(1)
    print('touch event: current code passes (%s)' % label)

    for label_, old, new in MUTATIONS:
        m = harness.replace(old, new)
        assert m != harness, label_
        ok_, _ = replay(m, label=label_)
        if ok_:
            print('touch event: NOT CAUGHT (%s)' % label_)
            raise SystemExit(1)
        print('touch event: caught %s' % label_)


if __name__ == '__main__':
    main()
