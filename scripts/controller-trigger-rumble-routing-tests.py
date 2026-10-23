#!/usr/bin/env python3
"""Compile the shipping per-number trigger-rumble path; replay two Xbox pads.

The host names the pad by player index and asks its triggers to rumble. Before
this gate the macOS app never received the rumbleTriggers callback at all, so
no pad's triggers ever moved. This gate compiles the real
triggersRumbleForControllerNumber / rumbleDeviceForPlayerIndex /
writeTriggerRumbleToDevice / entryForDevice out of the tree and replays two
pads:

  * the index resolves to the pad that owns it, not the first device;
  * an unknown index falls back to the first device (documented single-pad);
  * the Xbox trigger write dedups per device and keeps its own state separate
    from the body-rumble motors, so a trigger and a body rumble in flight do
    not each treat the other's value as a repeat and drop a frame.

The device-classification and I/O edges are stubbed (a test cannot hold two
real controllers); everything between the index and the write is the code that
ships. Self-test plants the two regressions this gate exists to catch.
"""
from pathlib import Path
import subprocess
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


rumble_src = Path('Limelight/Input/HIDSupport+Rumble.m').read_text()
hid_src = Path('Limelight/Input/HIDSupport.m').read_text()
HELPERS = ['- (void)triggersRumbleForControllerNumber:',
           '- (IOHIDDeviceRef)rumbleDeviceForPlayerIndex:',
           '- (void)writeTriggerRumbleToDevice:']
methods = ('\n'.join(method(rumble_src, h) for h in HELPERS) + '\n' +
           method(hid_src, '- (HIDDeviceControllerEntry *)entryForDevice:'))

harness = r'''
#import <Foundation/Foundation.h>
typedef const void *IOHIDDeviceRef;
CFTypeRef CFRetain(CFTypeRef v) { return v; }
void CFRelease(CFTypeRef v) { (void)v; }

// ---- stubbed device classification / I/O edges ---------------------------
// Both registered pads classify as an Xbox, so the standard trigger write
// branch is the one under test and the dedup guard is the shipped one.
static int xboxSetReportCalls = 0;
static int lastLow = -1, lastHigh = -1;
static const unsigned char *lastPacket = NULL;
// Regressed shared trigger-dedup state, what a pre-per-device guard would use.
static uint8_t sharedLeft __attribute__((unused)) = 0xFF, sharedRight __attribute__((unused)) = 0xFF;
static BOOL isXbox(IOHIDDeviceRef device) { return device == (const void *)0x1 || device == (const void *)0x2; }
static BOOL isKingKong(IOHIDDeviceRef device) { return NO; }
static BOOL isPS4(IOHIDDeviceRef device) { return NO; }
static BOOL isPS5(IOHIDDeviceRef device) { return NO; }
static BOOL isNintendo(IOHIDDeviceRef device) __attribute__((unused));
static BOOL isNintendo(IOHIDDeviceRef device) { (void)device; return NO; }
typedef int IOReturn;
enum { kIOHIDReportTypeInput = 0, kIOHIDReportTypeOutput = 1, kIOHIDReportTypeFeature = 2 };
#ifndef kIOReturnSuccess
enum { kIOReturnSuccess = 0 };
#endif
static IOReturn IOHIDDeviceSetReport(IOHIDDeviceRef d, int type, int id, const void *data, int len) {
    lastPacket = (const unsigned char *)data;
    xboxSetReportCalls++;
    lastLow = lastPacket[4];
    lastHigh = lastPacket[5];
    return 0;
}
static IOReturn IOHIDDeviceGetReport(IOHIDDeviceRef d, int type, int id, void *data, CFIndex *len) __attribute__((unused));
static IOReturn IOHIDDeviceGetReport(IOHIDDeviceRef d, int type, int id, void *data, CFIndex *len) {
    *len = 7;
    return kIOReturnSuccess;
}
static CFTypeRef IOHIDDeviceGetProperty(IOHIDDeviceRef d, CFStringRef key) __attribute__((unused));
static CFTypeRef IOHIDDeviceGetProperty(IOHIDDeviceRef d, CFStringRef key) { return NULL; }
static UInt16 usbIdFromDevice(IOHIDDeviceRef device, NSString *key) __attribute__((unused));
static UInt16 usbIdFromDevice(IOHIDDeviceRef device, NSString *key) { return 0; }

typedef struct { double pressedAt; } MLGamepadMenuGesture;
static MLGamepadMenuGesture MLGamepadMenuGestureIdle(void) {
    return (MLGamepadMenuGesture){__builtin_nan("")};
}
// The arrival capability constants the entry stores at creation.
static const uint16_t LI_CCAP_ANALOG_TRIGGERS = 0x01;
static const uint16_t LI_CCAP_RUMBLE = 0x02;
static const uint16_t LI_CCAP_TRIGGER_RUMBLE = 0x04;
static const uint16_t LI_CCAP_RGB_LED = 0x80;
static const uint16_t LI_CCAP_ACCEL = 0x10;
static const uint16_t LI_CCAP_GYRO = 0x20;
static const uint16_t kHIDArrivalCapabilities = LI_CCAP_ANALOG_TRIGGERS | LI_CCAP_RUMBLE;
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
@end
@implementation HIDDeviceControllerEntry
@end
@interface HIDSupport : NSObject
@property(strong) NSMutableDictionary<NSString *, HIDDeviceControllerEntry *> *deviceControllerTable;
@property NSInteger controllerDriver;
@property BOOL isPS5Bluetooth;
- (IOHIDDeviceRef)getFirstDevice;
- (void)triggersRumbleForControllerNumber:(int)number leftTriggerMotor:(UInt16)leftTriggerMotor rightTriggerMotor:(UInt16)rightTriggerMotor;
- (void)writeTriggerRumbleToDevice:(IOHIDDeviceRef)device leftTriggerMotor:(UInt16)leftTriggerMotor rightTriggerMotor:(UInt16)rightTriggerMotor;
- (IOHIDDeviceRef)rumbleDeviceForPlayerIndex:(int)number;
- (HIDDeviceControllerEntry *)entryForDevice:(IOHIDDeviceRef)device;
@end
@implementation HIDSupport
- (NSString *)deviceKeyForDevice:(IOHIDDeviceRef)device {
    return device == NULL ? nil : [NSString stringWithFormat:@"hid:%p", (void *)device];
}
- (int)allocatePlayerSlot { return 0; }
- (uint8_t)protocolTypeForDevice:(IOHIDDeviceRef)d { return 1; }
- (uint32_t)supportedButtonFlagsForDevice:(IOHIDDeviceRef)d { return 0xffff; }
- (IOHIDDeviceRef)getFirstDevice { return (IOHIDDeviceRef)0x1; }
__METHODS__
@end

#define CHECK(x) do { if (!(x)) { NSLog(@"failed line %d", __LINE__); return 1; } } while (0)

int main(void) { @autoreleasepool {
    HIDSupport *s = [HIDSupport new];
    // Register two Xbox pads: index 0 is the first device on the bus (0x1),
    // index 1 a second, physically distinct pad.
    const void *pad0 = (const void *)0x1;
    const void *pad1 = (const void *)0x2;
    HIDDeviceControllerEntry *e0 = [s entryForDevice:pad0];
    e0.playerIndex = 0;
    HIDDeviceControllerEntry *e1 = [s entryForDevice:pad1];
    e1.playerIndex = 1;

    // A trigger rumble is only advertised for a pad with a trigger write.
    CHECK((e0.capabilities & 0x04) != 0);

    // Routing table, directly: index 1 resolves to pad1, index 0 to pad0,
    // an unknown index to the documented first-device fallback.
    CHECK([s rumbleDeviceForPlayerIndex:1] == pad1);
    CHECK([s rumbleDeviceForPlayerIndex:0] == pad0);
    CHECK([s rumbleDeviceForPlayerIndex:9] == (IOHIDDeviceRef)0x1);

    // A body rumble in flight must not collide with the trigger state.
    e0.previousLowFreqMotor = 0x10;
    e0.previousHighFreqMotor = 0x20;
    [s triggersRumbleForControllerNumber:0 leftTriggerMotor:1024 rightTriggerMotor:2048];
    CHECK(xboxSetReportCalls == 1);          // pad0 writes its first trigger value
    CHECK(lastLow == 1024 / 655 && lastHigh == 2048 / 655);

    // The neighbour must NOT be skipped by pad0's dedup state.
    [s triggersRumbleForControllerNumber:1 leftTriggerMotor:1024 rightTriggerMotor:2048];
    CHECK(xboxSetReportCalls == 2);          // pad1 writes the same value too

    // But each pad still suppresses its own repeat.
    [s triggersRumbleForControllerNumber:0 leftTriggerMotor:1024 rightTriggerMotor:2048];
    [s triggersRumbleForControllerNumber:1 leftTriggerMotor:1024 rightTriggerMotor:2048];
    CHECK(xboxSetReportCalls == 2);

    // A change on one pad reaches only that pad.
    [s triggersRumbleForControllerNumber:0 leftTriggerMotor:2048 rightTriggerMotor:1024];
    CHECK(xboxSetReportCalls == 3);
    CHECK(lastLow == 2048 / 655 && lastHigh == 1024 / 655);

    puts("trigger rumble routing replay passed");
    return 0;
}}
'''
harness = (harness
           .replace('__METHODS__', methods))


def replay(code, root='.', label='current'):
    cc, sdk = clang_and_sdk('trigger rumble routing replay')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        (path / 'probe.m').write_text(code)
        proc = subprocess.run(
            [cc, '-fobjc-arc', '-Wall', '-Werror', '-isysroot', sdk,
             '-framework', 'Foundation',
             str(path / 'probe.m'), '-o', str(path / 'probe')],
            capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stdout + proc.stderr)
            return False, 'build'
        ran = subprocess.run([str(path / 'probe')], capture_output=True, text=True)
        ok = ran.returncode == 0 and 'trigger rumble routing replay passed' in ran.stdout
        if not ok:
            print(ran.stdout, ran.stderr)
        return ok, label


def main():
    ok, label = replay(harness)
    if not ok:
        print('trigger rumble routing: current code FAILS (%s)' % label)
        raise SystemExit(1)
    print('trigger rumble routing: current code passes (%s)' % label)

    # Mutation 1: routing ignores the index and always sends to the first
    # device -- pad1's trigger rumble lands on pad0, so pad1 never writes.
    m1 = harness.replace(
        'if (entry.playerIndex == number) {\n            return entry.hidDevice;\n        }',
        'if (entry.playerIndex == 0) {\n            return entry.hidDevice;\n        }')
    assert m1 != harness
    ok1, _ = replay(m1, label='index ignored')
    if ok1:
        print('trigger rumble routing: NOT CAUGHT (index ignored)')
        raise SystemExit(1)
    print('trigger rumble routing: caught index-ignored routing')

    # Mutation 2: the dedup guard is shared again -- the neighbour is skipped.
    m2 = harness.replace('entry.previousLeftTriggerMotor', 'sharedLeft') \
                .replace('entry.previousRightTriggerMotor', 'sharedRight')
    assert m2 != harness
    ok2, _ = replay(m2, label='shared dedup')
    if ok2:
        print('trigger rumble routing: NOT CAUGHT (shared dedup)')
        raise SystemExit(1)
    print('trigger rumble routing: caught shared dedup state')


if __name__ == '__main__':
    main()
