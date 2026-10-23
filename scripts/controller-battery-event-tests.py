#!/usr/bin/env python3
"""Compile the shipping pushBatteryEvent battery path; replay two PS4 pads.

The host's virtual pad can show a charge level if the client advertises
LI_CCAP_BATTERY_STATE and sends a battery event. Before this gate the macOS
app never read the charge byte that the PS4/PS5 state packets already
carry, so the host always saw an unknown level.

This gate compiles the real pushBatteryEventForEntry / resetControllerState /
entryForDevice out of the tree and replays two PS4 pads plus one PS5 and one
Xbox:

  * the index resolves to the pad that owns it; an unknown index falls back
    to the first device;
  * only a pad whose state packets carry a charge byte (PS4/PS5) advertises
    the battery capability, and only those two send;
  * the raw byte decodes per the SDL HIDAPI PS4/PS5 layout: the low nibble
    is a 0-10 level that maps to 0-100 percent, and bit 0x10 means the pad
    is on the wire, so it reports NOT_CHARGING with an unknown percentage
    instead of a fake 0 percent;
  * a level change resends, an unchanged level does not, and the per-device
    dedup does not suppress the next pad's first reading.

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
HELPERS = ['- (void)pushBatteryEventForEntry:',
           '- (void)stopMotionEventsForEntry:',
           '- (void)resetControllerStateForEntry:',
           '- (HIDDeviceControllerEntry *)entryForDevice:']
methods = '\n'.join(method(hid_src, h) for h in HELPERS) + '\n'

harness = r'''
#import <Foundation/Foundation.h>
typedef const void *IOHIDDeviceRef;
CFTypeRef CFRetain(CFTypeRef v) { return v; }
void CFRelease(CFTypeRef v) { (void)v; }

// pad0/pad1 are PS4, pad2 is PS5, pad3 is Xbox: the shipped capability
// decision and the family's own snapshot read are both exercised.
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
static const uint16_t LI_CCAP_ACCEL = 0x10;
static const uint16_t LI_CCAP_GYRO = 0x20;
static const uint16_t LI_CCAP_BATTERY_STATE = 0x40;
static const uint16_t LI_CCAP_RGB_LED = 0x80;
static const uint16_t kHIDArrivalCapabilities = LI_CCAP_ANALOG_TRIGGERS | LI_CCAP_RUMBLE;
static const uint8_t LI_BATTERY_STATE_DISCHARGING = 0x02;
static const uint8_t LI_BATTERY_STATE_NOT_CHARGING = 0x04;
static const uint8_t LI_BATTERY_PERCENTAGE_UNKNOWN = 0xFF;
typedef int *PML_INPUT_STREAM_CONTEXT;
typedef struct { PML_INPUT_STREAM_CONTEXT context; uint64_t generation; } HIDInputLease;
static int g_ctx;
@class HIDSupport;
static HIDInputLease HIDAcquireInputContext(HIDSupport *s) { (void)s; return (HIDInputLease){&g_ctx, 1}; }
@interface BCall : NSObject
@property uint8_t number, state, percentage;
@end
@implementation BCall
@end
static NSMutableArray *g_batt;
static int g_sendCalls = 0;
static void LiSendControllerBatteryEventCtx(PML_INPUT_STREAM_CONTEXT ctx, uint8_t number,
                                            uint8_t state, uint8_t percentage) {
    (void)ctx; g_sendCalls++;
    BCall *c = [BCall new];
    c.number = number; c.state = state; c.percentage = percentage;
    [g_batt addObject:c];
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
@property PS4StatePacket_t lastPS4State;
@property PS5StatePacket_t lastPS5State;
@end
@implementation HIDDeviceControllerEntry
@end
@interface HIDSupport : NSObject
@property(strong) NSMutableDictionary<NSString *, HIDDeviceControllerEntry *> *deviceControllerTable;
@property NSInteger controllerDriver;
@property BOOL shouldSendInputEvents;
@end
@implementation HIDSupport
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

// The state struct is stored by value; a subfield write is a read-modify-write.
static void setPS4Battery(HIDDeviceControllerEntry *e, uint8_t v) {
    PS4StatePacket_t p = e.lastPS4State; p.ucBatteryLevel = v; e.lastPS4State = p;
}
static void setPS5Battery(HIDDeviceControllerEntry *e, uint8_t v) {
    PS5StatePacket_t p = e.lastPS5State; p.ucBatteryLevel = v; e.lastPS5State = p;
}

#define CHECK(x) do { if (!(x)) { NSLog(@"failed line %d", __LINE__); return 1; } } while (0)
#define BATT(i) ((BCall *)g_batt[i])

int main(int argc, char *argv[]) { (void)argc; (void)argv; @autoreleasepool {
    g_batt = [NSMutableArray new];
    HIDSupport *s = [HIDSupport new];
    s.shouldSendInputEvents = YES;

    // Four pads: two PS4 (indices 0/1), one PS5 (2), one Xbox (3). The shipped
    // capability decision runs from entryForDevice: against them.
    HIDDeviceControllerEntry *e0 = [s entryForDevice:PAD0]; e0.playerIndex = 0;
    HIDDeviceControllerEntry *e1 = [s entryForDevice:PAD1]; e1.playerIndex = 1;
    HIDDeviceControllerEntry *e2 = [s entryForDevice:PAD2]; e2.playerIndex = 2;
    HIDDeviceControllerEntry *e3 = [s entryForDevice:PAD3]; e3.playerIndex = 3;
    CHECK((e0.capabilities & LI_CCAP_BATTERY_STATE) != 0);
    CHECK((e2.capabilities & LI_CCAP_BATTERY_STATE) != 0);
    CHECK((e3.capabilities & LI_CCAP_BATTERY_STATE) == 0);

    // PS4 decode: the low nibble is a 0-10 level, mapped to 0-100 percent.
    setPS4Battery(e0, 0x0A);     // full, on battery
    [s pushBatteryEventForEntry:e0];
    CHECK(g_batt.count == 1);
    CHECK(BATT(0).number == 0);
    CHECK(BATT(0).state == LI_BATTERY_STATE_DISCHARGING);
    CHECK(BATT(0).percentage == 100);
    // The first reading is remembered; an unchanged level does not resend.
    [s pushBatteryEventForEntry:e0];
    CHECK(g_batt.count == 1);
    // A level drop resends with the new percentage.
    setPS4Battery(e0, 0x05);
    [s pushBatteryEventForEntry:e0];
    CHECK(g_batt.count == 2);
    CHECK(BATT(1).percentage == 50);
    // Wired pads carry a meaningless level: report NOT_CHARGING, unknown pct.
    setPS4Battery(e0, 0x15);
    [s pushBatteryEventForEntry:e0];
    CHECK(g_batt.count == 3);
    CHECK(BATT(2).state == LI_BATTERY_STATE_NOT_CHARGING);
    CHECK(BATT(2).percentage == LI_BATTERY_PERCENTAGE_UNKNOWN);

    // The dedup is per device: the neighbour pad's first reading is not
    // suppressed by e0's remembered value, and it routes to its own index.
    setPS4Battery(e1, 0x05);
    [s pushBatteryEventForEntry:e1];
    CHECK(g_batt.count == 4);
    CHECK(BATT(3).number == 1);
    CHECK(BATT(3).percentage == 50);

    // Routing: the index resolves to the owning pad, an unknown index to the
    // first device.
    [s resetControllerStateForEntry:e0];       // clear e0's remembered reading
    setPS4Battery(e0, 0x03);
    [s pushBatteryEventForEntry:e0];
    CHECK(BATT(g_batt.count - 1).number == 0);
    CHECK(BATT(g_batt.count - 1).percentage == 30);
    [s resetControllerStateForEntry:e0];       // clear before the fallback probe
    setPS4Battery(e0, 0x08);
    [s pushBatteryEventForEntry:e0];           // e0 is first device, index 0 anyway
    CHECK(BATT(g_batt.count - 1).number == 0);
    CHECK(BATT(g_batt.count - 1).percentage == 80);

    // PS5 reads its own snapshot, not the PS4 one.
    [s resetControllerStateForEntry:e2];
    setPS5Battery(e2, 0x01);
    setPS4Battery(e2, 0x0A);     // must NOT be read
    [s pushBatteryEventForEntry:e2];
    CHECK(BATT(g_batt.count - 1).number == 2);
    CHECK(BATT(g_batt.count - 1).percentage == 10);

    // Gates: the driver switch and the input-forwarding gate suppress.
    [s resetControllerStateForEntry:e0];
    setPS4Battery(e0, 0x09);
    [s pushBatteryEventForEntry:e0];
    CHECK(BATT(g_batt.count - 1).percentage == 90);   // reset re-announced
    s.controllerDriver = 1;
    [s pushBatteryEventForEntry:e0];
    CHECK(BATT(g_batt.count - 1).percentage == 90);   // driver suppressed the resend
    s.controllerDriver = 0;
    s.shouldSendInputEvents = NO;
    [s pushBatteryEventForEntry:e0];
    CHECK(BATT(g_batt.count - 1).percentage == 90);
    s.shouldSendInputEvents = YES;

    // reset clears the dedup: the same level re-sends after a reset.
    [s resetControllerStateForEntry:e0];
    setPS4Battery(e0, 0x08);
    [s pushBatteryEventForEntry:e0];
    CHECK(BATT(g_batt.count - 1).number == 0);
    CHECK(BATT(g_batt.count - 1).percentage == 80);

    puts("battery event replay passed");
    return 0;
}}
'''

harness = harness.replace('__METHODS__', methods)


def replay_probe(path):
    cc, sdk = clang_and_sdk('battery event replay')
    proc = subprocess.run(
        [cc, '-fobjc-arc', '-fblocks', '-Wall', '-Werror', '-isysroot', sdk,
         '-framework', 'Foundation',
         str(path / 'probe.m'), '-o', str(path / 'probe')],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout + proc.stderr)
        return False, 'build'
    ran = subprocess.run([str(path / 'probe')], capture_output=True, text=True)
    ok = ran.returncode == 0 and 'battery event replay passed' in ran.stdout
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
    ('index ignored in routing',
     'int slot = entry.playerIndex;',
     'int slot = 0;'),
    ('level not scaled to percent',
     'percentage = (uint8_t)((raw & 0x0F) * 10);',
     'percentage = (uint8_t)(raw & 0x0F);'),
    ('wired pad reports a fake 0 percent',
     'state = LI_BATTERY_STATE_NOT_CHARGING;',
     'state = LI_BATTERY_STATE_DISCHARGING;\n        percentage = 0;'),
    ('dedup removed, repeats resend',
     'if (state == entry.previousBatteryState &&',
     'if (NO && state == entry.previousBatteryState &&'),
    ('family reads the wrong snapshot',
     'const uint8_t raw = isPS5(entry.hidDevice) ? entry.lastPS5State.ucBatteryLevel\n                                               : entry.lastPS4State.ucBatteryLevel;',
     'const uint8_t raw = entry.lastPS4State.ucBatteryLevel;'),
    ('wired bit not detected',
     'if (raw & 0x10) {',
     'if (raw & 0x20) {'),
)


def main():
    if '--self-test' in sys.argv:
        # Prove the harness itself: each planted mutation is written to a
        # temporary copy of the harness code and must be caught, and the clean
        # harness must pass. The source tree is not touched.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for label_, old, new in MUTATIONS:
                (path / 'probe.m').write_text(harness.replace(old, new))
                ok_, _ = replay_probe(path)
                if ok_:
                    print('battery event self-test: NOT CAUGHT (%s)' % label_)
                    raise SystemExit(1)
                print('battery event self-test: caught %s' % label_)
            (path / 'probe.m').write_text(harness)
            ok_, _ = replay_probe(path)
            if not ok_:
                print('battery event self-test: clean harness FAILS')
                raise SystemExit(1)
            print('battery event self-test: clean harness passes')
        return

    ok, label = replay(harness)
    if not ok:
        print('battery event: current code FAILS (%s)' % label)
        raise SystemExit(1)
    print('battery event: current code passes (%s)' % label)

    for label_, old, new in MUTATIONS:
        m = harness.replace(old, new)
        assert m != harness, label_
        ok_, _ = replay(m, label=label_)
        if ok_:
            print('battery event: NOT CAUGHT (%s)' % label_)
            raise SystemExit(1)
        print('battery event: caught %s' % label_)


if __name__ == '__main__':
    main()
