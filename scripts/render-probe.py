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
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_identity

DERIVED = os.path.join(ROOT, "build-render-probe")


def readable_texts(pane):
    """Every string the page vends to an assistive client, top and bottom of the scroll."""
    texts = set()
    for key in ("readableContent", "readableContentExpanded", "readableContentScrolled"):
        for node in pane.get(key) or []:
            text = node.get("text")
            if text:
                texts.add(text)
    return texts


def texts_of(pane, key):
    """What one reading pass vended, kept apart from the other passes.

    Merging the passes into one set is what let a collapsed section read as clean:
    the rows above the fold and the rows that only exist once the section is open
    look identical in a union, and only the second set can prove the lower half of
    the page was ever looked at.
    """
    return set(node.get("text") for node in pane.get(key) or [] if node.get("text"))


def paired_control(nodes, title):
    """The control in the row labelled `title`: the nearest one to its right.

    SwiftUI gives the control no label of its own, so a row is identified by the
    label beside it. Doing it by tree order instead would pair whatever control
    happened to come next, which is not the same claim.
    """
    rows = [node for node in nodes if node.get("text") == title]
    best = None
    for row in rows:
        candidates = [node for node in nodes
                      if node.get("role") == "AXPopUpButton"
                      and abs(node.get("y", 0) - row.get("y", 0)) < 26
                      and node.get("x", 0) > row.get("x", 0)]
        candidates.sort(key=lambda node: node["x"] - row["x"])
        if candidates and (best is None or candidates[0]["x"] - row["x"] < best[0]):
            best = (candidates[0]["x"] - row["x"], candidates[0])
    return best[1] if best else None


def verify_panes(report, refusals, out_dir):
    """Check each pane against the expectations its own page produced."""
    def expect(ok, message):
        if not ok:
            refusals.append(message)

    captures = {}
    seen_texts = {}
    for name in ("streamPane", "videoPane", "appPane"):
        pane = report.get(name)
        if not isinstance(pane, dict):
            refusals.append("the probe reported no %s pass at all" % name)
            continue
        # The app may open a window of its own during launch; that is not the claim
        # under test. What must never happen is the settings page living in a second
        # window, so that is the part refused.
        expect(pane.get("windowsAddedHostingSettings") == [],
               "%s put the page in another window: %r" % (name, pane.get("windowsAddedHostingSettings")))
        expect(pane.get("viewsAdded") == 1,
               "%s added %r views, expected the one embedded page" % (name, pane.get("viewsAdded")))
        expect(pane.get("storedPane") == pane.get("requestedPane"),
               "%s asked for pane %r but the page stored %r"
               % (name, pane.get("requestedPane"), pane.get("storedPane")))
        expect(pane.get("presentedAfterDismiss") is False, "%s was left presented after dismiss" % name)
        expect(pane.get("stillMountedAfterDismiss") is False, "%s was left mounted after dismiss" % name)
        if pane.get("capture"):
            captures[name] = pane["capture"]

        nodes = pane.get("readableContent") or []
        expect(len(nodes) > 0,
               "%s vends no readable content, so nothing on it could be checked "
               "(the accessibility channel came back empty)" % name)
        expectation = pane.get("expectations")
        expect(isinstance(expectation, dict), "%s reported no expectations" % name)
        if not isinstance(expectation, dict):
            continue
        expect(expectation.get("expectationsFromPageModel") is True,
               "%s was measured against a stand-in model, not the page's own" % name)
        texts = readable_texts(pane)

        if name == "videoPane":
            for expected in expectation.get("videoStrings") or []:
                expect(expected in texts,
                       "the video page does not display %r, the sentence its own rules chose" % expected[:48])
            titles = expectation.get("controlTitles") or {}
            for key, enabled_key, title_key in (
                    ("frameInterpolation", "expectedFrameInterpolationEnabled", "frameInterpolation"),
                    ("upscaling", "expectedUpscalingEnabled", "upscaling")):
                title = titles.get(title_key)
                expect(bool(title), "%s: no title to identify the %s row with" % (name, key))
                if not title:
                    continue
                control = paired_control(nodes, title)
                expect(control is not None,
                       "%s: the %s row has no control beside it, so its state cannot be read" % (name, title))
                if control is None:
                    continue
                want = expectation.get(enabled_key)
                expect(control.get("enabled") is want,
                       "%s is %s but the page's own rules say %s (%r)"
                       % (title, "live" if control.get("enabled") else "disabled",
                          "live" if want else "disabled", control.get("text")))

        if name == "appPane":
            # The capability matrix lives in a DisclosureGroup that ships collapsed,
            # and a collapsed SwiftUI group vends nothing inside it. Measured on a
            # clean launch every row of it is absent from the tree; measured on a
            # machine where somebody once opened it, every row is there. Checking the
            # merged text of all passes let the second machine certify the first, so
            # the claims are checked against the pass taken after the section was
            # pressed open, and the press is only believable when the page itself
            # said it was shut.
            shut_words = expectation.get("advancedSectionCollapsedLabel")
            open_words = expectation.get("advancedSectionExpandedLabel")
            expect(bool(shut_words) and bool(open_words),
                   "the page gave no wording for the Advanced section's state, so the "
                   "reading pass cannot be tied to the section being open at all")
            before_opening = texts_of(pane, "readableContent")
            after_opening = texts_of(pane, "readableContentExpanded")
            if shut_words in before_opening:
                expect(int(pane.get("disclosuresPressed") or 0) >= 1,
                       "%s says the Advanced section is shut and the probe pressed nothing, "
                       "so %d capability rows were never on the page to be compared"
                       % (name, len(expectation.get("capabilityRows") or [])))
            expect(open_words in after_opening,
                   "%s read its capability claims from a pass in which the Advanced section "
                   "is still shut, so nothing below it was seen" % name)
            expect(shut_words not in after_opening,
                   "%s claims the section is open but the page still reads %r, so the "
                   "capability rows beside that word were not on screen" % (name, shut_words))
            for row in expectation.get("capabilityRows") or []:
                for field in ("title", "availability", "detail"):
                    value = row.get(field)
                    if value:
                        expect(value in after_opening,
                               "the capability matrix does not show %s's %s (%r)"
                               % (row.get("id"), field, value[:44]))

        seen_texts[name] = texts
    # Selecting a pane has to change what is on the page, not merely what is stored.
    # The three panes are expected to read differently; if two of them vend the same
    # text, the selection never reached the content the user is looking at.
    names = [name for name in ("streamPane", "videoPane", "appPane") if seen_texts.get(name)]
    for index in range(len(names)):
        for other in names[index + 1:]:
            expect(seen_texts[names[index]] != seen_texts[other],
                   "%s and %s vend exactly the same text, so switching panes changed nothing "
                   "a reader can see" % (names[index], other))

    if len(captures) == 3:
        digests = {}
        for name, capture in captures.items():
            path = capture if os.path.isabs(capture) else os.path.join(out_dir or ".", capture)
            if not os.path.exists(path):
                refusals.append("%s capture %r is missing" % (name, capture))
                continue
            with open(path, "rb") as handle:
                digests[name] = hashlib.sha256(handle.read()).hexdigest()
        if len(digests) == 3:
            expect(len(set(digests.values())) == 3,
                   "the three panes drew the same pixels (%r), so the pane selection never reached "
                   "the render" % {k: v[:8] for k, v in digests.items()})


def verify(report, out_dir=None):
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
    # The presenter being asked to close, and the control on the page reaching the
    # presenter, are different claims. The exit the player uses is the second one.
    expect(report.get("backControlPressReachedPresenter") is True,
           "the page never ran the closure the back control runs, so the control reaches nothing")
    expect(report.get("presentedAfterBackControl") is False,
           "pressing the back control left the page presented, so the control never reached "
           "the presenter")
    expect(report.get("mountedAfterBackControl") is False,
           "pressing the back control left the page mounted in the window content")
    # Handing the keyboard back is a claim only a window that can hold the keyboard
    # can answer, so it is required where the probe window was key and reported as
    # unanswerable everywhere else -- an offscreen probe window is never key.
    expect(not (report.get("probeWindowIsKeyWindow") and report.get("focusOnPageAfterBackControl")),
           "the page kept the keyboard after a close in a window that can hold one")
    expect(report.get("titleAfterBackControl") == report.get("titleBeforePresent"),
           "pressing the back control did not give the window title back (%r after %r)"
           % (report.get("titleAfterBackControl"), report.get("titleBeforePresent")))

    pixels = report.get("settingsPagePixels") or {}
    stddev = pixels.get("stddev")
    distinct = pixels.get("distinctColours")
    expect(isinstance(stddev, (int, float)) and stddev >= 0.08,
           "the page drew no variation at all (stddev %r)" % stddev)
    expect(isinstance(distinct, int) and distinct >= 40,
           "the page drew %r distinct colours, which is not a rendered page" % distinct)

    materials = report.get("materialLayers") or []
    expect(len(materials) > 0, "no backdrop or material layer in the page: no Liquid Glass is composited")

    verify_panes(report, refusals, out_dir)
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
    return os.path.join(DERIVED, "Build", "Products", "Debug", project_identity.product_name() + ".app")


def env_developer_dir():
    if os.environ.get("DEVELOPER_DIR"):
        return os.environ["DEVELOPER_DIR"]
    probe = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True)
    return probe.stdout.strip() or "/Applications/Xcode.app/Contents/Developer"


def run(app, out, timeout):
    home = os.path.join(out, "home")
    shutil.rmtree(home, ignore_errors=True)
    os.makedirs(home)
    binary = os.path.join(app, "Contents", "MacOS",
                                   project_identity.bundle_executable(app))
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


def sample_panes():
    """A miniature of a real report, built from the shapes the probe emits.

    The geometry matters: a row is a label at one x and its control to the right at
    the same y, which is how `paired_control` finds it. Faked without that, the
    pairing rule would never be exercised and could break unseen.
    """
    video_expectation = {
        "expectationsFromPageModel": True,
        "videoStrings": ["cannot interpolate here", "runtime path", "off"],
        "controlTitles": {"frameInterpolation": "Frame interpolation", "upscaling": "Upscaling"},
        "expectedFrameInterpolationEnabled": False,
        "expectedUpscalingEnabled": True,
    }
    video_nodes = [
        {"role": "AXStaticText", "text": "Frame interpolation", "x": 300, "y": 474},
        {"role": "AXPopUpButton", "text": "VT low latency", "enabled": False, "x": 900, "y": 474},
        {"role": "AXStaticText", "text": "Upscaling", "x": 300, "y": 579},
        {"role": "AXPopUpButton", "text": "MetalFX", "enabled": True, "x": 900, "y": 579},
        {"role": "AXStaticText", "text": "cannot interpolate here", "x": 300, "y": 451},
        {"role": "AXStaticText", "text": "runtime path", "x": 300, "y": 300},
        {"role": "AXStaticText", "text": "off", "x": 800, "y": 300},
    ]

    def pane(pane_id, nodes, expectation, capture, **extra):
        report = {"requestedPane": pane_id, "storedPane": pane_id, "windowsAdded": [],
                "windowsAddedHostingSettings": [], "viewsAdded": 1,
                "presentedAfterDismiss": False, "stillMountedAfterDismiss": False,
                "readableContent": nodes, "expectations": expectation, "capture": capture}
        report.update(extra)
        return report

    stream_expectation = {"expectationsFromPageModel": True, "videoStrings": ["runtime path", "off"]}
    stream_nodes = [node for node in video_nodes if node["text"] in ("runtime path", "off")]
    app_expectation = {
        "expectationsFromPageModel": True, "videoStrings": [],
        "advancedSectionCollapsedLabel": "Collapsed",
        "advancedSectionExpandedLabel": "Expanded",
        "capabilityRows": [{"id": "enhancement.vtLowLatencyFI", "title": "VT interpolation",
                            "availability": "Unavailable", "detail": "no slots on this Mac"}],
    }
    # The fixture models a first run: the section is shut, so the matrix rows exist
    # only in the pass taken after the triangle was pressed. A fixture that started
    # open would test the collapsed path nowhere.
    app_nodes = [
        {"role": "AXDisclosureTriangle", "text": "", "x": 280, "y": 120},
        {"role": "AXStaticText", "text": "Capability Status", "x": 300, "y": 120},
        {"role": "AXStaticText", "text": "Collapsed", "x": 900, "y": 120},
    ]
    app_nodes_open = [
        app_nodes[0], app_nodes[1],
        {"role": "AXStaticText", "text": "Expanded", "x": 900, "y": 120},
        {"role": "AXStaticText", "text": "VT interpolation", "x": 300, "y": 200},
        {"role": "AXStaticText", "text": "Unavailable", "x": 700, "y": 200},
        {"role": "AXStaticText", "text": "no slots on this Mac", "x": 300, "y": 180},
    ]
    return {
        "streamPane": pane(0, stream_nodes, stream_expectation, SAMPLE_CAPTURES[0]),
        "videoPane": pane(1, video_nodes, video_expectation, SAMPLE_CAPTURES[1]),
        "appPane": pane(3, app_nodes, app_expectation, SAMPLE_CAPTURES[2],
                        disclosureTriangles=1, advancedSectionCollapsed=True,
                        forcedTheSectionShut=True, disclosuresPressed=1,
                        readableContentExpanded=app_nodes_open),
    }


SAMPLE_CAPTURES = ["probe-fixture-stream.png", "probe-fixture-video.png", "probe-fixture-app.png"]


def write_fixture_captures(out_dir):
    """Three captures that differ, because three identical ones would fail the rule."""
    paths = []
    for index, name in enumerate(SAMPLE_CAPTURES):
        path = os.path.join(out_dir, name)
        with open(path, "wb") as handle:
            handle.write(b"png-fixture-%d" % index)
        paths.append(path)
    return paths


def self_test():
    """The verifier has to be able to fail, or it certifies whatever it is shown."""
    failures = 0
    with tempfile.TemporaryDirectory(prefix="render-probe-fixture-") as out:
        previous = os.getcwd()
        os.chdir(out)
        try:
            write_fixture_captures(out)
            good = {"windowsAddedByPresentingSettings": [], "viewsAddedToWindowContent": 1,
                    "overlayInsideWindowContent": True, "overlayAlpha": 1.0,
                    "presentedAfterDismiss": False, "overlayStillMountedAfterDismiss": False,
                    "backControlPressReachedPresenter": True, "titleBeforePresent": "Moonlight",
                    "presentedAfterBackControl": False, "mountedAfterBackControl": False,
                    "focusOnPageAfterBackControl": False, "probeWindowIsKeyWindow": False,
                    "titleAfterBackControl": "Moonlight",
                    "settingsPagePixels": {"stddev": 0.21, "distinctColours": 77},
                    "materialLayers": ["CABackdropLayer x4"]}
            good.update(sample_panes())
            if verify(good):
                print("FAIL the verifier refused a report that satisfies every rule: %s" % verify(good))
                failures += 1
            else:
                print("ok   the verifier accepts a page that is embedded, drawn, composites glass, "
                      "and says what its rules say")

            def video():
                return good["videoPane"]

            cases = [
                ("settings opened a second window", lambda report: report.update(
                    {"windowsAddedByPresentingSettings": ["NSPanel/Settings"]})),
                ("the page is not embedded", lambda report: report.update({"overlayInsideWindowContent": False})),
                ("two pages stacked instead of one", lambda report: report.update({"viewsAddedToWindowContent": 2})),
                ("the fade never finished", lambda report: report.update({"overlayAlpha": 0.0})),
                ("dismiss left the page mounted", lambda report: report.update({"overlayStillMountedAfterDismiss": True})),
                ("the back control presses on air", lambda report: report.update(
                    {"presentedAfterBackControl": True, "mountedAfterBackControl": True,
                     "focusOnPageAfterBackControl": True})),
                ("the back control runs against a box nothing owns", lambda report: report.update(
                    {"backControlPressReachedPresenter": False, "presentedAfterBackControl": True})),
                ("closing by the back control keeps the window title", lambda report: report.update(
                    {"titleAfterBackControl": "Settings"})),
                ("the page keeps the keyboard in a window that can hold one", lambda report: report.update(
                    {"probeWindowIsKeyWindow": True, "focusOnPageAfterBackControl": True})),
                ("nothing was drawn", lambda report: report.update(
                    {"settingsPagePixels": {"stddev": 0.001, "distinctColours": 2}})),
                ("no material is composited", lambda report: report.update({"materialLayers": []})),
                ("the report is empty", lambda report: report.update({"windowsAddedByPresentingSettings": None})),
                ("no panes were probed at all", lambda report: [report.pop(name, None) for name in
                                                         ("streamPane", "videoPane", "appPane")]),
                ("a pane vends nothing readable", lambda report: report["videoPane"].update({"readableContent": []})),
                ("a pane was measured against a stand-in model",
                 lambda report: report["videoPane"]["expectations"].update({"expectationsFromPageModel": False})),
                ("the page drops the sentence its rules chose",
                 lambda report: report["videoPane"].update({"readableContent": [node for node in report["videoPane"]["readableContent"]
                                                              if node["text"] != "cannot interpolate here"]})),
                ("the interpolation picker stays live while the rules say it must not",
                 lambda report: report["videoPane"].update({"readableContent": [
                     dict(node, enabled=True) if node["text"] == "VT low latency" else node
                     for node in report["videoPane"]["readableContent"]]})),
                ("the upscaling picker is disabled while the rules say it is live",
                 lambda report: report["videoPane"].update({"readableContent": [
                     dict(node, enabled=False) if node["text"] == "MetalFX" else node
                     for node in report["videoPane"]["readableContent"]]})),
                ("the row lost its control entirely",
                 lambda report: report["videoPane"].update({"readableContent": [node for node in report["videoPane"]["readableContent"]
                                                              if node["text"] != "MetalFX"]})),
                ("the capability matrix hides what Video Toolbox can do",
                 lambda report: report["appPane"].update({"readableContentExpanded": [
                     node for node in report["appPane"]["readableContentExpanded"]
                     if node["text"] != "Unavailable"]})),
                ("the collapsed section was never opened but its wording is claimed",
                 lambda report: report["appPane"].update({"readableContentExpanded": [
                     node for node in report["appPane"]["readableContentExpanded"]
                     if node["text"] != "Expanded"]})),
                ("the probe swears it opened a section that was shut",
                 lambda report: report["appPane"].update({"disclosuresPressed": 0})),
                ("the matrix is read from the pass that never opened anything",
                 lambda report: report["appPane"].update(
                     {"readableContentExpanded": report["appPane"]["readableContent"],
                      "advancedSectionCollapsed": False, "disclosuresPressed": 0})),
                ("the page stopped saying which state the section is in",
                 lambda report: report["appPane"]["expectations"].update(
                     {"advancedSectionExpandedLabel": ""})),
                ("selecting a pane does not change what is drawn",
                 lambda report: report["videoPane"].update({"capture": SAMPLE_CAPTURES[0]})),
                ("the pane selection never reached the page",
                 lambda report: report["streamPane"].update(
                     {"readableContent": list(report["videoPane"]["readableContent"])})),
                ("asking for a pane did not stick", lambda report: report["videoPane"].update({"storedPane": 0})),
            ]
            for what, mutation in cases:
                doctored = json.loads(json.dumps(good))
                mutation(doctored)
                refused = verify(doctored, out)
                print("%-4s %s" % ("ok" if refused else "FAIL", what))
                if not refused:
                    print("     the verifier accepted it")
                    failures += 1
        finally:
            os.chdir(previous)
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
    report = run(app, out, min(args.timeout, 300))
    if report is None:
        return 1

    print("\n-- what the render reported --")
    print("windows opened by presenting settings: %r" % report.get("windowsAddedByPresentingSettings"))
    print("page mounted as: %r inside the window content: %r (alpha %r)"
          % (report.get("overlayClass"), report.get("overlayInsideWindowContent"), report.get("overlayAlpha")))
    print("materials composited: %r" % report.get("materialLayers"))
    print("page pixels: %s" % report.get("settingsPagePixels"))
    print("backdrop read-through: %r" % report.get("readThroughPageWhere"))
    for name in ("streamPane", "videoPane", "appPane"):
        pane = report.get(name) or {}
        expectation = pane.get("expectations") or {}
        print("%-10s readable rows: %3d | measured against the page's own model: %r | %r"
              % (name, len(pane.get("readableContent") or []),
                 expectation.get("expectationsFromPageModel"),
                 expectation.get("enhancementAvailability")))
        print("%-10s section shut as displayed: %r | triangles found: %r | pressed: %r | "
              "readable rows once open: %3d"
              % ("", pane.get("advancedSectionCollapsed"), pane.get("disclosureTriangles"),
                 pane.get("disclosuresPressed"), len(pane.get("readableContentExpanded") or [])))
    print("artifacts: %s" % ", ".join(sorted(name for name in os.listdir(out) if name.endswith(".png"))))

    refusals = verify(report, out)
    for refusal in refusals:
        print("FAIL %s" % refusal)
    for refusal in report.get("failures", []):
        print("note the probe itself also refused: %s" % refusal)
    print("%d render-probe failures" % len(refusals))
    return 1 if refusals else 0


if __name__ == "__main__":
    sys.exit(main())
