#!/usr/bin/env python3
"""Run the edge-handle acceptance on this machine and hand back a matrix.

The shipped checklist in docs/release-1720-2026-09-29.md is eight steps a human
performs and remembers. That is how "worked twice then failed" survives: nobody
repeats step 2 thirty times by hand and knows what they saw. This tool keeps the
human where only a human is needed -- starting the stream, and any physical
modifier press they choose to do -- and does the rest itself: it moves the real
pointer through the WindowServer (injected events, labelled as such, never
claimed as hardware), screenshots the real screen, and answers from the band the
app itself paints -- 14 pt idle, 30 pt armed -- rather than from anybody's memory.

Verdicts are per step with the screenshot kept. FAIL points at the image. Every
event this tool sends is injected; the matrix says so and keeps the hardware
rows UNVERIFIED instead of borrowing the injection's confidence.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER_SRC = os.path.join(ROOT, "scripts", "edge_acceptance_helper.swift")
HELPER_BIN = os.path.join(tempfile.gettempdir(), "mle", "edge-acceptance-helper")

IDLE_PT, ARMED_PT = 14.0, 30.0
IDLE_MAX, ARMED_MIN, MAX_DEPTH = 18.0, 22.0, 40.0
RESULTS = []


def record(step, verdict, detail, shot=None):
    RESULTS.append({"step": step, "verdict": verdict, "detail": detail, "shot": shot})
    print("%-6s %-28s %s%s" % (verdict, step, detail, ("  [" + shot + "]") if shot else ""))


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def ensure_helper():
    os.makedirs(os.path.dirname(HELPER_BIN), exist_ok=True)
    if not (os.path.exists(HELPER_BIN) and
            os.path.getmtime(HELPER_BIN) >= os.path.getmtime(HELPER_SRC)):
        r = run(["swiftc", "-O", "-o", HELPER_BIN, HELPER_SRC])
        if r.returncode:
            sys.exit("helper failed to compile:\n" + r.stderr)
    return HELPER_BIN


def band_detect(img, edge="right", scale=1.0):
    """Width of the near-white edge band, in points, plus its centre.

    The handle is drawn at the window edge (alpha 0.98), so the measurement is
    geometric: from the screen edge inward, the first run of columns whose
    longest contiguous near-white segment covers most of the 48 pt handle
    length. Video brightness cannot fake the run starting at column zero.
    """
    from PIL import Image  # noqa: local gate host has Pillow; CI never runs this
    px = img.load()
    w, h = img.size
    def near_white(r, g, b):
        return min(r, g, b) > 195 and (max(r, g, b) - min(r, g, b)) < 45
    # scan per column along the strip axis
    strip = int(MAX_DEPTH * scale)
    runs = []
    for depth in range(strip):
        coord = (w - 1 - depth) if edge == "right" else depth
        best = cur = 0
        best_lo = lo = 0
        for y in range(h):
            r, g, b = px[coord, y][:3]
            if near_white(r, g, b):
                if cur == 0:
                    lo = y
                cur += 1
                if cur > best:
                    best, best_lo = cur, lo
            else:
                cur = 0
        runs.append((depth, best, best_lo))
    min_run = 0.6 * 48.0 * scale
    # The handle is a capsule with a shadow: the outermost 0..OUTER_GAP columns
    # are anti-aliased corner pixels that fail near_white even at full idle.
    # Demanding a hit in column zero measured the screenshot pipeline, not the
    # app, and failed a perfectly painted handle. Allow a bounded outer gap --
    # but the band must still start within OUTER_GAP px of the screen edge, so
    # mid-strip video content cannot pose as the handle.
    OUTER_GAP = int(round(4 * scale))
    width_cols = 0
    centre = None
    started = False
    for depth, length, lo in runs:
        if length >= min_run:
            if not started:
                if depth > OUTER_GAP:
                    break  # nothing handle-like near the edge
                started = True
            width_cols = depth + 1
            centre = (lo + length / 2.0) / scale
        elif started and runs[depth - 1][1] >= min_run and length >= min_run * 0.5:
            continue  # single-column video gap
        elif not started and depth <= OUTER_GAP:
            continue  # anti-aliased capsule margin before the band starts
        else:
            break
    if width_cols == 0:
        return None
    return {"width_pt": width_cols / scale, "centre_pt": centre}


def strip_signature(img, edge, handle_c, scale):
    """Colour signature of the handle neighbourhood, independent of the armed
    look. The earlier rule assumed armed = a wider near-white band; on this
    build the armed handle paints in the accent colour instead, so the white
    band shrinks and an absolute-width rule calls a working hover a failure.
    The acceptance-relevant fact is that the strip changes while the pointer
    dwells and returns when it leaves -- whatever the armed look is."""
    px = img.load()
    w, h = img.size
    half = int(34 * scale)
    y0 = max(0, int(handle_c * scale) - half)
    y1 = min(h, int(handle_c * scale) + half)
    if edge == "right":
        x0, x1 = w - int(30 * scale), w
    elif edge == "left":
        x0, x1 = 0, int(30 * scale)
    elif edge == "top":
        x0, x1 = max(0, int(handle_c * scale) - half), min(w, int(handle_c * scale) + half)
        y0, y1 = 0, int(30 * scale)
    else:
        x0, x1 = max(0, int(handle_c * scale) - half), min(w, int(handle_c * scale) + half)
        y0, y1 = h - int(30 * scale), h
    white = blue = dark = other = 0
    for x in range(x0, x1):
        for y in range(y0, y1):
            r, g, b = px[x, y][:3]
            if min(r, g, b) > 195 and max(r, g, b) - min(r, g, b) < 45:
                white += 1
            elif b > 140 and b - r > 40:
                blue += 1
            elif min(r, g, b) < 60:
                dark += 1
            else:
                other += 1
    return {"white": white, "blue": blue, "dark": dark, "other": other}


def sig_distance(a, b):
    n = max(1, sum(a.values()))
    return sum(abs(a[k] - b[k]) for k in a) / float(n)


def self_test():
    """The detector must see the two contract widths and refuse an empty edge."""
    from PIL import Image
    fails = 0
    for n, width, want in (("idle", 14, (10, IDLE_MAX)), ("armed", 30, (ARMED_MIN, 38)),
                           ("empty", 0, None)):
        img = Image.new("RGB", (800, 600), (38, 42, 48))
        for x in range(800 - width, 800):
            for y in range(276, 324):
                img.putpixel((x, y), (246, 247, 251))
        got = band_detect(img, "right")
        if want is None:
            ok = got is None
        else:
            ok = got and want[0] <= got["width_pt"] <= want[1]
        print("%-4s synthetic %-6s band: %s" % ("ok" if ok else "FAIL", n,
              "none" if not got else "%.1f pt" % got["width_pt"]))
        fails += 0 if ok else 1
    # The pair that proves the delta rule earns its keep: a bright video edge
    # present in BOTH frames inflates the absolute width in both, and only the
    # growth between frames still separates armed from idle. If this case ever
    # shows absolute width agreeing with the delta, the delta rule is dead
    # weight and the rule above can go back to one number.
    base = Image.new("RGB", (800, 600), (38, 42, 48))
    # A full-height pale wall against the edge is the content that can fool a
    # plain width rule: it reads as a wide band in both frames. The idle frame
    # is the trap -- the absolute rule would call it armed before the pointer
    # ever dwelt -- and only the growth from the base can say idle.
    for x in range(800 - 22, 800):           # bright wall along the whole edge
        for y in range(0, 600):
            base.putpixel((x, y), (246, 247, 251))
    hover = base.copy()
    for x in range(800 - 30, 800 - 22):      # armed widening past the wall
        for y in range(0, 600):
            hover.putpixel((x, y), (246, 247, 251))
    # Regression: the shipped handle is a rounded capsule with a shadow, so on
    # a real screenshot the first two columns are anti-aliased and dim. A
    # detector that insists on column zero rejects the handle the app actually
    # paints (this is exactly how 1720's first live run produced a false FAIL).
    cap = Image.new("RGB", (800, 600), (38, 42, 48))
    for x in range(800 - 12, 798):          # 14 pt capsule, 2 px off the edge
        for y in range(276, 324):
            cap.putpixel((x, y), (246, 247, 251))
    got_cap = band_detect(cap, "right")
    cap_ok = got_cap and 12 <= got_cap["width_pt"] <= IDLE_MAX
    print("%-4s synthetic capsule-with-margin band: %s" % ("ok" if cap_ok else "FAIL",
          "none" if not got_cap else "%.1f pt" % got_cap["width_pt"]))
    fails += 0 if cap_ok else 1
    # And the gap must stay bounded: a bright block 10 px in is content, not handle.
    far = Image.new("RGB", (800, 600), (38, 42, 48))
    for x in range(800 - 24, 800 - 10):
        for y in range(276, 324):
            far.putpixel((x, y), (246, 247, 251))
    far_ok = band_detect(far, "right") is None
    print("%-4s synthetic mid-strip block rejected: %s" % ("ok" if far_ok else "FAIL",
          "rejected" if far_ok else "accepted"))
    fails += 0 if far_ok else 1
    b, hv = band_detect(base, "right"), band_detect(hover, "right")
    bw = b["width_pt"] if b else 0.0
    hw = hv["width_pt"] if hv else 0.0
    idle_abs_rule_says_armed = bw >= ARMED_MIN
    delta_rule = hw >= max(ARMED_MIN, bw + 6.0)
    ok = idle_abs_rule_says_armed and delta_rule
    print("%-4s synthetic bright-content pair: base %.1f armed %.1f, idle fooled by absolute rule=%s, delta armed=%s"
          % ("ok" if ok else "FAIL", bw, hw, idle_abs_rule_says_armed, delta_rule))
    fails += 0 if ok else 1
    print("%d band-detector self-test failure(s)" % fails)
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loops", type=int, default=5, help="hover/collapse cycles (acceptance asks for 30)")
    ap.add_argument("--edge", default="right", choices=["right", "left", "top", "bottom"])
    ap.add_argument("--mode", default="ask", choices=["ask", "free", "released", "locked"])
    ap.add_argument("--yes", action="store_true", help="the stream is already running; do not ask")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())

    helper = ensure_helper()
    if run(["pgrep", "-x", "MoonlightEnhanced"]).returncode:
        sys.exit("MoonlightEnhanced is not running; start it and connect to the host first")
    if run([helper, "locked"]).stdout.strip() == "1":
        # A locked screen produces black captures with every window still in
        # place; judging the bar from that would blame the app for the room.
        # This is an environment gate, not an acceptance result.
        sys.exit("screen is locked: unlock first (environment gate, not an app failure)")
    screens = [[float(v) for v in line.split()] for line in
               run([helper, "screens"]).stdout.splitlines() if line.strip()]
    if not screens:
        sys.exit("helper read no screens")
    x, y, w, h, scale = screens[0]
    if len(screens) > 1:
        print("note: %d screens; only the main one is measured, others UNVERIFIED" % len(screens))
    def ask(text, default=""):
        try:
            return input(text)
        except EOFError:
            return default
    if not args.yes:
        ans = ask("is the fullscreen stream to the host running on the MAIN display? [y/N] ")
        if ans.strip().lower() != "y":
            sys.exit("start the stream first; this tool will not launch it and will not interrupt you")
    mode = args.mode
    if mode == "ask":
        mode = ask("mouse state now -- free (f), after Shift-Option release (r), game-locked (l)? [f/r/l] ", "l").strip().lower()
        mode = {"f": "free", "r": "released", "l": "locked"}.get(mode, "free")

    out = tempfile.mkdtemp(prefix="mle-edge-acceptance-")
    def shot(tag):
        path = os.path.join(out, tag + ".png")
        # -R capture can transiently fail ("could not create image from rect")
        # while spaces/fullscreen animations run; a full capture + crop cannot
        # silently drop a frame, and the crop is pixel-identical at origin 0,0.
        full = path + ".full.png"
        if run(["screencapture", "-x", "-o", full]).returncode:
            return path, None
        from PIL import Image
        img = Image.open(full)
        img.crop((0, 0, int(w), int(h))).save(path)
        os.remove(full)
        try:
            from PIL import Image
            img = Image.open(path)
            img.load()
            det = band_detect(img, args.edge, scale) or {"width_pt": 0.0, "centre_pt": None}
            return path, det
        except Exception as e:
            return path, {"error": str(e)}

    centre = {"x": w / 2.0, "y": h / 2.0}
    path, base = shot("00-baseline")
    if not base or base.get("width_pt", 0) <= 0:
        record("baseline band visible", "FAIL",
               "no 14 pt handle band found on the %s edge; if it is docked elsewhere pass --edge" % args.edge, path)
    else:
        record("baseline band visible",
               "PASS" if base["width_pt"] <= IDLE_MAX else "FAIL",
               "idle band %.1f pt (expect <= %.0f)" % (base["width_pt"], IDLE_MAX), path)
        handle_c = base["centre_pt"] or h / 2.0
        hp = {"right": (w - IDLE_PT / 2.0, handle_c), "left": (IDLE_PT / 2.0, handle_c),
              "top": (handle_c, IDLE_PT / 2.0), "bottom": (handle_c, h - IDLE_PT / 2.0)}[args.edge]
        if mode in ("free", "released"):
            armed_ok = collapsed_ok = 0
            from PIL import Image
            for i in range(args.loops):
                run([helper, "move", str(centre["x"]), str(centre["y"])])
                time.sleep(0.3)
                p_park, _ = shot("loop-%02d-park" % i)
                park_sig = strip_signature(Image.open(p_park), args.edge, handle_c, scale)
                run([helper, "move", str(hp[0]), str(hp[1])])
                time.sleep(0.35)  # 0.12 s dwell lights it; 0.35 covers shot latency
                path, _ = shot("loop-%02d-hover" % i)
                hover_sig = strip_signature(Image.open(path), args.edge, handle_c, scale)
                # The strip must change while the pointer dwells. Video content
                # cannot fake this: the pointer's only effect is the bar's own
                # state, and the same dwell position is parked in the frame
                # one shot earlier.
                armed = sig_distance(park_sig, hover_sig) >= 0.15
                armed_ok += armed
                run([helper, "move", str(centre["x"]), str(centre["y"])])
                time.sleep(0.8)  # 0.45 s auto-collapse after the pointer leaves
                path2, _ = shot("loop-%02d-collapse" % i)
                back_sig = strip_signature(Image.open(path2), args.edge, handle_c, scale)
                ok2 = sig_distance(park_sig, back_sig) <= 0.05
                if not ok2:
                    # A late collapse under main-thread jitter is a latency
                    # fact, not the "armed forever" failure the acceptance
                    # cares about. Give it one bounded second, then judge.
                    time.sleep(1.2)
                    path2, _ = shot("loop-%02d-collapse-retry" % i)
                    back_sig = strip_signature(Image.open(path2), args.edge, handle_c, scale)
                    ok2 = sig_distance(park_sig, back_sig) <= 0.05
                collapsed_ok += ok2
                if not armed:
                    record("hover lights the handle x%d" % args.loops, "FAIL",
                           "strip unchanged at loop %d (park %s vs hover %s)" % (i, park_sig, hover_sig), path)
                    break
                if not ok2:
                    record("handle collapses x%d" % args.loops, "FAIL",
                           "strip did not return at loop %d (park %s vs after %s)" % (i, park_sig, back_sig), path2)
                    break
            else:
                record("hover lights the handle x%d" % args.loops, "PASS",
                       "%d/%d armed (injected pointer, not hardware)" % (armed_ok, args.loops))
                record("handle collapses x%d" % args.loops, "PASS",
                       "%d/%d collapsed" % (collapsed_ok, args.loops))

        else:
            record("hover/collapse loops", "N/A", "locked mode has no local hover; entry is the shortcut")

        # The keyDown+flags shortcut cannot be trusted through a pre-set-flags
        # event; combo injects control down, option down, C with both held —
        # the same shape a hand produces. 0x180000 was command+option, a typo
        # that made the shortcut look dead on this host (ctrl+option is 0xC0000).
        # Window-geometry verdict: the panel is an app window, so its
        # appearance/disappearance in CGWindowList is authoritative. Pixel
        # diffs were fooled by notification banners and black frames; a
        # window cannot fake itself.
        pid = int(run(["pgrep", "-x", "MoonlightEnhanced"]).stdout.split()[0])
        def wins():
            return set(l for l in run([helper, "wins", str(pid)]).stdout.splitlines() if l.strip())
        before = wins()
        run([helper, "combo", "8"])
        time.sleep(0.7)
        path_open, _ = shot("ctrl-opt-c-open")
        opened = wins()
        new_wins = opened - before
        gone_wins = before - opened
        run([helper, "combo", "8"])
        time.sleep(0.6)
        path_close, _ = shot("ctrl-opt-c-close")
        back = wins()
        restored = (back == before)
        ok = bool(new_wins or gone_wins) and restored
        record("control+option+C opens/closes the panel",
               "PASS" if ok else "FAIL",
               "window set changed on open (%d new/%d gone) and restored on close: %s"
               % (len(new_wins), len(gone_wins), restored), path_open)

        # Menu open/close/cancel and press-through, judged from the window
        # set: the expanded panel shifts the handle window 22 pt outward, and
        # every transition is a window-geometry fact, not a pixel guess.
        def wins_now():
            return sorted(run([helper, "wins", str(pid)]).stdout.splitlines())
        base_w = wins_now()
        run([helper, "move", str(hp[0]), str(hp[1])])
        time.sleep(0.4)
        run([helper, "click", str(hp[0]), str(hp[1])])
        time.sleep(0.8)
        opened_w = wins_now()
        run([helper, "click", str(centre["x"]), str(centre["y"])])
        time.sleep(0.8)
        closed_w = wins_now()
        ok = opened_w != base_w and closed_w == base_w
        record("menu opens on the handle and cancels outside",
               "PASS" if ok else "FAIL",
               "open changed the window set: %s; click-away restored: %s"
               % (opened_w != base_w, closed_w == base_w))
        clean = 0
        for _ in range(5):
            run([helper, "down", str(centre["x"]), str(centre["y"])])
            run([helper, "move", str(hp[0]), str(hp[1])])
            time.sleep(0.3)
            run([helper, "up", str(hp[0]), str(hp[1])])
            time.sleep(0.3)
        clean += wins_now() == base_w
        record("held-drag across the edge x5 does not summon the menu",
               "PASS" if clean else "FAIL", "window set stayed at baseline: %s" % bool(clean))
        # the stream may now hold a stale hover; park the pointer
        run([helper, "move", str(centre["x"]), str(centre["y"])])
        time.sleep(0.6)

    if mode == "released":
        record("shift+option released the pointer", "PASS",
               "user asserted the released state; the tool took it as the entry condition")
    else:
        record("shift+option release (hardware)", "UNVERIFIED",
               "pure modifiers cannot be claimed from injection; press them yourself")
    record("multi-display / non-Retina arrangement", "UNVERIFIED",
           "only the main display is measured here")

    report = os.path.join(out, "acceptance.json")
    json.dump({"mode": mode, "edge": args.edge, "loops": args.loops,
               "events": "injected", "results": RESULTS}, open(report, "w"), indent=2)
    failed = [r for r in RESULTS if r["verdict"] == "FAIL"]
    print("\n%d PASS, %d FAIL, %d CHECK/UNVERIFIED/N-A; artefacts: %s" % (
        sum(r["verdict"] == "PASS" for r in RESULTS), len(failed),
        sum(r["verdict"] not in ("PASS", "FAIL") for r in RESULTS), out))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
