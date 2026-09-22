#!/usr/bin/env python3
"""Fail an xcodebuild log that carries a warning in first-party sources.

The rule is old; this file is not the rule, it is the rule having a home. It used to live as an
inline ``grep`` inside the build job, and ``scripts/local-gates.sh`` builds its list out of the
``python3 scripts/*.py`` calls in the workflow, so a check written as shell never appeared on that
list and never ran on any laptop. The tree therefore had a gate whose only run happened after a
push, which is how a Swift file reached a runner with

    warning: left side of nil coalescing operator '??' has non-optional type 'String'

in it: the build succeeded, every local gate passed, and the same log -- built locally, sitting in
``/tmp`` -- contained the line that would have failed CI. A check that only CI can run is not a
local gate, and a local gate nobody runs is a comment.

Two rules are in force and both are the interesting half. First-party sources stay warning-free;
vendored sources keep their own diagnostics, because a warning inside an OpenSSL umbrella header is
a fact about OpenSSL, and a gate that reports it is a gate people learn to ignore.
"""
import argparse
import os
import re
import sys

# Vendored, generated, and tool-side noise. The list is a policy: each entry names why the
# warning it suppresses is somebody else's to fix.
VENDORED = (
    "xcframeworks/",        # prebuilt FFmpeg and Opus headers
    "moonlight-common",     # the shared protocol library, vendored as a submodule
    "Packages/",            # Swift Package checkouts
    "libs/openssl",         # the OpenSSL source drop
    "libs/OpenSSL",
)
TOOL_NOISE = (
    "appintentsmetadataprocessor",   # "Metadata extraction skipped", with no AppIntents to find
    "libtool",                       # "'win32.o' has no symbols", from a vendored object
)
FIRST_PARTY = "Limelight/"


def classify(text):
    """Return (first_party_warnings, suppressed_warnings) found in an xcodebuild log."""
    first_party, suppressed = [], []
    for line in text.splitlines():
        if "warning: " not in line:
            continue
        if any(marker in line for marker in VENDORED + TOOL_NOISE):
            suppressed.append(line.strip())
        elif FIRST_PARTY in line:
            first_party.append(line.strip())
        # A warning outside both sets names no first-party path: nothing here to hold anybody to.
    return first_party, suppressed


def self_test():
    """Both directions, plus the exact line this gate was written over."""
    problems = []

    def check(ok, message):
        if not ok:
            problems.append(message)
        print("%s %s" % ("ok  " if ok else "FAIL", message))

    swift = ("2026-09-22 14:11:52.900 appintentsmetadataprocessor[15313:45900] warning: "
             "Metadata extraction skipped. No AppIntents.framework dependency found.\n"
             "/Users/runner/work/x/x/Limelight/macOS/ViewControllers/SettingsDevicesPane.swift:"
             "390:35: warning: left side of nil coalescing operator '??' has non-optional type "
             "'String', so the right side is never used\n"
             "libtool: warning: 'win32.o' has no symbols\n"
             "../libs/openssl/rand.h:23:10: warning: non-portable path to file '<openssl/evp.h>'\n"
             "/Users/runner/work/x/x/moonlight-common/src/stream.c:17: warning: unused variable "
             "'seq'\n")
    first, suppressed = classify(swift)
    check(len(first) == 1 and "SettingsDevicesPane.swift" in first[0],
          "the warning that cost a red run is reported, whatever else the log contains")
    check(len(suppressed) == 4,
          "the vendored and tool-side noise is counted as suppressed, not ignored")

    clean = ("libtool: warning: 'awdl.o' has no symbols\n"
             "../libs/OpenSSL/include/openssl/evp.h:1:1: warning: duplicate declaration\n"
             "2026-09-22 14:11:52.900 appintentsmetadataprocessor[1:2] warning: "
             "Metadata extraction skipped.\n"
             "/Users/runner/x/Packages/Whatever/Source.swift:1:1: warning: unused import\n")
    first, suppressed = classify(clean)
    check(not first and len(suppressed) == 4,
          "a log whose only warnings belong to other people passes")

    objc = "ScanDependencies ... Limelight/Stream/DeviceRedirectionPanelModel.m\n" \
           "/x/Limelight/Stream/DeviceRedirectionPolicy.m:320:9: warning: unused variable\n"
    first, _ = classify(objc)
    check(len(first) == 1 and "DeviceRedirectionPolicy.m" in first[0],
          "an Objective-C warning is held to the same bar as a Swift one")

    # The rule lives here now, in one place. An inline copy in the workflow would drift the way
    # two copies of any rule in this repository drift once they are allowed to exist, and the
    # copy that drifts is the copy people read.
    workflow = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                            ".github", "workflows", "build.yml")
    lines = []
    if os.path.exists(workflow):
        lines = open(workflow, encoding="utf-8").read().splitlines()
    check(any("build-warning-audit.py" in line for line in lines),
          "the workflow calls this gate, so local-gates.sh can run it on a laptop too")
    BACKSLASH = chr(92)
    greps = [line for line in lines
             if "warning: " in line and line.rstrip().endswith(BACKSLASH)]
    check(not greps,
          "no inline copy of the warning rule is left in the workflow to drift from this one"
          if not greps else "the workflow still greps for warnings itself: %d line(s)" % len(greps))
    return problems


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", action="append", default=[],
                        help="an xcodebuild log to read; repeatable")
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args(argv)

    if arguments.self_test:
        problems = self_test()
        print("%d build-warning self-test failures" % len(problems))
        return 1 if problems else 0

    if not arguments.log:
        print("build-warning-audit: nothing to check. Pass --log once per xcodebuild log, the "
              "same logs the build job writes. This gate reads a compiler transcript, so it "
              "cannot substitute a guess for one; it does not build the tree itself.")
        return 0

    failures = 0
    for path in arguments.log:
        if not os.path.exists(path):
            print("build-warning-audit failed: no log at %s" % path)
            failures += 1
            continue
        with open(path, encoding="utf-8", errors="replace") as handle:
            first, suppressed = classify(handle.read())
        for line in first:
            print("first-party warning: %s" % line.split(": warning: ")[-1])
        if first:
            print("%s: %d first-party warning(s), %d vendored warning(s) ignored"
                  % (path, len(first), len(suppressed)))
            failures += 1
        else:
            print("%s: first-party sources are warning-free (%d vendored warning(s) ignored)"
                  % (path, len(suppressed)))
    print("%d build-warning failures" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
