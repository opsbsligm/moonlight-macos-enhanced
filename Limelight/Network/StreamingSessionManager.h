//
//  StreamingSessionManager.h
//  Limelight
//
//  Created by SkyHua on 2025-01-20.
//

#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>

NS_ASSUME_NONNULL_BEGIN

typedef NS_ENUM(NSInteger, StreamingState) {
    StreamingStateIdle,
    StreamingStateConnecting,    // Currently unused; reserved for future connection lifecycle phases.
    StreamingStateStreaming,
    StreamingStateDisconnecting  // Currently unused; reserved for future connection lifecycle phases.
};

@interface StreamingSessionManager : NSObject

@property (nonatomic, readonly) StreamingState state;
@property (nonatomic, readonly, nullable) NSString *activeHostUUID;
@property (nonatomic, readonly, nullable) NSString *activeAppId;
@property (nonatomic, readonly, nullable) NSString *activeAppName;
@property (nonatomic, weak, nullable) NSWindowController *streamWindowController;

+ (instancetype)shared;

// Check if a new stream can be started for the given host
// Returns YES if idle OR if the active stream is for a DIFFERENT host (allowing parallel streams)
- (BOOL)canStartStreamForHost:(NSString *)hostUUID;

// Start a session
- (void)startStreamingWithHost:(NSString *)hostUUID
                         appId:(NSString *)appId
                       appName:(NSString *)appName
            windowController:(NSWindowController *)windowController;

// Query state for a specific host
- (BOOL)isStreamingHost:(NSString *)hostUUID;

// Get app name for a specific host
- (nullable NSString *)appNameForHost:(NSString *)hostUUID;

// Signal that disconnection occurred (cleanup) for a specific host
- (void)didDisconnectForHost:(NSString *)hostUUID;

// Signal that disconnection occurred (cleanup)
- (void)didDisconnect;

// Focus the streaming window
- (void)focusStreamWindow;

// Focus a specific host's streaming window
- (void)focusStreamWindowForHost:(NSString *)hostUUID;

// Request disconnection (active action)
- (void)disconnect;

// Request disconnection for a specific host
- (void)disconnectHost:(NSString *)hostUUID;

// Request disconnection with explicit action (quitApp=YES means quit Sunshine app only)
- (void)requestDisconnectWithQuitApp:(BOOL)quitApp;

// Request disconnection for a specific host (quitApp=YES means quit Sunshine app only)
- (void)requestDisconnectWithQuitApp:(BOOL)quitApp hostUUID:(NSString *)hostUUID;

@end

NS_ASSUME_NONNULL_END
