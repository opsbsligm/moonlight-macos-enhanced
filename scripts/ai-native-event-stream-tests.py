#!/usr/bin/env python3
"""Prove the AI Native semantic event stream and the headless CLI say what an Agent needs.

The 2202 iteration promises two things to an Agent that has no UI: a JSONL file of
semantic runtime events it can tail, and an app binary that answers `--ai-native
report|events` instead of opening a window. Both are cheap to break quietly -- a
renamed event field, a dropped newline, a path that ignores its test override, a hook
that only exists in DEBUG builds -- and a gate that only reads the code cannot tell
the difference, so the emitter is compiled and driven.

The driver issues three known events, flushes, and re-reads the file: one line per
event, each line valid JSON, every line carrying ts/seq/pid/event, seq strictly
increasing from 1, the three event names in the order issued, the data payload
intact, the ISO-8601 timestamp parseable, and the file stable after flushAndClose.
An env override (ML_AI_EVENTS_PATH) must point the file where the test says, and
with no override the file must land in the documented default location.

Then eight defects are planted, one at a time, in the shipping source or its wiring:
the line break dropped, the path hardcoded, the data payload dropped, the sequence
reset, the event field renamed, the pid dropped, the timestamp format truncated, and
the project-file entry deleted. Seven are driven through a recompiled binary that must
fail; the last is a wiring fact that must flip. Every one has to be caught.

Finally the wiring is checked from the text of the tree, because the stream is worth
nothing if an event is never emitted or the CLI never reached: the eight emit sites
(key mapping, edge controls opened/closed, mouse capture both outcomes, stream
start/stop, report generation) must each be present in their file, the headless hook
must sit outside the DEBUG block in the app delegate, and the emitter must be
registered in the project file.

Usage: ai-native-event-stream-tests.py [root]
Exit 0 when the shipping emitter passes, every planted defect is caught, and the
wiring holds.
"""
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
EMITTER_HEADER = "Limelight/macOS/Helpers/AIEventEmitter.h"
EMITTER_SOURCE = "Limelight/macOS/Helpers/AIEventEmitter.m"
APP_DELEGATE = "Limelight/macOS/AppDelegateForAppKit.m"
PBX = "Moonlight.xcodeproj/project.pbxproj"
HID = "Limelight/Input/HIDSupport.m"
STREAM = "Limelight/macOS/ViewControllers/StreamViewController.m"
MOUSE = "Limelight/macOS/ViewControllers/StreamViewController+MouseCapture.m"
MENU = "Limelight/macOS/ViewControllers/StreamViewController+MenuUI.m"
LIVE = "Limelight/macOS/Helpers/DiagnosticsReportBuilder+Live.m"
DEFAULT_REL = os.path.join("Library", "Logs", "Moonlight", "ai-events.jsonl")
PBX_ENTRY = "macOS/Helpers/AIEventEmitter.m,"
MIN_DRIVER_CHECKS = 14

failures = []


def check(ok, message):
    print("%s %s" % ("ok  " if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return handle.read()


def _worker_count(job_count, ceiling=4):
    try:
        cpus = os.cpu_count() or 1
    except Exception:
        cpus = 1
    return max(1, min(ceiling, cpus, job_count))


DRIVER = r'''
#import <Foundation/Foundation.h>
#import "AIEventEmitter.h"

static const char *EVENTS[3] = {"stream_started", "key_mapping", "edge_controls_opened"};
static int gFailures = 0;
static int gChecks = 0;

static void ck(BOOL ok, const char *what) {
    gChecks += 1;
    if (!ok) {
        gFailures += 1;
        printf("FAIL %s\n", what);
    }
}

int main(void) {
    @autoreleasepool {
        const char *expected = getenv("ML_AI_EVENTS_EXPECT");
        const char *override = getenv("ML_AI_EVENTS_PATH");
        ck(expected != NULL || (override != NULL && *override != '\0'),
           "the driver is handed the event file it is to grade");
        NSString *path = [NSString stringWithUTF8String:(expected != NULL ? expected : override)];
        [[NSFileManager defaultManager] removeItemAtPath:path error:NULL];

        [AIEventEmitter emit:@"stream_started" data:nil];
        [AIEventEmitter emit:@"key_mapping"
                        data:@{@"mode": @"typed", @"layout": @"com.apple.keylayout.ABC",
                               @"host": @"host-uuid-1"}];
        [AIEventEmitter emit:@"edge_controls_opened"
                        data:@{@"reason": @"edge-sensor-arrival", @"edge": @(3)}];
        [NSThread sleepForTimeInterval:0.6];
        [AIEventEmitter flushAndClose];

        NSData *raw = [NSData dataWithContentsOfFile:path];
        ck(raw != nil, "the event file exists after flush");
        if (raw == nil) {
            printf("RUN FAILED (%d checks)\n", gChecks);
            return 1;
        }
        NSString *text = [[NSString alloc] initWithData:raw encoding:NSUTF8StringEncoding];
        NSArray<NSString *> *lines = [text componentsSeparatedByString:@"\n"];
        NSMutableArray<NSString *> *nonempty = [NSMutableArray array];
        for (NSString *line in lines) {
            if (line.length > 0) { [nonempty addObject:line]; }
        }
        ck(nonempty.count == 3, "one line per event, no torn or merged line");
        ck([text hasSuffix:@"\n"], "the file ends with a newline");
        NSDateFormatter *format = [[NSDateFormatter alloc] init];
        format.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
        format.timeZone = [NSTimeZone timeZoneWithName:@"UTC"];
        format.dateFormat = @"yyyy-MM-dd'T'HH:mm:ss.SSS'Z'";
        long previous = 0;
        for (NSUInteger i = 0; i < MIN(nonempty.count, (NSUInteger)3); i++) {
            char what[128];
            id object = [NSJSONSerialization JSONObjectWithData:
                             [nonempty[i] dataUsingEncoding:NSUTF8StringEncoding]
                                                      options:0 error:NULL];
            snprintf(what, sizeof(what), "line %lu is valid JSON", (unsigned long)(i + 1));
            ck([object isKindOfClass:[NSDictionary class]], what);
            if (![object isKindOfClass:[NSDictionary class]]) { continue; }
            NSDictionary *record = (NSDictionary *)object;
            snprintf(what, sizeof(what), "line %lu carries ts, seq, pid and event",
                     (unsigned long)(i + 1));
            ck(record[@"ts"] != nil && record[@"seq"] != nil &&
               record[@"pid"] != nil && record[@"event"] != nil, what);
            NSNumber *seq = [record[@"seq"] isKindOfClass:[NSNumber class]] ? record[@"seq"] : nil;
            snprintf(what, sizeof(what), "line %lu continues the sequence at %ld",
                     (unsigned long)(i + 1), (long)previous + 1);
            ck(seq != nil && (long)seq.integerValue == (long)previous + 1, what);
            previous = seq != nil ? (long)seq.integerValue : previous;
            snprintf(what, sizeof(what), "line %lu is the event %s", (unsigned long)(i + 1),
                     EVENTS[i]);
            ck([record[@"event"] isKindOfClass:[NSString class]] &&
               [record[@"event"] isEqualToString:@(EVENTS[i])], what);
            ck([format dateFromString:record[@"ts"] ?: @""] != nil,
               "the timestamp parses as ISO-8601 UTC with milliseconds");
            if (i == 1) {
                ck([record[@"data"][@"mode"] isEqualToString:@"typed"] &&
                   [record[@"data"][@"host"] isEqualToString:@"host-uuid-1"],
                   "the data payload arrives intact");
            }
            if (i == 2) {
                ck([record[@"data"][@"reason"] isEqualToString:@"edge-sensor-arrival"],
                   "the event data keeps its string values");
            }
        }
        [NSThread sleepForTimeInterval:0.15];
        NSData *after = [NSData dataWithContentsOfFile:path];
        ck(after != nil && after.length == raw.length, "flushAndClose leaves the file stable");
        if (gFailures == 0) {
            printf("RUN PASSED (%d checks)\n", gChecks);
            return 0;
        }
        printf("RUN FAILED (%d checks)\n", gChecks);
        return 1;
    }
}
'''


def compile_and_run(work, source, cc, sdk):
    """Build the driver against `source` and run it; return (driver_rc, log)."""
    with open(os.path.join(work, "AIEventEmitter.h"), "w", encoding="utf-8") as handle:
        handle.write(read(EMITTER_HEADER))
    with open(os.path.join(work, "AIEventEmitter.m"), "w", encoding="utf-8") as handle:
        handle.write(source)
    with open(os.path.join(work, "driver.m"), "w", encoding="utf-8") as handle:
        handle.write(DRIVER)
    binary = os.path.join(work, "emitter")
    built = subprocess.run(
        [cc, "-x", "objective-c", "-fobjc-arc", "-isysroot", sdk, "-Wall", "-Werror",
         "-mmacosx-version-min=27.0",
         "-framework", "Foundation", os.path.join(work, "driver.m"),
         os.path.join(work, "AIEventEmitter.m"), "-o", binary],
        capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr).strip()[-1500:]
    override = os.path.join(work, "events.jsonl")
    env = dict(os.environ)
    env["ML_AI_EVENTS_PATH"] = override
    ran = subprocess.run([binary], capture_output=True, text=True, env=env)
    return ran.returncode, (ran.stdout + ran.stderr).strip()


def once(text, needle, replacement=""):
    if text.count(needle) != 1:
        return None
    return text.replace(needle, replacement)


def mutation_case(cc, sdk, mutate):
    """Apply one defect to the shipping source; return (caught, detail)."""
    with tempfile.TemporaryDirectory() as work:
        text = mutate(read(EMITTER_SOURCE))
        if text is None:
            return False, "the planted defect did not match the shipping source"
        code, log = compile_and_run(work, text, cc, sdk)
        if code is None:
            return True, "the defect breaks the build, which is a catch: " + log[:160]
        caught = not (code == 0 and "RUN PASSED" in log)
        return caught, log[-160:]


def report_result():
    if failures:
        print("\n%d ai-native-event-stream failure(s)" % len(failures))
        return 1
    print("\n0 ai-native-event-stream failures")
    return 0


def main():
    pair = apple_toolchain.clang_and_sdk_or_none()
    if pair is None:
        check(False, "no usable clang/SDK on this host for the emitter harness")
        return report_result()
    cc, sdk = pair

    delegate = read(APP_DELEGATE)
    wiring = [
        (re.search(r"- \(void\)applicationWillFinishLaunching.*?"
                   r"MLRunAINativeCLIAndExitIfRequested\(\);.*?#ifdef DEBUG",
                   delegate, re.S) is not None,
         "the --ai-native hook runs before the DEBUG block, so release builds reach it"),
        ('--ai-native' in delegate and '@"events"' in delegate,
         "the headless CLI answers both report and events"),
        (read(PBX).count(PBX_ENTRY) == 1,
         "the emitter is registered in the project file"),
        ('#import "AIEventEmitter.h"' in read(HID) and '@"key_mapping"' in read(HID),
         "the key-mapping choice is emitted at the mapping site"),
        ('@"stream_started"' in read(STREAM) and '@"stream_stopped"' in read(STREAM),
         "stream start and stop are each emitted"),
        ('@"edge_controls_opened"' in read(MOUSE) and
         read(MOUSE).count('@"mouse_capture"') == 2,
         "edge-open and both mouse-capture outcomes are emitted"),
        ('@"edge_controls_closed"' in read(MENU),
         "edge close is emitted"),
        ('@"diagnostics_report"' in read(LIVE) and '#import "AIEventEmitter.h"' in read(LIVE),
         "the report-generation path is emitted"),
    ]
    for ok, message in wiring:
        check(ok, message)

    with tempfile.TemporaryDirectory() as work:
        code, log = compile_and_run(work, read(EMITTER_SOURCE), cc, sdk)
        if code is None:
            check(False, "the shipping emitter does not compile:" + log)
            return report_result()
        check(code == 0 and "RUN PASSED" in log,
              "the shipping emitter passes every driver case"
              if code == 0 and "RUN PASSED" in log else
              "the shipping emitter failed a case:" + log)
        if code != 0 or "RUN PASSED" not in log:
            return report_result()
        run_line = next((line for line in log.splitlines() if line.startswith("RUN PASSED")), "")
        checks = int(run_line.split("(")[1].split(" ")[0]) if "(" in run_line else 0
        check(checks >= MIN_DRIVER_CHECKS,
              "the driver runs its whole case list (%d checks in the shipped binary)" % checks
              if checks >= MIN_DRIVER_CHECKS else
              "the driver runs only %d of at least %d checks" % (checks, MIN_DRIVER_CHECKS))

    mutations = [
        ("the line break is dropped",
         lambda s: once(s, '[lineData appendBytes:(const uint8_t *)"\\n" length:1];\n')),
        ("the path is hardcoded",
         lambda s: once(s, 'const char *override = getenv("ML_AI_EVENTS_PATH");\n')),
        ("the data payload is dropped",
         lambda s: once(s, 'if (data != nil) {\n        line[@"data"] = data;\n    }\n')),
        ("the sequence resets on every event",
         lambda s: once(s, "sequence += 1;", "sequence = 1;")),
        ("the event field is renamed",
         lambda s: once(s, 'line[@"event"] = event;', 'line[@"kind"] = event;')),
        ("the pid field is dropped",
         lambda s: once(s, "line[@\"pid\"] = @(getpid());\n")),
        ("the timestamp format loses milliseconds",
         lambda s: once(s, "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", "yyyy-MM-dd'T'HH:mm:ss'Z'")),
    ]
    with ThreadPoolExecutor(max_workers=_worker_count(len(mutations))) as pool:
        futures = [pool.submit(mutation_case, cc, sdk, mutate)
                   for _, mutate in mutations]
        for (label, _), future in zip(mutations, futures):
            caught, detail = future.result()
            check(caught,
                  "mutation caught: %s" % label if caught else
                  "mutation missed: %s (%s)" % (label, detail))

    # The wiring mutation is a fact about the project file, not the binary: delete the
    # entry and the membership check above has to flip.
    pbx = read(PBX)
    deleted = once(pbx, "\t\t\t\t" + PBX_ENTRY + "\n")
    check(deleted is not None and deleted.count(PBX_ENTRY) == 0,
          "mutation caught: the project-file entry is deleted")

    # The default location, end to end: no override, the file must appear where the
    # header says an Agent looks.
    with tempfile.TemporaryDirectory() as work:
        with open(os.path.join(work, "driver.m"), "w", encoding="utf-8") as handle:
            handle.write(DRIVER)
        with open(os.path.join(work, "AIEventEmitter.h"), "w", encoding="utf-8") as handle:
            handle.write(read(EMITTER_HEADER))
        with open(os.path.join(work, "AIEventEmitter.m"), "w", encoding="utf-8") as handle:
            handle.write(read(EMITTER_SOURCE))
        binary = os.path.join(work, "emitter")
        built = subprocess.run(
            [cc, "-x", "objective-c", "-fobjc-arc", "-isysroot", sdk, "-Wall", "-Werror",
             "-mmacosx-version-min=27.0",
             "-framework", "Foundation", os.path.join(work, "driver.m"),
             os.path.join(work, "AIEventEmitter.m"), "-o", binary],
            capture_output=True, text=True)
        default_path = os.path.join(os.path.expanduser("~"), DEFAULT_REL)
        if os.path.exists(default_path):
            os.remove(default_path)
        env = dict(os.environ)
        env.pop("ML_AI_EVENTS_PATH", None)
        env["ML_AI_EVENTS_EXPECT"] = default_path
        ran = subprocess.run([binary], capture_output=True, text=True, env=env)
        check(built.returncode == 0 and ran.returncode == 0 and
              "RUN PASSED" in ran.stdout and os.path.exists(default_path),
              "with no override the events land at ~/Library/Logs/Moonlight/ai-events.jsonl")
        if os.path.exists(default_path):
            os.remove(default_path)

    return report_result()


if __name__ == "__main__":
    sys.exit(main())
