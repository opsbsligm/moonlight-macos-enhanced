#!/usr/bin/env python3
"""Prove that every key this app puts on the wire leaves a line the player can grep.

A player reports "a key arrived that I never pressed". The tree has the answer to one
shape of that report -- -keyCode is undefined on mouse, tablet and gesture events, one
driver left a value there that collides with kVK_ANSI_C, and a forwarded press with no
release is everything a guest auto-repeat needs -- and scripts/key-code-read-site-audit.py
keeps every reader of that field honest about it. What that gate cannot do is say which
side a *later* report came from, and every instrument that could was unavailable where it
mattered: the answer lived only in a debug build, a session-level observer goes blind
while a fullscreen stream owns the pointer, and the IOHID keyboard channel needs an Input
Monitoring grant only a Finder-launched instance can get.

So the answer moved into the log the player already has. With the existing Input
Diagnostics switch on, the shipping app records one line per keyboard edge at every point
where the answer changes: what the responder chain delivered to the stream view (before
anything here can swallow it), what HIDSupport forwarded, what reached
LiSendKeyboardEventCtx, what a shortcut invented, and the left double-click that happened
next to them. Then "did the app send it?" is one grep, and silence is evidence rather
than a broken instrument.

This gate reads the shipping sources as wiring. Each line has to sit at the decision it
answers: after the type gate that authorises the field it prints, before the dispatch it
describes, under the tag the grep asks for, and at a level that keeps it off the log until
somebody asks for it. A trace line in the wrong place answers a question nobody asked, and
one that was renamed answers it silently wrong.

--self-test puts the ways this goes wrong back in: a trace line printed before the type
gate, a send that stopped reporting, a level that floods every log, a Logger that drops the
edge, and a code printed as a signed short. All of them have to go red.
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HID = os.path.join(ROOT, "Limelight", "Input", "HIDSupport.m")
VC = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers",
                  "StreamViewController+MouseCapture.m")
LOGGER = os.path.join(ROOT, "Limelight", "Utility", "Logger.m")

TRACE = "[inputdiag] keyboard-wire"
# The edges the answer is built from, by file and tag. Renaming one is as gone as deleting
# it, so the list is checked against both sources rather than trusted.
HID_EDGES = ("down", "up", "up-swallowed", "sent-down", "sent-up", "synthetic")
VIEW_EDGES = ("view-down", "view-up")
MIN_CHECKS = 11

failures = []
checks = [0]
quiet = [False]


def check(ok, when_green, when_red=None):
    checks[0] += 1
    if ok:
        if not quiet[0]:
            print("ok   " + when_green)
    else:
        failures.append(when_red or when_green)
        print("FAIL " + (when_red or when_green))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def body(source, signature):
    """The text of one method, from its signature to the line that closes its brace."""
    start = source.find(signature)
    if start < 0:
        return ""
    open_at = source.index("{", start)
    depth = 0
    for index in range(open_at, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    return source[start:]


def statements(text):
    return [line.strip() for line in text.split("\n") if line.strip()]


def first(lines, needle):
    for index, line in enumerate(lines):
        if needle in line:
            return index
    return None


def log_call(source, tag):
    """The Log(...) call whose format string carries this tag, up to the end of the string."""
    return re.search(r'Log\(\s*LOG_\w\s*,\s*@"[^"]*' + re.escape(tag), source, re.S)


def wiring(hid, capture, logger):
    down = body(hid, "- (void)keyDown:(NSEvent *)event")
    up = body(hid, "- (void)keyUp:(NSEvent *)event")
    shortcut = body(hid, "- (void)sendSyntheticRemoteShortcut:(StreamShortcut *)shortcut")
    view_down = body(capture, "- (void)keyDown:(NSEvent *)event")
    view_up = body(capture, "- (void)keyUp:(NSEvent *)event")
    monitor = capture[capture.find("- (void)installLocalMouseClickMonitorIfNeeded"):]
    persist = logger[logger.find("static BOOL IsPersistableInputDiagnosticLine"):]
    persist = persist[:persist.find("\n}\n") + 3]

    # The edges the host is about to hear: one line each, after the type gate that
    # authorises the field they print, and before the dispatch they describe.
    for label, method, gate, tag, dispatch in (
        ("down", down, "event.type != NSEventTypeKeyDown", TRACE + " down", "KEY_ACTION_DOWN"),
        ("up", up, "event.type != NSEventTypeKeyUp", TRACE + " up", "KEY_ACTION_UP")):
        lines = statements(method)
        gated, logged, sent = first(lines, gate), first(lines, tag), first(lines, dispatch)
        check(None not in (gated, logged, sent) and gated < logged < sent,
              "the %s edge is recorded after its type gate and before the dispatch" % label,
              "the %s edge is not recorded where the answer is decided (gate=%s trace=%s send=%s)"
              % (label, gated, logged, sent))

    # The release that never reached the host has to say so from inside the guard that
    # swallows it, and the guard has to keep the early exit: an unmatched release is
    # exactly what reads as a key the player let go by themself.
    swallow = statements(up)
    guard, said = (first(swallow, "if ([self.keyboardSuppressedKeyDownKeyCodes containsObject:"),
                   first(swallow, TRACE + " up-swallowed"))
    check(None not in (guard, said) and guard < said <= guard + 6
          and "return;" in swallow[guard + 1:guard + 8],
          "a swallowed release reports itself and still returns",
          "the swallowed release stopped reporting or lost its return (guard=%s trace=%s)"
          % (guard, said))

    # The one path that puts a key on the wire with no key event behind it.
    check(TRACE + " synthetic" in shortcut and "LiSendKeyboardEventCtx" in shortcut
          and shortcut.index(TRACE + " synthetic") < shortcut.index("LiSendKeyboardEventCtx"),
          "a shortcut that invents a key reports it before sending",
          "the synthetic shortcut path no longer reports what it sends")

    # What the responder chain delivered, recorded before anything local can consume it:
    # a key the settings page or a shortcut took must not look like a key macOS never sent.
    for label, method, tag, handoff in (
            ("down", view_down, TRACE + " view-down", "[self.hidSupport keyDown:event]"),
            ("up", view_up, TRACE + " view-up", "[self.hidSupport keyUp:event]")):
        lines = statements(method)
        logged, gated, passed = first(lines, tag), first(lines, "event.type =="), first(lines, handoff)
        check(None not in (logged, gated, passed) and logged < passed
              and 0 <= logged - gated <= 2,
              "the stream view records the %s edge before it hands the key over" % label,
              "the stream view no longer records the %s edge ahead of the handoff" % label)

    # The gesture the report names, anchored in the same tag space as the edges.
    check("mouse-button left-double" in monitor and "clickCount >= 2" in monitor,
          "the left double-click is anchored beside the keyboard edges",
          "the left double-click anchor is gone, so the log cannot line the two up")

    # Every edge under one tag, because the answer is one grep; and none of them at a
    # level that floods the log, because a trace nobody leaves switched on answers nothing.
    named = [(hid, tag) for tag in HID_EDGES] + [(capture, tag) for tag in VIEW_EDGES]
    check(all((TRACE + " " + tag) in source for source, tag in named),
          "%d keyboard edges carry the tag the grep asks for" % len(named),
          "a keyboard edge no longer carries %r, so the one grep would miss it" % TRACE)
    calls = [(log_call(source, TRACE + " " + tag).group(0)
              if log_call(source, TRACE + " " + tag) else "") for source, tag in named]
    calls.append((log_call(capture, "left-double").group(0)
                  if log_call(capture, "left-double") else ""))
    check(all("LOG_D" in call for call in calls),
          "every trace line is a diagnostic, so a closed switch costs nothing",
          "a trace line is not LOG_D, so it lands in every log file whether asked for or not")

    # A dispatched code is 0x8000 | translation: through %x of a short, a plain C reads
    # back as 0xffff8043 and looks like a corrupt code to whoever is reading the log.
    check("code=0x%hx" in hid and "(unsigned short)keyCode" in hid and "VK=0x%x" not in hid,
          "the dispatched code prints unsigned, so C reads 0x8043 and not 0xffff8043",
          "a dispatched code is printed through %%x of a short again")

    # The Logger half: a keystroke is one line per press, so it is kept when asked for;
    # motion is a rate, and stays dropped.
    # The clause, not the word: prose about keyboard-wire lines keeps the word while
    # dropping the rule, which is the shape a comment can leave behind.
    check("[inputdiag]" in persist and 'rangeOfString:@"keyboard-wire"' in persist,
          "Logger keeps keyboard edges while input diagnostics are on",
          "Logger would drop the keyboard edge lines the whole answer rests on")
    check('rangeOfString:@"scroll"' in persist and 'rangeOfString:@"mouse-button"' in persist
          and "return" in persist,
          "the same rule still keeps the scroll and mouse-button lines it kept",
          "the persistable rule lost one of the lines it already kept")


def planted_defects():
    """The ways this trace goes wrong, each one put back for the self-test."""
    return [
        ("a trace line printed before the type gate that authorises the field",
         lambda h, c, l: (h.replace(
             "    if (event == nil || event.type != NSEventTypeKeyDown) {\n        return;\n    }\n\n"
             "    // Every keyboard edge", "    // Every keyboard edge", 1), c, l)),
        ("a send stopped reporting itself",
         lambda h, c, l: (h.replace(TRACE + " sent-down", "[inputdiag] dropped-down", 1), c, l)),
        ("the trace became an always-on line",
         lambda h, c, l: (h.replace('Log(LOG_D, @"' + TRACE + " down",
                                    'Log(LOG_I, @"' + TRACE + " down", 1), c, l)),
        ("Logger dropped the edge from the persistable rule",
         lambda h, c, l: (h, c, l.replace('@"keyboard-wire"', '@"keyboard-holes"', 1))),
        ("a dispatched code printed through %x of a short again",
         lambda h, c, l: (h.replace(
             'Log(LOG_D, @"' + TRACE + ' sent-down code=0x%hx mods=0x%hhx",\n'
             '                (unsigned short)keyCode, modifiers);',
             'Log(LOG_D, @"' + TRACE + ' sent-down VK=0x%x mods=0x%hhx", keyCode, modifiers);',
             1), c, l)),
        ("the stream view stopped recording ahead of the handoff",
         lambda h, c, l: (h, c.replace(TRACE + " view-down", TRACE + " dropped-down", 1), l)),
        ("the double-click anchor disappeared",
         lambda h, c, l: (h, c.replace("mouse-button left-double", "clickdiag left-double", 1), l)),
    ]


def main():
    hid, capture, logger = read(HID), read(VC), read(LOGGER)

    if "--self-test" not in sys.argv:
        wiring(hid, capture, logger)
        check(checks[0] >= MIN_CHECKS,
              "%d wiring checks ran (floor %d)" % (checks[0], MIN_CHECKS),
              "only %d wiring checks ran, so this gate stopped covering what it claims (floor %d)"
              % (checks[0], MIN_CHECKS))
        print("%d constraint failure(s)" % len(failures))
        sys.exit(1 if failures else 0)

    defects = planted_defects()
    quiet[0] = True
    print("self-test: %d defects, each has to turn the gate red" % len(defects))
    missed = 0
    for name, plant in defects:
        failures.clear()
        checks[0] = 0
        wiring(*plant(hid, capture, logger))
        if failures:
            print("red      " + name + "  (" + failures[0][:64] + ")")
        else:
            missed += 1
            print("NOT RED  " + name)
    print("%d defect(s) that went undetected" % missed)
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
