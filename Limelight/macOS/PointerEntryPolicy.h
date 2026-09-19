//
//  PointerEntryPolicy.h
//  Moonlight
//
//  Whether a pointer sliding into the stream window is allowed to take that window --
//  and with it the application -- away from whatever the player was using.
//
//  Two issues describe the same mechanism from two sides. #21: the pointer leaves the
//  window, the player goes to another application, and moving back over the window
//  brings Moonlight to the front without a click. #40: ⌘-Tab away and the stream window
//  comes back on its own. The tracking area is installed with NSTrackingActiveAlways, so
//  mouseEntered: arrives even while this application is in the background, and the entry
//  path made the stream window key, which activates the application.
//
//  The answer is not "hover never activates", because a player who has clicked into the
//  stream and steps the pointer out to reach a second monitor should not have to click
//  again. It is "ask, and decide from the state you were given" -- which is also the only
//  version of this that a test can hold still.
//

#import <Foundation/Foundation.h>

/// The state a pointer-entry event can see. Only fields that change the answer are here:
/// a field nothing reads is a field somebody will later assume matters.
typedef struct {
    /// The player's switch. Its default is the shipping behaviour, stated below once.
    BOOL hoverActivatesWindow;
    /// Free-pointer mode, the only mode in which a hover ever meant anything here.
    BOOL remoteDesktopMode;
    /// A captured mouse is already the host's; entering the window is not a new claim.
    BOOL mouseCaptured;
    /// The player is reaching past an edge for the overlay menu, not into the stream.
    BOOL edgeMenuTemporaryReleaseActive;
    /// The pointer left through a known edge and its re-entry is already owned by that
    /// handoff, which arrived with the player's own gesture.
    BOOL pendingReentryEdge;
} MLPointerEntryState;

typedef NS_OPTIONS(NSInteger, MLPointerEntryAction) {
    MLPointerEntryActionNone = 0,
    /// Make the stream window key. This is the step that activates the application.
    MLPointerEntryActionMakeWindowKey = 1 << 0,
    /// Line the host's cursor up with where the pointer landed, so a hover that does take
    /// the window does not start from a cursor the player has never looked at.
    MLPointerEntryActionSyncRemoteCursor = 1 << 1,
    /// Offer the pointer to the host again. The capture path activates the application, so
    /// a hover cannot hand it this action and then claim it did not steal focus.
    MLPointerEntryActionRearmCapture = 1 << 2,
};

/// Everything a hover may do, decided from the state above and from nothing else: not the
/// clock, not a stored counter, not the window server's mood. The whole point is that the
/// answer for a given situation can be written down, argued about, and re-run.
FOUNDATION_EXPORT MLPointerEntryAction MLPointerEntryActionsForState(MLPointerEntryState state);

/// The shipping default. Kept as a function rather than a literal at each call site, so a
/// release that quietly changed what a hover does for every existing player would have to
/// change one line that the harness also reads.
FOUNDATION_EXPORT BOOL MLPointerEntryHoverActivatesWindowDefault(void);
