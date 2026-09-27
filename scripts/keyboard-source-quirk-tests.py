#!/usr/bin/env python3
"""Compile the entire source filter with IOHID boundary stubs.

No device is opened, no input is observed, no preferences are written, and no
permission is requested. The actual manager callbacks, device classification,
timestamp conversion, source arbitration, history and lifecycle all run.
"""
from pathlib import Path
import subprocess
import tempfile

from apple_toolchain import clang_and_sdk

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Limelight/Input/HIDKeyboardQuirkFilter.m"

PREAMBLE = r'''
#import <Foundation/Foundation.h>
#import <Carbon/Carbon.h>
#import <IOKit/hid/IOHIDManager.h>
#import <IOKit/hid/IOHIDKeys.h>
#import <IOKit/hid/IOHIDUsageTables.h>
#import <IOKit/hidsystem/IOHIDLib.h>
#import <mach/mach_time.h>
#import "Logger.h"
#include <math.h>
static int failures, creations, opens, closes;
static BOOL accessGranted = YES, disabled;
static IOReturn openResult;
static NSArray *devices;
static NSArray *deviceMatching;
static NSDictionary *valueMatching;
static IOHIDDeviceCallback matched, removed;
static IOHIDValueCallback received;
static void *matchedContext, *removedContext, *receivedContext;
static uint32_t timeNumerator = 125, timeDenominator = 3;
static void check(BOOL ok, const char *label) {
    printf("%s %s\n", ok ? "ok  " : "FAIL", label); failures += !ok;
}
void Log(LogLevel level, NSString *format, ...) { (void)level; (void)format; }
@interface ProbeDefaults : NSObject
+ (id)standardUserDefaults;
- (BOOL)boolForKey:(NSString *)key;
@end
@implementation ProbeDefaults
+ (id)standardUserDefaults { static ProbeDefaults *instance; if (!instance) instance = [self new]; return instance; }
- (BOOL)boolForKey:(NSString *)key { return disabled; }
@end
static IOHIDAccessType probeAccess(IOHIDRequestType type) {
    check(type == kIOHIDRequestTypeListenEvent, "only listen permission is checked");
    return accessGranted ? kIOHIDAccessTypeGranted : kIOHIDAccessTypeDenied;
}
static IOHIDManagerRef probeCreate(CFAllocatorRef allocator, IOOptionBits options) {
    creations++;
    check(options == kIOHIDOptionsTypeNone, "manager never seizes the pointer");
    return (IOHIDManagerRef)CFDictionaryCreateMutable(kCFAllocatorDefault, 0,
                 &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
}
static IOReturn probeOpen(IOHIDManagerRef manager, IOOptionBits options) { opens++; return openResult; }
static IOReturn probeClose(IOHIDManagerRef manager, IOOptionBits options) { closes++; return kIOReturnSuccess; }
static void probeSchedule(IOHIDManagerRef manager, CFRunLoopRef loop, CFStringRef mode) {}
static void probeUnschedule(IOHIDManagerRef manager, CFRunLoopRef loop, CFStringRef mode) {}
static void probeDeviceMatching(IOHIDManagerRef manager, CFArrayRef matching) { deviceMatching = (__bridge NSArray *)matching; }
static void probeValueMatching(IOHIDManagerRef manager, CFDictionaryRef matching) { valueMatching = (__bridge NSDictionary *)matching; }
static void probeRegisterMatched(IOHIDManagerRef manager, IOHIDDeviceCallback callback, void *context) { matched = callback; matchedContext = context; }
static void probeRegisterRemoved(IOHIDManagerRef manager, IOHIDDeviceCallback callback, void *context) { removed = callback; removedContext = context; }
static void probeRegisterReceived(IOHIDManagerRef manager, IOHIDValueCallback callback, void *context) { received = callback; receivedContext = context; }
static CFSetRef probeDevices(IOHIDManagerRef manager) {
    return CFBridgingRetain([NSSet setWithArray:devices ?: @[]]);
}
static CFTypeRef probeDeviceProperty(IOHIDDeviceRef device, CFStringRef key) {
    return (__bridge CFTypeRef)((__bridge NSDictionary *)device)[(__bridge NSString *)key];
}
static CFIndex probeInteger(IOHIDValueRef value) { return [((__bridge NSDictionary *)value)[@"value"] longValue]; }
static IOHIDElementRef probeElement(IOHIDValueRef value) { return (IOHIDElementRef)value; }
static uint32_t probeUsagePage(IOHIDElementRef element) { return [((__bridge NSDictionary *)element)[@"page"] unsignedIntValue]; }
static uint32_t probeUsage(IOHIDElementRef element) { return [((__bridge NSDictionary *)element)[@"usage"] unsignedIntValue]; }
static IOHIDDeviceRef probeDevice(IOHIDElementRef element) { return (__bridge IOHIDDeviceRef)((__bridge NSDictionary *)element)[@"device"]; }
static uint64_t probeTimestamp(IOHIDValueRef value) { return [((__bridge NSDictionary *)value)[@"ticks"] unsignedLongLongValue]; }
static kern_return_t probeTimebase(mach_timebase_info_t info) { info->numer = timeNumerator; info->denom = timeDenominator; return KERN_SUCCESS; }
#define NSUserDefaults ProbeDefaults
#define IOHIDCheckAccess probeAccess
#define IOHIDManagerCreate probeCreate
#define IOHIDManagerOpen probeOpen
#define IOHIDManagerClose probeClose
#define IOHIDManagerScheduleWithRunLoop probeSchedule
#define IOHIDManagerUnscheduleFromRunLoop probeUnschedule
#define IOHIDManagerSetDeviceMatchingMultiple probeDeviceMatching
#define IOHIDManagerSetInputValueMatching probeValueMatching
#define IOHIDManagerRegisterDeviceMatchingCallback probeRegisterMatched
#define IOHIDManagerRegisterDeviceRemovalCallback probeRegisterRemoved
#define IOHIDManagerRegisterInputValueCallback probeRegisterReceived
#define IOHIDManagerCopyDevices probeDevices
#define IOHIDDeviceGetProperty probeDeviceProperty
#define IOHIDValueGetIntegerValue probeInteger
#define IOHIDValueGetElement probeElement
#define IOHIDValueGetTimeStamp probeTimestamp
#define IOHIDElementGetUsagePage probeUsagePage
#define IOHIDElementGetUsage probeUsage
#define IOHIDElementGetDevice probeDevice
#define mach_timebase_info probeTimebase
'''

DRIVER = r'''
static NSDictionary *device(int vendor, int product, int usage, NSString *identity) {
    return @{@kIOHIDVendorIDKey:@(vendor), @kIOHIDProductIDKey:@(product),
             @kIOHIDPrimaryUsagePageKey:@(kHIDPage_GenericDesktop),
             @kIOHIDPrimaryUsageKey:@(usage), @"identity":identity};
}
static void emit(NSDictionary *device, double seconds, uint32_t usage, int value) {
    NSDictionary *report = @{@"device":device, @"page":@(kHIDPage_KeyboardOrKeypad),
                            @"usage":@(usage), @"value":@(value),
                            @"ticks":@((uint64_t)llround(seconds * 1.0e9 * timeDenominator / timeNumerator))};
    received(receivedContext, kIOReturnSuccess, NULL, (__bridge IOHIDValueRef)report);
}
int main(void) { @autoreleasepool {
    NSDictionary *pointer = device(0x363C, 0xED1C, kHIDUsage_GD_Mouse, @"first");
    NSDictionary *secondPointer = device(0x363C, 0xED1C, kHIDUsage_GD_Pointer, @"second");
    NSDictionary *keyboard = device(0x05AC, 0x029C, kHIDUsage_GD_Keyboard, @"keyboard");
    NSDictionary *keypad = device(0x045E, 0x1234, kHIDUsage_GD_Keypad, @"keypad");
    NSDictionary *unknown = device(0x1234, 0xED1C, kHIDUsage_GD_Mouse, @"unknown");
    NSDictionary *keyboardTwin = device(0x363C, 0xED1C, kHIDUsage_GD_Keyboard, @"same vendor keyboard");
    HIDKeyboardQuirkFilter *filter = [HIDKeyboardQuirkFilter new];
    devices = @[pointer, keyboard, keypad, unknown, keyboardTwin];
    accessGranted = NO;
    [filter start];
    check(creations == 0 && ![filter shouldDeferKeyCode:kVK_ANSI_C timestamp:1],
          "missing permission preserves keyboard input and opens no device");
    accessGranted = YES;
    disabled = YES;
    [filter start];
    check(creations == 0, "explicitly disabled filter stays inactive");
    disabled = NO;
    openResult = kIOReturnError;
    [filter start];
    check(!filter.monitoring && filter.manager == NULL && received == NULL &&
          ![filter shouldDeferKeyCode:kVK_ANSI_C timestamp:1], "manager open failure cleans up and fails open");
    openResult = kIOReturnSuccess;
    [filter start];
    check(filter.knownPointerDevices.count == 1, "only the exact known pointer interface is eligible");
    check(deviceMatching.count == 4 &&
          [deviceMatching containsObject:@{@kIOHIDDeviceUsagePageKey:@(kHIDPage_GenericDesktop),
                                           @kIOHIDDeviceUsageKey:@(kHIDUsage_GD_Keypad)}] &&
          [valueMatching[@kIOHIDElementUsageKey] intValue] == kHIDUsage_KeyboardC,
          "matching observes C from pointer and genuine keyboard collections");
    check([filter shouldDeferKeyCode:kVK_ANSI_C timestamp:2] &&
          ![filter shouldDeferKeyCode:kVK_ANSI_W timestamp:2], "only C enters source arbitration");
    check(![filter isKnownPointerKeyCode:kVK_ANSI_C timestamp:2], "attached pointer alone never proves a keystroke source");
    emit(pointer, 2, kHIDUsage_KeyboardC, 1);
    check([filter isKnownPointerKeyCode:kVK_ANSI_C timestamp:2], "known pointer C is positively identified");
    check(fabs([filter.observations.lastObject[@"timestamp"] doubleValue] - 2) < 1e-9,
          "mach ticks convert with numerator/denominator into NSEvent seconds");
    check(![filter isKnownPointerKeyCode:kVK_ANSI_C timestamp:2.021], "source evidence outside the 20ms window expires open");
    check(![filter isKnownPointerKeyCode:kVK_ANSI_W timestamp:2], "pointer C evidence cannot suppress W");
    emit(keyboard, 2.005, kHIDUsage_KeyboardC, 1);
    check(![filter isKnownPointerKeyCode:kVK_ANSI_C timestamp:2], "concurrent genuine keyboard C wins over pointer evidence");
    [filter.observations removeAllObjects];
    emit(keyboard, 3, kHIDUsage_KeyboardC, 1);
    emit(pointer, 3.005, kHIDUsage_KeyboardC, 1);
    check(![filter isKnownPointerKeyCode:kVK_ANSI_C timestamp:3], "genuine keyboard wins regardless of callback order");
    [filter.observations removeAllObjects];
    emit(pointer, 4, kHIDUsage_KeyboardC, 1);
    emit(unknown, 4, kHIDUsage_KeyboardC, 1);
    check(![filter isKnownPointerKeyCode:kVK_ANSI_C timestamp:4], "unknown device makes source ambiguous and preserves C");
    [filter.observations removeAllObjects];
    emit(pointer, 4.5, kHIDUsage_KeyboardC, 1);
    emit(keypad, 4.5, kHIDUsage_KeyboardC, 1);
    check(![filter isKnownPointerKeyCode:kVK_ANSI_C timestamp:4.5], "keypad collection supplies negative keyboard evidence too");
    [filter.observations removeAllObjects];
    emit(pointer, 5, kHIDUsage_KeyboardC, 0);
    emit(pointer, 5, kHIDUsage_KeyboardD, 1);
    check(filter.observations.count == 0, "releases and other HID usages cannot create positive C evidence");
    check(![filter shouldDeferKeyCode:kVK_ANSI_C timestamp:NAN] &&
          ![filter shouldDeferKeyCode:kVK_ANSI_C timestamp:0], "invalid timestamps fail open");
    timeNumerator = timeDenominator = 1;
    emit(pointer, 6, kHIDUsage_KeyboardC, 1);
    check([filter isKnownPointerKeyCode:kVK_ANSI_C timestamp:6], "unit timebase also matches event seconds");
    for (int i = 0; i < 200; i++) emit(pointer, 10 + i, kHIDUsage_KeyboardC, 1);
    check(filter.observations.count == 64 &&
          ![filter isKnownPointerKeyCode:kVK_ANSI_C timestamp:10] &&
          [filter isKnownPointerKeyCode:kVK_ANSI_C timestamp:209], "history retains at most 64 observations and evicts oldest evidence");
    matched(matchedContext, kIOReturnSuccess, NULL, (__bridge IOHIDDeviceRef)secondPointer);
    removed(removedContext, kIOReturnSuccess, NULL, (__bridge IOHIDDeviceRef)pointer);
    check(filter.knownPointerDevices.count == 1 && filter.observations.count == 0,
          "disconnect invalidates queued source observations");
    emit(pointer, 300, kHIDUsage_KeyboardC, 1);
    check(![filter isKnownPointerKeyCode:kVK_ANSI_C timestamp:300],
          "late report from a removed pointer cannot borrow another pointer's identity");
    removed(removedContext, kIOReturnSuccess, NULL, (__bridge IOHIDDeviceRef)secondPointer);
    check(![filter shouldDeferKeyCode:kVK_ANSI_C timestamp:301], "last known pointer disconnect removes deferral");
    [filter stop];
    check(!filter.monitoring && filter.observations.count == 0 && filter.knownPointerDevices.count == 0 &&
          received == NULL && matched == NULL && removed == NULL, "stop unregisters callbacks and clears session state");
    int closeCount = closes;
    [filter stop];
    check(closes == closeCount, "stop is idempotent");
    @autoreleasepool {
        HIDKeyboardQuirkFilter *abandoned = [HIDKeyboardQuirkFilter new];
        [abandoned start];
        abandoned = nil;
    }
    check(received == NULL && matched == NULL && removed == NULL && closes == closeCount + 1,
          "deallocation unregisters every callback if the owner omitted stop");
    return failures ? 1 : 0;
} }
'''


def main():
    source = SOURCE.read_text()
    if "IOHIDRequestAccess(" in source:
        raise SystemExit("filter must never request input permission")
    clang, sdk = clang_and_sdk("keyboard source filter probe")
    with tempfile.TemporaryDirectory(prefix="keyboard-source-quirk-") as directory:
        mutants = [
            ("removed-device attribution", "activePointer && HIDDeviceHasKnownPointerQuirk(device)",
             "HIDDeviceHasKnownPointerQuirk(device)"),
            ("keyboard negative evidence", 'if (![observation[@"pointer"] boolValue]) return NO;', ""),
            ("timestamp units", "/ 1.0e9;", "/ 1.0e6;"),
            ("bounded history", "if (self.observations.count > HIDSourceHistoryLimit) [self.observations removeObjectAtIndex:0];", ""),
        ]
        variants = [("current", source, True)]
        for label, before, after in mutants:
            if source.count(before) != 1:
                raise SystemExit(f"mutation anchor moved: {label}")
            variants.append((label, source.replace(before, after, 1), False))
        for index, (label, implementation, should_pass) in enumerate(variants):
            path = Path(directory) / f"probe{index}.m"
            binary = Path(directory) / f"probe{index}"
            path.write_text(PREAMBLE + implementation + DRIVER)
            subprocess.run([clang, "-isysroot", sdk, "-fobjc-arc", "-framework", "Foundation",
                            "-framework", "Carbon", "-framework", "IOKit", "-I", str(SOURCE.parent),
                            "-I", str(ROOT / "Limelight/Utility"), str(path), "-o", str(binary)], check=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            if should_pass or (result.returncode == 0) != should_pass:
                print(result.stdout, end="")
                print(result.stderr, end="")
            if (result.returncode == 0) != should_pass:
                raise SystemExit(f"{label} unexpectedly returned {result.returncode}")
            if not should_pass:
                print(f"ok   missing {label} protection is rejected")


if __name__ == "__main__":
    main()
