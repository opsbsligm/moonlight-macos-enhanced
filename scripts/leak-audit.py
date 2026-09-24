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

The comparison is deliberately not an equality. ``leaks`` answers for the machine it
ran on: this laptop has a host configured, so the settings page really builds a
temporary host graph and really leaks it, while CI's fresh HOME has no hosts and
leaks none of that. A gate that demanded the same numbers everywhere would be red in
whichever place it was written for. So the rule is a ceiling per class plus a ceiling
on total bytes, which is the shape that survives both places, and a class that stops
leaking is reported rather than silently forgiven -- lowering a baseline is a thing a
person does on purpose, in the commit that fixes the leak.

Why one rule is exact and the other carries a margin, measured rather than assumed: five
runs of the same build on one machine gave first-party counts of 18/6 every single time,
while the totals moved between 10,000 and 11,792 bytes and the leak count between 104 and
105. So a per-class ceiling is written as an exact number and the byte ceiling is the
highest observed (11,792) plus half again, rounded to 17,700 -- a byte ceiling that is red
because the runner's CoreFoundation allocated differently is a ceiling somebody mutes.

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
    """(per-class first-party counts, total bytes, summary line or None, blocks read).

    The block count is the reader's own answer to "how many leaked objects did I look at",
    and the judge compares it against the number the report claims. It is returned rather
    than inferred so the fixtures and the red team can drive the rule with a report of
    their own.
    """
    summary = None
    first_party = {}
    total = 0
    blocks = 0
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
    return first_party, total, summary, blocks


def judge(first_party, total, summary, baseline, blocks):
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
    for class_name in sorted(first_party):
        allowed = baseline.get("classes", {}).get(class_name)
        if allowed is None:
            problems.append("a first-party class nobody budgeted is leaking: %s (%d)"
                            % (class_name, first_party[class_name]))
        elif first_party[class_name] > allowed:
            problems.append("%s leaks %d instances where the ceiling is %d"
                            % (class_name, first_party[class_name], allowed))
    for class_name in sorted(baseline.get("classes", {})):
        if class_name not in first_party:
            notes.append("%s is not leaking in this run, where the ceiling carries %d -- "
                         "if that is because it was fixed, lower the ceiling in the same "
                         "commit" % (class_name, baseline["classes"][class_name]))
    ceiling = baseline.get("total_bytes")
    if ceiling is not None and total > ceiling:
        problems.append("the process leaked %d bytes against a ceiling of %d"
                        % (total, ceiling))
    return problems, notes


def report(text, baseline, objc_names, module):
    first_party, total, summary, blocks = count_leaks(text, objc_names, module)
    problems, notes = judge(first_party, total, summary, baseline, blocks)
    print("leak-audit: %d leaked bytes over %d block(s), first-party classes: %s"
          % (total, blocks, ", ".join("%s=%d" % kv for kv in sorted(first_party.items()))
             or "none"))
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
    base = {"classes": {"TemporaryApp": 2, "TemporaryHost": 1}, "total_bytes": 400}
    clean = ("Process 9: 4 leaks for 300 total leaked bytes\n"
             "Leak: 0x1  size=64  zone: MallocZone   TemporaryApp  ObjC  MoonlightEnhanced\n"
             "Leak: 0x2  size=64  zone: MallocZone   TemporaryApp  ObjC  MoonlightEnhanced\n"
             "Leak: 0x3  size=64  zone: MallocZone   TemporaryHost  ObjC  MoonlightEnhanced\n"
             "Leak: 0x4  size=108  zone: MallocZone   CFString  ObjC  CoreFoundation\n")
    new_class = clean.replace(
        "Leak: 0x4  size=108  zone: MallocZone   CFString  ObjC  CoreFoundation",
        "Leak: 0x4  size=108  zone: MallocZone   AppDelegateForAppKit  ObjC  MoonlightEnhanced")
    grown = clean.replace("TemporaryApp  ObjC", "TemporaryHost  ObjC", 1)
    heavy = clean.replace("for 300 total leaked", "for 900 total leaked")
    empty = "Process 9:\nLeak: 0x1  size=64  zone: MallocZone   TemporaryApp  ObjC\n"
    # The shape of the first report this gate ever read: the summary counts every leak,
    # the body draws the graph, and the only blocks written out as blocks are the few the
    # tree chose to detail. Read by a reader that wants a line per block it says "none of
    # yours is leaking", which is why it is a case and not a footnote.
    tree = ("Process 9: 4 leaks for 300 total leaked bytes\n"
            " DISTANT CYCLE\n"
            "+  1 0x1  64 B  CFString  CoreFoundation\n")
    gone = ("Process 9: 1 leaks for 64 total leaked bytes\n"
            "Leak: 0x1  size=64  zone: MallocZone   TemporaryApp  ObjC\n")
    swift = ("Process 9: 1 leaks for 64 total leaked bytes\n"
             "Leak: 0x1  size=64  zone: MallocZone   "
             "_TtC17MoonlightEnhanced13SettingsModel  ObjC\n")
    cases = [("the shipped shape passes", clean, 0, None),
             ("a class nobody budgeted starts leaking", new_class, 1, None),
             ("a budgeted class leaks more instances than the ceiling", grown, 1, None),
             ("total bytes grow past the ceiling", heavy, 1, None),
             ("a report with no summary line", empty, 1, None),
             ("a Swift class is ours too, mangling and all", swift, 1, None),
             ("a budgeted class that stopped leaking is a note, not a failure",
              gone, 0, "not leaking in this run"),
             ("the default tree: a summary that outruns what the reader read",
              tree, 1, "never looked at")]
    failures = 0
    for label, text, want_problems, want_note in cases:
        first_party, total, summary, blocks = count_leaks(text, names, module)
        problems, notes = judge(first_party, total, summary, base, blocks)
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
    first_party, total, summary, blocks = count_leaks(text, objc_names, module)
    blockers = []
    if summary is None:
        blockers.append("the report handed to the red team carries no summary line, so "
                        "there is no sweep here to break")
    elif blocks != summary[0]:
        blockers.append("the report handed to the red team reads %d block(s) against the "
                        "%d its own summary counts, so breaking it would prove nothing "
                        "about a real sweep" % (blocks, summary[0]))
    budgeted = sorted(baseline.get("classes", {}))
    if not budgeted:
        blockers.append("the baseline budgets no class, so there is no ceiling to break")
    if summary is not None and blocks == summary[0] and not first_party:
        blockers.append("the report carries no first-party block, so the growth rule has "
                        "nothing to grow -- aim the red team at a sweep that leaks")
    unbudgeted = sorted(name for name in objc_names
                        if name not in budgeted and name not in first_party)
    if not unbudgeted:
        blockers.append("every class this repository declares is already budgeted, so no "
                        "name is left to plant")
    if blockers:
        for blocker in blockers:
            print("FAIL red team cannot run: %s" % blocker)
        return len(blockers)

    ceiling = baseline.get("total_bytes", 0)
    grown = budgeted[0]
    extra = baseline["classes"][grown] + 1 - first_party.get(grown, 0)
    quiet = budgeted[1] if len(budgeted) > 1 else None

    cases = []
    flooded = flood(text, grown, max(extra, 1))
    cases.append(("a budgeted class grows past its ceiling",
                  recount(flooded, summary[0] + max(extra, 1)), 1,
                  "ceiling is %d" % baseline["classes"][grown]))
    planted = flood(text, unbudgeted[0], 1)
    cases.append(("a class nobody budgeted starts leaking",
                  recount(planted, summary[0] + 1), 1, "nobody budgeted"))
    cases.append(("the byte ceiling is broken",
                  re.sub(r"( leaks for )\d+", lambda m: "%s%d" % (m.group(1), ceiling + 1),
                         text, count=1), 1, "against a ceiling of %d" % ceiling))
    cases.append(("the summary is cut off",
                  "\n".join(line for line in text.splitlines()
                             if SUMMARY.search(line) is None), 1, "no `leaks for"))
    cases.append(("the blocks disappear but the summary stays",
                  "\n".join(line for line in text.splitlines()
                             if not LEAK_LINE.match(line)), 1, "never looked at"))
    if quiet:
        dropped = [line for line in text.splitlines()
                   if not (LEAK_LINE.match(line)
                           and LEAK_LINE.match(line).group(2) == quiet)]
        kept = sum(1 for line in dropped if LEAK_LINE.match(line))
        cases.append(("a budgeted class is genuinely fixed", recount("\n".join(dropped) + "\n",
                                                                    kept), 0,
                      "%s is not leaking in this run" % quiet))

    failures = 0
    for label, mutated, want_problems, want_text in cases:
        per_class, mutated_total, mutated_summary, mutated_blocks = count_leaks(
            mutated, objc_names, module)
        problems, notes = judge(per_class, mutated_total, mutated_summary, baseline,
                                mutated_blocks)
        answer = 0 if not problems else 1
        said = problems if want_problems else notes
        if answer != want_problems:
            print("FAIL red team: %s -- expected %s, got %s"
                  % (label, "a refusal" if want_problems else "a pass",
                     "; ".join(problems) or "a clean answer"))
            failures += 1
        elif not any(want_text in line for line in said):
            print("FAIL red team: %s refused for the wrong reason: %s"
                  % (label, "; ".join(said) or "(nothing)"))
            failures += 1
        else:
            print("ok   red team: %s" % label)
    return failures


def capture(timeout):
    """Run the Debug probe under `leaks` and hand back its report."""
    tool = shutil.which("leaks")
    if tool is None:
        print("FAIL no `leaks` on this host -- install the Xcode command line tools."
              " This gate refuses rather than skipping, because a memory sweep that did"
              " not run is exactly what a green check with no memory sweep looks like.")
        return None
    app = os.path.join(DERIVED, "Build", "Products", "Debug",
                       project_identity.product_name() + ".app")
    if not os.path.isdir(app):
        print("FAIL no Debug build at %s -- `render-probe.py` builds it" % app)
        return None
    home = tempfile.mkdtemp(prefix="leak-home.")
    out = tempfile.mkdtemp(prefix="leak-out.")
    binary = os.path.join(app, "Contents", "MacOS", project_identity.bundle_executable(app))
    env = dict(os.environ, HOME=home, ML_RENDER_PROBE="1", ML_RENDER_PROBE_OUTPUT=out)
    proc = subprocess.run([tool, "--atExit", "--list", "--", binary],
                          capture_output=True, text=True, env=env, timeout=timeout,
                          cwd=ROOT)
    # `leaks` exits 1 when it found leaks, which is the normal answer for a real app.
    if SUMMARY.search(proc.stdout) is None:
        print("FAIL `leaks` produced no summary (exit %d):\n%s"
              % (proc.returncode, proc.stdout[-400:]))
        return None
    return proc.stdout


# A flag's value is not a positional, and the mistake of treating it as one is worth
# naming: `--log leaks-arm64.log` would otherwise be read as the repository to scan, the
# scan would find no classes at all, and the gate would pass every leak in the file.
VALUE_FLAGS = ("--timeout", "--log")


def parse(arguments):
    """(root, timeout, log path or None), keeping flag values out of the positionals."""
    root = ROOT
    timeout = 900
    log = None
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in VALUE_FLAGS:
            value = arguments[index + 1]
            if argument == "--timeout":
                timeout = int(value)
            else:
                log = value
            index += 2
            continue
        if not argument.startswith("--"):
            root = argument
        index += 1
    return root, timeout, log


def main():
    arguments = sys.argv[1:]
    root, timeout, log = parse(arguments)
    text = None
    if log is not None:
        text = open(log, encoding="utf-8", errors="replace").read()
    if "--self-test" in arguments:
        failures = fixtures() + class_discovery_fixture()
        print("%d leak-audit fixture failure(s)" % failures)
        return 1 if failures else 0
    if text is None:
        text = capture(timeout)
        if text is None:
            return 1
    module = project_identity.product_name()
    objc_names = first_party_classes(root)
    baseline = (json.load(open(BASELINE, encoding="utf-8"))
                if os.path.exists(BASELINE) else {"classes": {}, "total_bytes": 0})
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
    problems = report(text, baseline, objc_names, module)
    if "--write-baseline" in arguments:
        first_party, total, _summary, _blocks = count_leaks(text, objc_names, module)
        classes = dict(baseline.get("classes", {}))
        for name, count in first_party.items():
            classes[name] = max(count, classes.get(name, 0))
        ceiling = max(total, baseline.get("total_bytes", 0))
        json.dump({"classes": classes, "total_bytes": ceiling},
                  open(BASELINE, "w", encoding="utf-8"), indent=1, sort_keys=True)
        print("wrote %s (a ceiling only ever goes up here; lowering one is a decision"
              " somebody makes in the commit that fixes the leak)" % BASELINE)
        return 0
    for problem in problems:
        print("FAIL %s" % problem)
    print("%d leak-audit failure(s)" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
