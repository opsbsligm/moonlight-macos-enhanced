#!/usr/bin/env python3
"""Prove that the button which offers Ctrl+Alt+Del offers the chord the host actually needs.

Windows will not hand the secure attention sequence to an application, which is why Citrix
gives it a policy item of its own. macOS has no such interception, so this client never needed
a mechanism: the ordinary translation path already carries Control, Option and Forward Delete
to the host, and the rule editor's key table has named Forward Delete for as long as it has had
a table. What a player lacked was any way to find that out, so the fix is discoverability --
one preset -- and the risk moved accordingly. A button that prefills the wrong chord is worse
than no button, because it looks like a solution.

Nothing here compiles the app: `keyboard-shortcut-modifier-tests.py` already puts this exact
chord on a wire built from the shipping `HIDSupport.m` and finds Control+Alt+Forward Delete at
the other end. What this file holds together is the two ends of the sentence -- that the
preset in Settings is the same chord the wire test proved, that no local action already claims
it, and that the sheet still calls it an addition. The defects planted below are the shapes
that sentence loses in, and each has to be noticed.
"""
import os, re, sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
SHORTCUTS = "Limelight/macOS/ViewControllers/SettingsShortcuts.swift"
CONTROLS = "Limelight/macOS/ViewControllers/SettingsSharedControls.swift"
HID = "Limelight/Input/HIDSupport.m"
WIRE = "scripts/keyboard-shortcut-modifier-tests.py"
EN = "Limelight/macOS/en.lproj/Localizable.strings"
ZH = "Limelight/macOS/zh-Hans.lproj/Localizable.strings"

PRESET_KEY = "kVK_ForwardDelete"
PRESET_MODIFIERS = {".control", ".option"}

FILES = (SHORTCUTS, CONTROLS, HID, WIRE, EN, ZH)


def read(root, rel):
    return open(os.path.join(root, rel), encoding="utf-8").read()


def sources(root):
    return {name: read(root, name) for name in FILES}


def preset_body(text):
    """The factory's own body, or nothing at all: an absent preset fails every check below."""
    match = re.search(r"func secureAttentionSequencePresetRule\(\)[^{]*\{(.*?)\n  \}", text, re.S)
    return match.group(1) if match else ""


def chord_in(body):
    """One StreamShortcut(...) written as keyCode plus a modifier array."""
    match = re.search(r"StreamShortcut\(keyCode:\s*(\w+),\s*modifierFlags:\s*\[([^\]]*)\]", body)
    if match is None:
        return None, None
    return match.group(1), {m.strip() for m in match.group(2).split(",") if m.strip()}


def local_action_chords(shortcuts_text):
    """Every chord a local action ships with, so a preset cannot step on one."""
    block = re.search(r"func defaultShortcuts\(\)[^{]*\{(.*?)\n  \}", shortcuts_text, re.S)
    if block is None:
        return None
    chords = []
    for keyCode, flags in re.findall(r"keyCode:\s*(\w+),\s*modifierFlags:\s*\[([^\]]*)\]",
                                     block.group(1)):
        chords.append((keyCode, {m.strip() for m in flags.split(",") if m.strip()}))
    return chords


def findings(texts):
    out = []
    shortcuts, controls, hid, wire = (texts[SHORTCUTS], texts[CONTROLS], texts[HID], texts[WIRE])

    body = preset_body(shortcuts)
    if not body:
        out.append("the rule editor has no secure attention sequence preset to offer")
        return out

    keyCode, modifiers = chord_in(body)
    if keyCode != PRESET_KEY:
        out.append("the preset is built on %s, not the Forward Delete key the host reads as Delete"
                   % keyCode)
    if modifiers != PRESET_MODIFIERS:
        out.append("the preset names %s, not the Control and Option the sequence needs"
                   % ", ".join(sorted(modifiers or {"(none)"})))

    if body.count("StreamShortcut(keyCode:") != 1:
        out.append("the preset builds its chord more than once, so trigger and output can drift apart")
    if "trigger: chord, outputShortcut: chord" not in body:
        out.append("the preset does not send the chord it asks the player to press")

    chords = local_action_chords(shortcuts)
    if chords is None:
        out.append("the local actions' own chords could not be read, so a collision could not be ruled out")
    elif (PRESET_KEY, PRESET_MODIFIERS) in chords:
        out.append("a local action already fires on Control+Option+Forward Delete, "
                   "so the preset would hide it")

    if re.search(r"%s:\s*\"" % PRESET_KEY, shortcuts) is None:
        out.append("the rule editor's key table has no name for the preset's key, "
                   "so the player could not see what they were being offered")

    if "secureAttentionSequencePresetRule()" not in controls:
        out.append("no control offers the preset, so it stays as undiscoverable as the chord was")
    if "isPreset: true" not in controls:
        out.append("the preset opens the sheet as an edit of a rule nobody saved")
    if 'rule == nil || isPreset' not in controls:
        out.append("the sheet says Edit over a rule the player has not written yet")

    # The wire test is a different file, on a different side of the tree. These two have to
    # name the same chord, or the button is proved and the wire proves something else.
    if "Rule(kVK_ForwardDelete, NSEventModifierFlagControl | NSEventModifierFlagOption)" not in wire:
        out.append("the wire test fires a different chord than the preset builds")
    for needle, why in (("0x8000 | 0x2E", "Forward Delete on the host"),
                        ("MODIFIER_CTRL | MODIFIER_ALT", "Control and Alt in the modifier byte"),
                        ("@117: @(0x2E)", "the test table's own Forward Delete entry")):
        if needle not in wire:
            out.append("the wire test no longer asserts %s" % why)

    if "{kVK_ForwardDelete, 0x2E}" not in hid:
        out.append("the driver does not map Forward Delete to 0x2E, so 0x2E above is a guess")

    # Read from what the controls ask for, not from a list written here: a wording the pane
    # stopped naming would still be "covered" by a list, and the player would meet English.
    referenced = set(re.findall(
        r'localize\("(Add Preset Rule[^"]*|Secure Attention Sequence Rule[^"]*)"\)', controls))
    if not referenced:
        out.append("no wording of the preset's own is asked for anywhere in Settings")
    for key in sorted(referenced):
        for table, name in ((EN, "English"), (ZH, "Chinese")):
            if '"%s" = ' % key not in texts[table]:
                out.append("the %s table has no wording for %r" % (name, key))
    return out


def main():
    texts = sources(ROOT)
    failures = findings(texts)
    for message in failures:
        print("FAIL %s" % message)

    print("-- the shapes this check has to notice --")
    mutations = (
        ("the preset is built on Delete instead of Forward Delete",
         SHORTCUTS, "StreamShortcut(keyCode: kVK_ForwardDelete, modifierFlags: [.control, .option])",
         "StreamShortcut(keyCode: kVK_Delete, modifierFlags: [.control, .option])"),
        ("the preset reaches for Shift where it needs Option",
         SHORTCUTS, "StreamShortcut(keyCode: kVK_ForwardDelete, modifierFlags: [.control, .option])",
         "StreamShortcut(keyCode: kVK_ForwardDelete, modifierFlags: [.control, .shift])"),
        ("a local action starts claiming the same chord",
         SHORTCUTS,
         "openControlCenterAction: StreamShortcut(keyCode: kVK_ANSI_C, modifierFlags: [.control, .option]),",
         "openControlCenterAction: StreamShortcut(keyCode: kVK_ForwardDelete, modifierFlags: [.control, .option]),"),
        ("the preset opens the editor as an edit",
         CONTROLS, "isPreset: true", "isPreset: false"),
        ("the preset's explanation loses its table entry",
         CONTROLS, '"Add Preset Rule help"', '"Add Preset Rule hint"'),
        ("the wire test drifts to another chord",
         WIRE, "Rule(kVK_ForwardDelete, NSEventModifierFlagControl | NSEventModifierFlagOption)",
         "Rule(kVK_ANSI_C, NSEventModifierFlagControl | NSEventModifierFlagOption)"),
    )
    for label, name, before, after in mutations:
        if before not in texts[name]:
            print("FAIL %s: the source it mutates is no longer there" % label)
            failures.append(label)
            continue
        mutated = dict(texts)
        mutated[name] = texts[name].replace(before, after, 1)
        caught = findings(mutated)
        print("%-4s %s" % ("ok" if caught else "FAIL",
                           "noticed: %s" % label if caught else "the check passes %s" % label))
        if not caught:
            failures.append(label)

    print("%d sas-preset failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
