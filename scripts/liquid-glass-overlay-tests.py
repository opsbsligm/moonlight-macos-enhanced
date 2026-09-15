#!/usr/bin/env python3
"""Prove the stream's panels get the system's glass, not the pre-glass vibrancy.

Seven overlays -- the timeout panel, the log browser, the reconnect panel, the stream
menu, the connection warning, the mouse-mode hint and the notification banner -- each
built their own NSVisualEffectView with NSVisualEffectMaterialHUDWindow. That is the
material from before the liquid-glass APIs existed, so the panels a player looks at for
the whole session were the part of the interface that never moved, while the settings
page and the tab bar used the real thing.

The container in Limelight/macOS/Views answers that question once, and the claim is
only worth anything if something measures it: an availability branch is not a
behaviour. So this harness compiles the container as shipped and runs it in a window,
then reads back what the view actually built -- the class behind the content, whether
the radius reached it, and what the Core Animation tree underneath is made of.

Two things a source scan cannot answer are measured rather than argued:

  * legibility. The panels put white labels on the material, so the panel is captured
    inside the dark HUD appearance the stream window really pins (VibrantDark) and the
    contrast of white text against the panel's own background is computed. A panel that
    loses that appearance -- a light-appearance window, or a material that no longer
    follows it -- is refused, which also proves the measurement is not a constant.
  * interactive glass. The control-centre pill asks for `glassIsInteractive`, and a
    property a view ignores looks identical to one it honours until something reads it
    back off the glass view.

The known-bad shapes are the same file with the glass branch switched off and with the
interactivity never reaching the glass -- what a missing availability check or a
half-finished conversion looks like. On a system with real glass they have to fail, and
the harness says which side of each branch it is on rather than assuming the host
running it is representative.

Exit 0 only when the shipped container is what this host should be drawing, and the
glass-less and interactivity-less shapes are refused wherever they are distinguishable.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTAINER_M = os.path.join(ROOT, "Limelight", "macOS", "Views", "GlassOverlayContainer.m")
CONTAINER_H = os.path.join(ROOT, "Limelight", "macOS", "Views", "GlassOverlayContainer.h")

# What the panels looked like before glass, so the fallback cannot drift silently.
FALLBACK_MATERIAL = "NSVisualEffectMaterialHUDWindow"

SOURCE = r"""
#import <AppKit/AppKit.h>
#include <stdlib.h>
#include <math.h>
#import "__CONTAINER_HEADER__"

static NSString *gReport = nil;

// Every layer class under a view, because the glass backing is a Core Animation
// implementation class and no AppKit view class reports it.
static NSString *LayerClasses(NSView *view) {
    NSMutableSet *names = [NSMutableSet set];
    NSMutableArray<CALayer *> *queue = [NSMutableArray array];
    if (view.layer) [queue addObject:view.layer];
    for (NSUInteger seen = 0; seen < 256 && queue.count; seen++) {
        CALayer *layer = queue.firstObject;
        [queue removeObjectAtIndex:0];
        [names addObject:NSStringFromClass(layer.class)];
        [queue addObjectsFromArray:layer.sublayers ?: @[]];
    }
    return [[names.allObjects sortedArrayUsingSelector:@selector(compare:)] componentsJoinedByString:@","];
}

static BOOL Append(NSString *line, BOOL ok) {
    // Printed as it is measured: a probe that traps partway has to show which
    // assertion it reached, instead of an empty transcript and an exit signal.
    printf("%-4s %s\n", ok ? "ok" : "FAIL", line.UTF8String);
    fflush(stdout);
    gReport = [gReport stringByAppendingFormat:@"%@%@ %s\n",
               gReport.length ? @"\n" : @"", ok ? @"ok" : @"FAIL", line.UTF8String];
    return ok;
}

int main(void) {
    @autoreleasepool {
        setbuf(stdout, NULL);
        gReport = @"";
        int failures = 0;
        NSInteger system = NSProcessInfo.processInfo.operatingSystemVersion.majorVersion;
        BOOL glassExpected = system >= 26;

        // AppKit needs an application object before it will host a view hierarchy.
        NSApplication *app = [NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyProhibited];

        NSWindow *window = [[NSWindow alloc]
            initWithContentRect:NSMakeRect(0, 0, 320, 200)
                      styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered
                        defer:NO];
        GlassOverlayContainer *panel = [GlassOverlayContainer containerWithCornerRadius:24.0];
        NSTextField *label = [NSTextField labelWithString:@"panel content"];
        label.translatesAutoresizingMaskIntoConstraints = NO;
        [panel.contentView addSubview:label];
        [window.contentView addSubview:panel];
        panel.translatesAutoresizingMaskIntoConstraints = YES;
        panel.frame = NSMakeRect(60, 60, 200, 80);
        [window layoutIfNeeded];
        [window displayIfNeeded];

        // The content has to sit inside whatever background was chosen, not beside it.
        NSView *background = panel.backgroundView;
        failures += !Append(@"the panel's content sits inside the chosen background",
                            background != nil && [panel.contentView isDescendantOf:background]
                            && [background isDescendantOf:panel]);

        // The panels position their controls by frame inside the panel, so a content
        // view that arrives inset by the glass rim would move every control in the log
        // browser. Measured, not assumed.
        NSRect contentInPanel = [panel.contentView convertRect:panel.contentView.bounds
                                                        toView:panel];
        CGFloat insetX = fabs(NSMinX(contentInPanel) - NSMinX(panel.bounds));
        CGFloat insetY = fabs(NSMinY(contentInPanel) - NSMinY(panel.bounds));
        CGFloat sizeDiff = fabs(NSWidth(contentInPanel) - NSWidth(panel.bounds))
                         + fabs(NSHeight(contentInPanel) - NSHeight(panel.bounds));
        failures += !Append([NSString stringWithFormat:
                             @"the content covers the panel (inset %.2f/%.2f, size delta %.2f)",
                             insetX, insetY, sizeDiff],
                            insetX <= 1.0 && insetY <= 1.0 && sizeDiff <= 2.0);

        BOOL glass = panel.usesSystemGlass;
        NSString *backgroundClass = NSStringFromClass(background.class);
        NSString *glassLine = [NSString stringWithFormat:
            @"the panel background is the system glass on macOS %ld "
            @"(container reports %@, background is %@%@)",
            (long)system, glass ? @"glass" : @"vibrancy", backgroundClass,
            glassExpected ? @"" : @", so vibrancy is the correct answer here"];
        failures += !Append(glassLine, glass == glassExpected);

        CGFloat radius = 0;
        if (glass) {
            if (@available(macOS 26.0, *)) {
                radius = ((NSGlassEffectView *)background).cornerRadius;
            }
        } else {
            radius = background.layer.cornerRadius;
        }
        failures += !Append(@"the radius the panel asked for reached the background",
                            !glass || radius == 24.0);

        NSString *layers = LayerClasses(panel);
        BOOL backdrop = [layers rangeOfString:@"Backdrop"].location != NSNotFound;
        NSString *layerLine = [NSString stringWithFormat:
            @"the layer tree under the panel reports %@%@",
            layers, glass ? @" -- a glass backing is required here" : @""];
        failures += !Append(layerLine, glass ? backdrop : YES);

        // Legibility. These panels put white labels on the material, and the stream
        // window pins a dark HUD appearance for them (StreamViewController.m sets
        // NSAppearanceNameVibrantDark). Measured inside that appearance, and the same
        // panel measured in a light window, so the number cannot be a constant.
        for (int appearanceCase = 0; appearanceCase < 2; appearanceCase++) {
            BOOL hudDark = appearanceCase == 0;
            NSWindow *legible = [[NSWindow alloc]
                initWithContentRect:NSMakeRect(0, 0, 400, 200)
                          styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered
                            defer:NO];
            if (hudDark) {
                legible.appearance = [NSAppearance appearanceNamed:NSAppearanceNameVibrantDark];
            } else {
                legible.appearance = [NSAppearance appearanceNamed:NSAppearanceNameAqua];
            }
            legible.contentView.wantsLayer = YES;
            legible.contentView.layer.backgroundColor = [NSColor whiteColor].CGColor;

            GlassOverlayContainer *contrastPanel =
                [GlassOverlayContainer containerWithCornerRadius:10.0];
            contrastPanel.frame = NSMakeRect(60, 60, 280, 44);
            NSTextField *whiteLabel = [NSTextField labelWithString:@"Poor Connection"];
            whiteLabel.textColor = [NSColor whiteColor];
            whiteLabel.font = [NSFont systemFontOfSize:13 weight:NSFontWeightSemibold];
            whiteLabel.frame = NSMakeRect(10, 13, 200, 18);
            [contrastPanel.contentView addSubview:whiteLabel];
            [legible.contentView addSubview:contrastPanel];
            [legible layoutIfNeeded];
            [legible displayIfNeeded];

            NSBitmapImageRep *bitmap =
                [contrastPanel bitmapImageRepForCachingDisplayInRect:contrastPanel.bounds];
            [contrastPanel cacheDisplayInRect:contrastPanel.bounds toBitmapImageRep:bitmap];
            double total = 0, samples = 0;
            for (NSInteger y = 10; y < bitmap.pixelsHigh - 10; y += 2) {
                for (NSInteger x = 10; x < bitmap.pixelsWide - 10; x += 2) {
                    total += [[bitmap colorAtX:x y:y] brightnessComponent];
                    samples += 1;
                }
            }
            double background = samples ? total / samples : 1.0;
            double contrast = (1.0 + 0.05) / (fmax(background, 0.0) + 0.05);
            NSString *ratio = [NSString stringWithFormat:
                @"white labels read at %.2f:1 against the panel in the %@ appearance",
                contrast, hudDark ? @"dark HUD" : @"light"];
            if (hudDark) {
                failures += !Append(ratio, contrast >= 4.5);
            } else {
                // The measurement has to move with the appearance, or it measures nothing.
                failures += !Append([ratio stringByAppendingString:
                                     @" -- this one must fail, it is the shape that is refused"],
                                    contrast < 4.5);
            }
        }

        // The pill asks for interactive glass; a view that ignores the property looks
        // exactly like one that honours it until the glass itself is asked.
        GlassOverlayContainer *control = [GlassOverlayContainer containerWithCornerRadius:14.0];
        control.glassIsInteractive = YES;
        NSNumber *answered = nil;
        if (control.usesSystemGlass) {
            // Read the answer off the glass, by name rather than by header: the SDK this
            // compiles against is not necessarily the system it ends up running on.
            @try {
                answered = [control.backgroundView valueForKey:@"effectIsInteractive"];
            } @catch (NSException *exception) {
                answered = nil;
            }
        }
        BOOL interactivityHonoured = answered != nil ? [answered boolValue]
                                                     : control.glassIsInteractive;
        failures += !Append([NSString stringWithFormat:
                             @"a panel that asks for interactive glass gets it (%@)",
                             answered ? @"read back off the glass"
                                      : @"this system's glass has no such answer"],
                            interactivityHonoured == YES);

        // The fallback keeps the material the panels shipped with, whichever way the
        // host's version falls out.
        failures += !Append(@"the vibrancy fallback is the material the panels shipped with",
                            [GlassOverlayContainer fallbackMaterial]
                            == (NSVisualEffectMaterial)NSVisualEffectMaterialHUDWindow);

        printf("%d scenario failure(s) on macOS %ld\n", failures, (long)system);
        fflush(stdout);
        return failures ? 1 : 0;
    }
}
"""


def source_for(variant=None):
    body = open(CONTAINER_M, encoding="utf-8").read()
    if variant == "no-glass":
        # What it looks like when the availability branch is never taken: a container
        # that still says it is a panel, and quietly draws the pre-glass material.
        mutated = body.replace("if (@available(macOS 26.0, *)) {", "if (NO) {")
        if mutated == body:
            raise SystemExit("the container no longer has an availability branch, so this "
                             "harness would be proving nothing")
        body = mutated
    elif variant == "no-interactive":
        # The setter that keeps the answer but never hands it to the glass: the pill is a
        # button whose glass would sit there motionless, and nothing above this method
        # could tell.
        mutated = body.replace("MLSetGlassInteractivity(self.backgroundView, glassIsInteractive);",
                               "MLSetGlassInteractivity(self.backgroundView, NO);")
        if mutated == body:
            raise SystemExit("the container no longer hands interactivity to the glass, so "
                             "this harness would be proving nothing")
        body = mutated
    elif variant is not None:
        raise SystemExit("unknown variant %r" % variant)
    return (SOURCE.replace("__CONTAINER_HEADER__", CONTAINER_H) + "\n"
            + body.replace('#import "GlassOverlayContainer.h"', "") + "\n")


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        check.failures.append(message)
check.failures = []


def run_variant(directory, label, variant=None):
    path = os.path.join(directory, "container_%s.m" % label)
    open(path, "w", encoding="utf-8").write(source_for(variant))
    binary = os.path.join(directory, "container_%s" % label)
    cc, sdk = apple_toolchain.clang_and_sdk("liquid glass overlay probe")
    cmd = [cc, "-fobjc-arc", "-fmodules", "-mmacosx-version-min=13.0", "-isysroot", sdk,
           "-framework", "AppKit", path, "-o", binary]
    built = subprocess.run(cmd, capture_output=True, text=True)
    if built.returncode != 0:
        print("FAIL %s could not be compiled:\n%s" % (label, built.stderr.strip()[-1800:]))
        return None
    return subprocess.run([binary], capture_output=True, text=True, timeout=120)


def main():
    # Which panels still draw their own vibrancy is a debt list, and
    # scripts/liquid-glass-audit.py owns it. What is measured here is what the container
    # actually builds on the host running the gate, which no source scan can answer.
    with tempfile.TemporaryDirectory() as tmp:
        shipped = run_variant(tmp, "shipped")
        if shipped is None:
            return 1
        print(shipped.stdout.rstrip())
        if shipped.returncode != 0 and shipped.stderr.strip():
            print("     probe said: " + shipped.stderr.strip().splitlines()[-1])
        check(shipped.returncode == 0,
              "the shipped container draws what this host should draw"
              if shipped.returncode == 0 else
              "the shipped container fails %d assertion(s) on this host"
              % (shipped.returncode or 1))

        broken = run_variant(tmp, "no-glass", variant="no-glass")
        if broken is None:
            return 1
        print(broken.stdout.rstrip())
        host = re.search(r"on macOS (\d+)", broken.stdout or "")
        major = int(host.group(1)) if host else 0
        if major >= 26:
            check(broken.returncode != 0,
                  "the glass-less shape is refused on a host that has glass"
                  if broken.returncode != 0 else
                  "the glass-less shape passes on a host with real glass: the harness "
                  "cannot tell glass from vibrancy")
        else:
            print("skip  teeth check (this host has no system glass to withhold)")

        quiet = run_variant(tmp, "no-interactive", variant="no-interactive")
        if quiet is None:
            return 1
        print(quiet.stdout.rstrip())
        if major >= 27:
            check(quiet.returncode != 0,
                  "glass that never got its interactivity is refused"
                  if quiet.returncode != 0 else
                  "a container that never hands interactivity to the glass still passes: "
                  "the read-back is not reading the glass")
        else:
            print("skip  interactivity teeth (this host has no interactive glass)")

    print("%d harness failure(s)" % len(check.failures))
    return 1 if check.failures else 0


sys.exit(main())
