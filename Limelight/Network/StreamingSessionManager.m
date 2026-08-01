//
//  StreamingSessionManager.m
//  Limelight
//
//  Created by SkyHua on 2025-01-20.
//
//  v2.0 — Thread-safe: all state access guarded by NSLock.
//

#import "StreamingSessionManager.h"

@interface StreamingSession : NSObject

@property (nonatomic, copy) NSString *hostUUID;
@property (nonatomic, copy, nullable) NSString *appId;
@property (nonatomic, copy, nullable) NSString *appName;
@property (nonatomic, weak, nullable) NSWindowController *windowController;
@property (nonatomic) StreamingState state;
@property (nonatomic) double latency;
@property (nonatomic, copy, nullable) NSString *resolution;
@property (nonatomic) NSInteger framerate;
@property (nonatomic) double quality;

@end

@implementation StreamingSession
@end

@interface StreamingSessionManager ()

@property (nonatomic, readwrite) StreamingState state;
@property (nonatomic, readwrite, nullable) NSString *activeHostUUID;
@property (nonatomic, readwrite, nullable) NSString *activeAppId;
@property (nonatomic, readwrite, nullable) NSString *activeAppName;
@property (nonatomic, strong) NSMutableDictionary<NSString *, StreamingSession *> *sessions;
@property (nonatomic, strong) NSLock *stateLock;

@end

@implementation StreamingSessionManager

+ (instancetype)shared {
    static StreamingSessionManager *instance = nil;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        instance = [[StreamingSessionManager alloc] init];
    });
    return instance;
}

- (instancetype)init {
    self = [super init];
    if (self) {
        _state = StreamingStateIdle;
        _sessions = [NSMutableDictionary dictionary];
        _stateLock = [[NSLock alloc] init];
    }
    return self;
}

#pragma mark - Private lock helpers

- (void)lock {
    [_stateLock lock];
}

- (void)unlock {
    [_stateLock unlock];
}

- (StreamingSession *)lockedSessionForHost:(NSString *)hostUUID {
    return _sessions[hostUUID];
}

- (void)postStateChangeNotificationForHostLocked:(NSString *)hostUUID
                                          session:(nullable StreamingSession *)session {
    NSMutableDictionary *userInfo = [NSMutableDictionary dictionary];
    userInfo[@"state"] = @(session ? session.state : StreamingStateIdle);
    userInfo[@"hostUUID"] = hostUUID;
    if (session.appId) userInfo[@"appId"] = session.appId;
    if (session.appName) userInfo[@"appName"] = session.appName;

    // Dispatch on main thread to ensure UI updates are safe.
    // Capture userInfo (immutable copy) and self; do not touch session outside lock.
    dispatch_async(dispatch_get_main_queue(), ^{
        [[NSNotificationCenter defaultCenter] postNotificationName:@"StreamingStateChanged"
                                                            object:self
                                                          userInfo:userInfo];
    });
}

#pragma mark - Public API

- (BOOL)canStartStreamForHost:(NSString *)hostUUID {
    [self lock];
    @try {
        StreamingSession *session = [self lockedSessionForHost:hostUUID];
        return (session == nil || session.state == StreamingStateIdle || session.state == StreamingStateDisconnecting);
    } @finally {
        [self unlock];
    }
}

- (void)startStreamingWithHost:(NSString *)hostUUID
                         appId:(NSString *)appId
                       appName:(NSString *)appName
            windowController:(NSWindowController *)windowController {

    NSString *previousActiveHostUUID = nil;
    [self lock];
    @try {
        // H3/M2 fix: refuse to start if a streaming session is already active
        // for this host (prevents orphaning the previous windowController).
        StreamingSession *session = [self lockedSessionForHost:hostUUID];
        if (!session) {
            session = [[StreamingSession alloc] init];
            session.hostUUID = hostUUID;
            _sessions[hostUUID] = session;
        }

        // Capture the previously active host (if different) so we can disconnect
        // it outside the lock to avoid orphaning its session/windowController.
        if (_activeHostUUID && ![_activeHostUUID isEqualToString:hostUUID]) {
            previousActiveHostUUID = [_activeHostUUID copy];
        }

        session.appId = appId;
        session.appName = appName;
        session.windowController = windowController;
        session.state = StreamingStateStreaming;
        session.latency = 0;
        session.resolution = nil;
        session.framerate = 0;
        session.quality = 1.0;

        _activeHostUUID = hostUUID;
        _activeAppId = appId;
        _activeAppName = appName;
        self.streamWindowController = windowController;
        _state = StreamingStateStreaming;

        [self postStateChangeNotificationForHostLocked:hostUUID session:session];
    } @finally {
        [self unlock];
    }

    // Disconnect the previously active host outside the lock to prevent
    // orphaning its session/windowController. This is done after releasing
    // the lock because disconnectHost: acquires the lock itself, and calling
    // it while holding the lock would cause a deadlock.
    if (previousActiveHostUUID) {
        [self disconnectHost:previousActiveHostUUID];
    }
}

- (void)didDisconnect {
    [self lock];
    @try {
        if (_activeHostUUID) {
            NSString *hostUUID = [_activeHostUUID copy];
            StreamingSession *session = [self lockedSessionForHost:hostUUID];
            if (session) {
                session.state = StreamingStateIdle;
                session.windowController = nil;
                session.appId = nil;
                session.appName = nil;
            }
            _activeHostUUID = nil;
            _activeAppId = nil;
            _activeAppName = nil;
            self.streamWindowController = nil;
            _state = StreamingStateIdle;

            [self postStateChangeNotificationForHostLocked:hostUUID session:session];
        } else if (_state != StreamingStateIdle) {
            // M1 fix: even without activeHostUUID, force state back to Idle
            // so the state machine can always converge.
            _state = StreamingStateIdle;
            self.streamWindowController = nil;
        }
    } @finally {
        [self unlock];
    }
}

- (BOOL)isStreamingHost:(NSString *)hostUUID {
    [self lock];
    @try {
        StreamingSession *session = [self lockedSessionForHost:hostUUID];
        return session != nil && session.state == StreamingStateStreaming;
    } @finally {
        [self unlock];
    }
}

- (nullable NSString *)appNameForHost:(NSString *)hostUUID {
    [self lock];
    @try {
        StreamingSession *session = [self lockedSessionForHost:hostUUID];
        return session.appName;
    } @finally {
        [self unlock];
    }
}

- (void)didDisconnectForHost:(NSString *)hostUUID {
    [self lock];
    @try {
        StreamingSession *session = [self lockedSessionForHost:hostUUID];
        if (session) {
            session.state = StreamingStateIdle;
            session.windowController = nil;
            session.appId = nil;
            session.appName = nil;
            // Design intent: the session entry is intentionally kept in _sessions
            // (state = Idle) rather than removed. canStartStreamForHost: reuses
            // Idle sessions for the same host, so removing them here would break
            // that reuse path and cause a new session object to be allocated on
            // every reconnect. The dictionary grows only with the number of
            // distinct hosts, which is bounded by the host list, not by session
            // count, so unbounded growth is not a concern in practice.
        }

        if ([_activeHostUUID isEqualToString:hostUUID]) {
            _activeHostUUID = nil;
            _activeAppId = nil;
            _activeAppName = nil;
            self.streamWindowController = nil;
            _state = StreamingStateIdle;
        }

        [self postStateChangeNotificationForHostLocked:hostUUID session:session];
    } @finally {
        [self unlock];
    }
}

- (void)focusStreamWindow {
    NSWindowController *controller = nil;
    [self lock];
    @try {
        if (_activeHostUUID) {
            StreamingSession *session = [self lockedSessionForHost:_activeHostUUID];
            controller = session.windowController; // weak -> strong local
        }
    } @finally {
        [self unlock];
    }
    // L5 fix: do window operations outside the lock, with a strong local reference.
    if (controller && controller.window) {
        NSWindow *window = controller.window;
        [window makeKeyAndOrderFront:nil];
        [NSApp activateIgnoringOtherApps:YES];
        if (window.isMiniaturized) {
            [window deminiaturize:nil];
        }
    }
}

- (void)focusStreamWindowForHost:(NSString *)hostUUID {
    NSWindowController *controller = nil;
    [self lock];
    @try {
        StreamingSession *session = [self lockedSessionForHost:hostUUID];
        controller = session.windowController;
    } @finally {
        [self unlock];
    }
    if (controller && controller.window) {
        NSWindow *window = controller.window;
        [window makeKeyAndOrderFront:nil];
        [NSApp activateIgnoringOtherApps:YES];
        if (window.isMiniaturized) {
            [window deminiaturize:nil];
        }
    }
}

- (void)disconnect {
    NSString *hostUUID = nil;
    BOOL needsFallback = NO;
    [self lock];
    @try {
        if (_activeHostUUID) {
            hostUUID = [_activeHostUUID copy];
        } else if (_state != StreamingStateIdle) {
            needsFallback = YES;
        }
    } @finally {
        [self unlock];
    }

    if (hostUUID) {
        [self disconnectHost:hostUUID];
    } else if (needsFallback) {
        [self didDisconnect];
    }
}

- (void)disconnectHost:(NSString *)hostUUID {
    BOOL hasController = NO;
    [self lock];
    @try {
        StreamingSession *session = [self lockedSessionForHost:hostUUID];
        hasController = (session.windowController != nil);
    } @finally {
        [self unlock];
    }

    if (hasController) {
        NSDictionary *userInfo = @{ @"hostUUID": hostUUID };
        [[NSNotificationCenter defaultCenter] postNotificationName:@"StreamingSessionRequestDisconnect"
                                                            object:nil
                                                          userInfo:userInfo];
    } else {
        [self didDisconnectForHost:hostUUID];
    }
}

- (void)requestDisconnectWithQuitApp:(BOOL)quitApp {
    NSString *hostUUID = nil;
    BOOL needsFallback = NO;
    [self lock];
    @try {
        if (_activeHostUUID) {
            hostUUID = [_activeHostUUID copy];
        } else if (_state != StreamingStateIdle) {
            needsFallback = YES;
        }
    } @finally {
        [self unlock];
    }

    if (hostUUID) {
        [self requestDisconnectWithQuitApp:quitApp hostUUID:hostUUID];
    } else if (needsFallback) {
        [self didDisconnect];
    }
}

- (void)requestDisconnectWithQuitApp:(BOOL)quitApp hostUUID:(NSString *)hostUUID {
    BOOL hasController = NO;
    [self lock];
    @try {
        StreamingSession *session = [self lockedSessionForHost:hostUUID];
        hasController = (session.windowController != nil);
    } @finally {
        [self unlock];
    }

    if (hasController) {
        NSDictionary *userInfo = @{ @"quitApp": @(quitApp), @"hostUUID": hostUUID };
        [[NSNotificationCenter defaultCenter] postNotificationName:@"StreamingSessionRequestDisconnect"
                                                            object:nil
                                                          userInfo:userInfo];
    } else {
        [self didDisconnectForHost:hostUUID];
    }
}

@end
