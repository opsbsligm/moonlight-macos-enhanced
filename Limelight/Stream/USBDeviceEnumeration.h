//
//  USBDeviceEnumeration.h
//  Moonlight
//
//  Stage 1 of docs/usb-redirection-design.md: what this Mac can see about what is plugged
//  into it, and what it is allowed to say about that.
//
//  Seeing the bus needs no driver extension and no new entitlement -- an iterator from
//  IOServiceGetMatchingServices is available to any process, which is why nothing in this
//  header links IOKit. The risk this stage carries is therefore not capability but speech.
//  A product name and a serial number are personal data; an enumeration feature that writes
//  them to a log has assembled a device fingerprint out of two fields nobody thought about.
//  So there is no accessor here that returns a product name at all, and a serial number is
//  digested the moment it is read rather than the moment something is written.
//

#import <Foundation/Foundation.h>

#import "DeviceRedirectionPolicy.h"

NS_ASSUME_NONNULL_BEGIN

/// One device as the registry described it. A field the registry did not carry stays nil
/// rather than being guessed at: a vendor id invented to make a device look complete would
/// put a fabricated match in front of an allow-list rule, which is the one outcome an
/// allow list exists to prevent.
@interface MLUSBDeviceIdentity : NSObject
@property(nonatomic, readonly, strong, nullable) NSNumber *vendorID;
@property(nonatomic, readonly, strong, nullable) NSNumber *productID;
@property(nonatomic, readonly) NSArray<MLUSBInterfaceDescriptor *> *interfaces;
/// Safe to write down: a digest of the serial number, or "none".
@property(nonatomic, readonly, copy) NSString *auditToken;
/// The device with no serial in it. That is the shape the policy needs, and the only shape
/// that can be passed around without somebody having to remember not to log it.
@property(nonatomic, readonly, strong) MLUSBDeviceDescriptor *descriptor;
/// This device and the decision taken about it, in the one line that is safe to log.
- (NSString *)diagnosticLineForVerdict:(nullable MLDeviceRedirectionVerdict *)verdict;
@end

/// Properties of one registry node, in the shapes IORegistry actually hands over: numbers
/// and hex text for identifiers, interface classes either alone or in a list, a protocol
/// byte present or absent.
///
/// Deliberately pure. Attribution is where the rules live, and it has to be drivable with a
/// device that does not exist. The IOKit call site is a handful of lines that copy
/// properties out and do nothing else, which is why it is not what gets tested.
FOUNDATION_EXPORT MLUSBDeviceIdentity *MLUSBDeviceIdentityFromRegistryProperties(
    NSDictionary<NSString *, id> *properties);

/// One device the way the bus actually lays it out: the device node, plus one node per
/// interface. Measured on macOS 27.2 against every device attached at the time (see
/// docs/usb-redirection-design.md 2.5): the kernel publishes one `IOUSBHostInterface` /
/// `IOUSBInterface` object per interface, each carrying a single-number `bInterfaceClass`
/// and `bInterfaceProtocol` together with the parent's `idVendor` / `idProduct`, and it does
/// not publish an array of classes anywhere.
///
/// The composite case therefore arrives split, and the composite rule only exists if the
/// split is put back together here. A dock that is storage plus a smart card reaches this
/// function as two nodes; an aggregation that kept the first node's class would hand the
/// policy a storage device, and the reserved-class refusal in 4.5 -- written so a device
/// cannot choose which of its faces gets seen -- would never fire. So: identifiers and the
/// serial come from whichever node carries them, interfaces are the union over every node,
/// and the union keeps duplicates, because two identical interface descriptors is what the
/// registry said.
///
/// An empty array is an unreadable device, not an empty one: identifiers stay nil and the
/// audit token says `none`, which is the same answer 2.5 observed on real hardware, where no
/// device attached published a serial number at all.
FOUNDATION_EXPORT MLUSBDeviceIdentity *MLUSBDeviceIdentityFromRegistryNodes(
    NSArray<NSDictionary<NSString *, id> *> *nodes);

NS_ASSUME_NONNULL_END
