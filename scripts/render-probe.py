#!/usr/bin/env python3
"""Prove that the settings page is embedded in its own window and composites glass.

Two of the six goals are visual, and for a long time both were answered with
"needs a human eye". The human eye was unavailable, so the claims sat unverified
while the gates stayed green -- a green gate that cannot see is not a gate.

The app carries a Debug-only entry point, inert unless ML_RENDER_PROBE is set,
that drives the production presenter through the production call against a window
of its own and then measures what happened. This script builds that Debug binary,
runs it with HOME pointed at a scratch directory and reads the report back. That
scratch home is not the isolation it was described as for four rounds: the support
directory the app opens resolves out of the account record rather than out of
`$HOME` (`DatabaseSingleton.m:100`, measured 2026-09-25 by an empty temporary home
that still reported the machine's own library), so the probe reads and writes the
real store. For this probe that is harmless -- it opens the settings page, draws it,
and asks for no hosts -- but it is why the probe must never be given a flag that
deletes or plants anything, and why the seed and the reap live in the two probes that
count the library by who wrote it.

What it proves:
  * presenting settings does not open a window (the page lives in the window it
    was given, as one added view inside that window's own content view);
  * the fade finishes and dismissal unmounts cleanly;
  * the page really draws (a flat capture means the render never happened);
  * captures use the composited pixels of the probe's own visible window;
    ScreenCaptureKit's current-process API needs no access to other apps;
  * a Liquid Glass material is actually composited, measured from the Core
    Animation layer tree (CABackdropLayer and friends), because SwiftUI materials
    do not appear as AppKit view classes and the hosting view's own name contains
    "Glass" without meaning anything;
  * how many times each page goes to the database to open, and that closing it
    does not go there at all -- the read count is what turns the leak rate in
    `leak-audit.py` from a coincidence into an accounted-for number, because
    `getHosts` builds a fresh graph per host in the library on every call.

What it does not prove: how good it looks over a live stream. The page body sits
on a deliberate opaque base, so how much of the window backdrop reads through is
reported and not asserted -- zero is the designed behaviour there.

Usage: render-probe.py [--app path] [--out dir] [--self-test] [--timeout N]
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, time

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


# Two colours of red, and they must not share a sentence. A page that was never captured says
# nothing about rendering; a page that was captured and came back uniform is a rendering
# regression. The probe used to answer both with zeroes, so the reader said "the page drew no
# variation at all" about a capture channel that had refused to start, while the probe's own
# stderr carried the truth -- job 6840 left seven lines of `[render-probe] own window capture
# failed` that no judge ever read. The report now carries `captureFailure` in place of the
# measurements, and this is the one place that decides which of the two sentences is earned.
#
# The thresholds are unchanged by this: 0.02 and 40 sit under the real page's measured 0.0702
# with 53 distinct colours on a light-theme display, and above a flat fixture's 0.001.
PIXEL_STDDEV_MIN = 0.02
PIXEL_DISTINCT_MIN = 40

# ScreenCaptureKit refuses to start a stream (error -3811, "cannot start stream playback")
# when the machine has no active display, and a headless CI mini sleeps its panel between
# jobs. Measured on the mini on 2026-11-09: `CGGetActiveDisplayList` returned 0 with the
# panel asleep, and `caffeinate -u` brought it back to 1 active display in 1.1 s. So the
# probe wakes the panel and waits for the display list to answer before it asks for pixels;
# without this, every pane in the report says "capture refused" and reads like a rendering
# regression when it is a sleeping monitor.
DISPLAY_WAKE_SECONDS = 10
DISPLAY_WAIT_SECONDS = 20


def active_display_count():
    """How many displays macOS considers active, without compiling anything.

    CoreGraphics is reachable through ctypes, so this runs on a runner with no toolchain
    in play and leaves no build artefact behind. A failure to load the framework returns
    None, which means "no idea" and must not be read as "zero displays".
    """
    try:
        import ctypes
        core_graphics = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        count = ctypes.c_uint32(0)
        if core_graphics.CGGetActiveDisplayList(8, None, ctypes.byref(count)) != 0:
            return None
        return int(count.value)
    except Exception:
        return None


def ensure_display(timeout=DISPLAY_WAIT_SECONDS, hold_seconds=None):
    """Return a sentence about the display, waking the panel if nothing is active.

    This is a runtime prerequisite, not a judgement: the probe cannot tell a page that did
    not render from a machine that had nothing to render onto, so it removes the second
    cause instead of reporting it. A machine that stays display-less is reported in the
    same sentence, so a reader sees the environment before blaming the build.

    Waking the panel once is not enough: the panel can fall asleep again while the probe
    app is still running, and the refusal that follows reads exactly like the page never
    drew. When `hold_seconds` is given, a second `caffeinate` keeps the panel awake for
    that long after the wake, and this function returns its handle so the caller can stop
    it once the run is done. Pipeline 1596 refused every capture with the panel reported
    awake *at launch time* and the TCC grant read back as allowed -- the only remaining
    environment variable between those two facts and the pixels is the panel staying up
    for the whole run, so the probe removes it the same honest way.
    """
    count = active_display_count()
    if count is None:
        return "display state unknown (CoreGraphics could not be queried)", None
    if count > 0:
        awake = "%d active display(s)" % count
        return _hold_display(awake, hold_seconds), None
    try:
        subprocess.run(["caffeinate", "-u", "-t", str(DISPLAY_WAKE_SECONDS)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=DISPLAY_WAKE_SECONDS + 10)
    except Exception as error:
        return ("the panel could not be woken (%s), so ScreenCaptureKit will refuse to start"
                % error), None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        count = active_display_count()
        if count:
            break
    else:
        return ("the panel stayed asleep with no active display, so every capture in this run "
                "will be refused by the capture channel"), None
    return _hold_display("woke the panel: %d active display(s)" % count, hold_seconds)


def _hold_display(sentinel, hold_seconds):
    """Pair an awake panel with a keep-awake process for the whole probe run.

    The keep-awake path must exist on *both* entries into the awake state: a panel that
    was already awake when the probe started never went through the wake code, and
    pipeline 1596 refused every capture with exactly that entry -- reported awake at
    launch, TCC allowed, and the display nevertheless gone by the time ScreenCaptureKit
    was asked for pixels. The returned handle is the caller's responsibility to stop.
    """
    if not hold_seconds:
        return sentinel, None
    try:
        hold = subprocess.Popen(["caffeinate", "-u", "-t", str(int(hold_seconds))],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "%s; holding it awake for %ds" % (sentinel, hold_seconds), hold
    except Exception as error:
        return ("%s, but the hold-awake process could not start (%s), so the panel can "
                "still fall asleep mid-run" % (sentinel, error)), None
        time.sleep(0.5)
    return ("the panel stayed asleep with no active display, so every capture in this run "
            "will be refused by the capture channel")


def artefact_absence(pixels):
    """`("no-capture" | "no-artefact" | None, the probe's own sentence)`.

    There are two ways a fold has no PNG to open and they are not interchangeable: the capture
    channel refused, so no pixels were ever looked at, or the pixels were sampled and the
    encoder or volume refused the write, so the numbers are real but nothing can be opened and
    checked against them. The probe withholds the filename in both cases, so this is the one
    place that decides when a missing name is expected -- and it returns which of the two it
    was, because the two sentences a reader deserves are different.
    """
    if pixels.get("captureFailure"):
        return "no-capture", pixels["captureFailure"]
    if pixels.get("captureWriteFailure"):
        return "no-artefact", pixels["captureWriteFailure"]
    return None, None


def pixel_refusal(pixels, what, require_distinct=True):
    """Why this pixel measurement refuses the build, or None when it does not.

    `require_distinct` is off for the USB initial fold because that check has only ever
    measured luminance spread there; adding a colour floor to it would refuse captures every
    earlier run accepted, which is a different claim wearing this wave's clothes.
    """
    kind, reason = artefact_absence(pixels)
    if kind == "no-capture":
        return ("%s was never captured, so nothing here can say whether it drew: %s"
                % (what, reason))
    if kind == "no-artefact":
        # A third colour, and it is not a rendering fault either: the pixels were sampled and
        # the numbers are real, but the PNG a reader would check them against never reached the
        # disk, so the measurement cannot be reopened or hashed. Refusing it in the flat-page
        # vocabulary would send a reader to diff an application change that did not happen.
        return ("%s was measured but its artefact was never written, so its numbers cannot be "
                "checked: %s" % (what, reason))
    stddev = pixels.get("stddev")
    if not (isinstance(stddev, (int, float)) and stddev >= PIXEL_STDDEV_MIN):
        return "%s drew no variation at all (stddev %r)" % (what, stddev)
    if require_distinct:
        distinct = pixels.get("distinctColours")
        if not (isinstance(distinct, int) and distinct >= PIXEL_DISTINCT_MIN):
            return ("%s drew %r distinct colours, which is not a rendered page"
                    % (what, distinct))
    return None


def verify_panes(report, refusals, out_dir):
    """Check each pane against the expectations its own page produced."""
    def expect(ok, message):
        if not ok:
            refusals.append(message)

    # One entry per pane that answered the question, keyed by what it said: either the PNG it
    # wrote, or why there is none. A pane that says both is itself the defect this wave is
    # about, so it is recorded under both and the count below refuses it -- counting the two
    # maps separately would let a contradictory pane look like two panes and hide it.
    captures = {}
    uncaptured = {}
    seen_texts = {}
    for name in ("streamPane", "videoPane", "appPane", "devicesPane"):
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
        expect(pane.get("panePreferenceRestored") is True,
               "%s left the user's saved pane selection changed" % name)
        # A pane has to answer one of two questions, and which one it answers decides the
        # wording: either it names a PNG that must open, or it says the fold was never
        # measured and quotes why. The probe used to do both -- naming a file its own capture
        # channel had refused to write -- so a missing artefact was read as a second, separate
        # defect. Remembering the refusal lets the reader keep the two sentences apart.
        pixels = pane.get("pixels") or {}
        absence, absence_reason = artefact_absence(pixels)
        # A measured fold has to name the API that drew it; without that, a fallback
        # capture would read as the primary channel having done its job.
        if pixels.get("stddev") is not None:
            expect(pixels.get("captureChannel") in ("SCK", "CG", "CACHE"),
                   "%s reports pixel measurements but names no capture channel, so the "
                   "report cannot say which API drew it" % name)
        if absence:
            uncaptured[name] = (absence, absence_reason)
        if pane.get("capture"):
            captures[name] = pane["capture"]
        elif not absence:
            # The same size lie in the opposite shape: a fold that reports measurements but
            # names no file has numbers with nothing behind them, and a fold that names neither
            # leaves the digest comparison below silently short of a pane. One sentence per
            # pane, because both halves of that are the one defect of not answering.
            if pixels.get("stddev") is not None:
                expect(False, "%s reports pixel measurements but names no capture file, so the "
                              "numbers here have no artefact behind them" % name)
            else:
                expect(False, "%s said neither which capture file it wrote nor why there is "
                              "none, so this report cannot say whether the pane was ever drawn"
                       % name)

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

        if name == "devicesPane":
            pixels = pane.get("initialPixels") or {}
            if pixels.get("stddev") is not None:
                expect(pixels.get("captureChannel") in ("SCK", "CG", "CACHE"),
                       "the USB permission page's initial fold reports pixel measurements "
                       "but names no capture channel, so the report cannot say which API "
                       "drew it")
            refusal = pixel_refusal(pixels, "the USB permission page's initial fold",
                                    require_distinct=False)
            if not artefact_absence(pixels)[0]:
                # The probe writes no filename unless the PNG is on disk, so a missing name
                # beside an absence is the same fact twice. Asking for the file again would
                # read as a second defect and hide which one to fix.
                initial = pane.get("initialCapture")
                expect(bool(initial), "USB permission page supplied no initial-fold capture")
                if initial:
                    initial_path = initial if os.path.isabs(initial) else os.path.join(out_dir or ".", initial)
                    expect(os.path.isfile(initial_path), "USB initial-fold capture is missing")
            expect(refusal is None, refusal)
            hub_title = expectation.get("deviceHubsSectionTitle")
            hub_detail = expectation.get("deviceHubsSectionDetail")
            expect(bool(hub_title) and bool(hub_detail), "USB grouping expectations are missing")
            initial_texts = texts_of(pane, "readableContent")
            if hub_title and hub_title in initial_texts:
                expect(bool(hub_detail), "USB hub section supplies no scope explanation")
                expect(hub_detail not in initial_texts, "USB hubs did not start collapsed")
                expect(int(pane.get("hubDisclosuresPressed") or 0) >= 1,
                       "USB hubs were never expanded for the reachability pass")
                expect(hub_detail in texts_of(pane, "readableContentExpanded"),
                       "expanded USB hub group exposes no explanation")
            required = expectation.get("devicePermissionStrings")
            expect(isinstance(required, list) and len(required) >= 5,
                   "USB pane supplied no permission scope expectations")
            for expected in required or []:
                expect(expected in texts, "USB permissions page does not display %r" % expected)

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
    # The four panes are expected to read differently; if two of them vend the same
    # text, the selection never reached the content the user is looking at.
    names = [name for name in ("streamPane", "videoPane", "appPane", "devicesPane") if seen_texts.get(name)]
    for index in range(len(names)):
        for other in names[index + 1:]:
            expect(seen_texts[names[index]] != seen_texts[other],
                   "%s and %s vend exactly the same text, so switching panes changed nothing "
                   "a reader can see" % (names[index], other))

    # Each fold without an artefact earns its own sentence naming why, rather than one
    # collective "the four panes did not all supply final captures", which reads as the probe
    # having forgotten to take a screenshot. The two absences are still two different faults:
    # one says nothing about rendering, the other says the pixels were real and unopenable.
    for name in sorted(uncaptured):
        absence, reason = uncaptured[name]
        if absence == "no-artefact":
            expect(False, "%s was measured but its artefact was never written, so its numbers "
                          "cannot be reopened and checked: %s" % (name, reason))
        else:
            expect(False, "%s was never captured to disk, so nothing here can say whether it "
                          "drew: %s" % (name, reason))
    if len(captures) == 4:
        digests = {}
        for name, capture in captures.items():
            path = capture if os.path.isabs(capture) else os.path.join(out_dir or ".", capture)
            if not os.path.exists(path):
                if name in uncaptured:
                    refusals.append("%s names capture %r while also reporting none (%s), so the "
                                    "report contradicts itself"
                                    % (name, capture, uncaptured[name][1]))
                else:
                    refusals.append("%s capture %r is missing" % (name, capture))
                continue
            with open(path, "rb") as handle:
                digests[name] = hashlib.sha256(handle.read()).hexdigest()
        if len(digests) == 4:
            expect(len(set(digests.values())) == 4,
                   "the four panes drew the same pixels (%r), so the pane selection never reached "
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
    # unanswerable everywhere else -- the probe may not have keyboard focus.
    expect(not (report.get("probeWindowIsKeyWindow") and report.get("focusOnPageAfterBackControl")),
           "the page kept the keyboard after a close in a window that can hold one")
    expect(report.get("titleAfterBackControl") == report.get("titleBeforePresent"),
           "pressing the back control did not give the window title back (%r after %r)"
           % (report.get("titleAfterBackControl"), report.get("titleBeforePresent")))

    pixels = report.get("settingsPagePixels") or {}
    # An absolute luminance spread is a weak claim about a drawn page: this one is a
    # light theme, where 97% of the sampled luminance sits near white, so a fully drawn
    # page measured 0.0702 against a flat fixture's 0.001. The old 0.08 floor was above
    # the number the real page produces, which is how a gate that had never once run on
    # a real display came to fail a build that rendered correctly. 0.02 keeps a 3.5x
    # margin under the measured page and 20x over flat, and the two fixtures below hold
    # both ends of that line down. `pixel_refusal` is what keeps the unmeasured case out
    # of that sentence.
    expect(pixel_refusal(pixels, "the settings page") is None,
           pixel_refusal(pixels, "the settings page"))
    # A measured page has to say which API drew it: the producer stamps `captureChannel`
    # on every measurement block, and a fallback that silently disappears would otherwise
    # read as the primary channel having done its job.
    if pixels.get("stddev") is not None:
        expect(pixels.get("captureChannel") in ("SCK", "CG", "CACHE"),
               "the settings page reports pixel measurements but names no capture channel, "
               "so the report cannot say which API drew it")

    materials = report.get("materialLayers") or []
    expect(len(materials) > 0, "no backdrop or material layer in the page: no Liquid Glass is composited")

    verify_panes(report, refusals, out_dir)
    verify_host_reads(report, refusals)
    return refusals


# Historical full-library read counts, measured on 2026-09-25 by three runs of
# this build (one at 3 visit cycles, two at 6) against the machine's own one-host library:
# videoPane 1, appPane 1, streamPane 3, and nothing on every dismissal, the same numbers at
# both cycle counts. streamPane is the odd one because its own view model reads the host list
# per section rather than once per visit; that is the number the byte ceiling in
# `leak-audit.py` has been absorbing ever since it was written, and it is now written down
# where a change to it has to be argued about. These are historical numbers, not
# the current expectation: cp22 removes full-library reads from settings.
#
# The counts are exact rather than bounded above, deliberately: how many times a page opens
# the database is decided by the structure of the code that opens it, not by the machine, the
# library, or the load, so a range would only hide a doubling until the byte ceiling swallowed
# it. One read builds one graph per host in the library (DataManager.m:205 builds a fresh
# TemporaryHost per row every call), so a read added to a cell binding is a graph added per
# host per visit -- which is the leak, measured before it reaches the byte count.
# cp22: settings now fetch connection descriptors, never cyclic application libraries.
# The independent libraryEnd read must still increment the production counter below.
HOST_READS_WHEN_OPENED = {"videoPane": 0, "appPane": 0, "streamPane": 0, "devicesPane": 0}


def verify_host_reads(report, refusals):
    """Check how often the pages went to the database, and that the counter is wired up.

    The instrument is a debug-only atomic counter that `getHosts` itself bumps, so the first
    claim against any run is that the count exists and that a read this function can see for
    itself was registered by it. A report without the fields is a Release build or deleted
    instrumentation, either of which would make every other read number here a zero.
    """
    def expect(ok, message):
        if not ok:
            refusals.append(message)

    for name, want in sorted(HOST_READS_WHEN_OPENED.items()):
        pane = report.get(name)
        if not isinstance(pane, dict):
            continue
        opened = pane.get("hostReadsDuringPresent")
        expect(isinstance(opened, int),
               "%s recorded no hostReadsDuringPresent, so either the read counter was compiled"
               " out or it was deleted -- and then nothing in this report says how often the"
               " page goes to the database (it reports %r)" % (name, opened))
        if not isinstance(opened, int):
            continue
        expect(opened == want,
               "%s opened with %d library read(s) where this tree measures %d. Each read builds"
               " one TemporaryHost per host in the library, so a read added here is a graph per"
               " host per visit; if the shape changed on purpose, change"
               " HOST_READS_WHEN_OPENED in that same commit and say why in its message"
               % (name, opened, want))
        closed = pane.get("hostReadsDuringDismiss")
        expect(closed == 0,
               "%s read the library %r time(s) while being dismissed. Measured here it does not"
               " read at all on the way out, and a read during teardown is one that happens"
               " while the page is already on its way to being released" % (name, closed))

    cycles = report.get("memoryCycles")
    if not isinstance(cycles, dict):
        return
    expect(cycles.get("status") == "completed",
           "the memory visit cycles did not complete: %r" % cycles.get("status"))
    try:
        requested = int(cycles.get("requested", ""))
    except (TypeError, ValueError):
        requested = 0
    expect(1 <= requested <= 64 and cycles.get("completed") == requested,
           "the memory visit count differs from its request")
    panes = cycles.get("requestedPanesPerCycle")
    expect(panes == [0 if index % 2 == 0 else 6 for index in range(max(0, min(requested, 64)))],
           "the memory visits did not alternate stream and USB pages")
    scans = cycles.get("deviceScanResults")
    expect(isinstance(scans, list) and len(scans) == requested // 2 and
           all(result in ("read", "unreadable") for result in scans),
           "the USB visits did not each display a completed device scan")
    spans = cycles.get("readsPerCycle")
    expect(isinstance(spans, list) and len(spans) > 0,
           "the visit cycles recorded no readsPerCycle, so the growth being measured cannot be"
           " tied to the reads that cause it (it reports %r)" % (spans,))
    if isinstance(spans, list) and spans:
        expect(all(isinstance(value, int) for value in spans),
               "readsPerCycle holds a non-number, so the per-visit read count is not a count: %r" % (spans,))
        expect(len(set(spans)) == 1,
               "the visits did not read the library the same number of times (%r). A page that"
               " reads more on each trip gets slower the longer somebody leaves it open, which"
               " is a different fault from a constant count and cannot be fixed by shrinking a"
               " ceiling" % (spans,))
    expect(isinstance(cycles.get("readsDuringCycles"), int),
           "the visit cycles recorded no readsDuringCycles, so the total is missing and the"
           " per-visit spans cannot be checked against it: %r" % (cycles.get("readsDuringCycles"),))
    unattributed = cycles.get("readsUnattributedToCycles")
    expect(isinstance(unattributed, int) and unattributed == 0,
           "%r library read(s) happened outside every visit cycle while the status says they all"
           " completed -- a read nobody was charging for is how a count stops adding up"
           % (unattributed,))
    expect(isinstance(cycles.get("libraryEndReads"), int) and cycles["libraryEndReads"] >= 1,
           "counting the library at the end of the cycles did not register as a library read"
           " (%r), so the counter is not attached to the read path and every read number in this"
           " report is a zero" % (cycles.get("libraryEndReads"),))


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


def run(app, out, timeout, hold_seconds=None):
    home = os.path.join(out, "home")
    shutil.rmtree(home, ignore_errors=True)
    os.makedirs(home)
    binary = os.path.join(app, "Contents", "MacOS",
                                   project_identity.bundle_executable(app))
    if not os.path.exists(binary):
        print("FAIL no executable at %s" % binary)
        return None
    # The panel has to be awake before ScreenCaptureKit is asked for pixels, or every pane
    # reports a refused capture that reads exactly like a page which never rendered.
    display_sentence, hold = ensure_display(hold_seconds=hold_seconds)
    print("[render-probe] display: %s" % display_sentence)
    # LaunchServices, not a direct exec. A directly exec'd binary is attributed by macOS to
    # the calling lineage -- the shell, then the runner -- so the ScreenCaptureKit grant for
    # the bundle id is never consulted and every capture answers -3801 whatever TCC says
    # (docs/history/incidents/tcc-reset-recovery-2026-11-08.md). `open` attributes the
    # process to the bundle, which is the attribution the grant is written against.
    #
    # Two consequences of `open` measured on the mini on 2026-11-09, both load-bearing here:
    #   * `--env NAME=VALUE` does reach the app (verified for ML_RENDER_PROBE_OUTPUT), and
    #     `--stderr` captures what the app writes, so the diagnostics survive the launch;
    #   * `open -W` waits but does NOT propagate the app's exit status -- a bundle that
    #     exits 1 makes `open` exit 0. So this function never quotes a return code as a
    #     verdict: `report.json` is the verdict, and a missing report says the entry point
    #     never ran whatever `open` claimed.
    stderr_path = os.path.join(out, "probe-stderr.txt")
    command = ["open", "-n", "-W", "--stderr", stderr_path,
               "--env", "HOME=" + home, "--env", "ML_RENDER_PROBE=1",
               "--env", "ML_RENDER_PROBE_OUTPUT=" + out, app]
    try:
        subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # `open` going away does not take the app with it, and an app still holding the probe
        # window would keep the next run's window discovery honest-by-accident.
        subprocess.run(["pkill", "-f", binary], capture_output=True, text=True)
        print("FAIL the probe did not exit within %d s, so it never reached a verdict" % timeout)
        return None
    finally:
        if hold is not None:
            try:
                hold.terminate()
                hold.wait(timeout=5)
            except Exception:
                try:
                    hold.kill()
                except Exception:
                    pass
    if os.path.exists(stderr_path):
        with open(stderr_path, encoding="utf-8", errors="replace") as handle:
            print(handle.read().strip()[-500:])
    path = os.path.join(out, "report.json")
    if not os.path.exists(path):
        print("FAIL the probe wrote no report: the Debug entry point did not run "
              "(see %s above)" % os.path.basename(stderr_path))
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

    # The page's own pane tags, not indexes: 0 stream, 1 video, 3 apps. Each page's read
    # count is the one this tree measures, and `verify_host_reads` insists on it.
    PANE_READS = {0: HOST_READS_WHEN_OPENED["streamPane"],
                  1: HOST_READS_WHEN_OPENED["videoPane"],
                  3: HOST_READS_WHEN_OPENED["appPane"],
                  6: HOST_READS_WHEN_OPENED["devicesPane"]}

    def pane(pane_id, nodes, expectation, capture, reads=None, **extra):
        reads = PANE_READS[pane_id] if reads is None else reads
        report = {"requestedPane": pane_id, "storedPane": pane_id, "windowsAdded": [],
                "windowsAddedHostingSettings": [], "viewsAdded": 1,
                "presentedAfterDismiss": False, "stillMountedAfterDismiss": False,
                "panePreferenceRestored": True,
                "readableContent": nodes, "expectations": expectation, "capture": capture,
                # The read counts are part of what a report has to answer, so the fixture
                # answers them. It did not used to, which left the fixture itself the one
                # report the verifier refused, and every refusal after that looked like the
                # fixture's fault rather than the run's.
                "hostReadsDuringPresent": reads,
                "hostReadsDuringDismiss": 0,
                # The producer stamps the API that drew the pane on every measurement
                # block; the fixture answers with the primary channel, and the mutation
                # cases below prove the reader refuses a measurement without it.
                "pixels": {"stddev": 0.21, "distinctColours": 77, "sampled": 4000,
                            "mean": 0.9, "captureChannel": "SCK"}}
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
        "devicesPane": pane(6,
            [{"role": "AXStaticText", "text": value} for value in
             ("USB permissions", "permission only", "USB switch", "local devices", "refresh", "USB hubs")],
            {"expectationsFromPageModel": True, "deviceHubsSectionTitle": "USB hubs",
             "deviceHubsSectionDetail": "hubs remain reachable", "devicePermissionStrings":
             ["USB permissions", "permission only", "USB switch", "local devices", "refresh"]},
            SAMPLE_CAPTURES[3], initialCapture=SAMPLE_CAPTURES[3],
            initialPixels={"stddev": 0.21, "distinctColours": 77, "captureChannel": "SCK"},
            hubDisclosuresPressed=1,
            readableContentExpanded=[{"role": "AXStaticText", "text": "hubs remain reachable"}]),
        "streamPane": pane(0, stream_nodes, stream_expectation, SAMPLE_CAPTURES[0]),
        "videoPane": pane(1, video_nodes, video_expectation, SAMPLE_CAPTURES[1]),
        "appPane": pane(3, app_nodes, app_expectation, SAMPLE_CAPTURES[2],
                        disclosureTriangles=1, advancedSectionCollapsed=True,
                        forcedTheSectionShut=True, disclosuresPressed=1,
                        readableContentExpanded=app_nodes_open),
    }


SAMPLE_CAPTURES = ["probe-fixture-stream.png", "probe-fixture-video.png", "probe-fixture-app.png", "probe-fixture-devices.png"]


def write_fixture_captures(out_dir):
    """Four captures that differ, because identical panes must fail the rule."""
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
                    "settingsPagePixels": {"stddev": 0.21, "distinctColours": 77,
                                            "captureChannel": "SCK"},
                    "materialLayers": ["CABackdropLayer x4"]}
            good.update(sample_panes())
            good["memoryCycles"] = {
                "status": "completed", "requested": "4", "completed": 4,
                "requestedPanesPerCycle": [0, 6, 0, 6],
                "deviceScanResults": ["read", "read"],
                "readsPerCycle": [0, 0, 0, 0], "readsDuringCycles": 0,
                "readsUnattributedToCycles": 0, "libraryEndReads": 1,
            }
            if verify(good):
                print("FAIL the verifier refused a report that satisfies every rule: %s" % verify(good))
                failures += 1
            else:
                print("ok   the verifier accepts a page that is embedded, drawn, composites glass, "
                      "and says what its rules say")

            def video():
                return good["videoPane"]

            cases = [
                ("USB cycles never completed", lambda report: report["memoryCycles"].update(
                    {"status": "device-scan-timeout"})),
                ("USB cycle count is short", lambda report: report["memoryCycles"].update(
                    {"completed": 3})),
                ("USB page was skipped", lambda report: report["memoryCycles"].update(
                    {"requestedPanesPerCycle": [0, 0, 0, 0]})),
                ("one USB scan result is missing", lambda report: report["memoryCycles"].update(
                    {"deviceScanResults": ["read"]})),
                ("USB scan timed out", lambda report: report["memoryCycles"].update(
                    {"deviceScanResults": ["read", "timeout"]})),
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
                    {"settingsPagePixels": {"stddev": 0.001, "distinctColours": 2}})),                ("a drawn page that never says which API drew it", lambda report: report.update(
                    {"settingsPagePixels": {"stddev": 0.0702, "distinctColours": 53}})),
                ("a pane fold with measurements but no capture channel", lambda report: report["videoPane"].update(
                    {"pixels": {"stddev": 0.31, "distinctColours": 88, "sampled": 4000, "mean": 0.9}})),
                ("the USB initial fold with measurements but no capture channel", lambda report: report["devicesPane"].update(
                    {"initialPixels": {"stddev": 0.21, "distinctColours": 77}})),

                ("a flat colour lifted only by antialiasing noise", lambda report: report.update(
                    {"settingsPagePixels": {"stddev": 0.012, "distinctColours": 44}})),
                ("no material is composited", lambda report: report.update({"materialLayers": []})),
                ("the report is empty", lambda report: report.update({"windowsAddedByPresentingSettings": None})),
                ("USB grouping expectations absent", lambda report: report["devicesPane"]["expectations"].update(
                    {"deviceHubsSectionTitle": "", "deviceHubsSectionDetail": ""})),
                ("USB hubs unreachable", lambda report: report["devicesPane"].update(
                    {"hubDisclosuresPressed": 0, "readableContentExpanded": []})),
                ("USB initial fold is flat", lambda report: report["devicesPane"].update(
                    {"initialPixels": {"stddev": 0.001}})),
                ("USB initial fold capture missing", lambda report: report["devicesPane"].update(
                    {"initialCapture": "missing-initial.png"})),
                ("USB page missing entirely", lambda report: report.pop("devicesPane")),
                ("USB page hides permission-only scope", lambda report: report["devicesPane"].update(
                    {"readableContent": [node for node in report["devicesPane"]["readableContent"]
                                         if node["text"] != "permission only"]})),
                ("probe leaves selected pane changed", lambda report: report["devicesPane"].update(
                    {"panePreferenceRestored": False})),
                ("no panes were probed at all", lambda report: [report.pop(name, None) for name in
                                                         ("streamPane", "videoPane", "appPane", "devicesPane")]),
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
                ("a pane resumed reading the cyclic application library",
                 lambda report: report["videoPane"].update(
                     {"hostReadsDuringPresent": HOST_READS_WHEN_OPENED["videoPane"] + 1})),
                ("a pane read the library while it was being dismissed",
                 lambda report: report["streamPane"].update({"hostReadsDuringDismiss": 1})),
            ]
            # The other end of the line: the numbers this page really drew on a player's
            # display, measured on 2026-09-28 from the probe's own screenshot (mean 0.9765,
            # stddev 0.0702, 53 distinct colours). A threshold that refuses them refuses the
            # build, so the passing case is pinned here too and not only in a comment.
            lit = json.loads(json.dumps(good))
            lit.update({"settingsPagePixels": {"stddev": 0.0702, "distinctColours": 53,
                                               "captureChannel": "SCK"}})
            accepted = verify(lit, out)
            print("%-4s the page drawn on a real light-theme display still passes"
                  % ("ok" if not accepted else "FAIL"))
            if accepted:
                print("     the verifier refused numbers a real page produces")
                failures += 1
            # The CG window-list fallback is a first-class capture path: when ScreenCaptureKit
            # refuses the stream on the runner session, the report still passes -- it names
            # the channel it used instead of pretending SCK drew the pixels.
            cgrun = json.loads(json.dumps(good))
            for key in ("settingsPagePixels",) + tuple(
                    name for name in ("streamPane", "videoPane", "appPane", "devicesPane")):
                block = cgrun.get(key)
                if isinstance(block, dict) and block.get("stddev") is not None:
                    block["captureChannel"] = "CG"
                elif isinstance(block, dict):
                    for sub in ("pixels", "initialPixels"):
                        inner = block.get(sub)
                        if isinstance(inner, dict) and inner.get("stddev") is not None:
                            inner["captureChannel"] = "CG"
            cgaccepted = verify(cgrun, out)
            print("%-4s a report captured through the window-list fallback still passes"
                  % ("ok" if not cgaccepted else "FAIL"))
            if cgaccepted:
                print("     the verifier refused the fallback channel: %s"
                      % "; ".join(cgaccepted)[:200])
                failures += 1

            # Which sentence a red earns is the claim of this wave, so a check that only asked
            # "did it refuse?" would pass the very bug being fixed: the old verifier refused the
            # uncaptured page too, in the words of a rendering regression. Both colours are
            # therefore pinned by wording, not just by severity.
            wording_cases = [
                ("an uncaptured page says the channel failed, not that the page is flat",
                 lambda report: report.update({"settingsPagePixels": {
                     "captureFailure": "capture refused: cannot start capture"}}),
                 "never captured", ["no variation", "rendered as flat", "distinct colours"]),
                ("a genuinely flat page still says flat, and does not blame the channel",
                 lambda report: report.update({"settingsPagePixels": {
                     "stddev": 0.001, "distinctColours": 2}}),
                 "drew no variation", ["never captured"]),
                ("an uncaptured pane names the channel instead of a missing file",
                 lambda report: report["videoPane"].update({
                     "capture": "probe-fixture-never-written.png",
                     "pixels": {"captureFailure": "own window not offered for capture"}}),
                 "never captured", ["is missing"]),
                # The write can fail after a good capture, and that is a third thing: the
                # numbers are real, so "nothing here can say whether it drew" would be false,
                # and the page drew, so "no variation" would be false too.
                ("a pane whose PNG failed to land says the artefact is missing, not that the "
                 "page was never captured or flat",
                 lambda report: report["videoPane"].update({
                     "capture": "probe-fixture-never-written.png",
                     "pixels": {"stddev": 0.31, "distinctColours": 88, "sampled": 4000,
                                "captureWriteFailure": "the volume refused the write"}}),
                 "artefact was never written", ["no variation", "never captured"]),
                ("a pane that measured pixels and named no file says so, instead of the "
                 "digest comparison going quiet about it",
                 lambda report: report["videoPane"].update(
                     {"pixels": {"stddev": 0.31, "distinctColours": 88, "sampled": 4000},
                      "capture": None}),
                 "no artefact behind them", ["never captured", "no variation"]),
                ("a pane that answers neither question is named, not counted as a capture",
                 lambda report: report["videoPane"].update({"capture": None, "pixels": None}),
                 "cannot say whether the pane was ever drawn", ["no variation"]),
                # A report that does both is the exact defect this wave removes on the producer
                # side; the reader has to refuse it too, or an older binary keeps passing.
                ("a pane that names a file and reports it never happened is refused as "
                 "uncaptured, and its file is never hashed as if it were a capture",
                 lambda report: report["videoPane"].update({
                     "pixels": {"captureFailure": "own window not offered for capture"}}),
                 "never captured", ["drew the same pixels"]),
            ]
            for what, mutation, wanted, forbidden in wording_cases:
                doctored = json.loads(json.dumps(good))
                mutation(doctored)
                refused = " ".join(verify(doctored, out))
                wrong = []
                if wanted not in refused:
                    wrong.append("no refusal said %r" % wanted)
                wrong += ["%r appears in the verdict" % phrase
                          for phrase in forbidden if phrase in refused]
                print("%-4s %s" % ("ok" if not wrong else "FAIL", what))
                if wrong:
                    print("     %s" % "; ".join(wrong))
                    print("     verdict was: %s" % refused[:300])
                    failures += 1

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
    # The panel must stay awake for the whole run, not just at launch: pass the run
    # timeout straight through as the keep-awake horizon (plus a margin so a probe that
    # runs exactly to its limit is not captured in the last second of a lapsed hold).
    report = run(app, out, min(args.timeout, 300),
                 hold_seconds=min(args.timeout, 300) + 30)
    if report is None:
        return 1

    print("\n-- what the render reported --")
    print("windows opened by presenting settings: %r" % report.get("windowsAddedByPresentingSettings"))
    print("page mounted as: %r inside the window content: %r (alpha %r)"
          % (report.get("overlayClass"), report.get("overlayInsideWindowContent"), report.get("overlayAlpha")))
    print("materials composited: %r" % report.get("materialLayers"))
    print("page pixels: %s" % report.get("settingsPagePixels"))
    print("backdrop read-through: %r" % report.get("readThroughPageWhere"))
    for name in ("streamPane", "videoPane", "appPane", "devicesPane"):
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
