//
//  DiagnosticsReportBuilder.m
//  Moonlight for macOS
//

#import "DiagnosticsReportBuilder.h"

#import <math.h>

#import "InputDiagnosticsLedger.h"
#import "MLControllerInventory.h"

@interface DiagnosticsReportSection ()
// The public properties say readonly, because a report section that changed after it
// was handed over would make the assembled text disagree with the sections it came from.
@property (nonatomic, copy, readwrite) NSString *title;
@property (nonatomic, copy, readwrite) NSArray<NSString *> *lines;
@end

@implementation DiagnosticsReportSection

+ (instancetype)sectionWithTitle:(NSString *)title lines:(NSArray<NSString *> *)lines {
    // No `if (section != nil)` guard around the assignments. ARC hands back a nonnull
    // object from `alloc`/`init`, so the guard could not take its other branch, and the
    // static analyzer used that branch as the one path on which a method the header
    // promises nonnull returns nil. Assigning unconditionally leaves it nothing to
    // prove, and leaves the reader one branch that cannot happen.
    DiagnosticsReportSection *section = [[self alloc] init];
    section.title = [title copy] ?: @"";
    section.lines = [lines copy] ?: @[];
    return section;
}

@end

@interface DiagnosticsFeatureParam ()
// Same readonly-outside/readwrite-inside contract as the section above: the live side
// builds one of these per hand-feel parameter and nobody downstream may move a number
// after the block was assembled.
@property (nonatomic, copy, readwrite) NSString *label;
@property (nonatomic, readwrite) double shippedDefault;
@property (nonatomic, readwrite) double minimum;
@property (nonatomic, readwrite) double maximum;
@property (nonatomic, readwrite) double overrideValue;
@end

@implementation DiagnosticsFeatureParam

+ (instancetype)paramWithLabel:(NSString *)label
               shippedDefault:(double)shippedDefault
                       minimum:(double)minimum
                       maximum:(double)maximum
                overrideValue:(double)overrideValue {
    DiagnosticsFeatureParam *param = [[self alloc] init];
    param.label = [label copy] ?: @"";
    param.shippedDefault = shippedDefault;
    param.minimum = minimum;
    param.maximum = maximum;
    param.overrideValue = overrideValue;
    return param;
}

@end

@implementation DiagnosticsFeatureState

- (instancetype)init {
    self = [super init];
    if (self) {
        _profileScope = @"global profile";
        _sidebarParams = @[];
        _switches = @{};
        _pointerState = @{};
    }
    return self;
}

@end

@interface DiagnosticsReportBuilder ()
+ (NSString *)assembleSections:(NSArray<DiagnosticsReportSection *> *)sections;
+ (NSString *)replaceInString:(NSString *)input
                      pattern:(NSString *)pattern
                  replacement:(NSString *)replacement;
+ (NSString *)redactUuidsInString:(NSString *)input;
+ (NSString *)redactOpaqueTokensInString:(NSString *)input;
+ (BOOL)looksOpaqueToken:(NSString *)token;
@end

@implementation DiagnosticsReportBuilder

static NSString *const kInputSection = @"input";
static NSString *const kRedactedValue = @"[redacted]";
static NSString *const kRedactedPin = @"[redacted-pin]";
static NSString *const kRedactedMac = @"[redacted-mac]";
static NSString *const kRedactedUuid = @"[redacted-uuid]";
static NSString *const kRedactedBlob = @"[redacted-blob]";
static NSString *const kRedactedPath = @"[redacted-path]";
static NSString *const kRuleUnavailable = @"\n[redaction rule unavailable]\n";

// The stand-in for a build identity while the rest of the report is scrubbed. A control byte
// outside the base64 alphabet, so no rule below can match it or leave it in the finished text.
static NSString *const kBuildIdentityGuard = @"\001ml-build-git-commit\001";

// The name a protocol type reads as in a report. The comparison goes through the
// same table that produced the recorded number, so the builder and the sender
// cannot start calling the same id by different names -- including the id with no
// layout family behind it, which the sender can still put on the wire. An id the
// table does not know prints as unknown rather than being guessed.
+ (NSString *)controllerTypeNameForProtocolType:(uint8_t)protocolType {
    NSString *name = MLControllerProtocolTypeName(protocolType);
    if (name != nil) {
        return name;
    }
    return @"unknown";
}

+ (DiagnosticsReportSection *)controllersSectionWithSnapshot:(MLControllerInventorySnapshot *_Nullable)snapshot {
    NSMutableArray<NSString *> *lines = [NSMutableArray array];
    if (snapshot == nil) {
        [lines addObject:@"controllers: never looked (no stream has recorded them)"];
    } else {
        [lines addObject:[NSString stringWithFormat:@"controllers looked: %lu session(s)%s",
                          (unsigned long)snapshot.generations,
                          snapshot.recordingNow ? ", recording now" : ""]];
        if (snapshot.driverName.length > 0) {
            [lines addObject:[NSString stringWithFormat:@"controller driver: %@",
                              snapshot.driverName]];
        } else {
            [lines addObject:@"controller driver: none (not recorded for this session)"];
        }
        [lines addObject:@"driver captured at session start; type-map is a local candidate"];
        [lines addObject:snapshot.advertisedControllerArrivals
            ? @"controller arrivals sent to host: yes"
            : @"controller arrivals sent to host: no"];
        if (snapshot.advertisedControllerArrivals &&
            snapshot.advertisedControllerTypes.count > 0) {
            NSArray<NSNumber *> *slots = [snapshot.advertisedControllerTypes.allKeys
                                          sortedArrayUsingSelector:@selector(compare:)];
            NSMutableArray<NSString *> *parts = [NSMutableArray array];
            for (NSNumber *slot in slots) {
                [parts addObject:[NSString stringWithFormat:@"player %ld=%@",
                                   (long)[slot integerValue],
                                   [self controllerTypeNameForProtocolType:
                                        [snapshot.advertisedControllerTypes[slot] unsignedCharValue]]]];
            }
            [parts addObject:@"caps=analog triggers+rumble"];
            [lines addObject:[@"advertised controller type/caps: "
                               stringByAppendingString:[parts componentsJoinedByString:@" "]]];
        } else {
            [lines addObject:@"advertised controller type/caps: not advertised"];
        }
        [lines addObject:[NSString stringWithFormat:
                          @"HID identity groups: %lu (VID/PID/family groups, not a physical controller count)",
                          (unsigned long)snapshot.entries.count]];
        if (snapshot.entries.count == 0) {
            [lines addObject:@"controller HID nodes: none recorded"];
        }
        for (MLControllerEntry *entry in snapshot.entries) {
            NSMutableString *row = [NSMutableString string];
            [row appendFormat:@"  %@:%@ %@",
             [NSString stringWithFormat:@"%04lx", (unsigned long)entry.vendorId],
             [NSString stringWithFormat:@"%04lx", (unsigned long)entry.productId],
             MLControllerFamilyName(entry.family)];
            [row appendFormat:@" type-map=%d",
                              MLControllerProtocolTypeForFamily(entry.family)];
            if (entry.transport.length > 0) {
                [row appendFormat:@" %@", entry.transport];
            }
            if (entry.hasBatteryPercent) {
                [row appendFormat:@" battery=%ld%%", (long)entry.batteryPercent];
            }
            if (entry.nodeCount > 1) {
                [row appendFormat:@" nodes=%lu", (unsigned long)entry.nodeCount];
            }
            [lines addObject:row];
        }
    }
    return [DiagnosticsReportSection sectionWithTitle:@"controllers" lines:lines];
}

+ (NSString *)logSectionTitle {
    return @"log";
}

+ (NSUInteger)reportCharacterCap {
    // An issue body takes more than this, but a report nobody reads is not a report.
    // The log block gives way first, so what reaches the cap is the tail of the tail
    // rather than the machine description at the top.
    return 20000;
}

+ (NSUInteger)logLineCap {
    return 200;
}

+ (NSArray<NSString *> *)recentLinesFromLog:(NSString *)logBody maxLines:(NSUInteger)maxLines {
    if (logBody.length == 0 || maxLines == 0) {
        return @[];
    }
    NSArray<NSString *> *lines =
        [logBody componentsSeparatedByCharactersInSet:[NSCharacterSet newlineCharacterSet]];
    NSMutableArray<NSString *> *kept = [NSMutableArray arrayWithCapacity:maxLines];
    for (NSInteger index = (NSInteger)lines.count - 1;
         index >= 0 && kept.count < maxLines;
         index--) {
        NSString *trimmed = [lines[(NSUInteger)index]
            stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
        if (trimmed.length == 0) {
            continue;
        }
        [kept insertObject:trimmed atIndex:0];
    }
    return [kept copy];
}

/// The per-sender counts as `coreHIDMouse=4180, mouseMoved=12`.
///
/// Ordered by count first: the sender that carried the session is the one a reader has to see
/// first, and a report that listed the quietest sender at the top would send a maintainer to
/// the wrong branch. A handful at most, because a report is read in an issue thread and a
/// sender that moved three packets is not the story.
+ (NSString *)senderCountsStringFrom:(NSDictionary<NSString *, NSNumber *> *_Nullable)counts {
    if (counts.count == 0) {
        return @"none";
    }
    NSArray<NSString *> *names =
        [counts.allKeys sortedArrayUsingComparator:^NSComparisonResult(NSString *left, NSString *right) {
            unsigned long long leftCount = counts[left].unsignedLongLongValue;
            unsigned long long rightCount = counts[right].unsignedLongLongValue;
            if (leftCount != rightCount) {
                return leftCount > rightCount ? NSOrderedAscending : NSOrderedDescending;
            }
            return [left compare:right];
        }];
    NSUInteger cap = 6;
    NSMutableArray<NSString *> *parts = [NSMutableArray arrayWithCapacity:MIN(cap, names.count)];
    for (NSUInteger index = 0; index < MIN(cap, names.count); index++) {
        NSString *name = names[index];
        [parts addObject:[NSString stringWithFormat:@"%@=%llu", name,
                                                  counts[name].unsignedLongLongValue]];
    }
    if (names.count > cap) {
        [parts addObject:[NSString stringWithFormat:@"(+%lu more senders)",
                                                      (unsigned long)(names.count - cap)]];
    }
    return [parts componentsJoinedByString:@", "];
}

/// `yes`/`no`, because a report line a reader has to translate reads worse than one they
/// can grep.
static NSString *ReportYesNo(BOOL value) {
    return value ? @"yes" : @"no";
}

/// A hand-feel number without decoration: `12`, `0.12`, `0.45`. `%g` rather than a fixed
/// width, because `12.000000pt` for a shipped constant makes a default look like a measurement.
static NSString *ReportNumber(double value) {
    return [NSString stringWithFormat:@"%g", value];
}

/// The value the stream actually uses for one parameter, and how it got there.
///
/// This is a copy of the clamp the stream's own getters apply, kept here because the
/// report has to be compilable -- and replayed by the gate -- without a stream view
/// controller, a window, or a settings panel. The two copies are pinned together by
/// `scripts/edge-sensor-e1-clamp-tests.py`, which reads the shipped constants and the
/// published range out of the same header the stream compiles against, so a range moved
/// in one place fails the gate in the other.
///
/// Three answers, and only three. Zero is not a small value, it is the absence of a
/// preference, and it reads as the shipped constant. An override outside the published
/// range reads as the boundary it was clamped to, with the number the player wrote next
/// to it, because "you set 30 and the stream uses 16" is the whole reason this line
/// exists. Anything in between is the override.
static NSString *ReportFeatureParamLine(DiagnosticsFeatureParam *param) {
    double effective = param.shippedDefault;
    NSString *state = @"shipped default";
    if (param.overrideValue > 0) {
        if (param.overrideValue < param.minimum) {
            effective = param.minimum;
            state = [NSString stringWithFormat:@"clamped from %@, shipped %@",
                                        ReportNumber(param.overrideValue),
                                        ReportNumber(param.shippedDefault)];
        } else if (param.overrideValue > param.maximum) {
            effective = param.maximum;
            state = [NSString stringWithFormat:@"clamped from %@, shipped %@",
                                        ReportNumber(param.overrideValue),
                                        ReportNumber(param.shippedDefault)];
        } else {
            effective = param.overrideValue;
            state = [NSString stringWithFormat:@"player override, shipped %@",
                                        ReportNumber(param.shippedDefault)];
        }
    }
    return [NSString stringWithFormat:@"%@: %@ (%@)", param.label,
                                       ReportNumber(effective), state];
}

/// A duration as `12s`, `4m 05s` or `2h 03m`. Deliberately not clock-formatted: a report
/// that says a session ended at 21:14:07 still leaves the reader subtracting to find out
/// whether that was before or after the update they installed.
+ (NSString *)elapsedStringFrom:(NSDate *_Nullable)start to:(NSDate *_Nullable)end {
    if (start == nil || end == nil) {
        return @"unknown";
    }
    NSTimeInterval interval = [end timeIntervalSinceDate:start];
    if (interval < 0) {
        interval = 0;
    }
    NSUInteger seconds = (NSUInteger)llround(interval);
    if (seconds < 60) {
        return [NSString stringWithFormat:@"%lus", (unsigned long)seconds];
    }
    NSUInteger minutes = seconds / 60;
    if (minutes < 60) {
        return [NSString stringWithFormat:@"%lum %02lus", (unsigned long)minutes,
                                          (unsigned long)(seconds % 60)];
    }
    return [NSString stringWithFormat:@"%luh %02lum", (unsigned long)(minutes / 60),
                                       (unsigned long)(minutes % 60)];
}

+ (DiagnosticsReportSection *)inputSectionWithSummary:(InputDiagnosticsSummary *_Nullable)summary
                                collectionEnabledNow:(BOOL)collectionEnabledNow
                                                 now:(NSDate *)now {
    NSMutableArray<NSString *> *lines = [NSMutableArray array];
    [lines addObject:[NSString stringWithFormat:@"collecting input counters: %@",
                                                collectionEnabledNow ? @"yes"
                                                                     : @"no (turn on the "
                                                                       "\"Input Diagnostics\" "
                                                                       "switch in Settings, then "
                                                                       "reproduce the problem)"]];
    if (summary == nil) {
        [lines addObject:@"input state unavailable: the app recorded nothing"];
        return [DiagnosticsReportSection sectionWithTitle:kInputSection lines:lines];
    }

    [lines addObject:[NSString stringWithFormat:@"streams since launch: %lu (%lu finished)",
                                                (unsigned long)summary.streamsStarted,
                                                (unsigned long)summary.streamsFinished]];
    if (summary.streamStartedAt == nil) {
        // The one answer that rules out half of what an input report is read for: the
        // pointer has not been sent anywhere yet, so nothing below it can describe a game.
        [lines addObject:@"no stream has started since launch"];
        return [DiagnosticsReportSection sectionWithTitle:kInputSection lines:lines];
    }

    if (summary.streamInProgress) {
        [lines addObject:[NSString stringWithFormat:@"stream: in progress for %@",
                                                    [self elapsedStringFrom:summary.streamStartedAt
                                                                         to:now]]];
    } else {
        NSString *elapsed = [self elapsedStringFrom:summary.streamEndedAt to:now];
        NSString *reason = summary.streamEndReason.length > 0
            ? [NSString stringWithFormat:@" (%@)", summary.streamEndReason]
            : @"";
        [lines addObject:[NSString stringWithFormat:@"stream: finished %@ ago%@",
                                                    elapsed.length > 0 ? elapsed : @"(unknown)",
                                                    reason]];
    }

    NSString *stored = summary.mouseStrategyStoredValue >= 0
        ? [NSString stringWithFormat:@"%ld", (long)summary.mouseStrategyStoredValue]
        : @"none";
    [lines addObject:[NSString stringWithFormat:
                      @"pointer mode: %@ | absolute pointer path active: %@",
                      summary.pointerMode.length > 0 ? summary.pointerMode : @"unknown",
                      ReportYesNo(summary.absolutePointerPathActive)]];
    [lines addObject:[NSString stringWithFormat:
                      @"mouse driver: %@ (stored value: %@, corehid allowed by strategy: %@)",
                      summary.mouseStrategyName.length > 0 ? summary.mouseStrategyName : @"unknown",
                      stored,
                      ReportYesNo(summary.coreHIDAllowedByStrategy)]];
    NSString *failure = summary.coreHIDFailureReason.length > 0
        ? [NSString stringWithFormat:@", reason: %@", summary.coreHIDFailureReason]
        : @"";
    [lines addObject:[NSString stringWithFormat:
                      @"corehid: wanted to start: %@ | delivered movement: %@ | failed at "
                      @"runtime: %@%@",
                      ReportYesNo(summary.coreHIDWantedToStart),
                      ReportYesNo(summary.coreHIDDeliveredMovement),
                      ReportYesNo(summary.coreHIDFailedAtRuntime),
                      failure]];
    if (summary.coreHIDAllowedByStrategy && !summary.coreHIDWantedToStart) {
        // The two facts differ for a reason a reader cannot see from either alone: the
        // absolute pointer path takes the mouse before the driver is ever started, so
        // "allowed but never attempted" is a configuration, not a failure.
        [lines addObject:@"corehid: the strategy allows it and this session never started "
                        @"the driver (the absolute pointer path takes the mouse when mouse "
                        @"mode is remote or touchscreen mode is on)"];
    }
    if (summary.lastMotionSource.length > 0) {
        NSString *when = [self elapsedStringFrom:summary.lastMotionSourceAt to:now];
        [lines addObject:[NSString stringWithFormat:
                          @"sender that last handed motion to the host: %@ (%@ ago)",
                          summary.lastMotionSource,
                          when.length > 0 ? when : @"unknown"]];
    } else {
        // Absence stated as absence. Four senders can move the host's pointer, and a report
        // that left this line out altogether could not be told apart from a build too old to
        // carry it.
        [lines addObject:@"sender that last handed motion to the host: none (no relative "
                        @"motion has been handed to the host this session)"];
    }

    if (!summary.collectionEnabledForLastStream) {
        [lines addObject:@"input counters: not collected for this session, because the "
                        "\"Input Diagnostics\" switch was off when it ran -- the lines above "
                        @"are what was observable without it"];
        return [DiagnosticsReportSection sectionWithTitle:kInputSection lines:lines];
    }

    [lines addObject:[NSString stringWithFormat:
                      @"pointer events: %lu (relative dispatches %lu, absolute dispatches %lu, "
                      @"duplicate absolute skips %lu)",
                      (unsigned long)summary.mouseMoveEvents,
                      (unsigned long)summary.relativeDispatches,
                      (unsigned long)summary.absoluteDispatches,
                      (unsigned long)summary.absoluteDuplicateSkips]];
    [lines addObject:[NSString stringWithFormat:
                      @"packets handed to the host by sender (relative): %@",
                      [self senderCountsStringFrom:summary.relativeMotionBySource]]];
    [lines addObject:[NSString stringWithFormat:
                      @"packets handed to the host by sender (absolute): %@",
                      [self senderCountsStringFrom:summary.absoluteMotionBySource]]];
    [lines addObject:[NSString stringWithFormat:
                      @"relative motion: non-zero events %lu, suppressed before the host "
                      @"%lu",
                      (unsigned long)summary.nonZeroRelativeEvents,
                      (unsigned long)summary.suppressedRelativeEvents]];
    [lines addObject:[NSString stringWithFormat:
                      @"corehid: raw events %lu, dispatched %lu",
                      (unsigned long)summary.coreHIDRawEvents,
                      (unsigned long)summary.coreHIDDispatches]];
    [lines addObject:[NSString stringWithFormat:
                      @"relative delta: raw (%ld,%ld), sent (%ld,%ld)",
                      (long)summary.rawRelativeDeltaX, (long)summary.rawRelativeDeltaY,
                      (long)summary.sentRelativeDeltaX, (long)summary.sentRelativeDeltaY]];
    [lines addObject:[NSString stringWithFormat:
                      @"pointer capture: armed %lu, skipped %lu, released %lu",
                      (unsigned long)summary.captureArmed,
                      (unsigned long)summary.captureSkipped,
                      (unsigned long)summary.captureReleased]];
    [lines addObject:[NSString stringWithFormat:
                      @"capture rearm: attempted %lu, skipped %lu, deferred %lu",
                      (unsigned long)summary.rearms,
                      (unsigned long)summary.rearmSkips,
                      (unsigned long)summary.rearmDeferred]];
    // Pairs rather than a dictionary: a dictionary literal throws on a nil value, and every
    // one of these reasons is nil until a session has had a reason to record one.
    NSArray<NSArray<NSString *> *> *tops = @[
        @[ @"top capture skip reasons", summary.captureSkipTopReasons ?: @"" ],
        @[ @"top capture rearm reasons", summary.rearmTopReasons ?: @"" ],
        @[ @"top capture rearm skip reasons", summary.rearmSkipTopReasons ?: @"" ],
        @[ @"top capture rearm deferred reasons", summary.rearmDeferredTopReasons ?: @"" ],
    ];
    for (NSArray<NSString *> *pair in tops) {
        if (pair[1].length > 0) {
            [lines addObject:[NSString stringWithFormat:@"%@: %@", pair[0], pair[1]]];
        }
    }
    return [DiagnosticsReportSection sectionWithTitle:kInputSection lines:lines];
}

/// The switches this build offers, in the order a report reads them. The expectation
/// lives here rather than coming from the live side on purpose: a report that simply
/// omits a switch leaves the reader unable to tell "this build has no such switch" from
/// "the player turned it off", and those two lead to different fixes. A key the settings
/// never wrote is reported as unknown, which is the honest third answer.
+ (NSArray<NSString *> *)featureSwitchKeys {
    return @[ @"edgeSensorSummon", @"absoluteMouseMode", @"relativeMouseAsAbsolute",
              @"imeLocalComposition", @"muteOnFocusLoss", @"backgroundGamepad" ];
}

+ (NSDictionary<NSString *, NSNumber *> *)featureSwitchesFromPreferences:(NSDictionary *)preferences {
    NSMutableDictionary<NSString *, NSNumber *> *switches = [NSMutableDictionary dictionary];
    for (NSString *key in [self featureSwitchKeys]) {
        id value = preferences[key];
        // Only a real number counts. A string left by an older store, or a key the bridge
        // never wrote, stays absent so the line reads as unknown instead of as whatever
        // `boolValue` would have made of it.
        if ([value isKindOfClass:[NSNumber class]]) {
            switches[key] = value;
        }
    }
    return [switches copy];
}

static NSString *ReportFeatureSwitch(NSDictionary<NSString *, NSNumber *> *switches,
                                     NSString *key) {
    NSNumber *value = switches[key];
    return [NSString stringWithFormat:@"%@: %@", key,
                                       value ? ReportYesNo(value.boolValue)
                                             : @"unknown (no value written)"];
}

static NSString *ReportFeatureString(NSDictionary<NSString *, NSString *> *values,
                                     NSString *label,
                                     NSString *key) {
    NSString *value = values[key];
    return [NSString stringWithFormat:@"%@: %@", label,
                                       value.length > 0 ? value : @"unknown (not recorded)"];
}

+ (DiagnosticsReportSection *)featureStateSectionWithState:(DiagnosticsFeatureState *)state {
    NSMutableArray<NSString *> *lines = [NSMutableArray array];
    [lines addObject:@"values below are what the running build uses, not what the "
                     "settings file holds"];
    [lines addObject:[NSString stringWithFormat:@"profile in force: %@",
                                                state.profileScope.length > 0
                                                    ? state.profileScope
                                                    : @"unknown"]];

    if (state.sidebarParams.count == 0) {
        [lines addObject:@"sidebar hand-feel parameters: none reported by this build"];
    }
    for (DiagnosticsFeatureParam *param in state.sidebarParams) {
        [lines addObject:ReportFeatureParamLine(param)];
    }

    for (NSString *key in [self featureSwitchKeys]) {
        [lines addObject:ReportFeatureSwitch(state.switches, key)];
    }

    [lines addObject:ReportFeatureString(state.pointerState, @"mouse mode", @"mouseMode")];
    [lines addObject:ReportFeatureString(state.pointerState, @"pointer path", @"pointerPath")];

    if (!state.hasVideoStats) {
        // A zero here would read as "the stream received nothing", which is a diagnosis.
        // The truth is that no stream has been running, so there is no counter to read.
        [lines addObject:@"video counters: no active stream (nothing measured)"];
    } else {
        [lines addObject:[NSString stringWithFormat:
                          @"video counters: received=%u decoded=%u rendered=%u "
                          @"fps=%.1f jitter=%.1fms received=%.1fMiB format=%@",
                          state.receivedFrames, state.decodedFrames, state.renderedFrames,
                          state.renderedFps, state.jitterMs,
                          (double)state.receivedBytes / (1024.0 * 1024.0),
                          state.videoFormatName.length > 0 ? state.videoFormatName : @"unknown"]];
    }

    if (!state.hasReconnectState) {
        [lines addObject:@"reconnect backoff: no stream window to read the attempt counter "
                         "from"];
    } else {
        [lines addObject:[NSString stringWithFormat:
                          @"reconnect backoff: attempt %lu of %lu, attempt pending: %@, "
                          @"host confirmed gone: %@",
                          (unsigned long)state.reconnectAttemptCount,
                          (unsigned long)state.reconnectMaxAttempts,
                          ReportYesNo(state.reconnectPending),
                          ReportYesNo(state.reconnectHostConfirmedGone)]];
    }

    return [DiagnosticsReportSection sectionWithTitle:@"features" lines:lines];
}

// A hand-feel parameter name in the form a checker indexes by. The label is the same
// string the prose block prints and the same one `sidebarFeatureParamsWithOverrides:`
// builds, so there is still one name per parameter in the tree; this only makes it
// addressable without spaces.
static NSString *MachineParamKey(NSString *label) {
    NSString *lowered = label.lowercaseString ?: @"";
    NSMutableString *key = [NSMutableString string];
    for (NSUInteger index = 0; index < lowered.length; index++) {
        unichar character = [lowered characterAtIndex:index];
        BOOL isLetter = character >= 'a' && character <= 'z';
        BOOL isDigit = character >= '0' && character <= '9';
        [key appendString:(isLetter || isDigit) ? [NSString stringWithFormat:@"%C", character]
                                                : @"_"];
    }
    while ([key hasSuffix:@"_"]) {
        [key deleteCharactersInRange:NSMakeRange(key.length - 1, 1)];
    }
    return key.length > 0 ? key : @"unnamed";
}

// How a parameter reached its effective value, in one word. Three answers, the same three
// the prose block gives, because the checker has to be able to tell "the player never
// touched this" from "the player's number was out of range" without re-deriving the clamp.
static NSString *MachineParamState(DiagnosticsFeatureParam *param, double effective) {
    if (param.overrideValue <= 0) {
        return @"shipped";
    }
    if (param.overrideValue < param.minimum) {
        return [NSString stringWithFormat:@"clamped_below_%@", ReportNumber(param.minimum)];
    }
    if (param.overrideValue > param.maximum) {
        return [NSString stringWithFormat:@"clamped_above_%@", ReportNumber(param.maximum)];
    }
    return [NSString stringWithFormat:@"override_of_%@", ReportNumber(effective)];
}

+ (DiagnosticsReportSection *)machineStateSectionWithState:(DiagnosticsFeatureState *)state
                                                  snapshot:(MLControllerInventorySnapshot *_Nullable)snapshot {
    NSMutableArray<NSString *> *lines = [NSMutableArray array];
    [lines addObject:@"ml.schema=1"];
    // A comment rather than a bare sentence: everything that is not a comment or a key is data,
    // so a checker can take this block literally instead of learning which lines to skip.
    [lines addObject:@"# one key=value per line; unknown means the app could not read it, "
                      "never zero"];

    // Which bytes this report came from, before anything about their contents. A build number
    // is a monotonic count of whatever branch the checkout sat on, so it identifies a build
    // only inside one lineage; the commit is what makes an acceptance statement portable.
    // Every three of these is `unknown` when the bundle did not carry it, never a guess.
    NSString *commit = state.gitCommit;
    BOOL commitIsFull = commit.length == 40;
    for (NSUInteger index = 0; commitIsFull && index < commit.length; index++) {
        unichar symbol = [commit characterAtIndex:index];
        BOOL hex = (symbol >= '0' && symbol <= '9') ||
                   (symbol >= 'a' && symbol <= 'f');
        if (!hex) {
            commitIsFull = NO;
        }
    }
    [lines addObject:[NSString stringWithFormat:@"ml.build.git_commit=%@",
                      commitIsFull ? commit : @"unknown"]];
    [lines addObject:[NSString stringWithFormat:@"ml.build.version=%@",
                      state.appVersion.length > 0 ? state.appVersion : @"unknown"]];
    [lines addObject:[NSString stringWithFormat:@"ml.build.number=%@",
                      state.buildNumber.length > 0 ? state.buildNumber : @"unknown"]];

    NSString *scope = state.profileScope ?: @"";
    NSString *machineScope = @"unknown";
    if ([scope hasPrefix:@"per-host"]) {
        machineScope = @"per-host";
    } else if ([scope hasPrefix:@"global"]) {
        machineScope = @"global";
    }
    [lines addObject:[NSString stringWithFormat:@"ml.profile=%@", machineScope]];

    for (DiagnosticsFeatureParam *param in state.sidebarParams) {
        double effective = param.shippedDefault;
        if (param.overrideValue > 0) {
            effective = MIN(MAX(param.overrideValue, param.minimum), param.maximum);
        }
        NSString *base = [NSString stringWithFormat:@"ml.param.%@", MachineParamKey(param.label)];
        [lines addObject:[NSString stringWithFormat:@"%@.effective=%@", base, ReportNumber(effective)]];
        [lines addObject:[NSString stringWithFormat:@"%@.shipped=%@", base,
                                                  ReportNumber(param.shippedDefault)]];
        [lines addObject:[NSString stringWithFormat:@"%@.range=%.6g..%.6g", base,
                                                  param.minimum, param.maximum]];
        [lines addObject:[NSString stringWithFormat:@"%@.written=%@", base,
                          param.overrideValue > 0 ? ReportNumber(param.overrideValue) : @"none"]];
        [lines addObject:[NSString stringWithFormat:@"%@.state=%@", base,
                                                  MachineParamState(param, effective)]];
    }

    for (NSString *key in [self featureSwitchKeys]) {
        NSNumber *value = state.switches[key];
        [lines addObject:[NSString stringWithFormat:@"ml.switch.%@=%@", key,
                          value ? (value.boolValue ? @"on" : @"off") : @"unknown"]];
    }

    NSString *mouseMode = state.pointerState[@"mouseMode"];
    NSString *pointerPath = state.pointerState[@"pointerPath"];
    [lines addObject:[NSString stringWithFormat:@"ml.pointer.mouse_mode=%@",
                      mouseMode.length > 0 ? mouseMode : @"unknown"]];
    [lines addObject:[NSString stringWithFormat:@"ml.pointer.path=%@",
                      pointerPath.length > 0 ? pointerPath : @"unknown"]];
    [lines addObject:[NSString stringWithFormat:@"ml.pointer.absolute=%@",
                      pointerPath.length > 0
                          ? ([pointerPath hasSuffix:@"(absolute)"] ? @"yes" : @"no")
                          : @"unknown"]];

    if (!state.hasVideoStats) {
        [lines addObject:@"ml.video.present=no"];
    } else {
        [lines addObject:@"ml.video.present=yes"];
        [lines addObject:[NSString stringWithFormat:@"ml.video.frames.received=%u",
                          state.receivedFrames]];
        [lines addObject:[NSString stringWithFormat:@"ml.video.frames.decoded=%u",
                          state.decodedFrames]];
        [lines addObject:[NSString stringWithFormat:@"ml.video.frames.rendered=%u",
                          state.renderedFrames]];
        [lines addObject:[NSString stringWithFormat:@"ml.video.fps=%.1f", state.renderedFps]];
        [lines addObject:[NSString stringWithFormat:@"ml.video.jitter_ms=%.1f", state.jitterMs]];
        // Raw bytes rather than the MiB the prose block prints: a checker grading a bandwidth
        // claim must not have to reproduce a division that was only ever meant to be readable.
        [lines addObject:[NSString stringWithFormat:@"ml.video.bytes=%llu", state.receivedBytes]];
        [lines addObject:[NSString stringWithFormat:@"ml.video.format=%@",
                          state.videoFormatName.length > 0 ? state.videoFormatName : @"unknown"]];
    }

    if (!state.hasReconnectState) {
        [lines addObject:@"ml.reconnect.present=no"];
    } else {
        [lines addObject:@"ml.reconnect.present=yes"];
        [lines addObject:[NSString stringWithFormat:@"ml.reconnect.attempt=%lu",
                          (unsigned long)state.reconnectAttemptCount]];
        [lines addObject:[NSString stringWithFormat:@"ml.reconnect.max=%lu",
                          (unsigned long)state.reconnectMaxAttempts]];
        [lines addObject:[NSString stringWithFormat:@"ml.reconnect.pending=%@",
                          ReportYesNo(state.reconnectPending)]];
        [lines addObject:[NSString stringWithFormat:@"ml.reconnect.host_confirmed_gone=%@",
                          ReportYesNo(state.reconnectHostConfirmedGone)]];
    }

    if (snapshot == nil) {
        [lines addObject:@"ml.controllers.present=no"];
        return [DiagnosticsReportSection sectionWithTitle:@"machine" lines:lines];
    }

    [lines addObject:@"ml.controllers.present=yes"];
    [lines addObject:[NSString stringWithFormat:@"ml.controllers.sessions=%lu",
                      (unsigned long)snapshot.generations]];
    [lines addObject:[NSString stringWithFormat:@"ml.controllers.recording=%@",
                      ReportYesNo(snapshot.recordingNow)]];
    [lines addObject:[NSString stringWithFormat:@"ml.controllers.driver=%@",
                      snapshot.driverName.length > 0 ? snapshot.driverName : @"none"]];
    [lines addObject:[NSString stringWithFormat:@"ml.controllers.arrivals=%@",
                      ReportYesNo(snapshot.advertisedControllerArrivals)]];
    if (snapshot.advertisedControllerArrivals) {
        NSArray<NSNumber *> *slots = [snapshot.advertisedControllerTypes.allKeys
                                      sortedArrayUsingSelector:@selector(compare:)];
        for (NSNumber *slot in slots) {
            [lines addObject:[NSString stringWithFormat:@"ml.controllers.slot.%ld=%@",
                              (long)[slot integerValue],
                              [self controllerTypeNameForProtocolType:
                                   [snapshot.advertisedControllerTypes[slot] unsignedCharValue]]]];
        }
        // One key per capability. A checker grading "did we advertise something we do not
        // implement" asks per capability, and a `+`-joined bundle makes it split a string to
        // find out what was even claimed.
        [lines addObject:@"ml.controllers.caps.analog_triggers=yes"];
        [lines addObject:@"ml.controllers.caps.rumble=yes"];
    }
    // The one number here that a checker must not read as a device count. Two pads of the same
    // model are one row, so an acceptance run that wants "two controllers" grades the slots the
    // host was told about, not this line. The warning used to be prose inside the value, which a
    // parser reads as part of the number and a machine skips; as its own key it has to be
    // actively ignored to be misread.
    [lines addObject:[NSString stringWithFormat:@"ml.controllers.group_count=%lu",
                      (unsigned long)snapshot.entries.count]];
    [lines addObject:@"ml.controllers.group_count_is_physical_devices=no"];
    NSUInteger index = 0;
    for (MLControllerEntry *entry in snapshot.entries) {
        NSString *base = [NSString stringWithFormat:@"ml.controllers.group.%lu",
                          (unsigned long)index];
        [lines addObject:[NSString stringWithFormat:@"%@.vid=%04lx", base,
                          (unsigned long)entry.vendorId]];
        [lines addObject:[NSString stringWithFormat:@"%@.pid=%04lx", base,
                          (unsigned long)entry.productId]];
        [lines addObject:[NSString stringWithFormat:@"%@.family=%@", base,
                          MLControllerFamilyName(entry.family)]];
        [lines addObject:[NSString stringWithFormat:@"%@.type_map=%d", base,
                          MLControllerProtocolTypeForFamily(entry.family)]];
        [lines addObject:[NSString stringWithFormat:@"%@.transport=%@", base,
                          entry.transport.length > 0 ? entry.transport : @"none"]];
        // A bare number, not `87%`: the unit belongs to the key name. A pad that never reported
        // a charge reads as `unknown`, because zero would grade as "the battery is empty".
        [lines addObject:[NSString stringWithFormat:@"%@.battery_percent=%@", base,
                          entry.hasBatteryPercent
                              ? [NSString stringWithFormat:@"%ld", (long)entry.batteryPercent]
                              : @"unknown"]];
        [lines addObject:[NSString stringWithFormat:@"%@.nodes=%lu", base,
                          (unsigned long)entry.nodeCount]];
        index++;
    }

    return [DiagnosticsReportSection sectionWithTitle:@"machine" lines:lines];
}

+ (NSString *)redactString:(NSString *)input {
    return [self redactString:input homeDirectory:NSHomeDirectory()];
}

// Pull the build identity out of the text before the scrub, and hand back where it was held.
//
// The commit is the one value a report has to keep verbatim. The acceptance checker grades every
// row against a full 40-hex commit and marks the whole matrix unknown without it, and a 40-hex
// run of letters and digits is precisely what the blob rule below exists to remove. Redacting a
// commit buys nothing either: it is the repository's own public coordinate, and a report that
// cannot say which bytes it describes answers no question at all.
//
// The match is the builder's whole line -- key, equals sign, forty lowercase hex, line end -- and
// nothing narrower than that is spared. A 40-hex run inside a log line, a filename, or the value
// of some other key is still scrubbed, so this costs the secret rules nothing they had before.
+ (NSString *)maskBuildIdentityInString:(NSString *)input heldOut:(NSString *__autoreleasing *)heldOut {
    NSRegularExpression *regex =
        [NSRegularExpression regularExpressionWithPattern:@"(?:\\A|\\n)(ml\\.build\\.git_commit=)([0-9a-f]{40})(?=\\n|\\z)"
                                               options:0
                                                 error:nil];
    if (regex == nil) {
        return input;
    }
    NSTextCheckingResult *match =
        [regex firstMatchInString:input options:0 range:NSMakeRange(0, input.length)];
    if (match == nil || match.numberOfRanges < 3) {
        return input;
    }
    if (heldOut != NULL) {
        *heldOut = [input substringWithRange:[match rangeAtIndex:2]];
    }
    return [input stringByReplacingCharactersInRange:[match rangeAtIndex:2]
                                          withString:kBuildIdentityGuard];
}

+ (NSString *)redactString:(NSString *)input homeDirectory:(NSString *)home {
    if (input.length == 0) {
        return @"";
    }
    NSString *text = input;

    // Held aside first, so the rules below never see the bytes they would otherwise destroy.
    NSString *identity = nil;
    text = [self maskBuildIdentityInString:text heldOut:&identity];

    // Any user's home path first: the log was written by this machine, but it also
    // carries paths copied out of another build's report.
    text = [self replaceInString:text pattern:@"/Users/[^/\\s\"']+" replacement:@"~"];
    text = [self replaceInString:text
                         pattern:@"/private/var/folders/[^/\\s]+/[^/\\s]+"
                     replacement:kRedactedPath];

    text = [self replaceInString:text
                         pattern:@"(?i)\\b(password|passphrase|passwd|pass|secret|token|clientpairingsecret|pairingsecret|clientcert|servercert|unique ?id|client ?id)\\b(\\s*[:=]\\s*)\\S+"
                     replacement:[NSString stringWithFormat:@"$1$2%@", kRedactedValue]];

    text = [self replaceInString:text
                         pattern:@"(?i)\\b(pin code|pin)\\b(\\s*(?:is|was|:|=)?\\s*)[0-9]{4,6}\\b"
                     replacement:[NSString stringWithFormat:@"$1$2%@", kRedactedPin]];

    text = [self replaceInString:text
                         pattern:@"(?i)\\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\\b"
                     replacement:kRedactedMac];

    text = [self redactUuidsInString:text];
    text = [self redactOpaqueTokensInString:text];

    // The exact path beats any pattern: it also catches a home that is not under
    // /Users, which is what a developer's machine and a CI runner look like.
    if (home.length > 1 && [text rangeOfString:home].location != NSNotFound) {
        text = [text stringByReplacingOccurrencesOfString:home withString:@"~"];
    }
    if (identity.length > 0) {
        text = [text stringByReplacingOccurrencesOfString:kBuildIdentityGuard withString:identity];
    }
    return text;
}

+ (NSString *)replaceInString:(NSString *)input
                      pattern:(NSString *)pattern
                  replacement:(NSString *)replacement {
    NSError *error = nil;
    NSRegularExpression *regex = [NSRegularExpression regularExpressionWithPattern:pattern
                                                                          options:0
                                                                            error:&error];
    if (regex == nil) {
        // A rule that will not compile redacts nothing. That is the failure this file
        // exists to prevent, so it says so in the text a maintainer will read instead
        // of reporting a clean report.
        return [input stringByAppendingString:kRuleUnavailable];
    }
    return [regex stringByReplacingMatchesInString:input
                                          options:0
                                            range:NSMakeRange(0, input.length)
                                     withTemplate:replacement];
}

+ (NSString *)redactUuidsInString:(NSString *)input {
    NSRegularExpression *regex =
        [NSRegularExpression regularExpressionWithPattern:@"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
                                               options:0
                                                 error:nil];
    if (regex == nil) {
        return [input stringByAppendingString:kRuleUnavailable];
    }
    NSMutableString *output = [input mutableCopy];
    NSArray<NSTextCheckingResult *> *matches =
        [regex matchesInString:input options:0 range:NSMakeRange(0, input.length)];
    // Reverse, so each replacement leaves the earlier ranges pointing where they were.
    for (NSTextCheckingResult *match in [matches reverseObjectEnumerator]) {
        NSString *uuid = [input substringWithRange:match.range];
        NSString *prefix = [uuid substringToIndex:MIN((NSUInteger)8, uuid.length)];
        [output replaceCharactersInRange:match.range
                              withString:[NSString stringWithFormat:@"%@-%@", prefix, kRedactedUuid]];
    }
    return [output copy];
}

+ (NSString *)redactOpaqueTokensInString:(NSString *)input {
    // A long run of the base64 alphabet is a certificate, a key, or a pairing secret.
    // It is never a sentence, so the token has to hold a digit as well as a letter to
    // count: `NSLocalNetworkUsageDescription` is longer than the threshold and is all
    // letters, and redacting it would make the report lie about the build.
    NSRegularExpression *regex =
        [NSRegularExpression regularExpressionWithPattern:@"[A-Za-z0-9+/]{24,}={0,2}"
                                               options:0
                                                 error:nil];
    if (regex == nil) {
        return [input stringByAppendingString:kRuleUnavailable];
    }
    NSMutableString *output = [input mutableCopy];
    NSArray<NSTextCheckingResult *> *matches =
        [regex matchesInString:input options:0 range:NSMakeRange(0, input.length)];
    for (NSTextCheckingResult *match in [matches reverseObjectEnumerator]) {
        NSString *token = [input substringWithRange:match.range];
        if (![self looksOpaqueToken:token]) {
            continue;
        }
        [output replaceCharactersInRange:match.range withString:kRedactedBlob];
    }
    return [output copy];
}

+ (BOOL)looksOpaqueToken:(NSString *)token {
    BOOL hasDigit = NO;
    BOOL hasLetter = NO;
    for (NSUInteger index = 0; index < token.length; index++) {
        unichar character = [token characterAtIndex:index];
        if (character >= '0' && character <= '9') {
            hasDigit = YES;
        } else if ((character >= 'a' && character <= 'z') ||
                   (character >= 'A' && character <= 'Z')) {
            hasLetter = YES;
        }
    }
    return hasDigit && hasLetter;
}

+ (NSString *)reportFromSections:(NSArray<DiagnosticsReportSection *> *)sections {
    NSString *body = [self redactString:[self assembleSections:sections]];
    NSUInteger cap = [self reportCharacterCap];
    if (body.length <= cap) {
        return body;
    }

    NSMutableArray<DiagnosticsReportSection *> *mutable = [sections mutableCopy];
    NSUInteger logIndex = NSNotFound;
    for (NSUInteger index = 0; index < mutable.count; index++) {
        if ([mutable[index].title isEqualToString:[self logSectionTitle]]) {
            logIndex = index;
            break;
        }
    }
    // The log block gives way first, half at a time, down to its last five lines. A
    // report that dropped the permission list to fit cannot answer the question the
    // player is filing the issue about.
    while (body.length > cap && logIndex != NSNotFound && mutable[logIndex].lines.count > 5) {
        DiagnosticsReportSection *log = mutable[logIndex];
        NSUInteger keep = MAX((NSUInteger)5, log.lines.count / 2);
        NSArray<NSString *> *tail =
            [log.lines subarrayWithRange:NSMakeRange(log.lines.count - keep, keep)];
        mutable[logIndex] = [DiagnosticsReportSection sectionWithTitle:log.title lines:tail];
        body = [self redactString:[self assembleSections:mutable]];
    }

    if (body.length > cap) {
        NSUInteger dropped = body.length - cap;
        body = [[body substringToIndex:cap]
            stringByAppendingString:[NSString stringWithFormat:
                @"\n[report truncated: %lu characters omitted]", (unsigned long)dropped]];
    }
    return body;
}

// Every separator Python's `str.splitlines()` breaks a line on, except LF itself -- LF is the
// run boundary rather than a match. The acceptance checker reads a report in universal-newline
// text mode and splits its machine block with `str.splitlines()`, and those two disagree: text
// mode folds only CR and CRLF, while `splitlines()` also breaks on VT, FF, FS, GS, RS, NEL and
// the two Unicode separators. A report carrying any of them would hash as one text and parse as
// more lines than that text holds, so the byte the hash covers and the line a key came from
// would stop describing the same file. Folding all of them to LF leaves one canonical shape.
static BOOL MLIsLineBreak(unichar character) {
    return character == '\r' || character == '\v' || character == '\f' ||
           character == 0x1C || character == 0x1D || character == 0x1E ||
           character == 0x85 || character == 0x2028 || character == 0x2029;
}

+ (NSData *)canonicalReportBytesFromString:(NSString *)report {
    if (report.length == 0) {
        return [NSData data];
    }

    NSMutableString *body = [NSMutableString stringWithCapacity:report.length];
    NSUInteger index = 0;
    NSUInteger runStart = 0;
    NSUInteger length = report.length;
    while (index < length) {
        unichar character = [report characterAtIndex:index];
        if (!MLIsLineBreak(character)) {
            index += 1;
            continue;
        }
        if (runStart < index) {
            [body appendString:[report substringWithRange:NSMakeRange(runStart, index - runStart)]];
        }
        [body appendString:@"\n"];
        // CRLF is one break, not two.
        index += (character == '\r' && index + 1 < length &&
                  [report characterAtIndex:index + 1] == '\n') ? 2 : 1;
        runStart = index;
    }
    if (runStart < length) {
        [body appendString:[report substringWithRange:NSMakeRange(runStart, length - runStart)]];
    }

    // One LF to end the file, and nothing after it. An editor that adds a blank line is the
    // exact defect this method exists to make impossible.
    NSUInteger end = body.length;
    while (end > 0 && [body characterAtIndex:end - 1] == '\n') {
        end -= 1;
    }
    if (end == 0) {
        return [NSData data];
    }
    NSString *trimmed = [body substringToIndex:end];
    return [[trimmed stringByAppendingString:@"\n"] dataUsingEncoding:NSUTF8StringEncoding];
}

+ (BOOL)writeReport:(NSString *)report toURL:(NSURL *)url error:(NSError *__autoreleasing *)error {
    if (url.filePathURL == nil) {
        if (error != NULL) {
            *error = [NSError errorWithDomain:NSCocoaErrorDomain
                                         code:NSFileWriteUnknownError
                                     userInfo:@{NSLocalizedDescriptionKey:
                                         @"The chosen destination is not a file path this app can write."}];
        }
        return NO;
    }
    NSData *bytes = [self canonicalReportBytesFromString:report];
    if (bytes.length == 0) {
        if (error != NULL) {
            *error = [NSError errorWithDomain:NSCocoaErrorDomain
                                         code:NSFileWriteNoPermissionError
                                     userInfo:@{NSLocalizedDescriptionKey:
                                         @"There was no report to write."}];
        }
        return NO;
    }
    // Without `atomically` a save interrupted halfway leaves a truncated file that still
    // opens, still has a machine block, and grades as a real report.
    return [bytes writeToFile:url.path options:NSDataWritingAtomic error:error];
}

+ (NSString *)assembleSections:(NSArray<DiagnosticsReportSection *> *)sections {
    NSMutableString *text = [NSMutableString string];
    [text appendString:@"moonlight-macos-enhanced diagnostics report\n\n"];
    [text appendString:@"Generated by the app. A PIN, password, certificate, MAC address,\n"];
    [text appendString:@"client identifier or home path is replaced by a marker such as\n"];
    [text appendString:@"[redacted-pin] rather than carried out of the machine. Host names and\n"];
    [text appendString:@"addresses are included on purpose: a connection report without them\n"];
    [text appendString:@"cannot be triaged. The log block is the tail of the app's own debug log.\n\n"];
    for (DiagnosticsReportSection *section in sections) {
        [text appendFormat:@"[%@]\n", section.title];
        if (section.lines.count == 0) {
            [text appendString:@"(none)\n"];
        }
        for (NSString *line in section.lines) {
            [text appendFormat:@"%@\n", line];
        }
        [text appendString:@"\n"];
    }
    return [text copy];
}

@end
