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
    CGFloat radius = MIN(self.bounds.size.width, self.bounds.size.height) * 0.33;
    NSBezierPath *hitPath = [NSBezierPath bezierPathWithRoundedRect:self.bounds xRadius:radius yRadius:radius];
    NSPoint localPoint = [self convertPoint:point fromView:self.superview];
    return !self.hidden && [hitPath containsPoint:localPoint] ? self : nil;
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

- (void)setDockEdge:(MLFreeMouseExitEdge)dockEdge {
    if (_dockEdge == dockEdge) return;
    _dockEdge = dockEdge;
    [self setNeedsLayout:YES];
    [self updateVisualStyle];
}

- (void)layout {
    [super layout];

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
    if (self.compactAppearance) {
        CGFloat peek = MLEdgeMenuButtonVisiblePeek;
        switch (self.dockEdge) {
            case MLFreeMouseExitEdgeLeft: plateFrame = NSMakeRect(NSWidth(self.bounds) - peek + 2, 8, peek - 4, NSHeight(self.bounds) - 16); break;
            case MLFreeMouseExitEdgeRight: plateFrame = NSMakeRect(2, 8, peek - 4, NSHeight(self.bounds) - 16); break;
            case MLFreeMouseExitEdgeTop: plateFrame = NSMakeRect(8, NSHeight(self.bounds) - peek + 2, NSWidth(self.bounds) - 16, peek - 4); break;
            case MLFreeMouseExitEdgeBottom: plateFrame = NSMakeRect(8, 2, NSWidth(self.bounds) - 16, peek - 4); break;
            default: break;
        }
        _plateShadowLayer.frame = plateFrame;
        _plateLayer.frame = _plateShadowLayer.bounds;
        _plateLayer.cornerRadius = MIN(NSWidth(plateFrame), NSHeight(plateFrame)) / 2;
    }
    _plateInnerLayer.hidden = self.compactAppearance;
    _iconView.hidden = self.compactAppearance;
    _iconView.frame = NSMakeRect(NSMinX(plateFrame) + (plateSize - iconSize) / 2.0,
                                 NSMinY(plateFrame) + (plateSize - iconSize) / 2.0,
                                 iconSize,
                                 iconSize);
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

    self.layer.borderWidth = 0.0;
    self.layer.borderColor = NSColor.clearColor.CGColor;
    self.layer.shadowColor = [NSColor colorWithRed:0.0 green:0.0 blue:0.0 alpha:0.44].CGColor;
    self.layer.shadowOpacity = 0.0f;
    self.layer.shadowRadius = 0.0f;
    self.layer.shadowOffset = CGSizeZero;


    _plateShadowLayer.shadowColor = [NSColor colorWithWhite:0.0 alpha:0.26].CGColor;
    _plateShadowLayer.shadowOpacity = active ? 0.24f : 0.18f;
    _plateShadowLayer.shadowRadius = active ? 16.0f : 12.0f;
    _plateShadowLayer.shadowOffset = CGSizeMake(0.0, 3.0);

    _plateLayer.backgroundColor = [NSColor colorWithRed:0.96 green:0.97 blue:0.99 alpha:0.98].CGColor;
    _plateLayer.borderWidth = 1.0;
    _plateLayer.borderColor = [NSColor colorWithWhite:1.0 alpha:0.78].CGColor;

    _plateInnerLayer.backgroundColor = [NSColor colorWithRed:0.89 green:0.91 blue:0.95 alpha:0.92].CGColor;
    _plateInnerLayer.borderWidth = 1.0;
    _plateInnerLayer.borderColor = [NSColor colorWithWhite:0.72 alpha:0.42].CGColor;

    _iconView.contentTintColor = [NSColor colorWithRed:0.12 green:0.15 blue:0.20 alpha:0.98];
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

- (BOOL)canBecomeKeyWindow {
    return NO;
}

- (BOOL)canBecomeMainWindow {
    return NO;
}

@end
