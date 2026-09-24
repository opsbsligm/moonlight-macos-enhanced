#!/usr/bin/env python3
"""Refuse a first-party object that starts leaking, or starts leaking more.

The first run of this over the settings path found a retain cycle of our own making
(``TemporaryHost.appList`` retains its ``TemporaryApp`s`` and ``TemporaryApp.host``
retains the host back), and the interesting part was not the cycle -- it is written
down in ``docs/memory-ownership.md`` with the fix and the evidence that fix still
needs. The interesting part is that nobody had ever looked, and nothing would have
looked the next time. So this gate exists to keep looking: it drives the Debug probe
build through ``leaks``, reads every leaked block (not just the few stacks ``leaks``
puts in a tree), and compares what it finds against a committed ceiling.

The comparison is deliberately not an equality, and after one afternoon it stopped being a
count either. ``leaks`` answers for the machine it ran on and for the minute it ran on: the
settings page leaks one temporary host graph per host it can see, and how many hosts a
sweep sees is how many ``_nvstream._tcp`` answers arrived before the page drew
(``Limelight/Network/MDNSManager.m`` browses that service), so the host count is not a
property of this repository's code. Measured -- one Debug build, nine sweeps, one laptop,
no code change between them: hosts 4, 5, 5, 5, 6, 6, 6, 6, 8; first-party apps 12, 15, 15,
15, 18, 18, 18, 18, 24, which is exactly three apps per host every single time; 1,418 to
1,968 bytes per host; 6,176 to 15,696 bytes in all. The gate first shipped with absolute
per-class ceilings (18 and 6) and went red twice the same afternoon over numbers no commit
had moved.

So the rules judge the shape the code owns and leave the count the LAN alone: the set of
first-party classes may not grow; the fan-out -- apps per leaked host -- may not exceed the
measured ratio plus a per-host slack; total bytes may not exceed a per-host budget. What
that keeps the teeth on is a second retain cycle over the same graph, which multiplies the
fan-out instead of adding one to it. What it cannot see is a small extra object per host:
one more 80-byte string is 4% of a host's measured bytes, and the byte budget carries a 32%
margin on purpose, because a ceiling that goes red over somebody else's CoreFoundation is a
ceiling somebody mutes. The slack is per host rather than pinned at three because how many
apps a GameStream box publishes is its owner's library, not our code.

A host count of zero is its own answer and is not treated as a clean one: with no host
there is no graph, so the byte budget goes unjudged and says so, while apps leaking with no
host present is refused -- that is a leak with no environment to blame. That gap is now
closed rather than described: the Debug probe takes `ML_RENDER_PROBE_SEED_HOSTS` and writes
one host with three apps through the production `DataManager` before the page opens, so a
runner with no LAN still has a graph to judge. The sweep sets it, the visual probe does not,
a machine with hosts of its own is left alone, and the probe records what it did -- a seed
flag that reached a build which ignores it leaves the report looking exactly like a clean
run, so `probe_problems()` refuses that rather than reading an empty room as a result.

The byte budget judges our objects, not the machine. What the report totals is every leaked
object in the process, and the two machines this gate has run on disagree by more than half
before either has a host in it: 11,792 to 15,696 bytes on a laptop (2,304 of the first of
those ours -- one host plus its three apps is 384 bytes, every sweep, unchanged) against
18,720 on a GitHub runner with not one first-party object among them. A ceiling on that
total is a ceiling on the machine, and it goes red over CoreFoundation, which is how memory
gates get muted. So the rule is 512 first-party bytes per leaked host plus a 128-byte floor
that nothing has needed yet, and the report's total is printed as context instead.

The rule that keeps a reader that read nothing from being green: the report's own summary
says how many blocks leaked, and the audit refuses when it read fewer blocks than that.
Measured, not assumed. The first report this gate was pointed at was a default-tree report
of the same build: its summary said 105 leaks, it detailed 9 of them, and the audit found
no first-party class in it and answered "first-party classes: none" over a report holding
18 TemporaryApps and 6 TemporaryHosts, exit 0. The notes it printed beside that answer said
the budgeted classes were not leaking, which is the worst kind of wrong: a gate that
explains a leak it cannot see. `--list` writes one line per block, and a summary that
outruns what the reader read is the shape of a report the rules were never pointed at, so
that is refused rather than judged.

Usage:
  leak-audit.py [root]                     run the Debug probe under leaks and judge it
  leak-audit.py [root] --log <file>        judge a report somebody else captured
  leak-audit.py [root] --log <file> --red-team
                                           break a captured report one way at a time and
                                           check every break is refused: no process, no
                                           baseline file, runs on any host that has python
  leak-audit.py [root] --report <file>     also write the raw sweep report there, so a red
                                           run on a runner leaves the whole thing behind
  leak-audit.py [root] --growth            run two sweeps (1 visit and N visits) and judge
                                           how much the page orphans per extra visit
  leak-audit.py [root] --growth-cycles N   how many visits the longer sweep makes (8)
  leak-audit.py [root] --write-baseline    raise the ceiling where this run exceeded it
  leak-audit.py [root] --self-test         fixtures only, no process, no baseline file
Exit 0 only when the sweep really ran and first-party leaks stayed inside the ceiling.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_identity  # noqa: E402  (same directory, as render-probe.py does)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIVED = os.path.join(ROOT, "build-render-probe")
BASELINE = os.path.join(ROOT, "scripts", "leak-baseline.json")

# One leaked block per line, as `leaks --list` writes them. The class token is what
# decides whether the block is ours: `--list` was chosen over the default tree because
# the tree detailed 9 of 105 leaks and left 96 unattributed, which is a report that
# answers three questions out of fifty.
LEAK_LINE = re.compile(r"^Leak: 0x\S+\s+size=(\d+)\s+zone: \S+\s+(\S+)")
SUMMARY = re.compile(r"Process \d+: (\d+) leaks for (\d+) total leaked bytes")
# A primary declaration only. The first version also took `@interface X (...)`, and the
# first real run showed what that costs: this tree carries categories on Foundation and
# AppKit -- `NSNumber(F)`, `NSArray(F)`, `NSString (NSStringWithTrim)`, categories on
# NSView and NSWindow -- so the audit claimed nine system classes as ours and counted a
# system class leaking one extra instance as our regression. A category names the class
# it extends, not a class this repository declares.
OBJC_CLASS = re.compile(r"@interface\s+([A-Za-z_]\w*)\s*(?:$|:|\{)", re.M)


def first_party_classes(root):
    """Every class this repository declares, read out of the sources.

    The baseline has to say which leaked objects are *ours*, and a hand-kept list of
    names is a list that stops being true the day somebody adds a class. So the answer
    is read from `Limelight/` the same way the other gates read the tree.
    """
    names = set()
    for directory, _, files in os.walk(os.path.join(root, "Limelight")):
        for name in files:
            if not name.endswith((".h", ".m")):
                continue
            try:
                text = open(os.path.join(directory, name), encoding="utf-8",
                            errors="replace").read()
            except OSError:
                continue
            names.update(OBJC_CLASS.findall(text))
    return names


def is_first_party(class_name, objc_names, module):
    """Is this leaked class ours -- Objective-C by name, Swift by its module?

    Swift classes reach `leaks` mangled (`_TtC17MoonlightEnhanced13SettingsModel`) or
    demangled with the module in front (`MoonlightEnhanced.SettingsModel`), and both
    carry the module name, so that is the test. Objective-C carries no namespace at all,
    which is why the source scan is needed for those, and is also why a first-party
    Objective-C class can hide behind a name this function cannot tell from a system one.
    """
    if class_name in objc_names:
        return True
    return "_Tt" in class_name and module in class_name


def count_leaks(text, objc_names, module):
    """(per-class first-party counts, total bytes, summary line or None, blocks read,
    first-party bytes).

    The block count is the reader's own answer to "how many leaked objects did I look at",
    and the judge compares it against the number the report claims. It is returned rather
    than inferred so the fixtures and the red team can drive the rule with a report of
    their own.

    The bytes are totalled twice on purpose. The report's own total is every leaked object
    in the process -- ours and everybody else's -- and on the machine this was first run on
    that total was 11,792 bytes of which 2,304 were ours, while a GitHub runner reported
    18,720 bytes with none of them ours. A ceiling on the total is therefore a ceiling on
    the machine, and the two machines disagree by 60% before either one has a host in the
    report. So the rule judges the first-party total and the report's total is printed as
    context: still worth reading, no longer worth going red over.
    """
    summary = None
    first_party = {}
    total = 0
    blocks = 0
    ours_bytes = 0
    for line in text.splitlines():
        if summary is None:
            found = SUMMARY.search(line)
            if found:
                summary = (int(found.group(1)), int(found.group(2)))
                total = summary[1]
                continue
        match = LEAK_LINE.match(line)
        if not match:
            continue
        blocks += 1
        if is_first_party(match.group(2), objc_names, module):
            first_party[match.group(2)] = first_party.get(match.group(2), 0) + 1
            ours_bytes += int(match.group(1))
    return first_party, total, summary, blocks, ours_bytes


def judge(first_party, total, summary, baseline, blocks, ours_bytes=0):
    """The refusals. Kept apart from the reading so the fixtures can drive them."""
    problems = []
    notes = []
    if summary is None:
        return (["the report carries no `leaks for N total leaked bytes` line, so this "
                 "sweep either did not run or was truncated -- a report that says "
                 "nothing is not a clean report"], notes)
    if blocks != summary[0]:
        why = ("so %d were never looked at. The default `leaks` tree does exactly this -- "
               "it draws the graph and details a few of the blocks inside it -- and "
               "`--list`, which writes one line per block, is what this reader reads"
               % (summary[0] - blocks)) if blocks < summary[0] else (
               "so the file was written after the sweep or two reports were joined into "
               "it, and a ceiling cannot be judged against a report that disagrees with "
               "itself")
        return (["the report counts %d leaked blocks in its own summary and the audit "
                 "read %d, %s. A report the rules were never pointed at is refused, not "
                 "judged clean." % (summary[0], blocks, why)], notes)
    host_class = baseline.get("host_class")
    hosts = first_party.get(host_class, 0) if host_class else 0
    fan_out = baseline.get("apps_per_host", {})
    slack = baseline.get("slack_per_host", 0)
    budgeted = set(fan_out) | ({host_class} if host_class else set())
    measured = baseline.get("observed", {})

    for class_name in sorted(first_party):
        if class_name not in budgeted:
            problems.append("a first-party class nobody budgeted is leaking: %s (%d)"
                            % (class_name, first_party[class_name]))

    if host_class and host_class not in first_party:
        notes.append("%s is not leaking in this run, so no host graph was built here: the "
                     "fan-out ceiling held by having nothing to multiply, and the "
                     "first-party byte budget went unjudged -- this sweep cannot certify "
                     "that graph" % host_class)

    for class_name in sorted(fan_out):
        if class_name not in first_party:
            notes.append("%s is not leaking in this run, where the ceiling carries %d per "
                         "host -- if that is because it was fixed, lower the ceiling in the "
                         "same commit" % (class_name, fan_out[class_name]))
            continue
        allowed = hosts * (fan_out[class_name] + slack)
        if first_party[class_name] > allowed:
            problems.append(
                "%s leaks %d instances against %d leaked %s(s): a fan-out of %.2f per host "
                "where the ceiling is %d+%d. Measured on the shipped code: %s per host over "
                "%d runs. A fan-out that grew is a second owner of the same graph, not a "
                "busier network -- the host count is already accounted for here"
                % (class_name, first_party[class_name], hosts, host_class or "host",
                   float(first_party[class_name]) / hosts if hosts else float("inf"),
                   fan_out[class_name], slack,
                   ", ".join(str(value) for value in measured.get("apps_per_host", [])),
                   measured.get("runs", 0)))

    per_host = baseline.get("first_party_bytes_per_host")
    if per_host is not None and hosts:
        budget = per_host * hosts + baseline.get("first_party_bytes_floor", 0)
        if ours_bytes > budget:
            problems.append(
                "our own objects leaked %d bytes against %d (%d per leaked host plus a "
                "%d-byte floor, %d host(s) in the report): the host count is already "
                "accounted for, so this is bytes per host growing. Measured on the shipped "
                "code: %s bytes per host. The other %d leaked bytes belong to classes this "
                "repository does not declare and are reported, not judged"
                % (ours_bytes, budget, per_host, baseline.get("first_party_bytes_floor", 0),
                   hosts,
                   ", ".join(str(value) for value in
                             measured.get("first_party_bytes_per_host", [])),
                   max(total - ours_bytes, 0)))
    return problems, notes


def report(text, baseline, objc_names, module):
    first_party, total, summary, blocks, ours_bytes = count_leaks(text, objc_names, module)
    problems, notes = judge(first_party, total, summary, baseline, blocks, ours_bytes)
    host_class = baseline.get("host_class")
    print("leak-audit: %d leaked bytes over %d block(s), %d of them ours, first-party "
          "classes: %s%s"
          % (total, blocks, ours_bytes,
             ", ".join("%s=%d" % kv for kv in sorted(first_party.items())) or "none",
             "" if not host_class else " (fan-out judged against %d leaked %s)"
             % (first_party.get(host_class, 0), host_class)))
    for note in notes:
        print("note  %s" % note)
    return problems


def class_discovery_fixture():
    """A category on somebody else's class is not ours, and a primary declaration is.

    Worth a fixture because the first real run got this wrong: `@interface NSArray(F)`
    reads like a declaration to a reader that only looks for the name, and nine system
    classes were billed to this repository before the numbers said so.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        sources = os.path.join(directory, "Limelight")
        os.makedirs(sources)
        with open(os.path.join(sources, "Planted.h"), "w", encoding="utf-8") as handle:
            handle.write("@interface PlantedPrimary : NSObject\n@end\n"
                         "@interface NSNumber(Planted)\n@end\n"
                         "@interface NSString (PlantedToo)\n@end\n")
        found = first_party_classes(directory)
    problems = []
    if "PlantedPrimary" not in found:
        problems.append("the reader lost a class this repository declares: %s"
                        % sorted(found))
    for borrowed in ("NSNumber", "NSString"):
        if borrowed in found:
            problems.append("the reader claimed a class it only sees a category of: %s"
                            % borrowed)
    for problem in problems:
        print("FAIL %s" % problem)
    if not problems:
        print("ok   a category names the class it extends, not a class we declare")
    return len(problems)


def fixtures():
    """A report per shape, each one answering the question it claims to answer.

    The names here stand in for what `first_party_classes()` reads out of `Limelight/`:
    the planted class has to be one the audit believes is ours, or the fixture would be
    testing whether an unrelated system class can trip a rule -- which it cannot, and
    which is not the rule under test.
    """
    module = "MoonlightEnhanced"
    names = {"TemporaryApp", "TemporaryHost", "AppDelegateForAppKit"}
    # The shape of the committed baseline, at the scale of a report a person can read in
    # one screen: one leaked host, four bytes-per-host of budget, and a fan-out ceiling of
    # three plus a slack of one.
    base = {"host_class": "TemporaryHost", "apps_per_host": {"TemporaryApp": 3},
            "slack_per_host": 1, "first_party_bytes_per_host": 200,
            "first_party_bytes_floor": 100,
            "observed": {"apps_per_host": [3], "runs": 7,
                         "first_party_bytes_per_host": [192]}}
    clean = ("Process 9: 4 leaks for 300 total leaked bytes\n"
             "Leak: 0x1  size=64  zone: MallocZone   TemporaryApp  ObjC  MoonlightEnhanced\n"
             "Leak: 0x2  size=64  zone: MallocZone   TemporaryApp  ObjC  MoonlightEnhanced\n"
             "Leak: 0x3  size=64  zone: MallocZone   TemporaryHost  ObjC  MoonlightEnhanced\n"
             "Leak: 0x4  size=108  zone: MallocZone   CFString  ObjC  CoreFoundation\n")
    new_class = clean.replace(
        "Leak: 0x4  size=108  zone: MallocZone   CFString  ObjC  CoreFoundation",
        "Leak: 0x4  size=108  zone: MallocZone   AppDelegateForAppKit  ObjC  MoonlightEnhanced")
    # One host, six apps: twice the ceiling of four. This is the shape a second owner of
    # the same graph takes -- the fan-out multiplies -- and it is not the shape a busier
    # network takes, which moves the host count and leaves the ratio alone.
    grown = ("Process 9: 8 leaks for 380 total leaked bytes\n"
             + "Leak: 0x1  size=40  zone: MallocZone   TemporaryApp  ObjC  MoonlightEnhanced\n" * 6
             + "Leak: 0x7  size=40  zone: MallocZone   TemporaryHost  ObjC  MoonlightEnhanced\n"
               "Leak: 0x8  size=60  zone: MallocZone   CFString  ObjC  CoreFoundation\n")
    # Our own host object grew a 436-byte tail, and the report's total moved with it so
    # the report stays self-consistent: the only reason left to refuse is ours.
    heavy = clean.replace(
        "Leak: 0x3  size=64  zone: MallocZone   TemporaryHost  ObjC  MoonlightEnhanced",
        "Leak: 0x3  size=500  zone: MallocZone   TemporaryHost  ObjC  MoonlightEnhanced"
    ).replace("for 300 total leaked", "for 736 total leaked")
    # The shape a CI runner now reports after the Debug probe seeds a host: one graph of
    # ours -- 1 host + 3 apps, 256 fixture bytes against a 300-byte budget -- wrapped in
    # a machine's worth of somebody else's objects. Under the ceiling this file carried
    # until today (2,500 bytes per leaked host plus a 2,000 floor, judged against the
    # report's total) this report is a refusal, and it would have been a refusal no matter
    # what this repository's code did, because 18,720 of those bytes are CoreFoundation.
    # Written as a case rather than argued, because it is the reason the rule changed.
    runner = ("Process 9: 5 leaks for 3056 total leaked bytes\n"
              "Leak: 0x1  size=64  zone: MallocZone   TemporaryHost  ObjC  MoonlightEnhanced\n"
              "Leak: 0x2  size=64  zone: MallocZone   TemporaryApp  ObjC  MoonlightEnhanced\n"
              "Leak: 0x3  size=64  zone: MallocZone   TemporaryApp  ObjC  MoonlightEnhanced\n"
              "Leak: 0x4  size=64  zone: MallocZone   TemporaryApp  ObjC  MoonlightEnhanced\n"
              "Leak: 0x5  size=2800  zone: MallocZone   CFString  ObjC  CoreFoundation\n")
    # Somebody else's class leaking four times over is a busy machine, not a regression of
    # ours. Refusing this is how a memory gate gets muted: the ceiling goes red over
    # CoreFoundation and the next person adds a skip.
    machine_noise = clean.replace(
        "Leak: 0x4  size=108  zone: MallocZone   CFString  ObjC  CoreFoundation",
        "Leak: 0x4  size=4308  zone: MallocZone   CFString  ObjC  CoreFoundation"
    ).replace("for 300 total leaked", "for 4592 total leaked")
    # Apps with no host in the report: nothing here can be blamed on the LAN, because a
    # graph that was never built cannot have leaked anything.
    hostless = ("Process 9: 3 leaks for 200 total leaked bytes\n"
                "Leak: 0x1  size=64  zone: MallocZone   TemporaryApp  ObjC  MoonlightEnhanced\n"
                "Leak: 0x2  size=64  zone: MallocZone   TemporaryApp  ObjC  MoonlightEnhanced\n"
                "Leak: 0x3  size=72  zone: MallocZone   CFString  ObjC  CoreFoundation\n")
    empty = "Process 9:\nLeak: 0x1  size=64  zone: MallocZone   TemporaryApp  ObjC\n"
    # The shape of the first report this gate ever read: the summary counts every leak,
    # the body draws the graph, and the only blocks written out as blocks are the few the
    # tree chose to detail. Read by a reader that wants a line per block it says "none of
    # yours is leaking", which is why it is a case and not a footnote.
    tree = ("Process 9: 4 leaks for 300 total leaked bytes\n"
            " DISTANT CYCLE\n"
            "+  1 0x1  64 B  CFString  CoreFoundation\n")
    gone = ("Process 9: 2 leaks for 252 total leaked bytes\n"
            "Leak: 0x1  size=144  zone: MallocZone   TemporaryHost  ObjC\n"
            "Leak: 0x2  size=108  zone: MallocZone   CFString  ObjC\n")
    swift = ("Process 9: 1 leaks for 64 total leaked bytes\n"
             "Leak: 0x1  size=64  zone: MallocZone   "
             "_TtC17MoonlightEnhanced13SettingsModel  ObjC\n")
    cases = [("the shipped shape passes", clean, 0, None),
             ("a class nobody budgeted starts leaking", new_class, 1, None),
             ("the fan-out grows past the ceiling", grown, 1, "fan-out"),
             ("our own bytes grow past the per-host budget", heavy, 1, "per leaked host"),
             ("another class grows ours not at all", machine_noise, 0, None),
             ("a runner with one seeded host and a machine's noise around it", runner, 0, None),
             ("apps leak with no host in the report", hostless, 1, "fan-out"),
             ("a report with no summary line", empty, 1, None),
             ("a Swift class is ours too, mangling and all", swift, 1, None),
             ("a budgeted class that stopped leaking is a note, not a failure",
              gone, 0, "not leaking in this run"),
             ("the default tree: a summary that outruns what the reader read",
              tree, 1, "never looked at")]
    failures = 0
    for label, text, want_problems, want_note in cases:
        first_party, total, summary, blocks, ours_bytes = count_leaks(text, names, module)
        problems, notes = judge(first_party, total, summary, base, blocks, ours_bytes)
        answer = 0 if not problems else 1
        # A case that expects a refusal also says which words the refusal has to contain:
        # the reason matters as much as the exit code, because a gate that refuses for the
        # wrong reason teaches the next person the wrong lesson.
        said = problems if want_problems else notes
        if answer != want_problems:
            print("FAIL %s: expected %d problem group(s), got %d (%s)"
                  % (label, want_problems, answer, "; ".join(problems)))
            failures += 1
        elif want_note and not any(want_note in line for line in said):
            print("FAIL %s: `%s` never appeared in what the audit said: %s"
                  % (label, want_note, "; ".join(said) or "(nothing)"))
            failures += 1
        elif want_problems == 0 and not want_note and notes:
            print("FAIL %s: notes appeared where none belong: %s" % (label, notes))
            failures += 1
        else:
            print("ok   %s" % label)
    return failures


# ---------------------------------------------------------------------------
# The red team: break a report and check that the rules bite
# ---------------------------------------------------------------------------

CLASS_TOKEN = re.compile(r"^(Leak: 0x\S+\s+size=\d+\s+zone: \S+\s+)\S+(.*)$")


def reclass(line, class_name):
    """Rewrite one `Leak:` line's class token and keep the rest of it intact."""
    match = CLASS_TOKEN.match(line)
    if match is None:
        return None
    return match.group(1) + class_name + match.group(2)


def recount(text, count):
    """Rewrite the summary's leak count, as a real fix or a real flood would."""
    return re.sub(r"(Process \d+: )\d+( leaks for )",
                  lambda m: "%s%d%s" % (m.group(1), count, m.group(2)), text, count=1)


def flood(text, class_name, copies):
    """Hand back `text` with `copies` extra leaked blocks of one class.

    A regression reaches the reader as extra lines, so the break is written the same way
    rather than by editing the summary, which the reader no longer trusts on its own.
    """
    template = next((reclass(line, class_name) for line in text.splitlines()
                     if LEAK_LINE.match(line)), None)
    if template is None:
        return None
    return text + "".join("\n" + template for _ in range(copies)) + "\n"


def resize_block(text, class_name, new_size):
    """Grow one leaked block of one class and move the report's own total with it.

    The byte rule needs a break that changes the size of a block, not the summary: the
    summary stopped being the number the rule reads the moment the runner reported 18,720
    leaked bytes of which none were ours. Moving the total as well keeps the report
    self-consistent, so a refusal can only come from the budget and not from the report
    disagreeing with itself.
    """
    pattern = re.compile(r"(^Leak: 0x\S+\s+size=)(\d+)(\s+zone: \S+\s+%s\b)"
                         % re.escape(class_name))
    moved = []

    def bump(match):
        moved.append(int(match.group(2)))
        return "%s%d%s" % (match.group(1), new_size, match.group(3))

    lines = []
    for line in text.splitlines():
        if not moved:
            line = pattern.sub(bump, line, count=1)
        lines.append(line)
    if not moved:
        return None
    delta = new_size - moved[0]
    return re.sub(r"( leaks for )(\d+)",
                  lambda match: "%s%d" % (match.group(1), int(match.group(2)) + delta),
                  "\n".join(lines) + "\n", count=1)


def red_team(text, baseline, objc_names, module):
    """Break a captured report one way at a time and check that each break is refused.

    The fixtures prove the rules work on reports written to look like the reader's own
    format. This proves the reader works on the report `leaks` actually writes: every
    class token, size and block count comes out of a captured sweep, and the breaks are
    made in that text. It matters because a reader that matched nothing is invisible to
    the fixtures and invisible to a green run -- the first report this gate was aimed at
    was a tree report, and it read that as "first-party classes: none" and passed. If the
    line format ever changes under this script, the red team is the run that says so.

    Returns the number of breaks that were not refused for the reason they should have
    been.
    """
    first_party, total, summary, blocks, ours_bytes = count_leaks(text, objc_names, module)
    blockers = []
    if summary is None:
        blockers.append("the report handed to the red team carries no summary line, so "
                        "there is no sweep here to break")
    elif blocks != summary[0]:
        blockers.append("the report handed to the red team reads %d block(s) against the "
                        "%d its own summary counts, so breaking it would prove nothing "
                        "about a real sweep" % (blocks, summary[0]))
    host_class = baseline.get("host_class")
    fan_out = baseline.get("apps_per_host", {})
    slack = baseline.get("slack_per_host", 0)
    budgeted = sorted(set(fan_out) | ({host_class} if host_class else set()))
    if not budgeted:
        blockers.append("the baseline budgets no class, so there is no ceiling to break")
    hosts = first_party.get(host_class, 0) if host_class else 0
    if summary is not None and blocks == summary[0] and not hosts:
        blockers.append("the report leaked no %s, so every ratio in the baseline divides by "
                        "zero -- break a report that built the graph, or the fan-out rules "
                        "go untested and the run means nothing" % (host_class or "host"))
    unbudgeted = sorted(name for name in objc_names
                        if name not in budgeted and name not in first_party)
    if not unbudgeted:
        blockers.append("every class this repository declares is already budgeted, so no "
                        "name is left to plant")
    if blockers:
        for blocker in blockers:
            print("FAIL red team cannot run: %s" % blocker)
        return len(blockers)

    multiplied = next((name for name in sorted(fan_out)
                       if first_party.get(name, 0) > hosts), None)
    if multiplied is None:
        blockers.append("no budgeted class leaks more instances than the host count, so "
                        "there is no fan-out here to multiply")
        for blocker in blockers:
            print("FAIL red team cannot run: %s" % blocker)
        return len(blockers)
    allowed = hosts * (fan_out[multiplied] + slack)

    def without(class_name):
        """The same report with one class's blocks taken out, and its honest block count."""
        lines = [line for line in text.splitlines()
                 if not (LEAK_LINE.match(line) and LEAK_LINE.match(line).group(2)
                         == class_name)]
        return recount("\n".join(lines) + "\n",
                       sum(1 for line in lines if LEAK_LINE.match(line)))

    cases = []
    extra = max(allowed + 1 - first_party[multiplied], 1)
    cases.append(("the fan-out grows past the ceiling",
                  recount(flood(text, multiplied, extra), summary[0] + extra), 1, "fan-out"))
    planted = flood(text, unbudgeted[0], 1)
    cases.append(("a class nobody budgeted starts leaking",
                  recount(planted, summary[0] + 1), 1, "nobody budgeted"))
    per_host = baseline.get("first_party_bytes_per_host")
    if per_host:
        budget = per_host * hosts + baseline.get("first_party_bytes_floor", 0)
        grown = next((name for name in sorted(first_party) if first_party[name] > 0), None)
        # One block of ours gets one byte more than the whole budget can carry: the
        # smallest break that has to be caught, on the smallest block the report has.
        smallest = min(int(match.group(1)) for match in
                       (LEAK_LINE.match(line) for line in text.splitlines())
                       if match and is_first_party(match.group(2), objc_names, module))
        mutated = resize_block(text, grown, smallest + budget + 1 - ours_bytes)
        if mutated is None:
            blockers = ["no first-party block in this report could be resized, so the byte "
                        "budget cannot be broken here and a green run would not mean one"]
            for blocker in blockers:
                print("FAIL red team cannot run: %s" % blocker)
            return 1
        cases.append(("our bytes per leaked host grow past the budget", mutated, 1,
                      "per leaked host"))
        # The mirror image, and the reason the rule stopped reading the report's total: a
        # system class ballooning is the machine being busy, and a gate that refuses that
        # is a gate somebody mutes.
        noisy = resize_block(text, "CFString", 4096)
        if noisy is not None:
            cases.append(("a system class leaks a lot more of its own bytes", noisy, 0, None))
    cases.append(("the summary is cut off",
                  "\n".join(line for line in text.splitlines()
                             if SUMMARY.search(line) is None), 1, "no `leaks for"))
    cases.append(("the blocks disappear but the summary stays",
                  "\n".join(line for line in text.splitlines()
                             if not LEAK_LINE.match(line)), 1, "never looked at"))
    if host_class:
        # The one break a runner with no LAN would produce by itself, minus the excuse:
        # the hosts are gone and the apps are not, so no network remains to blame.
        cases.append(("apps leak with no host left in the report", without(host_class), 1,
                      "fan-out"))
    cases.append(("a budgeted class is genuinely fixed", without(multiplied), 0,
                  "%s is not leaking in this run" % multiplied))

    # The growth rule is arithmetic over two sweeps, so its breaks are made by holding this
    # one real report as the short sweep and asking what the long sweep would have to look
    # like. Every number in the break comes out of the report -- our bytes, its graphs, and
    # the cost of one graph derived from the two -- so the ceiling is exercised against real
    # magnitudes rather than against a constant this file invented. What is synthetic is only
    # the extra visiting, which no laptop report can contain.
    failures = 0
    growth_ceiling = baseline.get("growth_bytes_per_cycle_per_host")
    if growth_ceiling and ours_bytes and first_party.get(host_class):
        graphs = first_party[host_class]
        cost_of_one_graph = float(ours_bytes) / graphs
        shorter = {"cycles": 1, "library": graphs, "ours": ours_bytes, "hosts": graphs}
        for visits in (1, 2, 3):
            longer = dict(shorter, cycles=6,
                          ours=ours_bytes + 5 * graphs * visits * cost_of_one_graph)
            problems, notes = judge_growth(shorter, longer, baseline)
            label = "%d graph(s) per visit per host" % visits
            # Measured on an unchanged build: one graph per visit per host sits inside the
            # spread the page produces by itself, so the ceiling has to let it through.
            want_refusal = visits >= 3
            if bool(problems) != want_refusal:
                print("FAIL red team: %s -- expected %s, got %s"
                      % (label, "a refusal" if want_refusal else "a pass",
                         "; ".join(problems) or "; ".join(notes) or "silence"))
                failures += 1
            elif want_refusal and not any("per visit per host" in line for line in problems):
                print("FAIL red team: %s refused for the wrong reason: %s" % (label, problems))
                failures += 1
            else:
                said = "refused" if want_refusal else (
                    "passed -- the ceiling has to let the shipped page through" if visits == 1
                    else "passed -- the measured blind spot, two graphs a visit")
                print("ok   red team: %s %s" % (label, said))

    for label, mutated, want_problems, want_text in cases:
        per_class, mutated_total, mutated_summary, mutated_blocks, mutated_ours = \
            count_leaks(mutated, objc_names, module)
        problems, notes = judge(per_class, mutated_total, mutated_summary, baseline,
                                mutated_blocks, mutated_ours)
        answer = 0 if not problems else 1
        said = problems if want_problems else notes
        if answer != want_problems:
            print("FAIL red team: %s -- expected %s, got %s"
                  % (label, "a refusal" if want_problems else "a pass",
                     "; ".join(problems) or "a clean answer"))
            failures += 1
        elif want_text is None:
            print("ok   red team: %s" % label)
        elif not any(want_text in line for line in said):
            print("FAIL red team: %s refused for the wrong reason: %s"
                  % (label, "; ".join(said) or "(nothing)"))
            failures += 1
        else:
            print("ok   red team: %s" % label)
    return failures


def read_probe_record(output_directory):
    """What the probe believed about its own run, read before the scratch directory goes.

    The probe records its failures in structured form, so the sweep reads that form instead
    of pattern-matching a sentence printed to stderr. It is read here and nowhere else: the
    scratch directory is this function's to clean, and once it is gone the claim "the page
    presented" has no evidence left behind.
    """
    path = os.path.join(output_directory, "report.json")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def probe_problems(probe, returncode=0, cycles_requested=None):
    """Why this sweep may not be judged, read out of what the probe recorded about itself.

    Kept apart from `capture()` so a fixture can drive it: every one of these refusals is a
    shape a real run produces (no report, a page that failed to present, a seed flag that
    reached a build which ignores it), and none of them can be produced on demand at the
    moment the sweep happens to run. A rule nobody can exercise is a rule nobody can trust.
    """
    if probe is None:
        return ["the probe left no report.json behind, so nothing here says the settings"
                " page ever presented -- the sweep cannot certify a page it did not see."
                " Exit %d." % returncode]
    problems = []
    failures = probe.get("failures") or []
    if failures:
        problems.append("the probe refused its own run, so the sweep would have judged an app"
                        " that did not present: %s" % "; ".join(str(f) for f in failures[:4]))
    seed = probe.get("seedHosts")
    if not isinstance(seed, dict):
        problems.append("the sweep asked for a seeded host graph and the probe recorded no"
                        " seedHosts, so the flag reached a build that ignores it -- the graph"
                        " this gate budgets is unjudged again")
    elif seed.get("status") not in ("seeded", "existing-hosts"):
        problems.append("the sweep asked for %s seeded host(s) and got status %r, recorded by"
                        " the probe itself, so there is no host graph behind these numbers"
                        % (seed.get("requested"), seed.get("status")))
    if cycles_requested is not None:
        cycles = probe.get("memoryCycles")
        if not isinstance(cycles, dict):
            problems.append("the sweep asked for %d visit cycle(s) and the probe recorded no"
                            " memoryCycles, so the flag reached a build that ignores it and the"
                            " growth being measured has no visits in it" % cycles_requested)
        elif cycles.get("status") != "completed":
            problems.append("the sweep asked for %d visit cycle(s) and the probe stopped at %r"
                            " after %s -- a run that stopped partway has a shorter denominator"
                            " than the one it reports"
                            % (cycles_requested, cycles.get("status"),
                               cycles.get("completed")))
        elif not isinstance(cycles.get("readsPerCycle"), list) or not cycles["readsPerCycle"]:
            problems.append("the sweep asked for %d visit cycle(s) and the probe recorded no"
                            " readsPerCycle, so the growth has no library reads behind it -- the"
                            " counter is compiled out of this build or was deleted, and a leak"
                            " rate that cannot be tied to the reads that cause it is a"
                            " coincidence with a unit on it" % cycles_requested)
        elif cycles.get("completed") != cycles_requested:
            problems.append("the sweep asked for %d visit cycle(s) and the probe recorded %s as"
                            " completed, so the rate would be divided by visits that did not"
                            " happen" % (cycles_requested, cycles.get("completed")))
    return problems


def sibling_report(report_path, cycles):
    """Where the longer sweep's raw report goes, so the two reports do not overwrite each other."""
    if not report_path:
        return None
    base, extension = os.path.splitext(report_path)
    return "%s-%dvisits%s" % (base, cycles, extension or ".txt")


def library_hosts(probe):
    """How many hosts the page could have read during this run, as the probe recorded it.

    The rate wants a per-host denominator, and the number has to come from the run rather
    than from the leaked counts: the leaked counts are what is being measured, and dividing
    a measurement by itself is how a leak of one graph per visit gets reported as a rate of
    one. Zero is returned rather than guessed, and the caller refuses a zero.
    """
    cycles = (probe or {}).get("memoryCycles")
    if isinstance(cycles, dict) and cycles.get("libraryEnd"):
        # The count the visits actually saw. `seedHosts` is read before the page opens, and
        # discovery keeps writing hosts while the process lives, so dividing by it understates
        # the library and overstates the rate.
        return int(cycles["libraryEnd"])
    seed = (probe or {}).get("seedHosts")
    if not isinstance(seed, dict):
        return 0
    if seed.get("status") == "seeded":
        return int(seed.get("seeded") or 0)
    if seed.get("status") == "existing-hosts":
        return int(seed.get("existing") or 0)
    return 0


def host_reads_per_visit(probe):
    """How many times one trip through the page went to the library, as that run recorded it.

    `getHosts` builds a fresh `TemporaryHost` per row on every call (`DataManager.m:205`), so
    the read count is the reason the sweep sees graphs at all: one visit reads the library N
    times, each read materialises one graph per host in the library, and those graphs are the
    objects this file counts. It is a rate and not a prediction of the leaked count -- how many
    of the graphs a read builds are still standing when `leaks` takes its one snapshot is not
    fixed, which is why the rule that uses this number compares slopes over a long window
    (`judge_growth`). Measured on 2026-09-25 by three runs of one build, the settings root reads
    once per visit at both 3 and 6 cycles. None is returned when the run recorded nothing, which
    is a different fact from zero.
    """
    cycles = (probe or {}).get("memoryCycles")
    if not isinstance(cycles, dict):
        return None
    spans = cycles.get("readsPerCycle")
    if not isinstance(spans, list) or not spans:
        return None
    values = [value for value in spans if isinstance(value, int)]
    if len(values) != len(spans):
        return None
    return float(sum(values)) / len(values)


def judge_growth(shorter, longer, baseline):
    """Is the page leaking per visit, and is that rate the one the baseline already carries?

    `shorter` and `longer` are two sweeps of the same build, the second taking more trips
    through the page. Their difference is the only place a per-visit leak shows up: one
    sweep cannot tell "this page leaks once per run" from "this page leaks once per visit",
    because both leave the same objects at exit. The division is by completed visits and by
    the hosts the run could actually see, so the rate says what one trip through one host
    costs, which is the number that survives a different library and a different machine.
    """
    problems, notes = [], []
    visits = longer["cycles"] - shorter["cycles"]
    if visits <= 0:
        return (["the two sweeps asked for %d and %d visit cycle(s), so there is no extra"
                 " visiting between them and no rate to divide by"
                 % (shorter["cycles"], longer["cycles"])], notes)
    hosts = min(shorter["library"], longer["library"])
    if hosts <= 0:
        return (["neither sweep recorded a host in the library, so the rate has no per-host"
                 " denominator and would be a bytes-per-visit figure for an unknown number of"
                 " machines"], notes)
    per_cycle = float(longer["ours"] - shorter["ours"]) / visits
    per_cycle_per_host = per_cycle / hosts
    measured = baseline.get("observed", {}).get("growth_bytes_per_cycle_per_host")
    ceiling = baseline.get("growth_bytes_per_cycle_per_host")
    print("leak-audit growth: %d visits took our objects from %d to %d bytes -- %.0f bytes per"
          " visit, %.1f per visit per host across %d host(s)%s"
          % (visits, shorter["ours"], longer["ours"], per_cycle, per_cycle_per_host, hosts,
             ", graphs leaked %d then %d" % (shorter["hosts"], longer["hosts"])
             if shorter.get("hosts") is not None else ""))
    # How many graphs the extra visits left behind, against the rate the reads can name. The
    # byte ceiling below can absorb a doubling -- five unmodified runs of this build came back
    # spread over 192 to 461 bytes per visit per host -- so it is not the rule that ought to
    # notice a second creator of the same graph. The read count is that rule, and it can only be
    # compared as a rate, never as a count: `leaks` answers what is still orphaned at one
    # instant, and how many of the graphs a read builds are still standing when that instant
    # arrives is not a number this repository controls. Measured on one build with one host in
    # the library, the one-visit sweep has come back at 6, 8 and 9 leaked graphs, and the
    # difference between the two sweeps came back 3, 4, 5, 6 and 7 over five extra visits (CI
    # runs 36000138662, 36051089381 and 36058010642, both architectures each, and four laptop
    # sweeps). A rule that refused anything above the entitled count therefore refused the
    # shipped code twice on a runner and once on a laptop: it was refusing the snapshot, not the
    # leak. So the window has to be long enough for a slope to mean something, and what gets
    # refused is a slope above the read rate rather than any surplus at all. The blind spot that
    # leaves -- a creator adding less than the ratio on top of the read rate -- is recorded in
    # the baseline as growth_graph_rule_reason and reproduced as a fixture, not left implied.
    built = None
    if shorter.get("hosts") is not None and longer.get("hosts") is not None:
        built = longer["hosts"] - shorter["hosts"]
        reads = longer.get("reads")
        minimum = baseline.get("growth_graph_rule_min_visits")
        ratio = baseline.get("growth_graph_count_ratio")
        if reads is not None and minimum is not None and visits < int(minimum):
            problems.append(
                "the two sweeps are %d visit(s) apart, which is fewer than the %d this gate"
                " needs before it will judge leaked graphs at all. The leaked graph count is a"
                " snapshot and not a sum: one build, one host, and the difference over five"
                " visits has come back 3, 4, 5, 6 and 7, so a window that short cannot tell a"
                " second creator from the run it arrived in (2026-09-25 run 36058010642 is the"
                " record of what the short window does to correct code). Raise `--growth-cycles`"
                " rather than the ceiling" % (visits, int(minimum)))
        elif built > 0 and reads is not None and ratio is not None:
            entitled = reads * visits * hosts
            allowed = int(-(-(entitled * float(ratio)) // 1))  # ceil: a partial graph is one
            if built > allowed:
                problems.append(
                    "the extra visits left %d more leaked %s graph(s) behind than the %s library"
                    " read(s) per visit can name across %d host(s) (%d extra visits, %d to %d"
                    " graphs, %s entitled, %d allowed at the %s ratio). One read builds one graph"
                    " per host, so a slope above the ratio has another creator this gate cannot"
                    " name -- either something reads the library outside the path the probe"
                    " counts, or a graph is retained per visit by something other than the read"
                    % (built, baseline.get("host_class"), reads, hosts, visits, shorter["hosts"],
                       longer["hosts"], entitled, allowed, ratio))
    if per_cycle < 0:
        notes.append("the page leaked %d fewer bytes over %d extra visits than it did over %d:"
                     " the rate went down. That is a fix, and the ceiling in the baseline is"
                     " above it -- lowering one is a decision somebody makes in the commit that"
                     " fixes the leak" % (-int(per_cycle * visits), visits, shorter["cycles"]))
    elif ceiling is not None and per_cycle_per_host > ceiling:
        problems.append(
            "each extra trip through the page leaves %.1f first-party bytes per host behind"
            " where the ceiling is %.1f (%d hosts, %d extra visits, %d to %d bytes). Bytes per"
            " host inside one sweep stayed inside its own ceiling, so this is objects being"
            " orphaned per visit rather than a busier library. Measured on the shipped code: %s"
            " bytes per visit per host"
            % (per_cycle_per_host, ceiling, hosts, visits, shorter["ours"], longer["ours"],
               ", ".join(str(value) for value in (measured or []))))
    if built is not None:
        reads = longer.get("reads")
        ratio = baseline.get("growth_graph_count_ratio")
        notes.append("the %d extra leaked graph(s) across %d host(s) sit inside %sx the rate the"
                     " %s library read(s) per visit name (%s entitled over %d visit(s)), so the"
                     " growth has a named source rather than only a byte ceiling; what the ratio"
                     " cannot see is written up in the baseline as growth_graph_rule_reason"
                     % (built, hosts, ratio, reads,
                        reads * visits * hosts if reads is not None else 0, visits))
    return problems, notes


def growth_fixture():
    """The slope rule, driven without a process.

    The number that matters here is the one that cannot be seen in a single sweep: a page that
    orphans one graph per visit and a page that orphans one graph per launch look the same to a
    run that visits once, and only the first gets worse while somebody is using it. The cases
    below are the two shapes, the ways the measurement itself can lie -- no extra visits, no
    hosts to divide by, a window too short to carry a slope -- and the one that has to stay
    green, a rate that fell. Two of them are the literal CI shapes of 2026-09-25: the surplus
    that refused correct code over five visits, and the same surplus at a window that can name
    it.
    """
    base = {"growth_bytes_per_cycle_per_host": 1100.0,
            "observed": {"growth_bytes_per_cycle_per_host": [192, 461]},
            "growth_graph_rule_min_visits": 10,
            "growth_graph_count_ratio": 1.6}
    one_host = {"cycles": 1, "library": 2, "ours": 6912, "hosts": 18, "reads": 1.0}
    # Fifteen extra visits, because that is the shortest window the rule will judge: the leaked
    # graph count is a snapshot, and the noise in it is a constant number of graphs per sweep
    # rather than a fraction of the visits, so the longer the window the less the snapshot counts
    # for. Every case below that is about a rate is measured over the same 15 visits so the
    # arithmetic in the comments can be checked by hand.
    window = 16
    def after(graphs_per_visit_per_host, bytes_per_visit=302, visits=window, hosts=2):
        extra = visits - 1
        return dict(one_host, cycles=visits,
                    ours=6912 + int(extra * hosts * bytes_per_visit),
                    hosts=18 + int(extra * hosts * graphs_per_visit_per_host))
    cases = [
        # Measured on the shipped code: 302 first-party bytes per visit per host, and roughly one
        # leaked graph per visit, which is what one read per visit across two hosts looks like.
        ("the shipped rate is inside its ceiling", after(1.0), 0, None),
        # One whole graph per host per visit -- 384 bytes -- is inside the measured spread, and
        # 30 leaked graphs against the 30 the reads are entitled to name cannot be a surplus.
        ("a visit orphans one graph per host", after(1.0, 384), 0, None),
        # The blind spot, written as a case rather than as a comment: 1.5 graphs per visit per
        # host is 45 against the 48 the ratio allows, so a creator adding half again on top of the
        # read rate walks through this gate. It is refused by the byte ceiling only above 1100
        # bytes per visit per host (2.9 graphs), so the gap between 1.5 and 2.9 graphs is the
        # price of a rule that does not refuse a snapshot. Shrinking it means a longer window or
        # a ratio somebody can defend against the measured noise, not a quieter message.
        ("the measured blind spot: 1.5 graphs per visit per host", after(1.5, 576), 0,
         "sit inside 1.6x the rate"),
        # Two graphs per visit per host used to be the recorded blind spot of the count rule, and
        # 60 leaked graphs against 48 allowed is what the slope rule makes of it now: the change
        # of rule tightened this case rather than loosening it, and the refusal is named as a
        # surplus of graphs instead of as bytes that happen to be large (768 bytes is inside the
        # byte ceiling).
        ("a visit orphans two graphs per host", after(2.0, 768), 1, "another creator"),
        # Three graphs a visit is a second owner of the same cycle by both rules at once: 90
        # graphs against 48 allowed, and 1152 bytes against the 1100 ceiling.
        ("a visit orphans three graphs per host", after(3.0, 1152), 1, "per visit per host"),
        # The fix, which must not be refused for going the right way: one visit's worth of objects
        # came back, which is what a real repair of the ownership cycle looks like.
        ("the rate fell because somebody fixed it",
         dict(one_host, cycles=window, ours=5912, hosts=18), 0, "went down"),
        # Zero is not a fall and is not a refusal either: the page stopped growing, and the note
        # that says so is the one above. This case keeps "flat" from being read as a regression by
        # a rule written with the wrong sign.
        ("the rate is flat across visits", dict(one_host, cycles=window, ours=6912, hosts=18),
         0, None),
        # The rule the byte ceiling cannot do: 15 extra visits, one read each, two hosts in the
        # library, so 30 graphs are entitled to survive and 48 are allowed. This shape orphans 90.
        # The point is the surplus is refused as a surplus, named, rather than as bytes that
        # happen to be too large.
        ("a visit orphans more graphs than its reads can explain",
         dict(one_host, cycles=window, ours=9000, hosts=18 + 4 * 15), 1, "another creator"),
        # A run whose probe predates the counter, or whose counter was compiled out, is not
        # refused by this rule -- `probe_problems()` refuses it for missing the record, and a
        # growth rule that also fired would hide that sharper message behind a vaguer one.
        ("no read count recorded",
         dict(one_host, cycles=window, ours=9000, hosts=78, reads=None), 0, None),
        ("no extra visits to divide by", dict(one_host, cycles=1), 1, "no extra visiting"),
        ("no host in either sweep",
         dict(one_host, cycles=window, ours=9000, hosts=78, library=0), 1, "no per-host"),
        # The window refusal, which is the shape that refused correct code: five extra visits on
        # one host is the CI command of 2026-09-25, and the graph numbers are that run's arm64
        # sweep exactly (6 graphs at one visit, 12 at six). Nothing is wrong with the app here --
        # what is wrong is the denominator, and the gate has to say so instead of refusing the
        # code twice on a runner and once on a laptop.
        ("five visits is too short a window to name a creator",
         dict(one_host, library=1, ours=2304, hosts=6),
         dict(one_host, library=1, cycles=6, ours=4608, hosts=12), 1, "fewer than the 10"),
    ]
    failures = 0
    for case in cases:
        # A case names both sweeps when the shorter one is part of what is being tested -- the
        # short-window case below is the CI pair of 2026-09-25 exactly -- and names only the
        # longer one when it is testing a rate the first sweep merely provides.
        if len(case) == 5:
            label, shorter, longer, want_problems, want_text = case
        else:
            label, longer, want_problems, want_text = case
            shorter = one_host
        problems, notes = judge_growth(shorter, longer, base)
        if bool(problems) != bool(want_problems):
            print("FAIL %s: expected %s, got %s"
                  % (label, "a refusal" if want_problems else "a pass",
                     "; ".join(problems) or "; ".join(notes) or "silence"))
            failures += 1
        elif want_text and not any(want_text in line for line in (problems + notes)):
            print("FAIL %s answered without `%s`: %s" % (label, want_text, problems + notes))
            failures += 1
        else:
            print("ok   %s" % label)
    return failures


def probe_record_fixture():
    """A sweep whose probe refused, or whose seed went nowhere, is not a green sweep.

    These four are the shapes `probe_problems()` is meant to catch, and the one that matters
    most is the missing record: a flag that reached a build which ignores it leaves a report
    full of system leaks and no first-party object in it, which is exactly what a clean run
    looks like to a reader that never asks.
    """
    # The last four cases ask about the visit cycles, so they pass a cycle count the way
    # `--growth` does. Without one the cycle branch never runs, and a rule that only fires on
    # a flag nobody passed in a fixture is a rule nobody has ever seen fire.
    seeded = {"failures": [], "seedHosts": {"status": "seeded", "seeded": 1}}
    cases = [
        ("no report at all", None, None, 1, "no report.json"),
        ("the probe refused its own run", {"failures": ["the settings page did not mount"]},
         None, 1, "did not present"),
        ("the seed flag reached a build that ignores it", {"failures": []}, None, 1,
         "reached a build that ignores it"),
        ("the seed recorded a refusal", {"failures": [],
                                         "seedHosts": {"status": "invalid",
                                                       "requested": "two"}}, None, 1,
         "no host graph"),
        ("the graph was seeded", dict(seeded), None, 0, None),
        ("the machine had hosts of its own", {"failures": [],
                                              "seedHosts": {"status": "existing-hosts",
                                                            "existing": 4}}, None, 0, None),
        # Measured on 2026-09-25: the growth sweep divides by visits, and a build without the
        # read counter still reports visits, so the only thing saying whether any library read
        # happened inside them is this record.
        ("the cycle flag reached a build that ignores it", dict(seeded), 2, 1,
         "no memoryCycles"),
        ("the cycles completed but recorded no reads",
         dict(seeded, memoryCycles={"status": "completed", "completed": 3}), 3, 1,
         "no library reads"),
        ("the cycles completed and recorded their reads",
         dict(seeded, memoryCycles={"status": "completed", "completed": 3,
                                    "readsPerCycle": [1, 1, 1]}), 3, 0, None),
        # Stopping partway is refused for its own reason even though such a run would also
        # carry no reads: the shorter denominator is the sharper of the two messages.
        ("the cycles stopped partway",
         dict(seeded, memoryCycles={"status": "did-not-present", "completed": 1,
                                    "requested": "3"}), 3, 1, "stopped at"),
    ]
    failures = 0
    for label, probe, cycles_requested, want_problems, want_text in cases:
        problems = probe_problems(probe, cycles_requested=cycles_requested)
        if bool(problems) != bool(want_problems):
            print("FAIL %s: expected %s, got %s"
                  % (label, "a refusal" if want_problems else "a pass",
                     "; ".join(problems) or "a clean answer"))
            failures += 1
        elif want_text and not any(want_text in problem for problem in problems):
            print("FAIL %s refused for the wrong reason: %s" % (label, "; ".join(problems)))
            failures += 1
        else:
            print("ok   %s" % label)
    return failures


def capture(timeout, report_path=None, cycles=None):
    """Run the Debug probe under `leaks` and hand back its report.

    `--report` exists because a runner that refuses a leak leaves nothing else behind: the
    summary line says how many, the audit says which rule broke, but only the report says
    which objects, and nobody can re-run a memory sweep from a log once the machine is gone.
    """
    tool = shutil.which("leaks")
    if tool is None:
        print("FAIL no `leaks` on this host -- install the Xcode command line tools."
              " This gate refuses rather than skipping, because a memory sweep that did"
              " not run is exactly what a green check with no memory sweep looks like.")
        return None, None
    app = os.path.join(DERIVED, "Build", "Products", "Debug",
                       project_identity.product_name() + ".app")
    if not os.path.isdir(app):
        print("FAIL no Debug build at %s -- `render-probe.py` builds it" % app)
        return None, None
    home = tempfile.mkdtemp(prefix="leak-home.")
    out = tempfile.mkdtemp(prefix="leak-out.")
    binary = os.path.join(app, "Contents", "MacOS", project_identity.bundle_executable(app))
    # The sweep asks for one host to be seeded, because a runner has no LAN to browse and a
    # sweep with no host has no graph to judge (see MLSeedHostsForMemorySweep). The visual
    # probe does not set it: its pixel asserts were written against an empty library.
    env = dict(os.environ, HOME=home, ML_RENDER_PROBE="1", ML_RENDER_PROBE_OUTPUT=out,
               ML_RENDER_PROBE_SEED_HOSTS="1")
    if cycles:
        env["ML_RENDER_PROBE_CYCLES"] = str(cycles)
    try:
        try:
            proc = subprocess.run([tool, "--atExit", "--list", "--", binary],
                                  capture_output=True, text=True, env=env,
                                  timeout=timeout, cwd=ROOT)
        except subprocess.TimeoutExpired:
            # A probe that never exits has no report to judge, and `leaks` writes its
            # answer only when the target stops. Say which of the two failed and how long
            # the sweep was given: a runner that dies at the timeout has to be told the
            # timeout it died at, and a traceback is not an answer to that question.
            print("FAIL the sweep did not finish inside %d seconds, so `leaks` had no "
                  "report to write -- it prints its answer only when the app stops. "
                  "Raise `--timeout` if this machine is slow; it does not raise the "
                  "ceiling, which lives in the baseline file." % timeout)
            return None, None
        probe = read_probe_record(out)
    finally:
        # The gate that looks for leaks is not allowed to leave any of its own behind, and
        # the output directory is genuinely its own: that is where the probe writes its
        # screenshots and its report, and a laptop that ran the sweep a dozen times today
        # found out by filling up. The `home` below is worth removing for tidiness and is
        # not what kept this sweep out of the machine's library: the support directory the
        # app resolves comes out of the account record, not out of `$HOME`
        # (`DatabaseSingleton.m:100`), so the graph this sweep seeds is planted in -- and
        # read back out of -- the one store every probe on the machine shares. The ownership
        # probe reaps hosts it can prove it planted; this one leaves its host behind for the
        # life of the runner.
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)
    # Two things have to be true before any of this report is worth judging, and both come
    # out of what the probe itself recorded rather than out of the leak counts: the page has
    # to have presented (a sweep over a page that refused to open judges a broken app and
    # calls it a memory result), and the host graph this sweep asked for has to exist (a
    # sweep over no graph is the green that says nothing).
    refused = probe_problems(probe, proc.returncode, cycles)
    for problem in refused:
        print("FAIL %s" % problem)
    if refused:
        return None
    seed = probe.get("seedHosts")
    if isinstance(seed, dict):
        print("sweep ran on %s host(s) in the library (%s)"
              % (seed.get("seeded") if seed.get("status") == "seeded"
                 else seed.get("existing", 0), seed.get("status")))
    # `leaks` exits 1 when it found leaks, which is the normal answer for a real app.
    if report_path:
        directory = os.path.dirname(os.path.abspath(report_path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(proc.stdout)
        print("wrote the raw sweep to %s (%d bytes)" % (report_path, len(proc.stdout)))
    if SUMMARY.search(proc.stdout) is None:
        print("FAIL `leaks` produced no summary (exit %d):\n%s"
              % (proc.returncode, proc.stdout[-400:]))
        return None, None
    return proc.stdout, probe


# A flag's value is not a positional, and the mistake of treating it as one is worth
# naming: `--log leaks-arm64.log` would otherwise be read as the repository to scan, the
# scan would find no classes at all, and the gate would pass every leak in the file.
VALUE_FLAGS = ("--timeout", "--log", "--report", "--growth-cycles")


def parse(arguments):
    """(root, timeout, log path or None, report path or None, growth cycles), keeping each
    flag's value attached to its flag and out of the positionals.

    `--growth-cycles` is in the value list for the same reason `--log` is: a number left
    loose is read as the repository to scan, the scan finds no classes at all, and every
    first-party object in the report becomes somebody else's leak.
    """
    root = ROOT
    timeout = 900
    log = None
    report = None
    growth_cycles = 8
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in VALUE_FLAGS:
            value = arguments[index + 1]
            if argument == "--timeout":
                timeout = int(value)
            elif argument == "--log":
                log = value
            elif argument == "--growth-cycles":
                growth_cycles = int(value)
            else:
                report = value
            index += 2
            continue
        if not argument.startswith("--"):
            root = argument
        index += 1
    return root, timeout, log, report, growth_cycles


def main():
    arguments = sys.argv[1:]
    # `report` is also the name of the function that prints the verdict below, so the flag
    # value is not allowed to answer to it here: the first run of `--report` shadowed the
    # printer with a None and died on the way to reporting a leak.
    root, timeout, log, report_path, growth_cycles = parse(arguments)
    text = None
    if log is not None:
        text = open(log, encoding="utf-8", errors="replace").read()
    if "--self-test" in arguments:
        failures = (fixtures() + class_discovery_fixture() + growth_fixture()
                    + probe_record_fixture())
        print("%d leak-audit fixture failure(s)" % failures)
        return 1 if failures else 0
    # Both refusals belong here rather than inside the growth branch below: after them sits
    # the sweep, and a forty-second memory sweep spent before the gate says the request could
    # not be answered is not merely slow. It is worse than slow -- the run prints "sweep ran on
    # a graph of ..." first, so the refusal arrives under a line that reads like a result.
    if "--growth" in arguments and (log is not None or growth_cycles < 2):
        if log is not None:
            print("FAIL --growth measures a rate across two sweeps it runs itself, and `--log`"
                  " hands it one captured sweep. Drop the log and let it visit the page.")
        else:
            print("FAIL --growth needs at least 2 visits in the longer sweep to divide by --"
                  " it was given %d, which is the shorter sweep again" % growth_cycles)
        return 1
    # `--growth` runs two sweeps of its own below and judges each one on its own, so the sweep
    # this used to take first was a third full sweep whose only visible effect was to write the
    # shorter sweep's report file twice. On 2026-09-25 the artefact that came back from a red
    # growth run was the overwritten one, and the sweep that had produced the surplus the rule
    # was refusing had been replaced in the file by the time anybody could read it. Skipping the
    # extra sweep leaves one writer per report and saves the runner a sweep.
    if text is None and "--growth" not in arguments:
        text, _probe = capture(timeout, report_path)
        if text is None:
            return 1
    module = project_identity.product_name()
    objc_names = first_party_classes(root)
    baseline = (json.load(open(BASELINE, encoding="utf-8"))
                if os.path.exists(BASELINE) else {"apps_per_host": {}, "host_class": None,
                                                  "first_party_bytes_per_host": None})
    if "--red-team" in arguments:
        if text is None:
            print("FAIL --red-team breaks a captured report and none was given. Pass "
                  "`--log <report>`; the committed one is scripts/leak-sample.txt, and a "
                  "fresh `--atExit --list` capture answers the same question about this "
                  "host.")
            return 1
        failures = red_team(text, baseline, objc_names, module)
        print("%d leak-audit red-team failure(s)" % failures)
        return 1 if failures else 0
    if "--growth" in arguments:
        # Both halves are judged on their own before the difference between them is judged:
        # a growth run that quietly stops checking the ceiling would be a weaker gate hiding
        # inside a stronger-sounding one.
        host_class = baseline.get("host_class")
        problems = []
        notes = []
        sweeps = []
        for cycles, where in ((1, report_path),
                              (growth_cycles, sibling_report(report_path, growth_cycles))):
            sweep_text, sweep_probe = capture(timeout, where, cycles=cycles)
            if sweep_text is None:
                return 1
            per_class, _total, _summary, _blocks, ours = count_leaks(sweep_text,
                                                                    objc_names, module)
            problems += report(sweep_text, baseline, objc_names, module)
            sweeps.append({"cycles": cycles, "library": library_hosts(sweep_probe),
                           "ours": ours, "hosts": per_class.get(host_class, 0),
                           "reads": host_reads_per_visit(sweep_probe)})
        growth_problems, growth_notes = judge_growth(sweeps[0], sweeps[1], baseline)
        problems += growth_problems
        notes += growth_notes
        for note in growth_notes:
            print("note  %s" % note)
        for problem in problems:
            print("FAIL %s" % problem)
        print("%d leak-audit failure(s)" % len(problems))
        return 1 if problems else 0

    problems = report(text, baseline, objc_names, module)
    if "--write-baseline" in arguments:
        first_party, total, _summary, _blocks, ours_bytes = count_leaks(
            text, objc_names, module)
        host_class = baseline.get("host_class")
        hosts = first_party.get(host_class, 0) if host_class else 0
        if not hosts:
            print("FAIL --write-baseline refuses to write from a run that leaked no %s: "
                  "there is no host to divide by, so this run would record a ceiling of "
                  "zero for every ratio and call it a measurement"
                  % (host_class or "host class"))
            return 1
        fan_out = dict(baseline.get("apps_per_host", {}))
        for name, count in sorted(first_party.items()):
            if name == host_class:
                continue
            observed = -(-count // hosts)  # ceil: a partial host is still a whole app
            fan_out[name] = max(observed, fan_out.get(name, 0))
        # Ceil, because a partial host is still a whole host's worth of objects, and the
        # ceiling being judged is ours: the report's total includes every CoreFoundation
        # string the machine happened to be holding, and that number is not this
        # repository's to raise.
        observed_bytes = -(-ours_bytes // hosts)
        ceiling = max(observed_bytes, baseline.get("first_party_bytes_per_host", 0))
        baseline = dict(baseline)
        baseline["apps_per_host"] = fan_out
        baseline["first_party_bytes_per_host"] = ceiling
        baseline["observed"] = dict(baseline.get("observed", {}),
                                    hosts_seen=sorted(set(
                                        baseline.get("observed", {}).get("hosts_seen", [])
                                        + [hosts])),
                                    first_party_bytes_per_host=sorted(set(
                                        baseline.get("observed", {}).get(
                                            "first_party_bytes_per_host", [])
                                        + [observed_bytes])))
        with open(BASELINE, "w", encoding="utf-8") as handle:
            json.dump(baseline, handle, indent=1, sort_keys=True)
            # The trailing newline is not decoration: without it the writer dirties the
            # file on a run that raised nothing, and a gate that cannot be run without a
            # diff is a gate people stop running.
            handle.write("\n")
        print("wrote %s (a ceiling only ever goes up here; lowering one is a decision"
              " somebody makes in the commit that fixes the leak). Note that this raises"
              " the measured number, not the margin -- the slack and the byte floor stay"
              " where a human put them." % BASELINE)
        return 0
    for problem in problems:
        print("FAIL %s" % problem)
    if problems:
        # The rule says what broke; the blocks say what to go and look at. A red run on a
        # runner is otherwise a red run somebody has to reproduce locally to learn
        # anything, and the whole reason to run it on the runner is that the machine it
        # describes is not the one reading the log.
        ours = [line for line in text.splitlines()
                if LEAK_LINE.match(line)
                and is_first_party(LEAK_LINE.match(line).group(2), objc_names, module)]
        for line in ours[:20]:
            print("      %s" % line)
        if len(ours) > 20:
            print("      ... and %d more first-party block(s)%s"
                  % (len(ours) - 20,
                     ", all of them in the report `--report` wrote" if report_path
                     else ""))
    print("%d leak-audit failure(s)" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
