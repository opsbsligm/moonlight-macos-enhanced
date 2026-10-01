//
//  StreamViewController+MenuUI.m
//  Moonlight for macOS
//

#import "StreamViewController_Internal.h"

@implementation StreamViewController (MenuUI)

- (NSString *)mouseModeDisplayNameForMode:(NSString *)mode {
    return [mode isEqualToString:@"remote"] ? MLString(@"Free Mouse", nil) : MLString(@"Locked Mouse", nil);
}

- (NSString *)mouseModeHintForMode:(NSString *)mode {
    return [mode isEqualToString:@"remote"] ? MLString(@"Free Mouse hint", nil) : MLString(@"Locked Mouse hint", nil);
}

- (NSString *)shortcutDisplayStringForAction:(NSString *)action {
    StreamShortcut *shortcut = [self streamShortcutForAction:action];
    NSArray<NSString *> *tokens = [StreamShortcutProfile displayTokensFor:shortcut];
    return tokens.count > 0 ? [tokens componentsJoinedByString:@""] : @"";
}

- (NSString *)releaseMouseHintText {
    NSString *shortcut = [self shortcutDisplayStringForAction:MLShortcutActionReleaseMouseCapture];
    if (shortcut.length == 0) {
        return @"";
    }
    return [NSString stringWithFormat:MLString(@"Release mouse: %@", nil), shortcut];
}

- (NSString *)openControlCenterHintText {
    NSString *shortcut = [self shortcutDisplayStringForAction:MLShortcutActionOpenControlCenter];
    if (shortcut.length == 0) {
        return MLString(@"Control Center", nil);
    }
    return [NSString stringWithFormat:MLString(@"Open Control Center: %@", nil), shortcut];
}

- (void)updateControlCenterEntrypointHints {
    NSString *openHint = [self openControlCenterHintText];
    NSString *releaseHint = self.userReleasedInput ? MLString(@"Click stream to resume input", nil)
        : ((!self.isRemoteDesktopMode && self.isMouseCaptured) ? [self releaseMouseHintText] : @"");
    NSString *tooltip = releaseHint.length > 0
        ? [@[openHint, releaseHint] componentsJoinedByString:@"\n"]
        : openHint;

    self.menuTitlebarButton.toolTip = tooltip;
    self.edgeMenuButton.toolTip = tooltip;
    self.edgeMenuPanel.contentView.toolTip = tooltip;
}

- (NSView *)preferredControlCenterSourceView {
    if (([self isWindowFullscreen] || [self isWindowBorderlessMode]) &&
        self.edgeMenuPanel.isVisible &&
        self.edgeMenuButton &&
        !self.edgeMenuButton.hidden) {
        return self.edgeMenuButton;
    }
    if (self.menuTitlebarButton && self.menuTitlebarAccessory.view && !self.menuTitlebarAccessory.view.hidden) {
        return self.menuTitlebarButton;
    }
    return self.view;
}

- (void)presentControlCenterFromShortcut {
    // Pointer ownership is acquired by the same menu transaction as a click.
    // Releasing here used to lose the "captured before open" return intent.
    NSUInteger token = self.edgeMenuLifecycleToken;
    __weak typeof(self) weakSelf = self;
    dispatch_async(dispatch_get_main_queue(), ^{
        __strong typeof(weakSelf) strongSelf = weakSelf;
        if (!strongSelf || token != strongSelf.edgeMenuLifecycleToken || ![strongSelf edgeMenuCanInteract]) return;
        [strongSelf presentStreamMenuFromView:[strongSelf preferredControlCenterSourceView]];
    });
}

// Locked game mode detaches the local pointer, parks it at the centre of the video and
// hides it, so no hover exists to open the dock there. That used to leave the keyboard as
// the only entry, and it reached the dock only by accident: the source-view helper prefers
// the dock's button solely when the panel happens to be on screen already. Take the dock
// through the same transition a dwell or a slam makes, so the sidebar itself always opens:
// one release path, one temporary-release intent, one return-to-stream re-capture. Nothing
// here decides ownership on its own.
- (BOOL)openEdgeMenuDockForControlCenterShortcut {
    // A press that can only open is half a switch: the player who presses again wants the
    // bar out of the way, and instead gets a bar that keeps the pointer until its own timer
    // expires. Going away uses the one funnel that already hands the pointer back, so the
    // collapse is recorded, the temporary-release intent is honoured, and the press after it
    // opens a fresh stay on screen. Mid-drag falls through to the summon, which refuses, so
    // a dragged bar is never torn out of the pointer's hand and no second guard appears here.
    if (self.edgeMenuButtonExpanded && !self.edgeMenuDragging) {
        [self deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:self.edgeMenuTemporaryReleaseActive];
        return YES;
    }

    // Every refusal stays inside the summon, which is also the only place that decides
    // pointer ownership: a second copy of its guards here could only drift.
    [self summonEdgeMenuDockForEdge:self.edgeMenuDockEdge reason:@"control-center-shortcut"];
    return self.edgeMenuButtonExpanded;
}

- (StreamShortcut *)streamShortcutForAction:(NSString *)action {
    NSDictionary *shortcuts = [SettingsClass streamShortcutsFor:self.app.host.uuid];
    StreamShortcut *shortcut = shortcuts[action];
    return shortcut ?: [StreamShortcutProfile defaultShortcutFor:action];
}

- (BOOL)event:(NSEvent *)event matchesShortcut:(StreamShortcut *)shortcut {
    if (![StreamShortcutProfile shortcutCanMatchKeyboardEvent:shortcut]) {
        return NO;
    }
    if (!MLIsKeyboardKeyEvent(event)) {
        return NO;
    }

    return event.keyCode == shortcut.keyCode
        && MLRelevantShortcutModifiers(event.modifierFlags) == shortcut.modifierFlags;
}

- (void)applyShortcut:(StreamShortcut *)shortcut toMenuItem:(NSMenuItem *)item {
    if (!item) {
        return;
    }

    item.keyEquivalent = [StreamShortcutProfile menuKeyEquivalentFor:shortcut];
    item.keyEquivalentModifierMask = [StreamShortcutProfile menuModifierMaskFor:shortcut];
    // Named keys (arrows, F-keys, etc.) are handled by the stream responder.
    // Still show the configured binding when AppKit has no key equivalent.
    if (item.keyEquivalent.length == 0) {
        NSString *hint = [[StreamShortcutProfile displayTokensFor:shortcut] componentsJoinedByString:@""];
        if (hint.length > 0) item.title = [NSString stringWithFormat:@"%@ (%@)", item.title, hint];
    }
}

- (void)updateConfiguredShortcutMenus {
    if (self.streamMenu) {
        [self rebuildStreamMenu];
    }

    [self updateControlCenterEntrypointHints];
}

- (BOOL)windowSupportsTitlebarAccessoryControllers:(NSWindow *)window {
    // Some NSWindow subclasses (and older macOS) don't implement the setter even if the getter exists.
    // Never require setTitlebarAccessoryViewControllers:, because we can operate without it.
    return window != nil
        && [window respondsToSelector:@selector(titlebarAccessoryViewControllers)];
}

- (BOOL)windowAllowsTitlebarAccessories:(NSWindow *)window {
    if (!window) {
        return NO;
    }
    if ((window.styleMask & NSWindowStyleMaskTitled) == 0) {
        return NO;
    }
    if ((window.styleMask & NSWindowStyleMaskBorderless) != 0) {
        return NO;
    }
    if (![window respondsToSelector:@selector(addTitlebarAccessoryViewController:)]) {
        return NO;
    }
    return YES;
}

- (BOOL)isMenuTitlebarAccessoryInstalledInWindow:(NSWindow *)window {
    if (!window || !self.menuTitlebarAccessory) {
        return NO;
    }

    if ([self windowSupportsTitlebarAccessoryControllers:window]) {
        @try {
            return [window.titlebarAccessoryViewControllers containsObject:self.menuTitlebarAccessory];
        } @catch (NSException *exception) {
            // If AppKit asserts for this style/transition, fall back to our local flag.
        }
    }

    return self.menuTitlebarAccessoryInstalled;
}

- (void)buildMenuTitlebarAccessoryIfNeeded {
    if (self.menuTitlebarAccessory != nil) {
        return;
    }

    // The pill used to be 240pt wide and carry the words "Control Center" in it, which
    // is what made windowed mode look broken: the bar's only entry was a wide pill
    // fused into the right end of the titlebar, beside the stats overlay, while in the
    // other two modes the entry is a tab on the edge of the picture. The dock is the
    // entry everywhere now, so the pill is only a status badge: signal, elapsed time,
    // and words when something is actually wrong.
    const CGFloat containerWidth = 132.0;
    const CGFloat containerHeight = 28.0;

    NSView *container = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, containerWidth, containerHeight)];
    container.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    container.autoresizesSubviews = YES;

    // The control-centre pill is a button, so where the system has it its glass is
    // the interactive kind. The glass view owns its content host, and the glass
    // content covers the panel, so the panel-relative frames below do not move.
    GlassOverlayContainer *pill = [GlassOverlayContainer containerWithCornerRadius:containerHeight * 0.5];
    pill.frame = container.bounds;
    pill.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    pill.glassIsInteractive = YES;
    [container addSubview:pill];

    NSView *content = pill.contentView;

    NSImageView *signalImageView = [[NSImageView alloc] initWithFrame:NSMakeRect(10.0, 6.0, 16.0, 16.0)];
    signalImageView.imageScaling = NSImageScaleProportionallyUpOrDown;
    signalImageView.contentTintColor = [NSColor whiteColor];
    [content addSubview:signalImageView];

    NSTextField *timeLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(32.0, 6.0, 90.0, 16.0)];
    timeLabel.bezeled = NO;
    timeLabel.drawsBackground = NO;
    timeLabel.editable = NO;
    timeLabel.selectable = NO;
    timeLabel.alignment = NSTextAlignmentLeft;
    timeLabel.font = [NSFont monospacedDigitSystemFontOfSize:13.0 weight:NSFontWeightRegular];
    timeLabel.textColor = [NSColor whiteColor];
    timeLabel.stringValue = @"00:00";
    [content addSubview:timeLabel];

    // The badge shares the time label's slot and only speaks for itself when the stream
    // is actually in trouble; an ordinary session leaves it empty rather than filling the
    // titlebar with a button label nobody needs to read twice.
    NSTextField *titleLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(32.0, 6.0, 90.0, 16.0)];
    titleLabel.bezeled = NO;
    titleLabel.drawsBackground = NO;
    titleLabel.editable = NO;
    titleLabel.selectable = NO;
    titleLabel.alignment = NSTextAlignmentLeft;
    titleLabel.font = [NSFont systemFontOfSize:12.0 weight:NSFontWeightSemibold];
    titleLabel.textColor = [NSColor whiteColor];
    titleLabel.lineBreakMode = NSLineBreakByTruncatingTail;
    titleLabel.stringValue = @"";
    [content addSubview:titleLabel];

    NSButton *button = [NSButton buttonWithTitle:@"" target:self action:@selector(handleTitlebarControlCenterPressed:)];
    button.frame = container.bounds;
    button.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    button.bordered = NO;
    button.imagePosition = NSNoImage;
    button.title = @"";
    button.focusRingType = NSFocusRingTypeNone;
    if ([button respondsToSelector:@selector(setRefusesFirstResponder:)]) {
        button.refusesFirstResponder = YES;
    }

    // The button lives inside the glass rather than on top of it: interactive
    // glass answers controls it contains, and a control floating over the panel
    // would leave the glass motionless while the pill was the thing being pressed.
    [content addSubview:button];

    NSTitlebarAccessoryViewController *accessory = [[NSTitlebarAccessoryViewController alloc] init];
    accessory.layoutAttribute = NSLayoutAttributeRight;
    accessory.view = container;

    self.menuTitlebarAccessory = accessory;
    self.menuTitlebarButton = button;
    self.controlCenterPill = pill;
    self.controlCenterSignalImageView = signalImageView;
    self.controlCenterTimeLabel = timeLabel;
    self.controlCenterTitleLabel = titleLabel;
}

- (void)removeMenuTitlebarAccessoryFromWindowIfNeeded {
    if (!self.menuTitlebarAccessory) {
        return;
    }

    NSWindow *window = self.view.window;
    if (window &&
        [self isMenuTitlebarAccessoryInstalledInWindow:window] &&
        [window respondsToSelector:@selector(setTitlebarAccessoryViewControllers:)]) {
        @try {
            NSMutableArray *controllers = [[window titlebarAccessoryViewControllers] mutableCopy];
            [controllers removeObject:self.menuTitlebarAccessory];
            [window setValue:[controllers copy] forKey:@"titlebarAccessoryViewControllers"];
        } @catch (NSException *exception) {
        }
    }

    self.menuTitlebarAccessory.view.hidden = YES;
    self.menuTitlebarAccessoryInstalled = window ? [self isMenuTitlebarAccessoryInstalledInWindow:window] : NO;
}

- (void)ensureMenuTitlebarAccessoryInstalledIfNeeded {
    if (!MLUseOnScreenControlCenterEntrypoints) {
        return;
    }

    NSWindow *window = self.view.window;
    if (![self windowAllowsTitlebarAccessories:window] ||
        [self isWindowFullscreen] ||
        [self isWindowBorderlessMode] ||
        ![self isWindowInCurrentSpace]) {
        [self removeMenuTitlebarAccessoryFromWindowIfNeeded];
        return;
    }

    [self buildMenuTitlebarAccessoryIfNeeded];

    if (![self isMenuTitlebarAccessoryInstalledInWindow:window]) {
        @try {
            [window addTitlebarAccessoryViewController:self.menuTitlebarAccessory];
            self.menuTitlebarAccessoryInstalled = YES;
        } @catch (NSException *exception) {
            self.menuTitlebarAccessoryInstalled = NO;
            return;
        }
    }

    self.menuTitlebarAccessory.view.hidden = NO;
    [self updateControlCenterStatus];
    [self updateControlCenterEntrypointHints];
}

- (void)handleTitlebarControlCenterPressed:(id)sender {
    if (self.menuTitlebarButton) {
        [self presentStreamMenuFromView:self.menuTitlebarButton event:nil];
    } else {
        [self presentStreamMenuFromView:self.view event:nil];
    }
}

- (NSString *)fullscreenControlBallDefaultsKey {
    NSString *uuid = self.app.host.uuid ?: @"global";
    return [NSString stringWithFormat:@"%@-hideFullscreenControlBall", uuid];
}

- (NSString *)fullscreenControlBallDockSideDefaultsKey {
    NSString *uuid = self.app.host.uuid ?: @"global";
    return [NSString stringWithFormat:@"%@-fullscreenControlBallDockSide", uuid];
}

- (NSString *)fullscreenControlBallVerticalRatioDefaultsKey {
    NSString *uuid = self.app.host.uuid ?: @"global";
    return [NSString stringWithFormat:@"%@-fullscreenControlBallVerticalRatio", uuid];
}

- (MLFreeMouseExitEdge)defaultEdgeMenuDockEdge {
    return MLFreeMouseExitEdgeRight;
}





- (BOOL)edgeMenuButtonExpanded {
    return self.edgeMenuPhase == MLEdgeMenuPhaseExpanded ||
           self.edgeMenuPhase == MLEdgeMenuPhaseMenu ||
           self.edgeMenuPhase == MLEdgeMenuPhaseDragging;
}

- (BOOL)edgeMenuDragging { return self.edgeMenuPhase == MLEdgeMenuPhaseDragging; }
- (BOOL)edgeMenuMenuVisible { return self.edgeMenuPhase == MLEdgeMenuPhaseMenu; }

- (BOOL)edgeMenuCanInteract {
    NSWindow *window = self.view.window;
    return window && window.isKeyWindow && window.isVisible && !window.isMiniaturized && [NSApp isActive] &&
           !self.stopStreamInProgress && !self.reconnectInProgress &&
           !self.spaceTransitionInProgress && !self.fullscreenTransitionInProgress &&
           [self isWindowInCurrentSpace];
}

// Which of the two waits a bar that is on screen lives under: once the pointer has been on
// it, it is a hover and gets the short grace; a bar nobody looked at keeps the summon grace.
// Both the clock that fires and the line that reports the return read it here, so the log
// can never disagree with the timer that produced it.
- (NSTimeInterval)edgeMenuReturnDelay {
    return self.edgeMenuPointerHasVisited ? MLEdgeMenuAutoCollapseDelay : MLEdgeMenuSummonGraceDelay;
}

// Expanded, menu and drag are the states where the controls are on screen and may hold the
// pointer. Collapsed is the docked handle, hidden is gone.
- (BOOL)edgeMenuPhaseIsOnScreen:(MLEdgeMenuPhase)phase {
    return phase == MLEdgeMenuPhaseExpanded ||
           phase == MLEdgeMenuPhaseMenu ||
           phase == MLEdgeMenuPhaseDragging;
}

- (void)transitionEdgeMenuToPhase:(MLEdgeMenuPhase)phase {
    // Hidden is also a lifecycle barrier. Repeated teardown must invalidate
    // work queued while the controls were already hidden (e.g. a shortcut).
    if (self.edgeMenuPhase == phase && phase != MLEdgeMenuPhaseHidden) return;
    BOOL wasMenu = self.edgeMenuMenuVisible;
    MLEdgeMenuPhase previousPhase = self.edgeMenuPhase;
    // The bar came out because someone asked for it, so the moment it goes back is worth one
    // line - and it has to be one line for every way of going back. The clock that collapses
    // the bar is only one of them: a click in the stream, a window that stopped being able to
    // host the controls and the second press of the shortcut all take the pointer away too. A
    // return written at one caller's level is why a field session could log 18 openings and 17
    // returns while the player pressed eighteen times.
    if ([self edgeMenuPhaseIsOnScreen:previousPhase] && ![self edgeMenuPhaseIsOnScreen:phase]) {
        Log(LOG_I, @"[diag] Edge controls returned to stream: edge=%ld visited=%d grace=%.0fms captured=%d from=%ld to=%ld",
            (long)self.edgeMenuDockEdge, self.edgeMenuPointerHasVisited,
            [self edgeMenuReturnDelay] * 1000.0, self.isMouseCaptured,
            (long)previousPhase, (long)phase);
    }
    self.edgeMenuPhase = phase;
    // A visit record describes one stay on screen: it is opened when the bar comes out
    // and forgotten when it goes away, never by whichever caller happens to look at it.
    BOOL freshExpansion = phase == MLEdgeMenuPhaseExpanded &&
        previousPhase != MLEdgeMenuPhaseExpanded &&
        previousPhase != MLEdgeMenuPhaseMenu &&
        previousPhase != MLEdgeMenuPhaseDragging;
    if (freshExpansion || phase == MLEdgeMenuPhaseHidden) {
        self.edgeMenuPointerHasVisited = NO;
    }
    self.edgeMenuLifecycleToken += 1;
    [self resetEdgeSensorSummonState];
    [self cancelEdgeMenuAutoCollapse];
    // Collapsed geometry is only a hint; it must not steal game clicks in a
    // transparent 56pt panel or use native enter events to bypass the sensor.
    self.edgeMenuPanel.ignoresMouseEvents = phase == MLEdgeMenuPhaseCollapsed || phase == MLEdgeMenuPhaseHidden;
    if (phase == MLEdgeMenuPhaseHidden) {
        self.edgeMenuTemporaryReleaseActive = NO;
        self.edgeMenuPointerInside = NO;
        self.edgeMenuButton.hidden = YES;
        [self.edgeMenuPanel orderOut:nil];
        if (wasMenu) [self.streamMenu cancelTracking];
    }
}

- (NSRect)edgeSensorActivationRectInBounds:(NSRect)bounds {
    NSRect handle = [self expandedFrameForEdgeMenuButtonInBounds:bounds];
    NSRect region = handle;
    switch (self.edgeMenuDockEdge) {
        case MLFreeMouseExitEdgeLeft: region.size.width = MLEdgeSensorBandWidth; break;
        case MLFreeMouseExitEdgeRight:
            region.origin.x = NSMaxX(bounds) - MLEdgeSensorBandWidth;
            region.size.width = MLEdgeSensorBandWidth; break;
        case MLFreeMouseExitEdgeTop:
            region.origin.y = NSMaxY(bounds) - MLEdgeSensorBandWidth;
            region.size.height = MLEdgeSensorBandWidth; break;
        case MLFreeMouseExitEdgeBottom: region.size.height = MLEdgeSensorBandWidth; break;
        default: return NSZeroRect;
    }
    return NSIntersectionRect(region, bounds);
}

- (void)handleEdgeMenuHover {
    if (![self edgeMenuCanInteract] || !self.edgeMenuButtonExpanded) return;
    [self updateEdgeMenuPointerInsideForPoint:[self currentMouseLocationInViewCoordinates]];
    if (self.edgeMenuDragging || self.edgeMenuMenuVisible) return;
    if (self.edgeMenuPointerInside) [self cancelEdgeMenuAutoCollapse];
    else [self scheduleEdgeMenuAutoCollapse];
    [self updateEdgeMenuButtonAppearance];
}

- (BOOL)edgeMenuDockEdgeUsesVerticalAxis {
    return self.edgeMenuDockEdge == MLFreeMouseExitEdgeLeft || self.edgeMenuDockEdge == MLFreeMouseExitEdgeRight;
}

- (CGFloat)resolvedEdgeMenuCoordinateInRect:(NSRect)rect {
    // Keep the handle inside small views as well as large/portrait displays.
    CGFloat axisLength = [self edgeMenuDockEdgeUsesVerticalAxis] ? rect.size.height : rect.size.width;
    CGFloat handleLength = [self edgeMenuDockEdgeUsesVerticalAxis] ? MLEdgeMenuButtonHeight : MLEdgeMenuButtonWidth;
    CGFloat inset = MIN(MLEdgeMenuButtonInsetY, MAX(0.0, (axisLength - handleLength) * 0.5));
    if ([self edgeMenuDockEdgeUsesVerticalAxis]) {
        CGFloat minValue = NSMinY(rect) + inset;
        CGFloat maxValue = MAX(minValue, NSMaxY(rect) - MLEdgeMenuButtonHeight - inset);
        CGFloat available = MAX(maxValue - minValue, 0.0);
        return minValue + available * MIN(MAX(self.edgeMenuButtonEdgeRatio, 0.0), 1.0);
    }

    CGFloat minValue = NSMinX(rect) + inset;
    CGFloat maxValue = MAX(minValue, NSMaxX(rect) - MLEdgeMenuButtonWidth - inset);
    CGFloat available = MAX(maxValue - minValue, 0.0);
    return minValue + available * MIN(MAX(self.edgeMenuButtonEdgeRatio, 0.0), 1.0);
}

- (NSRect)edgeMenuFrameInRect:(NSRect)rect expanded:(BOOL)expanded {
    CGFloat coordinate = [self resolvedEdgeMenuCoordinateInRect:rect];
    switch (self.edgeMenuDockEdge) {
        case MLFreeMouseExitEdgeLeft:
            return NSMakeRect(expanded ? NSMinX(rect) : NSMinX(rect) - MLEdgeMenuButtonWidth + MLEdgeMenuButtonVisiblePeek,
                              coordinate,
                              MLEdgeMenuButtonWidth,
                              MLEdgeMenuButtonHeight);
        case MLFreeMouseExitEdgeTop:
            return NSMakeRect(coordinate,
                              expanded ? NSMaxY(rect) - MLEdgeMenuButtonHeight : NSMaxY(rect) - MLEdgeMenuButtonVisiblePeek,
                              MLEdgeMenuButtonWidth,
                              MLEdgeMenuButtonHeight);
        case MLFreeMouseExitEdgeBottom:
            return NSMakeRect(coordinate,
                              expanded ? NSMinY(rect) : NSMinY(rect) - MLEdgeMenuButtonHeight + MLEdgeMenuButtonVisiblePeek,
                              MLEdgeMenuButtonWidth,
                              MLEdgeMenuButtonHeight);
        case MLFreeMouseExitEdgeRight:
        case MLFreeMouseExitEdgeNone:
        default:
            return NSMakeRect(expanded ? NSMaxX(rect) - MLEdgeMenuButtonWidth : NSMaxX(rect) - MLEdgeMenuButtonVisiblePeek,
                              coordinate,
                              MLEdgeMenuButtonWidth,
                              MLEdgeMenuButtonHeight);
    }
}



- (void)resetEdgeMenuPlacementForNewStreamSession {
    [self resetEdgeSensorPointerState];
    self.edgeMenuDockEdge = [self defaultEdgeMenuDockEdge];
    self.edgeMenuButtonEdgeRatio = 0.5;
    self.globalInactivePointerInsideStreamView = NO;
    [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
    self.edgeMenuPointerInside = NO;
    self.edgeMenuTemporaryReleaseActive = NO;
    [self cancelEdgeMenuAutoCollapse];
    self.edgeMenuButton.hidden = YES;
    if (self.edgeMenuPanel.parentWindow) {
        [self.edgeMenuPanel.parentWindow removeChildWindow:self.edgeMenuPanel];
    }
    [self.edgeMenuPanel orderOut:nil];
    [self updateEdgeMenuButtonAppearance];
    [self refreshMouseMovedAcceptanceState];
    // Fullscreen may have completed before connectionStarted resets the dock.
    // Reconcile visibility even when startup mode application is skipped.
    [self requestStreamMenuEntrypointsVisibilityUpdate];
    [self scheduleDeferredStreamMenuEntrypointsVisibilityRetries];
}

- (void)hideEdgeMenuForInactiveSpaceIfNeeded {
    self.globalInactivePointerInsideStreamView = NO;
    self.edgeMenuPointerInside = NO;
    self.edgeMenuTemporaryReleaseActive = NO;
    [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
    [self cancelEdgeMenuAutoCollapse];
    self.edgeMenuButton.hidden = YES;
    if (self.edgeMenuPanel.parentWindow) {
        [self.edgeMenuPanel.parentWindow removeChildWindow:self.edgeMenuPanel];
    }
    [self.edgeMenuPanel orderOut:nil];
    [self updateEdgeMenuButtonAppearance];
    [self refreshMouseMovedAcceptanceState];
}

- (void)attachEdgeMenuPanelToWindowIfNeeded {
    if (!MLUseFloatingControlOrb || !self.edgeMenuPanel || !self.view.window) {
        return;
    }
    if (![self isWindowInCurrentSpace]) {
        return;
    }

    self.edgeMenuPanel.collectionBehavior = NSWindowCollectionBehaviorFullScreenAuxiliary;

    if (self.edgeMenuPanel.parentWindow == self.view.window) {
        return;
    }

    if (self.edgeMenuPanel.parentWindow) {
        [self.edgeMenuPanel.parentWindow removeChildWindow:self.edgeMenuPanel];
    }

    [self.view.window addChildWindow:self.edgeMenuPanel ordered:NSWindowAbove];
}

- (NSRect)edgeMenuAnchorRectInScreen {
    if (!self.view.window) {
        return NSZeroRect;
    }

    // Drawing and hit testing must share the view bounds, including fullscreen
    // content insets. Window frame, backing pixels and host resolution may differ.
    NSRect rectInWindow = [self.view convertRect:self.view.bounds toView:nil];
    return [self.view.window convertRectToScreen:rectInWindow];
}

- (NSRect)collapsedFrameForEdgeMenuPanelInScreenRect:(NSRect)screenRect {
    return [self edgeMenuFrameInRect:screenRect expanded:NO];
}

- (NSRect)expandedFrameForEdgeMenuPanelInScreenRect:(NSRect)screenRect {
    return [self edgeMenuFrameInRect:screenRect expanded:YES];
}

- (NSRect)frameForCurrentEdgeMenuPanelStateInScreenRect:(NSRect)screenRect {
    return self.edgeMenuButtonExpanded
        ? [self expandedFrameForEdgeMenuPanelInScreenRect:screenRect]
        : [self collapsedFrameForEdgeMenuPanelInScreenRect:screenRect];
}

- (BOOL)edgeMenuMatchesExitEdge:(MLFreeMouseExitEdge)exitEdge {
    return exitEdge != MLFreeMouseExitEdgeNone && exitEdge == self.edgeMenuDockEdge;
}

- (NSRect)collapsedFrameForEdgeMenuButtonInBounds:(NSRect)bounds {
    return [self edgeMenuFrameInRect:bounds expanded:NO];
}

- (NSRect)expandedFrameForEdgeMenuButtonInBounds:(NSRect)bounds {
    return [self edgeMenuFrameInRect:bounds expanded:YES];
}

- (CGFloat)edgeMenuHandleThickness {
    return self.edgeMenuHandleArmed ? MLEdgeMenuHandleArmedThickness : MLEdgeMenuHandleIdleThickness;
}

// Where the tab both is and can be seen, in the stream view's own bounds. The click
// that opens the bar is measured against this rectangle and against nothing else, so
// a player is never asked to hit a seam the drawing hid, and is never handed a
// 56pt switch that was never drawn. The 2pt of air on the screen side counts as the
// tab's; the inward margin is the only tolerance added.
- (NSRect)edgeMenuVisibleHandleRectInBounds:(NSRect)bounds {
    NSRect dock = [self collapsedFrameForEdgeMenuButtonInBounds:bounds];
    CGFloat thickness = [self edgeMenuHandleThickness] + 2.0 + MLEdgeMenuHandleHitSlop;
    CGFloat shortest = MIN(NSWidth(bounds), NSHeight(bounds));
    CGFloat along = MIN(MLEdgeMenuHandleLength, shortest - 8.0);
    BOOL verticalDock = self.edgeMenuDockEdge == MLFreeMouseExitEdgeLeft ||
                        self.edgeMenuDockEdge == MLFreeMouseExitEdgeRight;
    CGFloat cross = verticalDock
        ? dock.origin.y + (NSHeight(dock) - along) / 2.0
        : dock.origin.x + (NSWidth(dock) - along) / 2.0;
    switch (self.edgeMenuDockEdge) {
        case MLFreeMouseExitEdgeLeft:
            return NSMakeRect(NSMinX(bounds), cross, thickness, along);
        case MLFreeMouseExitEdgeRight:
            return NSMakeRect(NSMaxX(bounds) - thickness, cross, thickness, along);
        case MLFreeMouseExitEdgeTop:
            return NSMakeRect(cross, NSMaxY(bounds) - thickness, along, thickness);
        case MLFreeMouseExitEdgeBottom:
            return NSMakeRect(cross, NSMinY(bounds), along, thickness);
        case MLFreeMouseExitEdgeNone:
        default:
            return NSZeroRect;
    }
}

- (NSRect)edgeMenuInteractionRectInBounds:(NSRect)bounds {
    NSRect frame = [self expandedFrameForEdgeMenuButtonInBounds:bounds];
    switch (self.edgeMenuDockEdge) {
        case MLFreeMouseExitEdgeLeft:
            frame.origin.y -= MLEdgeMenuInteractionVerticalPadding;
            frame.size.height += MLEdgeMenuInteractionVerticalPadding * 2.0;
            frame.origin.x -= MLEdgeMenuInteractionOutwardPadding;
            frame.size.width += MLEdgeMenuInteractionOutwardPadding + MLEdgeMenuInteractionInwardPadding;
            break;
        case MLFreeMouseExitEdgeRight:
            frame.origin.y -= MLEdgeMenuInteractionVerticalPadding;
            frame.size.height += MLEdgeMenuInteractionVerticalPadding * 2.0;
            frame.origin.x -= MLEdgeMenuInteractionInwardPadding;
            frame.size.width += MLEdgeMenuInteractionOutwardPadding + MLEdgeMenuInteractionInwardPadding;
            break;
        case MLFreeMouseExitEdgeTop:
            frame.origin.x -= MLEdgeMenuInteractionVerticalPadding;
            frame.size.width += MLEdgeMenuInteractionVerticalPadding * 2.0;
            frame.origin.y -= MLEdgeMenuInteractionInwardPadding;
            frame.size.height += MLEdgeMenuInteractionOutwardPadding + MLEdgeMenuInteractionInwardPadding;
            break;
        case MLFreeMouseExitEdgeBottom:
            frame.origin.x -= MLEdgeMenuInteractionVerticalPadding;
            frame.size.width += MLEdgeMenuInteractionVerticalPadding * 2.0;
            frame.origin.y -= MLEdgeMenuInteractionOutwardPadding;
            frame.size.height += MLEdgeMenuInteractionOutwardPadding + MLEdgeMenuInteractionInwardPadding;
            break;
        case MLFreeMouseExitEdgeNone:
        default:
            break;
    }
    return frame;
}

- (BOOL)isPointInsideEdgeMenuInteractionRect:(NSPoint)point {
    if (!self.edgeMenuButtonExpanded || !self.edgeMenuButton || self.edgeMenuButton.hidden) {
        return NO;
    }

    return NSPointInRect(point, [self edgeMenuInteractionRectInBounds:self.view.bounds]);
}

- (void)updateEdgeMenuPointerInsideForPoint:(NSPoint)point {
    self.edgeMenuPointerInside = [self isPointInsideEdgeMenuInteractionRect:point];
    if (self.edgeMenuPointerInside) {
        self.edgeMenuPointerHasVisited = YES;
    }
}

- (NSRect)frameForEdgeMenuButtonInBounds:(NSRect)bounds {
    return self.edgeMenuButtonExpanded
        ? [self expandedFrameForEdgeMenuButtonInBounds:bounds]
        : [self collapsedFrameForEdgeMenuButtonInBounds:bounds];
}

- (void)cancelEdgeMenuAutoCollapse {
    [self.edgeMenuAutoCollapseTimer invalidate];
    self.edgeMenuAutoCollapseTimer = nil;
}

- (BOOL)edgeMenuShouldBeVisible {
    if (!self.view.window.isVisible || self.view.window.isMiniaturized || ![NSApp isActive] || ![self isWindowInCurrentSpace] ||
        self.stopStreamInProgress || self.reconnectInProgress || self.fullscreenTransitionInProgress ||
        self.spaceTransitionInProgress) return NO;
    // Windowed mode once hid the dock entirely and left the 240pt titlebar pill as the
    // only entry, which is not where the bar lives in the other two modes: the same
    // gesture (go to an edge, click the tab) worked fullscreen and did nothing windowed,
    // and the pill merged into the titlebar with the stats overlay. The dock is now the
    // entry in every presentation; the pill stays only as a status badge and a fallback.
    if ([self isWindowFullscreen] && self.hideFullscreenControlBall) {
        return NO;
    }
    return YES;
}

- (void)updateEdgeMenuButtonTrackingArea {
    if (!self.edgeMenuButton) {
        return;
    }
    [self.edgeMenuButton updateTrackingAreas];
}

- (void)setEdgeMenuButtonExpanded:(BOOL)expanded animated:(__unused BOOL)animated {
    if (!self.edgeMenuButton || !self.edgeMenuPanel) {
        return;
    }

    if (self.edgeMenuMenuVisible || self.edgeMenuDragging) return;
    [self transitionEdgeMenuToPhase:expanded ? MLEdgeMenuPhaseExpanded : MLEdgeMenuPhaseCollapsed];
    [self cancelEdgeMenuAutoCollapse];

    if (![self edgeMenuShouldBeVisible]) {
        [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
        self.edgeMenuButton.hidden = YES;
        return;
    }

    self.edgeMenuButton.hidden = NO;

    // Showing the bar and scheduling its return are one decision. Until now only the
    // hover and menu paths armed the timer, and in locked game mode the local pointer
    // never moves: the bar stayed expanded forever, so the next summon was refused as
    // already-open and the entry looked dead after one use. handleEdgeMenuHover is the
    // one rule that reads where the pointer is and decides to wait or to schedule, and
    // it runs once the handle is on screen, so a pointer resting on the bar is read as
    // resting on the bar and not as an empty space where a bar used to be.
    [self handleEdgeMenuHover];
    [self attachEdgeMenuPanelToWindowIfNeeded];
    NSRect anchorRect = [self edgeMenuAnchorRectInScreen];
    if (NSIsEmptyRect(anchorRect)) {
        return;
    }

    NSRect targetFrame = [self frameForCurrentEdgeMenuPanelStateInScreenRect:anchorRect];
    [self updateEdgeMenuButtonAppearance];

    if (!self.edgeMenuPanel.isVisible) {
        [self.edgeMenuPanel setFrame:targetFrame display:NO];
        self.edgeMenuPanel.alphaValue = 1.0;
        [self.edgeMenuPanel orderFront:nil];
        return;
    }

    // Frame animation queues tracking events and completion writes for older
    // states. Apply one final frame synchronously so hit testing and visibility
    // always describe the same expanded/collapsed state.
    if (!NSEqualRects(self.edgeMenuPanel.frame, targetFrame)) [self.edgeMenuPanel setFrame:targetFrame display:YES];
}

- (void)deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:(BOOL)shouldRecapture {
    // Closing requires leaving the activation region before a fresh dwell.
    [self resetEdgeSensorSummonState];

    BOOL wasTemporary = self.edgeMenuTemporaryReleaseActive;
    if (self.edgeMenuMenuVisible) {
        [self.streamMenu cancelTracking];
        [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseExpanded];
    }
    NSPoint returnPoint = [self currentMouseLocationInViewCoordinates];
    self.edgeMenuTemporaryReleaseActive = NO;
    self.edgeMenuPointerInside = NO;

    [self setEdgeMenuButtonExpanded:NO animated:YES];

    self.edgeSensorMustLeaveHoverRegion = YES;
    if (wasTemporary && shouldRecapture && NSPointInRect(returnPoint, self.view.bounds) &&
        ![self hasPressedMouseButtonsForCaptureTransition] && [self canCaptureMouseNow]) {
        if ([self.hidSupport shouldUseCoreHIDFreeMouseAbsoluteSyncForCurrentConfiguration] &&
            self.isRemoteDesktopMode &&
            self.view.window != nil) {
            NSPoint currentPoint = [self currentMouseLocationInViewCoordinates];
            NSPoint reseedPoint = NSMakePoint(
                MIN(MAX(currentPoint.x, NSMinX(self.view.bounds)), NSMaxX(self.view.bounds)),
                MIN(MAX(currentPoint.y, NSMinY(self.view.bounds)), NSMaxY(self.view.bounds))
            );
            [self prepareCoreHIDVirtualCursorForSystemPointerSyncIfNeeded];
            [self syncRemoteCursorToViewPoint:reseedPoint clampToBounds:YES];
        }
        [self captureMousePreservingEdgeSensorPoint:returnPoint];
    } else {
        [self refreshMouseMovedAcceptanceState];
    }
}

- (void)scheduleEdgeMenuAutoCollapse {
    if (self.edgeMenuAutoCollapseTimer.isValid || !self.edgeMenuButtonExpanded ||
        self.edgeMenuDragging || self.edgeMenuMenuVisible) return;
    NSUInteger token = self.edgeMenuLifecycleToken;
    NSTimeInterval delay = [self edgeMenuReturnDelay];
    __weak typeof(self) weakSelf = self;
    self.edgeMenuAutoCollapseTimer = [NSTimer timerWithTimeInterval:delay repeats:NO block:^(NSTimer *timer) {
        __strong typeof(weakSelf) strongSelf = weakSelf;
        if (!strongSelf || timer != strongSelf.edgeMenuAutoCollapseTimer || token != strongSelf.edgeMenuLifecycleToken) return;
        strongSelf.edgeMenuAutoCollapseTimer = nil;
        if (![strongSelf edgeMenuCanInteract]) {
            [strongSelf transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
            return;
        }
        [strongSelf updateEdgeMenuPointerInsideForPoint:[strongSelf currentMouseLocationInViewCoordinates]];
        if (strongSelf.edgeMenuPointerInside || strongSelf.edgeMenuDragging || strongSelf.edgeMenuMenuVisible) return;
        if ([strongSelf hasPressedMouseButtonsForCaptureTransition]) {
            [strongSelf scheduleEdgeMenuAutoCollapse];
            return;
        }
        [strongSelf deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:strongSelf.edgeMenuTemporaryReleaseActive];
    }];
    [[NSRunLoop mainRunLoop] addTimer:self.edgeMenuAutoCollapseTimer forMode:NSRunLoopCommonModes];
}

- (void)activateEdgeMenuDockForExitEdge:(MLFreeMouseExitEdge)exitEdge {
    if (![self edgeMenuCanInteract] || ![self edgeMenuMatchesExitEdge:exitEdge] || ![self edgeMenuShouldBeVisible]) {
        return;
    }

    self.pendingFreeMouseReentryEdge = MLFreeMouseExitEdgeNone;
    self.pendingFreeMouseReentryAtMs = 0;
    [self setEdgeMenuButtonExpanded:YES animated:YES];
    [self refreshMouseMovedAcceptanceState];
    [self updateEdgeMenuPointerInsideForPoint:[self currentMouseLocationInViewCoordinates]];
    [self updateControlCenterEntrypointHints];
}

- (BOOL)handleEdgeMenuTemporaryReleaseForEvent:(NSEvent *)event {
    if (!self.edgeMenuButtonExpanded) return NO;
    if (self.edgeMenuDragging || self.edgeMenuMenuVisible) return YES;
    [self handleEdgeMenuHover];
    // Movement cannot race the grace timer and reclaim the pointer immediately.
    // A deliberate stream click still resumes through the button paths.
    return YES;
}

- (void)updateEdgeMenuButtonAppearance {
    if (!self.edgeMenuButton) {
        return;
    }

    BOOL active = self.edgeMenuButtonExpanded || self.edgeMenuPointerInside || self.edgeMenuTemporaryReleaseActive || self.edgeMenuDragging || self.edgeMenuMenuVisible;
    self.edgeMenuButton.activeAppearance = active;
    self.edgeMenuButton.compactAppearance = !self.edgeMenuButtonExpanded && !self.edgeMenuTemporaryReleaseActive && !self.edgeMenuDragging && !self.edgeMenuMenuVisible;
    // Arming only ever shows on the tab: an open bar does not need a second signal,
    // and the phase transition clears the flag before the bar is on screen anyway.
    self.edgeMenuButton.armedAppearance = self.edgeMenuHandleArmed && !self.edgeMenuButtonExpanded;
    self.edgeMenuButton.dockEdge = self.edgeMenuDockEdge;
}

- (void)handleEdgeMenuButtonDragWithState:(NSGestureRecognizerState)state translation:(NSPoint)translation {
    if (!self.edgeMenuButton || self.edgeMenuButton.hidden || !self.edgeMenuPanel || self.edgeMenuMenuVisible || ![self edgeMenuCanInteract]) {
        return;
    }

    // A visible view may belong to a newer lifecycle after hide/show. Only
    // an expanded handle can start a drag; later callbacks require that drag.
    if (state == NSGestureRecognizerStateBegan) {
        if (self.edgeMenuPhase != MLEdgeMenuPhaseExpanded) return;
    } else if (!self.edgeMenuDragging) {
        return;
    }

    switch (state) {
        case NSGestureRecognizerStateBegan:
            [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseDragging];
            self.edgeMenuPointerInside = YES;
            [self cancelEdgeMenuAutoCollapse];
            [self setEdgeMenuButtonExpanded:YES animated:NO];
            self.edgeMenuButtonPanStartOrigin = self.edgeMenuPanel.frame.origin;
            [self refreshMouseMovedAcceptanceState];
            [self updateEdgeMenuButtonAppearance];
            break;
        case NSGestureRecognizerStateChanged: {
            NSRect anchorRect = [self edgeMenuAnchorRectInScreen];
            if (NSIsEmptyRect(anchorRect)) {
                break;
            }

            NSRect frame = self.edgeMenuPanel.frame;
            frame.origin.x = self.edgeMenuButtonPanStartOrigin.x + translation.x;
            frame.origin.y = self.edgeMenuButtonPanStartOrigin.y + translation.y;

            CGFloat minX = NSMinX(anchorRect);
            CGFloat maxX = NSMaxX(anchorRect) - MLEdgeMenuButtonWidth;
            CGFloat minY = NSMinY(anchorRect);
            CGFloat maxY = NSMaxY(anchorRect) - MLEdgeMenuButtonHeight;
            frame.origin.x = MIN(MAX(frame.origin.x, minX), maxX);
            frame.origin.y = MIN(MAX(frame.origin.y, minY), maxY);
            [self.edgeMenuPanel setFrame:frame display:YES];
            break;
        }
        case NSGestureRecognizerStateEnded:
        case NSGestureRecognizerStateCancelled:
        case NSGestureRecognizerStateFailed: {
            [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseExpanded];
            NSRect anchorRect = [self edgeMenuAnchorRectInScreen];
            if (NSIsEmptyRect(anchorRect)) {
                [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
                break;
            }

            NSRect frame = self.edgeMenuPanel.frame;
            CGFloat centerX = NSMidX(frame);
            CGFloat centerY = NSMidY(frame);
            CGFloat leftDistance = fabs(centerX - NSMinX(anchorRect));
            CGFloat rightDistance = fabs(NSMaxX(anchorRect) - centerX);
            CGFloat topDistance = fabs(NSMaxY(anchorRect) - centerY);
            CGFloat bottomDistance = fabs(centerY - NSMinY(anchorRect));

            self.edgeMenuDockEdge = MLFreeMouseExitEdgeLeft;
            CGFloat bestDistance = leftDistance;
            if (rightDistance < bestDistance) {
                bestDistance = rightDistance;
                self.edgeMenuDockEdge = MLFreeMouseExitEdgeRight;
            }
            if (topDistance < bestDistance) {
                bestDistance = topDistance;
                self.edgeMenuDockEdge = MLFreeMouseExitEdgeTop;
            }
            if (bottomDistance < bestDistance) {
                self.edgeMenuDockEdge = MLFreeMouseExitEdgeBottom;
            }

            if ([self edgeMenuDockEdgeUsesVerticalAxis]) {
                CGFloat inset = MIN(MLEdgeMenuButtonInsetY, MAX(0, (NSHeight(anchorRect) - MLEdgeMenuButtonHeight) * 0.5));
                CGFloat minY = NSMinY(anchorRect) + inset;
                CGFloat maxY = MAX(minY, NSMaxY(anchorRect) - MLEdgeMenuButtonHeight - inset);
                CGFloat availableHeight = MAX(maxY - minY, 1.0);
                self.edgeMenuButtonEdgeRatio = MIN(MAX((frame.origin.y - minY) / availableHeight, 0.0), 1.0);
            } else {
                CGFloat inset = MIN(MLEdgeMenuButtonInsetY, MAX(0, (NSWidth(anchorRect) - MLEdgeMenuButtonWidth) * 0.5));
                CGFloat minX = NSMinX(anchorRect) + inset;
                CGFloat maxX = MAX(minX, NSMaxX(anchorRect) - MLEdgeMenuButtonWidth - inset);
                CGFloat availableWidth = MAX(maxX - minX, 1.0);
                self.edgeMenuButtonEdgeRatio = MIN(MAX((frame.origin.x - minX) / availableWidth, 0.0), 1.0);
            }

            [self updateEdgeMenuPointerInsideForPoint:[self currentMouseLocationInViewCoordinates]];
            [self setEdgeMenuButtonExpanded:YES animated:YES];
            [self updateEdgeMenuPointerInsideForPoint:[self currentMouseLocationInViewCoordinates]];
            if (!self.edgeMenuPointerInside) [self scheduleEdgeMenuAutoCollapse];
            [self updateEdgeMenuButtonTrackingArea];
            [self refreshMouseMovedAcceptanceState];
            [self updateEdgeMenuButtonAppearance];
            break;
        }
        default:
            break;
    }
}

- (void)startControlCenterTimerIfNeeded {
    if (!MLUseOnScreenControlCenterEntrypoints) {
        return;
    }
    if (self.controlCenterTimer) {
        return;
    }
    self.controlCenterTimer = [NSTimer timerWithTimeInterval:MLControlCenterRefreshIntervalSec
                                                      target:self
                                                    selector:@selector(updateControlCenterStatus)
                                                    userInfo:nil
                                                     repeats:YES];
    self.controlCenterTimer.tolerance = 0.1;
    [[NSRunLoop mainRunLoop] addTimer:self.controlCenterTimer forMode:NSRunLoopCommonModes];
    [self updateControlCenterStatus];
}

- (void)bringStreamControlsToFront {
    if (![self isWindowInCurrentSpace]) {
        return;
    }
    if (self.edgeMenuPanel && self.edgeMenuPanel.isVisible) {
        @try {
            [self.edgeMenuPanel orderFront:nil];
        } @catch (NSException *exc) {
            Log(LOG_W, @"[ui] edgeMenuPanel orderFront failed: %@ %@", exc.name, exc.reason);
        }
    }
    if (self.edgeMenuButton) {
        @try {
            [self.edgeMenuButton.superview addSubview:self.edgeMenuButton positioned:NSWindowAbove relativeTo:nil];
        } @catch (NSException *exc) {
            Log(LOG_W, @"[ui] edgeMenuButton z-order failed: %@ %@", exc.name, exc.reason);
        }
    }
    if (self.overlayContainer) {
        @try {
            [self.view addSubview:self.overlayContainer positioned:NSWindowAbove relativeTo:nil];
        } @catch (NSException *exc) {
            Log(LOG_W, @"[ui] overlayContainer z-order failed: %@ %@", exc.name, exc.reason);
        }
    }
    if (self.logOverlayContainer) {
        @try {
            [self.view addSubview:self.logOverlayContainer positioned:NSWindowAbove relativeTo:nil];
        } @catch (NSException *exc) {
            Log(LOG_W, @"[ui] logOverlayContainer z-order failed: %@ %@", exc.name, exc.reason);
        }
    }
    if (self.reconnectOverlayContainer) {
        @try {
            [self.view addSubview:self.reconnectOverlayContainer positioned:NSWindowAbove relativeTo:nil];
        } @catch (NSException *exc) {
            Log(LOG_W, @"[ui] reconnectOverlayContainer z-order failed: %@ %@", exc.name, exc.reason);
        }
    }
}

- (NSString *)formatElapsed:(NSTimeInterval)seconds {
    NSInteger total = MAX(0, (NSInteger)llround(seconds));
    NSInteger h = total / 3600;
    NSInteger m = (total % 3600) / 60;
    NSInteger s = total % 60;
    if (h > 0) {
        return [NSString stringWithFormat:@"%02ld:%02ld:%02ld", (long)h, (long)m, (long)s];
    }
    return [NSString stringWithFormat:@"%02ld:%02ld", (long)m, (long)s];
}

- (NSString *)currentPreferredAddressForStatus {
    NSDictionary *prefs = [SettingsClass getSettingsFor:self.app.host.uuid];
    NSString *method = prefs[@"connectionMethod"];
    if (method && ![method isEqualToString:@"Auto"]) {
        return method;
    }
    if (self.app.host.activeAddress.length > 0) {
        return self.app.host.activeAddress;
    }

    NSArray<NSString *> *candidates = @[ self.app.host.localAddress ?: @"",
                                         self.app.host.address ?: @"",
                                         self.app.host.externalAddress ?: @"",
                                         self.app.host.ipv6Address ?: @"" ];
    NSString *bestAddr = nil;
    NSInteger bestLatency = NSIntegerMax;

    for (NSString *addr in candidates) {
        if (addr.length == 0) continue;
        NSNumber *state = self.app.host.addressStates[addr];
        BOOL online = state ? (state.intValue == 1) : YES;
        if (!online) continue;

        NSNumber *latency = self.app.host.addressLatencies[addr];
        if (latency != nil && latency.intValue >= 0) {
            if (latency.intValue < bestLatency) {
                bestLatency = latency.intValue;
                bestAddr = addr;
            }
        } else if (bestAddr == nil) {
            bestAddr = addr;
        }
    }

    return bestAddr;
}

- (BOOL)isActiveStreamGeneration:(NSUInteger)generation {
    return generation != 0 && generation == self.activeStreamGeneration;
}

- (NSString *)formattedLatencyTextForDisplay:(NSNumber *)latencyNumber {
    if (latencyNumber == nil || latencyNumber.integerValue < 0) {
        return nil;
    }

    NSInteger latencyMs = MAX(1, latencyNumber.integerValue);
    return [NSString stringWithFormat:@"%ldms", (long)latencyMs];
}

- (NSString *)currentLatencyLogSummary {
    PML_CONTROL_STREAM_CONTEXT controlCtx = self.streamMan.connection ? (PML_CONTROL_STREAM_CONTEXT)[self.streamMan.connection controlStreamContext] : NULL;
    NSString *controlSummary = MLRttLogSummary(controlCtx);
    if (![controlSummary isEqualToString:@"n/a"]) {
        return controlSummary;
    }

    NSString *addr = [self currentPreferredAddressForStatus];
    NSNumber *latency = addr ? self.app.host.addressLatencies[addr] : nil;
    if (latency != nil && latency.integerValue >= 0) {
        NSInteger pathProbeMs = MAX(1, latency.integerValue);
        NSString *pathText = [NSString stringWithFormat:@"%ld", (long)pathProbeMs];
        return [NSString stringWithFormat:@"probe~%@", pathText];
    }

    return @"n/a";
}

- (NSInteger)currentLatencyMs {
    // If we are actively streaming, use the real-time RTT.
    if ([self hasReceivedAnyVideoFrames]) {
        uint32_t rtt = 0;
        uint32_t rttVar = 0;
        PML_CONTROL_STREAM_CONTEXT controlCtx = self.streamMan.connection ? (PML_CONTROL_STREAM_CONTEXT)[self.streamMan.connection controlStreamContext] : NULL;
        if (MLGetUsableRttInfo(controlCtx, &rtt, &rttVar)) {
            return (NSInteger)MAX((uint32_t)1, rtt);
        }
    }

    NSString *addr = [self currentPreferredAddressForStatus];
    NSNumber *latency = addr ? self.app.host.addressLatencies[addr] : nil;
    if (!latency) {
        return -1;
    }
    return MAX(1, latency.integerValue);
}

// Only anomalies produce a badge. Returning the action name here is what widened the
// titlebar pill into a fake button and pushed the edge tab out of the picture.
- (NSString *)currentStreamHealthBadgeText {
    if (self.streamHealthNoPayloadStreak > 0) {
        return [NSString stringWithFormat:MLString(@"Stuck %lus", nil), (unsigned long)self.streamHealthNoPayloadStreak];
    }
    if (self.streamHealthHighDropStreak >= 2) {
        return MLString(@"High packet loss", nil);
    }
    return @"";
}

- (void)updateControlCenterStatus {
    if (!MLUseOnScreenControlCenterEntrypoints) {
        return;
    }
    if (!self.controlCenterTimeLabel || !self.controlCenterSignalImageView) {
        return;
    }

    NSTimeInterval elapsed = self.streamStartDate ? [[NSDate date] timeIntervalSinceDate:self.streamStartDate] : 0;
    self.controlCenterTimeLabel.stringValue = [self formatElapsed:elapsed];

    NSInteger latency = [self currentLatencyMs];
    NSString *symbol = @"wifi";
    if (self.streamHealthNoPayloadStreak >= 2 || self.streamHealthFrozenStatsStreak >= 2) {
        symbol = @"wifi.exclamationmark";
    } else if (latency < 0) {
        symbol = @"wifi.slash";
    } else if (latency <= 30) {
        symbol = @"cellularbars";
    } else if (latency <= 60) {
        symbol = @"cellularbars.3";
    } else if (latency <= 100) {
        symbol = @"cellularbars.2";
    } else {
        symbol = @"cellularbars.1";
    }

    if (@available(macOS 11.0, *)) {
        NSImage *img = [NSImage imageWithSystemSymbolName:symbol accessibilityDescription:nil];
        if (!img) {
            img = [NSImage imageWithSystemSymbolName:@"wifi" accessibilityDescription:nil];
        }
        self.controlCenterSignalImageView.image = img;
    }

    if (self.controlCenterTitleLabel) {
        NSString *badge = [self currentStreamHealthBadgeText];
        self.controlCenterTitleLabel.stringValue = badge;
        // The badge and the clock share the pill's text slot; a healthy stream shows the
        // clock, a stalled one shows what is wrong. Two labels drawn over each other
        // read as one unreadable label.
        self.controlCenterTimeLabel.hidden = badge.length > 0;
    }
}

- (void)installStreamMenuEntrypoints {
    if (!MLUseFloatingControlOrb) {
        return;
    }

    if (self.edgeMenuPanel && self.edgeMenuButton) {
        [self attachEdgeMenuPanelToWindowIfNeeded];
        [self requestStreamMenuEntrypointsVisibilityUpdate];
        return;
    }

    self.edgeMenuPanel = [[MLEdgeMenuPanel alloc] initWithContentRect:NSMakeRect(0, 0, MLEdgeMenuButtonWidth, MLEdgeMenuButtonHeight)
                                                            styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
                                                              backing:NSBackingStoreBuffered
                                                                defer:NO];
    self.edgeMenuPanel.opaque = NO;
    self.edgeMenuPanel.backgroundColor = NSColor.clearColor;
    self.edgeMenuPanel.hasShadow = NO;
    self.edgeMenuPanel.hidesOnDeactivate = NO;
    self.edgeMenuPanel.level = NSStatusWindowLevel;
    self.edgeMenuPanel.releasedWhenClosed = NO;
    self.edgeMenuPanel.acceptsMouseMovedEvents = YES;
    self.edgeMenuPanel.ignoresMouseEvents = NO;

    NSView *panelContentView = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, MLEdgeMenuButtonWidth, MLEdgeMenuButtonHeight)];
    panelContentView.wantsLayer = YES;
    panelContentView.layer.backgroundColor = NSColor.clearColor.CGColor;
    self.edgeMenuPanel.contentView = panelContentView;

    NSImage *edgeMenuImage = [NSImage imageWithSystemSymbolName:@"slider.horizontal.3" accessibilityDescription:nil];
    if (@available(macOS 11.0, *)) {
        NSImageSymbolConfiguration *config = [NSImageSymbolConfiguration configurationWithPointSize:18
                                                                                             weight:NSFontWeightSemibold
                                                                                              scale:NSImageSymbolScaleLarge];
        edgeMenuImage = [edgeMenuImage imageWithSymbolConfiguration:config];
    }

    self.edgeMenuButton = [[MLEdgeMenuHandleView alloc] initWithFrame:panelContentView.bounds];
    self.edgeMenuButton.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.edgeMenuButton.iconView.image = edgeMenuImage;
    self.edgeMenuButton.hidden = YES;
    __weak typeof(self) weakSelf = self;
    self.edgeMenuButton.activationHandler = ^(NSEvent *event) {
        __strong typeof(weakSelf) strongSelf = weakSelf;
        if (!strongSelf) {
            return;
        }
        [strongSelf handleStreamMenuButtonPressed:strongSelf.edgeMenuButton event:event];
    };
    self.edgeMenuButton.dragHandler = ^(NSGestureRecognizerState state, NSPoint translation) {
        __strong typeof(weakSelf) strongSelf = weakSelf;
        if (!strongSelf) {
            return;
        }
        [strongSelf handleEdgeMenuButtonDragWithState:state translation:translation];
    };
    self.edgeMenuButton.hoverHandler = ^(__unused BOOL hovering) {
        __strong typeof(weakSelf) strongSelf = weakSelf;
        [strongSelf handleEdgeMenuHover];
    };
    [panelContentView addSubview:self.edgeMenuButton];

    [self attachEdgeMenuPanelToWindowIfNeeded];
    [self updateEdgeMenuButtonAppearance];
    [self updateControlCenterEntrypointHints];
    [self requestStreamMenuEntrypointsVisibilityUpdate];
}

- (void)layoutStreamMenuEntrypointsIfNeeded {
    if (!MLUseFloatingControlOrb) {
        return;
    }
    if (![self isWindowInCurrentSpace]) {
        [self hideEdgeMenuForInactiveSpaceIfNeeded];
        return;
    }
    if (!self.edgeMenuButton || self.edgeMenuButton.hidden || !self.edgeMenuPanel) {
        return;
    }
    if (self.edgeMenuDragging) {
        [self.edgeMenuPanel orderFront:nil];
        return;
    }

    NSRect anchorRect = [self edgeMenuAnchorRectInScreen];
    if (NSIsEmptyRect(anchorRect)) {
        return;
    }

    [self attachEdgeMenuPanelToWindowIfNeeded];
    [self.edgeMenuPanel setFrame:[self frameForCurrentEdgeMenuPanelStateInScreenRect:anchorRect] display:YES];
    [self.edgeMenuPanel orderFront:nil];
    [self updateEdgeMenuButtonTrackingArea];
}

- (void)requestStreamMenuEntrypointsVisibilityUpdate {
    if (!MLUseFloatingControlOrb) {
        return;
    }
    if (![NSThread isMainThread]) {
        dispatch_async(dispatch_get_main_queue(), ^{
            [self requestStreamMenuEntrypointsVisibilityUpdate];
        });
        return;
    }

    if (self.streamMenuEntrypointsUpdateScheduled) {
        return;
    }

    self.streamMenuEntrypointsUpdateScheduled = YES;
    dispatch_async(dispatch_get_main_queue(), ^{
        self.streamMenuEntrypointsUpdateScheduled = NO;
        [self updateStreamMenuEntrypointsVisibility];
    });
}

- (void)scheduleDeferredStreamMenuEntrypointsVisibilityRetries {
    if (!MLUseFloatingControlOrb) {
        return;
    }

    __weak typeof(self) weakSelf = self;
    static const NSTimeInterval retryDelays[] = { 0.10, 0.28, 0.55 };
    for (NSUInteger i = 0; i < sizeof(retryDelays) / sizeof(retryDelays[0]); i++) {
        NSTimeInterval delay = retryDelays[i];
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(delay * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
            __strong typeof(weakSelf) strongSelf = weakSelf;
            if (!strongSelf || !strongSelf.view.window || strongSelf.stopStreamInProgress || strongSelf.reconnectInProgress) {
                return;
            }

            [strongSelf requestStreamMenuEntrypointsVisibilityUpdate];
            if ([strongSelf isWindowInCurrentSpace]) {
                [strongSelf bringStreamControlsToFront];
            }
        });
    }
}

- (void)updateStreamMenuEntrypointsVisibility {
    if (![NSThread isMainThread]) {
        dispatch_async(dispatch_get_main_queue(), ^{
            [self updateStreamMenuEntrypointsVisibility];
        });
        return;
    }
    if (!self.view.window) {
        return;
    }
    if (![self isWindowInCurrentSpace]) {
        [self removeMenuTitlebarAccessoryFromWindowIfNeeded];
        [self hideEdgeMenuForInactiveSpaceIfNeeded];
        return;
    }
    if (self.fullscreenTransitionInProgress || self.spaceTransitionInProgress || self.stopStreamInProgress || self.reconnectInProgress) {
        [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
        [self removeMenuTitlebarAccessoryFromWindowIfNeeded];
        self.edgeMenuButton.hidden = YES;
        [self.edgeMenuPanel orderOut:nil];
        return;
    }
    if (self.edgeMenuDragging) {
        [self ensureMenuTitlebarAccessoryInstalledIfNeeded];
        if (MLUseFloatingControlOrb) {
            [self.edgeMenuPanel orderFront:nil];
        }
        return;
    }

    [self ensureMenuTitlebarAccessoryInstalledIfNeeded];

    if (!MLUseFloatingControlOrb) {
        return;
    }

    [self attachEdgeMenuPanelToWindowIfNeeded];
    if ([self edgeMenuShouldBeVisible]) {
        if (self.edgeMenuPhase == MLEdgeMenuPhaseHidden) [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseCollapsed];
        self.edgeMenuButton.hidden = NO;
        [self layoutStreamMenuEntrypointsIfNeeded];
        [self updateEdgeMenuButtonAppearance];
        [self bringStreamControlsToFront];
    } else {
        self.edgeMenuButton.hidden = YES;
        [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
        self.edgeMenuTemporaryReleaseActive = NO;
        [self cancelEdgeMenuAutoCollapse];
        [self.edgeMenuPanel orderOut:nil];
    }

    [self updateControlCenterEntrypointHints];
}

- (void)handleStreamMenuButtonPressed:(id)sender event:(NSEvent *)event {
    NSView *sourceView = nil;
    if ([sender isKindOfClass:[NSView class]]) {
        sourceView = (NSView *)sender;
    } else {
        sourceView = self.view;
    }

    [self presentStreamMenuFromView:sourceView event:event];
}

- (void)presentStreamMenuFromView:(NSView *)sourceView {
    [self presentStreamMenuFromView:sourceView event:nil];
}

- (void)presentStreamMenuFromView:(NSView *)sourceView event:(NSEvent *)event {
    if (self.edgeMenuMenuVisible || self.edgeMenuDragging || ![self edgeMenuCanInteract]) return;
    [self rebuildStreamMenu];
    NSMenu *menu = self.streamMenu;

    NSRect bounds = sourceView.bounds;
    NSPoint p = NSMakePoint(NSMidX(bounds), NSMinY(bounds));
    if (sourceView == self.edgeMenuButton) {
        switch (self.edgeMenuDockEdge) {
            case MLFreeMouseExitEdgeLeft:
                p = NSMakePoint(NSMaxX(bounds), NSMidY(bounds));
                break;
            case MLFreeMouseExitEdgeTop:
                p = NSMakePoint(NSMidX(bounds), NSMinY(bounds));
                break;
            case MLFreeMouseExitEdgeBottom:
                p = NSMakePoint(NSMidX(bounds), NSMaxY(bounds));
                break;
            case MLFreeMouseExitEdgeRight:
            case MLFreeMouseExitEdgeNone:
            default:
                p = NSMakePoint(NSMinX(bounds), NSMidY(bounds));
                break;
        }
    }

    BOOL wasCaptured = self.isMouseCaptured;
    if (wasCaptured) [self uncaptureMouseWithCode:@"MUC203" reason:@"stream-menu-open"];
    if (self.isMouseCaptured) return;
    self.edgeMenuTemporaryReleaseActive |= wasCaptured && !self.userReleasedInput;
    if (sourceView == self.edgeMenuButton && [self edgeMenuShouldBeVisible]) {
        [self setEdgeMenuButtonExpanded:YES animated:NO];
    }
    [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseMenu];
    NSUInteger menuToken = self.edgeMenuLifecycleToken;
    [self refreshMouseMovedAcceptanceState];
    if (sourceView == self.edgeMenuButton && event != nil) {
        [NSMenu popUpContextMenu:menu withEvent:event forView:sourceView];
    } else {
        [menu popUpMenuPositioningItem:nil atLocation:p inView:sourceView];
    }
    // Menu tracking runs a nested loop: teardown/fullscreen changes may have
    // invalidated this invocation before it returns.
    if (menuToken != self.edgeMenuLifecycleToken) return;
    if (![self edgeMenuCanInteract]) {
        [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden];
        [self refreshMouseMovedAcceptanceState];
        return;
    }
    [self transitionEdgeMenuToPhase:MLEdgeMenuPhaseExpanded];
    [self updateEdgeMenuPointerInsideForPoint:[self currentMouseLocationInViewCoordinates]];
    [self refreshMouseMovedAcceptanceState];

    if (!self.edgeMenuPointerInside && !self.edgeMenuDragging) {
        [self scheduleEdgeMenuAutoCollapse];
    }
}

- (void)rebuildStreamMenu {
    if (![NSThread isMainThread]) {
        dispatch_async(dispatch_get_main_queue(), ^{
            [self rebuildStreamMenu];
        });
        return;
    }
    // Settings/diagnostic updates can run in NSMenu's nested tracking loop.
    // Preserve the active menu; the next presentation rebuilds from live state.
    if (self.edgeMenuMenuVisible) return;
    if (!self.streamMenu) {
        self.streamMenu = [[NSMenu alloc] initWithTitle:@"StreamMenu"];
    }
    [self.streamMenu removeAllItems];

    void (^setSymbol)(NSMenuItem *, NSString *) = ^(NSMenuItem *item, NSString *symbolName) {
        if (@available(macOS 11.0, *)) {
            item.image = [NSImage imageWithSystemSymbolName:symbolName accessibilityDescription:nil];
        }
    };

    // 一级顶部：鼠标模式
    NSDictionary *prefs = [SettingsClass getSettingsFor:self.app.host.uuid];
    NSString *mouseMode = [SettingsClass mouseModeFor:self.app.host.uuid];
    BOOL isRemoteMode = [mouseMode isEqualToString:@"remote"];

    NSMenuItem *mouseModeItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Mouse and Cursor", nil)
                                                           action:nil
                                                    keyEquivalent:@""];
    setSymbol(mouseModeItem, @"cursorarrow.motionlines");
    NSMenu *mouseModeMenu = [[NSMenu alloc] initWithTitle:MLString(@"Mouse and Cursor", nil)];

    NSMenuItem *currentModeItem = [[NSMenuItem alloc] initWithTitle:[NSString stringWithFormat:MLString(@"Current: %@", nil), [self mouseModeDisplayNameForMode:mouseMode]]
                                                             action:nil
                                                      keyEquivalent:@""];
    currentModeItem.enabled = NO;
    [mouseModeMenu addItem:currentModeItem];

    NSMenuItem *currentHintItem = [[NSMenuItem alloc] initWithTitle:[self mouseModeHintForMode:mouseMode]
                                                             action:nil
                                                      keyEquivalent:@""];
    currentHintItem.enabled = NO;
    [mouseModeMenu addItem:currentHintItem];

    [mouseModeMenu addItem:[NSMenuItem separatorItem]];

    NSMenuItem *lockedMouseItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Locked Mouse", nil)
                                                             action:@selector(selectLockedMouseModeFromMenu:)
                                                      keyEquivalent:@""];
    lockedMouseItem.target = self;
    lockedMouseItem.state = isRemoteMode ? NSControlStateValueOff : NSControlStateValueOn;
    setSymbol(lockedMouseItem, @"gamecontroller");
    [mouseModeMenu addItem:lockedMouseItem];

    NSMenuItem *freeMouseItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Free Mouse", nil)
                                                           action:@selector(selectFreeMouseModeFromMenu:)
                                                    keyEquivalent:@""];
    freeMouseItem.target = self;
    freeMouseItem.state = isRemoteMode ? NSControlStateValueOn : NSControlStateValueOff;
    setSymbol(freeMouseItem, @"desktopcomputer");
    [mouseModeMenu addItem:freeMouseItem];

    NSMenuItem *toggleMouseItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Toggle mouse mode", nil)
        action:@selector(toggleMouseModeFromMenu:) keyEquivalent:@""];
    toggleMouseItem.target = self;
    [self applyShortcut:[self streamShortcutForAction:MLShortcutActionToggleMouseMode] toMenuItem:toggleMouseItem];
    [mouseModeMenu addItem:toggleMouseItem];

    NSString *releaseHint = self.userReleasedInput ? MLString(@"Click stream to resume input", nil) : [self releaseMouseHintText];
    NSString *controlCenterHint = [self openControlCenterHintText];
    if (releaseHint.length > 0 || controlCenterHint.length > 0) {
        [mouseModeMenu addItem:[NSMenuItem separatorItem]];
    }

    if (releaseHint.length > 0) {
        NSMenuItem *releaseHintItem = [[NSMenuItem alloc] initWithTitle:releaseHint action:nil keyEquivalent:@""];
        releaseHintItem.enabled = NO;
        [mouseModeMenu addItem:releaseHintItem];
    }

    if (controlCenterHint.length > 0) {
        NSMenuItem *controlCenterHintItem = [[NSMenuItem alloc] initWithTitle:controlCenterHint action:nil keyEquivalent:@""];
        controlCenterHintItem.enabled = NO;
        [mouseModeMenu addItem:controlCenterHintItem];
    }

    mouseModeItem.submenu = mouseModeMenu;
    [self.streamMenu addItem:mouseModeItem];

    // 一级顶部：重连
    NSMenuItem *reconnectItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Reconnect Stream", nil) action:@selector(reconnectFromMenu:) keyEquivalent:@""];
    [self applyShortcut:[self streamShortcutForAction:MLShortcutActionReconnectStream] toMenuItem:reconnectItem];
    reconnectItem.target = self;
    setSymbol(reconnectItem, @"arrow.triangle.2.circlepath");
    [self.streamMenu addItem:reconnectItem];

    [self.streamMenu addItem:[NSMenuItem separatorItem]];

    // NSDictionary *prefs = [SettingsClass getSettingsFor:self.app.host.uuid]; // Already defined above

    // 二级：窗口
    NSMenuItem *windowItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Window", nil) action:nil keyEquivalent:@""];
    windowItem.tag = StreamMenuSectionWindow;
    setSymbol(windowItem, @"macwindow");
    NSMenu *windowMenu = [[NSMenu alloc] initWithTitle:MLString(@"Window", nil)]; 

    BOOL isFullscreen = [self isWindowFullscreen];
    BOOL isBorderless = ((self.view.window.styleMask & NSWindowStyleMaskTitled) == 0) && !isFullscreen;
    BOOL isWindowed = !isFullscreen && !isBorderless;

    NSMenuItem *windowedItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Window Mode", nil) action:@selector(switchToWindowedMode:) keyEquivalent:@""];
    windowedItem.target = self;
    windowedItem.state = isWindowed ? NSControlStateValueOn : NSControlStateValueOff;
    setSymbol(windowedItem, @"macwindow");
    [windowMenu addItem:windowedItem];

    NSMenuItem *fullscreenItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Fullscreen Mode", nil) action:@selector(switchToFullscreenMode:) keyEquivalent:@"f"];
    fullscreenItem.keyEquivalentModifierMask = NSEventModifierFlagControl | NSEventModifierFlagCommand;
    fullscreenItem.target = self;
    fullscreenItem.state = isFullscreen ? NSControlStateValueOn : NSControlStateValueOff;
    setSymbol(fullscreenItem, @"arrow.up.left.and.arrow.down.right");
    [windowMenu addItem:fullscreenItem];

    NSMenuItem *borderlessItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Borderless Window", nil) action:@selector(switchToBorderlessMode:) keyEquivalent:@""];
    borderlessItem.target = self;
    borderlessItem.state = isBorderless ? NSControlStateValueOn : NSControlStateValueOff;
    setSymbol(borderlessItem, @"rectangle.dashed");
    [windowMenu addItem:borderlessItem];

    [windowMenu addItem:[NSMenuItem separatorItem]];

    NSMenuItem *toggleBallItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Fullscreen Control Ball", nil) action:@selector(toggleFullscreenControlBallFromMenu:) keyEquivalent:@""];
    [self applyShortcut:[self streamShortcutForAction:MLShortcutActionToggleFullscreenControlBall] toMenuItem:toggleBallItem];
    toggleBallItem.target = self;
    toggleBallItem.state = self.hideFullscreenControlBall ? NSControlStateValueOff : NSControlStateValueOn;
    setSymbol(toggleBallItem, @"dot.circle.and.hand.point.up.left.fill");
    [windowMenu addItem:toggleBallItem];

    [windowMenu addItem:[NSMenuItem separatorItem]];

    NSMenuItem *detailsItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Connection Details", nil) action:@selector(toggleOverlay) keyEquivalent:@""];
    [self applyShortcut:[self streamShortcutForAction:MLShortcutActionTogglePerformanceOverlay] toMenuItem:detailsItem];
    detailsItem.target = self;
    detailsItem.state = self.overlayContainer ? NSControlStateValueOn : NSControlStateValueOff;
    setSymbol(detailsItem, @"gauge.with.dots.needle.33percent");
    [windowMenu addItem:detailsItem];

    windowItem.submenu = windowMenu;
    [self.streamMenu addItem:windowItem];

    // 二级：屏幕（分辨率/帧率）
    NSMenuItem *monitorItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Monitor", nil) action:nil keyEquivalent:@""];
    monitorItem.tag = StreamMenuSectionMonitor;
    setSymbol(monitorItem, @"display");
    NSMenu *monitorMenu = [[NSMenu alloc] initWithTitle:MLString(@"Monitor", nil)];

    // 1. Follow Monitor
    CGSize refreshLocalSize = CGSizeZero;
    if ([self.view.window screen]) {
        NSRect screenFrame = [self.view.window screen].frame;
        CGFloat scale = [self.view.window screen].backingScaleFactor;
        refreshLocalSize = CGSizeMake(screenFrame.size.width * scale, screenFrame.size.height * scale);
    }
    
    NSString *matchDisplayTitle = MLString(@"Follow Monitor", nil);
    if (refreshLocalSize.width > 0 && refreshLocalSize.height > 0) {
        matchDisplayTitle = [NSString stringWithFormat:@"%@ (%.0fx%.0f)", matchDisplayTitle, refreshLocalSize.width, refreshLocalSize.height];
    }

    NSMenuItem *matchDisplayItem = [[NSMenuItem alloc] initWithTitle:matchDisplayTitle action:@selector(selectMatchDisplayFromMenu:) keyEquivalent:@""];
    matchDisplayItem.target = self;
    
    NSDictionary *currentPrefs = [SettingsClass getSettingsFor:self.app.host.uuid];
    BOOL isMatchDisplay = currentPrefs ? [currentPrefs[@"matchDisplayResolution"] boolValue] : NO;
    matchDisplayItem.state = isMatchDisplay ? NSControlStateValueOn : NSControlStateValueOff;

    setSymbol(matchDisplayItem, @"macwindow.badge.plus");
    [monitorMenu addItem:matchDisplayItem];

    struct Resolution currentRes = [self.class getResolution];
    
    int currentFps = 0;
    if (prefs) {
        int rawFps = [prefs[@"fps"] intValue];
        if (rawFps == 0) {
            currentFps = [prefs[@"customFps"] intValue];
        } else {
            currentFps = rawFps;
        }
    }
    if (currentFps == 0) {
        TemporarySettings *tempSettings = [[DataManager alloc] getSettings];
        currentFps = [tempSettings.framerate intValue];
    }

    // Check if effective config is 0x0 (which we interpret as Host Native)
    BOOL isMatchHost = (!isMatchDisplay && currentRes.width == 0 && currentRes.height == 0);

    [monitorMenu addItem:[NSMenuItem separatorItem]];
    
    // 3. Custom
    NSMenuItem *customItem = [[NSMenuItem alloc] initWithTitle:[MLString(@"Custom Resolution", nil) stringByAppendingString:@"..."] action:@selector(selectCustomResolutionFromMenu:) keyEquivalent:@""];
    customItem.target = self;
    setSymbol(customItem, @"slider.horizontal.below.rectangle");
    [monitorMenu addItem:customItem];

    [monitorMenu addItem:[NSMenuItem separatorItem]];

    // 4. Resolutions Submenu
    // Determine if we should show "Current Resolution" or if it is covered by standard list / custom.
    BOOL currentIsStandard = NO;

    NSArray<NSValue *> *resolutions = @[
        [NSValue valueWithSize:NSMakeSize(3840, 2160)],
        [NSValue valueWithSize:NSMakeSize(2560, 1440)],
        [NSValue valueWithSize:NSMakeSize(1920, 1080)],
        [NSValue valueWithSize:NSMakeSize(1280, 720)]
    ];

    for (NSValue *val in resolutions) {
        NSSize size = val.sizeValue;
        if ((int)size.width == currentRes.width && (int)size.height == currentRes.height) {
            currentIsStandard = YES;
        }
        
        NSString *title = [NSString stringWithFormat:@"%.0f x %.0f", size.width, size.height];
        NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:title action:@selector(selectResolutionFromMenu:) keyEquivalent:@""];
        item.target = self;
        item.representedObject = val;
        
        BOOL selected = (!isMatchDisplay && !isMatchHost && currentRes.width == (int)size.width && currentRes.height == (int)size.height);
        item.state = selected ? NSControlStateValueOn : NSControlStateValueOff;
        
        [monitorMenu addItem:item];
    }
    
    // If current is NOT Follow Monitor, NOT Follow Host, and NOT Standard, we display it as "Effective Custom"
    if (!isMatchDisplay && !isMatchHost && !currentIsStandard) {
        NSString *customTitle = [NSString stringWithFormat:@"%@: %dx%d", MLString(@"Current (Custom)", nil), currentRes.width, currentRes.height];
        NSMenuItem *currentItem = [[NSMenuItem alloc] initWithTitle:customTitle action:nil keyEquivalent:@""];
        currentItem.state = NSControlStateValueOn;
        [monitorMenu addItem:currentItem];
    }

    [monitorMenu addItem:[NSMenuItem separatorItem]];

    // 5. Frame Rate Submenu
    NSMenuItem *fpsSubItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Frame Rate", nil) action:nil keyEquivalent:@""];
    NSMenu *fpsSubMenu = [[NSMenu alloc] initWithTitle:MLString(@"Frame Rate", nil)];
    
    NSArray<NSNumber *> *fpsOptions = @[ @30, @60, @90, @120, @144 ];
    BOOL currentFpsIsStandard = NO;
    for (NSNumber *fps in fpsOptions) {
        if (currentFps == fps.intValue) currentFpsIsStandard = YES;
        
        NSString *title = [NSString stringWithFormat:@"%@ FPS", fps];
        NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:title action:@selector(selectFrameRateFromMenu:) keyEquivalent:@""];
        item.target = self;
        item.representedObject = fps;
        
        BOOL selected = (currentFps == fps.intValue);
        item.state = selected ? NSControlStateValueOn : NSControlStateValueOff;
        
        [fpsSubMenu addItem:item];
    }
    
    // If FPS is weird (custom), show it
    if (!currentFpsIsStandard) {
         NSString *title = [NSString stringWithFormat:@"%@: %d FPS", MLString(@"Current FPS", nil), currentFps];
         NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:title action:nil keyEquivalent:@""];
         item.state = NSControlStateValueOn;
         [fpsSubMenu addItem:item];
    }

    [fpsSubMenu addItem:[NSMenuItem separatorItem]];

    NSMenuItem *customFpsItem = [[NSMenuItem alloc] initWithTitle:[MLString(@"Custom FPS", nil) stringByAppendingString:@"..."] action:@selector(selectCustomFpsFromMenu:) keyEquivalent:@""];
    customFpsItem.target = self;
    [fpsSubMenu addItem:customFpsItem];
    
    fpsSubItem.submenu = fpsSubMenu;
    [monitorMenu addItem:fpsSubItem];

    monitorItem.submenu = monitorMenu;
    [self.streamMenu addItem:monitorItem];

    // 二级：画质（码率）
    NSMenuItem *qualityItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Quality", nil) action:nil keyEquivalent:@""];
    qualityItem.tag = StreamMenuSectionQuality;
    setSymbol(qualityItem, @"sparkles");
    NSMenu *qualityMenu = [[NSMenu alloc] initWithTitle:MLString(@"Quality", nil)];

    NSMenuItem *bitrateHeader = [[NSMenuItem alloc] initWithTitle:MLString(@"Target Bitrate", nil) action:nil keyEquivalent:@""];
    bitrateHeader.enabled = NO;
    [qualityMenu addItem:bitrateHeader];

    BOOL autoAdjust = prefs ? [prefs[@"autoAdjustBitrate"] boolValue] : YES;
    NSNumber *customBitrate = prefs[@"customBitrate"]; // Kbps
    NSNumber *fallbackBitrate = prefs[@"bitrate"]; // Kbps
    NSInteger selectedKbps = customBitrate ? customBitrate.integerValue : (fallbackBitrate ? fallbackBitrate.integerValue : 0);

    NSMenuItem *autoBitrateItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Auto Bitrate", nil) action:@selector(selectBitrateFromMenu:) keyEquivalent:@""];
    autoBitrateItem.target = self;
    autoBitrateItem.representedObject = @"auto";
    autoBitrateItem.state = autoAdjust ? NSControlStateValueOn : NSControlStateValueOff;
    setSymbol(autoBitrateItem, @"wand.and.stars");
    [qualityMenu addItem:autoBitrateItem];

    NSArray<NSNumber *> *bitrateMbpsChoices = @[ @5, @10, @20, @40, @80, @120, @200 ];
    BOOL isPresetSelected = NO;
    for (NSNumber *mbps in bitrateMbpsChoices) {
        NSInteger kbps = mbps.integerValue * 1000;
        NSString *title = [NSString stringWithFormat:@"%@ Mbps", mbps];
        NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:title action:@selector(selectBitrateFromMenu:) keyEquivalent:@""];
        item.target = self;
        item.representedObject = @(kbps);
        BOOL selected = (!autoAdjust && selectedKbps == kbps);
        if (selected) isPresetSelected = YES;
        item.state = selected ? NSControlStateValueOn : NSControlStateValueOff;
        setSymbol(item, @"speedometer");
        [qualityMenu addItem:item];
    }

    [qualityMenu addItem:[NSMenuItem separatorItem]];

    // 自定义选项（三级菜单，悬停展开滑块和输入框）
    BOOL isCustomMode = !autoAdjust && !isPresetSelected && selectedKbps > 0;

    NSMenuItem *customBitrateItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Custom Bitrate", nil) action:nil keyEquivalent:@""];
    customBitrateItem.state = isCustomMode ? NSControlStateValueOn : NSControlStateValueOff;
    setSymbol(customBitrateItem, @"slider.horizontal.3");

    // 三级菜单：自定义码率
    NSMenu *customMenu = [[NSMenu alloc] initWithTitle:MLString(@"Custom Bitrate", nil)];

    // 滑块视图
    NSView *bitrateView = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 280, 70)];

    // 标题行
    NSTextField *bitrateLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(16, 46, 60, 16)];
    bitrateLabel.bezeled = NO;
    bitrateLabel.drawsBackground = NO;
    bitrateLabel.editable = NO;
    bitrateLabel.selectable = NO;
    bitrateLabel.font = [NSFont systemFontOfSize:12 weight:NSFontWeightMedium];
    bitrateLabel.textColor = [NSColor labelColor];
    bitrateLabel.stringValue = MLString(@"Target Bitrate", nil);
    [bitrateView addSubview:bitrateLabel];

    // 当前码率值显示（右侧）
    self.menuBitrateValueLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(200, 46, 64, 16)];
    self.menuBitrateValueLabel.bezeled = NO;
    self.menuBitrateValueLabel.drawsBackground = NO;
    self.menuBitrateValueLabel.editable = NO;
    self.menuBitrateValueLabel.selectable = NO;
    self.menuBitrateValueLabel.alignment = NSTextAlignmentRight;
    self.menuBitrateValueLabel.font = [NSFont monospacedDigitSystemFontOfSize:12 weight:NSFontWeightSemibold];
    self.menuBitrateValueLabel.textColor = [NSColor secondaryLabelColor];
    NSInteger displayKbps = isCustomMode ? selectedKbps : (fallbackBitrate ? fallbackBitrate.integerValue : 20000);
    CGFloat mbpsValue = displayKbps / 1000.0;
    if (mbpsValue < 1.0) {
        self.menuBitrateValueLabel.stringValue = [NSString stringWithFormat:@"%.1f Mbps", mbpsValue];
    } else {
        self.menuBitrateValueLabel.stringValue = [NSString stringWithFormat:@"%.0f Mbps", mbpsValue];
    }
    [bitrateView addSubview:self.menuBitrateValueLabel];

    // 码率滑杆
    self.menuBitrateSlider = [[NSSlider alloc] initWithFrame:NSMakeRect(16, 24, 248, 20)];
    self.menuBitrateSlider.minValue = 0.0;
    self.menuBitrateSlider.maxValue = 27.0; // bitrateSteps 数组长度 - 1
    self.menuBitrateSlider.target = self;
    self.menuBitrateSlider.action = @selector(handleBitrateSliderChanged:);
    self.menuBitrateSlider.continuous = YES;
    [self updateBitrateSliderPosition:displayKbps];
    [bitrateView addSubview:self.menuBitrateSlider];

    // 手动输入框
    NSTextField *inputField = [[NSTextField alloc] initWithFrame:NSMakeRect(16, 2, 60, 20)];
    inputField.bezeled = YES;
    inputField.bezelStyle = NSTextFieldRoundedBezel;
    inputField.editable = YES;
    inputField.selectable = YES;
    inputField.alignment = NSTextAlignmentCenter;
    inputField.font = [NSFont monospacedDigitSystemFontOfSize:11 weight:NSFontWeightRegular];
    inputField.placeholderString = @"Mbps";
    inputField.stringValue = [NSString stringWithFormat:@"%.0f", mbpsValue];
    inputField.target = self;
    inputField.action = @selector(handleBitrateInputChanged:);
    inputField.tag = 1001; // 用于识别
    [bitrateView addSubview:inputField];

    NSTextField *inputSuffix = [[NSTextField alloc] initWithFrame:NSMakeRect(80, 4, 40, 16)];
    inputSuffix.bezeled = NO;
    inputSuffix.drawsBackground = NO;
    inputSuffix.editable = NO;
    inputSuffix.selectable = NO;
    inputSuffix.font = [NSFont systemFontOfSize:11 weight:NSFontWeightRegular];
    inputSuffix.textColor = [NSColor secondaryLabelColor];
    inputSuffix.stringValue = @"Mbps";
    [bitrateView addSubview:inputSuffix];

    // 应用按钮
    NSButton *applyButton = [[NSButton alloc] initWithFrame:NSMakeRect(200, 2, 64, 20)];
    applyButton.bezelStyle = NSBezelStyleRecessed;
    applyButton.title = MLString(@"Apply", nil);
    applyButton.target = self;
    applyButton.action = @selector(handleBitrateApplyClicked:);
    applyButton.font = [NSFont systemFontOfSize:11 weight:NSFontWeightMedium];
    [bitrateView addSubview:applyButton];

    NSMenuItem *bitrateSliderItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    bitrateSliderItem.view = bitrateView;
    [customMenu addItem:bitrateSliderItem];

    customBitrateItem.submenu = customMenu;
    [qualityMenu addItem:customBitrateItem];

    qualityItem.submenu = qualityMenu;
    [self.streamMenu addItem:qualityItem];

    // 二级：声音（音量滑杆）
    NSMenuItem *audioItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Audio", nil) action:nil keyEquivalent:@""];
    setSymbol(audioItem, @"speaker.wave.2");
    NSMenu *audioMenu = [[NSMenu alloc] initWithTitle:MLString(@"Audio", nil)]; 

    NSView *volView = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 240, 28)];
    NSTextField *volLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(10, 6, 42, 16)];
    volLabel.bezeled = NO;
    volLabel.drawsBackground = NO;
    volLabel.editable = NO;
    volLabel.selectable = NO;
    volLabel.font = [NSFont systemFontOfSize:12 weight:NSFontWeightRegular];
    volLabel.textColor = [NSColor labelColor];
    volLabel.stringValue = MLString(@"Volume", nil);
    [volView addSubview:volLabel];

    if (!self.menuVolumeSlider) {
        self.menuVolumeSlider = [[NSSlider alloc] initWithFrame:NSMakeRect(58, 4, 170, 20)];
        self.menuVolumeSlider.minValue = 0.0;
        self.menuVolumeSlider.maxValue = 1.0;
        self.menuVolumeSlider.target = self;
        self.menuVolumeSlider.action = @selector(handleVolumeSliderChanged:);
        self.menuVolumeSlider.continuous = YES;
    }
    self.menuVolumeSlider.doubleValue = [SettingsClass volumeLevelFor:self.app.host.uuid];
    [volView addSubview:self.menuVolumeSlider];

    NSMenuItem *volSliderItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    volSliderItem.view = volView;
    [audioMenu addItem:volSliderItem];

    audioItem.submenu = audioMenu;
    [self.streamMenu addItem:audioItem];

    // 二级：网络（连接方式）
    NSMenuItem *networkItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Network", nil) action:nil keyEquivalent:@""];
    setSymbol(networkItem, @"network");
    NSMenu *networkMenu = [[NSMenu alloc] initWithTitle:MLString(@"Network", nil)]; 

    NSString *method = prefs[@"connectionMethod"] ?: @"Auto";
    NSMenuItem *autoItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Auto (Recommended)", nil) action:@selector(selectConnectionMethodFromMenu:) keyEquivalent:@""];
    autoItem.target = self;
    autoItem.representedObject = @"Auto";
    autoItem.state = [method isEqualToString:@"Auto"] ? NSControlStateValueOn : NSControlStateValueOff;
    setSymbol(autoItem, @"wand.and.stars");
    [networkMenu addItem:autoItem];

    NSArray<NSString *> *candidates = @[ self.app.host.localAddress ?: @"", self.app.host.address ?: @"", self.app.host.externalAddress ?: @"", self.app.host.ipv6Address ?: @"" ];
    NSMutableOrderedSet<NSString *> *unique = [[NSMutableOrderedSet alloc] init];
    for (NSString *addr in candidates) {
        if (addr.length > 0) {
            [unique addObject:addr];
        }
    }
    if (unique.count > 0) {
        [networkMenu addItem:[NSMenuItem separatorItem]];
        for (NSString *addr in unique) {
            NSMenuItem *addrItem = [[NSMenuItem alloc] initWithTitle:addr action:@selector(selectConnectionMethodFromMenu:) keyEquivalent:@""];
            addrItem.target = self;
            addrItem.representedObject = addr;
            addrItem.state = [method isEqualToString:addr] ? NSControlStateValueOn : NSControlStateValueOff;
            setSymbol(addrItem, @"link");
            [networkMenu addItem:addrItem];
        }
    }

    networkItem.submenu = networkMenu;
    [self.streamMenu addItem:networkItem];

    // 二级：日志（显示/复制）
    NSMenuItem *logsItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Logs", nil) action:nil keyEquivalent:@""];
    setSymbol(logsItem, @"text.justify.left");
    NSMenu *logsMenu = [[NSMenu alloc] initWithTitle:MLString(@"Logs", nil)]; 

    NSMenuItem *toggleLogsItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Show Log", nil) action:@selector(toggleLogOverlayFromMenu:) keyEquivalent:@""];
    toggleLogsItem.target = self;
    toggleLogsItem.state = self.logOverlayContainer ? NSControlStateValueOn : NSControlStateValueOff;
    setSymbol(toggleLogsItem, @"text.justify.left");
    [logsMenu addItem:toggleLogsItem];

    NSMenuItem *copyLogsItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Copy Log", nil) action:@selector(copyLogsFromMenu:) keyEquivalent:@""];
    copyLogsItem.target = self;
    setSymbol(copyLogsItem, @"doc.on.doc");
    [logsMenu addItem:copyLogsItem];

    logsItem.submenu = logsMenu;
    [self.streamMenu addItem:logsItem];

    // 二级：更多（把重连/退出放底部）
    NSMenuItem *moreItem = [[NSMenuItem alloc] initWithTitle:MLString(@"More", nil) action:nil keyEquivalent:@""];
    setSymbol(moreItem, @"ellipsis.circle");
    NSMenu *moreMenu = [[NSMenu alloc] initWithTitle:MLString(@"More", nil)]; 

    NSMenuItem *quitItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Close and Quit App", nil) action:@selector(performCloseAndQuitApp:) keyEquivalent:@""];
    [self applyShortcut:[self streamShortcutForAction:MLShortcutActionCloseAndQuitApp] toMenuItem:quitItem];
    quitItem.target = self;
    setSymbol(quitItem, @"power");
    [moreMenu addItem:quitItem];

    moreItem.submenu = moreMenu;
    [self.streamMenu addItem:moreItem];

    // 一级底部：退出
    [self.streamMenu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *disconnectItem = [[NSMenuItem alloc] initWithTitle:MLString(@"Disconnect from Stream", nil) action:@selector(performCloseStreamWindow:) keyEquivalent:@""];
    [self applyShortcut:[self streamShortcutForAction:MLShortcutActionDisconnectStream] toMenuItem:disconnectItem];
    disconnectItem.target = self;
    setSymbol(disconnectItem, @"xmark.circle");
    [self.streamMenu addItem:disconnectItem];
}

- (void)handleToggleFullscreenFromMenu:(id)sender {
    [self.view.window toggleFullScreen:self];
}

- (void)toggleLogOverlayFromMenu:(id)sender {
    [self toggleLogOverlay];
}

- (void)copyLogsFromMenu:(id)sender {
    [self copyAllLogsToPasteboard];
}

- (void)reconnectFromMenu:(id)sender {
    [self attemptReconnectWithReason:@"menu"]; 
}

- (void)selectConnectionMethodFromMenu:(NSMenuItem *)sender {
    NSString *method = (NSString *)sender.representedObject;
    if (method.length == 0) {
        return;
    }

    NSDictionary *prefs = [SettingsClass getSettingsFor:self.app.host.uuid];
    NSString *current = prefs[@"connectionMethod"] ?: @"Auto";
    if ([current isEqualToString:method]) {
        return;
    }

    [SettingsClass setConnectionMethod:method for:self.app.host.uuid];
    [self updateWindowSubtitle];
    [SettingsClass loadMoonlightSettingsFor:self.app.host.uuid];
    [self attemptReconnectWithReason:@"connection-method-changed"]; 
}

- (void)selectFollowHostFromMenu:(id)sender {
    // 0x0 resolution and 0 FPS usually signals "Native" or "Default" to the core library.
    // We treat this as "Follow Host".
    [SettingsClass setCustomResolution:0 :0 :0 for:self.app.host.uuid];
    
    [SettingsClass loadMoonlightSettingsFor:self.app.host.uuid];
    [self attemptReconnectWithReason:@"resolution-changed"];
}

- (void)selectCustomResolutionFromMenu:(id)sender {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = MLString(@"Custom resolution and frame rate", nil);
    alert.informativeText = MLString(@"Enter the resolution (width x height) and frame rate (FPS) you want.\nA value of 0 leaves the choice to the host, which is not recommended.", nil);
    [alert addButtonWithTitle:MLString(@"OK", nil)];
    [alert addButtonWithTitle:MLString(@"Cancel", nil)];
    
    NSView *container = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 200, 100)];
    
    // Width
    NSTextField *widthLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 75, 50, 20)];
    widthLabel.stringValue = MLString(@"Width:", nil);
    widthLabel.bezeled = NO;
    widthLabel.drawsBackground = NO;
    widthLabel.alignment = NSTextAlignmentRight;
    [container addSubview:widthLabel];
    
    NSTextField *widthField = [[NSTextField alloc] initWithFrame:NSMakeRect(55, 75, 60, 22)];
    widthField.placeholderString = @"1920";
    [container addSubview:widthField];
    
    // Height
    NSTextField *heightLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 45, 50, 20)];
    heightLabel.stringValue = MLString(@"Height:", nil);
    heightLabel.bezeled = NO;
    heightLabel.drawsBackground = NO;
    heightLabel.alignment = NSTextAlignmentRight;
    [container addSubview:heightLabel];
    
    NSTextField *heightField = [[NSTextField alloc] initWithFrame:NSMakeRect(55, 45, 60, 22)];
    heightField.placeholderString = @"1080";
    [container addSubview:heightField];
    
    // FPS
    NSTextField *fpsLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 15, 50, 20)];
    fpsLabel.stringValue = @"FPS:";
    fpsLabel.bezeled = NO;
    fpsLabel.drawsBackground = NO;
    fpsLabel.alignment = NSTextAlignmentRight;
    [container addSubview:fpsLabel];
    
    NSTextField *fpsField = [[NSTextField alloc] initWithFrame:NSMakeRect(55, 15, 60, 22)];
    fpsField.placeholderString = @"60";
    [container addSubview:fpsField];
    
    // Pre-fill with current
    struct Resolution res = [self.class getResolution];
    TemporarySettings *tempSettings = [[DataManager alloc] getSettings];
    int currentFps = [tempSettings.framerate intValue];
    
    if (res.width > 0) widthField.intValue = res.width;
    if (res.height > 0) heightField.intValue = res.height;
    if (currentFps > 0) fpsField.intValue = currentFps;
    
    alert.accessoryView = container;
    
    [alert beginSheetModalForWindow:self.view.window completionHandler:^(NSModalResponse returnCode) {
        if (returnCode == NSAlertFirstButtonReturn) {
            int w = widthField.intValue;
            int h = heightField.intValue;
            int f = fpsField.intValue;
            
            // Basic validation
            if (w < 0) w = 0;
            if (h < 0) h = 0;
            if (f < 0) f = 0;
            
            [SettingsClass setCustomResolution:w :h :f for:self.app.host.uuid];
            [SettingsClass loadMoonlightSettingsFor:self.app.host.uuid];
            [self attemptReconnectWithReason:@"custom-resolution"];
        }
    }];
}

- (void)selectMatchDisplayFromMenu:(id)sender {
    NSDictionary *prefs = [SettingsClass getSettingsFor:self.app.host.uuid];
    BOOL currentMatch = prefs ? [prefs[@"matchDisplayResolution"] boolValue] : NO;
    if (currentMatch) {
         return;
    }
    
    // Switch to match display
    // We need current FPS because setResolutionAndFps requires it.
    TemporarySettings *tempSettings = [[DataManager alloc] getSettings];
    int currentFps = [tempSettings.framerate intValue];

    [SettingsClass setResolutionAndFps:0 :0 :currentFps matchDisplay:YES for:self.app.host.uuid];
    
    [SettingsClass loadMoonlightSettingsFor:self.app.host.uuid];
    [self attemptReconnectWithReason:@"resolution-changed"];
}

- (void)selectResolutionFromMenu:(NSMenuItem *)sender {
    NSValue *val = sender.representedObject;
    if (!val) return;
    NSSize size = val.sizeValue;
    
    TemporarySettings *tempSettings = [[DataManager alloc] getSettings];
    int currentFps = [tempSettings.framerate intValue];

    // Disable match display, set explicit resolution
    [SettingsClass setResolutionAndFps:(int)size.width :(int)size.height :currentFps matchDisplay:NO for:self.app.host.uuid];

    [SettingsClass loadMoonlightSettingsFor:self.app.host.uuid];
    [self attemptReconnectWithReason:@"resolution-changed"];
}

- (void)selectFrameRateFromMenu:(NSMenuItem *)sender {
    NSNumber *fpsStats = sender.representedObject;
    if (!fpsStats) return;
    int newFps = fpsStats.intValue;

    TemporarySettings *tempSettings = [[DataManager alloc] getSettings];
    int currentFps = [tempSettings.framerate intValue];
    if (newFps == currentFps) return;
    
    // Get current resolution settings to preserve them
    NSDictionary *prefs = [SettingsClass getSettingsFor:self.app.host.uuid];
    BOOL matchDisplay = prefs ? [prefs[@"matchDisplayResolution"] boolValue] : NO;
    
    // If not matching display, we need to know the explicit resolution.
    // getResolution returns the currently streaming config resolution, which is what we want to keep.
    struct Resolution currentRes = [self.class getResolution];
    
    [SettingsClass setResolutionAndFps:currentRes.width :currentRes.height :newFps matchDisplay:matchDisplay for:self.app.host.uuid];
    
    [SettingsClass loadMoonlightSettingsFor:self.app.host.uuid];
    [self attemptReconnectWithReason:@"framerate-changed"];
}

- (void)selectCustomFpsFromMenu:(id)sender {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = MLString(@"Custom frame rate", nil);
    alert.informativeText = MLString(@"Enter the frame rate you want, in FPS.", nil);
    [alert addButtonWithTitle:MLString(@"OK", nil)];
    [alert addButtonWithTitle:MLString(@"Cancel", nil)];
    
    NSTextField *fpsField = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 200, 24)];
    fpsField.placeholderString = @"60";
    
    // Pre-fill
    NSDictionary *prefs = [SettingsClass getSettingsFor:self.app.host.uuid];
    int currentFps = 0;
    if (prefs) {
        int rawFps = [prefs[@"fps"] intValue];
        if (rawFps == 0) {
            currentFps = [prefs[@"customFps"] intValue];
        } else {
            currentFps = rawFps;
        }
    }
    if (currentFps == 0) {
        TemporarySettings *tempSettings = [[DataManager alloc] getSettings];
        currentFps = [tempSettings.framerate intValue];
    }
    
    if (currentFps > 0) fpsField.intValue = currentFps;
    
    alert.accessoryView = fpsField;
    
    [alert beginSheetModalForWindow:self.view.window completionHandler:^(NSModalResponse returnCode) {
        if (returnCode == NSAlertFirstButtonReturn) {
            int f = fpsField.intValue;
            if (f < 0) f = 0;
            
            NSDictionary *prefs = [SettingsClass getSettingsFor:self.app.host.uuid];
            BOOL matchDisplay = prefs ? [prefs[@"matchDisplayResolution"] boolValue] : NO;
            struct Resolution currentRes = [self.class getResolution];
            
            [SettingsClass setResolutionAndFps:currentRes.width :currentRes.height :f matchDisplay:matchDisplay for:self.app.host.uuid];
            
            [SettingsClass loadMoonlightSettingsFor:self.app.host.uuid];
            [self attemptReconnectWithReason:@"framerate-changed"];
        }
    }];
}


- (void)selectBitrateFromMenu:(NSMenuItem *)sender {
    id rep = sender.representedObject;
    NSDictionary *prefs = [SettingsClass getSettingsFor:self.app.host.uuid];
    BOOL currentAuto = prefs ? [prefs[@"autoAdjustBitrate"] boolValue] : YES;
    NSNumber *currentCustom = prefs[@"customBitrate"]; // Kbps

    if ([rep isKindOfClass:[NSString class]] && [(NSString *)rep isEqualToString:@"auto"]) {
        if (currentAuto) {
            return;
        }
        [SettingsClass setBitrateMode:YES customBitrateKbps:nil for:self.app.host.uuid];
    } else if ([rep isKindOfClass:[NSNumber class]]) {
        NSNumber *kbps = (NSNumber *)rep;
        if (!currentAuto && currentCustom && currentCustom.integerValue == kbps.integerValue) {
            return;
        }
        [SettingsClass setBitrateMode:NO customBitrateKbps:kbps for:self.app.host.uuid];
    } else {
        return;
    }

    [SettingsClass loadMoonlightSettingsFor:self.app.host.uuid];
    [self attemptReconnectWithReason:@"bitrate-changed"]; 
}

- (void)handleVolumeSliderChanged:(NSSlider *)sender {
    [SettingsClass setVolumeLevel:(CGFloat)sender.doubleValue for:self.app.host.uuid];
}

#pragma mark - Bitrate Slider

static NSArray<NSNumber *> *bitrateStepsArray(void) {
    return @[@0.5, @1, @1.5, @2, @2.5, @3, @4, @5, @6, @7, @8, @9, @10,
             @12, @15, @18, @20, @25, @30, @40, @50, @60, @70, @80, @90, @100, @120, @150];
}

- (void)updateBitrateSliderPosition:(NSInteger)currentKbps {
    NSArray *steps = bitrateStepsArray();
    NSInteger index = 0;
    CGFloat currentMbps = currentKbps / 1000.0;
    for (NSInteger i = 0; i < (NSInteger)steps.count; i++) {
        if (currentMbps <= [steps[i] floatValue]) {
            index = i;
            break;
        }
        if (i == (NSInteger)steps.count - 1) {
            index = i;
        }
    }
    self.menuBitrateSlider.doubleValue = index;
}

- (void)handleBitrateSliderChanged:(NSSlider *)sender {
    NSArray *steps = bitrateStepsArray();
    NSInteger index = (NSInteger)round(sender.doubleValue);
    index = MAX(0, MIN(index, (NSInteger)steps.count - 1));

    CGFloat mbps = [steps[index] floatValue];
    NSInteger kbps = (NSInteger)(mbps * 1000);

    // 更新显示
    if (mbps < 1.0) {
        self.menuBitrateValueLabel.stringValue = [NSString stringWithFormat:@"%.1f Mbps", mbps];
    } else {
        self.menuBitrateValueLabel.stringValue = [NSString stringWithFormat:@"%.0f Mbps", mbps];
    }

    // 同步更新输入框
    NSView *bitrateView = sender.superview;
    for (NSView *subview in bitrateView.subviews) {
        if ([subview isKindOfClass:[NSTextField class]] && subview.tag == 1001) {
            NSTextField *inputField = (NSTextField *)subview;
            if (mbps < 1.0) {
                inputField.stringValue = [NSString stringWithFormat:@"%.1f", mbps];
            } else {
                inputField.stringValue = [NSString stringWithFormat:@"%.0f", mbps];
            }
            break;
        }
    }

    // 保存设置（关闭自动模式，设置自定义码率）
    [SettingsClass setBitrateMode:NO customBitrateKbps:@(kbps) for:self.app.host.uuid];
    [SettingsClass loadMoonlightSettingsFor:self.app.host.uuid];
}

- (void)handleBitrateInputChanged:(NSTextField *)sender {
    CGFloat mbps = sender.doubleValue;
    if (mbps < 0.5) mbps = 0.5;
    if (mbps > 150) mbps = 150;

    NSInteger kbps = (NSInteger)(mbps * 1000);

    // 更新显示
    if (mbps < 1.0) {
        self.menuBitrateValueLabel.stringValue = [NSString stringWithFormat:@"%.1f Mbps", mbps];
    } else {
        self.menuBitrateValueLabel.stringValue = [NSString stringWithFormat:@"%.0f Mbps", mbps];
    }

    // 更新滑块位置
    [self updateBitrateSliderPosition:kbps];

    // 保存设置
    [SettingsClass setBitrateMode:NO customBitrateKbps:@(kbps) for:self.app.host.uuid];
    [SettingsClass loadMoonlightSettingsFor:self.app.host.uuid];
}

- (void)handleBitrateApplyClicked:(NSButton *)sender {
    // 触发重连以应用新码率
    [self rebuildStreamMenu];
    [self attemptReconnectWithReason:@"bitrate-changed"];
}

- (void)toggleFullscreenControlBallFromMenu:(NSMenuItem *)sender {
    [self toggleFullscreenControlBallVisibility];
}

- (void)toggleFullscreenControlBallVisibility {
    self.hideFullscreenControlBall = !self.hideFullscreenControlBall;
    [[NSUserDefaults standardUserDefaults] setBool:self.hideFullscreenControlBall forKey:[self fullscreenControlBallDefaultsKey]];
    [self requestStreamMenuEntrypointsVisibilityUpdate];
}

- (void)toggleMouseMode {
    NSString *currentMode = [SettingsClass mouseModeFor:self.app.host.uuid];
    NSString *newMode = [currentMode isEqualToString:@"game"] ? @"remote" : @"game";
    [self applyMouseModeNamed:newMode showNotification:YES];
}

- (void)toggleMouseModeFromMenu:(id)sender {
    [self toggleMouseMode];
}

- (void)selectLockedMouseModeFromMenu:(id)sender {
    [self applyMouseModeNamed:@"game" showNotification:YES];
}

- (void)selectFreeMouseModeFromMenu:(id)sender {
    [self applyMouseModeNamed:@"remote" showNotification:YES];
}

@end
