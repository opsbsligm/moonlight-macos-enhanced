#!/usr/bin/env python3
"""Prove a movement key held across a Space change reaches the host as a release.

Two release methods exist and they release different things.
`-releaseAllModifierKeys` sends eight KEY_ACTION_UP packets -- 0x5B, 0x5C and
0xA0 through 0xA5 -- and nothing else, so it clears Shift, Ctrl, Alt and Win.
`-releaseAllHeldKeys` walks the keys the player forwarded and are still pressed
and releases those: W, Space, everything that moves a character. Session
teardown calls both, in that order, and the mouse-uncapture path calls the
held-key one, with a comment explaining exactly why: input forwarding switches
off after that point, so a key held at uncapture would never reach the host as a
release.

The active-Space decision has a branch where that reasoning was not applied.
When the window is not in the current Space during a fullscreen transition it
deliberately skips the uncapture -- which is right, the window is coming back --
and then releases *only the modifiers*, hiding the edge menu and leaving every
ordinary key pressed on the host. Holding W while Space switches, which is the
normal way to enter or leave the fullscreen Space, leaves the character walking
forever, and no `keyUp:` can arrive afterwards because the window is not on the
Space receiving events.

The harness reads four facts out of the shipping source rather than trusting this
description: which keys each release method actually sends, whether the uncapture
path still releases held keys, and whether the not-in-current-Space branch does.
It models one host that remembers what is pressed, runs the gesture both ways,
and then removes the fix from the model to make sure the stuck key comes back.

Exit 0 only when the shipped source still contains every piece this reads.
"""
import os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
SVC = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers", "StreamViewController.m")
HID = os.path.join(ROOT, "Limelight", "Input", "HIDSupport.m")
CAPTURE = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers",
                       "StreamViewController+MouseCapture.m")
VK_W, VK_SPACE = 0x57, 0x20
MODIFIER_VKS = (0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5)


def text_of(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def method_body(text, signature, where):
    if signature not in text:
        raise SystemExit("%s is no longer in %s, so this harness cannot read it"
                         % (signature, os.path.basename(where)))
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
    raise SystemExit("%s in %s never closes" % (signature, os.path.basename(where)))


def observer_block(text, notification):
    """The body of one notification observer, matched by brace depth.

    The active-Space decision is not a method: it is a block handed to
    `-[NSWorkspace notificationCenter]`, so brace matching has to start at the
    `usingBlock:` rather than at a `- (void)` signature.
    """
    if notification not in text:
        raise SystemExit("%s is no longer observed here, so this harness cannot read "
                         "the decision it guards" % notification)
    start = text.index(notification)
    marker = "usingBlock:^(NSNotification *note) {"
    brace = text.index(marker, start) + len(marker) - 1
    depth, index = 0, brace
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[brace:index + 1]
        index += 1
    raise SystemExit("the %s observer never closes" % notification)


def shipped_facts():
    """Four things this test refuses to guess at."""
    hid = text_of(HID)
    modifiers_only = method_body(hid, "- (void)releaseAllModifierKeys", HID)
    held = method_body(hid, "- (void)releaseAllHeldKeys", HID)

    released_modifiers = {int(h, 16) for h in re.findall(r"0x([0-9A-Fa-f]{2}),\s*KEY_ACTION_UP",
                                                         modifiers_only)}
    if released_modifiers != set(MODIFIER_VKS):
        raise SystemExit("releaseAllModifierKeys now sends %s, which this model does not "
                         "represent; update the model rather than the assertion"
                         % sorted(hex(v) for v in released_modifiers))
    # The point of the split: the modifier release cannot be the answer to an
    # ordinary key, because it has no ordinary key in it.
    for vk in (VK_W, VK_SPACE):
        if vk in released_modifiers:
            raise SystemExit("releaseAllModifierKeys releases %#x, so the split this test "
                             "guards has changed shape" % vk)
    if "keyboardForwardedKeyDownKeyCodes" not in held:
        raise SystemExit("releaseAllHeldKeys no longer walks the forwarded key records")

    uncapture = method_body(text_of(CAPTURE), "- (void)uncaptureMouseWithCode:(NSString *)code",
                            CAPTURE)
    space = observer_block(text_of(SVC), "NSWorkspaceActiveSpaceDidChangeNotification")

    return {
        "uncapture_releases_held_keys": "releaseAllHeldKeys" in uncapture,
        "space_branch_releases_held_keys": re.search(
            r"if\s*\(\s*!windowInCurrentSpace\s*\)\s*\{[^}]*releaseAllHeldKeys", space) is not None,
        "space_branch_releases_modifiers": re.search(
            r"if\s*\(\s*!windowInCurrentSpace\s*\)\s*\{[^}]*releaseAllModifierKeys", space) is not None,
    }


PROLOGUE = r"""
typedef struct { unsigned long pressed_ordinary; unsigned char pressed_modifiers;
                 int released_ordinary; int released_modifiers; } host;

static void host_press_ordinary(host *h, int vk) { h->pressed_ordinary |= (1UL << vk); }
static void host_press_modifier(host *h, int bit) { h->pressed_modifiers |= (unsigned char)bit; }

/* Both of these are read from HIDSupport.m: the modifier release is eight fixed
   VK packets, the held-key release is whatever records are still open. */
static void host_release_all_modifiers(host *h) {
    h->pressed_modifiers = 0;
    h->released_modifiers = 1;
}

static void host_release_all_held_keys(host *h) {
    h->pressed_ordinary = 0;
    h->released_ordinary = 1;
}

/* The shipped decision, including the uncapture's own held-key release. */
static void active_space_changed(host *h, int app_active, int window_key, int window_main,
                                 int in_current_space, int fullscreen_transition) {
    int uncaptured = 0;
    int should_release = (!app_active || !window_key || !window_main ||
                          (!in_current_space && !fullscreen_transition));
    if (should_release) {
        host_release_all_modifiers(h);
        uncaptured = 1;                      /* requestMouseUncaptureWhenSafe: */
    }
    if (!in_current_space) {
        if (RELEASE_HELD_IN_SPACE_BRANCH) {
            host_release_all_held_keys(h);
        }
        host_release_all_modifiers(h);
    }
    if (uncaptured && UNCATURE_RELEASES_HELD_KEYS) {
        host_release_all_held_keys(h);
    }
}
"""

TEST_BODY = r"""
static int gFailed = 0;

static void expect(int ok, const char *message) {
    if (!ok) {
        gFailed += 1;
        printf("FAIL %s\n", message);
    }
}

int main(void) {
    /* The reported gesture: walking (W) while the Space changes underneath, with
       the window deliberately left off the current Space during a fullscreen
       transition -- the one combination where the decision skips the uncapture. */
    host switching = {0};
    host_press_ordinary(&switching, VK_W);
    host_press_ordinary(&switching, VK_SPACE);
    host_press_modifier(&switching, 1);
    active_space_changed(&switching, 1, 1, 1, 0, 1);
    expect(switching.pressed_ordinary == 0,
           "a key held across the Space change is still pressed on the host afterwards");
    expect(switching.pressed_modifiers == 0,
           "a modifier held across the Space change is still pressed on the host afterwards");

    /* The guarantee that already holds must keep holding: the uncapture path
       releases keys before input forwarding goes away. */
    host uncaptured = {0};
    host_press_ordinary(&uncaptured, VK_W);
    active_space_changed(&uncaptured, 0, 1, 1, 1, 0);
    expect(uncaptured.released_ordinary == 1,
           "the mouse uncapture stopped releasing the keys the host still thinks are held");

    /* And a Space change where nothing was held still has to be a no-op rather
       than an accident: nothing pressed, nothing left pressed. */
    host idle = {0};
    active_space_changed(&idle, 1, 1, 1, 1, 0);
    expect(idle.pressed_ordinary == 0 && idle.pressed_modifiers == 0,
           "an idle Space change somehow pressed something");

    printf("%s\n", gFailed ? "scenarios failed" : "all scenarios passed");
    return gFailed;
}
"""


def build_and_run(space_branch_releases, directory):
    header = ("#include <stdio.h>\n"
              "#define VK_W %d\n#define VK_SPACE %d\n"
              "#define RELEASE_HELD_IN_SPACE_BRANCH %d\n"
              "#define UNCATURE_RELEASES_HELD_KEYS %d\n"
              % (VK_W, VK_SPACE, 1 if space_branch_releases else 0, 1))
    source = header + PROLOGUE + TEST_BODY
    path = os.path.join(directory, "space_keys.c")
    binary = os.path.join(directory, "space_keys")
    with open(path, "w") as handle:
        handle.write(source)
    import apple_toolchain
    clang, sdk = apple_toolchain.clang_and_sdk("the active-Space held-key timeline")
    compiled = subprocess.run([clang, "-isysroot", sdk, "-Wall", "-Werror",
                               path, "-o", binary], capture_output=True, text=True)
    if compiled.returncode != 0:
        raise SystemExit("the host model does not compile:\n" + compiled.stderr)
    ran = subprocess.run([binary], capture_output=True, text=True)
    return ran.returncode, (ran.stdout + ran.stderr).strip()


def main():
    facts = shipped_facts()
    if not facts["uncapture_releases_held_keys"]:
        print("the shipped mouse uncapture no longer releases held keys")
    if not facts["space_branch_releases_modifiers"]:
        print("the not-in-current-Space branch no longer releases modifiers, so this "
              "harness is guarding a branch that moved")

    with tempfile.TemporaryDirectory() as workspace:
        code, output = build_and_run(True, workspace)
        if code != 0:
            print("FAIL the model still sticks a key with the fix in place:\n%s" % output)
            return 1
        print("ok a key held across the Space change reaches the host as a release")

        code, output = build_and_run(False, workspace)
        if code == 0:
            print("FAIL the model passes with the release removed, so it cannot notice "
                  "the stuck key it exists to notice")
            return 1
        print("ok removing it leaves the key pressed (%s)" % output.splitlines()[0])

    if not facts["space_branch_releases_held_keys"] or not facts["uncapture_releases_held_keys"]:
        print("the shipped source is missing a held-key release this model requires")
        return 1
    print("shipped source releases both kinds of key on both paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
