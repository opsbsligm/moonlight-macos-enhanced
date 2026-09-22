//
//  DeviceRedirectionPanelModel.h
//  Moonlight
//
//  The state behind the devices panel, and the whole of its logic. The panel itself renders
//  strings produced here, for the reason every other layer in this feature has the same shape:
//  what a settings page decides is worth checking, and a decision made inside a SwiftUI `body`
//  cannot be driven by a gate.
//
//  The panel exists because docs/usb-redirection-design.md 3 says a list of refusus would dress a
//  missing certificate up as a broken device. So the model answers two kinds of question in one
//  object: what this build and this bus can currently do, and what would happen to a particular
//  device if the missing part arrived. It changes nothing about streaming: it opens no device,
//  sends no message, and its switches are read by nothing but this panel until stage 3 lands.
//
//  Every preference is stored, and every stored value is re-validated on the way back out. A rule
//  that could not match a device is refused at the door rather than saved and silently inert, and
//  a stored record this code does not recognise is counted and reported instead of being skipped
//  in silence -- the difference between "no rules" and "three rules, one unreadable" is the whole
//  difference between a support thread and a shrug.
//

#import <Foundation/Foundation.h>

#import "CodeSignatureProfile.h"
#import "DeviceRedirectionPolicy.h"
#import "USBBusSnapshot.h"

NS_ASSUME_NONNULL_BEGIN

//
//  Swift renames a `setFeatureEnabled:` sitting beside a readonly `featureEnabled` instead of
//  folding the two into one property, and which way it decided depends on the compiler doing
//  the import. The switches are declared readwrite with the storage validation in the accessors,
//  so a page writes a property and every importer reads the same shape.
/// What the host has said about device redirection during this visit to the panel.
///
/// Deliberately not stored. Whether a host offers the feature is a fact about a running server, and
/// a settings page that remembered yesterday's answer would be showing a cached claim about
/// somebody else's machine. Leaving the panel resets it to `NotAsked`.
typedef NS_ENUM(NSInteger, MLDeviceRedirectionHostClaim) {
    MLDeviceRedirectionHostClaimNotAsked = 0,
    /// The host answered, and the answer was not yes. An absent field and a `0` both land
    /// here, and so does a field that says `yes` instead of one -- the answer has to arrive in
    /// the one spelling the protocol defines. What does not land here is never getting an
    /// answer, which is the next case.
    MLDeviceRedirectionHostClaimRefused = 1,
    MLDeviceRedirectionHostClaimOffered = 2,
    /// The question went out and nothing answerable came back: no route, an error status, or
    /// an answer signed by a different machine. A page that called this a refusal would be
    /// reporting a host's decision that nobody heard, which is the same class of lie as
    /// calling a missing signing identity a broken device -- and it sends a player to their
    /// PC's settings instead of their network.
    MLDeviceRedirectionHostClaimUnreachable = 3,
};

/// One device on the bus, with the reading taken of it and the decision that would follow.
@interface MLDeviceRedirectionPanelRow : NSObject
/// `vid=… pid=… classes=… token=…`. Identifiers this build could not read appear as `unread`,
/// and a product name or serial number never appears at all.
@property(nonatomic, readonly, copy) NSString *identityLine;
/// `allowed` or `refused: <reason>`, in the one spelling the log uses for the same refusal.
@property(nonatomic, readonly, copy) NSString *decisionLine;
/// The device this row was built from, so that a page can offer the identifiers back to the rule
/// editor instead of asking a player to retype hexadecimal digits they can already see. The line
/// above is what a player reads; this is what a page acts on, and neither is derived from the other.
@property(nonatomic, readonly, strong, nullable) MLUSBDeviceIdentity *identity;
@property(nonatomic, readonly) BOOL allowed;
@property(nonatomic, readonly) BOOL identityIsReadable;
@property(nonatomic, readonly) BOOL hasReservedInterface;
@end

@interface MLDeviceRedirectionPanelModel : NSObject
/// Which of the four preconditions are currently satisfied. All four are needed for one handover.
@property(nonatomic, readwrite) BOOL featureEnabled;
@property(nonatomic, readwrite) BOOL localInputDevicesAllowed;
@property(nonatomic, readonly) NSSet<NSNumber *> *allowedInterfaceClasses;
@property(nonatomic, readonly) NSArray<MLDeviceRedirectionRule *> *rules;
/// Records in storage that this code cannot honour, whether because they cannot be read at all or
/// because the rule they describe could never match a device. Not dropped quietly: the difference
/// between "no rules" and "five records, three of which do nothing" is the difference between a
/// support thread and a shrug.
@property(nonatomic, readonly) NSUInteger unreadableStoredRuleCount;
@property(nonatomic, readonly, strong) MLCodeSignatureProfile *signatureProfile;
@property(nonatomic, readonly) MLDeviceRedirectionHostClaim hostClaim;
/// False is not one answer but two, and the panel has to be able to tell them apart.
@property(nonatomic, readonly) MLUSBBusSnapshotStatus busStatus;
/// Whether the bus has been read since this panel was created. Until it has, `busStatus` is the
/// enumeration's zero value and nothing more -- which reads as `read` -- so the panel that prints it
/// has to say who asked. Nothing scans on its own: a settings page iterating the registry on every
/// redraw is a page that gets slower the more a player plugs in.
@property(nonatomic, readonly) BOOL busHasBeenScanned;
/// Whether all four preconditions are met. Not "nearly", and not per-device.
@property(nonatomic, readonly) BOOL mayBecomeActive;
/// The first precondition still missing, as the one word the panel puts in front of the list.
@property(nonatomic, readonly, copy) NSString *blockingReasonName;

/// Built over a caller's defaults, so a gate can drive the storage round trip against a suite
/// that is not the one the player's settings live in.
- (instancetype)initWithDefaults:(NSUserDefaults *)defaults;

/// The same, with the signature handed in. The panel reads its own, because the panel's whole
/// purpose is to report what the running binary can do; a gate needs to ask what the panel would
/// say about the identity that does not exist yet, and a precondition that cannot be turned on in
/// a test is a precondition no test has ever checked.
- (instancetype)initWithDefaults:(NSUserDefaults *)defaults
                signatureProfile:(MLCodeSignatureProfile *)signatureProfile;

// A no-argument factory whose name begins with the class's own noun is what the importer turns
// into `init()`, and a class that also has `initWithDefaults:` then has two initialisers claiming
// the same spelling -- so the factory is not here to be renamed, and a page builds the shipped
// configuration the way the header says: `MLDeviceRedirectionPanelModel(defaults: .standard)`,
// which is everything off, no classes allowed, no rules, and the signature read from the
// running binary.

/// Writes. Each setter validates before storing, so a switch that arrives with an out-of-range
/// class number is refused rather than remembered.
- (BOOL)setInterfaceClassAllowed:(BOOL)allowed forClass:(NSUInteger)majorClass
    NS_SWIFT_NAME(setInterfaceClassAllowed(_:forClass:));

/// False when the rule could not describe a device: a sentinel vendor id, or a product id on a
/// family rule. Nothing is stored in that case, which is the point -- an inert rule is a rule that
/// will be believed when it is in fact doing nothing.
- (BOOL)addRuleForVendorID:(NSUInteger)vendorID
                 productID:(NSUInteger)productID
                    family:(BOOL)familyIsWildcard
    NS_SWIFT_NAME(addRule(vendorID:productID:family:));
//
//  Every selector the devices pane calls carries an explicit Swift name. The importer's own
//  translation is not stable across compiler versions: it turned `removeRuleAtIndex:` into
//  `removeRule(at:)` and `rowsByScanningBusWithHostPaired:` into `rowsByScanningBus(withHostPaired:)`,
//  and a page written against one version's guess fails to compile on the next one for a reason
//  nobody changed. Pinning the spelling is the only way to state it once.
/// Removes the stored records that could not become rules, and returns how many went. They are
/// inert already -- neither this panel nor the policy can act on them -- so removing them changes
/// no decision; it is the only way a player stops being told about a record they cannot reach.
- (NSUInteger)removeUnhonourableStoredRecords;

/// Switches the rule at a row of the list the panel shows. A rule whose record was stored without
/// its enabled flag reads as off, and a page that could only delete it would be telling a player to
/// rebuild an allow list to change one byte of it.
- (BOOL)setRuleEnabled:(BOOL)enabled atIndex:(NSUInteger)index
    NS_SWIFT_NAME(setRuleEnabled(_:atIndex:));

/// Removes the rule at a row of the list the panel shows. The row is not the storage slot whenever
/// an unhonourable record sits above it, and addressing storage directly would delete the wrong
/// record while reporting the row as gone.
- (BOOL)removeRuleAtIndex:(NSUInteger)index NS_SWIFT_NAME(removeRule(atIndex:));

/// The value the host returned for MLDeviceRedirectionServerInfoTagName(), or nil when it answered
/// and the field was absent. Both land on `Refused`, and neither lands on `Offered`.
///
/// Only call this with an answer that was actually received and identified. A request that failed
/// belongs to the method below, and a page that conflates the two is what this comment exists for.
- (void)noteServerInfoValue:(id _Nullable)value NS_SWIFT_NAME(noteServerInfoValue(_:));

/// Records that the host could not be reached, or answered as somebody else. Explicitly not a
/// refusal: the host made no decision that this page is entitled to report.
- (void)noteHostWasUnreachable NS_SWIFT_NAME(noteHostWasUnreachable());

/// Forgets whatever was heard, which is what leaving the panel does and what changing the
/// selected host has to do too. An answer belongs to one machine, and a page that keeps showing
/// the previous host's answer is making a claim about a machine it has not asked.
- (void)clearHostClaim NS_SWIFT_NAME(clearHostClaim());

/// Scans the bus now and reads each device the bus reported. Explicit, because a settings page
/// should not iterate the registry on every redraw.
- (NSArray<MLDeviceRedirectionPanelRow *> *)rowsByScanningBusWithHostPaired:(BOOL)hostIsPaired
    NS_SWIFT_NAME(rowsByScanningBus(hostPaired:));

/// Rows for devices handed in, which is what a gate uses: a device nobody could plug in is still a
/// device the panel has to describe correctly.
- (NSArray<MLDeviceRedirectionPanelRow *> *)rowsForDevices:(NSArray<MLUSBDeviceIdentity *> *)devices
                                            hostIsPaired:(BOOL)hostIsPaired
    NS_SWIFT_NAME(rows(for:hostIsPaired:));

/// The classes a rule can never reach, in the order the panel lists them.
+ (NSArray<NSNumber *> *)interfaceClassesNoRuleCanReach;

/// One line, safe to log: the four preconditions and the totals. Never a device name.
@property(nonatomic, readonly, copy) NSString *auditLine;
@end

FOUNDATION_EXPORT NSString *MLDeviceRedirectionHostClaimName(MLDeviceRedirectionHostClaim claim);

NS_ASSUME_NONNULL_END
