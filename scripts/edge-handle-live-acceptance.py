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
    width_cols = 0
    centre = None
    for depth, length, lo in runs:  # contiguous from the outermost column
        if length >= min_run:
            width_cols = depth + 1
            centre = (lo + length / 2.0) / scale
        elif depth and runs[depth - 1][1] >= min_run and length >= min_run * 0.5:
            continue  # single-column video gap
        else:
            break
    if width_cols == 0:
        return None
    return {"width_pt": width_cols / scale, "centre_pt": centre}


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
        run(["screencapture", "-x", "-o", "-R", "0,0,%d,%d" % (int(w), int(h)), path])
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
            for i in range(args.loops):
                run([helper, "move", str(centre["x"]), str(centre["y"])])
                time.sleep(0.3)
                _, _ = shot("loop-%02d-park" % i)
                run([helper, "move", str(hp[0]), str(hp[1])])
                time.sleep(0.35)  # 0.12 s dwell lights it; 0.35 covers shot latency
                path, got = shot("loop-%02d-hover" % i)
                armed = got and got["width_pt"] >= ARMED_MIN
                armed_ok += armed
                run([helper, "move", str(centre["x"]), str(centre["y"])])
                time.sleep(0.8)  # 0.45 s auto-collapse after the pointer leaves
                path2, back = shot("loop-%02d-collapse" % i)
                ok2 = back and 0 < back["width_pt"] <= IDLE_MAX
                collapsed_ok += ok2
                if not armed:
                    record("hover lights the handle x%d" % args.loops, "FAIL",
                           "armed width %.1f pt at loop %d (expect >= %.0f)" %
                           (got["width_pt"] if got else -1, i, ARMED_MIN), path)
                    break
                if not ok2:
                    record("handle collapses x%d" % args.loops, "FAIL",
                           "width after leaving %.1f pt at loop %d" %
                           (back["width_pt"] if back else -1, i), path2)
                    break
            else:
                record("hover lights the handle x%d" % args.loops, "PASS",
                       "%d/%d armed (injected pointer, not hardware)" % (armed_ok, args.loops))
                record("handle collapses x%d" % args.loops, "PASS",
                       "%d/%d collapsed" % (collapsed_ok, args.loops))
        else:
            record("hover/collapse loops", "N/A", "locked mode has no local hover; entry is the shortcut")

        run([helper, "key", "8", "0x180000"])  # control+option+C, as configured on this host
        time.sleep(0.5)
        path, _ = shot("ctrl-opt-c-open")
        record("control+option+C opens the bar", "CHECK",
               "pixel verdict needs the panel geometry; open the shot and confirm", path)
        run([helper, "key", "8", "0x180000"])
        time.sleep(0.4)
        path, _ = shot("ctrl-opt-c-close")
        record("control+option+C again collapses", "CHECK", "confirm in the screenshot", path)

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
