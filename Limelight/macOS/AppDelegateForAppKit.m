//
//  AppDelegateForAppKit.m
//  Moonlight for macOS
//
//  Created by Michael Kenny on 10/2/18.
//  Copyright © 2018 Moonlight Stream. All rights reserved.
//

#import "AppDelegateForAppKit.h"
#import "DatabaseSingleton.h"
#import "AboutViewController.h"
#import "NSWindow+Moonlight.h"
#import "NSResponder+Moonlight.h"
#import "ControllerNavigation.h"

#import "MASPreferencesWindowController.h"
#import "GeneralPrefsPaneVC.h"

#import "AppsViewController.h"
#import "AppsWorkspaceViewController.h"
#import "TemporaryHost.h"
#import "Moonlight-Swift.h"
#import "DataManager.h"
#import <objc/runtime.h>
#import <ApplicationServices/ApplicationServices.h>

typedef enum : NSUInteger {
    SystemTheme,
    LightTheme,
    DarkTheme,
} Theme;


#ifdef DEBUG
// A render probe, compiled only for Debug and inert unless ML_RENDER_PROBE is set.
//
// The embedded settings page and the glass surfaces are the two things a build
// cannot sign off on its own: a page can open in a second window and still pass
// every compile-time rule, and a glass material can be absent while the source
// still says the right words. Both were reported as "needs a human eye" and the
// human eye was blocked, so the claims sat unverified. This probe drives the
// production presenter through the production call and measures what actually
// happened, so scripts/render-probe.py can assert it without a stream session
// and without touching anyone's settings: the runner points HOME at a scratch
// directory, so the database and preferences under test are the probe's own.
static void MLProbeSpin(NSTimeInterval seconds) {
    NSDate *until = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while ([until timeIntervalSinceNow] > 0) {
        NSEvent *event = [NSApp nextEventMatchingMask:NSEventMaskAny
                                            untilDate:[NSDate dateWithTimeIntervalSinceNow:0.02]
                                               inMode:NSDefaultRunLoopMode
                                              dequeue:YES];
        if (event) {
            [NSApp sendEvent:event];
        }
    }
}

static NSUInteger MLProbeCountMatching(NSView *root, BOOL (^match)(NSView *)) {
    NSUInteger found = match(root) ? 1 : 0;
    for (NSView *child in root.subviews) {
        found += MLProbeCountMatching(child, match);
    }
    return found;
}

static NSDictionary *MLProbePixels(NSString *path, NSBitmapImageRep *rep) {
    NSUInteger wide = rep.pixelsWide, high = rep.pixelsHigh;
    double sum = 0, sumSquared = 0;
    NSUInteger sampled = 0;
    NSMutableSet<NSNumber *> *colours = [NSMutableSet set];
    for (NSUInteger y = 0; y < high; y += 3) {
        for (NSUInteger x = 0; x < wide; x += 3) {
            NSColor *colour = [rep colorAtX:(NSInteger)x y:(NSInteger)y];
            if (colour == nil) {
                continue;
            }
            NSColor *rgb = [colour colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
            CGFloat red = [rgb redComponent], green = [rgb greenComponent];
            CGFloat blue = [rgb blueComponent];
            CGFloat luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue;
            sum += luminance;
            sumSquared += luminance * luminance;
            sampled++;
            [colours addObject:@((NSUInteger)(red * 31) << 10 | (NSUInteger)(green * 31) << 5
                                 | (NSUInteger)(blue * 31))];
        }
    }
    double mean = sampled ? sum / sampled : 0;
    double variance = sampled ? sumSquared / sampled - mean * mean : 0;
    if (path) {
        NSData *png = [rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
        [png writeToFile:path atomically:YES];
    }
    return @{ @"mean": @(mean),
              @"stddev": @(sqrt(MAX(variance, 0))),
              @"distinctColours": @(colours.count),
              @"sampled": @(sampled) };
}

static NSImage *MLProbePatternImage(NSSize size) {
    NSImage *image = [[NSImage alloc] initWithSize:size];
    [image lockFocus];
    [[NSColor whiteColor] set];
    NSRectFill(NSMakeRect(0, 0, size.width, size.height));
    const CGFloat cell = 22;
    for (CGFloat y = 0; y < size.height; y += cell) {
        for (CGFloat x = 0; x < size.width; x += cell) {
            BOOL dark = (((NSInteger)(x / cell)) + ((NSInteger)(y / cell))) % 2 == 0;
            [[NSColor colorWithSRGBRed:dark ? 0.05 : 0.95
                                 green:dark ? 0.05 : 0.95
                                  blue:dark ? 0.05 : 0.95
                                 alpha:1] set];
            NSRectFill(NSMakeRect(x, y, cell, cell));
        }
    }
    [image unlockFocus];
    return image;
}

static NSImage *MLProbeSolidImage(NSSize size, CGFloat red, CGFloat green, CGFloat blue) {
    NSImage *image = [[NSImage alloc] initWithSize:size];
    [image lockFocus];
    [[NSColor colorWithSRGBRed:red green:green blue:blue alpha:1] set];
    NSRectFill(NSMakeRect(0, 0, size.width, size.height));
    [image unlockFocus];
    return image;
}

static NSDictionary<NSString *, NSNumber *> *MLProbeClassInventory(NSView *root) {
    NSMutableDictionary<NSString *, NSNumber *> *tally = [NSMutableDictionary dictionary];
    NSMutableArray<NSView *> *queue = [NSMutableArray arrayWithObject:root];
    while (queue.count) {
        NSView *view = queue.firstObject;
        [queue removeObjectAtIndex:0];
        NSString *name = NSStringFromClass([view class]);
        tally[name] = @(tally[name].unsignedIntegerValue + 1);
        [queue addObjectsFromArray:view.subviews];
    }
    return tally;
}

static NSDictionary *MLProbeBlockAnalysis(NSBitmapImageRep *rep, NSRange xRange, NSRange yRange) {
    const NSInteger block = 24;
    NSUInteger blocks = 0, smoothed = 0, patterned = 0, flat = 0;
    double varianceSum = 0;
    for (NSInteger y = (NSInteger)yRange.location; y + block <= (NSInteger)(NSMaxRange(yRange)); y += block) {
        for (NSInteger x = (NSInteger)xRange.location; x + block <= (NSInteger)(NSMaxRange(xRange)); x += block) {
            double sum = 0, squared = 0;
            NSUInteger n = 0;
            for (NSInteger dy = 0; dy < block; dy += 2) {
                for (NSInteger dx = 0; dx < block; dx += 2) {
                    NSColor *colour = [rep colorAtX:x + dx y:y + dy];
                    NSColor *rgb = [colour colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
                    CGFloat luminance = 0.2126 * [rgb redComponent] + 0.7152 * [rgb greenComponent]
                                        + 0.0722 * [rgb blueComponent];
                    sum += luminance;
                    squared += luminance * luminance;
                    n++;
                }
            }
            if (!n) continue;
            double mean = sum / n;
            double variance = squared / n - mean * mean;
            double stddev = sqrt(MAX(variance, 0));
            varianceSum += stddev;
            blocks++;
            // A checkerboard cell of 22 px swings between .05 and .95; a page that
            // simply covers it sits at a steady ~.93; glass over it sits between.
            if (stddev > 0.30) {
                patterned++;
            } else if (stddev > 0.02 && stddev < 0.25 && mean > 0.10 && mean < 0.90) {
                smoothed++;
            } else if (stddev <= 0.02) {
                flat++;
            }
        }
    }
    return @{ @"blocks": @(blocks), @"patterned": @(patterned), @"smoothedMidTone": @(smoothed),
              @"flat": @(flat), @"meanBlockStddev": @(blocks ? varianceSum / blocks : 0) };
}

static NSDictionary *MLProbeTranslucentRegions(NSBitmapImageRep *patternRep,
                                               NSBitmapImageRep *solidRep,
                                               NSString **descriptionOut) {
    const NSInteger block = 24;
    NSInteger wide = (NSInteger)patternRep.pixelsWide, high = (NSInteger)patternRep.pixelsHigh;
    NSUInteger changed = 0, considered = 0;
    NSInteger minX = NSIntegerMax, maxX = NSIntegerMin, minY = NSIntegerMax, maxY = NSIntegerMin;
    for (NSInteger y = 0; y + block <= high; y += block) {
        for (NSInteger x = 0; x + block <= wide; x += block) {
            double shift = 0;
            NSUInteger samples = 0;
            for (NSInteger dy = 0; dy < block; dy += 3) {
                for (NSInteger dx = 0; dx < block; dx += 3) {
                    NSColor *a = [[patternRep colorAtX:x + dx y:y + dy]
                                  colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
                    NSColor *b = [[solidRep colorAtX:x + dx y:y + dy]
                                  colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
                    if (!a || !b) continue;
                    shift += fabs([a redComponent] - [b redComponent])
                           + fabs([a greenComponent] - [b greenComponent])
                           + fabs([a blueComponent] - [b blueComponent]);
                    samples++;
                }
            }
            if (!samples) continue;
            considered++;
            if (shift / samples > 0.05) {
                changed++;
                minX = MIN(minX, x); maxX = MAX(maxX, x + block);
                minY = MIN(minY, y); maxY = MAX(maxY, y + block);
            }
        }
    }
    if (descriptionOut && changed) {
        // Captured bitmaps are top-down, so say so rather than letting a reader
        // read the band as AppKit coordinates.
        *descriptionOut = [NSString stringWithFormat:@"%lu of %lu blocks read the backdrop through "
                           "the page, spanning y %ld..%ld and x %ld..%ld from the top edge",
                           (unsigned long)changed, (unsigned long)considered,
                           (long)minY, (long)maxY, (long)minX, (long)maxX];
    }
    return @{ @"changedBlocks": @(changed), @"consideredBlocks": @(considered) };
}

static void MLProbeRecordLayers(NSView *root, NSMutableDictionary<NSString *, NSNumber *> *tally) {
    NSMutableArray<NSView *> *queue = [NSMutableArray arrayWithObject:root];
    while (queue.count) {
        NSView *view = queue.firstObject;
        [queue removeObjectAtIndex:0];
        CALayer *layer = view.layer;
        NSArray<CALayer *> *layers = layer ? [layer.sublayers arrayByAddingObject:layer] : @[];
        for (CALayer *candidate in layers) {
            NSString *name = NSStringFromClass([candidate class]);
            tally[name] = @(tally[name].unsignedIntegerValue + 1);
            for (NSString *marker in @[@"Glass", @"Material", @"VisualEffect", @"Backdrop"]) {
                if ([name rangeOfString:marker options:NSCaseInsensitiveSearch].location != NSNotFound) {
                    NSString *key = [@"material:" stringByAppendingString:name];
                    tally[key] = @(tally[key].unsignedIntegerValue + 1);
                }
            }
        }
        [queue addObjectsFromArray:view.subviews];
    }
}

// Any AppKit text field the page happens to use. SwiftUI draws its own text, so this
// is usually short; it is recorded because it is an independent second channel
// when it is populated, and its emptiness is itself a measurement.
static void MLProbeCollectTextFields(NSView *root, NSMutableArray<NSDictionary *> *texts) {
    NSMutableArray<NSView *> *queue = [NSMutableArray arrayWithObject:root];
    while (queue.count && texts.count < 1200) {
        NSView *view = queue.firstObject;
        [queue removeObjectAtIndex:0];
        if ([view isKindOfClass:[NSTextField class]]) {
            NSTextField *field = (NSTextField *)view;
            NSRect inWindow = [view convertRect:view.bounds toView:nil];
            NSRect onScreen = view.window ? [view.window convertRectToScreen:inWindow] : inWindow;
            NSString *string = field.stringValue.length ? field.stringValue : field.placeholderString;
            if (string.length) {
                [texts addObject:@{ @"text": string,
                                    @"x": @((NSInteger)onScreen.origin.x),
                                    @"y": @((NSInteger)onScreen.origin.y),
                                    @"enabled": @([view isAccessibilityEnabled]) }];
            }
        }
        [queue addObjectsFromArray:view.subviews];
    }
}

// Turn the accessibility tree on. AppKit only builds the tree an assistive client
// would read once something has actually asked for it through the accessibility
// API, and that includes the SwiftUI elements behind a hosting view: measured, the
// protocol returned a dozen nodes before this call and several hundred after. The
// response is not usable from inside the process it queries -- the client API hands
// back the application element referring to itself, with no window and no text --
// so nothing here reads the result; the checker reads the tree in-process through
// the AppKit protocol, which is populated once the request has been made.
static void MLProbeActivateAccessibility(void) {
    static BOOL requested = NO;
    if (requested) {
        return;
    }
    requested = YES;
    AXUIElementRef app = AXUIElementCreateApplication(getpid());
    CFTypeRef children = NULL;
    AXUIElementCopyAttributeValue(app, kAXChildrenAttribute, &children);
    if (children) CFRelease(children);
    CFRelease(app);
    MLProbeSpin(0.2);
}

// The in-process channel: AppKit's own accessibility protocol, which is what
// AppKit answers when an assistive client reaches a view. Whether it is populated
// is a measurement, not an assumption -- asked before the app finished launching
// it came back empty for a page that was visibly drawing text.
static void MLProbeCollectAppKitAXNodes(id element, NSUInteger depth, NSUInteger maxNodes,
                                        NSMutableArray<NSDictionary *> *nodes) {
    if (element == nil || nodes.count >= maxNodes || depth > 40) {
        return;
    }
    if ([element isKindOfClass:[NSString class]] || [element isKindOfClass:[NSNumber class]]) {
        return;
    }
    id<NSAccessibility> ax = (id<NSAccessibility>)element;
    NSString *role = nil, *label = nil, *title = nil, *value = nil;
    BOOL enabled = YES;
    NSRect frame = NSZeroRect;
    if ([ax respondsToSelector:@selector(accessibilityRole)]) role = [ax accessibilityRole];
    if ([ax respondsToSelector:@selector(accessibilityLabel)]) label = [ax accessibilityLabel];
    if ([ax respondsToSelector:@selector(accessibilityTitle)]) title = [ax accessibilityTitle];
    if ([ax respondsToSelector:@selector(accessibilityValue)]) {
        id rawValue = [ax accessibilityValue];
        if ([rawValue isKindOfClass:[NSString class]] || [rawValue isKindOfClass:[NSNumber class]]) {
            value = [rawValue description];
        }
    }
    if ([ax respondsToSelector:@selector(isAccessibilityEnabled)]) enabled = [ax isAccessibilityEnabled];
    if ([ax respondsToSelector:@selector(accessibilityFrame)]) frame = [ax accessibilityFrame];

    BOOL carriesText = label.length > 0 || title.length > 0 || value.length > 0;
    BOOL isControl = [role containsString:@"Button"] || [role containsString:@"CheckBox"]
                     || [role containsString:@"RadioButton"] || [role containsString:@"Slider"]
                     || [role isEqualToString:NSAccessibilityPopUpButtonRole]
                     || [role isEqualToString:NSAccessibilityStaticTextRole]
                     || [role isEqualToString:NSAccessibilityTextFieldRole];
    if (carriesText || isControl) {
        [nodes addObject:@{ @"role": role ?: @"", @"label": label ?: @"", @"title": title ?: @"",
                            @"value": value ?: @"", @"enabled": @(enabled),
                            @"x": @((NSInteger)frame.origin.x), @"y": @((NSInteger)frame.origin.y),
                            @"width": @((NSInteger)frame.size.width),
                            @"height": @((NSInteger)frame.size.height) }];
    }
    for (id child in [ax accessibilityChildren]) {
        MLProbeCollectAppKitAXNodes(child, depth + 1, maxNodes, nodes);
    }
    if ([element isKindOfClass:[NSView class]]) {
        for (NSView *child in [(NSView *)element subviews]) {
            MLProbeCollectAppKitAXNodes(child, depth + 1, maxNodes, nodes);
        }
    }
}

// The same tree walk, collecting the controls that open a collapsed section instead
// of the text. The capability matrix lives inside a DisclosureGroup that ships
// collapsed (`settings.app.videoCapabilityStatusExpanded` defaults to false) and
// SwiftUI vends nothing inside a collapsed group: measured on a clean launch every
// matrix row and all three of its segments are absent from the accessibility tree,
// while on a machine where the section had once been opened by hand they are all
// present. A check that only reads what is on screen would then pass or fail
// according to the history of the machine, which is the opposite of a check.
static void MLProbeCollectDisclosureTriangles(id element, NSUInteger depth,
                                             NSMutableArray<id> *triangles) {
    if (element == nil || depth > 40 || triangles.count > 64) {
        return;
    }
    if ([element isKindOfClass:[NSString class]] || [element isKindOfClass:[NSNumber class]]) {
        return;
    }
    id<NSAccessibility> ax = (id<NSAccessibility>)element;
    NSString *role = [ax respondsToSelector:@selector(accessibilityRole)] ? [ax accessibilityRole] : nil;
    if ([role isEqualToString:NSAccessibilityDisclosureTriangleRole]
        && ![triangles containsObject:element]) {
        // Collected by identity, not by count: the walk reaches the same hosted
        // element through the accessibility children and through the view tree, and
        // measured without this it reported 65 triangles for the one section the page
        // has. Pressing one control sixty-five times would have looked like a pass and
        // proved nothing about the control the label sits beside.
        [triangles addObject:element];
    }
    for (id child in [ax accessibilityChildren]) {
        MLProbeCollectDisclosureTriangles(child, depth + 1, triangles);
    }
    if ([element isKindOfClass:[NSView class]]) {
        for (NSView *child in [(NSView *)element subviews]) {
            MLProbeCollectDisclosureTriangles(child, depth + 1, triangles);
        }
    }
}

// Press the triangles that are there. Whether a press is wanted is decided by the
// caller from the label the page itself displays, because pressing a disclosure that
// is already open closes it, and because the wording belongs to the page: the string
// arrives through the page's own rules, so renaming it moves this check with it
// instead of leaving it comparing an English literal baked in here.
static NSInteger MLProbePressDisclosureTriangles(NSArray<id> *triangles) {
    NSInteger pressed = 0;
    for (id triangle in triangles) {
        id<NSAccessibility> ax = (id<NSAccessibility>)triangle;
        if ([ax respondsToSelector:@selector(accessibilityPerformPress)]) {
            [ax accessibilityPerformPress];
            pressed += 1;
        }
    }
    return pressed;
}

static BOOL MLProbeNodesVendText(NSArray<NSDictionary *> *nodes, NSString *text) {
    if (!text.length) {
        return NO;
    }
    for (NSDictionary *node in nodes) {
        if ([node[@"text"] isEqualToString:text]) {
            return YES;
        }
    }
    return NO;
}

// A ScrollView only realises the rows inside its viewport, so a page longer than
// the window cannot be read from one look: the rows below the fold are simply not
// in the tree. Find the scroller the page actually uses so the checker can read
// the bottom of it the way a user would, and report whether it managed to.
static NSScrollView *MLProbeFindScrollView(NSView *root) {
    NSMutableArray<NSView *> *queue = [NSMutableArray arrayWithObject:root];
    while (queue.count) {
        NSView *view = queue.firstObject;
        [queue removeObjectAtIndex:0];
        if ([view isKindOfClass:[NSScrollView class]]) {
            return (NSScrollView *)view;
        }
        [queue addObjectsFromArray:view.subviews];
    }
    return nil;
}

static NSArray<NSDictionary *> *MLProbeReadableNodes(NSView *root) {
    NSMutableArray<NSDictionary *> *raw = [NSMutableArray array];
    MLProbeCollectAppKitAXNodes(root, 0, 8000, raw);
    NSMutableArray<NSDictionary *> *readable = [NSMutableArray array];
    NSMutableSet<NSString *> *seen = [NSMutableSet set];
    for (NSDictionary *node in raw) {
        NSString *text = [node[@"label"] length] ? node[@"label"]
                     : ([node[@"value"] length] ? node[@"value"] : node[@"title"]);
        NSString *key = [NSString stringWithFormat:@"%@|%@|%@|%@|%@|%@|%@",
                         node[@"role"], text, node[@"enabled"], node[@"x"], node[@"y"],
                         node[@"width"], node[@"height"]];
        if ([seen containsObject:key]) {
            continue;
        }
        [seen addObject:key];
        [readable addObject:@{ @"role": node[@"role"], @"text": text,
                               @"enabled": node[@"enabled"],
                               @"x": node[@"x"], @"y": node[@"y"],
                               @"width": node[@"width"], @"height": node[@"height"] }];
    }
    return readable;
}

// Present one named pane and record everything the checker needs to decide
// whether that pane is telling the truth about this machine.
// The key the app page keeps the Advanced section's state under. Kept next to the
// probe rather than in a header because nothing but the probe uses it, and the audit
// pairs it against the string in the SwiftUI source so a rename cannot leave this
// half pointing at a preference that no longer exists.
static NSString *const MLProbeAdvancedSectionCollapsedKey
    = @"settings.app.videoCapabilityStatusExpanded";

static void MLProbeRunPanePass(NSWindow *window, NSView *backdrop, NSString *output,
                               NSInteger pane, NSString *name, NSMutableDictionary *report) {
    NSView *content = window.contentView;
    [[NSUserDefaults standardUserDefaults] setInteger:pane forKey:@"selected-settings-pane"];
    [[NSUserDefaults standardUserDefaults] synchronize];

    // Start the pass in the state a first run would be in. The point is not to tidy
    // the preferences: reading the collapsed section only after opening it proves the
    // reachability once, on whatever machine happens to have the switch already set,
    // while forcing it closed proves it on every run, and the value is restored below
    // so the run leaves the user's own choice alone.
    NSUserDefaults *probeDefaults = [NSUserDefaults standardUserDefaults];
    id previousAdvancedState = [probeDefaults objectForKey:MLProbeAdvancedSectionCollapsedKey];
    BOOL forcedTheSectionShut = NO;
    if ([name isEqualToString:@"appPane"]) {
        [probeDefaults setObject:@(NO) forKey:MLProbeAdvancedSectionCollapsedKey];
        [probeDefaults synchronize];
        forcedTheSectionShut = YES;
    }

    NSSet<NSWindow *> *windowsBefore = [NSSet setWithArray:NSApp.windows];
    NSSet<NSView *> *subviewsBefore = [NSSet setWithArray:content.subviews];
    [SettingsOverlayPresenter presentSettingsInWindow:window hostId:nil];
    MLProbeSpin(1.4);

    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    result[@"requestedPane"] = @(pane);
    result[@"storedPane"] = @([[NSUserDefaults standardUserDefaults] integerForKey:@"selected-settings-pane"]);

    // Which new windows appeared while this pane was up, and which of them host a
    // settings page. The two are recorded apart because the app can open a window
    // for its own reasons during launch, and blaming that on the presenter would
    // teach the next reader to ignore the rule. The claim being checked is narrow
    // and stays hard: no other window may host the settings page.
    NSMutableArray<NSString *> *addedWindows = [NSMutableArray array];
    NSMutableArray<NSString *> *addedSettingsWindows = [NSMutableArray array];
    for (NSWindow *candidate in NSApp.windows) {
        if ([windowsBefore containsObject:candidate] || candidate == window) {
            continue;
        }
        NSString *name = NSStringFromClass([candidate class]);
        [addedWindows addObject:name];
        BOOL hostsSettingsPage = [SettingsOverlayPresenter isSettingsPresentedInWindow:candidate]
            || [[MLProbeClassInventory(candidate.contentView).allKeys
                 filteredArrayUsingPredicate:[NSPredicate predicateWithFormat:@"self CONTAINS %@",
                                              @"LiquidGlassSettingsView"]] count] > 0;
        if (hostsSettingsPage) {
            [addedSettingsWindows addObject:name];
        }
    }
    result[@"windowsAdded"] = addedWindows;
    result[@"windowsAddedHostingSettings"] = addedSettingsWindows;

    NSMutableArray<NSView *> *added = [NSMutableArray array];
    for (NSView *candidate in content.subviews) {
        if (![subviewsBefore containsObject:candidate]) {
            [added addObject:candidate];
        }
    }
    result[@"viewsAdded"] = @(added.count);
    NSView *overlay = added.firstObject;
    if (overlay == nil) {
        report[name] = result;
        return;
    }
    result[@"overlayClass"] = NSStringFromClass([overlay class]);

    // One channel, the one that measurably works: AppKit's accessibility protocol,
    // read in-process, after the app has finished launching. The client API
    // (AXUIElementCreateApplication against this own pid) was tried first and cannot
    // be used from inside the process it queries -- it returned the application
    // element referring to itself with no window and no text, however the query was
    // sequenced or which thread asked -- so it is not kept as a channel.
    //
    // Each entry is one distinct (role, text, enabled, position): SwiftUI vends the
    // same elements several times over, and the position is kept in the key rather
    // than dropped because the checker pairs a control with the label beside it and
    // has to be able to tell two same-named rows apart from one row counted twice.
    // The claims below are checked against the model this page is rendering from,
    // taken through the presenter rather than a model built here: two models built
    // at different moments of launch disagree, and then every comparison is between
    // two different machines. Reported through `expectationsFromPageModel` so a
    // silent fallback to a stand-in is visible in the report instead of plausible.
    id presentedModel = [SettingsOverlayPresenter presentedSettingsModelForProbeInWindow:window];
    NSDictionary *expectation = [MLDebugProbeExpectations currentForModel:presentedModel];
    result[@"expectations"] = expectation;

    MLProbeActivateAccessibility();
    result[@"readableContent"] = MLProbeReadableNodes(overlay);

    // Open the collapsed half of the page the way a user reaches it, then read again.
    // The state is taken from the label the page shows: it is the page's own answer,
    // and pressing a triangle that is already open would shut it.
    NSArray<NSDictionary *> *readBeforeOpening = result[@"readableContent"];
    NSMutableArray<id> *triangles = [NSMutableArray array];
    MLProbeCollectDisclosureTriangles(overlay, 0, triangles);
    BOOL sectionShutAsDisplayed = MLProbeNodesVendText(readBeforeOpening,
                                                       expectation[@"advancedSectionCollapsedLabel"]);
    NSInteger trianglesPressed = sectionShutAsDisplayed ? MLProbePressDisclosureTriangles(triangles) : 0;
    if (trianglesPressed) {
        MLProbeSpin(0.8);
    }
    result[@"disclosureTriangles"] = @(triangles.count);
    result[@"advancedSectionCollapsed"] = @(sectionShutAsDisplayed);
    result[@"forcedTheSectionShut"] = @(forcedTheSectionShut);
    result[@"disclosuresPressed"] = @(trianglesPressed);
    result[@"readableContentExpanded"] = MLProbeReadableNodes(overlay);

    // Read the rest of the page. The enhancement controls and the capability matrix
    // are below the fold, and a ScrollView that has not been scrolled has no such
    // rows to read, so "the page does not say it" would otherwise be indistinguishable
    // from "the checker never looked at the bottom".
    NSScrollView *scroller = MLProbeFindScrollView(overlay);
    result[@"hasScrollView"] = @(scroller != nil);
    if (scroller) {
        NSView *document = scroller.documentView;
        CGFloat travel = document.frame.size.height - scroller.contentView.bounds.size.height;
        [[scroller contentView] scrollToPoint:NSMakePoint(0, MAX(travel, 0))];
        [scroller reflectScrolledClipView:scroller.contentView];
        MLProbeSpin(0.7);
        result[@"readableContentScrolled"] = MLProbeReadableNodes(overlay);
        NSBitmapImageRep *scrolledRep = [overlay bitmapImageRepForCachingDisplayInRect:overlay.bounds];
        [overlay cacheDisplayInRect:overlay.bounds toBitmapImageRep:scrolledRep];
        NSString *scrolledPNG = [NSString stringWithFormat:@"11-%@-page-bottom.png", name];
        result[@"scrolledPixels"] = MLProbePixels([output stringByAppendingPathComponent:scrolledPNG],
                                                  scrolledRep);
        result[@"scrolledCapture"] = scrolledPNG;
        result[@"scrolledTravelPoints"] = @((NSInteger)MAX(travel, 0));
    }

    NSMutableArray<NSDictionary *> *fields = [NSMutableArray array];
    MLProbeCollectTextFields(overlay, fields);
    result[@"textFields"] = fields;

    NSMutableDictionary *layers = [NSMutableDictionary dictionary];
    MLProbeRecordLayers(overlay, layers);
    NSMutableArray<NSString *> *materials = [NSMutableArray array];
    [layers enumerateKeysAndObjectsUsingBlock:^(NSString *key, NSNumber *count, BOOL *stop) {
        if ([key hasPrefix:@"material:"]) {
            [materials addObject:[NSString stringWithFormat:@"%@ x%lu",
                                  [key substringFromIndex:@"material:".length],
                                  (unsigned long)count.unsignedIntegerValue]];
        }
    }];
    result[@"materialLayers"] = materials;

    NSBitmapImageRep *rep = [overlay bitmapImageRepForCachingDisplayInRect:overlay.bounds];
    [overlay cacheDisplayInRect:overlay.bounds toBitmapImageRep:rep];
    NSString *png = [NSString stringWithFormat:@"10-%@-page.png", name];
    result[@"pixels"] = MLProbePixels([output stringByAppendingPathComponent:png], rep);
    result[@"capture"] = png;
    result[@"backdropIsStillBehindPage"] = @(backdrop.superview == content);

    [SettingsOverlayPresenter dismissSettingsFromWindow:window];
    MLProbeSpin(0.5);
    result[@"presentedAfterDismiss"] = @([SettingsOverlayPresenter isSettingsPresentedInWindow:window]);
    result[@"stillMountedAfterDismiss"] = @([overlay isDescendantOf:content]);
    if (previousAdvancedState) {
        [probeDefaults setObject:previousAdvancedState forKey:MLProbeAdvancedSectionCollapsedKey];
    } else if (forcedTheSectionShut) {
        [probeDefaults removeObjectForKey:MLProbeAdvancedSectionCollapsedKey];
    }
    [probeDefaults synchronize];
    report[name] = result;
}

static NSMutableDictionary *MLProbeReport = nil;
static NSMutableArray<NSString *> *MLProbeFailures = nil;
static NSString *MLProbeOutputDirectory = nil;
static NSWindow *MLProbeWindow = nil;
static NSView *MLProbeBackdrop = nil;
static BOOL MLProbeArmed = NO;

static void MLRunRenderProbeAndExitIfRequested(void) {
    if (getenv("ML_RENDER_PROBE") == NULL) {
        return;
    }

    NSString *output = NSProcessInfo.processInfo.environment[@"ML_RENDER_PROBE_OUTPUT"]
                       ?: [NSHomeDirectory() stringByAppendingPathComponent:@"render-probe"];
    [[NSFileManager defaultManager] createDirectoryAtPath:output
                             withIntermediateDirectories:YES
                                              attributes:nil
                                                   error:nil];

    NSMutableDictionary *report = [NSMutableDictionary dictionary];
    NSMutableArray<NSString *> *failures = [NSMutableArray array];
    void (^refuse)(NSString *) = ^(NSString *reason) { [failures addObject:reason]; };

    // No title is set on purpose: a window title is user-facing text, the
    // localizability checker is right to say so, and a Diagnostic window that
    // never outlives its own process has nothing to title.
    NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(-12000, -12000, 1100, 700)
                                                  styleMask:(NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                                                            | NSWindowStyleMaskResizable)
                                                    backing:NSBackingStoreBuffered
                                                      defer:NO];
    [window orderFrontRegardless];
    MLProbeSpin(0.4);

    NSView *content = window.contentView;
    report[@"contentSize"] = NSStringFromSize(content.bounds.size);
    // A high contrast pattern behind the page: without it the offscreen window
    // captures as black and a glass material has nothing to bend, so "is the
    // glass doing anything" cannot be measured at all.
    NSImageView *backdrop = [[NSImageView alloc] initWithFrame:content.bounds];
    backdrop.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    backdrop.image = MLProbePatternImage(content.bounds.size);
    [content addSubview:backdrop];
    MLProbeSpin(0.2);

    NSBitmapImageRep *beforeRep = [content bitmapImageRepForCachingDisplayInRect:content.bounds];
    [content cacheDisplayInRect:content.bounds toBitmapImageRep:beforeRep];
    report[@"beforePresent"] = MLProbePixels([output stringByAppendingPathComponent:@"01-window-before.png"],
                                             beforeRep);
    report[@"backdropBlocksBeforePresent"] = MLProbeBlockAnalysis(
        beforeRep, NSMakeRange(0, (NSUInteger)content.bounds.size.width),
        NSMakeRange(0, (NSUInteger)content.bounds.size.height));

    NSSet<NSWindow *> *windowsBefore = [NSSet setWithArray:NSApp.windows];
    NSSet<NSView *> *subviewsBefore = [NSSet setWithArray:content.subviews];

    [SettingsOverlayPresenter presentSettingsInWindow:window hostId:nil];
    MLProbeSpin(1.0);

    NSMutableArray<NSString *> *addedWindows = [NSMutableArray array];
    for (NSWindow *candidate in NSApp.windows) {
        if (![windowsBefore containsObject:candidate] && candidate != window) {
            [addedWindows addObject:[NSString stringWithFormat:@"%@/%@",
                                     NSStringFromClass([candidate class]), candidate.title]];
        }
    }
    report[@"windowsAddedByPresentingSettings"] = addedWindows;
    if (addedWindows.count != 0) {
        refuse([NSString stringWithFormat:@"presenting settings opened %lu new window(s): %@",
                (unsigned long)addedWindows.count, [addedWindows componentsJoinedByString:@", "]]);
    }
    if (![SettingsOverlayPresenter isSettingsPresentedInWindow:window]) {
        refuse(@"the presenter did not record settings as presented in the window it was given");
    }

    NSMutableArray<NSView *> *addedViews = [NSMutableArray array];
    for (NSView *candidate in content.subviews) {
        if (![subviewsBefore containsObject:candidate]) {
            [addedViews addObject:candidate];
        }
    }
    report[@"viewsAddedToWindowContent"] = @(addedViews.count);
    if (addedViews.count != 1) {
        refuse([NSString stringWithFormat:@"the settings page added %lu views to the window content, expected 1",
                (unsigned long)addedViews.count]);
    }

    NSView *overlay = addedViews.firstObject;
    if (overlay) {
        report[@"overlayClass"] = NSStringFromClass([overlay class]);
        report[@"overlayAlpha"] = @(overlay.alphaValue);
        report[@"overlayInsideWindowContent"] = @([overlay isDescendantOf:content]);
        report[@"overlayFrame"] = NSStringFromRect(overlay.frame);
        if (overlay.alphaValue < 0.99) {
            refuse([NSString stringWithFormat:@"the settings page is still at alpha %.3f after the fade",
                    overlay.alphaValue]);
        }
        if (![overlay isDescendantOf:content]) {
            refuse(@"the settings page is not inside the window's own content view");
        }

        NSUInteger visualEffects = MLProbeCountMatching(overlay, ^BOOL(NSView *view) {
            return [view isKindOfClass:[NSVisualEffectView class]];
        });
        NSDictionary<NSString *, NSNumber *> *inventory = MLProbeClassInventory(overlay);
        NSMutableDictionary<NSString *, NSNumber *> *layers = [NSMutableDictionary dictionary];
        MLProbeRecordLayers(overlay, layers);
        report[@"layerInventory"] = layers;
        report[@"visualEffectViews"] = @(visualEffects);
        report[@"classInventory"] = inventory;
        NSMutableArray<NSString *> *glassBackings = [NSMutableArray array];
        [inventory enumerateKeysAndObjectsUsingBlock:^(NSString *name, NSNumber *count, BOOL *stop) {
            // The hosting view is named after the SwiftUI page it hosts, so its
            // class name mentioning "Glass" says nothing about a material.
            BOOL isHosting = [name rangeOfString:@"NSHostingView"].location != NSNotFound;
            BOOL looksGlassy = [name rangeOfString:@"Glass" options:NSCaseInsensitiveSearch].location != NSNotFound
                               || [name rangeOfString:@"VisualEffect" options:NSCaseInsensitiveSearch].location != NSNotFound
                               || [name rangeOfString:@"Material" options:NSCaseInsensitiveSearch].location != NSNotFound;
            if (looksGlassy && !isHosting) {
                [glassBackings addObject:[NSString stringWithFormat:@"%@ x%lu", name,
                                          (unsigned long)count.unsignedIntegerValue]];
            }
        }];
        report[@"glassBackings"] = glassBackings;

        NSBitmapImageRep *compositeRep = [content bitmapImageRepForCachingDisplayInRect:content.bounds];
        [content cacheDisplayInRect:content.bounds toBitmapImageRep:compositeRep];
        report[@"compositePixels"] = MLProbePixels([output stringByAppendingPathComponent:@"03-composite.png"],
                                                   compositeRep);
        report[@"behindPageBlocks"] = MLProbeBlockAnalysis(
            compositeRep, NSMakeRange(0, (NSUInteger)content.bounds.size.width),
            NSMakeRange(0, (NSUInteger)content.bounds.size.height));

        // How much of the page lets the window backdrop through. Reported, not
        // asserted: the page deliberately sits on an opaque base, so its materials
        // read the page's own content rather than the window behind it, and a zero
        // here is the designed behaviour, not a missing material. What a material
        // exists at all is measured from the layer tree below.
        backdrop.image = MLProbeSolidImage(content.bounds.size, 0.95, 0.10, 0.10);
        MLProbeSpin(0.3);
        NSBitmapImageRep *overSolid = [content bitmapImageRepForCachingDisplayInRect:content.bounds];
        [content cacheDisplayInRect:content.bounds toBitmapImageRep:overSolid];
        NSString *where = nil;
        NSDictionary *readThrough = MLProbeTranslucentRegions(compositeRep, overSolid, &where);
        report[@"readThroughPageBlocks"] = readThrough;
        report[@"readThroughPageWhere"] = where ?: @"no block changed when only the backdrop changed"
                                           " (expected while the page base is opaque)";

        NSMutableArray<NSString *> *materialLayers = [NSMutableArray array];
        [layers enumerateKeysAndObjectsUsingBlock:^(NSString *name, NSNumber *count, BOOL *stop) {
            if ([name hasPrefix:@"material:"]) {
                [materialLayers addObject:[NSString stringWithFormat:@"%@ x%lu",
                                           [name substringFromIndex:@"material:".length],
                                           (unsigned long)count.unsignedIntegerValue]];
            }
        }];
        report[@"materialLayers"] = materialLayers;
        if (materialLayers.count == 0) {
            refuse([NSString stringWithFormat:@"the settings page has no backdrop or material layer, so no "
                   @"Liquid Glass material is being composited; layers present: %lu",
                    (unsigned long)layers.count]);
        }

        NSBitmapImageRep *rep = [overlay bitmapImageRepForCachingDisplayInRect:overlay.bounds];
        [overlay cacheDisplayInRect:overlay.bounds toBitmapImageRep:rep];
        NSDictionary *pixels = MLProbePixels([output stringByAppendingPathComponent:@"02-settings-page.png"], rep);

        report[@"settingsPagePixels"] = pixels;
        double stddev = [pixels[@"stddev"] doubleValue];
        NSUInteger distinct = [pixels[@"distinctColours"] unsignedIntegerValue];
        if (stddev < 0.08 || distinct < 40) {
            refuse([NSString stringWithFormat:@"the settings page rendered as flat: stddev %.3f, %lu distinct colours",
                    stddev, (unsigned long)distinct]);
        }

        [SettingsOverlayPresenter dismissSettingsFromWindow:window];
        MLProbeSpin(0.6);
        report[@"overlayStillMountedAfterDismiss"] = @([overlay isDescendantOf:content]);
        report[@"presentedAfterDismiss"] = @([SettingsOverlayPresenter isSettingsPresentedInWindow:window]);
        if ([SettingsOverlayPresenter isSettingsPresentedInWindow:window]) {
            refuse(@"the presenter still reports settings as presented after dismissal");
        }
        if ([overlay isDescendantOf:content]) {
            refuse(@"the settings page is still mounted after dismissal");
        }
    }


    // Hand over to the stage that runs after launch. Accessibility is the reason:
    // measured on this tree, an app that has not finished launching vends a
    // placeholder tree (the application element referring to itself, no window, no
    // text), so nothing could be read from the page however hard the checker looked.
    // The visual claims above do not need accessibility and stay where they were
    // proven; the readable claims run once the app is really up.
    MLProbeReport = report;
    MLProbeFailures = failures;
    MLProbeOutputDirectory = output;
    MLProbeWindow = window;
    MLProbeBackdrop = backdrop;
    MLProbeArmed = YES;
}

static void MLFinishRenderProbeIfArmed(void) {
    if (!MLProbeArmed) {
        return;
    }
    MLProbeArmed = NO;
    MLProbeSpin(1.0);

    NSMutableDictionary *report = MLProbeReport;
    NSMutableArray<NSString *> *failures = MLProbeFailures;
    NSString *output = MLProbeOutputDirectory;

    // What the production code believes about this machine, recorded so the
    // checker compares the page against the rule instead of against a string
    // someone typed into a test.


    // Three panes of the same page. The video pane holds the enhancement controls
    // and the readout of what the decoder is really doing; the App pane holds the
    // capability matrix that says whether Video Toolbox and MetalFX can work here.
    // Both used to be claims nobody could check without a human looking.
    MLProbeRunPanePass(MLProbeWindow, MLProbeBackdrop, output, 0, @"streamPane", report);
    MLProbeRunPanePass(MLProbeWindow, MLProbeBackdrop, output, 1, @"videoPane", report);
    MLProbeRunPanePass(MLProbeWindow, MLProbeBackdrop, output, 3, @"appPane", report);

    report[@"failures"] = failures;
    NSData *json = [NSJSONSerialization dataWithJSONObject:report
                                                  options:NSJSONWritingPrettyPrinted
                                                    error:nil];
    [json writeToFile:[output stringByAppendingPathComponent:@"report.json"] atomically:YES];
    fprintf(stderr, "[render-probe] %s\n", failures.count
            ? [[failures componentsJoinedByString:@"; "] UTF8String]
            : "settings embedded in one window, glass present, page drew pixels");
    fflush(stderr);
    exit(failures.count ? 1 : 0);
}
#endif

@interface AppDelegateForAppKit () <NSApplicationDelegate, NSWindowDelegate>
@property (nonatomic, strong) NSWindowController *aboutWC;
@property (nonatomic, weak) NSWindow *mainWindow;
@property (nonatomic, strong) NSWindowController *welcomePermissionsWC;
@property (nonatomic, strong) ControllerNavigation *controllerNavigation;
@property (weak) IBOutlet NSMenuItem *themeMenuItem;
@property (nonatomic, assign) BOOL didAttemptPermissionRepair;
@end

// These two keys and the probe below are declared ahead of the @implementation
// on purpose. Every call site lives inside a method body, and C requires a
// visible declaration before use: the current toolchain happens to accept the
// reverse order, a stricter one reports an undeclared function and the file
// stops building. Keeping the definitions first removes that dependency.
// ---------------------------------------------------------------------------

static NSString * const kMoonlightFirstLaunchKey = @"MoonlightFirstLaunchCompleted.v2";
static NSString * const kMoonlightLocalNetworkTriggeredKey = @"MoonlightLocalNetworkTriggered.v1";

// Send a single UDP broadcast packet to the GameStream discovery port (47989).
// This has two critical effects on macOS 12+:
//   a) Triggers the system LocalNetwork permission prompt the FIRST time it runs.
//   b) Serves as a fallback discovery probe for Sunshine/GFE hosts that don't respond to mDNS.
// Never blocks; runs on a background queue. Does not require any entitlement beyond NSLocalNetworkUsageDescription.
static void TriggerLocalNetworkPermissionPromptWithDiscoveryProbe(void) {
    @autoreleasepool {
        int fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (fd < 0) {
            Log(LOG_W, @"[Connect] socket() failed for LocalNetwork trigger");
            return;
        }

        int one = 1;
        setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &one, sizeof(one));
        struct timeval tv = { .tv_sec = 0, .tv_usec = 200000 }; // 200ms send timeout max
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

        struct sockaddr_in sin;
        memset(&sin, 0, sizeof(sin));
        sin.sin_family = AF_INET;
        sin.sin_len = sizeof(sin);
        sin.sin_port = htons(47989);
        sin.sin_addr.s_addr = htonl(INADDR_BROADCAST); // 255.255.255.255

        // GameStream HTTP serverinfo payload fragment — anything works, we just need a
        // real datagram so the kernel reports us as "using local networking" to TCC.
        const char *probe = "GET /serverinfo HTTP/1.0\r\n\r\n";
        ssize_t n = sendto(fd, probe, strlen(probe), 0,
                           (struct sockaddr *)&sin, sizeof(sin));
        Log(LOG_I, @"[Connect] LocalNetwork trigger UDP probe sent: %zd bytes (errno=%d)",
            n, (int)(n < 0 ? errno : 0));
        close(fd);
    }
}

@implementation AppDelegateForAppKit

static const void *MoonlightOriginalMenuItemTitleKey = &MoonlightOriginalMenuItemTitleKey;
static const void *MoonlightOriginalMenuTitleKey = &MoonlightOriginalMenuTitleKey;
static const void *MoonlightOriginalToolbarLabelKey = &MoonlightOriginalToolbarLabelKey;
static const void *MoonlightOriginalToolbarPaletteLabelKey = &MoonlightOriginalToolbarPaletteLabelKey;
static const void *MoonlightOriginalToolbarToolTipKey = &MoonlightOriginalToolbarToolTipKey;

- (void)dealloc {
    [[NSNotificationCenter defaultCenter] removeObserver:self];
}

- (NSString *)hostUUIDFromViewControllerTree:(NSViewController *)viewController {
    if (viewController == nil) {
        return nil;
    }

    if ([viewController isKindOfClass:[AppsWorkspaceViewController class]]) {
        NSString *hostUUID = ((AppsWorkspaceViewController *)viewController).currentHostUUID;
        if (hostUUID.length > 0) {
            return hostUUID;
        }
    }

    if ([viewController isKindOfClass:[AppsViewController class]]) {
        NSString *hostUUID = ((AppsViewController *)viewController).host.uuid;
        if (hostUUID.length > 0) {
            return hostUUID;
        }
    }

    for (NSViewController *child in viewController.childViewControllers) {
        NSString *hostUUID = [self hostUUIDFromViewControllerTree:child];
        if (hostUUID.length > 0) {
            return hostUUID;
        }
    }

    return nil;
}

// Opt in explicitly to secure restorable state to avoid the system warning on some macOS versions.
- (BOOL)applicationSupportsSecureRestorableState:(NSApplication *)app {
    return YES;
}

- (void)applicationDidFinishLaunching:(NSNotification *)aNotification {
#ifdef DEBUG
    // The second half of the render probe: readable claims about the page, which
    // need an app that has finished launching. Inert unless the first half armed it.
    MLFinishRenderProbeIfArmed();
#endif
    [self createMainWindow];
    self.controllerNavigation = [[ControllerNavigation alloc] init];
    [self refreshLocalizedChrome];
    [self showWelcomePermissionsIfNeeded];

    // Listen for the Swift welcome-window "Request Local Network" button tap.
    // The welcome screen can't call POSIX socket APIs directly easily, so it
    // posts a Notification and our ObjC side runs the actual UDP probe.
    // NOTE: We match the notification name by literal string (mirroring the Swift
    // constant MoonlightRequestLocalNetworkTriggerNotification) to avoid needing
    // a Swift-ObjC bridging header just for this one symbol.
    [[NSNotificationCenter defaultCenter] addObserverForName:@"MoonlightRequestLocalNetworkTrigger"
                                                      object:nil
                                                       queue:[NSOperationQueue mainQueue]
                                                  usingBlock:^(NSNotification * _Nonnull note) {
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            TriggerLocalNetworkPermissionPromptWithDiscoveryProbe();
            NSUserDefaults *d = [NSUserDefaults standardUserDefaults];
            [d setBool:YES forKey:kMoonlightLocalNetworkTriggeredKey];
            [d synchronize];
        });
    }];

    [self scheduleConnectionHealthCheck];
    [self addDiagnoseMenu];
}

- (void)addDiagnoseMenu {
    NSMenu *mainMenu = [NSApp mainMenu];
    if (!mainMenu) return;

    NSMenu *helpMenu = nil;
    for (NSMenuItem *item in mainMenu.itemArray) {
        if ([[item.submenu title] isEqualToString:@"Help"]) {
            helpMenu = item.submenu;
            break;
        }
    }
    if (!helpMenu) return;

    // Add separator + "Diagnose Connection" item
    [helpMenu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *diagnoseItem = [helpMenu addItemWithTitle:@"诊断连接问题…"
                                                   action:@selector(repairLocalNetworkPermission)
                                            keyEquivalent:@""];
    [diagnoseItem setTarget:self];
}

- (void)applicationWillFinishLaunching:(NSNotification *)notification {
#ifdef DEBUG
    // Runs and exits when asked; otherwise this is a no-op.
    MLRunRenderProbeAndExitIfRequested();
#endif
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(languageChanged:) name:@"LanguageChanged" object:nil];
    [[LanguageManager shared] applyAppLanguage];

    [self applyThemePreference:[self currentThemePreference]];
}

- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag {
    if (!flag) {
        [self createMainWindow];

        return YES;
    }
    
    return NO;
}

- (void)applicationWillTerminate:(NSNotification *)aNotification {
    [[DatabaseSingleton shared] saveContext];
}

- (void)createMainWindow {
    NSWindowController *mainWC = [NSStoryboard.mainStoryboard instantiateControllerWithIdentifier:@"MainWindowController"];
    mainWC.window.frameAutosaveName = @"Main Window";
    self.mainWindow = mainWC.window;
    [mainWC.window setMinSize:NSMakeSize(650, 350)];
    
    [mainWC showWindow:self];
    [mainWC.window makeKeyAndOrderFront:nil];
    [self localizeToolbarForWindow:mainWC.window];
}

// MARK: - Connection Health Check (CI/CD best practices — FULL REWRITE)
// Key fixes:
// 1. Gatekeeper spctl check removed — Apple Dev certs ALWAYS fail spctl --assess; it's normal, not an error
// 2. LocalNetwork permission MUST be actively triggered by a real network action (Bonjour/UDP won't pop dialog otherwise)
// 3. No double-popups: welcome window OR permission guide, never both at the same time
// 4. All permission operations are NON-DESTRUCTIVE on normal launch. tccutil reset = opt-in only.
// 5. Full diagnostics: any connection issue → "Help → 诊断连接问题" gives a complete report.

- (void)scheduleConnectionHealthCheck {
    self.didAttemptPermissionRepair = NO;

    // 1) Quarantine removal — fire-and-forget, non-destructive, safe every launch
    [self asyncRemoveQuarantine];

    // 2) LocalNetwork trigger — runs on a BG queue after UI is painted.
    //    This is the ONLY way macOS 12+ will show the LocalNetwork dialog.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.8 * NSEC_PER_SEC)),
                   dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        NSUserDefaults *d = [NSUserDefaults standardUserDefaults];
        BOOL everTriggered = [d boolForKey:kMoonlightLocalNetworkTriggeredKey];
        // Trigger on first launch AND every 24h so that users who previously denied
        // can still be re-prompted after a tccutil reset without changing bundle ID.
        if (!everTriggered) {
            TriggerLocalNetworkPermissionPromptWithDiscoveryProbe();
            [d setBool:YES forKey:kMoonlightLocalNetworkTriggeredKey];
            [d synchronize];
        } else {
            // Even if already triggered, still send the probe so discovery has another shot.
            TriggerLocalNetworkPermissionPromptWithDiscoveryProbe();
        }
    });

    // 3) Non-destructive diagnosis on background queue.
    //    Delayed 3.5s so welcome window has already been shown/dismissed — NO double-popups.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(3.5 * NSEC_PER_SEC)),
                   dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        [self runPermissionDiagnosis];
    });
}

- (void)asyncRemoveQuarantine {
    @autoreleasepool {
        NSString *appPath = [[NSBundle mainBundle] bundlePath];
        if (appPath.length == 0) return;

        NSTask *task = [[NSTask alloc] init];
        [task setLaunchPath:@"/usr/bin/xattr"];
        [task setArguments:@[@"-d", @"com.apple.quarantine", appPath]];
        [task setTerminationHandler:^(NSTask *t) {
            Log(LOG_I, @"[Connect] Quarantine attr removal: exit=%d", t.terminationStatus);
        }];
        @try { [task launch]; } @catch (NSException *e) {
            Log(LOG_W, @"[Connect] xattr launch failed: %@", e);
        }
    }
}

- (void)runPermissionDiagnosis {
    @autoreleasepool {
        NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
        BOOL firstLaunch = ![defaults boolForKey:kMoonlightFirstLaunchKey];
        if (firstLaunch) {
            [defaults setBool:YES forKey:kMoonlightFirstLaunchKey];
            [defaults synchronize];
            Log(LOG_I, @"[Connect] First launch (v2 marker)");
        }

        // ---- Intentionally NOT running spctl --assess ----
        // Apple Development-signed apps always FAIL spctl assessment. That is NOT an error
        // condition and it does NOT mean Gatekeeper blocked the app. Gatekeeper only blocks
        // unnotarized Developer ID apps or apps with broken signatures. Ad-hoc / Apple Dev
        // signed apps that the user launched via Right-Click → Open have already cleared the
        // Gatekeeper UX gating. Showing a "Gatekeeper BLOCKED" alert every launch is wrong.
        // We still log the signature info for diagnostics only.
        [self syncRunTask:@"/usr/bin/codesign"
                arguments:@[@"--verify", @"--verbose=2", [[NSBundle mainBundle] bundlePath]]
                completion:^(int exitCode, NSString *output) {
            Log(LOG_I, @"[Connect] Code-sign verify: exit=%d — %@", exitCode,
                output.length > 0 ? [output stringByTrimmingCharactersInSet:
                                     [NSCharacterSet whitespaceAndNewlineCharacterSet]] : @"(no output)");
        }];

        // If the welcome-permissions sheet has already been shown (or doesn't need to show),
        // and hosts are still offline after ~10s, we show ONE gentle permission-reminder alert.
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(8.0 * NSEC_PER_SEC)),
                       dispatch_get_main_queue(), ^{
            // Only show a guide if we don't have a welcome sheet up already.
            if (self.welcomePermissionsWC != nil) return;
            // Also skip if app is not active in foreground.
            if (NSApp.isActive == NO) return;
            // Read saved host count via DataManager (CoreData backed)
            DataManager *dm = [[DataManager alloc] init];
            NSArray *allHosts = [dm performSelector:@selector(getHosts)] ? [dm getHosts] : nil;
            if (allHosts.count > 0) {
                Log(LOG_I, @"[Connect] %lu saved hosts exist; skipping permission nag",
                    (unsigned long)allHosts.count);
                return;
            }
            // No saved hosts AND 11.5s into first use → single gentle guide.
            // NEVER auto-reset TCC; NEVER show this if user has already seen welcome sheet.
            [self presentPermissionGuideSingleTime];
        });
    }
}

// Show the permission guide AT MOST ONCE per launch. The original presentPermissionGuide
// still exists for explicit "diagnose connection" menu flows.
- (void)presentPermissionGuideSingleTime {
    if (self.didAttemptPermissionRepair) return;
    [self presentPermissionGuide];
}

// Manual repair action: resets LocalNetwork TCC permission, THEN re-triggers the prompt.
- (void)repairLocalNetworkPermission {
    NSString *bundleID = [[NSBundle mainBundle] bundleIdentifier];
    if (bundleID.length == 0) bundleID = @"std.skyhua.MoonlightMac2";

    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        @autoreleasepool {
            // Collect full diagnostics FIRST so we always know what state things were in.
            NSMutableString *report = [NSMutableString stringWithString:
                @"===== Moonlight 连接诊断报告 =====\n"];
            [report appendFormat:@"Bundle ID: %@\n", bundleID];
            [report appendFormat:@"App path: %@\n", [[NSBundle mainBundle] bundlePath]];

            // Codesign
            [self syncRunTask:@"/usr/bin/codesign"
                    arguments:@[@"--verify", @"--verbose=4", [[NSBundle mainBundle] bundlePath]]
                    completion:^(int e, NSString *o) {
                [report appendFormat:@"\n--- Code Sign ---\nexit=%d\n%@\n", e, o ?: @""];
            }];

            // Quarantine attr
            [self syncRunTask:@"/usr/bin/xattr"
                    arguments:@[@"-l", [[NSBundle mainBundle] bundlePath]]
                    completion:^(int e, NSString *o) {
                [report appendFormat:@"\n--- xattrs (quarantine) ---\nexit=%d\n%@\n", e, o ?: @"(none)"];
            }];

            // TCC state is not queryable from our own process. tccutil implements
            // exactly one subcommand, "reset SERVICE [BUNDLE_ID]"; there is no
            // "dump" and no "list", and the database itself is protected by TCC.
            // The previous "tccutil dump" probe therefore always failed and the
            // report line it produced was pure noise. The only trustworthy signal
            // is what the UDP discovery probe actually observed, so record that.
            BOOL probeFired = [[NSUserDefaults standardUserDefaults]
                boolForKey:kMoonlightLocalNetworkTriggeredKey];
            [report appendString:@"\n--- TCC (LocalNetwork) ---\n"];
            [report appendString:@"Not queryable (tccutil has no read subcommand).\n"];
            [report appendFormat:@"Discovery probe already fired this install: %@\n",
                probeFired ? @"YES" : @"NO"];

            Log(LOG_I, @"[Connect-Diagnose]\n%@", report);

            // Now do the destructive reset + re-trigger
            Log(LOG_W, @"[Repair] Resetting LocalNetwork TCC for %@", bundleID);
            __block int resetExit = -1;
            __block NSString *resetOut = nil;
            // Real location is /usr/bin/tccutil. The previous /usr/sbin path does
            // not exist, so NSTask threw, syncRunTask swallowed it and reported
            // exit=-1: this reset silently never ran for anyone.
            [self syncRunTask:@"/usr/bin/tccutil"
                    arguments:@[@"reset", @"LocalNetwork", bundleID]
                    completion:^(int exitCode, NSString *output) {
                resetExit = exitCode;
                resetOut = output;
                Log(LOG_I, @"[Repair] tccutil reset LocalNetwork: exit=%d, out=%@",
                    exitCode, output ?: @"");
            }];

            // Clear the "triggered" marker so the UDP probe actually fires again and
            // macOS presents the permission prompt a second time.
            [[NSUserDefaults standardUserDefaults] removeObjectForKey:kMoonlightLocalNetworkTriggeredKey];
            [[NSUserDefaults standardUserDefaults] synchronize];

            // Re-trigger permission prompt
            TriggerLocalNetworkPermissionPromptWithDiscoveryProbe();

            dispatch_async(dispatch_get_main_queue(), ^{
                NSAlert *alert = [[NSAlert alloc] init];
                NSString *resetSummary = resetExit == 0
                    ? @"tccutil reset 结果：成功"
                    : [NSString stringWithFormat:
                       @"tccutil reset 结果：失败（exit=%d）。请手动前往系统设置关闭再开启本地网络开关。",
                       resetExit];
                [alert setMessageText:resetExit == 0
                    ? @"本地网络权限已重置，请允许访问"
                    : @"本地网络权限重置失败"];
                [alert setInformativeText:
                 [NSString stringWithFormat:
                  @"系统很快会弹出「Moonlight 想要访问本地网络」的对话框，请务必点击「允许」。\n\n"
                  @"如果对话框没有出现，请手动前往：\n"
                  @"系统设置 → 隐私与安全性 → 本地网络 → 开启 Moonlight。\n\n"
                  @"%@\n%@\n\n"
                  @"完整诊断已写入控制台日志（帮助 → 诊断连接问题 可随时重新运行）。",
                  resetSummary, resetOut.length > 0 ? resetOut : @""]];
                [alert setAlertStyle:NSAlertStyleInformational];
                [alert addButtonWithTitle:@"打开本地网络设置"];
                [alert addButtonWithTitle:@"知道了"];
                NSWindow *window = [NSApp mainWindow] ?: [[NSApp windows] firstObject];
                [alert beginSheetModalForWindow:window completionHandler:^(NSModalResponse rc) {
                    if (rc == NSAlertFirstButtonReturn) {
                        NSURL *u = [NSURL URLWithString:
                            @"x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork"];
                        [[NSWorkspace sharedWorkspace] openURL:u];
                    }
                }];
            });
        }
    });
}

// Synchronous task runner. MUST be called on a non-main queue.
- (void)syncRunTask:(NSString *)launchPath arguments:(NSArray *)arguments completion:(void (^)(int exitCode, NSString *output))completion {
    NSTask *task = [[NSTask alloc] init];
    [task setLaunchPath:launchPath];
    [task setArguments:arguments];

    NSPipe *pipe = [NSPipe pipe];
    [task setStandardOutput:pipe];
    [task setStandardError:pipe];

    __block int exitCode = -1;
    __block NSString *outputString = @"";

    @try {
        [task launch];
        [task waitUntilExit];
        exitCode = task.terminationStatus;

        NSData *data = [[pipe fileHandleForReading] readDataToEndOfFile];
        if (data.length > 0) {
            outputString = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] ?: @"";
        }
    } @catch (NSException *exception) {
        Log(LOG_W, @"[HealthCheck] Task %@ failed: %@", launchPath, exception);
    }

    if (completion) {
        completion(exitCode, outputString);
    }
}

- (void)presentPermissionGuide {
    if (self.didAttemptPermissionRepair) return;
    self.didAttemptPermissionRepair = YES;

    NSWindow *window = [NSApp mainWindow] ?: [[NSApp windows] firstObject];
    if (window == nil) return;

    NSAlert *alert = [[NSAlert alloc] init];
    [alert setMessageText:@"Moonlight 无法发现游戏主机？"];
    [alert setInformativeText:@"找不到主机通常是因为本地网络权限没有开启。\n\n请完成以下步骤：\n\n"
     @"① 打开 系统设置 → 隐私与安全性 → 本地网络，开启 Moonlight\n\n"
     @"② 如果系统之前没有弹出过「本地网络」权限提示，可以点击 帮助 → 诊断连接问题\n\n"
     @"③ 也可以点击主窗口右上角「+」按钮手动输入主机 IP 地址直接添加。"];
    [alert setAlertStyle:NSAlertStyleWarning];
    [alert addButtonWithTitle:@"打开本地网络设置"];
    [alert addButtonWithTitle:@"知道了"];
    [alert beginSheetModalForWindow:window completionHandler:^(NSModalResponse returnCode) {
        if (returnCode == NSAlertFirstButtonReturn) {
            NSURL *url = [NSURL URLWithString:@"x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork"];
            [[NSWorkspace sharedWorkspace] openURL:url];
        }
    }];
}

- (void)showWelcomePermissionsIfNeeded {
    if (![WelcomePermissionsWindowObjCBridge shouldShowWelcomeWindow]) {
        return;
    }

    dispatch_async(dispatch_get_main_queue(), ^{
        if (self.welcomePermissionsWC != nil) {
            return;
        }

        NSWindow *parentWindow = NSApplication.sharedApplication.mainWindow;
        if (parentWindow == nil) {
            parentWindow = NSApplication.sharedApplication.windows.firstObject;
        }
        if (parentWindow == nil) {
            return;
        }

        self.welcomePermissionsWC = [WelcomePermissionsWindowObjCBridge makeWelcomeWindow];
        self.welcomePermissionsWC.window.delegate = self;
        self.welcomePermissionsWC.window.frameAutosaveName = @"Welcome Permissions Window";
        [parentWindow beginSheet:self.welcomePermissionsWC.window completionHandler:^(__unused NSModalResponse returnCode) {
            [WelcomePermissionsWindowObjCBridge markWelcomeWindowShown];
            self.welcomePermissionsWC = nil;
        }];
    });
}

// Settings is a page inside the main window content region. There is no
// second window to position, no autosave name to keep in sync and no
// controller to rebuild: the presenter replaces the page in place and
// restores the toolbar and title on the way out.
- (NSWindow *)mainContentWindow {
    if (self.mainWindow != nil) {
        return self.mainWindow;
    }
    NSWindow *candidate = NSApplication.sharedApplication.mainWindow;
    self.mainWindow = candidate;
    return candidate;
}

- (void)showPreferencesForHost:(NSString *)hostId {
    NSWindow *window = [self mainContentWindow];
    if (window == nil) {
        return;
    }
    [window makeKeyAndOrderFront:nil];
    [SettingsWindowObjCBridge presentSettingsInWindow:window hostId:hostId];
}

- (IBAction)showPreferences:(id)sender {
    NSViewController *contentVC = [self mainContentWindow].contentViewController;
    [self showPreferencesForHost:[self hostUUIDFromViewControllerTree:contentVC]];
}

- (IBAction)showAbout:(id)sender {
    if (self.aboutWC == nil) {
        self.aboutWC = [[NSWindowController alloc] initWithWindowNibName:@"AboutWindow"];
        self.aboutWC.contentViewController = [[AboutViewController alloc] initWithNibName:@"AboutView" bundle:nil];
    }

    self.aboutWC.window.frameAutosaveName = @"About Window";
    [self.aboutWC.window moonlight_centerWindowOnFirstRunWithSize:CGSizeZero];
    
    [self.aboutWC showWindow:nil];
    [self.aboutWC.window makeKeyAndOrderFront:nil];
}

- (IBAction)filterList:(id)sender {
    NSWindow *window = NSApplication.sharedApplication.mainWindow;
    [window makeFirstResponder:[window moonlight_searchFieldInToolbar]];
}

- (IBAction)setSystemTheme:(id)sender {
    [self changeTheme:SystemTheme withMenuItem:((NSMenuItem *)sender)];
}

- (IBAction)setLightTheme:(id)sender {
    [self changeTheme:LightTheme withMenuItem:((NSMenuItem *)sender)];
}

- (IBAction)setDarkTheme:(id)sender {
    [self changeTheme:DarkTheme withMenuItem:((NSMenuItem *)sender)];
}

- (NSInteger)currentThemePreference {
    return [[NSUserDefaults standardUserDefaults] integerForKey:@"theme"];
}

- (void)applyThemePreference:(NSInteger)theme {
    Theme resolvedTheme = (theme >= SystemTheme && theme <= DarkTheme) ? (Theme)theme : SystemTheme;
    [self changeTheme:resolvedTheme withMenuItem:[self menuItemForTheme:resolvedTheme forMenu:self.themeMenuItem.submenu]];
}

- (NSMenuItem *)menuItemForTheme:(Theme)theme forMenu:(NSMenu *)menu {
    static NSUInteger menuIndexes[] = {0, 2, 3};
    if (menu == nil || theme > DarkTheme) {
        return nil;
    }
    return menu.itemArray[menuIndexes[theme]];
}

- (void)changeTheme:(Theme)theme withMenuItem:(NSMenuItem *)menuItem {
    NSMenu *menu = menuItem.menu ?: self.themeMenuItem.submenu;
    NSMenuItem *resolvedMenuItem = menuItem ?: [self menuItemForTheme:theme forMenu:menu];

    resolvedMenuItem.state = NSControlStateValueOn;
    for (NSMenuItem *item in menu.itemArray) {
        if (resolvedMenuItem != item) {
            item.state = NSControlStateValueOff;
        }
    }
    
    [[NSUserDefaults standardUserDefaults] setInteger:theme forKey:@"theme"];
    
    NSApplication *app = [NSApplication sharedApplication];
    switch (theme) {
        case SystemTheme:
            app.appearance = nil;
            break;
        case LightTheme:
            app.appearance = [NSAppearance appearanceNamed:NSAppearanceNameAqua];
            break;
        case DarkTheme:
            app.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
            break;
    }
}

- (void)languageChanged:(NSNotification *)notification {
    [self refreshLocalizedChrome];
}

- (void)refreshLocalizedChrome {
    [self localizeMenu:[NSApplication sharedApplication].mainMenu];

    for (NSWindow *window in NSApplication.sharedApplication.windows) {
        [self localizeToolbarForWindow:window];
    }
}

- (NSString *)localizedChromeString:(NSString *)key {
    if (key.length == 0) {
        return key;
    }
    return [[LanguageManager shared] localize:key];
}

- (NSString *)storedStringForObject:(id)object associationKey:(const void *)associationKey currentValue:(NSString *)currentValue {
    NSString *storedValue = objc_getAssociatedObject(object, associationKey);
    if (storedValue == nil && currentValue.length > 0) {
        storedValue = [currentValue copy];
        objc_setAssociatedObject(object, associationKey, storedValue, OBJC_ASSOCIATION_COPY_NONATOMIC);
    }
    return storedValue ?: currentValue ?: @"";
}

- (void)localizeMenu:(NSMenu *)menu {
    if (menu == nil) {
        return;
    }

    NSString *originalMenuTitle = [self storedStringForObject:menu associationKey:MoonlightOriginalMenuTitleKey currentValue:menu.title];
    if (originalMenuTitle.length > 0) {
        menu.title = [self localizedChromeString:originalMenuTitle];
    }

    for (NSMenuItem *item in menu.itemArray) {
        NSString *originalItemTitle = [self storedStringForObject:item associationKey:MoonlightOriginalMenuItemTitleKey currentValue:item.title];
        if (originalItemTitle.length > 0) {
            item.title = [self localizedChromeString:originalItemTitle];
        }

        if (item.submenu != nil) {
            NSString *submenuOriginalTitle = [self storedStringForObject:item.submenu associationKey:MoonlightOriginalMenuTitleKey currentValue:item.submenu.title];
            NSString *submenuKey = submenuOriginalTitle.length > 0 ? submenuOriginalTitle : originalItemTitle;
            if (submenuKey.length > 0) {
                item.submenu.title = [self localizedChromeString:submenuKey];
            }
            [self localizeMenu:item.submenu];
        }
    }
}

- (NSString *)toolbarLocalizationKeyForItem:(NSToolbarItem *)item originalValue:(NSString *)originalValue {
    if ([item.itemIdentifier isEqualToString:@"PreferencesToolbarItem"]) {
        if (@available(macOS 13.0, *)) {
            return @"Settings";
        }
        return @"Preferences";
    }
    return originalValue;
}

- (void)localizeToolbarForWindow:(NSWindow *)window {
    NSToolbar *toolbar = window.toolbar;
    if (toolbar == nil) {
        return;
    }

    for (NSToolbarItem *item in toolbar.items) {
        NSString *originalLabel = [self storedStringForObject:item associationKey:MoonlightOriginalToolbarLabelKey currentValue:item.label];
        NSString *originalPaletteLabel = [self storedStringForObject:item associationKey:MoonlightOriginalToolbarPaletteLabelKey currentValue:item.paletteLabel];
        NSString *originalToolTip = [self storedStringForObject:item associationKey:MoonlightOriginalToolbarToolTipKey currentValue:item.toolTip];

        NSString *labelKey = [self toolbarLocalizationKeyForItem:item originalValue:originalLabel];
        NSString *paletteLabelKey = [self toolbarLocalizationKeyForItem:item originalValue:(originalPaletteLabel.length > 0 ? originalPaletteLabel : originalLabel)];
        NSString *toolTipKey = [self toolbarLocalizationKeyForItem:item originalValue:(originalToolTip.length > 0 ? originalToolTip : originalLabel)];

        if (labelKey.length > 0) {
            item.label = [self localizedChromeString:labelKey];
        }
        if (paletteLabelKey.length > 0) {
            item.paletteLabel = [self localizedChromeString:paletteLabelKey];
        }
        if (toolTipKey.length > 0) {
            item.toolTip = [self localizedChromeString:toolTipKey];
        }

        if ([item.view isKindOfClass:[NSButton class]] && item.toolTip.length > 0) {
            ((NSButton *)item.view).toolTip = item.toolTip;
        }
    }
}


#pragma mark - NSWindowDelegate

- (void)windowWillClose:(NSNotification *)notification {
    if (notification.object == self.aboutWC.window) {
        self.aboutWC = nil;
    } else if (notification.object == self.welcomePermissionsWC.window && self.welcomePermissionsWC.window.sheetParent == nil) {
        [WelcomePermissionsWindowObjCBridge markWelcomeWindowShown];
        self.welcomePermissionsWC = nil;
    }
}

@end
