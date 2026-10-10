//
//  DeviceRedirectionPanelModel.m
//  Moonlight
//
//  See DeviceRedirectionPanelModel.h. The one rule worth restating: nothing here invents a
//  capability. Each precondition starts false, storage that cannot be read counts as absent rather
//  than as default-on, and a host that has not been asked has not said yes.
//

#import "DeviceRedirectionPanelModel.h"

static NSString *const kFeatureEnabledDefaultsKey = @"moonlight.usbredirection.enabled";
static NSString *const kLocalInputDefaultsKey = @"moonlight.usbredirection.localInputAllowed";
static NSString *const kAllowedClassesDefaultsKey = @"moonlight.usbredirection.allowedClasses";
static NSString *const kRulesDefaultsKey = @"moonlight.usbredirection.rules";

static NSString *const kRuleVendorField = @"vendor";
static NSString *const kRuleProductField = @"product";
static NSString *const kRuleFamilyField = @"family";
static NSString *const kRuleEnabledField = @"enabled";

/// The largest value a USB identifier can hold. A stored number beyond it is not an identifier, and
/// a rule built from one would wrap into something that could match a real device.
static const NSUInteger MLUSBIdentifierMaximum = 0xFFFF;

/// A stored rule, or nil when the record is not a rule at all. An identifier that is missing, is
/// not a number, or does not fit in the two bytes a USB identifier occupies cannot be turned into
/// a rule without inventing the missing half -- and an invented vendor id is exactly the thing an
/// allow list is there to make impossible.
static MLDeviceRedirectionRule *MLDeviceRedirectionRuleFromStoredRecord(id record) {
    if (![record isKindOfClass:[NSDictionary class]]) {
        return nil;
    }
    NSDictionary *dictionary = (NSDictionary *)record;
    id vendor = dictionary[kRuleVendorField];
    id product = dictionary[kRuleProductField];
    if (![vendor isKindOfClass:[NSNumber class]] || ![product isKindOfClass:[NSNumber class]]) {
        return nil;
    }
    const NSUInteger vendorID = [(NSNumber *)vendor unsignedIntegerValue];
    const NSUInteger productID = [(NSNumber *)product unsignedIntegerValue];
    if (vendorID > MLUSBIdentifierMaximum || productID > MLUSBIdentifierMaximum) {
        return nil;
    }
    // A rule stored without its enabled flag is a rule that was not stored by this code. Treated
    // as off, because the alternative is for a half-written record to authorise something.
    const BOOL enabled = [dictionary[kRuleEnabledField] isKindOfClass:[NSNumber class]]
        ? [(NSNumber *)dictionary[kRuleEnabledField] boolValue]
        : NO;
    const BOOL family = [dictionary[kRuleFamilyField] isKindOfClass:[NSNumber class]]
        ? [(NSNumber *)dictionary[kRuleFamilyField] boolValue]
        : NO;
    MLDeviceRedirectionRule *rule = family
        ? [MLDeviceRedirectionRule familyRuleForVendorID:(unsigned short)vendorID enabled:enabled]
        : [MLDeviceRedirectionRule ruleForVendorID:(unsigned short)vendorID
                                        productID:(unsigned short)productID
                                          enabled:enabled];
    // A record can be well-formed as a dictionary and still describe a device that cannot exist:
    // a sentinel vendor id, or an identifier wide enough to wrap into one on the way through two
    // bytes. The policy skips those at decision time, so a panel that listed them would be
    // promising a handover the policy is going to refuse -- the exact disagreement this whole
    // layer was written to prevent. It is reported instead of shown.
    return rule.isWellFormed ? rule : nil;
}

NSString *MLDeviceRedirectionHostClaimName(MLDeviceRedirectionHostClaim claim) {
    switch (claim) {
        case MLDeviceRedirectionHostClaimNotAsked:
            return @"host-not-asked";
        case MLDeviceRedirectionHostClaimRefused:
            return @"host-refused";
        case MLDeviceRedirectionHostClaimOffered:
            return @"host-offered";
        case MLDeviceRedirectionHostClaimUnreachable:
            return @"host-unreachable";
    }
    return @"host-not-asked";
}

//
//  The tables a device card is rendered from. They live here, beside the row that carries
//  them, for the reason everything else in this file lives here: a mapping a view owns is a
//  mapping no gate checks, and the two failures it makes are both silent -- a class with no
//  entry gets the fallback icon forever, and a denial with no entry gets a key that renders
//  as its own key. A gate pins both tables against their enums below.
//

/// Human names for the interface classes a card may have to name. Deliberately keyed by the
/// raw class number rather than reusing the panel's switch list: the panel offers nine
/// classes for a switch, but a device can report any of them plus classes nobody offered --
/// a hub (0x09), a CCID smart card (0x0b), a keyboard dock's diagnostic face (0xdc) -- and a
/// card that could only name the offered nine would answer "what is this?" with nothing for
/// exactly the devices a player is most likely to wonder about.
static NSDictionary<NSNumber *, NSString *> *MLInterfaceClassNameKeys(void) {
    return @{ @(0x00) : @"USB class device specific",
              @(0x01) : @"USB class audio",
              @(0x02) : @"USB class communications",
              @(0x03) : @"USB class human interface",
              @(0x05) : @"USB class physical",
              @(0x06) : @"USB class image",
              @(0x07) : @"USB class printer",
              @(0x08) : @"USB class mass storage",
              @(0x09) : @"USB class hub",
              @(0x0A) : @"USB class communications data",
              @(0x0B) : @"USB class smart card",
              @(0x0D) : @"USB class content security",
              @(0x0E) : @"USB class video",
              @(0xDC) : @"USB class diagnostic",
              @(0xE0) : @"USB class wireless controller",
              @(0xE1) : @"USB class miscellaneous",
              @(0xEF) : @"USB class miscellaneous",
              @(0xFF) : @"USB class vendor specific" };
}

/// One icon per entry of the name table, plus one more entry (0x0E is video in both). A card
/// with no picture reads as a broken row, so this table answers for every class the name
/// table knows, and the fallback below answers for every class it does not.
static NSDictionary<NSNumber *, NSString *> *MLInterfaceClassSymbolNames(void) {
    return @{ @(0x00) : @"circle",
              @(0x01) : @"speaker.wave.2",
              @(0x02) : @"network",
              @(0x03) : @"keyboard",
              @(0x05) : @"gamecontroller",
              @(0x06) : @"camera",
              @(0x07) : @"printer",
              @(0x08) : @"internaldrive",
              @(0x09) : @"hub",
              @(0x0A) : @"cable.connector",
              @(0x0B) : @"creditcard",
              @(0x0D) : @"lock.shield",
              @(0x0E) : @"web.camera",
              @(0xDC) : @"stethoscope",
              @(0xE0) : @"antenna.radiowaves.left.and.right",
              @(0xE1) : @"puzzlepiece.extension",
              @(0xEF) : @"square.stack.3d.up",
              @(0xFF) : @"wrench.and.screwdriver" };
}

/// One sentence per refusal, in the player's language, next to the machine spelling the log
/// keeps. Pinned against the whole denial enum by a gate: a row whose verdict has no sentence
/// here would render a raw key, which is the same "not allowed is not something a player can
/// act on" that the enum exists to answer.
static NSDictionary<NSNumber *, NSString *> *MLDeviceRedirectionDenialReasonKeys(void) {
    return @{ @(MLDeviceRedirectionDenialNone) : @"usb reason none",
              @(MLDeviceRedirectionDenialFeatureDisabled) : @"usb reason feature disabled",
              @(MLDeviceRedirectionDenialHostUnpaired) : @"usb reason host unpaired",
              @(MLDeviceRedirectionDenialHostUnsupported) : @"usb reason host unsupported",
              @(MLDeviceRedirectionDenialIdentityIncomplete) : @"usb reason identity incomplete",
              @(MLDeviceRedirectionDenialClassReserved) : @"usb reason class reserved",
              @(MLDeviceRedirectionDenialLocalInputReserved) : @"usb reason local input reserved",
              @(MLDeviceRedirectionDenialClassNotAllowed) : @"usb reason class not allowed",
              @(MLDeviceRedirectionDenialRuleDisabled) : @"usb reason rule disabled",
              @(MLDeviceRedirectionDenialNoRule) : @"usb reason no rule" };
}

/// The class a card leads with. The reserved face wins when there is one: it is the face that
/// decided the refusal -- class-reserved outranks every rule -- so a card that named the
/// storage half of a smart-card dock would describe the half that was not decided about.
/// Otherwise the first class the registry reported, which is the first face of the device as
/// the machine described it.
static NSUInteger MLDominantInterfaceClass(NSArray<MLUSBInterfaceDescriptor *> *interfaces,
                                          BOOL *isReserved) {
    for (MLUSBInterfaceDescriptor *interface in interfaces) {
        if ([MLDeviceRedirectionPolicy isReservedInterfaceClass:interface.majorClass]) {
            if (isReserved) {
                *isReserved = YES;
            }
            return interface.majorClass;
        }
    }
    if (isReserved) {
        *isReserved = NO;
    }
    return interfaces.firstObject ? interfaces.firstObject.majorClass : 0xFF;
}

@implementation MLDeviceRedirectionPanelRow

- (instancetype)initWithIdentity:(MLUSBDeviceIdentity *)identity
                         verdict:(MLDeviceRedirectionVerdict *)verdict {
    self = [super init];
    if (self) {
        _identity = identity;
        _identityLine = [identity diagnosticLineForVerdict:nil];
        _displayName = [identity.displayName copy];
        _identifiersLine = [NSString stringWithFormat:@"VID %@ \u00b7 PID %@",
                                                      MLUSBIdentityName(identity.vendorID),
                                                      MLUSBIdentityName(identity.productID)];
        _allowed = verdict.isAllowed;
        _identityIsReadable = identity.vendorID != nil && identity.productID != nil &&
                              identity.interfaces.count > 0;
        BOOL reserved = NO;
        for (MLUSBInterfaceDescriptor *interface in identity.interfaces) {
            if ([MLDeviceRedirectionPolicy isReservedInterfaceClass:interface.majorClass]) {
                reserved = YES;
                break;
            }
        }
        _hasReservedInterface = reserved;
        BOOL dominantIsReserved = NO;
        const NSUInteger dominant = MLDominantInterfaceClass(identity.interfaces,
                                                            &dominantIsReserved);
        _categoryNameKey = MLInterfaceClassNameKeys()[@(dominant)] ?:
                           MLInterfaceClassNameKeys()[@(0xFF)];
        // The class the card leads with decides the icon, so a dock with a smart-card face
        // shows the credit card -- the thing about it that matters -- and not a disk.
        (void)dominantIsReserved;
        _categorySymbolName = MLInterfaceClassSymbolNames()[@(dominant)] ?: @"questionmark.circle";
        _humanReasonKey = MLDeviceRedirectionDenialReasonKeys()[@(verdict.denial)] ?:
                          MLDeviceRedirectionDenialReasonKeys()[@(MLDeviceRedirectionDenialNone)];
        _decisionLine = verdict.isAllowed
            ? @"allowed"
            : [NSString stringWithFormat:@"refused: %@",
                                         MLDeviceRedirectionDenialName(verdict.denial)];
    }
    return self;
}

+ (NSArray<MLDeviceRedirectionPanelRow *> *)displayOrderedRows:(NSArray<MLDeviceRedirectionPanelRow *> *)rows {
    // Three groups, in the order a player reads them: what could move right now, what no rule
    // can ever move, and everything else -- which is a refusal with a fix. Inside a group, by
    // the name the card shows, with the machine line as the tiebreak so two devices the same
    // name does not decide shuffle between scans.
    NSMutableArray<MLDeviceRedirectionPanelRow *> *sorted = [rows mutableCopy];
    [sorted sortUsingComparator:^NSComparisonResult(MLDeviceRedirectionPanelRow *first,
                                                    MLDeviceRedirectionPanelRow *second) {
        const NSInteger firstGroup = first.allowed ? 0 : (first.hasReservedInterface ? 1 : 2);
        const NSInteger secondGroup = second.allowed ? 0 : (second.hasReservedInterface ? 1 : 2);
        if (firstGroup != secondGroup) {
            return firstGroup < secondGroup ? NSOrderedAscending : NSOrderedDescending;
        }
        NSString *firstKey = first.displayName ?: first.identityLine;
        NSString *secondKey = second.displayName ?: second.identityLine;
        const NSComparisonResult byName =
            [firstKey localizedStandardCompare:secondKey];
        if (byName != NSOrderedSame) {
            return byName;
        }
        return [first.identityLine compare:second.identityLine];
    }];
    return [sorted copy];
}

+ (NSString *)categorySymbolNameForInterfaceClass:(NSUInteger)majorClass {
    return MLInterfaceClassSymbolNames()[@(majorClass & 0xFF)] ?: @"questionmark.circle";
}

@end

@interface MLDeviceRedirectionPanelModel ()
@property(nonatomic, strong) NSUserDefaults *defaults;
@property(nonatomic, strong) MLCodeSignatureProfile *signatureProfile;
@end

@implementation MLDeviceRedirectionPanelModel

- (instancetype)initWithDefaults:(NSUserDefaults *)defaults {
    // Read from the binary rather than from a build setting: the setting says what was asked for,
    // and the panel is answering what this build can actually do.
    return [self initWithDefaults:defaults
                 signatureProfile:MLCodeSignatureProfileOfCurrentProcess()];
}

- (instancetype)initWithDefaults:(NSUserDefaults *)defaults
                signatureProfile:(MLCodeSignatureProfile *)signatureProfile {
    self = [super init];
    if (self) {
        _defaults = defaults ?: [NSUserDefaults standardUserDefaults];
        _signatureProfile = signatureProfile ?: MLCodeSignatureProfileOfCurrentProcess();
        _hostClaim = MLDeviceRedirectionHostClaimNotAsked;
    }
    return self;
}

// MARK: - Stored state

- (BOOL)featureEnabled {
    return [self.defaults boolForKey:kFeatureEnabledDefaultsKey];
}

- (void)setFeatureEnabled:(BOOL)enabled {
    [self.defaults setBool:enabled forKey:kFeatureEnabledDefaultsKey];
}

- (BOOL)localInputDevicesAllowed {
    return [self.defaults boolForKey:kLocalInputDefaultsKey];
}

- (void)setLocalInputDevicesAllowed:(BOOL)allowed {
    [self.defaults setBool:allowed forKey:kLocalInputDefaultsKey];
}

/// The records in storage, whatever they are.
- (NSArray *)storedRules {
    id stored = [self.defaults objectForKey:kRulesDefaultsKey];
    return [stored isKindOfClass:[NSArray class]] ? (NSArray *)stored : @[];
}

- (NSUInteger)unreadableStoredRuleCount {
    NSUInteger unreadable = 0;
    for (id record in [self storedRules]) {
        if (MLDeviceRedirectionRuleFromStoredRecord(record) == nil) {
            unreadable++;
        }
    }
    return unreadable;
}

// Read the storage once and in order, keeping the position each rule came from. The position has
// to travel with the rule: a player deletes a rule by the row they can see, and the row they can
// see is not the record it lives on whenever an unreadable record sits above it. Deleting by row
// while addressing storage would silently remove somebody else's entry -- most often one of the
// unreadable ones, which is the one record the panel just told them it could not read.
- (void)collectRules:(NSMutableArray<MLDeviceRedirectionRule *> *_Nullable)rulesOut
      storageIndices:(NSMutableArray<NSNumber *> *_Nullable)indicesOut {
    NSArray *records = [self storedRules];
    for (NSUInteger position = 0; position < records.count; position++) {
        MLDeviceRedirectionRule *rule =
            MLDeviceRedirectionRuleFromStoredRecord(records[position]);
        if (rule == nil) {
            continue;
        }
        if (rulesOut != nil) {
            [rulesOut addObject:rule];
        }
        if (indicesOut != nil) {
            [indicesOut addObject:@(position)];
        }
    }
}

- (NSArray<MLDeviceRedirectionRule *> *)rules {
    NSMutableArray<MLDeviceRedirectionRule *> *rules = [NSMutableArray array];
    [self collectRules:rules storageIndices:nil];
    return [rules copy];
}

- (NSSet<NSNumber *> *)allowedInterfaceClasses {
    id stored = [self.defaults objectForKey:kAllowedClassesDefaultsKey];
    if (![stored isKindOfClass:[NSArray class]]) {
        return [NSSet set];
    }
    NSMutableSet<NSNumber *> *classes = [NSMutableSet set];
    for (id value in (NSArray *)stored) {
        if (![value isKindOfClass:[NSNumber class]]) {
            continue;
        }
        const NSUInteger majorClass = [(NSNumber *)value unsignedIntegerValue];
        if (majorClass <= 0xFF) {
            [classes addObject:@(majorClass)];
        }
    }
    return [classes copy];
}

- (BOOL)setInterfaceClassAllowed:(BOOL)allowed forClass:(NSUInteger)majorClass {
    if (majorClass > 0xFF) {
        // A class byte is a byte. Storing 0x100 would come back as 0 on the way out and read as a
        // decision about the device interface nobody made.
        return NO;
    }
    NSMutableSet<NSNumber *> *classes = [[self allowedInterfaceClasses] mutableCopy];
    if (allowed) {
        [classes addObject:@(majorClass)];
    } else {
        [classes removeObject:@(majorClass)];
    }
    [self.defaults setObject:[classes.allObjects sortedArrayUsingSelector:@selector(compare:)]
                      forKey:kAllowedClassesDefaultsKey];
    return YES;
}

- (BOOL)addRuleForVendorID:(NSUInteger)vendorID
                 productID:(NSUInteger)productID
                    family:(BOOL)familyIsWildcard {
    if (vendorID > MLUSBIdentifierMaximum || productID > MLUSBIdentifierMaximum) {
        return NO;
    }
    MLDeviceRedirectionRule *rule = familyIsWildcard
        ? [MLDeviceRedirectionRule familyRuleForVendorID:(unsigned short)vendorID enabled:YES]
        : [MLDeviceRedirectionRule ruleForVendorID:(unsigned short)vendorID
                                         productID:(unsigned short)productID
                                           enabled:YES];
    if (!rule.isWellFormed) {
        return NO;
    }
    NSMutableArray *records = [[self storedRules] mutableCopy];
    [records addObject:@{
        kRuleVendorField : @(rule.vendorID),
        kRuleProductField : @(rule.productID),
        kRuleFamilyField : @(rule.productIsWildcard),
        kRuleEnabledField : @YES,
    }];
    [self.defaults setObject:records forKey:kRulesDefaultsKey];
    return YES;
}

- (NSUInteger)removeUnhonourableStoredRecords {
    // The records that are not rules are inert already: the policy cannot match them, and this
    // panel cannot show them. Leaving them in storage means a tally a player can see and can never
    // clear, so the panel gets one way to clear it, and it only ever touches records that are
    // doing nothing today.
    NSMutableArray *kept = [NSMutableArray array];
    for (id record in [self storedRules]) {
        if (MLDeviceRedirectionRuleFromStoredRecord(record) != nil) {
            [kept addObject:record];
        }
    }
    const NSUInteger removed = [self storedRules].count - kept.count;
    if (removed > 0) {
        [self.defaults setObject:kept forKey:kRulesDefaultsKey];
    }
    return removed;
}

- (BOOL)setRuleEnabled:(BOOL)enabled atIndex:(NSUInteger)index {
    // Row-addressed for the same reason deletion is, and it rewrites the record rather than
    // replacing the list: a row is one rule, and the records around it -- including the ones this
    // code cannot read -- are nobody's to touch.
    NSMutableArray<NSNumber *> *positions = [NSMutableArray array];
    [self collectRules:nil storageIndices:positions];
    if (index >= positions.count) {
        return NO;
    }
    const NSUInteger storageIndex = [positions[index] unsignedIntegerValue];
    NSArray *records = [self storedRules];
    if (storageIndex >= records.count) {
        return NO;
    }
    id record = records[storageIndex];
    if (![record isKindOfClass:[NSDictionary class]]) {
        return NO;
    }
    NSMutableDictionary *rewritten = [(NSDictionary *)record mutableCopy];
    rewritten[kRuleEnabledField] = @(enabled);
    NSMutableArray *kept = [records mutableCopy];
    [kept replaceObjectAtIndex:storageIndex withObject:rewritten];
    [self.defaults setObject:kept forKey:kRulesDefaultsKey];
    return YES;
}

- (BOOL)removeRuleAtIndex:(NSUInteger)index {
    // `index` is a row of the list the panel shows, not a slot in storage. The two differ the
    // moment a record this code cannot read is in there, and the panel shows both numbers.
    NSMutableArray<NSNumber *> *positions = [NSMutableArray array];
    [self collectRules:nil storageIndices:positions];
    if (index >= positions.count) {
        return NO;
    }
    const NSUInteger storageIndex = [positions[index] unsignedIntegerValue];
    NSMutableArray *records = [[self storedRules] mutableCopy];
    if (storageIndex >= records.count) {
        return NO;
    }
    [records removeObjectAtIndex:storageIndex];
    [self.defaults setObject:records forKey:kRulesDefaultsKey];
    return YES;
}

// MARK: - The host's answer

- (void)noteServerInfoValue:(id _Nullable)value {
    _hostClaim = [MLDeviceRedirectionPolicy hostAdvertisesDeviceRedirectionInServerInfo:
                      value == nil ? @{} : @{ MLDeviceRedirectionServerInfoTagName() : value }]
        ? MLDeviceRedirectionHostClaimOffered
        : MLDeviceRedirectionHostClaimRefused;
}

- (void)noteHostWasUnreachable {
    _hostClaim = MLDeviceRedirectionHostClaimUnreachable;
}

- (void)clearHostClaim {
    _hostClaim = MLDeviceRedirectionHostClaimNotAsked;
}

// MARK: - Reading the bus

+ (MLDeviceRedirectionPolicy *)policyWithFeatureEnabled:(BOOL)featureEnabled
                                         hostIsPaired:(BOOL)hostIsPaired
                     hostSupportsDeviceRedirection:(BOOL)hostSupportsDeviceRedirection
                       localInputDevicesAllowed:(BOOL)localInputDevicesAllowed
                           allowedInterfaceClasses:(NSSet<NSNumber *> *)allowedInterfaceClasses
                                             rules:(NSArray<MLDeviceRedirectionRule *> *)rules {
    return [[MLDeviceRedirectionPolicy alloc] initWithFeatureEnabled:featureEnabled
                                                        hostIsPaired:hostIsPaired
                                        hostSupportsDeviceRedirection:hostSupportsDeviceRedirection
                                              allowedInterfaceClasses:allowedInterfaceClasses
                                             localInputDevicesAllowed:localInputDevicesAllowed
                                                                rules:rules];
}

- (MLDeviceRedirectionPolicy *)currentPolicyWithHostPaired:(BOOL)hostIsPaired {
    return [MLDeviceRedirectionPanelModel
        policyWithFeatureEnabled:self.featureEnabled
                  hostIsPaired:hostIsPaired
    hostSupportsDeviceRedirection:self.hostClaim == MLDeviceRedirectionHostClaimOffered
        localInputDevicesAllowed:self.localInputDevicesAllowed
          allowedInterfaceClasses:self.allowedInterfaceClasses
                            rules:self.rules];
}

- (NSArray<MLDeviceRedirectionPanelRow *> *)rowsForDevices:(NSArray<MLUSBDeviceIdentity *> *)devices
                                            hostIsPaired:(BOOL)hostIsPaired {
    MLDeviceRedirectionPolicy *policy = [self currentPolicyWithHostPaired:hostIsPaired];
    NSMutableArray<MLDeviceRedirectionPanelRow *> *rows =
        [NSMutableArray arrayWithCapacity:devices.count];
    for (MLUSBDeviceIdentity *identity in devices) {
        [rows addObject:[[MLDeviceRedirectionPanelRow alloc]
                            initWithIdentity:identity
                                     verdict:[policy verdictForDevice:identity.descriptor]]];
    }
    return [rows copy];
}

- (NSArray<MLDeviceRedirectionPanelRow *> *)rowsByScanningBusWithHostPaired:(BOOL)hostIsPaired {
    MLUSBBusSnapshotStatus status = MLUSBBusSnapshotStatusBusUnreadable;
    NSArray<MLUSBDeviceIdentity *> *devices = MLUSBBusSnapshotCopyDeviceIdentities(&status);
    _busStatus = status;
    // The status alone cannot answer "was the bus ever looked at": before the first scan it holds
    // the enumeration's zero value, which is `read`. A page that printed it would be reporting an
    // empty bus as a fact learned from the machine, so the scan records that it happened.
    _busHasBeenScanned = YES;
    return [self rowsForDevices:devices hostIsPaired:hostIsPaired];
}

+ (NSArray<NSNumber *> *)interfaceClassesNoRuleCanReach {
    NSMutableArray<NSNumber *> *reserved = [NSMutableArray array];
    for (NSUInteger majorClass = 0; majorClass <= 0xFF; majorClass++) {
        if ([MLDeviceRedirectionPolicy isReservedInterfaceClass:(unsigned char)majorClass]) {
            [reserved addObject:@(majorClass)];
        }
    }
    return [reserved copy];
}

// MARK: - What still stands in the way

- (BOOL)mayBecomeActive {
    // Four things, and every one of them has to be true at the same moment. A Developer ID build
    // whose feature switch is off would be a build that redirects devices nobody asked it to, and
    // a build with the switch on but no identity would be a build that says it can and is refused.
    return self.signatureProfile.mayAttemptDriverExtension &&
           self.featureEnabled &&
           self.hostClaim == MLDeviceRedirectionHostClaimOffered;
}

- (NSString *)blockingReasonName {
    if (!self.signatureProfile.mayAttemptDriverExtension) {
        return [NSString stringWithFormat:@"build-%@",
                                          MLCodeSignatureFormName(self.signatureProfile.form)];
    }
    if (!self.featureEnabled) {
        return @"feature-disabled";
    }
    if (self.hostClaim != MLDeviceRedirectionHostClaimOffered) {
        return MLDeviceRedirectionHostClaimName(self.hostClaim);
    }
    return @"none";
}

- (NSString *)auditLine {
    return [NSString stringWithFormat:
              @"devices panel: %@, rules=%lu, unreadable-rules=%lu, classes=%lu, local-input=%@, %@",
              self.signatureProfile.auditLine, (unsigned long)self.rules.count,
              (unsigned long)self.unreadableStoredRuleCount,
              (unsigned long)self.allowedInterfaceClasses.count,
              self.localInputDevicesAllowed ? @"yes" : @"no",
              self.mayBecomeActive ? @"ready" : [NSString stringWithFormat:@"blocked=%@",
                                                 self.blockingReasonName]];
}

@end
