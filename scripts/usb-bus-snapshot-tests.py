#!/usr/bin/env python3
"""Prove the bus is read whole, read without being touched, and read without being described.

scripts/usb-device-enumeration-tests.py checks what a device may be called once its properties are
in hand. This file checks the step before that -- which registry nodes belong to which device --
and it is the step where the measurement in docs 2.5 matters most: on macOS 27.2 the interface
iterator named 11 interfaces while the attached devices named 16 under themselves, five of which the
iterator did not return at all. A snapshot assembled from the iterator would therefore describe a
composite device by part of its faces, which is the exact thing the reserved-class refusal in 4.5
exists to prevent. So grouping happens by the parent link, and the parent link is verified.

Four claims hold the file together, and each has a planted defect:

  an interface goes to the device it names as its parent, and nowhere else. Two devices with the
    same vendor and product id have to stay two devices, or one of them inherits the other's
    allow-list rule; an interface whose parent is unknown has to stay on its own, or it becomes
    evidence about a device it never named;
  the device node leads its group. A reading that began with interfaces would report the first
    face it met as the device, and 4.5 was written for the case where that face is a smart-card
    interface on a storage dock;
  nothing is opened. This is a read of the registry and nothing more: no service is opened, no
    interface is claimed, no property is written. The rules that decide whether a device may be
    redirected are not allowed to be influenced by having already taken it over;
  the snapshot says nothing. Product names and serial numbers stay in the dictionaries Stage 1
    digests, which is checked two ways here: the source carries no literal for those keys, and the
    real scan's lines are compared against the personal strings ioreg reports for the same bus.

The live scan runs on whatever the runner has plugged in, so it asserts invariants rather than
counts: the registry was readable, a second scan says the same thing as the first, and no line it
produced carries a name from the bus.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

MIN_SNAPSHOT_CHECKS = 30
SNAPSHOT_H = "Limelight/Stream/USBBusSnapshot.h"
SNAPSHOT_M = "Limelight/Stream/USBBusSnapshot.m"
ENUM_H = "Limelight/Stream/USBDeviceEnumeration.h"
ENUM_M = "Limelight/Stream/USBDeviceEnumeration.m"
POLICY_H = "Limelight/Stream/DeviceRedirectionPolicy.h"
POLICY_M = "Limelight/Stream/DeviceRedirectionPolicy.m"

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def code_only(text):
    """The source with its comments removed.

    Every rule below is a rule about what the file does, so none of them may fire on prose. The
    header carries the measurement that says why an interface iterator is the wrong assembly, and
    an audit that treated that sentence as the bug would end up deleting the reason.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def strip_imports(text, quoted):
    for name in quoted:
        text = text.replace('#import "%s"\n' % name, "")
    # Foundation and IOKit both stay: the live scan is part of what gets compiled, and a check
    # that quietly dropped the bus access would be checking a different file.
    return text.replace("#import <Foundation/Foundation.h>\n", "")


def shipping_rules():
    header, impl = read(SNAPSHOT_H), read(SNAPSHOT_M)
    check(sorted(set(re.findall(r"#import\s*<([^>]+)>", header))) == ["Foundation/Foundation.h"],
          "the snapshot header exposes no framework beyond Foundation")
    check(sorted(set(re.findall(r"#import\s*<([^>]+)>", impl))) == ["IOKit/IOKitLib.h"],
          "IOKitLib is the only framework this file imports, and it is the only file that imports it")
    # In dependency order, so the bundle is a translation unit rather than an exercise in
    # forward declarations: the snapshot is the thing under test and sits last.
    rules = strip_imports(read(POLICY_H), ["DeviceRedirectionPolicy.h"]) + "\n" + \
        strip_imports(read(POLICY_M), ["DeviceRedirectionPolicy.h"]) + "\n" + \
        strip_imports(read(ENUM_H), ["USBDeviceEnumeration.h", "DeviceRedirectionPolicy.h"]) + "\n" + \
        strip_imports(read(ENUM_M), ["USBDeviceEnumeration.h", "DeviceRedirectionPolicy.h"]) + "\n" + \
        strip_imports(header, ["USBBusSnapshot.h", "USBDeviceEnumeration.h"]) + "\n" + \
        strip_imports(impl, ["USBBusSnapshot.h", "USBDeviceEnumeration.h"])
    check(sorted(set(re.findall(r"#import\s*<([^>]+)>", rules))) ==
          ["CommonCrypto/CommonDigest.h", "IOKit/IOKitLib.h"],
          "the compiled bundle imports the digest and the bus and nothing else")
    check("#import \"" not in rules, "the compiled bundle carries no quoted import")
    return rules, impl, header


SNAPSHOT = r"""
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>

@@RULES@@

static int failures = 0;
static int checks_run = 0;

/// Evaluate the expression exactly once. `if (!(ok)) ... printf(..., (ok) ? ...)` reads the
/// expression twice, and every case that hands a check a call with a side effect then performs it
/// twice -- which is how one gate in this repo ended up storing two rules behind a single `add`
/// and reported an impossible count. A check observes; it does not take part.
#define CHECK(ok, what) do { const BOOL _passed = (ok); checks_run++; if (!_passed) failures++; \
    printf("%-4s %s\n", _passed ? "ok" : "FAIL", (what)); } while (0)

/// How many times the checks below have evaluated an expression.
static int evaluationCount = 0;
static BOOL ExpressionWasEvaluatedOnce(void) {
    evaluationCount++;
    return evaluationCount == 1;
}

#define DEVICE_NODE(vendor, product) @{ @"idVendor" : @(vendor), @"idProduct" : @(product), \
    @"USB Product Name" : @"Example Webcam" }
#define IFACE_NODE(vendor, product, number, klass) @{ @"idVendor" : @(vendor), \
    @"idProduct" : @(product), @"bInterfaceNumber" : @(number), \
    @"bInterfaceClass" : @(klass), @"bInterfaceProtocol" : @(0) }

static NSSet *Keys(NSDictionary *node) { return [NSSet setWithArray:[node allKeys]]; }

static NSUInteger GroupCount(NSArray *groups) { return groups.count; }

/// The interface number of the one interface in a group, so a case can say which interface landed
/// where without comparing object identities that a fresh literal can never satisfy.
static NSNumber *InterfaceNumberInGroup(NSArray *group) {
    for (NSDictionary *node in group) {
        if (MLUSBBusNodeRoleForPropertyKeys(Keys(node)) == MLUSBBusNodeRoleInterface) {
            return node[@"bInterfaceNumber"];
        }
    }
    return nil;
}

static BOOL GroupHasRole(NSArray *group, NSUInteger index, MLUSBBusNodeRole role) {
    if (index >= group.count) return NO;
    return MLUSBBusNodeRoleForPropertyKeys(Keys(group[index])) == role;
}

int main(void) {
    @autoreleasepool {
        printf("-- which nodes belong to which device, and what may be said about them --\n");

        // The harness proves its own macro first. Both lines fail when a check double-evaluates,
        // so the defect cannot come back disguised as a passing case list.
        CHECK(ExpressionWasEvaluatedOnce(), "a check evaluates the expression it is given");
        CHECK(evaluationCount == 1,
              "and once only, so a case with a side effect has exactly one side effect");

        // What makes a node an interface. Measured: every interface node carries bInterfaceNumber
        // and no device node carries a key whose name mentions an interface at all.
        CHECK(MLUSBBusNodeRoleForPropertyKeys(Keys(IFACE_NODE(0x1234, 0x5678, 0, 239))) ==
                  MLUSBBusNodeRoleInterface, "an interface number in the keys makes a node an interface");
        CHECK(MLUSBBusNodeRoleForPropertyKeys([NSSet setWithObject:@"USB Interface Number"]) ==
                  MLUSBBusNodeRoleInterface, "the historical spelling is tried as well");
        CHECK(MLUSBBusNodeRoleForPropertyKeys(Keys(DEVICE_NODE(0x1234, 0x5678))) ==
                  MLUSBBusNodeRoleNotInterface, "a device node's keys name no interface");
        CHECK(MLUSBBusNodeRoleForPropertyKeys([NSSet setWithArray:
                  @[ @"bInterfaceClass", @"bInterfaceSubClass", @"bInterfaceProtocol" ]]) ==
                  MLUSBBusNodeRoleNotInterface,
              "an interface class is not an interface number: a device gets to choose its class");
        CHECK(MLUSBBusNodeRoleForPropertyKeys([NSSet set]) == MLUSBBusNodeRoleNotInterface,
              "no keys is not an interface");
        CHECK(MLUSBBusNodeRoleForPropertyKeys((NSSet *)@"bInterfaceNumber") ==
                  MLUSBBusNodeRoleNotInterface, "keys that are not a set are refused rather than read");
        CHECK(![MLUSBBusSnapshotStatusName(MLUSBBusSnapshotStatusRead)
                  isEqual:MLUSBBusSnapshotStatusName(MLUSBBusSnapshotStatusBusUnreadable)],
              "a bus that was read and a bus that was not do not share a name");
        CHECK([MLUSBBusNodeRoleName(MLUSBBusNodeRoleInterface) isEqual:@"interface"] &&
              ![MLUSBBusNodeRoleName(MLUSBBusNodeRoleInterface)
                  isEqual:MLUSBBusNodeRoleName(MLUSBBusNodeRoleNotInterface)],
              "the two roles have two names");

        // Grouping. One device with two interfaces is the ordinary composite case.
        NSDictionary *webcam = DEVICE_NODE(0x1234, 0x5678);
        NSDictionary *camera = IFACE_NODE(0x1234, 0x5678, 0, 14);
        NSDictionary *microphone = IFACE_NODE(0x1234, 0x5678, 1, 14);
        NSArray *one = MLUSBBusGroupNodes(@[ webcam ], @[ @"1" ],
                                          @[ camera, microphone ], @[ @"1", @"1" ]);
        CHECK(GroupCount(one) == 1, "one device and its two interfaces make one group");
        CHECK(((NSArray *)one[0]).count == 3, "the interfaces arrive with the device, not instead of it");
        CHECK(GroupHasRole(one[0], 0, MLUSBBusNodeRoleNotInterface),
              "the device node leads its group");
        CHECK(GroupHasRole(one[0], 1, MLUSBBusNodeRoleInterface) &&
                  GroupHasRole(one[0], 2, MLUSBBusNodeRoleInterface),
              "every interface of the device is in the group");

        // Two identical products stay two devices. The rule is the parent's registry identity, and
        // an identifier would have merged them and handed one the other's rule.
        // The two interfaces arrive in the opposite order to the parents that claim them, so an
        // implementation that walked the two lists together would pass by accident and this one
        // fails: placement follows the parent link and nothing else.
        NSArray *twins = MLUSBBusGroupNodes(@[ DEVICE_NODE(0x045E, 0x07A5),
                                               DEVICE_NODE(0x045E, 0x07A5) ],
                                            @[ @"10", @"11" ],
                                            @[ IFACE_NODE(0x045E, 0x07A5, 101, 3),
                                               IFACE_NODE(0x045E, 0x07A5, 100, 3) ],
                                            @[ @"11", @"10" ]);
        CHECK(GroupCount(twins) == 2, "two devices that report the same ids are still two devices");
        CHECK(((NSArray *)twins[0]).count == 2 && ((NSArray *)twins[1]).count == 2,
              "each keeps the interface that named it as parent");
        CHECK([InterfaceNumberInGroup(twins[0]) isEqualToNumber:@100] &&
              [InterfaceNumberInGroup(twins[1]) isEqualToNumber:@101],
              "each keeps the interface that named it, not the one that arrived beside it");

        // A contested device id goes to the group that appeared first.
        NSArray *contested = MLUSBBusGroupNodes(@[ DEVICE_NODE(1, 1), DEVICE_NODE(1, 1) ],
                                                @[ @"9", @"9" ],
                                                @[ IFACE_NODE(1, 1, 0, 8) ], @[ @"9" ]);
        CHECK(((NSArray *)contested[0]).count == 2 && ((NSArray *)contested[1]).count == 1,
              "a duplicate id attaches to the first group, not the last");

        // An interface whose parent this pass did not see. Attached nowhere, kept on its own.
        NSArray *orphan = MLUSBBusGroupNodes(@[ webcam ], @[ @"1" ],
                                             @[ IFACE_NODE(0x9999, 0x0001, 0, 3) ], @[ @"77" ]);
        CHECK(GroupCount(orphan) == 2, "an interface with an unknown parent becomes its own group");
        CHECK(((NSArray *)orphan[0]).count == 1, "it is not attached to the device it did not name");
        CHECK(((NSArray *)orphan[1]).count == 1 && GroupHasRole(orphan[1], 0, MLUSBBusNodeRoleInterface),
              "and it is kept rather than dropped");
        CHECK(MLUSBBusDeviceIdentityFromGroup(orphan[1]).vendorID.intValue == 0x9999,
              "an orphan is still describable: an interface node carries the identifiers too");

        // Arrays that do not line up are a broken caller, not a licence to borrow a parent.
        NSArray *shortParents = MLUSBBusGroupNodes(@[ webcam ], @[ @"1" ],
                                                   @[ camera, IFACE_NODE(0x9999, 1, 0, 3) ], @[ @"1" ]);
        CHECK(GroupCount(shortParents) == 2, "an interface with no entry in the parent list is not placed");
        CHECK(((NSArray *)shortParents[0]).count == 2, "the interface that did have a parent is still placed");

        // Malformed input refuses the element rather than the snapshot.
        NSArray *withGarbage = @[ webcam, @"not a node" ];
        CHECK(GroupCount(MLUSBBusGroupNodes(withGarbage, @[ @"1", @"2" ], @[], @[])) == 1,
              "a node that is not a dictionary is left out");
        CHECK(GroupCount(MLUSBBusGroupNodes(nil, nil, @[ camera ], @[ @"1" ])) == 1,
              "interfaces without any device still come back as a group");
        CHECK(GroupCount(MLUSBBusGroupNodes(nil, nil, nil, nil)) == 0,
              "nothing in and nothing out");

        // The composite case 4.5 exists for: a dock that is storage and a smart card at once.
        NSMutableArray *faces = [NSMutableArray arrayWithObject:DEVICE_NODE(0x0781, 0x55B8)];
        NSMutableArray *faceParents = [NSMutableArray array];
        NSUInteger classes[] = { 8, 2, 11, 255, 255 };
        for (NSUInteger i = 0; i < 5; i++) {
            [faces addObject:IFACE_NODE(0x0781, 0x55B8, (int)i, (int)classes[i])];
            [faceParents addObject:@"5"];
        }
        NSArray *dock = MLUSBBusGroupNodes(@[ faces[0] ], @[ @"5" ],
                                           [faces subarrayWithRange:NSMakeRange(1, 5)], faceParents);
        CHECK(((NSArray *)dock[0]).count == 6, "five faces of one device arrive as six nodes in one group");
        MLUSBDeviceIdentity *dockIdentity = MLUSBBusDeviceIdentityFromGroup(dock[0]);
        CHECK(dockIdentity.interfaces.count == 5,
              "all five interface classes are read, not the one the device happened to publish first");
        BOOL sawSmartCard = NO, sawStorage = NO;
        for (MLUSBInterfaceDescriptor *face in dockIdentity.interfaces) {
            if (face.majorClass == 11) sawSmartCard = YES;
            if (face.majorClass == 8) sawStorage = YES;
        }
        CHECK(sawSmartCard && sawStorage,
              "the reserved class survives the aggregation, so it can be refused");
        CHECK([MLDeviceRedirectionPolicy isReservedInterfaceClass:11],
              "and the policy still calls it reserved");

        // A serial the registry publishes on both nodes must digest to one token, and must not
        // appear where the token is written.
        NSMutableDictionary *withSerial = [webcam mutableCopy];
        withSerial[@"USB Serial Number"] = @"SN-1234-ABCD";
        NSMutableDictionary *ifaceWithSerial = [camera mutableCopy];
        ifaceWithSerial[@"USB Serial Number"] = @"SN-1234-ABCD";
        NSArray *serialGroup = MLUSBBusGroupNodes(@[ withSerial ], @[ @"1" ],
                                                  @[ ifaceWithSerial ], @[ @"1" ])[0];
        MLUSBDeviceIdentity *serialIdentity = MLUSBBusDeviceIdentityFromGroup(serialGroup);
        CHECK([serialIdentity.auditToken isEqualToString:serialIdentity.descriptor.serialNumber] == NO,
              "the audit token is not the serial number");
        CHECK([[serialIdentity diagnosticLineForVerdict:nil]
                   rangeOfString:@"SN-1234-ABCD"].location == NSNotFound,
              "the line about the device does not carry the serial number");
        CHECK(serialIdentity.vendorID.intValue == 0x1234 && serialIdentity.productID.intValue == 0x5678,
              "the identifiers are read from whichever node carries them");

        // An empty group is an unreadable device, not a device with nothing on it.
        MLUSBDeviceIdentity *nothing = MLUSBBusDeviceIdentityFromGroup(@[]);
        CHECK(nothing.vendorID == nil && nothing.interfaces.count == 0,
              "a group with no nodes describes nothing, and says so");
        CHECK([nothing.auditToken isEqualToString:@"none"], "and its token is the one for no serial");

        // The live scan. Invariants only: the runner's bus is not ours to choose.
        MLUSBBusSnapshotStatus status = MLUSBBusSnapshotStatusBusUnreadable;
        NSArray<MLUSBDeviceIdentity *> *first = MLUSBBusSnapshotCopyDeviceIdentities(&status);
        CHECK(status == MLUSBBusSnapshotStatusRead,
              "the registry could be iterated on this machine, so the cases below are not vacuous");
        CHECK(first != nil, "a scan always returns an array, even when the bus is empty");
        BOOL shapesAreRight = YES;
        for (MLUSBDeviceIdentity *identity in first) {
            if (![identity isKindOfClass:[MLUSBDeviceIdentity class]] ||
                identity.auditToken.length == 0 ||
                [[identity diagnosticLineForVerdict:nil] length] == 0) {
                shapesAreRight = NO;
            }
        }
        CHECK(shapesAreRight, "every device the bus reported is described and tokenised");
        MLUSBBusSnapshotStatus againStatus = MLUSBBusSnapshotStatusBusUnreadable;
        NSArray *second = MLUSBBusSnapshotCopyDeviceIdentities(&againStatus);
        CHECK(second.count == first.count && againStatus == status,
              "a second scan says the same thing as the first: nothing is remembered between them");
        printf("SCAN status=%s devices=%lu\n", MLUSBBusSnapshotStatusName(status).UTF8String,
               (unsigned long)first.count);
        for (MLUSBDeviceIdentity *identity in first) {
            NSString *line = [identity diagnosticLineForVerdict:nil];
            printf("AUDIT %s\n", line.length > 0 ? line.UTF8String : "<empty>");
        }

        printf("RUN PASSED (%d checks)\n", checks_run);
        return failures ? 1 : 0;
    }
}
"""


def compiled(source, work, name, cc, sdk):
    path = os.path.join(work, name + ".m")
    binary = os.path.join(work, name)
    open(path, "w", encoding="utf-8").write(source)
    built = subprocess.run([cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
                            "-fobjc-arc", "-framework", "Foundation", "-framework", "IOKit",
                            path, "-o", binary], capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr)[-2500:]
    ran = subprocess.run([binary], capture_output=True, text=True)
    return ran, (ran.stdout + ran.stderr)


def run_rules(label, rules, cc, sdk, expect_pass=False):
    with tempfile.TemporaryDirectory() as work:
        source = SNAPSHOT.replace("@@RULES@@", rules)
        ran, out = compiled(source, work, "snapshot_driver", cc, sdk)
        if ran is None:
            check(False, "%s: the harness compiled (%s)"
                  % (label, (out or "").strip().splitlines()[-1:]))
            return ""
        if expect_pass:
            reported = re.search(r"RUN PASSED \((\d+) checks\)", out or "")
            check(ran.returncode == 0, "%s behaves as documented" % label)
            if ran.returncode != 0:
                print("\n".join([line for line in (out or "").splitlines()
                                  if line.startswith("FAIL")])[:900])
            count = int(reported.group(1)) if reported else -1
            check(count >= MIN_SNAPSHOT_CHECKS,
                  "the compiled run reports its own case list (%d checks, floor %d)"
                  % (count, MIN_SNAPSHOT_CHECKS))
        else:
            check(ran.returncode != 0, "the check still fails when %s" % label)
            if ran.returncode == 0:
                print((out or "").strip().splitlines()[-3:])
        return out or ""


def mutated(rules, label, before, after):
    check(before in rules, "%s: the source it mutates is still there" % label)
    return rules.replace(before, after, 1)


def personal_strings_on_this_bus():
    """The names and serials this machine's USB bus publishes, for the leak check below.

    Read from `ioreg` rather than from the code under test on purpose: a leak check that asked the
    leaking code what it had leaked would be a tautology. An empty result is reported as such --
    a runner with nothing plugged in cannot prove anything was kept out -- and is not a pass.
    """
    try:
        ran = subprocess.run(["ioreg", "-l", "-p", "IOUSB"], capture_output=True, text=True,
                             timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if ran.returncode != 0:
        return None
    found = set()
    for key in ("USB Product Name", "Product Name", "USB Serial Number", "kUSBProductString",
                "iInterface"):
        for value in re.findall(r'"%s"\s*=\s*"([^"]+)"' % re.escape(key), ran.stdout):
            value = value.strip()
            if len(value) >= 5:
                found.add(value)
    return found


def main():
    rules, impl, header = shipping_rules()
    print("-- which nodes belong to which device, and what may be said about them --")

    cc, sdk = apple_toolchain.clang_and_sdk("usb bus snapshot")
    out = run_rules("the shipping snapshot", rules, cc, sdk, expect_pass=True)

    # The bus is read, never touched. Each of these would let the snapshot change what it is
    # looking at, which is the point a read-only view of a device has to keep.
    code = code_only(impl)
    code_and_header = code_only(impl) + code_only(header)
    for forbidden in ("IOServiceOpen", "IOConnectCallMethod", "IOConnectMethod",
                      "IORegistryEntrySetCFProperties", "IORegistryEntrySetFlags",
                      "IOServiceRequestProbe", "IOCreateQueue",
                      "IOServiceAddMatchingNotification", "IOServiceAddInterestNotification"):
        check(forbidden not in code,
              "the snapshot never calls %s: reading the bus is all it does" % forbidden)
    # The measurement that decided this file's shape. A second interface iterator would reintroduce
    # the missing-third bug from docs 2.5, and it would look like a reasonable implementation.
    for forbidden in ("IOUSBHostInterface", "IOUSBInterface"):
        check(forbidden not in code_and_header,
              "the snapshot never matches %s: the interface iterator is not the set of interfaces"
              % forbidden)
    check('IOServiceMatching("IOUSBHostDevice")' in code,
          "the snapshot walks down from the devices, which is where the whole set of interfaces is")
    check("IOUSBHostInterface" in header,
          "the header still says which iterator was measured to be incomplete, so the rule above "
          "reads as a finding and not as a stylistic preference")
    for forbidden in ('@"USB Serial', '@"USB Product Name', '@"Product Name', '@"iInterface'):
        check(forbidden not in impl,
              "the snapshot carries no literal for %s: it forwards nodes and interprets none"
              % forbidden)
    check("NSLog(" not in code and "printf(" not in code,
          "the snapshot has no path to the log of its own")
    for forbidden in ("NSUserDefaults", "NSDate", "CACurrentMediaTime", "clock_gettime",
                      "static NSMutableArray", "static NSArray"):
        check(forbidden not in code,
              "the snapshot holds no %s: a cached bus view is a bus view that is wrong" % forbidden)

    # Leak check against a source the code under test does not control.
    personal = personal_strings_on_this_bus()
    audits = "\n".join(line for line in out.splitlines() if line.startswith("AUDIT "))
    if personal is None:
        print("     ioreg could not read the USB plane, so the leak check could not run here")
    elif not personal:
        print("     no personal strings on this bus to test against, so the leak check is vacuous")
    elif not audits:
        print("     the scan reported no devices, so the leak check is vacuous")
    else:
        leaked = sorted(value for value in personal if value in audits)
        check(not leaked,
              "no product name or serial number from this bus appears in a line the panel could show"
              " (checked %d strings, leaked %d)" % (len(personal), len(leaked)))

    run_rules("an interface class is taken for an interface number",
              mutated(rules, "the candidate keys",
                      'return @[ @"bInterfaceNumber", @"USB Interface Number" ];',
                      'return @[ @"bInterfaceNumber", @"USB Interface Number", @"bInterfaceClass" ];'),
              cc, sdk)
    run_rules("no node is ever an interface",
              mutated(rules, "the role of every node",
                      '        if ([propertyKeys containsObject:candidate]) {\n            return MLUSBBusNodeRoleInterface;\n        }',
                      '        if ([propertyKeys containsObject:candidate]) {\n            return MLUSBBusNodeRoleNotInterface;\n        }'),
              cc, sdk)
    run_rules("an orphaned interface is attached to the first device",
              mutated(rules, "the orphan rule",
                      "        [groups addObject:[NSMutableArray arrayWithObject:node]];\n    }\n\n    return [groups copy];",
                      "        if (groups.count > 0) {\n            [groups[0] addObject:node];\n        } else {\n            [groups addObject:[NSMutableArray arrayWithObject:node]];\n        }\n    }\n\n    return [groups copy];"),
              cc, sdk)
    run_rules("a contested device id goes to whoever asked last",
              mutated(rules, "the first-wins rule",
                      "            groupOfDevice[deviceID] == nil) {",
                      "            YES) {"),
              cc, sdk)
    run_rules("a missing parent borrows its neighbour's",
              mutated(rules, "the parallel-array guard",
                      "    if (![array isKindOfClass:[NSArray class]] || index >= array.count) {\n        return nil;\n    }\n    return array[index];",
                      "    if (![array isKindOfClass:[NSArray class]] || array.count == 0) {\n        return nil;\n    }\n    return array[index < array.count ? index : array.count - 1];"),
              cc, sdk)
    run_rules("the device node is left out of its own group",
              mutated(rules, "the device joins its group",
                      "        [groups addObject:[NSMutableArray arrayWithObject:node]];\n        id deviceID",
                      "        [groups addObject:[NSMutableArray array]];\n        id deviceID"),
              cc, sdk)
    run_rules("a node that is not a dictionary is treated as one",
              mutated(rules, "the node type check",
                      "        id node = deviceNodes[index];\n        if (![node isKindOfClass:[NSDictionary class]]) {\n            continue;\n        }",
                      "        id node = deviceNodes[index];\n        if (![node isKindOfClass:[NSDictionary class]]) {\n            node = @{};\n        }"),
              cc, sdk)
    run_rules("a scan that read the bus never says it did",
              mutated(rules, "the readable answer is never given",
                      "    if (status != NULL) {\n        *status = MLUSBBusSnapshotStatusRead;\n    }\n    return [identities copy];",
                      "    return [identities copy];"),
              cc, sdk)
    run_rules("one of the two status names answers both states",
              mutated(rules, "the status names",
                      '    return status == MLUSBBusSnapshotStatusRead ? @"read" : @"bus-unreadable";',
                      '    return @"read";'),
              cc, sdk)

    print("%d usb-bus-snapshot failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
