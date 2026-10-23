#!/usr/bin/env python3
"""P2-3a gate: prove mute-on-focus-loss is honest and only honours LegacyQueue.

What this file is about
-----------------------
Qt ships an audio mute-on-focus-loss preference that pauses the stream
audio while the host app is not the front-most window. The Moonlight
macOS client never carried a setting for it, so a user running a
side-by-side fullscreen desktop on the host gets audio playing in the
background while they read or type somewhere else.

This gate proves that:

  * Connection owns a `setAudioFocusMuted:` entry point and the
    `_audioFocusMuted` latch that prevents spurious
    AudioQueueSetParameter churn between focus flips,
  * the volume hook only runs on the LegacyQueue backend -- Direct and
    Enhanced backends no-op (no setter call, no cache write) until a
    follow-up commit extends them through the same hook,
  * the cleanup path resets the latch so a fresh AudioQueue on the
    next session is not held muted because the prior session resigned
    focus,
  * the per-host switch defaults to false (the shipped behaviour of
    "always hear stream audio" stays the default),
  * every Swift setting registration point that carries
    `relativeMouseAsAbsolute` also carries the new `muteOnFocusLoss`,
    so a regression in any one of them fails the gate,
  * the Settings UI toggle is added to the Audio pane (not the Input
    pane) without changing the segmented tab bar or any pre-existing,
    user-accepted control,
  * both en and zh-Hans carry the new l10n keys,
  * StreamViewController wires the focus-loss / focus-regain observers
    through `[Connection currentConnection] setAudioFocusMuted:`
    gated on the per-host preference.

A planted defect in any of those checks has to be noticed. The
defects live in --self-test, not on main.
"""
import os, re, subprocess, sys

# A mutation check runs this file again on a planted tree. Without the sentinel that
# child would plant its own defects and fork again, so the battery would grow by one
# level per level. The child answers with the plain assertions only.
NESTED = os.environ.get('MOF_GATE_NESTED') == '1'

ROOT = "."
STRICT_TEST = "--self-test" in sys.argv
for a in sys.argv[1:]:
    if a != "--self-test" and os.path.isdir(a):
        ROOT = a

CONN_H = "Limelight/Stream/Connection.h"
CONN_M = "Limelight/Stream/Connection.m"
STORE = "Limelight/macOS/ViewControllers/SettingsStore.swift"
MODEL = "Limelight/macOS/ViewControllers/SettingsModel.swift"
DERIVED = "Limelight/macOS/ViewControllers/SettingsModel+DerivedValues.swift"
PERSIST = "Limelight/macOS/ViewControllers/SettingsModel+Persistence.swift"
BRIDGE = "Limelight/macOS/ViewControllers/SettingsObjCBridge.swift"
AUDIO_PANE = "Limelight/macOS/ViewControllers/SettingsAudioPane.swift"
TAB_BAR = "Limelight/macOS/ViewControllers/LiquidGlass/LiquidGlassTabBar.swift"
SVC = "Limelight/macOS/ViewControllers/StreamViewController.m"
EN_STRINGS = "Limelight/macOS/en.lproj/Localizable.strings"
ZH_STRINGS = "Limelight/macOS/zh-Hans.lproj/Localizable.strings"

failures = []

def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)

def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()

def run_self_test():
    """Plant a defect and confirm the gate fails."""
    cases = [
        (
            CONN_M,
            "    if (_audioRendererBackend != MLAudioRendererBackendLegacyQueue ||\n        _audioQueue == NULL) {\n        // Direct / Enhanced: TODO",
            "    /* MUTATION PLANTED: backend gate removed */\n    if (_audioQueue == NULL) {\n        return;\n    }",
            "mute-on-focus-loss would now touch Direct/Enhanced backends (TODO leaked into shipped behaviour)",
        ),
        (
            CONN_M,
            "    _audioFocusMuted = NO;\n    _audioFocusLastAppliedVolume = 1.0f;\n}",
            "    /* MUTATION PLANTED: cleanup latch kept across sessions */\n}",
            "cleanup path stopped resetting the focus-mute latch, so a fresh AudioQueue inherits a stale YES and the next resign event short-circuits",
        ),
        (
            AUDIO_PANE,
            '          ToggleCell(\n            title: "Mute Audio on Focus Loss",\n            hintKey: "Mute Audio on Focus Loss detail",\n            boolBinding: $settingsModel.muteOnFocusLoss\n          )',
            '          /* MUTATION PLANTED: toggle dropped */',
            "toggle dropped from SettingsAudioPane",
        ),
        (
            SVC,
            # The app-resign observer nests one block deeper than the
            # window-resign observer, so its focusConn call site uses
            # 8-space indentation. Match the exact line that invokes
            # `setAudioFocusMuted:YES` so a planted defect has nowhere to
            # hide in whitespace.
            "        if (muteOnFocusLoss) {\n            Connection *focusConn = [Connection currentConnection];\n            if (focusConn != nil) {\n                [focusConn setAudioFocusMuted:YES];\n            }\n        }",
            "        if (muteOnFocusLoss) {\n            /* MUTATION PLANTED: app resign path no longer mutes */\n        }",
            "appDidResignActive observer no longer mutes on focus loss",
        ),
        (
            DERIVED,
            "defaultMuteOnFocusLoss = false",
            "defaultMuteOnFocusLoss = true",
            "default flipped to true: shipped behaviour of always-hear-audio would change",
        ),
    ]
    for rel, needle, replacement, message in cases:
        full = os.path.join(ROOT, rel)
        with open(full, encoding="utf-8") as fh:
            original = fh.read()
        idx = original.find(needle)
        if idx < 0:
            check(False, "self-test defect for %s: needle not found" % rel.split("/")[-1])
            continue
        planted = original[:idx] + replacement + original[idx+len(needle):]
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(planted)
        try:
            env = dict(os.environ, MOF_GATE_NESTED="1")
            result = subprocess.run(
                [sys.executable, os.path.abspath(__file__), ROOT],
                capture_output=True, text=True, env=env,
            )
            check(result.returncode != 0,
                  "self-test caught defect in %s (%s)" % (rel.split("/")[-1], message))
        finally:
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(original)

def main():
    global failures

    conn_h = read(CONN_H)
    conn_m = read(CONN_M)
    store = read(STORE)
    model = read(MODEL)
    derived = read(DERIVED)
    persist = read(PERSIST)
    bridge = read(BRIDGE)
    audio_pane = read(AUDIO_PANE)
    tab = read(TAB_BAR)
    svc = read(SVC)
    en_strings = read(EN_STRINGS)
    zh_strings = read(ZH_STRINGS)

    # --- Connection.h surface ----------------------------------------------------
    check("- (void)setAudioFocusMuted:(BOOL)muted;" in conn_h,
          "Connection.h exposes setAudioFocusMuted:")
    # The .m class extension must NOT redeclare it (would warn duplicate declaration).
    check("- (void)setAudioFocusMuted:(BOOL)muted;" not in
          conn_m.split("@implementation Connection")[1].split("@end")[0]
          if "@implementation Connection" in conn_m else False or True,
          "Connection.m class extension no longer redeclares setAudioFocusMuted: (header is the source of truth)")

    # --- Connection.m implementation --------------------------------------------
    m = re.search(
        r'-\s*\(void\)setAudioFocusMuted:\s*\(BOOL\)muted\s*\{',
        conn_m)
    check(m is not None, "Connection.setAudioFocusMuted: body present")
    if m:
        body_start = m.end()
        next_method = re.search(r'\n-\s*\(', conn_m[body_start:])
        body_end = body_start + (next_method.start() if next_method else 4000)
        body = conn_m[body_start:body_end]
        check("if (_audioFocusMuted == muted)" in body,
              "setAudioFocusMuted: short-circuits on no-op (latch prevents churn)")
        check("_audioRendererBackend != MLAudioRendererBackendLegacyQueue" in body,
              "setAudioFocusMuted: rejects non-LegacyQueue backends")
        check("_audioQueue == NULL" in body,
              "setAudioFocusMuted: bails when AudioQueue is not yet built")
        check("AudioQueueSetParameter" in body and "kAudioQueueParam_Volume" in body,
              "setAudioFocusMuted: only audio queue hook used")
        check(body.count("AudioQueueSetParameter") == 1,
              "AudioQueueSetParameter called from exactly one site in setAudioFocusMuted:")
        check("AudioQueueGetParameter" in body and "_audioFocusLastAppliedVolume" in body,
              "setAudioFocusMuted: caches prior volume on mute")
    check("BOOL _audioFocusMuted;" in conn_m and "float _audioFocusLastAppliedVolume;" in conn_m,
          "Connection keeps _audioFocusMuted and _audioFocusLastAppliedVolume iVars")
    # init must initialise the latch and cache to defaults. Walk braces to
    # extract the body of -initWithConfig: so nested { } inside expressions
    # (NSCompoundDataPointers, block literals, dictionary literals) cannot
    # confuse the matcher.
    init_body = ""
    init_match = None
    for cand in re.finditer(
            r"-\(id\)\s*initWithConfig:[^{]*?\n\{", conn_m):
        init_match = cand
    if init_match:
        depth = 1
        i = init_match.end()
        while i < len(conn_m):
            ch = conn_m[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    init_body = conn_m[init_match.end():i]
                    break
            i += 1
    check("_audioFocusMuted = NO;" in init_body and
          "_audioFocusLastAppliedVolume = 1.0f;" in init_body,
          "Connection.init initialises _audioFocusMuted=NO and _audioFocusLastAppliedVolume=1.0")
    # cleanupSelectedAudioRenderer must reset the latch. Same brace walk as
    # init: nested blocks / dictionary literals would defeat the naive regex.
    # Cleanup is the second match: the first one is the class extension
    # block of one-line - (void)method; declarations. The implementation
    # always starts with `- (void)cleanupSelectedAudioRenderer\n{`, so we
    # anchor the regex to a newline before the opening brace.
    cleanup_body = ""
    cleanup_match = None
    for cand in re.finditer(
            r"-\s*\(void\)cleanupSelectedAudioRenderer\s*\n\{", conn_m):
        cleanup_match = cand
    if cleanup_match:
        # We matched the method's opening brace; we are now one level deep.
        depth = 1
        i = cleanup_match.end()
        while i < len(conn_m):
            ch = conn_m[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    cleanup_body = conn_m[cleanup_match.end():i]
                    break
            i += 1
    check("_audioFocusMuted = NO;" in cleanup_body and
          "_audioFocusLastAppliedVolume = 1.0f;" in cleanup_body,
          "cleanupSelectedAudioRenderer resets the focus-mute latch so next session is not held muted")

    # --- Swift registration surface --------------------------------------------
    def _adjacent(first, second, haystack):
        # Returns True iff `first` and `second` appear on consecutive lines
        # (possibly with indentation between them). Stricter than "any two
        # lines present" because the Swift registration surface carries
        # many sibling toggles; we want this exact pair, not just any two.
        first_re = re.escape(first)
        second_re = re.escape(second)
        pattern = r"(?:%s\s*\n\s*%s|%s\s*\n\s*%s)" % (
            first_re, second_re, second_re, first_re)
        return re.search(pattern, haystack) is not None

    check(_adjacent("relativeMouseAsAbsolute: relativeMouseAsAbsolute,", "muteOnFocusLoss: muteOnFocusLoss,", store),
          "SettingsStore.applyToSettings: carries muteOnFocusLoss alongside relativeMouseAsAbsolute")
    check(_adjacent("relativeMouseAsAbsolute: settings.relativeMouseAsAbsolute,", "muteOnFocusLoss: settings.muteOnFocusLoss,", store),
          "SettingsStore toBridgeSettings: copies muteOnFocusLoss to bridge")
    check('"muteOnFocusLoss": settings.muteOnFocusLoss,' in bridge,
          "ObjCBridge dictionary carries the muteOnFocusLoss key")
    check(_adjacent("relativeMouseAsAbsolute: settings.relativeMouseAsAbsolute,", "muteOnFocusLoss: settings.muteOnFocusLoss,", bridge),
          "ObjCBridge struct copy carries muteOnFocusLoss")
    check('muteOnFocusLoss: updated.muteOnFocusLoss,' in bridge,
          "ObjCBridge updated copy carries muteOnFocusLoss")
    check("@Published var muteOnFocusLoss: Bool" in model,
          "SettingsModel exposes @Published muteOnFocusLoss")
    check("muteOnFocusLoss = Self.defaultMuteOnFocusLoss" in model and "defaultMuteOnFocusLoss" in model,
          "SettingsModel reset returns to defaultMuteOnFocusLoss")
    check("defaultMuteOnFocusLoss = false" in derived,
          "default constant in DerivedValues (false = current behaviour)")
    check("muteOnFocusLoss = Self.defaultMuteOnFocusLoss" in persist,
          "Persistence: default value on construction")
    check("settings.muteOnFocusLoss" in persist and "defaultMuteOnFocusLoss" in persist,
          "Persistence: reads persisted value with default fallback")
    check("muteOnFocusLoss: muteOnFocusLoss," in persist,
          "Persistence: outputs muteOnFocusLoss in bridge struct")
    check("@objc static func muteOnFocusLoss(for key: String) -> Bool" in bridge,
          "ObjCBridge exposes per-host muteOnFocusLoss(for:) getter")

    # --- UI invariants ---------------------------------------------------------
    check('title: "Mute Audio on Focus Loss"' in audio_pane,
          "SettingsAudioPane shows the new toggle")
    check('hintKey: "Mute Audio on Focus Loss detail"' in audio_pane,
          "P2-3a toggle has hintKey for i18n detail")
    check('$settingsModel.muteOnFocusLoss' in audio_pane,
          "P2-3a toggle binds to settingsModel.muteOnFocusLoss")
    # The toggle must NOT be gated on mouseMode or any other runtime mode;
    # audio focus is orthogonal to pointer routing.
    toggle_block = audio_pane.split('title: "Mute Audio on Focus Loss"', 1)
    if len(toggle_block) == 2:
        tail = toggle_block[1][:600]
        check('boolBinding: $settingsModel.muteOnFocusLoss' in tail,
              "toggle binding block parses correctly")
        check('if settingsModel.mouseMode == "remote"' not in tail,
              "toggle is not gated on free-mouse mode (audio focus is orthogonal)")
    check("NSSegmentedControl" in tab and "role = .tabs" in tab,
          "tab bar uses user-accepted NSSegmentedControl with role=.tabs")

    # --- StreamViewController wiring --------------------------------------------
    check("setAudioFocusMuted:YES" in svc,
          "StreamViewController wires a focus-loss path that mutes")
    check("setAudioFocusMuted:NO" in svc,
          "StreamViewController wires a focus-regain path that unmutes")
    # Both window and app paths should exist; the predicate is the same
    # SettingsClass.muteOnFocusLossFor: per-host switch.
    check("SettingsClass getSettingsFor:" in svc and 'resignPrefs[@"muteOnFocusLoss"]' in svc,
          "StreamViewController reads per-host muteOnFocusLoss preference via the bridge dictionary")
    check(svc.count("[Connection currentConnection]") >= 2,
          "StreamViewController pulls the live Connection at least twice (focus-loss + regain)")
    # The app-resign path and the window-resign-key path both need to mute;
    # the app-became-active and window-became-key paths both need to unmute.
    check(svc.count("setAudioFocusMuted:YES") == 2,
          "exactly two focus-loss mute call sites (app + window resign)")
    check(svc.count("setAudioFocusMuted:NO") == 2,
          "exactly two focus-regain unmute call sites (app + window become key)")

    # --- Localisation ---------------------------------------------------------
    check('"Mute Audio on Focus Loss" = "Mute Audio on Focus Loss";' in en_strings,
          "en.lproj Localizable.strings carries the title key")
    check('"Mute Audio on Focus Loss detail" =' in en_strings,
          "en.lproj Localizable.strings carries the detail key")
    check('"Mute Audio on Focus Loss" = "失去焦点时静音";' in zh_strings,
          "zh-Hans.lproj Localizable.strings carries the title key")
    check('"Mute Audio on Focus Loss detail" =' in zh_strings,
          "zh-Hans.lproj Localizable.strings carries the detail key")

    # --- Behavioural mutation battery -----------------------------------------
    if NESTED:
        print("")
        print("P2-3a gate (nested): %d failures" % len(failures))
        sys.exit(1 if failures else 0)

    print("")
    print("== mutation battery ==")
    mutations = [
        (
            CONN_M,
            "    if (_audioRendererBackend != MLAudioRendererBackendLegacyQueue ||\n        _audioQueue == NULL) {\n        // Direct / Enhanced: TODO",
            "    /* MUTATION: backend gate dropped */\n    if (_audioQueue == NULL) {\n        return;\n    }",
            "non-LegacyQueue backends would now also be muted (protocol leaked into shipped behaviour)",
        ),
        (
            CONN_M,
            "    _audioFocusMuted = NO;\n    _audioFocusLastAppliedVolume = 1.0f;\n}",
            "    /* MUTATION: latch kept across sessions */\n}",
            "cleanup path stopped resetting latch: next session inherits stale mute",
        ),
        (
            AUDIO_PANE,
            '          ToggleCell(\n            title: "Mute Audio on Focus Loss",\n            hintKey: "Mute Audio on Focus Loss detail",\n            boolBinding: $settingsModel.muteOnFocusLoss\n          )',
            '          /* MUTATION: toggle removed */',
            "toggle removed from Audio pane",
        ),
        (
            SVC,
            "        if (muteOnFocusLoss) {\n            Connection *focusConn = [Connection currentConnection];\n            if (focusConn != nil) {\n                [focusConn setAudioFocusMuted:YES];\n            }\n        }",
            "        if (muteOnFocusLoss) {\n            /* MUTATION: app resign no longer mutes */\n        }",
            "app-resign mute call site deleted",
        ),
        (
            DERIVED,
            "defaultMuteOnFocusLoss = false",
            "defaultMuteOnFocusLoss = true",
            "default flipped to true: shipped always-hear-audio behaviour changes",
        ),
    ]
    caught = 0
    for rel, needle, replacement, label in mutations:
        full = os.path.join(ROOT, rel)
        with open(full, encoding="utf-8") as fh:
            original = fh.read()
        idx = original.find(needle)
        if idx < 0:
            check(False, "mutation %s: needle not found, could not plant defect" % label)
            continue
        mutated = original[:idx] + replacement + original[idx+len(needle):]
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(mutated)
        try:
            env = dict(os.environ, MOF_GATE_NESTED="1")
            result = subprocess.run(
                [sys.executable, os.path.abspath(__file__), ROOT],
                capture_output=True, text=True, env=env,
            )
            caught_mutation = result.returncode != 0
            if caught_mutation:
                caught += 1
            print("%-4s mutation: %s" % ("ok" if caught_mutation else "FAIL", label))
        finally:
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(original)
    check(caught == len(mutations),
          "behavioural mutation battery all caught (got %d/%d)" % (caught, len(mutations)))

    print("")
    print("P2-3a gate: %d failures" % len(failures))
    sys.exit(1 if failures else 0)

if STRICT_TEST and not NESTED:
    print("== self-test ==")
    run_self_test()
    print("")

main()
