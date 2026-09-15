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

The known-bad shape is the same file with the glass branch switched off, which is what
a missing availability check or a reverted container looks like. On a system with real
glass it has to fail the assertion that the panel is glass, and the harness says which
side of the branch it is on rather than assuming the host running it is representative.

Exit 0 only when the shipped container is what this host should be drawing, and the
glass-less shape is refused wherever that is distinguishable.
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
        distinguishable = int(re.search(r"on macOS (\d+)", broken.stdout or "").group(1)) >= 26 \
            if re.search(r"on macOS (\d+)", broken.stdout or "") else False
        if distinguishable:
            check(broken.returncode != 0,
                  "the glass-less shape is refused on a host that has glass"
                  if broken.returncode != 0 else
                  "the glass-less shape passes on a host with real glass: the harness "
                  "cannot tell glass from vibrancy")
        else:
            print("skip  teeth check (this host has no system glass to withhold)")

    print("%d harness failure(s)" % len(check.failures))
    return 1 if check.failures else 0


sys.exit(main())
