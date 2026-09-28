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
@property BOOL edgeMenuPointerInside, staleEvent;
@property (readonly) BOOL expanded;
@property BOOL edgeSensorMustLeaveHoverRegion;
@property Panel *edgeMenuPanel;
@property ProbeHandle *edgeMenuButton;
@property NSTimer *edgeMenuAutoCollapseTimer;
@property NSInteger releases;
@property BOOL edgeSensorRelativePointValid, buttons, visible;
@property NSPoint edgeSensorRelativePoint;
@property NSRect edgeSensorRelativeBounds;
@property NSTimer *edgeSensorDwellTimer;
@property CGFloat edgeSensorPushAccumulator, edgeMenuButtonEdgeRatio;
@property double edgeSensorIgnoreMotionUntilMs, suppressFreeMouseEdgeUncaptureUntilMs, edgeSensorLastRefusalLogMs;
@property double fakeNowMs;
@property MLFreeMouseExitEdge edgeMenuDockEdge, freeEdge;
@property NSInteger summons;
@property NSString *reason;
@property CGFloat edgePushStrokePoints, edgePushReturnPoints;
@property BOOL edgePushAwaitingReturn;
@property NSUInteger edgePushStrokeCount;
@property double edgePushWindowStartMs, edgePushLastMotionMs, edgeSensorLastSampleLogMs;
@property BOOL edgeMenuClickConsumedLocally;
- (void)resetEdgePushGesture;
- (BOOL)noteEdgeSensorPushMotionForEvent:(NSEvent *)event;
- (BOOL)expandEdgeMenuForLocalClickAtCurrentPointer;
- (double)nowMs;
- (NSPoint)currentMouseLocationInViewCoordinates;
- (NSPoint)boundaryInteractionViewPointForMouseEvent:(NSEvent *)event;
- (NSRect)edgeMenuInteractionRectInBounds:(NSRect)bounds;
- (BOOL)edgeMenuShouldBeVisible;
- (BOOL)hasPressedMouseButtonsForCaptureTransition;
- (MLFreeMouseExitEdge)freeMouseExitEdgeForEvent:(NSEvent *)event;
- (void)summonEdgeMenuDockForEdge:(MLFreeMouseExitEdge)edge reason:(NSString *)reason;
- (void)finishEdgeSensorSummonIfStillArmedForEdge:(MLFreeMouseExitEdge)edge;
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
- (void)updateEdgeMenuButtonAppearance {}
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
- (void)updateEdgeMenuPointerInsideForPoint:(NSPoint)point { self.edgeMenuPointerInside = [self isPointInsideEdgeMenuInteractionRect:point]; }
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
            s.systemPoint = NSMakePoint(NSMidX(region),NSMidY(region));
            s.edgeSensorIgnoreMotionUntilMs = 0;
            move(s,0,0);
            CHECK(s.edgeSensorDwellTimer.isValid, "authoritative local position starts dwell");
            fire(s.edgeSensorDwellTimer);
            CHECK(s.expanded && !s.isMouseCaptured && s.edgeMenuTemporaryReleaseActive, "dwell acquires pointer and opens controls");
            CHECK(!s.edgeMenuPanel.ignoresMouseEvents, "expanded controls accept native input");
            s.systemPoint = NSMakePoint(edge == MLFreeMouseExitEdgeLeft ? NSMaxX(s.view.bounds)-1 : NSMinX(s.view.bounds)+1,
                                        edge == MLFreeMouseExitEdgeBottom ? NSMaxY(s.view.bounds)-1 : NSMinY(s.view.bounds)+1);
            [s handleEdgeMenuTemporaryReleaseForEvent:nil];
            NSTimer *deadline = s.edgeMenuAutoCollapseTimer;
            [s handleEdgeMenuTemporaryReleaseForEvent:nil];
            CHECK(s.expanded && deadline == s.edgeMenuAutoCollapseTimer, "movement neither collapses immediately nor restarts the grace deadline");
            fire(deadline);
            CHECK(!s.expanded && s.isMouseCaptured && !s.edgeMenuTemporaryReleaseActive, "grace completion returns captured input exactly once");
            CHECK(s.edgeMenuPanel.ignoresMouseEvents, "collapsed transparent panel cannot swallow stream clicks");
            s.edgeSensorIgnoreMotionUntilMs=0;
            move(s,0,0); // leave before rearming
        }
    }
    s=fresh(MLFreeMouseExitEdgeRight); s.systemPoint=NSMakePoint(1918,540);
    move(s,0,0);
    [[NSRunLoop currentRunLoop] runMode:NSEventTrackingRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.3]];
    CHECK(s.expanded, "native event-tracking mode does not suspend dwell");
    s=fresh(MLFreeMouseExitEdgeRight); s.systemPoint=NSMakePoint(1918,540); move(s,0,0);
    NSTimer *obsolete=s.edgeSensorDwellTimer;
    s.view.bounds=NSMakeRect(0,0,1280,720); fire(obsolete);
    CHECK(!s.expanded, "resizing invalidates geometry captured by a dwell");
    s=fresh(MLFreeMouseExitEdgeRight); s.systemPoint=NSMakePoint(1918,540); move(s,0,0); obsolete=s.edgeSensorDwellTimer;
    [s transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden]; fire(obsolete);
    CHECK(!s.expanded && !s.edgeSensorDwellTimer && !s.edgeMenuAutoCollapseTimer, "hidden lifecycle cancels all pending work");
    for (int blocker=0; blocker<5; blocker++) {
        s=fresh(MLFreeMouseExitEdgeRight); s.systemPoint=NSMakePoint(1918,540); move(s,0,0);
        if(blocker==0)s.buttons=YES;
        if(blocker==1)s.visible=NO;
        if(blocker==2)s.stopStreamInProgress=YES;
        if(blocker==3)s.reconnectInProgress=YES;
        if(blocker==4)s.edgeSensorSummonEnabled=NO;
        fire(s.edgeSensorDwellTimer);
        CHECK(!s.expanded && s.isMouseCaptured, "timeout revalidates buttons, focus/visibility, stop, reconnect and preference");
    }
    s=fresh(MLFreeMouseExitEdgeRight); s.systemPoint=NSMakePoint(NAN,540); move(s,1000,0);
    CHECK(!s.edgeSensorDwellTimer, "nonfinite coordinate cannot arm");
    s.systemPoint=NSMakePoint(1921,540); move(s,0,0);
    CHECK(!s.edgeSensorDwellTimer, "pointer on another display cannot arm");
    s=fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode=NO; s.systemPoint=NSMakePoint(1918,540);
    for(int i=0;i<100;i++)move(s,1000,0);
    CHECK(!s.edgeSensorDwellTimer && s.isMouseCaptured && !s.expanded, "locked game motion never invents a remote cursor");
    CHECK(s.edgePushStrokeCount <= 1, "continuous outward motion is one stroke, never a completed gesture");
    [s releaseInputToLocalControlWithCode:@"test" reason:@"explicit"];
    s.edgeSensorIgnoreMotionUntilMs=0; move(s,0,0); fire(s.edgeSensorDwellTimer);
    CHECK(s.expanded && s.userReleasedInput && !s.edgeMenuTemporaryReleaseActive, "released game mode uses local hover without promising automatic recapture");
    s.systemPoint=NSMakePoint(1000,500); [s handleEdgeMenuTemporaryReleaseForEvent:nil]; fire(s.edgeMenuAutoCollapseTimer);
    CHECK(!s.isMouseCaptured && s.userReleasedInput, "collapse respects persistent user release");
    [s resumeInputForExplicitStreamClick:nil];
    CHECK(s.isMouseCaptured && !s.userReleasedInput, "explicit click resumes game after closing controls");
    s=fresh(MLFreeMouseExitEdgeRight); s.systemPoint=NSMakePoint(1918,540); move(s,0,0); fire(s.edgeSensorDwellTimer);
    [s deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:YES]; s.edgeSensorIgnoreMotionUntilMs=0;
    move(s,0,0);
    CHECK(!s.edgeSensorDwellTimer, "dismiss over activation region requires exit and reentry");
    s.systemPoint=NSMakePoint(1800,540); move(s,0,0); s.systemPoint=NSMakePoint(1918,540); move(s,0,0);
    CHECK(s.edgeSensorDwellTimer.isValid, "leaving and reentering reliably rearms");
    fire(s.edgeSensorDwellTimer);
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

    // Locked-mode slam gesture: two separated strokes toward the docked edge. A stroke ends
    // when the device comes back inside, so the gesture is out-back-out.
    double toward[][2] = {{-60,0},{60,0},{0,60},{0,-60}};   // left, right, top, bottom
    double back[][2]   = {{ 30,0},{-30,0},{0,-30},{0,30}};
    for (int edge = 1; edge <= 4; edge++) {
        s = fresh(edge); s.isRemoteDesktopMode = NO;
        for (int stroke = 0; stroke < 2; stroke++) {
            move(s, toward[edge-1][0]/3, toward[edge-1][1]/3);
            move(s, toward[edge-1][0]/3, toward[edge-1][1]/3);
            move(s, toward[edge-1][0]/3, toward[edge-1][1]/3);
            if (stroke < 1) { move(s, back[edge-1][0]/2, back[edge-1][1]/2); move(s, back[edge-1][0]/2, back[edge-1][1]/2); }
        }
        CHECK(s.expanded && !s.isMouseCaptured && s.edgeMenuTemporaryReleaseActive,
              "two slams open the dock on every edge while the game mouse stays locked");
        CHECK(!s.isRemoteDesktopMode, "the slam gesture never switches the host out of game mode");
    }
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int cycle = 0; cycle < 30; cycle++) {
        for (int stroke = 0; stroke < 2; stroke++) {
            for (int k = 0; k < 3; k++) move(s, 20, 0);
            if (stroke < 1) { move(s, -15, 0); move(s, -15, 0); }
        }
        CHECK(s.expanded && !s.isMouseCaptured, "thirtieth slam still opens; no first-hit-only failure");
        [s deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:YES];
        s.edgeSensorIgnoreMotionUntilMs = 0; // the recapture cooldown models a later real motion
        CHECK(!s.expanded && s.isMouseCaptured, "slam cycle collapses and returns capture for the next gesture");
    }
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int i = 0; i < 300; i++) move(s, 1, 0);
    CHECK(!s.expanded && s.edgePushStrokeCount <= 1, "slow drift cannot farm strokes");
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int i = 0; i < 300; i++) move(s, (i % 2) ? 10 : -10, 0);
    CHECK(!s.expanded && s.edgePushStrokeCount == 0, "jitter below both thresholds never counts");
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int k = 0; k < 3; k++) move(s, 20, 0);
    move(s, -15, 0); move(s, -15, 0);          // one stroke counted
    Motion *pressed = [Motion new]; pressed.deltaX = 20;
    s.buttons = YES; [s noteEdgeSensorPushMotionForEvent:(NSEvent *)pressed]; s.buttons = NO;
    CHECK(s.edgePushStrokeCount == 0, "a button press voids the accumulated slam strokes");
    for (int k = 0; k < 3; k++) move(s, 20, 0); // one fresh stroke, and it is not enough on its own
    CHECK(!s.expanded, "a button press inside the gesture cannot be replayed as a summon");
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int stroke = 0; stroke < 4; stroke++) {
        for (int k = 0; k < 3; k++) move(s, 0, 20);
        move(s, 0, -15); move(s, 0, -15);
    }
    CHECK(!s.expanded, "vertical play cannot farm a horizontal dock");
    // The two clocks are separate on purpose: the idle gap forgets a stale gesture,
    // the window bounds the whole one. One flick, one stroke: never a summon.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int k = 0; k < 3; k++) moveAt(s, 1000, 20, 0);
    moveAt(s, 1050, -15, 0); moveAt(s, 1080, -15, 0);
    CHECK(!s.expanded, "one slam toward the dock is never a summon");
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int k = 0; k < 3; k++) moveAt(s, 1000, 20, 0);
    moveAt(s, 1050, -15, 0); moveAt(s, 1080, -15, 0);
    for (int k = 0; k < 3; k++) moveAt(s, 1380, 20, 0);   // a 300ms pause to re-aim
    CHECK(s.expanded && !s.isMouseCaptured, "pausing to re-aim inside the idle gap keeps the counted stroke");
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int k = 0; k < 3; k++) moveAt(s, 1000, 20, 0);
    moveAt(s, 1050, -15, 0); moveAt(s, 1080, -15, 0);
    for (int k = 0; k < 3; k++) moveAt(s, 1780, 20, 0);   // 700ms of quiet: the idle gap ends it
    CHECK(!s.expanded && s.edgePushStrokeCount <= 1, "a stalled gesture is forgotten, not chained");
    // Two clocks, so two schedules that differ only in the total: the same
    // 1400ms gesture must open, the same gesture at 1600ms must not.
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int k = 0; k < 3; k++) moveAt(s, 2000 + 300 * k, 20, 0);
    moveAt(s, 2700, -15, 0); moveAt(s, 2800, -15, 0);
    moveAt(s, 3100, 20, 0); moveAt(s, 3200, 20, 0); moveAt(s, 3400, 20, 0); // 1400ms total, no gap over 300ms
    CHECK(s.expanded, "a gesture the old 1200ms budget refused still completes inside the window");
    s = fresh(MLFreeMouseExitEdgeRight); s.isRemoteDesktopMode = NO;
    for (int k = 0; k < 3; k++) moveAt(s, 4000 + 400 * k, 20, 0);
    moveAt(s, 4900, -15, 0); moveAt(s, 5000, -15, 0);
    moveAt(s, 5400, 20, 0); moveAt(s, 5500, 20, 0); moveAt(s, 5900, 20, 0); // 1900ms is past the budget
    CHECK(!s.expanded, "strokes outside the gesture window do not chain");

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
    NSRect tab = [s edgeMenuInteractionRectInBounds:s.view.bounds];
    s.systemPoint = NSMakePoint(NSMidX(tab), NSMidY(tab));
    Motion *tabMotion = [Motion new]; NSEvent *tabClick = (NSEvent *)tabMotion;
    [s mouseDown:tabClick];
    CHECK(s.expanded && s.edgeMenuClickConsumedLocally && !s.isMouseCaptured && [s.wire count] == 0,
          "a released-mode click on the tab opens controls and sends nothing to the host");
    [s mouseUp:tabClick];
    CHECK(!s.edgeMenuClickConsumedLocally && s.expanded && [s.wire count] == 0,
          "the consumed press's release never reaches the host either");
    s = fresh(MLFreeMouseExitEdgeRight); s.isMouseCaptured = NO; s.isRemoteDesktopMode = NO;
    s.wire = [NSMutableArray array];
    s.systemPoint = NSMakePoint(960, 540);
    [s mouseDown:tabClick];
    [s mouseUp:tabClick];
    CHECK(s.isMouseCaptured && !s.expanded && [s.wire count] == 2,
          "ordinary stream clicks still capture and forward their button pair");

    printf("%d runtime edge checks, %d failures\n", count, failures);
    return failures != 0;
} }
'''

def run_runtime_probe(objc, menu, internal, helpers="", self_test=False):
    signatures = [
        '- (void)resetEdgeSensorSummonState', '- (void)resetEdgeSensorPointerState',
        '- (BOOL)edgeSensorPointIsInHoverRegion:', '- (void)captureMousePreservingEdgeSensorPoint:',
        '- (BOOL)captureFreeMouseIfNeededForEvent:', '- (BOOL)edgeMenuOwnsPointer', '- (void)rightMouseDown:', '- (void)rightMouseUp:',
        '- (void)otherMouseDown:', '- (void)otherMouseUp:', '- (void)handleModifierOnlyReleaseShortcut:',
        '- (void)releaseInputToLocalControlWithCode:', '- (void)resumeInputForExplicitStreamClick:',
        '- (NSPoint)edgeSensorPointForEvent:', '- (void)beginEdgeSensorDwellTimerIfNeededForEdge:',
        '- (void)finishEdgeSensorSummonIfStillArmedForEdge:', '- (BOOL)handleEdgeSensorSummonForEvent:', '- (NSString *)edgeSensorSummonBlocker',
        '- (void)summonEdgeMenuDockForEdge:',
        '- (void)resetEdgePushGesture', '- (BOOL)noteEdgeSensorPushMotionForEvent:',
        '- (BOOL)expandEdgeMenuForLocalClickAtCurrentPointer', '- (void)mouseDown:', '- (void)mouseUp:',
    ]
    methods = "\n".join(method(objc, sig) for sig in signatures)
    methods += "\n" + "\n".join(method(menu, sig) for sig in (
        '- (void)presentStreamMenuFromView:(NSView *)sourceView event:',
        '- (void)handleEdgeMenuButtonDragWithState:',
        '- (BOOL)isPointInsideEdgeMenuInteractionRect:',
        '- (BOOL)edgeMenuButtonExpanded', '- (BOOL)edgeMenuDragging', '- (BOOL)edgeMenuMenuVisible',
        '- (void)transitionEdgeMenuToPhase:', '- (void)handleEdgeMenuHover', '- (NSRect)edgeSensorActivationRectInBounds:',
        '- (void)deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:', '- (void)setEdgeMenuButtonExpanded:',
        '- (void)cancelEdgeMenuAutoCollapse', '- (void)scheduleEdgeMenuAutoCollapse',
        '- (void)activateEdgeMenuDockForExitEdge:', '- (BOOL)handleEdgeMenuTemporaryReleaseForEvent:',
        '- (BOOL)openEdgeMenuDockForControlCenterShortcut',
        '- (BOOL)edgeMenuDockEdgeUsesVerticalAxis', '- (CGFloat)resolvedEdgeMenuCoordinateInRect:',
        '- (NSRect)edgeMenuFrameInRect:', '- (NSRect)edgeMenuInteractionRectInBounds:',
        '- (NSRect)expandedFrameForEdgeMenuButtonInBounds:',
        '- (NSRect)frameForCurrentEdgeMenuPanelStateInScreenRect:',
        '- (NSRect)collapsedFrameForEdgeMenuPanelInScreenRect:', '- (NSRect)expandedFrameForEdgeMenuPanelInScreenRect:',
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
                ('slam counts continuous outward motion as strokes', 'if (self.edgePushReturnPoints < MLEdgeSensorPushReturnPoints) return NO;', 'if (NO) return NO;'),
                ('slam strokes shrink to nothing', 'if (self.edgePushStrokePoints >= MLEdgeSensorPushStrokePoints) {', 'if (self.edgePushStrokePoints > 0) {'),
                ('slam survives a button press', 'if ([self hasPressedMouseButtonsForCaptureTransition]) {\n        [self resetEdgePushGesture];\n        return NO;\n    }', 'if (NO) {\n        [self resetEdgePushGesture];\n        return NO;\n    }'),
                ('a refused sensor stays silent', 'Log(LOG_I, @"[diag] Edge sensor refused: reason=%@ captured=%d locked=%d edge=%ld",\n                blocker, self.isMouseCaptured, self.isMouseCaptured && !self.isRemoteDesktopMode,\n                (long)self.edgeMenuDockEdge);', 'Log(LOG_D, @"ignored");'),
                ('keyboard entry never takes the dock', '[self summonEdgeMenuDockForEdge:self.edgeMenuDockEdge reason:@\"control-center-shortcut\"];', ';'),
                ('keyboard entry reports a dock it never opened', '[self summonEdgeMenuDockForEdge:self.edgeMenuDockEdge reason:@"control-center-shortcut"];\n    return self.edgeMenuButtonExpanded;', '[self summonEdgeMenuDockForEdge:self.edgeMenuDockEdge reason:@"control-center-shortcut"];\n    return NO;'),
                ('slam gesture reuses one clock for both questions', 'now - self.edgePushLastMotionMs > MLEdgeSensorPushIdleMs', 'now - self.edgePushLastMotionMs > 1e9'),
                ('slam gesture keeps the old 1200ms budget', 'BOOL completed = now - self.edgePushWindowStartMs <= MLEdgeSensorPushWindowMs;', 'BOOL completed = now - self.edgePushWindowStartMs <= 1200.0;'),
                ('one flick is enough to summon', 'if (self.edgePushStrokeCount >= MLEdgeSensorPushStrokeCount) {', 'if (self.edgePushStrokeCount >= 1) {'),
                ('tab click leaks into the game', 'if ([self expandEdgeMenuForLocalClickAtCurrentPointer]) {\n        return;\n    }', 'if (NO) {\n        return;\n    }'),
            ]
            for label,before,after in mutations:
                assert before in methods,label
                assert run(methods.replace(before,after)).returncode!=0,label
                print('PASS negative control: '+label)
