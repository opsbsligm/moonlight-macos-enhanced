#import "HIDKeyboardQuirkFilter.h"
#import "Logger.h"
#import <Carbon/Carbon.h>
#import <IOKit/hid/IOHIDManager.h>
#import <IOKit/hid/IOHIDKeys.h>
#import <IOKit/hid/IOHIDUsageTables.h>
#import <IOKit/hidsystem/IOHIDLib.h>
#import <mach/mach_time.h>
#include <math.h>

// IOHIDValue timestamps use mach absolute time; NSEvent timestamps use seconds
// since boot. Compare event creation times, never callback arrival times.
// https://developer.apple.com/documentation/iokit/1433294-iohidvaluecreatewithintegervalue
static const NSTimeInterval HIDSourceMatchTolerance = 0.020;
static const NSUInteger HIDSourceHistoryLimit = 64;

@interface HIDKeyboardQuirkFilter ()
@property (nonatomic) IOHIDManagerRef manager;
@property (nonatomic) BOOL monitoring;
@property (nonatomic, strong) NSMutableSet<NSValue *> *knownPointerDevices;
@property (nonatomic, strong) NSMutableArray<NSDictionary *> *observations;
- (void)recordKnownPointer:(BOOL)knownPointer timestamp:(NSTimeInterval)timestamp;
@end

static NSInteger HIDDeviceInteger(IOHIDDeviceRef device, CFStringRef key) {
    CFTypeRef value = IOHIDDeviceGetProperty(device, key);
    if (value == NULL || CFGetTypeID(value) != CFNumberGetTypeID()) return 0;
    NSInteger result = 0;
    CFNumberGetValue((CFNumberRef)value, kCFNumberNSIntegerType, &result);
    return result;
}

static BOOL HIDDeviceHasKnownPointerQuirk(IOHIDDeviceRef device) {
    NSInteger page = HIDDeviceInteger(device, CFSTR(kIOHIDPrimaryUsagePageKey));
    NSInteger usage = HIDDeviceInteger(device, CFSTR(kIOHIDPrimaryUsageKey));
    return HIDDeviceInteger(device, CFSTR(kIOHIDVendorIDKey)) == 0x363C &&
           HIDDeviceInteger(device, CFSTR(kIOHIDProductIDKey)) == 0xED1C &&
           page == kHIDPage_GenericDesktop &&
           (usage == kHIDUsage_GD_Mouse || usage == kHIDUsage_GD_Pointer);
}

static void HIDQuirkDeviceMatched(void *context, IOReturn result, void *sender, IOHIDDeviceRef device) {
    (void)sender;
    if (result != kIOReturnSuccess || !HIDDeviceHasKnownPointerQuirk(device)) return;
    HIDKeyboardQuirkFilter *filter = (__bridge HIDKeyboardQuirkFilter *)context;
    [filter.knownPointerDevices addObject:[NSValue valueWithPointer:device]];
    Log(LOG_I, @"[input] pointer keyboard quirk available: vid=363c pid=ed1c (C usage only)");
}

static void HIDQuirkDeviceRemoved(void *context, IOReturn result, void *sender, IOHIDDeviceRef device) {
    (void)result; (void)sender;
    HIDKeyboardQuirkFilter *filter = (__bridge HIDKeyboardQuirkFilter *)context;
    [filter.knownPointerDevices removeObject:[NSValue valueWithPointer:device]];
    // Removal invalidates attribution, including any observation waiting on AppKit.
    [filter.observations removeAllObjects];
}

static void HIDQuirkValueReceived(void *context, IOReturn result, void *sender, IOHIDValueRef value) {
    (void)sender;
    if (result != kIOReturnSuccess || value == NULL || IOHIDValueGetIntegerValue(value) == 0) return;
    IOHIDElementRef element = IOHIDValueGetElement(value);
    if (IOHIDElementGetUsagePage(element) != kHIDPage_KeyboardOrKeypad ||
        IOHIDElementGetUsage(element) != kHIDUsage_KeyboardC) return;
    IOHIDDeviceRef device = IOHIDElementGetDevice(element);
    if (device == NULL) return;
    mach_timebase_info_data_t timebase;
    mach_timebase_info(&timebase);
    NSTimeInterval timestamp = (double)IOHIDValueGetTimeStamp(value) *
                              (double)timebase.numer / (double)timebase.denom / 1.0e9;
    HIDKeyboardQuirkFilter *filter = (__bridge HIDKeyboardQuirkFilter *)context;
    // A removal can precede an already queued value callback. Device metadata
    // alone must not revive its attribution while another pointer is attached.
    BOOL activePointer = [filter.knownPointerDevices containsObject:[NSValue valueWithPointer:device]];
    [filter recordKnownPointer:activePointer && HIDDeviceHasKnownPointerQuirk(device) timestamp:timestamp];
}

@implementation HIDKeyboardQuirkFilter
- (instancetype)init {
    if ((self = [super init])) {
        _knownPointerDevices = [NSMutableSet set];
        _observations = [NSMutableArray array];
    }
    return self;
}

- (void)start {
    NSAssert(NSThread.isMainThread, @"Keyboard source observation belongs to the main run loop");
    if (self.manager != NULL ||
        [[NSUserDefaults standardUserDefaults] boolForKey:@"input.disablePointerKeyboardQuirkFilter"]) return;
    if (IOHIDCheckAccess(kIOHIDRequestTypeListenEvent) != kIOHIDAccessTypeGranted) {
        Log(LOG_I, @"[input] pointer keyboard quirk filter unavailable: Input Monitoring not granted; keyboard forwarding unchanged");
        return;
    }
    IOHIDManagerRef manager = IOHIDManagerCreate(kCFAllocatorDefault, kIOHIDOptionsTypeNone);
    if (manager == NULL) return;
    self.manager = manager;
    // Include real keyboards as negative evidence: overlapping real C input wins.
    // Matching keyboard usage collections also includes composite pointer nodes.
    NSDictionary *match = @{@kIOHIDDeviceUsagePageKey: @(kHIDPage_GenericDesktop),
                            @kIOHIDDeviceUsageKey: @(kHIDUsage_GD_Keyboard)};
    NSDictionary *keypad = @{@kIOHIDDeviceUsagePageKey: @(kHIDPage_GenericDesktop),
                             @kIOHIDDeviceUsageKey: @(kHIDUsage_GD_Keypad)};
    NSDictionary *mouse = @{@kIOHIDDeviceUsagePageKey: @(kHIDPage_GenericDesktop),
                            @kIOHIDDeviceUsageKey: @(kHIDUsage_GD_Mouse)};
    NSDictionary *pointer = @{@kIOHIDDeviceUsagePageKey: @(kHIDPage_GenericDesktop),
                              @kIOHIDDeviceUsageKey: @(kHIDUsage_GD_Pointer)};
    IOHIDManagerSetDeviceMatchingMultiple(manager, (__bridge CFArrayRef)@[match, keypad, mouse, pointer]);
    IOHIDManagerSetInputValueMatching(manager, (__bridge CFDictionaryRef)@{
        @kIOHIDElementUsagePageKey: @(kHIDPage_KeyboardOrKeypad),
        @kIOHIDElementUsageKey: @(kHIDUsage_KeyboardC)});
    IOHIDManagerRegisterDeviceMatchingCallback(manager, HIDQuirkDeviceMatched, (__bridge void *)self);
    IOHIDManagerRegisterDeviceRemovalCallback(manager, HIDQuirkDeviceRemoved, (__bridge void *)self);
    IOHIDManagerRegisterInputValueCallback(manager, HIDQuirkValueReceived, (__bridge void *)self);
    IOHIDManagerScheduleWithRunLoop(manager, CFRunLoopGetMain(), kCFRunLoopCommonModes);
    IOReturn result = IOHIDManagerOpen(manager, kIOHIDOptionsTypeNone);
    if (result != kIOReturnSuccess) {
        Log(LOG_W, @"[input] pointer keyboard quirk listener failed: 0x%x; keyboard forwarding unchanged", result);
        [self stop];
        return;
    }
    self.monitoring = YES;
    CFSetRef devices = IOHIDManagerCopyDevices(manager);
    for (id device in (__bridge NSSet *)devices) {
        HIDQuirkDeviceMatched((__bridge void *)self, kIOReturnSuccess, NULL, (__bridge IOHIDDeviceRef)device);
    }
    if (devices != NULL) CFRelease(devices);
}

- (void)stop {
    NSAssert(NSThread.isMainThread, @"Keyboard source observation belongs to the main run loop");
    self.monitoring = NO;
    if (self.manager != NULL) {
        IOHIDManagerUnscheduleFromRunLoop(self.manager, CFRunLoopGetMain(), kCFRunLoopCommonModes);
        IOHIDManagerRegisterInputValueCallback(self.manager, NULL, NULL);
        IOHIDManagerRegisterDeviceMatchingCallback(self.manager, NULL, NULL);
        IOHIDManagerRegisterDeviceRemovalCallback(self.manager, NULL, NULL);
        IOHIDManagerClose(self.manager, kIOHIDOptionsTypeNone);
        CFRelease(self.manager);
        self.manager = NULL;
    }
    [self.knownPointerDevices removeAllObjects];
    [self.observations removeAllObjects];
}

- (void)dealloc {
    // Owners stop on the main thread before releasing their session. This fallback
    // also disconnects callbacks if initialization or connection setup was aborted.
    if (_manager != NULL) {
        IOHIDManagerUnscheduleFromRunLoop(_manager, CFRunLoopGetMain(), kCFRunLoopCommonModes);
        IOHIDManagerRegisterInputValueCallback(_manager, NULL, NULL);
        IOHIDManagerRegisterDeviceMatchingCallback(_manager, NULL, NULL);
        IOHIDManagerRegisterDeviceRemovalCallback(_manager, NULL, NULL);
        IOHIDManagerClose(_manager, kIOHIDOptionsTypeNone);
        CFRelease(_manager);
    }
}

- (void)recordKnownPointer:(BOOL)knownPointer timestamp:(NSTimeInterval)timestamp {
    if (!self.monitoring || !isfinite(timestamp) || timestamp <= 0) return;
    [self.observations addObject:@{@"pointer": @(knownPointer), @"timestamp": @(timestamp)}];
    if (self.observations.count > HIDSourceHistoryLimit) [self.observations removeObjectAtIndex:0];
}

- (BOOL)shouldDeferKeyCode:(unsigned short)keyCode timestamp:(NSTimeInterval)timestamp {
    return keyCode == kVK_ANSI_C && isfinite(timestamp) && timestamp > 0 &&
           self.monitoring && self.knownPointerDevices.count != 0;
}

- (BOOL)isKnownPointerKeyCode:(unsigned short)keyCode timestamp:(NSTimeInterval)timestamp {
    if (![self shouldDeferKeyCode:keyCode timestamp:timestamp]) return NO;
    BOOL matchedPointer = NO;
    for (NSDictionary *observation in self.observations) {
        if (fabs([observation[@"timestamp"] doubleValue] - timestamp) > HIDSourceMatchTolerance) continue;
        // A real keyboard or an unknown device at the same instant is ambiguous.
        // Preserve the keystroke rather than blaming the attached mouse for it.
        if (![observation[@"pointer"] boolValue]) return NO;
        matchedPointer = YES;
    }
    return matchedPointer;
}
@end
