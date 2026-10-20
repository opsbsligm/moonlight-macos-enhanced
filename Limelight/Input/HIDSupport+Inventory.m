//
//  HIDSupport+Inventory.m
//  Moonlight for macOS
//

#import "HIDSupport+Inventory.h"
#import "HIDSupport_Internal.h"
#import "MLControllerInventory.h"

// Apple names no key for these in its SDK headers, so they are spelled as the property
// strings IOKit actually returns. Best effort by design: a wired pad answers neither, and
// the reader has to be able to tell "no battery reported" from "battery flat".
static NSString *const kMLBatteryPercentProperty = @"BatteryPercent";
static NSString *const kMLTransportProperty = @"Transport";

static MLControllerEntry *MLControllerEntryForDevice(IOHIDDeviceRef device) {
    if (device == NULL) {
        return nil;
    }
    MLControllerEntry *entry = [[MLControllerEntry alloc] init];
    entry.vendorId = usbIdFromDevice(device, @kIOHIDVendorIDKey);
    entry.productId = usbIdFromDevice(device, @kIOHIDProductIDKey);
    entry.family = MLControllerFamilyForIds(entry.vendorId, entry.productId);
    // A missing property reads as NULL, and `CFGetTypeID(NULL)` faults rather than
    // returning zero, so every property read here has to check the pointer before asking
    // what it is. A wired pad answers neither key, which is the common case, not the edge.
    CFTypeRef transport = IOHIDDeviceGetProperty(device, (__bridge CFStringRef)kMLTransportProperty);
    if (transport != NULL && CFGetTypeID(transport) == CFStringGetTypeID()) {
        entry.transport = (__bridge NSString *)transport;
    }
    CFTypeRef battery = IOHIDDeviceGetProperty(device, (__bridge CFStringRef)kMLBatteryPercentProperty);
    if (battery != NULL && CFGetTypeID(battery) == CFNumberGetTypeID()) {
        NSInteger percent = 0;
        if (CFNumberGetValue((CFNumberRef)battery, kCFNumberNSIntegerType, &percent) &&
            percent >= 0 && percent <= 100) {
            entry.hasBatteryPercent = YES;
            entry.batteryPercent = percent;
        }
    }
    return entry;
}

@implementation HIDSupport (Inventory)

static NSArray<MLControllerEntry *> *MLControllerEntriesFromManager(IOHIDManagerRef manager) {
    if (manager == NULL) {
        return nil;
    }
    CFSetRef devices = IOHIDManagerCopyDevices(manager);
    if (devices == NULL) {
        return nil;
    }
    CFIndex count = CFSetGetCount(devices);
    NSMutableArray<MLControllerEntry *> *entries =
        [NSMutableArray arrayWithCapacity:(NSUInteger)MAX((CFIndex)0, count)];
    if (count > 0) {
        // The set is a bench's worth of nodes, so one buffer sized to it is both the simple
        // reading and the honest one: no node is dropped, and no fixed stack array silently
        // truncates a bench that grew.
        const void **values = calloc((size_t)count, sizeof(void *));
        if (values != NULL) {
            CFSetGetValues(devices, values);
            for (CFIndex index = 0; index < count; index++) {
                MLControllerEntry *entry = MLControllerEntryForDevice((IOHIDDeviceRef)values[index]);
                if (entry != nil) {
                    [entries addObject:entry];
                }
            }
            free((void *)values);
        }
    }
    CFRelease(devices);
    return [entries copy];
}

- (void)publishControllerInventoryForSessionStart {
    NSAssert(NSThread.isMainThread, @"the HID manager is scheduled on the main run loop");
    NSArray<MLControllerEntry *> *entries = MLControllerEntriesFromManager(self.hidManager);
    if (entries == nil) {
        // No manager means nobody looked. Publishing an empty list here would tell a report
        // "nothing was plugged in", which is a different claim from the one being made.
        return;
    }
    MLControllerInventory *inventory = MLControllerInventory.sharedInventory;
    [inventory noteSessionStarted];
    [inventory recordEntries:entries];
}

- (void)publishControllerInventoryChange {
    NSAssert(NSThread.isMainThread, @"the HID manager is scheduled on the main run loop");
    NSArray<MLControllerEntry *> *entries = MLControllerEntriesFromManager(self.hidManager);
    if (entries == nil) {
        return;
    }
    [MLControllerInventory.sharedInventory recordEntries:entries];
}

@end
