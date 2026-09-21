//
//  USBDeviceEnumeration.m
//  Moonlight
//
//  See the header. Two rules hold this file together: nothing is invented where the registry
//  was silent, and nothing identifying leaves it.
//

#import "USBDeviceEnumeration.h"

// Key names are tried in order rather than assumed. IORegistry has carried these fields
// under both the human-readable USB keys and the io-kit short names, and a build that reads
// exactly one of them reports a perfectly good device as an unknown one -- which the policy
// then refuses, and which reads to the player as a bug in the refusal.
static NSArray<NSString *> *MLVendorKeys(void) {
    return @[ @"USB Vendor ID", @"idVendor", @"USB_Vendor_ID" ];
}

static NSArray<NSString *> *MLProductKeys(void) {
    return @[ @"USB Product ID", @"idProduct", @"USB_Product_ID" ];
}

static NSArray<NSString *> *MLSerialKeys(void) {
    return @[ @"USB Serial Number", @"kUSBSerialNumberString" ];
}

static NSArray<NSString *> *MLInterfaceClassKeys(void) {
    return @[ @"bInterfaceClass", @"interfaceClasses" ];
}

static NSArray<NSString *> *MLInterfaceProtocolKeys(void) {
    return @[ @"bInterfaceProtocol", @"interfaceProtocols" ];
}

/// Identifiers arrive as numbers or as hex text. Text that is not hex shaped was not an
/// identifier and is returned as unread rather than parsed as decimal: a device whose
/// vendor id is misread is a device that can be matched against the wrong rule.
static NSNumber *MLIdentifierFromProperty(id value) {
    if ([value isKindOfClass:[NSNumber class]]) {
        return value;
    }
    if (![value isKindOfClass:[NSString class]]) {
        return nil;
    }
    NSString *text = (NSString *)value;
    if ([text hasPrefix:@"0x"] || [text hasPrefix:@"0X"]) {
        text = [text substringFromIndex:2];
    }
    if (text.length == 0 || text.length > 4) {
        return nil;
    }
    unsigned int parsed = 0;
    for (NSUInteger index = 0; index < text.length; index++) {
        const unichar character = [text characterAtIndex:index];
        int digit;
        if (character >= '0' && character <= '9') {
            digit = character - '0';
        } else if (character >= 'a' && character <= 'f') {
            digit = character - 'a' + 10;
        } else if (character >= 'A' && character <= 'F') {
            digit = character - 'A' + 10;
        } else {
            return nil;
        }
        parsed = (parsed << 4) | (unsigned int)digit;
    }
    return @(parsed);
}

static NSNumber *MLIdentifierFromKeys(NSDictionary<NSString *, id> *properties,
                                      NSArray<NSString *> *keys) {
    for (NSString *key in keys) {
        NSNumber *value = MLIdentifierFromProperty(properties[key]);
        if (value != nil) {
            return value;
        }
    }
    return nil;
}

static NSArray *MLPropertyAsList(id value) {
    if (value == nil) {
        return @[];
    }
    return [value isKindOfClass:[NSArray class]] ? value : @[ value ];
}

/// Interfaces are the reason a device is refused or allowed, so they are read with the
/// protocol byte when the registry has one and marked as unread when it does not. An unread
/// protocol is treated by the policy as boot capable -- see isBootInputInterface -- because
/// the safe direction is the one that costs a player a click, not the one that hands a
/// keyboard to a remote machine.
static NSArray<MLUSBInterfaceDescriptor *> *MLInterfacesFromProperties(
    NSDictionary<NSString *, id> *properties) {
    NSArray *classes = @[];
    for (NSString *key in MLInterfaceClassKeys()) {
        NSArray *candidate = MLPropertyAsList(properties[key]);
        if (candidate.count > 0) {
            classes = candidate;
            break;
        }
    }

    NSArray *protocols = @[];
    for (NSString *key in MLInterfaceProtocolKeys()) {
        NSArray *candidate = MLPropertyAsList(properties[key]);
        if (candidate.count > 0) {
            protocols = candidate;
            break;
        }
    }

    NSMutableArray<MLUSBInterfaceDescriptor *> *interfaces = [NSMutableArray array];
    for (id classValue in classes) {
        NSNumber *major = MLIdentifierFromProperty(classValue);
        if (major == nil) {
            continue;
        }
        const BOOL paired = protocols.count == classes.count;
        NSNumber *protocol = paired ? MLIdentifierFromProperty(protocols[interfaces.count]) : nil;
        MLUSBInterfaceDescriptor *interface =
            protocol != nil
            ? [[MLUSBInterfaceDescriptor alloc] initWithMajorClass:(unsigned char)major.unsignedCharValue
                                                        minorClass:0
                                                     protocolClass:(unsigned char)protocol.unsignedCharValue]
            : [MLUSBInterfaceDescriptor interfaceWithMajorClass:(unsigned char)major.unsignedCharValue
                                                     minorClass:0
                                                  protocolKnown:NO];
        [interfaces addObject:interface];
    }
    return interfaces;
}

@implementation MLUSBDeviceIdentity
- (instancetype)initWithVendorID:(NSNumber *)vendorID
                       productID:(NSNumber *)productID
                      interfaces:(NSArray<MLUSBInterfaceDescriptor *> *)interfaces
                      auditToken:(NSString *)auditToken {
    self = [super init];
    if (self) {
        _vendorID = [vendorID copy];
        _productID = [productID copy];
        _interfaces = [interfaces copy] ?: @[];
        _auditToken = [auditToken copy] ?: @"none";
        // No serial, in a property a caller could hand to something that logs its argument.
        _descriptor = [MLUSBDeviceDescriptor descriptorWithVendorID:_vendorID
                                                         productID:_productID
                                                        interfaces:_interfaces];
    }
    return self;
}

- (NSString *)diagnosticLineForVerdict:(MLDeviceRedirectionVerdict *)verdict {
    NSMutableString *line = [NSMutableString stringWithFormat:@"usb device: vid=%@ pid=%@ classes=%@ token=%@",
                                                                  MLUSBIdentityName(self.vendorID),
                                                                  MLUSBIdentityName(self.productID),
                                                                  MLUSBInterfaceClassNames(self.interfaces),
                                                                  self.auditToken];
    if (verdict != nil) {
        [line appendFormat:@" decision=%@ reason=%@ rule=%ld",
                           verdict.isAllowed ? @"allow" : @"deny",
                           MLDeviceRedirectionDenialName(verdict.denial),
                           (long)verdict.ruleIndex];
    }
    return line;
}
@end

static NSString *MLSerialNumberFromProperties(NSDictionary<NSString *, id> *properties) {
    for (NSString *key in MLSerialKeys()) {
        id candidate = properties[key];
        if ([candidate isKindOfClass:[NSString class]] && [(NSString *)candidate length] > 0) {
            return candidate;
        }
    }
    return nil;
}

/// The one place an identity gets built, so there is one digest call, one set of identifier
/// keys and one interface reading -- not two that can drift apart once the bus changes shape.
MLUSBDeviceIdentity *MLUSBDeviceIdentityFromRegistryNodes(
    NSArray<NSDictionary<NSString *, id> *> *nodes) {
    NSNumber *vendorID = nil;
    NSNumber *productID = nil;
    NSString *serialNumber = nil;
    NSMutableArray<MLUSBInterfaceDescriptor *> *interfaces = [NSMutableArray array];

    for (NSDictionary<NSString *, id> *node in nodes) {
        // Each identifier half is taken once, from the first node that spells it. The measured
        // bus publishes idVendor and idProduct on the interface objects as well, so a caller
        // that walked only the interface nodes still names the device instead of being forced
        // to refuse something it can see.
        if (vendorID == nil) {
            vendorID = MLIdentifierFromKeys(node, MLVendorKeys());
        }
        if (productID == nil) {
            productID = MLIdentifierFromKeys(node, MLProductKeys());
        }
        if (serialNumber == nil) {
            serialNumber = MLSerialNumberFromProperties(node);
        }
        // The union, in the order the registry gave, duplicates included. This is where a
        // composite device stops being two devices: the storage face and the smart-card face
        // end up on one descriptor, so the reserved-class gate sees the smart card and refuses
        // the whole thing rather than allowing the half that was looked at first.
        [interfaces addObjectsFromArray:MLInterfacesFromProperties(node)];
    }

    // Digested here, not later. The serial number exists in this function's locals and
    // nowhere else, so there is no object that can be logged with it inside.
    return [[MLUSBDeviceIdentity alloc] initWithVendorID:vendorID
                                               productID:productID
                                              interfaces:interfaces
                                              auditToken:MLUSBDeviceAuditToken(serialNumber)];
}

MLUSBDeviceIdentity *MLUSBDeviceIdentityFromRegistryProperties(NSDictionary<NSString *, id> *properties) {
    // One node is the degenerate case of a device laid out as nodes, so it is expressed as
    // that rather than as a second reading of the same keys.
    return MLUSBDeviceIdentityFromRegistryNodes(properties == nil ? @[] : @[ properties ]);
}
