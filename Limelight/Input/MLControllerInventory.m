//
//  MLControllerInventory.m
//  Moonlight for macOS
//

#import "MLControllerInventory.h"

// The ids, and the reason each one is here. This comment block used to live inside the
// axis-layout predicates; it moved with the table rather than being copied, because the
// day two lists of these ids disagree is the day a Zeus pad lands on the Xbox axis map.
//
// Microsoft (0x045E):
//   0x02FD Xbox One (original GIP), 0x0B00 Xbox Elite 2 (BTH), 0x0B05 Xbox Elite 2 (USB),
//   0x0B13 Xbox Series X|S, 0x0B22 Xbox Elite Series 2 Core.
//   0x02E0 is deliberately absent: it is a KingKong product id borrowing the Microsoft
//   vendor id, and KingKong must win that pair -- KingKong reports the right stick on Rx/Ry
//   and the triggers on Z/Rz, while Xbox reports the right stick on Z/Rz.
// Betop / KingKong: 0x2DC8:0x2000/0x2020/0x2100 (BTP-A1T2/A1U2/A1S2).
// Sony: 0x054C:0x09CC and 0x05C4 are DualShock 4 (wired and BT), 0x0CE6 is DualSense.
// Nintendo: 0x057E:0x2009 is the Pro Controller. The single Joy-Cons (0x2006 left, 0x2007
//   right) are absent on purpose for now -- their report layout differs from the Pro's, so
//   claiming them here before the parser reads them would hand a Joy-Con the wrong map.
static MLControllerFamily MLControllerFamilyForKnownPair(NSUInteger vendorId, NSUInteger productId) {
    switch (vendorId) {
        case 0x045E:
            if (productId == 0x02FD || productId == 0x0B00 || productId == 0x0B05 ||
                productId == 0x0B13 || productId == 0x0B22) {
                return MLControllerFamilyXbox;
            }
            if (productId == 0x02E0) {
                return MLControllerFamilyKingKong;
            }
            break;
        case 0x2DC8:
            if (productId == 0x2000 || productId == 0x2020 || productId == 0x2100) {
                return MLControllerFamilyKingKong;
            }
            break;
        case 0x054C:
            if (productId == 0x09CC || productId == 0x05C4) {
                return MLControllerFamilyPS4;
            }
            if (productId == 0x0CE6) {
                return MLControllerFamilyPS5;
            }
            break;
        case 0x057E:
            if (productId == 0x2009) {
                return MLControllerFamilyNintendo;
            }
            break;
        default:
            break;
    }
    return MLControllerFamilyUnknown;
}

MLControllerFamily MLControllerFamilyForIds(NSUInteger vendorId, NSUInteger productId) {
    return MLControllerFamilyForKnownPair(vendorId, productId);
}

NSString *MLControllerFamilyName(MLControllerFamily family) {
    switch (family) {
        case MLControllerFamilyXbox: return @"xbox";
        case MLControllerFamilyKingKong: return @"kingkong";
        case MLControllerFamilyPS4: return @"ps4";
        case MLControllerFamilyPS5: return @"ps5";
        case MLControllerFamilyNintendo: return @"nintendo";
        case MLControllerFamilyUnknown: break;
    }
    return @"unknown";
}

uint8_t MLControllerProtocolTypeForFamily(MLControllerFamily family) {
    // LI_CTYPE_* from Limelight.h. Named by number rather than included here so this file
    // stays free of the protocol header: the identity table answers a question about a
    // device, and it must not start depending on which host protocol is compiled in.
    switch (family) {
        case MLControllerFamilyXbox:
        case MLControllerFamilyKingKong: return 0x01; // LI_CTYPE_XBOX
        case MLControllerFamilyPS4:
        case MLControllerFamilyPS5: return 0x02;      // LI_CTYPE_PS
        case MLControllerFamilyNintendo: return 0x03; // LI_CTYPE_NINTENDO
        case MLControllerFamilyUnknown: break;
    }
    return 0x00; // LI_CTYPE_UNKNOWN
}

NSString *MLControllerDriverNameForIndex(NSInteger index) {
    switch (index) {
        case 0: return @"HID";
        case 1: return @"MFi";
        default: return @"unknown";
    }
}

@implementation MLControllerEntry

- (id)copyWithZone:(NSZone *)zone {
    MLControllerEntry *copy = [[MLControllerEntry allocWithZone:zone] init];
    copy.vendorId = self.vendorId;
    copy.productId = self.productId;
    copy.family = self.family;
    copy.transport = self.transport;
    copy.hasBatteryPercent = self.hasBatteryPercent;
    copy.batteryPercent = self.batteryPercent;
    copy.nodeCount = self.nodeCount;
    return copy;
}

/// Identity grouping, not physical device identity: identical pads share this key too.
- (NSString *)identityKey {
    return [NSString stringWithFormat:@"%04lx:%04lx:%ld",
            (unsigned long)self.vendorId, (unsigned long)self.productId, (long)self.family];
}

@end

@implementation MLControllerInventorySnapshot

- (id)copyWithZone:(NSZone *)zone {
    MLControllerInventorySnapshot *copy = [[MLControllerInventorySnapshot allocWithZone:zone] init];
    copy.entries = self.entries;
    copy.generations = self.generations;
    copy.recordingNow = self.recordingNow;
    copy.driverName = self.driverName;
    copy.advertisedControllerArrivals = self.advertisedControllerArrivals;
    return copy;
}

@end

@interface MLControllerInventory ()
@property (nonatomic, strong, nullable) MLControllerInventorySnapshot *snapshot;
@property (nonatomic) NSUInteger generations;
@property (nonatomic) BOOL recording;
@end

@implementation MLControllerInventory

+ (MLControllerInventory *)sharedInventory {
    static MLControllerInventory *shared;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        shared = [[MLControllerInventory alloc] init];
    });
    return shared;
}

- (void)recordEntries:(NSArray<MLControllerEntry *> *)entries {
    NSAssert(NSThread.isMainThread, @"the inventory is written where the HID manager runs");
    MLControllerInventorySnapshot *previous = self.snapshot;
    NSMutableArray<MLControllerEntry *> *merged = [NSMutableArray array];
    NSMutableDictionary<NSString *, MLControllerEntry *> *rows = [NSMutableDictionary dictionary];
    for (MLControllerEntry *entry in entries) {
        MLControllerEntry *existing = rows[entry.identityKey];
        if (existing != nil) {
            existing.nodeCount += 1;
            // One pad presents several nodes and not all of them answer for the battery or
            // the transport, so the first node that reports a fact wins it.
            if (existing.transport.length == 0) {
                existing.transport = entry.transport;
            }
            if (!existing.hasBatteryPercent && entry.hasBatteryPercent) {
                existing.hasBatteryPercent = YES;
                existing.batteryPercent = entry.batteryPercent;
            }
            continue;
        }
        MLControllerEntry *row = [entry copy];
        row.nodeCount = 1;
        rows[row.identityKey] = row;
        [merged addObject:row];
    }
    // A stable order so two reports of the same bench read the same way: known families
    // first, then by id. Enumeration order from IOKit is not that.
    [merged sortUsingComparator:^NSComparisonResult(MLControllerEntry *left, MLControllerEntry *right) {
        if (left.family != right.family) {
            // Unknown last, rather than first among names.
            NSInteger leftRank = left.family == MLControllerFamilyUnknown ? INT_MAX : left.family;
            NSInteger rightRank = right.family == MLControllerFamilyUnknown ? INT_MAX : right.family;
            return leftRank < rightRank ? NSOrderedAscending : NSOrderedDescending;
        }
        if (left.vendorId != right.vendorId) {
            return left.vendorId < right.vendorId ? NSOrderedAscending : NSOrderedDescending;
        }
        if (left.productId != right.productId) {
            return left.productId < right.productId ? NSOrderedAscending : NSOrderedDescending;
        }
        return NSOrderedSame;
    }];

    MLControllerInventorySnapshot *snapshot = [[MLControllerInventorySnapshot alloc] init];
    snapshot.entries = [merged copy];
    snapshot.generations = self.generations;
    snapshot.recordingNow = self.recording;
    snapshot.driverName = previous.driverName;
    snapshot.advertisedControllerArrivals = previous.advertisedControllerArrivals;
    self.snapshot = snapshot;
}

- (void)noteSessionStarted {
    [self noteSessionStartedWithDriverName:nil];
}

- (void)noteSessionStartedWithDriverName:(NSString *_Nullable)driverName {
    NSAssert(NSThread.isMainThread, @"the inventory is written where the HID manager runs");
    self.generations += 1;
    self.recording = YES;
    MLControllerInventorySnapshot *snapshot = [self.snapshot copy];
    if (snapshot == nil) {
        snapshot = [[MLControllerInventorySnapshot alloc] init];
        snapshot.entries = @[];
    }
    snapshot.recordingNow = YES;
    snapshot.generations = self.generations;
    snapshot.driverName = driverName;
    // 0.1 does not send controller arrival packets. M1 owns the hop from this flag to YES.
    snapshot.advertisedControllerArrivals = NO;
    self.snapshot = snapshot;
}

- (void)noteSessionStopped {
    NSAssert(NSThread.isMainThread, @"the inventory is written where the HID manager runs");
    self.recording = NO;
    // Keep the entries: the report is usually copied after the session that would have
    // answered is over. Only the claim that a stream is running now has to be withdrawn.
    MLControllerInventorySnapshot *previous = self.snapshot;
    if (previous == nil) {
        return;
    }
    MLControllerInventorySnapshot *snapshot = [previous copy];
    snapshot.recordingNow = NO;
    self.snapshot = snapshot;
}

- (MLControllerInventorySnapshot *)snapshot {
    return _snapshot;
}

@end
