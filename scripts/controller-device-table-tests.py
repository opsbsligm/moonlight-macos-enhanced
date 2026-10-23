#!/usr/bin/env python3
"""Compile the shipping table methods; replay distinct devices and slot exhaustion.

Also compiles the real isNintendo/isPlayStation predicates from
HIDSupport_Internal.h with a fake IOHID property bus, so the protocol type an
arrival would send is checked against the device ids: the Pro Controller and a
lone left or right Joy-Con (0x2006/0x2007) all answer LI_CTYPE_NINTENDO, a
DualShock 4 answers LI_CTYPE_PS, and an Xbox or unknown pad falls to
LI_CTYPE_XBOX.
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


source = Path('Limelight/Input/HIDSupport.m').read_text()
internal = Path('Limelight/Input/HIDSupport_Internal.h').read_text()
methods = '\n'.join(method(source, name) for name in (
    '- (NSString *)deviceKeyForDevice:',
    '- (HIDDeviceControllerEntry *)entryForDevice:',
    '- (int)allocatePlayerSlot {',
    '- (int)activeDeviceMask {',
    '- (uint8_t)protocolTypeForDevice:'))
predicates = '\n'.join(method(internal, name) for name in (
    'static inline UInt16 usbIdFromDevice',
    'static inline BOOL isNintendo',
    'static inline BOOL isPlayStation'))
harness = r'''
#import <Foundation/Foundation.h>
typedef const void *IOHIDDeviceRef;
CFTypeRef CFRetain(CFTypeRef v) { return v; }
void CFRelease(CFTypeRef v) { (void)v; }
typedef struct { double pressedAt; } MLGamepadMenuGesture;
static MLGamepadMenuGesture MLGamepadMenuGestureIdle(void) {
    return (MLGamepadMenuGesture){__builtin_nan("")};
}
static const uint16_t LI_CCAP_ANALOG_TRIGGERS = 0x01;
static const uint16_t LI_CCAP_RUMBLE = 0x02;
static const uint16_t LI_CCAP_TRIGGER_RUMBLE = 0x04;
static const uint16_t LI_CCAP_RGB_LED = 0x80;
static const uint16_t LI_CCAP_ACCEL = 0x10;
static const uint16_t LI_CCAP_GYRO = 0x20;
static const uint16_t LI_CCAP_BATTERY_STATE = 0x40;
static const uint16_t LI_CCAP_TOUCHPAD = 0x08;
static const uint16_t kHIDArrivalCapabilities = LI_CCAP_ANALOG_TRIGGERS | LI_CCAP_RUMBLE;
static const uint8_t LI_CTYPE_XBOX = 0x01;
static const uint8_t LI_CTYPE_PS = 0x02;
static const uint8_t LI_CTYPE_NINTENDO = 0x03;
// Fake IOHID property bus: the predicates under test only ever ask for the two
// usb id keys, so a two-slot table answers the whole question.
typedef struct { const void *device; unsigned short vid, pid; } FakePair;
static FakePair g_bus[8];
static int g_busCount;
static void busSet(const void *device, unsigned short vid, unsigned short pid) {
    g_bus[g_busCount].device = device;
    g_bus[g_busCount].vid = vid;
    g_bus[g_busCount].pid = pid;
    g_busCount++;
}
static unsigned short busId(const void *device, int isProduct) {
    for (int i = 0; i < g_busCount; i++) {
        if (g_bus[i].device == device) {
            return isProduct ? g_bus[i].pid : g_bus[i].vid;
        }
    }
    return 0xFFFF;
}
// The SDK spells these keys as C string macros (IOHIDDeviceKeys.h); the real
// predicates below are compiled against the same spelling, so the fake bus
// answers by comparing the CFString bytes it is handed.
#define kIOHIDVendorIDKey "VendorID"
#define kIOHIDProductIDKey "ProductID"
static CFTypeRef IOHIDDeviceGetProperty(IOHIDDeviceRef device, CFStringRef key) {
    if (key == NULL) return NULL;
    char buf[64];
    if (!CFStringGetCString(key, buf, sizeof(buf), kCFStringEncodingUTF8)) {
        return NULL;
    }
    if (strcmp(buf, "VendorID") == 0) {
        return CFBridgingRetain([NSNumber numberWithUnsignedShort:busId(device, 0)]);
    }
    if (strcmp(buf, "ProductID") == 0) {
        return CFBridgingRetain([NSNumber numberWithUnsignedShort:busId(device, 1)]);
    }
    return NULL;
}
__PREDICATES__
static BOOL isPS4(IOHIDDeviceRef device) { (void)device; return NO; }
static BOOL isPS5(IOHIDDeviceRef device) { (void)device; return NO; }
static BOOL isXbox(IOHIDDeviceRef device) __attribute__((unused));
static BOOL isXbox(IOHIDDeviceRef device) { (void)device; return NO; }
static BOOL isKingKong(IOHIDDeviceRef device) __attribute__((unused));
static BOOL isKingKong(IOHIDDeviceRef device) { (void)device; return NO; }
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
@end
@implementation HIDSupport
- (uint32_t)supportedButtonFlagsForDevice:(IOHIDDeviceRef)d { return 0xffff; }
__METHODS__
@end
#define CHECK(x) do { if (!(x)) { NSLog(@"failed line %d", __LINE__); return 1; } } while (0)
int main(void) { @autoreleasepool {
    HIDSupport *s = [HIDSupport new];
    int handles[17] = {0};
    CHECK([s entryForDevice:NULL] == nil);
    HIDDeviceControllerEntry *a = [s entryForDevice:&handles[0]];
    HIDDeviceControllerEntry *b = [s entryForDevice:&handles[1]];
    CHECK(a != nil && b != nil && a != b);
    CHECK(s.deviceControllerTable.count == 2);
    CHECK(a.playerIndex == 0 && b.playerIndex == 1);
    CHECK([s entryForDevice:&handles[0]] == a);
    a.controller.lastButtonFlags = 0x1000;
    b.controller.lastButtonFlags = 0x2000;
    CHECK(a.controller.lastButtonFlags == 0x1000 && b.controller.lastButtonFlags == 0x2000);
    CHECK([s activeDeviceMask] == 3);
    [s.deviceControllerTable removeObjectForKey:[s deviceKeyForDevice:&handles[0]]];
    CHECK([s activeDeviceMask] == 2);
    CHECK([s entryForDevice:&handles[2]].playerIndex == 0);
    for (int i = 3; i < 17; i++) CHECK([s entryForDevice:&handles[i]] != nil);
    int overflow;
    CHECK(s.deviceControllerTable.count == 16);
    CHECK([s activeDeviceMask] == 0xffff);
    CHECK([s entryForDevice:&overflow] == nil);
    CHECK(s.deviceControllerTable.count == 16);

    // M4: the arrival type is decided by the same predicates the bus reader
    // uses, so the pair list is replayed through the real ones. The Pro
    // Controller and a lone left or right Joy-Con must all answer NINTENDO;
    // a DualShock 4 answers PS; an Xbox and an unknown pair fall to XBOX.
    // The exhaustion table above is cleared first: six more pads would
    // overflow the sixteen slots.
    [s.deviceControllerTable removeAllObjects];
    busSet((const void *)0x7001, 0x057E, 0x2009);
    busSet((const void *)0x7002, 0x057E, 0x2006);
    busSet((const void *)0x7003, 0x057E, 0x2007);
    busSet((const void *)0x7004, 0x054C, 0x09CC);
    busSet((const void *)0x7005, 0x045E, 0x0B13);
    busSet((const void *)0x7006, 0x1234, 0x5678);
    HIDDeviceControllerEntry *n1 = [s entryForDevice:(const void *)0x7001];
    HIDDeviceControllerEntry *jl = [s entryForDevice:(const void *)0x7002];
    HIDDeviceControllerEntry *jr = [s entryForDevice:(const void *)0x7003];
    HIDDeviceControllerEntry *ps = [s entryForDevice:(const void *)0x7004];
    HIDDeviceControllerEntry *xb = [s entryForDevice:(const void *)0x7005];
    HIDDeviceControllerEntry *uk = [s entryForDevice:(const void *)0x7006];
    CHECK(n1 != nil && jl != nil && jr != nil && ps != nil && xb != nil && uk != nil);
    CHECK(n1.protocolType == 0x03 && jl.protocolType == 0x03 && jr.protocolType == 0x03);
    CHECK(ps.protocolType == 0x02);
    CHECK(xb.protocolType == 0x01 && uk.protocolType == 0x01);
    puts("device table replay passed");
    return 0;
}}
'''.replace('__METHODS__', methods).replace('__PREDICATES__', predicates)
cc, sdk = clang_and_sdk('controller table replay')
def replay(code):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        (path / 'probe.m').write_text(code)
        subprocess.run([cc, '-fobjc-arc', '-Wall', '-Werror', '-isysroot', sdk,
                        str(path / 'probe.m'), '-o', str(path / 'probe'),
                        '-framework', 'Foundation'],
                       check=True)
        return subprocess.run([str(path / 'probe')], capture_output=True, text=True)


result = replay(harness)
assert result.returncode == 0, result.stderr
print(result.stdout.strip())
mutations = (
    ('missing table initialization', 'self.deviceControllerTable = [NSMutableDictionary dictionary];',
     'self.deviceControllerTable = nil;'),
    ('identical device keys', '[NSString stringWithFormat:@"hid:%p", (void *)device]', '@"same-model"'),
    ('exhausted slot reused', '    return -1;', '    return 0;'),
    ('a lone Joy-Con no longer recognized as Nintendo',
     '(productId == 0x2009 || productId == 0x2006 || productId == 0x2007);',
     '(productId == 0x2009);'),
)
for label, old, new in mutations:
    assert harness.count(old) == 1, label
    result = replay(harness.replace(old, new, 1))
    assert result.returncode == 1 and 'failed line' in result.stderr, label + result.stderr
    print('caught:', label)
