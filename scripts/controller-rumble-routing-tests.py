#!/usr/bin/env python3
"""Compile the shipping per-number rumble path; replay two pads, one motor.

The host names the pad by player index. Before this gate the HID write path
ignored that index and sent to whichever device the bus listed first, with a
single shared dedup guard -- the second pad's rumble either landed on the
first pad or was swallowed by the neighbour's last value. The gate compiles
the real rumbleForControllerNumber / rumbleDeviceForPlayerIndex /
writeRumbleToDevice / entryForDevice out of the tree and replays:

  * the index resolves to the pad that owns it, not the first device;
  * an unknown index falls back to the first device (documented single-pad);
  * the Xbox wire write dedups per device, so two pads both write their
    first value and each still suppresses its own repeat.

The device-classification and I/O edges are stubbed (a test cannot hold two
real controllers); everything between the index and the write is the code
that ships. Self-test plants the two regressions this gate exists to catch.
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
TYPES = Path('Limelight/Input/HIDSupportRumbleTypes.h').read_text()
CRC = '\n'.join(method(rumble_src, name) for name in
                 ('static UInt32 crc32_for_byte', 'static UInt32 SDL_crc32'))
SWITCH_PACKET = 'SwitchCommonOutputPacket_t switchRumblePacket;'
TICKS = '''#define TICKS_PASSED(A, B) ((int32_t)((B) - (A)) <= 0)\n@interface Ticks : NSObject\n- (UInt32)getTicks;\n@end\n@implementation Ticks\n- (UInt32)getTicks { return 0; }\n@end'''
HELPERS = ['- (void)rumbleForControllerNumber:',
           '- (IOHIDDeviceRef)rumbleDeviceForPlayerIndex:',
           '- (void)writeRumbleToDevice:',
           '- (int)hidGetFeatureReport:',
           '- (int)switch_RumbleJoystick:',
           '- (int)switchSendPendingRumble:',
           '- (int)switchActuallyRumbleJoystick:',
           '- (void)setNeutralRumble:',
           '- (void)switchEncodeRumble:',
           '- (BOOL)writeRumble:',
           '- (BOOL)writePacket:']
methods = ('\n'.join(method(rumble_src, h) for h in HELPERS) + '\n' +
           method(hid_src, '- (HIDDeviceControllerEntry *)entryForDevice:'))

harness = r'''
#import <Foundation/Foundation.h>
typedef const void *IOHIDDeviceRef;
CFTypeRef CFRetain(CFTypeRef v) { return v; }
void CFRelease(CFTypeRef v) { (void)v; }
__TYPES__
__TICKS__
__CRC__
__SWITCH_PACKET__

// ---- stubbed device classification / I/O edges ---------------------------
// The first device in the harness is classified as an Xbox pad; any other
// pointer classifies as nothing, so exactly the Xbox write branch runs and
// the dedup guard under test is the shipped one.
static int xboxSetReportCalls = 0;
static int lastXboxLow = -1, lastXboxHigh = -1;
// Regressed shared dedup state, what the pre-fix code used for every pad.
static uint8_t sharedLow __attribute__((unused)) = 0xFF, sharedHigh __attribute__((unused)) = 0xFF;
static BOOL isXbox(IOHIDDeviceRef device) { return device == (const void *)0x1 || device == (const void *)0x2; }
static BOOL isKingKong(IOHIDDeviceRef device) { return NO; }
static BOOL isPS4(IOHIDDeviceRef device) { return NO; }
static BOOL isPS5(IOHIDDeviceRef device) { return NO; }
static const uint16_t LI_CCAP_ANALOG_TRIGGERS = 0x01;
static const uint16_t LI_CCAP_RUMBLE = 0x02;
static const uint16_t LI_CCAP_TRIGGER_RUMBLE = 0x04;
static const uint16_t LI_CCAP_RGB_LED = 0x80;
static const uint16_t LI_CCAP_ACCEL = 0x10;
static const uint16_t LI_CCAP_GYRO = 0x20;
static const uint16_t LI_CCAP_BATTERY_STATE = 0x40;
static const uint16_t kHIDArrivalCapabilities = LI_CCAP_ANALOG_TRIGGERS | LI_CCAP_RUMBLE;
static BOOL isNintendo(IOHIDDeviceRef device) { return NO; }
typedef int IOReturn;
enum { kIOHIDReportTypeInput = 0, kIOHIDReportTypeOutput = 1, kIOHIDReportTypeFeature = 2 };
#ifndef kIOReturnSuccess
enum { kIOReturnSuccess = 0 };
#endif
static IOReturn IOHIDDeviceSetReport(IOHIDDeviceRef d, int type, int id, const void *data, int len) {
    const unsigned char *p = (const unsigned char *)data;
    xboxSetReportCalls++;
    lastXboxLow = p[4];
    lastXboxHigh = p[5];
    return 0;
}
static IOReturn IOHIDDeviceGetReport(IOHIDDeviceRef d, int type, int id, void *data, CFIndex *len) {
    // No real PS4 present: a short read forces the Bluetooth report layout.
    *len = 4;
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
@property(strong) Ticks *ticks;
@property BOOL isPS5Bluetooth;
@property(atomic) dispatch_semaphore_t rumbleSemaphore;
@property UInt8 switchCommandNumber;
@property BOOL isRumbleTimer;
@property BOOL switchRumbleActive;
@property UInt32 switchUnRumbleSent;
@property BOOL switchRumblePending;
@property BOOL switchRumbleZeroPending;
@property UInt32 switchUnRumblePending;
@property BOOL switchUsingBluetooth;
@property(atomic) dispatch_semaphore_t hidReadSemaphore;
@property BOOL vibrationEnableResponded;
@property BOOL waitingForVibrationEnable;
@property UInt32 startedWaitingForVibrationEnable;
- (IOHIDDeviceRef)getFirstDevice;
- (void)rumbleForControllerNumber:(int)number lowFreqMotor:(UInt16)lowFreqMotor highFreqMotor:(UInt16)highFreqMotor;
- (IOHIDDeviceRef)rumbleDeviceForPlayerIndex:(int)number;
- (void)writeRumbleToDevice:(IOHIDDeviceRef)device lowFreqMotor:(UInt16)lowFreqMotor highFreqMotor:(UInt16)highFreqMotor;
- (HIDDeviceControllerEntry *)entryForDevice:(IOHIDDeviceRef)device;
- (int)hidGetFeatureReport:(IOHIDDeviceRef)device data:(unsigned char *)data length:(size_t)length;
- (int)switch_RumbleJoystick:(IOHIDDeviceRef)device lowFreqMotor:(UInt16)lowFreqMotor highFreqMotor:(UInt16)highFreqMotor;
- (int)switchSendPendingRumble:(IOHIDDeviceRef)device;
- (int)switchActuallyRumbleJoystick:(IOHIDDeviceRef)device low_frequency_rumble:(UInt16)low high_frequency_rumble:(UInt16)high;
- (void)setNeutralRumble:(SwitchRumbleData_t *)pRumble;
- (void)switchEncodeRumble:(SwitchRumbleData_t *)pRumble usHighFreq:(UInt16)usHighFreq ucHighFreqAmp:(UInt8)ucHighFreqAmp ucLowFreq:(UInt8)ucLowFreq usLowFreqAmp:(UInt16)usLowFreqAmp;
- (BOOL)writeRumble:(IOHIDDeviceRef)device;
- (BOOL)writePacket:(IOHIDDeviceRef)device pBuf:(void *)pBuf ucLen:(UInt8)ucLen;
@end
@implementation HIDSupport
- (uint8_t)protocolTypeForDevice:(IOHIDDeviceRef)d { return 1; }
- (uint32_t)supportedButtonFlagsForDevice:(IOHIDDeviceRef)d { return 0xffff; }
- (NSString *)deviceKeyForDevice:(IOHIDDeviceRef)device {
    return device == NULL ? nil : [NSString stringWithFormat:@"hid:%p", (void *)device];
}
- (int)allocatePlayerSlot { return 0; }
- (IOHIDDeviceRef)getFirstDevice { return (IOHIDDeviceRef)0x1; }
__METHODS__
@end

#define CHECK(x) do { if (!(x)) { NSLog(@"failed line %d", __LINE__); return 1; } } while (0)

int main(void) { @autoreleasepool {
    HIDSupport *s = [HIDSupport new];
    s.ticks = [Ticks new];
    // Register two pads: index 0 is the device the bus lists first (0x1,
    // classified as an Xbox), index 1 is a second, physically distinct pad.
    const void *pad0 = (const void *)0x1;
    const void *pad1 = (const void *)0x2;
    HIDDeviceControllerEntry *e0 = [s entryForDevice:pad0];
    e0.playerIndex = 0;
    HIDDeviceControllerEntry *e1 = [s entryForDevice:pad1];
    e1.playerIndex = 1;

    // Routing table, directly: index 1 resolves to pad1, index 0 to pad0,
    // an unknown index to the documented first-device fallback.
    CHECK([s rumbleDeviceForPlayerIndex:1] == pad1);
    CHECK([s rumbleDeviceForPlayerIndex:0] == pad0);
    CHECK([s rumbleDeviceForPlayerIndex:9] == (IOHIDDeviceRef)0x1);

    [s rumbleForControllerNumber:0 lowFreqMotor:1024 highFreqMotor:2048];
    CHECK(xboxSetReportCalls == 1);          // pad0 writes its first value
    CHECK(lastXboxLow == 1024 / 655 && lastXboxHigh == 2048 / 655);

    // The neighbour must NOT be skipped by pad0's dedup state.
    [s rumbleForControllerNumber:1 lowFreqMotor:1024 highFreqMotor:2048];
    CHECK(xboxSetReportCalls == 2);          // pad1 writes the same value too

    // But each pad still suppresses its own repeat.
    [s rumbleForControllerNumber:0 lowFreqMotor:1024 highFreqMotor:2048];
    [s rumbleForControllerNumber:1 lowFreqMotor:1024 highFreqMotor:2048];
    CHECK(xboxSetReportCalls == 2);

    // A change on one pad reaches only that pad.
    [s rumbleForControllerNumber:0 lowFreqMotor:2048 highFreqMotor:1024];
    CHECK(xboxSetReportCalls == 3);

    puts("rumble routing replay passed");
    return 0;
}}
'''
harness = (harness
           .replace('__TYPES__', TYPES)
           .replace('__TICKS__', TICKS)
           .replace('__CRC__', CRC)
           .replace('__SWITCH_PACKET__', SWITCH_PACKET)
           .replace('__METHODS__', methods))


def replay(code, root='.', label='current'):
    cc, sdk = clang_and_sdk('rumble routing replay')
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
        ok = ran.returncode == 0 and 'rumble routing replay passed' in ran.stdout
        if not ok:
            print(ran.stdout, ran.stderr)
        return ok, label


def main():
    ok, label = replay(harness)
    if not ok:
        print('rumble routing: current code FAILS (%s)' % label)
        raise SystemExit(1)
    print('rumble routing: current code passes (%s)' % label)

    # Mutation 1: routing ignores the index and always sends to the first
    # device -- pad1's rumble lands on pad0.
    m1 = harness.replace(
        'if (entry.playerIndex == number) {\n            return entry.hidDevice;\n        }',
        'if (entry.playerIndex == 0) {\n            return entry.hidDevice;\n        }')
    assert m1 != harness
    ok1, _ = replay(m1, label='index ignored')
    if ok1:
        print('rumble routing: NOT CAUGHT (index ignored)')
        raise SystemExit(1)
    print('rumble routing: caught index-ignored routing')

    # Mutation 2: the dedup guard is shared again -- the neighbour is skipped.
    m2 = harness.replace('entry.previousLowFreqMotor', 'sharedLow') \
                .replace('entry.previousHighFreqMotor', 'sharedHigh')
    assert m2 != harness
    ok2, _ = replay(m2, label='shared dedup')
    if ok2:
        print('rumble routing: NOT CAUGHT (shared dedup)')
        raise SystemExit(1)
    print('rumble routing: caught shared dedup state')


if __name__ == '__main__':
    main()
