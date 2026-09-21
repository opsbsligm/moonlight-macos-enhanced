//
//  InputDiagnosticsLedger.m
//  Moonlight for macOS
//

#import "InputDiagnosticsLedger.h"

@implementation InputDiagnosticsSummary

- (id)copyWithZone:(NSZone *_Nullable)zone {
    (void)zone;
    InputDiagnosticsSummary *copy = [[InputDiagnosticsSummary alloc] init];
    copy.startedAt = self.startedAt;
    copy.streamsStarted = self.streamsStarted;
    copy.streamsFinished = self.streamsFinished;
    copy.streamInProgress = self.streamInProgress;
    copy.streamStartedAt = self.streamStartedAt;
    copy.streamEndedAt = self.streamEndedAt;
    copy.streamEndReason = self.streamEndReason;
    copy.mouseStrategyName = self.mouseStrategyName;
    copy.mouseStrategyStoredValue = self.mouseStrategyStoredValue;
    copy.coreHIDAllowedByStrategy = self.coreHIDAllowedByStrategy;
    copy.coreHIDWantedToStart = self.coreHIDWantedToStart;
    copy.coreHIDDeliveredMovement = self.coreHIDDeliveredMovement;
    copy.coreHIDFailedAtRuntime = self.coreHIDFailedAtRuntime;
    copy.coreHIDFailureReason = self.coreHIDFailureReason;
    copy.lastMotionSource = self.lastMotionSource;
    copy.lastMotionSourceAt = self.lastMotionSourceAt;
    copy.collectionEnabledForLastStream = self.collectionEnabledForLastStream;
    copy.mouseMoveEvents = self.mouseMoveEvents;
    copy.nonZeroRelativeEvents = self.nonZeroRelativeEvents;
    copy.relativeDispatches = self.relativeDispatches;
    copy.absoluteDispatches = self.absoluteDispatches;
    copy.absoluteDuplicateSkips = self.absoluteDuplicateSkips;
    copy.coreHIDRawEvents = self.coreHIDRawEvents;
    copy.coreHIDDispatches = self.coreHIDDispatches;
    copy.suppressedRelativeEvents = self.suppressedRelativeEvents;
    copy.rawRelativeDeltaX = self.rawRelativeDeltaX;
    copy.rawRelativeDeltaY = self.rawRelativeDeltaY;
    copy.sentRelativeDeltaX = self.sentRelativeDeltaX;
    copy.sentRelativeDeltaY = self.sentRelativeDeltaY;
    copy.captureArmed = self.captureArmed;
    copy.captureSkipped = self.captureSkipped;
    copy.captureReleased = self.captureReleased;
    copy.rearms = self.rearms;
    copy.rearmSkips = self.rearmSkips;
    copy.rearmDeferred = self.rearmDeferred;
    copy.relativeMotionBySource = self.relativeMotionBySource;
    copy.absoluteMotionBySource = self.absoluteMotionBySource;
    copy.captureSkipTopReasons = self.captureSkipTopReasons;
    copy.rearmTopReasons = self.rearmTopReasons;
    copy.rearmSkipTopReasons = self.rearmSkipTopReasons;
    copy.rearmDeferredTopReasons = self.rearmDeferredTopReasons;
    return copy;
}

@end

@implementation InputDiagnosticsLedger {
    InputDiagnosticsSummary *_summary;
    NSLock *_lock;
}

+ (instancetype)sharedLedger {
    static InputDiagnosticsLedger *ledger = nil;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        ledger = [[InputDiagnosticsLedger alloc] init];
    });
    return ledger;
}

- (instancetype)init {
    self = [super init];
    if (self) {
        _lock = [[NSLock alloc] init];
        _summary = [[InputDiagnosticsSummary alloc] init];
        _summary.startedAt = [NSDate date];
        // -1, not 0: 0 is the retired strategy number, and a report that printed 0 for a
        // session that never resolved a driver would name a mode this build removed.
        _summary.mouseStrategyStoredValue = -1;
    }
    return self;
}

- (InputDiagnosticsSummary *)summary {
    [_lock lock];
    InputDiagnosticsSummary *snapshot = [_summary copy];
    [_lock unlock];
    return snapshot;
}

- (void)updateSummary:(void (^)(InputDiagnosticsSummary *summary))update {
    if (update == nil) {
        return;
    }
    [_lock lock];
    update(_summary);
    [_lock unlock];
}

- (void)noteStreamStarted {
    [_lock lock];
    _summary.streamsStarted += 1;
    _summary.streamInProgress = YES;
    _summary.streamStartedAt = [NSDate date];
    _summary.streamEndedAt = nil;
    _summary.streamEndReason = nil;
    _summary.lastMotionSource = nil;
    _summary.lastMotionSourceAt = nil;
    _summary.coreHIDWantedToStart = NO;
    _summary.coreHIDDeliveredMovement = NO;
    _summary.coreHIDFailedAtRuntime = NO;
    _summary.coreHIDFailureReason = nil;
    // The strategy is deliberately not cleared. The code that decides it runs once per
    // session and not in step with this method, and a report missing the one line that says
    // which driver was chosen is worse than one carrying the strategy a moment too long.
    _summary.collectionEnabledForLastStream = NO;
    _summary.mouseMoveEvents = 0;
    _summary.nonZeroRelativeEvents = 0;
    _summary.relativeDispatches = 0;
    _summary.absoluteDispatches = 0;
    _summary.absoluteDuplicateSkips = 0;
    _summary.coreHIDRawEvents = 0;
    _summary.coreHIDDispatches = 0;
    _summary.suppressedRelativeEvents = 0;
    _summary.rawRelativeDeltaX = 0;
    _summary.rawRelativeDeltaY = 0;
    _summary.sentRelativeDeltaX = 0;
    _summary.sentRelativeDeltaY = 0;
    _summary.captureArmed = 0;
    _summary.captureSkipped = 0;
    _summary.captureReleased = 0;
    _summary.rearms = 0;
    _summary.rearmSkips = 0;
    _summary.rearmDeferred = 0;
    _summary.relativeMotionBySource = nil;
    _summary.absoluteMotionBySource = nil;
    _summary.captureSkipTopReasons = nil;
    _summary.rearmTopReasons = nil;
    _summary.rearmSkipTopReasons = nil;
    _summary.rearmDeferredTopReasons = nil;
    [_lock unlock];
}

- (void)noteStreamEndedWithReason:(NSString *_Nullable)reason {
    [_lock lock];
    // Started and never marked running: a session that ended before it started is not a
    // finished session, and counting it as one would let a report claim a session whose
    // counters belong to another.
    if (_summary.streamStartedAt != nil) {
        _summary.streamsFinished += 1;
    }
    _summary.streamInProgress = NO;
    _summary.streamEndedAt = [NSDate date];
    _summary.streamEndReason = reason.length > 0 ? [reason copy] : nil;
    [_lock unlock];
}

@end
