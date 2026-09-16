#!/usr/bin/env python3
"""Prove that the keyboard-constraint assertions fail when the code regresses.

An assertion that only looks for words passes on code that no longer behaves,
so every guard we rely on has to be broken on purpose at least once and shown
to be caught. Each mutation below is a realistic regression: the words stay in
place while the behaviour is gone.

Usage: assertion-battery.py [--keep-broken <name>]
Exit 0 only when every mutation is caught by constraints-audit.py.
"""
import os
import re
import subprocess
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HID = os.path.join(root, "Limelight", "Input", "HIDSupport.m")
HID_INTERNAL = os.path.join(root, "Limelight", "Input", "HIDSupport_Internal.h")
POINTER_FILE = os.path.join(root, "Limelight", "Input", "HIDSupport+Pointer.m")
STREAM_SVC = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                          "StreamViewController.m")
CAPTURE = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                       "StreamViewController+MouseCapture.m")
MENU = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                    "StreamViewController+MenuUI.m")
DIAGNOSTICS = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                           "StreamViewController+Diagnostics.m")
APPDELEGATE = os.path.join(root, "Limelight", "macOS", "AppDelegateForAppKit.m")
SHORTCUTS = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                         "SettingsShortcuts.swift")
DERIVED = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                       "SettingsModel+DerivedValues.swift")
L10N = os.path.join(root, "scripts", "l10n-audit.py")
ANALYZER = os.path.join(root, "scripts", "analyzer-audit.py")
COLLECTION_VIEW = os.path.join(root, "Limelight", "macOS", "Views", "CollectionView.m")
APP_CELL = os.path.join(root, "Limelight", "macOS", "ViewControllers", "AppCell.m")
PREPARER = os.path.join(root, "scripts", "prepare-release.py")
BUILD_SH = os.path.join(root, "Limelight", "build-number.sh")
WORKFLOW = os.path.join(root, ".github", "workflows", "build.yml")
CHANGELOG = os.path.join(root, "CHANGELOG.md")
FETCHER = os.path.join(root, "scripts", "download-frameworks.sh")
AUDIT = os.path.join(root, "scripts", "constraints-audit.py")
TOOLCHAIN = os.path.join(root, "scripts", "apple_toolchain.py")
INTERNAL = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                        "StreamViewController_Internal.h")
WINDOW_MODES = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                             "StreamViewController+WindowModes.m")
VIDEO_RULES = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                      "SettingsModel+VideoPageRules.swift")
PBXPROJ = os.path.join(root, "Moonlight.xcodeproj", "project.pbxproj")
VIDEO_RENDERER = os.path.join(root, "Limelight", "Stream", "VideoDecoderRenderer.m")
NAVIGATION = os.path.join(root, "Limelight", "macOS", "Views", "NavigatableAlertView.m")
RENDER_PROBE = os.path.join(root, "scripts", "render-probe.py")


# A mutation is judged by the gate that is supposed to notice it. Both gates run an
# extra proof of their own when invoked normally, so the battery has to tell the
# gate it is asking not to ask back.
# The default gate is the aggregate without the battery, so a mutation owned by a
# behavioural harness has to name that harness: the aggregate's full pass is where
# harnesses run, and asking for it here would run the battery inside the battery.
AUDIT_GATE = (os.path.join(root, "scripts", "constraints-audit.py"), ["--no-battery"])
# The localization gate has no opt-out: its self-test is part of the gate.
L10N_GATE = (L10N, [])
ANALYZER_GATE = (ANALYZER, ["--self-test"])
# The synthetic-shortcut gate is its own harness: it compiles the state machine, so
# only it can see a packet sequence that strands the modifier tracker.
SHORTCUT_GATE = (os.path.join(root, "scripts", "keyboard-shortcut-modifier-tests.py"), [])
COLLISION_GATE = (os.path.join(root, "scripts", "modifier-only-release-collision-tests.py"), [])
SPACE_HELD_GATE = (os.path.join(root, "scripts", "space-transition-held-key-tests.py"), [])
NAVIGATION_GATE = (os.path.join(root, "scripts", "controller-key-navigation-tests.py"), [])
VIDEO_GATE = (os.path.join(root, "scripts", "video-enhancement-tests.py"), [])
# The workflow audit reads the pipeline that runs every other gate, so a mutation of
# the pipeline itself is judged by it and by nothing else.
WF_GATE = (os.path.join(root, "scripts", "workflow-audit.py"), [])
# Both SDK-shaped mutations are judged by the aggregate rather than by
# scripts/compile-audit.py itself: the audit runner has no Apple toolchain, a gate that
# has to skip answers "I cannot tell", and the battery would read that as a mutation
# that slipped through. compile-audit is still run for real -- by the aggregate and by
# the CI analyze job -- and it proves its own two directions with --self-test.
# The glass ratchet is a source rule, so a reverted panel is visible to it.
LIQUID_GATE = (os.path.join(root, "scripts", "liquid-glass-audit.py"), [])
# And this is the runtime half of the same rule: the container is compiled and run, so a
# behaviour inside it -- an answer that never reaches the glass -- is visible here and
# nowhere in a source scan.
OVERLAY_GATE = (os.path.join(root, "scripts", "liquid-glass-overlay-tests.py"), [])
# The release preparer's own self-test, reached through the gate that CI already
# runs: `--self-test` on release-gate.py executes the preparation fixtures too, so a
# preparer whose release procedure has gone wrong cannot leave the audit green.
PREP_GATE = (os.path.join(root, "scripts", "release-gate.py"), ["--self-test"])
# The notch consumer is judged by the harness that lifts it out of the header and
# runs it, since the behaviour lives in an inline function the app never calls on a
# testable path here.
NOTCH_GATE = (os.path.join(root, "scripts", "scroll-notch-consumption-tests.py"), [])
GAIN_GATE = (os.path.join(root, "scripts", "relative-pointer-gain-tests.py"), [])
# The notch count a packet answers with lives in the same header, and the
# harness that judges it compiles the function out and runs it, because no
# test path in the app reaches the quantized branch.
CLICK_GATE = (os.path.join(root, "scripts", "discrete-scroll-click-tests.py"), [])
# The stick-driven pointer is judged by the harness that runs the shared
# normaliser and the drain the shipping sequence uses, and that also reads the
# call site, because the defect was in how the frame was answered.
EMULATION_GATE = (os.path.join(root, "scripts",
                            "controller-mouse-emulation-tests.py"), [])
SHORTCUT_PROFILE = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                                 "SettingsShortcuts.swift")
MOUSE_CAPTURE = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                             "StreamViewController+MouseCapture.m")
GLASS_CONTAINER = os.path.join(root, "Limelight", "macOS", "Views",
                               "GlassOverlayContainer.m")
VIDEO_PANE = os.path.join(root, "Limelight", "macOS", "ViewControllers",
                          "SettingsVideoPane.swift")

UP_GUARD = """        if ([self.keyboardSuppressedKeyDownKeyCodes containsObject:physicalKeyCode]) {
            // The host never saw this key go down, so it must not see it come up
            // either: an unmatched release reads as the key being let go by
            // itself, which is what made local shortcuts look like gameplay keys
            // releasing mid-action.
            [self.keyboardSuppressedKeyDownKeyCodes removeObject:physicalKeyCode];
            return;
        }
"""
UP_DISPATCH = """        HIDDispatchInput(self, inputCtx, ^{
            LiSendKeyboardEventCtx(inputCtx, keyCode, KEY_ACTION_UP, modifiers);
        });
"""
DOWN_CLEAR = """        [self.keyboardSuppressedKeyDownKeyCodes removeObject:@(event.keyCode)];
"""
DOWN_DISPATCH = """        HIDDispatchInput(self, inputCtx, ^{
            LiSendKeyboardEventCtx(inputCtx, keyCode, KEY_ACTION_DOWN, modifiers);
        });
"""


def once(text, needle, where):
    if text.count(needle) != 1:
        raise SystemExit("anchor found %d times, expected 1: %s in %s"
                         % (text.count(needle), where, os.path.basename(needle[:40])))
    return text


def replace_nth(text, needle, repl, position, where):
    """Replace only the nth occurrence, for anchors that appear once per edge."""
    index, seen = -1, 0
    while True:
        index = text.find(needle, index + 1)
        if index == -1:
            raise SystemExit("anchor found %d times, expected >= %d: %s"
                             % (seen, position, where))
        seen += 1
        if seen == position:
            return text[:index] + repl + text[index + len(needle):]


def neuter_if(text):
    return once(text, UP_GUARD, "keyUp guard").replace(
        "if ([self.keyboardSuppressedKeyDownKeyCodes containsObject:physicalKeyCode]) {",
        "if (NO && [self.keyboardSuppressedKeyDownKeyCodes containsObject:physicalKeyCode]) {", 1)


def no_return(text):
    once(text, UP_GUARD, "keyUp guard")
    return text.replace(
        "[self.keyboardSuppressedKeyDownKeyCodes removeObject:physicalKeyCode];\n            return;",
        "[self.keyboardSuppressedKeyDownKeyCodes removeObject:physicalKeyCode];", 1)


def drop_release(text):
    once(text, UP_GUARD, "keyUp guard")
    return text.replace(
        "            [self.keyboardSuppressedKeyDownKeyCodes removeObject:physicalKeyCode];\n            return;\n",
        "            return;\n", 1)


def late_guard(text):
    once(text, UP_GUARD, "keyUp guard")
    once(text, UP_DISPATCH, "keyUp dispatch")
    rest = text.replace(UP_GUARD, "", 1)
    return rest.replace(UP_DISPATCH, UP_DISPATCH + "\n" + UP_GUARD.rstrip("\n") + "\n", 1)


def commented_guard(text):
    once(text, UP_GUARD, "keyUp guard")
    return text.replace(UP_GUARD, "".join("//" + line + "\n" for line in
                                          UP_GUARD.rstrip("\n").split("\n")), 1)


def neuter_settings(text):
    return once(text, "if ([SettingsWindowObjCBridge isSettingsPresentedInWindow:self.view.window]) {",
                "settings guard").replace(
        "if ([SettingsWindowObjCBridge isSettingsPresentedInWindow:self.view.window]) {",
        "if (NO && [SettingsWindowObjCBridge isSettingsPresentedInWindow:self.view.window]) {", 1)


def late_clear(text):
    once(text, DOWN_CLEAR, "keyDown clear")
    once(text, DOWN_DISPATCH, "keyDown dispatch")
    rest = text.replace(DOWN_CLEAR, "", 1)
    return rest.replace(DOWN_DISPATCH, DOWN_DISPATCH + DOWN_CLEAR, 1)


DOWN_DISPATCH = """        HIDDispatchInput(self, inputCtx, ^{
            LiSendKeyboardEventCtx(inputCtx, keyCode, KEY_ACTION_DOWN, modifiers);
        });
"""
REC = """        [self.keyboardForwardedKeyDownKeyCodes addObject:@(keyCode)];
"""
INIT = """        self.keyboardForwardedKeyDownKeyCodes = [NSMutableSet set];
"""
CLEAR = """    [self.keyboardForwardedKeyDownKeyCodes removeAllObjects];
"""
TEARDOWN = """    // 0) Release keys the host still believes are pressed, before input is
    //    switched off, so an action key held at disconnect cannot stay stuck.
    [self releaseAllHeldKeys];
"""
UNCAPTURE_CALL = """    [self.hidSupport releaseAllHeldKeys];
"""
UNCAPTURE_OFF = """    self.hidSupport.shouldSendInputEvents = NO;
"""


def no_record(text):
    once(text, REC, "held-key record")
    return text.replace(REC, "", 1)


def late_record(text):
    once(text, REC, "held-key record")
    once(text, DOWN_DISPATCH, "keyDown dispatch")
    rest = text.replace(REC, "", 1)
    return rest.replace(DOWN_DISPATCH, DOWN_DISPATCH + REC, 1)


def no_init(text):
    once(text, INIT, "held-key record init")
    return text.replace(INIT, "", 1)


def leak_records(text):
    once(text, CLEAR, "held-key release")
    return text.replace(CLEAR, "", 1)


def drop_teardown_release(text):
    once(text, TEARDOWN, "session teardown")
    return text.replace(TEARDOWN, "", 1)


def drop_uncapture_release(text):
    once(text, UNCAPTURE_CALL, "capture release")
    return text.replace(UNCAPTURE_CALL, "", 1)


def late_uncapture_release(text):
    once(text, UNCAPTURE_CALL, "capture release")
    once(text, UNCAPTURE_OFF, "input switch off")
    rest = text.replace(UNCAPTURE_CALL, "", 1)
    return rest.replace(UNCAPTURE_OFF, UNCAPTURE_OFF + UNCAPTURE_CALL, 1)



FLOOR = "    return modifierCount(relevantModifierFlags(shortcut.modifierFlags)) >= 1\n"
MENU_GATE = "    if (![StreamShortcutProfile shortcutCanMatchKeyboardEvent:shortcut]) {\n"
RULE_GATE = "        if (![StreamShortcutProfile shortcutCanMatchKeyboardEvent:trigger]) {\n"
MENU_EQUIV = "    guard StreamShortcutProfile.shortcutCanMatchKeyboardEvent(shortcut),\n"


def bare_predicate(text):
    once(text, FLOOR, "modifier floor")
    return text.replace(FLOOR, FLOOR.replace(">= 1", ">= 0"), 1)


def bare_menu_gate(text):
    once(text, MENU_GATE, "responder gate")
    return text.replace(MENU_GATE,
                        MENU_GATE.replace("if (![", "if (NO && !["), 1)


def bare_rule_gate(text):
    once(text, RULE_GATE, "translation matcher")
    return text.replace(RULE_GATE,
                        RULE_GATE.replace("if (![", "if (NO && !["), 1)


def bare_menu_equivalent(text):
    once(text, MENU_EQUIV, "menu key equivalent")
    return text.replace(MENU_EQUIV, "    guard true,\n", 1)



MFX_QUERY = "      return MTLFXSpatialScalerDescriptor.supportsDevice(device)\n"
FI_DECISION = "      return slots >= 1 ? .available : .unavailable\n"
SR_GUARD = "      guard !factors.isEmpty else { return .unavailable }\n"
FI_TOGGLE = """  var frameInterpolationIsCapable: Bool {
    videoCapabilityMatrix.items.first(where: { $0.id == \"enhancement.vtLowLatencyFI\" })?
      .availability == .available
  }"""


def unmeasured_mfx(text):
    once(text, MFX_QUERY, "MetalFX query")
    return text.replace(MFX_QUERY, "      return true\n", 1)


def unmeasured_interpolation(text):
    once(text, FI_DECISION, "interpolation decision")
    return text.replace(FI_DECISION, "      return .available\n", 1)


def unmeasured_scaler(text):
    once(text, SR_GUARD, "scaler guard")
    return text.replace(SR_GUARD, "      _ = factors\n", 1)


def constant_toggle(text):
    """Make the interpolation gate believe the GPU can always interpolate.

    The rule lives on the model now, because the page and the thing that checks the
    page have to be measured against one answer. Breaking it here breaks both.
    """
    once(text, FI_TOGGLE, "interpolation toggle gate")
    return text.replace(FI_TOGGLE, """  var frameInterpolationIsCapable: Bool {
    return true
  }""", 1)



UNMAPPED_GUARD = "        if (translated == 0) {\n"
SPACE_ROW = "    {kVK_Space, 0x20},\n"
ISO_ROW = "    {kVK_ISO_Section, 0xE2},\n"
JIS_ROW = "    {kVK_JIS_Yen, 0x7D},\n"
W_ROW = "    {kVK_ANSI_W, 'W'},\n"


def unmapped_press(text):
    return replace_nth(text, UNMAPPED_GUARD,
                       "        if (NO && translated == 0) {\n", 1, "keyDown zero guard")


def unmapped_release(text):
    return replace_nth(text, UNMAPPED_GUARD,
                       "        if (NO && translated == 0) {\n", 2, "keyUp zero guard")


def drop_space_row(text):
    once(text, SPACE_ROW, "space mapping")
    return text.replace(SPACE_ROW, "", 1)


def undocumented_mapping(text):
    once(text, ISO_ROW, "ISO section mapping")
    return text.replace(ISO_ROW, JIS_ROW + ISO_ROW, 1)


def duplicate_w_row(text):
    once(text, W_ROW, "W mapping")
    return text.replace(W_ROW, W_ROW + W_ROW, 1)



SCAN_HEALTH = "def scan_health(keys_found, tokens_present):\n"
# Built from single characters so no layer of quoting can eat a metacharacter:
# AT_TOLERANT is the backslash-paren-question-quote the audit compiles, and
# AT_BLIND is the same pattern with the at-sign branch removed.
AT_TOLERANT = chr(92) + "(?@?" + chr(34)
AT_BLIND = chr(92) + "(?" + chr(34)
IMPORTS = "import io, os, re, sys\n"


def blind_scan_health(text):
    once(text, SCAN_HEALTH, "scan health rule")
    return text.replace(SCAN_HEALTH, SCAN_HEALTH + "    return None\n", 1)


def at_blind_scan(text):
    once(text, AT_TOLERANT, "at-quoted call pattern")
    return text.replace(AT_TOLERANT, AT_BLIND, 1)


def grep_scanned(text):
    once(text, IMPORTS, "localization imports")
    return text.replace(IMPORTS, "import io, os, re, subprocess, sys\n", 1)



EVENT_RELEASE = "    CFRelease(cgEvent);\n"
PATH_ANNOTATION = " CF_RETURNS_RETAINED {"
HID_RELEASE = "        CFRelease(_hidManager);\n"
SWEEP_RULE = "def sweep_health(analyzed, source_count, scan_root=\".\"):\n"
ADDED_RULE = "if key not in baseline"
BUILD_VIA_SCRIPT = "else str(build_number())"
TEARDOWN_BEFORE_STOP = '    [self.hidSupport tearDownKeyboardStateForSessionEnd:"performCloseStreamWindow"];\n'
KEYBOARD_STEP = "      run: python3 scripts/keyboard-concurrency-tests.py\n"
SHALLOW_GUARD = r'''if [ "${1:-}" = "--print" ] && \
   [ "$("$git" rev-parse --is-shallow-repository 2>/dev/null)" = "true" ]; then
    echo "error: $PWD is a shallow clone, so rev-list --count HEAD reports $bundleVersion instead of the real total; run: git fetch --unshallow" >&2
    exit 1
fi
'''


def leak_the_key_event(text):
    once(text, EVENT_RELEASE, "key event release")
    return text.replace(EVENT_RELEASE, "", 1)


def unowned_path_helper(text):
    once(text, PATH_ANNOTATION, "path ownership annotation")
    return text.replace(PATH_ANNOTATION, " {", 1)


def hid_manager_outlives(text):
    once(text, HID_RELEASE, "HID manager release")
    return text.replace(HID_RELEASE, "", 1)


def blind_sweep(text):
    once(text, SWEEP_RULE, "sweep health rule")
    return text.replace(SWEEP_RULE, SWEEP_RULE + "    return None\n", 1)


def accept_new_findings(text):
    once(text, ADDED_RULE, "new finding rule")
    return text.replace(ADDED_RULE, "if False", 1)



def recounted_build(text):
    once(text, BUILD_VIA_SCRIPT, "build number asked of the shared script")
    return text.replace(BUILD_VIA_SCRIPT,
                        'else git("rev-list", "--count", "HEAD").strip()', 1)


# A cleared promotion used to end with "the gate accepts the tag". That is true of
# the working tree and false about the release, because the next thing a person does
# is commit: BUILD_NUMBER counts that commit, so the section just written names a
# build one too low, and every further commit moves the target again. The sentence
# telling them to amend is the only thing preventing the loop, so it is an assertion.
AMEND_ADVICE = '    print("Do not commit that as a new commit. %s" % AMEND_HOWTO)\n'


# Restoring the one-notch clamp is the regression this consumer was written to keep
# out: the arrival can be several notches, and answering one while subtracting one
# parks the rest in an accumulator that a finished gesture never returns to.
NOTCH_LIMIT = "    CGFloat limit = (CGFloat)(SHRT_MAX / HIDScrollWheelDelta);\n"


# The draining replacement is only a fix where the call sites use it, so the
# mutation rewires one of them to the per-frame answer that promises a pixel.
POINTER_DRAIN = "                short moveX = HIDDrainRelativeDelta(&residualX, normalizedDeltaX, sensitivity);\n"


# The count a wheel event answers with, and the step the changelog claims for it.
CLICK_LIMIT = "    NSInteger limit = SHRT_MAX / HIDScrollWheelDelta;\n"
GAIN_STEP = re.compile(
    r"    - name: Verify the pointer ships the motion it was asked for\n"
    r"(?:.*\n)*?      run: python3 scripts/relative-pointer-gain-tests\.py\n\n"
)


def answer_one_notch(text):
    """Put the one-notch clamp back on the count a wheel event answers with.

    The count is what the fix widened, so the mutation is the exact line the
    defect shipped with: round, then refuse anything past a single notch. The
    accumulator half of the path is untouched, which is why only the harness
    that runs the quantized branch can see it.
    """
    once(text, CLICK_LIMIT, "the packet bound on a discrete scroll count")
    clamp = "    if (clicks > 1) { clicks = 1; } else if (clicks < -1) { clicks = -1; }\n"
    return text.replace(CLICK_LIMIT, clamp + CLICK_LIMIT, 1)


LOST_ROUND_HEADER = ("### Round 33: a fast flick lost most of its scroll before "
                     "the host saw it\n")


RETRY_FLAGS = "         --retry 5 --retry-all-errors --retry-connrefused \\\n"


TRUNCATE_A_FRAME = """        short moveX = HIDDrainRelativeDelta(&emulationResidualX,
                                            emulationDeltaX,
                                            HIDMouseEmulationSpeed);\n"""
DRAFT_THE_RATE = """                                            -emulationDeltaY,
                                            HIDMouseEmulationSpeed);\n"""
NORMALISE_Y_HERE = "        CGFloat emulationDeltaY = HIDControllerMouseDeltaForAxis(ry);\n"


REASON_PRESERVATION = '    reasons = previous.get("_accepted_reasons") or DEFAULT_ACCEPTED_REASONS\n'


def forget_the_written_reasons(text):
    """Let a refresh overwrite the explanations a person wrote.

    The baseline is the file that says why a finding is tolerated, and the tool that
    regenerates it used to carry its own copy of those sentences and write them over
    whatever was on file -- it deleted the audit and printed a success line. Fixing
    one finding is what makes the damage visible, so the battery keeps the guard on.
    """
    once(text, REASON_PRESERVATION, "the refresh keeping the reasons already on file")
    return text.replace(REASON_PRESERVATION,
                        "    reasons = DEFAULT_ACCEPTED_REASONS\n", 1)


def truncate_a_stick_frame(text):
    """Answer one stick frame on its own, which is what shipped.

    The lost fraction is largest exactly where a careful player holds the stick, and
    the display-link path was already exact, so the two paths disagreed about how far
    the same stick position moved the cursor.
    """
    once(text, TRUNCATE_A_FRAME, "the drained X frame of the emulated pointer")
    return text.replace(TRUNCATE_A_FRAME,
                        "        short moveX = (short)(emulationDeltaX * HIDMouseEmulationSpeed);\n",
                        1)


def draft_the_emulation_rate(text):
    """Give one axis its own number for the pointer rate."""
    once(text, DRAFT_THE_RATE, "the drained Y frame of the emulated pointer")
    return text.replace(DRAFT_THE_RATE,
                        "                                            -emulationDeltaY,\n"
                        "                                            8.0);\n", 1)


def count_the_stick_in_raw_units(text):
    """Compare the deadzone against raw stick counts on one path again."""
    once(text, NORMALISE_Y_HERE, "the normalised Y axis of the emulated pointer")
    return text.replace(NORMALISE_Y_HERE,
                        "        CGFloat emulationDeltaY = (fabs(ry) > 4000) ? ry / 32767.0 : 0.0;\n",
                        1)


def give_up_on_one_connection(text):
    """Take the retry out of the only download path the build has.

    The failure was real: a runner could not open a connection to github.com for
    nine seconds, curl made one attempt, and both macOS builds ended. Keeping the
    same flags written by hand across a growing list of dependencies is not a rule,
    so the battery has to notice the moment the rule stops being true in the file.
    """
    once(text, RETRY_FLAGS, "the retry flags on the only download path")
    return text.replace(RETRY_FLAGS, "", 1)


def lose_a_round_header(text):
    """Delete a round's heading from the changelog.

    A rewrite that swallows the tail of the file does not look like a deletion of
    seven rounds when the gate only reads sentences: the claim above this one was
    green while it happened. Round numbers are the part of the file a truncation
    cannot survive, so the rule that reads them has to be judged by the same
    battery it exists to complement.
    """
    once(text, LOST_ROUND_HEADER, "the round-33 heading")
    return text.replace(LOST_ROUND_HEADER, "", 1)


def unhook_a_claimed_step(text):
    """Delete the build step the changelog says the pointer harness has.

    Round 34 wrote that its harness is a step in both macOS build jobs when the
    step existed in no commit. The rule that replaced that sentence reads the
    claim back out of the changelog and looks for the step, so removing the step
    has to redden the aggregate -- a claim about the pipeline that the pipeline
    cannot show is the class of defect this battery exists to keep impossible.
    """
    match = GAIN_STEP.search(text)
    if not match:
        raise SystemExit("anchor found 0 times, expected 1: the pointer harness step")
    return text[:match.start()] + text[match.end():]


def promise_a_pixel(text):
    once(text, POINTER_DRAIN, "the display-link drain of relative pointer motion")
    return text.replace(POINTER_DRAIN,
                        "                short moveX = HIDScaledRelativeDelta(normalizedDeltaX, sensitivity);\n",
                        1)


def hoard_a_notch(text):
    once(text, NOTCH_LIMIT, "the notch consumer's packet limit")
    return text.replace(NOTCH_LIMIT,
                        "    if (whole > 1.0) { whole = 1.0; } else if (whole < -1.0) { whole = -1.0; }\n"
                        + NOTCH_LIMIT, 1)


def forgot_the_amend(text):
    once(text, AMEND_ADVICE, "the amend advice in the promotion report")
    return text.replace(AMEND_ADVICE, "", 1)


def believe_shallow(text):
    once(text, SHALLOW_GUARD, "shallow history refusal")
    return text.replace(SHALLOW_GUARD, "", 1)



def unplug_gate(text):
    once(text, KEYBOARD_STEP, "keyboard gate wiring")
    return text.replace(KEYBOARD_STEP, "", 1)



def stop_without_release(text):
    once(text, TEARDOWN_BEFORE_STOP, "keyboard teardown before the stop")
    return text.replace(TEARDOWN_BEFORE_STOP, "", 1)


def drop_swift_debug_condition(text):
    """Stop compiling the Debug-only Swift code, while its caller stays.

    Naming the condition for the Swift compiler is what makes `#if DEBUG` in a
    .swift file mean anything. Remove the line and the file reads as though it
    were part of the app, Release is unchanged, and only a Debug link would notice.
    """
    return re.sub(r"\n\t+SWIFT_ACTIVE_COMPILATION_CONDITIONS = DEBUG;", "", text, count=1)


def read_the_matrix_while_it_is_shut(text):
    """Take the capability claims from the pass that opened nothing.

    The Advanced section ships collapsed and SwiftUI vends nothing inside a collapsed
    group, so the merged text of every pass makes a machine that never opened the
    section look the same as one that did. Renaming the channel the checker reads is
    how that split disappears without any line of the check being edited.
    """
    return text.replace("readableContentExpanded", "readableContentNeverOpened")


def pane_keeps_its_own_rule(text):
    """Move the enhancement gate back inside the page.

    The words stay plausible. What disappears is any way for something outside the
    page to disagree with it, which is the reason the rule was moved in the first
    place -- measured, a page and a checker built from two copies disagreed.
    """
    return text.replace("!settingsModel.frameInterpolationControlIsEnabled",
                        "!showsMetalTuningControls")


DIAG_TRANSIENT_CALL = '        [self showTransientTitle:MLString(@"Copied", nil)'
APPDELEGATE_IMPORT = '#import "Localization.h"'


def unadvertise_section(text):
    return once(text, "    monitorItem.tag = StreamMenuSectionMonitor;\n",
                "the monitor tag assignment").replace(
        "    monitorItem.tag = StreamMenuSectionMonitor;\n", "", 1)


def address_by_title_again(text):
    """The regression that actually shipped: keep the tag, add the old words back."""
    return once(text, "        if (item.tag == section && item.submenu != nil) {",
                "the section lookup").replace(
        "        if (item.tag == section && item.submenu != nil) {",
        '        if ((item.tag == section && item.submenu != nil)\n'
        '            || [item.title isEqualToString:@"\u5c4f\u5e55"]) {', 1)


def point_a_button_at_the_wrong_section(text):
    return once(text, "[self popUpStreamSubmenuForSection:StreamMenuSectionMonitor fromButton:sender];",
                "the monitor button").replace(
        "StreamMenuSectionMonitor fromButton:sender]",
        "StreamMenuSectionWindow fromButton:sender]", 1)


def a_second_localization_macro(text):
    """A file that stops asking the shared macro and answers for itself again."""
    return once(text, APPDELEGATE_IMPORT, "the shared localization import").replace(
        APPDELEGATE_IMPORT,
        APPDELEGATE_IMPORT + "\n#define MLString(key, comment) (key)", 1)


def localize_a_localized_string(text):
    """Wrap a finished translation in the lookup a second time."""
    return once(text, DIAG_TRANSIENT_CALL, "the transient title call").replace(
        '[self showTransientTitle:MLString(@"Copied", nil)',
        '[self showTransientTitle:[[LanguageManager sharedLanguage] localize:MLString(@"Copied", nil)]',
        1)


LOGGER = os.path.join(root, "Limelight", "Utility", "Logger.m")

RESOLVER_M = os.path.join(root, "Limelight", "Input", "KeyboardMapResolver.m")
RESOLVER_H = os.path.join(root, "Limelight", "Input", "KeyboardMapResolver.h")

RIGHT_COMMAND_ROW = "    KMR_Remote_RightMeta,   // KMR_Phys_RightCommand"
LWIN_DECL = "    KMR_VK_LWIN     = 0x5B,"
FLAGS_COMMAND = "        out |= KMR_RemoteMaskForPhysical(KMR_Phys_LeftCommand);"


def right_command_sends_the_left_win(text):
    """Both hands of one modifier answering as the left hand."""
    return once(text, RIGHT_COMMAND_ROW, "the right Command row").replace(
        RIGHT_COMMAND_ROW, "    KMR_Remote_LeftMeta,    // KMR_Phys_RightCommand", 1)


def a_virtual_key_one_digit_off(text):
    return once(text, LWIN_DECL, "the left Win declaration").replace(
        LWIN_DECL, "    KMR_VK_LWIN     = 0x5C,", 1)


def the_flags_path_asks_for_the_right_hand(text):
    """NSEvent flags do not say which side went down, so this invents an answer."""
    return once(text, FLAGS_COMMAND, "the flags path Command line").replace(
        FLAGS_COMMAND, "        out |= KMR_RemoteMaskForPhysical(KMR_Phys_RightCommand);", 1)


HIDDEN_LOG_ROW = 'MLLogRow(@"WARN", @"Log", @"Repeated log lines suppressed")'


def hide_a_row_behind_a_variable(text):
    """Correct code, and a key no scan can ask a table about."""
    return once(text, HIDDEN_LOG_ROW, "the suppression row").replace(
        HIDDEN_LOG_ROW, 'MLLogRow(@"WARN", logCategory, @"Repeated log lines suppressed")', 1)


ONE_ARGUMENT_CALL = 'MLString(@"NSURLError %@", nil)'


def call_the_localizer_with_one_argument(text):
    """The tree does not build: MLString takes two arguments, this hands it one."""
    return once(text, ONE_ARGUMENT_CALL, "the NSURLError row").replace(
        ONE_ARGUMENT_CALL, 'MLString(@"NSURLError %@")', 1)


def uncapture_leaves_the_host_holding_modifiers(text):
    """Capture release hands back the pointer but keeps the host holding keys.

    The commit point already lets go of held keys and pressed buttons, so the
    modifier tracker looks like the third item of a tidy three. It is not:
    flagsChanged: stops reaching the sync the moment input is off, so a modifier
    the player lets go of on the Mac desktop never comes up on the host until some
    later keyboard event happens to correct it, and every pointer click in between
    carries a modifier nobody is holding.
    """
    line = "    [self.hidSupport releaseRemoteModifierKeysForUncapture];\n"
    if text.count(line) != 1:
        raise SystemExit("the capture-release modifier return is not where this "
                         "mutation expects it, so it would prove nothing")
    return text.replace(line, "", 1)


def recapture_loses_a_modifier_still_held(text):
    """The capture-release return clears the physical hold as well.

    The player triggers capture release with a finger still on Shift and comes back
    to a tracker that says nothing is held, so the first gameplay key after
    recapture goes out with a modifier byte of zero: the sprint they never stopped
    became a walk, and it reads as another keyboard mapping conflict.
    """
    kept = """    HIDKeyboardPhysicalModifierMask heldPhysical =
        self.keyboardPhysicalModifierSourceMask;
    [self releaseAllModifierKeys];
    self.keyboardPhysicalModifierSourceMask = heldPhysical;
"""
    plain = "    [self releaseAllModifierKeys];\n"
    if text.count(kept) != 1:
        raise SystemExit("the physical-tracking guard in the capture-release return "
                         "is not where this mutation expects it, so it would "
                         "prove nothing")
    return text.replace(kept, plain, 1)


def record_no_modifier_behind_the_door(text):
    """A modifier pressed while input forwarding is off is never learned about.

    The gate reads as one more input guard, and it is the shape that shipped: it
    stands in front of the physical record as well as the send, so when the player
    comes back from the embedded settings page still holding Shift, the tracker has
    never heard of it. The host is told to walk where the player is running, and the
    release that follows is gated the same way, so nothing is ever logged.
    """
    shipped = """    [self updateKeyboardPhysicalModifierStateFromEvent:event];

    if (!self.shouldSendInputEvents) {
        return;
    }
"""
    gated = """    if (!self.shouldSendInputEvents) {
        return;
    }

    [self updateKeyboardPhysicalModifierStateFromEvent:event];
"""
    if text.count(shipped) != 1:
        raise SystemExit("the record-before-gate pair in -flagsChanged: is not where "
                         "this mutation expects it, so it would prove nothing")
    return text.replace(shipped, gated, 1)


def release_a_modifier_the_player_is_holding(text):
    """The rule lets go of a modifier the player never released.

    Correct-looking code, and the packet sequence strands the physical modifier
    tracker: the sync diffs desired against the tracker, the tracker still says the key
    is down, so no corrective press is ever sent and the host stays without Shift until
    the player releases and presses it again.
    """
    mutated = text \
        .replace("HIDSyntheticOwnedModifierMask(support, remoteModifierMask)", "remoteModifierMask") \
        .replace("HIDSyntheticOwnedModifierMask(self, remoteModifierMask)", "remoteModifierMask")
    if mutated == text:
        raise SystemExit("the modifier-ownership rule is not in HIDSupport.m any more, so "
                         "this mutation would be proving nothing")
    return mutated


def release_modifiers_without_clearing_the_tracker(text):
    """Releases all eight keys on the host and leaves the tracker saying they are down.

    The sync diffs desired against that tracker, so the next real event computes a
    diff of zero and sends nothing: the tracker and the host never meet again until
    each key is pressed and released separately.
    """
    cleared = """    self.keyboardPhysicalModifierSourceMask = 0;
    self.keyboardRemoteModifierMask = 0;
"""
    if text.count(cleared) != 1:
        raise SystemExit("the tracker-clearing pair in releaseAllModifierKeys is not "
                         "where this mutation expects it, so it would prove nothing")
    return text.replace(cleared, "", 1)


def hotkey_fires_at_autorepeat_rate(text):
    """Removes the guard that makes a held hotkey fire once.

    AppKit keeps sending keyDown while a key is held, and the key-equivalent chain
    delivers those deliveries exactly like the first press, so this version runs the
    rule once per repeat: a bound panel strobes at the autorepeat rate, and a rule
    bound to a window rebuild releases the player's held modifiers over and over while
    one finger never leaves the key. The screen says the hotkey is held; the game says
    the player keeps letting go of everything else they were holding.
    """
    start = text.index("- (BOOL)handleKeyboardTranslationRuleForEvent:(NSEvent *)event {")
    end = text.index("\n}\n", start) + 3
    body = text[start:end]
    guard = re.search(r"    if \(event\.isARepeat\) \{\n(?:.*\n)*?    \}\n", body)
    if guard is None:
        raise SystemExit("the translation-rule handler no longer guards key repeats, so "
                         "this mutation would be proving nothing")
    return text[:start] + body.replace(guard.group(0), "", 1) + text[end:]


def release_ignores_the_modifier_its_press_carried(text):
    """Answers every key release with a modifier byte of zero.

    It compiles, it still releases the key, and the simplest test passes: the press went
    out as "W with Shift" while the release says plain "W", which the host cannot pair
    with anything it was told, so the character keeps running after the finger lifts.
    Only a packet-level probe of -keyUp: sees it, which is why this one is planted.
    """
    start = text.index("- (void)keyUp:(NSEvent *)event {")
    end = text.index("\n}\n", start) + 3
    body = text[start:end]
    line = "char modifiers = [self translateKeyModifierWithEvent:event];"
    if body.count(line) != 1:
        raise SystemExit("the modifier byte in -keyUp: is not where this mutation "
                         "expects it, so it would prove nothing")
    return text[:start] + body.replace(line, "char modifiers = 0;", 1) + text[end:]


def blanket_release_at_the_translation_rules(text):
    """Puts the release back at the translation-rule entry point, unguarded.

    This is the shape the project shipped until now: every rule the player wrote
    released all eight modifiers as it fired, so a rule invoked while Shift was held for
    a sprint took the sprint away on the next key press. The harness that owns this
    reads the caller's source, so the mutation has to be in the caller's source.
    """
    anchor = """    KeyboardTranslationRule *rule = [self keyboardTranslationRuleMatchingEvent:event];
    if (rule == nil) {
        return NO;
    }
"""
    if text.count(anchor) != 1:
        raise SystemExit("the translation-rule handler no longer has the shape this "
                         "mutation expects, so it would prove nothing")
    return text.replace(anchor, anchor + "\n    [self.hidSupport releaseAllModifierKeys];\n", 1)


def naming_an_api_only_the_newest_sdk_declares(text):
    """Names `effectIsInteractive` instead of asking the object for it.

    The property is declared in a newer SDK than the one the build jobs compile with,
    so every local grep and every behavioural harness stayed silent while three CI jobs
    failed to build. Only a compiler pointed at the build's own SDK can see this, which
    is why the compile gate exists and why this mutation belongs to it.
    """
    needle = "MLSetGlassInteractivity(self.backgroundView, glassIsInteractive);"
    if text.count(needle) != 1:
        raise SystemExit("the glass container no longer asks for interactivity through the "
                         "lookup this mutation replaces, so it would prove nothing")
    return text.replace(needle, "self.backgroundView.effectIsInteractive = glassIsInteractive;", 1)


def menu_hint_offers_a_word(text):
    """Hands `Space` to AppKit instead of declining to register a hint.

    A word is not a key equivalent: a live NSMenu matches neither the key the word names
    nor the key its first letter names, so the row advertises something nobody can press
    and the binding survives only while the stream view is taking keys. The gate reads
    the answer out of the compiled profile, so the mutation has to live in that file.
    """
    mutated, hits = re.subn(
        r"\n    guard key\.utf16\.count[\s\S]*?\n    \}\n", "\n", text, count=1)
    if hits != 1:
        raise SystemExit("the menu-equivalent guard is not where this mutation expects it, "
                         "so it would prove nothing")
    return mutated


def drift_one_upload_action(text):
    """Moves one upload step to a different major of the same action.

    This is what a partial dependency bump leaves behind: the file still parses, every
    job still runs, and the producer and the consumer of an artifact are now two
    versions of one action. Only the pipeline's own audit can see that, so it has to be
    run against the pipeline.
    """
    mutated = text.replace("uses: actions/upload-artifact@v7",
                           "uses: actions/upload-artifact@v6", 1)
    if mutated == text:
        raise SystemExit("no upload-artifact@v7 is in the workflow any more, so this "
                         "mutation would be proving nothing")
    return mutated


GLASS_PANEL_CALL = "    self.logOverlayContainer = [GlassOverlayContainer containerWithCornerRadius:12.0];"


def glass_is_never_told_it_must_answer(text):
    """The container keeps the request and never hands it to the glass.

    The control-centre pill is a button, and its glass is asked to respond to being
    pressed. A setter that stores the answer without passing it on is invisible to every
    source rule -- only the glass view knows, so the compiled container is run and asked.
    """
    needle = "MLSetGlassInteractivity(self.backgroundView, glassIsInteractive);"
    if text.count(needle) != 1:
        raise SystemExit("the container no longer hands interactivity to the glass in one "
                         "place, so this mutation would be proving nothing")
    return text.replace(needle, "MLSetGlassInteractivity(self.backgroundView, NO);", 1)


def give_the_log_panel_its_own_vibrancy(text):
    """A panel goes back to the pre-glass material it shipped with.

    The look a reviewer signed off is a claim about a specific view, so a silent move
    back to the old material has to be refused by the list that says which panels are
    converted.
    """
    if text.count(GLASS_PANEL_CALL) != 1:
        raise SystemExit("the log panel no longer asks the glass container for its "
                         "background, so this mutation would be proving nothing")
    return text.replace(GLASS_PANEL_CALL, """    self.logOverlayContainer = [[NSVisualEffectView alloc] initWithFrame:NSZeroRect];
    self.logOverlayContainer.material = NSVisualEffectMaterialHUDWindow;""", 1)


HOSTS_VC = os.path.join(root, "Limelight", "macOS", "ViewControllers", "HostsViewController.m")

RETRY_SHAPE = """    BOOL retryableElsewhere = reason == PairFailureReasonNetwork ||
                              reason == PairFailureReasonTimeout;
"""
TIMEOUT_CASE = """        case PairFailureReasonTimeout:
            return NSLocalizedString(@"Pairing timed out. Make sure the host PC is reachable and try again.", @"Pairing timed out");
"""


def guess_the_retry_from_text(text):
    """The shape that shipped: decide the retry by searching the message for words."""
    return once(text, RETRY_SHAPE, "the retry decision").replace(
        RETRY_SHAPE,
        """    NSString *lowered = detail.lowercaseString ?: @"";
    BOOL retryableElsewhere = [lowered containsString:@"timeout"] ||
                              [lowered containsString:@"network"] ||
                              [lowered containsString:@"\u8bf7\u6c42\u8d85\u65f6"];
""", 1)


def drop_a_reason_from_the_wording(text):
    """A new reason arrives and one screen never learns to answer it."""
    return once(text, TIMEOUT_CASE, "the timeout wording").replace(TIMEOUT_CASE, "", 1)


MARKER_LITERAL = '@"[curated] repeated %ld time(s) within %.1fs (last: %@)"'
BROWSER_MATCH = '[line containsString:@"[curated] repeated "]'


def reword_the_written_marker(text):
    """A copy edit in Logger.m that the log browser never hears about."""
    return once(text, MARKER_LITERAL, "the summary marker").replace(
        MARKER_LITERAL,
        MARKER_LITERAL.replace("[curated] repeated", "[curated] suppressed", 1), 1)


def fold_on_prose_again(text):
    return once(text, BROWSER_MATCH, "the browser fold test").replace(
        BROWSER_MATCH,
        '[line localizedCaseInsensitiveContainsString:@"\u5185\u91cd\u590d"]', 1)


# The project file is the only thing that decides whether a new source file is
# compiled at all, and a missing entry produces no error, no warning and no
# binary: the feature simply is not in the product. The membership audit reads
# that file, so the entry has to be loadable.
GLASS_MEMBER_ENTRY = "\t\t\t\tmacOS/Views/GlassOverlayContainer.m,\n"
# The internal header declared a property whose class it could not see, so every
# translation unit that reached it failed to compile and the feature lived in no
# binary. Only a build of the app itself notices, and this host cannot run one, so
# the rule that does notice is shape: the class has to be reachable from the header.
# The shared compiler finder answers "which clang, which SDK", and on a host with
# no xcrun the answer has to be "none", not a traceback: two CI runs on ubuntu
# learned the difference the expensive way. Narrowing the exception to something
# that cannot happen is how a hardening like that quietly stops being one.
NARROWED_EXCEPTION = '        except OSError:\n            return ""\n'


def xcrun_assumed_present(text):
    return once(text, NARROWED_EXCEPTION, "the compiler finder's answer").replace(
        NARROWED_EXCEPTION, '        except KeyboardInterrupt:\n            return ""\n', 1)


BLIND_IMPORT = '#import "GlassOverlayContainer.h"\n'


def header_blind_to_its_type(text):
    return once(text, BLIND_IMPORT, "the internal header's import").replace(
        BLIND_IMPORT, "", 1)


MEMBERSHIP_STEP = 'os.path.join(root, "scripts", "source-membership-audit.py")'


def unlisted_source(text):
    return once(text, GLASS_MEMBER_ENTRY, "the project file's member list").replace(
        GLASS_MEMBER_ENTRY, "", 1)


def aggregate_stops_running_an_audit(text):
    # Realistic shape: someone edits the aggregate to speed it up and loses a
    # step, so CI keeps checking while the local verdict quietly stops covering it.
    return once(text, MEMBERSHIP_STEP, "the aggregate's membership step").replace(
        MEMBERSHIP_STEP, 'os.path.join(root, "scripts", "l10n-audit.py")', 1)


# The mouse-capture escape hatch is Ctrl+Option held alone, and the shipped default
# shortcut table puts six keyed actions behind that same pair. The guard is one line
# at the top of -keyDown:, and its absence is invisible in every other gate: the
# shortcut still fires, the overlay still toggles, and the only thing that happens
# is that the player's held modifiers let go on the host 150 ms later.
# The active-Space observer releases modifiers on the path that skips the uncapture,
# and -releaseAllModifierKeys is eight fixed VK packets: without the held-key release
# a movement key held while the Space changes stays pressed with no window left on
# that Space to ever deliver its keyUp:.
SPACE_HELD_RELEASE = """            [strongSelf.hidSupport releaseAllHeldKeys];
            [strongSelf.hidSupport releaseAllModifierKeys];"""


def drop_space_held_release(text):
    once(text, SPACE_HELD_RELEASE, "the active-Space held-key release")
    return text.replace(SPACE_HELD_RELEASE,
                        "            [strongSelf.hidSupport releaseAllModifierKeys];", 1)


KEY_DOWN_PENDING_CANCEL = """- (void)keyDown:(NSEvent *)event {
    // A pending modifier-only release means"""


def drop_pending_cancel(text):
    once(text, KEY_DOWN_PENDING_CANCEL, "keyDown's cancellation of a pending release")
    start = text.index(KEY_DOWN_PENDING_CANCEL)
    marker = "    self.pendingOptionUncaptureToken += 1;\n"
    return text[:start] + text[start:].replace(marker, "", 1)


# A pad cannot press half a key, so the view that presses keys on its behalf has to send
# both edges of the stroke it claims. The helper has always taken a `down:` argument and
# always called keyDown:, and every caller passed YES: nothing downstream of it was ever
# told the key came back up. Both halves of that mistake are worth a mutation -- a stroke
# missing its release, and a release delivered as a second press -- because either one
# compiles, ships, and reads on a pad as a button that does not quite work.
CONTROLLER_STROKE = """    [self sendKey:keyCode down:YES modifiers:modifierFlags];
    [self sendKey:keyCode down:NO modifiers:modifierFlags];"""


def drop_controller_release(text):
    once(text, CONTROLLER_STROKE, "the controller press-and-release pair")
    return text.replace(CONTROLLER_STROKE,
                        "    [self sendKey:keyCode down:YES modifiers:modifierFlags];", 1)


EDGE_DELIVERY = """    if (down) {
        [self.responder keyDown:event];
    } else {
        [self.responder keyUp:event];
    }"""


def swallow_controller_release(text):
    once(text, EDGE_DELIVERY, "the delivery that matches the edge it was given")
    return text.replace(EDGE_DELIVERY, "    [self.responder keyDown:event];", 1)


# Zero interpolation slots is two answers, and only the re-asked question tells them
# apart: a GPU with no interpolation engine and a GPU that has one but is being asked
# about a stream above its ceiling both report zero at the stream size. Either half of
# that can be lost without touching a line of the interpolation code itself.
INTERPOLATION_CEILING_PROBE = """                    VTLowLatencyFrameInterpolationConfiguration *probe =
                        [[VTLowLatencyFrameInterpolationConfiguration alloc]
                            initWithFrameWidth:ML_INTERPOLATION_PROBE_WIDTH
                                   frameHeight:ML_INTERPOLATION_PROBE_HEIGHT
                       numberOfInterpolatedFrames:1];
                    slotsAtProbeSize = probe ? probe.numberOfInterpolatedFrames : 0;"""


def ask_the_engine_the_same_question_again(text):
    once(text, INTERPOLATION_CEILING_PROBE, "the re-ask at a size the engine can answer")
    return text.replace(INTERPOLATION_CEILING_PROBE,
                        "                    slotsAtProbeSize = configuration.numberOfInterpolatedFrames;",
                        1)


TWO_ZERO_SLOT_ANSWERS = """    return slotsAtProbeSize >= 1 ? MLInterpolationSlotVerdictStreamAboveCeiling
                                 : MLInterpolationSlotVerdictNoHardware;"""


def merge_the_two_zero_slot_answers(text):
    once(text, TWO_ZERO_SLOT_ANSWERS, "the two zero-slot verdicts")
    return text.replace(TWO_ZERO_SLOT_ANSWERS,
                        "    return MLInterpolationSlotVerdictNoHardware;", 1)


MUTATIONS = [
    ("neuter-if", HID, neuter_if, "keyUp release guard is disabled but still worded"),
    ("no-key-cancel", CAPTURE, drop_pending_cancel,
     "a key press no longer cancels a pending modifier-only release", COLLISION_GATE),
    ("space-change-keeps-a-held-key", STREAM_SVC, drop_space_held_release,
     "a Space change releases modifiers but leaves an ordinary key pressed",
     SPACE_HELD_GATE),
    ("press-without-release", NAVIGATION, drop_controller_release,
     "a gamepad press reaches the responder as a press and never as a release",
     NAVIGATION_GATE),
    ("release-as-a-press", NAVIGATION, swallow_controller_release,
     "the release half of a gamepad stroke is delivered as a second press",
     NAVIGATION_GATE),
    ("oversized-stream-blames-the-gpu", VIDEO_RENDERER, merge_the_two_zero_slot_answers,
     "a stream above the interpolation ceiling is reported as a Mac without the engine",
     VIDEO_GATE),
    ("interpolation-never-reasked", VIDEO_RENDERER, ask_the_engine_the_same_question_again,
     "a refused stream size is re-asked at the same refused size",
     VIDEO_GATE),
    ("no-return", HID, no_return, "keyUp guard records without returning"),
    ("drop-release", HID, drop_release, "keyUp guard no longer clears the record"),
    ("late-guard", HID, late_guard, "keyUp guard runs after the release is sent"),
    ("commented-guard", HID, commented_guard, "keyUp guard moved into a comment"),
    ("neuter-settings", CAPTURE, neuter_settings, "settings guard is disabled but still worded"),
    ("late-clear", HID, late_clear, "stale record cleared after the press is sent"),
    ("no-record", HID, no_record, "forwarded presses are never recorded"),
    ("late-record", HID, late_record, "the press is recorded after it is sent"),
    ("no-init", HID, no_init, "the held-key set is left nil so records vanish"),
    ("leak-records", HID, leak_records, "the held-key release keeps its records"),
    ("drop-teardown", HID, drop_teardown_release, "session teardown no longer releases held keys"),
    ("drop-uncapture", CAPTURE, drop_uncapture_release, "capture release forgets held keys entirely"),
    ("late-uncapture", CAPTURE, late_uncapture_release, "held keys released after input is switched off"),
    ("bare-predicate", SHORTCUTS, bare_predicate, "the modifier floor is dropped to zero"),
    ("bare-menu-gate", MENU, bare_menu_gate, "the responder gate ignores the floor"),
    ("bare-rule-gate", CAPTURE, bare_rule_gate, "a bare translation rule eats a gameplay key"),
    ("bare-menu-equiv", SHORTCUTS, bare_menu_equivalent, "a bare key becomes a menu key equivalent"),
    ("unmeasured-mfx", DERIVED, unmeasured_mfx, "MetalFX availability falls back to trusting the OS version"),
    ("unmeasured-fi", DERIVED, unmeasured_interpolation, "interpolation claims available without slots"),
    ("unmeasured-sr", DERIVED, unmeasured_scaler, "the scaler ignores an empty scale factor list"),
    ("constant-fi-toggle", VIDEO_RULES, constant_toggle, "the interpolation control ignores the measured capability"),
    ("unmapped-keydown", HID, unmapped_press, "an unmapped press is forwarded as VK 0"),
    ("unmapped-keyup", HID, unmapped_release, "an unmapped release is forwarded as VK 0"),
    ("drop-space-row", HID, drop_space_row, "the mapping table loses the space bar"),
    ("duplicate-row", HID, duplicate_w_row, "a physical code is mapped twice so one row wins"),
    ("undocumented-mapping", HID, undocumented_mapping, "a key gap closes without the list saying why"),
    ("leaked-key-event", COLLECTION_VIEW, leak_the_key_event, "a gamepad press leaks its synthesized key event"),
    ("unowned-path-helper", APP_CELL, unowned_path_helper, "a path hands out +1 without saying so"),
    ("hid-manager-outlives", HID, hid_manager_outlives, "the HID manager survives the object its callbacks use"),
    ("blind-sweep", ANALYZER, blind_sweep, "an analyzer that did not run reads as clean", ANALYZER_GATE),
    ("accept-new-findings", ANALYZER, accept_new_findings, "a new finding class slips past the baseline", ANALYZER_GATE),
    ("blind-scan-health", L10N, blind_scan_health, "an empty scan reads as a clean tree", L10N_GATE),
    ("at-blind-scan", L10N, at_blind_scan, "the at-quoted call sites go unseen again", L10N_GATE),
    ("grep-scanned", L10N, grep_scanned, "the scan shells out to the host grep dialect", AUDIT_GATE),
    ("recounted-build", PREPARER, recounted_build, "the release tool counts commits its own way"),
    ("believed-shallow", BUILD_SH, believe_shallow, "a shallow clone stamps a build number that is too small"),
    ("promoted-then-committed", PREPARER, forgot_the_amend,
     "a cleared promotion hides the amend the build count forces", PREP_GATE),
    ("notch-consumer-hoards-a-notch", HID_INTERNAL, hoard_a_notch,
     "one scroll event hoards the notches it was given, and a finished gesture never pays them",
     NOTCH_GATE),
    ("pointer-promises-a-pixel", POINTER_FILE, promise_a_pixel,
     "a pointer frame answers a whole pixel for a tenth of one, so the slider's low half lies",
     GAIN_GATE),
    ("wheel-answers-one-notch-for-several", HID_INTERNAL, answer_one_notch,
     "a wheel event carrying three notches answers for one, and the other two never existed",
     CLICK_GATE),
    ("changelog-claims-a-step-the-pipeline-lacks", WORKFLOW, unhook_a_claimed_step,
     "the changelog says a harness is a build step and the workflow does not run it",
     AUDIT_GATE),
    ("changelog-loses-a-whole-round", CHANGELOG, lose_a_round_header,
     "a rewrite takes a round of history out of the changelog and nothing notices",
     AUDIT_GATE),
    ("download-gives-up-on-one-connection", FETCHER, give_up_on_one_connection,
     "one refused connection ends both macOS builds, as it did on the runner",
     AUDIT_GATE),
    ("stick-keeps-only-whole-pixels", POINTER_FILE, truncate_a_stick_frame,
     "a stick held just past the deadzone ships a little over half the travel it asked for",
     EMULATION_GATE),
    ("stick-rate-drafted-into-a-literal", POINTER_FILE, draft_the_emulation_rate,
     "one axis of the emulated pointer stops agreeing with the other about the rate",
     EMULATION_GATE),
    ("stick-counted-in-raw-units", POINTER_FILE, count_the_stick_in_raw_units,
     "the two pointer paths disagree about where stick movement begins",
     EMULATION_GATE),
    ("baseline-refresh-forgets-why", ANALYZER, forget_the_written_reasons,
     "regenerating the analyzer baseline deletes the reasons a person wrote for it",
     ANALYZER_GATE),
    ("unwired-gate", WORKFLOW, unplug_gate, "a gate exists that CI never runs"),
    ("upload-action-split-across-versions", WORKFLOW, drift_one_upload_action,
     "one workflow uses two versions of the same upload action", WF_GATE),
    ("translation-rule-clears-a-held-modifier", MOUSE_CAPTURE,
     blanket_release_at_the_translation_rules,
     "a keyboard translation rule releases a modifier the player is holding", SHORTCUT_GATE),
    ("keyup-forgets-the-modifier-its-press-carried", HID,
     release_ignores_the_modifier_its_press_carried,
     "a key release does not carry the modifier byte its press carried"),
    ("held-hotkey-fires-at-autorepeat-rate", MOUSE_CAPTURE,
     hotkey_fires_at_autorepeat_rate,
     "a held hotkey runs its action again for every repeated keyDown AppKit sends"),
    ("naming-an-sdk-the-build-does-not-have", GLASS_CONTAINER,
     naming_an_api_only_the_newest_sdk_declares,
     "a source file names an API the build's SDK does not declare"),
    ("menu-hint-offers-a-word-instead-of-a-key", SHORTCUT_PROFILE,
     menu_hint_offers_a_word,
     "a bound shortcut shows a hint no keyboard can produce"),
    ("stop-without-release", WINDOW_MODES, stop_without_release, "the stream stops while the host still holds a key"),
    ("swift-debug-condition-gone", PBXPROJ, drop_swift_debug_condition,
     "Debug-only Swift code stops compiling while the Objective-C half keeps calling it"),
    ("matrix-read-while-shut", RENDER_PROBE, read_the_matrix_while_it_is_shut,
     "the capability matrix is certified from a pass in which its section stayed shut"),
    ("pane-keeps-own-rule", VIDEO_PANE, pane_keeps_its_own_rule,
     "the video page recomputes the enhancement rule instead of asking the model"),
    ("unadvertised-section", MENU, unadvertise_section,
     "a submenu stops advertising the section the overlay addresses it by"),
    ("address-by-title-again", DIAGNOSTICS, address_by_title_again,
     "the submenu lookup compares the words on the item again"),
    ("wrong-section-button", DIAGNOSTICS, point_a_button_at_the_wrong_section,
     "a timeout button pops up another section's submenu"),
    ("second-localization-macro", APPDELEGATE, a_second_localization_macro,
     "a file answers localization for itself instead of the shared macro"),
    ("double-lookup", DIAGNOSTICS, localize_a_localized_string,
     "a translated string is looked up a second time on the way to the screen"),
    ("reworded-log-marker", LOGGER, reword_the_written_marker,
     "the summary Logger.m writes stops carrying the marker the browser folds on"),
    ("fold-on-prose", DIAGNOSTICS, fold_on_prose_again,
     "the log browser folds on a Chinese sentence instead of the marker"),
    ("guessed-pairing-retry", HOSTS_VC, guess_the_retry_from_text,
     "the pairing retry is decided by searching the failure text for words again"),
    ("unanswered-pair-reason", HOSTS_VC, drop_a_reason_from_the_wording,
     "a pairing reason reaches a screen that has no wording for it"),
    ("right-command-left-win", RESOLVER_M, right_command_sends_the_left_win,
     "the right Command key sends the left Win key, so one of the two disappears"),
    ("modifier-vk-drift", RESOLVER_H, a_virtual_key_one_digit_off,
     "a modifier is sent as the virtual key of a different key"),
    ("flags-invent-a-side", RESOLVER_M, the_flags_path_asks_for_the_right_hand,
     "the flags path answers a modifier with a side it cannot know"),
    ("log-row-hidden-from-scan", DIAGNOSTICS, hide_a_row_behind_a_variable,
     "a log row hides its category behind a value no scan can read", L10N_GATE),
    ("localizer-called-with-one-argument", DIAGNOSTICS, call_the_localizer_with_one_argument,
     "a two-argument localizer macro is invoked with one argument, which the "
     "preprocessor refuses", L10N_GATE),
    ("modifier-release-forgets-the-tracker", HID, release_modifiers_without_clearing_the_tracker,
     "all modifiers are released on the host while the tracker still claims they are held"),
    ("panel-reverts-to-its-own-vibrancy", DIAGNOSTICS, give_the_log_panel_its_own_vibrancy,
     "a stream panel goes back to drawing the pre-glass vibrancy material", LIQUID_GATE),
    ("glass-never-told-it-must-answer", GLASS_CONTAINER, glass_is_never_told_it_must_answer,
     "a control asks its glass to answer interaction and the glass is never told",
     OVERLAY_GATE),
    ("shortcut-releases-held-modifier", HID, release_a_modifier_the_player_is_holding,
     "a synthetic shortcut releases a modifier the player is still holding", SHORTCUT_GATE),
    ("record-no-modifier-behind-the-door", HID, record_no_modifier_behind_the_door,
     "a modifier pressed while input forwarding is off is never recorded",
     SHORTCUT_GATE),
    ("uncapture-leaves-host-modifiers", CAPTURE,
     uncapture_leaves_the_host_holding_modifiers,
     "capture release returns keys and buttons but leaves the host holding "
     "modifiers", AUDIT_GATE),
    ("recapture-loses-a-held-modifier", HID, recapture_loses_a_modifier_still_held,
     "capture release clears a hold the player's finger never left",
     SHORTCUT_GATE),
    ("unlisted-source-file", PBXPROJ, unlisted_source,
     "a source file belongs to no target, so nothing ever compiles it"),
    ("aggregate-drops-a-ci-audit", AUDIT, aggregate_stops_running_an_audit,
     "the local aggregate stops running an audit that CI still runs"),
    ("header-names-a-type-it-cannot-see", INTERNAL, header_blind_to_its_type,
     "a property names a first-party class that its own imports cannot see"),
    ("xcrun-assumed-present", TOOLCHAIN, xcrun_assumed_present,
     "a host with no xcrun gets a traceback instead of an answer"),
]


def gate_failed(gate):
    # A gate that runs the battery as one of its own checks has to be told not to
    # ask back, which is what the flags carried with each gate are for.
    script, extra_args = gate
    proc = subprocess.run([sys.executable, script] + list(extra_args),
                          capture_output=True, text=True, cwd=root)
    detail = [line for line in (proc.stdout + proc.stderr).splitlines() if "FAIL" in line]
    return proc.returncode != 0, detail


def main():
    keep = None
    if "--keep-broken" in sys.argv:
        keep = sys.argv[sys.argv.index("--keep-broken") + 1]
    if "--no-audit-recursion" in sys.argv:
        print("(audit recursion suppressed: this run was started by the audit)")

    original = {entry[1]: open(entry[1], encoding="utf-8").read()
                for entry in MUTATIONS}
    missed = []
    for entry in MUTATIONS:
        name, path, mutate, note = entry[:4]
        gate = entry[4] if len(entry) > 4 else AUDIT_GATE
        # Evaluate the mutation before the file is opened. `open(path, "w")` truncates
        # the moment it is called, and `write(mutate(...))` evaluates the file name
        # first, so a mutation that raises part way through used to leave the real
        # source empty -- which is how a green-looking battery run once took the video
        # pane apart and left the tree unable to compile.
        mutated = mutate(original[path])
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(mutated)
        try:
            failed, detail = gate_failed(gate)
        finally:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(original[path])
        caught = "CAUGHT " if failed else "MISSED "
        print("%s %-18s %s" % (caught, name, note))
        if failed and detail:
            print("        %s" % detail[0].strip()[:160])
        if not failed:
            missed.append(name)

    print("\n%d/%d mutations caught" % (len(MUTATIONS) - len(missed), len(MUTATIONS)))
    if missed:
        print("assertions that a real regression would slip past: %s" % ", ".join(missed))
    if keep:
        for entry in MUTATIONS:
            name, path, mutate = entry[0], entry[1], entry[2]
            if name == keep:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(mutate(original[path]))
                print("left %s applied for manual inspection" % name)
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
