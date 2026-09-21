//
//  DiagnosticsReportBuilder.m
//  Moonlight for macOS
//

#import "DiagnosticsReportBuilder.h"

#import <math.h>

#import "InputDiagnosticsLedger.h"

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

+ (NSString *)redactString:(NSString *)input {
    return [self redactString:input homeDirectory:NSHomeDirectory()];
}

+ (NSString *)redactString:(NSString *)input homeDirectory:(NSString *)home {
    if (input.length == 0) {
        return @"";
    }
    NSString *text = input;

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
