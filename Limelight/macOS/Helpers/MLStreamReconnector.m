//
//  MLStreamReconnector.m
//  P2-2 退避状态机实现。契约与取舍见同名 .h。
//

#import "MLStreamReconnector.h"

@interface MLStreamReconnector ()
@property (atomic) NSUInteger attemptCount;
@property (atomic, readwrite) BOOL hostConfirmedGone;
@property (atomic, readwrite) BOOL hasPendingAttempt;
@property (nonatomic) uint64_t startupGraceMs;
@property (atomic, copy, nullable) void (^pendingBegin)(MLReconnectTrigger, NSUInteger, NSString *);
@property (atomic, copy, nullable) NSString *pendingReason;
@property (atomic) MLReconnectTrigger pendingTrigger;
@property (nonatomic, strong, nullable) NSTimer *scheduledTimer;
@end

@implementation MLStreamReconnector

- (instancetype)init {
    self = [super init];
    if (self) {
        _maxAttempts = 3;
        _backoffSeconds = @[@1, @3, @9];
        _startupGraceMs = 30000;
        _attemptCount = 0;
        _hostConfirmedGone = NO;
        _hasPendingAttempt = NO;
        _pendingTrigger = 0;
    }
    return self;
}

- (void)dealloc {
    [self invalidateTimer];
}

- (void)invalidateTimer {
    if (self.scheduledTimer) {
        [self.scheduledTimer invalidate];
        self.scheduledTimer = nil;
    }
    self.hasPendingAttempt = NO;
}

- (void)clearPendingWork {
    self.pendingBegin = nil;
    self.pendingReason = nil;
    self.pendingTrigger = 0;
}

- (BOOL)requestReconnectFromTrigger:(MLReconnectTrigger)trigger
                         withReason:(NSString *)reason
                     startupElapsedMs:(uint64_t)startupElapsedMs
                      shouldReconnect:(BOOL (^)(void))shouldReconnect
                    beginReconnectNow:(void (^)(MLReconnectTrigger, NSUInteger, NSString *))beginReconnectNow {
    NSAssert([NSThread isMainThread], @"MLStreamReconnector must run on main thread");

    if (self.hostConfirmedGone) {
        return NO;
    }
    if (shouldReconnect && !shouldReconnect()) {
        return NO;
    }

    if (self.scheduledTimer) {
        // Already counting down: coalesce. The latest trigger + reason wins so the
        // diagnostics name the condition that is still true, not the first one seen.
        self.pendingTrigger = trigger;
        self.pendingReason = reason;
        if (beginReconnectNow) {
            self.pendingBegin = [beginReconnectNow copy];
        }
        return YES;
    }

    if (self.attemptCount >= self.maxAttempts) {
        return NO;
    }

    // A stall inside the first grace window is a normal cold start, not a lost
    // connection; it must not spend budget that a real drop will need.
    BOOL isStall = (trigger == MLReconnectTriggerPayloadStall ||
                    trigger == MLReconnectTriggerNoFrameStall);
    if (isStall && startupElapsedMs < self.startupGraceMs) {
        return NO;
    }

    NSUInteger nextAttempt = self.attemptCount + 1;
    NSUInteger idx = MIN(nextAttempt - 1, self.backoffSeconds.count - 1);
    NSTimeInterval delay = [self.backoffSeconds[idx] doubleValue];
    self.attemptCount = nextAttempt;
    self.pendingTrigger = trigger;
    self.pendingReason = reason;
    self.pendingBegin = beginReconnectNow ? [beginReconnectNow copy] : nil;

    // Common modes: the stream window spends most of its life in a fullscreen
    // space, and a default-mode timer stops during menu tracking. The stats
    // timer already uses the same mode for the same reason.
    self.scheduledTimer = [NSTimer timerWithTimeInterval:delay
                                                  target:self
                                                selector:@selector(timerFired:)
                                                userInfo:nil
                                                 repeats:NO];
    [[NSRunLoop mainRunLoop] addTimer:self.scheduledTimer forMode:NSRunLoopCommonModes];
    self.hasPendingAttempt = YES;
    return YES;
}

- (void)timerFired:(NSTimer *)timer {
    (void)timer;
    NSAssert([NSThread isMainThread], @"MLStreamReconnector must run on main thread");
    [self invalidateTimer];

    if (self.hostConfirmedGone) {
        [self clearPendingWork];
        return;
    }

    void (^begin)(MLReconnectTrigger, NSUInteger, NSString *) = self.pendingBegin;
    MLReconnectTrigger firedTrigger = self.pendingTrigger;
    NSUInteger firedAttempt = self.attemptCount;
    NSString *firedReason = self.pendingReason;
    // The budget stays spent: clearing it here is how every attempt would wait
    // one second again and the ceiling would never be reached.
    [self clearPendingWork];

    if (begin) {
        begin(firedTrigger, firedAttempt, firedReason ?: @"");
    }
}

- (void)cancelWithReason:(NSString *)reason {
    (void)reason;
    NSAssert([NSThread isMainThread], @"MLStreamReconnector must run on main thread");
    [self invalidateTimer];
    [self clearPendingWork];
    self.attemptCount = 0;
    self.hostConfirmedGone = NO;
}

- (void)resetForNextAttemptWithReason:(NSString *)reason {
    (void)reason;
    NSAssert([NSThread isMainThread], @"MLStreamReconnector must run on main thread");
    [self invalidateTimer];
    [self clearPendingWork];
}

- (void)markHostConfirmedGoneWithReason:(NSString *)reason {
    NSAssert([NSThread isMainThread], @"MLStreamReconnector must run on main thread");
    (void)reason;
    self.hostConfirmedGone = YES;
    [self invalidateTimer];
    [self clearPendingWork];
}

- (void)recordSuccess {
    NSAssert([NSThread isMainThread], @"MLStreamReconnector must run on main thread");
    [self invalidateTimer];
    [self clearPendingWork];
    self.attemptCount = 0;
    self.hostConfirmedGone = NO;
}

- (BOOL)requestImmediateReconnectFromMenuWithReason:(NSString *)reason
                                  beginReconnectNow:(void (^)(MLReconnectTrigger, NSUInteger, NSString *))beginReconnectNow {
    NSAssert([NSThread isMainThread], @"MLStreamReconnector must run on main thread");
    if (!beginReconnectNow) {
        return NO;
    }
    // User intent: it burns no attempt and the ceiling is irrelevant, so a menu
    // click after the budget was spent is still a way back in.
    [self invalidateTimer];
    [self clearPendingWork];
    self.hostConfirmedGone = NO;
    beginReconnectNow(MLReconnectTriggerUserMenu, self.attemptCount, reason ?: @"user-menu");
    return YES;
}

@end
