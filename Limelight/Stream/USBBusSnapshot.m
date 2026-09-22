//
//  USBBusSnapshot.m
//  Moonlight
//
//  See USBBusSnapshot.h for the measurements that chose this shape. The short version: the bus
//  is read from the devices downward, because the interface iterator is missing a third of the
//  interfaces the devices themselves name, and it is read without being touched, because nothing
//  in this feature has earned the right to claim an interface yet.
//

#import "USBBusSnapshot.h"

#import <IOKit/IOKitLib.h>

/// The registry is asked for properties by these names and by no others. The names below are the
/// ones whose values are personal or device-chosen -- a product name the vendor picked, a serial
/// that identifies one unit, an interface description -- and this layer has no use for any of
/// them. It hands whole dictionaries to Stage 1, which reads the identifiers it whitelists and
/// digests a serial the moment it touches one, so a literal here would mean this layer had
/// started deciding what to keep. The gate keeps the literals out.
NSArray<NSString *> *MLUSBBusInterfaceNumberCandidateKeys(void) {
    return @[ @"bInterfaceNumber", @"USB Interface Number" ];
}

MLUSBBusNodeRole MLUSBBusNodeRoleForPropertyKeys(NSSet<NSString *> *propertyKeys) {
    if (![propertyKeys isKindOfClass:[NSSet class]]) {
        return MLUSBBusNodeRoleNotInterface;
    }
    for (NSString *candidate in MLUSBBusInterfaceNumberCandidateKeys()) {
        if ([propertyKeys containsObject:candidate]) {
            return MLUSBBusNodeRoleInterface;
        }
    }
    return MLUSBBusNodeRoleNotInterface;
}

NSString *MLUSBBusNodeRoleName(MLUSBBusNodeRole role) {
    return role == MLUSBBusNodeRoleInterface ? @"interface" : @"not-interface";
}

NSString *MLUSBBusSnapshotStatusName(MLUSBBusSnapshotStatus status) {
    return status == MLUSBBusSnapshotStatusRead ? @"read" : @"bus-unreadable";
}

/// The element at an index, or nil when the parallel arrays do not line up. A snapshot assembled
/// from mismatched arrays would attach interfaces to the wrong device, so a missing entry costs
/// that node its placement instead of borrowing a neighbour's parent.
static id MLUSBBusParallelObject(NSArray *array, NSUInteger index) {
    if (![array isKindOfClass:[NSArray class]] || index >= array.count) {
        return nil;
    }
    return array[index];
}

NSArray<NSArray<NSDictionary<NSString *, id> *> *> *MLUSBBusGroupNodes(
    NSArray<NSDictionary<NSString *, id> *> *deviceNodes,
    NSArray<NSString *> *deviceIDs,
    NSArray<NSDictionary<NSString *, id> *> *interfaceNodes,
    NSArray<NSString *> *interfaceParentIDs) {
    NSMutableArray<NSMutableArray<NSDictionary<NSString *, id> *> *> *groups =
        [NSMutableArray array];
    NSMutableDictionary<NSString *, NSNumber *> *groupOfDevice = [NSMutableDictionary dictionary];

    const NSUInteger deviceCount =
        [deviceNodes isKindOfClass:[NSArray class]] ? deviceNodes.count : 0;
    for (NSUInteger index = 0; index < deviceCount; index++) {
        id node = deviceNodes[index];
        if (![node isKindOfClass:[NSDictionary class]]) {
            continue;
        }
        [groups addObject:[NSMutableArray arrayWithObject:node]];
        id deviceID = MLUSBBusParallelObject(deviceIDs, index);
        if ([deviceID isKindOfClass:[NSString class]] && [(NSString *)deviceID length] > 0 &&
            groupOfDevice[deviceID] == nil) {
            // The first group wins a contested id rather than the last, so that an interface is
            // never moved onto a device that appeared later in the same pass.
            groupOfDevice[deviceID] = @(groups.count - 1);
        }
    }

    const NSUInteger interfaceCount =
        [interfaceNodes isKindOfClass:[NSArray class]] ? interfaceNodes.count : 0;
    for (NSUInteger index = 0; index < interfaceCount; index++) {
        id node = interfaceNodes[index];
        if (![node isKindOfClass:[NSDictionary class]]) {
            continue;
        }
        id parentID = MLUSBBusParallelObject(interfaceParentIDs, index);
        NSNumber *group = [parentID isKindOfClass:[NSString class]] ? groupOfDevice[parentID] : nil;
        if (group != nil) {
            [groups[group.unsignedIntegerValue] addObject:node];
            continue;
        }
        // No parent among the devices this pass saw. Kept as a group of one: the node carries its
        // own identifiers, so it is still describable, but it is not attached to a device it did
        // not name as its parent.
        [groups addObject:[NSMutableArray arrayWithObject:node]];
    }

    return [groups copy];
}

MLUSBDeviceIdentity *MLUSBBusDeviceIdentityFromGroup(
    NSArray<NSDictionary<NSString *, id> *> *nodeGroup) {
    return MLUSBDeviceIdentityFromRegistryNodes(nodeGroup);
}

#pragma mark - The bus itself

static NSString *MLUSBBusEntryID(io_registry_entry_t entry) {
    uint64_t entryID = 0;
    if (IORegistryEntryGetRegistryEntryID(entry, &entryID) != KERN_SUCCESS || entryID == 0) {
        return nil;
    }
    return [NSString stringWithFormat:@"%llu", (unsigned long long)entryID];
}

static NSDictionary *MLUSBBusNodeProperties(io_registry_entry_t entry) {
    CFMutableDictionaryRef properties = NULL;
    if (IORegistryEntryCreateCFProperties(entry, &properties, kCFAllocatorDefault, 0) !=
            KERN_SUCCESS ||
        properties == NULL) {
        return nil;
    }
    return CFBridgingRelease(properties);
}

/// The device a node names as its parent, when it names exactly one. Two parents would mean the
/// node could belong to either of them, and an interface attached to the wrong device would put
/// one device's interfaces behind another device's rule. Zero parents is the same problem.
static NSString *MLUSBBusSoleParentID(io_registry_entry_t entry) {
    io_iterator_t parents = IO_OBJECT_NULL;
    if (IORegistryEntryGetParentIterator(entry, kIOServicePlane, &parents) != KERN_SUCCESS) {
        return nil;
    }
    NSString *parentID = nil;
    NSUInteger seen = 0;
    io_registry_entry_t parent = IO_OBJECT_NULL;
    while ((parent = IOIteratorNext(parents)) != IO_OBJECT_NULL) {
        NSString *candidate = MLUSBBusEntryID(parent);
        if (candidate != nil) {
            if (seen == 0) {
                parentID = candidate;
            }
            seen++;
        }
        IOObjectRelease(parent);
    }
    IOObjectRelease(parents);
    return seen == 1 ? parentID : nil;
}

NSArray<MLUSBDeviceIdentity *> *MLUSBBusSnapshotCopyDeviceIdentities(
    MLUSBBusSnapshotStatus *status) {
    if (status != NULL) {
        *status = MLUSBBusSnapshotStatusBusUnreadable;
    }

    CFDictionaryRef deviceMatch = IOServiceMatching("IOUSBHostDevice");
    if (deviceMatch == NULL) {
        return @[];
    }

    io_iterator_t devices = IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, deviceMatch, &devices) != KERN_SUCCESS ||
        devices == IO_OBJECT_NULL) {
        return @[];
    }

    NSMutableArray<NSDictionary *> *deviceNodes = [NSMutableArray array];
    NSMutableArray<NSString *> *deviceIDs = [NSMutableArray array];
    NSMutableArray<NSDictionary *> *interfaceNodes = [NSMutableArray array];
    NSMutableArray<NSString *> *interfaceParentIDs = [NSMutableArray array];
    NSMutableSet<NSString *> *interfacesAlreadyCollected = [NSMutableSet set];

    io_service_t device = IO_OBJECT_NULL;
    while ((device = IOIteratorNext(devices)) != IO_OBJECT_NULL) {
        NSDictionary *deviceProperties = MLUSBBusNodeProperties(device);
        if (deviceProperties != nil) {
            [deviceNodes addObject:deviceProperties];
            [deviceIDs addObject:MLUSBBusEntryID(device) ?: @""];
        }

        io_iterator_t children = IO_OBJECT_NULL;
        if (IORegistryEntryGetChildIterator(device, kIOServicePlane, &children) == KERN_SUCCESS) {
            io_registry_entry_t child = IO_OBJECT_NULL;
            while ((child = IOIteratorNext(children)) != IO_OBJECT_NULL) {
                NSDictionary *childProperties = MLUSBBusNodeProperties(child);
                if (childProperties == nil ||
                    MLUSBBusNodeRoleForPropertyKeys([NSSet setWithArray:
                        [childProperties allKeys]]) != MLUSBBusNodeRoleInterface) {
                    // A hub driver, a composite helper, a user-client object. Not an interface.
                    IOObjectRelease(child);
                    continue;
                }
                NSString *childID = MLUSBBusEntryID(child);
                if (childID == nil ||
                    [interfacesAlreadyCollected containsObject:childID]) {
                    // Collected under the device that named it first. The registry was not
                    // observed to name one interface twice, and if it ever does, the reading
                    // should carry one interface rather than two.
                    IOObjectRelease(child);
                    continue;
                }
                [interfacesAlreadyCollected addObject:childID];
                [interfaceNodes addObject:childProperties];
                [interfaceParentIDs addObject:MLUSBBusSoleParentID(child) ?: @""];
                IOObjectRelease(child);
            }
            IOObjectRelease(children);
        }
        IOObjectRelease(device);
    }
    IOObjectRelease(devices);

    NSArray<NSArray<NSDictionary *> *> *groups = MLUSBBusGroupNodes(
        deviceNodes, deviceIDs, interfaceNodes, interfaceParentIDs);

    NSMutableArray<MLUSBDeviceIdentity *> *identities =
        [NSMutableArray arrayWithCapacity:groups.count];
    for (NSArray<NSDictionary *> *group in groups) {
        [identities addObject:MLUSBBusDeviceIdentityFromGroup(group)];
    }

    if (status != NULL) {
        *status = MLUSBBusSnapshotStatusRead;
    }
    return [identities copy];
}
