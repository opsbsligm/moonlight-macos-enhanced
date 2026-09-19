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
depend on, and driven with devices that do not exist. Six defects are planted one at a time:
the serial written out instead of digested, the serial dropped so every device looks alike,
the hex length bound removed, half-parsed text believed, a protocol byte matched to the wrong
interface, and a key-name list shortened.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
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

static void check(BOOL ok, const char *what) {
    if (!ok) failures++;
    printf("%-4s %s\n", ok ? "ok" : "FAIL", what);
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

        printf("%s\n", failures ? "RUN FAILED" : "RUN PASSED");
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
            check(code == 0 and out is not None and "RUN PASSED" in out,
                  "the shipping enumeration reads and speaks correctly"
                  if code == 0 else "the shipping enumeration failed a case:%s" % out)
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

    print("%d usb-device-enumeration failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
