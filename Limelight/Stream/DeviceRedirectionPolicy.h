//
//  DeviceRedirectionPolicy.h
//  Moonlight
//
//  The decision layer for handing a USB device over to a streaming host.
//
//  Nothing in here opens a device, loads a driver, or sends a byte: it answers one
//  question -- may this device be offered to that host -- and every answer that has
//  not been earned is a refusal. Stage 0 of docs/usb-redirection-design.md exists
//  because the parts that can be built today (a policy that cannot be talked into
//  saying yes, and a capability check that cannot be talked into lying) are the
//  parts that must exist before the parts that need a signed driver extension and a
//  cooperating host are ever built.
//

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// One interface of a device. A USB device is a bundle of interfaces, and a policy
/// that only looked at the device's first class code would let a composite device --
/// a hub that is also a keyboard, a dock that is also a security key -- choose which
/// of its faces the policy saw.
@interface MLUSBInterfaceDescriptor : NSObject
@property(nonatomic, readonly) unsigned char majorClass;
@property(nonatomic, readonly) unsigned char minorClass;
@property(nonatomic, readonly) unsigned char protocolClass;
- (instancetype)initWithMajorClass:(unsigned char)majorClass
                        minorClass:(unsigned char)minorClass
                     protocolClass:(unsigned char)protocolClass;
/// A keyboard or a mouse the host would be able to drive before any driver loads. On
/// the machine that is typing a passphrase these are the two classes that can take the
/// machine over, so redirecting one is a different decision from redirecting a scanner.
@property(nonatomic, readonly) BOOL isBootInputInterface;
@end

/// What the client can claim about a device it is looking at. A field the client could
/// not read stays nil rather than being guessed at, because a guess reaches the policy
/// looking exactly like a match.
@interface MLUSBDeviceDescriptor : NSObject
@property(nonatomic, readonly, nullable) NSNumber *vendorID;
@property(nonatomic, readonly, nullable) NSNumber *productID;
@property(nonatomic, readonly, nullable) NSString *serialNumber;
@property(nonatomic, readonly) NSArray<MLUSBInterfaceDescriptor *> *interfaces;
+ (instancetype)descriptorWithVendorID:(nullable NSNumber *)vendorID
                             productID:(nullable NSNumber *)productID
                            interfaces:(NSArray<MLUSBInterfaceDescriptor *> *)interfaces;
+ (instancetype)descriptorWithVendorID:(nullable NSNumber *)vendorID
                             productID:(nullable NSNumber *)productID
                          serialNumber:(nullable NSString *)serialNumber
                            interfaces:(NSArray<MLUSBInterfaceDescriptor *> *)interfaces;
@end

/// One entry of the allow list. A rule is the only thing that can produce a yes, and it
/// has to name a device it could exist: a rule that carries a sentinel vendor id, or
/// that covers a whole vendor's products without saying so, matches nothing at all.
@interface MLDeviceRedirectionRule : NSObject
@property(nonatomic, readonly) unsigned short vendorID;
@property(nonatomic, readonly) unsigned short productID;
@property(nonatomic, readonly) BOOL productIsWildcard;
@property(nonatomic, readonly) BOOL enabled;
@property(nonatomic, readonly, copy, nullable) NSString *note;
+ (instancetype)ruleForVendorID:(unsigned short)vendorID
                      productID:(unsigned short)productID
                        enabled:(BOOL)enabled;
+ (instancetype)familyRuleForVendorID:(unsigned short)vendorID
                              enabled:(BOOL)enabled;
/// False for a rule that could never describe a device. Inert is deliberate: the
/// alternative is a typo that quietly authorises every device on the bus.
@property(nonatomic, readonly) BOOL isWellFormed;
@end

/// The reason behind a refusal, because "not allowed" is not something a player can act
/// on. These are reported to the log and the diagnostics panel, never used to decide.
typedef NS_ENUM(NSInteger, MLDeviceRedirectionOutcome) {
    MLDeviceRedirectionOutcomeDenied = 0,
    MLDeviceRedirectionOutcomeAllowed = 1,
};

typedef NS_ENUM(NSInteger, MLDeviceRedirectionDenial) {
    MLDeviceRedirectionDenialNone = 0,
    MLDeviceRedirectionDenialFeatureDisabled = 1,
    MLDeviceRedirectionDenialHostUnpaired = 2,
    MLDeviceRedirectionDenialHostUnsupported = 3,
    MLDeviceRedirectionDenialIdentityIncomplete = 4,
    MLDeviceRedirectionDenialClassReserved = 5,
    MLDeviceRedirectionDenialLocalInputReserved = 6,
    MLDeviceRedirectionDenialClassNotAllowed = 7,
    MLDeviceRedirectionDenialRuleDisabled = 8,
    MLDeviceRedirectionDenialNoRule = 9,
};

@interface MLDeviceRedirectionVerdict : NSObject
@property(nonatomic, readonly) MLDeviceRedirectionOutcome outcome;
@property(nonatomic, readonly) MLDeviceRedirectionDenial denial;
@property(nonatomic, readonly) NSInteger ruleIndex;
/// A stable, non-reversible handle on the device for the audit trail. A serial number
/// is a personal identifier; the log gets a digest of it and nothing else.
@property(nonatomic, readonly, copy) NSString *deviceToken;
@property(nonatomic, readonly) BOOL isAllowed;
/// One line, safe to log, and the only form this verdict should ever reach disk in.
@property(nonatomic, readonly, copy) NSString *auditLine;
@end

/// The whole state the decision depends on, passed in rather than read from anywhere.
/// A policy that consulted NSUserDefaults, the clock, or the attached-device list could
/// not be replayed, and a refusal nobody can replay is a bug report nobody can close.
@interface MLDeviceRedirectionPolicy : NSObject
@property(nonatomic, readonly) BOOL featureEnabled;
@property(nonatomic, readonly) BOOL hostIsPaired;
@property(nonatomic, readonly) BOOL hostSupportsDeviceRedirection;
@property(nonatomic, readonly) NSSet<NSNumber *> *allowedInterfaceClasses;
@property(nonatomic, readonly) BOOL localInputDevicesAllowed;
@property(nonatomic, readonly) NSArray<MLDeviceRedirectionRule *> *rules;

/// What the application ships with: nothing enabled, nothing allowed, nothing paired.
+ (instancetype)lockedDownPolicy;
- (instancetype)initWithFeatureEnabled:(BOOL)featureEnabled
                          hostIsPaired:(BOOL)hostIsPaired
           hostSupportsDeviceRedirection:(BOOL)hostSupportsDeviceRedirection
                 allowedInterfaceClasses:(nullable NSSet<NSNumber *> *)allowedInterfaceClasses
                localInputDevicesAllowed:(BOOL)localInputDevicesAllowed
                                   rules:(nullable NSArray<MLDeviceRedirectionRule *> *)rules;

- (MLDeviceRedirectionVerdict *)verdictForDevice:(MLUSBDeviceDescriptor *)device;

/// Interface classes no rule can reach. Asked by the diagnostics panel so it can say
/// why a rule it just accepted will never fire, instead of accepting it in silence.
+ (BOOL)isReservedInterfaceClass:(unsigned char)majorClass;
/// Whether a host's /serverinfo answers the question at all. Anything that is not an
/// explicit yes is a no: an old host, a host that answers nothing, and a host whose
/// answer could not be parsed all get the same refusal as a host that said no.
+ (BOOL)hostAdvertisesDeviceRedirectionInServerInfo:(nullable NSDictionary<NSString *, id> *)serverInfo;
@end

NS_ASSUME_NONNULL_END
