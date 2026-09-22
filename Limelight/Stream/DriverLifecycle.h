//
//  DriverLifecycle.h
//  Moonlight
//
//  Whether a driver extension may be relied on right now, and who is holding a device.
//
//  Stage 3 of docs/usb-redirection-design.md needs a DriverKit extension, and an extension that
//  is not loaded is not a feature: it is a settings page that lies. Everything in here exists so
//  "we ship device passthrough" can only be said when a loadable extension and a free slot in it
//  were both observed, and so that a crash leaves something recoverable behind.
//
//  Two facts are tracked separately, and keeping them separate is the point. An extension can be
//  installed and still be holding a device it was never told to give back; a device can be free
//  while no extension is loaded at all. A model that merged them would report "nothing is
//  attached" as "nothing can be attached", which is how an uninstall stops being reversible.
//
//  Nothing here reads a clock. A timeout is a fact somebody with a timer reports; a state
//  machine that also told the time could not be replayed, and a test run whose assertions depend
//  on when they ran is not a test of the sequence at all.
//

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Where the extension stands. `installing` is a real phase rather than a boolean, because an
/// install that never finishes has to end somewhere, and the place it ends is a claim about the
/// system that a log line has to be able to make.
typedef NS_ENUM(NSInteger, MLDriverExtensionPhase) {
    MLDriverExtensionPhaseNotInstalled = 0,
    MLDriverExtensionPhaseInstalling = 1,
    MLDriverExtensionPhaseActive = 2,
    /// The extension stopped in the middle of holding something. Distinct from not-installed:
    /// the request is still registered, and whether it may be retried is the question this file
    /// is for.
    MLDriverExtensionPhaseCrashed = 3,
    MLDriverExtensionPhaseRemoving = 4,
    /// No further attempt will be made in this session. Reached by a crash budget spent or an
    /// install that timed out, and the reason is reported rather than folded into "failed".
    MLDriverExtensionPhaseHeldBack = 5,
};

/// Who holds a device that was handed to the extension. A lease is the only thing that can make
/// a device available, it is taken by exactly one event, and it expires whether it was given
/// back or not.
typedef NS_ENUM(NSInteger, MLDeviceLeaseState) {
    MLDeviceLeaseStateNone = 0,
    MLDeviceLeaseStateHeld = 1,
    /// The extension died while holding it. The device is not available: a lease that became
    /// free the moment its holder crashed would let the next session attach to a device the
    /// dying extension may still have configured.
    MLDeviceLeaseStateOrphaned = 2,
};

typedef NS_ENUM(NSInteger, MLDriverLifecycleStop) {
    MLDriverLifecycleStopNone = 0,
    MLDriverLifecycleStopNeverRequested = 1,
    MLDriverLifecycleStopInstallUnanswered = 2,
    MLDriverLifecycleStopCrashBudgetSpent = 3,
    MLDriverLifecycleStopUserDeclined = 4,
    MLDriverLifecycleStopRemovalUnanswered = 5,
    MLDriverLifecycleStopNotActive = 6,
    MLDriverLifecycleStopDeviceNotLeased = 7,
    /// The host asked about a device this lifecycle has never seen. Answering from a stale
    /// table is the hot-plug bug this file exists to prevent.
    MLDriverLifecycleStopDeviceUnknown = 8,
};

FOUNDATION_EXPORT NSString *MLDriverExtensionPhaseName(MLDriverExtensionPhase phase);
FOUNDATION_EXPORT NSString *MLDeviceLeaseStateName(MLDeviceLeaseState state);
FOUNDATION_EXPORT NSString *MLDriverLifecycleStopName(MLDriverLifecycleStop stop);

/// One device, named the way Stage 1 names it: the audit token, which is a digest and can be
/// written down. A lifecycle that keyed devices by product name would be a lifecycle that can
/// name a user's hardware in a log.
@interface MLManagedDevice : NSObject
@property(nonatomic, readonly, copy) NSString *deviceToken;
+ (instancetype)managedDeviceWithToken:(NSString *)deviceToken;
@end

/// The lifecycle plus the leases, immutable and returned fresh from every event, for the reason
/// the session class already gives: a mutable lifecycle lets one stale answer be read twice.
@interface MLDriverLifecycle : NSObject
@property(nonatomic, readonly) MLDriverExtensionPhase phase;
@property(nonatomic, readonly) MLDriverLifecycleStop stop;
/// Crashes survived so far. The budget is a count rather than a timestamp because the only
/// clock in this file is the caller's.
@property(nonatomic, readonly) NSInteger crashesObserved;
@property(nonatomic, readonly) NSInteger crashBudget;
@property(nonatomic, readonly, copy) NSArray<NSString *> *deviceTokens;

/// A lifecycle nobody asked about yet: not installed, nothing held, nothing allowed.
+ (instancetype)untouchedLifecycleWithCrashBudget:(NSInteger)crashBudget;

/// Records an event. Each returns a new lifecycle, and one that is held back stays held back.
- (instancetype)lifecycleByRequestingInstall;
- (instancetype)lifecycleByRecordingUserApproval;
- (instancetype)lifecycleByRecordingUserDecline;
- (instancetype)lifecycleByRecordingActivation;
- (instancetype)lifecycleByRecordingCrash;
- (instancetype)lifecycleByRequestingRemoval;
- (instancetype)lifecycleByRecordingRemovalCompleted;
/// The install or removal was asked for and no answer came. The caller owns the timer.
- (instancetype)lifecycleByRecordingInstallTimeout;
- (instancetype)lifecycleByRecordingRemovalTimeout;

/// A device plugged in. A second arrival of the same token is a new event and starts a new
/// lease: the availability of a device that was replugged is not inherited from the session
/// that last saw it.
- (instancetype)lifecycleByNoticingDevice:(MLManagedDevice *)device;
- (instancetype)lifecycleByNoticingDeviceRemoved:(MLManagedDevice *)device;
/// The extension took the device. Only this event makes a device usable.
- (instancetype)lifecycleByLeasingDevice:(MLManagedDevice *)device;
/// The extension let go, cleanly.
- (instancetype)lifecycleByReturningDevice:(MLManagedDevice *)device;
/// A lease that was never returned when the clock ran out. Same outcome as a return, reached by
/// a different road, and named differently so a log can tell an honest release from a timeout.
- (instancetype)lifecycleByExpiringLeaseForDevice:(MLManagedDevice *)device;

- (MLDeviceLeaseState)leaseStateForDeviceToken:(NSString *)deviceToken;
- (BOOL)mayAttemptInstall;
- (BOOL)mayHandOverDevices;
- (BOOL)mayUseDeviceToken:(NSString *)deviceToken;
/// One line, safe to log. It says which phase, which stop, how many crashes were seen, and how
/// many leases are held -- and never a device name.
@property(nonatomic, readonly, copy) NSString *auditLine;
@end

NS_ASSUME_NONNULL_END
