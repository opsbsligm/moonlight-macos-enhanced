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
BRIDGE = "Limelight/Moonlight-Bridging-Header.h"
HOSTS = "Limelight/macOS/ViewControllers/HostsViewController.m"
APP_PANE = "Limelight/macOS/ViewControllers/SettingsAppPane.swift"

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

static int gFailures = 0;

static void check(BOOL ok, const char *what) {
    printf("%s %s\n", ok ? "ok  " : "FAIL", what);
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
    }

    if (gFailures == 0) {
        printf("RUN PASSED\n");
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
                       (os.path.basename(SOURCE), source)):
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


def compile_and_run(source, work, cc, sdk):
    for name, text in ((os.path.basename(HEADER), read(HEADER)),
                       (os.path.basename(SOURCE), source),
                       ("driver.m", DRIVER)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    binary = os.path.join(work, "report")
    built = subprocess.run(
        [cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
         "-framework", "Foundation", os.path.join(work, "driver.m"),
         os.path.join(work, os.path.basename(SOURCE)), "-o", binary],
        capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr).strip()[-2000:]
    ran = subprocess.run([binary], capture_output=True, text=True)
    return ran.returncode, (ran.stdout + ran.stderr).strip()[-2000:]


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
            caught = code is not None and code != 0
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
