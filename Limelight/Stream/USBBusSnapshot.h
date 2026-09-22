//
//  USBBusSnapshot.h
//  Moonlight
//
//  The one place in this application that looks at the USB bus, and the only one that links
//  IOKit. Stage 1 decided what a device may be said to be; this file decides which registry
//  nodes belong to the same device, which is the question Stage 1's own header had to leave to
//  its caller.
//
//  What measuring the bus on macOS 27.2 settled, and what therefore shaped this API:
//
//  • `IOServiceGetMatchingServices` for `IOUSBHostInterface` returned 11 objects while the
//    devices attached at the same moment named 16 interface nodes under themselves. Five of the
//    sixteen were not in the matching list at all. So the interface list of the bus is NOT the
//    interface iterator: a snapshot assembled from it would describe a composite device by part
//    of its faces, and the reserved-class refusal in docs 4.5 exists precisely so that a device
//    cannot choose which face a policy sees. Reading 31% of the interfaces would do that for it.
//  • Every interface node named exactly one `IOUSBHostDevice` parent in the IOService plane, and
//    that parent was the device that named it as a child. The parent link is therefore what
//    groups nodes; it is checked rather than assumed, and the assertion below that no interface
//    iterator appears in this file is what keeps the wrong assembly from coming back.
//  • Interface nodes carry `bInterfaceNumber` and no device node carries any key whose name
//    mentions an interface, so the role of a node is readable from its own key names.
//
//  Two properties this file has to keep, because everything downstream trusts them: it reads and
//  never touches. No device is opened, no interface is claimed, no property is written -- an
//  iterator and `IORegistryEntryCreateCFProperties` are the whole of the bus access. And it says
//  nothing: the dictionaries it hands over are the registry's own, and the only exit for their
//  contents is Stage 1, which digests a serial number the moment it reads one.
//

#import <Foundation/Foundation.h>

#import "USBDeviceEnumeration.h"

NS_ASSUME_NONNULL_BEGIN

/// What one registry node is, judged from the names of its properties. Two answers, because
/// only one distinction is load bearing: an interface node has to be put under its device, and
/// everything else that hangs off a device -- a hub driver, a composite helper, a user-client
/// object -- is not an interface and contributes no interface to the reading. Nothing here
/// claims a node is a device: that is decided by which iterator produced it, not by its keys.
typedef NS_ENUM(NSInteger, MLUSBBusNodeRole) {
    /// No interface number among the key names. Carries no interface of its own.
    MLUSBBusNodeRoleNotInterface = 0,
    MLUSBBusNodeRoleInterface = 1,
};

/// The role of a node, from the names of the properties it carries. Values are not consulted:
/// a role that depended on a value could be changed by the device it describes, and the whole
/// point of the composite rule is that the device does not get to decide how it is read.
FOUNDATION_EXPORT MLUSBBusNodeRole MLUSBBusNodeRoleForPropertyKeys(
    NSSet<NSString *> *propertyKeys);

/// Names an interface node uses for its interface number, in the order they are tried. Only the
/// first was measured on macOS 27.2; the rest are recorded as untested candidates rather than as
/// facts, which is what scripts/usb-registry-shape.py reports them as.
FOUNDATION_EXPORT NSArray<NSString *> *MLUSBBusInterfaceNumberCandidateKeys(void);

/// Nodes grouped per device: one array per device, each beginning with that device's own node
/// followed by the interface nodes whose parent is that device.
///
/// A node is placed by its parent's identity and by nothing else. Two devices with the same
/// vendor and product id stay two groups -- merging them by identifier would give one device the
/// allow-list rule the other one was granted, which is the failure an allow list exists to
/// prevent. An interface whose parent is not among `interfaceParentIDs` is returned as a group of
/// its own rather than attached to the nearest-looking device: it is still readable, because an
/// interface node carries its parent's identifiers too, but it is not evidence about a device
/// this snapshot did not see it belong to.
/// Every argument is nullable and nil means "no nodes", not "assume nothing about them": an
/// iterator that failed halfway is a caller with a short list, and the answer to a short list is
/// the nodes that did arrive, placed by what is known about them.
FOUNDATION_EXPORT NSArray<NSArray<NSDictionary<NSString *, id> *> *> *MLUSBBusGroupNodes(
    NSArray<NSDictionary<NSString *, id> *> * _Nullable deviceNodes,
    NSArray<NSString *> * _Nullable deviceIDs,
    NSArray<NSDictionary<NSString *, id> *> * _Nullable interfaceNodes,
    NSArray<NSString *> * _Nullable interfaceParentIDs);

/// One device, from the node that describes it plus the nodes that describe its interfaces.
FOUNDATION_EXPORT MLUSBDeviceIdentity *MLUSBBusDeviceIdentityFromGroup(
    NSArray<NSDictionary<NSString *, id> *> *nodeGroup);

/// The one spelling of each role.
FOUNDATION_EXPORT NSString *MLUSBBusNodeRoleName(MLUSBBusNodeRole role);

/// Whether the bus was read. An empty list arrives both when nothing is attached and when the
/// registry could not be iterated, and those two answers mean different things to whoever is
/// looking at the panel: one is an invitation to plug something in, the other is a bug report.
/// The caller that cannot be told which it has is not allowed to invent the difference.
typedef NS_ENUM(NSInteger, MLUSBBusSnapshotStatus) {
    MLUSBBusSnapshotStatusRead = 0,
    MLUSBBusSnapshotStatusBusUnreadable = 1,
};

FOUNDATION_EXPORT NSString *MLUSBBusSnapshotStatusName(MLUSBBusSnapshotStatus status);

/// The bus, read now, with the one answer the caller needs alongside it.
FOUNDATION_EXPORT NSArray<MLUSBDeviceIdentity *> *MLUSBBusSnapshotCopyDeviceIdentities(
    MLUSBBusSnapshotStatus * _Nullable status);

NS_ASSUME_NONNULL_END
