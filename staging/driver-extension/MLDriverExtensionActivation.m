//
//  MLDriverExtensionActivation.m
//
//  STAGED: not compiled into the product. See UNLOCK(stage3) in the header.
//

#import "MLDriverExtensionActivation.h"

#import <SystemExtensions/SystemExtensions.h>

@interface MLDriverExtensionOutcome ()
+ (instancetype)outcomeWithLifecycle:(MLDriverLifecycle *)lifecycle
                          reasonName:(NSString *)reasonName
                  playerActionRequired:(BOOL)playerActionRequired;
@end

@implementation MLDriverExtensionOutcome

+ (instancetype)outcomeWithLifecycle:(MLDriverLifecycle *)lifecycle
                          reasonName:(NSString *)reasonName
                  playerActionRequired:(BOOL)playerActionRequired {
    MLDriverExtensionOutcome *outcome = [[MLDriverExtensionOutcome alloc] init];
    outcome->_lifecycle = lifecycle;
    outcome->_reasonName = [reasonName copy];
    outcome->_playerActionRequired = playerActionRequired;
    // Derived, not decided per case. "May I ask again by myself" is the lifecycle's question, and
    // a translation that answered it locally would be free to say yes to a session that the
    // lifecycle already decided must wait for the player.
    outcome->_mayAskAgain = lifecycle.mayAttemptInstall;
    return outcome;
}

@end

NSString *MLDriverExtensionCallbackName(MLDriverExtensionCallback callback) {
    switch (callback) {
        case MLDriverExtensionCallbackNeedsUserApproval: return @"needs-user-approval";
        case MLDriverExtensionCallbackCompleted: return @"completed";
        case MLDriverExtensionCallbackCompletedAfterReboot: return @"completed-after-reboot";
        case MLDriverExtensionCallbackReplacementRequested: return @"replacement-requested";
        case MLDriverExtensionCallbackFailed: return @"failed";
    }
    return @"unmapped-callback";
}

/// The one spelling each refusal gets, shared with `MLDriverLifecycleStopName` and with the panel.
/// An error case this file does not name has to be added here deliberately rather than falling
/// through into the nearest case, which is how a signing gap ends up reported as a decline.
static NSString *MLDriverExtensionErrorReason(NSError *error, BOOL *isOurDomain) {
    *isOurDomain = [error.domain isEqualToString:OSSystemExtensionErrorDomain];
    if (!*isOurDomain) {
        return @"failed-foreign-error";
    }
    switch (error.code) {
        // The build class: the system answered, and the answer is about this product rather than
        // about a player or a network. A retry of the same bytes cannot change any of them.
        case OSSystemExtensionErrorMissingEntitlement: return @"missing-entitlement";
        case OSSystemExtensionErrorCodeSignatureInvalid: return @"code-signature-invalid";
        case OSSystemExtensionErrorValidationFailed: return @"validation-failed";
        case OSSystemExtensionErrorUnsupportedParentBundleLocation: return @"unsupported-parent-bundle-location";
        case OSSystemExtensionErrorExtensionNotFound: return @"extension-not-found";
        case OSSystemExtensionErrorExtensionMissingIdentifier: return @"extension-missing-identifier";
        case OSSystemExtensionErrorDuplicateExtensionIdentifer: return @"duplicate-extension-identifier";
        case OSSystemExtensionErrorUnknownExtensionCategory: return @"unknown-extension-category";
        // The consent class: nothing is installed, and the thing missing is a person pressing a
        // button. Distinct from the build class because the player can finish it.
        case OSSystemExtensionErrorForbiddenBySystemPolicy: return @"forbidden-by-system-policy";
        case OSSystemExtensionErrorAuthorizationRequired: return @"authorization-required";
        // The request class: our own request stopped mattering. The system's state is unchanged,
        // so the lifecycle keeps saying `installing` and the caller's timer ends it honestly.
        case OSSystemExtensionErrorRequestCanceled: return @"request-canceled";
        case OSSystemExtensionErrorRequestSuperseded: return @"request-superseded";
        case OSSystemExtensionErrorUnknown: return @"unknown-error";
    }
    return @"unmapped-error";
}

MLDriverExtensionOutcome *MLDriverExtensionApplyCallback(MLDriverLifecycle *lifecycle,
                                                         MLDriverExtensionCallback callback,
                                                         NSError *error) {
    switch (callback) {
        case MLDriverExtensionCallbackNeedsUserApproval:
            // A dialog opened. Nothing is installed, nobody declined, and the request is still
            // outstanding -- so no event at all. Recording an approval here would be the same
            // mistake MLDriverLifecycle already refuses to make: the dialog closing is not a
            // loaded driver.
            return [MLDriverExtensionOutcome outcomeWithLifecycle:lifecycle
                                                       reasonName:@"awaiting-user-approval"
                                             playerActionRequired:YES];

        case MLDriverExtensionCallbackCompleted:
            return [MLDriverExtensionOutcome
                        outcomeWithLifecycle:[lifecycle lifecycleByRecordingActivation]
                                  reasonName:@"activated"
                        playerActionRequired:NO];

        case MLDriverExtensionCallbackCompletedAfterReboot:
            // Registered, scheduled, and not running. `mayHandOverDevices` asks for Active, so an
            // event here would hand a device to a driver that starts on a boot this machine has
            // not taken yet. Leaving the phase at `installing` is not a stall: the caller owns the
            // install timer, and the answer that never arrives ends at `install-unanswered`.
            return [MLDriverExtensionOutcome outcomeWithLifecycle:lifecycle
                                                       reasonName:@"active-after-reboot"
                                             playerActionRequired:YES];

        case MLDriverExtensionCallbackReplacementRequested:
            // Apple is asking which of two versions to keep. Answering is a decision, not a load.
            return [MLDriverExtensionOutcome outcomeWithLifecycle:lifecycle
                                                       reasonName:@"replacement-decision"
                                             playerActionRequired:NO];

        case MLDriverExtensionCallbackFailed: {
            if (error == nil) {
                // A failure with nothing to read. Claiming a reason would be inventing one.
                return [MLDriverExtensionOutcome outcomeWithLifecycle:lifecycle
                                                           reasonName:@"failed-without-error"
                                                 playerActionRequired:YES];
            }
            BOOL ours = NO;
            NSString *reason = MLDriverExtensionErrorReason(error, &ours);
            if (!ours) {
                return [MLDriverExtensionOutcome outcomeWithLifecycle:lifecycle
                                                           reasonName:reason
                                                 playerActionRequired:YES];
            }
            if ([reason isEqualToString:@"missing-entitlement"] ||
                [reason isEqualToString:@"code-signature-invalid"] ||
                [reason isEqualToString:@"validation-failed"] ||
                [reason isEqualToString:@"unsupported-parent-bundle-location"] ||
                [reason isEqualToString:@"extension-not-found"] ||
                [reason isEqualToString:@"extension-missing-identifier"] ||
                [reason isEqualToString:@"duplicate-extension-identifier"] ||
                [reason isEqualToString:@"unknown-extension-category"]) {
                return [MLDriverExtensionOutcome
                            outcomeWithLifecycle:[lifecycle lifecycleByRecordingBuildRefusal]
                                      reasonName:reason
                            playerActionRequired:NO];
            }
            if ([reason isEqualToString:@"forbidden-by-system-policy"] ||
                [reason isEqualToString:@"authorization-required"]) {
                return [MLDriverExtensionOutcome
                            outcomeWithLifecycle:[lifecycle lifecycleByRecordingUserDecline]
                                      reasonName:reason
                            playerActionRequired:YES];
            }
            // `request-canceled`, `request-superseded`, `unknown-error`, `unmapped-error`: the
            // system said the request did not succeed, which is not the same statement as "the
            // extension is not installed", and not a reason to stop asking forever either.
            return [MLDriverExtensionOutcome outcomeWithLifecycle:lifecycle
                                                       reasonName:reason
                                             playerActionRequired:YES];
        }
    }
    // A callback value this switch does not carry. It arrives from a header newer than this file,
    // and the honest reading of a message nobody recognised is that nothing was learned.
    return [MLDriverExtensionOutcome outcomeWithLifecycle:lifecycle
                                               reasonName:@"unmapped-callback"
                                     playerActionRequired:YES];
}

//
//  The port. Three methods of Apple's API, behind an object so the sequence above can be driven
//  by a gate instead of by a system extension nobody can install yet.
//

@interface MLDriverExtensionActivationController ()
@property(nonatomic, readonly, copy) NSString *extensionIdentifier;
@property(nonatomic, strong) id<MLSystemExtensionRequesting> port;
// Redeclared readwrite: every callback returns a fresh lifecycle, and the object that holds one
// has to be able to put the next one in. Nothing outside this file can.
@property(nonatomic, readwrite, strong) MLDriverLifecycle *lifecycle;
@property(nonatomic, readwrite, copy) NSString *lastReasonName;
@end

@implementation MLDriverExtensionActivationController

- (instancetype)initWithExtensionIdentifier:(NSString *)identifier
                                crashBudget:(NSInteger)crashBudget
                                       port:(nullable id<MLSystemExtensionRequesting>)port {
    return [self initWithExtensionIdentifier:identifier
                            startingLifecycle:[MLDriverLifecycle untouchedLifecycleWithCrashBudget:crashBudget]
                                         port:port];
}

- (instancetype)initWithExtensionIdentifier:(NSString *)identifier
                            startingLifecycle:(MLDriverLifecycle *)lifecycle
                                         port:(nullable id<MLSystemExtensionRequesting>)port {
    self = [super init];
    if (self) {
        _extensionIdentifier = [identifier copy];
        _lifecycle = lifecycle;
        _port = port ?: [MLSystemExtensionPort port];
        _lastReasonName = @"never-asked";
    }
    return self;
}

- (MLDriverExtensionOutcome *)askForActivation {
    MLDriverLifecycle *before = self.lifecycle;
    if (!before.mayAttemptInstall) {
        // Refused here, before the framework is touched: a request that the lifecycle would
        // reject anyway is still a request the system has to process, and a page that pressed it
        // in a loop would be a page that asked Apple to do work it had already refused.
        return [MLDriverExtensionOutcome outcomeWithLifecycle:before
                                                   reasonName:@"attempt-refused-by-lifecycle"
                                         playerActionRequired:NO];
    }
    MLDriverExtensionOutcome *outcome =
        [self recordCallback:MLDriverExtensionCallbackNeedsUserApproval error:nil];
    // The request goes out under the phase it is about to be recorded with, so an answer that
    // arrives on another thread cannot find a lifecycle that has not asked yet. Needs-user-approval
    // is not assumed to be the first callback -- it is the state any outstanding request is in for
    // the caller's purposes, and Completed replaces it the moment it arrives.
    [self.port submitActivationForExtension:self.extensionIdentifier
                                    delegate:self
                                       queue:dispatch_get_main_queue()];
    self.lifecycle = [before lifecycleByRequestingInstall];
    self.lastReasonName = outcome.reasonName;
    return outcome;
}

- (MLDriverExtensionOutcome *)recordCallback:(MLDriverExtensionCallback)callback
                                       error:(NSError *_Nullable )error {
    MLDriverExtensionOutcome *outcome =
        MLDriverExtensionApplyCallback(self.lifecycle, callback, error);
    self.lifecycle = outcome.lifecycle;
    self.lastReasonName = outcome.reasonName;
    return outcome;
}

//
//  OSSystemExtensionRequestDelegate. Each one forwards and adds nothing, which is the point: the
//  decisions are in the table above, where a gate can reach them.
//

- (void)requestNeedsUserApproval:(OSSystemExtensionRequest *)request {
    [self recordCallback:MLDriverExtensionCallbackNeedsUserApproval error:nil];
}

- (void)request:(OSSystemExtensionRequest *)request didFinishWithResult:(OSSystemExtensionRequestResult)result {
    [self recordCallback:result == OSSystemExtensionRequestCompleted
                             ? MLDriverExtensionCallbackCompleted
                             : (result == OSSystemExtensionRequestWillCompleteAfterReboot
                                    ? MLDriverExtensionCallbackCompletedAfterReboot
                                    : MLDriverExtensionCallbackFailed)
                   error:nil];
}

- (void)request:(OSSystemExtensionRequest *)request didFailWithError:(NSError *)error {
    [self recordCallback:MLDriverExtensionCallbackFailed error:error];
}

- (OSSystemExtensionReplacementAction)request:(OSSystemExtensionRequest *)request
                  actionForReplacingExtension:(OSSystemExtensionProperties *)existing
                                withExtension:(OSSystemExtensionProperties *)extension {
    // Replacing our own older extension with the one this build carries is the only reason Apple
    // asks; cancelling would keep a version this build does not ship. The decision is recorded as
    // a decision -- it says nothing about whether anything is loaded.
    [self recordCallback:MLDriverExtensionCallbackReplacementRequested error:nil];
    return OSSystemExtensionReplacementActionReplace;
}

@end

@implementation MLSystemExtensionPort

+ (instancetype)port {
    return [[MLSystemExtensionPort alloc] init];
}

- (void)submitActivationForExtension:(NSString *)identifier
                             delegate:(id<OSSystemExtensionRequestDelegate>)delegate
                                queue:(dispatch_queue_t)queue {
    OSSystemExtensionRequest *request =
        [OSSystemExtensionRequest activationRequestForExtension:identifier queue:queue];
    // The cast is the seam's one untyped step, and it is checked here rather than in the protocol:
    // a gate holds an `id` it does not have to make conform, and the object that reaches Apple's
    // class is this file's controller, which does.
    request.delegate = delegate;
    [[OSSystemExtensionManager sharedManager] submitRequest:request];
}

@end
