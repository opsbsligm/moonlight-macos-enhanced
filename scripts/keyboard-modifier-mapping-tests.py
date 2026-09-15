#!/usr/bin/env python3
"""Prove the modifier mapping sends the key the user pressed, left for left.

The header says this module is the single source of truth for the modifier mapping,
and the header is the thing the user is buying: Command goes to Win, Control to Ctrl,
Option to Alt, Shift to Shift, each side to its own side. Nothing checked it. No test,
no constraint, no scenario named KMR_ at all -- so a table entry pointing at the wrong
side, or two physical keys collapsing onto one remote key, would have shipped silently
and shown up as "my keyboard feels wrong in games", which is exactly the class of report
this file exists to make impossible.

What is compiled here is the shipped file, verbatim apart from its two project imports:
the lookup table, the keycode-to-physical switch, the mask lookup, the mask-to-virtual-key
reverse lookup, and the AppKit-flags path that mouse-driven events take. The only stub is
the logger, because nothing here depends on what it prints.

Three shapes of wrong are caught by construction:
  * two mac keys resolving to one physical modifier, which is how a left and a right key
    become the same key on the host;
  * a table entry holding more than one remote bit, which makes the reverse lookup fall
    through to zero and the host receive no modifier at all;
  * a Windows virtual key that is not the standard one, checked against values written
    out here rather than against the same table.

Teeth: the same scenarios run against two variants -- the right-hand keys mapped to the
left-hand remote key, which is the shape that made a double-click send a Win key -- and a
variant that passes would mean the scenarios prove nothing.

Usage: keyboard-modifier-mapping-tests.py [--preflight]
Exit 0 only when the shipped mapping passes every scenario and both variants fail them.
"""
import os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOLVER_M = os.path.join(ROOT, "Limelight", "Input", "KeyboardMapResolver.m")
RESOLVER_H = os.path.join(ROOT, "Limelight", "Input", "KeyboardMapResolver.h")

# Windows virtual-key codes for the eight modifier keys, written out here on purpose:
# quoting them from the code under test would only prove the code agrees with itself.
WINDOWS_VK = {
    "LSHIFT": 0xA0, "RSHIFT": 0xA1,
    "LCONTROL": 0xA2, "RCONTROL": 0xA3,
    "LALT": 0xA4, "RALT": 0xA5,
    "LWIN": 0x5B, "RWIN": 0x5C,
}

# mac keycode, expected remote key, and the single remote bit it has to be.
EXPECTATIONS = [
    ("kVK_Shift", "KMR_Phys_LeftShift", "KMR_Remote_LeftShift", "LSHIFT"),
    ("kVK_RightShift", "KMR_Phys_RightShift", "KMR_Remote_RightShift", "RSHIFT"),
    ("kVK_Control", "KMR_Phys_LeftControl", "KMR_Remote_LeftControl", "LCONTROL"),
    ("kVK_RightControl", "KMR_Phys_RightControl", "KMR_Remote_RightControl", "RCONTROL"),
    ("kVK_Option", "KMR_Phys_LeftOption", "KMR_Remote_LeftAlt", "LALT"),
    ("kVK_RightOption", "KMR_Phys_RightOption", "KMR_Remote_RightAlt", "RALT"),
    ("kVK_Command", "KMR_Phys_LeftCommand", "KMR_Remote_LeftMeta", "LWIN"),
    ("kVK_RightCommand", "KMR_Phys_RightCommand", "KMR_Remote_RightMeta", "RWIN"),
]

STUB = r'''
// AppKit, not Foundation: NSEventModifierFlags is declared by NSEvent, and the
// resolver header only pulls in Carbon, which is why the shipped file compiles inside
// the app (something else in its translation unit brings AppKit) while a probe that
// includes the header alone does not. The first version of this harness asked for
// Foundation and the CI job said so in one line.
#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#include <string.h>
#include <stdio.h>

#define LOG_I 0
#define Log(level, ...) ((void) 0)

#import "RESOLVER_HEADER"
'''

MAIN = r'''
static int g_failed = 0;

static void expect(int condition, const char *what) {
    if (!condition) {
        fprintf(stderr, "FAIL %s\n", what);
        g_failed++;
    }
}

static const unsigned short keyCodes[] = { KEYCODE_LIST };

int main(void) {
    @autoreleasepool {
        // Each mac modifier key has to reach its own physical slot. Two keys landing on
        // one slot is how a laptop's left and right Command become the same key on the
        // host, and no amount of reading the table shows it: the table itself is what
        // has to be walked.
        int seen[KMR_Phys_Count] = { 0 };
        for (size_t i = 0; i < sizeof(keyCodes) / sizeof(keyCodes[0]); i++) {
            KMR_PhysicalModifier phys = KMR_PhysicalFromKeyCode(keyCodes[i]);
            char note[128];
            snprintf(note, sizeof(note), "keycode %u resolves to no physical modifier",
                     (unsigned) keyCodes[i]);
            expect(phys != KMR_Phys_Count, note);
            if (phys != KMR_Phys_Count) {
                seen[phys]++;
            }
        }
        for (int p = 0; p < KMR_Phys_Count; p++) {
            char note[128];
            snprintf(note, sizeof(note), "physical modifier %d is reached by %d mac keys",
                     p, seen[p]);
            expect(seen[p] == 1, note);
        }

        // One mac key, one remote bit, one Windows virtual key. A table entry carrying
        // two bits survives the mask lookup but makes the reverse lookup fall through to
        // zero, so the host receives no modifier at all and nothing is logged.
        unsigned short vkOf[] = { VK_LIST };
        unsigned int bitOf[] = { BIT_LIST };
        for (size_t i = 0; i < sizeof(keyCodes) / sizeof(keyCodes[0]); i++) {
            KMR_PhysicalModifier phys = KMR_PhysicalFromKeyCode(keyCodes[i]);
            KMR_RemoteModifierMask mask = KMR_RemoteMaskForPhysical(phys);
            char note[160];
            snprintf(note, sizeof(note),
                     "keycode %u maps to remote mask 0x%02X, expected 0x%02X (%d bit(s))",
                     (unsigned) keyCodes[i], (unsigned) mask, (unsigned) bitOf[i],
                     __builtin_popcount((unsigned) mask));
            expect(mask == bitOf[i], note);

            unsigned short vk = KMR_RemoteVKForPhysicalKeyCode(keyCodes[i]);
            snprintf(note, sizeof(note), "keycode %u sends VK 0x%02X, expected 0x%02X",
                     (unsigned) keyCodes[i], (unsigned) vk, (unsigned) vkOf[i]);
            expect(vk == vkOf[i], note);
        }

        // The flags path is what a device that reports only the state of the modifiers
        // takes, and it can never tell left from right: it has to answer with the left
        // key of each pair, never the right one and never a mixture.
        struct { NSEventModifierFlags flags; KMR_RemoteModifierMask want; } flagCases[] = {
            { 0, 0 },
            { NSEventModifierFlagShift, KMR_Remote_LeftShift },
            { NSEventModifierFlagControl, KMR_Remote_LeftControl },
            { NSEventModifierFlagOption, KMR_Remote_LeftAlt },
            { NSEventModifierFlagCommand, KMR_Remote_LeftMeta },
            { NSEventModifierFlagShift | NSEventModifierFlagCommand,
              KMR_Remote_LeftShift | KMR_Remote_LeftMeta },
            { NSEventModifierFlagShift | NSEventModifierFlagControl |
              NSEventModifierFlagOption | NSEventModifierFlagCommand,
              KMR_Remote_LeftShift | KMR_Remote_LeftControl |
              KMR_Remote_LeftAlt | KMR_Remote_LeftMeta },
        };
        for (size_t i = 0; i < sizeof(flagCases) / sizeof(flagCases[0]); i++) {
            KMR_RemoteModifierMask got = KMR_RemoteMaskForAppKitFlags(flagCases[i].flags);
            char note[160];
            snprintf(note, sizeof(note),
                     "flags 0x%lx resolve to mask 0x%02X, expected 0x%02X",
                     (unsigned long) flagCases[i].flags, (unsigned) got,
                     (unsigned) flagCases[i].want);
            expect(got == flagCases[i].want, note);
        }

        // A keycode that is not a modifier must not borrow one of the eight.
        expect(KMR_PhysicalFromKeyCode(kVK_ANSI_W) == KMR_Phys_Count,
               "an ordinary key was read as a modifier");
        expect(KMR_RemoteVKForPhysicalKeyCode(kVK_ANSI_W) == 0,
               "an ordinary key was given a modifier virtual key");
    }
    if (g_failed) {
        fprintf(stderr, "%d modifier scenario(s) failed\n", g_failed);
        return 1;
    }
    printf("ok   each mac modifier key reaches its own remote key, left for left\n");
    printf("ok   the AppKit flags path answers the left key of each pair, never a mixture\n");
    return 0;
}
'''


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def shipped_body():
    """The resolver source with its two project imports dropped and nothing else touched."""
    body = read(RESOLVER_M)
    stripped = re.sub(r'^#import\s+"[^"]*"\n', "", body, flags=re.M)
    if stripped == body:
        raise SystemExit("KeyboardMapResolver.m no longer imports its project headers, so "
                         "this harness is compiling something other than what it was written "
                         "against")
    if "s_mapTable" not in stripped:
        raise SystemExit("KeyboardMapResolver.m has no s_mapTable, so the mapping this "
                         "harness walks is no longer a table")
    return stripped


def assemble(variant=None):
    """The fixture source for one variant, with every number read out of the shipped files."""
    header = read(RESOLVER_H)
    for name in list(WINDOWS_VK) + ["KMR_Remote_LeftShift", "KMR_Remote_LeftMeta"]:
        if name not in header and not re.search(r"\b%s\b" % name, header):
            raise SystemExit("%s is not in KeyboardMapResolver.h any more" % name)

    body = shipped_body()
    if variant == "both-sides-left":
        # The shape that made a double-click send a Win key: both hands of one modifier
        # answering as the left hand, so the right key of each pair disappears.
        body = re.sub(r"KMR_Remote_Right(Shift|Control|Alt|Meta),(\s*//\s*KMR_Phys_Right)",
                      lambda m: "KMR_Remote_Left%s,%s" % (m.group(1), m.group(2)), body)
    elif variant == "flags-mix-sides":
        # Command answering with Alt is the other classic: a shortcut that also moves
        # the modifier the game is watching.
        body = body.replace("out |= KMR_RemoteMaskForPhysical(KMR_Phys_LeftCommand);",
                            "out |= KMR_RemoteMaskForPhysical(KMR_Phys_LeftOption);", 1)
    elif variant is not None:
        raise SystemExit("unknown variant %r" % variant)

    values = re.search(r"typedef NS_ENUM\(uint8_t, KMR_PhysicalModifier\) \{(.*?)\};",
                       header, re.S)
    if values is None:
        raise SystemExit("the physical modifier enum is not readable out of the header")

    key_codes = ", ".join(code for code, _, _, _ in EXPECTATIONS)
    vk_list = ", ".join("0x%02X" % WINDOWS_VK[remote] for _, _, _, remote in EXPECTATIONS)
    bit_list = ", ".join(bit for _, _, bit, _ in EXPECTATIONS)

    source = STUB.replace('"RESOLVER_HEADER"', '"%s"' % RESOLVER_H)
    source += body + "\n" + MAIN.replace("KEYCODE_LIST", key_codes) \
                                 .replace("VK_LIST", vk_list) \
                                 .replace("BIT_LIST", bit_list)
    leftovers = sorted(set(re.findall(r"\b(KEYCODE_LIST|VK_LIST|BIT_LIST|RESOLVER_HEADER)\b",
                                      source)))
    if leftovers:
        raise SystemExit("the fixture still carries unreplaced placeholders: %s" % leftovers)
    return source


def toolchain():
    """The compiler and SDK, as one matched pair. See scripts/apple_toolchain.py."""
    return apple_toolchain.clang_and_sdk("modifier mapping probe")


def build_and_run(work, name, source):
    binary = os.path.join(work, name)
    clang, sdk = toolchain()
    built = subprocess.run([clang, "-fobjc-arc", "-O1", "-isysroot", sdk,
                            "-framework", "AppKit", "-framework", "Foundation",
                            "-o", binary,
                            "-x", "objective-c", "-"],
                           input=source, text=True, capture_output=True, cwd=ROOT)
    if built.returncode != 0:
        sys.stderr.write("the modifier mapping probe did not compile:\n%s\n%s\n"
                         % (built.stdout, built.stderr))
        raise SystemExit(1)
    return subprocess.run([binary], capture_output=True, text=True)


def main():
    argv = sys.argv[1:]
    base = assemble()
    for variant in ("both-sides-left", "flags-mix-sides"):
        if assemble(variant) == base:
            # A variant that changes nothing is not a planted regression: it runs the
            # scenarios on the shipped code, passes them, and the harness reports that
            # the scenarios have teeth when they have none.
            raise SystemExit("the %s variant produced the shipped source unchanged, so "
                             "the anchor it plants is no longer in KeyboardMapResolver.m"
                             % variant)
    print("ok   both planted variants differ from the shipped source (they are real edits)")
    print("ok   the shipped table, the keycode switch and the flags path were compiled "
          "from KeyboardMapResolver.m")

    if "--preflight" in argv:
        print("0 modifier mapping failures (preflight only: extraction, no assertions run)")
        return 0

    failures = []
    with tempfile.TemporaryDirectory() as work:
        run = build_and_run(work, "modifier-mapping", assemble())
        sys.stdout.write(run.stdout)
        sys.stderr.write(run.stderr)
        if run.returncode != 0:
            failures.append("the shipped mapping failed a scenario")

        for variant, why in (("both-sides-left",
                              "both hands of a modifier answering as the left hand"),
                             ("flags-mix-sides",
                              "the flags path answering Command with Alt")):
            broken = build_and_run(work, "variant-" + variant, assemble(variant))
            if broken.returncode == 0:
                print("FAIL the variant where %s passed the scenarios, so the scenarios "
                      "cannot detect it" % why)
                failures.append(variant)
            else:
                print("ok   the variant where %s is refused (the scenarios have teeth)" % why)

    print("%d modifier mapping failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
