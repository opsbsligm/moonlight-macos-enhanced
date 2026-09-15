#!/usr/bin/env python3
"""Compile the shipped shortcut profile and ask it what it hands to AppKit.

`-menuKeyEquivalentFor:` feeds `NSMenuItem.keyEquivalent`, and the symbol table it
reads is written for people: `Space`, `Tab`, `Return`, `Page Up`, an arrow glyph.
Handing one of those words to AppKit does not turn its first letter into a shortcut.
Measured against a live `NSMenu`, an item whose key equivalent is "space" matches
neither Control+Option+S nor Control+Option+Space, so the menu shows a hint nobody can
press and the binding only works while the stream view itself is taking keys.

The fix is a line, so the line is what gets tested: every key the settings page offers
has to produce either nothing or one printable ASCII character, the single-character
keys still have to produce their letter, and the shape that predates the guard -- the
word itself -- still has to be refused. Nothing here restates the table; the key list
is read out of the same Swift source that is then compiled.

Exit 0 when the shipped file answers correctly and the known-bad variant does not.
"""
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers", "SettingsShortcuts.swift")
MAIN = r"""
import AppKit
import Carbon.HIToolbox

let cases: [(String, Int)] = [
__CASES__
]

var failures = 0
var wordsRefused = 0
var lettersThatPassed = 0
for (name, code) in cases {
    let shortcut = StreamShortcut(keyCode: code, modifierFlags: [.control, .option])
    let equivalent = StreamShortcutProfile.menuKeyEquivalent(for: shortcut)
    let symbol = StreamShortcutProfile.keySymbol(for: code) ?? ""
    if equivalent.isEmpty {
        // No hint at all is the right answer for a name AppKit cannot compare against a
        // key, and it is the answer the guard exists to produce. Counting the refusals
        // is what keeps the next scenario honest: if the table ever stops offering any
        // word, the guard has nothing left to refuse and the test would prove nothing.
        if symbol.count > 1 {
            wordsRefused += 1
        }
        continue
    }
    let scalars = Array(equivalent.unicodeScalars)
    let single = scalars.count == 1
    let printable = single && scalars[0].value >= 0x20 && scalars[0].value < 0x7F
    if !single || !printable {
        print("FAIL \(name) (\(symbol)) produced \(equivalent.count) scalar(s) AppKit cannot match")
        failures += 1
    } else if symbol.count > 1 {
        print("FAIL \(name) is named \(symbol) yet produced '\(equivalent)'")
        failures += 1
    } else {
        lettersThatPassed += 1
    }
}

if wordsRefused == 0 {
    print("FAIL no multi-character key name was refused, so the guard has nothing to say")
    failures += 1
}
if lettersThatPassed < 30 {
    print("FAIL only \(lettersThatPassed) single-key bindings still produced their letter, "
          + "which would mean the guard switched the feature off rather than aimed it")
    failures += 1
}

// The defaults have to survive the guard: a player who never opened settings should
// still see Control+Option+S on the performance-overlay row.
let overlay = StreamShortcut(keyCode: kVK_ANSI_S, modifierFlags: [.control, .option])
if StreamShortcutProfile.menuKeyEquivalent(for: overlay) != "s" {
    print("FAIL the default Control+Option+S overlay shortcut no longer reaches the menu")
    failures += 1
}

print("\(failures) failure(s), \(lettersThatPassed) letter bindings kept")
exit(Int32(failures == 0 ? 0 : 1))
"""


def offered_keys(text):
    """The key names the settings page lets a person bind, read from the source."""
    start = text.index("supportedKeySymbols: [Int: String] = [")
    end = text.index("\n  ]", start)
    names = re.findall(r"(kVK_[A-Za-z0-9_]+)\s*:", text[start:end])
    if len(names) < 40:
        raise SystemExit("the settings page offers %d keys, which is too few for this "
                         "gate to mean anything -- check the table's shape" % len(names))
    return names


def build_and_run(directory, source, label):
    swiftc = None
    clang, sdk = apple_toolchain.clang_and_sdk("shortcut menu key probe")
    candidate = os.path.join(os.path.dirname(clang), "swiftc")
    if os.path.exists(candidate):
        swiftc = candidate
    if swiftc is None:
        raise SystemExit("no swiftc beside the compiler this project builds with, so the "
                         "shipped shortcut profile cannot be compiled and asked")
    profile = os.path.join(directory, "SettingsShortcuts.swift")
    with open(profile, "w", encoding="utf-8") as handle:
        handle.write(source)
    main = os.path.join(directory, "main.swift")
    with open(main, "w", encoding="utf-8") as handle:
        handle.write(MAIN.replace("__CASES__", CASES))
    binary = os.path.join(directory, "probe_" + label)
    built = subprocess.run([swiftc, "-sdk", sdk, "-target", "arm64-apple-macosx26.0",
                            profile, main, "-o", binary], capture_output=True, text=True)
    if built.returncode != 0:
        print("FAIL the %s shortcut profile did not compile:\n%s"
              % (label, (built.stdout + built.stderr)[-1500:]))
        return None
    return subprocess.run([binary], capture_output=True, text=True)


def remove_the_guard(text):
    """The shipped shape before the fix: whatever the table calls it, hand it over.

    Matched by shape rather than by a copy of the source, because a second copy of that
    text would be a second thing that can drift away from the file it is supposed to
    describe -- and a mutation that no longer matches anything is a gate with no teeth.
    """
    mutated, hits = re.subn(
        r"\n    guard key\.utf16\.count[\s\S]*?\n    \}\n", "\n", text, count=1)
    if hits != 1:
        raise SystemExit("the menu-equivalent guard is not where this mutation expects it, "
                         "so it would prove nothing")
    return mutated


check_failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        check_failures.append(message)


def main():
    global CASES
    source = open(SOURCE, encoding="utf-8").read()
    keys = offered_keys(source)
    CASES = "\n".join('    ("%s", %s),' % (name, code) for name, code in
                      ((name, name) for name in keys))
    # Swift wants the constant, not its name repeated as a string.
    CASES = "\n".join('    ("%s", %s),' % (name[4:], name) for name in keys)

    with tempfile.TemporaryDirectory() as tmp:
        shipped = build_and_run(tmp, source, "shipped")
        if shipped is None:
            return 1
        print(shipped.stdout.rstrip())
        check(shipped.returncode == 0,
              "every key the settings page offers yields a hint AppKit can match"
              if shipped.returncode == 0 else
              "the shipped shortcut profile answers with something AppKit cannot match")

        broken = remove_the_guard(source)
        if broken == source:
            print("FAIL the unguarded shape is identical to the shipped one (no teeth)")
            return 1
        bad = build_and_run(tmp, broken, "unguarded")
        if bad is None:
            return 1
        check(bad.returncode != 0,
              "the shape that hands the word itself to AppKit is refused"
              if bad.returncode != 0 else
              "the unguarded profile passes: this gate has no teeth")
        print("        %s" % (bad.stdout.strip().splitlines() or ["no output"])[0])

    print("%d harness failure(s)" % len(check_failures))
    return 1 if check_failures else 0


sys.exit(main())
