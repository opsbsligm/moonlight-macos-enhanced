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
import os, re, subprocess, sys, tempfile, time
import hashlib
import importlib.util
from concurrent.futures import ThreadPoolExecutor

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
CHECKER = "scripts/hardware-acceptance-check.py"

# The floor, not a claim about the exact number: the shipped binary prints how many checks it
# actually ran, and this refuses a run that quietly lost cases. Raised from 68 when the
# machine-readable block became part of the report rather than dead code, from 105 when
# Wave O-1 named the protocol id that has no layout family, and from 109 when Wave S added the
# export shape -- a build identity that survives its own secret scrub, the canonical byte form an
# exported file has to hold, and the write that produces it. A floor that stays behind the real
# count is how a case list disappears without anyone noticing.
MIN_DRIVER_CHECKS = 134

failures = []


def check(ok, message):
    print("%s %s" % ("ok  " if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def _worker_count(job_count, ceiling=4):
    """How many harness compiles may run at once.

    The job that drives this script has a ten-minute ceiling on a single shared Mac runner, and
    pipeline 779 job 4496 spent 465 of its 601 seconds inside this file. The same file locally
    measures 60.0s wall for 38.0s user and 8.2s sys on eight cores -- 0.77 cores busy, because
    each of its 36 clang compiles and 2 analyzer runs starts only after the one before it ended.
    The runs are independent and each owns a
    `tempfile.TemporaryDirectory`, so the serial ordering was never doing work the wide form
    cannot do. Measured twice on the same commit, the serial control run second on a warmer
    cache: 24.6s wide against 60.0s serial, with identical verdicts -- which is what
    `scheduler_self_test` exists to keep true.

    Four rather than eight: the runner takes two concurrent pipelines, and a gate that starves
    the build beside it is a gate that breaks the pipeline it protects.
    """
    try:
        cpus = os.cpu_count() or 1
    except Exception:
        cpus = 1
    return max(1, min(ceiling, cpus, job_count))


def _call_job(job):
    """Call one harness job, turning a crash into a refusal so no job can vanish.

    A job that raises has proved nothing, which is a refusal and not a pass -- and it is a line
    rather than a silence, because a gate whose failing case disappeared prints a clean tree.
    """
    try:
        return job()
    except Exception as error:
        return (False, "a harness job died and proved nothing: %s: %s"
                % (type(error).__name__, error))


def run_jobs(jobs, report=check, workers=None):
    """Run toolchain-heavy jobs concurrently and report them in the planned order.

    Each job is a callable returning `(ok, message)`, with the message composed inside the job,
    so a wide run prints the same words in the same order a one-core run does: `pool.map` hands
    back results in the order the jobs were planned, not the order they finished. `report` is
    injectable so the scheduler's own self-test can grade it without writing into the run's real
    failure list.
    """
    if workers is None:
        workers = _worker_count(len(jobs))
    if workers <= 1:
        for job in jobs:
            report(*_call_job(job))
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        verdicts = list(pool.map(_call_job, jobs))
    for ok, message in verdicts:
        report(ok, message)


def acceptance_checker():
    """The shipping acceptance checker, loaded from the tree rather than reimplemented here.

    The producer and the consumer of a diagnostics report each had a green light and the seam
    between them had none: the builder asserted that a commit-shaped string appeared somewhere in
    its text, the checker graded only the fixture it carries in its own file, and a real export
    still graded every row of an acceptance matrix UNKNOWN while CI stayed green. A gate that
    copied the checker's parsing rules into this file would have the same hole as a gate that
    copied its wording -- it would pass while the real consumer rejected. So the real module is
    imported, and the real file on disk is what gets handed to it.
    """
    spec = importlib.util.spec_from_file_location(
        "ml_hardware_acceptance_check", os.path.join(ROOT, CHECKER))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def grade_text(module, text):
    """Hand the exported bytes to the checker's own parser. Returns `(accepted, detail)`.

    Text mode is not a convenience: it is how the checker reads a report off disk, so a separator
    the builder failed to fold would break lines here that the hashed bytes still count as one.
    """
    try:
        machine = module.parse_machine(text)
    except module.ReportError as error:
        return False, "the checker refused the export: %s" % error
    return module.build_identity(machine)


def export_with(source, cc, sdk, inventory_source=None):
    """Build and run the harness, and return the export the shipping writer put on disk.

    `(code, log, export_text)`; `export_text` is None when the run wrote no file. The driver
    keeps going after a failed check, so a mutated build that fails its own assertions still
    writes a report -- which is what lets the consumer, rather than the producer, decide whether
    a defect is visible from its side. The bytes come back as text rather than a path because the
    working directory is gone by the time the caller reads them.
    """
    with tempfile.TemporaryDirectory() as work:
        dump = os.path.join(work, "export.txt")
        code, log = compile_and_run(source, work, cc, sdk, inventory_source, dump_path=dump)
        if code is None:
            return None, log, None
        if not os.path.exists(dump):
            return code, log, None
        with open(dump, encoding="utf-8") as handle:
            return code, log, handle.read()


def scheduler_self_test():
    """Prove that running the jobs concurrently cannot change what the gate says.

    Parallelism is the kind of change that buys speed with honesty, so the scheduler is graded
    rather than trusted. The same planned jobs run one core deep and four deep, and the two
    transcripts have to match exactly -- same verdicts, same order, same count -- over a job
    list whose jobs finish in the opposite order to the one they were planned in, plus a job
    that fails and a job that raises. A scheduler that reported jobs as they completed, or lost
    a failing one, is caught here rather than in a CI log where a missing line just looks like
    nobody wrote it.
    """
    def transcript(workers):
        seen = []
        # Staggered sleeps, descending: the last job finishes first, so a scheduler that reported
        # on completion order would produce a different transcript than the planned order. The
        # spacing is in milliseconds because this self-test runs on every pass of the gate, and a
        # scheduler check that costs the gate more than the compiles it protects is not a check.
        jobs = [lambda index=index: (time.sleep((24 - index) * 0.004),
                                     (index % 3 != 0, "job %d" % index))[1]
                for index in range(24)]
        jobs.append(lambda: (_ for _ in ()).throw(RuntimeError("the probe would not build")))
        run_jobs(jobs, report=lambda ok, message: seen.append((ok, message)), workers=workers)
        return seen

    serial = transcript(1)
    parallel = transcript(_worker_count(25, ceiling=4))
    check(len(parallel) > 1 or len(serial) == len(parallel),
          "the wide path is really wide on this host (%d workers for 25 jobs)"
          % _worker_count(25, ceiling=4))
    check(serial == parallel,
          "the concurrent scheduler returns the same verdicts in the same order as a serial run"
          if serial == parallel else
          "the concurrent scheduler disagrees with the serial one: %s"
          % next((("job %d: %r vs %r" % (index, a, b))
                  for index, (a, b) in enumerate(zip(serial, parallel)) if a != b),
                 "%d reports vs %d" % (len(serial), len(parallel))))
    check(len(serial) == 25 and serial[-1][0] is False,
          "a job that dies is reported as a refusal rather than vanishing"
          if len(serial) == 25 and serial[-1][0] is False else
          "a job that died was not reported as a refusal (%d reports)" % len(serial))
    check(sum(1 for ok, _ in serial if not ok) == 9,
          "the scheduler's own case list still contains the failures it must carry"
          if sum(1 for ok, _ in serial if not ok) == 9 else
          "the scheduler's case list carries %d refusals, expected 9"
          % sum(1 for ok, _ in serial if not ok))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return handle.read()


DRIVER = r'''
#import <Foundation/Foundation.h>
#import <CommonCrypto/CommonDigest.h>
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

// The hex digest of the bytes the builder says a file must hold. The checker hashes a report
// with Python's hashlib over the file's bytes, so a byte the builder adds or drops moves every
// declaration bound to that report. Printing the digest lets the Python side re-hash the same
// text on its own and compare: two readers agreeing is the only proof that the shape written and
// the shape graded are one shape.
static NSString *sha256Hex(NSData *data) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes, (CC_LONG)data.length, digest);
    NSMutableString *hex = [NSMutableString stringWithCapacity:CC_SHA256_DIGEST_LENGTH * 2];
    for (int index = 0; index < CC_SHA256_DIGEST_LENGTH; index++) {
        [hex appendFormat:@"%02x", digest[index]];
    }
    return hex;
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
        // The build identity is spared, so the rule that spares it has to be shown to spare
        // nothing else. Each case below is a 40-hex run that is NOT the builder's own
        // `ml.build.git_commit=<40 lowercase hex>` line, and every one still has to leave.
        check([[DiagnosticsReportBuilder redactString:
                    @"log 0123456789abcdef0123456789abcdef01234567 tail"]
                   rangeOfString:@"[redacted-blob]"].location != NSNotFound,
              "a 40-hex run in ordinary prose is still scrubbed -- the exemption is one whole "
              "assignment line, not every long hex string");
        check([[DiagnosticsReportBuilder redactString:
                    @"ml.build.git_checksum=0123456789abcdef0123456789abcdef01234567"]
                   rangeOfString:@"[redacted-blob]"].location != NSNotFound,
              "a similar key name does not buy an exemption");
        check([[DiagnosticsReportBuilder redactString:
                    @"ml.build.git_commit=0123456789ABCDEF0123456789ABCDEF01234567"]
                   rangeOfString:@"[redacted-blob]"].location != NSNotFound,
              "an uppercase run is not a commit this builder writes, so it is still scrubbed");
        check([[DiagnosticsReportBuilder redactString:
                    @"ml.build.git_commit=0123456789abcdef0123456789abcdef0123456"]
                   rangeOfString:@"[redacted-blob]"].location != NSNotFound,
              "a truncated run is not a commit either");
        check([[DiagnosticsReportBuilder redactString:
                    @"ml.build.git_commit=0123456789abcdef0123456789abcdef0123456789"]
                   rangeOfString:@"[redacted-blob]"].location != NSNotFound,
              "a longer run is not a commit either, so the exemption cannot be widened by "
              "padding a secret out to forty characters");
        // The builder writes the commit as a line of its own, so a line that carries this key
        // and more beside it is not the builder's line -- it came from a log, and forfeits the
        // exemption. Every long run on it then leaves, the commit-shaped one included. That is
        // the safe direction to fail in: the checker grades such a report as unknown rather than
        // a report full of logs grading a secret as a build identity.
        check([[DiagnosticsReportBuilder redactString:
                    @"ml.build.git_commit=0123456789abcdef0123456789abcdef01234567 spare MVJubm5uNTY3ODlmZGVmYQ=="]
                   rangeOfString:@"[redacted-blob]"].location != NSNotFound &&
               [[DiagnosticsReportBuilder redactString:
                     @"ml.build.git_commit=0123456789abcdef0123456789abcdef01234567 spare MVJubm5uNTY3ODlmZGVmYQ=="]
                    rangeOfString:@"0123456789abcdef0123456789abcdef01234567 spare"].location == NSNotFound,
              "a line that only looks like the build identity keeps the full scrub, so the "
              "exemption cannot be talked into spareing a secret sharing its line");
        check([[DiagnosticsReportBuilder redactString:@"nothing here"]
                   rangeOfString:@"\001"].location == NSNotFound,
              "the internal stand-in for a spared commit never survives into a report, so no "
              "reader ever sees a byte they cannot type");

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
        check(MLControllerFamilyForIds(0x057E, 0x2006) == MLControllerFamilyNintendo &&
              MLControllerFamilyForIds(0x057E, 0x2007) == MLControllerFamilyNintendo,
              "a lone left or right Joy-Con is named Nintendo, matching the HID path");
        check(MLControllerFamilyForIds(0x1234, 0x5678) == MLControllerFamilyUnknown &&
              MLControllerProtocolTypeForFamily(MLControllerFamilyUnknown) == 0x00,
              "an unknown pad stays unknown and maps to LI_CTYPE_UNKNOWN");
        // Wave O-1: the Steam Controller is the one protocol id with no layout family behind
        // it, so the sender and the report would need two answers unless one table names it.
        check(MLControllerFamilyForIds(0x28DE, 0x1142) == MLControllerFamilyUnknown,
              "a Steam Controller has no HID layout family: it reads through the standard layout");
        check(MLControllerProtocolTypeName(0x04) != nil &&
              [MLControllerProtocolTypeName(0x04) isEqualToString:@"steam"],
              "LI_CTYPE_STEAM has a report name even though no family produced it");
        check(MLControllerProtocolTypeName(0x01) != nil &&
              [MLControllerProtocolTypeName(0x01) isEqualToString:@"xbox"] &&
              [MLControllerProtocolTypeName(0x02) isEqualToString:@"ps"] &&
              [MLControllerProtocolTypeName(0x03) isEqualToString:@"nintendo"] &&
              MLControllerProtocolTypeName(0x00) == nil &&
              MLControllerProtocolTypeName(0x05) == nil,
              "the names the family table owns are unchanged and an id nobody sends has no name");
        // The report path, not just the name table: a Steam arrival is the one announced
        // type with no family behind it, so this is where an `unknown` would leak in.
        MLControllerInventory *steamInventory = MLControllerInventory.new;
        [steamInventory noteSessionStartedWithDriverName:@"AppleUserHIDDrivers"];
        [steamInventory noteControllerArrival:0 protocolType:0x04];
        NSString *steamText = [[DiagnosticsReportBuilder
            controllersSectionWithSnapshot:steamInventory.snapshot].lines
            componentsJoinedByString:@"\n"];
        check([steamText rangeOfString:@"player 0=steam"].location != NSNotFound &&
              [steamText rangeOfString:@"unknown"].location == NSNotFound,
              "the report names an announced Steam type rather than calling it unknown");
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
              [idleText rangeOfString:@"no (0.1 probe"].location == NSNotFound &&
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
        [inventory noteControllerArrival:0 protocolType:0x02];
        [inventory noteControllerArrival:1 protocolType:0x03];
        NSString *announced = [[DiagnosticsReportBuilder
            controllersSectionWithSnapshot:inventory.snapshot].lines componentsJoinedByString:@"\n"];
        check([announced rangeOfString:@"controller arrivals sent to host: yes"].location != NSNotFound &&
              [announced rangeOfString:@"advertised controller type/caps: player 0=ps player 1=nintendo caps=analog triggers+rumble"].location != NSNotFound,
              "recorded arrivals print the types the host was told, per player slot, with the capability set");
        [inventory noteSessionStartedWithDriverName:@"MFi"];
        NSString *freshSession = [[DiagnosticsReportBuilder
            controllersSectionWithSnapshot:inventory.snapshot].lines componentsJoinedByString:@"\n"];
        check([freshSession rangeOfString:@"controller arrivals sent to host: no"].location != NSNotFound,
              "a new session starts with no arrivals of its own, so a re-plug cannot ride the old record");
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

    {
        // The feature-state block. It exists because every real-device acceptance check asks
        // "what is this build actually doing", and a screenshot of a settings pane answers what
        // the player wrote -- which is not the same number whenever the stream clamps.
        DiagnosticsFeatureState *bare = DiagnosticsFeatureState.new;
        NSString *nothing = [[DiagnosticsReportBuilder
            featureStateSectionWithState:bare].lines componentsJoinedByString:@"\n"];
        check([nothing rangeOfString:@"no active stream"].location != NSNotFound &&
              [nothing rangeOfString:@"received="].location == NSNotFound,
              "a build with no stream says nothing was measured, rather than printing zeros "
              "that read as a stream that received nothing");
        check([nothing rangeOfString:@"no stream window"].location != NSNotFound &&
              [nothing rangeOfString:@"reconnect backoff: attempt"].location == NSNotFound,
              "and the reconnect line says there was no window to read, not attempt zero of zero");
        check([nothing rangeOfString:@"unknown (no value written)"].location != NSNotFound,
              "a switch this build never wrote reads as unknown, not as off");
        check([nothing rangeOfString:@"mouse mode: unknown"].location != NSNotFound &&
              [nothing rangeOfString:@"pointer path: unknown"].location != NSNotFound,
              "a pointer path that was never recorded says so");
        check([nothing rangeOfString:@"none reported by this build"].location != NSNotFound,
              "a build with no hand-feel parameters says it has none, rather than leaving an "
              "empty block that looks like a shipped default");

        DiagnosticsFeatureState *tuned = DiagnosticsFeatureState.new;
        tuned.profileScope = @"per-host profile";
        tuned.sidebarParams = @[
            [DiagnosticsFeatureParam paramWithLabel:@"edge sensor band"
                                    shippedDefault:12 minimum:8 maximum:16 overrideValue:0],
            [DiagnosticsFeatureParam paramWithLabel:@"edge sensor dwell"
                                    shippedDefault:0.12 minimum:0.06 maximum:0.3 overrideValue:0.2],
            [DiagnosticsFeatureParam paramWithLabel:@"auto collapse"
                                    shippedDefault:0.45 minimum:0.3 maximum:1.0 overrideValue:30],
            [DiagnosticsFeatureParam paramWithLabel:@"idle tab thickness"
                                    shippedDefault:14 minimum:10 maximum:20 overrideValue:4],
        ];
        tuned.switches = @{ @"edgeSensorSummon": @NO, @"imeLocalComposition": @YES };
        tuned.pointerState = @{ @"mouseMode": @"Remote Desktop", @"pointerPath": @"relative" };
        tuned.hasVideoStats = YES;
        tuned.receivedFrames = 1200;
        tuned.decodedFrames = 1198;
        tuned.renderedFrames = 1150;
        tuned.renderedFps = 119.4f;
        tuned.jitterMs = 2.5f;
        tuned.receivedBytes = 32 * 1024 * 1024;
        tuned.videoFormatName = @"HEVC";
        tuned.hasReconnectState = YES;
        tuned.reconnectAttemptCount = 2;
        tuned.reconnectMaxAttempts = 3;
        tuned.reconnectPending = YES;
        NSString *detail = [[DiagnosticsReportBuilder
            featureStateSectionWithState:tuned].lines componentsJoinedByString:@"\n"];
        check([detail rangeOfString:@"edge sensor band: 12 (shipped default)"]
                  .location != NSNotFound,
              "a parameter nobody touched reports the shipped constant and says it is the "
              "shipped constant");
        check([detail rangeOfString:@"edge sensor dwell: 0.2 (player override, shipped 0.12)"]
                  .location != NSNotFound,
              "a written override reports the override as the value in force and keeps the "
              "constant it replaced visible, so an upgrade can be read against the old hand-feel");
        check([detail rangeOfString:@"auto collapse: 1 (clamped from 30, shipped 0.45)"]
                  .location != NSNotFound,
              "an override past the published range reports the boundary the stream uses plus "
              "the number the player wrote -- the whole reason this block exists");
        check([detail rangeOfString:@"idle tab thickness: 10 (clamped from 4, shipped 14)"]
                  .location != NSNotFound,
              "and the same honesty at the bottom of the range");
        check([detail rangeOfString:@"edgeSensorSummon: no"].location != NSNotFound &&
              [detail rangeOfString:@"imeLocalComposition: yes"].location != NSNotFound &&
              [detail rangeOfString:@"backgroundGamepad: unknown"].location != NSNotFound,
              "each switch reports its own answer, and only the switches this build never "
              "touched stay unknown");
        check([detail rangeOfString:@"mouse mode: Remote Desktop"].location != NSNotFound &&
              [detail rangeOfString:@"pointer path: relative"].location != NSNotFound,
              "the pointer path the session settled on is carried");
        check([detail rangeOfString:@"received=1200 decoded=1198 rendered=1150"].location != NSNotFound &&
              [detail rangeOfString:@"fps=119.4"].location != NSNotFound &&
              [detail rangeOfString:@"format=HEVC"].location != NSNotFound &&
              [detail rangeOfString:@"received=32.0MiB"].location != NSNotFound,
              "the video counters arrive with the codec name, so a stutter report says which "
              "decoder was even in use");
        check([detail rangeOfString:@"attempt 2 of 3"].location != NSNotFound &&
              [detail rangeOfString:@"attempt pending: yes"].location != NSNotFound &&
              [detail rangeOfString:@"host confirmed gone: no"].location != NSNotFound,
              "the backoff state machine is described by its own counters");

        DiagnosticsFeatureState *formatless = DiagnosticsFeatureState.new;
        formatless.hasVideoStats = YES;
        NSString *noFormat = [[DiagnosticsReportBuilder
            featureStateSectionWithState:formatless].lines componentsJoinedByString:@"\n"];
        check([noFormat rangeOfString:@"format=unknown"].location != NSNotFound,
              "a stream whose codec was never recorded says unknown, not an empty field");

        // The block is a report section like any other, so it goes through the same redaction
        // pass. The label is the one field that can carry text from outside the code, so that
        // is where a secret is planted.
        DiagnosticsFeatureState *leaking = DiagnosticsFeatureState.new;
        leaking.sidebarParams = @[
            [DiagnosticsFeatureParam paramWithLabel:@"band /Users/Someone/secret.app"
                                    shippedDefault:12 minimum:8 maximum:16 overrideValue:0],
        ];
        NSString *assembled = [DiagnosticsReportBuilder
            reportFromSections:@[[DiagnosticsReportBuilder featureStateSectionWithState:leaking]]];
        check([assembled rangeOfString:@"/Users/Someone"].location == NSNotFound &&
              [assembled rangeOfString:@"features"].location != NSNotFound,
              "the block is assembled under the redaction pass, so a path in one of its lines "
              "still leaves");

        // The switch list is the block's own contract, and the filter is the only thing
        // between a settings dictionary and it. Both are tested here rather than assumed,
        // because the failure mode is a report that quietly stops mentioning a switch.
        NSArray<NSString *> *keys = [DiagnosticsReportBuilder featureSwitchKeys];
        check(keys.count == 6 &&
              [keys containsObject:@"absoluteMouseMode"] &&
              [keys containsObject:@"relativeMouseAsAbsolute"] &&
              [keys containsObject:@"imeLocalComposition"] &&
              [keys containsObject:@"muteOnFocusLoss"] &&
              [keys containsObject:@"backgroundGamepad"],
              "the block names the switches a player can actually move, so a switch added to "
              "the settings page has to be added here before a report can claim it is off");

        NSDictionary *profile = @{
            @"absoluteMouseMode": @YES,
            @"muteOnFocusLoss": @NO,
            // Not every value a profile holds is a switch. A leftover string, a number for a
            // hand-feel parameter, and a key nobody reads all have to be refused: filtering by
            // the key list is what stops a hand-feel number printing as a yes/no switch.
            @"edgeSensorBandWidthPoints": @30,
            @"someOtherKey": @"yes",
            // A switch key holding something that is not a number is a stale or foreign write.
            // Reading it with boolValue would invent a verdict, so it has to stay unknown.
            @"imeLocalComposition": @"yes",
        };
        NSDictionary *carried = [DiagnosticsReportBuilder featureSwitchesFromPreferences:profile];
        check(carried.count == 2 &&
              [carried[@"absoluteMouseMode"] boolValue] &&
              [carried[@"muteOnFocusLoss"] boolValue] == NO &&
              carried[@"imeLocalComposition"] == nil,
              "the filter keeps only the switches a profile really carries -- an untouched "
              "switch arrives with no value and prints as unknown, and a value that is not a "
              "number is refused rather than read into a verdict by whatever boolValue makes "
              "of it");
        check([DiagnosticsReportBuilder featureSwitchesFromPreferences:nil].count == 0,
              "a build that could not read its settings reports every switch as unknown "
              "instead of inventing a verdict");
    }

    {
        // The machine-readable mirror. It exists so a real-device acceptance run is graded from
        // the report instead of from a screenshot, which makes its contract a parser's contract:
        // one addressable key per fact, an explicit absence for everything unmeasured, and a
        // name that cannot be misread. Each of those is a shape the block can get wrong while
        // still reading fine to a person, so each is checked as text rather than admired.
        NSString *machineText = [[DiagnosticsReportBuilder
            machineStateSectionWithState:DiagnosticsFeatureState.new
                                snapshot:nil].lines componentsJoinedByString:@"\n"];
        check([machineText rangeOfString:@"ml.controllers.present=no"].location != NSNotFound &&
              [machineText rangeOfString:@"ml.video.present=no"].location != NSNotFound &&
              [machineText rangeOfString:@"ml.reconnect.present=no"].location != NSNotFound,
              "a report taken before anything ran says which blocks have nothing to read");
        check([machineText rangeOfString:@"ml.video.frames"].location == NSNotFound &&
              [machineText rangeOfString:@"ml.reconnect.attempt="].location == NSNotFound,
              "an unmeasured counter is absent rather than zero -- a checker that read "
              "rendered=0 would report a host that sent nothing");
        check([machineText rangeOfString:@"ml.switch.imeLocalComposition=unknown"]
                  .location != NSNotFound,
              "a switch this build never wrote stays unknown in the machine block too");
        check([machineText rangeOfString:@"ml.pointer.mouse_mode=unknown"].location != NSNotFound &&
              [machineText rangeOfString:@"ml.pointer.absolute=unknown"].location != NSNotFound,
              "a pointer path never recorded is unknown, not inferred to be relative");
        check([machineText rangeOfString:@"ml.build.git_commit=unknown"].location != NSNotFound &&
              [machineText rangeOfString:@"ml.build.version=unknown"].location != NSNotFound &&
              [machineText rangeOfString:@"ml.build.number=unknown"].location != NSNotFound,
              "a state carrying no build identity says so three times, rather than leaving a "
              "checker to tell \"no identity\" apart from \"no identity key\"");

        DiagnosticsFeatureState *shape = DiagnosticsFeatureState.new;
        shape.profileScope = @"per-host profile for one host";
        shape.sidebarParams = @[
            [DiagnosticsFeatureParam paramWithLabel:@"edge sensor band"
                                    shippedDefault:12 minimum:8 maximum:16 overrideValue:0],
            [DiagnosticsFeatureParam paramWithLabel:@"edge sensor dwell"
                                    shippedDefault:0.12 minimum:0.06 maximum:0.3 overrideValue:0.02],
        ];
        shape.hasVideoStats = YES;
        shape.receivedFrames = 1200;
        shape.renderedFrames = 1150;
        shape.renderedFps = 119.4f;
        shape.receivedBytes = 32 * 1024 * 1024;
        shape.gitCommit = @"0123456789abcdef0123456789abcdef01234567";
        shape.appVersion = @"1.6.0";
        shape.buildNumber = @"2050";
        MLControllerInventorySnapshot *pad = MLControllerInventorySnapshot.new;
        pad.entries = @[ MLControllerEntry.new ];
        NSString *shaped = [[DiagnosticsReportBuilder
            machineStateSectionWithState:shape snapshot:pad].lines componentsJoinedByString:@"\n"];
        // Every non-comment line has to be exactly one assignment, with no spaces anywhere in
        // the key. This is what makes the second line of the block a comment instead of data,
        // and what lets a checker index `ml.param.edge_sensor_band.effective` directly.
        BOOL strict = YES;
        NSMutableArray<NSString *> *stray = [NSMutableArray array];
        for (NSString *line in [shaped componentsSeparatedByString:@"\n"]) {
            if ([line hasPrefix:@"#"]) {
                continue;
            }
            NSRange firstSeparator = [line rangeOfString:@"="];
            if (firstSeparator.location == NSNotFound ||
                [line rangeOfString:@"=" options:0 range:NSMakeRange(firstSeparator.location + 1,
                    line.length - firstSeparator.location - 1)].location != NSNotFound ||
                [[line substringToIndex:firstSeparator.location] rangeOfString:@" "].location != NSNotFound) {
                strict = NO;
                [stray addObject:line];
            }
        }
        if (!strict) {
            printf("    offending lines: %s\n",
                   [[stray componentsJoinedByString:@" | "] UTF8String]);
        }
        check(strict, "every line of the machine block is one key=value with a space-free key"
              " -- the block is data for a checker, not prose");
        check([shaped rangeOfString:@"ml.video.frames.received=1200"].location != NSNotFound &&
              [shaped rangeOfString:@"ml.video.frames.rendered=1150"].location != NSNotFound,
              "the frame counters are separately addressable, so a checker does not split a "
              "sentence to get a number");
        check([shaped rangeOfString:@"ml.video.format=unknown"].location != NSNotFound,
              "a codec that was never recorded reads unknown, not blank and not a guess");
        check([shaped rangeOfString:@"ml.video.bytes=33554432"].location != NSNotFound,
              "the byte counter arrives raw, so a bandwidth check does not redo a division "
              "meant only for a human eye");
        check([shaped rangeOfString:@"ml.param.edge_sensor_band.effective=12"]
                  .location != NSNotFound &&
              [shaped rangeOfString:@"ml.param.edge_sensor_band.shipped=12"]
                  .location != NSNotFound &&
              [shaped rangeOfString:@"ml.param.edge_sensor_band.range=8..16"]
                  .location != NSNotFound &&
              [shaped rangeOfString:@"ml.param.edge_sensor_band.written=none"]
                  .location != NSNotFound &&
              [shaped rangeOfString:@"ml.param.edge_sensor_band.state=shipped"]
                  .location != NSNotFound,
              "a hand-feel parameter reports its value, its constant, its published range and "
              "how it got there, each under its own key");
        // The defect this line exists to catch: a range bound rounded to an integer makes
        // `minimum=0.06` announce itself as `clamped_below_0`, which grades as "below zero".
        check([shaped rangeOfString:@"ml.param.edge_sensor_dwell.state=clamped_below_0.06"]
                  .location != NSNotFound,
              "a clamp keeps the decimal places of the bound it hit, so a fractional dwell "
              "range does not report a bound of zero");
        check([shaped rangeOfString:@"ml.controllers.group_count=1"].location != NSNotFound &&
              [shaped rangeOfString:@"ml.controllers.group_count_is_physical_devices=no"]
                  .location != NSNotFound,
              "the identity-group count states in its own key that it is not a controller "
              "count, so a two-pad acceptance run has to grade host-advertised slots");
        check([shaped rangeOfString:@"ml.controllers.group.0.battery_percent=unknown"]
                  .location != NSNotFound,
              "a pad that never reported a charge is unknown, because zero would grade as an "
              "empty battery");
        check([shaped rangeOfString:@"ml.profile=per-host"].location != NSNotFound,
              "the profile scope is one of two fixed words, so the scope a run was graded "
              "under is machine-comparable");
        check([shaped rangeOfString:@"ml.build.git_commit=0123456789abcdef0123456789abcdef01234567"]
                  .location != NSNotFound,
              "the commit that produced the binary is carried verbatim, so an acceptance "
              "statement is pinned to source rather than to a build count");
        check([shaped rangeOfString:@"ml.build.version=1.6.0"].location != NSNotFound &&
              [shaped rangeOfString:@"ml.build.number=2050"].location != NSNotFound,
              "the version the binary announced itself with is addressable, so a DMG and a "
              "report can be matched without reading the About pane");
        // The same keys, read out of a shipped report rather than out of the section that made
        // them. The block above proves the builder writes a commit; only this one proves the
        // report a player copies still holds it, because every line passes through the redaction
        // scrub on the way out -- and a 40-hex commit is a long run of letters and digits, which
        // is exactly what the blob rule exists to remove. The acceptance checker refuses any
        // report whose commit is not a full 40 hex, so a scrubbed identity does not mark one row
        // unknown, it marks the whole matrix unknown, and the run that produced it is lost.
        NSString *shippedReport = [DiagnosticsReportBuilder
            reportFromSections:@[ [DiagnosticsReportBuilder
                machineStateSectionWithState:shape snapshot:pad] ]];
        check([shippedReport rangeOfString:@"ml.build.git_commit=0123456789abcdef0123456789abcdef01234567"]
                  .location != NSNotFound,
              "the commit survives the redaction scrub, because a report whose identity was "
              "scrubbed grades every row of an acceptance run as unknown");
        check([shippedReport rangeOfString:@"[redacted-blob]"].location == NSNotFound,
              "no blob marker replaces anything in the machine block, so a checker reads the "
              "bytes the build actually named rather than a marker that looks like a value");

        MLControllerInventorySnapshot *advertised = MLControllerInventorySnapshot.new;
        advertised.advertisedControllerArrivals = YES;
        advertised.advertisedControllerTypes = @{ @1: @(MLControllerProtocolTypeForFamily(
                                            MLControllerFamilyPS5)) };
        advertised.driverName = @"MFi";
        NSString *advertisedText = [[DiagnosticsReportBuilder
            machineStateSectionWithState:DiagnosticsFeatureState.new
                                snapshot:advertised].lines componentsJoinedByString:@"\n"];
        check([advertisedText rangeOfString:@"ml.controllers.slot.1=ps"].location != NSNotFound,
              "the type the host was told about is addressable per player slot, which is the "
              "number an acceptance run counts pads by");
        check([advertisedText rangeOfString:@"ml.controllers.caps.analog_triggers=yes"]
                  .location != NSNotFound &&
              [advertisedText rangeOfString:@"ml.controllers.caps.rumble=yes"]
                  .location != NSNotFound,
              "each advertised capability is its own key, so a check for an unimplemented "
              "capability does not have to split a joined bundle");
        check([advertisedText rangeOfString:@"ml.controllers.driver=MFi"].location != NSNotFound,
              "the driver recorded at session start is carried, because the three HID drivers "
              "disagree about the same pad");

        // --- the bytes an exported report file holds -------------------------------
        // An acceptance run grades the file, not the app: the checker hashes the file's bytes and
        // binds every observation to that hash. An editor that appends a blank line, or a CR that
        // survives a paste, changes every byte a declaration was bound to and the whole matrix
        // grades as unknown. So the app writes the file itself, from one canonical shape.
        NSData *clean = [DiagnosticsReportBuilder canonicalReportBytesFromString:
            @"alpha\nbeta\ngamma"];
        check([[[NSString alloc] initWithData:clean encoding:NSUTF8StringEncoding]
                  isEqualToString:@"alpha\nbeta\ngamma\n"],
              "a report gains the one newline that ends a file, and a player's editor cannot "
              "add a second one later");
        check([DiagnosticsReportBuilder canonicalReportBytesFromString:
                   @"alpha\nbeta\ngamma\n"].length == clean.length &&
              [[DiagnosticsReportBuilder canonicalReportBytesFromString:
                    @"alpha\nbeta\ngamma\n\n\n"] isEqualToData:clean],
              "exporting an already-exported report hashes the same, so a round trip through a "
              "file cannot drift from the report the checker was handed");
        check([[DiagnosticsReportBuilder canonicalReportBytesFromString:
                    @"a\r\nb\rc\r\n\r\nd"]
                   isEqualToData:[DiagnosticsReportBuilder
                       canonicalReportBytesFromString:@"a\nb\nc\n\nd"]],
              "CRLF and lone CR fold to one LF each, because a paste through an editor is allowed "
              "to change a line ending but not the report's hash");
        // The checker reads the file in universal-newline text mode and splits its machine block
        // with str.splitlines(), which also breaks on VT, FF, FS, GS, RS, NEL and U+2028/2029.
        // A separator only one of the two folds would make the hashed text and the parsed lines
        // describe different files.
        NSData *exotic = [DiagnosticsReportBuilder canonicalReportBytesFromString:
            [NSString stringWithCharacters:(const unichar[]){'a', 0x0B, 'b', 0x0C, 'c', 0x1C,
                                                           'd', 0x85, 'e', 0x2028, 'f'}
                                    length:11]];
        NSString *exoticText = [[NSString alloc] initWithData:exotic encoding:NSUTF8StringEncoding];
        check([exoticText isEqualToString:@"a\nb\nc\nd\ne\nf\n"],
              "every separator Python splits a line on becomes an LF, so the bytes a hash covers "
              "and the line a key came from stay one file");
        // Trailing blank lines go, because an editor adds one without anyone choosing it. A line
        // that holds a space is kept: folding it would mean deciding the player did not mean what
        // the file says, which is not this method's call to make.
        check([DiagnosticsReportBuilder canonicalReportBytesFromString:@"\n\n\n"].length == 0,
              "a report that says nothing exports as an empty file rather than a newline nobody "
              "can see");
        check([[DiagnosticsReportBuilder canonicalReportBytesFromString:@"   \n\t\n"]
                   isEqualToData:[DiagnosticsReportBuilder
                       canonicalReportBytesFromString:@"   \n\t"]],
              "only the end-of-file newline is normalised, so no whitespace the report actually "
              "carries disappears between the bytes hashed and the bytes read");
        check([DiagnosticsReportBuilder canonicalReportBytesFromString:@""].length == 0,
              "no report exports no bytes");

        NSData *shapedBytes = [DiagnosticsReportBuilder canonicalReportBytesFromString:shaped];
        NSString *shapedText = [[NSString alloc] initWithData:shapedBytes encoding:NSUTF8StringEncoding];
        check(shapedBytes.length > 0 &&
              [shapedText hasSuffix:@"\n"] &&
              [shapedText rangeOfString:@"\n\n"].location == NSNotFound,
              "the machine block a run would actually be graded on exports as one LF-terminated "
              "text with no blank line for a parser to trip over");

        // The whole report, as the settings pane hands it to a file. A single block on its own
        // would be a shape no checker ever sees: `parse_machine` indexes on the `[machine]`
        // header, and only the assembled text carries it. Everything below therefore travels
        // through the same two methods the Export button calls, over the assembled report.
        NSData *exportBytes = [DiagnosticsReportBuilder canonicalReportBytesFromString:shippedReport];
        NSString *exportText = [[NSString alloc] initWithData:exportBytes encoding:NSUTF8StringEncoding];
        check(exportBytes.length > 0 &&
              [exportText hasPrefix:@"moonlight-macos-enhanced diagnostics report\n"] &&
              [exportText rangeOfString:@"[machine]\n"].location != NSNotFound,
              "the exported file is a whole report with the header the checker indexes on, so "
              "the bytes under test are the bytes a player saves rather than a block in isolation");
        check([exportText hasSuffix:@"\n"] && ![exportText hasSuffix:@"\n\n"],
              "exactly one newline ends the exported file, because a second one is a byte the "
              "checker hashes and no reader can see");
        check([[DiagnosticsReportBuilder canonicalReportBytesFromString:exportText]
                   isEqualToData:exportBytes],
              "exporting an exported report hashes the same, so a file round trip cannot drift "
              "from the report a declaration was bound to");
        // The write goes through the production entry point, not a hand-rolled `writeToFile:`,
        // so the atomic option and the error path are the ones a player can actually reach.
        // The default destination keeps the case count independent of the environment: a check
        // that only runs when someone remembered to set a variable is a check the floor number
        // cannot see.
        NSString *dumpPath = NSProcessInfo.processInfo.environment[@"ML_CANONICAL_DUMP"];
        if (dumpPath.length == 0) {
            dumpPath = [NSTemporaryDirectory() stringByAppendingPathComponent:
                @"ml-diagnostics-canonical-probe.txt"];
        }
        NSError *writeError = nil;
        BOOL wrote = [DiagnosticsReportBuilder writeReport:shippedReport
                                                     toURL:[NSURL fileURLWithPath:dumpPath]
                                                     error:&writeError];
        check(wrote && writeError == nil,
              "the report writes without saying why it did not happen");
        check([[NSData dataWithContentsOfFile:dumpPath] isEqualToData:exportBytes],
              "the file on disk holds exactly the canonical bytes, so nothing an editor adds "
              "stands between the report and the hash bound to it");
        printf("CANONICAL-SHA256 %s (%lu bytes)\n",
               sha256Hex(exportBytes).UTF8String, (unsigned long)exportBytes.length);
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
    ("the report claims controller arrivals reached the host before the record says so",
     "        [lines addObject:snapshot.advertisedControllerArrivals\n"
     "            ? @\"controller arrivals sent to host: yes\"\n"
     "            : @\"controller arrivals sent to host: no\"];",
     "        [lines addObject:@\"controller arrivals sent to host: yes\"];"),
    ("the report drops the capability set that goes with the announced types",
     "@\"caps=analog triggers+rumble\"",
     "@\"caps=rumble\""),
    ("the report claims controller type/caps were advertised",
     '@"advertised controller type/caps: not advertised"',
     '@"advertised controller type/caps: sent"'),
    ("the report loses the boundary between HID groups and physical devices",
     "not a physical controller count", "physical controller count"),
    # The features block is the one a player reads to find out what their own settings did,
    # so each of its three answers gets a defect that keeps the line and loses the meaning.
    ("a written override is reported as the shipped constant it replaced",
     "        effective = param.overrideValue;\n", ""),
    ("an out-of-range override reports the number the player wrote, not the boundary in force",
     "        } else if (param.overrideValue > param.maximum) {\n"
     "            effective = param.maximum;",
     "        } else if (param.overrideValue > param.maximum) {\n"
     "            effective = param.overrideValue;"),
    ("an untouched parameter stops saying it is the shipped default",
     '    NSString *state = @"shipped default";',
     '    NSString *state = @"as configured";'),
    ("video counters are printed for a build that never had a stream",
     "    if (!state.hasVideoStats) {",
     "    if (NO) {"),
    ("a switch this build never wrote is reported as off",
     '                                             : @"unknown (no value written)"];',
     '                                             : ReportYesNo(NO)];'),
    ("a pointer path that was never recorded prints as an empty field",
     '    return [NSString stringWithFormat:@"%@: %@", label,\n'
     '                                       value.length > 0 ? value : @"unknown (not recorded)"];',
     '    return [NSString stringWithFormat:@"%@: %@", label, value];'),
    ("the backoff counters are printed where no stream window exists to hold them",
     "    if (!state.hasReconnectState) {",
     "    if (NO) {"),
    ("any value a profile holds counts as a switch, so a hand-feel number reads as a toggle",
      "        if ([value isKindOfClass:[NSNumber class]]) {",
      "        if (value != nil) {"),
    ("a switch the player never touched is reported as on rather than unknown",
      "    NSMutableDictionary<NSString *, NSNumber *> *switches = [NSMutableDictionary dictionary];\n"
      "    for (NSString *key in [self featureSwitchKeys]) {\n"
      "        id value = preferences[key];",
      "    NSMutableDictionary<NSString *, NSNumber *> *switches = [NSMutableDictionary dictionary];\n"
      "    for (NSString *key in [self featureSwitchKeys]) {\n"
      "        id value = preferences[key] ?: @YES;"),
    ("a switch disappears from the block when a build stops mentioning it",
      "    return @[ @\"edgeSensorSummon\", @\"absoluteMouseMode\", @\"relativeMouseAsAbsolute\",\n"
      "              @\"imeLocalComposition\", @\"muteOnFocusLoss\", @\"backgroundGamepad\" ];",
      "    return @[ @\"edgeSensorSummon\", @\"absoluteMouseMode\", @\"relativeMouseAsAbsolute\",\n"
      "              @\"imeLocalComposition\", @\"muteOnFocusLoss\" ];"),
    # The machine block is graded by a checker, so its defects are shape defects: the text still
    # reads correctly to a person, and only a parser notices.
    ("a switch the app could not read degrades to a verdict in the machine block",
     "value ? (value.boolValue ? @\"on\" : @\"off\") : @\"unknown\"]];",
     "value ? (value.boolValue ? @\"on\" : @\"off\") : @\"off\"]];"),
    ("a machine key grows a space, so the fact is no longer addressable",
     '@"ml.video.frames.received=%u"',
     '@"ml.video.frames received=%u"'),
    ("the identity-group count stops saying it is not a device count",
     "    [lines addObject:@\"ml.controllers.group_count_is_physical_devices=no\"];\n",
     ""),
    ("a pad that never reported a charge reads as an empty battery",
     "                              ? [NSString stringWithFormat:@\"%ld\", (long)entry.batteryPercent]\n"
     "                              : @\"unknown\"]];",
     "                              ? [NSString stringWithFormat:@\"%ld\", (long)entry.batteryPercent]\n"
     "                              : @\"0\"]];"),
    ("a clamp reports its bound rounded, so a fractional dwell range announces zero",
     "[NSString stringWithFormat:@\"clamped_below_%@\", ReportNumber(param.minimum)]",
     "[NSString stringWithFormat:@\"clamped_below_%.0f\", param.minimum]"),
    ("the block's own legend becomes data, so every checker reads it as a malformed fact",
     "    [lines addObject:@\"# one key=value per line; ",
     "    [lines addObject:@\"one key=value per line; "),
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

# Three defects whose only witness is the consumer. Each leaves the producer's own assertions
# green or nearly green -- the schema case leaves them entirely green -- while the acceptance
# checker stops being able to grade an exported report at all. That is the seam this file exists
# to close: the builder's text and the checker's parser have to be graded against one file, and a
# planted defect has to be caught by the reader that would actually be broken by it.
ACCEPTANCE_MUTATIONS = (
    ("the build identity is no longer held aside before the secret scrub",
     "    text = [self maskBuildIdentityInString:text heldOut:&identity];\n", ""),
    ("the machine block writes a header the checker does not index on",
     '    return [DiagnosticsReportSection sectionWithTitle:@"machine" lines:lines];\n}',
     '    return [DiagnosticsReportSection sectionWithTitle:@"machine_state" lines:lines];\n}'),
    ("the builder raises its schema without the checker agreeing",
     '[lines addObject:@"ml.schema=1"]', '[lines addObject:@"ml.schema=2"]'),
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


def compile_and_run(source, work, cc, sdk, inventory_source=None, dump_path=None):
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
    # Each run owns its dump file. The jobs go wide, and two of them writing one shared path
    # would have a checker read whichever report finished last rather than the one its own
    # build wrote -- a green gate describing a file that no longer exists.
    env = dict(os.environ)
    if dump_path is not None:
        env["ML_CANONICAL_DUMP"] = dump_path
    ran = subprocess.run([binary], capture_output=True, text=True, env=env)
    return ran.returncode, (ran.stdout + ran.stderr).strip()


def main():
    cc, sdk = apple_toolchain.clang_and_sdk("the diagnostics report harness")
    shipping = read(SOURCE)
    checker = acceptance_checker()

    with tempfile.TemporaryDirectory() as work:
        export_path = os.path.join(work, "export.txt")
        code, log = compile_and_run(shipping, work, cc, sdk, dump_path=export_path)
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

        # The seam between the two halves of an acceptance run, graded here once rather than in a
        # mutated copy. The producer printed a digest of the bytes it wrote; the consumer's own
        # hash of the file it was handed has to be the same number, and its parser has to reach a
        # build identity. Two independent readers agreeing on the digest is the only form of proof
        # available here -- a single reader recomputing its own hash proves nothing about the file.
        with open(export_path, "rb") as handle:
            exported_bytes = handle.read()
        exported_text = exported_bytes.decode("utf-8")
        printed = next((line for line in log.splitlines() if line.startswith("CANONICAL-SHA256")), "")
        producer_digest = printed.split()[1] if len(printed.split()) > 1 else ""
        consumer_digest = checker.report_sha256(exported_text)
        check(producer_digest == consumer_digest ==
              hashlib.sha256(exported_bytes).hexdigest(),
              "the digest the builder printed and the digest the checker computes over the "
              "exported file are one number, so the declaration an acceptance run writes is "
              "bound to the bytes a player can actually save"
              if producer_digest == consumer_digest else
              "the builder printed %s and the checker computes %s for the same file -- a report "
              "whose readers disagree on its hash loses every declaration bound to it"
              % (producer_digest, consumer_digest))
        export_ok, export_detail = grade_text(checker, exported_text)
        check(export_ok,
              "the shipping export is readable by the acceptance checker: %s" % export_detail
              if export_ok else
              "the acceptance checker cannot grade the shipping export: %s" % export_detail)
        check(b"\r" not in exported_bytes and exported_bytes.endswith(b"\n") and
              not exported_bytes.endswith(b"\n\n"),
              "the exported file carries no byte a line reader folds differently than the hash "
              "does, and ends in exactly one newline")

    # Everything below this line is an independent clang run, so it is planned as a list of
    # jobs and run wide. The source-shape guards stay in the planning loop rather than inside a
    # job: a mutation whose anchor no longer matches the source was never tested, and that has
    # to be said whether or not a compiler is available to be busy.
    jobs = []

    def baseline_analyzer_job(source=shipping):
        with tempfile.TemporaryDirectory() as work:
            found, log = analyze(source, work, cc, sdk)
        return (not found,
                "the static analyzer finds nothing in the shipping builder"
                if not found else
                "the static analyzer found %d thing(s) in the shipping builder:\n    %s"
                % (len(found), "\n    ".join(found)))
    jobs.append(baseline_analyzer_job)

    for label, old, new in ANALYZER_DEFECTS:
        if old not in shipping:
            check(False, "the analyzer defect '%s' no longer matches the source" % label)
            continue

        def defect_job(source=shipping.replace(old, new, 1), label=label):
            with tempfile.TemporaryDirectory() as work:
                found, log = analyze(source, work, cc, sdk)
            return (bool(found),
                    "the analyzer reports it when %s" % label
                    if found else "NOT CAUGHT (%s): %s" % (label, log))
        jobs.append(defect_job)

    for label, old, new in MUTATIONS:
        if old not in shipping:
            check(False, "the mutation '%s' no longer matches the source" % label)
            continue

        def mutation_job(source=shipping.replace(old, new, 1), label=label):
            with tempfile.TemporaryDirectory() as work:
                code, log = compile_and_run(source, work, cc, sdk)
            caught = code == 1 and "FAIL " in log
            return (caught, "the run fails when %s" % label
                    if caught else "NOT CAUGHT (%s): %s" % (label, log))
        jobs.append(mutation_job)

    inventory_source = read(INVENTORY_SOURCE)
    for label, old, new in INVENTORY_MUTATIONS:
        if inventory_source.count(old) != 1:
            check(False, "the inventory mutation '%s' must match exactly once" % label)
            continue

        def inventory_job(mutated=inventory_source.replace(old, new, 1), label=label):
            with tempfile.TemporaryDirectory() as work:
                code, log = compile_and_run(shipping, work, cc, sdk, mutated)
            caught = code == 1 and "FAIL " in log
            return (caught, "the run fails when %s" % label
                    if caught else "NOT CAUGHT (%s): %s" % (label, log))
        jobs.append(inventory_job)

    # --- the producer and the consumer graded against one file -------------------------------
    # Everything above asks the builder whether it wrote what it meant. Nothing above asks the
    # acceptance checker whether it can still read it, which is the failure that actually costs a
    # real-device run: an exported report whose build identity was scrubbed, whose block header
    # moved, or whose schema moved ahead of the reader grades every row UNKNOWN, and the whole
    # acceptance session is lost with no CI job to say so.
    for label, old, new_text in ACCEPTANCE_MUTATIONS:
        if shipping.count(old) != 1:
            check(False, "the acceptance mutation '%s' must match the source exactly once" % label)
            continue

        def acceptance_job(mutated=shipping.replace(old, new_text, 1), label=label):
            code, log, exported = export_with(mutated, cc, sdk)
            if code is None:
                return False, "the mutated builder did not compile (%s): %s" % (label, log[-400:])
            if exported is None:
                # A writer that produces no file is the loudest possible refusal, but it has to be
                # said: without this the job would report "the checker accepted it" for a build
                # that never wrote anything to check.
                return True, "the checker stops accepting the export when %s (no file written)" % label
            accepted, detail = grade_text(checker, exported)
            return (not accepted,
                    "the checker stops accepting the export when %s (%s)" % (label, detail)
                    if not accepted else
                    "NOT CAUGHT (%s): the checker still graded the export: %s" % (label, detail))
        jobs.append(acceptance_job)

    wanted = (1 + len(ANALYZER_DEFECTS) + len(MUTATIONS) + len(INVENTORY_MUTATIONS) +
            len(ACCEPTANCE_MUTATIONS))
    check(len(jobs) == wanted,
          "every compile-heavy case reached the scheduler (%d jobs)" % len(jobs)
          if len(jobs) == wanted else
          "only %d of %d compile-heavy cases reached the scheduler; a case that stops being "
          "planned stops being tested" % (len(jobs), wanted))
    scheduler_self_test()
    run_jobs(jobs)

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
    check("featureStateSectionWithState:featureState]" in live_builds and
          "machineStateSectionWithState:featureState" in live_builds,
          "the report a player copies carries both the prose feature block and its "
          "machine-readable mirror, and both come from the shared formatter rather than a "
          "second copy of the wording")
    # The two blocks are only a mirror while they describe one reading. Read the inventory or
    # the feature state twice and a pad pairing between the reads makes the report say one
    # thing in prose and another in keys, which is worse than either being wrong alone. So the
    # invariant is one local per source, handed to both blocks.
    check(re.search(r"DiagnosticsFeatureState \*featureState = \[self liveFeatureState\];",
                    live_builds) and
          live_builds.count("liveFeatureState]") == 1,
          "the feature state is read once and shared, so the prose and the keys cannot "
          "describe two different moments")
    check(re.search(r"MLControllerInventorySnapshot \*inventorySnapshot = "
                    r"MLControllerInventory\.sharedInventory\.snapshot;", live_builds) and
          "controllersSectionWithSnapshot:inventorySnapshot]" in live_builds and
          "snapshot:inventorySnapshot]" in live_builds,
          "the controller inventory is read once and handed to both the prose controllers "
          "block and the machine mirror")
    check("machineStateSectionWithState:featureState" in live_builds,
          "the machine block reaches the report a player copies -- a block nothing assembles "
          "is a block no acceptance run can grade")
    check("featureStateSourceController" in live_builds and
          "featureStateSnapshot" in live_builds,
          "the live report reads its feature state off the running stream, so the numbers it "
          "quotes are the ones that moved the player's sidebar")

    # The host's identifier is the one value this block must never carry, and the collector
    # has to read it to resolve which profile applies. So the rule is stated where it can be
    # checked: the identifier goes into a settings lookup and nowhere into the state object,
    # and the scope line is one of two fixed words.
    snapshot = read(STREAM_DIAG)
    scope_block = snapshot[snapshot.find("- (DiagnosticsFeatureState *)featureStateSnapshot"):]
    scope_block = scope_block[:scope_block.find("\n}\n")] if "\n}\n" in scope_block else scope_block
    check("state.profileScope = [SettingsClass hasHostSpecificProfileFor:hostKey]" in scope_block,
          "the scope line comes from a yes/no question about the profile, never from the key "
          "itself")
    check(not re.search(r"profileScope\s*=\s*[^\n]*hostKey", scope_block.replace(
              "hasHostSpecificProfileFor:hostKey", "")),
          "the host's identifier is never assigned to anything the report prints")
    check("[SettingsClass globalHostKey]" in snapshot,
          "a stream that cannot resolve a host identity names the shared profile through the "
          "store's own constant, rather than retyping it")
    check("MLStreamReconnector *reconnector = self.reconnector;" in scope_block and
          "if (reconnector != nil) {" in scope_block,
          "the backoff counters are reported only when a reconnector exists to hold them, so "
          "a session that never built one does not read as a finished backoff")
    check("MLVideoFormatName(int videoFormat)" in snapshot and
          "VIDEO_FORMAT_MASK_AV1" in snapshot,
          "the codec name is decoded from the negotiated format with the same masks the "
          "on-screen stats use")
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
    # The export button is the only path that produces a file an acceptance run can be graded
    # from, so the wiring is asserted where the canonical bytes are: a control that copies to the
    # clipboard instead of writing the file would leave this whole gate proving a shape nobody can
    # reach, and the failure a player would hit -- a save that silently writes nothing -- is the
    # one an alert has to name.
    check("Export Diagnostics Report…" in pane and
          "DiagnosticsReportBuilder.writeReport" in pane and
          "Diagnostics Report Exported" in pane and
          "Diagnostics Report Unsaved" in pane,
          "the settings pane offers a file export that goes through the canonical writer and "
          "says either way whether the file was written")
    builder_source = read(SOURCE)
    check("options:NSDataWritingAtomic" in builder_source,
          "the report is written atomically, because a cancelled save that leaves half a file "
          "behind still opens, still has a machine block, and grades as a whole report")
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
