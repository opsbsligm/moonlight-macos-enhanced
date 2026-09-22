//
//  CodeSignatureProfile.h
//  Moonlight
//
//  What this build can honestly say about how it was signed, and therefore about whether a
//  driver extension could ever load inside it.
//
//  Stage 3 of docs/usb-redirection-design.md is blocked on a signing identity, and the panel
//  built in the same document has to say why it has nothing to offer. A panel that only listed
//  refused devices would dress a missing certificate up as a broken webcam, so the refusal needs
//  a precondition line beside it -- and that line has to be read from the running binary rather
//  than written down by whoever last configured the build. A hard-coded "not signed" would be
//  wrong the day this repository gets an identity; a hard-coded "signed" would be wrong today.
//
//  Two measurements set the shape of this header, both on macOS 27.2 with public Security APIs:
//  the ad-hoc build described in 2.3 returns a signing-information dictionary with no
//  `certificates` key at all, while a third-party Developer ID app returns a three-certificate
//  chain whose leaf reads `Developer ID Application: <company> (<TEAM>)`. So the chain, not the
//  opaque `flags` number, is what gets read: `flags` came back as 131074 for the ad-hoc build and
//  the bit meanings are not in the installed SDK, and a rule nobody can recompute is a rule
//  nobody can debug.
//
//  What is deliberately absent: notarisation. A Developer ID signature is necessary for a system
//  extension and not sufficient -- it also has to be notarised and run the hardened runtime --
//  and nothing here can observe a notarisation ticket. `mayAttemptDriverExtension` therefore
//  means "the identity and the entitlement are both present", which is the strongest claim the
//  available API supports, and the panel says the rest is unverified rather than implied.
//

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// How the binary was signed, read from its own signature.
typedef NS_ENUM(NSInteger, MLCodeSignatureForm) {
    /// Nothing readable came back. Not "unsigned": the question could not be asked.
    MLCodeSignatureFormUnknown = 0,
    /// No certificate chain. Ad-hoc and unsigned both land here. Both are refused at the moment
    /// an extension is asked for -- the authorization refusal measured in docs 2.3 -- which is
    /// the only question this header is asked. The API name is kept out of this file on purpose:
    /// scripts/driver-extension-signing-audit.py reads it as evidence that stage 3 has begun.
    MLCodeSignatureFormAdhoc = 1,
    /// A chain exists whose leaf is named below neither of the two known issuers. Recorded
    /// rather than guessed at: an enterprise or a future signing shape is not an ad-hoc build.
    MLCodeSignatureFormOther = 2,
    /// `Apple Development:` -- enough to run on this machine, not enough to load an extension.
    MLCodeSignatureFormAppleDevelopment = 3,
    /// `Developer ID Application:` -- the identity a loadable extension requires.
    MLCodeSignatureFormDeveloperID = 4,
};

@interface MLCodeSignatureProfile : NSObject
@property(nonatomic, readonly) MLCodeSignatureForm form;
/// Whether any signing information could be read at all. False is not a verdict about the
/// signature, and the panel must not render it as one.
@property(nonatomic, readonly) BOOL signingInformationWasReadable;
@property(nonatomic, readonly) NSUInteger certificateCount;
/// Read from the signing information's team id when it carries one, and left nil when it does
/// not. A team id invented to fill the gap would make an ad-hoc build look like somebody's.
@property(nonatomic, readonly, copy, nullable) NSString *teamIdentifier;
/// Any `com.apple.developer.driverkit...` entitlement. Prefix-matched on purpose: the transport
/// and user-client keys are separate entitlements, and a dext needs more than one of them.
@property(nonatomic, readonly) BOOL hasDriverKitEntitlement;
/// `com.apple.developer.system-extension.install` exactly. Not prefix-matched: the key has no
/// family, and a rule that accepted `...install.something` would credit an entitlement Apple
/// does not define.
@property(nonatomic, readonly) BOOL hasSystemExtensionEntitlement;
/// Identity and entitlement together. Either alone is a build that will be refused.
@property(nonatomic, readonly) BOOL mayAttemptDriverExtension;
@property(nonatomic, readonly) BOOL mayAttemptSystemExtension;
/// One line, safe to log and to show. It carries the form, the counts and the two capability
/// answers; it does not carry the leaf summary, whose subject is a company name and which is
/// nothing a support log needs in order to know that the build is ad-hoc.
@property(nonatomic, readonly, copy) NSString *auditLine;
@end

/// The one spelling of each form, shared by the audit line and the panel.
FOUNDATION_EXPORT NSString *MLCodeSignatureFormName(MLCodeSignatureForm form);

/// Which identity an issuer name describes. Split out from the chain because reading a subject
/// summary needs a certificate object, and every prefix rule below has to be reachable from a
/// string: the day the identity arrives is the day nobody can produce the sample on the machine
/// that is checking the rule. An unknown or empty subject is `other`, and so is a name that only
/// resembles a known one -- `Developer ID Application` without its colon, or the same words in
/// lower case, are not identities this build has met.
FOUNDATION_EXPORT MLCodeSignatureForm MLCodeSignatureFormForLeafSubject(
    NSString * _Nullable subject);

/// The classification, with the signing-information dictionary handed in. Pure: every form
/// above, including the ones nobody can produce on the machine running the test, is reachable
/// from here, which is why the gate can assert them at all.
FOUNDATION_EXPORT MLCodeSignatureProfile *MLCodeSignatureProfileFromSigningInformation(
    NSDictionary<NSString *, id> * _Nullable signingInformation);

/// This process, asked through Security.framework. Ad-hoc on every machine that has not been
/// given an identity, which is measured by the gate rather than assumed.
FOUNDATION_EXPORT MLCodeSignatureProfile *MLCodeSignatureProfileOfCurrentProcess(void);

NS_ASSUME_NONNULL_END
