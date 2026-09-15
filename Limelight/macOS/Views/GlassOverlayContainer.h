//
//  GlassOverlayContainer.h
//  Moonlight for macOS
//
//  One background for every panel the stream puts on top of the video: the system's
//  own glass where the system has it, HUD-window vibrancy where it does not.
//
//  Seven overlays built their own NSVisualEffectView with NSVisualEffectMaterialHUDWindow
//  -- the timeout panel, the log browser, the reconnect panel, the stream menu, the
//  connection warning, the mouse-mode hint and the notification banner. That is the
//  material from before the liquid-glass APIs, so the streaming interface was the one
//  part of this app that never moved to it: the settings page and the tab bar sample
//  the system glass, and the panels a player actually looks at during a session did not.
//
//  One container owns the answer, because the choice has to be made the same way seven
//  times or the panels will disagree with each other on screen. NSGlassEffectView is a
//  container view whose content it embeds in glass, so the content goes into its
//  contentView -- arbitrary subviews of the glass view itself are explicitly not
//  guaranteed a z-order, which is why the content host exists here rather than callers
//  adding straight into the glass.
//

#import <AppKit/AppKit.h>

NS_ASSUME_NONNULL_BEGIN

@interface GlassOverlayContainer : NSView

/// A panel background with the corners rounded by `cornerRadius`.
+ (instancetype)containerWithCornerRadius:(CGFloat)cornerRadius;

/// Where a caller adds what the panel shows. Never add to the container itself:
/// on the glass path that view is the system's, and off it it is the vibrancy view.
@property (nonatomic, readonly) NSView *contentView;

/// The radius the panel is drawn with, whatever the background turns out to be.
@property (nonatomic) CGFloat cornerRadius;

/// The view drawing behind the content: the system's glass, or the vibrancy view.
/// Published because a panel that asks for glass and quietly receives none is a claim,
/// not a behaviour, and something has to be able to go and look.
@property (nonatomic, readonly, strong) NSView *backgroundView;

/// YES when the system drew real glass behind the content. Read-only, and reported by
/// the interface diagnostics so a panel never claims a material it is not using.
@property (nonatomic, readonly) BOOL usesSystemGlass;

/// The material the vibrancy path uses, exposed so the gate can assert the fallback is
/// still the one the panels shipped with before glass existed.
+ (NSVisualEffectMaterial)fallbackMaterial;

@end

NS_ASSUME_NONNULL_END
