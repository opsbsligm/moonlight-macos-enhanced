//
//  DeviceRedirectionPolicy.m
//  Moonlight
//
//  One decision, made once, from the state it was handed. See the header for what this
//  layer is for, and docs/usb-redirection-design.md for why a yes has to be this hard.
//

#import "DeviceRedirectionPolicy.h"

#import <CommonCrypto/CommonDigest.h>

// Named here and nowhere else, because a class code that appears as a bare number in a
// condition is a class code whose meaning has to be looked up by whoever reads it next.
enum {
    MLUSBClassHID = 0x03,
    MLUSBClassPrinter = 0x07,
    MLUSBClassMassStorage = 0x08,
    // One code covers both smart cards and content-security devices (FIDO keys), which is
    // convenient: both are the thing a user authenticates with.
    MLUSBClassChipSmartCard = 0x0B,
    MLUSBClassDiagnostic = 0xDC,
};

enum {
    // The HID interface protocol that means "no driver is needed to use this", which is
    // the same thing as "the host can use this before anything local can stop it".
    MLHIDInterfaceProtocolKeyboard = 0x01,
    MLHIDInterfaceProtocolMouse = 0x02,
};

// A device that reports either of these for a vendor or product id has not reported it.
// Reading them as unread can only ever refuse a device, which is the safe direction.
static const unsigned short MLUSBIdentityUnread = 0x0000;
static const unsigned short MLUSBIdentityUnknown = 0xFFFF;

// The protocol byte that means "not read". 0 is a real protocol (no boot protocol), so
// it cannot double as the absence of one.
static const unsigned char MLUSBProtocolUnread = 0xFF;

// The tag a host would answer in /serverinfo. Stage 0 reads it and nothing else: no host
// answers it today, and the refusal it produces is the honest one.
static NSString *const MLDeviceRedirectionServerInfoTag = @"usbRedirection";

// What a verdict was about, carried on the verdict so the audit line can name the device
// without the policy having to keep a copy of the world somewhere it could go stale.
@interface MLDeviceRedirectionVerdict ()
@property(nonatomic, readwrite) MLDeviceRedirectionOutcome outcome;
@property(nonatomic, readwrite) MLDeviceRedirectionDenial denial;
@property(nonatomic, readwrite) NSInteger ruleIndex;
@property(nonatomic, readwrite, copy) NSString *deviceToken;
@property(nonatomic, copy, nullable) NSNumber *subjectVendorID;
@property(nonatomic, copy, nullable) NSNumber *subjectProductID;
@property(nonatomic, copy) NSArray<MLUSBInterfaceDescriptor *> *subjectInterfaces;
+ (instancetype)verdictWithOutcome:(MLDeviceRedirectionOutcome)outcome
                            denial:(MLDeviceRedirectionDenial)denial
                         ruleIndex:(NSInteger)ruleIndex
                            device:(nullable MLUSBDeviceDescriptor *)device
                       deviceToken:(NSString *)deviceToken;
@end

@implementation MLUSBInterfaceDescriptor {
    BOOL _protocolIsKnown;
}
- (instancetype)initWithMajorClass:(unsigned char)majorClass
                        minorClass:(unsigned char)minorClass
                     protocolClass:(unsigned char)protocolClass {
    self = [super init];
    if (self) {
        _majorClass = majorClass;
        _minorClass = minorClass;
        _protocolClass = protocolClass;
        _protocolIsKnown = YES;
    }
    return self;
}

+ (instancetype)interfaceWithMajorClass:(unsigned char)majorClass
                             minorClass:(unsigned char)minorClass
                          protocolKnown:(BOOL)protocolKnown {
    MLUSBInterfaceDescriptor *interface = [[MLUSBInterfaceDescriptor alloc] initWithMajorClass:majorClass
                                                                                    minorClass:minorClass
                                                                                 protocolClass:protocolKnown ? 0 : MLUSBProtocolUnread];
    interface->_protocolIsKnown = protocolKnown;
    return interface;
}

- (BOOL)isBootInputInterface {
    if (self.majorClass != MLUSBClassHID) {
        return NO;
    }
    // An HID interface whose protocol byte was never read is treated as boot capable.
    // Refusing on missing information costs somebody a device they have to enable; guessing
    // zero would hand a keyboard to a host on the strength of a byte nobody read.
    if (!_protocolIsKnown) {
        return YES;
    }
    return self.protocolClass == MLHIDInterfaceProtocolKeyboard ||
           self.protocolClass == MLHIDInterfaceProtocolMouse;
}
@end

@implementation MLUSBDeviceDescriptor
+ (instancetype)descriptorWithVendorID:(NSNumber *)vendorID
                             productID:(NSNumber *)productID
                            interfaces:(NSArray<MLUSBInterfaceDescriptor *> *)interfaces {
    return [self descriptorWithVendorID:vendorID
                              productID:productID
                           serialNumber:nil
                             interfaces:interfaces];
}

+ (instancetype)descriptorWithVendorID:(NSNumber *)vendorID
                             productID:(NSNumber *)productID
                          serialNumber:(NSString *)serialNumber
                            interfaces:(NSArray<MLUSBInterfaceDescriptor *> *)interfaces {
    MLUSBDeviceDescriptor *descriptor = [[MLUSBDeviceDescriptor alloc] init];
    descriptor->_vendorID = [vendorID copy];
    descriptor->_productID = [productID copy];
    descriptor->_serialNumber = [serialNumber copy];
    descriptor->_interfaces = interfaces ? [interfaces copy] : @[];
    return descriptor;
}
@end

@implementation MLDeviceRedirectionRule
+ (instancetype)ruleForVendorID:(unsigned short)vendorID
                      productID:(unsigned short)productID
                        enabled:(BOOL)enabled {
    MLDeviceRedirectionRule *rule = [[MLDeviceRedirectionRule alloc] init];
    rule->_vendorID = vendorID;
    rule->_productID = productID;
    rule->_productIsWildcard = NO;
    rule->_enabled = enabled;
    return rule;
}

+ (instancetype)familyRuleForVendorID:(unsigned short)vendorID enabled:(BOOL)enabled {
    MLDeviceRedirectionRule *rule = [[MLDeviceRedirectionRule alloc] init];
    rule->_vendorID = vendorID;
    rule->_productID = MLUSBIdentityUnknown;
    rule->_productIsWildcard = YES;
    rule->_enabled = enabled;
    return rule;
}

- (BOOL)isWellFormed {
    if (self.vendorID == MLUSBIdentityUnread || self.vendorID == MLUSBIdentityUnknown) {
        return NO;
    }
    if (self.productIsWildcard) {
        return YES;
    }
    return self.productID != MLUSBIdentityUnread && self.productID != MLUSBIdentityUnknown;
}
@end

NSString *MLDeviceRedirectionDenialName(MLDeviceRedirectionDenial denial) {
    switch (denial) {
        case MLDeviceRedirectionDenialNone:
            return @"none";
        case MLDeviceRedirectionDenialFeatureDisabled:
            return @"feature-disabled";
        case MLDeviceRedirectionDenialHostUnpaired:
            return @"host-unpaired";
        case MLDeviceRedirectionDenialHostUnsupported:
            return @"host-unsupported";
        case MLDeviceRedirectionDenialIdentityIncomplete:
            return @"identity-incomplete";
        case MLDeviceRedirectionDenialClassReserved:
            return @"class-reserved";
        case MLDeviceRedirectionDenialLocalInputReserved:
            return @"local-input-reserved";
        case MLDeviceRedirectionDenialClassNotAllowed:
            return @"class-not-allowed";
        case MLDeviceRedirectionDenialRuleDisabled:
            return @"rule-disabled";
        case MLDeviceRedirectionDenialNoRule:
            return @"no-rule";
    }
    // Reaching this needs an enum value that no case names. A name that cannot be
    // mistaken for a refusal the policy chose is better than a default that quietly
    // reads as one of them.
    return @"unclassified";
}

NSString *MLUSBIdentityName(NSNumber *identity) {
    if (identity == nil) {
        return @"unread";
    }
    return [NSString stringWithFormat:@"%04x", (unsigned short)[identity unsignedShortValue]];
}

NSString *MLUSBInterfaceClassNames(NSArray<MLUSBInterfaceDescriptor *> *interfaces) {
    NSMutableArray<NSString *> *classes = [NSMutableArray array];
    for (MLUSBInterfaceDescriptor *interface in interfaces) {
        [classes addObject:[NSString stringWithFormat:@"%02x", interface.majorClass]];
    }
    return classes.count ? [classes componentsJoinedByString:@" "] : @"none";
}

@implementation MLDeviceRedirectionVerdict
+ (instancetype)verdictWithOutcome:(MLDeviceRedirectionOutcome)outcome
                            denial:(MLDeviceRedirectionDenial)denial
                         ruleIndex:(NSInteger)ruleIndex
                            device:(MLUSBDeviceDescriptor *)device
                       deviceToken:(NSString *)deviceToken {
    MLDeviceRedirectionVerdict *verdict = [[MLDeviceRedirectionVerdict alloc] init];
    verdict.outcome = outcome;
    verdict.denial = denial;
    verdict.ruleIndex = ruleIndex;
    verdict.deviceToken = [deviceToken copy];
    verdict.subjectVendorID = device.vendorID;
    verdict.subjectProductID = device.productID;
    verdict.subjectInterfaces = device.interfaces ?: @[];
    return verdict;
}

- (BOOL)isAllowed {
    return self.outcome == MLDeviceRedirectionOutcomeAllowed;
}

- (NSString *)auditLine {
    return [NSString stringWithFormat:@"device redirection: %@ vid=%@ pid=%@ classes=%@ token=%@ reason=%@ rule=%ld",
                                      self.isAllowed ? @"allow" : @"deny",
                                      MLUSBIdentityName(self.subjectVendorID),
                                      MLUSBIdentityName(self.subjectProductID),
                                      MLUSBInterfaceClassNames(self.subjectInterfaces),
                                      self.deviceToken.length ? self.deviceToken : @"none",
                                      MLDeviceRedirectionDenialName(self.denial),
                                      (long)self.ruleIndex];
}
@end

NSString *MLUSBDeviceAuditToken(NSString *serialNumber) {
    if (serialNumber.length == 0) {
        return @"none";
    }
    NSData *data = [serialNumber dataUsingEncoding:NSUTF8StringEncoding];
    if (data.length == 0) {
        return @"none";
    }
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes, (CC_LONG)data.length, digest);
    NSMutableString *token = [NSMutableString stringWithCapacity:8];
    for (int i = 0; i < 4; i++) {
        [token appendFormat:@"%02x", digest[i]];
    }
    return token;
}

static BOOL MLIdentityIsReadable(NSNumber *identity) {
    if (identity == nil) {
        return NO;
    }
    const long long value = [identity longLongValue];
    // Both ends of the range are unread: zero is what an unread field reads as, and all
    // ones is what a device reports when it has no answer. A rule is held to the same
    // pair, so a sentinel can never line up with a sentinel and look like a match.
    if (value <= (long long)MLUSBIdentityUnread || value >= (long long)MLUSBIdentityUnknown) {
        return NO;
    }
    return YES;
}

@implementation MLDeviceRedirectionPolicy

- (MLDeviceRedirectionVerdict *)denialFor:(MLDeviceRedirectionDenial)denial
                                   device:(MLUSBDeviceDescriptor *)device
                                    token:(NSString *)token
                                ruleIndex:(NSInteger)ruleIndex {
    return [MLDeviceRedirectionVerdict verdictWithOutcome:MLDeviceRedirectionOutcomeDenied
                                                   denial:denial
                                                ruleIndex:ruleIndex
                                                   device:device
                                              deviceToken:token];
}

+ (instancetype)lockedDownPolicy {
    return [[MLDeviceRedirectionPolicy alloc] initWithFeatureEnabled:NO
                                                       hostIsPaired:NO
                                        hostSupportsDeviceRedirection:NO
                                            allowedInterfaceClasses:nil
                                           localInputDevicesAllowed:NO
                                                              rules:nil];
}

- (instancetype)initWithFeatureEnabled:(BOOL)featureEnabled
                          hostIsPaired:(BOOL)hostIsPaired
           hostSupportsDeviceRedirection:(BOOL)hostSupportsDeviceRedirection
                 allowedInterfaceClasses:(NSSet<NSNumber *> *)allowedInterfaceClasses
                localInputDevicesAllowed:(BOOL)localInputDevicesAllowed
                                   rules:(NSArray<MLDeviceRedirectionRule *> *)rules {
    self = [super init];
    if (self) {
        _featureEnabled = featureEnabled;
        _hostIsPaired = hostIsPaired;
        _hostSupportsDeviceRedirection = hostSupportsDeviceRedirection;
        _allowedInterfaceClasses = allowedInterfaceClasses ? [allowedInterfaceClasses copy] : [NSSet set];
        _localInputDevicesAllowed = localInputDevicesAllowed;
        _rules = rules ? [rules copy] : @[];
    }
    return self;
}

+ (BOOL)isReservedInterfaceClass:(unsigned char)majorClass {
    return majorClass == MLUSBClassChipSmartCard || majorClass == MLUSBClassDiagnostic;
}

+ (BOOL)hostAdvertisesDeviceRedirectionInServerInfo:(NSDictionary<NSString *, id> *)serverInfo {
    id value = serverInfo[MLDeviceRedirectionServerInfoTag];
    if ([value isKindOfClass:[NSNumber class]]) {
        return [value longLongValue] == 1;
    }
    if ([value isKindOfClass:[NSString class]]) {
        return [(NSString *)value isEqualToString:@"1"];
    }
    return NO;
}

- (MLDeviceRedirectionVerdict *)verdictForDevice:(MLUSBDeviceDescriptor *)device {
    NSString *token = MLUSBDeviceAuditToken(device.serialNumber);

    // The order below is the order a reader has to be able to trust, and the harness
    // drives each gate on its own so no later gate can be reached while an earlier one is
    // still false. Cheapest and most global first: a session that is not encrypted to a
    // paired host is not a session any device should be trusted with, and telling the
    // player that is worth more than telling them the vendor id did not match.
    if (!self.featureEnabled) {
        return [self denialFor:MLDeviceRedirectionDenialFeatureDisabled device:device token:token ruleIndex:-1];
    }
    if (!self.hostIsPaired) {
        return [self denialFor:MLDeviceRedirectionDenialHostUnpaired device:device token:token ruleIndex:-1];
    }
    if (!self.hostSupportsDeviceRedirection) {
        return [self denialFor:MLDeviceRedirectionDenialHostUnsupported device:device token:token ruleIndex:-1];
    }
    // Nothing after this point can be trusted about a device whose identity is not known,
    // so none of it is tried: a rule cannot be matched against an unknown vendor, and a
    // class check cannot be run over an empty interface list.
    if (!MLIdentityIsReadable(device.vendorID) || !MLIdentityIsReadable(device.productID) ||
        device.interfaces.count == 0) {
        return [self denialFor:MLDeviceRedirectionDenialIdentityIncomplete
                        device:device token:token ruleIndex:-1];
    }

    BOOL wantsLocalInput = NO;
    BOOL anyClassAllowed = NO;
    for (MLUSBInterfaceDescriptor *interface in device.interfaces) {
        if ([MLDeviceRedirectionPolicy isReservedInterfaceClass:interface.majorClass]) {
            return [self denialFor:MLDeviceRedirectionDenialClassReserved
                            device:device token:token ruleIndex:-1];
        }
        wantsLocalInput = wantsLocalInput || interface.isBootInputInterface;
        anyClassAllowed = anyClassAllowed ||
                          [self.allowedInterfaceClasses containsObject:@(interface.majorClass)];
    }
    // Ahead of the class list on purpose. Someone who allowed class 0x03 for a gamepad
    // must not find their keyboard handed to the host by the same allowance.
    if (wantsLocalInput && !self.localInputDevicesAllowed) {
        return [self denialFor:MLDeviceRedirectionDenialLocalInputReserved
                        device:device token:token ruleIndex:-1];
    }
    if (!anyClassAllowed) {
        return [self denialFor:MLDeviceRedirectionDenialClassNotAllowed
                        device:device token:token ruleIndex:-1];
    }

    NSInteger disabledMatch = -1;
    for (NSInteger index = 0; index < (NSInteger)self.rules.count; index++) {
        MLDeviceRedirectionRule *rule = self.rules[index];
        if (!rule.isWellFormed) {
            continue;
        }
        if (rule.vendorID != (unsigned short)[device.vendorID unsignedShortValue]) {
            continue;
        }
        if (!rule.productIsWildcard &&
            rule.productID != (unsigned short)[device.productID unsignedShortValue]) {
            continue;
        }
        if (rule.enabled) {
            return [MLDeviceRedirectionVerdict verdictWithOutcome:MLDeviceRedirectionOutcomeAllowed
                                                           denial:MLDeviceRedirectionDenialNone
                                                        ruleIndex:index
                                                           device:device
                                                      deviceToken:token];
        }
        if (disabledMatch < 0) {
            disabledMatch = index;
        }
    }
    // A rule that matches but is switched off is reported as that rather than as the
    // absence of a rule. The two read alike in a log and mean opposite things to whoever
    // turned it off and forgot.
    if (disabledMatch >= 0) {
        return [self denialFor:MLDeviceRedirectionDenialRuleDisabled
                        device:device token:token ruleIndex:disabledMatch];
    }
    return [self denialFor:MLDeviceRedirectionDenialNoRule device:device token:token ruleIndex:-1];
}

@end
