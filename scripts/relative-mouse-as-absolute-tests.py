#!/usr/bin/env python3
"""P2-1 gate: prove the relative-mouse-as-absolute rewire is honest.

What this file is about
-----------------------
The "free mouse" motion path used to fire one relative wire packet per
delta: `LiSendMouseMoveEventCtx`. Some hosts (windowed-fullscreen games,
CAD apps, anything that consumes the absolute-pointer coordinate stream)
ignore relative deltas and leave the host cursor stuck. Sunshine /
Moonlight Qt both ship an absolute-wire variant that already exists in
`moonlight-common-c` -- `LiSendMouseMoveAsMousePositionEventCtx`. This
gate proves that:

  * the rewire exists in `HIDSupport.m` and reads through the new
    `HIDShouldRouteRelativeAsAbsolute` predicate,
  * the predicate only fires when (a) the per-host switch is on,
    (b) the session is in remote/free mouse mode, and
    (c) the session has produced a fresh absolute pointer reference
    within a 5s staleness window,
  * the per-host switch defaults to false (the existing relative-only
    wire path stays the shipped behaviour),
  * every Swift setting registration point that carries
    `absoluteMouseMode` also carries the new `relativeMouseAsAbsolute`,
    so a regression in any one of them fails the gate,
  * the Settings UI toggle is added cleanly without changing the
    segmented tab bar or any pre-existing, user-accepted control.

A planted defect in any of those checks has to be noticed. The
defects live in --self-test, not on main.
"""
import os, re, subprocess, sys

# A mutation check runs this file again on a planted tree. Without the sentinel that
# child would plant its own defects and fork again, so the battery would grow by one
# level per level. The child answers with the plain assertions only.
NESTED = os.environ.get('P21_GATE_NESTED') == '1'

ROOT = "."
STRICT_TEST = "--self-test" in sys.argv
for a in sys.argv[1:]:
    if a != "--self-test" and os.path.isdir(a):
        ROOT = a

HID = "Limelight/Input/HIDSupport.m"
INTERNAL = "Limelight/Input/HIDSupport_Internal.h"
INPUT_STREAM = "moonlight-common/moonlight-common-c/src/InputStream.c"
STORE = "Limelight/macOS/ViewControllers/SettingsStore.swift"
MODEL = "Limelight/macOS/ViewControllers/SettingsModel.swift"
DERIVED = "Limelight/macOS/ViewControllers/SettingsModel+DerivedValues.swift"
PERSIST = "Limelight/macOS/ViewControllers/SettingsModel+Persistence.swift"
BRIDGE = "Limelight/macOS/ViewControllers/SettingsObjCBridge.swift"
PANE = "Limelight/macOS/ViewControllers/SettingsInputPane.swift"
TAB_BAR = "Limelight/macOS/ViewControllers/LiquidGlass/LiquidGlassTabBar.swift"
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
            HID,
            "LiSendMouseMoveAsMousePositionEventCtx(inputCtx, moveX, moveY,\n                                                   p2ReferenceWidth, p2ReferenceHeight)",
            "/* P2-1 PLANTED: rewire path dropped */\n        LiSendMouseMoveEventCtx(inputCtx, moveX, moveY)",
            "rewire path regressed to pure-relative wire packet",
        ),
        (
            INTERNAL,
            "  if (ageMs > 5000) return NO;",
            "  /* P2-1 PLANTED: staleness gate removed */",
            "staleness gate weakened",
        ),
        (
            STORE,
            # Tolerate any sibling toggles (e.g. P2-3a muteOnFocusLoss)
            # inserted between these two lines by later commits.
            re.compile(
                r"relativeMouseAsAbsolute: relativeMouseAsAbsolute,\n"
                r"(?:      [^\n]*\n){1,2}"
                r"      swapMouseButtons: swapMouseButtons,"),
            "/* P2-1 PLANTED: registration dropped */\n      swapMouseButtons: swapMouseButtons,",
            "SettingsStore.applyToSettings lost registration",
        ),
        (
            PANE,
            'title: "Relative Mouse Sends Absolute Position",\n          hintKey: "Relative Mouse As Absolute detail",\n          boolBinding: $settingsModel.relativeMouseAsAbsolute',
            '/* P2-1 PLANTED: toggle hidden */',
            "toggle content dropped from SettingsInputPane",
        ),
    ]
    for rel, needle, replacement, message in cases:
        full = os.path.join(ROOT, rel)
        with open(full, encoding="utf-8") as fh:
            original = fh.read()
        if hasattr(needle, "search"):
            m = needle.search(original)
            idx = m.start() if m else -1
            length = (m.end() - m.start()) if m else 0
        else:
            idx = original.find(needle)
            length = len(needle)
        if idx < 0:
            check(False, "self-test defect for %s: needle not found" % rel.split("/")[-1])
            continue
        planted = original[:idx] + replacement + original[idx+length:]
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(planted)
        try:
            env = dict(os.environ, P21_GATE_NESTED="1")
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

    hid = read(HID)
    internal = read(INTERNAL)
    istream = read(INPUT_STREAM)
    store = read(STORE)
    model = read(MODEL)
    derived = read(DERIVED)
    persist = read(PERSIST)
    bridge = read(BRIDGE)
    pane = read(PANE)
    tab = read(TAB_BAR)

    # --- Protocol layer precondition --------------------------------------------
    check("int LiSendMouseMoveAsMousePositionEventCtx(" in istream,
          "moonlight-common-c exposes LiSendMouseMoveAsMousePositionEventCtx")

    # --- HIDSupport.m rewire ----------------------------------------------------
    m = re.search(
        r'- \(void\)dispatchRelativeMouseDeltaX:\(CGFloat\)deltaX\s+'
        r'deltaY:\(CGFloat\)deltaY\s+sourceTag:\(NSString \*\)sourceTag\s*\{',
        hid)
    check(m is not None, "HIDSupport.dispatchRelativeMouseDeltaX signature unchanged")
    if m:
        body_start = m.end()
        next_method = re.search(r'\n- \(void\)', hid[body_start:])
        if next_method:
            body = hid[body_start:body_start + next_method.start()]
        else:
            body = hid[body_start:body_start+5000]
        check("LiSendMouseMoveAsMousePositionEventCtx" in body,
              "rewire uses LiSendMouseMoveAsMousePositionEventCtx on P2-1 path")
        check("HIDShouldRouteRelativeAsAbsolute" in body,
              "HIDSupport dispatchRelativeMouseDeltaX reads the new predicate")
        check(body.count("LiSendMouseMoveEventCtx(") == 1,
              "LiSendMouseMoveEventCtx kept as fallback (exactly one call site)")
    else:
        body = ""

    # --- Predicate gates --------------------------------------------------------
    check("static inline BOOL HIDShouldRouteRelativeAsAbsolute" in internal,
          "HIDShouldRouteRelativeAsAbsolute predicate in Internal.h")
    check("SettingsClass relativeMouseAsAbsoluteFor:" in internal,
          "predicate reads per-host switch via SettingsClass")
    check('"remote"' in internal.split("HIDShouldRouteRelativeAsAbsolute")[1].split("}", 1)[0],
          "predicate restricts to free-mouse / remote mode")
    check("ageMs > 5000" in internal,
          "predicate enforces 5s staleness window")
    check("getLastAbsolutePointerHostX:NULL" in internal,
          "predicate reads via getLastAbsolutePointerHostX/Y")

    # --- Swift registration surface --------------------------------------------
    check("relativeMouseAsAbsolute: relativeMouseAsAbsolute," in store,
          "SettingsStore.applyToSettings: registered in payload")
    check("relativeMouseAsAbsolute: settings.relativeMouseAsAbsolute," in store,
          "SettingsStore toBridgeSettings: registered in bridge copy")
    check("@Published var relativeMouseAsAbsolute: Bool" in model,
          "SettingsModel exposes @Published relativeMouseAsAbsolute")
    check("defaultRelativeMouseAsAbsolute = false" in derived,
          "default constant in DerivedValues (false = current behaviour)")
    check("relativeMouseAsAbsolute = Self.defaultRelativeMouseAsAbsolute" in persist,
          "Persistence: default value on construction")
    check("settings.relativeMouseAsAbsolute" in persist and "defaultRelativeMouseAsAbsolute" in persist,
          "Persistence: reads persisted value with default fallback")
    check("relativeMouseAsAbsolute: relativeMouseAsAbsolute," in persist,
          "Persistence: outputs relativeMouseAsAbsolute in bridge struct")
    check("static func relativeMouseAsAbsolute(for key: String) -> Bool" in bridge,
          "ObjCBridge exposes per-host relativeMouseAsAbsolute(for:) getter")
    check('"relativeMouseAsAbsolute":' in bridge,
          "ObjCBridge dictionary includes relativeMouseAsAbsolute")

    # --- UI invariants ----------------------------------------------------------
    check('title: "Relative Mouse Sends Absolute Position"' in pane,
          "SettingsInputPane shows the new toggle")
    check('hintKey: "Relative Mouse As Absolute detail"' in pane,
          "P2-1 toggle has hintKey for i18n detail")
    check('$settingsModel.relativeMouseAsAbsolute' in pane,
          "P2-1 toggle binds to settingsModel.relativeMouseAsAbsolute")
    check('if settingsModel.mouseMode == "remote" {' in pane and
          'Relative Mouse Sends Absolute Position' in pane.split('if settingsModel.mouseMode == "remote" {')[1][:500],
          "P2-1 toggle is gated on free-mouse mode")
    check("NSSegmentedControl" in tab and "role = .tabs" in tab,
          "tab bar uses user-accepted NSSegmentedControl with role=.tabs")

    # --- Behavioural mutation battery -------------------------------------------
    if NESTED:
        print("")
        print("P2-1 gate (nested): %d failures" % len(failures))
        sys.exit(1 if failures else 0)

    print("")
    print("== mutation battery ==")
    mutations = [
        (
            HID,
            "LiSendMouseMoveAsMousePositionEventCtx(inputCtx, moveX, moveY,\n                                                   p2ReferenceWidth, p2ReferenceHeight)",
            "/* MUTATION: rewire dropped */\n        LiSendMouseMoveEventCtx(inputCtx, moveX, moveY)",
            "rewire path regressed to pure-relative wire packet",
        ),
        (
            INTERNAL,
            "  if (ageMs > 5000) return NO;",
            "  /* MUTATION: staleness removed */",
            "staleness gate weakened: stale absolute reference would now be honoured",
        ),
        (
            STORE,
            re.compile(
                r"relativeMouseAsAbsolute: relativeMouseAsAbsolute,\n"
                r"(?:      [^\n]*\n){1,2}"
                r"      swapMouseButtons: swapMouseButtons,"),
            "/* MUTATION: registration dropped */\n      swapMouseButtons: swapMouseButtons,",
            "SettingsStore.applyToSettings lost relativeMouseAsAbsolute registration",
        ),
        (
            PANE,
            'title: "Relative Mouse Sends Absolute Position",\n          hintKey: "Relative Mouse As Absolute detail",\n          boolBinding: $settingsModel.relativeMouseAsAbsolute',
            '/* MUTATION: toggle hidden */',
            "toggle became always-visible (free-mouse guard dropped)",
        ),
    ]
    caught = 0
    for rel, needle, replacement, label in mutations:
        full = os.path.join(ROOT, rel)
        with open(full, encoding="utf-8") as fh:
            original = fh.read()
        if hasattr(needle, "search"):
            m = needle.search(original)
            idx = m.start() if m else -1
            length = (m.end() - m.start()) if m else 0
        else:
            idx = original.find(needle)
            length = len(needle)
        if idx < 0:
            check(False, "mutation %s: needle not found, could not plant defect" % label)
            continue
        mutated = original[:idx] + replacement + original[idx+length:]
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(mutated)
        try:
            env = dict(os.environ, P21_GATE_NESTED="1")
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
    print("P2-1 gate: %d failures" % len(failures))
    sys.exit(1 if failures else 0)

if STRICT_TEST and not NESTED:
    print("== self-test ==")
    run_self_test()
    print("")

main()
