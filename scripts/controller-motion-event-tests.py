#!/usr/bin/env python3
"""Compile the shipping setMotionEventState motion path; replay two PS4 pads.

The host names the pad by player index and asks it to stream one sensor
type at a rate in Hz (or to stop it). Before this gate the macOS app never
received the setMotionEventState callback at all, so even a PS4 whose
state packets already carry six-axis bytes never sent a single sensor
sample to the host.

This gate compiles the real setMotionEventStateForControllerNumber /
pushMotionEventsForEntry / sendMotionSampleToHostForEntry /
stopMotionEventsForEntry / entryForDevice out of the tree and replays two
PS4 pads plus one PS5 and one Xbox:

  * the index resolves to the pad that owns it; an unknown index falls back
    to the first device;
  * only a pad whose state packets carry six-axis samples (PS4/PS5) gets an
    activation, and only that family's capability bits are advertised;
  * the raw-to-protocol conversion is the SDL HIDAPI PS4/PS5 scale (PS4
    16 counts per deg/s and 8192 per g, PS5 1024 per deg/s);
  * the host's Hz request becomes a minimum send interval, the same type in
    the same window is coalesced, and the two types pace independently;
  * an inactive type sends nothing, stream gating and the driver switch do,
    and an explicit stop clears the pad.

Self-test plants the six regressions this gate exists to catch.
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
HELPERS = ['- (void)setMotionEventStateForControllerNumber:',
           '- (void)pushMotionEventsForEntry:',
           '- (void)sendMotionSampleToHostForEntry:',
           '- (void)stopMotionEventsForEntry:']
methods = '\n'.join(method(hid_src, h) for h in HELPERS) + '\n' + \
          method(hid_src, '- (HIDDeviceControllerEntry *)entryForDevice:')

harness = r'''
#import <Foundation/Foundation.h>
typedef const void *IOHIDDeviceRef;
typedef struct { PS4_PLACEHOLDER } PS4StatePacket_t;
typedef struct { PS5_PLACEHOLDER } PS5StatePacket_t;
CFTypeRef CFRetain(CFTypeRef v) { return v; }
void CFRelease(CFTypeRef v) { (void)v; }

// ---- stubbed bus / I/O edges --------------------------------------------
// pad0 and pad1 classify as PS4, pad2 as PS5, pad3 as Xbox: the shipped
// capability decision and the family-dependent scale are both exercised.
static const void *PAD0 = (const void *)0x1;
static const void *PAD1 = (const void *)0x2;
static const void *PAD2 = (const void *)0x3;
static const void *PAD3 = (const void *)0x4;
static BOOL isPS4(IOHIDDeviceRef device) { return device == PAD0 || device == PAD1; }
static BOOL isPS5(IOHIDDeviceRef device) { return device == PAD2; }
static BOOL isXbox(IOHIDDeviceRef device) __attribute__((unused));
static BOOL isXbox(IOHIDDeviceRef device) { (void)device; return NO; }
static BOOL isKingKong(IOHIDDeviceRef device) __attribute__((unused));
static BOOL isKingKong(IOHIDDeviceRef device) { (void)device; return NO; }
static CFTypeRef IOHIDDeviceGetProperty(IOHIDDeviceRef d, CFStringRef key) __attribute__((unused));
static CFTypeRef IOHIDDeviceGetProperty(IOHIDDeviceRef d, CFStringRef key) { return NULL; }
static UInt16 usbIdFromDevice(IOHIDDeviceRef device, NSString *key) __attribute__((unused));
static UInt16 usbIdFromDevice(IOHIDDeviceRef device, NSString *key) { return 0; }
static IOReturn IOHIDDeviceSetReport(IOHIDDeviceRef d, int type, int id, const void *data, int len) __attribute__((unused));
static IOReturn IOHIDDeviceSetReport(IOHIDDeviceRef d, int type, int id, const void *data, int len) {
    (void)d; (void)type; (void)id; (void)data; (void)len; return 0;
}
static IOReturn IOHIDDeviceGetReport(IOHIDDeviceRef d, int type, int id, void *data, CFIndex *len) __attribute__((unused));
static IOReturn IOHIDDeviceGetReport(IOHIDDeviceRef d, int type, int id, void *data, CFIndex *len) {
    *len = 7; return 0;
}
typedef struct { double pressedAt; } MLGamepadMenuGesture;
static MLGamepadMenuGesture MLGamepadMenuGestureIdle(void) {
    return (MLGamepadMenuGesture){__builtin_nan("")};
}
// The real Limelight.h is too heavy for this replay; the values are the
// protocol constants the entry stores at creation and the types it tests.
static const uint16_t LI_CCAP_ANALOG_TRIGGERS = 0x01;
static const uint16_t LI_CCAP_RUMBLE = 0x02;
static const uint16_t LI_CCAP_TRIGGER_RUMBLE = 0x04;
static const uint16_t LI_CCAP_RGB_LED = 0x80;
static const uint16_t LI_CCAP_ACCEL = 0x10;
static const uint16_t LI_CCAP_GYRO = 0x20;
static const uint16_t LI_CCAP_BATTERY_STATE = 0x40;
static const uint16_t LI_CCAP_TOUCHPAD = 0x08;
static const uint8_t LI_MOTION_TYPE_ACCEL = 0x01;
static const uint8_t LI_MOTION_TYPE_GYRO = 0x02;
static const uint16_t kHIDArrivalCapabilities = LI_CCAP_ANALOG_TRIGGERS | LI_CCAP_RUMBLE;
typedef int *PML_INPUT_STREAM_CONTEXT;
typedef struct { PML_INPUT_STREAM_CONTEXT context; uint64_t generation; } HIDInputLease;
@class HIDSupport;
static int g_ctx;
static HIDInputLease HIDAcquireInputContext(HIDSupport *s) {
    (void)s; return (HIDInputLease){&g_ctx, 1};
}
typedef struct {
    uint8_t type; float x, y, z; PML_INPUT_STREAM_CONTEXT ctx;
} MotionCall;
@interface MCall : NSObject
@property uint8_t type;
@property float x, y, z;
@property PML_INPUT_STREAM_CONTEXT ctx;
@end
@implementation MCall
@end
static NSMutableArray *g_motion;
static void LiSendControllerMotionEventCtx(PML_INPUT_STREAM_CONTEXT ctx, uint8_t slot,
                                           uint8_t type, float x, float y, float z) {
    MCall *c = [MCall new];
    c.type = type; c.x = x; c.y = y; c.z = z; c.ctx = ctx;
    [g_motion addObject:c];
    (void)slot;
}
static void HIDDispatchInput(HIDSupport *s, HIDInputLease lease, dispatch_block_t job) {
    (void)s; (void)lease; job();
}
@interface Controller : NSObject
@property int lastButtonFlags;
@property MLGamepadMenuGesture menuGesture;
@end
@implementation Controller
@end
@interface HIDDeviceControllerEntry : NSObject
@property(strong) Controller *controller;
@property IOHIDDeviceRef hidDevice;
@property int playerIndex;
@property uint8_t protocolType;
@property uint32_t supportedButtonFlags;
@property uint16_t capabilities;
@property uint8_t previousLowFreqMotor;
@property uint8_t previousHighFreqMotor;
@property uint8_t previousLEDRed;
@property uint8_t previousLEDGreen;
@property uint8_t previousLEDBlue;
@property uint8_t previousLeftTriggerMotor;
@property uint8_t previousRightTriggerMotor;
@property uint8_t motionActiveTypes;
@property uint16_t motionAccelIntervalMs;
@property uint16_t motionGyroIntervalMs;
@property uint64_t lastMotionAccelAtMs;
@property uint64_t lastMotionGyroAtMs;
@property PS4StatePacket_t lastPS4State;
@property PS5StatePacket_t lastPS5State;
@property BOOL touchPressed;
@property BOOL touchPressed2;
@property uint32_t touchPointerId;
@property float touchLastX, touchLastY;
@property uint32_t touchPointerId2;
@property float touchLastX2, touchLastY2;
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

static PS4StatePacket_t ps4Packet(int16_t gx, int16_t gy, int16_t gz,
                                  int16_t ax, int16_t ay, int16_t az) {
    PS4StatePacket_t p;
    memset(&p, 0, sizeof(p));
    p.rgucGyroX[0] = gx & 0xFF;  p.rgucGyroX[1] = (gx >> 8) & 0xFF;
    p.rgucGyroY[0] = gy & 0xFF;  p.rgucGyroY[1] = (gy >> 8) & 0xFF;
    p.rgucGyroZ[0] = gz & 0xFF;  p.rgucGyroZ[1] = (gz >> 8) & 0xFF;
    p.rgucAccelX[0] = ax & 0xFF; p.rgucAccelX[1] = (ax >> 8) & 0xFF;
    p.rgucAccelY[0] = ay & 0xFF; p.rgucAccelY[1] = (ay >> 8) & 0xFF;
    p.rgucAccelZ[0] = az & 0xFF; p.rgucAccelZ[1] = (az >> 8) & 0xFF;
    return p;
}
static PS5StatePacket_t ps5Packet(int16_t gx, int16_t gy, int16_t gz,
                                   int16_t ax, int16_t ay, int16_t az) {
    PS5StatePacket_t p;
    memset(&p, 0, sizeof(p));
    p.rgucGyroX[0] = gx & 0xFF;  p.rgucGyroX[1] = (gx >> 8) & 0xFF;
    p.rgucGyroY[0] = gy & 0xFF;  p.rgucGyroY[1] = (gy >> 8) & 0xFF;
    p.rgucGyroZ[0] = gz & 0xFF;  p.rgucGyroZ[1] = (gz >> 8) & 0xFF;
    p.rgucAccelX[0] = ax & 0xFF; p.rgucAccelX[1] = (ax >> 8) & 0xFF;
    p.rgucAccelY[0] = ay & 0xFF; p.rgucAccelY[1] = (ay >> 8) & 0xFF;
    p.rgucAccelZ[0] = az & 0xFF; p.rgucAccelZ[1] = (az >> 8) & 0xFF;
    return p;
}
static MCall *call_(NSMutableArray *arr, int i) {
    return (MCall *)arr[i];
}
#define CHECK(x) do { if (!(x)) { NSLog(@"failed line %d", __LINE__); return 1; } } while (0)

int main(void) { @autoreleasepool {
    g_motion = [NSMutableArray new];
    HIDSupport *s = [HIDSupport new];
    s.shouldSendInputEvents = YES;

    // Four pads: two PS4 (indices 0/1), one PS5 (2), one Xbox (3). The
    // shipped capability decision runs from entryForDevice: against them.
    HIDDeviceControllerEntry *e0 = [s entryForDevice:PAD0]; e0.playerIndex = 0;
    HIDDeviceControllerEntry *e1 = [s entryForDevice:PAD1]; e1.playerIndex = 1;
    HIDDeviceControllerEntry *e2 = [s entryForDevice:PAD2]; e2.playerIndex = 2;
    HIDDeviceControllerEntry *e3 = [s entryForDevice:PAD3]; e3.playerIndex = 3;
    CHECK((e0.capabilities & (LI_CCAP_ACCEL | LI_CCAP_GYRO)) == (LI_CCAP_ACCEL | LI_CCAP_GYRO));
    CHECK((e2.capabilities & (LI_CCAP_ACCEL | LI_CCAP_GYRO)) == (LI_CCAP_ACCEL | LI_CCAP_GYRO));
    CHECK((e3.capabilities & (LI_CCAP_ACCEL | LI_CCAP_GYRO)) == 0);

    // Routing: the index resolves to the owning pad, the unknown index to the
    // first device fallback. Activation only sticks on a PS family pad.
    [s setMotionEventStateForControllerNumber:1 motionType:LI_MOTION_TYPE_GYRO reportRateHz:100];
    CHECK(e1.motionActiveTypes == LI_MOTION_TYPE_GYRO);
    CHECK(e0.motionActiveTypes == 0);
    CHECK(e1.motionGyroIntervalMs == 10);
    [s setMotionEventStateForControllerNumber:9 motionType:LI_MOTION_TYPE_ACCEL reportRateHz:100];
    CHECK(e0.motionActiveTypes == LI_MOTION_TYPE_ACCEL);
    CHECK(e1.motionActiveTypes == LI_MOTION_TYPE_GYRO);
    [s setMotionEventStateForControllerNumber:3 motionType:LI_MOTION_TYPE_GYRO reportRateHz:100];
    CHECK(e3.motionActiveTypes == 0);
    CHECK(e2.motionActiveTypes == 0);
    // An explicit stop clears only that type, on the pad it was set on.
    [s setMotionEventStateForControllerNumber:1 motionType:LI_MOTION_TYPE_GYRO reportRateHz:0];
    CHECK(e1.motionActiveTypes == 0);
    CHECK(e0.motionActiveTypes == LI_MOTION_TYPE_ACCEL);

    // Conversion, PS4 scale: 100 deg/s -> 1600 raw, 1 g -> 8192 raw. The
    // push reads the family's own snapshot and sends through the C layer.
    // The routing section left an ACCEL request on e0, so clear it first.
    [s stopMotionEventsForEntry:e0];
    [s setMotionEventStateForControllerNumber:0 motionType:LI_MOTION_TYPE_GYRO reportRateHz:1000];
    e0.lastPS4State = ps4Packet(1600, -1600, 3200, 8192, -8192, 0);
    [s pushMotionEventsForEntry:e0];
    CHECK(g_motion.count == 1);
    MCall *c = call_(g_motion, 0);
    CHECK(c.type == LI_MOTION_TYPE_GYRO);
    CHECK(c.x == 100.0f && c.y == -100.0f && c.z == 200.0f);
    CHECK(c.ctx == &g_ctx);
    // Accelerometer conversion, 1 g on X only: m/s^2 with gravity. Both
    // types are active now, so one push offers every requested sensor,
    // accelerometer first, gyro second. Stamps reset so the rate guard
    // cannot swallow the gyro frame of the first push in the same millisecond.
    [s setMotionEventStateForControllerNumber:0 motionType:LI_MOTION_TYPE_ACCEL reportRateHz:1000];
    e0.lastPS4State = ps4Packet(0, 0, 0, 8192, 0, 0);
    e0.lastMotionAccelAtMs = 0; e0.lastMotionGyroAtMs = 0;
    [s pushMotionEventsForEntry:e0];
    CHECK(g_motion.count == 3);
    c = call_(g_motion, 1);
    CHECK(c.type == LI_MOTION_TYPE_ACCEL);
    CHECK(fabsf(c.x - 9.80665f) < 0.0005f && c.y == 0.0f && c.z == 0.0f);
    c = call_(g_motion, 2);
    CHECK(c.type == LI_MOTION_TYPE_GYRO);
    // Both types active: a fresh sample still rides both sensors in order.
    e0.lastMotionAccelAtMs = 0; e0.lastMotionGyroAtMs = 0;
    [s pushMotionEventsForEntry:e0];
    CHECK(g_motion.count == 5);
    c = call_(g_motion, 3);
    CHECK(c.type == LI_MOTION_TYPE_ACCEL);
    c = call_(g_motion, 4);
    CHECK(c.type == LI_MOTION_TYPE_GYRO);

    // Rate: 100 Hz is a 10 ms minimum interval. The push reads the clock
    // itself, so the harness paces via recorded stamps relative to the same
    // clock: a stamp from this instant is inside the interval, one from 20
    // ms ago is not.
    [g_motion removeAllObjects];
    e0.lastMotionAccelAtMs = 0; e0.lastMotionGyroAtMs = 0;
    [s stopMotionEventsForEntry:e0];
    [s setMotionEventStateForControllerNumber:0 motionType:LI_MOTION_TYPE_ACCEL reportRateHz:100];
    e0.lastPS4State = ps4Packet(0, 0, 0, 4096, 0, 0);
    uint64_t nowMs = (uint64_t)([[NSDate date] timeIntervalSince1970] * 1000.0);
    e0.lastMotionAccelAtMs = nowMs;
    [s pushMotionEventsForEntry:e0];
    CHECK(g_motion.count == 0);          // stamp is this instant: inside 10 ms
    e0.lastMotionAccelAtMs = nowMs - 20;
    [s pushMotionEventsForEntry:e0];
    CHECK(g_motion.count == 1);          // 20 ms old: passes the interval
    CHECK(fabsf(call_(g_motion, 0).x - 4.903325f) < 0.002f);

    // The two types pace independently: a fresh gyro frame is not blocked by
    // the accelerometer's just-sent stamp.
    e1.lastPS4State = ps4Packet(160, 0, 0, 0, 0, 0);
    [s setMotionEventStateForControllerNumber:1 motionType:LI_MOTION_TYPE_GYRO reportRateHz:1000];
    [s setMotionEventStateForControllerNumber:1 motionType:LI_MOTION_TYPE_ACCEL reportRateHz:1000];
    e1.lastMotionAccelAtMs = (uint64_t)([[NSDate date] timeIntervalSince1970] * 1000.0);
    e1.lastMotionGyroAtMs = 0;           // gyro never sent
    [s pushMotionEventsForEntry:e1];
    CHECK(g_motion.count == 2);          // only the gyro went out
    CHECK(call_(g_motion, 1).type == LI_MOTION_TYPE_GYRO);

    // Independent pacing across types: the gyro runs 200 Hz (5 ms) while the
    // accelerometer runs 10 Hz (100 ms). A sample 20 ms later clears the
    // gyro interval and must still be inside the accelerometer's, so the
    // push carries the gyro frame and only the gyro frame.
    [g_motion removeAllObjects];
    [s stopMotionEventsForEntry:e0];
    [s setMotionEventStateForControllerNumber:0 motionType:LI_MOTION_TYPE_GYRO reportRateHz:200];
    [s setMotionEventStateForControllerNumber:0 motionType:LI_MOTION_TYPE_ACCEL reportRateHz:10];
    e0.lastPS4State = ps4Packet(160, 0, 0, 0, 0, 0);
    e0.lastMotionAccelAtMs = 0; e0.lastMotionGyroAtMs = 0;
    [s pushMotionEventsForEntry:e0];
    CHECK(g_motion.count == 2);
    c = call_(g_motion, 1);
    CHECK(c.type == LI_MOTION_TYPE_GYRO);
    e0.lastMotionAccelAtMs = nowMs;            // accel sent this instant
    e0.lastMotionGyroAtMs = nowMs - 20;        // gyro frame from 20 ms ago
    [s pushMotionEventsForEntry:e0];
    CHECK(g_motion.count == 3);                // gyro 20 > 5 ms: out
    c = call_(g_motion, 2);
    CHECK(c.type == LI_MOTION_TYPE_GYRO);      // and only the gyro

    // PS5 family reads its own snapshot at the PS5 scale (1024 per deg/s).
    [g_motion removeAllObjects];
    e2.lastPS5State = ps5Packet(1024, 0, 0, 0, 0, 0);   // own snapshot
    e2.lastPS4State = ps4Packet(1600, 0, 0, 0, 0, 0);   // must NOT be read
    [s setMotionEventStateForControllerNumber:2 motionType:LI_MOTION_TYPE_GYRO reportRateHz:1000];
    [s pushMotionEventsForEntry:e2];
    CHECK(g_motion.count == 1);
    CHECK(fabsf(call_(g_motion, 0).x - 1.0f) < 0.0001f);

    // Gates: an inactive type sends nothing, the driver switch and the
    // input-forwarding gate do too, and a stream-end stop clears the pad.
    [g_motion removeAllObjects];
    [s setMotionEventStateForControllerNumber:1 motionType:LI_MOTION_TYPE_ACCEL reportRateHz:0];
    [s pushMotionEventsForEntry:e1];
    CHECK(g_motion.count == 0);
    s.shouldSendInputEvents = NO;
    [s pushMotionEventsForEntry:e1];
    CHECK(g_motion.count == 0);
    s.shouldSendInputEvents = YES;
    s.controllerDriver = 1;
    [s pushMotionEventsForEntry:e1];
    CHECK(g_motion.count == 0);
    s.controllerDriver = 0;
    [s stopMotionEventsForEntry:e1];
    CHECK(e1.motionActiveTypes == 0 && e1.motionAccelIntervalMs == 0 && e1.motionGyroIntervalMs == 0);
    puts("motion event replay passed");
    return 0;
}}
'''

PS4_FIELDS = '''UInt8 ucLeftJoystickX; UInt8 ucLeftJoystickY; UInt8 ucRightJoystickX; UInt8 ucRightJoystickY;
    UInt8 rgucButtonsHatAndCounter[3]; UInt8 ucTriggerLeft; UInt8 ucTriggerRight;
    UInt8 _rgucPad0[3];
    UInt8 rgucGyroX[2]; UInt8 rgucGyroY[2]; UInt8 rgucGyroZ[2];
    UInt8 rgucAccelX[2]; UInt8 rgucAccelY[2]; UInt8 rgucAccelZ[2];
    UInt8 _rgucPad1[5]; UInt8 ucBatteryLevel; UInt8 _rgucPad2[4];
    UInt8 ucTouchpadCounter1; UInt8 rgucTouchpadData1[3];
    UInt8 ucTouchpadCounter2; UInt8 rgucTouchpadData2[3];'''
PS5_FIELDS = '''UInt8 ucLeftJoystickX; UInt8 ucLeftJoystickY; UInt8 ucRightJoystickX; UInt8 ucRightJoystickY;
    UInt8 ucTriggerLeft; UInt8 ucTriggerRight; UInt8 ucCounter; UInt8 rgucButtonsAndHat[3];
    UInt8 ucZero; UInt8 rgucPacketSequence[4];
    UInt8 rgucGyroX[2]; UInt8 rgucGyroY[2]; UInt8 rgucGyroZ[2];
    UInt8 rgucAccelX[2]; UInt8 rgucAccelY[2]; UInt8 rgucAccelZ[2];
    UInt8 rgucTimer1[4]; UInt8 ucBatteryTemp;
    UInt8 ucTouchpadCounter1; UInt8 rgucTouchpadData1[3];
    UInt8 ucTouchpadCounter2; UInt8 rgucTouchpadData2[3];
    UInt8 rgucUnknown1[8]; UInt8 rgucTimer2[4];
    UInt8 ucBatteryLevel; UInt8 ucConnectState;'''

harness = (harness.replace('PS4_PLACEHOLDER', PS4_FIELDS)
                    .replace('PS5_PLACEHOLDER', PS5_FIELDS)
                    .replace('__METHODS__', methods))


def replay_probe(path):
    cc, sdk = clang_and_sdk('motion event replay')
    proc = subprocess.run(
        [cc, '-fobjc-arc', '-fblocks', '-Wall', '-Werror', '-isysroot', sdk,
         '-framework', 'Foundation',
         str(path / 'probe.m'), '-o', str(path / 'probe')],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout + proc.stderr)
        return False, 'build'
    ran = subprocess.run([str(path / 'probe')], capture_output=True, text=True)
    ok = ran.returncode == 0 and 'motion event replay passed' in ran.stdout
    if not ok:
        print(ran.stdout, ran.stderr)
    return ok, None


def replay(code, label='current'):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        (path / 'probe.m').write_text(code)
        ok, _ = replay_probe(path)
        return ok, label


# The six regressions this gate exists to catch. --self-test replants each one
# into a temporary copy of the harness and requires it to be caught, which is
# what proves the harness would notice; the normal run replants the same list
# on the shipping source instead.
MUTATIONS = (
    ('index ignored in routing',
     'if (candidate.playerIndex == number) {\n            entry = candidate;',
     'if (candidate.playerIndex == 0) {\n            entry = candidate;'),
    ('activation not limited to PS family',
     'if (!isPS4(entry.hidDevice) && !isPS5(entry.hidDevice)) {\n        return;\n    }',
     'if (NO) {\n        return;\n    }'),
    ('PS4 gyro scale drift',
     'const float gyroDiv = isPS5(entry.hidDevice) ? 1024.0f : 16.0f;',
     'const float gyroDiv = isPS5(entry.hidDevice) ? 1024.0f : 160.0f;'),
    ('rate limit removed',
     'if (stamp != 0 && nowMs - stamp < interval) {\n        return;\n    }',
     '(void)stamp;\n    if (NO) {\n        return;\n    }'),
    ('shared pacing across types',
     'uint16_t interval = isGyro ? entry.motionGyroIntervalMs : entry.motionAccelIntervalMs;',
     'uint16_t interval = entry.motionAccelIntervalMs;'),
    ('inactive type still sends',
     'if ((types & type) == 0) {\n            continue;\n        }',
     'if ((types | type) == 0) {\n            continue;\n        }'),
)


def main():
    if '--self-test' in sys.argv:
        # Self-test against the harness code itself: every planted mutation
        # must fail and the clean harness must pass. The source tree is not
        # touched, so this mode is cheap enough to run in the gate sequence.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for label_, old, new in MUTATIONS:
                (path / 'probe.m').write_text(harness.replace(old, new))
                ok_, _ = replay_probe(path)
                if ok_:
                    print('motion event self-test: NOT CAUGHT (%s)' % label_)
                    raise SystemExit(1)
                print('motion event self-test: caught %s' % label_)
            (path / 'probe.m').write_text(harness)
            ok_, _ = replay_probe(path)
            if not ok_:
                print('motion event self-test: clean harness FAILS')
                raise SystemExit(1)
            print('motion event self-test: clean harness passes')
        return

    ok, label = replay(harness)
    if not ok:
        print('motion event: current code FAILS (%s)' % label)
        raise SystemExit(1)
    print('motion event: current code passes (%s)' % label)

    for label_, old, new in MUTATIONS:
        m = harness.replace(old, new)
        assert m != harness, label_
        ok_, _ = replay(m, label=label_)
        if ok_:
            print('motion event: NOT CAUGHT (%s)' % label_)
            raise SystemExit(1)
        print('motion event: caught %s' % label_)


if __name__ == '__main__':
    main()
