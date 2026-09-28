"""Replay production edge-control state, geometry and pointer ownership without desktop input."""
from pathlib import Path
import re
import subprocess
import tempfile
from apple_toolchain import clang_and_sdk

def method(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 0
    for end in range(brace, len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if depth == 0:
            return source[start:end + 1]
    raise AssertionError(signature)


HARNESS = r'''
#import <AppKit/AppKit.h>
#include <math.h>
static NSMutableArray<NSString *> *ProbeLogLines;
@interface ProbeLog : NSObject
+ (void)reset;
+ (void)record:(NSString *)line;
+ (NSInteger)countMatching:(NSString *)needle;
@end
@implementation ProbeLog
+ (void)reset { ProbeLogLines = [NSMutableArray array]; }
+ (void)record:(NSString *)line { if (!ProbeLogLines) ProbeLogLines = [NSMutableArray array]; [ProbeLogLines addObject:line ?: @""]; }
+ (NSInteger)countMatching:(NSString *)needle {
    NSInteger hits = 0;
    for (NSString *line in ProbeLogLines) if ([line rangeOfString:needle].location != NSNotFound) hits++;
    return hits;
}
@end
#define Log(level, ...) [ProbeLog record:[NSString stringWithFormat:__VA_ARGS__]]
#define BUTTON_LEFT 1
#define BUTTON_RIGHT 3
__CONSTANTS__
__HELPERS__
@interface Motion : NSObject
@property CGFloat deltaX, deltaY;
@property NSInteger buttonNumber;
@property NSEventModifierFlags modifierFlags;
@end
@implementation Motion
@end
static NSString * const MLShortcutActionReleaseMouseCapture = @"releaseMouseCapture";
static NSEventModifierFlags MLRelevantShortcutModifiers(NSEventModifierFlags f) {
    return f & (NSEventModifierFlagShift | NSEventModifierFlagControl | NSEventModifierFlagOption | NSEventModifierFlagCommand);
}
@interface StreamShortcut : NSObject
@property BOOL modifierOnly;
@property NSEventModifierFlags modifierFlags;
@end
@implementation StreamShortcut
@end
@interface Bounds : NSObject
@property NSRect bounds;
@property NSWindow *window;
@end
@implementation Bounds
@end
@interface PointerMode : NSObject
- (BOOL)shouldUseCoreHIDFreeMouseAbsoluteSyncForCurrentConfiguration;
@end
@implementation PointerMode
- (BOOL)shouldUseCoreHIDFreeMouseAbsoluteSyncForCurrentConfiguration { return NO; }
@end
@interface Panel : NSObject
@property BOOL isVisible, ignoresMouseEvents;
@property CGFloat alphaValue;
@property NSRect frame;
- (void)setFrame:(NSRect)frame display:(BOOL)display;
- (void)orderFront:(id)sender;
- (void)orderOut:(id)sender;
@end
@implementation Panel
- (void)setFrame:(NSRect)frame display:(BOOL)display { self.frame = frame; }
- (void)orderFront:(id)sender { self.isVisible = YES; }
- (void)orderOut:(id)sender { self.isVisible = NO; }
@end
@interface ProbeHandle : NSView
@property BOOL armedAppearance;
@property BOOL compactAppearance;
@end
@implementation ProbeHandle
@end
@interface ProbeMenu : NSMenu
@property(copy) void (^onTrack)(void);
@property NSInteger cancellations;
@end
@implementation ProbeMenu
- (BOOL)popUpMenuPositioningItem:(NSMenuItem *)item atLocation:(NSPoint)point inView:(NSView *)view {
    if (self.onTrack) self.onTrack();
    return YES;
}
- (void)cancelTracking { self.cancellations++; }
@end
@interface Sensor : NSObject
@property Bounds *view;
@property NSMutableArray *wire;
@property NSInteger menuOpens, menuRebuilds;
@property BOOL suppressNextRightMouseUp, pendingMouseExitedRecapture;
@property PointerMode *hidSupport;
@property NSPoint systemPoint;
@property BOOL captureAllowed, userReleasedInput, stopStreamInProgress, reconnectInProgress;
@property StreamShortcut *releaseShortcut;
@property NSEventModifierFlags physicalModifiers, pendingModifierOnlyReleaseMask;
@property NSUInteger pendingModifierOnlyReleaseToken;
@property NSUInteger pendingOptionUncaptureToken, pendingMouseCaptureRetryToken;
@property double lastOptionUncaptureAtMs;
@property NSInteger pendingFreeMouseReentryEdge;
@property double pendingFreeMouseReentryAtMs;
@property BOOL isRemoteDesktopMode, isMouseCaptured, edgeSensorSummonEnabled;
@property BOOL edgeMenuTemporaryReleaseActive;
@property MLEdgeMenuPhase edgeMenuPhase;
@property NSUInteger edgeMenuLifecycleToken;
@property NSMenu *streamMenu;
@property NSPoint edgeMenuButtonPanStartOrigin;
- (void)rebuildStreamMenu;
- (void)updateEdgeMenuButtonTrackingArea;
- (void)presentStreamMenuFromView:(NSView *)sourceView event:(NSEvent *)event;
- (void)handleEdgeMenuButtonDragWithState:(NSGestureRecognizerState)state translation:(NSPoint)translation;
- (BOOL)edgeMenuButtonExpanded;
- (BOOL)edgeMenuDragging;
- (BOOL)edgeMenuMenuVisible;
- (void)transitionEdgeMenuToPhase:(MLEdgeMenuPhase)phase;
- (BOOL)edgeMenuCanInteract;
- (void)handleEdgeMenuHover;
- (NSRect)edgeSensorActivationRectInBounds:(NSRect)bounds;
@property BOOL edgeMenuPointerInside, edgeMenuPointerHasVisited, staleEvent;
@property (readonly) BOOL expanded;
@property BOOL edgeSensorMustLeaveHoverRegion;
@property BOOL edgeMenuHandleArmed;
@property Panel *edgeMenuPanel;
@property ProbeHandle *edgeMenuButton;
@property NSTimer *edgeMenuAutoCollapseTimer;
@property NSInteger releases;
@property BOOL edgeSensorRelativePointValid, buttons, visible;
@property NSPoint edgeSensorRelativePoint;
@property NSRect edgeSensorRelativeBounds;
@property NSTimer *edgeSensorDwellTimer;
@property CGFloat edgeMenuButtonEdgeRatio;
@property double edgeSensorIgnoreMotionUntilMs, suppressFreeMouseEdgeUncaptureUntilMs, edgeSensorLastRefusalLogMs;
@property double fakeNowMs;
@property MLFreeMouseExitEdge edgeMenuDockEdge, freeEdge;
@property NSInteger summons;
@property NSString *reason;
@property double edgeSensorLastSampleLogMs;
@property BOOL edgeMenuClickConsumedLocally;
- (BOOL)expandEdgeMenuForLocalClickAtCurrentPointer;
- (double)nowMs;
- (NSPoint)currentMouseLocationInViewCoordinates;
- (NSPoint)boundaryInteractionViewPointForMouseEvent:(NSEvent *)event;
- (NSRect)edgeMenuInteractionRectInBounds:(NSRect)bounds;
- (BOOL)edgeMenuShouldBeVisible;
- (BOOL)hasPressedMouseButtonsForCaptureTransition;
- (MLFreeMouseExitEdge)freeMouseExitEdgeForEvent:(NSEvent *)event;
- (void)summonEdgeMenuDockForEdge:(MLFreeMouseExitEdge)edge reason:(NSString *)reason;
- (void)cancelEdgeMenuAutoCollapse;
- (void)scheduleEdgeMenuAutoCollapse;
- (void)uncaptureMouseWithCode:(NSString *)code reason:(NSString *)reason;
- (void)setEdgeMenuButtonExpanded:(BOOL)expanded animated:(BOOL)animated;
- (void)refreshMouseMovedAcceptanceState;
- (void)updateEdgeMenuButtonAppearance;
- (BOOL)canCaptureMouseNow;
- (void)captureMouse;
- (void)prepareCoreHIDVirtualCursorForSystemPointerSyncIfNeeded;
- (void)syncRemoteCursorToViewPoint:(NSPoint)point clampToBounds:(BOOL)clamp;
- (BOOL)edgeMenuMatchesExitEdge:(MLFreeMouseExitEdge)edge;
- (void)updateControlCenterEntrypointHints;
- (void)updateEdgeMenuPointerInsideForPoint:(NSPoint)point;
- (NSPoint)viewPointForMouseEvent:(NSEvent *)event;
- (BOOL)isPointInsideEdgeMenuInteractionRect:(NSPoint)point;
- (void)ensureStreamWindowKeyIfPossible;
- (void)updateCoreHIDFreeMouseTruthPointFromEvent:(NSEvent *)event;
- (void)reassertHiddenLocalCursorIfNeededWithReason:(NSString *)reason;
- (void)logMouseClickDiagnosticsForPhase:(NSString *)phase event:(NSEvent *)event;
- (BOOL)captureFreeMouseIfNeededForEvent:(NSEvent *)event;
- (void)dispatchMouseButton:(int)button pressed:(BOOL)pressed event:(NSEvent *)event;
- (void)completeDeferredMouseUncaptureIfNeeded;
- (void)presentStreamMenuAtEvent:(NSEvent *)event;
- (int)getMouseButtonFromEvent:(NSEvent *)event;
- (void)attachEdgeMenuPanelToWindowIfNeeded;
- (NSRect)edgeMenuAnchorRectInScreen;
- (NSRect)frameForCurrentEdgeMenuPanelStateInScreenRect:(NSRect)rect;
@end
@implementation Sensor
- (void)rebuildStreamMenu { self.menuRebuilds++; }
- (void)updateEdgeMenuButtonTrackingArea {}
- (void)ensureStreamWindowKeyIfPossible {}
- (void)updateCoreHIDFreeMouseTruthPointFromEvent:(NSEvent *)event {}
- (void)reassertHiddenLocalCursorIfNeededWithReason:(NSString *)reason {}
- (void)logMouseClickDiagnosticsForPhase:(NSString *)phase event:(NSEvent *)event {}
- (BOOL)isCurrentPointerInsideStreamView { return NSPointInRect(self.systemPoint, self.view.bounds); }
- (void)syncRemoteCursorToMouseEvent:(NSEvent *)event clampToBounds:(BOOL)clamp {}
- (void)rearmMouseCaptureIfPossibleWithReason:(NSString *)reason { [self captureMouse]; }
- (void)dispatchMouseButton:(int)button pressed:(BOOL)pressed event:(NSEvent *)event {
    if (self.isMouseCaptured) [self.wire addObject:[NSString stringWithFormat:@"%d%@", button, pressed ? @"D" : @"U"]];
}
- (void)completeDeferredMouseUncaptureIfNeeded {}
- (void)presentStreamMenuAtEvent:(NSEvent *)event { self.menuOpens++; }
- (int)getMouseButtonFromEvent:(NSEvent *)event { return 2; }
- (double)nowMs { return self.fakeNowMs != 0 ? self.fakeNowMs : NSProcessInfo.processInfo.systemUptime * 1000.0; }
- (NSPoint)currentMouseLocationInViewCoordinates { return self.systemPoint; }
- (NSPoint)boundaryInteractionViewPointForMouseEvent:(NSEvent *)event { return [self currentMouseLocationInViewCoordinates]; }
- (BOOL)edgeMenuShouldBeVisible { return self.visible; }
- (BOOL)edgeMenuCanInteract { return !self.stopStreamInProgress && !self.reconnectInProgress && self.visible; }
- (BOOL)hasPressedMouseButtonsForCaptureTransition { return self.buttons; }
- (MLFreeMouseExitEdge)freeMouseExitEdgeForEvent:(NSEvent *)event { return self.freeEdge; }
- (void)uncaptureMouseWithCode:(NSString *)code reason:(NSString *)reason { self.releases++; self.isMouseCaptured = NO; }
- (BOOL)expanded { return self.edgeMenuButtonExpanded; }
- (void)attachEdgeMenuPanelToWindowIfNeeded {}
- (NSRect)edgeMenuAnchorRectInScreen { return self.view.bounds; }
- (void)refreshMouseMovedAcceptanceState {}
- (void)updateEdgeMenuButtonAppearance {
    self.edgeMenuButton.armedAppearance = self.edgeMenuHandleArmed && !self.edgeMenuButtonExpanded;
}
- (BOOL)canCaptureMouseNow { return self.captureAllowed && !self.userReleasedInput && ![self edgeMenuOwnsPointer]; }
- (void)updateSystemHotkeySuppression {}
- (StreamShortcut *)streamShortcutForAction:(NSString *)action { return self.releaseShortcut; }
- (NSEventModifierFlags)currentReleaseShortcutModifiers { return self.physicalModifiers; }
- (void)captureMouse {
    if (self.isMouseCaptured || !self.captureAllowed || self.userReleasedInput || [self edgeMenuOwnsPointer]) return;
    [self resetEdgeSensorPointerState]; self.isMouseCaptured = YES;
    if (!self.isRemoteDesktopMode) self.systemPoint = NSMakePoint(960, 540);
}
- (void)prepareCoreHIDVirtualCursorForSystemPointerSyncIfNeeded {}
- (void)syncRemoteCursorToViewPoint:(NSPoint)point clampToBounds:(BOOL)clamp {}
- (BOOL)edgeMenuMatchesExitEdge:(MLFreeMouseExitEdge)edge { return edge == self.edgeMenuDockEdge; }
- (void)updateControlCenterEntrypointHints {}
- (NSPoint)viewPointForMouseEvent:(NSEvent *)event { return self.staleEvent ? NSMakePoint(960,540) : self.systemPoint; }
__METHODS__
@end
static Sensor *fresh(MLFreeMouseExitEdge edge) {
    Sensor *s = [Sensor new]; s.view = [Bounds new];
    s.hidSupport = [PointerMode new]; s.systemPoint = NSMakePoint(960, 540); s.captureAllowed = YES;
    s.edgeMenuPanel = [Panel new]; s.edgeMenuButton = [ProbeHandle new];
    s.view.bounds = NSMakeRect(0, 0, 1920, 1080);
    s.visible = s.isMouseCaptured = s.edgeSensorSummonEnabled = s.isRemoteDesktopMode = YES;
    [s transitionEdgeMenuToPhase:MLEdgeMenuPhaseCollapsed];
    s.edgeMenuDockEdge = edge; s.edgeMenuButtonEdgeRatio = 0.5;
    return s;
}
static void move(Sensor *s, double x, double y) {
    Motion *m = [Motion new]; m.deltaX = x; m.deltaY = y;
    [s handleEdgeSensorSummonForEvent:(NSEvent *)m];
}
static void moveAt(Sensor *s, double atMs, double x, double y) {
    s.fakeNowMs = atMs; move(s, x, y);
}
static void waitForDwell(void) {
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.30]];
}
#define CHECK(x, label) do { count++; if (!(x)) { failures++; printf("FAIL %s\n", label); } } while (0)

static void fire(NSTimer *timer) { [timer fire]; [timer invalidate]; }
int main(void) { @autoreleasepool {
    int failures = 0, count = 0;
    CFRunLoopAddCommonMode(CFRunLoopGetMain(), (__bridge CFStringRef)NSEventTrackingRunLoopMode);
    Sensor *s;
    NSSize sizes[] = {{640,480},{1280,720},{1920,1080},{2560,1440},{3840,2160},{3440,1440},{1080,1920},{160,120}};
    for (int size = 0; size < 8; size++) for (int edge = 1; edge <= 4; edge++) {
        s = fresh(edge); s.view.bounds = NSMakeRect(-80,35,sizes[size].width,sizes[size].height);
        NSRect dock = [s expandedFrameForEdgeMenuButtonInBounds:s.view.bounds];
        NSRect region = [s edgeSensorActivationRectInBounds:s.view.bounds];
        CHECK(NSContainsRect(s.view.bounds,dock), "all four placements fit wide, portrait and small bounds");
        CHECK(NSContainsRect(s.view.bounds,region), "activation never extends onto another display");
        CHECK((edge <= 2 ? NSWidth(region) : NSHeight(region)) == MLEdgeSensorBandWidth, "activation depth matches the twelve-point band");
        CHECK(MLEdgeSensorBandWidth >= 8 && MLEdgeSensorBandWidth <= 16, "band is findable after release yet far shallower than the old 24pt regression");
        CHECK((edge <= 2 ? NSHeight(region) : NSWidth(region)) == 56, "activation is limited to the handle span");
        CHECK(![s edgeSensorPointIsInHoverRegion:NSMakePoint(NSMidX(dock),NSMidY(dock)) edge:edge], "expanded interaction box is not an activation region");
        NSPoint outsideSpan = edge <= 2 ? NSMakePoint(NSMidX(region),NSMinY(s.view.bounds)+1) : NSMakePoint(NSMinX(s.view.bounds)+1,NSMidY(region));
        CHECK(![s edgeSensorPointIsInHoverRegion:outsideSpan edge:edge], "rest of the screen edge cannot summon controls");
        for (int cycle=0; cycle<10; cycle++) {
            // Arrival is not a request. Resting against the dock lights the tab and must
            // change nothing else: the same ten cycles are what turned "the sidebar fires
            // on its own" into a repeatable expectation instead of an anecdote.
            s.systemPoint = NSMakePoint(NSMidX(region),NSMidY(region));
            s.edgeSensorIgnoreMotionUntilMs = 0;
            move(s,0,0);
            CHECK(s.edgeSensorDwellTimer.isValid, "authoritative local position starts dwell");
            NSRect idleTab = [s edgeMenuVisibleHandleRectInBounds:s.view.bounds];
            CGFloat idleDepth = MIN(NSWidth(idleTab), NSHeight(idleTab));
            // The tab has to sit on the span the sensor watches. The panel is square, so
            // reading the wrong axis still centres it on screen and only shows up as a
            // handle that does not line up with where a dwell actually arms.
            NSPoint watched = NSMakePoint(NSMidX(region), NSMidY(region));
            NSPoint drawn = NSMakePoint(NSMidX(idleTab), NSMidY(idleTab));
            CGFloat alongEdge = edge == MLFreeMouseExitEdgeLeft || edge == MLFreeMouseExitEdgeRight
                ? fabs(watched.y - drawn.y) : fabs(watched.x - drawn.x);
            CHECK(alongEdge <= 1.0, "the tab the player clicks sits on the span the sensor watches");
            CHECK(NSPointInRect(watched, idleTab), "the point that arms the tab is inside the tab it lights");
            [ProbeLog reset];
            fire(s.edgeSensorDwellTimer);
            CHECK(s.edgeMenuHandleArmed && !s.expanded, "arrival at the edge lights the tab instead of opening the bar");
            CHECK(s.isMouseCaptured && !s.edgeMenuTemporaryReleaseActive, "lighting the tab leaves the pointer with the game");
            CHECK(s.edgeMenuPanel.ignoresMouseEvents, "an armed tab never takes native input away from the stream");
            CHECK([ProbeLog countMatching:@"Edge controls opened"] == 0, "lighting the tab opens nothing it could report");
            NSRect litTab = [s edgeMenuVisibleHandleRectInBounds:s.view.bounds];
            CHECK(MIN(NSWidth(litTab), NSHeight(litTab)) > idleDepth,
                  "arming the tab is something the player can see, not a flag only the code reads");
            s.systemPoint = NSMakePoint(edge == MLFreeMouseExitEdgeLeft ? NSMaxX(s.view.bounds)-1 : NSMinX(s.view.bounds)+1,
                                        edge == MLFreeMouseExitEdgeBottom ? NSMaxY(s.view.bounds)-1 : NSMinY(s.view.bounds)+1);
            move(s,0,0);
            CHECK(!s.edgeMenuHandleArmed, "leaving the band takes the light away again");
        }
    }
    // The idle tab is where a player looks for the control bar before they have found
    // it, so it has to be deep enough to see and no deeper than a deliberate target.
    for (int edge = 1; edge <= 4; edge++) {
        s = fresh(edge);
        NSRect idleTab = [s edgeMenuVisibleHandleRectInBounds:s.view.bounds];
        CGFloat idleDepth = MIN(NSWidth(idleTab), NSHeight(idleTab));
        CHECK(idleDepth >= MLEdgeMenuHandleIdleThickness && idleDepth <= MLEdgeMenuButtonVisiblePeek + 2.0,
              "the idle tab is visible at the dock without reaching into the game");
    }
    // The click is what asks for the bar, and it is aimed at the tab the player was
    // shown. Repeated on every docked edge, because the first open used to work and the
    // ones after it did not.
    for (int edge = 1; edge <= 4; edge++) for (int cycle = 0; cycle < 10; cycle++) {
        s = fresh(edge);
        s.wire = [NSMutableArray array];
        NSRect region = [s edgeSensorActivationRectInBounds:s.view.bounds];
        s.systemPoint = NSMakePoint(NSMidX(region),NSMidY(region));
        s.edgeSensorIgnoreMotionUntilMs = 0;
        move(s,0,0); fire(s.edgeSensorDwellTimer);
        [s releaseInputToLocalControlWithCode:@"probe" reason:@"free mouse"];
        s.edgeSensorIgnoreMotionUntilMs = 0;
        CHECK([s expandEdgeMenuForLocalClickAtCurrentPointer] && s.expanded && s.edgeMenuClickConsumedLocally,
              "the click on the lit tab opens the controls and consumes the press");
        CHECK(!s.edgeMenuPanel.ignoresMouseEvents, "expanded controls accept native input");
        CHECK(!s.edgeMenuHandleArmed, "an open bar does not keep the tab lit");
        [s mouseUp:(NSEvent *)[Motion new]];
        CHECK(!s.edgeMenuClickConsumedLocally && [s.wire count] == 0,
              "the press that opened the bar never reaches the host as a game click");
        [s deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:NO];
        CHECK(!s.expanded, "closing the bar puts the controls away");
    }
    // The light has to survive the pointer travelling to it. Pulling back from the band
    // onto the tab is how a click is actually aimed, and a tab that went dark on the way
    // made the lit state a promise the click could not keep.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    [s releaseInputToLocalControlWithCode:@"test" reason:@"explicit"];
    s.edgeSensorIgnoreMotionUntilMs = 0;
    s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - 2, 540); move(s, 0, 0);
    fire(s.edgeSensorDwellTimer);
    CHECK(s.edgeMenuHandleArmed && !s.expanded, "the band lights the tab");
    s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - 20, 540); move(s, 0, 0);
    CHECK(s.edgeMenuHandleArmed && !s.expanded, "pulling back onto the lit tab keeps it lit");
    CHECK([s expandEdgeMenuForLocalClickAtCurrentPointer] && s.expanded,
          "the click that follows the light opens the bar where the player was shown it");
    [s deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:NO];
    s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - 60, 540); move(s, 0, 0);
    CHECK(!s.edgeMenuHandleArmed, "leaving the tab puts the light out");
    s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - 25, 540); move(s, 0, 0);
    CHECK(!s.edgeMenuHandleArmed && ![s expandEdgeMenuForLocalClickAtCurrentPointer],
          "a deeper point can neither re-light the tab nor open the bar without the band");

    // How deep a click may reach is a measurement, not a feeling: the drawn tab, the 2pt
    // of air it floats on, and 2pt of tolerance. Past that the press belongs to whatever
    // sits on the seam -- a HUD, a taskbar -- which used to open the bar instead.
    {
        CGFloat depth = MLEdgeMenuHandleIdleThickness + 2.0 + MLEdgeMenuHandleHitSlop;
        CGFloat litDepth = MLEdgeMenuHandleArmedThickness + 2.0 + MLEdgeMenuHandleHitSlop;
        s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
        [s releaseInputToLocalControlWithCode:@"test" reason:@"explicit"];
        s.edgeSensorIgnoreMotionUntilMs = 0;
        s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - depth + 1, 540);
        CHECK([s expandEdgeMenuForLocalClickAtCurrentPointer] && s.expanded,
              "a click on the idle tab itself opens the bar");
        [s deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:NO];
        s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - depth - 1, 540);
        CHECK(![s expandEdgeMenuForLocalClickAtCurrentPointer] && !s.expanded,
              "a click just inside the drawn tab belongs to the game, not to the bar");
        s.edgeMenuHandleArmed = YES;
        s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - litDepth - 1, 540);
        CHECK(![s expandEdgeMenuForLocalClickAtCurrentPointer],
              "arming widens the target to the tab it draws and not beyond it");
        s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - litDepth + 1, 540);
        CHECK([s expandEdgeMenuForLocalClickAtCurrentPointer],
              "the lit tab is clickable across the width the player was shown");
    }

    // Geometry has only ever been measured on one nearly-square window on the main display.
    // The panel (screen coordinates), the visible tab (view bounds) and the activation band
    // come from three different functions, and the placement depends on a ratio the player
    // changes by dragging. A disagreement between them is what "it answered twice and then
    // stopped after I moved it" reports look like, and no case below duplicates the 1920x1080
    // centred one. These are the production rectangles, not a model of them.
    {
        NSRect windows[] = { NSMakeRect(0,0,1920,1080), NSMakeRect(0,0,1000,375),
                             NSMakeRect(0,0,375,1000), NSMakeRect(0,0,320,60) };
        for (int w = 0; w < 4; w++) for (int edge = 1; edge <= 4; edge++) {
            s = fresh((MLFreeMouseExitEdge)edge);
            s.view.bounds = windows[w];
            NSRect tab = [s edgeMenuVisibleHandleRectInBounds:windows[w]];
            NSRect band = [s edgeSensorActivationRectInBounds:windows[w]];
            NSRect overlap = NSIntersectionRect(tab, band);
            CHECK(!NSIsEmptyRect(tab) && !NSIsEmptyRect(band) && overlap.size.width > 0.5 && overlap.size.height > 0.5,
                  "every edge of every window size has a tab, a band, and the band sits on the tab");
            BOOL vertical = (edge == MLFreeMouseExitEdgeLeft || edge == MLFreeMouseExitEdgeRight);
            CGFloat tabCentre = vertical ? NSMidY(tab) : NSMidX(tab);
            CGFloat bandCentre = vertical ? NSMidY(band) : NSMidX(band);
            CHECK(fabs(tabCentre - bandCentre) <= 0.6,
                  "the band is centred on the tab it lights at this window size and edge");
            CHECK(NSMinX(tab) >= NSMinX(windows[w]) - 0.5 && NSMaxX(tab) <= NSMaxX(windows[w]) + 0.5 &&
                  NSMinY(tab) >= NSMinY(windows[w]) - 0.5 && NSMaxY(tab) <= NSMaxY(windows[w]) + 0.5,
                  "the click target never leaves the window it belongs to");
        }
    }

    // Dragging is a placement change, not a new control: band, tab and panel must all follow,
    // and the light has to come back at the new place. This is the automated half of the
    // acceptance item "docked on each of the four edges, and re-triggers after a drag".
    {
        s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
        NSRect before = [s edgeMenuVisibleHandleRectInBounds:s.view.bounds];
        // A drag can only happen while the bar holds the pointer, which in a game session
        // means the pointer has been handed over. Modeling the drag any other way asked the
        // sensor to light a tab in a state the app can never be in, and the answer it got
        // ("it never lights again") was an artifact of that impossible state.
        CHECK([s openEdgeMenuDockForControlCenterShortcut] && !s.isMouseCaptured,
              "opening the bar hands the pointer over before anything can be dragged");
        [s handleEdgeMenuButtonDragWithState:NSGestureRecognizerStateBegan translation:NSZeroPoint];
        [s handleEdgeMenuButtonDragWithState:NSGestureRecognizerStateChanged translation:NSMakePoint(0, -400)];
        [s handleEdgeMenuButtonDragWithState:NSGestureRecognizerStateEnded translation:NSZeroPoint];
        CHECK(fabs(NSMidY([s edgeMenuVisibleHandleRectInBounds:s.view.bounds]) - NSMidY(before)) > 100.0,
              "a real drag through the handler moves the tab");
        CHECK(s.edgeMenuDockEdge == MLFreeMouseExitEdgeRight,
              "dragging along the edge re-parks the tab on the edge it was docked to");
        [s deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:NO];
        s.edgeSensorIgnoreMotionUntilMs = 0;
        s.suppressFreeMouseEdgeUncaptureUntilMs = 0;
        NSRect after = [s edgeMenuVisibleHandleRectInBounds:s.view.bounds];
        NSRect band = [s edgeSensorActivationRectInBounds:s.view.bounds];
        CHECK(fabs(NSMidY(band) - NSMidY(after)) <= 0.6, "the activation band follows the dragged tab");
        NSRect anchor = NSMakeRect(-1900.0, 320.0, 1920.0, 1080.0);   // second display, left of main
        NSRect panel = [s collapsedFrameForEdgeMenuPanelInScreenRect:anchor];
        CGFloat onScreen = NSMidY(NSIntersectionRect(panel, anchor));
        CHECK(fabs((onScreen - NSMinY(anchor)) - NSMidY(after)) <= 0.6,
              "the panel is put where the tab is measured, even on a display with a negative origin");
        // A bar that closed under the pointer is not allowed to re-light from the resting
        // position it left the pointer in (edgeSensorMustLeaveHoverRegion), so the honest
        // sequence is the one the acceptance item describes: leave the band, come back.
        s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - 300, 540); move(s, 0, 0);
        CHECK(!s.edgeMenuHandleArmed, "leaving the band after a drag answers nothing");
        s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - 2, NSMidY(after)); move(s, 0, 0);
        CHECK(s.edgeSensorDwellTimer != nil, "returning to the dragged tab starts a dwell");
        CHECK(!s.edgeSensorMustLeaveHoverRegion, "leaving the band opened the leave-before-dwell latch");
        CHECK(!s.edgeMenuButtonExpanded, "the bar is collapsed again after the drag");
        fire(s.edgeSensorDwellTimer);
        CHECK(s.edgeMenuHandleArmed && !s.expanded, "the dragged tab lights again where it now is");
        s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - 2, NSMidY(before)); move(s, 0, 0);
        CHECK(!s.edgeMenuHandleArmed, "the place the tab was dragged away from stops answering");
        // The same pointer back inside the game is a different contract. No local position
        // is authoritative there, so the tab has to stay dark instead of lighting from a
        // guessed coordinate; release the pointer or use the shortcut to get in.
        s.isMouseCaptured = YES;
        s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - 300, 540); move(s, 0, 0);
        s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - 2, NSMidY(after)); move(s, 0, 0);
        CHECK(!s.edgeSensorDwellTimer && !s.edgeMenuHandleArmed,
              "a locked game pointer cannot light the dragged tab from a guessed position");
    }

    // The way back belongs to a bar the pointer holds, which is what a keyboard summon
    // buys in a locked session. Ten repeats per edge, same reason as above.
    for (int edge = 1; edge <= 4; edge++) for (int cycle = 0; cycle < 10; cycle++) {
        s = fresh(edge); s.isRemoteDesktopMode = NO; s.wire = [NSMutableArray array];
        CHECK([s openEdgeMenuDockForControlCenterShortcut] && s.expanded && s.edgeMenuTemporaryReleaseActive,
              "the keyboard summon still hands the pointer to the bar");
        s.systemPoint = NSMakePoint(edge == MLFreeMouseExitEdgeLeft ? NSMaxX(s.view.bounds)-1 : NSMinX(s.view.bounds)+1,
                                    edge == MLFreeMouseExitEdgeBottom ? NSMaxY(s.view.bounds)-1 : NSMinY(s.view.bounds)+1);
        [s handleEdgeMenuTemporaryReleaseForEvent:nil];
        NSTimer *deadline = s.edgeMenuAutoCollapseTimer;
        [s handleEdgeMenuTemporaryReleaseForEvent:nil];
        CHECK(s.expanded && deadline == s.edgeMenuAutoCollapseTimer, "movement neither collapses immediately nor restarts the grace deadline");
        fire(deadline);
        CHECK(!s.expanded && s.isMouseCaptured && !s.edgeMenuTemporaryReleaseActive, "grace completion returns captured input exactly once");
        CHECK(s.edgeMenuPanel.ignoresMouseEvents, "collapsed transparent panel cannot swallow stream clicks");
    }
    s=fresh(MLFreeMouseExitEdgeRight); s.systemPoint=NSMakePoint(1918,540);
    move(s,0,0);
    [[NSRunLoop currentRunLoop] runMode:NSEventTrackingRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.3]];
    CHECK(s.edgeMenuHandleArmed, "native event-tracking mode does not suspend dwell");
    s=fresh(MLFreeMouseExitEdgeRight); s.systemPoint=NSMakePoint(1918,540); move(s,0,0);
    NSTimer *obsolete=s.edgeSensorDwellTimer;
    s.view.bounds=NSMakeRect(0,0,1280,720); fire(obsolete);
    CHECK(!s.expanded && !s.edgeMenuHandleArmed, "resizing invalidates geometry captured by a dwell");
    s=fresh(MLFreeMouseExitEdgeRight); s.systemPoint=NSMakePoint(1918,540); move(s,0,0); obsolete=s.edgeSensorDwellTimer;
    [s transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden]; fire(obsolete);
    CHECK(!s.expanded && !s.edgeSensorDwellTimer && !s.edgeMenuAutoCollapseTimer && !s.edgeMenuHandleArmed,
          "hidden lifecycle cancels all pending work and every light it left on");
    for (int blocker=0; blocker<5; blocker++) {
        s=fresh(MLFreeMouseExitEdgeRight); s.systemPoint=NSMakePoint(1918,540); move(s,0,0);
        if(blocker==0)s.buttons=YES;
        if(blocker==1)s.visible=NO;
        if(blocker==2)s.stopStreamInProgress=YES;
        if(blocker==3)s.reconnectInProgress=YES;
        if(blocker==4)s.edgeSensorSummonEnabled=NO;
        fire(s.edgeSensorDwellTimer);
        CHECK(!s.expanded && !s.edgeMenuHandleArmed && s.isMouseCaptured,
              "timeout revalidates buttons, focus/visibility, stop, reconnect and preference");
    }
    s=fresh(MLFreeMouseExitEdgeRight); s.systemPoint=NSMakePoint(NAN,540); move(s,1000,0);
    CHECK(!s.edgeSensorDwellTimer, "nonfinite coordinate cannot arm");
    s.systemPoint=NSMakePoint(1921,540); move(s,0,0);
    CHECK(!s.edgeSensorDwellTimer, "pointer on another display cannot arm");
    s=fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode=NO; s.systemPoint=NSMakePoint(1918,540);
    for(int i=0;i<100;i++)move(s,1000,0);
    CHECK(!s.edgeSensorDwellTimer && s.isMouseCaptured && !s.expanded, "locked game motion never invents a remote cursor");
    CHECK(!s.edgeMenuHandleArmed, "locked motion never lights a tab the player could not click");
    {
        // A lit tab has to be clickable wherever a lit tab is allowed to exist. Remote desktop
        // mode keeps the capture bookkeeping on while the local pointer stays authoritative --
        // that is exactly why arrival may light the tab there -- so a press that lands on the
        // drawn tab belongs to the tab. Forwarding it sent the player's click to the host at a
        // spot they had aimed at our own UI, which is the "it lit up but the click did nothing"
        // report in the one mode where hovering works at all.
        Sensor *d = fresh(MLFreeMouseExitEdgeRight); d.systemPoint = NSMakePoint(1918, 540); move(d, 0, 0);
        CHECK(d.isMouseCaptured && d.isRemoteDesktopMode,
              "desktop mode keeps capture on while the local pointer is still authoritative");
        fire(d.edgeSensorDwellTimer);
        CHECK(d.edgeMenuHandleArmed, "desktop mode lights the tab while capture is on");
        CHECK([d expandEdgeMenuForLocalClickAtCurrentPointer] && d.expanded,
              "a click on the lit tab opens the bar in desktop mode too");
        CHECK(d.edgeMenuClickConsumedLocally,
              "the matching release is swallowed with the press that opened the bar");
    }

    [s releaseInputToLocalControlWithCode:@"test" reason:@"explicit"];
    s.edgeSensorIgnoreMotionUntilMs=0; move(s,0,0); fire(s.edgeSensorDwellTimer);
    CHECK(s.edgeMenuHandleArmed && s.userReleasedInput && !s.expanded,
          "released game mode lights the tab without promising a bar it did not open");
    CHECK([s expandEdgeMenuForLocalClickAtCurrentPointer] && s.expanded && !s.edgeMenuTemporaryReleaseActive,
          "the released player opens the bar with a click, still without automatic recapture");
    s.systemPoint=NSMakePoint(1000,500); [s handleEdgeMenuTemporaryReleaseForEvent:nil]; fire(s.edgeMenuAutoCollapseTimer);
    CHECK(!s.isMouseCaptured && s.userReleasedInput, "collapse respects persistent user release");
    [s resumeInputForExplicitStreamClick:nil];
    CHECK(s.isMouseCaptured && !s.userReleasedInput, "explicit click resumes game after closing controls");
    s=fresh(MLFreeMouseExitEdgeRight); s.systemPoint=NSMakePoint(1918,540); move(s,0,0); fire(s.edgeSensorDwellTimer);
    [s activateEdgeMenuDockForExitEdge:MLFreeMouseExitEdgeRight];
    [s deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:YES]; s.edgeSensorIgnoreMotionUntilMs=0;
    move(s,0,0);
    CHECK(!s.edgeSensorDwellTimer, "dismiss over activation region requires exit and reentry");
    s.systemPoint=NSMakePoint(1800,540); move(s,0,0); s.systemPoint=NSMakePoint(1918,540); move(s,0,0);
    CHECK(s.edgeSensorDwellTimer.isValid, "leaving and reentering reliably rearms");
    fire(s.edgeSensorDwellTimer);
    CHECK(s.edgeMenuHandleArmed && s.isMouseCaptured, "arrival offers the tab and still keeps the pointer in the game");
    [s openEdgeMenuDockForControlCenterShortcut];
    CHECK(s.expanded && s.edgeMenuTemporaryReleaseActive, "the keyboard takes the bar the lit tab was offering");
    s.systemPoint=NSMakePoint(2000,540); [s handleEdgeMenuTemporaryReleaseForEvent:nil]; fire(s.edgeMenuAutoCollapseTimer);
    CHECK(!s.isMouseCaptured && !s.expanded, "leaving onto another display cannot warp or capture the pointer back");
    for(int phase=MLEdgeMenuPhaseExpanded;phase<=MLEdgeMenuPhaseDragging;phase++) {
        s=fresh(MLFreeMouseExitEdgeRight); s.isMouseCaptured=NO;
        [s transitionEdgeMenuToPhase:phase];
        [s captureMouse];
        CHECK(!s.isMouseCaptured, "expanded, menu and drag states exclusively own local pointer");
        CHECK(s.edgeMenuMenuVisible == (phase==MLEdgeMenuPhaseMenu) && s.edgeMenuDragging == (phase==MLEdgeMenuPhaseDragging), "menu and drag cannot coexist");
    }
    // Exercise the real menu transaction with a nested-loop stand-in. No menu
    // is displayed; callbacks mimic actions occurring while native tracking runs.
    for (int invalidated=0;invalidated<3;invalidated++) {
        s=fresh(MLFreeMouseExitEdgeRight);
        ProbeMenu *menu=[ProbeMenu new]; s.streamMenu=menu;
        __weak Sensor *weak=s;
        __block BOOL localDuringMenu=NO;
        menu.onTrack=^{
            Sensor *owner=weak;
            localDuringMenu=owner.edgeMenuMenuVisible && !owner.isMouseCaptured && [owner edgeMenuOwnsPointer] &&
                NSEqualRects(owner.edgeMenuPanel.frame,[owner expandedFrameForEdgeMenuButtonInBounds:owner.view.bounds]);
            if(invalidated==1) [owner transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
            if(invalidated==2) owner.visible=NO;
        };
        [s presentStreamMenuFromView:s.edgeMenuButton event:nil];
        CHECK(localDuringMenu, "native menu transaction releases capture and owns pointer during nested loop");
        if(invalidated) {
            CHECK(s.edgeMenuPhase==MLEdgeMenuPhaseHidden && !s.edgeMenuAutoCollapseTimer,
                  "obsolete menu completion cannot reopen a hidden lifecycle");
            CHECK(menu.cancellations==1, "hiding cancels native menu tracking once");
        } else {
            CHECK(s.expanded && s.edgeMenuTemporaryReleaseActive, "menu preserves captured-before-open return intent");
            fire(s.edgeMenuAutoCollapseTimer);
            CHECK(s.isMouseCaptured && !s.expanded, "menu grace completion restores input");
        }
    }
    s=fresh(MLFreeMouseExitEdgeRight);
    ProbeMenu *reentrantMenu=[ProbeMenu new]; s.streamMenu=reentrantMenu;
    __weak Sensor *reentrantOwner=s;
    reentrantMenu.onTrack=^{
        Sensor *owner=reentrantOwner;
        [owner presentStreamMenuFromView:owner.edgeMenuButton event:nil];
    };
    [s presentStreamMenuFromView:s.edgeMenuButton event:nil];
    CHECK(s.menuRebuilds==1, "reentrant menu request must not rebuild the menu being tracked");

    s=fresh(MLFreeMouseExitEdgeRight); s.isMouseCaptured=NO;
    [s setEdgeMenuButtonExpanded:YES animated:NO];
    [s handleEdgeMenuButtonDragWithState:NSGestureRecognizerStateBegan translation:NSZeroPoint];
    [s transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
    [s setEdgeMenuButtonExpanded:NO animated:NO];
    NSRect settledFrame=s.edgeMenuPanel.frame;
    NSUInteger settledToken=s.edgeMenuLifecycleToken;
    [s handleEdgeMenuButtonDragWithState:NSGestureRecognizerStateChanged translation:NSMakePoint(-500,200)];
    [s handleEdgeMenuButtonDragWithState:NSGestureRecognizerStateEnded translation:NSZeroPoint];
    CHECK(s.edgeMenuPhase==MLEdgeMenuPhaseCollapsed && NSEqualRects(settledFrame,s.edgeMenuPanel.frame) && s.edgeMenuLifecycleToken==settledToken,
          "late drag callbacks after hide and reshow cannot move or expand the dock");
    [s handleEdgeMenuButtonDragWithState:NSGestureRecognizerStateBegan translation:NSZeroPoint];
    CHECK(s.edgeMenuPhase==MLEdgeMenuPhaseCollapsed, "collapsed pass-through dock cannot begin dragging");

    [s transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
    NSUInteger hiddenToken=s.edgeMenuLifecycleToken;
    [s transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
    CHECK(s.edgeMenuLifecycleToken!=hiddenToken, "repeated lifecycle teardown invalidates queued work even when already hidden");
    for(int edge=1;edge<=4;edge++) {
        s=fresh(edge); s.isMouseCaptured=NO;
        [s setEdgeMenuButtonExpanded:YES animated:NO];
        s.edgeMenuTemporaryReleaseActive=YES;
        [s handleEdgeMenuButtonDragWithState:NSGestureRecognizerStateBegan translation:NSZeroPoint];
        CHECK(s.edgeMenuDragging && [s edgeMenuOwnsPointer], "native handle drag enters exclusive local ownership");
        [s handleEdgeMenuButtonDragWithState:NSGestureRecognizerStateChanged translation:NSMakePoint(100000,-100000)];
        CHECK(NSContainsRect(s.view.bounds,s.edgeMenuPanel.frame), "drag is clamped to local bounds");
        [s handleEdgeMenuButtonDragWithState:NSGestureRecognizerStateCancelled translation:NSZeroPoint];
        CHECK(!s.edgeMenuDragging && s.expanded && s.edgeMenuButtonEdgeRatio>=0 && s.edgeMenuButtonEdgeRatio<=1,
              "cancelled drag settles at valid dock without stale dragging state");
        [s transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
        [s handleEdgeMenuButtonDragWithState:NSGestureRecognizerStateEnded translation:NSZeroPoint];
        CHECK(s.edgeMenuPhase==MLEdgeMenuPhaseHidden, "late mouse-up after teardown cannot revive controls");
    }
    s=fresh(MLFreeMouseExitEdgeRight); s.userReleasedInput=YES; s.isMouseCaptured=NO;
    s.systemPoint=NSMakePoint(1800,540); [s resumeInputForExplicitStreamClick:nil];
    CHECK(s.isMouseCaptured && !s.userReleasedInput, "a click clear of the visible tab still resumes the game");

    // The reported menu loop: a dock release followed by right presses without
    // an intervening move must hand off before the very first DOWN.
    Motion *click = [Motion new]; click.buttonNumber = 1;
    for (int remote = 0; remote < 2; remote++) {
        for (int explicitRelease = 0; explicitRelease < 2; explicitRelease++) {
            s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = remote;
            s.wire = [NSMutableArray array];
            for (int cycle = 0; cycle < 30; cycle++) {
                s.isMouseCaptured = NO;
                s.edgeMenuTemporaryReleaseActive = YES; [s transitionEdgeMenuToPhase:MLEdgeMenuPhaseExpanded];
                s.userReleasedInput = explicitRelease;
                s.systemPoint = NSMakePoint(1000, 500);
                [s rightMouseDown:(NSEvent *)click];
                CHECK(s.isMouseCaptured && !s.userReleasedInput && !s.edgeMenuTemporaryReleaseActive,
                      "right press resumes both temporary and explicit release");
                CHECK([s.wire.lastObject isEqual:@"3D"], "first right DOWN reaches host before any release");
                [s rightMouseUp:(NSEvent *)click];
                CHECK(s.wire.count == (cycle+1)*2 && [s.wire.lastObject isEqual:@"3U"] && s.menuOpens == 0,
                      "repeated right click delivers pairs without opening a local menu");
            }
            [s releaseInputToLocalControlWithCode:@"test" reason:@"user"];
            s.systemPoint = NSMakePoint(1000, 500);
            [s otherMouseDown:(NSEvent *)click]; [s otherMouseUp:(NSEvent *)click];
            CHECK(s.isMouseCaptured && [s.wire.lastObject isEqual:@"2U"], "middle button also resumes with a complete pair");
        }
        s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = remote;
        s.wire = [NSMutableArray array]; s.isMouseCaptured = NO; s.edgeMenuTemporaryReleaseActive = YES; [s transitionEdgeMenuToPhase:MLEdgeMenuPhaseExpanded];
        s.systemPoint = NSMakePoint(1900, 540);
        [s rightMouseDown:(NSEvent *)click]; [s rightMouseUp:(NSEvent *)click];
        CHECK(!s.isMouseCaptured && s.wire.count == 0 && s.menuOpens == 0,
              "control hit area does not send clicks into the host or open a view menu");
        s.systemPoint = NSMakePoint(1000, 500); s.captureAllowed = NO;
        [s rightMouseDown:(NSEvent *)click]; [s rightMouseUp:(NSEvent *)click];
        CHECK(s.wire.count == 0 && s.menuOpens == 0, "failed capture neither invents a click nor opens a menu");
        s.userReleasedInput = YES; s.captureAllowed = YES; [s transitionEdgeMenuToPhase:MLEdgeMenuPhaseMenu];
        [s rightMouseDown:(NSEvent *)click];
        CHECK(s.userReleasedInput && !s.isMouseCaptured, "tracking menu retains local ownership");
        [s transitionEdgeMenuToPhase:MLEdgeMenuPhaseDragging];
        [s rightMouseDown:(NSEvent *)click];
        CHECK(s.userReleasedInput && !s.isMouseCaptured, "control drag retains local ownership");
    }

    // Execute the actual modifier-only dispatch_after branch with configurable
    // combinations, including the user's Shift+Option. Never post desktop input.
    for (int useShift = 0; useShift < 2; useShift++) {
        s = fresh(MLFreeMouseExitEdgeRight);
        s.releaseShortcut = [StreamShortcut new]; s.releaseShortcut.modifierOnly = YES;
        s.physicalModifiers = s.releaseShortcut.modifierFlags = NSEventModifierFlagOption |
            (useShift ? NSEventModifierFlagShift : NSEventModifierFlagControl);
        Motion *m = [Motion new]; m.modifierFlags = s.physicalModifiers;
        [s handleModifierOnlyReleaseShortcut:(NSEvent *)m]; waitForDwell();
        CHECK(s.userReleasedInput && !s.isMouseCaptured, "configured modifier-only escape actually fires");
        s.userReleasedInput = NO; s.isMouseCaptured = YES;
        [s handleModifierOnlyReleaseShortcut:(NSEvent *)m];
        s.pendingOptionUncaptureToken++; // A following letter/action cancels the modifier-only chord.
        waitForDwell();
        CHECK(!s.userReleasedInput && s.isMouseCaptured, "a keyed shortcut cannot also detach input");
        [s handleModifierOnlyReleaseShortcut:(NSEvent *)m]; s.physicalModifiers = 0;
        waitForDwell();
        CHECK(!s.userReleasedInput, "releasing the modifiers before dwell cancels escape");
        s.physicalModifiers = m.modifierFlags;
        [s handleModifierOnlyReleaseShortcut:(NSEvent *)m];
        Motion *up = [Motion new]; up.modifierFlags = 0; s.physicalModifiers = 0;
        [s handleModifierOnlyReleaseShortcut:(NSEvent *)up];
        CHECK(s.userReleasedInput && !s.isMouseCaptured, "quick modifier chord tap releases without needing a hold");
        s.userReleasedInput = NO; s.isMouseCaptured = YES;
        [s handleModifierOnlyReleaseShortcut:(NSEvent *)m]; s.pendingOptionUncaptureToken++;
        [s handleModifierOnlyReleaseShortcut:(NSEvent *)up];
        CHECK(!s.userReleasedInput, "key press cancels release on modifier key-up too");

    }

    // Locked mode has no pointer entry, and this is the contract that replaced the slam
    // gesture. The gesture completed on out-48pt / back-24pt / out-48pt inside 1.5s, which
    // is what aiming at moving targets looks like in a real game, and every completion took
    // the pointer out of the player's hands. The schedules below are exactly the sequences
    // that used to open the bar; none of them may do anything now but leave the pointer in
    // the game. Deleting the gesture is not a test convenience: it is the user report.
    double toward[][2] = {{-60,0},{60,0},{0,60},{0,-60}};   // left, right, top, bottom
    for (int edge = 1; edge <= 4; edge++) {
        s = fresh(edge); s.isRemoteDesktopMode = NO;
        for (int stroke = 0; stroke < 2; stroke++) {
            for (int k = 0; k < 3; k++) move(s, toward[edge-1][0]/3, toward[edge-1][1]/3);
            move(s, -toward[edge-1][0]/4, -toward[edge-1][1]/4);
            move(s, -toward[edge-1][0]/4, -toward[edge-1][1]/4);
        }
        CHECK(!s.expanded && s.isMouseCaptured && !s.edgeMenuTemporaryReleaseActive,
              "two slams at the docked edge never take the pointer in a locked game");
        CHECK(!s.edgeMenuHandleArmed, "a locked slam never lights a tab it cannot be clicked on");
        CHECK(!s.isRemoteDesktopMode, "locked motion never switches the host out of game mode");
    }
    // Thirty repeats of the old gesture: the failure the player reported was the first hit
    // working and later ones firing on their own, so both directions are pinned.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int cycle = 0; cycle < 30; cycle++) {
        for (int stroke = 0; stroke < 2; stroke++) {
            for (int k = 0; k < 3; k++) move(s, 20, 0);
            move(s, -15, 0); move(s, -15, 0);
        }
        CHECK(!s.expanded && s.isMouseCaptured, "thirtieth slam still leaves the pointer in the game");
    }
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int i = 0; i < 300; i++) move(s, 1, 0);
    CHECK(!s.expanded && s.isMouseCaptured, "slow drift cannot summon anything in a locked game");
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int i = 0; i < 300; i++) move(s, (i % 2) ? 10 : -10, 0);
    CHECK(!s.expanded && s.isMouseCaptured, "play jitter cannot summon anything in a locked game");
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int stroke = 0; stroke < 4; stroke++) {
        for (int k = 0; k < 3; k++) move(s, 0, 20);
        move(s, 0, -15); move(s, 0, -15);
    }
    CHECK(!s.expanded && s.isMouseCaptured, "vertical play cannot open a horizontal dock");
    // The timed schedules: the one that completed inside the old 1400ms budget, the one
    // that paused to re-aim inside the idle gap, and the one that stalled past it.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int k = 0; k < 3; k++) moveAt(s, 2000 + 300 * k, 20, 0);
    moveAt(s, 2700, -15, 0); moveAt(s, 2800, -15, 0);
    for (int k = 0; k < 3; k++) moveAt(s, 3100 + 100 * k, 20, 0);
    CHECK(!s.expanded && s.isMouseCaptured, "the schedule that used to complete the gesture is inert");
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int k = 0; k < 3; k++) moveAt(s, 4000 + 400 * k, 20, 0);
    moveAt(s, 4900, -15, 0); moveAt(s, 5000, -15, 0);
    for (int k = 0; k < 3; k++) moveAt(s, 5400 + 200 * k, 20, 0);
    CHECK(!s.expanded && s.isMouseCaptured, "a second attempt after a pause is inert too");
    // A held button is the ordinary state of a game: it must be as inert as a released one.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO; s.buttons = YES;
    for (int stroke = 0; stroke < 2; stroke++) {
        for (int k = 0; k < 3; k++) move(s, 20, 0);
        move(s, -15, 0); move(s, -15, 0);
    }
    CHECK(!s.expanded && s.isMouseCaptured, "a held button cannot open the bar either");
    // And the freed pointer still works: releasing, not flicking, is what makes the tab
    // reachable, so the negative contract above must not have cost the positive one.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    [s releaseInputToLocalControlWithCode:@"test" reason:@"explicit"];
    s.edgeSensorIgnoreMotionUntilMs = 0;
    s.systemPoint = NSMakePoint(1918, 540); move(s, 0, 0);
    fire(s.edgeSensorDwellTimer);
    CHECK(s.edgeMenuHandleArmed && s.userReleasedInput && !s.expanded,
          "the freed pointer still lights the tab after the gesture is gone");
    CHECK([s expandEdgeMenuForLocalClickAtCurrentPointer] && s.expanded,
          "a click on the lit tab is still how a freed player opens the bar");

    // A refused sensor has to say why. The field log for the failing session contained
    // no sensor line at all, which is the reason the report could not be diagnosed.
    [ProbeLog reset];
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO; s.visible = NO;
    move(s, 40, 0);
    CHECK([ProbeLog countMatching:@"Edge sensor refused: reason=cannot-interact"] == 1,
          "the gate that keeps the bar away names itself in the log");
    for (int i = 0; i < 300; i++) move(s, 40, 0);
    CHECK([ProbeLog countMatching:@"Edge sensor refused"] == 1,
          "the refusal is named once a second, not once a motion sample");
    [ProbeLog reset];
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO; s.buttons = YES;
    move(s, 40, 0);
    CHECK([ProbeLog countMatching:@"reason=button-held"] == 1,
          "a held mouse button names itself instead of swallowing the gesture silently");

    [ProbeLog reset];
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int k = 0; k < 3; k++) move(s, 20, 0);   // armed and allowed: the sensor acts
    CHECK([ProbeLog countMatching:@"Edge sensor refused"] == 0, "an armed sensor keeps the log quiet");

    [ProbeLog reset];
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    [s openEdgeMenuDockForControlCenterShortcut];
    for (int k = 0; k < 3; k++) move(s, 20, 0);   // motion over an open bar
    CHECK([ProbeLog countMatching:@"Edge sensor refused"] == 0, "an open bar is not logged as a refusal");

    // Locked mode has no pointer to hover, so the keyboard must take the dock itself.
    // The panel is deliberately off screen: the sidebar may not depend on it.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    s.wire = [NSMutableArray array]; s.edgeMenuPanel.isVisible = NO; s.isMouseCaptured = YES;
    CHECK([s openEdgeMenuDockForControlCenterShortcut] && s.expanded && !s.isMouseCaptured &&
          s.edgeMenuTemporaryReleaseActive && [s.wire count] == 0,
          "the control-center shortcut opens the sidebar itself in locked mode, with nothing sent to the host");
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO; s.visible = NO;
    CHECK(![s openEdgeMenuDockForControlCenterShortcut] && !s.expanded && s.isMouseCaptured,
          "the shortcut cannot open a control bar the window refused to show");
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO; s.buttons = YES;
    CHECK(![s openEdgeMenuDockForControlCenterShortcut] && !s.expanded && s.isMouseCaptured,
          "a held mouse button is not interrupted by the keyboard entry");

    // Clicking the visible collapsed tab opens the controls instead of leaking a click.
    s = fresh(MLFreeMouseExitEdgeRight); s.isMouseCaptured = NO; s.isRemoteDesktopMode = NO;
    s.wire = [NSMutableArray array];
    NSRect tab = [s edgeMenuVisibleHandleRectInBounds:s.view.bounds];
    s.systemPoint = NSMakePoint(NSMidX(tab), NSMidY(tab));
    CHECK(s.edgeMenuButton.armedAppearance == NO, "a click without arrival still finds the tab to press");
    Motion *tabMotion = [Motion new]; NSEvent *tabClick = (NSEvent *)tabMotion;
    [s mouseDown:tabClick];
    CHECK(s.expanded && s.edgeMenuClickConsumedLocally && !s.isMouseCaptured && [s.wire count] == 0,
          "a released-mode click on the tab opens controls and sends nothing to the host");
    [s mouseUp:tabClick];
    CHECK(!s.edgeMenuClickConsumedLocally && s.expanded && [s.wire count] == 0,
          "the consumed press's release never reaches the host either");
    // The panel is wider than the tab it shows. A press on the part of it that was
    // never drawn belongs to the game, which is the half of "it fires on its own"
    // that no arrival test can see.
    s = fresh(MLFreeMouseExitEdgeRight); s.isMouseCaptured = NO; s.isRemoteDesktopMode = NO;
    s.wire = [NSMutableArray array];
    NSRect box = [s edgeMenuInteractionRectInBounds:s.view.bounds];
    NSRect hiddenPart = [s edgeMenuVisibleHandleRectInBounds:s.view.bounds];
    s.systemPoint = NSMakePoint(NSMinX(box) + 1, NSMidY(box));
    CHECK(NSPointInRect(s.systemPoint, box) && !NSPointInRect(s.systemPoint, hiddenPart),
          "the click outside the tab is aimed inside the panel and outside the drawing");
    [s mouseDown:tabClick];
    [s mouseUp:tabClick];
    CHECK(!s.expanded && !s.edgeMenuClickConsumedLocally && s.isMouseCaptured && [s.wire count] == 2,
          "a click on the undrawn part of the dock stays a game click in both directions");
    s = fresh(MLFreeMouseExitEdgeRight); s.isMouseCaptured = NO; s.isRemoteDesktopMode = NO;
    s.wire = [NSMutableArray array];
    s.systemPoint = NSMakePoint(960, 540);
    [s mouseDown:tabClick];
    [s mouseUp:tabClick];
    CHECK(s.isMouseCaptured && !s.expanded && [s.wire count] == 2,
          "ordinary stream clicks still capture and forward their button pair");

    // A summon the pointer is already resting on must not schedule its own dismissal:
    // stopping still is what a player does after they hover, and the bar disappearing
    // under a still pointer is the same "it opened and then it did nothing" report.
    s = fresh(MLFreeMouseExitEdgeRight);
    s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - 6, NSMidY(s.view.bounds));
    s.edgeSensorIgnoreMotionUntilMs = 0;
    move(s, 0, 0);
    fire(s.edgeSensorDwellTimer);
    [s activateEdgeMenuDockForExitEdge:MLFreeMouseExitEdgeRight];
    CHECK(s.expanded && s.edgeMenuPointerHasVisited && !s.edgeMenuAutoCollapseTimer.isValid,
          "a bar the pointer is resting on waits for the pointer to leave, not for a clock");

    // A bar that was called out still has to find its way back, and the player who
    // repeats the entry must not be refused because the first one is still on screen.
    // This is the failure the field log showed: eight presses, four openings, and a bar
    // that never came down because nothing in a locked session moves the local pointer.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO; s.wire = [NSMutableArray array];
    s.systemPoint = NSMakePoint(960, 540);              // where locked mode parks the pointer
    [ProbeLog reset];
    CHECK([s openEdgeMenuDockForControlCenterShortcut] && s.expanded,
          "the keyboard entry opens the bar from the centre of the screen");
    CHECK(s.edgeMenuAutoCollapseTimer.isValid,
          "a bar the pointer never touched is scheduled to go back the moment it came out");
    CHECK(!s.edgeMenuPointerHasVisited, "one stay on screen starts with no visit recorded");
    CHECK([ProbeLog countMatching:@"Edge controls returned to stream"] == 0,
          "a bar that has not gone back yet does not claim to have gone back");
    fire(s.edgeMenuAutoCollapseTimer);
    CHECK(!s.expanded && s.isMouseCaptured && !s.edgeMenuTemporaryReleaseActive && [s.wire count] == 0,
          "the summon grace ends with the pointer back in the game, once, and nothing sent");
    CHECK([ProbeLog countMatching:@"Edge controls returned to stream"] == 1,
          "the return to the stream is one named line in the log beside the opening");
    CHECK([ProbeLog countMatching:@"grace=2500ms"] == 1,
          "the wait it chose was the summon grace, not the 450ms hover grace");

    // The player who does reach the bar must not be kept waiting twice as long, and the
    // press after a return must open again rather than be refused as already-open.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO; s.wire = [NSMutableArray array];
    s.systemPoint = NSMakePoint(960, 540);
    [ProbeLog reset];
    [s openEdgeMenuDockForControlCenterShortcut];
    s.systemPoint = NSMakePoint(NSMaxX(s.view.bounds) - 6, NSMidY(s.view.bounds));  // the pointer arrives
    [s handleEdgeMenuTemporaryReleaseForEvent:nil];
    CHECK(s.edgeMenuPointerHasVisited && !s.edgeMenuAutoCollapseTimer.isValid,
          "the pointer reaching the bar cancels the wait and records the visit");
    s.systemPoint = NSMakePoint(960, 540);                                            // and leaves it
    [s handleEdgeMenuTemporaryReleaseForEvent:nil];
    fire(s.edgeMenuAutoCollapseTimer);
    CHECK(!s.expanded && s.isMouseCaptured && [ProbeLog countMatching:@"grace=450ms"] == 1,
          "a bar the pointer has been on returns on the short 450ms grace");
    s.systemPoint = NSMakePoint(960, 540);
    CHECK([s openEdgeMenuDockForControlCenterShortcut] && s.expanded &&
          s.edgeMenuAutoCollapseTimer.isValid && !s.edgeMenuPointerHasVisited,
          "the press after a return opens a fresh stay on screen instead of dying on the second use");

    // The switch has to have both sides. A bar that can only come out is a bar the player
    // has to wait out, and a second press that does nothing is how the entry got reported as
    // dead again while the log said it had opened.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO; s.wire = [NSMutableArray array];
    s.systemPoint = NSMakePoint(960, 540);
    [ProbeLog reset];
    [s openEdgeMenuDockForControlCenterShortcut];
    CHECK(s.expanded && !s.isMouseCaptured, "the first press takes the pointer for the bar");
    CHECK([s openEdgeMenuDockForControlCenterShortcut] && !s.expanded && s.isMouseCaptured &&
          !s.edgeMenuTemporaryReleaseActive && [s.wire count] == 0,
          "the same press gives the bar back and the pointer to the game without waiting for a clock");
    CHECK([ProbeLog countMatching:@"Edge controls returned to stream"] == 1,
          "the press that closes the bar reports the return like every other way of going back");
    CHECK([s openEdgeMenuDockForControlCenterShortcut] && s.expanded && !s.isMouseCaptured &&
          s.edgeMenuAutoCollapseTimer.isValid && !s.edgeMenuPointerHasVisited,
          "the press after closing opens a fresh stay on screen, so repeating the switch never dead-ends");

    // Dragging the handle is the one state where a press must not tear the bar out of the
    // pointer's hand, and must not answer with the modal menu on top of the drag either.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO; s.wire = [NSMutableArray array];
    s.systemPoint = NSMakePoint(960, 540);
    [s openEdgeMenuDockForControlCenterShortcut];
    s.edgeMenuPhase = MLEdgeMenuPhaseDragging;
    CHECK([s openEdgeMenuDockForControlCenterShortcut] && s.expanded &&
          s.edgeMenuPhase == MLEdgeMenuPhaseDragging && s.edgeMenuTemporaryReleaseActive &&
          !s.isMouseCaptured,
          "a press during a drag neither drops the bar nor gives away that the bar holds the pointer");

    // A click in the stream is the other way the bar leaves the screen, and it used to be
    // silent: that missing half of the cycle is why 18 openings read like 17 returns.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO; s.wire = [NSMutableArray array];
    s.systemPoint = NSMakePoint(960, 540);
    [ProbeLog reset];
    [s openEdgeMenuDockForControlCenterShortcut];
    Motion *streamMotion = [Motion new];
    NSEvent *streamClick = (NSEvent *)streamMotion;
    [s mouseDown:streamClick];
    [s mouseUp:streamClick];
    CHECK(!s.expanded && s.isMouseCaptured &&
          [ProbeLog countMatching:@"Edge controls returned to stream"] == 1,
          "the click that takes the pointer back also says that the bar went back");

    printf("%d runtime edge checks, %d failures\n", count, failures);
    return failures != 0;
} }
'''

def run_runtime_probe(objc, menu, internal, helpers="", self_test=False):
    signatures = [
        '- (void)resetEdgeSensorSummonState', '- (void)resetEdgeSensorPointerState',
        '- (BOOL)edgeSensorPointIsInHoverRegion:', '- (BOOL)edgeSensorPointIsOnVisibleHandle:',
        '- (void)captureMousePreservingEdgeSensorPoint:',
        '- (BOOL)captureFreeMouseIfNeededForEvent:', '- (BOOL)edgeMenuOwnsPointer', '- (void)rightMouseDown:', '- (void)rightMouseUp:',
        '- (void)otherMouseDown:', '- (void)otherMouseUp:', '- (void)handleModifierOnlyReleaseShortcut:',
        '- (void)releaseInputToLocalControlWithCode:', '- (void)resumeInputForExplicitStreamClick:',
        '- (NSPoint)edgeSensorPointForEvent:', '- (void)beginEdgeSensorDwellTimerIfNeededForEdge:',
        '- (void)armEdgeMenuHandleIfStillAtEdge:', '- (BOOL)handleEdgeSensorSummonForEvent:', '- (NSString *)edgeSensorSummonBlocker',
        '- (void)summonEdgeMenuDockForEdge:',
        '- (BOOL)expandEdgeMenuForLocalClickAtCurrentPointer', '- (void)mouseDown:', '- (void)mouseUp:',
    ]
    methods = "\n".join(method(objc, sig) for sig in signatures)
    methods += "\n" + "\n".join(method(menu, sig) for sig in (
        '- (void)presentStreamMenuFromView:(NSView *)sourceView event:',
        '- (void)handleEdgeMenuButtonDragWithState:',
        '- (void)updateEdgeMenuPointerInsideForPoint:',
        '- (BOOL)isPointInsideEdgeMenuInteractionRect:',
        '- (BOOL)edgeMenuButtonExpanded', '- (BOOL)edgeMenuDragging', '- (BOOL)edgeMenuMenuVisible',
        '- (void)transitionEdgeMenuToPhase:', '- (void)handleEdgeMenuHover', '- (NSRect)edgeSensorActivationRectInBounds:',
        '- (void)deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:', '- (void)setEdgeMenuButtonExpanded:',
        '- (NSTimeInterval)edgeMenuReturnDelay', '- (BOOL)edgeMenuPhaseIsOnScreen:',
        '- (void)cancelEdgeMenuAutoCollapse', '- (void)scheduleEdgeMenuAutoCollapse',
        '- (void)activateEdgeMenuDockForExitEdge:', '- (BOOL)handleEdgeMenuTemporaryReleaseForEvent:',
        '- (BOOL)openEdgeMenuDockForControlCenterShortcut',
        '- (BOOL)edgeMenuDockEdgeUsesVerticalAxis', '- (CGFloat)resolvedEdgeMenuCoordinateInRect:',
        '- (NSRect)edgeMenuFrameInRect:', '- (NSRect)edgeMenuInteractionRectInBounds:',
        '- (NSRect)expandedFrameForEdgeMenuButtonInBounds:',
        '- (NSRect)frameForCurrentEdgeMenuPanelStateInScreenRect:',
        '- (NSRect)collapsedFrameForEdgeMenuPanelInScreenRect:', '- (NSRect)expandedFrameForEdgeMenuPanelInScreenRect:',
        '- (NSRect)collapsedFrameForEdgeMenuButtonInBounds:', '- (CGFloat)edgeMenuHandleThickness',
        '- (NSRect)edgeMenuVisibleHandleRectInBounds:',
    ))
    enums = "\n".join(re.findall(r'typedef NS_ENUM\(NSInteger, (?:MLFreeMouseExitEdge|MLEdgeMenuPhase)\) \{.*?\};', internal, re.S))
    constants = "\n".join(re.findall(r'static (?:CGFloat|NSTimeInterval|NSUInteger) const (?:MLEdgeSensor\w+|MLEdgeMenu\w+) = .*?;', internal))
    source = HARNESS.replace('__CONSTANTS__', enums + "\n" + constants).replace('__HELPERS__', '')
    cc, sdk = clang_and_sdk('edge controls runtime')
    with tempfile.TemporaryDirectory() as tmp:
        def run(body):
            path=Path(tmp)/'edge.m'; binary=Path(tmp)/'edge'
            path.write_text(source.replace('__METHODS__',body))
            subprocess.run([cc,'-fobjc-arc','-Wall','-Werror','-Wno-unused-variable','-isysroot',sdk,'-framework','AppKit',str(path),'-o',str(binary)],check=True)
            return subprocess.run([str(binary)],capture_output=True,text=True,timeout=45)
        result=run(methods); print(result.stdout,end=''); assert result.returncode==0,result.stderr
        if self_test:
            mutations=[
                ('reentrant menu mutation', '- (void)presentStreamMenuFromView:(NSView *)sourceView event:(NSEvent *)event {', '- (void)presentStreamMenuFromView:(NSView *)sourceView event:(NSEvent *)event { [self rebuildStreamMenu];'),
                ('stale drag callbacks', '} else if (!self.edgeMenuDragging) {', '} else if (NO) {'),
                ('collapsed dock drag', 'if (self.edgeMenuPhase != MLEdgeMenuPhaseExpanded) return;', 'if (NO) return;'),
                ('hidden lifecycle invalidation', 'self.edgeMenuPhase == phase && phase != MLEdgeMenuPhaseHidden', 'self.edgeMenuPhase == phase'),
                ('stale nested menu completion', 'if (menuToken != self.edgeMenuLifecycleToken) return;', 'if (NO) return;'),
                ('right-click menu regression', '- (void)rightMouseDown:(NSEvent *)event {', '- (void)rightMouseDown:(NSEvent *)event { if (!self.isMouseCaptured) { self.suppressNextRightMouseUp = YES; [self presentStreamMenuAtEvent:event]; return; }'),
                ('lost explicit release', 'self.userReleasedInput = YES;', 'self.userReleasedInput = NO;'),
                ('expanded hitbox used for activation', 'NSRect region = [self edgeSensorActivationRectInBounds:bounds];', 'NSRect region = [self edgeMenuInteractionRectInBounds:bounds];'),
                ('default-mode-only dwell', 'addTimer:self.edgeSensorDwellTimer forMode:NSRunLoopCommonModes', 'addTimer:self.edgeSensorDwellTimer forMode:NSDefaultRunLoopMode'),
                ('recapture on another screen', 'NSPointInRect(returnPoint, self.view.bounds) &&', 'YES &&'),
                ('expanded controls lose pointer ownership', 'self.edgeMenuTemporaryReleaseActive || self.edgeMenuButtonExpanded', 'self.edgeMenuTemporaryReleaseActive || self.edgeMenuDragging || self.edgeMenuMenuVisible'),
                ('a refused sensor stays silent', 'Log(LOG_I, @"[diag] Edge sensor refused: reason=%@ captured=%d locked=%d edge=%ld",\n                blocker, self.isMouseCaptured, self.isMouseCaptured && !self.isRemoteDesktopMode,\n                (long)self.edgeMenuDockEdge);', 'Log(LOG_D, @"ignored");'),
                ('keyboard entry never takes the dock', '[self summonEdgeMenuDockForEdge:self.edgeMenuDockEdge reason:@\"control-center-shortcut\"];', ';'),
                ('keyboard entry reports a dock it never opened', '[self summonEdgeMenuDockForEdge:self.edgeMenuDockEdge reason:@"control-center-shortcut"];\n    return self.edgeMenuButtonExpanded;', '[self summonEdgeMenuDockForEdge:self.edgeMenuDockEdge reason:@"control-center-shortcut"];\n    return NO;'),
                ('a summoned bar is left on screen forever', '    [self handleEdgeMenuHover];\n    [self attachEdgeMenuPanelToWindowIfNeeded];', '    [self attachEdgeMenuPanelToWindowIfNeeded];'),
                ('the summon grace collapses into the hover delay', 'return self.edgeMenuPointerHasVisited ? MLEdgeMenuAutoCollapseDelay : MLEdgeMenuSummonGraceDelay;', 'return MLEdgeMenuAutoCollapseDelay;'),
                ('the keyboard entry is a one-way switch', 'if (self.edgeMenuButtonExpanded && !self.edgeMenuDragging) {\n        [self deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:self.edgeMenuTemporaryReleaseActive];\n        return YES;\n    }', 'if (NO) {\n        [self deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:self.edgeMenuTemporaryReleaseActive];\n        return YES;\n    }'),
                ('a press during a drag drops the bar out of the pointer', 'if (self.edgeMenuButtonExpanded && !self.edgeMenuDragging) {', 'if (self.edgeMenuButtonExpanded) {'),
                ('a bar that vanished on its own is not a return', 'if ([self edgeMenuPhaseIsOnScreen:previousPhase] && ![self edgeMenuPhaseIsOnScreen:phase]) {', 'if (self.edgeMenuPointerHasVisited && [self edgeMenuPhaseIsOnScreen:previousPhase] && ![self edgeMenuPhaseIsOnScreen:phase]) {'),
                ('a pointer that visited the bar is forgotten', '        self.edgeMenuPointerHasVisited = YES;', '        self.edgeMenuPointerHasVisited = NO;'),
                ('a bar that goes back leaves no trace', '@"[diag] Edge controls returned to stream', '@"[diag] ignored'),
                ('the two waits report one number', '[self edgeMenuReturnDelay] * 1000.0,', 'MLEdgeMenuAutoCollapseDelay * 1000.0,'),
                ('tab click leaks into the game', 'if ([self expandEdgeMenuForLocalClickAtCurrentPointer]) {\n        return;\n    }', 'if (NO) {\n        return;\n    }'),
                ('a lit desktop tab cannot be clicked', '((self.isMouseCaptured && !self.isRemoteDesktopMode) ||\n        self.edgeMenuPhase != MLEdgeMenuPhaseCollapsed ||', '(self.isMouseCaptured ||\n        self.edgeMenuPhase != MLEdgeMenuPhaseCollapsed ||'),
                ('arrival at the edge still grabs the pointer', '    if (self.edgeMenuHandleArmed) return;\n    self.edgeMenuHandleArmed = YES;', '    [self summonEdgeMenuDockForEdge:edge reason:@"edge-sensor-dwell"];\n    if (self.edgeMenuHandleArmed) return;\n    self.edgeMenuHandleArmed = YES;'),
                ('the tab ignores where the player dragged it', 'return minValue + available * MIN(MAX(self.edgeMenuButtonEdgeRatio, 0.0), 1.0);', 'return minValue + available * 0.5;'),
                ('the lit tab shrinks under the pointer that is clicking it', '        if (![self edgeSensorPointIsOnVisibleHandle:point]) [self resetEdgeSensorSummonState];', '        if (YES) [self resetEdgeSensorSummonState];'),
                ('locked motion opens the bar again', '        // here may only ever take a light off the tab.\n        [self resetEdgeSensorSummonState];\n        return NO;', '        // here may only ever take a light off the tab.\n        [self resetEdgeSensorSummonState];\n        [self summonEdgeMenuDockForEdge:self.edgeMenuDockEdge reason:@"edge-sensor-push"];\n        return NO;'),
                ('the hit rect ignores what the player can see', 'NSRect handle = [self edgeMenuVisibleHandleRectInBounds:self.view.bounds];', 'NSRect handle = [self edgeMenuInteractionRectInBounds:self.view.bounds];'),
                ('arming is invisible', 'return self.edgeMenuHandleArmed ? MLEdgeMenuHandleArmedThickness : MLEdgeMenuHandleIdleThickness;', 'return MLEdgeMenuHandleIdleThickness;'),
                ('the click target reads the wrong axis for a horizontal dock', 'BOOL verticalDock = self.edgeMenuDockEdge == MLFreeMouseExitEdgeLeft ||\n                        self.edgeMenuDockEdge == MLFreeMouseExitEdgeRight;', 'BOOL verticalDock = YES;'),
                ('the click target reads the wrong axis for a vertical dock', 'BOOL verticalDock = self.edgeMenuDockEdge == MLFreeMouseExitEdgeLeft ||\n                        self.edgeMenuDockEdge == MLFreeMouseExitEdgeRight;', 'BOOL verticalDock = NO;'),
                ('the armed light never goes out', 'if (self.edgeMenuHandleArmed) {\n        self.edgeMenuHandleArmed = NO;\n        [self updateEdgeMenuButtonAppearance];\n    }', 'if (NO) {\n        self.edgeMenuHandleArmed = NO;\n        [self updateEdgeMenuButtonAppearance];\n    }'),
            ]
            for label,before,after in mutations:
                assert before in methods,label
                assert run(methods.replace(before,after)).returncode!=0,label
                print('PASS negative control: '+label)
