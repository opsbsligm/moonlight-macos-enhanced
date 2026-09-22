//
//  DriverLifecycle.m
//  Moonlight
//

#import "DriverLifecycle.h"

// How many times an extension may stop on its own before this session stops trying. It is a
// count and not a window, because the only clock in this file is the caller's: a rule written as
// "three crashes in a minute" would need this file to know what minute it is, and then no run of
// it could be replayed. A caller that wants a window may build one and report a decline.
static const NSInteger MLDriverCrashBudgetDefault = 3;

NSString *MLDriverExtensionPhaseName(MLDriverExtensionPhase phase) {
    switch (phase) {
        case MLDriverExtensionPhaseNotInstalled: return @"not-installed";
        case MLDriverExtensionPhaseInstalling: return @"installing";
        case MLDriverExtensionPhaseActive: return @"active";
        case MLDriverExtensionPhaseCrashed: return @"crashed";
        case MLDriverExtensionPhaseRemoving: return @"removing";
        case MLDriverExtensionPhaseHeldBack: return @"held-back";
    }
    return @"unknown-phase";
}

NSString *MLDeviceLeaseStateName(MLDeviceLeaseState state) {
    switch (state) {
        case MLDeviceLeaseStateNone: return @"none";
        case MLDeviceLeaseStateHeld: return @"held";
        case MLDeviceLeaseStateOrphaned: return @"orphaned";
    }
    return @"unknown-lease";
}

NSString *MLDriverLifecycleStopName(MLDriverLifecycleStop stop) {
    switch (stop) {
        case MLDriverLifecycleStopNone: return @"none";
        case MLDriverLifecycleStopNeverRequested: return @"never-requested";
        case MLDriverLifecycleStopInstallUnanswered: return @"install-unanswered";
        case MLDriverLifecycleStopCrashBudgetSpent: return @"crash-budget-spent";
        case MLDriverLifecycleStopUserDeclined: return @"user-declined";
        case MLDriverLifecycleStopRemovalUnanswered: return @"removal-unanswered";
        case MLDriverLifecycleStopNotActive: return @"not-active";
        case MLDriverLifecycleStopDeviceNotLeased: return @"device-not-leased";
        case MLDriverLifecycleStopDeviceUnknown: return @"device-unknown";
    }
    return @"unknown-stop";
}

@implementation MLManagedDevice

+ (instancetype)managedDeviceWithToken:(NSString *)deviceToken {
    MLManagedDevice *device = [[MLManagedDevice alloc] init];
    device->_deviceToken = [deviceToken copy];
    return device;
}

@end

@interface MLDriverLifecycle ()
@property(nonatomic, readwrite) MLDriverExtensionPhase phase;
@property(nonatomic, readwrite) MLDriverLifecycleStop stop;
@property(nonatomic, readwrite) NSInteger crashesObserved;
@property(nonatomic, readwrite) NSInteger crashBudget;
/// token -> lease state. NSNumber rather than a dictionary of mutable devices, because the whole
/// object is replaced at every event and a nested mutable thing is where a stale answer hides.
@property(nonatomic, readonly) NSDictionary<NSString *, NSNumber *> *leases;
@end

@implementation MLDriverLifecycle

+ (instancetype)untouchedLifecycleWithCrashBudget:(NSInteger)crashBudget {
    MLDriverLifecycle *lifecycle = [[MLDriverLifecycle alloc] init];
    lifecycle.phase = MLDriverExtensionPhaseNotInstalled;
    lifecycle.stop = MLDriverLifecycleStopNeverRequested;
    lifecycle.crashesObserved = 0;
    // A budget of zero is a caller that wants no retries, and is honoured. Only a negative one
    // is nonsense, and nonsense becomes the default rather than an instant "always held back".
    lifecycle.crashBudget = crashBudget < 0 ? MLDriverCrashBudgetDefault : crashBudget;
    lifecycle->_leases = @{};
    return lifecycle;
}

- (instancetype)lifecycleByCarryingPhase:(MLDriverExtensionPhase)phase
                                    stop:(MLDriverLifecycleStop)stop
                             crashBudget:(BOOL)keepCrashes {
    MLDriverLifecycle *next = [[MLDriverLifecycle alloc] init];
    next.phase = phase;
    next.stop = stop;
    next.crashesObserved = keepCrashes ? self.crashesObserved : 0;
    next.crashBudget = self.crashBudget;
    next->_leases = [self.leases copy];
    return next;
}

/// An event that cannot happen here is refused by changing nothing. Overwriting the reason would
/// be the same mistake as letting a later failure relabel the first one: the caller would read a
/// lifecycle that reported a different problem than the one it caused.
- (instancetype)lifecycleByRefusing {
    return self;
}

- (instancetype)lifecycleByRequestingInstall {
    if (self.phase != MLDriverExtensionPhaseNotInstalled) {
        return [self lifecycleByRefusing];
    }
    return [self lifecycleByCarryingPhase:MLDriverExtensionPhaseInstalling
                                     stop:MLDriverLifecycleStopNone
                              crashBudget:YES];
}

- (instancetype)lifecycleByRecordingUserApproval {
    if (self.phase != MLDriverExtensionPhaseInstalling) {
        return [self lifecycleByRefusing];
    }
    // Approval is not activation. A lifecycle that treated the dialog closing as a loaded
    // extension would hand devices to something that is not there yet.
    return self;
}

- (instancetype)lifecycleByRecordingUserDecline {
    if (self.phase != MLDriverExtensionPhaseInstalling) {
        return [self lifecycleByRefusing];
    }
    // A decline leaves nothing installed, so the honest phase is not-installed and not a phase of
    // its own: the system state is exactly what it was before the ask. What the decline changes is
    // the reason, and the reason is what keeps this session from asking again by itself. The
    // player may still press the button; a session that pressed it for them is the thing refused.
    return [self lifecycleByCarryingPhase:MLDriverExtensionPhaseNotInstalled
                                     stop:MLDriverLifecycleStopUserDeclined
                              crashBudget:YES];
}

- (instancetype)lifecycleByRecordingActivation {
    if (self.phase == MLDriverExtensionPhaseActive) {
        return self;
    }
    if (self.phase != MLDriverExtensionPhaseInstalling) {
        return [self lifecycleByRefusing];
    }
    return [self lifecycleByCarryingPhase:MLDriverExtensionPhaseActive
                                     stop:MLDriverLifecycleStopNone
                              crashBudget:YES];
}

- (instancetype)lifecycleByRecordingCrash {
    // From `crashed` as well: the system relaunches an extension it did not stop, so the second
    // death arrives while the phase still says crashed. A crash that could not be recorded twice
    // is a crash budget that never empties, which is the difference between giving up and
    // restarting a broken driver for the rest of the player's session.
    if (self.phase != MLDriverExtensionPhaseActive &&
        self.phase != MLDriverExtensionPhaseInstalling &&
        self.phase != MLDriverExtensionPhaseCrashed) {
        return [self lifecycleByRefusing];
    }
    const NSInteger seen = self.crashesObserved + 1;
    if (seen >= self.crashBudget) {
        MLDriverLifecycle *spent =
            [self lifecycleByCarryingPhase:MLDriverExtensionPhaseHeldBack
                                      stop:MLDriverLifecycleStopCrashBudgetSpent
                               crashBudget:YES];
        spent.crashesObserved = seen;
        return [spent lifecycleByOrphaningLeases];
    }
    MLDriverLifecycle *crashed =
        [self lifecycleByCarryingPhase:MLDriverExtensionPhaseCrashed
                                  stop:MLDriverLifecycleStopNone
                           crashBudget:YES];
    crashed.crashesObserved = seen;
    return [crashed lifecycleByOrphaningLeases];
}

/// A crash does not give anything back. A lease that became free when its holder died would let
/// the next session attach to a device the dying extension may still have configured; those
/// leases expire, which is a different road to the same place with a different name in the log.
- (instancetype)lifecycleByOrphaningLeases {
    MLDriverLifecycle *orphaned =
        [self lifecycleByCarryingPhase:self.phase stop:self.stop crashBudget:YES];
    orphaned.crashesObserved = self.crashesObserved;
    NSMutableDictionary *leases = [self.leases mutableCopy];
    for (NSString *token in leases) {
        if ([leases[token] integerValue] == MLDeviceLeaseStateHeld) {
            leases[token] = @(MLDeviceLeaseStateOrphaned);
        }
    }
    orphaned->_leases = [leases copy];
    return orphaned;
}

- (instancetype)lifecycleByRequestingRemoval {
    // Not while an install is outstanding: two system requests at once is a race the caller
    // would lose without either phase being able to say which one it lost.
    if (self.phase == MLDriverExtensionPhaseInstalling ||
        self.phase == MLDriverExtensionPhaseRemoving) {
        return [self lifecycleByRefusing];
    }
    return [self lifecycleByCarryingPhase:MLDriverExtensionPhaseRemoving
                                     stop:MLDriverLifecycleStopNone
                              crashBudget:YES];
}

- (instancetype)lifecycleByRecordingRemovalCompleted {
    if (self.phase != MLDriverExtensionPhaseRemoving) {
        return [self lifecycleByRefusing];
    }
    // A fresh install is a fresh crash budget: the previous extension's history is not this
    // one's guilt. Every lease is gone with the extension that held it.
    MLDriverLifecycle *removed =
        [self lifecycleByCarryingPhase:MLDriverExtensionPhaseNotInstalled
                                  stop:MLDriverLifecycleStopNeverRequested
                           crashBudget:NO];
    removed->_leases = @{};
    return removed;
}

- (instancetype)lifecycleByRecordingInstallTimeout {
    if (self.phase != MLDriverExtensionPhaseInstalling) {
        return [self lifecycleByRefusing];
    }
    // The install never finished, so the honest phase is the one that says there is nothing to
    // use. Staying in `installing` is the failure this transition exists to prevent: a settings
    // page that keeps saying "installing" forever is a page that never tells the player to retry.
    return [self lifecycleByCarryingPhase:MLDriverExtensionPhaseNotInstalled
                                     stop:MLDriverLifecycleStopInstallUnanswered
                              crashBudget:YES];
}

- (instancetype)lifecycleByRecordingRemovalTimeout {
    if (self.phase != MLDriverExtensionPhaseRemoving) {
        return [self lifecycleByRefusing];
    }
    // The other direction, and it does not get the same treatment: an unanswered *removal* means
    // the extension is probably still there, and reporting `not-installed` would be a claim about
    // the system that no observation supports. The phase stays where the request left it.
    return [self lifecycleByCarryingPhase:MLDriverExtensionPhaseRemoving
                                     stop:MLDriverLifecycleStopRemovalUnanswered
                              crashBudget:YES];
}

- (instancetype)lifecycleByNoticingDevice:(MLManagedDevice *)device {
    if (device.deviceToken.length == 0) {
        return [self lifecycleByRefusing];
    }
    // A device that came back is a device that went away, and a lease belongs to the departure
    // that has already happened. Inheriting it is the hot-plug bug: the second arrival would be
    // usable because the first one was, which is a claim about a device nobody has re-attached.
    MLDriverLifecycle *noticed =
        [self lifecycleByCarryingPhase:self.phase stop:self.stop crashBudget:YES];
    NSMutableDictionary *leases = [self.leases mutableCopy];
    leases[device.deviceToken] = @(MLDeviceLeaseStateNone);
    noticed->_leases = [leases copy];
    return noticed;
}

- (instancetype)lifecycleByNoticingDeviceRemoved:(MLManagedDevice *)device {
    if (self.leases[device.deviceToken] == nil) {
        return [self lifecycleByRefusing];
    }
    MLDriverLifecycle *noticed =
        [self lifecycleByCarryingPhase:self.phase stop:self.stop crashBudget:YES];
    NSMutableDictionary *leases = [self.leases mutableCopy];
    [leases removeObjectForKey:device.deviceToken];
    noticed->_leases = [leases copy];
    return noticed;
}

- (instancetype)lifecycleByLeasingDevice:(MLManagedDevice *)device {
    if (self.phase != MLDriverExtensionPhaseActive) {
        return [self lifecycleByRefusing];
    }
    NSNumber *current = self.leases[device.deviceToken];
    if (current == nil || [current integerValue] != MLDeviceLeaseStateNone) {
        return [self lifecycleByRefusing];
    }
    MLDriverLifecycle *leased =
        [self lifecycleByCarryingPhase:self.phase stop:self.stop crashBudget:YES];
    NSMutableDictionary *leases = [self.leases mutableCopy];
    leases[device.deviceToken] = @(MLDeviceLeaseStateHeld);
    leased->_leases = [leases copy];
    return leased;
}

- (instancetype)lifecycleByReturningDevice:(MLManagedDevice *)device {
    NSNumber *current = self.leases[device.deviceToken];
    // An orphaned lease cannot be returned. The thing that would return it is the extension that
    // died, and a model that accepted a return from it would be accepting a report from a
    // process that is gone.
    if (current == nil || [current integerValue] != MLDeviceLeaseStateHeld) {
        return [self lifecycleByRefusing];
    }
    MLDriverLifecycle *returned =
        [self lifecycleByCarryingPhase:self.phase stop:self.stop crashBudget:YES];
    NSMutableDictionary *leases = [self.leases mutableCopy];
    leases[device.deviceToken] = @(MLDeviceLeaseStateNone);
    returned->_leases = [leases copy];
    return returned;
}

- (instancetype)lifecycleByExpiringLeaseForDevice:(MLManagedDevice *)device {
    NSNumber *current = self.leases[device.deviceToken];
    if (current == nil || [current integerValue] == MLDeviceLeaseStateNone) {
        return [self lifecycleByRefusing];
    }
    MLDriverLifecycle *expired =
        [self lifecycleByCarryingPhase:self.phase stop:self.stop crashBudget:YES];
    NSMutableDictionary *leases = [self.leases mutableCopy];
    leases[device.deviceToken] = @(MLDeviceLeaseStateNone);
    expired->_leases = [leases copy];
    return expired;
}

- (MLDeviceLeaseState)leaseStateForDeviceToken:(NSString *)deviceToken {
    return (MLDeviceLeaseState)[self.leases[deviceToken] integerValue];
}

- (NSArray<NSString *> *)deviceTokens {
    return self.leases.allKeys;
}

- (BOOL)mayAttemptInstall {
    // Not-installed is the only place a request makes sense, and an unanswered request may be
    // asked again: the player can press the button a second time. A held-back session cannot be
    // argued out of holding back, which is the whole reason it is a phase.
    return self.phase == MLDriverExtensionPhaseNotInstalled &&
           self.stop != MLDriverLifecycleStopUserDeclined;
}

- (BOOL)mayHandOverDevices {
    return self.phase == MLDriverExtensionPhaseActive &&
           self.stop == MLDriverLifecycleStopNone;
}

- (BOOL)mayUseDeviceToken:(NSString *)deviceToken {
    // Both facts at once: a loaded extension and a lease this lifecycle handed out. Neither on
    // its own is enough, and a check that asked only one of them is how a device reaches a host
    // that another session is still holding.
    return [self mayHandOverDevices] &&
           self.leases[deviceToken] != nil &&
           [self.leases[deviceToken] integerValue] == MLDeviceLeaseStateHeld;
}

- (NSString *)auditLine {
    NSInteger held = 0;
    NSInteger orphaned = 0;
    for (NSNumber *state in self.leases.allValues) {
        held += [state integerValue] == MLDeviceLeaseStateHeld;
        orphaned += [state integerValue] == MLDeviceLeaseStateOrphaned;
    }
    return [NSString stringWithFormat:
            @"driver lifecycle: phase=%@ stop=%@ crashes=%ld/%ld leases=%ld held, %ld orphaned",
            MLDriverExtensionPhaseName(self.phase), MLDriverLifecycleStopName(self.stop),
            (long)self.crashesObserved, (long)self.crashBudget, (long)held, (long)orphaned];
}

@end
