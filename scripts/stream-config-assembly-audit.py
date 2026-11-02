#!/usr/bin/env python3
"""Report a stream-configuration field the stream reads and nobody ever writes.

`StreamConfiguration` is the object the window hands the stream at start-up. Its
properties are declared in one header, filled in inside `startStream` in
`StreamViewController.m`, and read on the other side by `Connection.m` and
`VideoDecoderRenderer.m`. Nothing connects those three. A property nobody assigns keeps
Objective-C's zero initialisation, so it reads as `NO`/`0`/`nil` forever, the build is
clean, the app launches, and a setting the player can see does nothing.

That is not a hypothetical. `shortQueueOnDoubledCadence` shipped with its Settings
switch, its persisted field, its exported dictionary row, and a renderer that trims a
frame off the pending queue when it is set -- and no assembly line anywhere. Wave Z-3's
`settings-usage-audit.py` could not see it, and was right not to: that audit asks
whether anything *acts on* a persisted key, and the renderer does act on this one. The
missing link sits one stage later, in the hop from the settings dictionary into the
configuration object, and no audit looked there. This gate asks the question that was
never asked: for every field of the object the stream reads, does anything write it.

Receiver identity is what makes the question answerable. `Connection.m` holds a C
struct member spelled `_streamConfig` whose fields collide with property names --
`_streamConfig.enableHdr = config.enableHdr` writes the *struct*, and crediting that as
an assignment to the object would hide a genuinely unwritten property forever. So a
write counts only through an identifier this audit has seen declared as
`StreamConfiguration *`: a local, a parameter, or an ivar. `SCStreamConfiguration` is
ScreenCaptureKit's unrelated class and stays out by a word boundary, not by luck.

"Unwritten" and "harmless" are still different claims, because zero initialisation means
an unwritten field has a defined value. A field whose shipped behaviour *is* zero is not
broken, it is unconfigurable; the ledger records which, and an entry stays valid only
while the source still spells that value.

Usage:
  stream-config-assembly-audit.py            # audit the current tree
  stream-config-assembly-audit.py --json
  stream-config-assembly-audit.py --self-test
  stream-config-assembly-audit.py --write-baseline
Exit 0 only when every property that is read somewhere is also written somewhere, or
sits in the ledger with a reason that still matches the source.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "scripts", "stream-config-assembly-baseline.json")
HEADER = os.path.join("Limelight", "Stream", "StreamConfiguration.h")
SOURCES = os.path.join("Limelight", "macOS", "ViewControllers", "StreamViewController.m")
# The object is declared with this spelling and no other, in either shape it appears: a
# local or ivar (`StreamConfiguration *_config;`) or a parameter
# (`initWithConfig:(StreamConfiguration *)config`). The optional `)` is not decoration:
# without it the parameter shape is invisible, the reads in `VideoDecoderRenderer.m`
# disappear with it, and an unwritten-but-read field reports itself as merely *unused*
# -- a wrong verdict, not a missing one. The lookbehind keeps SCStreamConfiguration
# (ScreenCaptureKit) out: same suffix, different class, and its `configuration.width`
# writes have nothing to do with ours.
DECLARATION = re.compile(r"(?<![A-Za-z])StreamConfiguration\s*\*\s*\)?\s*(\w+)")
PROPERTY = re.compile(r"@property\s*\([^)]*\)\s*([^;]+);")
# Modifiers and nullability spellings that sit between `@property(...)` and the type.
QUALIFIERS = re.compile(
    r"\b(?:nonatomic|assign|copy|strong|weak|readonly|readwrite|atomic|retain|"
    r"dangerous|class|nonnull|nullable|null_unspecified|null_resettable|"
    r"null_completes|getter|setter|objc)\b")


def path(*parts):
    return os.path.join(ROOT, *parts)


def read(relative):
    with open(path(relative), encoding="utf-8", errors="ignore") as handle:
        return handle.read()


class Tree:
    """The sources the audit reads, as text, with per-file overrides.

    Every conclusion comes from source text, so the self-test rewrites source text and
    the audit re-derives everything from it -- the same discipline as
    `settings-usage-audit.py`. A test that edited a verdict list would only prove the
    test could edit a list.
    """

    def __init__(self, overrides=None):
        self.overrides = dict(overrides or {})

    def read(self, relative):
        if relative in self.overrides:
            return self.overrides[relative]
        return read(relative)

    def with_override(self, relative, text):
        return Tree({**self.overrides, relative: text})

    def sources(self):
        """Every first-party `.swift`/`.m`/`.mm`/`.h`, build trees excluded.

        `scripts/` is outside `Limelight/` and therefore never walked, which matters:
        `scripts/fixtures/enhanced-queue-depth.m` declares its own stub
        `shortQueueOnDoubledCadence` and assigns it, so crediting a fixture would
        certify that the real tree assembled the value from a test harness.
        """
        found = []
        base = path("Limelight")
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith("build") and d not in ("Pods", "carthage")]
            for name in filenames:
                if name.endswith((".swift", ".m", ".mm", ".h")):
                    found.append(os.path.relpath(os.path.join(dirpath, name), ROOT))
        return sorted(found)


def properties(tree, relative=HEADER):
    """Property names declared by the configuration class, in declaration order.

    The name is the last bare identifier of the declaration. Type tokens, generics and
    pointer stars are stripped first so `NSArray<NSNumber *> *counts` still yields
    `counts`; a name that starts uppercase means the parse left a type behind, and that
    is dropped rather than reported as a phantom field.
    """
    text = tree.read(relative)
    names = []
    for match in PROPERTY.finditer(text):
        declaration = QUALIFIERS.sub(" ", match.group(1))
        declaration = re.sub(r"[()<>*]", " ", declaration)
        tokens = [token for token in re.split(r"[\s,:]+", declaration) if token]
        if len(tokens) < 2:
            continue
        name = tokens[-1]
        if name[0].islower():
            names.append(name)
    return names


def receivers(tree):
    """Identifiers this tree has seen declared as `StreamConfiguration *`.

    Collected across every source file, because the object is created in one file, kept
    in an ivar in another, and read through a parameter in a third. An identifier never
    declared with that type -- `_streamConfig`, the C struct in `Connection.m` -- cannot
    lend its writes to a property of the object.
    """
    found = set()
    for relative in tree.sources():
        if relative == HEADER:
            continue
        found.update(DECLARATION.findall(tree.read(relative)))
    return found


ACCESS = re.compile(r"(?<![\w.]) (\w+) [ \t]*(?:->|\.)[ \t]*(\w+) \b", re.X)


def strip_comments(text):
    """Blank out comment regions and string bodies, keeping every offset.

    The first version scanned raw source and was wrong because of it: a comment whose
    previous line ended in a full stop let the scanner pair that full stop with the
    receiver on the next line, which consumed the receiver and left the one property this
    gate exists to watch unseen -- the gate reported a fixed defect as still present. The
    gap between receiver and member is now same-line only, and prose is gone, because a
    mention in a comment is a claim about the code, not the code. Blanks rather than
    deletions keep offsets and line structure, so a site is still named by its real line.

    String bodies are blanked too, both ways round: a double slash in a URL or a path
    would otherwise open a comment that is not there, and a format string would otherwise
    read as an accessor on some class nobody declared. Comments are recognised before
    quotes, or an apostrophe in prose would open a string and swallow the code after it,
    so only the double quote counts as a string start. An escape consumes two characters
    so a backslash before a quote cannot be mistaken for the end of a literal.
    """
    out = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "/" and text[index + 1:index + 2] == "/":
            end = text.find("\n", index)
            end = length if end < 0 else end
            out.append(" " * (end - index))
            index = end
            continue
        if char == "/" and text[index + 1:index + 2] == "*":
            end = text.find("*/", index + 2)
            end = length if end < 0 else end + 2
            out.append("".join(ch if ch == "\n" else " " for ch in text[index:end]))
            index = end
            continue
        if char == '"':
            end = index + 1
            while end < length and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            end = min(end + 1, length)
            out.append("".join(ch if ch == "\n" else " " for ch in text[index:end]))
            index = end
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _accesses(text):
    """Every `receiver.name` position in one file, with what follows it.

    One scan per file rather than one per (receiver, property) pair: the first version
    asked 68 properties times 4 receivers to scan every source separately, which made a
    single self-test run 49 seconds -- more than the pipeline budget this gate is meant
    to sit inside. Membership in the receiver and property sets is decided afterwards,
    which is what keeps the receiver rule intact; a `foo.bar` belonging to no class we
    care about is simply not in the sets. Comments are stripped first, for the reason
    spelled out on `strip_comments`.
    """
    for match in ACCESS.finditer(strip_comments(text)):
        yield match.group(1), match.group(2), text[match.end():match.end() + 24]


# A mention whose next token is a comparison is a read, not a write. `=(?!=)` is what
# makes that true rather than intended: an alternation leading with a bare `=` matches
# the first half of `==`, and the self-test caught a bare comparison being credited as
# an assembly line.
ASSIGNMENT = re.compile(r"^\s*(?:=(?!=)|\+=|-=|\|=|&=|\^=|\*=|/=|\+\+|--)")
COMPARISON = re.compile(r"^\s*(?:==|!=|===)")


def usage(tree, names, receivers_):
    """{name: {"writers": [...], "readers": [...]}} over every declared property."""
    sources = [(relative, tree.read(relative)) for relative in tree.sources()
               if relative != HEADER]
    wanted = set(names)
    usage_map = {name: {"writers": [], "readers": []} for name in names}
    for relative, text in sources:
        for receiver, name, tail in _accesses(text):
            if receiver not in receivers_ or name not in wanted:
                continue
            site = "%s (%s)" % (relative, receiver)
            if ASSIGNMENT.match(tail) and not COMPARISON.match(tail):
                usage_map[name]["writers"].append(site)
            else:
                usage_map[name]["readers"].append(site)
    return usage_map


def classify(tree):
    """One row per declared property, judged on who writes and who reads it."""
    names = properties(tree)
    receivers_ = receivers(tree)
    usage_map = usage(tree, names, receivers_)
    rows = []
    for name in names:
        writers = sorted(set(usage_map[name]["writers"]))
        readers = sorted(set(usage_map[name]["readers"]))
        if writers:
            state = "assembled"
        elif readers:
            # Read on the stream path, written nowhere: the stream sees the zero value
            # and no setting can change what it sees.
            state = "unwritten-read"
        else:
            state = "declared-unused"
        rows.append({"key": name, "state": state, "writers": writers, "readers": readers})
    return rows


def reason_for(row):
    """The falsifiable statement that has to keep matching for the debt to stay valid."""
    if row["state"] == "unwritten-read":
        return ("%s is read by %s and written by nothing, so the stream always sees the "
                "zero initial value" % (row["key"], ", ".join(row["readers"])))
    return "%s is declared and read by nothing outside its own header" % row["key"]


# ---------------------------------------------------------------------------
# debt ledger
# ---------------------------------------------------------------------------
def load_baseline():
    """{key: reason} from the committed ledger, or {} when there is none yet."""
    if not os.path.exists(BASELINE):
        return {}
    with open(BASELINE, encoding="utf-8") as handle:
        document = json.load(handle)
    return {entry["key"]: entry["reason"] for entry in document.get("debts", [])}


def write_baseline(rows):
    """Record today's unwritten fields with the source-bound reason each one carries."""
    debts = [{"key": row["key"], "reason": reason_for(row)}
             for row in rows if row["state"] != "assembled"]
    document = {"_about": (
        "StreamConfiguration fields that nothing writes. Regenerate with "
        "`python3 scripts/stream-config-assembly-audit.py --write-baseline` and read the "
        "diff: an entry that leaves means the field got assembled or the reason stopped "
        "matching, which is the only good reason for one to go. The reason names the "
        "reader, so a field that gains a different reader is a different debt and has to "
        "be re-reviewed."),
        "debts": debts}
    with open(BASELINE, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    return debts


def check_ledger(rows):
    """Compare the tree against the ledger; report new, drifted, and stale entries."""
    baseline = load_baseline()
    current = {row["key"]: row for row in rows if row["state"] != "assembled"}
    problems = []
    for key, row in sorted(current.items()):
        reason = reason_for(row)
        if key not in baseline:
            problems.append("NEW %s: %s" % (key, reason))
        elif baseline[key] != reason:
            problems.append("DRIFT %s: reason no longer matches the source\n"
                            "       ledger: %s\n       source: %s"
                            % (key, baseline[key], reason))
    for key in sorted(set(baseline) - set(current)):
        problems.append("STALE %s: no longer reported" % key)
    return problems


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------
def _overridden(tree, relative, pairs):
    """`tree` with `relative` rewritten by exact (old, new, count) replacements."""
    text = tree.read(relative)
    for old, new, count in pairs:
        found = text.count(old)
        if found != count:
            raise AssertionError("expected %d copies of %r, found %d" % (count, old, found))
        text = text.replace(old, new)
    return tree.with_override(relative, text)


def _state(rows, key):
    for row in rows:
        if row["key"] == key:
            return row["state"]
    return None


# (name, mutation, key, expected state): each mutation has to move exactly one verdict.
MUTATIONS = (
    # The defect this exists for: the assembly line is deleted, the reader stays.
    ("assembly-line-deleted",
     lambda tree: _overridden(tree, SOURCES, [(
         "streamConfig.shortQueueOnDoubledCadence = ",
         "streamConfig.shortQueueOnDoubledCadenceRemoved = ", 1)]),
     "shortQueueOnDoubledCadence", "unwritten-read"),
    # An assembly line that writes a *different* object must not count. This is the
    # Connection.m C-struct shape: same field spelling, wrong receiver.
    ("assembly-line-wrong-object",
     lambda tree: _overridden(tree, SOURCES, [(
         "streamConfig.shortQueueOnDoubledCadence = ",
         "unusedReceiver.shortQueueOnDoubledCadence = ", 1)]),
     "shortQueueOnDoubledCadence", "unwritten-read"),
    # A comparison is not a write. Reading the field to decide something else leaves the
    # field itself unconfigurable.
    ("comparison-counts-as-write",
     lambda tree: _overridden(tree, SOURCES, [(
         "streamConfig.shortQueueOnDoubledCadence = ",
         "streamConfig.shortQueueOnDoubledCadence == ", 1)]),
     "shortQueueOnDoubledCadence", "unwritten-read"),
    # Comments are prose, not code. This is the shape that bit the first version: a
    # sentence ending in a full stop above the assembly line, which the scanner paired
    # across the line break as `choice. streamConfig`, consuming the receiver and hiding
    # the only line this gate exists to watch.
    ("comment-eats-the-assembly-line",
     lambda tree: _overridden(tree, SOURCES, [(
         "    streamConfig.shortQueueOnDoubledCadence = ",
         "    // the shipped default, not a choice.\n"
         "    streamConfig.shortQueueOnDoubledCadence = ", 1)]),
     "shortQueueOnDoubledCadence", "assembled"),
    # Declaring a property nothing reads or writes is a different debt; it must not be
    # reported as a live setting that is broken.
    ("declared-unused-classified-as-read",
     lambda tree: _overridden(tree, HEADER, [(
         "@end",
         "// read by nothing\n@property(nonatomic) int mlSelfTestUnusedField;\n\n@end", 1)]),
     "mlSelfTestUnusedField", "declared-unused"),
)

# Verdicts pinned against the committed tree, so a refactor that quietly changes one of
# them fails here rather than silently narrowing what the gate can see.
REQUIRED_STATES = (
    # The field that motivated the gate: assembled now, and it has to stay assembled.
    ("shortQueueOnDoubledCadence", "assembled"),
    # Assembled through the local in StreamViewController.m alongside 60-odd siblings,
    # so a green here is not the mutation battery passing by absence.
    ("width", "assembled"),
    # Read on the stream path and assembled in `startStream` through a *different*
    # statement shape (a dictionary read with a fallback); the two assembly shapes the
    # real tree uses both have to count.
    ("frameInterpolationForce", "assembled"),
)


def self_test():
    """Each mutation has to change exactly the verdict it invalidates."""
    tree = Tree()
    before = {row["key"]: row for row in classify(tree)}
    failures = []
    for name, mutate, key, expected in MUTATIONS:
        try:
            mutated = mutate(tree)
        except AssertionError as error:
            failures.append("%s: %s" % (name, error))
            continue
        after = {row["key"]: row for row in classify(mutated)}
        states = list(after.values())
        if _state(states, key) != expected:
            failures.append("%s: %s became %r, expected %r"
                            % (name, key, _state(states, key), expected))
        moved = sorted(other for other in before
                       if other != key
                       and _state(states, other) != before[other]["state"])
        if moved:
            failures.append("%s: also moved %s" % (name, ", ".join(moved)))
    # The control has to be capable of failing: if deleting the declaration from the
    # header leaves the row behind, the audit is reading something other than the header.
    unseen = classify(_overridden(tree, HEADER, [(
        "@property(nonatomic) BOOL shortQueueOnDoubledCadence;",
        "@property(nonatomic) BOOL shortQueueOnDoubledCadenceRenamed;", 1)]))
    if _state(unseen, "shortQueueOnDoubledCadence") is not None:
        failures.append("header-rename: reports a property the header no longer declares")
    # Receiver identity is the whole gate, so its two halves are asserted on the
    # mechanism rather than through a verdict, because neither can be shown any other
    # way. (a) The tree really does declare `SCStreamConfiguration *configuration` in
    # AppDelegateForAppKit.m; if the lookbehind ever stops holding, that name joins the
    # set and another class's writes start excusing ours -- and no verdict moves,
    # because those properties are assembled by our own code too. (b) Both declaration
    # shapes have to be read: `_config` is only ever an ivar and `streamConfig` only
    # ever a parameter in the renderer, so a set holding neither shape would still let
    # the pinned verdicts pass while seeing less of the tree.
    seen = receivers(tree)
    if "configuration" in seen:
        failures.append("the receiver set credits SCStreamConfiguration's `configuration`")
    for shape, name in (("ivar", "_config"), ("parameter", "config")):
        if name not in seen:
            failures.append("the receiver set is missing the %s `%s`" % (shape, name))
    for key, expected in REQUIRED_STATES:
        if _state(list(before.values()), key) != expected:
            failures.append("pinned: %s is %r, expected %r"
                            % (key, _state(list(before.values()), key), expected))
    # The stripper is judged on what the audit can see *through* it, not on its own
    # character classes. Each line below is a hazard that would change a verdict: an
    # apostrophe in prose (an opening quote that is not one) hiding the code beneath it,
    # a double slash in a URL opening a comment that is not there, and a dotted path in a
    # log format reading as an accessor on a receiver nobody declared.
    sample = ("// the player's queue is short\n"
              'NSString *u = @"https://example.com/a";\n'
              'Log(LOG_I, @"streamConfig.width = %d", 1);\n'
              "streamConfig.width = 1;\n")
    stripped = strip_comments(sample)
    if len(stripped) != len(sample):
        failures.append("strip_comments changed the length, so reported offsets drift")
    seen = [(receiver, name) for receiver, name, _ in _accesses(sample)]
    if ("streamConfig", "shortQueueOnDoubledCadence") in seen:
        failures.append("unrelated sample edited, the control is broken")
    if seen.count(("streamConfig", "width")) != 1:
        failures.append("the audit sees %d `streamConfig.width` in a sample that has "
                        "one; a comment or a format string is being read as code"
                        % seen.count(("streamConfig", "width")))
    # An unwritten-but-read field is only excusable by name, so it has to name its
    # reader; a row that cannot say who reads it would let the ledger excuse anything.
    for row in before.values():
        if row["state"] == "unwritten-read" and not row["readers"]:
            failures.append("%s: unwritten-read with no reader named" % row["key"])
    return failures


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable rows")
    parser.add_argument("--self-test", action="store_true", help="prove the gate can fail")
    parser.add_argument("--write-baseline", action="store_true",
                        help="record the current unwritten fields as accepted debt")
    args = parser.parse_args(argv)

    if args.self_test:
        failures = self_test()
        for failure in failures:
            print(failure)
        print("self-test ok" if not failures else "self-test FAILED (%d)" % len(failures))
        return 0 if not failures else 1

    rows = classify(Tree())
    if args.write_baseline:
        debts = write_baseline(rows)
        print("wrote %d debt entries to %s" % (len(debts), os.path.relpath(BASELINE, ROOT)))
        return 0

    problems = check_ledger(rows)
    if args.json:
        print(json.dumps({"rows": rows, "problems": problems}, indent=1, ensure_ascii=False))
        return 1 if problems else 0

    for state in ("unwritten-read", "declared-unused"):
        group = [row for row in rows if row["state"] == state]
        if not group:
            continue
        print("debt %s (%d)" % (state, len(group)))
        for row in group:
            print("  %-34s %s" % (row["key"], reason_for(row)))
    for problem in problems:
        print(problem)
    total = len(rows)
    assembled = sum(1 for row in rows if row["state"] == "assembled")
    print("%d of %d StreamConfiguration fields are written somewhere; %d are registered debt"
          % (assembled, total, total - assembled))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
