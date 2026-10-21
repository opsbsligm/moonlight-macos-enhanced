#!/usr/bin/env python3
"""Prove the diagnostics report says what a maintainer needs and nothing the player did not offer.

Five upstream issues -- 19, 28, 33, 35 and 41 -- are stuck for the same reason: the report
describes a symptom and no one can say what the machine was allowing the app to do. The
answer to that is a report the player can paste, so the app grew one. Which moves the risk
from "nobody can diagnose anything" to "a bug report can carry a pairing PIN, a pinned
certificate, or the player's home folder", and a leak of that shape is not something a
code review catches by reading, because the code that writes a report is expected to write
whatever it is handed.

So the rules are executed, not read. The shipping builder is compiled with a real clang and
driven with planted secrets -- a PIN stated in a sentence, a password, a base64 certificate,
a MAC address, a UUID, another user's home path, this machine's home path -- and each has to
come back redacted. Two controls matter as much: an all-letter identifier longer than the
blob threshold (`NSLocalNetworkUsageDescription`) must survive, because a report that
redacts its own vocabulary lies about the build; and a plain sentence must arrive unchanged.

The size policy is tested too, because a report that exceeds what an issue takes has to give
something up. It gives up the oldest log lines: the version, the macOS build, the permission
answers and the newest lines have to survive a report assembled from four thousand log lines.

Then eight defects are planted, one at a time, in the source that is being tested -- the
newest lines replaced by the oldest, the PIN rule removed, the blob pass removed, the home
path kept, the log section no longer giving way, an empty section no longer saying so, every
long token redacted, the UUID prefix lost. Every one has to be caught. A gate that only
passes tells you nothing about whether it would notice.

 clang also runs its static analyzer over the same shipping source. The analyzer belongs to
CI, where xcodebuild sweeps the whole tree, and it is the gate that went red one commit after
this file was written: the report's section factory guarded its assignments with
`if (section != nil)`, which gives the nullability checker a path where a method the header
declares nonnull returns nil. This file needs nothing but Foundation, so the sweep that caught
it costs a second here instead of arriving with the next build, and the defect it caught is
planted back below to prove the pass would say so again.

Finally the wiring is checked from the text of the tree, because the report is worth nothing
if no failure path can reach it: the pairing failure alert has to offer it, the settings pane
has to carry the button, the bridging header has to hand the class to Swift, and the collector
must not so much as read the three properties it promises to leave out -- the host MAC
address, the pinned certificate, and the client UUID.

The input block is held to the same standard, and for the same reason: it is the block issue
24 is waiting on. It is compiled and run against a planted session, and three shapes of the
mistake it can make are caught by construction -- describing a session that never started,
printing counters that were never collected, and dropping the line that names which sender
was holding the pointer. A zero and an uncollected value look identical once a report is
pasted, which is why that one is a refusal rather than a preference.

Usage: diagnostics-report-tests.py [root]
Exit 0 when the shipping builder passes, every planted defect is caught, and the wiring holds.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
HEADER = "Limelight/macOS/Helpers/DiagnosticsReportBuilder.h"
SOURCE = "Limelight/macOS/Helpers/DiagnosticsReportBuilder.m"
LIVE = "Limelight/macOS/Helpers/DiagnosticsReportBuilder+Live.m"
LEDGER_HEADER = "Limelight/Input/InputDiagnosticsLedger.h"
LEDGER_SOURCE = "Limelight/Input/InputDiagnosticsLedger.m"
INVENTORY_HEADER = "Limelight/Input/MLControllerInventory.h"
INVENTORY_SOURCE = "Limelight/Input/MLControllerInventory.m"
HID = "Limelight/Input/HIDSupport.m"
HID_INVENTORY = "Limelight/Input/HIDSupport+Inventory.m"
STREAM_DIAG = "Limelight/macOS/ViewControllers/StreamViewController+Diagnostics.m"
PBX = "Moonlight.xcodeproj/project.pbxproj"
BRIDGE = "Limelight/Moonlight-Bridging-Header.h"
HOSTS = "Limelight/macOS/ViewControllers/HostsViewController.m"
APP_PANE = "Limelight/macOS/ViewControllers/SettingsAppPane.swift"

# The floor, not a claim about the exact number: the shipped binary prints how many checks it
# actually ran, and this refuses a run that quietly lost cases.
MIN_DRIVER_CHECKS = 68

failures = []


def check(ok, message):
    print("%s %s" % ("ok  " if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return handle.read()


DRIVER = r'''
#import <Foundation/Foundation.h>
#import "DiagnosticsReportBuilder.h"
#import "InputDiagnosticsLedger.h"
#import "MLControllerInventory.h"

static int gFailures = 0;
static int gChecks = 0;

static void check(BOOL ok, const char *what) {
    printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    gChecks++;
    if (!ok) {
        gFailures++;
    }
}

int main(void) {
    @autoreleasepool {
        NSArray *tail = [DiagnosticsReportBuilder recentLinesFromLog:@"a\nb\n\n  \nc\nd\ne"
                                                            maxLines:2];
        check([tail isEqualToArray:@[ @"d", @"e" ]],
              "the log tail keeps the newest lines, in the order they were written");
        check([DiagnosticsReportBuilder recentLinesFromLog:@"" maxLines:5].count == 0,
              "an empty log carries nothing");
        check([DiagnosticsReportBuilder recentLinesFromLog:@"a\nb" maxLines:0].count == 0,
              "a zero line cap carries nothing");

        NSString *identifier = [DiagnosticsReportBuilder
            redactString:@"bonjour services declared: NSLocalNetworkUsageDescription"];
        check([identifier rangeOfString:@"NSLocalNetworkUsageDescription"].location != NSNotFound,
              "a long all-letter identifier survives the blob rule");
        check([identifier rangeOfString:@"[redacted"].location == NSNotFound,
              "and no marker appears where nothing secret was");

        NSString *sentence = [DiagnosticsReportBuilder redactString:@"macos build: 25E253 warm"];
        check([sentence isEqualToString:@"macos build: 25E253 warm"],
              "an ordinary line arrives unchanged");

        check([[DiagnosticsReportBuilder redactString:@"password=hunter2 done"]
            isEqualToString:@"password=[redacted] done"],
              "a password value leaves");
        check([[DiagnosticsReportBuilder redactString:@"clientpairingsecret: 9f8e7d6c5b4a3210"]
            rangeOfString:@"9f8e7d6c5b4a3210"].location == NSNotFound,
              "a pairing secret leaves");

        NSString *pin = [DiagnosticsReportBuilder redactString:@"Enter PIN is 1234 now"];
        check([pin rangeOfString:@"1234"].location == NSNotFound, "a stated PIN leaves");
        check([pin rangeOfString:@"[redacted-pin]"].location != NSNotFound,
              "and it leaves a marker a maintainer can read");

        NSString *mac = [DiagnosticsReportBuilder redactString:@"mac aa:bb:cc:dd:ee:ff end"];
        check([mac rangeOfString:@"aa:bb:cc"].location == NSNotFound, "a MAC address leaves");

        NSString *uuid = [DiagnosticsReportBuilder
            redactString:@"client 0e57f5e6-9b7a-4d3c-8f21-abcdef012345 end"];
        check([uuid rangeOfString:@"0e57f5e6-[redacted-uuid]"].location != NSNotFound,
              "a UUID keeps only the prefix that correlates two reports");

        NSString *blob = [DiagnosticsReportBuilder
            redactString:@"cert MIICabc123DEF456ghiJ789KLMnop0== end"];
        check([blob rangeOfString:@"[redacted-blob]"].location != NSNotFound,
              "a base64 certificate leaves");

        NSString *other = [DiagnosticsReportBuilder redactString:@"at /Users/other/code/x.app"];
        check([other rangeOfString:@"~"].location != NSNotFound &&
              [other rangeOfString:@"/Users/other"].location == NSNotFound,
              "another user's home path becomes ~");

        NSString *mine = [DiagnosticsReportBuilder
            redactString:@"log /opt/build/Library/Logs/x.log"
           homeDirectory:@"/opt/build"];
        check([mine rangeOfString:@"opt/build"].location == NSNotFound,
              "this machine's home path leaves");

        NSString *folders = [DiagnosticsReportBuilder
            redactString:@"/private/var/folders/zz/zyxvpxvq6csfxvn/T/x"];
        check([folders rangeOfString:@"zyxvpxvq"].location == NSNotFound,
              "a gatekeeper translocation folder leaves");

        NSDate *now = [NSDate dateWithTimeIntervalSince1970:1770000000];

        // The input block. Every claim below is a claim a report makes about somebody's
        // mouse, so each is checked against a session whose state is known exactly.
        InputDiagnosticsSummary *noStream = [[InputDiagnosticsSummary alloc] init];
        noStream.startedAt = now;
        NSString *beforeAnyStream = [[DiagnosticsReportBuilder
            inputSectionWithSummary:noStream collectionEnabledNow:YES now:now].lines componentsJoinedByString:@"\n"];
        check([beforeAnyStream rangeOfString:@"no stream has started since launch"].location != NSNotFound,
              "a report written before any stream says that, and does not describe a session");

        InputDiagnosticsSummary *uncollected = [[InputDiagnosticsSummary alloc] init];
        uncollected.startedAt = now;
        uncollected.streamStartedAt = [now dateByAddingTimeInterval:-100];
        uncollected.streamEndedAt = [now dateByAddingTimeInterval:-15];
        uncollected.streamEndReason = @"connection-terminated:-1";
        uncollected.streamsStarted = 1;
        uncollected.streamsFinished = 1;
        uncollected.mouseStrategyName = @"automatic";
        uncollected.mouseStrategyStoredValue = 3;
        uncollected.coreHIDAllowedByStrategy = YES;
        uncollected.pointerMode = @"remote";
        uncollected.absolutePointerPathActive = YES;
        uncollected.lastMotionSource = @"coreHIDMouse";
        uncollected.lastMotionSourceAt = [now dateByAddingTimeInterval:-3];
        NSString *withoutCounters = [[DiagnosticsReportBuilder
            inputSectionWithSummary:uncollected collectionEnabledNow:NO now:now].lines componentsJoinedByString:@"\n"];
        check([withoutCounters rangeOfString:@"not collected"].location != NSNotFound,
              "a session that ran with the switch off says nobody was counting");
        check([withoutCounters rangeOfString:@"pointer events:"].location == NSNotFound,
              "and it does not print counters that were never collected -- a zero would read "
              "as a mouse that never moved");
        check([withoutCounters rangeOfString:@"finished 15s ago"].location != NSNotFound,
              "a finished session is named as finished, with how long ago");
        check([withoutCounters rangeOfString:@"connection-terminated:-1"].location != NSNotFound,
              "and why it ended");
        check([withoutCounters rangeOfString:@"coreHIDMouse"].location != NSNotFound,
              "the sender that last moved the pointer survives without the counters, because "
              "it is recorded by the sender rather than by the logging switch");
        check([withoutCounters rangeOfString:@"mouse driver: automatic (stored value: 3"].location != NSNotFound,
              "the strategy is printed with the value stored for it");
        check([withoutCounters rangeOfString:@"pointer mode: remote | absolute pointer path active: yes"].location != NSNotFound,
              "the mode the pointer was in is printed without the switch, because it is the "
              "thing that decides whether a zero below it means anything at all");

        InputDiagnosticsSummary *collecting = [uncollected copy];
        collecting.collectionEnabledForLastStream = YES;
        collecting.mouseMoveEvents = 4210;
        collecting.relativeDispatches = 4180;
        collecting.absoluteDispatches = 30;
        collecting.coreHIDRawEvents = 4190;
        collecting.suppressedRelativeEvents = 7;
        collecting.sentRelativeDeltaX = 1230;
        collecting.relativeMotionBySource = @{ @"mouseMoved": @4180, @"coreHIDMouse": @12 };
        collecting.absoluteMotionBySource = @{ @"sendAbsoluteMousePosition": @30 };
        NSString *withCounters = [[DiagnosticsReportBuilder
            inputSectionWithSummary:collecting collectionEnabledNow:YES now:now].lines componentsJoinedByString:@"\n"];
        check([withCounters rangeOfString:@"pointer events: 4210"].location != NSNotFound &&
              [withCounters rangeOfString:@"suppressed before the host 7"].location != NSNotFound,
              "with the switch on, the counters are carried");
        check([withCounters rangeOfString:@"not collected"].location == NSNotFound,
              "and the not-collected line is not carried into a session that was collected");
        check([withCounters rangeOfString:
                   @"packets handed to the host by sender (relative): mouseMoved=4180, coreHIDMouse=12"].location != NSNotFound,
              "the relative totals name the senders that wrote them, busiest first -- the "
              "totals alone cannot tell one sender from four");
        check([withCounters rangeOfString:
                   @"packets handed to the host by sender (absolute): sendAbsoluteMousePosition=30"].location != NSNotFound,
              "and the absolute path is kept apart from the relative one, because a mouseMoved "
              "packet means a different thing on each");
        check([withoutCounters rangeOfString:@"by sender (relative)"].location == NSNotFound,
              "a session that was never collected gets no sender counts, only the sender the "
              "code credited on its own");

        InputDiagnosticsSummary *noSender = [uncollected copy];
        noSender.lastMotionSource = nil;
        NSString *withoutSender = [[DiagnosticsReportBuilder
            inputSectionWithSummary:noSender collectionEnabledNow:NO now:now].lines componentsJoinedByString:@"\n"];
        check([withoutSender rangeOfString:@"none (no relative motion"].location != NSNotFound,
              "a session where no sender handed motion says so, instead of dropping the line -- "
              "an absent line and an absent feature cannot be told apart");

        InputDiagnosticsSummary *live = [uncollected copy];
        live.streamEndedAt = nil;
        live.streamEndReason = nil;
        live.streamsFinished = 0;
        live.streamInProgress = YES;
        NSString *whileStreaming = [[DiagnosticsReportBuilder
            inputSectionWithSummary:live collectionEnabledNow:YES now:now].lines componentsJoinedByString:@"\n"];
        check([whileStreaming rangeOfString:@"in progress for 1m 40s"].location != NSNotFound,
              "a stream that is still running is reported as running, for as long as it has");

        InputDiagnosticsLedger *ledger = [[InputDiagnosticsLedger alloc] init];
        [ledger noteStreamStarted];
        [ledger updateSummary:^(InputDiagnosticsSummary *summary) {
            summary.mouseStrategyName = @"coreHID";
            summary.lastMotionSource = @"mouseMoved";
        }];
        check(ledger.summary.mouseStrategyName != nil &&
              ledger.summary.lastMotionSource != nil,
              "the ledger keeps what the input code recorded on a thread other than the "
              "report's");
        [ledger noteStreamEndedWithReason:@"launch-failed"];
        check(ledger.summary.streamsFinished == 1 && !ledger.summary.streamInProgress,
              "and closing a session is visible in the summary the report reads");
        [ledger noteStreamStarted];
        check(ledger.summary.lastMotionSource == nil &&
              ledger.summary.mouseStrategyName != nil,
              "a new session loses the sender and counters of the one before it, and keeps the "
              "strategy, which the code that decides it records rather than this method");

        NSMutableArray *lines = [NSMutableArray array];
        for (int index = 0; index < 4000; index++) {
            [lines addObject:[NSString stringWithFormat:
                @"2026-09-21 line %04d aloglineoftextanddigits0123456789", index]];
        }
        NSArray *sections = @[
            [DiagnosticsReportSection sectionWithTitle:@"application"
                                                 lines:@[ @"version: 1.3.10 (build 1544)" ]],
            [DiagnosticsReportSection sectionWithTitle:@"permissions" lines:@[]],
            [DiagnosticsReportSection sectionWithTitle:[DiagnosticsReportBuilder logSectionTitle]
                                                 lines:lines],
        ];
        NSString *report = [DiagnosticsReportBuilder reportFromSections:sections];
        check(report.length <= [DiagnosticsReportBuilder reportCharacterCap],
              "the report fits what an issue body takes");
        check([report rangeOfString:@"[application]"].location != NSNotFound,
              "the header survives a report that had to shrink");
        check([report rangeOfString:@"version: 1.3.10 (build 1544)"].location != NSNotFound,
              "the version survives it");
        check([report rangeOfString:@"[permissions]\n(none)"].location != NSNotFound,
              "a section with nothing in it says so instead of vanishing");
        check([report rangeOfString:@"line 3999"].location != NSNotFound,
              "the newest log line survives");
        check([report rangeOfString:@"line 0000"].location == NSNotFound,
              "the oldest log lines are what gave way");

        NSUInteger applicationAt = [report rangeOfString:@"[application]"].location;
        NSUInteger logAt = [report rangeOfString:@"[log]"].location;
        check(applicationAt != NSNotFound && logAt != NSNotFound && applicationAt < logAt,
              "sections are emitted in the order they were handed over");

        NSString *small = [DiagnosticsReportBuilder reportFromSections:@[
            [DiagnosticsReportSection sectionWithTitle:@"report" lines:@[ @"generated: now" ]],
        ]];
        check([small rangeOfString:@"generated: now"].location != NSNotFound &&
              [small rangeOfString:@"[report truncated"].location == NSNotFound,
              "a report that fits is not shortened at all");

        // The controller inventory is the part of a report that answers "what was in the
        // player's hand and what did the app know how to call it". It is pure classification
        // and accounting: no IO, no product strings, no serials. The classification maps a
        // device to the protocol type an arrival would use once M1 sends one; the 0.1 probe
        // prints that map as a candidate, never as a type the host was actually told about.
        check(MLControllerFamilyForIds(0x054C, 0x0CE6) == MLControllerFamilyPS5 &&
              MLControllerProtocolTypeForFamily(MLControllerFamilyPS5) == 0x02,
              "a DualSense maps to PS5 and LI_CTYPE_PS (M1 owns announcing it to the host)");
        check(MLControllerFamilyForIds(0x054C, 0x09CC) == MLControllerFamilyPS4 &&
              MLControllerProtocolTypeForFamily(MLControllerFamilyPS4) == 0x02,
              "a DualShock 4 maps to PS4 and LI_CTYPE_PS (M1 owns announcing it to the host)");
        check(MLControllerFamilyForIds(0x045E, 0x0B13) == MLControllerFamilyXbox &&
              MLControllerProtocolTypeForFamily(MLControllerFamilyXbox) == 0x01,
              "an Xbox Series pad maps to Xbox and LI_CTYPE_XBOX (M1 owns announcing it)");
        check(MLControllerFamilyForIds(0x045E, 0x02E0) == MLControllerFamilyKingKong &&
              MLControllerProtocolTypeForFamily(MLControllerFamilyKingKong) == 0x01,
              "the Betop device borrowing Microsoft's vendor id maps to KingKong, not Xbox");
        check(MLControllerFamilyForIds(0x057E, 0x2009) == MLControllerFamilyNintendo &&
              MLControllerProtocolTypeForFamily(MLControllerFamilyNintendo) == 0x03,
              "a Pro Controller maps to Nintendo and LI_CTYPE_NINTENDO");
        check(MLControllerFamilyForIds(0x1234, 0x5678) == MLControllerFamilyUnknown &&
              MLControllerProtocolTypeForFamily(MLControllerFamilyUnknown) == 0x00,
              "an unknown pad stays unknown and maps to LI_CTYPE_UNKNOWN");
        check([MLControllerDriverNameForIndex(0) isEqualToString:@"HID"] &&
              [MLControllerDriverNameForIndex(1) isEqualToString:@"MFi"],
              "the probe names the HID and MFi settings indices");
        check([MLControllerDriverNameForIndex(-1) isEqualToString:@"unknown"] &&
              [MLControllerDriverNameForIndex(2) isEqualToString:@"unknown"],
              "an invalid driver index never masquerades as HID");

        MLControllerInventory *inventory = MLControllerInventory.sharedInventory;
        check(inventory.snapshot == nil,
              "the process inventory has not claimed a bench existed before anything looked");
        NSString *neverLooked = [[DiagnosticsReportBuilder
            controllersSectionWithSnapshot:nil].lines componentsJoinedByString:@"\n"];
        check([neverLooked rangeOfString:@"controllers: never looked"].location != NSNotFound,
              "the formatter names absence before any stream has recorded a bench");
        MLControllerEntry *ps5 = [[MLControllerEntry alloc] init];
        ps5.vendorId = 0x054C;
        ps5.productId = 0x0CE6;
        ps5.family = MLControllerFamilyPS5;
        ps5.transport = @"Bluetooth";
        MLControllerEntry *ps5Again = [ps5 copy];
        [inventory recordEntries:@[ ps5, ps5Again ]];
        check(inventory.snapshot != nil && inventory.snapshot.entries.count == 1 &&
              inventory.snapshot.entries.firstObject.nodeCount == 2 &&
              inventory.snapshot.recordingNow == NO &&
              inventory.snapshot.driverName == nil &&
              !inventory.snapshot.advertisedControllerArrivals,
              "two nodes that share one identity collapse into one row with a node count");
        NSString *idleText = [[DiagnosticsReportBuilder
            controllersSectionWithSnapshot:inventory.snapshot].lines componentsJoinedByString:@"\n"];
        check([idleText rangeOfString:@"controller driver: none"].location != NSNotFound &&
              [idleText rangeOfString:@"controller arrivals sent to host: no"].location != NSNotFound &&
              [idleText rangeOfString:@"advertised controller type/caps: not advertised"].location != NSNotFound &&
              [idleText rangeOfString:@"not a physical controller count"].location != NSNotFound &&
              [idleText rangeOfString:@"type-map=2"].location != NSNotFound,
              "an idle record prints driver, the un-sent arrival claim and the protocol map "
              "as a candidate, not as a type the host was told");
        [inventory noteSessionStartedWithDriverName:@"MFi"];
        check(inventory.snapshot.recordingNow == YES && inventory.snapshot.generations == 1 &&
              [inventory.snapshot.driverName isEqualToString:@"MFi"] &&
              inventory.snapshot.entries.count == 1 &&
              !inventory.snapshot.advertisedControllerArrivals,
              "starting a stream keeps the recorded identities, records the driver it uses, marks the record live and "
              "keeps arrivals as not sent while M1 owns them");
        NSString *captured = [[DiagnosticsReportBuilder
            controllersSectionWithSnapshot:inventory.snapshot].lines componentsJoinedByString:@"\n"];
        check([captured rangeOfString:@"controller driver: MFi"].location != NSNotFound &&
              [captured rangeOfString:@"controller arrivals sent to host: no"].location != NSNotFound &&
              [captured rangeOfString:@"advertised controller type/caps: not advertised"].location != NSNotFound,
              "a session report names the driver the stream used and does not claim "
              "controller types reached the host");
        MLControllerInventory *freshDoneFirst = MLControllerInventory.new;
        MLControllerEntry *first = [[MLControllerEntry alloc] init];
        first.vendorId = 0x045E;
        first.productId = 0x0B13;
        first.family = MLControllerFamilyXbox;
        [freshDoneFirst recordEntries:@[ first ]];
        [freshDoneFirst noteSessionStartedWithDriverName:@"MFi"];
        MLControllerInventorySnapshot *doneBeforeNewSession = freshDoneFirst.snapshot;
        [freshDoneFirst noteSessionStartedWithDriverName:@""];
        check(freshDoneFirst.snapshot.recordingNow == YES &&
              freshDoneFirst.snapshot.driverName.length == 0,
              "a session with no recorded driver clears the previous session's name "
              "rather than carrying a stale one");
        [freshDoneFirst noteSessionStopped];
        check(freshDoneFirst.snapshot.recordingNow == NO &&
              freshDoneFirst.snapshot.entries.count == 1 &&
              freshDoneFirst.snapshot.driverName.length == 0,
              "ending the driver-less session leaves the identities that were already recorded "
              "and keeps the absence recorded");
        [freshDoneFirst recordEntries:@[ ps5 ]];
        [freshDoneFirst noteSessionStartedWithDriverName:@"HID"];
        check(doneBeforeNewSession.entries.count == 1 &&
              [doneBeforeNewSession.driverName isEqualToString:@"MFi"] &&
              freshDoneFirst.snapshot.generations == doneBeforeNewSession.generations + 2 &&
              freshDoneFirst.snapshot.entries.count == 1 &&
              freshDoneFirst.snapshot.entries.firstObject.vendorId == 0x054C &&
              [freshDoneFirst.snapshot.driverName isEqualToString:@"HID"],
              "a snapshot keeps the identities and driver of the moment it captured, while a "
              "later read and session replace the live record it reports");
        [freshDoneFirst noteSessionStopped];
        [inventory noteSessionStopped];
        check(inventory.snapshot.recordingNow == NO && inventory.snapshot.entries.count == 1 &&
              [inventory.snapshot.driverName isEqualToString:@"MFi"],
              "ending a session withdraws the live claim but keeps the entries and the "
              "driver a report reads");

        MLControllerInventory *activeInventory = MLControllerInventory.new;
        [activeInventory noteSessionStartedWithDriverName:@"HID"];
        MLControllerInventorySnapshot *beforeRead = activeInventory.snapshot;
        check(beforeRead.entries != nil && beforeRead.entries.count == 0 &&
              beforeRead.recordingNow && beforeRead.generations == 1,
              "a session can start before its first device read with a valid empty snapshot");
        [activeInventory recordEntries:@[ ps5, first ]];
        check(activeInventory.snapshot.entries.count == 2 && activeInventory.snapshot.recordingNow &&
              activeInventory.snapshot.generations == 1 && [activeInventory.snapshot.driverName isEqualToString:@"HID"],
              "refreshing two different identities preserves the active session metadata");
        check(beforeRead.entries.count == 0 && beforeRead.generations == 1 &&
              [beforeRead.driverName isEqualToString:@"HID"],
              "a subsequent device read does not rewrite an earlier snapshot");
        NSString *withoutBattery = [[DiagnosticsReportBuilder
            controllersSectionWithSnapshot:activeInventory.snapshot].lines componentsJoinedByString:@"\n"];
        check([withoutBattery rangeOfString:@"battery="].location == NSNotFound,
              "missing battery readings do not become zero percent");

        MLControllerEntry *batteryNode = [ps5 copy];
        batteryNode.transport = nil;
        batteryNode.hasBatteryPercent = YES;
        batteryNode.batteryPercent = 0;
        [activeInventory recordEntries:@[ batteryNode, ps5 ]];
        MLControllerEntry *merged = activeInventory.snapshot.entries.firstObject;
        check(merged.nodeCount == 2 && merged.hasBatteryPercent && merged.batteryPercent == 0 &&
              [merged.transport isEqualToString:@"Bluetooth"],
              "identity grouping retains a real zero battery and the available transport");
        NSString *withBattery = [[DiagnosticsReportBuilder
            controllersSectionWithSnapshot:activeInventory.snapshot].lines componentsJoinedByString:@"\n"];
        check([withBattery rangeOfString:@"battery=0%"].location != NSNotFound,
              "the report preserves a measured zero battery");
        [activeInventory recordEntries:@[]];
        NSString *empty = [[DiagnosticsReportBuilder
            controllersSectionWithSnapshot:activeInventory.snapshot].lines componentsJoinedByString:@"\n"];
        check([empty rangeOfString:@"HID identity groups: 0"].location != NSNotFound &&
              [empty rangeOfString:@"controller HID nodes: none recorded"].location != NSNotFound &&
              [empty rangeOfString:@"never looked"].location == NSNotFound,
              "an empty recorded inventory differs from an inventory nobody recorded");
        [activeInventory noteSessionStopped];
        [activeInventory noteSessionStarted];
        check(activeInventory.snapshot.driverName == nil && activeInventory.snapshot.generations == 2 &&
              activeInventory.snapshot.recordingNow && activeInventory.snapshot.entries != nil,
              "starting without a driver clears the previous name and advances the session");
    }

    // The count is printed rather than counted from the transcript by whoever reads it: a
    // report that quotes "the harness has N checks" and is wrong is the same kind of number
    // this repository keeps refusing to write down.
    if (gFailures == 0) {
        printf("RUN PASSED (%d checks)\n", gChecks);
    }
    return gFailures != 0;
}
'''

# Each defect is a realistic regression: the file still compiles, the words are still in
# place, and the behaviour the report exists for is gone.
MUTATIONS = (
    ("the log tail keeps the oldest lines instead of the newest",
     "        [kept insertObject:trimmed atIndex:0];",
     "        [kept addObject:trimmed];"),
    ("the PIN rule only matches a length no host asks for",
     '"(?i)\\\\b(pin code|pin)\\\\b(\\\\s*(?:is|was|:|=)?\\\\s*)[0-9]{4,6}\\\\b"',
     '"(?i)\\\\b(pin code|pin)\\\\b(\\\\s*(?:is|was|:|=)?\\\\s*)[0-9]{7,9}\\\\b"'),
    ("the opaque blob pass is removed",
     "    text = [self redactOpaqueTokensInString:text];\n", ""),
    ("this machine's home path is left in",
     'text = [text stringByReplacingOccurrencesOfString:home withString:@"~"];',
     "text = [text copy];"),
    ("the log section no longer gives way, so the newest lines are what truncation takes",
     "    while (body.length > cap && logIndex != NSNotFound && mutable[logIndex].lines.count > 5) {",
     "    while (NO) {"),
    ("an empty section says nothing at all",
     '            [text appendString:@"(none)\\n"];',
     "            // (none)"),
    ("every long token is treated as a secret, vocabulary included",
     "    return hasDigit && hasLetter;",
     "    return hasDigit || hasLetter;"),
    ("the UUID loses the prefix that correlates two reports about one client",
     'stringWithFormat:@"%@-%@", prefix, kRedactedUuid',
     'stringWithFormat:@"%@-%@", kRedactedUuid, prefix'),
    ("a session that never started is described as though it had run",
     "    if (summary.streamStartedAt == nil) {",
     "    if (NO) {"),
    ("counters are printed for a session that was never collected",
     "    if (!summary.collectionEnabledForLastStream) {",
     "    if (NO) {"),
    ("the sender line names a sender even when no sender handed motion",
     "    if (summary.lastMotionSource.length > 0) {",
     "    if (YES) {"),
    ("a session that ended is reported as still running",
     "    if (summary.streamInProgress) {",
     "    if (YES) {"),
    ("the per-sender line renders empty, so the totals stand alone again",
     '    return [parts componentsJoinedByString:@", "];',
     '    return @"";'),
    ("the per-sender list is ordered by name, so the quietest sender appears first",
     "                return leftCount > rightCount ? NSOrderedAscending : NSOrderedDescending;",
     "                return NSOrderedSame;"),
    ("the report drops the controller driver a stream recorded",
     "        if (snapshot.driverName.length > 0) {",
     "        if (NO) {"),
    ("the report claims controller arrivals reached the host before M1",
     "        [lines addObject:snapshot.advertisedControllerArrivals\n"
     "            ? @\"controller arrivals sent to host: yes\"\n"
     "            : @\"controller arrivals sent to host: no (0.1 probe; M1 owns arrival)\"];",
     "        [lines addObject:@\"controller arrivals sent to host: yes\"];"),
    ("the report claims controller type/caps were advertised",
     '@"advertised controller type/caps: not advertised"',
     '@"advertised controller type/caps: sent"'),
    ("the report loses the boundary between HID groups and physical devices",
     "not a physical controller count", "physical controller count"),
)

INVENTORY_MUTATIONS = (
    ("starting a session leaves the snapshot idle",
     "    snapshot.recordingNow = YES;", "    snapshot.recordingNow = NO;"),
    ("starting a session leaves the old generation in its snapshot",
     "    snapshot.recordingNow = YES;\n    snapshot.generations = self.generations;",
     "    snapshot.recordingNow = YES;\n    snapshot.generations = 0;"),
    ("copying a snapshot discards the recorded driver",
     "    copy.driverName = self.driverName;", "    copy.driverName = nil;"),
    ("refreshing identities discards the session driver",
     "    snapshot.driverName = previous.driverName;", "    snapshot.driverName = nil;"),
    ("a session without a driver inherits the previous session's name",
     "    snapshot.driverName = driverName;",
     "    if (driverName != nil) { snapshot.driverName = driverName; }"),
    ("an invalid driver setting is reported as HID",
     '        default: return @"unknown";', '        default: return @"HID";'),
)


# The defect CI's analyzer job found on this file, planted back into the source to prove the
# local pass bites. It is the shape the checker reads, not this file's wording: a nonnull
# factory whose own guard hands the analyzer a branch where the object is nil at the return.
ANALYZER_DEFECTS = (
    ("a report section can come back nil from a factory the header promises nonnull",
     """    DiagnosticsReportSection *section = [[self alloc] init];
    section.title = [title copy] ?: @"";
    section.lines = [lines copy] ?: @[];
    return section;""",
     """    DiagnosticsReportSection *section = [[self alloc] init];
    if (section != nil) {
        section.title = [title copy] ?: @"";
        section.lines = [lines copy] ?: @[];
    }
    return section;"""),
)


def analyze(source, work, cc, sdk):
    """Run clang's static analyzer over the builder on its own, and return its findings.

    ARC is passed on purpose. The project builds with it, and the analyzer reads a manual
    retain-count world differently: without the flag this file reports a dozen leaks and a
    missing `dealloc` that the shipping build cannot have, and the finding worth seeing is
    one line inside that noise.
    """
    for name, text in ((os.path.basename(HEADER), read(HEADER)),
                       (os.path.basename(SOURCE), source),
                       (os.path.basename(LEDGER_HEADER), read(LEDGER_HEADER)),
                       (os.path.basename(INVENTORY_HEADER), read(INVENTORY_HEADER))):
        with open(os.path.join(work, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    ran = subprocess.run(
        [cc, "--analyze", "-x", "objective-c", "-fobjc-arc", "-isysroot", sdk, "-I", work,
         os.path.join(work, os.path.basename(SOURCE)),
         "-o", os.path.join(work, "analysis.plist")],
        capture_output=True, text=True)
    # The analyzer exits 0 while reporting findings, so the text is the verdict.
    log = (ran.stdout + ran.stderr).strip()
    return [line for line in log.splitlines() if "warning:" in line or "error:" in line], log


def compile_and_run(source, work, cc, sdk, inventory_source=None):
    for name, text in ((os.path.basename(HEADER), read(HEADER)),
                       (os.path.basename(SOURCE), source),
                       (os.path.basename(LEDGER_HEADER), read(LEDGER_HEADER)),
                       (os.path.basename(LEDGER_SOURCE), read(LEDGER_SOURCE)),
                       (os.path.basename(INVENTORY_HEADER), read(INVENTORY_HEADER)),
                       (os.path.basename(INVENTORY_SOURCE),
                        read(INVENTORY_SOURCE) if inventory_source is None else inventory_source),
                       ("driver.m", DRIVER)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    binary = os.path.join(work, "report")
    built = subprocess.run(
        [cc, "-x", "objective-c", "-fobjc-arc", "-isysroot", sdk, "-Wall", "-Werror",
         "-framework", "Foundation", os.path.join(work, "driver.m"),
         os.path.join(work, os.path.basename(SOURCE)),
         os.path.join(work, os.path.basename(LEDGER_SOURCE)),
         os.path.join(work, os.path.basename(INVENTORY_SOURCE)), "-o", binary],
        capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr).strip()[-2000:]
    ran = subprocess.run([binary], capture_output=True, text=True)
    return ran.returncode, (ran.stdout + ran.stderr).strip()


def main():
    cc, sdk = apple_toolchain.clang_and_sdk("the diagnostics report harness")
    shipping = read(SOURCE)

    with tempfile.TemporaryDirectory() as work:
        code, log = compile_and_run(shipping, work, cc, sdk)
        if code is None:
            check(False, "the shipping builder does not compile:" + log)
            return report_result()
        check(code == 0 and "RUN PASSED" in log,
              "the shipping builder passes every case"
              if code == 0 else "the shipping builder failed a case:" + log)
        if code != 0 or "RUN PASSED" not in log:
            return report_result()
        # The case list is asserted as well as its verdict. The count travels in the binary's
        # own output rather than being counted from this file's text, because what a report
        # quotes has to be something the run printed: a harness whose input cases were quietly
        # deleted still reports success, and only the number notices.
        run_line = next((line for line in log.splitlines() if line.startswith("RUN PASSED")), "")
        checks = int(run_line.split("(")[1].split(" ")[0]) if "(" in run_line else 0
        check(checks >= MIN_DRIVER_CHECKS,
              "the harness runs its whole case list (%d checks in the shipped binary)" % checks
              if checks >= MIN_DRIVER_CHECKS else
              "the harness runs only %d of at least %d checks; a case list that shrinks in "
              "silence reports success on less than it used to test"
              % (checks, MIN_DRIVER_CHECKS))

    with tempfile.TemporaryDirectory() as work:
        found, log = analyze(shipping, work, cc, sdk)
        check(not found,
              "the static analyzer finds nothing in the shipping builder"
              if not found else
              "the static analyzer found %d thing(s) in the shipping builder:\n    %s"
              % (len(found), "\n    ".join(found)))

    for label, old, new in ANALYZER_DEFECTS:
        if old not in shipping:
            check(False, "the analyzer defect '%s' no longer matches the source" % label)
            continue
        with tempfile.TemporaryDirectory() as work:
            found, log = analyze(shipping.replace(old, new, 1), work, cc, sdk)
            check(bool(found),
                  "the analyzer reports it when %s" % label
                  if found else "NOT CAUGHT (%s): %s" % (label, log))

    for label, old, new in MUTATIONS:
        if old not in shipping:
            check(False, "the mutation '%s' no longer matches the source" % label)
            continue
        with tempfile.TemporaryDirectory() as work:
            code, log = compile_and_run(shipping.replace(old, new, 1), work, cc, sdk)
            caught = code == 1 and "FAIL " in log
            check(caught, "the run fails when %s" % label
                  if caught else "NOT CAUGHT (%s): %s" % (label, log))

    inventory_source = read(INVENTORY_SOURCE)
    for label, old, new in INVENTORY_MUTATIONS:
        if inventory_source.count(old) != 1:
            check(False, "the inventory mutation '%s' must match exactly once" % label)
            continue
        with tempfile.TemporaryDirectory() as work:
            code, log = compile_and_run(
                shipping, work, cc, sdk, inventory_source.replace(old, new, 1))
            caught = code == 1 and "FAIL " in log
            check(caught, "the run fails when %s" % label
                  if caught else "NOT CAUGHT (%s): %s" % (label, log))

    live = read(LIVE)
    for needed, why in (
            ("IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)", "the input monitoring answer"),
            ("CGPreflightScreenCaptureAccess()", "the screen recording answer"),
            ("NSBonjourServices", "the declared browse services"),
            ("_nvstream._tcp", "the GameStream service the report has to name"),
            ("LoggerCuratedLogPath()", "the log the report reads"),
            ("AppTranslocation", "the gatekeeper mount that voids a grant"),
            ("getHosts", "the hosts the player has paired")):
        check(needed in live, "the report carries %s" % why)
    for forbidden in (".mac", ".serverCert", ".uuid"):
        check(not re.search(r"host%s\b" % re.escape(forbidden), live),
              "the collector never reads %s, which the report promises to leave out" % forbidden)

    live_builds = read(LIVE)
    check("inputSectionWithSummary:" in live_builds and
          "InputDiagnosticsLedger.sharedLedger.summary" in live_builds,
          "the report a player copies asks the ledger for the input block, rather than "
          "carrying a block nothing fills")
    check("controllersSectionWithSnapshot:" in live_builds and
          "MLControllerInventory.sharedInventory.snapshot" in live_builds,
          "the report asks the shared formatter for the controllers block, handing it the "
          "recorded inventory rather than assembling a block by guessing from product strings")
    inventory_builds = read(HID_INVENTORY)
    check("[inventory noteSessionStartedWithDriverName:" in inventory_builds and
          "MLControllerDriverNameForIndex(self.controllerDriver)" in inventory_builds and
          "[inventory recordEntries:entries]" in inventory_builds and
          "MLControllerFamilyForIds(entry.vendorId, entry.productId)" in inventory_builds,
          "the bus reader records what this HID manager sees and classifies it by the same "
          "table a report prints, naming the controller driver the stream used")
    hid = read(HID)
    check("recordMouseInputPathStateIntoLedger" in hid and
          "[self recordMouseInputPathStateIntoLedger];" in hid and
          hid.count("InputDiagnosticsLedger sharedLedger") >= 3,
          "the input code records the strategy, the CoreHID outcome and the sender that moved "
          "the pointer, from the places that decide them")
    stream_diag = read(STREAM_DIAG)
    check("noteStreamStarted" in stream_diag and "noteStreamEndedWithReason:" in stream_diag and
          stream_diag.count("[self publishInputDiagnosticsToLedger];") >= 3,
          "a session opens, publishes on every sample, and closes in the ledger")
    check("Input/InputDiagnosticsLedger.m" in read(PBX),
          "the ledger is a member of the target, so something compiles it")

    ledger_props = re.findall(r"@property[^;]*?\b([A-Za-z0-9_]+);", read(LEDGER_HEADER))
    identity = {"uuid", "macAddress", "serverCert", "clientCert", "pairingSecret", "pin",
                "password", "homePath", "ipAddress", "hostName"} & set(ledger_props)
    check(not identity,
          "the input summary holds behaviour and no identity, so a pasted report cannot carry "
          "the player's host"
          if not identity else
          "the input summary declares identity fields: %s" % sorted(identity))

    hosts = read(HOSTS)
    check("Pairing Failed" in hosts and "Copy Diagnostics" in hosts and
          "writeCurrentReportToPasteboard" in hosts,
          "the pairing failure alert offers the report, rather than waiting to be asked")
    pane = read(APP_PANE)
    check("Copy Diagnostics Report…" in pane and
          "Diagnostics Report Copied" in pane and
          "Diagnostics Report Unavailable" in pane,
          "the settings pane carries the button and says whether it worked")
    check("DiagnosticsReportBuilder+Live.h" in read(BRIDGE),
          "the class reaches Swift, so the settings button compiles")

    return report_result()


def report_result():
    if failures:
        print("\n%d diagnostics-report failure(s)" % len(failures))
        return 1
    print("\n0 diagnostics-report failures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
