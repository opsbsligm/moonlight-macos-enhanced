//
//  MLDriverExtensionActivation.h
//
//  STAGED: not compiled into the product. See UNLOCK(stage3) at the bottom of this header.
//
//  What Apple's activation delegate says, translated into what this project already knows.
//
//  Stage 3 of docs/usb-redirection-design.md is blocked on two things the repository does not
//  have -- a Developer ID identity and a notarisation pipeline (2.3) -- and the blocker is not a
//  missing call. `Limelight/` is a synchronised folder group, so a `.m` dropped in there would be
//  compiled into the app whether or not anybody wired it, which is how "we ship device
//  passthrough" ends up in a binary whose extension cannot load. So the half that is *ours to get
//  right today* lives outside that group, is compiled by scripts/driver-extension-activation-tests.py
//  against the SDK headers the build uses, and is asserted there. The half that is not ours --
//  the extension bundle, the entitlement, the certificate -- is what UNLOCK(stage3) below lists,
//  and scripts/driver-extension-signing-audit.py refuses the combination "the extension target
//  exists" and "nobody can load what it produces".
//
//  The translation is the part worth having. `MLDriverLifecycle` already refuses to treat an
//  unanswered request as an installed driver, and Apple's delegate has four callbacks that an
//  unwary caller would read as one: needs-user-approval (a dialog opened, nothing installed),
//  didFinishWithResult: with WillCompleteAfterReboot (registered, not running), didFailWithError:
//  with a signing-class code (this build cannot load, ever), and didFinishWithResult: with
//  Completed (the only one that means running). Each maps to one lifecycle event or to none, and
//  the ones that mean nothing get no event rather than the nearest one.
//

#import <Foundation/Foundation.h>

#import <SystemExtensions/SystemExtensions.h>

#import "../../Limelight/Stream/DriverLifecycle.h"

NS_ASSUME_NONNULL_BEGIN

/// One callback from `OSSystemExtensionRequestDelegate`, named for what it says rather than for
/// the method that delivered it. `ReplacementRequested` is Apple's `actionForReplacingExtension:`
/// question; a decision is not a load.
typedef NS_ENUM(NSInteger, MLDriverExtensionCallback) {
    MLDriverExtensionCallbackNeedsUserApproval = 1,
    /// `didFinishWithResult: OSSystemExtensionRequestCompleted`.
    MLDriverExtensionCallbackCompleted = 2,
    /// `didFinishWithResult: OSSystemExtensionRequestWillCompleteAfterReboot`.
    MLDriverExtensionCallbackCompletedAfterReboot = 3,
    MLDriverExtensionCallbackReplacementRequested = 4,
    MLDriverExtensionCallbackFailed = 5,
};

/// What one callback leaves behind: the lifecycle after the one event the callback supports (or
/// after no event at all), one reason name shared with the log line, and two questions a caller
/// has to be able to ask separately -- whether the player has something to do, and whether this
/// side may ask again.
@interface MLDriverExtensionOutcome : NSObject
@property(nonatomic, readonly, strong) MLDriverLifecycle *lifecycle;
@property(nonatomic, readonly, copy) NSString *reasonName;
/// Approving a dialog, rebooting, or pressing the button again. Anything the app cannot do for
/// the player, said once, so a page does not have to guess from a phase.
@property(nonatomic, readonly) BOOL playerActionRequired;
/// False exactly when asking again in this session cannot change the answer: the extension is
/// already running, or the system refused something about this build.
@property(nonatomic, readonly) BOOL mayAskAgain;
@end

/// The translation, with no clock and no system call in it.
///
/// `error` is interpreted only when it carries `OSSystemExtensionErrorDomain`: a foreign error is
/// reported as one, and reported as unmapped, rather than being read against a table of codes it
/// was never drawn from. A code in our domain that this file does not name lands on
/// `unmapped-error` and produces no event -- a callback nobody recognised is not evidence that
/// anything is installed, whatever the nearest case would have said.
FOUNDATION_EXPORT MLDriverExtensionOutcome *MLDriverExtensionApplyCallback(
    MLDriverLifecycle *lifecycle,
    MLDriverExtensionCallback callback,
    NSError *_Nullable error);

/// The three calls of Apple's activation API, behind an object. Everything above this line is
/// arithmetic on an enum and can be driven by a gate; this protocol is the part that would
/// otherwise need a signed extension to observe. The delegate is `id` rather than
/// `id<OSSystemExtensionRequestDelegate>` so a gate can hold one without conforming to a protocol
/// whose required methods it would have to invent -- the port below casts at the one place it
/// touches Apple's class.
@protocol MLSystemExtensionRequesting <NSObject>
- (void)submitActivationForExtension:(NSString *)identifier
                             delegate:(id)delegate
                                queue:(dispatch_queue_t)queue;
@end

/// The real port. Three lines of Apple API, none of which a gate can execute: submitting an
/// activation request asks a system daemon about an extension bundle this repository does not
/// build. It is compiled against the SDK headers the build uses -- which is what makes naming a
/// method Apple does not have a build failure rather than a runtime surprise -- and its behaviour
/// is asserted by the gate driving the fake, not claimed.
@interface MLSystemExtensionPort : NSObject <MLSystemExtensionRequesting>
+ (instancetype)port;
@end

/// The callback sink a real app would own: it holds the lifecycle, asks once, and turns every
/// delegate callback into exactly one row of the table above.
@interface MLDriverExtensionActivationController : NSObject <OSSystemExtensionRequestDelegate>
- (instancetype)init NS_UNAVAILABLE;
@property(nonatomic, readonly, strong) MLDriverLifecycle *lifecycle;
@property(nonatomic, readonly, copy) NSString *lastReasonName;
- (instancetype)initWithExtensionIdentifier:(NSString *)identifier
                                crashBudget:(NSInteger)crashBudget
                                       port:(nullable id<MLSystemExtensionRequesting>)port;
- (instancetype)initWithExtensionIdentifier:(NSString *)identifier
                           startingLifecycle:(MLDriverLifecycle *)lifecycle
                                        port:(nullable id<MLSystemExtensionRequesting>)port NS_DESIGNATED_INITIALIZER;
- (MLDriverExtensionOutcome *)askForActivation;
- (MLDriverExtensionOutcome *)recordCallback:(MLDriverExtensionCallback)callback
                                        error:(NSError *_Nullable )error;
@end

/// The name used for a callback this switch does not carry. Two spellings of one refusal is a
/// support thread nobody can follow, so the spelling lives here.
FOUNDATION_EXPORT NSString *MLDriverExtensionCallbackName(MLDriverExtensionCallback callback);

//
//  UNLOCK(stage3) -- the four things that must happen before this file belongs to the product.
//  scripts/driver-extension-signing-audit.py asserts this list's first three items against the
//  workflow, and asserts that this directory is not referenced by Moonlight.xcodeproj. Do not
//  "tidy" this block away: a placeholder that does not announce itself is a feature nobody
//  marked unfinished.
//
//    1. a DriverKit extension target built by both macOS jobs, embedding an `OSBundleUsageDescription`;
//    2. the app and that extension signed with a Developer ID identity and the hardened runtime;
//    3. `notarytool` submission plus `stapler staple`, or the downloaded copy will not open;
//    4. `com.apple.developer.driverkit` and the driver-family entitlement on the extension, which
//       MLCodeSignatureProfile already reports as missing for the shipping build today.
//
//  When all four land, moving this directory into the product is the change -- not writing it.
//

NS_ASSUME_NONNULL_END
