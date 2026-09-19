#!/usr/bin/env python3
"""Prove that a device gets refused by default, and that the refusal says why.

This is stage 0 of docs/usb-redirection-design.md. The design's conclusion is that a
device cannot be handed to a streaming host today: moonlight-common-c carries HID
semantics and no device channel, and a driver extension would have to be signed and
notarised with a certificate this project does not have. What can be built now, and what
has to exist before that changes, is the part that cannot be talked into saying yes.

So the shipping answer is lifted whole out of DeviceRedirectionPolicy.h and .m and
compiled with a real clang, then played against the devices a USB bus actually holds: a
gamepad that is only a gamepad, a boot keyboard, a webcam, a dock that is storage and a
smart card at once, and a device whose vendor id was never read. Every one of them is
checked for the decision and for the reason, because a refusal that cannot explain itself
is how a policy bug becomes a support thread.

The gates have to fire in the written order, so each one is driven alone: a case that
would end in the same refusal whichever gate fired proves nothing about which one did.
Seven defects are then planted one at a time -- refuse by default inverted, the pairing
gate removed, the reserved classes emptied, the local-input gate removed, the order of the
two input gates swapped, product ids left to match any rule, and the serial number written
into the log -- and each has to be caught. A mutation that does not even change the source
fails on its own, because a mutation that silently does nothing is worse than none.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
HEADER = "Limelight/Stream/DeviceRedirectionPolicy.h"
IMPL = "Limelight/Stream/DeviceRedirectionPolicy.m"

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def shipping_rules():
    """The header and the implementation, whole, with only the two import lines removed."""
    header_raw, impl_raw = read(HEADER), read(IMPL)
    check(re.findall(r"#import\s*<[^>]+>", header_raw) == ["#import <Foundation/Foundation.h>"],
          "the header imports nothing but Foundation")
    check(re.findall(r'#import\s*"([^"]+)"', impl_raw) == ["DeviceRedirectionPolicy.h"] and
          re.findall(r"#import\s*<([^>]+)>", impl_raw) == ["CommonCrypto/CommonDigest.h"],
          "the implementation imports one digest header and its own interface, nothing else")
    return (header_raw.replace("#import <Foundation/Foundation.h>\n", "")
            .replace('#import "DeviceRedirectionPolicy.h"\n', "")
            + "\n" + impl_raw.replace('#import "DeviceRedirectionPolicy.h"\n', ""))


# The two gates whose order is a decision, kept here as the exact text so the swap below
# cannot quietly mutate nothing.
# Written out here as well as there, so a mutation that quietly stops applying is caught.
IDENTITY_GATE = (
    "    if (!MLIdentityIsReadable(device.vendorID) || !MLIdentityIsReadable(device.productID) ||\n"
    "        device.interfaces.count == 0) {\n"
)
LEAKABLE_LINE = "    NSString *token = MLDeviceToken(device.serialNumber);"
LEAKED_LINE = (
    "    NSString *token = [MLDeviceToken(device.serialNumber) isEqualToString:@\"none\"]"
    " ? @\"none\" : device.serialNumber;"
)

LOCAL_INPUT_GATE = """    if (wantsLocalInput && !self.localInputDevicesAllowed) {
        return [self denialFor:MLDeviceRedirectionDenialLocalInputReserved
                        device:device token:token ruleIndex:-1];
    }
"""
CLASS_GATE = """    if (!anyClassAllowed) {
        return [self denialFor:MLDeviceRedirectionDenialClassNotAllowed
                        device:device token:token ruleIndex:-1];
    }
"""

DRIVER = r"""
#import <Foundation/Foundation.h>

@@RULES@@

static int failures = 0;


static const char *reasonName(MLDeviceRedirectionDenial denial) {
    switch (denial) {
        case MLDeviceRedirectionDenialNone: return "none";
        case MLDeviceRedirectionDenialFeatureDisabled: return "feature-disabled";
        case MLDeviceRedirectionDenialHostUnpaired: return "host-unpaired";
        case MLDeviceRedirectionDenialHostUnsupported: return "host-unsupported";
        case MLDeviceRedirectionDenialIdentityIncomplete: return "identity-incomplete";
        case MLDeviceRedirectionDenialClassReserved: return "class-reserved";
        case MLDeviceRedirectionDenialLocalInputReserved: return "local-input-reserved";
        case MLDeviceRedirectionDenialClassNotAllowed: return "class-not-allowed";
        case MLDeviceRedirectionDenialRuleDisabled: return "rule-disabled";
        case MLDeviceRedirectionDenialNoRule: return "no-rule";
    }
    return "unclassified";
}

static void check(BOOL ok, const char *what) {
    if (!ok) failures++;
    printf("%-4s %s\n", ok ? "ok" : "FAIL", what);
}

static MLUSBInterfaceDescriptor *iface(unsigned char major, unsigned char minor,
                                       unsigned char protocol) {
    return [[MLUSBInterfaceDescriptor alloc] initWithMajorClass:major
                                                     minorClass:minor
                                                  protocolClass:protocol];
}

static MLUSBDeviceDescriptor *device(unsigned short vid, unsigned short pid, NSString *serial,
                                     NSArray<MLUSBInterfaceDescriptor *> *interfaces) {
    return [MLUSBDeviceDescriptor descriptorWithVendorID:@(vid)
                                               productID:@(pid)
                                            serialNumber:serial
                                              interfaces:interfaces];
}

static MLDeviceRedirectionPolicy *policy(BOOL paired, BOOL hostSupports,
                                        NSSet<NSNumber *> *classes, BOOL localInput,
                                        NSArray<MLDeviceRedirectionRule *> *rules) {
    return [[MLDeviceRedirectionPolicy alloc] initWithFeatureEnabled:YES
                                                       hostIsPaired:paired
                                        hostSupportsDeviceRedirection:hostSupports
                                              allowedInterfaceClasses:classes
                                             localInputDevicesAllowed:localInput
                                                                rules:rules];
}

static void expect(const char *what, MLDeviceRedirectionPolicy *policy,
                   MLUSBDeviceDescriptor *subject, BOOL wantAllowed,
                   MLDeviceRedirectionDenial wantDenial, NSInteger wantRule) {
    MLDeviceRedirectionVerdict *verdict = [policy verdictForDevice:subject];
    BOOL ok = verdict.isAllowed == wantAllowed && verdict.denial == wantDenial &&
              verdict.ruleIndex == wantRule;
    if (!ok) failures++;
    printf("%-4s %-46s -> %s reason=%s rule=%ld (%s)\n", ok ? "ok" : "FAIL", what,
           verdict.isAllowed ? "allow" : "deny", reasonName(verdict.denial),
           (long)verdict.ruleIndex, verdict.auditLine.UTF8String);
    if (verdict.auditLine.length == 0) { failures++; printf("FAIL %s has no audit line\n", what); }
}

static void expect_capability(const char *what, NSDictionary *serverInfo, BOOL want) {
    BOOL got = [MLDeviceRedirectionPolicy hostAdvertisesDeviceRedirectionInServerInfo:serverInfo];
    if (got != want) failures++;
    printf("%-4s %-46s -> %s (want %s)\n", got == want ? "ok" : "FAIL", what,
           got ? "yes" : "no", want ? "yes" : "no");
}

int main(void) {
    @autoreleasepool {
        NSArray *pad = @[iface(0x03, 0x00, 0x00)];
        NSArray *keyboard = @[iface(0x03, 0x01, 0x01)];
        NSArray *webcam = @[iface(0x0e, 0x00, 0x00)];
        NSArray *dock = @[iface(0x08, 0x06, 0x50), iface(0x0b, 0x00, 0x00)];
        NSSet *padClass = [NSSet setWithObject:@(0x03)];
        NSSet *storageClass = [NSSet setWithObject:@(0x08)];
        NSArray *padRule = @[[MLDeviceRedirectionRule ruleForVendorID:0x28de productID:0x2202
                                                              enabled:YES]];

        // What ships today: nothing is switched on, so nothing is allowed.
        MLDeviceRedirectionPolicy *shipped = [MLDeviceRedirectionPolicy lockedDownPolicy];
        check(!shipped.featureEnabled && !shipped.hostIsPaired &&
              !shipped.hostSupportsDeviceRedirection && !shipped.localInputDevicesAllowed &&
              shipped.rules.count == 0 && shipped.allowedInterfaceClasses.count == 0,
              "the locked down policy enables nothing and allows nothing");
        expect("shipping build refuses before anything else", shipped,
               device(0x28de, 0x2202, nil, pad), NO,
               MLDeviceRedirectionDenialFeatureDisabled, -1);

        // Each of the three session gates is driven with a matching rule in place, so the
        // only thing that can produce the refusal is the gate under test.
        expect("an unpaired host is refused even with a matching rule",
               policy(NO, YES, padClass, NO, padRule), device(0x28de, 0x2202, nil, pad),
               NO, MLDeviceRedirectionDenialHostUnpaired, -1);
        expect("a host that never answered is refused even with a matching rule",
               policy(YES, NO, padClass, NO, padRule), device(0x28de, 0x2202, nil, pad),
               NO, MLDeviceRedirectionDenialHostUnsupported, -1);

        // The allow, which has to name the rule that earned it.
        MLDeviceRedirectionVerdict *earned =
            [policy(YES, YES, padClass, NO, padRule) verdictForDevice:device(0x28de, 0x2202, nil, pad)];
        check(earned.isAllowed && earned.denial == MLDeviceRedirectionDenialNone &&
              earned.ruleIndex == 0,
              "the one device the list names is allowed by the rule that names it");

        // A device nobody wrote down is refused, and says so, with every other gate open.
        expect("a device no rule names is refused",
               policy(YES, YES, padClass, NO, padRule), device(0x046d, 0xc52b, nil, pad),
               NO, MLDeviceRedirectionDenialNoRule, -1);
        expect("a device whose class was never allowed is refused",
               policy(YES, YES, padClass, NO,
                      @[[MLDeviceRedirectionRule ruleForVendorID:0x046d productID:0x085d
                                                         enabled:YES]]),
               device(0x046d, 0x085d, nil, webcam), NO,
               MLDeviceRedirectionDenialClassNotAllowed, -1);
        expect("a rule that is switched off is refused as a switched off rule",
               policy(YES, YES, padClass, NO,
                      @[[MLDeviceRedirectionRule ruleForVendorID:0x1111 productID:0x2222
                                                         enabled:YES],
                        [MLDeviceRedirectionRule ruleForVendorID:0x046d productID:0xc52b
                                                         enabled:NO]]),
               device(0x046d, 0xc52b, nil, pad), NO,
               MLDeviceRedirectionDenialRuleDisabled, 1);
        expect("a product id does not match a rule for another one",
               policy(YES, YES, padClass, NO, padRule), device(0x28de, 0x2203, nil, pad),
               NO, MLDeviceRedirectionDenialNoRule, -1);

        // A whole vendor's products is a bigger claim than one product, and has to be
        // asked for as one.
        check([MLDeviceRedirectionRule familyRuleForVendorID:0x28de enabled:YES].isWellFormed,
              "a family rule that says it is a family rule is well formed");
        expect("a family rule covers the vendor's other products",
               policy(YES, YES, padClass, NO,
                      @[[MLDeviceRedirectionRule familyRuleForVendorID:0x28de enabled:YES]]),
               device(0x28de, 0x9999, nil, pad), YES, MLDeviceRedirectionDenialNone, 0);
        check(![MLDeviceRedirectionRule ruleForVendorID:0x28de productID:0xffff enabled:YES].isWellFormed &&
              ![MLDeviceRedirectionRule ruleForVendorID:0x0000 productID:0x2202 enabled:YES].isWellFormed,
              "a rule built from a sentinel id could never match anything");
        expect("a device reporting an unknown product id is refused as unread",
               policy(YES, YES, padClass, NO, padRule), device(0x28de, 0xffff, nil, pad),
               NO, MLDeviceRedirectionDenialIdentityIncomplete, -1);

        // The identity gate, driven so that its reason is the one reported.
        expect("a device whose vendor id was never read is refused",
               [[MLDeviceRedirectionPolicy alloc] initWithFeatureEnabled:YES
                                                           hostIsPaired:YES
                                            hostSupportsDeviceRedirection:YES
                                                allowedInterfaceClasses:padClass
                                               localInputDevicesAllowed:NO
                                                                  rules:padRule],
               [MLUSBDeviceDescriptor descriptorWithVendorID:nil productID:@(0x2202)
                                                 interfaces:pad],
               NO, MLDeviceRedirectionDenialIdentityIncomplete, -1);
        expect("a vendor id of zero is a vendor id that was not read",
               policy(YES, YES, padClass, NO, padRule), device(0x0000, 0x2202, nil, pad),
               NO, MLDeviceRedirectionDenialIdentityIncomplete, -1);
        expect("a device that reported no interfaces is refused",
               policy(YES, YES, padClass, NO, padRule), device(0x28de, 0x2202, nil, @[]),
               NO, MLDeviceRedirectionDenialIdentityIncomplete, -1);

        // Classes no rule can reach, whatever the list says.
        check([MLDeviceRedirectionPolicy isReservedInterfaceClass:0x0b] &&
              [MLDeviceRedirectionPolicy isReservedInterfaceClass:0xdc] &&
              ![MLDeviceRedirectionPolicy isReservedInterfaceClass:0x03] &&
              ![MLDeviceRedirectionPolicy isReservedInterfaceClass:0x08],
              "a security key and a diagnostic device are reserved, a pad and a disk are not");
        expect("a dock that is also a smart card is refused whole",
               policy(YES, YES, storageClass, NO,
                      @[[MLDeviceRedirectionRule ruleForVendorID:0x17ef productID:0x304f
                                                         enabled:YES]]),
               device(0x17ef, 0x304f, nil, dock), NO,
               MLDeviceRedirectionDenialClassReserved, -1);

        // The keyboard, and the order the two input gates fire in.
        expect("a boot keyboard is refused although its class was allowed for a pad",
               policy(YES, YES, padClass, NO, padRule), device(0x04d9, 0x0169, nil, keyboard),
               NO, MLDeviceRedirectionDenialLocalInputReserved, -1);
        expect("a boot keyboard whose class was never allowed still reports the input",
               policy(YES, YES, storageClass, NO,
                      @[[MLDeviceRedirectionRule ruleForVendorID:0x04d9 productID:0x0169
                                                         enabled:YES]]),
               device(0x04d9, 0x0169, nil, keyboard), NO,
               MLDeviceRedirectionDenialLocalInputReserved, -1);
        expect("a gamepad is not a boot keyboard",
               policy(YES, YES, padClass, NO, padRule), device(0x28de, 0x2202, nil, pad),
               YES, MLDeviceRedirectionDenialNone, 0);

        // The capability negotiation, where an unanswered question is a no.
        expect_capability("no server info at all", nil, NO);
        expect_capability("server info with no answer in it", @{@"hostname": @"desk"}, NO);
        expect_capability("a host that says no", @{@"usbRedirection": @"0"}, NO);
        expect_capability("a host that says yes", @{@"usbRedirection": @"1"}, YES);
        expect_capability("a host that answers with a number", @{@"usbRedirection": @1}, YES);
        expect_capability("a count that is not one", @{@"usbRedirection": @2}, NO);
        expect_capability("a word instead of the answer", @{@"usbRedirection": @"yes"}, NO);
        expect_capability("a tag nobody agreed on", @{@"usbredirection": @"1"}, NO);

        // The audit line, which is the only form any of this should reach disk in.
        MLUSBDeviceDescriptor *serialised = device(0x28de, 0x2202, @"SERIAL-NEVER-LOGGED-9", pad);
        MLDeviceRedirectionVerdict *quiet = [policy(YES, YES, padClass, NO, padRule)
                                             verdictForDevice:serialised];
        check([quiet.auditLine rangeOfString:@"SERIAL-NEVER-LOGGED-9"].location == NSNotFound,
              "the audit line does not carry the serial number");
        check([quiet.auditLine rangeOfString:@"token="].location != NSNotFound,
              "the audit line carries a token in its place");
        MLDeviceRedirectionVerdict *same = [policy(YES, YES, padClass, NO, padRule)
                                            verdictForDevice:serialised];
        MLDeviceRedirectionVerdict *other = [policy(YES, YES, padClass, NO, padRule)
                                             verdictForDevice:device(0x28de, 0x2202, @"OTHER-SERIAL-1", pad)];
        check(quiet.ruleIndex == same.ruleIndex && [quiet.deviceToken isEqual:same.deviceToken] &&
              [quiet.auditLine isEqual:same.auditLine],
              "the same device and policy decide the same way twice");
        check(quiet.deviceToken.length == 8 && ![quiet.deviceToken isEqual:other.deviceToken],
              "two serials give two tokens, and a serial gives no token of its own");
        MLDeviceRedirectionVerdict *unserialised = [policy(YES, YES, padClass, NO, padRule)
                                                    verdictForDevice:device(0x28de, 0x2202, nil, pad)];
        check([unserialised.deviceToken isEqual:@"none"] &&
              [unserialised.auditLine rangeOfString:@"token=none"].location != NSNotFound,
              "a device with no serial says it has none instead of inventing one");
        printf("%s\n", failures ? "RUN FAILED" : "RUN PASSED");
        return failures ? 1 : 0;
    }
}
"""


def compiled(source, work, name, cc, sdk):
    path = os.path.join(work, name + ".m")
    open(path, "w", encoding="utf-8").write(source)
    command = [cc, "-x", "objective-c", "-fobjc-arc", "-isysroot", sdk, "-Wall", "-Werror",
               "-framework", "Foundation", path, "-o", os.path.join(work, name)]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return None, None, (built.stdout + built.stderr).strip()[-2500:]
    ran = subprocess.run([os.path.join(work, name)], capture_output=True, text=True)
    return ran.returncode, ran.stdout, (ran.stdout + ran.stderr).strip()[-2500:]


def run_rules(label, rules, cc, sdk, expect_pass=False):
    with tempfile.TemporaryDirectory() as work:
        code, out, log = compiled(DRIVER.replace("@@RULES@@", rules), work, "devpolicy", cc, sdk)
        if code is None:
            check(False, "%s: %s" % (label, log))
            return
        if expect_pass:
            check(code == 0 and out is not None and "RUN PASSED" in out,
                  "the shipping policy decides every case correctly"
                  if code == 0 else "the shipping policy failed a case:%s" % out)
        else:
            check(code != 0, "the check still fails when %s" % label)


def mutated(rules, label, before, after):
    check(before in rules, "%s: the source it mutates is still there" % label)
    return rules.replace(before, after, 1)


def main():
    rules = shipping_rules()
    print("-- what the policy does with a device it is asked about --")

    cc, sdk = apple_toolchain.clang_and_sdk("device redirection policy")
    run_rules("the shipping policy", rules, cc, sdk, expect_pass=True)

    # --- nothing here touches a device, a driver, or a socket -----------------
    impl = read(IMPL)
    check(not re.search(r"#import\s*<(?:IOKit|DriverKit|Usb)", impl),
          "the policy imports no IOKit, DriverKit or USB header")
    check("NSLog(" not in impl and "printf(" not in impl,
          "the policy has no path to the log of its own, so the audit line is the only one")
    entitlements = read("Moonlight.entitlements")
    check("usb" not in entitlements.lower() and "driverkit" not in entitlements.lower(),
          "no device or driver entitlement was added to the app bundle")
    check("MLDeviceRedirectionDenialClassNotAllowed" not in
          impl.split("verdictForDevice:")[1].split("for (MLUSBInterfaceDescriptor")[0],
          "the class gate cannot be reached before the reserved-class gate has been tried")

    # --- and the assertions above have to be the thing that fails ------------
    run_rules("refusing by default is inverted",
              mutated(rules, "refusing by default",
                      "return [self denialFor:MLDeviceRedirectionDenialNoRule device:device token:token ruleIndex:-1];",
                      "return [MLDeviceRedirectionVerdict verdictWithOutcome:MLDeviceRedirectionOutcomeAllowed"
                      " denial:MLDeviceRedirectionDenialNone ruleIndex:-1 device:device deviceToken:token];"),
              cc, sdk)
    run_rules("the pairing gate is removed",
              mutated(rules, "the pairing gate",
                      "if (!self.hostIsPaired) {", "if (NO) {"),
              cc, sdk)
    run_rules("the reserved classes are emptied",
              mutated(rules, "the reserved classes",
                      "return majorClass == MLUSBClassChipSmartCard || majorClass == MLUSBClassDiagnostic;",
                      "return NO;"),
              cc, sdk)
    run_rules("the local input gate is removed",
              mutated(rules, "the local input gate",
                      "if (wantsLocalInput && !self.localInputDevicesAllowed) {",
                      "if (NO && !self.localInputDevicesAllowed) {"),
              cc, sdk)
    check(LOCAL_INPUT_GATE + CLASS_GATE in rules,
          "the two input gates are adjacent in the source, so their order can be swapped")
    run_rules("the two input gates trade places",
              rules.replace(LOCAL_INPUT_GATE + CLASS_GATE, CLASS_GATE + LOCAL_INPUT_GATE, 1),
              cc, sdk)
    run_rules("a rule's product id is allowed to match any product",
              mutated(rules, "any product matches",
                      "if (!rule.productIsWildcard &&", "if (NO &&"),
              cc, sdk)
    run_rules("the identity gate only fires when everything is unread",
              mutated(rules, "the identity gate",
                      IDENTITY_GATE,
                      IDENTITY_GATE.replace("||", "&&")),
              cc, sdk)
    run_rules("the serial number is written into the log",
              mutated(rules, "the serial number leaks",
                      LEAKABLE_LINE, LEAKED_LINE),
              cc, sdk)

    print("%d device-redirection-policy failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
