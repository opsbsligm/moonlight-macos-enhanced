#!/usr/bin/env python3
"""Prove the bus can be read without turning a device list into a personal profile.

Stage 1 of docs/usb-redirection-design.md. Reading USB needs no driver extension and no new
entitlement -- an IORegistry iterator is open to any process -- so the risk in this stage is
not capability. It is speech. A product name and a serial number are personal data, and an
enumeration feature that logs what it saw has built a device fingerprint out of two fields
nobody stopped to think about.

So the shipping answer digests the serial where it is read, keeps it in no object, exposes
no accessor for a product name, and says nothing about a device that it did not read: a
vendor id is never filled in to make a device look complete, and an interface whose protocol
byte never arrived is marked unread rather than given a zero, because a zero is a real
protocol answer and the policy would believe it.

The header and the implementation are compiled whole, together with the Stage 0 policy they
depend on, and driven with devices that do not exist. The node-shaped fixtures are not
invented: they were read off the IORegistry on macOS 27.2 (docs/usb-redirection-design.md 2.5
records what that measurement said, including the two assumptions it overturned), so the
shipping parser is asserted against the shape the kernel hands over rather than a tidier one.

Defects are planted one at a time and every one has to be caught -- the serial written out
instead of digested, the serial dropped so every device looks alike, the hex length bound
removed, half-parsed text believed, a protocol byte matched to the wrong interface, a key-name
list shortened, an aggregation that stops at the first registry node, an aggregation that only
reads identifiers off the device node, one that collapses duplicate interfaces, a blob of bytes
becoming a vendor id, and a list becoming its first element. How many behavioural cases the
compiled binary ran is its own report, and the run is refused if that count falls below a floor.

The measurement that justified the node shapes is checked from here as well: the classifier in
scripts/usb-registry-shape.py is run against buses that are not attached, because the machine
that runs this gate usually has no USB devices on it.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

# The floor the compiled driver's own case count has to clear. It is a floor and not the
# count itself, because the count the binary prints is the truth and this number only notices
# a case list that got shorter.
MIN_DRIVER_CHECKS = 20
POLICY_H = "Limelight/Stream/DeviceRedirectionPolicy.h"
POLICY_M = "Limelight/Stream/DeviceRedirectionPolicy.m"
ENUM_H = "Limelight/Stream/USBDeviceEnumeration.h"
ENUM_M = "Limelight/Stream/USBDeviceEnumeration.m"

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def strip_imports(text, quoted):
    for name in quoted:
        text = text.replace('#import "%s"\n' % name, "")
    return text.replace("#import <Foundation/Foundation.h>\n", "")


def shipping_rules():
    policy_h, policy_m = read(POLICY_H), read(POLICY_M)
    enum_h, enum_m = read(ENUM_H), read(ENUM_M)
    check(re.findall(r"#import\s*<(?:IOKit|DriverKit)[^>]*>", enum_h + enum_m) == [],
          "the enumeration layer links no IOKit: what is tested is the rules, not the bus")
    rules = strip_imports(policy_h, ["DeviceRedirectionPolicy.h"]) + "\n" + \
        strip_imports(policy_m, ["DeviceRedirectionPolicy.h"]) + "\n" + \
        strip_imports(enum_h, ["DeviceRedirectionPolicy.h", "USBDeviceEnumeration.h"]) + "\n" + \
        strip_imports(enum_m, ["USBDeviceEnumeration.h", "DeviceRedirectionPolicy.h"])
    check(sorted(set(re.findall(r"#import\s*<([^>]+)>", rules))) == ["CommonCrypto/CommonDigest.h"],
          "the compiled bundle imports one system header beyond Foundation, and it is the digest")
    return rules


DRIVER = r"""
#import <Foundation/Foundation.h>

@@RULES@@

static int failures = 0;
static int checks_run = 0;

static void check(BOOL ok, const char *what) {
    checks_run++;
    if (!ok) failures++;
    printf("%-4s %s\n", ok ? "ok" : "FAIL", what);
}

// expect_identity reports through printf rather than check(), so it counts itself.
static void count_a_check(void) {
    checks_run++;
}

static NSDictionary *device(id vendor, id product, id serial, id classes, id protocols,
                            id productName) {
    NSMutableDictionary *props = [NSMutableDictionary dictionary];
    if (vendor) props[@"USB Vendor ID"] = vendor;
    if (product) props[@"USB Product ID"] = product;
    if (serial) props[@"USB Serial Number"] = serial;
    if (classes) props[@"bInterfaceClass"] = classes;
    if (protocols) props[@"bInterfaceProtocol"] = protocols;
    if (productName) props[@"USB Product Name"] = productName;
    return props;
}

// The node shapes below were read off the registry rather than imagined: on macOS 27.2, for
// every device attached at the time, identifiers arrived as numbers under the io-kit short
// keys, each interface got its own node carrying one class byte and one protocol byte plus
// the device's identifiers and its own serial, and every node published a product name.
// The first version of this note also claimed no device published a serial number. That was
// wrong, and it was wrong because the probe asked for a key name the kernel does not use:
// docs/usb-redirection-design.md 2.5 records the correction, and scripts/usb-registry-shape.py
// is what keeps a probe from under-asking again.
static NSDictionary *measured_device_node(unsigned short vid, unsigned short pid, id name) {
    NSMutableDictionary *node = [NSMutableDictionary dictionary];
    node[@"idVendor"] = @(vid);
    node[@"idProduct"] = @(pid);
    node[@"bDeviceClass"] = @0;
    node[@"bDeviceProtocol"] = @0;
    node[@"USB Address"] = @3;
    if (name) node[@"USB Product Name"] = name;
    return node;
}

static NSDictionary *measured_interface_node(unsigned short vid, unsigned short pid,
                                             unsigned char interfaceClass,
                                             unsigned char subclass,
                                             unsigned char protocol, id name) {
    NSMutableDictionary *node = [NSMutableDictionary dictionary];
    node[@"idVendor"] = @(vid);
    node[@"idProduct"] = @(pid);
    node[@"bInterfaceClass"] = @(interfaceClass);
    node[@"bInterfaceSubClass"] = @(subclass);
    node[@"bInterfaceProtocol"] = @(protocol);
    if (name) node[@"USB Product Name"] = name;
    return node;
}

// Each half of the identifier is read on its own: a vendor id the registry never
// spelled is reported as unread, and the product id that did arrive stays honest.
static void expect_identity(const char *what, NSDictionary *props, unsigned short wantVid,
                            BOOL vidReadable, unsigned short wantPid, BOOL pidReadable) {
    MLUSBDeviceIdentity *identity = MLUSBDeviceIdentityFromRegistryProperties(props);
    BOOL gotVid = identity.vendorID != nil;
    BOOL gotPid = identity.productID != nil;
    BOOL ok = gotVid == vidReadable && gotPid == pidReadable &&
              (!vidReadable || identity.vendorID.unsignedShortValue == wantVid) &&
              (!pidReadable || identity.productID.unsignedShortValue == wantPid);
    count_a_check();
    if (!ok) failures++;
    printf("%-4s %-46s -> vid=%s pid=%s\n", ok ? "ok" : "FAIL", what,
           identity.vendorID ? identity.vendorID.stringValue.UTF8String : "unread",
           identity.productID ? identity.productID.stringValue.UTF8String : "unread");
}

int main(void) {
    @autoreleasepool {
        // Identifiers arrive as numbers or as hex text, under more than one key name.
        expect_identity("numeric identifiers", device(@0x28de, @0x2202, nil, @0x03, nil, nil),
                        0x28de, YES, 0x2202, YES);
        expect_identity("hex text identifiers", device(@"28de", @"2202", nil, @0x03, nil, nil),
                        0x28de, YES, 0x2202, YES);
        expect_identity("0x prefixed hex text", device(@"0x28de", @"0x2202", nil, @0x03, nil, nil),
                        0x28de, YES, 0x2202, YES);
        expect_identity("no identifiers at all", device(nil, nil, nil, @0x03, nil, nil),
                        0, NO, 0, NO);
        expect_identity("a too-long vendor id stays unread while its product id reads",
                        device(@"32768", @"2202", nil, @0x03, nil, nil), 0, NO, 0x2202, YES);
        expect_identity("half a hex number is not an identifier",
                        device(@"28deZ", @"2202", nil, @0x03, nil, nil), 0, NO, 0x2202, YES);
        // The short form is the one that tells a stop-and-keep from a refusal: four
        // characters clears the length guard, so only the scanner itself can refuse it.
        expect_identity("a non-hex tail voids the half not a prefix",
                        device(@"28dZ", @"2202", nil, @0x03, nil, nil), 0, NO, 0x2202, YES);
        // Two shapes the parser can be handed that the measured bus never published: an
        // identifier as raw bytes, and an identifier as a list. Neither is a number and
        // neither is text, so accepting one means choosing bytes or an element out of a
        // blob, which is how a device gets matched against the wrong rule. They are pinned
        // here so the rule outlives the absence, and usb-registry-shape.py turns them into
        // a red run the day a bus really carries one.
        expect_identity("a data-shaped identifier stays unread instead of becoming two bytes of a vendor id",
                        device([NSData dataWithBytes:(unsigned char[]){0x28, 0xde} length:2],
                               @0x2202, nil, @0x03, nil, nil), 0, NO, 0x2202, YES);
        expect_identity("an array-shaped identifier is not read out of its first element",
                        device(@[ @0x28de ], @0x2202, nil, @0x03, nil, nil),
                        0, NO, 0x2202, YES);

        MLUSBDeviceIdentity *shortNamed = MLUSBDeviceIdentityFromRegistryProperties(
            @{@"idVendor": @"046d", @"idProduct": @"c52b"});
        check(shortNamed.vendorID.unsignedShortValue == 0x046d &&
              shortNamed.productID.unsignedShortValue == 0xc52b,
              "the io-kit short key names are read too, not only the USB ones");

        // Interfaces, with the protocol byte when the registry had one.
        MLUSBDeviceIdentity *paired = MLUSBDeviceIdentityFromRegistryProperties(
            device(@0x28de, @0x2202, nil, @[@0x03], @[@0x00], nil));
        check(paired.interfaces.count == 1 && !paired.interfaces[0].isBootInputInterface,
              "an interface whose protocol byte arrived is believed");
        MLUSBDeviceIdentity *unpaired = MLUSBDeviceIdentityFromRegistryProperties(
            device(@0x28de, @0x2202, nil, @[@0x03], nil, nil));
        check(unpaired.interfaces.count == 1 && unpaired.interfaces[0].isBootInputInterface,
              "an interface whose protocol byte never arrived is not assumed harmless");
        MLUSBDeviceIdentity *mismatched = MLUSBDeviceIdentityFromRegistryProperties(
            device(@0x04d9, @0x1695, nil, @[@0x03, @0x03], @[@0x01], nil));
        check(mismatched.interfaces.count == 2 &&
              mismatched.interfaces[0].isBootInputInterface &&
              mismatched.interfaces[1].isBootInputInterface,
              "one protocol byte is not shared out to two interfaces");

        // The bus as it was measured, not as a single dictionary.
        NSArray *dongle = @[ measured_device_node(0x0c45, 0xff1c, @"HS USB Dongle"),
                             measured_interface_node(0x0c45, 0xff1c, 0x03, 0x01, 0x01, @"HS USB Dongle"),
                             measured_interface_node(0x0c45, 0xff1c, 0x03, 0x01, 0x02, @"HS USB Dongle"),
                             measured_interface_node(0x0c45, 0xff1c, 0x03, 0x00, 0x00, @"HS USB Dongle") ];
        MLUSBDeviceIdentity *hub = MLUSBDeviceIdentityFromRegistryNodes(dongle);
        check(hub.vendorID.unsignedShortValue == 0x0c45 &&
              hub.productID.unsignedShortValue == 0xff1c &&
              hub.interfaces.count == 3 &&
              hub.interfaces[0].isBootInputInterface &&
              hub.interfaces[1].isBootInputInterface &&
              !hub.interfaces[2].isBootInputInterface,
              "a device split across four registry nodes comes back as one device with three interfaces");
        check([hub.auditToken isEqual:@"none"],
              "a device the registry gave no serial for says none");
        check([[hub diagnosticLineForVerdict:nil]
               rangeOfString:@"HS USB Dongle"].location == NSNotFound,
              "the product name the registry publishes on every node stays out of the line");

        // Only the interface nodes: identifiers are published there too, so walking the
        // interfaces must not come back with a device the policy has to refuse as anonymous.
        MLUSBDeviceIdentity *fromInterfacesOnly =
            MLUSBDeviceIdentityFromRegistryNodes(@[ dongle[1], dongle[2], dongle[3] ]);
        check(fromInterfacesOnly.vendorID.unsignedShortValue == 0x0c45 &&
              fromInterfacesOnly.productID.unsignedShortValue == 0xff1c &&
              fromInterfacesOnly.interfaces.count == 3,
              "the interface nodes alone still identify the device they belong to");

        // Duplicates survive aggregation: two identical interface nodes is a fact about the
        // bus, and a set would quietly report one interface where the registry said two.
        MLUSBDeviceIdentity *twice = MLUSBDeviceIdentityFromRegistryNodes(
            @[ measured_interface_node(0x0c45, 0xff1c, 0x03, 0x01, 0x00, nil),
               measured_interface_node(0x0c45, 0xff1c, 0x03, 0x01, 0x00, nil) ]);
        check(twice.interfaces.count == 2,
              "two identical interface nodes are not collapsed into one");

        // The composite device the reserved-class rule was written for. It does not arrive as
        // an array of classes; it arrives as separate nodes, so an aggregation that stopped at
        // the first one would show the policy a storage device and allow the dock.
        MLDeviceRedirectionPolicy *dockPolicy =
            [[MLDeviceRedirectionPolicy alloc] initWithFeatureEnabled:YES
                                                        hostIsPaired:YES
                                         hostSupportsDeviceRedirection:YES
                                             allowedInterfaceClasses:[NSSet setWithObject:@(0x08)]
                                            localInputDevicesAllowed:NO
                                                               rules:@[[MLDeviceRedirectionRule ruleForVendorID:0x17ef
                                                                                                     productID:0x304f
                                                                                                       enabled:YES]]];
        NSDictionary *dockBody = measured_device_node(0x17ef, 0x304f, @"Thunderbolt Dock");
        NSDictionary *dockStorage = measured_interface_node(0x17ef, 0x304f, 0x08, 0x06, 0x50,
                                                           @"Thunderbolt Dock");
        NSDictionary *dockCard = measured_interface_node(0x17ef, 0x304f, 0x0b, 0x00, 0x00,
                                                         @"Thunderbolt Dock");
        MLDeviceRedirectionVerdict *splitVerdict =
            [dockPolicy verdictForDevice:[MLUSBDeviceIdentityFromRegistryNodes(
                @[ dockBody, dockStorage, dockCard ]) descriptor]];
        MLDeviceRedirectionVerdict *reversedVerdict =
            [dockPolicy verdictForDevice:[MLUSBDeviceIdentityFromRegistryNodes(
                @[ dockBody, dockCard, dockStorage ]) descriptor]];
        MLDeviceRedirectionVerdict *firstFaceOnly =
            [dockPolicy verdictForDevice:[MLUSBDeviceIdentityFromRegistryNodes(
                @[ dockBody, dockStorage ]) descriptor]];
        check(splitVerdict.denial == MLDeviceRedirectionDenialClassReserved &&
              reversedVerdict.denial == MLDeviceRedirectionDenialClassReserved &&
              firstFaceOnly.isAllowed,
              "a dock arrives as separate nodes and is refused whichever face is looked at first");

        MLUSBDeviceIdentity *noNodes = MLUSBDeviceIdentityFromRegistryNodes(@[]);
        check(noNodes.vendorID == nil && noNodes.productID == nil &&
              noNodes.interfaces.count == 0 && [noNodes.auditToken isEqual:@"none"],
              "no nodes is an unreadable device, not an empty one");

        // What may be said about a device.
        MLUSBDeviceIdentity *dock = MLUSBDeviceIdentityFromRegistryProperties(
            device(@0x17ef, @0x304f, @"S3CR3T-SERIAL", @[@0x08, @0x0b], nil, @"Thunderbolt Dock"));
        MLDeviceRedirectionPolicy *policy =
            [[MLDeviceRedirectionPolicy alloc] initWithFeatureEnabled:YES
                                                        hostIsPaired:YES
                                         hostSupportsDeviceRedirection:YES
                                             allowedInterfaceClasses:[NSSet setWithObject:@(0x08)]
                                            localInputDevicesAllowed:NO
                                                               rules:@[[MLDeviceRedirectionRule ruleForVendorID:0x17ef
                                                                                                     productID:0x304f
                                                                                                       enabled:YES]]];
        MLDeviceRedirectionVerdict *verdict = [policy verdictForDevice:dock.descriptor];
        NSString *line = [dock diagnosticLineForVerdict:verdict];
        check(verdict.denial == MLDeviceRedirectionDenialClassReserved,
              "a dock that is also a smart card is refused through the enumeration path too");
        check([line rangeOfString:@"S3CR3T-SERIAL"].location == NSNotFound &&
              [line rangeOfString:@"Thunderbolt Dock"].location == NSNotFound,
              "the line carries no serial and no product name");
        check([line rangeOfString:@"token="].location != NSNotFound &&
              [line rangeOfString:@"reason=class-reserved"].location != NSNotFound,
              "the line names the device by digest and says why it was refused");
        check(dock.descriptor.serialNumber == nil,
              "no object built here carries the serial number at all");

        MLUSBDeviceIdentity *same = MLUSBDeviceIdentityFromRegistryProperties(
            device(@0x17ef, @0x304f, @"S3CR3T-SERIAL", @[@0x08], nil, nil));
        MLUSBDeviceIdentity *other = MLUSBDeviceIdentityFromRegistryProperties(
            device(@0x17ef, @0x304f, @"ANOTHER-SERIAL", @[@0x08], nil, nil));
        MLUSBDeviceIdentity *blank = MLUSBDeviceIdentityFromRegistryProperties(
            device(@0x17ef, @0x304f, nil, @[@0x08], nil, nil));
        check([same.auditToken isEqual:dock.auditToken] &&
              ![same.auditToken isEqual:other.auditToken] &&
              same.auditToken.length == 8 && [blank.auditToken isEqual:@"none"],
              "one serial is one token, two serials are two, and no serial says none");

        printf("%s (%d checks)\n", failures ? "RUN FAILED" : "RUN PASSED", checks_run);
        return failures ? 1 : 0;
    }
}
"""


def compiled(source, work, name, cc, sdk):
    path = os.path.join(work, name + ".m")
    open(path, "w", encoding="utf-8").write(source)
    command = [cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
               "-framework", "Foundation", path, "-o", os.path.join(work, name)]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return None, None, (built.stdout + built.stderr).strip()[-2500:]
    ran = subprocess.run([os.path.join(work, name)], capture_output=True, text=True)
    return ran.returncode, ran.stdout, (ran.stdout + ran.stderr).strip()[-2500:]


def run_rules(label, rules, cc, sdk, expect_pass=False):
    with tempfile.TemporaryDirectory() as work:
        code, out, log = compiled(DRIVER.replace("@@RULES@@", rules), work, "usbenum", cc, sdk)
        if code is None:
            check(False, "%s: %s" % (label, log))
            return
        if expect_pass:
            passed = code == 0 and out is not None and "RUN PASSED" in out
            check(passed, "the shipping enumeration reads and speaks correctly"
                  if passed else "the shipping enumeration failed a case:%s" % out)
            # A compiled run that quietly lost cases still reports success, so the count the
            # binary printed for the cases it executed is checked against a floor: only the
            # number notices a case list that was shortened.
            reported = re.search(r"RUN PASSED \((\d+) checks\)", out or "")
            counted = int(reported.group(1)) if reported else -1
            check(counted >= MIN_DRIVER_CHECKS,
                  "the compiled run reports its own case list (%d checks, floor %d)"
                  % (counted, MIN_DRIVER_CHECKS))
        else:
            check(code != 0, "the check still fails when %s" % label)


def mutated(rules, label, before, after):
    check(before in rules, "%s: the source it mutates is still there" % label)
    return rules.replace(before, after, 1)


def main():
    rules = shipping_rules()
    impl = read(ENUM_M)
    print("-- what the bus can be read as, and what may be said about it --")

    cc, sdk = apple_toolchain.clang_and_sdk("usb device enumeration")
    run_rules("the shipping enumeration", rules, cc, sdk, expect_pass=True)

    check("NSLog(" not in impl and "printf(" not in impl,
          "the enumeration has no path to the log of its own")
    check("Product Name" not in impl.split("@end")[-1],
          "nothing on the read path even looks at a product name")
    entitlements = read("Moonlight.entitlements")
    check("usb" not in entitlements.lower(),
          "reading the bus needed no new entitlement, and none was added")

    # The bus-shape classifier has to be right for the 2.5 table to mean anything, and a
    # CI runner has no USB devices on it -- so the classifier is exercised against buses
    # that are not attached, from inside a gate that already runs everywhere.
    shape_tool = subprocess.run(
        [sys.executable, os.path.abspath(os.path.join(ROOT, "scripts", "usb-registry-shape.py")),
         "--self-test", "--root", os.path.abspath(ROOT)], capture_output=True, text=True)
    check(shape_tool.returncode == 0 and "RUN PASSED" in shape_tool.stdout,
          "the bus-shape classifier checks itself, so a wrong measurement is caught with no bus attached")
    if shape_tool.returncode != 0:
        print(shape_tool.stdout[-1200:])
        print(shape_tool.stderr[-400:])

    run_rules("the serial is written out instead of digested",
              mutated(rules, "the serial digest",
                      "auditToken:MLUSBDeviceAuditToken(serialNumber)",
                      "auditToken:serialNumber ?: @\"none\""),
              cc, sdk)
    run_rules("the serial is dropped so every device looks alike",
              mutated(rules, "the serial dropped",
                      "auditToken:MLUSBDeviceAuditToken(serialNumber)",
                      "auditToken:(serialNumber == nil ? @\"none\" : @\"none\")"),
              cc, sdk)
    run_rules("a long string is parsed as an identifier anyway",
              mutated(rules, "the hex bound",
                      "if (text.length == 0 || text.length > 4) {",
                      "if (text.length == 0) {"),
              cc, sdk)
    run_rules("half-parsed text is believed as an identifier",
              mutated(rules, "the half parse",
                      "        } else {\n            return nil;\n        }\n        parsed = (parsed << 4)",
                      "        } else {\n            break;\n        }\n        parsed = (parsed << 4)"),
              cc, sdk)
    run_rules("one protocol byte is shared out across interfaces",
              mutated(rules, "the protocol pairing",
                      "const BOOL paired = protocols.count == classes.count;",
                      "const BOOL paired = protocols.count > 0;"),
              cc, sdk)
    run_rules("the short io-kit key name is dropped from the list",
              mutated(rules, "the key names",
                      '@[ @"USB Vendor ID", @"idVendor", @"USB_Vendor_ID" ]',
                      '@[ @"USB Vendor ID", @"USB_Vendor_ID" ]'),
              cc, sdk)
    run_rules("the aggregation stops at the first node's interfaces",
              mutated(rules, "the interface union",
                      "        [interfaces addObjectsFromArray:MLInterfacesFromProperties(node)];",
                      "        if (interfaces.count == 0) {\n"
                      "            [interfaces addObjectsFromArray:MLInterfacesFromProperties(node)];\n"
                      "        }"),
              cc, sdk)
    run_rules("identifiers are only taken from a node that is not an interface",
              mutated(rules, "the identifier sweep",
                      "        if (vendorID == nil) {",
                      "        if (vendorID == nil && MLInterfacesFromProperties(node).count == 0) {"),
              cc, sdk)
    run_rules("a data-shaped identifier becomes two bytes of a vendor id",
              mutated(rules, "the data identifier",
                      "    if (![value isKindOfClass:[NSString class]]) {\n        return nil;",
                      "    if ([value isKindOfClass:[NSData class]] && [(NSData *)value length] >= 2) {\n"
                      "        const unsigned char *bytes = [(NSData *)value bytes];\n"
                      "        return @(((unsigned int)bytes[0] << 8) | bytes[1]);\n"
                      "    }\n"
                      "    if (![value isKindOfClass:[NSString class]]) {\n        return nil;"),
              cc, sdk)
    run_rules("an array-shaped identifier becomes its first element",
              mutated(rules, "the array identifier",
                      "    if (![value isKindOfClass:[NSString class]]) {\n        return nil;",
                      "    if ([value isKindOfClass:[NSArray class]] && [(NSArray *)value count] > 0) {\n"
                      "        return MLIdentifierFromProperty([(NSArray *)value objectAtIndex:0]);\n"
                      "    }\n"
                      "    if (![value isKindOfClass:[NSString class]]) {\n        return nil;"),
              cc, sdk)
    run_rules("identical interfaces are collapsed while aggregating",
              mutated(rules, "the duplicate union",
                      "        [interfaces addObjectsFromArray:MLInterfacesFromProperties(node)];",
                      "        for (MLUSBInterfaceDescriptor *candidate in MLInterfacesFromProperties(node)) {\n"
                      "            BOOL seen = NO;\n"
                      "            for (MLUSBInterfaceDescriptor *kept in interfaces) {\n"
                      "                seen = seen || (kept.majorClass == candidate.majorClass &&\n"
                      "                            kept.protocolClass == candidate.protocolClass);\n"
                      "            }\n"
                      "            if (!seen) {\n"
                      "                [interfaces addObject:candidate];\n"
                      "            }\n"
                      "        }"),
              cc, sdk)

    print("%d usb-device-enumeration failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
