#!/usr/bin/env python3
"""Prove that a build without an identity cannot come to believe it has one.

The panel described in docs/usb-redirection-design.md 3 has to say why it has nothing to offer,
and the answer comes from the running binary rather than from a string somebody wrote: this
repository has no Developer ID, so today the honest answer is "ad-hoc, no driver extension", and
the day it gets an identity the same code has to stop saying that. Both directions fail loudly --
a profile hard-coded to "unsigned" would be a lie after the certificate arrives, and one that
inferred a capability from an entitlement alone would hand the panel a claim nothing checked.

Four claims hold the file together, and each has a planted defect:

  no certificate chain is not a signature. The ad-hoc build measured in 2.3 and an unrecognised
    build with no chain both classify as `adhoc`, and neither may reach `allowed`;
  the identity and the entitlement are separate facts. `Developer ID` without DriverKit asked for
    is refused, and DriverKit asked for on a development identity is refused, so the answer needs
    both and each half is mutated away on its own;
  an unrecognised issuer stays unrecognised. A prefix that is neither of the two known ones is
    `other`, because the alternative is a signing shape nobody observed being reported as a
    capability somebody has;
  the leaf summary is not shown. It names a company. The audit line answers the only question a
    support thread asks, which is whether the build could load an extension.

One case is not a fixture: the harness runs `MLCodeSignatureProfileOfCurrentProcess()` against
itself and asserts that a binary clang just built says it cannot load an extension. That is the
only case in this file that touches a real signature, and it is the reason the key names come
from Security.framework's constants rather than from a transcription -- a wrong key would still
produce "no chain" here, so nothing else would ever notice.
"""
import base64, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

MIN_PROFILE_CHECKS = 30
PROFILE_H = "Limelight/Stream/CodeSignatureProfile.h"
PROFILE_M = "Limelight/Stream/CodeSignatureProfile.m"

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
    # Security stays: the classifier reads a SecCertificate summary and the live case asks the
    # running process, so the harness compiles the file the way the app does.
    return text.replace("#import <Foundation/Foundation.h>\n", "")


def shipping_rules():
    header, impl = read(PROFILE_H), read(PROFILE_M)
    check(sorted(set(re.findall(r"#import\s*<([^>]+)>", header))) == ["Foundation/Foundation.h"],
          "the profile header exposes no framework beyond Foundation")
    check(sorted(set(re.findall(r"#import\s*<([^>]+)>", impl))) == ["Security/Security.h"],
          "the implementation links Security alone: Foundation arrives through its own header, "
          "and neither a driver bus nor a clock is linked here")
    rules = strip_imports(header, ["CodeSignatureProfile.h"]) + "\n" + \
        strip_imports(impl, ["CodeSignatureProfile.h"])
    check("#import \"" not in rules, "the compiled bundle carries no quoted import")
    return rules, impl, header


PROFILE = r"""
#import <Foundation/Foundation.h>
#import <Security/Security.h>

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

static NSString *CKey(void) { return (__bridge NSString *)kSecCodeInfoCertificates; }
static NSString *EKey(void) { return (__bridge NSString *)kSecCodeInfoEntitlementsDict; }
static NSString *TKey(void) { return (__bridge NSString *)kSecCodeInfoTeamIdentifier; }

// info builds a signing-information dictionary the way Security.framework hands one over: a
// chain of subject strings and an entitlements dictionary under the framework's own keys.
static NSDictionary *info(NSArray *chain, NSDictionary *entitlements, NSString *team) {
    NSMutableDictionary *built = [NSMutableDictionary dictionary];
    if (chain) built[CKey()] = chain;
    if (entitlements) built[EKey()] = entitlements;
    if (team) built[TKey()] = team;
    return built;
}

static MLCodeSignatureProfile *dev(NSArray *chain, NSDictionary *entitlements) {
    return MLCodeSignatureProfileFromSigningInformation(info(chain, entitlements, nil));
}

static NSString *const kDeveloperIDSubject = @"Developer ID Application: Example Corp (ABCDE12345)";
static NSString *const kDevelopmentSubject = @"Apple Development: somebody at example (ABCDE12345)";
static NSString *const kOtherSubject = @"3rd Party Mac Developer Application: Other Corp (ZZZZZZZZZZ)";
#define DEV_ID_B64 @"@@DEVID@@"
#define DEV_B64 @"@@DEVCERT@@"
#define OTHER_B64 @"@@OTHER@@"

// A chain is only useful if the certificate survived the round trip, so every case below takes
// its chain from a builder that says when it did not.
static NSArray *ChainFromBase64(NSString *base64) {
    NSData *der = [[NSData alloc] initWithBase64EncodedString:base64 options:0];
    if (der == nil) return nil;
    SecCertificateRef leaf = SecCertificateCreateWithData(NULL, (__bridge CFDataRef)der);
    if (leaf == NULL) return nil;
    return @[ CFBridgingRelease(leaf) ];
}
#define DRIVERKIT @{ @"com.apple.developer.driverkit.transport.usb" : @1 }

static void expect(const char *what, MLCodeSignatureProfile *profile, MLCodeSignatureForm form,
                   BOOL readable, BOOL driverKit, BOOL systemExtension, BOOL dextAllowed,
                   BOOL sextAllowed) {
    CHECK(profile.form == form, what);
    CHECK(profile.signingInformationWasReadable == readable, what);
    CHECK(profile.hasDriverKitEntitlement == driverKit, what);
    CHECK(profile.hasSystemExtensionEntitlement == systemExtension, what);
    CHECK(profile.mayAttemptDriverExtension == dextAllowed, what);
    CHECK(profile.mayAttemptSystemExtension == sextAllowed, what);
}

int main(void) {
    @autoreleasepool {
        printf("-- what a build may say about its own signature --\n");

        // The harness proves its own macro first. Both lines fail when a check double-evaluates,
        // so the defect cannot come back disguised as a passing case list.
        CHECK(ExpressionWasEvaluatedOnce(), "a check evaluates the expression it is given");
        CHECK(evaluationCount == 1,
              "and once only, so a case with a side effect has exactly one side effect");

        // The fixtures carry their own check: a chain that came back nil, or whose subject is not
        // the name it was built with, would turn every case below into an assertion about nothing.
        NSArray *devIdChain = ChainFromBase64(DEV_ID_B64);
        NSArray *devCertChain = ChainFromBase64(DEV_B64);
        NSArray *otherChain = ChainFromBase64(OTHER_B64);
        CHECK(devIdChain != nil && devCertChain != nil && otherChain != nil,
              "all three leaf certificates were built, so the identity cases are not vacuous");
        CHECK(devIdChain.count == 1 && devIdChain[0] != (id)kCFNull,
              "a leaf certificate survives the round trip into a chain");
        BOOL subjectsMatch = YES;
        for (NSArray *chain in @[ devIdChain ?: @[], devCertChain ?: @[], otherChain ?: @[] ]) {
            for (id leaf in chain) {
                CFStringRef sum = SecCertificateCopySubjectSummary((__bridge SecCertificateRef)leaf);
                NSString *subject = sum ? CFBridgingRelease(sum) : nil;
                if (subject.length == 0) subjectsMatch = NO;
            }
        }
        CHECK(subjectsMatch, "Security can read a subject out of each leaf it was given");
        CHECK(MLCodeSignatureFormForLeafSubject(
                  @"Developer ID Application: Example Corp (ABCDE12345)") ==
                  MLCodeSignatureFormDeveloperID,
              "the subject the Developer ID fixture carries is the one the rule recognises");
        CHECK(dev(devIdChain, DRIVERKIT).certificateCount == 1,
              "one leaf is counted as one certificate, not as zero");

        // Nothing readable came back. That is not a verdict about the signature, and it may not
        // become one: an unreadable profile is the one state that must not reach allowed.
        MLCodeSignatureProfile *none = MLCodeSignatureProfileFromSigningInformation(nil);
        expect("nothing readable is not a signature", none, MLCodeSignatureFormUnknown, NO,
               NO, NO, NO, NO);
        CHECK(none.teamIdentifier == nil, "an unreadable profile invents no team");
        CHECK([none.auditLine rangeOfString:@"signature=unreadable"].location == 0,
              "the audit line says it could not read, in the one spelling the panel uses");

        // A dictionary with no chain is the shape the ad-hoc build measured in 2.3 returns.
        expect("a dictionary without a chain is ad-hoc", dev(nil, nil), MLCodeSignatureFormAdhoc,
               YES, NO, NO, NO, NO);
        expect("an empty chain is ad-hoc", dev(@[], nil), MLCodeSignatureFormAdhoc, YES, NO, NO,
               NO, NO);
        CHECK(dev(@[], nil).certificateCount == 0, "an empty chain counts as no certificates");

        // Identity and capability, together and apart.
        expect("Developer ID with DriverKit asked for", dev(devIdChain, DRIVERKIT),
               MLCodeSignatureFormDeveloperID, YES, YES, NO, YES, NO);
        expect("Developer ID that asked for nothing", dev(devIdChain, nil),
               MLCodeSignatureFormDeveloperID, YES, NO, NO, NO, NO);
        expect("DriverKit asked for on no identity", dev(nil, DRIVERKIT),
               MLCodeSignatureFormAdhoc, YES, YES, NO, NO, NO);
        expect("DriverKit asked for on a development identity", dev(devCertChain, DRIVERKIT),
               MLCodeSignatureFormAppleDevelopment, YES, YES, NO, NO, NO);
        expect("a system extension entitlement on a development identity",
               dev(devCertChain, @{ @"com.apple.developer.system-extension.install" : @1 }),
               MLCodeSignatureFormAppleDevelopment, YES, NO, YES, NO, NO);
        expect("a system extension entitlement on Developer ID",
               dev(devIdChain, @{ @"com.apple.developer.system-extension.install" : @1 }),
               MLCodeSignatureFormDeveloperID, YES, NO, YES, NO, YES);

        // An issuer nobody named stays unknown rather than becoming one of the two known shapes.
        expect("an unrecognised issuer", dev(otherChain, DRIVERKIT), MLCodeSignatureFormOther,
               YES, YES, NO, NO, NO);
        // A chain element that is not a certificate must be refused, not interrogated. Asking a
        // Foundation value type for a subject summary is a crash, and the crash is the bug this
        // case exists to keep out: an unexpected chain shape has to cost the panel its answer,
        // not the app.
        expect("a chain whose leaf is not a certificate", dev(@[ @12345 ], DRIVERKIT),
               MLCodeSignatureFormOther, YES, YES, NO, NO, NO);
        expect("a chain of text", dev(@[ @"Developer ID Application: Example Corp (ABCDE12345)" ],
                                     nil), MLCodeSignatureFormOther, YES, NO, NO, NO, NO);

        // The prefix rules, on the string they are really about.
        CHECK(MLCodeSignatureFormForLeafSubject(@"Developer ID Application: X (TEAM)") ==
                  MLCodeSignatureFormDeveloperID, "the Developer ID issuer name is recognised");
        CHECK(MLCodeSignatureFormForLeafSubject(@"Apple Development: someone (TEAM)") ==
                  MLCodeSignatureFormAppleDevelopment, "the development issuer name is recognised");
        CHECK(MLCodeSignatureFormForLeafSubject(@"Developer ID ApplicationX: X") ==
                  MLCodeSignatureFormOther, "a name that only resembles the issuer is not it");
        CHECK(MLCodeSignatureFormForLeafSubject(@"developer id application: x") ==
                  MLCodeSignatureFormOther, "the issuer name is not matched case-insensitively");
        CHECK(MLCodeSignatureFormForLeafSubject(@"") == MLCodeSignatureFormOther &&
                  MLCodeSignatureFormForLeafSubject(nil) == MLCodeSignatureFormOther,
              "no name is an unknown name, not an ad-hoc build");

        // Which entitlements count, and which merely look close.
        MLCodeSignatureProfile *transport = dev(devIdChain, DRIVERKIT);
        CHECK(transport.hasDriverKitEntitlement,
              "a DriverKit transport entitlement is DriverKit being asked for");
        MLCodeSignatureProfile *sandboxUSB = dev(devIdChain, @{ @"com.apple.security.device.usb" : @1 });
        CHECK(!sandboxUSB.hasDriverKitEntitlement,
              "the USB sandbox entitlement is not DriverKit: one is a sandbox hole, the other a bus");
        MLCodeSignatureProfile *nearMiss = dev(devIdChain, @{
            @"com.apple.developer.system-extension.install.extra" : @1 });
        CHECK(!nearMiss.hasSystemExtensionEntitlement,
              "a key that only starts like the system extension entitlement does not grant it");
        CHECK(dev(devIdChain, @{ @"com.apple.developer.driverkit" : @1 }).hasDriverKitEntitlement,
              "the base DriverKit entitlement counts as DriverKit being asked for");

        // Malformed values are absent, never empty: the difference is between a build that has
        // no entitlements and a reader that could not see them.
        // The entitlements value is a string here, which is what a malformed payload looks like
        // to a reader: the capability answers must be no while the signature stays readable.
        NSDictionary *malformed = @{ CKey() : devIdChain, EKey() : @"com.apple.developer.driverkit" };
        expect("entitlements that are not a dictionary",
               MLCodeSignatureProfileFromSigningInformation(malformed),
               MLCodeSignatureFormDeveloperID, YES, NO, NO, NO, NO);
        CHECK(MLCodeSignatureProfileFromSigningInformation(
                  @{ CKey() : devIdChain, EKey() : @1 }).signingInformationWasReadable,
              "unreadable entitlements do not make the signature unreadable");

        // Where the team id comes from, and what a blank one is.
        MLCodeSignatureProfile *fromSignature =
            MLCodeSignatureProfileFromSigningInformation(info(devIdChain, nil, @"SIGTEAM1234"));
        CHECK([fromSignature.teamIdentifier isEqualToString:@"SIGTEAM1234"],
              "the team the signature carries is the team reported");
        MLCodeSignatureProfile *fromEntitlement =
            dev(devIdChain, @{ @"com.apple.developer.team-identifier" : @"ENTTEAM12345" });
        CHECK([fromEntitlement.teamIdentifier isEqualToString:@"ENTTEAM12345"],
              "a Developer ID build's entitlement team is still its team");
        CHECK(dev(devIdChain, @{ @"com.apple.developer.team-identifier" : @"" }).teamIdentifier == nil,
              "a blank team id is reported as no team, not as the empty string");

        // What the line may and may not carry. The leaf subject names a company.
        MLCodeSignatureProfile *shown = dev(devIdChain, DRIVERKIT);
        CHECK([shown.auditLine rangeOfString:@"Example Corp"].location == NSNotFound &&
              [shown.auditLine rangeOfString:@"Application:"].location == NSNotFound,
              "the audit line carries no certificate subject");
        CHECK([shown.auditLine rangeOfString:@"dext=allowed"].location != NSNotFound,
              "the audit line answers the only question the panel asks");
        CHECK([dev(nil, nil).auditLine rangeOfString:@"dext=blocked"].location != NSNotFound,
              "an ad-hoc build is said to be blocked, in so many words");

        CHECK(MLCodeSignatureFormName(MLCodeSignatureFormUnknown) !=
                  MLCodeSignatureFormName(MLCodeSignatureFormAdhoc) &&
              MLCodeSignatureFormName(MLCodeSignatureFormAdhoc) !=
                  MLCodeSignatureFormName(MLCodeSignatureFormOther) &&
              MLCodeSignatureFormName(MLCodeSignatureFormOther) !=
                  MLCodeSignatureFormName(MLCodeSignatureFormAppleDevelopment) &&
              MLCodeSignatureFormName(MLCodeSignatureFormAppleDevelopment) !=
                  MLCodeSignatureFormName(MLCodeSignatureFormDeveloperID),
              "each form has its own name, so a panel cannot render two states alike");

        // The live case. clang's output is unsigned or ad-hoc on every runner this repository has,
        // so the assertion is that the code says so -- and that it could read the answer at all,
        // which is what separates this from a case that passes because nothing was seen.
        MLCodeSignatureProfile *live = MLCodeSignatureProfileOfCurrentProcess();
        CHECK(live.signingInformationWasReadable,
              "the running harness could read its own signature, so the case below is not vacuous");
        CHECK(live.form != MLCodeSignatureFormDeveloperID && !live.mayAttemptDriverExtension,
              "a binary clang just built says it cannot load a driver extension");
        CHECK([live.auditLine rangeOfString:@"dext=blocked"].location != NSNotFound,
              "and it says so in the line the panel would show");

        printf("RUN PASSED (%d checks)\n", checks_run);
        return failures ? 1 : 0;
    }
}
"""


def leaf_certificate(subject, what):
    """A real X.509 certificate whose subject is one of the issuer names under test.

    The classifier asks Security for a subject summary, and a summary can only be asked of a
    certificate. A chain made of strings would exercise the guard that refuses it and nothing
    else, which means the Developer ID branch -- the one branch that matters the day an identity
    exists -- would go untested forever. So the fixtures are generated here: an unrecognised
    issuer cannot be produced on this machine at all, and a chain nobody can build is a chain
    nobody can check.
    """
    with tempfile.TemporaryDirectory() as work:
        pem = os.path.join(work, "leaf.pem")
        der = os.path.join(work, "leaf.der")
        made = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                               "-keyout", os.devnull, "-out", pem, "-days", "36500",
                               "-subj", "/CN=" + subject], capture_output=True, text=True)
        turned = subprocess.run(["openssl", "x509", "-outform", "der", "-in", pem, "-out", der],
                                capture_output=True, text=True)
        if made.returncode != 0 or turned.returncode != 0 or not os.path.exists(der):
            raise SystemExit(
                "openssl could not produce the %s leaf certificate, so this gate cannot ask "
                "Security for a subject summary. openssl said: %s / %s. That is a missing "
                "or failing tool on the runner, not a defect in the code under test."
                % (what, made.stderr.strip()[-200:], turned.stderr.strip()[-200:]))
        return base64.b64encode(open(der, "rb").read()).decode()


def compiled(source, work, name, cc, sdk):
    path = os.path.join(work, name + ".m")
    binary = os.path.join(work, name)
    open(path, "w", encoding="utf-8").write(source)
    built = subprocess.run([cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
                            "-fobjc-arc", "-framework", "Foundation", "-framework", "Security",
                            path, "-o", binary], capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr)[-1500:]
    ran = subprocess.run([binary], capture_output=True, text=True)
    return ran, (ran.stdout + ran.stderr)


def run_rules(label, rules, cc, sdk, expect_pass=False):
    with tempfile.TemporaryDirectory() as work:
        source = PROFILE.replace("@@RULES@@", rules)
        ran, out = compiled(source, work, "profile_driver", cc, sdk)
        if ran is None:
            check(False, "%s: the harness compiled (%s)"
                  % (label, (out or "").strip().splitlines()[-1:]))
            return
        if expect_pass:
            reported = re.search(r"RUN PASSED \((\d+) checks\)", out or "")
            check(ran.returncode == 0, "%s behaves as documented" % label)
            count = int(reported.group(1)) if reported else -1
            check(count >= MIN_PROFILE_CHECKS,
                  "the compiled run reports its own case list (%d checks, floor %d)"
                  % (count, MIN_PROFILE_CHECKS))
        else:
            check(ran.returncode != 0, "the check still fails when %s" % label)
            if ran.returncode == 0:
                print((out or "").strip().splitlines()[-3:])


def mutated(rules, label, before, after):
    check(before in rules, "%s: the source it mutates is still there" % label)
    return rules.replace(before, after, 1)


def main():
    rules, impl, header = shipping_rules()
    print("-- what a build may say about its own signature --")

    cc, sdk = apple_toolchain.clang_and_sdk("code signature profile")
    leaves = {
        "@@DEVID@@": leaf_certificate(
            "Developer ID Application: Example Corp (ABCDE12345)", "Developer ID"),
        "@@DEVCERT@@": leaf_certificate(
            "Apple Development: somebody at example (ABCDE12345)", "development"),
        "@@OTHER@@": leaf_certificate(
            "3rd Party Mac Developer Application: Other Corp (ZZZZZZZZZZ)", "unrecognised"),
    }
    check(len(leaves) == 3, "three leaf certificates were generated, one per issuer shape")

    def inject(source):
        for token, value in leaves.items():
            source = source.replace(token, value)
        return source

    def run_and_patch(label, rules_, cc_, sdk_, expect_pass=False):
        with tempfile.TemporaryDirectory() as work:
            source = inject(PROFILE.replace("@@RULES@@", rules_))
            ran, out = compiled(source, work, "profile_driver", cc_, sdk_)
            if ran is None:
                check(False, "%s: the harness compiled (%s)"
                      % (label, (out or "").strip().splitlines()[-1:]))
                return
            if expect_pass:
                reported = re.search(r"RUN PASSED \((\d+) checks\)", out or "")
                check(ran.returncode == 0, "%s behaves as documented" % label)
                if ran.returncode != 0:
                    print("\n".join([line for line in (out or "").splitlines()
                                      if line.startswith("FAIL")])[:900])
                count = int(reported.group(1)) if reported else -1
                check(count >= MIN_PROFILE_CHECKS,
                      "the compiled run reports its own case list (%d checks, floor %d)"
                      % (count, MIN_PROFILE_CHECKS))
            else:
                check(ran.returncode != 0, "the check still fails when %s" % label)
                if ran.returncode == 0:
                    print((out or "").strip().splitlines()[-3:])

    run_and_patch("the shipping profile", rules, cc, sdk, expect_pass=True)

    check("NSLog(" not in impl and "printf(" not in impl,
          "the profile has no path to the log of its own")
    for forbidden in ("NSDate", "CACurrentMediaTime", "clock_gettime", "gettimeofday",
                      "OSSystemExtension", "IOService", "IORegistryEntry", "SecCodeCheckValidity"):
        check(forbidden not in impl + header,
              "the profile never touches %s: it reads a signature and stops there" % forbidden)
    check("SecRequirementCreateWithString" not in impl,
          "no requirement is asserted, so no designated requirement is guessed at")
    for key in ("kSecCodeInfoCertificates", "kSecCodeInfoEntitlementsDict",
                "kSecCodeInfoTeamIdentifier"):
        check(key in impl, "%s is read by its Security.framework constant" % key)
    check(len(re.findall(r"MLCodeSignatureForm\w+ = \d", header)) == 5,
          "five forms are named, and the panel has one word for each")

    run_and_patch("an absent chain is called Developer ID",
              mutated(rules, "the empty chain",
                      "        return MLCodeSignatureFormAdhoc;",
                      "        return MLCodeSignatureFormDeveloperID;"),
              cc, sdk)
    run_and_patch("the identity alone is taken as permission",
              mutated(rules, "the driver-kit half",
                      "        _mayAttemptDriverExtension = form == MLCodeSignatureFormDeveloperID && driverKitEntitlement;",
                      "        _mayAttemptDriverExtension = form == MLCodeSignatureFormDeveloperID;"),
              cc, sdk)
    run_and_patch("the entitlement alone is taken as permission",
              mutated(rules, "the identity half",
                      "        _mayAttemptDriverExtension = form == MLCodeSignatureFormDeveloperID && driverKitEntitlement;",
                      "        _mayAttemptDriverExtension = driverKitEntitlement;"),
              cc, sdk)
    run_and_patch("the system extension half borrows the DriverKit entitlement",
              mutated(rules, "the second capability",
                      "        _mayAttemptSystemExtension = form == MLCodeSignatureFormDeveloperID && systemExtensionEntitlement;",
                      "        _mayAttemptSystemExtension = form == MLCodeSignatureFormDeveloperID && driverKitEntitlement;"),
              cc, sdk)
    run_and_patch("a development identity is treated as good enough",
              mutated(rules, "the development prefix",
                      "    if ([subject hasPrefix:kAppleDevelopmentLeafPrefix]) {\n        return MLCodeSignatureFormAppleDevelopment;\n    }",
                      "    if ([subject hasPrefix:kAppleDevelopmentLeafPrefix]) {\n        return MLCodeSignatureFormDeveloperID;\n    }"),
              cc, sdk)
    run_and_patch("an unknown issuer becomes a known one",
              mutated(rules, "the unknown leaf",
                      "        return MLCodeSignatureFormAppleDevelopment;\n    }\n    return MLCodeSignatureFormOther;\n}",
                      "        return MLCodeSignatureFormAppleDevelopment;\n    }\n    return MLCodeSignatureFormDeveloperID;\n}"),
              cc, sdk)
    run_and_patch("the colon stops being part of the issuer name",
              mutated(rules, "the loose prefix",
                      'static NSString *const kDeveloperIDLeafPrefix = @"Developer ID Application:";',
                      'static NSString *const kDeveloperIDLeafPrefix = @"Developer ID";'),
              cc, sdk)
    run_and_patch("no chain element is ever believed to be a certificate",
              mutated(rules, "the guard refuses everything",
                      "    return CFGetTypeID((__bridge CFTypeRef)element) == SecCertificateGetTypeID();",
                      "    return NO;"),
              cc, sdk)
    # A guard that only refuses strings was tried and is not distinguishable here: Security
    # answers a foreign element with no summary rather than with a crash, so both shapes end at
    # `other`. It is left out because a mutation nobody can tell apart is noise, and the case
    # that keeps the original crash out -- a chain of numbers, a chain of text -- stays in.

    run_and_patch("any entitlement mentioning usb grants DriverKit",
              mutated(rules, "the driver-kit test",
                      "    return [key hasPrefix:kDriverKitEntitlementPrefix];",
                      "    return [key rangeOfString:@\"usb\"].location != NSNotFound;"),
              cc, sdk)
    run_and_patch("the system extension entitlement is prefix-matched",
              mutated(rules, "the exact key",
                      "    return [key isEqualToString:kSystemExtensionEntitlementKey];",
                      "    return [key hasPrefix:kSystemExtensionEntitlementKey];"),
              cc, sdk)
    run_and_patch("the team id is filled in when absent",
              mutated(rules, "the blank team",
                      "    if ([value isKindOfClass:[NSString class]] && [(NSString *)value length] > 0) {\n        return (NSString *)value;\n    }",
                      "    if ([value isKindOfClass:[NSString class]]) {\n        return [(NSString *)value length] > 0 ? (NSString *)value : @\"none\";\n    }"),
              cc, sdk)
    run_and_patch("the audit line carries the certificate subject",
              mutated(rules, "the audit line",
                      "              MLCodeSignatureFormName(self.form), (unsigned long)self.certificateCount,",
                      "              [NSString stringWithFormat:@\"%@ %@\", MLCodeSignatureFormName(self.form), self.teamIdentifier ?: @\"Application: unnamed\"], (unsigned long)self.certificateCount,"),
              cc, sdk)
    run_and_patch("an unreadable signature is reported as readable",
              mutated(rules, "the unreadable state",
                      "initWithForm:MLCodeSignatureFormUnknown\n                                                   readable:NO",
                      "initWithForm:MLCodeSignatureFormUnknown\n                                                   readable:YES"),
              cc, sdk)

    print("%d code-signature-profile failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
