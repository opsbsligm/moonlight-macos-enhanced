//
//  DiagnosticsReportBuilder.m
//  Moonlight for macOS
//

#import "DiagnosticsReportBuilder.h"

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
