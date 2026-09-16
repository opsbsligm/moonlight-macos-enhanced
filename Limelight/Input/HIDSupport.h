//
//  HIDSupport.h
//  Moonlight for macOS
//
//  Created by Michael Kenny on 26/12/17.
//  Copyright © 2017 Moonlight Stream. All rights reserved.
//

#import "TemporaryHost.h"
#import <Foundation/Foundation.h>

extern NSString *const HIDMouseModeToggledNotification;
extern NSString *const HIDGamepadQuitNotification;
typedef void (^HIDFreeMouseAbsoluteSyncHandler)(void);
@class StreamShortcut;

@interface HIDInputDiagnosticsSnapshot : NSObject
@property(nonatomic) NSUInteger mouseMoveEvents;
@property(nonatomic) NSUInteger nonZeroRelativeEvents;
@property(nonatomic) NSUInteger relativeDispatches;
@property(nonatomic) NSUInteger absoluteDispatches;
@property(nonatomic) NSUInteger absoluteDuplicateSkips;
@property(nonatomic) NSUInteger coreHIDRawEvents;
@property(nonatomic) NSUInteger coreHIDDispatches;
@property(nonatomic) NSUInteger suppressedRelativeEvents;
@property(nonatomic) NSInteger rawRelativeDeltaX;
@property(nonatomic) NSInteger rawRelativeDeltaY;
@property(nonatomic) NSInteger sentRelativeDeltaX;
@property(nonatomic) NSInteger sentRelativeDeltaY;
@end

@interface HIDSupport : NSObject
@property(atomic) BOOL shouldSendInputEvents;
@property(atomic) TemporaryHost *host;
@property(nonatomic, assign) void *inputContext;
@property(nonatomic, copy) HIDFreeMouseAbsoluteSyncHandler freeMouseAbsoluteSyncHandler;

- (instancetype)init:(TemporaryHost *)host;

- (void)flagsChanged:(NSEvent *)event;
- (void)keyDown:(NSEvent *)event;
- (void)keyUp:(NSEvent *)event;

/// Sends UP for every key this session forwarded a DOWN for, then clears the
/// record.
///
/// Mouse capture and keyboard forwarding switch off together, and keyUp: stops
/// forwarding while they are off. A key that is still physically held down when
/// capture ends therefore never reaches the host as a release, which leaves the
/// host holding it for the rest of the session: holding a movement key and
/// releasing the mouse makes the remote character run forever. Call this from
/// every path that turns input forwarding off, before it turns them off, while
/// the input context is still alive. Releasing a key that the host already
/// released is harmless; the reverse is not.
- (void)releaseAllHeldKeys;

- (void)releaseAllModifierKeys;

/// Hands the modifiers the host was told about back to it, without touching the
/// physical tracker: for the moment input forwarding stops (mouse capture
/// released) and the session continues afterwards. A modifier the player is
/// genuinely still holding is re-pressed on the first keyboard event after
/// recapture; one they let go of while input was off stays up.
- (void)releaseRemoteModifierKeysForUncapture;

/// Records that a key's keyDown was consumed locally and never forwarded, so the
/// matching keyUp must not be forwarded either.
///
/// AppKit only offers the key-equivalent stage on keyDown: a view that consumes a
/// key still receives its keyUp through normal dispatch. Forwarding that release
/// tells the host a key went up that it never saw go down, which is how a local
/// shortcut looks like a gameplay key releasing on its own. Call this from every
/// branch that consumes a real key event; do not call it for non-keyboard events
/// (keyCode is undefined there) or for events dropped after teardown (the
/// release is already suppressed because input is off).
- (void)noteKeyboardKeyDownSuppressedForEvent:(NSEvent *)event;

/// Returns YES once tearDownKeyboardStateForSessionEnd has run.
/// Safe to poll from any thread. Readonly atomic BOOL.
@property (atomic, readonly) BOOL keyboardTeardownAlreadyCalled;

/// Called exactly once when the streaming session terminates (either via
/// connectionTerminated, performCloseStreamWindow, or windowWillClose).
/// Does ALL of the following atomically:
///   - Zeroes local physical + remote modifier masks
///   - Sends UP for all 8 modifier keys (Win/L/Ctrl/Alt/Shift × left/right)
///   - Releases all pressed mouse buttons (per PointerInput)
///   - Disables shouldSendInputEvents so subsequent events become no-ops
///   - Idempotent: second and later calls are a safe no-op
- (void)tearDownKeyboardStateForSessionEnd:(const char *)reason;

- (void)sendSyntheticRemoteShortcut:(StreamShortcut *)shortcut;
- (void)sendSyntheticRemoteModifierTapForFlags:(NSEventModifierFlags)modifierFlags;
- (void)sendSyntheticRemoteModifierTapForKeyCode:(unsigned short)keyCode
            preferShortcutTranslationCommandMapping:(BOOL)preferShortcutTranslationCommandMapping;
- (void)beginDeferredShortcutTranslationCommandHoldForKeyCode:(unsigned short)keyCode;
- (void)endDeferredShortcutTranslationCommandHoldForKeyCode:(unsigned short)keyCode;
- (BOOL)getLastAbsolutePointerHostX:(short *)hostX
                              hostY:(short *)hostY
                     referenceWidth:(short *)referenceWidth
                    referenceHeight:(short *)referenceHeight
                              ageMs:(uint64_t *)ageMs
                             source:(NSString * __autoreleasing *)source;
- (void)refreshInputDiagnosticsPreference;
- (void)resetInputDiagnostics;
- (HIDInputDiagnosticsSnapshot *)consumeInputDiagnosticsSnapshot;
- (void)refreshMouseInputConfiguration;
- (void)tearDownHidManager;
- (BOOL)shouldUseAbsolutePointerPathForCurrentConfiguration;
- (BOOL)shouldUseCoreHIDFreeMouseAbsoluteSyncForCurrentConfiguration;
- (BOOL)hasRecentCoreHIDMouseMovement;

@end

@interface HIDSupport (PointerInput)
- (BOOL)hasPressedMouseButtons;
- (void)releaseAllPressedMouseButtons;
- (void)mouseDown:(NSEvent *)event withButton:(int)button;
- (void)mouseUp:(NSEvent *)event withButton:(int)button;
- (void)mouseMoved:(NSEvent *)event;
- (void)setFreeMouseVirtualCursorActive:(BOOL)active;
- (void)resetFreeMouseVirtualCursorState;
- (void)updateFreeMouseVirtualCursorAnchorWithViewPoint:(NSPoint)viewPoint
                                          referenceSize:(NSSize)referenceSize;
- (BOOL)reconcileFreeMouseVirtualCursorToViewPoint:(NSPoint)viewPoint
                                     referenceSize:(NSSize)referenceSize
                               correctionThreshold:(CGFloat)correctionThreshold;
- (BOOL)getFreeMouseVirtualCursorPoint:(NSPoint *)viewPoint
                         referenceSize:(NSSize *)referenceSize;
- (void)sendAbsoluteMousePositionForViewPoint:(NSPoint)viewPoint
                                referenceSize:(NSSize)referenceSize
                                clampToBounds:(BOOL)clampToBounds;
- (void)sendMouseButton:(int)button
                pressed:(BOOL)pressed
      syncedToViewPoint:(NSPoint)viewPoint
          referenceSize:(NSSize)referenceSize
          clampToBounds:(BOOL)clampToBounds;
- (BOOL)absoluteMousePayloadForViewPoint:(NSPoint)viewPoint
                           referenceSize:(NSSize)referenceSize
                           clampToBounds:(BOOL)clampToBounds
                                   hostX:(short *)hostX
                                   hostY:(short *)hostY
                          referenceWidth:(short *)referenceWidth
                         referenceHeight:(short *)referenceHeight;
- (void)suppressRelativeMouseMotionForMilliseconds:(uint64_t)durationMs;
@end

@interface HIDSupport (ScrollInput)
- (void)scrollWheel:(NSEvent *)event;
@end

@interface HIDSupport (RumbleOutput)
- (void)rumbleLowFreqMotor:(unsigned short)lowFreqMotor
             highFreqMotor:(unsigned short)highFreqMotor;
@end
