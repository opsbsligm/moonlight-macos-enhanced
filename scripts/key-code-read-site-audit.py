#!/usr/bin/env python3
"""Prove that every reader of an NSEvent's keyCode asks what kind of event it is holding.

Some device drivers leave garbage in the keyCode field of a mouse, tablet or gesture event,
and one of the values that garbage takes collides with kVK_ANSI_C (8). Reading it is what once
made "double-click the left button" send C at the host -- repeatedly, because a press with no
matching release is all an auto-repeat needs. The fix was a type gate: ask whether the event is
keyDown, keyUp or flagsChanged, and only then read the field. StreamViewController_Internal.h
writes that down as a rule for ALL keyCode readers, and a rule that lives only in a comment is
a rule that comes back. Nothing until this file could notice the next reader that skipped it,
and the symptom arrives much later, in a game, not in a log.

The verdict is per function, and it is earned alone:

  * a reader passes when its own body asks about event.type or calls MLIsKeyboardKeyEvent;
  * a reader passing because "its callers are gated" is refused on purpose: that argument is
    a call graph, call graphs rot, and the tree already held an exported helper of that shape
    with no caller at all -- the exact thing that turns into "double-click sends C" the day
    somebody wires it to a mouse or a modifier path. It carries a gate now;
  * a reader passing because it is *named* keyDown: is refused too. A method with that name in
    a class that is not a responder is handed its event by another function, not by AppKit,
    and HIDSupport has two of those -- the functions standing one hop from the driver, which
    is precisely where an event with an undefined field can arrive. Four methods in this tree
    are named for AppKit's keyboard contract and all four now state it themselves.

So the verdict today is 13 readers, 13 gates, and no exemption list to keep honest.

--self-test plants three mistakes: take the type gate out of -[HIDSupport keyDown:], whose
name used to be able to hide behind -[CollectionView keyDown:]; take it out of
-event:matchesShortcut:, the helper a gated caller reaches; and hand -mouseDown: an event
keyCode read of its own. All three have to come back red.
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTERNAL = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers",
                        "StreamViewController_Internal.h")

MIN_EVENT_READS = 20   # the tree measures 25 today; a rule that sees nothing is vacuous
MIN_GATED = 13         # today every reader gates itself, and a floor is how that stays true

# Reads that matter: the keyCode field of something named like an NSEvent. A shortcut
# record's own keyCode is a stored integer with no undefined state, so matching ".keyCode"
# alone would cry wolf at every StreamShortcut comparison in the tree.
EVENT_KEYCODE = re.compile(r"\b(?:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*[Ee]vent|theEvent|event)\.keyCode\b")
GATE = re.compile(r"MLIsKeyboardKeyEvent\s*\(|\btype\s*[!=]=\s*NSEventType|"
                  r"switch\s*\(\s*[A-Za-z_][\w.]*\btype\b")
DEFINITION = re.compile(r"^(?:[-+]\s*\([^)]*\)\s*[\w:()+\-]*|static\s+[A-Za-z_][\w \*]*?\b\w+\s*\()[^;]*\{")

# Deliberately empty of exemptions. A method named keyDown: in a class that is not a
# responder gets the event from a caller, not from AppKit, and HIDSupport has two of those:
# judging them by their name would hand the pass to the very functions standing one hop from
# the driver, which is where a mouse event with an undefined field can actually arrive.


def first_party_sources():
    out = []
    for base, dirs, files in os.walk(os.path.join(ROOT, "Limelight")):
        dirs[:] = [d for d in dirs if d not in (".git", "build", "dist")]
        for name in sorted(files):
            if name.endswith(".m"):
                out.append(os.path.join(base, name))
    return sorted(out)


def definitions(text):
    """[(selector, start, end)] for top-level definitions, spans by line index."""
    lines = text.split("\n")
    found = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if DEFINITION.match(line) and line[:1] not in (" ", "\t", "#", "@"):
            header = line
            walk = index
            while "{" not in header and walk + 1 < len(lines) and walk - index < 5:
                walk += 1
                header += " " + lines[walk].strip()
            depth = 0
            opened = False
            end = walk
            for cursor in range(walk, len(lines)):
                for char in lines[cursor]:
                    if char == "{":
                        depth += 1
                        opened = True
                    elif char == "}":
                        depth -= 1
                if opened and depth == 0:
                    end = cursor
                    break
            after = header[header.index(")") + 1:header.index("{")] if ")" in header and "{" in header else ""
            keywords = re.findall(r"([A-Za-z_]\w*\s*:)", after)
            if keywords:
                selector = "".join(keywords)
                if selector.count(":") > 1:
                    selector = ":".join(keywords[-1:]) + ":"
            else:
                match = re.findall(r"\b([A-Za-z_]\w*)\s*\(", header)
                selector = match[-1] if match else ""
            if selector:
                found.append((selector, index, end))
            index = end + 1
            continue
        index += 1
    return found


def readers_of(path, text):
    """[(selector, start, end, hits, body)] for every function of this file that reads one."""
    lines = text.split("\n")
    out = []
    for selector, start, end in definitions(text):
        body = "\n".join(lines[start:end + 1])
        hits = [line for line in body.split("\n") if EVENT_KEYCODE.search(line)]
        if hits:
            out.append((selector, start, end, hits, body))
    return out


def analyse(sources):
    gated = entry = reads = 0
    findings = []
    for path in sources:
        for selector, start, _end, hits, body in readers_of(path, text=sources[path]):
            reads += len(hits)
            if GATE.search(body):
                gated += 1
            else:
                findings.append("%s:%d  %s  (%d reads, no type gate in its own body)"
                                % (os.path.relpath(path, ROOT), start + 1, selector, len(hits)))
    return gated, entry, reads, findings


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    return ok


def main():
    sources = {p: open(p, encoding="utf-8", errors="replace").read() for p in first_party_sources()}

    if "--self-test" in sys.argv[1:]:
        return red_proofs(sources)

    gated, entry, reads, findings = analyse(sources)
    internal = open(INTERNAL, encoding="utf-8").read()

    check(reads >= MIN_EVENT_READS,
          "the audit sees %d event keyCode reads in %d functions (floor %d)"
          % (reads, gated + entry + len(findings), MIN_EVENT_READS))
    check(gated >= MIN_GATED, "%d of %d functions gate the read themselves (floor %d)"
          % (gated, gated + len(findings), MIN_GATED))
    check("ALL keyCode readers MUST gate on this FIRST" in internal
          and "MLIsKeyboardKeyEvent" in internal,
          "the rule this enforces is still written beside the helper it names")
    check(not findings, "every first-party reader gates its own keyCode read"
          if not findings else "ungated keyCode readers:\n  " + "\n  ".join(findings))
    return 1 if findings else 0


def red_proofs(sources):
    rc = 0
    target = lambda suffix: [p for p in sources if p.endswith(suffix)][0]

    def plant(suffix, before, after, expect, label):
        path = target(suffix)
        replaced = sources[path].replace(before, after, 1)
        if replaced == sources[path]:
            print("FAIL  %s could not be planted (the source text moved)" % label)
            return 1
        trial = dict(sources)
        trial[path] = replaced
        found = analyse(trial)[3]
        hit = any(expect in f for f in found)
        print("%-4s %s is refused (%d readers named)"
              % ("ok" if hit else "FAIL", label, len(found)))
        return 0 if hit else 1

    rc |= plant("HIDSupport.m",
                "- (void)keyDown:(NSEvent *)event {\n"
                "    if (event == nil || event.type != NSEventTypeKeyDown) {\n        return;\n    }",
                "- (void)keyDown:(NSEvent *)event {\n"
                "    if (event == nil) {\n        return;\n    }",
                "keyDown:", "taking the gate out of -[HIDSupport keyDown:], with a same-named "
                            "AppKit entry point elsewhere")
    rc |= plant("StreamViewController+MenuUI.m",
                "    if (!MLIsKeyboardKeyEvent(event)) {",
                "    if (event == nil) {",
                "matchesShortcut:", "a helper that stops gating because its callers do")
    rc |= plant("StreamViewController+MouseCapture.m",
                "- (void)mouseDown:(NSEvent *)event {",
                "- (void)mouseDown:(NSEvent *)event {\n"
                "    if (event.keyCode == kVK_ANSI_C) { return; }",
                "mouseDown:", "a mouse handler that reads the keyCode of its event")
    return rc


if __name__ == "__main__":
    sys.exit(main())
