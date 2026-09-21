//
//  DiagnosticsReportBuilder+Live.m
//  Moonlight for macOS
//

#import "DiagnosticsReportBuilder+Live.h"

#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>
#import <IOKit/hid/IOHIDLib.h>
#import <sys/sysctl.h>
#import <sys/utsname.h>

#import "DataManager.h"
#import "Logger.h"
#import "TemporaryHost.h"

static NSString *const kReportSection = @"report";
static NSString *const kApplicationSection = @"application";
static NSString *const kSystemSection = @"system";
static NSString *const kPermissionsSection = @"permissions";
static NSString *const kNetworkSection = @"network";
static NSString *const kHostsSection = @"hosts";

static NSString *stringOrNone(NSString *_Nullable value) {
    return value.length > 0 ? value : @"(none)";
}

@implementation DiagnosticsReportBuilder (Live)

+ (NSString *)currentReport {
    NSMutableArray<DiagnosticsReportSection *> *sections = [NSMutableArray array];
    [sections addObject:[self reportSection]];
    [sections addObject:[self applicationSection]];
    [sections addObject:[self systemSection]];
    [sections addObject:[self permissionsSection]];
    [sections addObject:[self networkSection]];
    [sections addObject:[self hostsSection]];
    [sections addObject:[self logSection]];
    return [self reportFromSections:sections];
}

+ (BOOL)writeCurrentReportToPasteboard {
    NSString *report = [self currentReport];
    if (report.length == 0) {
        return NO;
    }
    NSPasteboard *pasteboard = NSPasteboard.generalPasteboard;
    [pasteboard clearContents];
    return [pasteboard setString:report forType:NSPasteboardTypeString];
}

+ (DiagnosticsReportSection *)reportSection {
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
    formatter.timeZone = [NSTimeZone timeZoneForSecondsFromGMT:0];
    formatter.dateFormat = @"yyyy-MM-dd'T'HH:mm:ss'Z'";
    return [DiagnosticsReportSection sectionWithTitle:kReportSection
                                               lines:@[[NSString stringWithFormat:@"generated: %@",
                                                        [formatter stringFromDate:[NSDate date]]]]];
}

+ (DiagnosticsReportSection *)applicationSection {
    NSBundle *bundle = NSBundle.mainBundle;
    NSDictionary *info = bundle.infoDictionary ?: @{};
    NSString *path = bundle.bundlePath ?: @"(unknown)";
    // Gatekeeper runs a quarantined app from a random read-only mount, which silently
    // breaks the local network and input monitoring grants a player believes they gave.
    BOOL translocated = [path rangeOfString:@"AppTranslocation"].location != NSNotFound;
    return [DiagnosticsReportSection
        sectionWithTitle:kApplicationSection
                   lines:@[
                       [NSString stringWithFormat:@"name: %@", stringOrNone(info[@"CFBundleName"])],
                       [NSString stringWithFormat:@"version: %@ (build %@)",
                        stringOrNone(info[@"CFBundleShortVersionString"]),
                        stringOrNone(info[@"CFBundleVersion"])],
                       [NSString stringWithFormat:@"bundle id: %@",
                        stringOrNone(bundle.bundleIdentifier)],
                       [NSString stringWithFormat:@"running from: %@", path],
                       [NSString stringWithFormat:@"translocated by gatekeeper: %@",
                        translocated ? @"yes" : @"no"],
                   ]];
}

+ (DiagnosticsReportSection *)systemSection {
    NSProcessInfo *process = NSProcessInfo.processInfo;
    NSOperatingSystemVersion version = process.operatingSystemVersion;
    struct utsname name;
    NSString *machine = @"(unknown)";
    if (uname(&name) == 0) {
        machine = [NSString stringWithUTF8String:name.machine] ?: @"(unknown)";
    }
    return [DiagnosticsReportSection
        sectionWithTitle:kSystemSection
                   lines:@[
                       [NSString stringWithFormat:@"macos: %ld.%ld.%ld",
                        (long)version.majorVersion, (long)version.minorVersion,
                        (long)version.patchVersion],
                       [NSString stringWithFormat:@"macos build: %@", [self sysctlStringForKey:"kern.osversion"]],
                       [NSString stringWithFormat:@"cpu: %@ (%lu logical cores, %lu active)",
                        [self sysctlStringForKey:"machdep.cpu.brand_string"],
                        (unsigned long)process.processorCount,
                        (unsigned long)process.activeProcessorCount],
                       [NSString stringWithFormat:@"machine model: %@", [self sysctlStringForKey:"hw.model"]],
                       [NSString stringWithFormat:@"architecture: %@", machine],
                       [NSString stringWithFormat:@"memory: %.0f GiB",
                        (double)process.physicalMemory / (1024.0 * 1024.0 * 1024.0)],
                   ]];
}

+ (NSString *)sysctlStringForKey:(const char *)key {
    char buffer[256] = {0};
    size_t size = sizeof(buffer) - 1;
    if (sysctlbyname(key, buffer, &size, NULL, 0) != 0 || size == 0) {
        return @"(unknown)";
    }
    buffer[size] = '\0';
    return [NSString stringWithUTF8String:buffer] ?: @"(unknown)";
}

+ (NSString *)hidAccessDescription:(IOHIDAccessType)access {
    switch (access) {
        case kIOHIDAccessTypeGranted:
            return @"granted";
        case kIOHIDAccessTypeDenied:
            return @"denied (System Settings > Privacy & Security > Input Monitoring)";
        default:
            // The header offers granted, denied and one other answer. `unknown` is what
            // macOS says before the player has ever been asked, and a report that calls
            // that "denied" sends them looking for a switch that is not switched off.
            return @"undetermined (the prompt has not been answered yet)";
    }
}

+ (DiagnosticsReportSection *)permissionsSection {
    return [DiagnosticsReportSection
        sectionWithTitle:kPermissionsSection
                   lines:@[
                       [NSString stringWithFormat:@"input monitoring listen: %@",
                        [self hidAccessDescription:IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)]],
                       [NSString stringWithFormat:@"input monitoring post event: %@",
                        [self hidAccessDescription:IOHIDCheckAccess(kIOHIDRequestTypePostEvent)]],
                       [NSString stringWithFormat:@"coregraphics listen preflight: %@",
                        CGPreflightListenEventAccess() ? @"yes" : @"no"],
                       [NSString stringWithFormat:@"accessibility: %@",
                        AXIsProcessTrusted() ? @"granted" : @"not granted"],
                       [NSString stringWithFormat:@"screen recording: %@",
                        CGPreflightScreenCaptureAccess() ? @"granted" : @"not granted"],
                   ]];
}

+ (DiagnosticsReportSection *)networkSection {
    NSDictionary *info = NSBundle.mainBundle.infoDictionary ?: @{};
    NSArray<NSString *> *services = nil;
    id declared = info[@"NSBonjourServices"];
    if ([declared isKindOfClass:[NSArray class]]) {
        services = (NSArray<NSString *> *)declared;
    }
    BOOL browsesGameStream = NO;
    for (NSString *service in services) {
        if ([service isEqualToString:@"_nvstream._tcp"] ||
            [service isEqualToString:@"_nvstream._tcp."]) {
            browsesGameStream = YES;
            break;
        }
    }
    NSString *usage = info[@"NSLocalNetworkUsageDescription"];
    NSMutableArray<NSString *> *lines = [NSMutableArray array];
    [lines addObject:[NSString stringWithFormat:@"local network usage description: %@",
                                                usage.length > 0 ? @"declared" : @"missing"]];
    if (services.count == 0) {
        [lines addObject:@"bonjour services declared: (none -- discovery cannot work)"];
    } else {
        [lines addObject:[NSString stringWithFormat:@"bonjour services declared: %@",
                                                    [services componentsJoinedByString:@", "]]];
    }
    // Issue 33 and issue 35 are both "another client sees the host and this one does
    // not". Whether the bundle even asks to browse the GameStream service is the first
    // question that report can answer, and it is the one nobody can infer from a screenshot.
    [lines addObject:[NSString stringWithFormat:@"gamestream browsing declared: %@",
                                                browsesGameStream ? @"yes" : @"no"]];
    return [DiagnosticsReportSection sectionWithTitle:kNetworkSection lines:lines];
}

+ (DiagnosticsReportSection *)hostsSection {
    NSMutableArray<NSString *> *lines = [NSMutableArray array];
    NSArray<TemporaryHost *> *hosts = nil;
    @try {
        hosts = [[DataManager.alloc init] getHosts];
    } @catch (NSException *exception) {
        // A report that says nothing about the hosts is worse than one that says the
        // database could not be read. The exception itself stays in the app's log.
        [lines addObject:@"hosts could not be read from the store"];
    }
    if (hosts != nil) {
        [lines addObject:[NSString stringWithFormat:@"hosts in the store: %lu", (unsigned long)hosts.count]];
        NSUInteger shown = MIN((NSUInteger)8, hosts.count);
        for (NSUInteger index = 0; index < shown; index++) {
            TemporaryHost *host = hosts[index];
            // The MAC address, the client UUID and the pinned certificate are the three
            // things a report must never carry, so they are not read here at all.
            [lines addObject:[NSString stringWithFormat:@"%@ | %@ | %@ | %@",
                              host.displayName ?: @"(unnamed)",
                              host.activeAddress.length > 0 ? host.activeAddress : stringOrNone(host.address),
                              host.pairState == PairStatePaired ? @"paired" : @"not paired",
                              host.state == StateOnline ? @"online" : @"offline"]];
        }
        if (hosts.count > shown) {
            [lines addObject:[NSString stringWithFormat:@"... %lu more hosts not shown",
                                                        (unsigned long)(hosts.count - shown)]];
        }
    }
    return [DiagnosticsReportSection sectionWithTitle:kHostsSection lines:lines];
}

+ (NSUInteger)logTailBytes {
    // Reading a debug log whole is how a report would cost a hundred megabytes on a
    // machine that has been streaming for a month.
    return 256 * 1024;
}

+ (NSString *)tailOfLogAtPath:(NSString *)path maxBytes:(NSUInteger)maxBytes {
    if (path.length == 0) {
        return nil;
    }
    NSDictionary *attributes = [[NSFileManager defaultManager]
        attributesOfItemAtPath:path
                         error:NULL];
    unsigned long long size = [attributes fileSize];
    if (size == 0) {
        return nil;
    }
    NSFileHandle *handle = [NSFileHandle fileHandleForReadingAtPath:path];
    if (handle == nil) {
        return nil;
    }
    NSString *body = nil;
    @try {
        if (size > maxBytes) {
            [handle seekToFileOffset:(size - maxBytes)];
        } else {
            [handle seekToFileOffset:0];
        }
        NSData *data = handle.readDataToEndOfFile;
        if (data.length > 0) {
            body = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
            // The window almost certainly starts in the middle of a line.
            NSRange newline = [body rangeOfString:@"\n"];
            if (newline.location != NSNotFound && newline.location + 1 < body.length) {
                body = [body substringFromIndex:newline.location + 1];
            }
        }
    } @catch (NSException *exception) {
        body = nil;
    }
    [handle closeFile];
    return body;
}

+ (DiagnosticsReportSection *)logSection {
    NSString *curated = LoggerCuratedLogPath();
    NSString *raw = LoggerRawLogPath();
    NSString *path = LoggerCuratedLogPath();
    NSString *source = @"curated";
    NSString *body = [self tailOfLogAtPath:path maxBytes:[self logTailBytes]];
    if (body.length == 0 && raw.length > 0 && ![raw isEqualToString:curated]) {
        path = raw;
        source = @"raw";
        body = [self tailOfLogAtPath:path maxBytes:[self logTailBytes]];
    }

    NSMutableArray<NSString *> *lines = [NSMutableArray array];
    [lines addObject:[NSString stringWithFormat:@"log source: %@",
                                                body.length > 0 ? source : @"none (no log was written)"]];
    if (body.length > 0) {
        NSArray<NSString *> *tail =
            [self recentLinesFromLog:body maxLines:[self logLineCap]];
        [lines addObject:[NSString stringWithFormat:@"log lines carried: %lu",
                                                    (unsigned long)tail.count]];
        [lines addObjectsFromArray:tail];
    }
    return [DiagnosticsReportSection sectionWithTitle:[self logSectionTitle] lines:lines];
}

@end
