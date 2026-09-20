#!/usr/bin/env python3
"""Prove that a settings rebuild carries the field its own name asks for.

Three places in SettingsObjCBridge.swift rebuild the whole Settings value by hand: they read
what is stored, spell all ninety-one fields out again, change one thing, and persist the
result. That transcription is checked by nothing. A compiler cannot see it -- Bool into Bool,
both names real, the shape perfect -- and CI cannot see it either, because no test has ever
called setCustomResolution. It is one row per field, ninety-one rows deep, and the failure
mode of transcription is a row that reads a different field than it names.

One such row shipped. `hoverActivatesStreamWindow: settings.emulateGuide` sat directly under
the emulateGuide row it had been copied from, so setting a custom resolution overwrote the
switch that decides whether a pointer entering the stream window may activate it with the
value of the switch that decides whether a controller Guide button is synthesised. Both
default to on, so the fault surfaced only for a player who had turned controller Guide
emulation off: the first custom resolution they set silently switched pointer-entry
activation off too, with no setting touched and no page to look at afterwards. That is the
shape this file exists for -- not a crash, a field that quietly belongs to somebody else.

So the transcription is audited as transcription:

  * every full rebuild must spell the same list. A row one of them drops is not carried at
    all: it falls back to the initialiser default, which is the same fault in the same
    silence. Three tables that agree is what is promised here, and it is worth saying what is
    not promised -- if a field ever gains a default and all three tables stop spelling it,
    nothing here would notice.
  * a row whose two names differ is either a rename or a mistake, so a rename has to be
    written down with a reason, one entry per pair. None is standing today: the three rebuilds
    are pure same-name copies, and the only hand-written argument list nearby belongs to the
    legacy `dataMan.saveSettings(...)`, whose parameters are called optimizeGames and enableHdr
    because that Objective-C API named them that way long before this file existed. It is not
    a Settings rebuild and is not treated as one.
  * a written-down rename that nothing uses any more is red too, for the reason
    constraints-audit.py already has: an exemption nobody is using is not an exemption, it is
    a hole with a note beside it.

`--self-test` mispells one row at the rebuild where the fault really happened and one where it
did not, drops one row out of one table, adds a rename nobody registered, registers a rename
that no row uses, and lets a registered rename through. Every one of those has to change the
answer, and it has to happen in a copy of the file rather than in a comment about it.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers",
                      "SettingsObjCBridge.swift")

# A rename is (the name written on the left, the field read on the right) -> why they differ.
# Empty today, and it stays empty only while every row is a same-name copy.
RENAMES = {}

# `dataMan.saveSettings(withBitrate:...)` ends with the word Settings, so a rebuild is
# recognised as an assignment to the type rather than as any call whose name ends that way.
REBUILD = re.compile(r"=\s*Settings\($")
FIELD_LINE = re.compile(r"^\s*(?P<lhs>[A-Za-z_]\w*):")
PASSTHROUGH = re.compile(
    r"^\s*(?P<lhs>[A-Za-z_]\w*):\s*(?:settings|updated)\.(?P<rhs>[A-Za-z_]\w*)\s*,?\s*"
    r"(?P<note>//.*)?$")


def rebuild_sites(text):
    """Every `= Settings(` rebuild: the rows it spells and the rows it copies."""
    lines = text.splitlines()
    sites = []
    for start, line in enumerate(lines):
        if not REBUILD.search(line):
            continue
        depth = 0
        rows = {}
        copies = []
        for j in range(start, len(lines)):
            depth += lines[j].count("(") - lines[j].count(")")
            if j > start and not lines[j].lstrip().startswith("//"):
                named = FIELD_LINE.match(lines[j])
                if named:
                    rows[named.group("lhs")] = j + 1
                copied = PASSTHROUGH.match(lines[j])
                if copied:
                    copies.append((j + 1, copied.group("lhs"), copied.group("rhs")))
            if depth <= 0 and j > start:
                break
        sites.append({"line": start + 1, "rows": rows, "copies": copies})
    return sites


def audit(text, renames=None):
    """The faults a reader cannot see in a table this wide. Returns messages, not exits."""
    renames = RENAMES if renames is None else renames
    problems = []
    sites = rebuild_sites(text)
    if not sites:
        return ["no settings rebuild was found to audit -- the file changed shape"]

    shared = None
    for site in sites:
        if shared is None:
            shared = set(site["rows"])
            first = site["line"]
            continue
        gone = sorted(shared - set(site["rows"]))
        extra = sorted(set(site["rows"]) - shared)
        if gone or extra:
            problems.append(
                "the rebuild at line %d spells a different list than the one at line %d: %s"
                % (site["line"], first,
                   ", ".join(["missing " + g for g in gone]
                             + ["extra " + e for e in extra])))

    used = set()
    for site in sites:
        for line, lhs, rhs in site["copies"]:
            if lhs == rhs:
                continue
            if (lhs, rhs) not in renames:
                problems.append(
                    "line %d hands %s the value of %s, which is either a rename nobody "
                    "registered or the field that belongs to somebody else"
                    % (line, lhs, rhs))
            else:
                used.add((lhs, rhs))

    for pair in sorted(set(renames) - used):
        problems.append("the registered rename %s from %s is used by no rebuild any more"
                        % (pair[0], pair[1]))
    return problems


def main():
    failures = []

    def check(ok, message):
        print("%-4s %s" % ("ok" if ok else "FAIL", message))
        if not ok:
            failures.append(message)

    text = open(BRIDGE, encoding="utf-8").read()
    sites = rebuild_sites(text)

    def check_mutated(label, mutated, renames, expect_red):
        """Red for a broken copy, clean for a good one, and never the same answer for both."""
        problems = audit(mutated, renames)
        if expect_red:
            check(bool(problems), "%s was caught" % label)
            if not problems:
                print("     the mutation produced no complaint at all")
        else:
            check(not problems, "%s stayed clean" % label)
            for problem in problems[:4]:
                print("     " + problem)

    def edit_line(source, line, transform):
        """Change one row of one named table, by the row number that table reported.

        Row numbers rather than a text search, because the same correct row exists in more
        than one table: searching for the text and replacing once would land on whichever
        table comes first, which is a different rebuild than the one being mutated.
        """
        rows = source.splitlines(True)
        before = rows[line - 1]
        rows[line - 1] = transform(before)
        out = "".join(rows)
        assert out != source, "the mutation changed nothing at line %d" % line
        return out

    check(len(sites) == 3,
          "three whole-table settings rebuilds are audited, not %d" % len(sites))
    check(not audit(text),
          "every settings rebuild carries the field its own name asks for")

    if "--self-test" in sys.argv:
        # The fault exactly as it reached the tree: the pointer-entry switch reading the
        # controller Guide field, in the rebuild that actually did it.
        shipped = sites[-1]
        check_mutated(
            "the shipped fault reproduced at the rebuild that shipped it",
            edit_line(text, shipped["rows"]["hoverActivatesStreamWindow"],
                      lambda row: row.replace(".hoverActivatesStreamWindow", ".emulateGuide")),
            RENAMES, True)

        # The same single wrong word in a table that got it right, so the check is not about
        # one function in particular.
        check_mutated(
            "the same wrong word in a rebuild that got it right",
            edit_line(text, sites[0]["rows"]["hoverActivatesStreamWindow"],
                      lambda row: row.replace(".hoverActivatesStreamWindow", ".emulateGuide")),
            RENAMES, True)

        # A row dropped from one table and left in the others: the field does not go missing,
        # it quietly falls back to the initialiser default.
        check_mutated("one row dropped from one rebuild",
                      edit_line(text, sites[0]["rows"]["appArtworkDimensions"],
                                lambda row: ""),
                      RENAMES, True)

        # A rename invented on the spot, which is what a mistake looks like until somebody
        # writes it down and explains it.
        check_mutated(
            "a rename nobody registered",
            edit_line(text, sites[0]["rows"]["mouseMode"],
                      lambda row: row.replace(".mouseMode", ".gamepadMouseMode")),
            RENAMES, True)

        # The same rename, now registered with a reason: a registered rename has to be let
        # through, or the exemption list is decoration.
        registered = dict(RENAMES)
        registered[("mouseMode", "gamepadMouseMode")] = "test"
        check_mutated(
            "that rename once it is registered",
            edit_line(text, sites[0]["rows"]["mouseMode"],
                      lambda row: row.replace(".mouseMode", ".gamepadMouseMode")),
            registered, False)

        # An exemption for a rename no row uses.
        stale = dict(RENAMES)
        stale[("optimizeGames", "optimize")] = "test"
        check_mutated("a registered rename no row uses", text, stale, True)

        check_mutated("the tree as it stands", text, RENAMES, False)
        print("     rebuilds audited: %s"
              % ", ".join("line %d carries %d rows" % (s["line"], len(s["rows"]))
                          for s in sites))

    print("%d settings-rebuild-passthrough failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
