#!/usr/bin/env python3
"""Hold the Liquid Glass surface to the rules that were decided for it.

A glass look is easy to fake and easy to erode. The failures these rules catch are
all ones that compile, run and look plausible in a code review:

  * a hand-made blur, gradient or .regularMaterial standing in for the system
    material, which is exactly what produced the see-through-the-desktop panel
    first reported by a user;
  * a warm accent, which the design brief rules out;
  * a glass transition given its own literal duration, so the panel and the tab
    pill stop moving together;
  * a springy curve, which the brief rejects.

The rules are a pure function over file contents. --self-test breaks each rule on
a fixture to prove it fires, because a rule that never fires is worse than none.
"""
import argparse, os, re, sys

GLASS_DIR = "Limelight/macOS/ViewControllers/LiquidGlass"
COLOUR = re.compile(r"red:\s*([0-9.]+)\s*,\s*green:\s*([0-9.]+)\s*,\s*blue:\s*([0-9.]+)")
# The glass is the system's to draw, so nothing hand-made may stand in for it. The
# blur is the spelling that first produced the see-through-the-desktop panel, and a
# gradient laid over the panel is the same failure in another form: it reads as depth
# in a screenshot while the panel behind it stops bending what is actually there.
# Every prohibited spelling has to be listed, because a rule that catches six of nine
# is a rule a gradient walks through.
FAKE_GLASS = ("NSVisualEffectView", "UIBlurEffect", ".blur(radius:", ".regularMaterial",
              ".thinMaterial", ".thickMaterial",
              "LinearGradient(", "RadialGradient(", "AngularGradient(",
              ".linearGradient(", ".radialGradient(", ".angularGradient(")
# Everything that overshoots and settles back. The brief rejects it for glass.
SPRINGY = re.compile(r"\.bouncy\b|\.spring\s*\(|interpolatingSpring|\bSpring\s*\(|bounce\s*:")
DURATION = re.compile(r"duration:\s*[0-9.]+")


def strip_comments(text):
    out = []
    for line in text.split("\n"):
        if line.lstrip().startswith("//"):
            continue
        out.append(re.sub(r"//.*$", "", line))
    return "\n".join(out)


def project_problems(project_text, bar_text):
    """problems with the build settings the tab bar's guarded role depends on."""
    problems = []
    # The guard only means something if the project still declares the condition for the
    # SDK that has the symbol; without it the accepted tabs look silently disappears.
    if "#if ML_APPKIT_TABS_ROLE" in bar_text:
        if "SWIFT_ACTIVE_COMPILATION_CONDITIONS[sdk=macosx27.*]" not in project_text:
            problems.append("the tabs role waits for a build condition no configuration "
                            "declares, so no build ever sets it")
    return problems


def check(files):
    """files maps basename to raw source. Returns human readable violations."""
    problems = []
    combined = "\n".join(strip_comments(t) for t in files.values())

    native_segments = "NSSegmentedControl" in combined and "control.segmentStyle = .rounded" in combined
    if ".glassEffect(" not in combined and not native_segments:
        problems.append("no native .glassEffect anywhere in the glass surface")
    if ".glassEffect(" in combined and "GlassEffectContainer(" not in combined:
        problems.append("glass elements are not grouped in a GlassEffectContainer, "
                        "so they cannot merge, cull or morph together")

    for needle in FAKE_GLASS:
        if needle in combined:
            problems.append("%s stands in for the system glass" % needle)

    for name, text in files.items():
        hit = SPRINGY.search(strip_comments(text))
        if hit:
            problems.append("%s uses an overshooting curve (%s)" % (name, hit.group(0).strip()))

    bar = files.get("LiquidGlassTabBar.swift", "")
    # NSSegmentedControl.role = .tabs hides the selected segment's label. Measured inside a
    # real key window over a light page base: the darkest pixel in the selected segment's
    # label band is 0.12 without a role and 0.92 with .tabs, under every combination of
    # segmentStyle, borderShape, controlSize and per-segment widths tried, including a bare
    # control with no overrides. The tab naming the page the user is reading is the one tab
    # that goes white-on-white, so the role stays unset until a system build draws its
    # selected tab with readable text -- and the guard that used to make it compile on one
    # SDK alone is gone with it, because a condition nothing reads is a second way to lie.
    # The segmented control draws its own selection: on macOS 27 that is the system's
    # tabs look, guarded so the macOS 26 SDK CI builds against still compiles. The bar
    # overlays nothing; hand-drawn stands-ins for that surface were measured and refused.
    if ".role = " in strip_comments(bar) and "#if ML_APPKIT_TABS_ROLE" not in strip_comments(bar):
        problems.append("the tabs role compiles unguarded, so the macOS 26 SDK cannot build the tab bar")
    match = COLOUR.search(strip_comments(bar))
    if match is None:
        problems.append("the glass accent colour could not be read from TabBarConfig")
    else:
        r, g, b = (float(match.group(i)) for i in (1, 2, 3))
        if not (b > r and g > r):
            problems.append("accent is warm: red %.2f is not below green %.2f and blue %.2f"
                            % (r, g, b))

    duration = re.search(r"animationDuration\s*:\s*Double\s*=\s*([0-9.]+)", strip_comments(bar))
    if duration is None:
        problems.append("TabBarConfig no longer declares animationDuration")
    elif abs(float(duration.group(1)) - 0.22) > 1e-9:
        problems.append("the shared glass transition is %ss, not the agreed 0.22s"
                        % duration.group(1))

    for name, text in files.items():
        body = strip_comments(text)
        for found in DURATION.finditer(body):
            if "TabBarConfig.animationDuration" not in body:
                problems.append("%s sets its own animation duration" % name)
            break

    presenter = files.get("SettingsOverlayPresenter.swift", "")
    if presenter and "TabBarConfig.animationDuration" not in strip_comments(presenter):
        problems.append("the overlay animates with something other than the shared duration")

    return problems


FIXTURE = {
    "LiquidGlassTabBar.swift": """
        static let accentCoolBlue = Color(
          .sRGB, red: 0.34, green: 0.62, blue: 0.95, opacity: 1.0
        )
        static let animationDuration: Double = 0.22
        GlassEffectContainer(spacing: 6) {
          view.glassEffect(.regular.tint(accentCoolBlue), in: shape)
        }
        """,
    "SettingsOverlayPresenter.swift": """
        context.duration = TabBarConfig.animationDuration
        """,
}


def mutate(text, old, new):
    assert old in text, "fixture drift: " + old
    return text.replace(old, new, 1)


def self_test():
    cases = []
    cases.append(("the compliant fixture", FIXTURE, False))

    unguarded = dict(FIXTURE)
    unguarded["LiquidGlassTabBar.swift"] = FIXTURE["LiquidGlassTabBar.swift"] + (
        "\n        let control = NSSegmentedControl()\n        control.role = .tabs\n        ")
    cases.append(("tabs role compiled without the SDK guard", unguarded, True))

    guarded = dict(FIXTURE)
    guarded["LiquidGlassTabBar.swift"] = FIXTURE["LiquidGlassTabBar.swift"] + (
        "\n        let control = NSSegmentedControl()\n        #if ML_APPKIT_TABS_ROLE\n"
        "        control.role = .tabs\n        #endif\n        ")
    cases.append(("tabs role behind the SDK guard", guarded, False))

    native = dict(FIXTURE)
    native["LiquidGlassTabBar.swift"] = native["LiquidGlassTabBar.swift"].replace(
        "GlassEffectContainer(spacing: 6) {\n          view.glassEffect(.regular.tint(accentCoolBlue), in: shape)\n        }",
        "let control = NSSegmentedControl()\n        control.segmentStyle = .rounded")
    cases.append(("system segmented control owns its glass", native, False))

    warm = dict(FIXTURE)
    warm["LiquidGlassTabBar.swift"] = mutate(FIXTURE["LiquidGlassTabBar.swift"],
                                             "red: 0.34, green: 0.62, blue: 0.95",
                                             "red: 0.95, green: 0.45, blue: 0.20")
    cases.append(("a warm accent", warm, True))

    slow = dict(FIXTURE)
    slow["LiquidGlassTabBar.swift"] = mutate(FIXTURE["LiquidGlassTabBar.swift"],
                                             "animationDuration: Double = 0.22",
                                             "animationDuration: Double = 0.4")
    cases.append(("a retimed shared transition", slow, True))

    fake = dict(FIXTURE)
    fake["LiquidGlassTabBar.swift"] = mutate(FIXTURE["LiquidGlassTabBar.swift"],
                                             "GlassEffectContainer(spacing: 6) {",
                                             "NSVisualEffectView()\n        GlassEffectContainer(spacing: 6) {")
    cases.append(("a hand-made blur replacing the material", fake, True))

    # One fixture per prohibited spelling. A single planted blur proves the loop runs
    # and nothing about the other needles, which is how three gradient APIs went
    # undetected while this rule was reported as covering gradients.
    for needle in FAKE_GLASS:
        planted = dict(FIXTURE)
        planted["LiquidGlassTabBar.swift"] = mutate(
            FIXTURE["LiquidGlassTabBar.swift"],
            "GlassEffectContainer(spacing: 6) {",
            "%s\n        GlassEffectContainer(spacing: 6) {" % needle)
        cases.append(("planted %s" % needle, planted, True))

    ungrouped = dict(FIXTURE)
    ungrouped["LiquidGlassTabBar.swift"] = mutate(FIXTURE["LiquidGlassTabBar.swift"],
                                                 "GlassEffectContainer(spacing: 6) {", "VStack {")
    cases.append(("glass elements outside a container", ungrouped, True))

    noglass = dict(FIXTURE)
    noglass["LiquidGlassTabBar.swift"] = mutate(FIXTURE["LiquidGlassTabBar.swift"],
                                               ".glassEffect(", ".tint(")
    cases.append(("no native glass at all", noglass, True))

    springy = dict(FIXTURE)
    springy["LiquidGlassTabBar.swift"] = mutate(FIXTURE["LiquidGlassTabBar.swift"],
                                                "static let animationDuration",
                                                "withAnimation(.bouncy) { label.isHidden = true }\n        static let animationDuration")
    cases.append(("a springy curve", springy, True))

    solo = dict(FIXTURE)
    solo["SettingsOverlayPresenter.swift"] = "withAnimation(.easeInOut(duration: 0.5)) { panel.alpha = 1 }\n"
    cases.append(("an overlay with its own duration", solo, True))

    failures = 0
    # The guard's dependency proves itself like every other rule: the shipped pair passes,
    # and a project that stopped declaring the condition for the SDK is refused.
    project_path = os.path.join(".", "Moonlight.xcodeproj", "project.pbxproj")
    shipped_project = open(project_path, encoding="utf-8").read() if os.path.isfile(project_path) else ""
    shipped_bar = open(os.path.join(".", "Limelight", "macOS", "ViewControllers", "LiquidGlass",
                                    "LiquidGlassTabBar.swift"), encoding="utf-8").read()
    if project_problems(shipped_project, shipped_bar):
        failures += 1
        print("FAIL %-46s expected clean, got %s"
              % ("the shipped project file", project_problems(shipped_project, shipped_bar)))
    else:
        print("ok   %-46s accepted" % "the shipped project file")
    unconfigured = "\n".join(
        line for line in shipped_project.split("\n")
        if "SWIFT_ACTIVE_COMPILATION_CONDITIONS[sdk=macosx27.*]" not in line)
    if not project_problems(unconfigured, shipped_bar):
        failures += 1
        print("FAIL %-46s expected a violation, got clean" % "a project that dropped the guard's condition")
    else:
        print("ok   %-46s refused" % "a project that dropped the guard's condition")

    for what, files, expect_problem in cases:
        problems = check(files)
        if bool(problems) != expect_problem:
            failures += 1
            print("FAIL %-38s expected %s, got %s"
                  % (what, "a violation" if expect_problem else "clean", problems))
        else:
            print("ok   %-38s %s" % (what, "refused" if problems else "accepted"))
    print("%d liquid glass audit self-test failures" % failures)
    return 1 if failures else 0


# --- the panels that sit on top of the stream ------------------------------
# Eight surfaces sit on top of the picture: the performance HUD, the connection warning,
# the mouse-mode hint, the notification banner, the timeout dialog, the reconnect card,
# the log browser, and the menu pill in the titlebar. Seven of them used to build their
# own NSVisualEffectView with NSVisualEffectMaterialHUDWindow -- the material from before
# the liquid-glass APIs -- so the settings page and the tab bar sampled the system glass
# while the panels a player looks at for a whole session did not.
#
# Every one of them now asks GlassOverlayContainer for its background, so this list is no
# longer a debt list but a ratchet: it says what a regression looks like. A panel that
# goes back to drawing its own vibrancy, that sets a material while claiming the
# container, or that masks its corners by hand to get the old look, is refused, and so is
# a panel that disappears from the list without being converted.
GLASS_PANELS = {
    # panel -> (file it lives in, the line that puts it on the container, what it may
    #           never do again)
    "logOverlayContainer": (
        "ViewControllers/StreamViewController+Diagnostics.m",
        "self.logOverlayContainer = [GlassOverlayContainer containerWithCornerRadius:",
        ("self.logOverlayContainer.material", "self.logOverlayContainer.layer.cornerRadius")),
    "overlayContainer": (
        "ViewControllers/StreamViewController+Diagnostics.m",
        "self.overlayContainer = [GlassOverlayContainer containerWithCornerRadius:",
        ("self.overlayContainer.material", "self.overlayContainer.layer.cornerRadius")),
    "connectionWarningContainer": (
        "ViewControllers/StreamViewController+Diagnostics.m",
        "self.connectionWarningContainer = [GlassOverlayContainer containerWithCornerRadius:",
        ("self.connectionWarningContainer.material",
         "self.connectionWarningContainer.layer.cornerRadius")),
    "mouseModeContainer": (
        "ViewControllers/StreamViewController+Diagnostics.m",
        "self.mouseModeContainer = [GlassOverlayContainer containerWithCornerRadius:",
        ("self.mouseModeContainer.material", "self.mouseModeContainer.layer.cornerRadius")),
    "notificationContainer": (
        "ViewControllers/StreamViewController+Diagnostics.m",
        "self.notificationContainer = [GlassOverlayContainer containerWithCornerRadius:",
        ("self.notificationContainer.material", "self.notificationContainer.layer.cornerRadius")),
    "timeoutOverlayContainer": (
        "ViewControllers/StreamViewController+Diagnostics.m",
        "GlassOverlayContainer *container = [GlassOverlayContainer containerWithCornerRadius:",
        ("self.timeoutOverlayContainer.material", "self.timeoutOverlayContainer.layer.mask",
         "container.shadow = shadow")),
    "reconnectGlassCard": (
        "ViewControllers/StreamViewController+Diagnostics.m",
        "self.reconnectGlassCard = [GlassOverlayContainer containerWithCornerRadius:",
        ("self.reconnectGlassCard.material", "self.reconnectOverlayContainer.material")),
    "controlCenterPill": (
        "ViewControllers/StreamViewController+MenuUI.m",
        "GlassOverlayContainer *pill = [GlassOverlayContainer containerWithCornerRadius:",
        ("pill.material", "pill.layer.cornerRadius")),
}

# A panel may only draw vibrancy again if it is named here, and the number of vibrancy
# views built by hand in the panel files has to agree with this list. It is empty: the
# panels are on glass, and a new hand-built one is refused until somebody says why.
PANELS_STILL_ON_VIBRANCY = {}

# The reconnect scrim dims the whole picture rather than being a panel, so it carries no
# material at all -- not glass, not vibrancy. The card floating in it is the glass.
RECONNECT_SCRIM = ("self.reconnectOverlayContainer = [[NSView alloc] initWithFrame:",)

# --- the settings surface --------------------------------------------------
# The stream panels get their glass from GlassOverlayContainer; the settings page gets it
# straight from .glassEffect, one surface per section card and per fold. That makes it the
# part of the app most likely to quietly regress, because every regression here still renders
# and still looks like a card in a screenshot: a GroupBox walks back in, a system
# DisclosureGroup reappears inside a glass card and draws a second frame, or a card keeps
# its glass but leaves the container so the stack stops sampling as one material.
# The list covers the settings panes, the page that hosts them, and the first-run permission
# sheet: a player meets that sheet before any settings page, and it draws the same cards.
# Surfaces, not files: the settings page and the first-run sheet are separate windows, so each
# needs its own container, and the card that draws the glass and the page that supplies the
# container are different files inside one surface. A container shared across two windows would
# be as wrong as one card left outside its own.
SETTINGS_SURFACES = (
    ("settings page", ("ViewControllers/SettingsSharedControls.swift",
                       "ViewControllers/LiquidGlass/LiquidGlassSettingsView.swift")),
    ("first-run permission sheet",
     ("ViewControllers/SettingsHostingController.swift",)),
)
SETTINGS_FILES = tuple(sorted({name for _, files in SETTINGS_SURFACES for name in files}))
# The spellings the settings page moved away from on purpose. Each one still compiles and
# still looks acceptable, which is exactly why they need a rule and not a reviewer.
# GroupBox draws its own frame inside the glass card. A custom DisclosureGroupStyle is the
# subtler one: measured on a standalone harness and then on the render probe, a style with
# a composite label vends two disclosure triangles (one per press path), so a checker that
# presses "every triangle that is there" presses the same group shut again and never sees
# the collapsed matrix below it. The system's default style is the only shape measured to
# be single-triangle and label-readable, so the fold's chrome stays the system's and the
# glass is the card around it.
RETIRED_SETTINGS_CONTAINERS = ("GroupBox(", ".disclosureGroupStyle(")
# The settings cards draw their glass through one shared helper rather than repeating the
# modifier in four places: a card that opts out of the helper gets a different material or
# loses the edge that makes its boundary visible over the washed base. The rule has two
# halves, and the second is the one that stops the first from being a rubber stamp: the
# helper itself has to stay a glassEffect, because .settingsGlassCard() over a
# Color.background is a rule that approves its own removal.
SHARED_CARD_HELPER = "func settingsGlassCard()"
# Where a card asks for the shared glass. The definition of the helper lives in one file;
# every card on every surface spells its request this way, and a surface is allowed to stop
# drawing glass directly only as long as it keeps asking.
SHARED_CARD_CALL = ".settingsGlassCard()"
SHARED_CARD_GLASS = ".glassEffect(.regular, in: cardShape)"


def settings_surface_problems(texts):
    """problems with the settings glass, given {settings file: source}."""
    problems = []
    for name in SETTINGS_FILES:
        if name not in texts:
            problems.append("%s is gone, so nothing is holding the settings glass to its rules" % name)
    if problems:
        return problems
    shared = strip_comments(texts.get("ViewControllers/SettingsSharedControls.swift", ""))
    helper_is_glass = SHARED_CARD_HELPER in shared and SHARED_CARD_GLASS in shared
    for surface, names in SETTINGS_SURFACES:
        body = "\n".join(strip_comments(texts[name]) for name in names if name in texts)
        # A surface may draw its glass directly or hand out the shared card, but it has to do
        # one of the two, and whichever it does it still needs its own container. Skipping the
        # container check for a surface that moved to the helper is how a card ends up glass
        # and stranded: it samples the desktop instead of the page.
        has_glass = ".glassEffect(" in body or (SHARED_CARD_CALL in body and helper_is_glass)
        if not has_glass:
            problems.append("%s has no native .glassEffect at all, so every card on it is "
                            "standing in for the system material again" % surface)
        if has_glass and "GlassEffectContainer(" not in body:
            problems.append("%s has glass surfaces outside a GlassEffectContainer, so its "
                            "cards stop bending the page as one material" % surface)
    for name in SETTINGS_FILES:
        body = strip_comments(texts[name])
        if SHARED_CARD_HELPER in body and SHARED_CARD_GLASS not in body:
            problems.append("%s exposes %s without %s inside it, so the shared settings card "
                            "is no longer the system material it hands out"
                            % (name, SHARED_CARD_HELPER, SHARED_CARD_GLASS))
        for needle in RETIRED_SETTINGS_CONTAINERS:
            if needle in body:
                problems.append("%s puts %s back on the settings page, which draws its own "
                                "frame inside the glass card" % (name, needle))
        for line in body.split("\n"):
            if DURATION.search(line) and "TabBarConfig.animationDuration" not in line:
                problems.append("%s gives a glass transition its own duration: %s"
                                % (name, line.strip()))
                break
    return problems


# --- the host cards ---------------------------------------------------------
# The list of PCs is the first screen a player meets, and its cells now sit on the same
# system glass as the settings cards, through the same container the stream panels use.
# The failures this pins are the ones that still render: a cell that quietly goes back to
# the flat fill behind the artwork, a selection that returns as a paint-over (the pill or
# a blue box) instead of a tint folded into the card, or a card left over a page whose
# wash was removed -- glass with nothing to bend is a grey rectangle that claims a design
# it does not have.
HOST_CARD_FILE = "ViewControllers/HostCell.m"
HOST_CARD_CONTAINER = "[GlassOverlayContainer containerWithCornerRadius:10.0]"
HOST_CARD_TINT = "self.glassCard.tintColor = selected"
# The old selected name: a solid accent pill behind the label. Over a tinted card it
# stacked two "this one" signals and was the older of the two.
HOST_PILL_BG = "self.labelContainer.backgroundColor = selected"
# The wash has to be installed by the controller that owns the window -- Container-
# ViewController, the one object that outlives the navigation between the hosts grid
# and the apps grid -- into the window's content view, and every scroll view on a page
# has to stop drawing over it. Pinning only the variable name let the wash shrink back
# under the toolbar unchallenged; pinning the page that first shipped it let the apps
# grid lose its base the moment the app navigated.
HOST_PAGE_WASH = "[windowHost addSubview:pageBase positioned:NSWindowBelow relativeTo:nil]"
HOST_SCROLL_TRANSPARENT = "scroll.drawsBackground = NO"
APPS_SCROLL_TRANSPARENT = "appsScroll.drawsBackground = NO"


HOST_WATCHED_FILES = (HOST_CARD_FILE,
                      "ViewControllers/HostsViewController.m",
                      "ViewControllers/ContainerViewController.m",
                      "ViewControllers/AppsViewController.m")


def host_card_problems(texts):
    """problems with the host-list cards, given {watched file: source}."""
    problems = []
    missing = [name for name in HOST_WATCHED_FILES if texts.get(name) is None]
    if missing:
        return ["the host-card rules lost %s, so the cards are unwatched" % ", ".join(missing)]
    cell = texts[HOST_CARD_FILE]
    vc = texts["ViewControllers/HostsViewController.m"]
    container = texts["ViewControllers/ContainerViewController.m"]
    apps = texts["ViewControllers/AppsViewController.m"]
    body = strip_comments(cell)
    if HOST_CARD_CONTAINER not in body:
        problems.append("the host card no longer asks the container for its background, "
                        "so the cells are back on a hand-drawn fill")
    if HOST_CARD_TINT not in body:
        problems.append("the host card no longer folds selection into the glass tint, so "
                        "selection is either gone or painted over the material again")
    if HOST_PILL_BG in body:
        problems.append("the host cell puts the selected name pill back, which stacks a "
                        "paint-over on top of the card's own tint")
    if HOST_PAGE_WASH not in strip_comments(container):
        problems.append("the window lost its washed base at its owner, so the cards have "
                        "nothing behind them to bend")
    if HOST_SCROLL_TRANSPARENT not in strip_comments(vc):
        problems.append("the hosts scroll view draws its own background again, which paints "
                        "over the wash the cards need behind them")
    if APPS_SCROLL_TRANSPARENT not in strip_comments(apps):
        problems.append("the apps scroll view draws its own background again, so the grid "
                        "meets an opaque rectangle where the page should show through")
    return problems


def host_card_self_test(repo):
    """Break the host-card rules on the shipped tree and make sure each break is caught."""
    texts = {}
    for name in HOST_WATCHED_FILES:
        path = os.path.join(repo, "Limelight", "macOS", name)
        if not os.path.isfile(path):
            print("FAIL the host-card self-test cannot read %s" % name)
            return 1
        texts[name] = open(path, encoding="utf-8").read()

    def edited(name, old, new):
        copy = dict(texts)
        if old not in copy[name]:
            raise SystemExit("the host-card self-test lost its anchor in %s" % name)
        copy[name] = copy[name].replace(old, new, 1)
        return copy

    cases = [
        ("the shipped host cards", texts, False),
        ("the card back on a hand-drawn fill",
         edited(HOST_CARD_FILE, HOST_CARD_CONTAINER,
                "[[BackgroundColorView alloc] initWithFrame:NSZeroRect]"), True),
        ("selection painted over the glass again",
         edited(HOST_CARD_FILE, HOST_CARD_TINT, "// selection tint removed"), True),
        ("the selected name pill back on the card",
         edited(HOST_CARD_FILE,
                "self.labelContainer.backgroundColor = [NSColor clearColor];",
                HOST_PILL_BG + " ? [NSColor selectedContentBackgroundColor] : [NSColor clearColor];"),
         True),
        ("the page wash pulled out from under the cards",
         edited("ViewControllers/ContainerViewController.m", HOST_PAGE_WASH,
                "// wash removed"), True),
        ("the hosts scroll view painting over the wash again",
         edited("ViewControllers/HostsViewController.m", HOST_SCROLL_TRANSPARENT,
                "scroll.drawsBackground = YES"), True),
        ("the apps scroll view painting over the wash again",
         edited("ViewControllers/AppsViewController.m", APPS_SCROLL_TRANSPARENT,
                "appsScroll.drawsBackground = YES"), True),
    ]
    failures = 0
    for what, files, expect_problem in cases:
        problems = host_card_problems(files)
        if bool(problems) != expect_problem:
            failures += 1
            print("FAIL %-46s expected %s, got %s"
                  % (what, "a violation" if expect_problem else "clean", problems))
        else:
            print("ok   %-46s %s" % (what, "refused" if problems else "accepted"))
    return failures


def settings_self_test(repo):
    """Prove each settings rule fires, using the shipped tree as the compliant baseline."""
    texts = {}
    for name in SETTINGS_FILES:
        path = os.path.join(repo, "Limelight", "macOS", name)
        if not os.path.isfile(path):
            print("FAIL the settings self-test cannot read %s" % name)
            return 1
        texts[name] = open(path, encoding="utf-8").read()

    def edited(name, old, new):
        copy = dict(texts)
        if old not in copy[name]:
            raise SystemExit("the settings self-test lost its anchor in %s" % name)
        copy[name] = copy[name].replace(old, new, 1)
        return copy

    def surface_edits(surface, old, new):
        # Strip the glass from every file of one surface at once. A rule that only fires when the
        # whole app loses its glass is not a rule about this surface.
        copy = dict(texts)
        names = dict(SETTINGS_SURFACES)[surface]
        hits = 0
        for name in names:
            if old in copy[name]:
                copy[name] = copy[name].replace(old, new)
                hits += 1
        if not hits:
            raise SystemExit("the settings self-test lost its anchor in %s" % surface)
        return copy

    def without_shared_card():
        # The page's cards get their glass from the shared helper, so taking the page's glass
        # away means taking both halves: the material inside the helper and the calls that
        # hand it out. Only the calls going missing is the quieter regression, and the helper
        # pin below covers that one.
        copy = dict(texts)
        body = copy[shared_file]
        if SHARED_CARD_GLASS not in body or SHARED_CARD_CALL not in body:
            raise SystemExit("the settings self-test lost its anchor in the shared card")
        copy[shared_file] = (body.replace(SHARED_CARD_GLASS, ".background(.background)")
                                 .replace(SHARED_CARD_CALL, ".background(.background)"))
        return copy

    def drop_containers():
        copy = dict(texts)
        kept = 0
        for name, text in copy.items():
            stripped = text.replace("GlassEffectContainer(", "VStack(")
            kept += text.count("GlassEffectContainer(")
            copy[name] = stripped
        if not kept:
            raise SystemExit("the settings self-test found no container to remove")
        return copy

    shared_file = "ViewControllers/SettingsSharedControls.swift"
    shared = shared_file
    page = "ViewControllers/LiquidGlass/LiquidGlassSettingsView.swift"
    sheet = "ViewControllers/SettingsHostingController.swift"
    cases = [
        ("the shipped settings surface", texts, False),
        ("a section card back in a GroupBox",
         edited(shared, "VStack(alignment: .leading, spacing: 0) {\n      Text(languageManager.localize(title))",
                "GroupBox(\n      content: {\n      VStack(alignment: .leading, spacing: 0) {\n      Text(languageManager.localize(title))"),
         True),
        ("a fold that restyles the disclosure anyway",
         edited(shared, "    .padding(.vertical, 8)\n    .padding(.horizontal, 10)\n    .settingsGlassCard()",
                "    .disclosureGroupStyle(GlassStyleProbe())\n    .padding(.vertical, 8)\n    .padding(.horizontal, 10)\n    .settingsGlassCard()"),
         True),
        ("no container anywhere on the settings surface",
         drop_containers(),
         True),
        ("the settings page with no glass at all",
         without_shared_card(),
         True),
        ("the first-run sheet with no glass at all",
         edited(sheet, SHARED_CARD_CALL, ".background(.background)"),
         True),
        ("the first-run sheet with no container",
         edited(sheet, "GlassEffectContainer(spacing: 20) {", "VStack(spacing: 20) {"),
         True),
        ("a fold with a duration of its own",
         edited(shared, "    .padding(.vertical, 8)\n    .padding(.horizontal, 10)\n    .settingsGlassCard()",
                "    .animation(.easeOut(duration: 0.15), value: expanded.wrappedValue)\n    .padding(.vertical, 8)\n    .padding(.horizontal, 10)\n    .settingsGlassCard()"),
         True),
    ]
    # The pin has to fire while every card still asks for the helper: cards calling a
    # helper that stopped being glass is the regression a call-site check cannot see.
    pin_probe = dict(texts)
    pin_probe[shared_file] = texts[shared_file].replace(SHARED_CARD_GLASS, ".background(.background)", 1)
    pin_problems = settings_surface_problems(pin_probe)

    failures = 0
    if not any("system material it hands out" in problem for problem in pin_problems):
        failures += 1
        print("FAIL %-46s expected the helper pin to fire, got %s"
              % ("the shared card handed out empty", pin_problems))
    else:
        print("ok   %-46s refused" % "the shared card handed out empty")

    for what, files, expect_problem in cases:
        problems = settings_surface_problems(files)
        if bool(problems) != expect_problem:
            failures += 1
            print("FAIL %-46s expected %s, got %s"
                  % (what, "a violation" if expect_problem else "clean", problems))
        else:
            print("ok   %-46s %s" % (what, "refused" if problems else "accepted"))
    return failures


PANEL_FILES = ("ViewControllers/StreamViewController+Diagnostics.m",
               "ViewControllers/StreamViewController+MenuUI.m")


def panel_problems(texts, container_exists=True):
    """problems with the stream panels, given {panel file: source}."""
    problems = []
    for name in PANEL_FILES:
        if name not in texts:
            problems.append("%s is gone, so the panel ratchet is watching nothing" % name)
    if problems:
        return problems
    if not container_exists:
        problems.append("GlassOverlayContainer.m is gone, so every panel is on its own again")

    joined = "\n".join(texts.values())
    raw = joined.count("[[NSVisualEffectView alloc] init")
    if raw != len(PANELS_STILL_ON_VIBRANCY):
        problems.append("%d panels build their own vibrancy view, expected %d: the list "
                        "below has to say which ones and why"
                        % (raw, len(PANELS_STILL_ON_VIBRANCY)))

    for panel, (path, marker, forbidden) in sorted(GLASS_PANELS.items()):
        source = texts.get(path, "")
        if marker not in source:
            problems.append("the %s panel is listed as converted but does not ask the "
                            "container for its background" % panel)
        for needle in forbidden:
            if needle in joined:
                problems.append("the %s panel is on the container and still does `%s`"
                                % (panel, needle))

    diagnostics = texts.get("ViewControllers/StreamViewController+Diagnostics.m", "")
    for needle in RECONNECT_SCRIM:
        if needle not in diagnostics:
            problems.append("the reconnect scrim is no longer a plain dimming view, so the "
                            "picture behind it is being filtered by a material again")
    return problems


def panel_self_test(root):
    """Break the panel rules on the real files and make sure each break is caught."""
    texts = {}
    for name in PANEL_FILES:
        path = os.path.join(root, "Limelight", "macOS", name)
        texts[name] = open(path, encoding="utf-8").read()

    def edited(path, old, new):
        copy = dict(texts)
        if old not in copy[path]:
            raise SystemExit("the panel self-test lost its anchor in %s" % path)
        copy[path] = copy[path].replace(old, new, 1)
        return copy

    diagnostics = "ViewControllers/StreamViewController+Diagnostics.m"
    pill_file = "ViewControllers/StreamViewController+MenuUI.m"
    cases = [
        ("every panel on the container", texts, False),
        ("the container file deleted", None, True),
        ("a panel reverted to vibrancy",
         edited(diagnostics,
                "self.notificationContainer = [GlassOverlayContainer containerWithCornerRadius:10.0];",
                "self.notificationContainer = [[NSVisualEffectView alloc] initWithFrame:NSZeroRect];"),
         True),
        ("a panel on the container but setting a material",
         edited(diagnostics,
                "self.mouseModeContainer = [GlassOverlayContainer containerWithCornerRadius:10.0];",
                "self.mouseModeContainer = [GlassOverlayContainer containerWithCornerRadius:10.0];\n"
                "    self.mouseModeContainer.material = NSVisualEffectMaterialHUDWindow;"),
         True),
        ("the timeout panel masked by hand again",
         edited(diagnostics, "CGFloat centerX = width / 2.0;",
                "self.timeoutOverlayContainer.layer.mask = [CAShapeLayer layer];\n"
                "        CGFloat centerX = width / 2.0;"),
         True),
        ("the pill back on vibrancy",
         edited(pill_file,
                "GlassOverlayContainer *pill = [GlassOverlayContainer containerWithCornerRadius:containerHeight * 0.5];",
                "NSVisualEffectView *pill = [[NSVisualEffectView alloc] initWithFrame:container.bounds];"),
         True),
        ("the reconnect scrim given a material again",
         edited(diagnostics,
                "self.reconnectOverlayContainer = [[NSView alloc] initWithFrame:self.view.bounds];",
                "self.reconnectOverlayContainer = [[NSView alloc] initWithFrame:self.view.bounds];\n"
                "        self.reconnectOverlayContainer.material = NSVisualEffectMaterialHUDWindow;"),
         True),
    ]

    failures = 0
    for what, files, expect_problem in cases:
        problems = panel_problems(files if files is not None else {},
                                  container_exists=files is not None)
        if bool(problems) != expect_problem:
            failures += 1
            print("FAIL %-46s expected %s, got %s"
                  % (what, "a violation" if expect_problem else "clean", problems))
        else:
            print("ok   %-46s %s" % (what, "refused" if problems else "accepted"))
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        failures = self_test()
        failures += panel_self_test(args.repo)
        print("-- settings surface --")
        failures += settings_self_test(args.repo)
        print("-- host cards --")
        failures += host_card_self_test(args.repo)
        print("%d liquid glass audit self-test failures in all" % failures)
        return 1 if failures else 0

    root = os.path.join(args.repo, GLASS_DIR)
    if not os.path.isdir(root):
        print("error: %s is missing" % GLASS_DIR)
        return 1
    files = {}
    for name in sorted(os.listdir(root)):
        if name.endswith(".swift"):
            files[name] = open(os.path.join(root, name), encoding="utf-8").read()
    problems = check(files)
    project_path = os.path.join(args.repo, "Moonlight.xcodeproj", "project.pbxproj")
    project_text = open(project_path, encoding="utf-8").read() if os.path.isfile(project_path) else ""
    problems += project_problems(project_text, files.get("LiquidGlassTabBar.swift", ""))
    settings_texts = {}
    for name in SETTINGS_FILES:
        path = os.path.join(args.repo, "Limelight", "macOS", name)
        if os.path.isfile(path):
            settings_texts[name] = open(path, encoding="utf-8").read()
    problems += settings_surface_problems(settings_texts)
    host_texts = {}
    for name in HOST_WATCHED_FILES:
        path = os.path.join(args.repo, "Limelight", "macOS", name)
        if os.path.isfile(path):
            host_texts[name] = open(path, encoding="utf-8").read()
    problems += host_card_problems(host_texts)
    texts = {}
    for name in PANEL_FILES:
        path = os.path.join(args.repo, "Limelight", "macOS", name)
        if os.path.isfile(path):
            texts[name] = open(path, encoding="utf-8").read()
    problems += panel_problems(texts,
                               os.path.isfile(os.path.join(args.repo, "Limelight", "macOS",
                                                           "Views", "GlassOverlayContainer.m")))
    for problem in problems:
        print("violation: %s" % problem)
    print("%d liquid glass violations across %d files, %d panels, %d settings surfaces "
          "and the host cards (%d files) checked"
          % (len(problems), len(files) + len(PANEL_FILES) + len(SETTINGS_FILES) + len(HOST_WATCHED_FILES),
             len(GLASS_PANELS), len(SETTINGS_SURFACES), len(SETTINGS_FILES)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
