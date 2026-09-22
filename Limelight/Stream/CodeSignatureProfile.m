//
//  CodeSignatureProfile.m
//  Moonlight
//
//  See CodeSignatureProfile.h for why the certificate chain is read and the flags number is
//  not. The one thing worth repeating here is the direction of every rule below: each capability
//  answer starts false and is only ever set by evidence, so a dictionary that arrives empty,
//  malformed, or from an SDK that renamed a key produces "cannot attempt" rather than a guess.
//

#import "CodeSignatureProfile.h"

#import <Security/Security.h>

// The three keys that Security.framework names are taken from its own constants. A spelling
// copied out of `codesign` output would compile and run either way, so a wrong one could only be
// found on a machine that had an identity to test with -- which is exactly the machine this
// repository does not have yet. Everything Apple does not name stays a literal, commented as such.
static NSString *CertificatesKey(void) {
    return (__bridge NSString *)kSecCodeInfoCertificates;
}
static NSString *EntitlementsKey(void) {
    return (__bridge NSString *)kSecCodeInfoEntitlementsDict;
}
static NSString *TeamIdentifierKey(void) {
    return (__bridge NSString *)kSecCodeInfoTeamIdentifier;
}
// Apple defines no constant for either of these two. The first is a published entitlement
// identifier, the second the requirement text every DriverKit build repeats.
static NSString *const kTeamIdentifierEntitlementKey = @"com.apple.developer.team-identifier";
static NSString *const kDriverKitEntitlementPrefix = @"com.apple.developer.driverkit";
static NSString *const kSystemExtensionEntitlementKey = @"com.apple.developer.system-extension.install";
// The two issuer names this header can distinguish, measured on the leaf summary of a Developer
// ID app on this machine. The development prefix is the published spelling and is the one form
// here that has no second-party sample on this host; an unrecognised prefix classifies as
// `other` rather than as either known form, so a wrong guess degrades to "unknown identity"
// instead of claiming a capability.
static NSString *const kDeveloperIDLeafPrefix = @"Developer ID Application:";
static NSString *const kAppleDevelopmentLeafPrefix = @"Apple Development:";

@interface MLCodeSignatureProfile ()
- (instancetype)initWithForm:(MLCodeSignatureForm)form
                    readable:(BOOL)readable
           certificateCount:(NSUInteger)certificateCount
              teamIdentifier:(nullable NSString *)teamIdentifier
        driverKitEntitlement:(BOOL)driverKitEntitlement
   systemExtensionEntitlement:(BOOL)systemExtensionEntitlement;
@end

@implementation MLCodeSignatureProfile

- (instancetype)initWithForm:(MLCodeSignatureForm)form
                    readable:(BOOL)readable
           certificateCount:(NSUInteger)certificateCount
              teamIdentifier:(nullable NSString *)teamIdentifier
        driverKitEntitlement:(BOOL)driverKitEntitlement
   systemExtensionEntitlement:(BOOL)systemExtensionEntitlement {
    self = [super init];
    if (self) {
        _form = form;
        _signingInformationWasReadable = readable;
        _certificateCount = certificateCount;
        _teamIdentifier = [teamIdentifier copy];
        _hasDriverKitEntitlement = driverKitEntitlement;
        _hasSystemExtensionEntitlement = systemExtensionEntitlement;
        // Both answers need the identity and the entitlement. A correctly entitled build signed
        // by a development identity is refused, and a Developer ID build without the entitlement
        // is refused, so neither half may carry the other.
        _mayAttemptDriverExtension = form == MLCodeSignatureFormDeveloperID && driverKitEntitlement;
        _mayAttemptSystemExtension = form == MLCodeSignatureFormDeveloperID && systemExtensionEntitlement;
    }
    return self;
}

- (NSString *)auditLine {
    return [NSString stringWithFormat:
              @"signature=%@ certificates=%lu team=%@ driverkit=%@ system-extension=%@ dext=%@",
              MLCodeSignatureFormName(self.form), (unsigned long)self.certificateCount,
              self.teamIdentifier ?: @"none",
              self.hasDriverKitEntitlement ? @"yes" : @"no",
              self.hasSystemExtensionEntitlement ? @"yes" : @"no",
              self.mayAttemptDriverExtension ? @"allowed" : @"blocked"];
}

@end

NSString *MLCodeSignatureFormName(MLCodeSignatureForm form) {
    switch (form) {
        case MLCodeSignatureFormUnknown:
            return @"unreadable";
        case MLCodeSignatureFormAdhoc:
            return @"adhoc";
        case MLCodeSignatureFormOther:
            return @"other";
        case MLCodeSignatureFormAppleDevelopment:
            return @"apple-development";
        case MLCodeSignatureFormDeveloperID:
            return @"developer-id";
    }
    // An out of range form arrives only from a caller that cast an integer into the enum. It is
    // reported as unreadable rather than reaching an unreachable return, because the alternative
    // is a crash or a name that claims something about a signature nobody read.
    return @"unreadable";
}

MLCodeSignatureForm MLCodeSignatureFormForLeafSubject(NSString *subject) {
    if (![subject isKindOfClass:[NSString class]] || subject.length == 0) {
        return MLCodeSignatureFormOther;
    }
    // The colon is part of the prefix. Without it, a subject that merely begins with the same
    // words would be read as an identity this build has never seen.
    if ([subject hasPrefix:kDeveloperIDLeafPrefix]) {
        return MLCodeSignatureFormDeveloperID;
    }
    if ([subject hasPrefix:kAppleDevelopmentLeafPrefix]) {
        return MLCodeSignatureFormAppleDevelopment;
    }
    return MLCodeSignatureFormOther;
}

/// Whether one element of the chain can be asked for a subject summary. `SecCertificate` is a
/// CoreFoundation type, so the array's contents are not Objective-C objects in the ordinary
/// sense, and a Foundation value type reaching here is a chain this reader does not understand.
/// Naming the value types first is deliberate: `CFGetTypeID` is itself unsafe on an object that
/// is not a CF one, so it must not be the thing standing between a foreign element and a crash.
static BOOL MLLooksLikeCertificate(id element) {
    if (element == nil) {
        return NO;
    }
    if ([element isKindOfClass:[NSString class]] || [element isKindOfClass:[NSNumber class]] ||
        [element isKindOfClass:[NSArray class]] || [element isKindOfClass:[NSDictionary class]] ||
        [element isKindOfClass:[NSData class]] || [element isKindOfClass:[NSURL class]]) {
        return NO;
    }
    return CFGetTypeID((__bridge CFTypeRef)element) == SecCertificateGetTypeID();
}

/// The leaf is the first certificate in the chain, which is the order both `codesign` and the
/// measured third-party app hand over. A chain that arrives in some other order, or whose leaf
/// is not what it claims to be, classifies as `other`: the issuer this rule would have needed was
/// not where it should have been.
static MLCodeSignatureForm MLFormForCertificates(NSArray *certificates) {
    if (![certificates isKindOfClass:[NSArray class]] || certificates.count == 0) {
        return MLCodeSignatureFormAdhoc;
    }
    id leaf = certificates.firstObject;
    if (!MLLooksLikeCertificate(leaf)) {
        return MLCodeSignatureFormOther;
    }
    CFStringRef summary = SecCertificateCopySubjectSummary((__bridge SecCertificateRef)leaf);
    if (summary == NULL) {
        return MLCodeSignatureFormOther;
    }
    return MLCodeSignatureFormForLeafSubject(CFBridgingRelease(summary));
}

static NSString *MLStringInDictionary(NSDictionary *dictionary, NSString *key) {
    id value = dictionary[key];
    if ([value isKindOfClass:[NSString class]] && [(NSString *)value length] > 0) {
        return (NSString *)value;
    }
    // A number is a shape a team id could arrive as, and reporting it as its digits is reporting
    // what was read. A blank or a foreign type is reported as no team.
    if ([value isKindOfClass:[NSNumber class]]) {
        return [(NSNumber *)value stringValue];
    }
    return nil;
}

static BOOL MLEntitlementIsDriverKit(NSString *key) {
    // Prefix, not equality: `com.apple.developer.driverkit` and its transport and user-client
    // children are all part of the same capability, and a dext that declares only the transport
    // is not a build that can load one either -- but the panel's question is whether the build
    // asked for DriverKit at all, and the prefix is what answers that.
    return [key hasPrefix:kDriverKitEntitlementPrefix];
}

static BOOL MLEntitlementIsSystemExtension(NSString *key) {
    // Equality, not prefix: this key has no family, and `com.apple.developer.system-extension.`
    // followed by anything would credit an entitlement that Apple does not define.
    return [key isEqualToString:kSystemExtensionEntitlementKey];
}

MLCodeSignatureProfile *MLCodeSignatureProfileFromSigningInformation(
    NSDictionary<NSString *, id> *signingInformation) {
    if (![signingInformation isKindOfClass:[NSDictionary class]]) {
        return [[MLCodeSignatureProfile alloc] initWithForm:MLCodeSignatureFormUnknown
                                                   readable:NO
                                          certificateCount:0
                                              teamIdentifier:nil
                                        driverKitEntitlement:NO
                                   systemExtensionEntitlement:NO];
    }

    id certificatesValue = signingInformation[CertificatesKey()];
    const MLCodeSignatureForm form = MLFormForCertificates(certificatesValue);
    const NSUInteger certificateCount =
        [certificatesValue isKindOfClass:[NSArray class]] ? [(NSArray *)certificatesValue count] : 0;

    // A malformed entitlements value is treated as absent rather than as empty: an empty
    // entitlements dictionary is a fact about the build, while a dictionary that is not a
    // dictionary means this reader could not see the entitlements.
    id entitlementsValue = signingInformation[EntitlementsKey()];
    NSDictionary *entitlements = [entitlementsValue isKindOfClass:[NSDictionary class]]
        ? (NSDictionary *)entitlementsValue
        : nil;

    BOOL driverKit = NO;
    BOOL systemExtension = NO;
    for (id key in entitlements) {
        if (![key isKindOfClass:[NSString class]]) {
            continue;
        }
        if (MLEntitlementIsDriverKit((NSString *)key)) {
            driverKit = YES;
        }
        if (MLEntitlementIsSystemExtension((NSString *)key)) {
            systemExtension = YES;
        }
    }

    // The signing information first, because that is what the signature itself carries; the
    // entitlement second, because a Developer ID build that omitted it could not be signed at all
    // and an ad-hoc build simply has neither.
    NSString *team = MLStringInDictionary(signingInformation, TeamIdentifierKey());
    if (team == nil) {
        team = MLStringInDictionary(entitlements, kTeamIdentifierEntitlementKey);
    }

    return [[MLCodeSignatureProfile alloc] initWithForm:form
                                               readable:YES
                                      certificateCount:certificateCount
                                         teamIdentifier:team
                                   driverKitEntitlement:driverKit
                              systemExtensionEntitlement:systemExtension];
}

MLCodeSignatureProfile *MLCodeSignatureProfileOfCurrentProcess(void) {
    SecCodeRef code = NULL;
    if (SecCodeCopySelf(kSecCSDefaultFlags, &code) != errSecSuccess || code == NULL) {
        return MLCodeSignatureProfileFromSigningInformation(nil);
    }
    CFDictionaryRef information = NULL;
    const OSStatus status = SecCodeCopySigningInformation(
        code, kSecCSSigningInformation | kSecCSRequirementInformation | kSecCSDynamicInformation,
        &information);
    NSDictionary *read = information ? CFBridgingRelease(information) : nil;
    CFRelease(code);
    if (status != errSecSuccess || read == nil) {
        return MLCodeSignatureProfileFromSigningInformation(nil);
    }
    return MLCodeSignatureProfileFromSigningInformation(read);
}
