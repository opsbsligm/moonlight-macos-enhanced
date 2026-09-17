#!/usr/bin/env python3
"""Prove a Shift-only binding is refused without harming a single shipped shortcut.

A translation rule or shortcut whose trigger is Shift plus a movement key is
reachable by playing: Shift is sprint, aim and the jump variant in a game, and the
player holds it while pressing WASD and the space bar. A matched rule consumes the
press, so the host never learns the player started running forward and the release
that does arrive reads as a key letting go on its own. That is the "W and Space
collide when I play" report.

The answer lives twice, because it is asked at two moments that cannot see each
other: in Objective-C at the moment a key arrives, and in Swift at the moment a
person records a binding. Two answers drift, so both are compiled from the shipping
sources here -- the inline function out of StreamViewController_Internal.h and the
Swift function out of SettingsShortcuts.swift, with only a fake shortcut as their
container -- and every combination of the five relevant modifier bits, with and
without a key code, has to come out the same from both.

Agreeing with each other is not enough, because two implementations can agree on
the wrong thing. So the shipped defaults are parsed out of defaultShortcuts() and
every one of them has to survive the guard: the six Control+Option bindings, the
Command+W that opens the disconnect page and the Control+Shift+W that quits are the
keys a player must never lose. And the shape the guard exists to stop is played
back directly: Shift+W and Shift+Space have to be named.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
HEADER = "Limelight/macOS/ViewControllers/StreamViewController_Internal.h"
CALLSITE = "Limelight/macOS/ViewControllers/StreamViewController+MouseCapture.m"
VALIDATOR = "Limelight/macOS/ViewControllers/SettingsShortcuts.swift"
L10N = "Limelight/macOS/Helpers/LanguageManager.swift"
GUARD = "MLShortcutUsesGameplayOnlyModifiers"
SWIFT_GUARD = "shortcutUsesGameplayOnlyModifiers"
ERROR_KEY = "Shortcut reserved by gameplay keys"

# The five bits MLRelevantShortcutModifiers keeps, in the order the model walks them.
BITS = [("Shift", 1 << 17), ("Control", 1 << 18), ("Option", 1 << 19),
        ("Command", 1 << 20), ("Function", 1 << 21)]

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def inline_function(text, name):
    """The shipping text of a static inline function, braces included."""
    match = re.search(r"^static inline\s+[^\n;]*\b%s\s*\(" % re.escape(name), text, re.M)
    assert match, "no inline definition of %s" % name
    brace = text.index("{", match.start())
    depth, index = 0, brace
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[match.start():index + 1]
        index += 1
    raise AssertionError("unbalanced braces in " + name)


def swift_functions(text, name):
    """Every body that declares this name, signature included, in source order.

    The signature can be spread over several lines and a validator can be
    overloaded, so the name is located, the first brace after it opens the body,
    and the brace walk decides where that body ends. Reading only the first
    overload, or stopping at the end of the signature, would let a missing guard
    read as a present one.
    """
    bodies, cursor = [], 0
    while True:
        match = re.search(r"^\s*(?:@objc )?static func %s\b" % re.escape(name),
                          text[cursor:], re.M)
        if match is None:
            return bodies
        start = cursor + match.start()
        brace = text.index("{", start)
        depth, index = 0, brace
        while index < len(text):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        else:
            raise AssertionError("unbalanced braces in Swift " + name)
        bodies.append(text[start:index + 1])
        cursor = index + 1


def swift_function(text, name):
    """The shipping text of a Swift static func, braces included.

    A signature may be spread over several lines, so the name is located and the
    brace walk decides where the body ends.
    """
    match = re.search(r"^\s*(?:@objc )?static func %s\b" % re.escape(name), text, re.M)
    assert match, "no Swift definition of %s" % name
    lines = text[match.start():].splitlines()
    depth, out = 0, []
    for line in lines:
        out.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0 and len(out) > 1:
            break
    if depth != 0:
        raise AssertionError("unbalanced braces in Swift " + name)
    return "\n".join(out)


def shipped_shortcuts(swift_text):
    """Every default binding, as (modifier names, key name) straight from the source."""
    block = re.search(r"static func defaultShortcuts\(\) -> \[String: StreamShortcut\] \{(.*?)\n  \}",
                      swift_text, re.S)
    assert block, "no defaultShortcuts() to read"
    found = []
    for entry in re.finditer(r"StreamShortcut\(([^)]*)\)", block.group(1)):
        body = entry.group(1)
        modifiers = re.search(r"modifierFlags: \[([^\]]*)\]", body)
        keys = [m.group(1) for m in re.finditer(r"\.(\w+)", modifiers.group(1))] if modifiers else []
        found.append((sorted(keys), "modifierOnly: true" in body))
    return found


OBJC_MODEL = r"""
#import <AppKit/AppKit.h>
#include <stdio.h>

@@GUARD@@

static const NSEventModifierFlags kBits[5] = {NSEventModifierFlagShift,
                                              NSEventModifierFlagControl,
                                              NSEventModifierFlagOption,
                                              NSEventModifierFlagCommand,
                                              NSEventModifierFlagFunction};

int main(void) {
    unsigned long checked = 0;
    for (int combo = 0; combo < 32; combo++) {
        NSEventModifierFlags mask = 0;
        for (int bit = 0; bit < 5; bit++) {
            if (combo & (1 << bit)) {
                mask |= kBits[bit];
            }
        }
        for (int hasKey = 0; hasKey <= 1; hasKey++) {
            for (int modOnly = 0; modOnly <= 1; modOnly++) {
                BOOL verdict = MLShortcutUsesGameplayOnlyModifiers(mask, hasKey, modOnly);
                printf("%d %d %d %d\n", combo, hasKey, modOnly, verdict ? 1 : 0);
                checked++;
            }
        }
    }
    printf("checked %lu\n", checked);
    return 0;
}
"""

SWIFT_MODEL = r"""
import AppKit

struct FakeShortcut {
    let modifierOnly: Bool
    let hasKeyCode: Bool
    let modifierFlags: NSEvent.ModifierFlags
}

@@RELEVANT@@

@@GUARD@@

let bits: [NSEvent.ModifierFlags] = [.shift, .control, .option, .command, .function]
var checked = 0
for combo in 0..<32 {
    var mask = NSEvent.ModifierFlags(rawValue: 0)
    for bit in 0..<5 where combo & (1 << bit) != 0 {
        mask.insert(bits[bit])
    }
    for hasKey in [false, true] {
        for modOnly in [false, true] {
            let candidate = FakeShortcut(modifierOnly: modOnly, hasKeyCode: hasKey, modifierFlags: mask)
            let verdict = StreamShortcutProfile.shortcutUsesGameplayOnlyModifiers(candidate)
            print("\(combo) \(hasKey ? 1 : 0) \(modOnly ? 1 : 0) \(verdict ? 1 : 0)")
            checked += 1
        }
    }
}
print("checked \(checked)")
"""


def strip_declaration(model):
    """Drop the class-only decorators. The logic stays word for word."""
    lines = []
    for line in model.splitlines():
        stripped = re.sub(r"^(\s*)@objc static func ", r"\1func ", line)
        stripped = re.sub(r"^(\s*)static func ", r"\1func ", stripped)
        lines.append(stripped)
    return "\n".join(lines) + "\n"


def compile_and_run(path, binary, command):
    built = subprocess.run(command + [path, "-o", binary], capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr).strip()[-1500:]
    ran = subprocess.run([binary], capture_output=True, text=True)
    return ran.stdout, (ran.stdout + ran.stderr).strip()[-1500:]


def matrix(stdout):
    """{(combo, hasKey, modOnly): verdict} plus the coverage count the run reported."""
    rows, checked = {}, None
    for line in stdout.splitlines():
        if line.startswith("checked"):
            checked = int(line.split()[1])
            continue
        fields = line.split()
        if len(fields) == 4:
            rows[tuple(int(field) for field in fields[:3])] = int(fields[3])
    return rows, checked


def main():
    header = read(HEADER)
    callsite = read(CALLSITE)
    swift = read(VALIDATOR)
    l10n = read(L10N)

    objc_guard = inline_function(header, GUARD)
    swift_guard = swift_function(swift, SWIFT_GUARD)
    relevant = swift_function(swift, "relevantModifierFlags")

    check(GUARD in callsite, "the streaming path asks the guard at all")

    # The guard has to be asked where a stored rule is matched, not merely exist.
    gate = re.search(r"- \(KeyboardTranslationRule \*\)keyboardTranslationRuleMatchingEvent:.*?\n\}",
                     callsite, re.S)
    check(gate is not None and GUARD + "(" in gate.group(0),
          "the guard is asked inside the rule matcher, before a rule can consume a key")
    check(gate is not None and "trigger.hasKeyCode" in gate.group(0)
          and "trigger.modifierOnly" in gate.group(0),
          "the guard is asked about the shape it documents, not a guess of it")

    validators = [body for body in swift_functions(swift, "validationErrorKey")
                  if "forTrigger" in body]
    check(len(validators) == 1,
          "exactly one validator decides what a rule trigger may be (%d found)"
          % len(validators))
    check(bool(validators) and SWIFT_GUARD + "(" in validators[0]
          and ERROR_KEY in validators[0],
          "the settings form refuses the same shape the runtime refuses, and says why")
    check(ERROR_KEY in swift, "the refusal says why in a localized key")
    check(l10n.count('"%s"' % ERROR_KEY) == 2,
          "%s has wording in both languages" % ERROR_KEY)

    cc, sdk = apple_toolchain.clang_and_sdk("gameplay modifier model")
    pair = apple_toolchain.swiftc_and_sdk("gameplay modifier model")
    if pair is None:
        print("SKIP no swiftc/SDK pair on this host")
        return 1
    swiftc, swift_sdk = pair

    with tempfile.TemporaryDirectory() as work:
        objc_path = os.path.join(work, "guard.m")
        open(objc_path, "w", encoding="utf-8").write(
            OBJC_MODEL.replace("@@GUARD@@", objc_guard))
        objc_rows, objc_checked = compile_and_run(
            objc_path, os.path.join(work, "objc"),
            [cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
             "-framework", "AppKit", "-framework", "Foundation"])

        swift_path = os.path.join(work, "guard.swift")
        model = (SWIFT_MODEL.replace("@@RELEVANT@@", relevant)
                 .replace("@@GUARD@@", swift_guard)
                 .replace("StreamShortcut?", "FakeShortcut?")
                 .replace("StreamShortcutProfile.", ""))
        model = strip_declaration(model)
        open(swift_path, "w", encoding="utf-8").write(model)
        swift_rows, swift_checked = compile_and_run(
            swift_path, os.path.join(work, "swift"),
            [swiftc, "-sdk", swift_sdk])

    check(objc_rows is not None and swift_rows is not None,
          "both halves of the answer compile"
          if objc_rows is not None and swift_rows is not None else
          "both halves of the answer compile:\nobjective-c: %s\nswift: %s"
          % (objc_checked if not objc_rows else "(ok)",
             swift_checked if not swift_rows else "(ok)"))
    if objc_rows is None or swift_rows is None:
        return finish()

    objc_matrix, objc_count = matrix(objc_rows)
    swift_matrix, swift_count = matrix(swift_rows)
    check(objc_count == 128 and swift_count == 128,
          "both sweeps played all 128 modifier shapes (%s objective-c, %s swift)"
          % (objc_count, swift_count))
    check(objc_matrix == swift_matrix,
          "the runtime and the settings form answer the same question for every shape")

    shift_only = (1, 1, 0)
    check(objc_matrix.get(shift_only) == 1 and swift_matrix.get(shift_only) == 1,
          "Shift plus a movement key is named as the shape that steals gameplay")

    shipped = shipped_shortcuts(swift)
    killed = []
    for modifiers, modifier_only in shipped:
        combo = 0
        for index, (name, _bit) in enumerate(BITS):
            if name.lower() in modifiers:
                combo |= 1 << index
        key = (combo, 0 if modifier_only else 1, 1 if modifier_only else 0)
        if objc_matrix.get(key) == 1:
            killed.append("%s%s" % ("+".join(modifiers) or "bare", " only" if modifier_only else ""))
    check(len(shipped) >= 10 and not killed,
          "every shipped default survives the guard (%d checked%s)"
          % (len(shipped), ": would kill " + ", ".join(killed) if killed else ""))

    # --- the guard has to be the thing that fails, not just be present ---------
    # An assertion nobody has seen fail is a rumour, and this file has been burned
    # by exactly that, so each planted shape is compiled and played as well.
    shift_return = "return (relevantModifiers & NSEventModifierFlagShift) != 0;"
    dead_guard = objc_guard.replace(shift_return, "return NO; /* inverted: never fires */")
    check(dead_guard != objc_guard,
          "the dead-guard mutation has to be a real edit, or the test below proves nothing")
    flipped_guard = objc_guard.replace("if (relevantModifiers & outsideGames) {",
                                       "if (!(relevantModifiers & outsideGames)) {")
    check(flipped_guard != objc_guard,
          "the flipped-guard mutation has to be a real edit, or the test below proves nothing")

    with tempfile.TemporaryDirectory() as work:
        for label, guard in (("dead", dead_guard), ("flipped", flipped_guard)):
            path = os.path.join(work, "%s.m" % label)
            open(path, "w", encoding="utf-8").write(
                OBJC_MODEL.replace("@@GUARD@@", guard))
            rows, _count = compile_and_run(
                path, os.path.join(work, label),
                [cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
                 "-framework", "AppKit", "-framework", "Foundation"])
            check(rows is not None,
                  "%s guard model compiles" % label if rows is not None else
                  "%s guard model must compile:\n%s" % (label, rows))
            if rows is None:
                continue
            bad, _bad_count = matrix(rows)
            if label == "dead":
                check(bad.get(shift_only) == 0,
                      "the Shift+W assertion fails on a guard that never fires")
                check(bad != objc_matrix,
                      "the sweep notices a guard that stopped answering")
            else:
                lost = [key for key, verdict in bad.items()
                        if key[1] == 1 and key[2] == 0 and verdict == 1
                        and objc_matrix.get(key) == 0]
                check(bool(lost),
                      "the shipped-default assertion fails on a guard that also eats "
                      "Control, Option and Command (%d shapes newly seized)" % len(lost))

    # One half learning the rule on its own is the drift this file exists to catch.
    one_sided = swift_guard.replace(
        "    if !flags.intersection(outsideGames).isEmpty {\n      return false\n    }\n",
        "")
    check(one_sided != swift_guard,
          "the one-sided mutation has to be a real edit, or the test below proves nothing")
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "one_sided.swift")
        model = strip_declaration(
            SWIFT_MODEL.replace("@@RELEVANT@@", relevant)
            .replace("@@GUARD@@", one_sided)
            .replace("StreamShortcut?", "FakeShortcut?")
            .replace("StreamShortcutProfile.", ""))
        open(path, "w", encoding="utf-8").write(model)
        rows, _count = compile_and_run(path, os.path.join(work, "one_sided"),
                                       [swiftc, "-sdk", swift_sdk])
        check(rows is not None, "the one-sided guard model compiles"
              if rows is not None else
              "the one-sided guard model must compile:\n%s" % rows)
        if rows is not None:
            bad, _bad_count = matrix(rows)
            check(bad != objc_matrix,
                  "the two-halves-agree assertion fails when only the form knows "
                  "about Control, Option and Command")

    return finish()


def finish():
    print("%d gameplay modifier failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
