//
//  MLControllerInventory.h
//  Moonlight for macOS
//
//  Which controller a vendor/product pair is, and what was on the bus the last time a
//  stream looked.
//
//  Two things live here because they are the same knowledge held at two moments.
//
//  The classification is the single table the axis-layout predicates ask, so what a report
//  prints cannot disagree with the packets the app decodes, and the controller arrival
//  event -- when it arrives -- cannot be handed a second id list that drifted. The overlap
//  that makes one table necessary is a Betop device borrowing Microsoft's vendor id: only
//  one owner of that pair may win, and two tables disagreeing about who wins is exactly how
//  a Zeus pad ends up on the wrong axis map.
//
//  The snapshot exists because the report is read after the session that would have
//  answered is over, and because a report must not go hunting on the bus: the player
//  copying one is usually the one whose device is already misbehaving. So the list is
//  recorded by the code that already owns a controller HID manager -- at stream start and
//  on every arrival and removal it is told about -- and the report reads that record.
//  Hot plug and unplug keep it current, which is why an idle app still has something
//  honest to say.
//

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// The HID report layout family a device belongs to. Named for the question it answers --
/// how to read this device's packets and address its motors -- rather than for a brand,
/// because a borrowed vendor id is only settled by the layout question.
typedef NS_ENUM(NSInteger, MLControllerFamily) {
    MLControllerFamilyUnknown = 0,
    MLControllerFamilyXbox,
    /// KingKong / Betop Zeus: the axis order differs from the Xbox layout whose ids it borrows.
    MLControllerFamilyKingKong,
    MLControllerFamilyPS4,
    MLControllerFamilyPS5,
    MLControllerFamilyNintendo,
};

/// One controller identity the app has seen, described by the facts a report needs and
/// nothing that identifies the player: no product string, because a DualSense can be
/// renamed by its owner, and no serial number, for the reason the report refuses a host
/// MAC address.
@interface MLControllerEntry : NSObject <NSCopying>
@property (nonatomic) NSUInteger vendorId;
@property (nonatomic) NSUInteger productId;
@property (nonatomic) MLControllerFamily family;
/// The IOHID transport string when the device publishes one ("USB", "Bluetooth"), else nil.
@property (nonatomic, copy, nullable) NSString *transport;
/// The battery percentage the device publishes, when it publishes one. Best effort: Apple
/// defines no key for this property in its SDK headers, so absence is an expected answer
/// and prints as one rather than as a fault.
@property (nonatomic) BOOL hasBatteryPercent;
@property (nonatomic) NSInteger batteryPercent;
/// How many HID nodes share this identity. One Pro Controller over Bluetooth presents more
/// than one, so a row is an identity and its node count, not a promise about device count.
@property (nonatomic) NSUInteger nodeCount;
@end

/// Recorded HID identities and metadata from the current or most recent session.
@interface MLControllerInventorySnapshot : NSObject <NSCopying>
@property (nonatomic, copy) NSArray<MLControllerEntry *> *entries;
@property (nonatomic) NSUInteger generations;
@property (nonatomic) BOOL recordingNow;
/// The driver captured at session start: "HID", "MFi", or "unknown".
/// nil means no driver was recorded for this session.
@property (nonatomic, copy, nullable) NSString *driverName;
/// Whether controller arrival packets were sent to the host for the recorded stream.
/// The 0.1 probe left this NO; M1 sets it when an arrival event actually goes out.
@property (nonatomic) BOOL advertisedControllerArrivals;
/// What the host was told for each arriving pad, in the LI_CTYPE_* numbering. The
/// record is the arrival event itself, so an empty dictionary reads as "nothing was
/// sent" even though the arrival flag says a stream ran.
@property (nonatomic, copy) NSDictionary<NSNumber *, NSNumber *> *advertisedControllerTypes;
@end

/// The layout family for a vendor/product pair. A zero id is a legal read -- some devices
/// report none -- so "unknown" here means "not a layout this app knows", never "missing".
FOUNDATION_EXPORT MLControllerFamily MLControllerFamilyForIds(NSUInteger vendorId, NSUInteger productId);

/// The family name for a log line or a report line. English on purpose, like every other
/// report and log string: the reader is whoever triages a report, not the player.
FOUNDATION_EXPORT NSString *MLControllerFamilyName(MLControllerFamily family);

/// The protocol type candidate, in the `LI_CTYPE_*` numbering. This mapping does not send
/// an arrival event or prove the host received it. Unrecognized families return 0.
FOUNDATION_EXPORT uint8_t MLControllerProtocolTypeForFamily(MLControllerFamily family);

/// The name a protocol type reads as in a report, for ids that have no layout family.
/// `MLControllerProtocolTypeForFamily` cannot answer this one: a Valve Steam Controller
/// reports through the standard HID layout, so it has no family, yet the arrival we send
/// for it does carry `LI_CTYPE_STEAM`. The name table lives here rather than in the report
/// builder so the sender and the report cannot call the same id by different names.
/// Unknown ids return nil, and the caller prints `unknown` instead of guessing.
FOUNDATION_EXPORT NSString *_Nullable MLControllerProtocolTypeName(uint8_t protocolType);

/// The settings index used by the input path, without assuming an invalid value is HID.
FOUNDATION_EXPORT NSString *MLControllerDriverNameForIndex(NSInteger index);

/// The process-wide inventory. Everything happens on the main queue, which is where the HID
/// manager is scheduled and where the report is assembled.
@interface MLControllerInventory : NSObject
@property (class, readonly) MLControllerInventory *sharedInventory;

/// Replace the recorded identities with what the caller's manager sees right now, leaving
/// the session tally alone. The entries are built by the caller because it is the code that
/// owns the manager. The list replaces rather than appends, so a device that came and went
/// cannot be reported as still present.
- (void)recordEntries:(NSArray<MLControllerEntry *> *)entries;

/// A streaming session started without a recorded driver.
- (void)noteSessionStarted;

/// Record the driver at session start. A missing name clears the previous session's name.
- (void)noteSessionStartedWithDriverName:(nullable NSString *)driverName;

/// A controller was told to the host. The type is what the arrival event carried,
/// the slot its player index. Called from the main thread, like the rest of the record.
- (void)noteControllerArrival:(NSInteger)playerIndex protocolType:(uint8_t)protocolType;

/// That session ended. The tally stays and the entries stay -- a report read afterwards is
/// exactly the case the record exists for -- but it stops claiming the bench is in use.
- (void)noteSessionStopped;

/// The last snapshot, or nil when this process has never looked -- which reads as absence,
/// not as a session in which nothing was plugged in.
@property (nonatomic, readonly, nullable) MLControllerInventorySnapshot *snapshot;
@end

NS_ASSUME_NONNULL_END
