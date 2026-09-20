#!/usr/bin/env python3
"""Prove that one switch decides what a Command key means on the host, and that it decides it everywhere.

The mapping this app ships is deliberate: Command sends the Windows key, because that is what
Parsec, UU Remote and Steam Link do and what a player arriving from them already knows. The
player this file is about arrives from somewhere else, and for them Command is the Control key.
A translation rule cannot serve that player, because a rule names one chord and
Command-as-Control has to hold for every chord they might press. So the fork gained one switch
rather than the seven-mode picker it deleted in August.

One switch means every path answers the same way at once: the keys typed, the modifier state the
host is kept in sync with, the shortcut that fires from a mouse rule, the rule the player bound,
and the Windows key that goes away when Control takes its place. The mapping is compiled whole
with a real clang and driven with samples, including the shape this file exists to forbid -- a
Command press that arrives as Control and Win at the same time. Seven planted defects have to be
noticed, and the default is compared between the two languages that have to agree on it.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
HEADER = "Limelight/Input/KeyboardMapResolver.h"
IMPL = "Limelight/Input/KeyboardMapResolver.m"
HID = "Limelight/Input/HIDSupport.m"
INTERN = "Limelight/Input/HIDSupport_Internal.h"
CAPTURE = "Limelight/macOS/ViewControllers/StreamViewController+MouseCapture.m"
DERIVED = "Limelight/macOS/ViewControllers/SettingsModel+DerivedValues.swift"
BRIDGE = "Limelight/macOS/ViewControllers/SettingsObjCBridge.swift"
PANE = "Limelight/macOS/ViewControllers/SettingsInputPane.swift"
SHORTCUTS = "Limelight/macOS/ViewControllers/SettingsShortcuts.swift"
CONTROLS = "Limelight/macOS/ViewControllers/SettingsSharedControls.swift"
PBX = "Moonlight.xcodeproj/project.pbxproj"
EN = "Limelight/macOS/en.lproj/Localizable.strings"
ZH = "Limelight/macOS/zh-Hans.lproj/Localizable.strings"

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def shipping_rules():
    header_raw, impl_raw = read(HEADER), read(IMPL)
    check(re.findall(r'#import\s*"([^"]+)"', impl_raw) == ["KeyboardMapResolver.h", "../Utility/Logger.h"],
          "the mapping needs its own header and the logger, and nothing else: no HID internals, "
          "so it can be compiled on its own and a change here cannot drag the driver in")
    rules = header_raw + "\n" + impl_raw \
        .replace('#import "KeyboardMapResolver.h"\n', "") \
        .replace('#import "../Utility/Logger.h"\n', "")
    # AppKit is where NSEventModifierFlags lives. The app reaches it through the usual
    # prefix header; the gate names it directly rather than inventing the flag values.
    # The silenced warning belongs to the silenced logger: the startup dump uses the value
    # it computes, and here the dump says nothing, so the value goes unread. The samples
    # below read the mapping directly, so the warning is noise, not a finding.
    return ("#import <AppKit/AppKit.h>\n#include <string.h>\n#include <stdio.h>\n"
            "#pragma clang diagnostic ignored \"-Wunused-variable\"\n"
            "#define LOG_I 0\n#define Log(level, ...) ((void)0)\n") + rules


DRIVER = r"""
@@RULES@@

static int failures = 0;

static void expect_mask(const char *what, KMR_PhysicalModifier phys, KMR_CommandPreference pref,
                        KMR_RemoteModifierMask want) {
    KMR_RemoteModifierMask got = KMR_RemoteMaskForPhysicalWithCommandPreference(phys, pref);
    if (got != want) {
        failures++;
        printf("FAIL %s: mask 0x%02X, wanted 0x%02X\n", what, got, want);
    }
}

static void expect_vk(const char *what, unsigned short keyCode, KMR_CommandPreference pref,
                      unsigned short want) {
    unsigned short got = KMR_RemoteVKForPhysicalKeyCodeWithCommandPreference(keyCode, pref);
    if (got != want) {
        failures++;
        printf("FAIL %s: VK 0x%02X, wanted 0x%02X\n", what, got, want);
    }
}

static void expect_flags(const char *what, NSEventModifierFlags flags, KMR_CommandPreference pref,
                         KMR_RemoteModifierMask want) {
    KMR_RemoteModifierMask got = KMR_RemoteMaskForAppKitFlagsWithCommandPreference(flags, pref);
    if (got != want) {
        failures++;
        printf("FAIL %s: flags mask 0x%02X, wanted 0x%02X\n", what, got, want);
    }
}

int main(void) {
    const KMR_CommandPreference win = KMR_CommandPreferenceWin;
    const KMR_CommandPreference ctrl = KMR_CommandPreferenceControl;

    // --- the answer a player who never opened the switch gets ----------------
    if (KMR_CommandPreferenceDefault() != KMR_CommandPreferenceWin) {
        failures++;
        printf("FAIL the shipped default moved off the Windows key\n");
    }
    for (uint8_t p = 0; p < KMR_Phys_Count; p++) {
        KMR_PhysicalModifier phys = (KMR_PhysicalModifier)p;
        if (KMR_RemoteMaskForPhysicalWithCommandPreference(phys, win) != KMR_RemoteMaskForPhysical(phys)) {
            failures++;
            printf("FAIL %s: the default answer differs from the answer of the table\n",
                   KMR_LabelForPhysical(phys));
        }
        if (KMR_RemoteMaskForPhysical(phys) == (KMR_RemoteMaskForPhysical(phys) & KMR_Remote_LeftControl) &&
            phys == KMR_Phys_LeftCommand) {
            failures++;
            printf("FAIL the argument-free answer sends Control for Command\n");
        }
    }

    // --- Command means Control, on both sides, and nothing else moves -------
    expect_mask("left Command under the Control preference", KMR_Phys_LeftCommand, ctrl, KMR_Remote_LeftControl);
    expect_mask("right Command under the Control preference", KMR_Phys_RightCommand, ctrl, KMR_Remote_RightControl);
    expect_mask("left Command still means the Windows key by default", KMR_Phys_LeftCommand, win, KMR_Remote_LeftMeta);
    expect_mask("right Command still means the Windows key by default", KMR_Phys_RightCommand, win, KMR_Remote_RightMeta);

    static const struct { KMR_PhysicalModifier phys; KMR_RemoteModifierMask mask; } others[] = {
        { KMR_Phys_LeftShift,    KMR_Remote_LeftShift    },
        { KMR_Phys_RightShift,   KMR_Remote_RightShift   },
        { KMR_Phys_LeftControl,  KMR_Remote_LeftControl  },
        { KMR_Phys_RightControl, KMR_Remote_RightControl },
        { KMR_Phys_LeftOption,   KMR_Remote_LeftAlt      },
        { KMR_Phys_RightOption,  KMR_Remote_RightAlt     },
    };
    for (size_t i = 0; i < sizeof(others) / sizeof(others[0]); i++) {
        expect_mask("a key that is not Command keeps its mapping", others[i].phys, ctrl, others[i].mask);
    }

    // --- the shape this file exists to forbid -------------------------------
    for (uint8_t p = 0; p < KMR_Phys_Count; p++) {
        KMR_RemoteModifierMask got = KMR_RemoteMaskForPhysicalWithCommandPreference((KMR_PhysicalModifier)p, ctrl);
        if (got & (KMR_Remote_LeftMeta | KMR_Remote_RightMeta)) {
            failures++;
            printf("FAIL %s under the Control preference still sends the Windows key\n",
                   KMR_LabelForPhysical((KMR_PhysicalModifier)p));
        }
    }
    expect_flags("Command held with the Control preference also taps the Windows key",
                 NSEventModifierFlagCommand, ctrl, KMR_Remote_LeftControl);
    expect_flags("Command and Shift under the Control preference",
                 NSEventModifierFlagCommand | NSEventModifierFlagShift, ctrl,
                 KMR_Remote_LeftControl | KMR_Remote_LeftShift);
    expect_flags("Command under the default preference", NSEventModifierFlagCommand, win, KMR_Remote_LeftMeta);
    expect_flags("no modifier held", 0, ctrl, 0);
    // Both Control keys held is one bit to the host, which is what lets the player release
    // either of them and keep the key down. Two bits here would let the first release end a
    // sprint the other finger is still holding.
    expect_flags("Control and Command together under the Control preference",
                 NSEventModifierFlagControl | NSEventModifierFlagCommand, ctrl, KMR_Remote_LeftControl);
    expect_flags("Control and Command together by default",
                 NSEventModifierFlagControl | NSEventModifierFlagCommand, win,
                 KMR_Remote_LeftControl | KMR_Remote_LeftMeta);

    // --- the keycode path has to agree with the mask path -------------------
    expect_vk("left Command under the Control preference", kVK_Command, ctrl, KMR_VK_LCONTROL);
    expect_vk("right Command under the Control preference", kVK_RightCommand, ctrl, KMR_VK_RCONTROL);
    expect_vk("left Command by default", kVK_Command, win, KMR_VK_LWIN);
    expect_vk("right Command by default", kVK_RightCommand, win, KMR_VK_RWIN);
    expect_vk("left Control under either preference", kVK_Control, ctrl, KMR_VK_LCONTROL);
    expect_vk("left Control under either preference by default", kVK_Control, win, KMR_VK_LCONTROL);
    expect_vk("a key that is not a modifier", kVK_ANSI_A, ctrl, 0);
    expect_vk("a key that is not a modifier by default", kVK_ANSI_A, win, 0);

    printf("%s\n", failures ? "RUN FAILED" : "RUN PASSED");
    return failures ? 1 : 0;
}
"""


def token_findings(shortcuts_text, controls_text):
    """What the Settings pane calls the key it is showing, and who has to agree with it.

    A switch that changes what a key means has to change what the pane names it, or the card
    describing a rule lies about the packets it sends. These are text checks, so a defect can
    be planted and read back through the same function.
    """
    out = []
    block = re.search(r"static func remoteDisplayTokens\(for shortcut: StreamShortcut,"
                      r"(.*?)\n  \}", shortcuts_text, re.S)
    branch = re.search(r"if modifiers\.contains\(\.command\) \{(.*?)\n    \}",
                       block.group(1) if block else "", re.S)
    if block is None or "commandSendsControl: Bool = false" not in block.group(1):
        out.append("the list of keys a rule shows does not take the switch")
    if branch is None or "if commandSendsControl" not in branch.group(1) or \
            'tokens.append("Win")' not in branch.group(1):
        out.append("the Command token does not answer Ctrl when the switch is on and Win when it is not")
    elif "if !controlHeld" not in branch.group(1):
        out.append("the two keys that are one bit to the host are counted twice on screen")
    for needle, why in (
            ("forRemoteOutput: outputShortcut, commandSendsControl: commandSendsControl",
             "a saved rule card stops naming the switch it reads"),
            ("forRemoteOutput: remoteOutputShortcut,\n              commandSendsControl: settingsModel.commandSendsControl",
             "the editor's preview stops naming the switch it reads")):
        if needle not in controls_text:
            out.append(why)
    return out


def compiled(source, work, name, cc, sdk):
    path = os.path.join(work, name + ".m")
    open(path, "w", encoding="utf-8").write(source)
    command = [cc, "-x", "objective-c", "-isysroot", sdk, "-Wall", "-Werror",
               "-framework", "Foundation", path, "-o", os.path.join(work, name)]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        return None, None, (built.stdout + built.stderr).strip()[-2200:]
    ran = subprocess.run([os.path.join(work, name)], capture_output=True, text=True)
    return ran.returncode, ran.stdout, (ran.stdout + ran.stderr).strip()[-2200:]


def run_rules(label, rules, cc, sdk, expect_pass=False):
    with tempfile.TemporaryDirectory() as work:
        code, out, log = compiled(DRIVER.replace("@@RULES@@", rules), work, "commandcontrol", cc, sdk)
        if code is None:
            check(False, "%s: %s" % (label, log))
            return
        if expect_pass:
            check(code == 0 and out is not None and "RUN PASSED" in out,
                  "the shipping mapping answers every sample correctly"
                  if code == 0 else "the shipping mapping failed a case:%s" % out)
        else:
            check(code != 0, "the check still fails when %s" % label)


def mutated(rules, label, before, after):
    check(before in rules, "%s: the source it mutates is still there" % label)
    return rules.replace(before, after, 1)


def main():
    rules = shipping_rules()
    print("-- what one Command key is allowed to mean on the host --")

    cc, sdk = apple_toolchain.clang_and_sdk("command to control")
    run_rules("the shipping mapping", rules, cc, sdk, expect_pass=True)

    # --- every keyboard path has to ask the same question -------------------
    hid = read(HID)
    for bare in ("KMR_RemoteMaskForPhysical(", "KMR_RemoteMaskForAppKitFlags(",
                 "KMR_RemoteVKForPhysicalKeyCode("):
        check(bare not in hid,
              "no keyboard path in the driver takes the answer without the switch: %s" % bare)
    check(hid.count("commandKeyPreferenceForCurrentHost") >= 6,
          "every one of the driver's Command paths asks the switch, not a chosen few")
    check("[SettingsClass commandSendsControlFor:hostUuid]" in hid and
          '- (KMR_CommandPreference)commandKeyPreferenceForCurrentHost {' in hid,
          "the switch is read from this host's own stored preference")
    check("- (KMR_CommandPreference)commandKeyPreferenceForCurrentHost;" in read(INTERN),
          "the question is declared in the internal header, so the paths that need it can ask")
    check("KMR_LogActiveMapping([self commandKeyPreferenceForCurrentHost])" in hid,
          "the log at session start says which Command mapping this host actually got")

    check("KMR_" not in read(CAPTURE),
          "the paths that decide what the Mac keeps for itself never consult the remote mapping")

    # --- what the pane calls the key it is showing --------------------------
    token_problems = token_findings(read(SHORTCUTS), read(CONTROLS))
    for message in token_problems:
        check(False, message)
    check(not token_problems,
          "the pane names the Command key the way the switch says it travels")

    # --- one default, spelled twice ------------------------------------------
    body = re.search(r"KMR_CommandPreference KMR_CommandPreferenceDefault\(void\) \{(.*?)\n\}",
                     read(IMPL), re.S)
    c_default = re.search(r"return (KMR_CommandPreference\w+);", body.group(1)) if body else None
    swift_default = re.search(r"static let defaultCommandSendsControl = (true|false)", read(DERIVED))
    check(c_default is not None and swift_default is not None and
          (c_default.group(1) == "KMR_CommandPreferenceControl") == (swift_default.group(1) == "true"),
          "C and Swift agree on the shipping default, because one switch is read in one and written in the other")
    check("@objc static func commandSendsControl (for key: String) -> Bool" in read(BRIDGE),
          "the driver asks through a declared bridge method, not by name")
    check("boolBinding: $settingsModel.commandSendsControl" in read(PANE),
          "the switch is on the Keyboard section of Settings, where a player can find it")
    check("Input/KeyboardMapResolver.m," in read(PBX),
          "the mapping is named in the project, so it is compiled and not silently absent")

    for table, name in ((EN, "English"), (ZH, "Chinese")):
        text = read(table)
        check('"Command Key Sends Control" = ' in text and
              '"Command Key Sends Control detail" = ' in text,
              "the %s table answers the switch and its explanation" % name)

    # --- the planted defects --------------------------------------------------
    print("-- the defects this check has to notice --")
    run_rules("left Command is left behind by the switch",
              mutated(rules, "left Command",
                      "if (mask == KMR_Remote_LeftMeta)  return KMR_Remote_LeftControl;",
                      "if (mask == KMR_Remote_LeftMeta)  return mask;"), cc, sdk)
    run_rules("right Command arrives as the left Control key",
              mutated(rules, "right Command",
                      "if (mask == KMR_Remote_RightMeta) return KMR_Remote_RightControl;",
                      "if (mask == KMR_Remote_RightMeta) return KMR_Remote_LeftControl;"), cc, sdk)
    run_rules("the switch is read and then ignored",
              mutated(rules, "an unread switch",
                      "    if (pref == KMR_CommandPreferenceControl) {",
                      "    if (NO && pref == KMR_CommandPreferenceControl) {"), cc, sdk)
    run_rules("the keycode path keeps answering the Windows key",
              mutated(rules, "a keycode path that ignores the switch",
                      "    KMR_RemoteModifierMask mask = KMR_MaskForPhysicalPref(phys, pref);",
                      "    KMR_RemoteModifierMask mask = s_mapTable[phys];"), cc, sdk)
    run_rules("the rule path keeps answering the Windows key",
              mutated(rules, "a flags path that ignores the switch",
                      "        out |= KMR_MaskForPhysicalPref(KMR_Phys_LeftCommand, pref);",
                      "        out |= KMR_RemoteMaskForPhysical(KMR_Phys_LeftCommand);"), cc, sdk)
    run_rules("a Command press sends Control and the Windows key at once",
              mutated(rules, "a Command press that sends both keys",
                      "        out |= KMR_MaskForPhysicalPref(KMR_Phys_LeftCommand, pref);",
                      "        out |= KMR_MaskForPhysicalPref(KMR_Phys_LeftCommand, pref) | KMR_RemoteMaskForPhysical(KMR_Phys_LeftCommand);"), cc, sdk)
    for label, target, before, after in (
            ("the card keeps calling Command by the name the switch replaced", SHORTCUTS,
             "      if commandSendsControl {", "      if false {"),
            ("the card counts one key as two", SHORTCUTS,
             "        if !controlHeld {", "        if true {"),
            ("a saved rule card asks for nothing", CONTROLS,
             "forRemoteOutput: outputShortcut, commandSendsControl: commandSendsControl",
             "forRemoteOutput: outputShortcut"),
    ):
        text = read(target)
        check(before in text, "%s: the source it mutates is still there" % label)
        mutated_texts = text.replace(before, after, 1)
        other = read(CONTROLS) if target == SHORTCUTS else read(SHORTCUTS)
        caught = token_findings(mutated_texts, other) if target == SHORTCUTS \
            else token_findings(other, mutated_texts)
        check(bool(caught), "the check still fails when %s" % label)

    run_rules("the shipping default quietly becomes Control",
              mutated(rules, "the default",
                      "    return KMR_CommandPreferenceWin;\n}",
                      "    return KMR_CommandPreferenceControl;\n}"), cc, sdk)

    print("%d command-to-control failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
