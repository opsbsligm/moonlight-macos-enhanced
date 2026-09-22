#!/usr/bin/env python3
"""Prove the devices panel cannot be talked into promising a handover it cannot make.

The panel is where the feature becomes a thing a player touches, and it is the first place where
four independent preconditions have to be true at once: an identity that can load an extension, the
feature switched on, a host that offered the exchange, and a device whose class and rule both line
up. Each one is separately plausible and separately insufficient, which is the shape of bug this
file is for -- a panel that shows "ready" because two of them are set, or one that lists refusals
without saying which of the four is the one still missing.

Five claims hold it together, and each has a planted defect:

  storage is a hostile input. A rule whose identifiers are missing, are not numbers, or do not fit
    in two bytes is not a rule, and a record stored without its enabled flag is a rule that is off
    -- the alternative is a half-written record authorising a device;
  an inert rule is refused at the door. A sentinel vendor id stored as a rule is a rule that will
    be believed while matching nothing, so `add` says no and nothing is written;
  a host that has not been asked has not said yes. `NotAsked` is its own state and it refuses the
    same way a refusal does, because a settings page that treated "we never looked" as "the host
    offers it" would show devices as ready to hand over on the strength of an absence;
  a reserved class stays reserved no matter what the panel is configured to. Allowing class 0x0b,
    matching the rule, and satisfying every precondition still ends in `class-reserved`, which is
    the case 4.5 was written for and the case a settings page is most likely to get wrong;
  the panel says nothing about the device beyond its digest. The same line the log gets is the line
    the screen gets, and neither carries a product name.

One case is not a fixture: the live model reads the running binary, and the harness asserts that the
build clang just made reports itself as standing in the way.
"""
import importlib.util, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

MIN_PANEL_CHECKS = 60
STREAM = "Limelight/Stream/"
PANEL_H = STREAM + "DeviceRedirectionPanelModel.h"
PANEL_M = STREAM + "DeviceRedirectionPanelModel.m"

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def _signature_gate():
    """Reuse the leaf-certificate builder rather than a second copy of it.

    Two generators would drift, and the drift would show up as the panel gate being unable to make
    a Developer ID profile -- the one fixture that lets the later preconditions be tested at all.
    """
    spec = importlib.util.spec_from_file_location(
        "signature_gate", os.path.join(ROOT, "scripts/code-signature-profile-tests.py"))
    module = importlib.util.module_from_spec(spec)
    import io as _io
    with _io.StringIO() as captured:
        import contextlib
        with contextlib.redirect_stdout(captured):
            spec.loader.exec_module(module)
    return module


def strip_imports(text, quoted):
    for name in quoted:
        text = text.replace('#import "%s"\n' % name, "")
    return text.replace("#import <Foundation/Foundation.h>\n", "")


def shipping_rules():
    header, impl = read(PANEL_H), read(PANEL_M)
    check(sorted(set(re.findall(r"#import\s*<([^>]+)>", impl))) == [],
          "the panel model imports no framework of its own: it composes the layers that do")
    parts = [
        ("DeviceRedirectionPolicy.h", "DeviceRedirectionPolicy.m", ["DeviceRedirectionPolicy.h"]),
        ("USBDeviceEnumeration.h", "USBDeviceEnumeration.m",
         ["USBDeviceEnumeration.h", "DeviceRedirectionPolicy.h"]),
    ]
    rules = ""
    for name_h, name_m, quoted in parts:
        rules += strip_imports(read(STREAM + name_h), quoted) + "\n" + \
            strip_imports(read(STREAM + name_m), quoted) + "\n"
    rules += strip_imports(read(STREAM + "CodeSignatureProfile.h"),
                           ["CodeSignatureProfile.h"]) + "\n" + \
        strip_imports(read(STREAM + "CodeSignatureProfile.m"),
                      ["CodeSignatureProfile.h"]) + "\n"
    rules += strip_imports(read(STREAM + "USBBusSnapshot.h"),
                           ["USBBusSnapshot.h", "USBDeviceEnumeration.h"]) + "\n" + \
        strip_imports(read(STREAM + "USBBusSnapshot.m"),
                      ["USBBusSnapshot.h", "USBDeviceEnumeration.h"]) + "\n"
    rules += strip_imports(header, ["DeviceRedirectionPanelModel.h", "CodeSignatureProfile.h",
                                          "DeviceRedirectionPolicy.h", "USBBusSnapshot.h",
                                          "USBDeviceEnumeration.h"]) + "\n" + \
        strip_imports(impl, ["DeviceRedirectionPanelModel.h"])
    check(sorted(set(re.findall(r"#import\s*<([^>]+)>", rules))) ==
          ["CommonCrypto/CommonDigest.h", "IOKit/IOKitLib.h", "Security/Security.h"],
          "the compiled bundle imports the digest, the bus, and the signature API, and nothing else")
    check("#import \"" not in rules, "the compiled bundle carries no quoted import")
    return rules, impl, header


PANEL = r"""
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#import <Security/Security.h>

@@RULES@@

static int failures = 0;
static int checks_run = 0;

/// Evaluate the expression once. The first version of this macro read
/// `if (!(ok)) failures++; printf(..., (ok) ? "ok" : "FAIL", ...)` and so ran the expression
/// twice. Half the cases in this file pass a call with a side effect -- `addRuleForVendorID:` --
/// and every one of them silently did it twice: the rule the panel "added once" came back as two
/// rules, and the failure read like a defect in the panel rather than in the test. A check
/// observes; it does not take part. The self-test below is what keeps that from coming back.
#define CHECK(ok, what) do { const BOOL _passed = (ok); checks_run++; if (!_passed) failures++; \
    printf("%-4s %s\n", _passed ? "ok" : "FAIL", (what)); } while (0)

/// Counts how many times a check evaluated the expression it was handed.
static int evaluationCount = 0;
static BOOL ExpressionWasEvaluatedOnce(void) {
    evaluationCount++;
    return evaluationCount == 1;
}

static NSString *CKey(void) { return (__bridge NSString *)kSecCodeInfoCertificates; }
static NSString *EKey(void) { return (__bridge NSString *)kSecCodeInfoEntitlementsDict; }

static NSDictionary *DeveloperIDInformation(void) {
    NSData *der = [[NSData alloc] initWithBase64EncodedString:@"@@DEVID@@" options:0];
    SecCertificateRef leaf = SecCertificateCreateWithData(NULL, (__bridge CFDataRef)der);
    CHECK(leaf != NULL, "a Developer ID leaf certificate exists, so the ready cases are not vacuous");
    if (leaf == NULL) return nil;
    return @{ CKey() : @[ CFBridgingRelease(leaf) ],
              EKey() : @{ @"com.apple.developer.driverkit" : @1 } };
}

static NSUserDefaults *FreshDefaults(const char *name) {
    NSUserDefaults *suite = [[NSUserDefaults alloc] initWithSuiteName:
        [NSString stringWithUTF8String:name]];
    [suite removePersistentDomainForName:[NSString stringWithUTF8String:name]];
    return suite;
}

#define DEVICE_NODE(vendor, product) @{ @"idVendor" : @(vendor), @"idProduct" : @(product), \
    @"USB Product Name" : @"Example Webcam", @"USB Serial Number" : @"SN-SECRET-1" }
#define IFACE(vendor, product, number, klass, proto) @{ @"idVendor" : @(vendor), \
    @"idProduct" : @(product), @"bInterfaceNumber" : @(number), \
    @"bInterfaceClass" : @(klass), @"bInterfaceProtocol" : @(proto) }

/// An interface node without its protocol byte. The registry does not always carry one, and the
/// policy treats an HID interface whose protocol is unknown as boot capable rather than assuming
/// zero, so this is the fixture that reaches the local-input gate.
static MLUSBDeviceIdentity *DeviceWithBlindFace(NSUInteger vendor, NSUInteger product,
                                                NSArray<NSNumber *> *classes) {
    NSMutableArray *nodes = [NSMutableArray arrayWithObject:DEVICE_NODE(vendor, product)];
    for (NSUInteger index = 0; index < classes.count; index++) {
        [nodes addObject:@{ @"idVendor" : @(vendor), @"idProduct" : @(product),
                            @"bInterfaceNumber" : @(index),
                            @"bInterfaceClass" : classes[index] }];
    }
    return MLUSBDeviceIdentityFromRegistryNodes(nodes);
}

static MLUSBDeviceIdentity *DeviceWithFaces(NSUInteger vendor, NSUInteger product,
                                            NSArray<NSNumber *> *classes) {
    NSMutableArray *nodes = [NSMutableArray arrayWithObject:DEVICE_NODE(vendor, product)];
    for (NSUInteger index = 0; index < classes.count; index++) {
        [nodes addObject:IFACE(vendor, product, (int)index, classes[index].unsignedIntegerValue, 0)];
    }
    return MLUSBDeviceIdentityFromRegistryNodes(nodes);
}

static NSString *DecisionFor(MLDeviceRedirectionPanelModel *model, MLUSBDeviceIdentity *device,
                             BOOL paired) {
    NSArray<MLDeviceRedirectionPanelRow *> *rows =
        [model rowsForDevices:@[ device ] hostIsPaired:paired];
    return rows.firstObject.decisionLine;
}

/// Whether a row's line says a word, so that eleven cases read as a question rather than as a
/// bracket-counting exercise. The first version of these cases inlined
/// `[[DecisionFor(…) rangeOfString:@"…"].location != NSNotFound` and failed to compile: one
/// bracket too many, since a C call needs no message brackets around it. The predicate is what
/// makes that mistake impossible to repeat, and it is also what a reader wants.
static BOOL Says(NSString *line, NSString *needle) {
    return line != nil && [line rangeOfString:needle].location != NSNotFound;
}

static BOOL NeverSays(NSString *line, NSString *needle) {
    return line != nil && [line rangeOfString:needle].location == NSNotFound;
}

int main(void) {
    @autoreleasepool {
        printf("-- what the devices panel may claim, and about what --\n");

        // The test harness checks itself before it checks the panel. Both halves fail when the
        // macro double-evaluates, which is the point: the defect this file is recovering from was
        // invisible in the case list and only showed up as an impossible rule count.
        CHECK(ExpressionWasEvaluatedOnce(), "a check evaluates the expression it is given");
        CHECK(evaluationCount == 1,
              "and once only, so a case with a side effect has exactly one side effect");

        // A fresh install: nothing switched on, nothing allowed, nothing remembered.
        MLDeviceRedirectionPanelModel *clean =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:FreshDefaults("clean")];
        CHECK(!clean.featureEnabled && !clean.localInputDevicesAllowed,
              "a fresh install has both switches off, including the dangerous one");
        CHECK(clean.allowedInterfaceClasses.count == 0 && clean.rules.count == 0,
              "and no class is allowed and no rule exists");
        CHECK(clean.unreadableStoredRuleCount == 0, "nothing is remembered, so nothing is unreadable");
        CHECK(!clean.busHasBeenScanned,
              "and nobody has looked at the bus, which is not the same as a bus with nothing on it");
        CHECK(clean.hostClaim == MLDeviceRedirectionHostClaimNotAsked,
              "a host nobody has asked this visit has not offered anything");
        CHECK(!clean.mayBecomeActive, "and a fresh install cannot hand a device to anybody");
        CHECK([[clean blockingReasonName] hasPrefix:@"build-"],
              "the first thing standing in the way is the build itself, which is true today");

        // The same model, told to believe it has an identity. Every later precondition then has to
        // refuse on its own, one at a time.
        MLCodeSignatureProfile *identity =
            MLCodeSignatureProfileFromSigningInformation(DeveloperIDInformation());
        CHECK(identity.mayAttemptDriverExtension,
              "the injected profile really does say an extension could load");
        NSUserDefaults *readyDefaults = FreshDefaults("ready");
        MLDeviceRedirectionPanelModel *ready =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:readyDefaults
                                                   signatureProfile:identity];
        CHECK(!ready.mayBecomeActive, "an identity alone does not make the panel ready");
        CHECK([[ready blockingReasonName] isEqualToString:@"feature-disabled"],
              "and it names the switch that is still off");
        [ready setFeatureEnabled:YES];
        CHECK(ready.featureEnabled, "the switch is stored, not just remembered in the object");
        CHECK([[MLDeviceRedirectionPanelModel alloc] initWithDefaults:readyDefaults].featureEnabled,
              "and a second reader of the same defaults sees the same switch");
        CHECK(!ready.mayBecomeActive &&
                  [[ready blockingReasonName] isEqualToString:@"host-not-asked"],
              "with the switch on and nobody asked, the panel is still not ready");
        [ready noteServerInfoValue:@"1"];
        CHECK(ready.hostClaim == MLDeviceRedirectionHostClaimOffered && ready.mayBecomeActive,
              "an offer, an identity, and the switch are the three that make it ready");

        // The same defaults, the same switches, a different binary. This is the precondition no
        // switch can move, so it gets the loudest case: everything a player can do is already
        // done, and the answer is still no -- with the reason named as the build, because a panel
        // that blamed the host here would send someone to re-pair a host that is fine.
        MLDeviceRedirectionPanelModel *sameSwitchesOtherBuild =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:readyDefaults];
        [sameSwitchesOtherBuild noteServerInfoValue:@"1"];
        CHECK(sameSwitchesOtherBuild.featureEnabled &&
                  sameSwitchesOtherBuild.hostClaim == MLDeviceRedirectionHostClaimOffered,
              "every switch this build can move is moved, and the host really did offer");
        CHECK(!sameSwitchesOtherBuild.mayBecomeActive,
              "a build that cannot load an extension is not ready with every switch in its favour");
        CHECK([[sameSwitchesOtherBuild blockingReasonName] hasPrefix:@"build-"],
              "and it names its own signature as what stands in the way, not the host");

        // What counts as an offer. Only the value the protocol defines.
        MLDeviceRedirectionPanelModel *answers =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:FreshDefaults("answers")
                                                   signatureProfile:identity];
        [answers noteServerInfoValue:nil];
        CHECK(answers.hostClaim == MLDeviceRedirectionHostClaimRefused,
              "a host that answered nothing did not answer yes");
        [answers noteServerInfoValue:@"yes"];
        CHECK(answers.hostClaim == MLDeviceRedirectionHostClaimRefused,
              "a field that says yes instead of one is not an offer either");
        [answers noteServerInfoValue:@"0"];
        CHECK(answers.hostClaim == MLDeviceRedirectionHostClaimRefused, "zero is a refusal");
        [answers noteServerInfoValue:@(1)];
        CHECK(answers.hostClaim == MLDeviceRedirectionHostClaimOffered,
              "the number one and the text one mean the same thing");
        // The literal above is what a caller hands over after trimming. The ones below are what
        // the XML reader hands over, which is the shape `ServerInfoResponse` trims every tag of
        // for this reason: an untrimmed comparison reports a host that offered devices as one
        // that refused them, and the page states that with the same confidence as a real no.
        [answers noteServerInfoValue:@" 1 "];
        CHECK(answers.hostClaim == MLDeviceRedirectionHostClaimOffered,
              "spaces the reader left behind do not turn an offer into a refusal");
        [answers noteServerInfoValue:@"1\n"];
        CHECK(answers.hostClaim == MLDeviceRedirectionHostClaimOffered,
              "nor does the newline that usually follows a tag");
        [answers noteServerInfoValue:@" 0 "];
        CHECK(answers.hostClaim == MLDeviceRedirectionHostClaimRefused,
              "a trimmed zero is still a refusal");
        [answers noteServerInfoValue:@"10"];
        CHECK(answers.hostClaim == MLDeviceRedirectionHostClaimRefused,
              "trimming does not turn ten into one, so the strictness survives the convenience");
        CHECK(![MLDeviceRedirectionHostClaimName(MLDeviceRedirectionHostClaimNotAsked)
                   isEqual:MLDeviceRedirectionHostClaimName(MLDeviceRedirectionHostClaimRefused)] &&
              ![MLDeviceRedirectionHostClaimName(MLDeviceRedirectionHostClaimRefused)
                   isEqual:MLDeviceRedirectionHostClaimName(MLDeviceRedirectionHostClaimOffered)],
              "not-asked, refused, and offered have three names");

        // Class selection, and the range of a byte.
        MLDeviceRedirectionPanelModel *classes =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:FreshDefaults("classes")
                                                   signatureProfile:identity];
        CHECK([classes setInterfaceClassAllowed:YES forClass:0x03], "a class byte is accepted");
        CHECK([classes.allowedInterfaceClasses containsObject:@3], "and it is remembered");
        CHECK(![classes setInterfaceClassAllowed:YES forClass:0x100],
              "a number that is not a class byte is refused rather than truncated");
        CHECK(![classes.allowedInterfaceClasses containsObject:@0],
              "and nothing was stored behind it");
        [classes setInterfaceClassAllowed:NO forClass:0x03];
        CHECK(classes.allowedInterfaceClasses.count == 0, "allowing can be undone");

        // Rules. An inert one is refused on the way in.
        MLDeviceRedirectionPanelModel *rules =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:FreshDefaults("rules")
                                                   signatureProfile:identity];
        CHECK(![rules addRuleForVendorID:0x0000 productID:0x0001 family:NO],
              "a sentinel vendor id is refused before it can be stored");
        CHECK(rules.rules.count == 0, "a sentinel vendor id never becomes a rule");
        CHECK(rules.unreadableStoredRuleCount == 0,
              "and the refusal left no record behind, not even one the panel would only tally");
        CHECK([rules addRuleForVendorID:0x1234 productID:0x5678 family:NO],
              "a rule that could match a device is accepted");
        CHECK(rules.rules.count == 1 && rules.rules[0].vendorID == 0x1234 &&
                  rules.rules[0].productID == 0x5678 && rules.rules[0].enabled,
              "and it comes back as the rule that went in");
        CHECK([rules addRuleForVendorID:0x4321 productID:0 family:YES] &&
                  rules.rules[1].productIsWildcard,
              "a family rule keeps its wildcard instead of acquiring a product id");
        CHECK(![rules addRuleForVendorID:0x1234 productID:0x100000 family:NO],
              "an identifier larger than two bytes is refused rather than wrapped");
        CHECK(rules.rules.count == 2, "and the refusal stored nothing");
        CHECK([rules removeRuleAtIndex:0] && rules.rules.count == 1, "a rule can be removed");
        CHECK(![rules removeRuleAtIndex:9], "removing the tenth rule of a two-rule list says no");

        // Storage somebody else wrote.
        NSMutableArray *records = [NSMutableArray array];
        [records addObject:@{ @"vendor" : @(0x045E), @"product" : @(0x07A5), @"enabled" : @YES }];
        [records addObject:@{ @"product" : @(1) }];
        [records addObject:@"not a record"];
        [records addObject:@{ @"vendor" : @"0x1234", @"product" : @(2), @"enabled" : @YES }];
        [records addObject:@{ @"vendor" : @(0x1234), @"product" : @(0x5678) }];
        NSUserDefaults *dirty = FreshDefaults("dirty");
        [dirty setObject:records forKey:@"moonlight.usbredirection.rules"];
        MLDeviceRedirectionPanelModel *stored =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:dirty
                                                   signatureProfile:identity];
        CHECK(stored.rules.count == 2, "two of the five records really are rules");
        CHECK(stored.unreadableStoredRuleCount == 3,
              "and the three that are not are counted and reported, not skipped");
        CHECK(stored.rules[0].enabled && !stored.rules[1].enabled,
              "a rule stored without its enabled flag is a rule that is off");

        // Switching a rule the panel is showing. A record stored without its enabled flag reads
        // as off, and the only honest way to change that is a write that names the row and
        // touches nothing else -- the three unreadable records around it are nobody to modify.
        CHECK([stored setRuleEnabled:NO atIndex:0] && !stored.rules[0].enabled,
              "a rule that was on is off once the switch on its row is moved");
        CHECK([stored setRuleEnabled:YES atIndex:0] && stored.rules[0].enabled,
              "and it comes back on, because a switch that only goes one way is a delete button");
        CHECK([stored setRuleEnabled:YES atIndex:1] && stored.rules[1].enabled &&
                  stored.rules[0].enabled,
              "and the second row switches the rule that row stands for");
        CHECK(![stored setRuleEnabled:NO atIndex:4],
              "and there is no fifth rule to switch, even though storage holds five records");
        CHECK(stored.unreadableStoredRuleCount == 3,
              "and switching a rule left the unreadable records exactly as they were");

        // An identifier that does not fit in the two bytes one occupies. It arrived through
        // storage rather than through `add`, so the parser is the only thing between a number that
        // wraps to zero on the way through `unsigned short` and an allow list entry for a device
        // nobody typed. A wrapped sentinel is not an unusual rule; it is a rule that quietly
        // matches nothing while being believed.
        NSUserDefaults *wrappedDefaults = FreshDefaults("wrapped");
        [wrappedDefaults setObject:@[ @{ @"vendor" : @(0x100000), @"product" : @(1),
                                         @"enabled" : @YES },
                                       @{ @"vendor" : @(0x11234), @"product" : @(1),
                                          @"enabled" : @YES },
                                       @{ @"vendor" : @(0x1234), @"product" : @(0x15678),
                                          @"enabled" : @YES } ]
                            forKey:@"moonlight.usbredirection.rules"];
        MLDeviceRedirectionPanelModel *wrapped =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:wrappedDefaults
                                                   signatureProfile:identity];
        // The first wraps to a sentinel, which the shape of a rule would catch on its own. The
        // second and third wrap into identifiers that look entirely real -- 0x1234, 0x5678 -- so
        // the only thing between them and an allow list entry for a device nobody typed is the
        // width check. That is the guard this case is for.
        CHECK(wrapped.rules.count == 0,
              "an identifier too wide for a device never becomes a rule from storage either");
        CHECK(wrapped.unreadableStoredRuleCount == 3,
              "and all three are tallied as records this build cannot honour, not skipped");

        // Clearing the records that do nothing. They cannot be shown, so without this a player is
        // told about a record they can never reach or remove.
        CHECK([stored removeUnhonourableStoredRecords] == 3,
              "the three records that could not become rules can be removed in one go");
        CHECK(stored.rules.count == 2 && stored.unreadableStoredRuleCount == 0,
              "and the two rules that were real are untouched");
        CHECK([[MLDeviceRedirectionPanelModel alloc] initWithDefaults:dirty
                                                   signatureProfile:identity].rules.count == 2,
              "and the clean-up is stored, not remembered in the object");

        // Deleting by the row a player can see. Two of the five records above are rules, so row
        // one is the fifth record; a delete that addressed storage straight would take out record
        // index one instead -- an unreadable one -- and leave the list one rule longer than the
        // row that was removed. The tally has to move in the other direction.
        NSUserDefaults *mixed = FreshDefaults("mixed");
        [mixed setObject:[records copy] forKey:@"moonlight.usbredirection.rules"];
        MLDeviceRedirectionPanelModel *deleting =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:mixed
                                                   signatureProfile:identity];
        CHECK([deleting removeRuleAtIndex:1], "the second rule of a five-record storage is removable");
        CHECK(deleting.rules.count == 1 && deleting.rules[0].vendorID == 0x045E &&
                  deleting.unreadableStoredRuleCount == 3,
              "and the record that went is the one the row stood for, unreadable neighbours intact");
        CHECK(![deleting removeRuleAtIndex:1],
              "and there is no second rule to delete, even though storage still holds four records");
        CHECK([deleting removeUnhonourableStoredRecords] == 3 && deleting.rules.count == 1,
              "and the unreadable records those rows were sitting on can still be cleared");

        // Decisions, through the panel, on devices nobody plugged in.
        MLUSBDeviceIdentity *webcam = DeviceWithFaces(0x1234, 0x5678, @[ @14 ]);
        MLUSBDeviceIdentity *keyed = DeviceWithBlindFace(0x1234, 0x5678, @[ @3 ]);
        MLUSBDeviceIdentity *dock = DeviceWithFaces(0x0781, 0x55B8, @[ @8, @11 ]);

        MLDeviceRedirectionPanelModel *silent =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:FreshDefaults("silent")
                                                   signatureProfile:identity];
        CHECK(Says(DecisionFor(silent, webcam, YES), @"feature-disabled"),
              "with the feature off the reason is the feature, not the device");
        CHECK(Says(DecisionFor(silent, webcam, NO), @"feature-disabled"),
              "and the switch is checked before the pairing, cheapest and most global first");

        [silent setFeatureEnabled:YES];
        CHECK(Says(DecisionFor(silent, webcam, NO), @"host-unpaired"),
              "an unpaired host is the next thing a device is refused over");
        CHECK(Says(DecisionFor(silent, webcam, YES), @"host-not-asked") ||
                  Says(DecisionFor(silent, webcam, YES), @"host-unsupported"),
              "a host nobody asked is refused the same way a host that said no is");

        MLDeviceRedirectionPanelModel *armed =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:FreshDefaults("armed")
                                                   signatureProfile:identity];
        [armed setFeatureEnabled:YES];
        [armed noteServerInfoValue:@"1"];
        [armed setInterfaceClassAllowed:YES forClass:14];
        [armed setInterfaceClassAllowed:YES forClass:3];
        [armed setInterfaceClassAllowed:YES forClass:8];
        [armed setInterfaceClassAllowed:YES forClass:11];
        [armed addRuleForVendorID:0x1234 productID:0x5678 family:NO];
        [armed addRuleForVendorID:0x0781 productID:0x55B8 family:NO];
        CHECK([DecisionFor(armed, webcam, YES) isEqualToString:@"allowed"],
              "an allowed class and a matching rule really do reach allowed");
        CHECK(Says(DecisionFor(armed, dock, YES), @"class-reserved"),
              "a smart-card face is refused even with its class allowed and its rule present");
        CHECK([DecisionFor(armed, dock, YES) length] > 0,
              "and the row still says something rather than nothing");
        CHECK(Says(DecisionFor(armed, keyed, YES), @"local-input-reserved"),
              "a keyboard is refused until the local-input switch is moved, even with its rule");
        [armed setLocalInputDevicesAllowed:YES];
        CHECK([DecisionFor(armed, keyed, YES) isEqualToString:@"allowed"],
              "and the switch is what changed, not the passage of time");
        [armed setLocalInputDevicesAllowed:NO];

        MLDeviceRedirectionPanelModel *unruled =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:FreshDefaults("unruled")
                                                   signatureProfile:identity];
        [unruled setFeatureEnabled:YES];
        [unruled noteServerInfoValue:@"1"];
        [unruled setInterfaceClassAllowed:YES forClass:14];
        CHECK(Says(DecisionFor(unruled, webcam, YES), @"no-rule"),
              "an allowed class with no rule for this device is still a refusal");

        // What a row may contain.
        MLDeviceRedirectionPanelModel *shown = armed;
        NSArray<MLDeviceRedirectionPanelRow *> *rows =
            [shown rowsForDevices:@[ webcam, dock ] hostIsPaired:YES];
        CHECK(rows.count == 2, "one row per device, in the order the bus reported them");
        BOOL rowsAreClean = YES;
        for (MLDeviceRedirectionPanelRow *row in rows) {
            if (Says(row.identityLine, @"Example Webcam") ||
                Says(row.identityLine, @"SN-SECRET-1")) {
                rowsAreClean = NO;
            }
        }
        CHECK(rowsAreClean, "no row carries a product name or a serial number");
        CHECK(NeverSays(rows[0].identityLine, @"unread"),
              "a device whose identifiers were read does not say unread");
        CHECK(rows[1].hasReservedInterface && !rows[0].hasReservedInterface,
              "and the row knows which device has a face no rule can reach");
        CHECK(rows[0].identity.vendorID.unsignedIntValue == 0x1234 &&
                  rows[0].identity.productID.unsignedIntValue == 0x5678,
              "a row carries the identifiers it was drawn from, so offering them back is not a re-scan");
        CHECK(rows[0].identity != nil && rows[1].identity != nil,
              "no row arrives without its device: a page could only show it and not act on it");
        CHECK(NeverSays(shown.auditLine, @"Example Webcam"),
              "the panel's own line names no device either");

        CHECK([MLDeviceRedirectionPanelModel interfaceClassesNoRuleCanReach].count == 2 &&
                  [[MLDeviceRedirectionPanelModel interfaceClassesNoRuleCanReach]
                      containsObject:@0x0B] &&
                  [[MLDeviceRedirectionPanelModel interfaceClassesNoRuleCanReach]
                      containsObject:@0xDC],
              "the classes no rule can reach are the smart-card and diagnostic ones, named before a rule is typed");

        // Looking at the real bus. Read-only, and explicit: this is the one case that reaches the
        // machine the tests run on, and it is here because the property it sets is the one the page
        // puts next to an empty list.
        NSArray<MLDeviceRedirectionPanelRow *> *liveRows = [clean rowsByScanningBusWithHostPaired:NO];
        CHECK(clean.busHasBeenScanned, "and pressing the button really did look at the bus");
        CHECK(liveRows.count == 0 || clean.busStatus == MLUSBBusSnapshotStatusRead,
              "a list of devices is never shown for a bus that could not be read");
        BOOL liveRowsAreClean = YES;
        for (MLDeviceRedirectionPanelRow *row in liveRows) {
            if (Says(row.identityLine, @"Serial") || Says(row.identityLine, @"Product Name")) {
                liveRowsAreClean = NO;
            }
        }
        CHECK(liveRowsAreClean, "and a row about a real device carries no product name or serial");

        // The live model: the binary clang just built has to agree it is in the way.
        MLDeviceRedirectionPanelModel *live =
            [[MLDeviceRedirectionPanelModel alloc] initWithDefaults:[NSUserDefaults standardUserDefaults]];
        CHECK(live.signatureProfile.signingInformationWasReadable,
              "the live model could read the signature, so the case below is not vacuous");
        CHECK(!live.mayBecomeActive && [[live blockingReasonName] hasPrefix:@"build-"],
              "and it reports this build, not a device, as what stops a handover");

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
                            "-framework", "Security", path, "-o", binary],
                           capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr)[-2500:]
    ran = subprocess.run([binary], capture_output=True, text=True)
    return ran, (ran.stdout + ran.stderr)


def run_rules(label, rules, cc, sdk, expect_pass=False):
    with tempfile.TemporaryDirectory() as work:
        source = PANEL.replace("@@RULES@@", rules)
        ran, out = compiled(source, work, "panel_driver", cc, sdk)
        if ran is None:
            check(False, "%s: the harness compiled (%s)"
                  % (label, (out or "").strip().splitlines()[-1:]))
            return
        if expect_pass:
            reported = re.search(r"RUN PASSED \((\d+) checks\)", out or "")
            check(ran.returncode == 0, "%s behaves as documented" % label)
            if ran.returncode != 0:
                print("\n".join([line for line in (out or "").splitlines()
                                  if line.startswith("FAIL")])[:1200])
            count = int(reported.group(1)) if reported else -1
            check(count >= MIN_PANEL_CHECKS,
                  "the compiled run reports its own case list (%d checks, floor %d)"
                  % (count, MIN_PANEL_CHECKS))
        else:
            check(ran.returncode != 0, "the check still fails when %s" % label)
            if ran.returncode == 0:
                print((out or "").strip().splitlines()[-3:])


def mutated(rules, label, before, after):
    check(before in rules, "%s: the source it mutates is still there" % label)
    return rules.replace(before, after, 1)


def main():
    rules, impl, header = shipping_rules()
    print("-- what the devices panel may claim, and about what --")

    cc, sdk = apple_toolchain.clang_and_sdk("device redirection panel")
    signature_gate = _signature_gate()
    leaf = signature_gate.leaf_certificate(
        "Developer ID Application: Example Corp (ABCDE12345)", "Developer ID")

    def patch(source):
        return source.replace("@@DEVID@@", leaf)

    global PANEL
    original = PANEL
    PANEL = patch(PANEL)
    run_rules("the shipping panel model", rules, cc, sdk, expect_pass=True)

    check("NSLog(" not in impl and "printf(" not in impl,
          "the panel model has no path to the log of its own")
    check('"moonlight.usbredirection.' in impl,
          "the panel's preferences live under one prefix, so they can be found and audited")
    for forbidden in ("NSDate", "CACurrentMediaTime", "clock_gettime", "gettimeofday",
                      "OSSystemExtension", "IOServiceOpen"):
        check(forbidden not in impl + header,
              "the panel model never touches %s: it reads, stores, and decides" % forbidden)
    check("initWithSuiteName" not in impl,
          "the production model never reaches for a defaults suite of its own: a caller supplies one")

    # Wiring. The model above is worth nothing if no screen shows it and nothing can reach it, and
    # both of those failures are silent: a class method with no caller compiles, and a pane that is
    # not in the target does not appear in an error message anybody reads. The unlock note is pinned
    # for the same reason -- a placeholder whose comment can evaporate is not a placeholder, it is a
    # feature that quietly stopped being unfinished.
    pane = read("Limelight/macOS/ViewControllers/SettingsDevicesPane.swift")
    check("UNLOCK(stage3)" in pane,
          "the devices pane still says out loud which half of stage 3 it is waiting on")
    check("MLDeviceRedirectionPanelModel" in pane,
          "and the pane really is the consumer of this model rather than a second copy of its rules")
    check("DeviceRedirectionPanelModel.h" in read("Limelight/Moonlight-Bridging-Header.h"),
          "the Objective-C model is reachable from Swift, so the pane is reading this code")
    for pinned in ("NS_SWIFT_NAME(setInterfaceClassAllowed(_:forClass:))",
                  "NS_SWIFT_NAME(addRule(vendorID:productID:family:))",
                  "NS_SWIFT_NAME(setRuleEnabled(_:atIndex:))",
                  "NS_SWIFT_NAME(removeRule(atIndex:))",
                  "NS_SWIFT_NAME(rowsByScanningBus(hostPaired:))",
                  "NS_SWIFT_NAME(rows(for:hostIsPaired:))"):
        check(pinned in header,
              "%s is still pinned, and the pane is written against that spelling rather than a "
              "compiler version's guess" % pinned.split("(")[0])
    check("MLDeviceRedirectionPanelModel(defaults:" in pane,
          "the pane builds the model through the initialiser the header declares, because a "
          "no-argument factory named after its class is what an importer rewrites into init()")
    check("panelModel" not in pane and "panelModel" not in header and "panelModel" not in impl,
          "no factory is left for an importer to rename out from under the page that calls it")
    folded_pane = " ".join(pane.split())
    for tag in ("TAG_UNIQUE_ID", "MLDeviceRedirectionServerInfoTagName()"):
        at = folded_pane.find("getStringTag(" + tag)
        check(at != -1 and "trimmingCharacters" in folded_pane[at:at + 220],
              "%s is trimmed before the page compares it, because the answer arrives from an "
              "XML reader and `ServerInfoResponse` trims every tag it stores for that reason"
              % tag)
    check("!expectedUuid.isEmpty" in pane,
          "a host whose identifier this app never learned is not credited with the answer of "
          "whoever replied, which is what comparing two missing identifiers would do")
    check("@property(nonatomic, readwrite) BOOL featureEnabled" in header and
          "@property(nonatomic, readwrite) BOOL localInputDevicesAllowed" in header,
          "the two switches are properties a page can assign, not a getter and a setter that "
          "an importer may or may not fold together")
    check("SettingsDevicesPane.swift" in read("Moonlight.xcodeproj/project.pbxproj"),
          "the pane is a member of the target, which is the only reason it ends up in the app")
    check("DevicesView()" in read("Limelight/macOS/ViewControllers/LiquidGlass/LiquidGlassSettingsView.swift"),
          "the pane is reachable from the settings tab bar, not just compiled")
    check("UNLOCK(stage3)" in read("docs/usb-redirection-design.md"),
          "the unlock checklist the pane points at is still in the document it points at")

    def key_lines(table):
        return [line for line in table.splitlines() if line.startswith('"') and '" = "' in line]

    en = read("Limelight/macOS/en.lproj/Localizable.strings")
    zh = read("Limelight/macOS/zh-Hans.lproj/Localizable.strings")
    pane_keys = set()
    for literal in re.findall(r'localize\("([^"]+)"\)', pane):
        pane_keys.add(literal)
    for offered in re.findall(r'labelKey:\s*"([^"]+)"', pane):
        pane_keys.add(offered)
    for title in re.findall(r'(?:titleKey|textKey|hintKey|title):\s*"([^"]+)"', pane):
        pane_keys.add(title)
    check(len(pane_keys) >= 30,
          "the pane asks for %d translation keys, which is what a page with this many sentences needs"
          % len(pane_keys))
    unanswered = sorted(
        key for key in pane_keys
        if ('"%s" = "' % key) not in en or ('"%s" = "' % key) not in zh)
    check(not unanswered,
          "both language tables answer every sentence this pane can print"
          if not unanswered else "the devices pane asks for keys nobody can answer: "
          + ", ".join(unanswered))

    run_rules("the identity is not asked about",
              mutated(rules, "the first precondition",
                      "    return self.signatureProfile.mayAttemptDriverExtension &&\n           self.featureEnabled &&",
                      "    return self.featureEnabled &&"),
              cc, sdk)
    run_rules("the host's answer is not asked about",
              mutated(rules, "the last precondition",
                      "           self.hostClaim == MLDeviceRedirectionHostClaimOffered;",
                      "           self.hostClaim != MLDeviceRedirectionHostClaimRefused;"),
              cc, sdk)
    run_rules("the switch is asked about before the build",
              mutated(rules, "the order of reasons",
                      '    if (!self.signatureProfile.mayAttemptDriverExtension) {\n        return [NSString stringWithFormat:@"build-%@",\n                                          MLCodeSignatureFormName(self.signatureProfile.form)];\n    }\n    if (!self.featureEnabled) {\n        return @"feature-disabled";\n    }',
                      '    if (!self.featureEnabled) {\n        return @"feature-disabled";\n    }\n    if (!self.signatureProfile.mayAttemptDriverExtension) {\n        return [NSString stringWithFormat:@"build-%@",\n                                          MLCodeSignatureFormName(self.signatureProfile.form)];\n    }'),
              cc, sdk)
    run_rules("an inert rule is stored anyway",
              mutated(rules, "the door keeps inert rules out",
                      "    if (!rule.isWellFormed) {\n        return NO;\n    }",
                      "    if (NO) {\n        return NO;\n    }"),
              cc, sdk)
    run_rules("a rule with no enabled flag is an enabled one",
              mutated(rules, "the missing flag means off",
                      "    const BOOL enabled = [dictionary[kRuleEnabledField] isKindOfClass:[NSNumber class]]\n        ? [(NSNumber *)dictionary[kRuleEnabledField] boolValue]\n        : NO;",
                      "    const BOOL enabled = [dictionary[kRuleEnabledField] isKindOfClass:[NSNumber class]]\n        ? [(NSNumber *)dictionary[kRuleEnabledField] boolValue]\n        : YES;"),
              cc, sdk)
    run_rules("an oversized identifier is truncated into a rule",
              mutated(rules, "the two-byte limit",
                      "    if (vendorID > MLUSBIdentifierMaximum || productID > MLUSBIdentifierMaximum) {\n        return nil;\n    }",
                      "    if (NO) {\n        return nil;\n    }"),
              cc, sdk)
    run_rules("a row forgets which device it stands for",
              mutated(rules, "the row's device",
                      "        _identity = identity;",
                      "        _identity = nil;"),
              cc, sdk)
    run_rules("a rule switch writes the answer it was given",
              mutated(rules, "the rule switch",
                      "    rewritten[kRuleEnabledField] = @(enabled);",
                      "    rewritten[kRuleEnabledField] = @(YES);"),
              cc, sdk)
    run_rules("an offer is refused because it arrived with the whitespace the reader left",
              mutated(rules, "the trimmed answer",
                      "        NSString *answered = [(NSString *)value stringByTrimmingCharactersInSet:"
                      + chr(10) + "            [NSCharacterSet whitespaceAndNewlineCharacterSet]];"
                      + chr(10) + '        return [answered isEqualToString:@"1"];',
                      "        return [(NSString *)value isEqualToString:@\"1\"];\\"),
              cc, sdk)
    run_rules("a host that answered nothing answered yes",
              mutated(rules, "the empty answer",
                      "                      value == nil ? @{} : @{ MLDeviceRedirectionServerInfoTagName() : value }]",
                      "                      value == nil ? @{ MLDeviceRedirectionServerInfoTagName() : @\"1\" } : @{ MLDeviceRedirectionServerInfoTagName() : value }]"),
              cc, sdk)
    run_rules("unreadable records are counted as none",
              mutated(rules, "the unreadable tally",
                      "        if (MLDeviceRedirectionRuleFromStoredRecord(record) == nil) {\n            unreadable++;",
                      "        if (MLDeviceRedirectionRuleFromStoredRecord(record) != nil) {\n            unreadable++;"),
              cc, sdk)
    run_rules("a rule switch addresses storage instead of the row it was given",
              mutated(rules, "the switch\'s own row addressing",
                      "    NSMutableArray<NSNumber *> *positions = [NSMutableArray array];\n    [self collectRules:nil storageIndices:positions];\n    if (index >= positions.count) {\n        return NO;\n    }\n    const NSUInteger storageIndex = [positions[index] unsignedIntegerValue];\n    NSArray *records = [self storedRules];\n    if (storageIndex >= records.count) {\n        return NO;\n    }\n    id record = records[storageIndex];",
                      "    const NSUInteger storageIndex = index;\n    NSArray *records = [self storedRules];\n    if (storageIndex >= records.count) {\n        return NO;\n    }\n    id record = records[storageIndex];"),
              cc, sdk)
    run_rules("a bus that was never scanned claims it was",
              mutated(rules, "the scan records itself",
                      "    _busHasBeenScanned = YES;",
                      "    _busHasBeenScanned = NO;"),
              cc, sdk)
    run_rules("a class number is accepted whatever it is",
              mutated(rules, "the byte range",
                      "    if (majorClass > 0xFF) {",
                      "    if (majorClass > 0xFFFFFFFF) {"),
              cc, sdk)
    run_rules("a reserved face is invisible to the row",
              mutated(rules, "the reserved face",
                      "            if ([MLDeviceRedirectionPolicy isReservedInterfaceClass:interface.majorClass]) {\n                reserved = YES;",
                      "            if ([MLDeviceRedirectionPolicy isReservedInterfaceClass:interface.minorClass]) {\n                reserved = YES;"),
              cc, sdk)
    run_rules("a row keeps the product name",
              mutated(rules, "the row's line",
                      "        _identityLine = [identity diagnosticLineForVerdict:nil];",
                      "        _identityLine = [NSString stringWithFormat:@\"%@ %@\", [identity diagnosticLineForVerdict:nil], identity.descriptor.serialNumber ?: @\"Example Webcam\"];"),
              cc, sdk)

    PANEL = original
    print("%d device-redirection-panel-model failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
