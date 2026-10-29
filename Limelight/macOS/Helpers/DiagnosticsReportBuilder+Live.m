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
#import "DeviceRedirectionPanelModel.h"
#import "InputDiagnosticsLedger.h"
#import "MLControllerInventory.h"
#import "Moonlight-Swift.h"
#import "Logger.h"
#import "TemporaryHost.h"
#import "StreamViewController_Internal.h"

static NSString *const kReportSection = @"report";
static NSString *const kApplicationSection = @"application";
static NSString *const kSystemSection = @"system";
static NSString *const kPermissionsSection = @"permissions";
static NSString *const kNetworkSection = @"network";
static NSString *const kHostsSection = @"hosts";
static NSString *const kDevicesSection = @"devices";

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
    // Input sits right after permissions, because the two questions a pointer report is
    // read for are answered next to each other: whether the system lets the app listen to
    // the mouse at all, and which sender was holding it when it stopped.
    [sections addObject:[self inputSection]];
    // The inventory and the feature state are each read once, into a local, and handed to both
    // the prose block and its machine-readable mirror. Read twice, the two could disagree --
    // a pad pairing between the two reads would make the report say one thing in prose and
    // another in keys, which is worse than either being wrong on its own.
    MLControllerInventorySnapshot *inventorySnapshot = MLControllerInventory.sharedInventory.snapshot;
    DiagnosticsFeatureState *featureState = [self liveFeatureState];
    [sections addObject:[DiagnosticsReportBuilder
        controllersSectionWithSnapshot:inventorySnapshot]];
    // Features sits under input and controllers because it is the block that says what the
    // two above are configured to do: which hand-feel numbers are in force, which switches
    // are on, and which pointer path took the session.
    [sections addObject:[DiagnosticsReportBuilder featureStateSectionWithState:featureState]];
    // The machine block mirrors the three above, so it sits under all of them: a human reads
    // the prose, and a checker grades the keys, and the two have to be the same reading.
    [sections addObject:[DiagnosticsReportBuilder
        machineStateSectionWithState:featureState
                            snapshot:inventorySnapshot]];
    // Devices sits under input rather than under hosts, because the four preconditions the
    // devices panel reports are answered by the same two questions a permissions and input
    // readout raises: whether the app may watch the mouse at all, and whether this build is
    // signed in the one form a kernel extension tolerates.
    [sections addObject:[self devicesSection]];
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

+ (DiagnosticsReportSection *)devicesSection {
    MLDeviceRedirectionPanelModel *panel = [[MLDeviceRedirectionPanelModel alloc]
        initWithDefaults:[NSUserDefaults standardUserDefaults]];
    NSMutableArray<NSString *> *lines = [NSMutableArray array];
    [lines addObject:panel.auditLine];
    BOOL asked = panel.hostClaim != MLDeviceRedirectionHostClaimNotAsked;
    [lines addObject:[NSString stringWithFormat:@"host claim: %@%@",
                      MLDeviceRedirectionHostClaimName(panel.hostClaim),
                      asked ? @"" : @" (a report never asks a host)"]];
    [lines addObject:[NSString stringWithFormat:@"bus: %@%@",
                      panel.busHasBeenScanned ? MLUSBBusSnapshotStatusName(panel.busStatus)
                                              : @"not-scanned",
                      panel.busHasBeenScanned ? @"" : @" (a report never enumerates the bus)"]];
    return [DiagnosticsReportSection sectionWithTitle:kDevicesSection lines:lines];
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
                       // Preflight does not describe the Debug probe's permission-free
                       // capture of its own window, or prove the ungranted case works.
                       [NSString stringWithFormat:@"screen recording: %@ (normal operation calls no capture API;"
                                                   @" the Debug render probe captures only its own window;"
                                                   @" the one window-list call compares its own window number,"
                                                   @" and the ungranted case is not measured here)",
                        CGPreflightScreenCaptureAccess() ? @"granted" : @"not granted"],
                   ]];
}

+ (DiagnosticsReportSection *)inputSection {
    return [self inputSectionWithSummary:InputDiagnosticsLedger.sharedLedger.summary
                   collectionEnabledNow:[SettingsClass inputDiagnosticsEnabled]
                                    now:[NSDate date]];
}

// The one place the live report reaches into a running stream. Everything else in this file
// reads a singleton or the bundle. It is worth the exception because the questions this block
// answers -- "is my sidebar band 12pt or did I move it", "is the IME path on", "which pointer
// sender has the mouse", "how far into the reconnect backoff am I" -- have no answer that does
// not involve the session. A build with no stream in it still gets a full block of absences,
// so a report taken before connecting describes a pre-stream build rather than failing.
+ (DiagnosticsFeatureState *)liveFeatureState {
    StreamViewController *source = [StreamViewController featureStateSourceController];
    DiagnosticsFeatureState *state;
    if (source != nil) {
        state = [source featureStateSnapshot];
    } else {
        // No stream has run, so nothing session-shaped is knowable. The hand-feel numbers
        // and the switches still are: they come from the shared profile, which is what a
        // host without its own settings would stream with anyway. Reporting them here is
        // what lets a report taken before connecting still show an override that a player
        // wrote globally -- the absence lines then cover only the counters that genuinely
        // need a stream.
        state = [[DiagnosticsFeatureState alloc] init];
        NSDictionary *prefs = [SettingsClass getSettingsFor:[SettingsClass globalHostKey]];
        state.profileScope = @"global profile (no stream has started)";
        state.switches = [self featureSwitchesFromPreferences:prefs];
        state.sidebarParams = [StreamViewController sidebarFeatureParamsWithOverrides:prefs];
    }
    return state;
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
