#!/usr/bin/env python3
"""Keep the static analyzer's findings from growing, and prove it actually ran.

xcodebuild analyze finds what review does not. On this tree it found a CGEvent
created and never released on every gamepad navigation press, a CGPath handed
out with a +1 reference and a name that does not say so (one caller released it,
the caller in another file leaked one per shadow refresh), and a struct stored as
the previous gamepad state while holding whatever the stack happened to contain.
Those are the same shape as the input bugs this project keeps being asked about.

The finding list cannot be "zero", because some findings are modelling limits
rather than defects: an NSNumber nil test that the retain-count checker reads as
a boolean conversion, a VideoToolbox parameter Apple documents as pass-NULL while
the header marks it nonnull. So the comparison is against a committed baseline,
keyed by file, checker and message shape, and counted. A new class fails, one
more instance of an accepted class fails, and a finding that got fixed fails
until the baseline says so -- which is the point, because a baseline nobody has
to acknowledge is a to-do list that reads as done.

The size of the sweep is checked before any of that, for the reason this
repository has now been bitten by twice: an analyzer that did not run reports no
findings, and a gate that reads silence as cleanliness reports success.

Usage:
  analyzer-audit.py [root] --log <transcript>            audit one run
  analyzer-audit.py [root] --write-baseline --log <t>     refresh the baseline
  analyzer-audit.py [root] --self-test                    fixtures only, no log
Exit 0 only when the sweep is real and the findings match the baseline.
"""
import io, json, os, re, sys, tempfile

ANALYZED = re.compile(r"--analyze (\S+\.(?:m|mm|c))")
FINDING = re.compile(r"(\S+?\.(?:m|mm|c|h|swift)):(\d+):(\d+): warning: "
                     r"(.*?)(?:\s+\[([A-Za-z0-9._]+)\])?\s*$")
# Findings outside these directories belong to vendored code we do not own.
PROJECT_PREFIXES = ("Limelight/", "Moonlight/")
# The target excludes a handful of implementation files with a documented reason,
# and analyze only reaches what the target compiles, so the sweep is allowed to
# come up short by this much and not one key more.
SWEEP_SLACK = 20

def parse_arguments(argv):
    """Split the command line into flags, the tree, and the transcript.

    The transcript path is a value, not a flag, and the tree argument is positional
    in either order, so the value after --log has to be taken out of the positionals
    before the first one is read as the root. Reading it as the root is how an audit
    ends up looking for scripts inside its own log file.
    """
    arguments = list(argv)
    log_path = None
    if "--log" in arguments:
        index = arguments.index("--log") + 1
        if index < len(arguments):
            log_path = arguments[index]
            del arguments[index]
        arguments.remove("--log")
    positional = [a for a in arguments if not a.startswith("--")]
    return {
        "root": positional[0] if positional else ".",
        "log": log_path,
        "write_baseline": "--write-baseline" in arguments,
        "self_test": "--self-test" in arguments,
    }


options = parse_arguments(sys.argv[1:])
root = options["root"]
log_path = options["log"]
write_baseline = options["write_baseline"]
run_self_test = options["self_test"]
baseline_path = os.path.join(root, "scripts", "analyzer-baseline.json")

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def message_shape(message):
    """The finding without the parts that move when unrelated code moves.

    Line numbers are not in the key at all, and quoted names and integers are
    removed here, so renaming a variable or shifting a function does not read as
    a new finding, and a new finding cannot hide behind an existing line number.
    """
    shape = re.sub(r"'[^']*'", "X", message)
    shape = re.sub(r'"[^"]*"', "X", shape)
    shape = re.sub(r"\b\d+\b", "N", shape)
    return shape.strip()


def project_source_count(scan_root):
    """Implementation files on disk, which is the ceiling on any honest sweep."""
    total = 0
    for directory, _, names in os.walk(os.path.join(scan_root, "Limelight")):
        total += sum(1 for name in names if name.endswith((".m", ".mm", ".c")))
    return total


def relative_to_project(path):
    """Trim a transcript path to the repository, however the compiler spelled it."""
    path = path.replace("\\", "/")
    for prefix in PROJECT_PREFIXES:
        index = path.find("/" + prefix)
        if index >= 0:
            return path[index + 1:]
        if path.startswith(prefix):
            return path
    return None


def parse_transcript(text):
    """The analyzed files and the findings, as (file, checker, shape) counts."""
    analyzed = set()
    findings = {}
    for line in text.splitlines():
        match = ANALYZED.search(line)
        if match:
            project_path = relative_to_project(match.group(1))
            if project_path:
                analyzed.add(project_path)
        for match in FINDING.finditer(line):
            project_path = relative_to_project(match.group(1))
            if project_path is None:
                continue
            key = (project_path, match.group(5) or "unknown",
                   message_shape(match.group(4)))
            findings[key] = findings.get(key, 0) + 1
    return analyzed, findings


def sweep_health(analyzed, source_count, scan_root="."):
    """Why the sweep cannot be trusted, or None when it can.

    Silence from an analyzer that never ran and silence from a clean tree have to
    be tellable apart before any comparison means anything.
    """
    if not analyzed:
        return ("the transcript contains no analyze command for a project file, so "
                "the analyzer did not run here")
    floor = max(1, source_count - SWEEP_SLACK)
    if len(analyzed) < floor:
        return ("only %d project files were analysed against %d implementation "
                "files on disk, so the sweep is partial and its silence means "
                "nothing" % (len(analyzed), source_count))
    missing = sorted(path for path in analyzed
                     if not os.path.exists(os.path.join(scan_root, path)))
    if missing:
        return "%d analysed paths are not files in this tree, e.g. %s" % (len(missing), missing[0])
    return None


def compare(findings, baseline):
    """Findings that are new, more frequent, or gone without the baseline knowing."""
    added = {key: count for key, count in findings.items() if key not in baseline}
    grown = {key: count - baseline[key] for key, count in findings.items()
             if key in baseline and count > baseline[key]}
    gone = {key: baseline[key] - findings.get(key, 0) for key in baseline
            if findings.get(key, 0) < baseline[key]}
    return added, grown, gone


def key_text(key):
    path, checker, shape = key
    return "%s [%s] %s" % (path, checker, shape)


def load_baseline(path):
    if not os.path.exists(path):
        return {}
    document = json.load(io.open(path, encoding="utf-8"))
    return {(entry["file"], entry["checker"], entry["shape"]): entry["count"]
            for entry in document.get("findings", [])}


# The reasons a person wrote for accepting a finding. Used only when there is no
# baseline to read them from: a regeneration has to keep what is on file rather than
# replace it with this.
DEFAULT_ACCEPTED_REASONS = {

        "NSNumber nil test read as a boolean conversion":
            "the retain-count checker reports any NSNumber in a condition, "
            "including a nil test, and these sites compare or test for nil",
        "VideoToolbox parameter documented as pass-NULL":
            "Apple's VTDecompressionSessionCreate says pass NULL for the "
            "default decoder; the header marks the parameter nonnull",
        "CoreFoundation reference kept in an assign property":
            "clang does not manage a CF typed property, so the checker sees a "
            "store into a non-owning slot and cannot follow the release in "
            "another method; BackgroundColorView retains before releasing and "
            "never calls CFRetain or CFRelease with NULL, and HIDSupport "
            "releases its manager both in tearDownHidManager and in dealloc",
        "dead store":
            "a value written and then overwritten or ignored: no behaviour "
            "depends on it, and removing it changes nothing a test can see",
}


def load_baseline_document(path):
    """The baseline as written, reasons and all, or nothing if there is none."""
    if not os.path.exists(path):
        return None
    try:
        return json.loads(io.open(path, encoding="utf-8").read())
    except ValueError:
        return None


def unexplained_shapes(findings, reasons):
    """Accepted findings that no written reason covers.

    A reason is keyed by a phrase from the message shape, which is how a reader of
    the baseline finds the explanation for a line in it.
    """
    keys = [key.lower() for key in reasons]
    return sorted({shape for (_file, _checker, shape) in findings
                   if not any(key in shape.lower() for key in keys)})


def save_baseline(path, findings, previous_document=None):
    """Write the accepted findings, keeping whatever reasons a person wrote.

    The reasons are the part of the baseline a human wrote and the part a
    regeneration cannot know. This function used to carry a fixed copy of them and
    overwrite the file with that copy, so refreshing the baseline after one fixed
    finding also deleted the explanation behind every other one -- and reported
    success while doing it. A refresh now keeps what is on file and refuses to invent
    a reason for a class nobody has read.
    """
    previous = previous_document if isinstance(previous_document, dict) else {}
    reasons = previous.get("_accepted_reasons") or DEFAULT_ACCEPTED_REASONS
    document = {
        "_about": "Accepted static analyzer findings. Compare is by file, checker "
                  "and message shape, counted. Regenerate with "
                  "`python3 scripts/analyzer-audit.py --write-baseline --log <transcript>` "
                  "and read the diff: an entry that disappears means a finding was "
                  "fixed, which is the only good reason for one to go.",
        "_accepted_reasons": reasons,
        "findings": [{"count": count, "file": file_, "checker": checker, "shape": shape}
                     for (file_, checker, shape), count in sorted(findings.items())],
    }
    io.open(path, "w", encoding="utf-8").write(json.dumps(document, indent=2,
                                                          ensure_ascii=False) + "\n")


# A transcript where the analyzer ran on two files and produced two findings of
# one class and one of another, plus a line that must not be read as a finding.
FIXTURE_TRANSCRIPT = """
Analyze Limelight/macOS/Views/AlphaView.m normal arm64
    /usr/bin/clang --analyze /abs/path/Limelight/macOS/Views/AlphaView.m -o out.plist
warning noise with no location
Limelight/macOS/Views/AlphaView.m:40:26: warning: Potential leak of an object stored into 'cgEvent' [osx.cocoa.RetainCount]
2026-09-14T13:00:04.0Z Limelight/macOS/Views/AlphaView.m:91:9: warning: Potential leak of an object stored into 'otherEvent' [osx.cocoa.RetainCount]
    /usr/bin/clang --analyze /abs/path/Limelight/macOS/Views/BetaView.m -o out.plist
Limelight/macOS/Views/BetaView.m:7:1: warning: Value stored to 'x' is never read [deadcode.DeadStores]
"""

FIXTURE_BASELINE = {
    ("Limelight/macOS/Views/AlphaView.m", "osx.cocoa.RetainCount",
     "Potential leak of an object stored into X"): 2,
    ("Limelight/macOS/Views/BetaView.m", "deadcode.DeadStores",
     "Value stored to X is never read"): 1,
}

FIXTURE_EMPTY_RUN = """
Analyze Limelight/macOS/Views/AlphaView.m normal arm64
    nothing here that analyses anything
"""

FIXTURE_PARTIAL_RUN = """
    /usr/bin/clang --analyze /abs/path/Limelight/macOS/Views/AlphaView.m -o out.plist
"""


def self_test():
    analyzed, findings = parse_transcript(FIXTURE_TRANSCRIPT)
    check(findings == FIXTURE_BASELINE,
          "the transcript parses into the expected counts"
          if findings == FIXTURE_BASELINE else
          "parsed %s" % sorted(findings.items()))
    check(len(analyzed) == 2, "both analysed files are counted")
    added, grown, gone = compare(findings, FIXTURE_BASELINE)
    check(not (added or grown or gone), "a matching baseline is accepted")

    one_short = dict(FIXTURE_BASELINE)
    one_short[("Limelight/macOS/Views/AlphaView.m", "osx.cocoa.RetainCount",
               "Potential leak of an object stored into X")] = 1
    added, grown, gone = compare(findings, one_short)
    check(bool(grown), "one more instance of an accepted finding is refused")

    one_more = dict(FIXTURE_BASELINE)
    one_more[("Limelight/macOS/Views/AlphaView.m", "osx.cocoa.RetainCount",
              "Potential leak of an object stored into X")] = 3
    added, grown, gone = compare(findings, one_more)
    check(bool(gone) and not added and not grown,
          "a finding that went away is reported instead of quietly accepted")

    added, grown, gone = compare(findings, {})
    check(len(added) == 2, "a new class of finding is refused")

    _, renamed = parse_transcript(
        "Limelight/macOS/Views/AlphaView.m:41:3: warning: Potential leak of an "
        "object stored into 'renamedVariable' [osx.cocoa.RetainCount]")
    check(renamed == {("Limelight/macOS/Views/AlphaView.m", "osx.cocoa.RetainCount",
                       "Potential leak of an object stored into X"): 1},
          "renaming a variable does not create a finding")

    check(sweep_health(set(), 100) is not None, "a run that analysed nothing is refused")
    analyzed_only_noise, _ = parse_transcript(FIXTURE_EMPTY_RUN)
    check(sweep_health(analyzed_only_noise, 100) is not None,
          "a transcript with no analyze command is refused")
    partial, _ = parse_transcript(FIXTURE_PARTIAL_RUN)
    check(sweep_health(partial, 100) is not None, "a partial sweep is refused")
    split = parse_arguments(["--log", "/tmp/run.log"])
    check(split["root"] == "." and split["log"] == "/tmp/run.log",
          "the transcript is not read as the tree")
    split = parse_arguments(["repo", "--log", "/tmp/run.log", "--self-test"])
    check(split["root"] == "repo" and split["self_test"] and split["log"] == "/tmp/run.log",
          "flags and a positional tree work in any order")

    _, absolute = parse_transcript(
        "2026-09-14T13:00:04.0Z\t/Users/builds/checkout/Limelight/macOS/Views/"
        "AlphaView.m:9:1: warning: Potential leak of an object stored into "
        "'cgEvent' [osx.cocoa.RetainCount]")
    check(absolute == {("Limelight/macOS/Views/AlphaView.m", "osx.cocoa.RetainCount",
                        "Potential leak of an object stored into X"): 1},
          "a finding reported with an absolute path is still counted")
    _, vendored = parse_transcript(
        "/Users/builds/checkout/Packages/OpenSSL.xcframework/Headers/ssl.h:4:1: "
        "warning: Something about 'x' [deadcode.DeadStores]")
    check(vendored == {}, "a finding in vendored code is not this project's")

    # The reasons are what a person wrote. A refresh that replaces them with a
    # generic sentence, or invents one for a class nobody has read, is a tool
    # reporting success while deleting the audit it was supposed to serve.
    with tempfile.TemporaryDirectory() as tmp:
        written_path = os.path.join(tmp, "baseline.json")
        human = {"_accepted_reasons":
                 {"potential leak of an object stored into X":
                  "a reason a person wrote after reading the code"},
                 "findings": []}
        io.open(written_path, "w", encoding="utf-8").write(json.dumps(human))
        save_baseline(written_path, FIXTURE_BASELINE, load_baseline_document(written_path))
        written = json.loads(io.open(written_path, encoding="utf-8").read())
        check(written["_accepted_reasons"].get(
                  "potential leak of an object stored into X")
              == "a reason a person wrote after reading the code",
              "refreshing the baseline keeps a reason a person wrote")
        check(unexplained_shapes(FIXTURE_BASELINE, written["_accepted_reasons"])
              == ["Value stored to X is never read"],
              "a refresh can say which accepted findings lost their explanation")
        check(unexplained_shapes(FIXTURE_BASELINE, {
                  "potential leak of an object stored into X": "r",
                  "value stored to x": "r"}) == [],
              "a reason covering every shape leaves nothing pending")
        check(load_baseline_document(os.path.join(tmp, "nothing.json")) is None,
              "a missing baseline is not read as an empty one")
        io.open(written_path, "w", encoding="utf-8").write("{not json")
        check(load_baseline_document(written_path) is None,
              "a baseline that will not parse is not read as an empty one")

    real = "Limelight/Input/HIDSupport.m"
    check(sweep_health({real}, 2) is None, "a full sweep of a small tree is accepted")
    check(sweep_health({real}, 2, "no-such-tree") is not None,
          "an analysed file that is not in this tree is refused")


if run_self_test:
    self_test()
    print("%d analyzer audit self-test failures" % len(failures))
    sys.exit(1 if failures else 0)

if log_path is None:
    raise SystemExit("a transcript is required: --log <path>, or --self-test")

text = io.open(log_path, encoding="utf-8", errors="replace").read()
analyzed, findings = parse_transcript(text)
health = sweep_health(analyzed, project_source_count(root), root)
check(health is None, "the analyzer really ran on this tree"
      if health is None else "the analyzer sweep is not trustworthy: " + health)

if write_baseline:
    previous = load_baseline_document(baseline_path)
    pending = [] if previous is None else unexplained_shapes(
        findings, previous.get("_accepted_reasons", {}))
    for shape in pending:
        # A note, not a refusal: the reasons are keyed by phrases a reader chose, so
        # a shape they already explained under a different phrase is not an absence.
        # A refresh that cannot say which lines lost their explanation is the failure.
        print("::notice::no reason phrase in the baseline matches this shape, add one if "
              "it is not covered: %s" % shape)
    if not failures:
        save_baseline(baseline_path, findings, previous)
        print("wrote %d accepted findings to %s, keeping the reasons already on file"
              % (len(findings), baseline_path))
    sys.exit(1 if failures else 0)

baseline = load_baseline(baseline_path)
check(bool(baseline) or not findings, "the accepted finding baseline exists")
added, grown, gone = compare(findings, baseline)
for key, count in sorted(added.items())[:12]:
    print("::error file=%s::new static analyzer finding, %d instance(s): %s"
          % (key[0], count, key_text(key)))
for key, count in sorted(grown.items())[:12]:
    print("::error file=%s::more instances than accepted (%d more): %s"
          % (key[0], count, key_text(key)))
for key, count in sorted(gone.items())[:12]:
    print("::error file=%s::accepted finding no longer reported (%d): refresh the "
          "baseline after reading this: %s" % (key[0], count, key_text(key)))
check(not (added or grown or gone),
      "%d analysed files, %d findings, all of them accepted" % (len(analyzed), sum(findings.values()))
      if not (added or grown or gone) else
      "static analyzer findings differ from the baseline: %d new, %d grown, %d gone"
      % (len(added), len(grown), len(gone)))

print("%d analyzer audit failures" % len(failures))
sys.exit(1 if failures else 0)
