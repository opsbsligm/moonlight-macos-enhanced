//
//  GlassOverlayContainer.m
//  Moonlight for macOS
//
//  See GlassOverlayContainer.h for why this exists.
//

#import "GlassOverlayContainer.h"

// AppKit added `effectIsInteractive` in macOS 27, and a build host may compile against an
// older SDK than the systems this runs on -- the CI image builds with the 26.x SDK, where
// that property is simply not in the header. Asking the object rather than the header is
// the only way to use it from both, and where the property does not exist this does
// nothing, which is the same behaviour as a system with no interactive glass.
static void MLSetGlassInteractivity(NSView *glass, BOOL interactive) {
    SEL setter = NSSelectorFromString(@"setEffectIsInteractive:");
    if (glass == nil || ![glass respondsToSelector:setter]) {
        return;
    }
    NSMethodSignature *signature = [glass methodSignatureForSelector:setter];
    NSInvocation *invocation = [NSInvocation invocationWithMethodSignature:signature];
    invocation.target = glass;
    invocation.selector = setter;
    [invocation setArgument:&interactive atIndex:2];
    [invocation invoke];
}

@interface GlassOverlayContainer ()
@property (nonatomic, strong) NSView *contentView;
@property (nonatomic, readwrite, strong) NSView *backgroundView;
@property (nonatomic, readwrite) BOOL usesSystemGlass;
@property (nonatomic) BOOL requestedInteractivity;
@end

@implementation GlassOverlayContainer

+ (NSVisualEffectMaterial)fallbackMaterial {
    return NSVisualEffectMaterialHUDWindow;
}

+ (instancetype)containerWithCornerRadius:(CGFloat)cornerRadius {
    GlassOverlayContainer *container = [[GlassOverlayContainer alloc] initWithFrame:NSZeroRect];
    container.cornerRadius = cornerRadius;
    return container;
}

- (instancetype)initWithFrame:(NSRect)frameRect {
    if ((self = [super initWithFrame:frameRect])) {
        // The panels position themselves by frame (the log browser lays its controls out
        // by hand), so this view keeps the autoresizing mask on and does not force the
        // constraint path on its callers.
        [self buildBackground];
    }
    return self;
}

// The system's glass when the system has it, the shipped vibrancy material when it
// does not. Both paths put the caller's content inside `contentView`, so nothing above
// this method knows which one it got -- which is the point: a panel that asks for glass
// and quietly receives none is a claim, not a behaviour.
- (void)buildBackground {
    NSView *background = nil;
    NSView *content = nil;

    if (@available(macOS 26.0, *)) {
        NSGlassEffectView *glass = [[NSGlassEffectView alloc] initWithFrame:NSZeroRect];
        content = [[NSView alloc] initWithFrame:NSZeroRect];
        glass.contentView = content;
        glass.cornerRadius = _cornerRadius;
        background = glass;
        self.usesSystemGlass = YES;
    } else {
        NSVisualEffectView *effect = [[NSVisualEffectView alloc] initWithFrame:NSZeroRect];
        effect.material = [[self class] fallbackMaterial];
        effect.blendingMode = NSVisualEffectBlendingModeBehindWindow;
        effect.state = NSVisualEffectStateActive;
        content = [[NSView alloc] initWithFrame:NSZeroRect];
        background = effect;
        self.usesSystemGlass = NO;
        // Rounded vibrancy needs layer masking, which is what the panels did by hand
        // before this container existed.
        effect.wantsLayer = YES;
    }

    background.frame = self.bounds;
    background.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    [self addSubview:background];
    if (!self.usesSystemGlass) {
        // The vibrancy path owns its content view, so it is pinned here. The glass path
        // is laid out by the system, and the harness measures that the content still
        // covers the panel rather than being inset by the rim.
        content.frame = background.bounds;
        content.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
        [background addSubview:content];
    }
    self.backgroundView = background;
    self.contentView = content;
}

- (void)setGlassIsInteractive:(BOOL)glassIsInteractive {
    _requestedInteractivity = glassIsInteractive;
    if (!self.usesSystemGlass) {
        return;
    }
    MLSetGlassInteractivity(self.backgroundView, glassIsInteractive);
}

- (BOOL)glassIsInteractive {
    return _requestedInteractivity;
}

- (void)setCornerRadius:(CGFloat)cornerRadius {
    _cornerRadius = cornerRadius;
    if (@available(macOS 26.0, *)) {
        if (self.usesSystemGlass) {
            ((NSGlassEffectView *)self.backgroundView).cornerRadius = cornerRadius;
            return;
        }
    }
    self.backgroundView.wantsLayer = YES;
    self.backgroundView.layer.cornerRadius = cornerRadius;
    self.backgroundView.layer.maskedCorners = kCALayerMinXMinYCorner | kCALayerMaxXMinYCorner
                                        | kCALayerMinXMaxYCorner | kCALayerMaxXMaxYCorner;
}

@end
