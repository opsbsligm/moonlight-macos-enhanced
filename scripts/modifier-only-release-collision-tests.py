#!/usr/bin/env python3
"""Prove that a key press cannot cancel a pending modifier-only mouse release.

The escape hatch is `Ctrl+Option` held alone: after 150 ms the app releases every
modifier on the host, uncaptures the mouse and mutes connection warnings for two
seconds. The schedule condition is "the relevant modifiers are exactly Ctrl+Option"
and the expiry condition is the same test again, and nothing in between asks
whether the player has pressed a key in the meantime -- because a letter key does
not change the modifier flags at all.

That shape collides with the shipped default shortcut table, which puts six keyed
actions behind the very same modifier set (Ctrl+Option+S overlay, M mouse mode,
G control ball, W disconnect, R reconnect, C control centre). Press Ctrl+Option+S
to check the frame rate and the schedule taken while the modifiers came down is
still standing at the 150 ms mark: `currentMods` still reads Ctrl+Option, so the
overlay toggles *and* the mouse leaves the game and the host is told every
modifier came up, which is the "I pressed a shortcut and my held keys let go"
report in full.

The harness does not paraphrase that. It lifts three facts out of the shipping
source -- the schedule condition, the expiry condition, and which message
invalidates the pending token -- compiles them into one timeline machine, and runs
two orders of the same physical gesture: modifiers then key, and modifiers alone.
The first must not release anything. Then the fix is removed from the model and
the release has to come back, because a timeline test that cannot fail is a
comment.

Exit 0 only when the shipped source still carries the pieces this reads.
"""
import os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers",
                      "StreamViewController+MouseCapture.m")

MOD_SHIFT, MOD_CONTROL, MOD_OPTION, MOD_COMMAND = 1, 2, 4, 8
RELEASE_MODS = MOD_CONTROL | MOD_OPTION  # the shipped default: Ctrl+Option


def source_text():
    with open(SOURCE, encoding="utf-8") as handle:
        return handle.read()


def method_body(text, signature):
    """The body of one Objective-C method, matched by brace depth."""
    start = text.index(signature)
    brace = text.index("{", start)
    depth, index = 0, brace
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[brace:index + 1]
        index += 1
    raise SystemExit("%s has no closing brace, so this harness cannot read it" % signature)


def shipped_facts():
    """Three things this test refuses to guess at."""
    text = source_text()
    flags = method_body(text, "- (void)flagsChanged:(NSEvent *)event")
    key_down = method_body(text, "- (void)keyDown:(NSEvent *)event")

    schedule = re.search(r"releaseShortcut\.modifierOnly\s*&&\s*relevantMods\s*==\s*releaseShortcut\.modifierFlags",
                         flags)
    expiry = re.search(r"currentMods\s*!=\s*releaseShortcut\.modifierFlags", flags)
    if schedule is None or expiry is None:
        raise SystemExit("the modifier-only schedule or its expiry test is no longer in "
                         "flagsChanged:, so this harness is testing something that moved")

    # A pending release is cancelled by bumping the token. Whatever still bumps it
    # from a key press is what keeps the shortcut table from colliding with it.
    invalidates_on_key = "pendingOptionUncaptureToken" in key_down
    return {"invalidates_on_key": invalidates_on_key}


PROLOGUE = r"""
typedef struct { unsigned mods; int token; int pending; int released_modifiers;
                 int uncaptured_mouse; int pressed_a_key; } machine;

static void schedule(machine *m, unsigned new_mods) {
    m->mods = new_mods;
    /* The shipped schedule condition, read from flagsChanged:. */
    if (RELEASE_MODS == m->mods) {
        m->token += 1;
        m->pending = m->token;
    } else {
        m->token += 1;
    }
}

static void press_key(machine *m) {
    m->pressed_a_key = 1;
    /* A letter key does not change the modifier flags, so the only thing that can
       stand between "held Ctrl+Option" and the timer is this line. */
    if (INVALIDATES_ON_KEY) {
        m->token += 1;
    }
}

static void timer(machine *m) {
    if (m->pending != m->token) {
        return;
    }
    /* The shipped expiry condition, read from the same dispatch_after block. */
    if (RELEASE_MODS != m->mods) {
        return;
    }
    m->released_modifiers = 1;
    m->uncaptured_mouse = 1;
}

static void run(machine *m, int with_key) {
    schedule(m, MOD_CONTROL);                 /* Ctrl comes down            */
    schedule(m, MOD_CONTROL | MOD_OPTION);    /* Option comes down: schedule */
    if (with_key) {
        press_key(m);                         /* S arrives within 150 ms      */
    }
    timer(m);                                 /* and the 150 ms elapses      */
}
"""

TEST_BODY = r"""
int main(void) {
    machine with_key = {0}, alone = {0};
    int failures = 0;

    run(&with_key, 1);
    if (with_key.released_modifiers || with_key.uncaptured_mouse) {
        failures += 1;
        printf("FAIL a shortcut behind the same modifier set released the held "
               "modifiers and uncaptured the mouse\n");
    }
    if (!with_key.pressed_a_key) {
        failures += 1;
        printf("FAIL the timeline never pressed a key, so it proved nothing\n");
    }

    /* The escape hatch itself has to stay: modifiers alone, no key, must still
       uncapture. A fix that only silences the release is a regression of the
       feature this guard protects. */
    run(&alone, 0);
    if (!alone.released_modifiers || !alone.uncaptured_mouse) {
        failures += 1;
        printf("FAIL holding only Ctrl+Option stopped releasing the mouse capture\n");
    }

    printf("%s\n", failures ? "scenarios failed" : "all scenarios passed");
    return failures;
}
"""


def build_and_run(invalidates_on_key, directory):
    header = ("#include <stdio.h>\n"
              "#define MOD_SHIFT %d\n#define MOD_CONTROL %d\n"
              "#define MOD_OPTION %d\n#define MOD_COMMAND %d\n"
              "#define RELEASE_MODS (%d)\n"
              % (MOD_SHIFT, MOD_CONTROL, MOD_OPTION, MOD_COMMAND, RELEASE_MODS))
    source = (header
              + PROLOGUE.replace("INVALIDATES_ON_KEY", "1" if invalidates_on_key else "0")
              + TEST_BODY)
    path = os.path.join(directory, "timeline.c")
    binary = os.path.join(directory, "timeline")
    with open(path, "w") as handle:
        handle.write(source)
    import apple_toolchain
    clang, sdk = apple_toolchain.clang_and_sdk("the modifier-only timeline")
    compiled = subprocess.run([clang, "-isysroot", sdk, "-Wall", "-Werror",
                               path, "-o", binary], capture_output=True, text=True)
    if compiled.returncode != 0:
        raise SystemExit("the timeline model does not compile:\n" + compiled.stderr)
    ran = subprocess.run([binary], capture_output=True, text=True)
    return ran.returncode, (ran.stdout + ran.stderr).strip()


def main():
    facts = shipped_facts()
    if not facts["invalidates_on_key"]:
        print("the shipped -keyDown: does not invalidate a pending modifier-only release")
    with tempfile.TemporaryDirectory() as workspace:
        code, output = build_and_run(True, workspace)
        if code != 0:
            print("FAIL the guarded timeline still collides:\n%s" % output)
            return 1
        print("ok a key pressed within the window cancels the pending release")

        # And the other half of the guarantee: the guard is what cancels it, so
        # taking it away has to bring the collision back.
        code, output = build_and_run(False, workspace)
        if code == 0:
            print("FAIL the timeline passes with the guard removed, so it cannot "
                  "notice the collision it exists to notice")
            return 1
        print("ok removing the guard brings the collision back (%s)" % output.splitlines()[0])

    if not facts["invalidates_on_key"]:
        print("the shipped source is missing the guard this timeline requires")
        return 1
    print("shipped source carries the guard, and the timeline proves what it prevents")
    return 0


if __name__ == "__main__":
    sys.exit(main())
