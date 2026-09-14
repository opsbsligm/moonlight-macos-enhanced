#!/usr/bin/env python3
"""Prove that the settings page is embedded in its own window and composites glass.

Two of the six goals are visual, and for a long time both were answered with
"needs a human eye". The human eye was unavailable, so the claims sat unverified
while the gates stayed green -- a green gate that cannot see is not a gate.

The app carries a Debug-only entry point, inert unless ML_RENDER_PROBE is set,
that drives the production presenter through the production call against a window
of its own and then measures what happened. This script builds that Debug binary,
runs it with HOME pointed at a scratch directory so the database and preferences
under test are the probe's own and nobody's real settings are touched, and reads
the report back.

What it proves:
  * presenting settings does not open a window (the page lives in the window it
    was given, as one added view inside that window's own content view);
  * the fade finishes and dismissal unmounts cleanly;
  * the page really draws (a flat capture means the render never happened);
  * a Liquid Glass material is actually composited, measured from the Core
    Animation layer tree (CABackdropLayer and friends), because SwiftUI materials
    do not appear as AppKit view classes and the hosting view's own name contains
    "Glass" without meaning anything.

What it does not prove: how good it looks over a live stream. The page body sits
on a deliberate opaque base, so how much of the window backdrop reads through is
reported and not asserted -- zero is the designed behaviour there.

Usage: render-probe.py [--app path] [--out dir] [--self-test] [--timeout N]
"""
import argparse, json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIVED = os.path.join(ROOT, "build-render-probe")


def verify(report):
    """Return every way this report says the product is wrong."""
    refusals = []

    def expect(ok, message):
        if not ok:
            refusals.append(message)

    added = report.get("windowsAddedByPresentingSettings")
    expect(added == [], "settings opened %d extra window(s): %s" % (len(added or []), added))
    expect(report.get("viewsAddedToWindowContent") == 1,
           "the page added %r views to the window content, expected the one embedded page"
           % report.get("viewsAddedToWindowContent"))
    expect(report.get("overlayInsideWindowContent") is True,
           "the page is not inside the window's own content view")
    alpha = report.get("overlayAlpha")
    expect(isinstance(alpha, (int, float)) and alpha >= 0.99,
           "the page never finished fading in (alpha %r)" % alpha)
    expect(report.get("presentedAfterDismiss") is False, "the presenter still reports settings after dismiss")
    expect(report.get("overlayStillMountedAfterDismiss") is False, "the page is still mounted after dismiss")

    pixels = report.get("settingsPagePixels") or {}
    stddev = pixels.get("stddev")
    distinct = pixels.get("distinctColours")
    expect(isinstance(stddev, (int, float)) and stddev >= 0.08,
           "the page drew no variation at all (stddev %r)" % stddev)
    expect(isinstance(distinct, int) and distinct >= 40,
           "the page drew %r distinct colours, which is not a rendered page" % distinct)

    materials = report.get("materialLayers") or []
    expect(len(materials) > 0, "no backdrop or material layer in the page: no Liquid Glass is composited")
    return refusals


def build(timeout):
    env = dict(os.environ, DEVELOPER_DIR=env_developer_dir())
    cmd = ["xcodebuild", "-project", os.path.join(ROOT, "Moonlight.xcodeproj"),
           "-scheme", "Moonlight for macOS", "-configuration", "Debug",
           "-destination", "platform=macOS,arch=arm64",
           "-derivedDataPath", DERIVED, "build"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=env, timeout=timeout)
    if proc.returncode != 0:
        tail = [line for line in proc.stdout.splitlines() if "error:" in line][:6]
        print("FAIL the Debug build of the probe did not succeed")
        for line in tail:
            print("     %s" % line.strip())
        return None
    return os.path.join(DERIVED, "Build", "Products", "Debug", "Moonlight.app")


def env_developer_dir():
    if os.environ.get("DEVELOPER_DIR"):
        return os.environ["DEVELOPER_DIR"]
    probe = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True)
    return probe.stdout.strip() or "/Applications/Xcode.app/Contents/Developer"


def run(app, out, timeout):
    home = os.path.join(out, "home")
    shutil.rmtree(home, ignore_errors=True)
    os.makedirs(home)
    binary = os.path.join(app, "Contents", "MacOS", "Moonlight")
    if not os.path.exists(binary):
        print("FAIL no executable at %s" % binary)
        return None
    env = dict(os.environ, HOME=home, ML_RENDER_PROBE="1", ML_RENDER_PROBE_OUTPUT=out)
    try:
        proc = subprocess.run([binary], capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        print("FAIL the probe did not exit within %d s, so it never reached a verdict" % timeout)
        return None
    print(proc.stderr.strip()[-500:])
    path = os.path.join(out, "report.json")
    if not os.path.exists(path):
        print("FAIL the probe wrote no report: the Debug entry point did not run (exit %d)"
              % proc.returncode)
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def self_test():
    """The verifier has to be able to fail, or it certifies whatever it is shown."""
    good = {"windowsAddedByPresentingSettings": [], "viewsAddedToWindowContent": 1,
            "overlayInsideWindowContent": True, "overlayAlpha": 1.0,
            "presentedAfterDismiss": False, "overlayStillMountedAfterDismiss": False,
            "settingsPagePixels": {"stddev": 0.21, "distinctColours": 77},
            "materialLayers": ["CABackdropLayer x4"]}
    failures = 0
    if verify(good):
        print("FAIL the verifier refused a report that satisfies every rule")
        failures += 1
    else:
        print("ok   the verifier accepts a page that is embedded, drawn and composites glass")
    cases = [
        ("settings opened a second window", {"windowsAddedByPresentingSettings": ["NSPanel/Settings"]}),
        ("the page is not embedded", {"overlayInsideWindowContent": False}),
        ("two pages stacked instead of one", {"viewsAddedToWindowContent": 2}),
        ("the fade never finished", {"overlayAlpha": 0.0}),
        ("dismiss left the page mounted", {"overlayStillMountedAfterDismiss": True}),
        ("nothing was drawn", {"settingsPagePixels": {"stddev": 0.001, "distinctColours": 2}}),
        ("no material is composited", {"materialLayers": []}),
        ("the report is empty", {"windowsAddedByPresentingSettings": None}),
    ]
    for what, mutation in cases:
        doctored = dict(good)
        doctored.update(mutation)
        refused = verify(doctored)
        print("%-4s %s" % ("ok" if refused else "FAIL", what))
        if not refused:
            print("     the verifier accepted it")
            failures += 1
    print("%d render-probe self-test failures" % failures)
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app")
    parser.add_argument("--out")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    out = args.out or tempfile.mkdtemp(prefix="render-probe-")
    os.makedirs(out, exist_ok=True)
    app = args.app or build(args.timeout)
    if app is None:
        return 1
    report = run(app, out, min(args.timeout, 180))
    if report is None:
        return 1

    print("\n-- what the render reported --")
    print("windows opened by presenting settings: %r" % report.get("windowsAddedByPresentingSettings"))
    print("page mounted as: %r inside the window content: %r (alpha %r)"
          % (report.get("overlayClass"), report.get("overlayInsideWindowContent"), report.get("overlayAlpha")))
    print("materials composited: %r" % report.get("materialLayers"))
    print("page pixels: %s" % report.get("settingsPagePixels"))
    print("backdrop read-through: %r" % report.get("readThroughPageWhere"))
    print("artifacts: %s" % ", ".join(sorted(name for name in os.listdir(out) if name.endswith(".png"))))

    refusals = verify(report)
    for refusal in refusals:
        print("FAIL %s" % refusal)
    for refusal in report.get("failures", []):
        print("note the probe itself also refused: %s" % refusal)
    print("%d render-probe failures" % len(refusals))
    return 1 if refusals else 0


if __name__ == "__main__":
    sys.exit(main())
