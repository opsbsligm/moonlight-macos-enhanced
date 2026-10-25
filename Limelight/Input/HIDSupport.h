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
/// K1.2: drafts and commits the local IME produced since the last sample.
@property(nonatomic) NSUInteger imeCompositions;
@property(nonatomic) NSUInteger imeCommits;

/// Packets that reached the host, counted per sender, relative and absolute apart.
///
/// The totals above say how much motion moved; these say who moved it. A pointer that stops
/// in locked mouse mode is a question about which of four senders is still holding the
/// packet, and totals cannot answer it: the same `rel=4180` arrives whether one sender wrote
/// all of it or four wrote a quarter each. Keys are the tags the senders pass when they
/// dispatch, so the name in a report is the name in the branch that sent it.
@property(nonatomic, copy) NSDictionary<NSString *, NSNumber *> *relativeMotionBySource;
@property(nonatomic, copy) NSDictionary<NSString *, NSNumber *> *absoluteMotionBySource;
@end

@interface HIDSupport : NSObject
@property(atomic) BOOL shouldSendInputEvents;
/// P2-3b backgroundGamepad: while YES the controller wire path (arrival /
/// axis+button / motion / touch / battery) is suppressed even when
/// shouldSendInputEvents is YES, so the app can keep keyboard + mouse
/// forwarding alive across a focus flip while refusing gamepad events the
/// player is no longer in a position to see. Default NO matches the
/// shipped behaviour of "always forward gamepad input regardless of focus".
@property(atomic) BOOL suspendControllerEvents;
/// K1.2 local IME composition, mirrored from the per-host setting. The
/// stream window sets it from the persisted preference before arming
/// capture and clears it on teardown, so a mid-stream setting flip cannot
/// leave an active text input context the player can no longer see the
/// candidate window of. Default NO keeps every shipped key path intact.
@property(atomic) BOOL imeLocalCompositionEnabled;
/// Screen-space anchor for the candidate window while composition is
/// enabled: the top-left corner of the stream view in screen coordinates.
/// Set by the stream window; (0,0,0,0) when the view is not on screen.
@property(atomic) NSRect imeCandidateAnchorRect;
@property(atomic) TemporaryHost *host;
@property(atomic, assign) void *inputContext;
@property(nonatomic, copy) HIDFreeMouseAbsoluteSyncHandler freeMouseAbsoluteSyncHandler;

- (instancetype)init:(TemporaryHost *)host;

- (void)flagsChanged:(NSEvent *)event;
- (void)keyDown:(NSEvent *)event;
- (void)keyUp:(NSEvent *)event;

/// K1.2: open the local composition session for this capture, when the
/// setting is on, the input context is live, and the system input source
/// is a select-capable non-ASCII keyboard (i.e. an input method). Called
/// from the capture path after the input context is attached. Idempotent:
/// calling it while a session is already open leaves it in place.
- (void)beginIMECompositionIfEnabled;
/// K1.2: any commit the system IME produced while capture was active goes
/// to the host now; a draft that was still marked is discarded with the
/// session. Safe when the session was never opened.
- (void)flushIMECommit;
/// K1.2: close the session, discarding any in-progress composition.
- (void)endIMEComposition;
/// K1.2: distinct non-empty drafts and committed insertions since the
/// last snapshot, for the input diagnostics report.
- (NSUInteger)imeCompositionsSinceLastSnapshot;
- (NSUInteger)imeCommitsSinceLastSnapshot;

/// Releases every remote key owned by this session and cancels deferred presses.
///
/// Mouse capture and keyboard forwarding switch off together, and keyUp: stops
/// forwarding while they are off. A key that is still physically held down when
/// capture ends therefore never reaches the host as a release, which leaves the
/// host holding it for the rest of the session: holding a movement key and
/// releasing the mouse makes the remote character run forever. Call this from
/// every path that turns input forwarding off, after closing admission but while
/// the input context is still alive. Releasing a key that the host already
/// released is harmless; the reverse is not.
- (void)releaseAllHeldKeys;

- (void)releaseAllModifierKeys;
/// Reconcile missed modifier edges when the stream regains capture.
- (void)refreshKeyboardModifiersForCapture;

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
/// Runs on the main thread; closes admission before returning ownership:
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
/// Mouse sources share remote button ownership; each source releases only its own presses.
- (void)sendMouseButton:(int)button pressed:(BOOL)pressed source:(NSString *)source;
- (void)releaseMouseButtonsForSource:(NSString *)source;
/// Sends already-quantized controller motion without applying pointer sensitivity again.
- (void)sendRelativeMouseMoveDeltaX:(short)deltaX deltaY:(short)deltaY;
- (BOOL)hasPressedMouseButtons;
- (void)releaseAllPressedMouseButtons;
// Logs only fields defined for a mouse edge; keyboard-only fields are never read.
- (void)logMouseEventDiagnosticsForEvent:(NSEvent *)event where:(NSString *)where;
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
- (void)resetScrollInputState;
- (void)scrollWheel:(NSEvent *)event;
@end

@interface HIDSupport (RumbleOutput)
- (void)rumbleLowFreqMotor:(unsigned short)lowFreqMotor
             highFreqMotor:(unsigned short)highFreqMotor;
- (void)rumbleForControllerNumber:(int)number
                  lowFreqMotor:(unsigned short)lowFreqMotor
                   highFreqMotor:(unsigned short)highFreqMotor;
- (void)ledForControllerNumber:(int)number
                          red:(unsigned char)red
                        green:(unsigned char)green
                         blue:(unsigned char)blue;
- (void)triggersRumbleForControllerNumber:(int)number
                     leftTriggerMotor:(unsigned short)leftTriggerMotor
                    rightTriggerMotor:(unsigned short)rightTriggerMotor;
- (void)setMotionEventStateForControllerNumber:(int)number
                                  motionType:(uint8_t)motionType
                                reportRateHz:(uint16_t)reportRateHz;
@end
