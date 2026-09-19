//
//  PointerEntryPolicy.m
//  Moonlight
//
//  See PointerEntryPolicy.h. This file holds the whole answer on purpose: the two issues
//  about hover activation both came from the decision being spread across four early
//  returns inside an AppKit callback, where nothing could see it and no test could drive
//  one branch without a window, a pointer, and another application.
//

#import "PointerEntryPolicy.h"

// Yes, by default. Hover-to-activate is what every build of this application has done up
// to now, and a player who has clicked into the stream and steps the pointer out to reach
// a second display should not have to click their way back in. The two issues above are
// answered by making the switch exist and reachable from the mouse settings, not by
// changing what a fresh install does.
static const BOOL MLHoverActivatesWindowDefault = YES;

BOOL MLPointerEntryHoverActivatesWindowDefault(void) {
    return MLHoverActivatesWindowDefault;
}

MLPointerEntryAction MLPointerEntryActionsForState(MLPointerEntryState state) {
    // A hover was never a claim in captured mode -- the host already has the pointer, and
    // the player is looking at their own machine only through the picture on screen -- and
    // it means nothing at all in absolute-pointer mode, where the window is not holding
    // the pointer for anyone.
    if (!state.remoteDesktopMode || state.mouseCaptured) {
        return MLPointerEntryActionNone;
    }
    // Reaching out for the overlay menu is the player's hand crossing the edge, not a
    // decision to play again.
    if (state.edgeMenuTemporaryReleaseActive) {
        return MLPointerEntryActionNone;
    }
    // A pointer that came back through an edge the player used to leave is already owned
    // by that handoff, which arrived with a gesture behind it. A hover on top of it would
    // decide the same thing twice.
    if (state.pendingReentryEdge) {
        return MLPointerEntryActionNone;
    }
    // The switch. Off means exactly what #21 asked for: the window keeps tracking the
    // pointer, because that is bookkeeping and costs nothing, and waits for a click.
    if (!state.hoverActivatesWindow) {
        return MLPointerEntryActionNone;
    }
    return MLPointerEntryActionMakeWindowKey | MLPointerEntryActionSyncRemoteCursor |
           MLPointerEntryActionRearmCapture;
}
