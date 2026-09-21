//
//  InputDiagnosticsLedger.h
//  Moonlight for macOS
//
//  What the pointer-input path looked like, held somewhere that outlives the stream
//  window.
//
//  Issue 24 describes a pointer that stops moving during a session, and a player copies
//  the diagnostics report once that session is already over. Every number that could
//  explain it lived on the stream view controller and on its HIDSupport instance, both of
//  which are gone by the time the button is reachable, so the evidence existed only as a
//  line in the overlay while the overlay was on screen. This ledger is written by the code
//  that really moves the pointer -- the sender that credits itself, the CoreHID driver that
//  starts or fails, the strategy the settings resolved to -- and read by the report, so a
//  report says what happened and keeps saying it after the session that happened in.
//

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// The pointer-input state of the most recent streaming session, as the app last observed
/// it, plus the two process facts needed to read that state: how many sessions there have
/// been, and whether the last one is still running.
///
/// English on purpose, like the rest of the report: the reader is whoever triages the
/// issue, and a translated key would make a pasted line disagree with the code it
/// describes.
@interface InputDiagnosticsSummary : NSObject <NSCopying>

/// When this process started collecting. The ledger is created at first use, which is
/// early enough that "no stream has started" is a statement about the session list and not
/// about a ledger that has not been touched yet.
@property (nonatomic, copy) NSDate *startedAt;
@property (nonatomic) NSUInteger streamsStarted;
@property (nonatomic) NSUInteger streamsFinished;
/// NO once the session that is described has ended. A report that says "0 relative
/// dispatches" for a finished session and one that says it about a session still running
/// are different claims, and the reader cannot tell them apart without this.
@property (nonatomic) BOOL streamInProgress;

// The session being described. nil means it never reached the point where the value
// exists; the report prints the absence rather than a default.
@property (nonatomic, copy, nullable) NSDate *streamStartedAt;
@property (nonatomic, copy, nullable) NSDate *streamEndedAt;
@property (nonatomic, copy, nullable) NSString *streamEndReason;

/// The strategy the settings resolved to, as the enum case name rather than the menu
/// label. Issue 24 is exactly what a label that disagrees with its effect costs.
@property (nonatomic, copy, nullable) NSString *mouseStrategyName;
/// The number stored for it, or -1 when nothing is stored. Printing both is what makes a
/// retired 0, a corrupt value, and the string the menu no longer lists visible: each of
/// them resolves to the default, and a report that showed only the default could not tell
/// "chosen" from "never configured".
@property (nonatomic) NSInteger mouseStrategyStoredValue;
/// The mode the pointer is in, and whether the absolute path took the session. Both decide
/// how every number below reads: in locked mode the cursor association is off and the
/// relative senders are the only thing that can move the host's pointer, while an absolute
/// session never sends a relative packet at all -- and a report that says `relative dispatches
/// 0` about that second case is describing a working client.
@property (nonatomic, copy, nullable) NSString *pointerMode;
@property (nonatomic) BOOL absolutePointerPathActive;
@property (nonatomic) BOOL coreHIDAllowedByStrategy;
@property (nonatomic) BOOL coreHIDWantedToStart;
@property (nonatomic) BOOL coreHIDDeliveredMovement;
@property (nonatomic) BOOL coreHIDFailedAtRuntime;
@property (nonatomic, copy, nullable) NSString *coreHIDFailureReason;

/// The sender that last handed motion to the host, and when. This is the answer to "which
/// path is actually moving my mouse", which is the question the in-stream status line
/// answers and which nobody can answer from a screenshot after the fact.
@property (nonatomic, copy, nullable) NSString *lastMotionSource;
@property (nonatomic, copy, nullable) NSDate *lastMotionSourceAt;

/// Whether the counters below were being collected during this session. They only advance
/// while the "Input Diagnostics" switch is on, so zero is never evidence on its own.
@property (nonatomic) BOOL collectionEnabledForLastStream;

// The counters. Valid only when collectionEnabledForLastStream is YES.
@property (nonatomic) NSUInteger mouseMoveEvents;
@property (nonatomic) NSUInteger nonZeroRelativeEvents;
@property (nonatomic) NSUInteger relativeDispatches;
@property (nonatomic) NSUInteger absoluteDispatches;
@property (nonatomic) NSUInteger absoluteDuplicateSkips;
@property (nonatomic) NSUInteger coreHIDRawEvents;
@property (nonatomic) NSUInteger coreHIDDispatches;
@property (nonatomic) NSUInteger suppressedRelativeEvents;
@property (nonatomic) NSInteger rawRelativeDeltaX;
@property (nonatomic) NSInteger rawRelativeDeltaY;
@property (nonatomic) NSInteger sentRelativeDeltaX;
@property (nonatomic) NSInteger sentRelativeDeltaY;
@property (nonatomic) NSUInteger captureArmed;
@property (nonatomic) NSUInteger captureSkipped;
@property (nonatomic) NSUInteger captureReleased;
@property (nonatomic) NSUInteger rearms;
@property (nonatomic) NSUInteger rearmSkips;
@property (nonatomic) NSUInteger rearmDeferred;
/// Packets that reached the host, per sender, from the session being described. The totals
/// next to them cannot say which of the four senders was holding the pointer; these can, and
/// that is the question issue 24 is asked with.
@property (nonatomic, copy, nullable) NSDictionary<NSString *, NSNumber *> *relativeMotionBySource;
@property (nonatomic, copy, nullable) NSDictionary<NSString *, NSNumber *> *absoluteMotionBySource;
@property (nonatomic, copy, nullable) NSString *captureSkipTopReasons;
@property (nonatomic, copy, nullable) NSString *rearmTopReasons;
@property (nonatomic, copy, nullable) NSString *rearmSkipTopReasons;
@property (nonatomic, copy, nullable) NSString *rearmDeferredTopReasons;
@end

/// The one copy of that state in the process.
///
/// `updateSummary:` runs the caller's block under the ledger's lock, from whichever thread
/// the input code happens to be on, and `summary` returns a copy taken under the same lock.
/// That is the whole discipline: the input paths stay free to record what they did, and the
/// report reads one consistent picture instead of seventeen properties that a writer could
/// be halfway through changing.
@interface InputDiagnosticsLedger : NSObject

+ (instancetype)sharedLedger;

- (InputDiagnosticsSummary *)summary;

- (void)updateSummary:(void (^)(InputDiagnosticsSummary *summary))update;

/// A session began. Bumps `streamsStarted`, marks it in progress, and clears the fields
/// that describe the previous session: totals from an earlier session reported against the
/// current one would be the same mistake as a HUD line crediting a sender that sent
/// nothing.
- (void)noteStreamStarted;

- (void)noteStreamEndedWithReason:(nullable NSString *)reason;
@end

NS_ASSUME_NONNULL_END
