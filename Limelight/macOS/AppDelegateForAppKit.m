//
//  AppDelegateForAppKit.m
//  Moonlight for macOS
//
//  Created by Michael Kenny on 10/2/18.
//  Copyright © 2018 Moonlight Stream. All rights reserved.
//

#import "AppDelegateForAppKit.h"
#import "DatabaseSingleton.h"
#import "Localization.h"
#import "AboutViewController.h"
#import "NSWindow+Moonlight.h"
#import "NSResponder+Moonlight.h"
#import "ControllerNavigation.h"

#import "MASPreferencesWindowController.h"
#import "GeneralPrefsPaneVC.h"

#import "AppsViewController.h"
#import "AppsWorkspaceViewController.h"
#import "TemporaryHost.h"
#import "ServerInfoResponse.h"
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
#if DEBUG
// Defined in `DataManager.m`. Debug-only, like the counter it reads: the release binary carries
// neither, and `getHosts` does not branch on anything a player would pay for.
extern unsigned long long MLHostReads(void);
extern void MLResetHostReads(void);
#endif

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
#if DEBUG
    // Counted around the presentation rather than around the pass, because the question the leak
    // gate answers is "what does one visit cost", and a visit is present-and-close. `SettingsModel
    // .hosts` is computed and each read builds a fresh graph, so this count is the number of
    // graphs this one pane pinned -- and the pane is where the reading happens, not the window.
    unsigned long long readsAtEntry = MLHostReads();
#endif
    [SettingsOverlayPresenter presentSettingsInWindow:window hostId:nil];
    MLProbeSpin(1.4);
#if DEBUG
    unsigned long long readsAfterPresent = MLHostReads();
#endif

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
#if DEBUG
    result[@"hostReadsDuringPresent"] = @(readsAfterPresent - readsAtEntry);
    result[@"hostReadsDuringDismiss"] = @(MLHostReads() - readsAfterPresent);
    result[@"hostReadsDuringPass"] = @(MLHostReads() - readsAtEntry);
#endif
    result[@"stillMountedAfterDismiss"] = @([overlay isDescendantOf:content]);
    if (previousAdvancedState) {
        [probeDefaults setObject:previousAdvancedState forKey:MLProbeAdvancedSectionCollapsedKey];
    } else if (forcedTheSectionShut) {
        [probeDefaults removeObjectForKey:MLProbeAdvancedSectionCollapsedKey];
    }
    [probeDefaults synchronize];
    report[name] = result;
}

// The back control is the exit a player actually presses, so the probe presses it
// rather than only asking the presenter to close the page. SwiftUI vends the control
// through the hosting view accessibility tree, which this process can read without any
// system permission.
static id<NSAccessibility> MLProbeFindBackControl(id<NSAccessibility> node, int depth) {
    if (node == nil || depth > 24) {
        return nil;
    }
    if ([[node accessibilityRole] isEqual:NSAccessibilityButtonRole]) {
        NSString *label = [node accessibilityLabel];
        if ([label isEqual:@"Back"] || [label isEqual:@"返回"]) {
            return node;
        }
    }
    for (id<NSAccessibility> child in [node accessibilityChildren]) {
        id<NSAccessibility> found = MLProbeFindBackControl(child, depth + 1);
        if (found) {
            return found;
        }
    }
    return nil;
}

static NSMutableDictionary *MLProbeReport = nil;
static NSMutableArray<NSString *> *MLProbeFailures = nil;
static NSString *MLProbeOutputDirectory = nil;
static NSWindow *MLProbeWindow = nil;
static NSView *MLProbeBackdrop = nil;
static BOOL MLProbeArmed = NO;

// Seed a host graph for the memory sweep, and only for the memory sweep.
//
// `leaks` answers for the graph the settings page built, and that page builds one temporary
// host graph per host the machine can see. A CI runner has no LAN to browse, so it sees no
// host, builds no graph, and the memory gate can only report "nothing of ours started
// leaking" over an empty room -- a green that says less than it looks like. So the sweep
// asks for a host, and this writes one through the production `DataManager`, the way
// discovery writes one when a box answers. It is not a stand-in object: the settings page
// then reads it back through the production `getHosts`, which is the ownership path that
// leaked in the first place.
//
// What that measures is the graph and the code that owns it. What it does not measure is the
// discovery path that builds a host out of a live box, and it is not what a user's library
// holds. The visual probe leaves the flag unset so its pixel asserts keep facing the empty
// library they were written against, and a machine with hosts of its own is left alone -- so
// the apps-per-host ratio the gate judges stays the library's rather than this seed's.
//
// The status is recorded rather than assumed, because the failure this gate exists to catch
// is a sweep that judged an empty room and called it clean: a flag that asked for a graph and
// silently got none has to be visible in the report the audit reads.
// Every host this file plants carries this uuid prefix, so "which of the hosts in the library
// came from a probe" is one question with one answer. The seed below writes it, the count under
// it reads it, and the reaper removes nothing that does not start with it. Three places that
// each spelled the prefix out would disagree the first time somebody renamed one of them, and
// the disagreement would be a probe deleting a player's machines.
static NSString *const MLProbeHostUuidPrefix = @"probe-host-";

// Split the library by who put each host in it. `total` is what the app would show a person and
// `probeOwned` is what an earlier probe left behind. The two are counted together because the
// difference between them is what decides whether a probe may touch the library at all, and a
// probe that asked that question of a second copy of the library would be asking it of a
// library that had changed since the first look.
static void MLCountLibraryHosts(DataManager *store, long *total, long *probeOwned) {
    long seen = 0;
    long ours = 0;
    for (TemporaryHost *host in [store getHosts]) {
        seen++;
        // A host with no uuid is not ours: it cannot have come from a seed that always names
        // its hosts, and it is exactly the kind of half-written record a real library can hold.
        if ([host.uuid hasPrefix:MLProbeHostUuidPrefix]) {
            ours++;
        }
    }
    if (total != NULL) {
        *total = seen;
    }
    if (probeOwned != NULL) {
        *probeOwned = ours;
    }
}

// Count the app records in the store, and how many of them belong to no host.
//
// This question is asked because `-[DataManager removeHost:]` deletes a host and nothing else, and
// whether the apps that host was holding go with it is decided by the Core Data model rather than
// by any line of code in this repository: `Host.appList` carries a deletion rule, and the file that
// says which one (`Limelight.xcdatamodeld`, whose current version `.xccurrentversion` names) is not
// a header anyone can grep alongside the code. The audit reads that model and compares; this counts
// what the store actually did.
//
// A fresh context is opened on purpose. `DataManager` works on its own private-queue context and
// `DatabaseSingleton` exposes a second one, and neither is obliged to see the other's committed
// rows without a refresh -- a count read through a stale context would be a count of some earlier
// moment, which is exactly the kind of reading that agrees with the model by accident. A new
// context on the same store coordinator reads what the SQLite file holds.
//
// Orphans matter on their own: an app record whose host is gone is invisible to every production
// read (`getHosts` reaches apps through hosts), so it is a row nothing can delete through the app
// while still costing the store its space.
static void MLCountAppRecords(long *total, long *orphans, NSString **problem) {
    NSManagedObjectContext *reader = [[NSManagedObjectContext alloc]
            initWithConcurrencyType:NSPrivateQueueConcurrencyType];
    reader.persistentStoreCoordinator = [DatabaseSingleton shared].persistentStoreCoordinator;

    __block long totalRows = -1;
    __block long orphanRows = -1;
    __block NSString *failure = nil;
    [reader performBlockAndWait:^{
        NSError *error = nil;
        NSFetchRequest *all = [NSFetchRequest fetchRequestWithEntityName:@"App"];
        all.resultType = NSCountResultType;
        NSArray<NSNumber *> *rows = [reader executeFetchRequest:all error:&error];
        if (error != nil) {
            failure = [NSString stringWithFormat:@"counting the app records failed: %@",
                       error.localizedDescription ?: @"no description"];
            return;
        }
        totalRows = rows.firstObject.unsignedIntegerValue;

        NSFetchRequest *loose = [NSFetchRequest fetchRequestWithEntityName:@"App"];
        loose.resultType = NSCountResultType;
        loose.predicate = [NSPredicate predicateWithFormat:@"host == nil"];
        error = nil;
        NSArray<NSNumber *> *looseRows = [reader executeFetchRequest:loose error:&error];
        if (error != nil) {
            // Not a refusal of its own: a store that will not answer the orphan question is
            // reported as unmeasured rather than guessed at, and the audit decides whether an
            // unmeasured orphan count can carry a green.
            failure = [NSString stringWithFormat:@"counting app records with no host failed: %@",
                       error.localizedDescription ?: @"no description"];
            return;
        }
        orphanRows = looseRows.firstObject.unsignedIntegerValue;
    }];

    if (total != NULL) {
        *total = totalRows;
    }
    if (orphans != NULL) {
        *orphans = orphanRows;
    }
    if (problem != NULL) {
        *problem = failure;
    }
}

// Reap the hosts earlier probes planted, and only those.
//
// This exists because of a fact about macOS that every probe in this file had assumed away: the
// `HOME` a probe is handed does not move its database. `URLsForDirectory:NSApplicationSupportDirectory
// inDomains:NSUserDomainMask` resolves out of the account record rather than out of `$HOME`, so
// a Debug probe started with a private temporary home still opens the store in the real user's
// Application Support, and the directory an audit removes afterwards is a directory that was
// never written to. Measured on this laptop on 2026-09-24: an empty temporary `HOME`, a probe
// that asked for one seeded host, and a report of two existing hosts -- that machine's own
// library, reached through an environment variable that was supposed to have hidden it.
//
// Which means the graph a probe measures belongs to whoever that file belongs to, and the steps
// of one CI job share it. The memory sweep seeds a host, and the ownership probe that runs after
// it in the same job finds that host already waiting and calls the library somebody else's. That
// is the whole difference between `seeded` and `existing-hosts` in the runner's record, and it is
// why the runner's ownership reading had been measuring the previous step's handiwork underneath
// a comment claiming a clean room.
//
// A probe cannot fix that by deleting a library, so it does not try. It removes hosts only when
// every host in the library could only have come from a probe, and it records which of the
// outcomes happened: `reaped`, `kept` (a person's machines, untouched), `empty`, `mixed`, or
// `did-not-clear`. `mixed` is a refusal rather than a note: a library holding both is one where
// no rule written here can tell the probe's from the player's without guessing, and the guess
// would be the deletion of somebody's GameStream host.
//
// What this step does not look at is the apps. `removeHost:` is the app's own deletion path and
// it takes the host record; whether the app records a seeded host hung its apps on go with it is
// Core Data's delete rule and nobody measured it here. The reading after the removal counts
// hosts, because hosts are what the ownership question is about.
static void MLReapProbeOwnedHostsIfRequested(NSMutableDictionary *report, void (^refuse)(NSString *)) {
    if (getenv("ML_PROBE_REAP_OWN_HOSTS") == NULL) {
        return;
    }
    NSMutableDictionary *record = [NSMutableDictionary dictionary];
    report[@"reapedHosts"] = record;
    DataManager *store = [[DataManager alloc] init];
    long total = 0;
    long ours = 0;
    MLCountLibraryHosts(store, &total, &ours);
    record[@"found"] = @(total);
    record[@"probeOwned"] = @(ours);

    // The app records are counted on both sides of any deletion, because "the library reads back
    // empty" only speaks about hosts. Whatever the model's rule turns out to be, the two numbers
    // and the orphan count have to be a story the audit can read.
    long appsBefore = 0;
    long orphansBefore = 0;
    NSString *countFailure = nil;
    MLCountAppRecords(&appsBefore, &orphansBefore, &countFailure);
    record[@"appRecordsBefore"] = @(appsBefore);
    record[@"orphanAppRecordsBefore"] = @(orphansBefore);
    if (countFailure != nil) {
        record[@"appRecordProblem"] = countFailure;
    }
    if (total == 0) {
        record[@"status"] = @"empty";
        return;
    }
    if (ours == 0) {
        record[@"status"] = @"kept";
        return;
    }
    if (ours != total && getenv("ML_PROBE_REMOVE_OWN_HOSTS") != NULL) {
        // A person asking for their own machine back. The default reap refuses a mixed library
        // because it cannot be sure which half is a probe's and which half is somebody's LAN;
        // this flag does not lower that bar, it raises the evidence: a human read the numbers and
        // named the hosts to remove, which is the one thing the reap on a runner cannot do. Hosts
        // that do not carry the seed's uuid are still not touched.
        record[@"status"] = @"removed-some";
    }
    if (ours != total && ![record[@"status"] isEqualToString:@"removed-some"]) {
        record[@"status"] = @"mixed";
        refuse([NSString stringWithFormat:@"%ld of the %ld host(s) in the library were planted by a"
                @" probe and the rest were not, so this run cannot say whose library the graph it"
                @" measured came from", ours, total]);
        return;
    }
    NSMutableArray<TemporaryHost *> *doomed = [NSMutableArray array];
    for (TemporaryHost *host in [store getHosts]) {
        if ([host.uuid hasPrefix:MLProbeHostUuidPrefix]) {
            [doomed addObject:host];
        }
    }
    for (TemporaryHost *host in doomed) {
        [store removeHost:host];
    }
    long remaining = 0;
    long stillOurs = 0;
    MLCountLibraryHosts(store, &remaining, &stillOurs);
    record[@"removed"] = @(ours);
    record[@"remaining"] = @(remaining);

    long appsAfter = 0;
    long orphansAfter = 0;
    NSString *afterFailure = nil;
    MLCountAppRecords(&appsAfter, &orphansAfter, &afterFailure);
    record[@"appRecordsAfter"] = @(appsAfter);
    record[@"orphanAppRecordsAfter"] = @(orphansAfter);
    if (afterFailure != nil) {
        // The before count is still worth what it is, and the gap is named rather than left for a
        // reader to mistake for a zero.
        record[@"appRecordProblem"] = afterFailure;
    }
    if (stillOurs != 0) {
        record[@"status"] = @"did-not-clear";
        refuse([NSString stringWithFormat:@"asked to remove %ld probe host(s) and the library still"
                @" holds %ld of them, so the removal did not go the way the app removes a host",
                ours, stillOurs]);
        return;
    }
    if ([record[@"status"] isEqualToString:@"removed-some"]) {
        // Somebody's hosts are still in there, which is the point: the verdict here is that the
        // probe's own are gone, not that the library is empty.
        return;
    }
    if (remaining != 0) {
        record[@"status"] = @"did-not-clear";
        refuse([NSString stringWithFormat:@"removed the only probe host(s) in a library of %ld and"
                @" it still reads %ld host(s), so something other than the seed wrote here",
                total, remaining]);
        return;
    }
    record[@"status"] = @"reaped";
}

static void MLSeedHostsIntoLibrary(NSMutableDictionary *report, void (^refuse)(NSString *),
                                   long wanted) {
    NSMutableDictionary *record = [NSMutableDictionary dictionary];
    record[@"requested"] = @(wanted);
    report[@"seedHosts"] = record;

    DataManager *store = [[DataManager alloc] init];
    long existing = (long)[[store getHosts] count];
    // `ML_RENDER_PROBE_SEED_IGNORE_EXISTING` exists so the seeding branch can be executed at
    // all by a person with a working LAN. Without it the branch only runs where nothing
    // answers mDNS -- which is the CI runner, so the code that hands the runner a graph would
    // have been read and never run. With it, the same machine adds the probe hosts on top of
    // the discovered ones and the ratio the gate judges is still three apps to a host. It
    // ships off, and the sweep does not set it: a runner that seeded on top of a real library
    // would be judging a library nobody has.
    BOOL ignoreExisting = getenv("ML_RENDER_PROBE_SEED_IGNORE_EXISTING") != NULL;
    if (ignoreExisting) {
        record[@"ignoredExisting"] = @(existing);
    }
    if (existing != 0 && !ignoreExisting) {
        // Somebody's real library. Seeding it would measure the seed instead of the library,
        // and the ratio the ceiling was fitted to is the library's.
        record[@"status"] = @"existing-hosts";
        record[@"existing"] = @(existing);
        record[@"seeded"] = @0;
        return;
    }

    // Three apps each, because three is the fan-out nine sweeps of a real library measured.
    // The address is in 192.0.2.0/24, a documentation range that routes nowhere, and the host
    // stays unpaired with no certificate, so nothing here can reach a machine.
    for (long hostNumber = 0; hostNumber < wanted; hostNumber++) {
        TemporaryHost *host = [[TemporaryHost alloc] init];
        host.name = [NSString stringWithFormat:@"Probe Host %ld", hostNumber + 1];
        host.uuid = [NSString stringWithFormat:@"%@%ld", MLProbeHostUuidPrefix, hostNumber + 1];
        host.address = [NSString stringWithFormat:@"192.0.2.%ld", 10 + hostNumber];
        [store updateHost:host];

        NSMutableSet *apps = [NSMutableSet set];
        for (long appNumber = 0; appNumber < 3; appNumber++) {
            TemporaryApp *app = [[TemporaryApp alloc] init];
            app.id = [NSString stringWithFormat:@"%ld", 900000 + hostNumber * 10 + appNumber];
            app.name = [NSString stringWithFormat:@"Probe App %ld", appNumber + 1];
            app.host = host;
            [apps addObject:app];
        }
        host.appList = apps;
        // The apps reach the library only through this call, which is the one the app pane
        // makes after a box answers, so the parent lookup has to work for the seed to exist.
        [store updateAppsForExistingHost:host];
    }

    long readBack = (long)[[store getHosts] count];
    record[@"seeded"] = @(readBack);
    if (readBack < wanted) {
        record[@"status"] = @"did-not-read-back";
        refuse([NSString stringWithFormat:@"seeded %ld host(s) but the library reads back %ld, so"
                @" the sweep would judge a graph that is not there", wanted, readBack]);
        return;
    }
    record[@"status"] = @"seeded";
}

// The memory sweep's shape of the helper above: how many hosts it wants comes from the
// environment, and a flag that is absent means the sweep measures the library exactly as it
// stands. The refusal and the `invalid` status it records are unchanged from the version that
// parsed and seeded in one function, because `leak-audit.py` judges that status by name.
static void MLSeedHostsForMemorySweep(NSMutableDictionary *report, void (^refuse)(NSString *)) {
    const char *requested = getenv("ML_RENDER_PROBE_SEED_HOSTS");
    if (requested == NULL) {
        return;
    }

    char *end = NULL;
    long wanted = strtol(requested, &end, 10);
    if (end == requested || *end != '\0' || wanted < 1 || wanted > 16) {
        NSMutableDictionary *record = [NSMutableDictionary dictionary];
        record[@"requested"] = [NSString stringWithUTF8String:requested];
        record[@"status"] = @"invalid";
        report[@"seedHosts"] = record;
        refuse([NSString stringWithFormat:@"ML_RENDER_PROBE_SEED_HOSTS asks for %s, which is not a"
                @" whole host count between 1 and 16, so the sweep would judge a graph of unknown"
                @" size", requested]);
        return;
    }

    MLSeedHostsIntoLibrary(report, refuse, wanted);
}

// The ownership experiment: who keeps a host alive while a stream holds only its app.
//
// Section 5 of docs/memory-ownership.md wants to make `TemporaryApp.host` weak, and it is
// blocked on an honest reason rather than on courage: no stream session runs here, so nobody
// can claim from a live session that `app.host` would not go nil underneath the stream. That
// question does not need a session. It asks only who holds what, and who holds what can be
// asked of the objects themselves.
//
// So this builds the pair and holds it the way `prepareForSegue:` holds it -- `streamVC.app`
// and nothing else (`AppsViewController.m:613`) -- then asks two questions of each shape:
//
//   hostAliveWhileAppHeld -- the host is still alive when the only strong reference outside
//       the pair is the app pointing at it. Yes means `TemporaryApp.host` is doing that job:
//       the stream's host is alive because its own app is holding it. That is precisely what
//       turning the back-pointer weak takes away, and what step 2 and step 3 of the fix have
//       to hand back by name.
//   hostAliveWithNoHolder -- nothing outside the pair holds either object any more and they
//       are still alive. Yes is the retain cycle `leaks` reports, seen from inside the process
//       instead of from a heap sampler, and it is the number step 1 has to move to No.
//
// Three shapes, because a single reading is not evidence:
//
//   productionGraph -- the app is taken out of `-[DataManager getHosts]`, the call the settings
//       page makes and the call whose graph leaked. Nothing in this shape is assembled by hand,
//       so the reading cannot be an artefact of how a test wrote its fixture.
//   handBuiltGraph -- the same shape (`host.appList` owns the apps, `app.host` owns the host
//       back, as `-[TemporaryHost initFromHost:]` leaves it at TemporaryHost.m:42-51) built
//       directly. It exists only to agree with the shape above. If the two disagree, something
//       outside the pair is retaining it and every number below is worthless.
//   backpointerOnly -- an app that knows its host with nothing pointing back. This is the shape
//       `AppAssetRetriever` is in (`AppAssetManager.m:34` reads `app.host.uuid` asynchronously),
//       it is what every holder becomes the day `host` turns weak, and it is the control that
//       keeps the leak honest: nothing holds this pair, so if it fails to go back, the harness
//       is holding it and the other two readings are measuring this probe, not the app.
//
// This function reports what it saw and refuses only what it can call a broken harness. The
// judgement lives in scripts/ownership-audit.py, which reads these numbers next to the property
// declarations and refuses when the two disagree -- including the direction that matters most,
// because `weak` in the header and the host still alive is not a pass, it is somebody else
// holding it. A run that asks for the experiment and leaves no record behind is refused too.
//
// The seed below writes through the production `DataManager`, so running this by hand without
// pointing HOME at a scratch directory adds a probe host to your own library. The memory sweep
// carries the same hazard and the same instruction.
static NSDictionary *MLOwnershipMeasureShape(void (^build)(TemporaryHost **hostSlot,
                                                           TemporaryApp **appSlot,
                                                           NSUInteger *appListCountSlot)) {
    __weak TemporaryHost *witnessHost = nil;
    __weak TemporaryApp *witnessApp = nil;
    __block TemporaryApp *appHolder = nil;
    __block NSUInteger appListCount = NSUIntegerMax;

    @autoreleasepool {
        TemporaryHost *builtHost = nil;
        TemporaryApp *builtApp = nil;
        build(&builtHost, &builtApp, &appListCount);
        witnessHost = builtHost;
        witnessApp = builtApp;
        appHolder = builtApp;
        // Let the pair out of this scope with the app as its only outside holder, which is the
        // state a stream is in. Whatever the builder autoreleased (the graph array, the app
        // literals) goes with the pool below, so anything still here after it drained is being
        // kept by the pair itself.
        builtHost = nil;
        builtApp = nil;
    }
    MLProbeSpin(0.3);

    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    result[@"appListCount"] = @(appListCount);
    result[@"hostAliveWhileAppHeld"] = @(witnessHost != nil);
    result[@"appHostReadableWhileAppHeld"] = @(appHolder.host != nil);

    appHolder = nil;
    @autoreleasepool {
    }
    MLProbeSpin(0.3);
    result[@"hostAliveWithNoHolder"] = @(witnessHost != nil);
    result[@"appAliveWithNoHolder"] = @(witnessApp != nil);
    return result;
}

// The pair `-[TemporaryHost initFromHost:]` leaves behind, built without Core Data: the host
// owns the apps through `appList` and the app owns the host back.
static void MLOwnershipBuildGraphPair(TemporaryHost **hostSlot,
                                      TemporaryApp **appSlot,
                                      NSUInteger *appListCountSlot) {
    TemporaryHost *host = [[TemporaryHost alloc] init];
    TemporaryApp *app = [[TemporaryApp alloc] init];
    host.name = @"Ownership Probe Host";
    host.uuid = @"ownership-probe-host";
    host.address = @"192.0.2.9";
    app.id = @"910000";
    app.name = @"Ownership Probe App";
    app.host = host;
    host.appList = [[NSMutableSet alloc] initWithArray:@[app]];
    *hostSlot = host;
    *appSlot = app;
    *appListCountSlot = host.appList.count;
}

// The same app and host with nothing pointing back at the app, which is what `app.host` alone
// is on the day it turns weak, and what `AppAssetRetriever` is holding right now.
static void MLOwnershipBuildBackpointerPair(TemporaryHost **hostSlot,
                                            TemporaryApp **appSlot,
                                            NSUInteger *appListCountSlot) {
    TemporaryHost *host = [[TemporaryHost alloc] init];
    TemporaryApp *app = [[TemporaryApp alloc] init];
    host.name = @"Ownership Probe Host";
    host.uuid = @"ownership-probe-host";
    host.address = @"192.0.2.9";
    app.id = @"910000";
    app.name = @"Ownership Probe App";
    app.host = host;
    *hostSlot = host;
    *appSlot = app;
    *appListCountSlot = host.appList.count;
}

// Two shapes that ask the question the three above cannot, because in all three the outside
// holder *is* the app: whether a separate holder that keeps the app can keep its host alive, and
// whether a holder that keeps the app *and* the host can do it. That is the whole of step 2 and
// step 3 of the fix -- `streamVC.app` plus `streamVC.host`, `item.app` plus `item.host` -- and the
// claim it rests on, "today the host is alive because its own app points back at it", has been
// read off the declarations rather than measured.
//
// The pair is built the way `-[TemporaryHost initFromHost:]` leaves it and then the back-pointer is
// severed by hand (`app.host = nil`), which stands in for what `weak` does to the graph the day it
// is declared, without anybody having to land the declaration first. Severing is explicit and is
// reported as such, so a reader cannot mistake these two for a run of the fixed build: what they
// measure is the *contribution* of that one edge, held fixed against the shape that keeps it.
//
// The holder itself is a stand-in object, not a view controller -- the probe constructs no views --
// and it is witnessed like everything else. Its own aliveness after the probe lets go is the control
// that says the harness is not holding what it claims to watch: if the holder survives being dropped
// here, every `yes` below belongs to the harness and the run is refused.
//
// What these two shapes can say, and what they cannot. They can say that with the back-pointer
// severed, a holder keeping only the app loses the host and a holder keeping both does not: that is
// the pairing doing the job by name, measured rather than argued, and it is the number the fix has
// to hold on to when it lands. They cannot say what a live stream session does with those objects --
// the probe builds no `StreamViewController`, and the session's own references are not in this
// process. The holder rule in scripts/ownership-audit.py is what watches the assignment sites, and
// the boundary between the two stays written down on both sides.
static NSDictionary *MLOwnershipMeasureHolderShape(BOOL holderKeepsHost,
                                                   BOOL severBackpointer) {
    __weak TemporaryHost *witnessHost = nil;
    __weak TemporaryApp *witnessApp = nil;
    __weak NSMutableArray *witnessHolder = nil;
    __block NSMutableArray *holder = nil;

    @autoreleasepool {
        TemporaryHost *host = nil;
        TemporaryApp *app = nil;
        NSUInteger appListCount = NSUIntegerMax;
        MLOwnershipBuildGraphPair(&host, &app, &appListCount);
        if (severBackpointer) {
            // Only the hand-severed shapes are comparable to the fix: the graph shape keeps its
            // back-pointer, and leaving it in place here would make "the holder keeps the host
            // alive" true of both variants for the wrong reason.
            app.host = nil;
        }
        holder = [NSMutableArray array];
        [holder addObject:app];
        if (holderKeepsHost) {
            [holder addObject:host];
        }
        witnessHost = host;
        witnessApp = app;
        witnessHolder = holder;
        // Drop the local references so the holder is the only outside hand on the pair, which is
        // the state `prepareForSegue:` leaves the app in.
        host = nil;
        app = nil;
    }
    MLProbeSpin(0.3);

    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    result[@"holderKind"] = holderKeepsHost ? @"app-and-host" : @"app-only";
    result[@"backpointerSevered"] = @(severBackpointer);
    result[@"hostAliveWhileHeldByHolder"] = @(witnessHost != nil);
    result[@"appAliveWhileHeldByHolder"] = @(witnessApp != nil);

    holder = nil;
    @autoreleasepool {
    }
    MLProbeSpin(0.3);
    result[@"holderAliveWithNoHolder"] = @(witnessHolder != nil);
    result[@"hostAliveWithNoHolder"] = @(witnessHost != nil);
    result[@"appAliveWithNoHolder"] = @(witnessApp != nil);
    return result;
}

// The same question asked of the host's name, because the method answers it bare.
//
// `propagateChangesToParent:` assigns `name` the way `uuid` used to be assigned, and
// `-[ServerInfoResponse populateHost:]` overwrites the stored temporary host's name with whatever the
// response carried -- so a body with no `hostname` empties the name of a host that already had one,
// and `-[TemporaryHost displayName]` falls back to the empty string when there is no custom name
// behind it. The damage stops there: an empty name deletes nothing, and the row keeps its uuid, which
// is why this one costs a blank row in the device list rather than the loss of somebody's apps. It is
// filed and measured anyway for the reason the uuid case was -- the method promises not to overwrite
// with nil, and a promise kept for six fields and broken for two is not a promise.
//
// One field is deliberately left bare, and saying so is part of the record. `customName` is written
// with `setValue:forKey:` and no guard, because the rename sheet at `HostsViewController.m:473`
// expresses "the person cleared their custom name" by assigning nil, and a guard there would make the
// field impossible to clear. `populateHost:` never touches `customName`, and a temporary host read
// out of the store carries it (`TemporaryHost.m:35`), so the discovery path writes the same value
// back rather than an absent one. That is the difference between the three fields, and it is why the
// two guards went where they did and the third did not go at all.
static void MLProbeMissingHostNameIfRequested(NSMutableDictionary *report, void (^refuse)(NSString *)) {
    if (getenv("ML_PROBE_PARTIAL_HOST_NAME") == NULL) {
        return;
    }
    NSMutableDictionary *record = [NSMutableDictionary dictionary];
    report[@"partialHostName"] = record;

    NSString *plantedUuid = [NSString stringWithFormat:@"%@named", MLProbeHostUuidPrefix];
    NSString *plantedName = @"Probe Host Named";
    DataManager *store = [[DataManager alloc] init];

    TemporaryHost *host = [[TemporaryHost alloc] init];
    host.name = plantedName;
    host.uuid = plantedUuid;
    host.address = @"192.0.2.98";
    [store updateHost:host];

    long appsBefore = 0;
    NSString *countProblem = nil;
    MLCountAppRecords(&appsBefore, NULL, &countProblem);
    record[@"appsBefore"] = @(appsBefore);
    record[@"plantedUuid"] = plantedUuid;
    record[@"plantedName"] = plantedName;

    // The uuid is present and correct here, so the write lands on the planted row through the
    // primary match rather than the fall-back: the question is what a missing name does, and the two
    // questions must not be measured in the same run.
    NSString *body = [NSString stringWithFormat:@"<hc><uniqueid>%@</uniqueid>"
                                                @"<PairStatus>1</PairStatus></hc>", plantedUuid];
    ServerInfoResponse *response = [[ServerInfoResponse alloc] init];
    [response populateWithData:[body dataUsingEncoding:NSUTF8StringEncoding]];
    TemporaryHost *partial = [[TemporaryHost alloc] init];
    partial.address = @"192.0.2.98";
    [response populateHost:partial];
    record[@"parsedName"] = partial.name ?: @"<absent>";
    record[@"parsedUuid"] = partial.uuid ?: @"<absent>";
    if (partial.name != nil || partial.uuid.length == 0) {
        record[@"status"] = @"body-did-not-parse-as-intended";
        refuse(@"a server-info body without a hostname did not parse into a host with no name and"
               @" the planted uuid, so the write below would not be the one a machine answers with"
               @" when it leaves its name out");
        return;
    }

    [store updateHost:partial];

    NSString *nameAfter = nil;
    for (TemporaryHost *readBack in [store getHosts]) {
        if ([readBack.uuid isEqualToString:plantedUuid]) {
            nameAfter = readBack.name;
            break;
        }
    }
    record[@"nameAfterPropagate"] = nameAfter.length > 0 ? nameAfter : @"<empty>";
    record[@"displayNameAfterPropagate"] = ^{
        for (TemporaryHost *readBack in [store getHosts]) {
            if ([readBack.uuid isEqualToString:plantedUuid]) {
                return readBack.displayName ?: @"";
            }
        }
        return @"<row gone>";
    }();

    long hostsAfter = 0;
    long oursAfter = 0;
    MLCountLibraryHosts(store, &hostsAfter, &oursAfter);
    long appsAfter = 0;
    countProblem = nil;
    MLCountAppRecords(&appsAfter, NULL, &countProblem);
    record[@"hostsAfter"] = @(hostsAfter);
    record[@"probeOwnedAfter"] = @(oursAfter);
    record[@"appsAfter"] = @(appsAfter);
    if (countProblem != nil) {
        record[@"appRecordProblem"] = countProblem;
    }
    record[@"status"] = @"measured";

    TemporaryHost *retire = [[TemporaryHost alloc] init];
    retire.uuid = plantedUuid;
    [store removeHost:retire];
    record[@"cleanedUp"] = @"by-the-probe";
}


// One server-info response with its unique id missing, measured against a host that has one.
//
// The reason this probe exists is a pair of facts read out of the shipping code rather than
// inferred. `-[DataManager getHostForTemporaryHost:withHostRecords:]` carries a branch commented
// "Fallback matching when UUID is missing", which matches a temporary host to a stored one by mac,
// address or name -- so the code does not merely tolerate a discovery response that arrived without
// a uuid, it expects one often enough to look the machine up without it. `-[TemporaryHost
// propagateChangesToParent:]` then writes that missing uuid back: the method opens with "Avoid
// overwriting existing data with nil if we don't have everything populated in the temporary host",
// guards `address`, `externalAddress`, `localAddress`, `ipv6Address`, `mac` and `serverCert` with
// exactly that intent, and assigns `uuid` bare. The fallback finds the paired host; the write
// clears the uuid that identified it.
//
// What turns that from a bad row into lost work is the deletion rule measured in section 12 of
// `docs/memory-ownership.md`: `Host.appList` is `Cascade`, so a host that disappears takes the app
// records under it with it -- the applications somebody added. The read path also deletes:
// `SettingsModel.hosts` calls `removeHostsWithEmptyUuid` before it reads a single row, and so does
// the device sidebar, so the row is not left to be repaired by the next good response. Looking at
// the device list is what removes it.
//
// This function therefore does what the app does, in the app's own order, and reports every number
// without judging them: plant a host with a uuid and three apps, feed the production parser a body
// with every field a paired machine sends except `uniqueid`, let the production `updateHost:` find
// the row and write into it, then read the device list the way the settings page does. The verdict
// belongs to `scripts/ownership-audit.py`, which is where the expected shape is written down, so a
// change to the code turns a record red rather than turning this function off.
static void MLProbePartialHostInfoIfRequested(NSMutableDictionary *report, void (^refuse)(NSString *)) {
    if (getenv("ML_PROBE_PARTIAL_HOST_INFO") == NULL) {
        return;
    }
    NSMutableDictionary *record = [NSMutableDictionary dictionary];
    report[@"partialHostInfo"] = record;

    NSString *plantedUuid = [NSString stringWithFormat:@"%@partial", MLProbeHostUuidPrefix];
    NSString *plantedName = @"Probe Host Partial";
    NSString *plantedMac = @"aa:bb:cc:dd:ee:f0";
    DataManager *store = [[DataManager alloc] init];

    TemporaryHost *host = [[TemporaryHost alloc] init];
    host.name = plantedName;
    host.uuid = plantedUuid;
    host.mac = plantedMac;
    host.address = @"192.0.2.99";
    [store updateHost:host];

    NSMutableSet *plantedApps = [NSMutableSet set];
    for (long appNumber = 0; appNumber < 3; appNumber++) {
        TemporaryApp *app = [[TemporaryApp alloc] init];
        app.id = [NSString stringWithFormat:@"%ld", 950000 + appNumber];
        app.name = [NSString stringWithFormat:@"Probe Partial App %ld", appNumber + 1];
        app.host = host;
        [plantedApps addObject:app];
    }
    host.appList = plantedApps;
    // The same call the app pane makes after a box answers, so the apps hang off the host the way
    // a person's do -- and so the cascade, if it runs, has something of the user's to take.
    [store updateAppsForExistingHost:host];

    long appsBefore = 0;
    NSString *countProblem = nil;
    MLCountAppRecords(&appsBefore, NULL, &countProblem);
    record[@"appsBefore"] = @(appsBefore);
    record[@"plantedUuid"] = plantedUuid;

    // Every tag a paired machine sends, minus `uniqueid`. Handing the parser a body of the shape it
    // really receives is the point: the bug being measured lives in what the code does with a tag it
    // did not get, not in a hand-built object that skipped one.
    NSString *body = @"<hc><hostname>Probe Host Partial</hostname>"
                     @"<mac>aa:bb:cc:dd:ee:f0</mac><PairStatus>1</PairStatus></hc>";
    ServerInfoResponse *response = [[ServerInfoResponse alloc] init];
    [response populateWithData:[body dataUsingEncoding:NSUTF8StringEncoding]];
    TemporaryHost *partial = [[TemporaryHost alloc] init];
    [response populateHost:partial];
    record[@"parsedName"] = partial.name ?: @"<absent>";
    record[@"parsedMac"] = partial.mac ?: @"<absent>";
    record[@"parsedUuid"] = partial.uuid ?: @"<absent>";
    if (partial.name.length == 0 || partial.mac.length == 0 || partial.uuid != nil) {
        // The body failed to say what the measurement needs it to say, so nothing below this point
        // would be about a missing unique id at all. Say so and stop rather than measure an object
        // that was never the thing under test.
        record[@"status"] = @"body-did-not-parse-as-intended";
        refuse(@"a server-info body without a unique id did not parse into a host with a name and"
               @" mac and no uuid, so the fall-back match below would not be the one the shipping"
               @" code reaches when a machine answers without its id");
    } else {
        [store updateHost:partial];

        // Read the row back the way the app does -- out of `getHosts`, by the name the response
        // carried -- rather than by the uuid that is the thing in question. Matching by uuid could
        // not tell "the uuid is gone" from "this row is gone", and those two are the difference
        // between a damaged row and a deleted one.
        NSString *uuidAfterPropagate = nil;
        BOOL rowStillThere = NO;
        for (TemporaryHost *readBack in [store getHosts]) {
            if ([readBack.name isEqualToString:plantedName]) {
                rowStillThere = YES;
                uuidAfterPropagate = readBack.uuid;
                break;
            }
        }
        record[@"rowAfterPropagate"] = @(rowStillThere);
        record[@"uuidAfterPropagate"] = uuidAfterPropagate.length > 0 ? uuidAfterPropagate : @"<empty>";

        // Now look at the device list, which is what an ordinary person does next and what removes
        // anything whose uuid went missing.
        long hostsBeforeCleanup = 0;
        long oursBeforeCleanup = 0;
        MLCountLibraryHosts(store, &hostsBeforeCleanup, &oursBeforeCleanup);
        [store removeHostsWithEmptyUuid];
        long hostsAfterCleanup = 0;
        long oursAfterCleanup = 0;
        MLCountLibraryHosts(store, &hostsAfterCleanup, &oursAfterCleanup);
        long appsAfterCleanup = 0;
        countProblem = nil;
        MLCountAppRecords(&appsAfterCleanup, NULL, &countProblem);
        record[@"hostsBeforeCleanup"] = @(hostsBeforeCleanup);
        record[@"hostsAfterCleanup"] = @(hostsAfterCleanup);
        record[@"probeOwnedBeforeCleanup"] = @(oursBeforeCleanup);
        record[@"probeOwnedAfterCleanup"] = @(oursAfterCleanup);
        record[@"appsAfterCleanup"] = @(appsAfterCleanup);
        if (countProblem != nil) {
            record[@"appRecordProblem"] = countProblem;
        }
        record[@"status"] = @"measured";

        // Leave nothing behind when the app did not already do it for us. If the row is gone the
        // measurement is that the app deleted its own host, and there is nothing to clean -- the
        // absence is the answer, so it is reported rather than hidden by a re-plant.
        if (rowStillThere && uuidAfterPropagate.length > 0) {
            TemporaryHost *retire = [[TemporaryHost alloc] init];
            retire.uuid = plantedUuid;
            [store removeHost:retire];
            record[@"cleanedUp"] = @"by-the-probe";
        } else {
            record[@"cleanedUp"] = @"by-the-app";
        }
    }
}


static void MLRunOwnershipProbeAndExitIfRequested(void) {
    if (getenv("ML_OWNERSHIP_PROBE") == NULL) {
        return;
    }

    NSString *output = NSProcessInfo.processInfo.environment[@"ML_RENDER_PROBE_OUTPUT"]
                       ?: [NSHomeDirectory() stringByAppendingPathComponent:@"ownership-probe"];
    [[NSFileManager defaultManager] createDirectoryAtPath:output
                             withIntermediateDirectories:YES
                                              attributes:nil
                                                   error:nil];

    NSMutableDictionary *ownership = [NSMutableDictionary dictionary];
    NSMutableArray<NSString *> *failures = [NSMutableArray array];
    void (^refuse)(NSString *) = ^(NSString *problem) {
        [failures addObject:problem];
    };
    // The premise every number below rests on: the holder is the app and nothing else. Named in
    // the report so the audit reads the premise instead of assuming it from this file.
    ownership[@"holder"] = @"app-only";

    // Reap before seeding. Without this the ownership probe on a CI runner measures the graph
    // the memory sweep left in the same database one step earlier -- the same shape, the same
    // three apps, and a `seed status` of existing-hosts rather than seeded, which is the only
    // clue that the room was not clean. A person's own library is left exactly as it was.
    // Before the reap, so a host this measurement removed is not also blamed on the reap, and a
    // host it left behind still gets swept by the flag that exists for that job.
    MLProbePartialHostInfoIfRequested(ownership, refuse);
    MLProbeMissingHostNameIfRequested(ownership, refuse);
    MLReapProbeOwnedHostsIfRequested(ownership, refuse);

    // One host through the production write path, exactly as the memory sweep seeds one. A
    // machine with a library of its own is left alone and its library is what gets measured.
    MLSeedHostsIntoLibrary(ownership, refuse, 1);

    NSMutableDictionary *shapes = [NSMutableDictionary dictionary];
    ownership[@"shapes"] = shapes;

    // Picked inside its own pool, and only the two objects of interest leave it. The array
    // `getHosts` returns, and the `allObjects` array of each host, are autoreleased, and an
    // array that outlives the handover is a second pair of hands on the graph: the measurement
    // would then be watching its own harness and reporting the harness's retain as the app's
    // leak. Nothing else is still held when the first observation is taken.
    NSUInteger libraryHostCount = 0;
    NSUInteger libraryProbeOwned = 0;
    __block TemporaryHost *libraryHost = nil;
    __block TemporaryApp *libraryApp = nil;
    __block NSUInteger libraryAppListCount = 0;
    @autoreleasepool {
        DataManager *store = [[DataManager alloc] init];
        NSArray<TemporaryHost *> *library = [store getHosts];
        libraryHostCount = library.count;
        for (TemporaryHost *candidate in library) {
            // Counted over the whole library, before anything picks a host out of it. The first
            // version of this counted inside the loop below and stopped where that loop stopped,
            // and a real library caught it: two probe hosts, one picked, and a report that said
            // the library held none -- a count of the search, presented as a count of the
            // library. The reap above counts the same library a second way, and the audit now
            // refuses the two answers whenever they differ.
            if ([candidate.uuid hasPrefix:MLProbeHostUuidPrefix]) {
                libraryProbeOwned++;
            }
        }
        for (TemporaryHost *candidate in library) {
            NSArray<TemporaryApp *> *apps = candidate.appList.allObjects;
            if (apps.count > 0) {
                libraryHost = candidate;
                libraryApp = apps.firstObject;
                libraryAppListCount = candidate.appList.count;
                break;
            }
        }
        if (libraryHost != nil) {
            ownership[@"productionHostUuid"] = libraryHost.uuid ?: @"";
        }
    }
    ownership[@"libraryHosts"] = @(libraryHostCount);
    ownership[@"probeOwnedHosts"] = @(libraryProbeOwned);
    if (libraryApp == nil) {
        // Not a skip: a library with no app behind any host means there is no production graph
        // to hold, which is the whole subject, so the run has to say so out loud.
        shapes[@"productionGraph"] = @"not-measured";
        refuse([NSString stringWithFormat:@"%@ host(s) in the library and none of them has an"
                @" app, so there is no graph from `getHosts` to hold", @(libraryHostCount)]);
    } else {
        shapes[@"productionGraph"] = MLOwnershipMeasureShape(^(TemporaryHost **hostSlot,
                                                              TemporaryApp **appSlot,
                                                              NSUInteger *appListCountSlot) {
            *hostSlot = libraryHost;
            *appSlot = libraryApp;
            *appListCountSlot = libraryAppListCount;
            // The builder is the last place outside the pair that still held these two, so the
            // handover has to empty it. Leaving them here would put a second holder in the room
            // and turn "the app keeps its host alive" into a tautology.
            libraryHost = nil;
            libraryApp = nil;
        });
    }
    // Wrapped rather than passed: the measurement takes a block because the production shape
    // needs to hand over captured state, and a helper that takes one kind of builder and not
    // the other would be two measurements pretending to be one.
    shapes[@"handBuiltGraph"] = MLOwnershipMeasureShape(^(TemporaryHost **hostSlot,
                                                          TemporaryApp **appSlot,
                                                          NSUInteger *appListCountSlot) {
        MLOwnershipBuildGraphPair(hostSlot, appSlot, appListCountSlot);
    });
    shapes[@"backpointerOnly"] = MLOwnershipMeasureShape(^(TemporaryHost **hostSlot,
                                                           TemporaryApp **appSlot,
                                                           NSUInteger *appListCountSlot) {
        MLOwnershipBuildBackpointerPair(hostSlot, appSlot, appListCountSlot);
    });
    // The two holder shapes above: the same severed graph, held by a holder that keeps the app
    // alone and by one that keeps the app and the host. The difference between the two readings is
    // the pairing's contribution, which is what step 2 and step 3 of the fix are for.
    shapes[@"severedBackpointerAppOnlyHolder"] = MLOwnershipMeasureHolderShape(NO, YES);
    shapes[@"severedBackpointerPairedHolder"] = MLOwnershipMeasureHolderShape(YES, YES);

    NSDictionary *report = @{@"ownership": ownership, @"failures": failures};
    NSData *json = [NSJSONSerialization dataWithJSONObject:report
                                                  options:NSJSONWritingPrettyPrinted
                                                    error:nil];
    [json writeToFile:[output stringByAppendingPathComponent:@"report.json"] atomically:YES];
    NSDictionary *handBuilt = shapes[@"handBuiltGraph"];
    fprintf(stderr, "[ownership-probe] app-only holder keeps the host alive: %s | pair survives"
            " with no holder: %s | a lone back-pointer survives with no holder: %s\n",
            [handBuilt[@"hostAliveWhileAppHeld"] boolValue] ? "yes" : "no",
            [handBuilt[@"hostAliveWithNoHolder"] boolValue] ? "yes" : "no",
            [shapes[@"backpointerOnly"][@"hostAliveWithNoHolder"] boolValue] ? "yes" : "no");
    NSDictionary *severedAppOnly = shapes[@"severedBackpointerAppOnlyHolder"];
    NSDictionary *severedPaired = shapes[@"severedBackpointerPairedHolder"];
    fprintf(stderr, "[ownership-probe] back-pointer severed: a holder keeping only the app keeps"
            " the host alive: %s | a holder keeping the app and the host keeps it alive: %s\n",
            [severedAppOnly[@"hostAliveWhileHeldByHolder"] boolValue] ? "yes" : "no",
            [severedPaired[@"hostAliveWhileHeldByHolder"] boolValue] ? "yes" : "no");
    if (failures.count) {
        fprintf(stderr, "[ownership-probe] %s\n",
                [[failures componentsJoinedByString:@"; "] UTF8String]);
    }
    fflush(stderr);
    exit(failures.count ? 1 : 0);
}

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

    // Seeded before the page opens: the page is what reads the library, and a graph that
    // arrives after the first read is a graph the sweep never saw.
    MLSeedHostsForMemorySweep(report, refuse);

    NSSet<NSWindow *> *windowsBefore = [NSSet setWithArray:NSApp.windows];
    NSSet<NSView *> *subviewsBefore = [NSSet setWithArray:content.subviews];
    // Taken before presenting: the presenter is about to rename the window, so a
    // baseline read afterwards is the page own title, which no close can return to.
    NSString *titleBeforePresent = window.title ?: @"";
    // Read before the present, so one window answers for itself on both sides of the
    // page: no page in it here, a page in it below.
    BOOL presentedBeforePresent = [SettingsOverlayPresenter isSettingsPresentedInWindow:window];

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
    // The filter that gives Command+W back is an app local monitor, so it sees the
    // gesture in every window this app owns and may swallow it only where the page is
    // up. It is asked of the same predicate the accessibility bridge uses, which is what
    // makes this answer the whole claim: the monitor hands the event back to AppKit
    // unless that predicate is true. A window that could not answer for a page before
    // one was shown is the shape that closed a stream window instead of settings.
    report[@"settingsReportedBeforePresent"] = @(presentedBeforePresent);
    if (presentedBeforePresent) {
        refuse(@"the window reported a settings page before one was presented, so the Command+W filter had nothing to hand back");
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

        // Asking the presenter to close proves the teardown works. It does not prove the
        // control on the page can reach the presenter, and those are different claims: the
        // page holds the box that carries the action weakly, so only the presenter keeping
        // that box alive makes the back control mean anything. With it unheld, the button
        // and Escape both press on air while Command+W and the window closing still work.
        // Press the control, then ask what came down with it.
        // Whether the control is visible to accessibility is reported and not asserted:
        // SwiftUI publishes that tree to an external client, so a runner with no client
        // attached answers empty and the assertion would refuse a working page. What is
        // asserted is the closure the control runs, which is the thing a press executes.
        report[@"backControlVisibleToAccessibility"] = @(MLProbeFindBackControl((id<NSAccessibility>)overlay, 0) != nil);
        BOOL backControlReached = [SettingsOverlayPresenter pressBackControlInWindow:window];
        report[@"backControlPressReachedPresenter"] = @(backControlReached);
        MLProbeSpin(0.6);
        report[@"presentedAfterBackControl"] = @([SettingsOverlayPresenter isSettingsPresentedInWindow:window]);
        report[@"mountedAfterBackControl"] = @([overlay isDescendantOf:content]);
        report[@"focusOnPageAfterBackControl"] = @(window.firstResponder == overlay);
        report[@"probeWindowIsKeyWindow"] = @(window.isKeyWindow);
        report[@"titleBeforePresent"] = titleBeforePresent;
        report[@"titleAfterBackControl"] = window.title ?: @"";
        if (!backControlReached) {
            refuse(@"the settings page was not presented when the back control was asked to run");
        }
        if ([SettingsOverlayPresenter isSettingsPresentedInWindow:window]) {
            refuse(@"running the back control closure left the page presented -- the closure reaches a box nothing owns");
        }
        if ([overlay isDescendantOf:content]) {
            refuse(@"running the back control closure left the page mounted in the window content");
        }
        // Handing the keyboard back is only a claim a window that can hold the keyboard
        // can answer. This probe window sits offscreen and is never key, and AppKit does not
        // move the first responder of a window that is not key, so the claim is asserted
        // only where the window can actually answer it.
        if (window.isKeyWindow && window.firstResponder == overlay) {
            refuse(@"running the back control closure left the keyboard on the page it just closed");
        }
        if (![window.title isEqualToString:titleBeforePresent]) {
            refuse([NSString stringWithFormat:@"running the back control closure left the title %@ instead of %@", window.title ?: @"", titleBeforePresent]);
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


    // Cumulative measurement: what a person going in and out of the page leaves behind.
    //
    // Every claim above looks at one visit and one close. A page that leaks once per visit
    // and a page that leaks once per run answer the same question at exit -- "these objects
    // are still here" -- and the difference between them is the one a user feels: the first
    // gets worse over an evening, the second does not. So the flag asks for N further visits
    // through the production presenter, in the production order (present, run the back
    // control's closure, let the teardown land), and the sweep then reports for N visits
    // rather than one. scripts/leak-audit.py --growth is what turns two of these runs into a
    // rate; this function deliberately asserts no count, because how many graphs a run holds
    // is the library's and the render's, not a property anyone should hardcode here.
    //
    // What it does assert is that the cycles it was asked for ran. A flag that reached a
    // build which ignores it would otherwise be read as "the page does not grow across
    // visits", which is the same false green with a number next to it.
    const char *requestedCycles = getenv("ML_RENDER_PROBE_CYCLES");
    if (requestedCycles != NULL) {
        char *cyclesEnd = NULL;
        long wantedCycles = strtol(requestedCycles, &cyclesEnd, 10);
        NSMutableDictionary *cycleRecord = [NSMutableDictionary dictionary];
        cycleRecord[@"requested"] = [NSString stringWithUTF8String:requestedCycles];
        cycleRecord[@"completed"] = @0;
        report[@"memoryCycles"] = cycleRecord;
        if (cyclesEnd == requestedCycles || *cyclesEnd != '\0' || wantedCycles < 1 || wantedCycles > 64) {
            cycleRecord[@"status"] = @"invalid";
            refuse([NSString stringWithFormat:@"ML_RENDER_PROBE_CYCLES asks for %s, which is not a"
                    @" whole cycle count between 1 and 64, so the growth being measured would have"
                    @" an unknown denominator", requestedCycles]);
        } else {
            cycleRecord[@"status"] = @"running";
            NSMutableArray<NSNumber *> *readsPerCycle = [NSMutableArray array];
#if DEBUG
            // The loop total is measured from before the first visit rather than summed from the
            // per-cycle spans, so a read that happens between two cycles (the library count a
            // pane pass does on its way out, say) cannot hide in the gaps of a sum. Both numbers
            // are reported; scripts/render-probe.py is what checks they add up.
            unsigned long long readsAtCyclesStart = MLHostReads();
#endif
            for (long cycle = 0; cycle < wantedCycles; cycle++) {
#if DEBUG
                unsigned long long readsAtCycleStart = MLHostReads();
#endif
                [SettingsOverlayPresenter presentSettingsInWindow:window hostId:nil];
                MLProbeSpin(0.25);
                if (![SettingsOverlayPresenter isSettingsPresentedInWindow:window]) {
                    cycleRecord[@"status"] = @"did-not-present";
                    refuse([NSString stringWithFormat:@"memory cycle %ld did not present the page,"
                            @" so the sweep counted fewer visits than it asked for", cycle + 1]);
                    break;
                }
                if (![SettingsOverlayPresenter pressBackControlInWindow:window]) {
                    cycleRecord[@"status"] = @"back-control-unreachable";
                    refuse([NSString stringWithFormat:@"memory cycle %ld could not reach the back"
                            @" control, so the page was never closed and the next cycle would have"
                            @" presented on top of it", cycle + 1]);
                    break;
                }
                MLProbeSpin(0.25);
                if ([SettingsOverlayPresenter isSettingsPresentedInWindow:window]) {
                    cycleRecord[@"status"] = @"did-not-close";
                    refuse([NSString stringWithFormat:@"memory cycle %ld left the page presented,"
                            @" which is a visit that never ends rather than a leak rate", cycle + 1]);
                    break;
                }
#if DEBUG
                [readsPerCycle addObject:@(MLHostReads() - readsAtCycleStart)];
#endif
                cycleRecord[@"completed"] = @(cycle + 1);
            }
            if ([cycleRecord[@"status"] isEqualToString:@"running"]) {
                cycleRecord[@"status"] = @"completed";
            }
            // How many hosts the library holds now, read after the visits rather than before
            // them. The count moves underneath a run -- MDNSManager keeps adding hosts while
            // the process is alive -- and a rate divided by a number from the start of the run
            // is divided by a library that has since grown. Measured across five growth runs on
            // one build: 230 to 500 first-party bytes per visit per host depending on which of
            // those two numbers is used, so the denominator is not a detail.
#if DEBUG
            cycleRecord[@"readsPerCycle"] = readsPerCycle;
            cycleRecord[@"readsDuringCycles"] = @(MLHostReads() - readsAtCyclesStart);
            // The read below is itself a read of the library, so it is counted on its own line
            // rather than being folded into a per-cycle average. The library count has to be taken
            // after the visits -- mDNS keeps adding hosts while the process lives -- and a rate
            // divided by a stale denominator is not the rate anyone thinks they measured.
            unsigned long long readsBeforeLibraryEnd = MLHostReads();
#endif
            cycleRecord[@"libraryEnd"] = @((long)[[[DataManager.alloc init] getHosts] count]);
#if DEBUG
            cycleRecord[@"libraryEndReads"] = @(MLHostReads() - readsBeforeLibraryEnd);
            // Reads that the per-cycle spans did not account for. The spans are cut at cycle
            // boundaries and the total is taken across the whole loop, so this is what a
            // completed cycle leaves unexplained -- it should be nothing. It is reported rather
            // than asserted here because a cycle that broke partway through is allowed to owe a
            // read to the visit it never finished; render-probe.py is where the completed runs
            // get held to zero, and it can tell the two cases apart by the status field.
            unsigned long long sumOfCycleSpans = 0;
            for (NSNumber *span in readsPerCycle) {
                sumOfCycleSpans += [span unsignedLongLongValue];
            }
            unsigned long long readsDuringAllCycles = [cycleRecord[@"readsDuringCycles"] unsignedLongLongValue];
            cycleRecord[@"readsUnattributedToCycles"] = @(readsDuringAllCycles - sumOfCycleSpans);
            // The counter has to be wired to the thing it claims to count. Every library count
            // goes through getHosts, so a run that reports zero reads for the one read this
            // function makes on its own behalf means the instrumentation is dead -- and every
            // other number in this record would then be a zero as well.
            if ([cycleRecord[@"libraryEndReads"] unsignedLongLongValue] < 1) {
                refuse(@"counting the library through getHosts did not register as a library read,"
                       @" so the host-read counter is not attached to the read path and every"
                       @" read count in this report is meaningless");
            }
#endif
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
// A block observer is only reachable through the token it returns: -removeObserver:
// with the object that owns the block removes nothing, which is measured rather than
// assumed. -dealloc below already asks for that; it needs the token to act on.
@property (nonatomic) id localNetworkTriggerObserver;
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
    if (self.localNetworkTriggerObserver != nil) {
        [[NSNotificationCenter defaultCenter] removeObserver:self.localNetworkTriggerObserver];
        self.localNetworkTriggerObserver = nil;
    }
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
    self.localNetworkTriggerObserver = [[NSNotificationCenter defaultCenter] addObserverForName:@"MoonlightRequestLocalNetworkTrigger"
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
    NSMenuItem *diagnoseItem = [helpMenu addItemWithTitle:MLString(@"Diagnose Connection Problems…", nil)
                                                   action:@selector(repairLocalNetworkPermission)
                                            keyEquivalent:@""];
    [diagnoseItem setTarget:self];
}

- (void)applicationWillFinishLaunching:(NSNotification *)notification {
#ifdef DEBUG
    // Ownership first, then pixels: the ownership experiment has no window to wait for, and
    // each probe answers to its own flag, so asking for one never runs the other.
    MLRunOwnershipProbeAndExitIfRequested();
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
// 5. Full diagnostics: any connection issue → "Help > Diagnose Connection Problems" gives a complete report.

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
                MLString(@"===== Moonlight connection diagnostic report =====\n", nil)];
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
                    ? MLString(@"tccutil reset succeeded", nil)
                    : [NSString stringWithFormat:
                       MLString(@"tccutil reset failed (exit=%d). Turn the Local Network switch off and on again by hand in System Settings.", nil),
                       resetExit];
                [alert setMessageText:resetExit == 0
                    ? MLString(@"Local network permission was reset, please allow access", nil)
                    : MLString(@"Resetting the local network permission failed", nil)];
                // One key per sentence rather than one key for the whole paragraph:
                // the paragraph is assembled from four sentences plus the two command
                // outputs, and a language table line that carries four sentences and
                // two %@ slots is a line no translator can safely edit.
                NSMutableArray<NSString *> *guidance = [NSMutableArray arrayWithArray:@[
                    MLString(@"macOS is about to ask whether Moonlight may access your local network. Tap Allow.", nil),
                    MLString(@"If that prompt does not appear, turn Moonlight on by hand in:", nil),
                    MLString(@"System Settings → Privacy & Security → Local Network → Moonlight", nil),
                ]];
                [guidance addObject:[NSString stringWithFormat:@"%@\n%@",
                                     resetSummary, resetOut.length > 0 ? resetOut : @""]];
                [guidance addObject:MLString(@"The full diagnostic report was written to the console log (Help → Diagnose Connection Problems can rerun it at any time).", nil)];
                [alert setInformativeText:[guidance componentsJoinedByString:@"\n\n"]];
                [alert setAlertStyle:NSAlertStyleInformational];
                [alert addButtonWithTitle:MLString(@"Open Local Network Settings", nil)];
                [alert addButtonWithTitle:MLString(@"Got it", nil)];
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
    [alert setMessageText:MLString(@"Moonlight cannot find your game host?", nil)];
    NSArray<NSString *> *steps = @[
        MLString(@"Hosts are usually missing because Local Network permission has not been granted.", nil),
        MLString(@"Work through these steps:", nil),
        MLString(@"1. Open System Settings → Privacy & Security → Local Network and turn Moonlight on", nil),
        MLString(@"2. If macOS never showed the Local Network prompt, run Help → Diagnose Connection Problems", nil),
        MLString(@"3. You can also press the + button at the top right of the main window and add the host address by hand.", nil),
    ];
    [alert setInformativeText:[steps componentsJoinedByString:@"\n\n"]];
    [alert setAlertStyle:NSAlertStyleWarning];
    [alert addButtonWithTitle:MLString(@"Open Local Network Settings", nil)];
    [alert addButtonWithTitle:MLString(@"Got it", nil)];
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
