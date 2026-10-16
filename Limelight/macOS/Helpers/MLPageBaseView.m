//
//  MLPageBaseView.m
//  Moonlight for macOS
//
//  mme-page-wash-v1
//
//  Why this exists in two implementations: the settings page is SwiftUI and bends the
//  page through .glassEffect; the hosts grid is an AppKit collection view that cannot
//  host a SwiftUI surface without a hosting round-trip. Both need the same base or the
//  two halves of one window would visibly disagree, so the numbers below are pinned to
//  SettingsPageBase by the audit, not by memory: cool blue top-leading at 0.16 fading
//  out at radius 680, warm amber bottom-trailing at 0.12 out at 720, both over an
//  opaque controlBackgroundColor so every appearance stays opaque. The alpha ramp is
//  the point of the whole view -- a flat fill gives glass nothing to sample and the
//  cards read as bare text (measured: a settings page's distinct colours went from 45
//  flat to 152 washed), and a wash strong enough to look designed rather than stained
//  is also strong enough to stop being a page background.
//

#import "MLPageBaseView.h"

@implementation MLPageBaseView

- (BOOL)isOpaque {
    return YES;  // the base fill is opaque in every appearance, whatever the washes do
}

- (void)drawRect:(NSRect)dirtyRect {
    [super drawRect:dirtyRect];

    NSRect bounds = self.bounds;
    NSColor *base = [NSColor controlBackgroundColor];
    [base setFill];
    NSRectFill(bounds);

    CGContextRef ctx = NSGraphicsContext.currentContext.CGContext;
    CGColorSpaceRef srgb = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);

    // Cool blue (sRGB 0.34, 0.62, 0.95 -- the tab bar's accent) from the top-leading
    // corner, which in this view's unflipped geometry is (0, height).
    const CGFloat blue[] = { 0.34, 0.62, 0.95, 0.16,   // start: the tab accent at 16%
                             0.34, 0.62, 0.95, 0.0 };  // end: same hue, transparent
    const CGFloat blueLocations[] = { 0.0, 1.0 };
    CGGradientRef blueGrad = CGGradientCreateWithColorComponents(srgb, blue, blueLocations, 2);
    CGContextSaveGState(ctx);
    CGContextClipToRect(ctx, bounds);
    CGPoint blueCentre = CGPointMake(0.0, NSMaxY(bounds));
    CGContextDrawRadialGradient(ctx, blueGrad, blueCentre, 20.0,
                                blueCentre, 680.0,
                                kCGGradientDrawsAfterEndLocation);
    CGContextRestoreGState(ctx);
    CGGradientRelease(blueGrad);

    // Warm amber (sRGB 0.98, 0.72, 0.42) from the bottom-trailing corner.
    const CGFloat amber[] = { 0.98, 0.72, 0.42, 0.12,   // start: warm amber at 12%
                              0.98, 0.72, 0.42, 0.0 };
    const CGFloat amberLocations[] = { 0.0, 1.0 };
    CGGradientRef amberGrad = CGGradientCreateWithColorComponents(srgb, amber, amberLocations, 2);
    CGContextSaveGState(ctx);
    CGContextClipToRect(ctx, bounds);
    CGPoint amberCentre = CGPointMake(NSMaxX(bounds), 0.0);
    CGContextDrawRadialGradient(ctx, amberGrad, amberCentre, 20.0,
                                amberCentre, 720.0,
                                kCGGradientDrawsAfterEndLocation);
    CGContextRestoreGState(ctx);
    CGGradientRelease(amberGrad);

    CGColorSpaceRelease(srgb);
}

@end
