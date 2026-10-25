//
//  MLEdgeMenuUI.m
//  Moonlight for macOS
//

#import "StreamViewController_Internal.h"

@implementation MLEdgeMenuHandleView {
    NSImageView *_iconView;
    NSPoint _mouseDownPointOnScreen;
    BOOL _dragStarted;
    BOOL _pressActive;
    NSTrackingArea *_trackingArea;
    CALayer *_plateShadowLayer;
    CALayer *_plateLayer;
    CALayer *_plateInnerLayer;
    NSRect _compactHitRect;
}

// Wave C: the idle tab's thickness, clamped to the published 10-20pt range. The
// stored idleThicknessPoints may be zero (nothing written) or out of range; the
// shipped 14pt is the fallback, so a fresh install draws the exact tab it drew
// before this setting existed.
- (CGFloat)effectiveIdleThickness {
    CGFloat value = self.idleThicknessPoints;
    if (value <= 0) return MLEdgeMenuHandleIdleThickness;
    if (value < MLEdgeMenuHandleIdleThicknessMinPoints) return MLEdgeMenuHandleIdleThicknessMinPoints;
    if (value > MLEdgeMenuHandleIdleThicknessMaxPoints) return MLEdgeMenuHandleIdleThicknessMaxPoints;
    return value;
}

- (instancetype)initWithFrame:(NSRect)frameRect {
    self = [super initWithFrame:frameRect];
    if (self) {
        self.wantsLayer = YES;
        self.layer.masksToBounds = NO;
        self.layer.cornerRadius = 28.0;

        _plateShadowLayer = [CALayer layer];
        [self.layer addSublayer:_plateShadowLayer];

        _plateLayer = [CALayer layer];
        [_plateShadowLayer addSublayer:_plateLayer];

        _plateInnerLayer = [CALayer layer];
        [_plateLayer addSublayer:_plateInnerLayer];

        _iconView = [[NSImageView alloc] initWithFrame:NSZeroRect];
        _iconView.imageScaling = NSImageScaleProportionallyUpOrDown;
        _iconView.autoresizingMask = NSViewMinXMargin | NSViewMaxXMargin | NSViewMinYMargin | NSViewMaxYMargin;
        [self addSubview:_iconView];

        [self updateVisualStyle];
    }
    return self;
}

// Called automatically when the effective appearance changes (Light/Dark mode switch),
// so the handle colours update without needing KVO or notification observation.
- (void)viewDidChangeEffectiveAppearance {
    [super viewDidChangeEffectiveAppearance];
    [self updateVisualStyle];
    [self setNeedsLayout:YES];
}


- (NSImageView *)iconView {
    return _iconView;
}

- (BOOL)isFlipped {
    return YES;
}

- (BOOL)acceptsFirstMouse:(NSEvent *)event {
    return YES;
}

- (NSView *)hitTest:(NSPoint)point {
    NSPoint localPoint = [self convertPoint:point fromView:self.superview];
    if (self.hidden) return nil;
    // The collapsed tab is a strip, not a 56pt switch. Anything outside the drawn
    // strip plus its own hit slop has to return nil so the panel below — the stream —
    // keeps the click; a collapsed dock must never be able to swallow a game click
    // in an area the player was never shown.
    if (self.compactAppearance) {
        if (NSIsEmptyRect(_compactHitRect)) return nil;
        return NSPointInRect(localPoint, _compactHitRect) ? self : nil;
    }
    CGFloat radius = MIN(self.bounds.size.width, self.bounds.size.height) * 0.33;
    NSBezierPath *hitPath = [NSBezierPath bezierPathWithRoundedRect:self.bounds xRadius:radius yRadius:radius];
    return [hitPath containsPoint:localPoint] ? self : nil;
}

- (void)setActiveAppearance:(BOOL)activeAppearance {
    if (_activeAppearance == activeAppearance) return;
    _activeAppearance = activeAppearance;
    [self updateVisualStyle];
}

- (void)setCompactAppearance:(BOOL)compactAppearance {
    if (_compactAppearance == compactAppearance) return;
    _compactAppearance = compactAppearance;
    [self setNeedsLayout:YES];
    [self updateVisualStyle];
}

- (void)setArmedAppearance:(BOOL)armedAppearance {
    if (_armedAppearance == armedAppearance) return;
    _armedAppearance = armedAppearance;
    [self setNeedsLayout:YES];
    [self updateVisualStyle];
}

- (void)setDockEdge:(MLFreeMouseExitEdge)dockEdge {
    if (_dockEdge == dockEdge) return;
    _dockEdge = dockEdge;
    [self setNeedsLayout:YES];
    [self updateVisualStyle];
}

- (void)layout {
    [super layout];

    // Recomputed every pass: the strip moves with the dock edge and with arming, and
    // the hit-test has to follow the drawing rather than the panel that carries it.
    _compactHitRect = NSZeroRect;

    CGFloat cornerRadius = MIN(self.bounds.size.width, self.bounds.size.height) * 0.33;
    self.layer.cornerRadius = cornerRadius;
    CGPathRef shadowPath = CGPathCreateWithRoundedRect(NSRectToCGRect(self.bounds), cornerRadius, cornerRadius, NULL);
    self.layer.shadowPath = shadowPath;
    CGPathRelease(shadowPath);
    CGFloat plateSize = MIN(self.bounds.size.width, self.bounds.size.height) * 0.58;
    NSRect plateFrame = NSMakeRect((NSWidth(self.bounds) - plateSize) / 2.0,
                                   (NSHeight(self.bounds) - plateSize) / 2.0,
                                   plateSize,
                                   plateSize);
    _plateShadowLayer.frame = NSInsetRect(plateFrame, -6.0, -6.0);
    _plateLayer.frame = NSInsetRect(_plateShadowLayer.bounds, 6.0, 6.0);
    _plateLayer.cornerRadius = plateSize * 0.30;
    _plateInnerLayer.frame = CGRectInset(_plateLayer.bounds, 4.0, 4.0);
    _plateInnerLayer.cornerRadius = MAX(8.0, _plateLayer.cornerRadius - 4.0);

    CGFloat iconSize = plateSize * 0.42;
    if (!self.compactAppearance) {
        _plateInnerLayer.hidden = NO;
        _iconView.hidden = NO;
        _iconView.frame = NSMakeRect(NSMinX(plateFrame) + (plateSize - iconSize) / 2.0,
                                     NSMinY(plateFrame) + (plateSize - iconSize) / 2.0,
                                     iconSize,
                                     iconSize);
        return;
    }
    // Compact: remember the strip that was just laid out, widened only by the
    // tab's own slop, as the one region allowed to take a click.

    // The compact tab. Only the strip between the docked screen edge and
    // MLEdgeMenuButtonVisiblePeek is on screen at all, so every measurement below
    // starts at that edge and grows inwards, and the rectangle the view controller
    // hits-tests (edgeMenuVisibleHandleRectInBounds:) describes the same strip.
    BOOL armed = self.armedAppearance;
    CGFloat thickness = armed ? MLEdgeMenuHandleArmedThickness : [self effectiveIdleThickness];
    CGFloat shortest = MIN(NSWidth(self.bounds), NSHeight(self.bounds));
    CGFloat along = MIN(MLEdgeMenuHandleLength, shortest - 8.0);
    // A docked left or right edge runs along y, a top or bottom edge along x. The
    // panel is square, so the wrong axis still centres the tab here and would only
    // show up as a handle that sits off the dock on some other placement.
    CGFloat alongCross = (self.dockEdge == MLFreeMouseExitEdgeLeft || self.dockEdge == MLFreeMouseExitEdgeRight)
        ? (NSHeight(self.bounds) - along) / 2.0
        : (NSWidth(self.bounds) - along) / 2.0;
    switch (self.dockEdge) {
        case MLFreeMouseExitEdgeLeft:
            plateFrame = NSMakeRect(NSWidth(self.bounds) - MLEdgeMenuButtonVisiblePeek + 2.0, alongCross, thickness, along);
            break;
        case MLFreeMouseExitEdgeRight:
            plateFrame = NSMakeRect(MLEdgeMenuButtonVisiblePeek - 2.0 - thickness, alongCross, thickness, along);
            break;
        case MLFreeMouseExitEdgeTop:
            plateFrame = NSMakeRect(alongCross, NSHeight(self.bounds) - MLEdgeMenuButtonVisiblePeek + 2.0, along, thickness);
            break;
        case MLFreeMouseExitEdgeBottom:
            plateFrame = NSMakeRect(alongCross, 2.0, along, thickness);
            break;
        default:
            break;
    }
    _plateShadowLayer.frame = NSInsetRect(plateFrame, -6.0, -6.0);
    _plateLayer.frame = NSInsetRect(_plateShadowLayer.bounds, 6.0, 6.0);
    _plateLayer.cornerRadius = thickness / 2.0;
    _plateInnerLayer.frame = CGRectInset(_plateLayer.bounds, 3.0, 3.0);
    _plateInnerLayer.cornerRadius = MAX(6.0, thickness / 2.0 - 3.0);
    _plateInnerLayer.hidden = !armed;
    _iconView.hidden = !armed;
    CGFloat tabIcon = MAX(12.0, thickness - 8.0);
    _iconView.frame = NSMakeRect(NSMinX(plateFrame) + (NSWidth(plateFrame) - tabIcon) / 2.0,
                                 NSMinY(plateFrame) + (NSHeight(plateFrame) - tabIcon) / 2.0,
                                 tabIcon,
                                 tabIcon);
    _compactHitRect = NSInsetRect(plateFrame, -MLEdgeMenuHandleHitSlop, -MLEdgeMenuHandleHitSlop);
}

- (void)updateTrackingAreas {
    [super updateTrackingAreas];

    if (_trackingArea) {
        [self removeTrackingArea:_trackingArea];
    }

    NSTrackingAreaOptions options = NSTrackingMouseEnteredAndExited | NSTrackingMouseMoved | NSTrackingActiveAlways | NSTrackingInVisibleRect;
    _trackingArea = [[NSTrackingArea alloc] initWithRect:self.bounds options:options owner:self userInfo:nil];
    [self addTrackingArea:_trackingArea];
}

- (void)mouseEntered:(NSEvent *)event {
    [super mouseEntered:event];
    if (self.hoverHandler) {
        self.hoverHandler(YES);
    }
}

- (void)mouseExited:(NSEvent *)event {
    [super mouseExited:event];
    if (self.hoverHandler) {
        self.hoverHandler(NO);
    }
}

- (void)updateVisualStyle {
    BOOL active = self.activeAppearance;
    // Arming is the tab's own reply to a pointer that stopped at the edge, so it is
    // drawn in the accent colour and nothing else changes: no panel, no pointer.
    BOOL armed = self.armedAppearance && self.compactAppearance;

    // Use system colours that adapt to Light and Dark appearances, so the handle
    // never reads as paper glued over the video or as a dead pixel on OLED panels.
    // The old fixed RGB values looked fine on Light and invisible on Dark (or vice
    // versa), and a handle a player cannot see is a handle they cannot press.
        // Determine if the system is in Dark Mode using the appearance name comparison.
    // The name is a constant string; comparing with isEqual: avoids SDK availability issues.
    BOOL isDark = [[self.effectiveAppearance.name lowercaseString] hasSuffix:@"dark"];

    self.layer.borderWidth = 0.0;
    self.layer.borderColor = NSColor.clearColor.CGColor;
    self.layer.shadowColor = [NSColor colorWithRed:0.0 green:0.0 blue:0.0 alpha:0.44].CGColor;
    self.layer.shadowOpacity = 0.0f;
    self.layer.shadowRadius = 0.0f;
    self.layer.shadowOffset = CGSizeZero;

    _plateShadowLayer.shadowColor = [NSColor colorWithWhite:0.0 alpha:isDark ? 0.40 : 0.26].CGColor;
    _plateShadowLayer.shadowOpacity = (active || armed) ? 0.32f : 0.20f;
    _plateShadowLayer.shadowRadius = (active || armed) ? 16.0f : 12.0f;
    _plateShadowLayer.shadowOffset = CGSizeMake(0.0, 3.0);

    _plateLayer.backgroundColor = (isDark
        ? [NSColor colorWithRed:0.18 green:0.19 blue:0.21 alpha:0.96].CGColor
        : [NSColor colorWithRed:0.96 green:0.97 blue:0.99 alpha:0.98].CGColor);
    _plateLayer.borderWidth = armed ? 2.0 : 1.0;
    _plateLayer.borderColor = armed
        ? [NSColor.selectedContentBackgroundColor colorWithAlphaComponent:isDark ? 0.90 : 0.95].CGColor
        : (isDark
            ? [NSColor colorWithWhite:0.08 alpha:0.50].CGColor
            : [NSColor colorWithWhite:1.0 alpha:0.78].CGColor);

    _plateInnerLayer.backgroundColor = (armed
        ? (isDark
            ? [NSColor.selectedContentBackgroundColor colorWithAlphaComponent:0.30].CGColor
            : [NSColor colorWithRed:0.80 green:0.90 blue:1.0 alpha:0.95].CGColor)
        : (isDark
            ? [NSColor colorWithRed:0.12 green:0.13 blue:0.15 alpha:0.90].CGColor
            : [NSColor colorWithRed:0.89 green:0.91 blue:0.95 alpha:0.92].CGColor));
    _plateInnerLayer.borderWidth = 1.0;
    _plateInnerLayer.borderColor = (isDark
        ? [NSColor colorWithWhite:0.00 alpha:0.55].CGColor
        : [NSColor colorWithWhite:0.72 alpha:0.42].CGColor);

    _iconView.contentTintColor = (isDark
        ? [NSColor colorWithRed:0.85 green:0.86 blue:0.88 alpha:0.98]
        : [NSColor colorWithRed:0.12 green:0.15 blue:0.20 alpha:0.98]);
}

- (void)setHidden:(BOOL)hidden {
    if (hidden) {
        _pressActive = NO;
        _dragStarted = NO;
    }
    [super setHidden:hidden];
}

- (void)mouseDown:(NSEvent *)event {
    _pressActive = YES;
    _mouseDownPointOnScreen = [NSEvent mouseLocation];
    _dragStarted = NO;
}

- (void)mouseDragged:(NSEvent *)event {
    if (!_pressActive || self.hidden) return;
    NSPoint screenPoint = [NSEvent mouseLocation];
    NSPoint translation = NSMakePoint(screenPoint.x - _mouseDownPointOnScreen.x,
                                      screenPoint.y - _mouseDownPointOnScreen.y);
    if (!_dragStarted) {
        if (fabs(translation.x) < 2.0 && fabs(translation.y) < 2.0) {
            return;
        }
        _dragStarted = YES;
        if (self.dragHandler) {
            self.dragHandler(NSGestureRecognizerStateBegan, NSZeroPoint);
        }
    }

    if (self.dragHandler) {
        self.dragHandler(NSGestureRecognizerStateChanged, translation);
    }
}

- (void)mouseUp:(NSEvent *)event {
    if (!_pressActive || self.hidden) return;
    _pressActive = NO;
    NSPoint screenPoint = [NSEvent mouseLocation];
    NSPoint translation = NSMakePoint(screenPoint.x - _mouseDownPointOnScreen.x,
                                      screenPoint.y - _mouseDownPointOnScreen.y);
    if (_dragStarted) {
        if (self.dragHandler) {
            self.dragHandler(NSGestureRecognizerStateEnded, translation);
        }
    } else if (self.activationHandler && NSPointInRect([self convertPoint:event.locationInWindow fromView:nil], self.bounds)) {
        self.activationHandler(event);
    }
    _dragStarted = NO;
}

- (void)mouseMoved:(NSEvent *)event {
    [super mouseMoved:event];
    if (self.hoverHandler) {
        self.hoverHandler(YES);
    }
}


@end

@implementation MLEdgeMenuPanel

// AppKit clamps borderless panels below the menu bar, which cuts the top-docked
// handle in half. The edge handle owns its own geometry, including the strip
// above the menu bar on a top dock, so opt out of that single clamp.
- (NSRect)constrainFrameRect:(NSRect)frame toScreen:(NSScreen *)screen {
    return frame;
}

- (BOOL)canBecomeKeyWindow {
    return NO;
}

- (BOOL)canBecomeMainWindow {
    return NO;
}

@end
