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


def check(files):
    """files maps basename to raw source. Returns human readable violations."""
    problems = []
    combined = "\n".join(strip_comments(t) for t in files.values())

    if ".glassEffect(" not in combined:
        problems.append("no native .glassEffect anywhere in the glass surface")
    if "GlassEffectContainer(" not in combined:
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
    print("%d liquid glass violations across %d files, %d panels checked"
          % (len(problems), len(files) + len(PANEL_FILES), len(GLASS_PANELS)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
